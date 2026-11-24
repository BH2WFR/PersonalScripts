"""Send screen keyboard input to the foreground application through Win32."""

import ctypes as C
from ctypes import wintypes as W
from functools import cache

from utils import Keyboard, ScanCodePrefix
from utils.windows_input import EXTENDED, KEYUP, SCANCODE, InputPacket, WindowsInput, keyboard_packet
from .layout import NUMPAD_NAVIGATION
from .state import KeyRepeat, LeftKeyMode

ALIASES = {
    "CapsLock": "caps_lock", "NumLock": "num_lock", "ScrollLock": "scroll_lock",
    "PgUp": "page_up", "PgDn": "page_down", "AppsKey": "menu", "vkE2sc056": "non_us_backslash",
    "LControl": "left_ctrl", "RControl": "right_ctrl", "NumpadEnter": "kp_enter",
    "NumpadDiv": "kp/", "NumpadMult": "kp*", "NumpadAdd": "kp+", "NumpadSub": "kp-",
    "NumpadDot": "kp.", **{f"Numpad{n}": f"kp{n}" for n in range(10)},
}
# With NumLock off Windows translates the same physical keypad positions to navigation keys.
ALIASES.update({nav: ALIASES[key] for key, (nav, _) in NUMPAD_NAVIGATION.items()})
LOCK_CODES = {"CapsLock": 0x14, "NumLock": 0x90, "ScrollLock": 0x91}
SPI_GETKEYBOARDSPEED = 0x000A
SPI_GETKEYBOARDDELAY = 0x0016
SPI_GETFILTERKEYS = 0x0032
FKF_FILTERKEYSON = 0x0001


class _FilterKeys(C.Structure):
    _fields_ = [("size", W.UINT), ("flags", W.DWORD), ("wait", W.DWORD),
                ("delay", W.DWORD), ("interval", W.DWORD), ("bounce", W.DWORD)]


@cache
def key_fields(name: str) -> tuple[int, int, int]:
    """Resolve an onscreen position without conflating keypad and navigation scans."""
    if name == "Pause":
        return 0x45, 0, 0x13
    if name == "F24":
        return 0x76, 0, 0x87  # VK_F24, including its physical scan position.
    code = Keyboard.windows_scan_code(ALIASES.get(name, name))
    if code is None:
        raise ValueError(f"Unknown screen key {name!r}")
    return code.code, SCANCODE | (EXTENDED if code.prefix == ScanCodePrefix.E0 else 0), 0


def packet(name: str, down: bool) -> InputPacket:
    scan, flags, vk = key_fields(name)
    return keyboard_packet(scan, flags if down else flags | KEYUP, vk)


class WindowsOutput(WindowsInput):
    mac = False

    def __init__(self) -> None:
        super().__init__()
        self.api.GetForegroundWindow.restype = W.HWND
        self.api.GetKeyState.argtypes = self.api.GetAsyncKeyState.argtypes = [C.c_int]
        self.api.GetKeyState.restype = self.api.GetAsyncKeyState.restype = C.c_short
        self.api.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.api.GetKeyboardLayout.argtypes = [W.DWORD]
        self.api.GetKeyboardLayout.restype = W.HANDLE
        self.api.SystemParametersInfoW.argtypes = [W.UINT, W.UINT, C.c_void_p, W.UINT]
        self.api.SystemParametersInfoW.restype = W.BOOL
        self.mode = LeftKeyMode.NATIVE
        self.owned: list[str] = []
        self.chord: list[str] = []

    def target(self) -> int:
        return self.api.GetForegroundWindow() or 0

    def locks(self) -> dict[str, bool]:
        return {name: bool(self.api.GetKeyState(vk) & 1) for name, vk in LOCK_CODES.items()}

    def hold(self, name: str, down: bool) -> None:
        if self.mode is LeftKeyMode.NATIVE:
            return
        key = self.mode.value if name == "Layer" else name
        if down:
            vk = Keyboard.windows_virtual_key(ALIASES.get(key, key))
            if key in self.owned or (vk is not None and self.api.GetAsyncKeyState(vk) < 0):
                return
            self.send_packets([packet(key, True)])
            self.owned.append(key)
        elif key in self.owned:
            self.send_packets([packet(key, False)])
            self.owned.remove(key)

    def repeat_timing(self) -> tuple[float, float] | None:
        """Return the configured repeat delay and interval in seconds."""
        query = self.api.SystemParametersInfoW
        filters = _FilterKeys(size=C.sizeof(_FilterKeys))
        if not query(SPI_GETFILTERKEYS, filters.size, C.byref(filters), 0):
            raise C.WinError(C.get_last_error())
        if filters.flags & FKF_FILTERKEYSON:
            return (filters.delay / 1000, filters.interval / 1000) if filters.interval else None
        delay, speed = W.UINT(), W.DWORD()
        if not (query(SPI_GETKEYBOARDDELAY, 0, C.byref(delay), 0)
                and query(SPI_GETKEYBOARDSPEED, 0, C.byref(speed), 0)):
            raise C.WinError(C.get_last_error())
        # Win32 specifies a speed range from roughly 2.5 to 30 repeats per second.
        return (delay.value + 1) * .25, 1 / (2.5 + (30 - 2.5) * speed.value / 31)

    def key_down(self, name: str, modifiers: list[str]) -> KeyRepeat | None:
        """Hold the scan code and any one-shot modifiers until pointer release."""
        if name in self.owned:
            return None
        press = []
        if self.mode is LeftKeyMode.NATIVE:
            for modifier in modifiers:
                vk = Keyboard.windows_virtual_key(ALIASES.get(modifier, modifier))
                if vk is not None and self.api.GetAsyncKeyState(vk) >= 0:
                    press.append(modifier)
        press.append(name)
        self.send_packets([packet(key, True) for key in press])
        self.chord = press
        if name in LOCK_CODES:
            return None
        timing = self.repeat_timing()
        if timing is None:
            return None
        delay, interval = timing
        return KeyRepeat(delay, interval, lambda: self.send_packets([packet(name, True)]))

    def key_up(self) -> None:
        if not self.chord:
            return
        modifiers = self.chord[:-1]
        packets = [packet(self.chord[-1], False)]
        if set(modifiers).intersection({"LWin", "RWin", "LAlt", "RAlt"}):
            packets.extend(keyboard_packet(0, flag, 0xE8) for flag in (0, KEYUP))
        packets.extend(packet(key, False) for key in reversed(modifiers))
        self.send_packets(packets)
        self.chord.clear()

    def language(self) -> None:
        if self.mode is not LeftKeyMode.NATIVE:
            self.key_down(self.mode.value, [])
            self.key_up()
            return
        thread = self.api.GetWindowThreadProcessId(self.target(), None)
        lang = self.api.GetKeyboardLayout(thread) & 0x3FF
        if lang == 4:
            self.key_down("Space", ["LControl"])
            self.key_up()
        elif lang == 0x11:
            self.key_down("`", ["LAlt"])
            self.key_up()
        elif lang == 0x12:
            self.send_packets([keyboard_packet(0, flags, 0x15) for flags in (0, KEYUP)])

    def reset(self) -> None:
        errors = []
        try:
            self.key_up()
        except RuntimeError as exc:
            errors.append(str(exc))
        for key in reversed(self.owned.copy()):
            try:
                self.send_packets([packet(key, False)])
                self.owned.remove(key)
            except RuntimeError as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("\n".join(errors))
