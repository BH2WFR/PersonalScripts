"""Send screen keyboard input to the foreground application through Win32."""

import ctypes as C
from ctypes import wintypes as W
from functools import cache

from utils import Keyboard, ScanCodePrefix
from utils.windows_input import EXTENDED, KEYUP, SCANCODE, InputPacket, WindowsInput, keyboard_packet
from .layout import NUMPAD_NAVIGATION
from .state import LeftKeyMode

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
        self.mode = LeftKeyMode.NATIVE
        self.owned: list[str] = []

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

    def key(self, name: str, modifiers: list[str]) -> None:
        if self.mode is not LeftKeyMode.NATIVE:
            if name not in self.owned:
                self.send_packets([packet(name, True), packet(name, False)])
            return
        press = []
        for modifier in modifiers:
            vk = Keyboard.windows_virtual_key(ALIASES.get(modifier, modifier))
            if vk is not None and self.api.GetAsyncKeyState(vk) >= 0:
                press.append(modifier)
        packets = [packet(key, True) for key in press]
        packets.extend((packet(name, True), packet(name, False)))
        if set(press).intersection({"LWin", "RWin", "LAlt", "RAlt"}):
            packets.extend(keyboard_packet(0, flag, 0xE8) for flag in (0, KEYUP))
        packets.extend(packet(key, False) for key in reversed(press))
        self.send_packets(packets)

    def language(self) -> None:
        if self.mode is not LeftKeyMode.NATIVE:
            self.key(self.mode.value, [])
            return
        thread = self.api.GetWindowThreadProcessId(self.target(), None)
        lang = self.api.GetKeyboardLayout(thread) & 0x3FF
        if lang == 4:
            self.key("Space", ["LControl"])
        elif lang == 0x11:
            self.key("`", ["LAlt"])
        elif lang == 0x12:
            self.send_packets([keyboard_packet(0, flags, 0x15) for flags in (0, KEYUP)])

    def reset(self) -> None:
        errors = []
        for key in reversed(self.owned.copy()):
            try:
                self.send_packets([packet(key, False)])
                self.owned.remove(key)
            except RuntimeError as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("\n".join(errors))
