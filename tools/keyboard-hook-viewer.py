#!/usr/bin/env python3
# pyright: reportMissingImports=false, reportMissingModuleSource=false
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
# pyright: reportUnreachable=false
"""Global keyboard and mouse hook monitor.

Monitors keyboard and mouse events globally (press/release/click/scroll) and
prints them to the console. All events are passed through transparently.

Platforms:
  macOS:   Native CGEvent tap plus IOHID keyboard source tracking.
  Windows: Low-level hooks via ctypes (SetWindowsHookEx).
  Linux:   X11 via python-xlib/XRecord. Wayland reserved for future.
"""

import os
import sys
import json
import time
import ctypes
import ctypes.wintypes
import dataclasses
import subprocess
import threading
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402



"""
--------------------



"""



# ============ lazy OS detection ============
# Evaluated once at import time — avoid repeated sys.platform string compares.
_OS: str = sys.platform


# ============ help ============
if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}KEYBOARD & MOUSE HOOK MONITOR{CRst}
================================

Usage:
  python {script_name}                start monitoring keyboard & mouse
  python {script_name} --help         show this help

{FLYellow}Platform notes:{CRst}
  macOS:   Requires Accessibility and Input Monitoring permissions.
           Keyboard events include the physical HID device serial number when
           the device exposes one; otherwise its IORegistry entry ID is shown.
  Windows: Low-level hooks via SetWindowsHookEx. No dependencies.
  Linux:   X11 via python-xlib/XRecord.
           Wayland is not yet supported (reserved for future).

{FLYellow}Dependencies:{CRst}
  macOS:   pyobjc-framework-Quartz  (pip install pyobjc-framework-Quartz)
  Windows: none (stdlib ctypes)
  Linux:   python-xlib              (pip install python-xlib)
""")
    sys.exit(0)


# ── External API ──────────────────────────────────────────────────────
# ```
#   The filename contains hyphens, so load it by path with ``importlib`` when
#   using these APIs from another Python program.
#
#   # ── monitoring (keyboard / mouse hooks) ──
#   setup(
#       on_key=lambda e: print(f"{'↓' if e.pressed else '↑'} {e.name}"),
#       hotkeys=[
#           Hotkey("caps+a",      lambda: print(">>> Caps+A!")),
#           Hotkey("caps+shift+a",lambda: print(">>> Caps+Shift+A!")),
#       ],
#       blocking=True,
#   )
#
#   # ── sending input ──
#   tap("a")                        # press + release a key
#   press("shift"); release("shift")  # hold / release a key
#   hotkey("ctrl+shift+esc")        # send a modifier combo
#   send([                          # send a sequence
#       ("ctrl", "down"), "a", 0.05, ("ctrl", "up"),
#   ])
#   move(500, 300)                  # move mouse to (500, 300)
#   click("left")                   # click left button at current position
#   scroll(dy=3)                    # scroll vertically
#   toggle_modifier("caps_lock")    # flip caps_lock / num_lock state
#
#   # ── foreground window ──
#   wi = get_foreground_window()
#   print(wi.pid, wi.process_name, wi.title)
# ```
#
# Normalized key names (all platforms):  "shift" "ctrl" "alt" "super"
# "caps_lock" "enter" "esc" "tab" "space" "backspace" "delete" "insert"
# "left" "right" "up" "down" "home" "end" "page_up" "page_down"
# "F1"–"F24"  "a"–"z" "0"–"9"  "media_play_pause" "media_volume_up" …
# Mouse buttons: "left" "right" "middle" "back" "forward"
# ──────────────────────────────────────────────────────────────────────


# ============ event types ============

@dataclasses.dataclass
class KeyEvent:
    """Normalized key event. ``name`` uses common names across all platforms."""
    name: str
    pressed: bool
    raw_name: str = ""
    raw_vk: int = 0
    device_name: str = ""
    device_serial: str = ""
    device_id: str = ""


@dataclasses.dataclass
class MouseEvent:
    """Normalized mouse event."""
    x: int = 0
    y: int = 0
    button: str = ""
    pressed: bool = False
    scroll_dx: int = 0
    scroll_dy: int = 0
    is_scroll: bool = False


@dataclasses.dataclass
class WindowInfo:
    """Foreground window metadata."""
    pid: int = 0
    process_name: str = ""     # e.g. "Safari", "Code"
    title: str = ""            # window title
    window_class: str = ""     # OS window class name
    bundle_id: str = ""        # macOS bundle ID (empty on other platforms)


# ============ key wrapper ============

class Key:
    """Represents a key that can be pressed, released, or tapped.

    ``name`` is normalised so ``"caps"``, ``"Caps_Lock"``, and ``"caps_lock"``
    are all equivalent.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = _normalize(name)

    @property
    def name(self) -> str:
        return self._name

    def press(self) -> None:
        """Press (hold down) this key."""
        _controller().press(self._name)

    def release(self) -> None:
        """Release this key."""
        _controller().release(self._name)

    def tap(self) -> None:
        """Press and immediately release this key."""
        self.press()
        self.release()

    def __repr__(self) -> str:
        return f"Key({self._name!r})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Key):
            return self._name == other._name
        if isinstance(other, str):
            return self._name == _normalize(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._name)


# ============ key name normalization ============

# X11 keysym names → common names.  macOS / Windows names are already
# lowercase snake_case and pass through ``_normalize`` unchanged.
_X11_NORM: dict[str, str] = {
    "Shift_L": "shift",       "Shift_R": "shift",
    "Control_L": "ctrl",      "Control_R": "ctrl",
    "Alt_L": "alt",           "Alt_R": "alt",
    "Meta_L": "super",        "Meta_R": "super",
    "Super_L": "super",       "Super_R": "super",
    "Caps_Lock": "caps_lock", "Num_Lock": "num_lock",
    "Scroll_Lock": "scroll_lock",
    "Return": "enter",        "Escape": "esc",
    "BackSpace": "backspace", "Delete": "delete",
    "Tab": "tab",             "ISO_Left_Tab": "tab",
    "space": "space",
    "Home": "home",           "End": "end",
    "Page_Up": "page_up",     "Page_Down": "page_down",
    "Left": "left",           "Right": "right",
    "Up": "up",               "Down": "down",
    "Insert": "insert",       "Print": "print_screen",
    "Pause": "pause",         "Menu": "menu",
    "Multi_key": "compose",
    "KP_Enter": "kp_enter",   "KP_Add": "kp+",
    "KP_Subtract": "kp-",     "KP_Multiply": "kp*",
    "KP_Divide": "kp/",       "KP_Decimal": "kp.",
    "KP_0": "kp0", "KP_1": "kp1", "KP_2": "kp2", "KP_3": "kp3", "KP_4": "kp4",
    "KP_5": "kp5", "KP_6": "kp6", "KP_7": "kp7", "KP_8": "kp8", "KP_9": "kp9",
    "XF86AudioPlay": "media_play_pause",
    "XF86AudioStop": "media_stop",
    "XF86AudioPrev": "media_previous",
    "XF86AudioNext": "media_next",
    "XF86AudioMute": "media_volume_mute",
    "XF86AudioLowerVolume": "media_volume_down",
    "XF86AudioRaiseVolume": "media_volume_up",
    "XF86MonBrightnessDown": "brightness_down",
    "XF86MonBrightnessUp": "brightness_up",
}


# User-facing shorthands → common names.  Applied before platform lookups.
_NAME_ALIASES: dict[str, str] = {
    "caps": "caps_lock", "scroll": "scroll_lock", "num": "num_lock",
    "pageup": "page_up", "pagedown": "page_down",
    "printscreen": "print_screen", "prtscn": "print_screen",
    "volup": "media_volume_up", "voldown": "media_volume_down",
    "volmute": "media_volume_mute",
    "volume_up": "media_volume_up", "volume_down": "media_volume_down",
    "volume_mute": "media_volume_mute",
    "media_prev": "media_previous",
    "next": "media_next", "prev": "media_previous",
    "play": "media_play_pause", "stop": "media_stop",
    "return": "enter",
    "lbutton": "left", "rbutton": "right", "mbutton": "middle",
    "lshift": "shift", "rshift": "shift",
    "lctrl": "ctrl", "rctrl": "ctrl",
    "lalt": "alt", "ralt": "alt",
    "lwin": "super", "rwin": "super",
}


def _normalize(name: str) -> str:
    """Normalize a platform-specific key name to the common form."""
    if not name:
        return "?"
    lower = name.lower()
    if lower in _NAME_ALIASES:
        return _NAME_ALIASES[lower]
    return _X11_NORM.get(name, lower)


# ============ hotkey ============

class Hotkey:
    """A key combination that triggers *callback* when all modifiers are held
    and the trigger key is pressed.

    *combo* is a ``+``-separated string, e.g. ``"caps+a"`` or ``"ctrl+shift+k"``.
    The last segment is the trigger; preceding segments are modifiers.
    Key names are :func:`_normalize`\\ d so ``"caps"``, ``"Caps_Lock"``, and
    ``"caps_lock"`` are all equivalent.

    Modifiers may include toggle keys (``caps_lock``, ``num_lock``,
    ``scroll_lock``) — these are treated as held while their toggle state is on.
    """

    __slots__ = ("_mods", "_trigger", "_callback")

    def __init__(self, combo: str, callback) -> None:
        parts = [_normalize(p) for p in combo.lower().replace(" ", "").split("+")]
        if len(parts) < 2:
            raise ValueError(
                f"Hotkey combo must have at least one modifier: {combo!r}"
            )
        self._mods: frozenset[str] = frozenset(parts[:-1])
        self._trigger: str = parts[-1]
        self._callback = callback

    def __repr__(self) -> str:
        return f"Hotkey({'+'.join(sorted(self._mods))}+{self._trigger})"


# ============ dispatch ============

# Keys whose physical press toggles a persistent on/off state.
_TOGGLE_NAMES: frozenset[str] = frozenset({"caps_lock", "num_lock", "scroll_lock"})

_on_key_cb: "Callable[[KeyEvent], None] | None" = None  # type: ignore[valid-type]
_on_mouse_cb: "Callable[[MouseEvent], None] | None" = None  # type: ignore[valid-type]
_hotkeys: list[Hotkey] = []
_held: set[str] = set()       # currently held momentary keys
_toggled: set[str] = set()    # toggle keys currently in "on" state

# foreground-window change tracking (for console output)
_last_win_key: tuple[int, str] = (-1, "")


def _check_win_change() -> None:
    """Print a banner when the foreground window changes.

    Called on every keyboard / mouse event.  Compares both PID and window
    title, so tab switches within the same app are also detected.
    """
    global _last_win_key
    try:
        wi = get_foreground_window()
    except Exception:
        return
    key = (wi.pid, wi.title)
    if key == _last_win_key:
        return
    _last_win_key = key
    label = wi.process_name or f"PID:{wi.pid}"
    title = wi.title[:72] + "…" if len(wi.title) > 72 else wi.title
    wnd_class = wi.window_class
    ts = f"{FGray}{Console.get_time_str()}{CRst}"
    cls_str = f"  {FGray}[{FLWhite}{wnd_class}{FGray}]{CRst}" if wnd_class else ""
    print(
        f"{ts} {FLYellow}─── {FLWhite}{CBold}{label}{CRst} "
        f"{FLYellow}({wi.pid}){CRst}{cls_str}  {FLCyan}{title}{CRst}"
    )


def _emit_key(
    name: str,
    pressed: bool,
    raw_vk: int = 0,
    device: "InputDevice | None" = None,
) -> None:
    """Called by every platform hook for key events.

    Normalises the name, updates held/toggled state, checks hotkeys,
    calls the user callback, and prints the default formatting.
    """
    _check_win_change()
    norm = _normalize(name)

    if norm in _TOGGLE_NAMES:
        # Toggle keys: each physical press flips the logical state.
        # Ignore the corresponding release — only the press matters.
        if not pressed:
            return
        if norm in _toggled:
            _toggled.discard(norm)
        else:
            _toggled.add(norm)
        _print_key(norm, True, device)
        _print_key(norm, False, device)
        if _on_key_cb:
            event_device = device or InputDevice.empty()
            _on_key_cb(KeyEvent(
                norm, True, name, raw_vk,
                event_device.name, event_device.serial, event_device.path,
            ))
            _on_key_cb(KeyEvent(
                norm, False, name, raw_vk,
                event_device.name, event_device.serial, event_device.path,
            ))
        return

    if pressed:
        if norm in _held:
            return  # skip auto-repeat
        _held.add(norm)
        # Hotkey matching: trigger must match, all modifiers must be held/toggled
        for hk in _hotkeys:
            if hk._trigger == norm and hk._mods.issubset(_held | _toggled):
                hk._callback()
    else:
        _held.discard(norm)

    _print_key(norm, pressed, device)
    if _on_key_cb:
        event_device = device or InputDevice.empty()
        _on_key_cb(KeyEvent(
            norm, pressed, name, raw_vk,
            event_device.name, event_device.serial, event_device.path,
        ))


def _emit_mouse(x: int, y: int, btn: str, pressed: bool) -> None:
    """Called by every platform hook for mouse button events."""
    _check_win_change()
    _print_mouse(x, y, btn, pressed)
    if _on_mouse_cb:
        _on_mouse_cb(MouseEvent(x=x, y=y, button=btn, pressed=pressed))


def _emit_scroll(dx: int, dy: int) -> None:
    """Called by every platform hook for scroll events."""
    _check_win_change()
    _print_scroll(dx, dy)
    if _on_mouse_cb:
        _on_mouse_cb(MouseEvent(scroll_dx=dx, scroll_dy=dy, is_scroll=True))


# ============ public setup ============

def _create_hook():
    """Return the right platform hook instance (with ``.start()``/``.stop()``)."""
    if _OS == "darwin":
        hook = _create_macos_hook()
        if hook is None:
            raise ImportError(
                "pyobjc-framework-Quartz is required on macOS.\n"
                "Install with: pip install pyobjc-framework-Quartz"
            )
        return hook
    elif _OS == "win32":
        hook = _create_win_hook()
        if hook is None:
            raise OSError("Failed to create Windows hooks.")
        return hook
    elif _OS.startswith("linux"):
        return _create_x11_hook()
    else:
        raise OSError(f"Unsupported platform: {_OS}")


def setup(*, on_key=None, on_mouse=None, hotkeys=None, blocking=True):
    """Configure callbacks and start input monitoring.

    Args:
        on_key: ``callable(KeyEvent)`` — called for every key press/release.
        on_mouse: ``callable(MouseEvent)`` — called for every mouse event.
        hotkeys: ``list[Hotkey]`` — hotkey combos to watch.
        blocking: If True (default), blocks until Ctrl+C.

    Returns:
        ``(hook, thread)`` — the platform hook instance and its thread.
    """
    global _on_key_cb, _on_mouse_cb, _hotkeys
    _on_key_cb = on_key
    _on_mouse_cb = on_mouse
    _hotkeys = list(hotkeys or [])

    hook = _create_hook()
    thread = threading.Thread(
        target=hook.start, daemon=True, name="input-hook",
    )
    thread.start()

    if not hook._ready.wait(timeout=5):
        print("Waiting for hook permission…")

    if blocking:
        try:
            thread.join()
        except KeyboardInterrupt:
            pass
        finally:
            hook.stop()

    return hook, thread


# ============ device enumeration ============
@dataclasses.dataclass
class InputDevice:
    idx: int
    name: str
    kind: str
    vendor_id: str
    product_id: str
    serial: str
    path: str

    @classmethod
    def empty(cls) -> "InputDevice":
        return cls(0, "", "", "", "", "", "")


def _enumerate_devices_macos() -> list[InputDevice]:
    try:
        r = subprocess.run(
            ["hidutil", "list", "--ndjson"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        raw_devices = [
            json.loads(line) for line in r.stdout.splitlines() if line.strip()
        ]
    except Exception:
        return []

    result: list[InputDevice] = []
    for raw in raw_devices:
        # A service and its backing device are normally both present.  The
        # device record is the one IOHIDElementGetDevice identifies later.
        if raw.get("type") != "device":
            continue
        usage_page = int(raw.get("PrimaryUsagePage", 0))
        usage = int(raw.get("PrimaryUsage", 0))
        if usage_page == 0x01 and usage == 0x06:
            kind = "KBD"
        elif usage_page == 0x01 and usage == 0x02:
            kind = "MOU"
        else:
            continue
        result.append(InputDevice(
            idx=0,
            name=raw.get("Product", "") or raw.get("Transport", "") or "Unknown",
            kind=kind,
            vendor_id=str(raw.get("VendorID", "")),
            product_id=str(raw.get("ProductID", "")),
            serial=str(raw.get("SerialNumber", "")),
            path=str(raw.get("IORegistryEntryID", "")),
        ))
    return result


def _enumerate_devices_windows() -> list[InputDevice]:
    result: list[InputDevice] = []

    def _run_ps(query: str) -> list[dict[str, Any]]:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", query],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return []
            data = json.loads(r.stdout)
            return [data] if isinstance(data, dict) else data
        except Exception:
            return []

    for kb in _run_ps(
        "Get-CimInstance -ClassName Win32_Keyboard | "
        "Select-Object Name, PNPDeviceID | ConvertTo-Json"
    ):
        result.append(InputDevice(
            idx=0,
            name=str(kb.get("Name", "Unknown Keyboard")),
            kind="KBD", vendor_id="", product_id="", serial="",
            path=str(kb.get("PNPDeviceID", "")),
        ))
    for mou in _run_ps(
        "Get-CimInstance -ClassName Win32_PointingDevice | "
        "Select-Object Name, PNPDeviceID | ConvertTo-Json"
    ):
        result.append(InputDevice(
            idx=0,
            name=str(mou.get("Name", "Unknown Mouse")),
            kind="MOU", vendor_id="", product_id="", serial="",
            path=str(mou.get("PNPDeviceID", "")),
        ))
    return result


def enumerate_devices() -> list[InputDevice]:
    if _OS == "darwin":
        devices = _enumerate_devices_macos()
    elif _OS == "win32":
        devices = _enumerate_devices_windows()
    else:
        devices = []
    for i, d in enumerate(devices):
        d.idx = i
    return devices


# ============ shared state & formatting ============
_state: dict[str, list[InputDevice]] = {"kbd_devs": [], "mou_devs": []}
_show_event_device = True


def _device_idx(kind: str) -> str:
    devs = _state["kbd_devs"] if kind == "KBD" else _state["mou_devs"]
    n = len(devs)
    if n == 1:
        return f" {devs[0].idx}"
    if n > 1:
        return " ?"
    return ""


def _format_event(kind: str, arrow: str, detail: str, extra: str = "") -> str:
    ts = f"{FGray}{Console.get_time_str()}{CRst}"
    kind_color = FLCyan if kind == "KBD" else FLMagenta
    arrow_color = FLGreen if arrow == "↓" else FLYellow
    kind_label = f"{kind_color}[{kind}{_device_idx(kind)}]{CRst}"
    a = f"{arrow_color}{arrow}{CRst}"
    d = f"{FLWhite}{detail}{CRst}"
    ext = f" {FGray}{extra}{CRst}" if extra else ""
    return f"{ts} {kind_label} {a} {d}{ext}"


def _print_mouse(x: int, y: int, btn_name: str, pressed: bool):
    arrow = "↓" if pressed else "↑"
    print(_format_event("MOU", arrow, btn_name, f"({x}, {y})"))


def _print_scroll(dx: int, dy: int):
    direction = "↑" if dy > 0 else "↓"
    print(_format_event("MOU", direction, f"scroll ({dx}, {dy})"))


def _print_key(
    key_name: str,
    pressed: bool,
    device: "InputDevice | None" = None,
):
    arrow = "↓" if pressed else "↑"
    source = ""
    if device is not None and _show_event_device:
        identity = f"S/N:{device.serial}" if device.serial else f"ID:{device.path}"
        source = f"{device.name}  {identity}" if device.name else identity
    print(_format_event("KBD", arrow, key_name, source))


# ====================================================================
#  macOS — native CGEvent tap (keyboard + mouse unified)
# ====================================================================

# Virtual key code → name mapping.
_VK_MAP: dict[int, str] = {
    # Modifiers
    0x38: "shift",      0x3C: "shift_r",
    0x3B: "ctrl",       0x3E: "ctrl_r",
    0x3A: "alt",        0x3D: "alt_r",
    0x37: "cmd",        0x36: "cmd_r",
    0x39: "caps_lock",
    # Navigation
    0x7B: "left",       0x7C: "right",
    0x7D: "down",       0x7E: "up",
    0x73: "home",       0x77: "end",
    0x74: "page_up",    0x79: "page_down",
    # Editing
    0x33: "backspace",  0x75: "delete",
    0x24: "enter",      0x35: "esc",
    0x30: "tab",        0x31: "space",
    # Function keys
    0x7A: "F1",  0x78: "F2",  0x63: "F3",  0x76: "F4",
    0x60: "F5",  0x61: "F6",  0x62: "F7",  0x64: "F8",
    0x65: "F9",  0x6D: "F10", 0x67: "F11", 0x6F: "F12",
    0x69: "F13", 0x6B: "F14", 0x71: "F15", 0x6A: "F16",
    0x40: "F17", 0x4F: "F18", 0x50: "F19", 0x5A: "F20",
    # fn / globe
    63: "fn",           179: "fn/globe",
    # Keypad
    0x41: "kp.",        0x43: "kp*",        0x45: "kp+",
    0x47: "kp_clear",   0x4B: "kp/",        0x4C: "kp_enter",
    0x4E: "kp-",        0x51: "kp=",
    0x52: "kp0",        0x53: "kp1",        0x54: "kp2",
    0x55: "kp3",        0x56: "kp4",        0x57: "kp5",
    0x58: "kp6",        0x59: "kp7",        0x5B: "kp8",
    0x5C: "kp9",
    # Misc
    0x72: "help",       0x6E: "menu",
    0x4A: "fwd_del",
}

_NX_KEYTYPE_SOUND_UP, _NX_KEYTYPE_SOUND_DOWN = 0, 1
_NX_KEYTYPE_MUTE, _NX_KEYTYPE_EJECT = 7, 14
_NX_KEYTYPE_PLAY, _NX_KEYTYPE_NEXT, _NX_KEYTYPE_PREVIOUS = 16, 17, 18
_NX_KEYTYPE_REWIND, _NX_KEYTYPE_FAST = 19, 20

_MEDIA_KEY_MAP: dict[int, str] = {
    _NX_KEYTYPE_SOUND_UP: "media_volume_up",
    _NX_KEYTYPE_SOUND_DOWN: "media_volume_down",
    _NX_KEYTYPE_MUTE: "media_volume_mute",
    _NX_KEYTYPE_EJECT: "media_eject",
    _NX_KEYTYPE_PLAY: "media_play_pause",
    _NX_KEYTYPE_NEXT: "media_next",
    _NX_KEYTYPE_PREVIOUS: "media_previous",
    _NX_KEYTYPE_REWIND: "media_rewind",
    _NX_KEYTYPE_FAST: "media_fast_forward",
}

_MOD_FLAG_MAP: dict[int, int] = {
    0x38: 1 << 17, 0x3C: 1 << 17,
    0x3B: 1 << 18, 0x3E: 1 << 18,
    0x3A: 1 << 19, 0x3D: 1 << 19,
    0x37: 1 << 20, 0x36: 1 << 20,
}

_MOUSE_BTN_MAP: dict[int, str] = {
    0: "left", 1: "right", 2: "middle", 3: "back", 4: "forward",
}

# USB HID Usage Tables, Keyboard/Keypad page (0x07).  IOHID reports these
# before Quartz merges devices into the session-wide CGEvent stream.
_HID_KEYBOARD_USAGE_MAP: dict[int, str] = {
    **{usage: chr(ord("a") + usage - 0x04) for usage in range(0x04, 0x1E)},
    **{
        usage: str((usage - 0x1D) % 10)
        for usage in range(0x1E, 0x28)
    },
    0x28: "enter", 0x29: "esc", 0x2A: "backspace", 0x2B: "tab",
    0x2C: "space", 0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]",
    0x31: "\\", 0x32: "non_us_hash", 0x33: ";", 0x34: "'",
    0x35: "`", 0x36: ",", 0x37: ".", 0x38: "/",
    0x39: "caps_lock",
    **{usage: f"F{usage - 0x39}" for usage in range(0x3A, 0x46)},
    0x46: "print_screen", 0x47: "scroll_lock", 0x48: "pause",
    0x49: "insert", 0x4A: "home", 0x4B: "page_up", 0x4C: "delete",
    0x4D: "end", 0x4E: "page_down", 0x4F: "right", 0x50: "left",
    0x51: "down", 0x52: "up", 0x53: "num_lock", 0x54: "kp/",
    0x55: "kp*", 0x56: "kp-", 0x57: "kp+", 0x58: "kp_enter",
    **{usage: f"kp{usage - 0x58}" for usage in range(0x59, 0x62)},
    0x62: "kp0", 0x63: "kp.", 0x64: "non_us_backslash", 0x65: "menu",
    0x66: "power", 0x67: "kp=",
    **{usage: f"F{usage - 0x5B}" for usage in range(0x68, 0x74)},
    0xE0: "ctrl", 0xE1: "shift", 0xE2: "alt", 0xE3: "cmd",
    0xE4: "ctrl_r", 0xE5: "shift_r", 0xE6: "alt_r", 0xE7: "cmd_r",
}


class _MacHIDKeyboardMonitor:
    """Read physical keyboard values together with their IOHIDDevice source."""

    _CF_STRING_ENCODING_UTF8 = 0x08000100
    _CF_NUMBER_SINT64_TYPE = 4
    _IORETURN_EXCLUSIVE_ACCESS = -536870203

    def __init__(self, on_key: Callable[[str, bool, int, InputDevice], None]):
        self._on_key = on_key
        self._manager = None
        self._loop = None
        self._callback = None
        self._property_keys: dict[str, int] = {}
        self._device_cache: dict[int, InputDevice] = {}
        self._recent_physical: dict[tuple[int, bool], float] = {}
        self._iokit = None
        self._cf = None
        self.open_result = 0

    def _load(self) -> None:
        self._iokit = ctypes.CDLL(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        self._cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        I = self._iokit
        C = self._cf

        I.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDManagerCreate.restype = ctypes.c_void_p
        I.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        I.IOHIDManagerRegisterInputValueCallback.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerScheduleWithRunLoop.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerUnscheduleFromRunLoop.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDManagerOpen.restype = ctypes.c_int32
        I.IOHIDManagerClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDValueGetElement.argtypes = [ctypes.c_void_p]
        I.IOHIDValueGetElement.restype = ctypes.c_void_p
        I.IOHIDValueGetIntegerValue.argtypes = [ctypes.c_void_p]
        I.IOHIDValueGetIntegerValue.restype = ctypes.c_longlong
        I.IOHIDElementGetUsagePage.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetUsagePage.restype = ctypes.c_uint32
        I.IOHIDElementGetUsage.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetUsage.restype = ctypes.c_uint32
        I.IOHIDElementGetDevice.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetDevice.restype = ctypes.c_void_p
        I.IOHIDDeviceGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        I.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
        I.IOHIDDeviceGetService.argtypes = [ctypes.c_void_p]
        I.IOHIDDeviceGetService.restype = ctypes.c_uint32
        I.IORegistryEntryGetRegistryEntryID.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64),
        ]
        I.IORegistryEntryGetRegistryEntryID.restype = ctypes.c_int32

        C.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        C.CFStringCreateWithCString.restype = ctypes.c_void_p
        C.CFStringGetTypeID.restype = ctypes.c_ulong
        C.CFNumberGetTypeID.restype = ctypes.c_ulong
        C.CFBooleanGetTypeID.restype = ctypes.c_ulong
        C.CFGetTypeID.argtypes = [ctypes.c_void_p]
        C.CFGetTypeID.restype = ctypes.c_ulong
        C.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
        ]
        C.CFStringGetCString.restype = ctypes.c_bool
        C.CFNumberGetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ]
        C.CFNumberGetValue.restype = ctypes.c_bool
        C.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        C.CFBooleanGetValue.restype = ctypes.c_bool
        C.CFRelease.argtypes = [ctypes.c_void_p]
        C.CFRunLoopGetCurrent.argtypes = []
        C.CFRunLoopGetCurrent.restype = ctypes.c_void_p

    def _make_property_keys(self) -> None:
        for key in (
            "Product", "SerialNumber", "VendorID", "ProductID", "LocationID",
        ):
            ref = self._cf.CFStringCreateWithCString(
                None, key.encode("ascii"), self._CF_STRING_ENCODING_UTF8,
            )
            if ref:
                self._property_keys[key] = ref

    def _property(self, device: int, key: str) -> str:
        key_ref = self._property_keys.get(key)
        if not key_ref:
            return ""
        value = self._iokit.IOHIDDeviceGetProperty(device, key_ref)
        if not value:
            return ""
        type_id = self._cf.CFGetTypeID(value)
        if type_id == self._cf.CFStringGetTypeID():
            buf = ctypes.create_string_buffer(1024)
            if self._cf.CFStringGetCString(
                value, buf, len(buf), self._CF_STRING_ENCODING_UTF8,
            ):
                return buf.value.decode("utf-8", errors="replace")
        elif type_id == self._cf.CFNumberGetTypeID():
            number = ctypes.c_longlong()
            if self._cf.CFNumberGetValue(
                value, self._CF_NUMBER_SINT64_TYPE, ctypes.byref(number),
            ):
                return str(number.value)
        elif type_id == self._cf.CFBooleanGetTypeID():
            return "1" if self._cf.CFBooleanGetValue(value) else "0"
        return ""

    def _device(self, device_ref: int) -> InputDevice:
        cache_key = int(device_ref)
        cached = self._device_cache.get(cache_key)
        if cached is not None:
            return cached

        registry_id = ctypes.c_uint64()
        service = self._iokit.IOHIDDeviceGetService(device_ref)
        if service:
            self._iokit.IORegistryEntryGetRegistryEntryID(
                service, ctypes.byref(registry_id),
            )
        path = f"0x{registry_id.value:x}" if registry_id.value else "unknown"
        result = InputDevice(
            idx=0,
            name=self._property(device_ref, "Product") or "Unknown keyboard",
            kind="KBD",
            vendor_id=self._property(device_ref, "VendorID"),
            product_id=self._property(device_ref, "ProductID"),
            serial=self._property(device_ref, "SerialNumber"),
            path=path,
        )
        self._device_cache[cache_key] = result
        return result

    def start(self) -> bool:
        try:
            self._load()
            iokit = self._iokit
            cf = self._cf
            if iokit is None or cf is None:
                return False
            self._make_property_keys()
            self._manager = iokit.IOHIDManagerCreate(None, 0)
            if not self._manager:
                self.stop()
                return False

            callback_type = ctypes.CFUNCTYPE(
                None, ctypes.c_void_p, ctypes.c_int32,
                ctypes.c_void_p, ctypes.c_void_p,
            )

            def handle_value(_context, result, _sender, value):
                if result != 0 or not value:
                    return
                try:
                    element = self._iokit.IOHIDValueGetElement(value)
                    if not element or self._iokit.IOHIDElementGetUsagePage(element) != 0x07:
                        return
                    usage = self._iokit.IOHIDElementGetUsage(element)
                    # 0x00-0x03 are HID no-event/error codes.  Values beyond
                    # the Keyboard/Keypad page range are not physical keys.
                    if usage < 0x04 or usage > 0xE7:
                        return
                    name = _HID_KEYBOARD_USAGE_MAP.get(
                        usage, f"hid_usage(0x{usage:02x})",
                    )
                    device_ref = self._iokit.IOHIDElementGetDevice(element)
                    if not device_ref:
                        return
                    pressed = bool(self._iokit.IOHIDValueGetIntegerValue(value))
                    device = self._device(device_ref)
                    event_key = (usage, pressed)
                    now = time.monotonic()
                    is_virtual = "virtualhidkeyboard" in device.name.lower()
                    if is_virtual:
                        # Karabiner commonly re-emits an unchanged physical
                        # event through its virtual keyboard.  Hide that exact
                        # duplicate, while retaining genuinely remapped usages.
                        if now - self._recent_physical.get(event_key, 0.0) < 0.05:
                            return
                    else:
                        self._recent_physical[event_key] = now
                    self._on_key(name, pressed, usage, device)
                except Exception:
                    return

            self._callback = callback_type(handle_value)
            # Use the CoreFoundation C API on this worker thread.  PyObjC's
            # CFRunLoopRef wrapper cannot be passed directly to ctypes.
            self._loop = cf.CFRunLoopGetCurrent()
            mode = ctypes.c_void_p.in_dll(
                cf, "kCFRunLoopDefaultMode",
            ).value
            self._mode = mode
            iokit.IOHIDManagerSetDeviceMatching(self._manager, None)
            iokit.IOHIDManagerRegisterInputValueCallback(
                self._manager, self._callback, None,
            )
            iokit.IOHIDManagerScheduleWithRunLoop(
                self._manager, self._loop, self._mode,
            )
            self.open_result = iokit.IOHIDManagerOpen(self._manager, 0)
            if self.open_result not in (0, self._IORETURN_EXCLUSIVE_ACCESS):
                self.stop()
                return False
            return True
        except (AttributeError, OSError):
            self.stop()
            return False

    def stop(self) -> None:
        if self._manager and self._iokit:
            if self._loop and getattr(self, "_mode", None):
                self._iokit.IOHIDManagerUnscheduleFromRunLoop(
                    self._manager, self._loop, self._mode,
                )
            self._iokit.IOHIDManagerClose(self._manager, 0)
            if self._cf:
                self._cf.CFRelease(self._manager)
        if self._cf:
            for key_ref in self._property_keys.values():
                self._cf.CFRelease(key_ref)
        self._manager = None
        self._loop = None
        self._callback = None
        self._property_keys.clear()
        self._device_cache.clear()
        self._recent_physical.clear()


def _key_name_from_event(vk: int, chars: Optional[str]) -> str:
    if vk in _VK_MAP:
        return _VK_MAP[vk]
    if chars and len(chars) > 0 and chars.isprintable():
        return chars
    return f"key({vk})"


def _create_macos_hook():
    """Unified CGEvent tap.  Returns object with .start() / .stop()."""
    if _OS != "darwin":
        return None

    try:
        from Quartz import (
            CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent,
            CFRunLoopRemoveSource, CFRunLoopRunInMode, CFRunLoopStop,
            CGEventGetFlags, CGEventGetIntegerValueField, CGEventGetLocation,
            CGEventKeyboardGetUnicodeString, CGEventMaskBit,
            CGEventTapCreate, CGEventTapEnable,
            kCFRunLoopDefaultMode, kCFRunLoopRunTimedOut,
            kCGEventFlagsChanged, kCGEventKeyDown, kCGEventKeyUp,
            kCGEventLeftMouseDown, kCGEventLeftMouseDragged, kCGEventLeftMouseUp,
            kCGEventOtherMouseDown, kCGEventOtherMouseDragged, kCGEventOtherMouseUp,
            kCGEventRightMouseDown, kCGEventRightMouseDragged, kCGEventRightMouseUp,
            kCGEventScrollWheel,
            kCGEventTapOptionListenOnly, kCGHeadInsertEventTap,
            kCGKeyboardEventKeycode, kCGMouseEventButtonNumber,
            kCGScrollWheelEventDeltaAxis1, kCGScrollWheelEventDeltaAxis2,
            kCGSessionEventTap,
            NSEvent, NSSystemDefined,
        )
    except ImportError:
        return None

    kSystemDefinedEventMediaKeysSubtype = 8

    _MASK = (
        CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(NSSystemDefined)
        | CGEventMaskBit(kCGEventLeftMouseDown) | CGEventMaskBit(kCGEventLeftMouseUp)
        | CGEventMaskBit(kCGEventLeftMouseDragged)
        | CGEventMaskBit(kCGEventRightMouseDown) | CGEventMaskBit(kCGEventRightMouseUp)
        | CGEventMaskBit(kCGEventRightMouseDragged)
        | CGEventMaskBit(kCGEventOtherMouseDown) | CGEventMaskBit(kCGEventOtherMouseUp)
        | CGEventMaskBit(kCGEventOtherMouseDragged)
        | CGEventMaskBit(kCGEventScrollWheel)
    )

    _MOUSE_PRESS = {
        kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventOtherMouseDown,
    }
    _MOUSE_RELEASE = {
        kCGEventLeftMouseUp, kCGEventRightMouseUp, kCGEventOtherMouseUp,
    }

    class MacHook:
        def __init__(self):
            self._tap = None
            self._loop_source = None
            self._loop = None
            self._hid_monitor = _MacHIDKeyboardMonitor(self._handle_hid_key_event)
            self._hid_keyboard_seen = False
            self._ready = threading.Event()
            self.running = False

        def _handle_hid_key_event(self, name, pressed, usage, device):
            self._hid_keyboard_seen = True
            _emit_key(name, pressed, usage, device)

        def _handle_key_event(self, event_type, event):
            if self._hid_keyboard_seen:
                return
            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            length, chars = CGEventKeyboardGetUnicodeString(event, 100, None, None)
            chars = chars if length > 0 else None
            if event_type == kCGEventKeyDown:
                _emit_key(_key_name_from_event(vk, chars), True, vk)
            elif event_type == kCGEventKeyUp:
                _emit_key(_key_name_from_event(vk, chars), False, vk)

        def _handle_flags_changed(self, event):
            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            # Fn/Globe is not part of the standard HID keyboard usage page.
            # Other modifiers arrive through IOHID with their physical source.
            if self._hid_keyboard_seen and vk not in (63, 179):
                return
            flags = CGEventGetFlags(event)
            if vk == 0x39:
                name = _VK_MAP.get(vk, f"key({vk})")
                _emit_key(name, True, vk)
                return
            flag = _MOD_FLAG_MAP.get(vk)
            if flag is not None:
                name = _VK_MAP.get(vk, f"key({vk})")
                _emit_key(name, bool(flags & flag), vk)

        def _handle_system_defined(self, event):
            sys_event = NSEvent.eventWithCGEvent_(event)
            if sys_event.subtype() != kSystemDefinedEventMediaKeysSubtype:
                return
            data1 = sys_event.data1()
            media_vk = (data1 & 0xFFFF0000) >> 16
            is_press = ((data1 & 0x0000FFFF) >> 8) == 0x0A
            name = _MEDIA_KEY_MAP.get(media_vk)
            if name is not None:
                _emit_key(name, is_press, media_vk)

        def _handle_mouse_event(self, event_type, event):
            btn = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
            (x, y) = CGEventGetLocation(event)
            x, y = int(x), int(y)
            if event_type == kCGEventScrollWheel:
                dx = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis2)
                dy = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
                _emit_scroll(dx, dy)
            elif event_type in _MOUSE_PRESS:
                _emit_mouse(x, y, _MOUSE_BTN_MAP.get(btn, f"button{btn}"), True)
            elif event_type in _MOUSE_RELEASE:
                _emit_mouse(x, y, _MOUSE_BTN_MAP.get(btn, f"button{btn}"), False)

        def _handle(self, _proxy, event_type, event, _refcon):
            try:
                if event_type == kCGEventKeyDown:
                    self._handle_key_event(event_type, event)
                elif event_type == kCGEventKeyUp:
                    self._handle_key_event(event_type, event)
                elif event_type == kCGEventFlagsChanged:
                    self._handle_flags_changed(event)
                elif event_type == NSSystemDefined:
                    self._handle_system_defined(event)
                elif event_type in (
                    kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                    kCGEventLeftMouseDragged,
                    kCGEventRightMouseDown, kCGEventRightMouseUp,
                    kCGEventRightMouseDragged,
                    kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                    kCGEventOtherMouseDragged,
                    kCGEventScrollWheel,
                ):
                    self._handle_mouse_event(event_type, event)
            except Exception:
                pass

        def start(self):
            self._tap = CGEventTapCreate(
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly, _MASK, self._handle, None,
            )
            if self._tap is None:
                self._ready.set()
                raise OSError(
                    "Failed to create event tap — grant Input Monitoring permission"
                )
            self._loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self._loop, self._loop_source, kCFRunLoopDefaultMode)
            if self._hid_monitor.start():
                if self._hid_monitor.open_result:
                    print(
                        f"{FLYellow}  HID source tracking is partial: one or more "
                        f"devices are held exclusively (for example by Karabiner).{CRst}"
                    )
            else:
                print(
                    f"{FLYellow}  HID source tracking unavailable; keyboard events "
                    f"will fall back to CGEvent without device identity.{CRst}"
                )
            CGEventTapEnable(self._tap, True)
            self._ready.set()
            self.running = True
            while self.running:
                result = CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1, False)
                if result != kCFRunLoopRunTimedOut:
                    break

        def stop(self):
            self.running = False
            self._hid_monitor.stop()
            if self._tap is not None:
                CGEventTapEnable(self._tap, False)
                CFRunLoopRemoveSource(
                    self._loop, self._loop_source, kCFRunLoopDefaultMode,
                )
                CFRunLoopStop(self._loop)
                self._tap = None
                self._loop_source = None
                self._loop = None

    return MacHook()


# --- macOS input controller ------------------------------------------------

# US QWERTY character → macOS virtual keycode (for sending events)
_CHAR_TO_VK_US: dict[str, int] = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B,
    "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D,
    "]": 0x1E, "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23,
    "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A,
    ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F,
    "`": 0x32,
}

# Reverse _VK_MAP → name for sending special keys
_NAME_TO_VK_MAC: dict[str, int] = {}
for _vk, _nm in _VK_MAP.items():
    _NAME_TO_VK_MAC[_nm] = _vk


class _MacController:
    """Send keyboard / mouse events via CGEvent API."""

    _Q = None  # Quartz module, lazy-loaded

    @classmethod
    def _quartz(cls):
        if cls._Q is None:
            from Quartz import (
                CGEventCreateKeyboardEvent, CGEventCreateMouseEvent,
                CGEventCreateScrollWheelEvent,
                CGEventKeyboardSetUnicodeString, CGEventPost, CGEventSetFlags,
                CGEventGetLocation,
                kCGHIDEventTap, kCGScrollEventUnitPixel,
                kCGEventKeyDown, kCGEventKeyUp,
                kCGEventMouseMoved,
                kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                kCGEventRightMouseDown, kCGEventRightMouseUp,
                kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                kCGEventFlagMaskShift, kCGEventFlagMaskControl,
                kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand,
            )
            cls._Q = type(sys)("Quartz")  # namespace
            for n in (
                "CGEventCreateKeyboardEvent", "CGEventCreateMouseEvent",
                "CGEventCreateScrollWheelEvent",
                "CGEventKeyboardSetUnicodeString", "CGEventPost", "CGEventSetFlags",
                "CGEventGetLocation",
                "kCGHIDEventTap", "kCGScrollEventUnitPixel",
                "kCGEventKeyDown", "kCGEventKeyUp",
                "kCGEventMouseMoved",
                "kCGEventLeftMouseDown", "kCGEventLeftMouseUp",
                "kCGEventRightMouseDown", "kCGEventRightMouseUp",
                "kCGEventOtherMouseDown", "kCGEventOtherMouseUp",
                "kCGEventFlagMaskShift", "kCGEventFlagMaskControl",
                "kCGEventFlagMaskAlternate", "kCGEventFlagMaskCommand",
            ):
                setattr(cls._Q, n, locals()[n])
        return cls._Q

    def _name_to_vk(self, name: str) -> int:
        if name in _NAME_TO_VK_MAC:
            return _NAME_TO_VK_MAC[name]
        if len(name) == 1 and name in _CHAR_TO_VK_US:
            return _CHAR_TO_VK_US[name]
        return 0

    def press(self, name: str) -> None:
        Q = self._quartz()
        vk = self._name_to_vk(name)
        event = Q.CGEventCreateKeyboardEvent(None, vk, True)
        if vk == 0 and len(name) == 1:
            Q.CGEventKeyboardSetUnicodeString(event, 1, name)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def release(self, name: str) -> None:
        Q = self._quartz()
        vk = self._name_to_vk(name)
        event = Q.CGEventCreateKeyboardEvent(None, vk, False)
        if vk == 0 and len(name) == 1:
            Q.CGEventKeyboardSetUnicodeString(event, 1, name)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        Q = self._quartz()
        event = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (x, y), 0)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def _mouse_pos(self):
        """Get current mouse position as (x, y) tuple."""
        from AppKit import NSEvent
        from Quartz import CGDisplayPixelsHigh
        pos = NSEvent.mouseLocation()
        return (pos.x, CGDisplayPixelsHigh(0) - pos.y)

    def _btn_event(self, down: bool, button: str):
        Q = self._quartz()
        x, y = self._mouse_pos()
        btn_map = {
            "left": (
                Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, 0,
            ),
            "right": (
                Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, 1,
            ),
            "middle": (
                Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, 2,
            ),
        }
        ev_down, ev_up, btn_num = btn_map.get(button, btn_map["middle"])
        ev_type = ev_down if down else ev_up
        event = Q.CGEventCreateMouseEvent(None, ev_type, (x, y), btn_num)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def mouse_down(self, button: str = "left") -> None:
        self._btn_event(True, button)

    def mouse_up(self, button: str = "left") -> None:
        self._btn_event(False, button)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        Q = self._quartz()
        event = Q.CGEventCreateScrollWheelEvent(
            None, Q.kCGScrollEventUnitPixel, 2, dy * 10, dx * 10,
        )
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def set_modifier(self, name: str, on: bool) -> None:
        """Set a modifier key state directly (without generating key events).
        Useful for toggling caps_lock / num_lock when the physical state
        differs from the desired logical state.
        """
        flag_map = {
            "shift": _MacController._Q.kCGEventFlagMaskShift
                     if _MacController._Q else 1 << 17,
            "ctrl": 1 << 18,
            "alt": 1 << 19,
            "cmd": 1 << 20,
            "super": 1 << 20,
        }
        # For modifiers, we send a flags-changed event
        # This is a simplified approach — for full toggle support use press/release
        self.press(name) if on else self.release(name)


# --- macOS foreground window -----------------------------------------------


def _get_foreground_window_darwin() -> WindowInfo:
    """Return foreground window info.

    Uses only CGWindowList (CoreGraphics C API) which is thread-safe.
    CGWindowListCopyWindowInfo returns windows in front-to-back order,
    so the first layer-0 window is the frontmost.
    """
    from Quartz import (
        CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )

    try:
        wins = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
        )
    except Exception:
        return WindowInfo()

    for w in wins:
        if w.get("kCGWindowLayer", 999) != 0:
            continue
        pid = w.get("kCGWindowOwnerPID", 0)
        return WindowInfo(
            pid=pid,
            process_name=w.get("kCGWindowOwnerName", "") or "",
            title=w.get("kCGWindowName", "") or "",
            window_class="",
            bundle_id="",
        )

    return WindowInfo()


# ====================================================================
#  Windows — low-level hooks via ctypes (WH_KEYBOARD_LL + WH_MOUSE_LL)
# ====================================================================

# Windows virtual key code → name mapping.
_WIN_VK_MAP: dict[int, str] = {
    0x01: "lbutton", 0x02: "rbutton", 0x03: "cancel", 0x04: "mbutton",
    0x05: "xbutton1", 0x06: "xbutton2",
    0x08: "backspace", 0x09: "tab",
    0x0C: "clear", 0x0D: "enter",
    0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0x13: "pause",
    0x14: "caps_lock",
    0x1B: "esc",
    0x20: "space", 0x21: "page_up", 0x22: "page_down",
    0x23: "end", 0x24: "home",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "print_screen", 0x2D: "insert", 0x2E: "delete",
    0x5B: "lwin", 0x5C: "rwin", 0x5D: "apps",
    0x5F: "sleep",
    0x60: "kp0",   0x61: "kp1",   0x62: "kp2",   0x63: "kp3",
    0x64: "kp4",   0x65: "kp5",   0x66: "kp6",   0x67: "kp7",
    0x68: "kp8",   0x69: "kp9",
    0x6A: "kp*",   0x6B: "kp+",
    0x6D: "kp-",   0x6E: "kp.",   0x6F: "kp/",
    0x70: "F1",  0x71: "F2",  0x72: "F3",  0x73: "F4",
    0x74: "F5",  0x75: "F6",  0x76: "F7",  0x77: "F8",
    0x78: "F9",  0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x7C: "F13", 0x7D: "F14", 0x7E: "F15", 0x7F: "F16",
    0x80: "F17", 0x81: "F18", 0x82: "F19", 0x83: "F20",
    0x84: "F21", 0x85: "F22", 0x86: "F23", 0x87: "F24",
    0x90: "num_lock", 0x91: "scroll_lock",
    0xA0: "lshift",  0xA1: "rshift",
    0xA2: "lctrl",   0xA3: "rctrl",
    0xA4: "lalt",    0xA5: "ralt",
    0xA6: "browser_back", 0xA7: "browser_forward",
    0xA8: "browser_refresh", 0xA9: "browser_stop",
    0xAA: "browser_search", 0xAB: "browser_favorites",
    0xAC: "browser_home",
    0xAD: "volume_mute", 0xAE: "volume_down", 0xAF: "volume_up",
    0xB0: "media_next", 0xB1: "media_prev", 0xB2: "media_stop",
    0xB3: "media_play_pause",
    0xB4: "launch_mail", 0xB5: "launch_media_select",
    0xB6: "launch_app1", 0xB7: "launch_app2",
}

_WH_KEYBOARD_LL = 13
_WH_MOUSE_LL = 14
_WM_KEYDOWN, _WM_KEYUP = 0x0100, 0x0101
_WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x0104, 0x0105
_WM_LBUTTONDOWN, _WM_LBUTTONUP = 0x0201, 0x0202
_WM_RBUTTONDOWN, _WM_RBUTTONUP = 0x0204, 0x0205
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208
_WM_XBUTTONDOWN, _WM_XBUTTONUP = 0x020B, 0x020C
_WM_MOUSEMOVE = 0x0200
_WM_MOUSEWHEEL, _WM_MOUSEHWHEEL = 0x020A, 0x020E


def _win_vk_name(vk: int) -> str:
    if vk in _WIN_VK_MAP:
        return _WIN_VK_MAP[vk]
    # Try ToUnicode for printable char
    try:
        buf = ctypes.create_unicode_buffer(4)
        kb_state = (ctypes.c_ubyte * 256)()
        _ = ctypes.windll.user32.ToUnicode(vk, 0, kb_state, buf, 4, 0)
        if buf.value and buf.value.isprintable():
            return buf.value
    except Exception:
        pass
    return f"key({vk})"


def _create_win_hook():
    """Low-level Windows hooks.  Returns object with .start() / .stop()."""
    if _OS != "win32":
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # ---- ctypes types --------------------------------------------------------
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
            ("wParam", ULONG_PTR), ("lParam", ctypes.c_longlong),
            ("time", ctypes.c_uint), ("pt", POINT),
        ]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", ctypes.c_uint32), ("scanCode", ctypes.c_uint32),
            ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", POINT), ("mouseData", ctypes.c_uint32),
            ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
            ("dwExtraInfo", ULONG_PTR),
        ]

    # ---- function prototypes -------------------------------------------------
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_longlong, ctypes.c_int, ULONG_PTR, ctypes.c_longlong,
    )
    _SetWindowsHookExW = user32.SetWindowsHookExW
    _SetWindowsHookExW.argtypes = [
        ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32,
    ]
    _SetWindowsHookExW.restype = ctypes.c_void_p

    _UnhookWindowsHookEx = user32.UnhookWindowsHookEx
    _UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    _UnhookWindowsHookEx.restype = ctypes.c_bool

    _CallNextHookEx = user32.CallNextHookEx
    _CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ULONG_PTR, ctypes.c_longlong,
    ]
    _CallNextHookEx.restype = ctypes.c_longlong

    _GetMessageW = user32.GetMessageW
    _GetMessageW.argtypes = [
        ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ]
    _GetMessageW.restype = ctypes.c_bool

    _PostThreadMessageW = user32.PostThreadMessageW
    _PostThreadMessageW.argtypes = [
        ctypes.c_uint32, ctypes.c_uint, ULONG_PTR, ctypes.c_longlong,
    ]
    _PostThreadMessageW.restype = ctypes.c_bool

    _GetCurrentThreadId = kernel32.GetCurrentThreadId
    _GetCurrentThreadId.argtypes = []
    _GetCurrentThreadId.restype = ctypes.c_uint32

    _WM_STOP = 0x0401
    _WM_PROCESS = 0x0410

    # Packing helpers — coordinates get 32 bits each in wParam;
    # lParam gets message id (low 16) + auxiliary data (upper 48).
    def _pack_mouse(x: int, y: int, msg_id: int, aux: int = 0) -> tuple:
        """Pack mouse event into (wParam, lParam) for PostThreadMessageW."""
        wx = ctypes.c_ulonglong(ctypes.c_uint32(x).value).value
        wy = ctypes.c_ulonglong(ctypes.c_uint32(y).value).value
        wp = (wx << 32) | wy
        lp = (msg_id & 0xFFFF) | ((aux & 0xFFFFFFFFFFFF) << 16)
        return (wp, lp)

    def _unpack_mouse(wParam, lParam) -> tuple:
        """Unpack mouse event → (x, y, msg_id, aux)."""
        msg_id = lParam & 0xFFFF
        aux = (lParam >> 16) & 0xFFFFFFFFFFFF
        wx = (wParam >> 32) & 0xFFFFFFFF
        wy = wParam & 0xFFFFFFFF
        x = ctypes.c_int32(wx).value
        y = ctypes.c_int32(wy).value
        return (x, y, msg_id, aux)

    class WinHook:
        def __init__(self):
            self._kbd_hook = None
            self._mou_hook = None
            self._thread_id = None
            self._ready = threading.Event()
            self.running = False

        # ---- hook callbacks --------------------------------------------------

        def _kbd_proc(self, code, wParam, lParam):
            if code >= 0:
                ks = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if wParam == _WM_KEYDOWN and ks.vkCode == 0x43:  # VK_C
                    if ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000:
                        _PostThreadMessageW(self._thread_id, _WM_STOP, 0, 0)
                _PostThreadMessageW(self._thread_id, _WM_PROCESS, ks.vkCode, wParam)
            return _CallNextHookEx(None, code, wParam, lParam)

        def _mou_proc(self, code, wParam, lParam):
            if code >= 0:
                ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = int(ms.pt.x), int(ms.pt.y)
                msg = wParam

                if msg in (_WM_MOUSEWHEEL, _WM_MOUSEHWHEEL):
                    delta = ctypes.c_short(ms.mouseData >> 16).value
                    wp, lp = _pack_mouse(x, y, msg, delta)
                elif msg in (_WM_XBUTTONDOWN, _WM_XBUTTONUP):
                    xbtn = ms.mouseData >> 16
                    wp, lp = _pack_mouse(x, y, msg, xbtn)
                else:
                    wp, lp = _pack_mouse(x, y, msg)
                _PostThreadMessageW(self._thread_id, _WM_PROCESS, wp, lp)
            return _CallNextHookEx(None, code, wParam, lParam)

        # ---- message processing ----------------------------------------------

        def _process_kbd(self, vk: int, msg_id: int):
            if msg_id in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                _emit_key(_win_vk_name(vk), True, vk)
            elif msg_id in (_WM_KEYUP, _WM_SYSKEYUP):
                _emit_key(_win_vk_name(vk), False, vk)

        def _process_mou(self, x: int, y: int, msg_id: int, aux: int):
            if msg_id in (_WM_LBUTTONDOWN,):
                _emit_mouse(x, y, "left", True)
            elif msg_id in (_WM_LBUTTONUP,):
                _emit_mouse(x, y, "left", False)
            elif msg_id in (_WM_RBUTTONDOWN,):
                _emit_mouse(x, y, "right", True)
            elif msg_id in (_WM_RBUTTONUP,):
                _emit_mouse(x, y, "right", False)
            elif msg_id in (_WM_MBUTTONDOWN,):
                _emit_mouse(x, y, "middle", True)
            elif msg_id in (_WM_MBUTTONUP,):
                _emit_mouse(x, y, "middle", False)
            elif msg_id in (_WM_XBUTTONDOWN,):
                name = "back" if aux == 1 else "forward" if aux == 2 else f"xbutton{aux}"
                _emit_mouse(x, y, name, True)
            elif msg_id in (_WM_XBUTTONUP,):
                name = "back" if aux == 1 else "forward" if aux == 2 else f"xbutton{aux}"
                _emit_mouse(x, y, name, False)
            elif msg_id == _WM_MOUSEWHEEL:
                delta = ctypes.c_short(aux & 0xFFFF).value // 120
                _emit_scroll(0, delta)
            elif msg_id == _WM_MOUSEHWHEEL:
                delta = ctypes.c_short(aux & 0xFFFF).value // 120
                _emit_scroll(delta, 0)

        def _process_message(self, wParam, lParam):
            msg_id = lParam & 0xFFFF
            # Keyboard: lParam = bare message id, wParam = vk
            if msg_id in (_WM_KEYDOWN, _WM_SYSKEYDOWN, _WM_KEYUP, _WM_SYSKEYUP):
                self._process_kbd(int(wParam), msg_id)
            else:
                x, y, msg_id, aux = _unpack_mouse(wParam, lParam)
                self._process_mou(x, y, msg_id, aux)

        # ---- message loop ----------------------------------------------------

        def start(self):
            self._thread_id = _GetCurrentThreadId()
            kbd_cb = HOOKPROC(self._kbd_proc)
            mou_cb = HOOKPROC(self._mou_proc)
            self._kbd_hook = _SetWindowsHookExW(_WH_KEYBOARD_LL, kbd_cb, None, 0)
            self._mou_hook = _SetWindowsHookExW(_WH_MOUSE_LL, mou_cb, None, 0)
            if self._kbd_hook is None or self._mou_hook is None:
                self._ready.set()
                raise OSError("Failed to install Windows hooks")
            self._kbd_cb = kbd_cb
            self._mou_cb = mou_cb
            self._ready.set()

            self.running = True
            msg = MSG()
            while self.running:
                if _GetMessageW(ctypes.byref(msg), None, 0, 0):
                    if msg.message == _WM_STOP:
                        break
                    elif msg.message == _WM_PROCESS:
                        self._process_message(msg.wParam, msg.lParam)

        def stop(self):
            self.running = False
            if self._thread_id is not None:
                _PostThreadMessageW(self._thread_id, _WM_STOP, 0, 0)
                time.sleep(0.02)
            if self._kbd_hook is not None:
                _UnhookWindowsHookEx(self._kbd_hook)
                self._kbd_hook = None
            if self._mou_hook is not None:
                _UnhookWindowsHookEx(self._mou_hook)
                self._mou_hook = None

    return WinHook()


# --- Windows input controller ----------------------------------------------

# Reverse _WIN_VK_MAP → name for sending special keys
_NAME_TO_VK_WIN: dict[str, int] = {}
for _vk, _nm in _WIN_VK_MAP.items():
    _NAME_TO_VK_WIN[_nm] = _vk


class _WinController:
    """Send keyboard / mouse events via SendInput API."""

    def __init__(self):
        self._u32 = ctypes.windll.user32

    def _name_to_vk(self, name: str) -> int:
        if name in _NAME_TO_VK_WIN:
            return _NAME_TO_VK_WIN[name]
        if len(name) == 1:
            vk = self._u32.VkKeyScanW(ord(name)) & 0xFF
            if vk != 0xFF:
                return vk
        return 0

    # ctypes structures for SendInput (instantiated via name to avoid
    # forward-reference hassles inside a class body)
    def _make_kbd_input(self):
        class K(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_void_p),
            ]
        return K

    def _make_mouse_input(self):
        class M(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p),
            ]
        return M

    def _make_input(self, KI, MI):
        class I(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_uint32), ("ki", KI), ("mi", MI),
            ]
        return I

    _K = None  # cached structure classes
    _M = None
    _I = None

    def _kbd_input(self):
        if self._K is None:
            self._K = self._make_kbd_input()
        return self._K()

    def _mouse_input(self):
        if self._M is None:
            self._M = self._make_mouse_input()
        return self._M()

    def _input(self):
        if self._I is None:
            self._I = self._make_input(self._make_kbd_input(), self._make_mouse_input())
        return self._I()

    _INPUT_KEYBOARD = 1
    _INPUT_MOUSE = 0
    _KEYEVENTF_KEYUP = 0x0002

    def _send_kbd(self, vk: int, flags: int = 0):
        inp = self._input()
        inp.type = self._INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = flags
        self._u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def press(self, name: str) -> None:
        vk = self._name_to_vk(name)
        if vk:
            self._send_kbd(vk, 0)

    def release(self, name: str) -> None:
        vk = self._name_to_vk(name)
        if vk:
            self._send_kbd(vk, self._KEYEVENTF_KEYUP)

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        self._u32.SetCursorPos(x, y)

    def _send_mouse(self, flags: int, data: int = 0):
        inp = self._input()
        inp.type = self._INPUT_MOUSE
        inp.mi.mouseData = data
        inp.mi.dwFlags = flags
        self._u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    _INPUT_MOUSE = 0
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040
    _MOUSEEVENTF_XDOWN = 0x0080
    _MOUSEEVENTF_XUP = 0x0100
    _MOUSEEVENTF_WHEEL = 0x0800
    _MOUSEEVENTF_HWHEEL = 0x1000

    _BTN_DOWN = {
        "left": _MOUSEEVENTF_LEFTDOWN,
        "right": _MOUSEEVENTF_RIGHTDOWN,
        "middle": _MOUSEEVENTF_MIDDLEDOWN,
        "back": _MOUSEEVENTF_XDOWN,
        "forward": _MOUSEEVENTF_XDOWN,
    }
    _BTN_UP = {
        "left": _MOUSEEVENTF_LEFTUP,
        "right": _MOUSEEVENTF_RIGHTUP,
        "middle": _MOUSEEVENTF_MIDDLEUP,
        "back": _MOUSEEVENTF_XUP,
        "forward": _MOUSEEVENTF_XUP,
    }
    _BTN_XDATA = {"back": 1, "forward": 2}

    def mouse_down(self, button: str = "left") -> None:
        flags = self._BTN_DOWN.get(button, self._MOUSEEVENTF_LEFTDOWN)
        xdata = self._BTN_XDATA.get(button, 0)
        self._send_mouse(flags, xdata << 16)

    def mouse_up(self, button: str = "left") -> None:
        flags = self._BTN_UP.get(button, self._MOUSEEVENTF_LEFTUP)
        xdata = self._BTN_XDATA.get(button, 0)
        self._send_mouse(flags, xdata << 16)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        if dy:
            self._send_mouse(self._MOUSEEVENTF_WHEEL, dy * 120)
        if dx:
            self._send_mouse(self._MOUSEEVENTF_HWHEEL, dx * 120)

    def set_modifier(self, name: str, on: bool) -> None:
        self.press(name) if on else self.release(name)


# --- Windows foreground window ---------------------------------------------


def _get_foreground_window_win() -> WindowInfo:
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    hwnd = u32.GetForegroundWindow()

    # window title
    title_buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(hwnd, title_buf, 256)
    title = title_buf.value or ""

    # PID
    pid = ctypes.c_uint32()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # process name
    proc_name = ""
    try:
        handle = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if handle:
            exe_buf = ctypes.create_unicode_buffer(260)
            sz = ctypes.c_uint32(260)
            if k32.QueryFullProcessImageNameW(handle, 0, exe_buf, ctypes.byref(sz)):
                proc_name = exe_buf.value.rsplit("\\", 1)[-1]
            k32.CloseHandle(handle)
    except Exception:
        pass

    # window class
    cls_buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, cls_buf, 256)
    wnd_class = cls_buf.value or ""

    return WindowInfo(
        pid=pid.value, process_name=proc_name, title=title,
        window_class=wnd_class, bundle_id="",
    )


# ====================================================================
#  Linux — X11 via python-xlib / XRecord
# ====================================================================

def _is_x11_session() -> bool:
    """Return True if running under X11 (not Wayland)."""
    session = os.environ.get("XDG_SESSION_TYPE", "")
    if session:
        return session.lower() == "x11"
    # Fallback: check if DISPLAY is set and X11-specific vars
    if os.environ.get("DISPLAY", ""):
        if os.environ.get("WAYLAND_DISPLAY", ""):
            return False
        return True
    return False


def _create_x11_hook():
    """X11 hook via XRecord.  Returns object with .start() / .stop()."""
    if _OS != "linux2" and _OS != "linux":
        return None
    if not _is_x11_session():
        # Wayland — not supported yet
        raise NotImplementedError(
            "Wayland is not yet supported. "
            "Please run under X11 or check back for future Wayland support."
        )

    try:
        from Xlib import X, XK, display
        from Xlib.ext import record
        from Xlib.protocol import rq
    except ImportError:
        raise ImportError(
            "python-xlib is required on Linux. "
            "Install with: pip install python-xlib"
        )

    class X11Hook:
        def __init__(self):
            self._ctx = None
            self._display_stop = None
            self._display_record = None
            self._ready = threading.Event()
            self.running = False

        def _key_name(self, event):
            """Extract key name from an X11 KeyPress/KeyRelease event."""
            keysym = event.detail
            try:
                name = XK.keysym_to_string(keysym)
                if name and name.isprintable() and len(name) == 1:
                    return name
                if name:
                    return name.lower()
            except Exception:
                pass
            return f"key({keysym})"

        def _btn_name(self, detail: int) -> str:
            btn_map = {1: "left", 2: "middle", 3: "right",
                       4: "scroll_up", 5: "scroll_down",
                       6: "scroll_left", 7: "scroll_right"}
            if detail in btn_map:
                return btn_map[detail]
            if detail >= 8:
                return f"button{detail}"
            return f"button{detail}"

        def _handler(self, reply):
            if not self.running:
                return
            data = reply.data
            while data:
                event, data = rq.EventField("").parse_binary_value(
                    data, self._display_record.display, 0, None,
                )
                if event is None:
                    continue

                etype = event.type
                if etype == X.KeyPress:
                    _emit_key(self._key_name(event), True, event.detail)
                elif etype == X.KeyRelease:
                    _emit_key(self._key_name(event), False, event.detail)
                elif etype == X.ButtonPress:
                    detail = event.detail
                    if detail in (4, 5, 6, 7):
                        # scroll events
                        mapping = {4: (0, 1), 5: (0, -1), 6: (1, 0), 7: (-1, 0)}
                        dx, dy = mapping.get(detail, (0, 0))
                        _emit_scroll(dx, dy)
                    else:
                        _emit_mouse(
                            event.root_x, event.root_y,
                            self._btn_name(detail), True,
                        )
                elif etype == X.ButtonRelease:
                    detail = event.detail
                    if detail not in (4, 5, 6, 7):
                        _emit_mouse(
                            event.root_x, event.root_y,
                            self._btn_name(detail), False,
                        )
                # MotionNotify not captured (too noisy)

        def start(self):
            self._display_stop = display.Display()
            self._display_record = display.Display()
            if not self._display_record.has_extension("RECORD"):
                self._ready.set()
                raise OSError("X server does not have RECORD extension")

            self._ctx = self._display_record.record_create_context(
                0, [record.AllClients],
                [record.ClientStarted, record.ClientDied, record.EnableData],
            )

            self._ready.set()
            self.running = True
            self._display_record.record_enable_context(self._ctx, self._handler)
            # record_enable_context blocks until record_disable_context is called

        def stop(self):
            self.running = False
            if self._display_record is not None and self._ctx is not None:
                try:
                    self._display_record.record_disable_context(self._ctx)
                    self._display_record.record_free_context(self._ctx)
                except Exception:
                    pass
            if self._display_stop is not None:
                try:
                    self._display_stop.close()
                except Exception:
                    pass
            if self._display_record is not None:
                try:
                    self._display_record.close()
                except Exception:
                    pass
            self._ctx = None

    return X11Hook()


# --- Linux X11 input controller --------------------------------------------


class _X11Controller:
    """Send keyboard / mouse events via X11 XTest extension."""

    _display = None

    @classmethod
    def _disp(cls):
        if cls._display is None:
            from Xlib.display import Display
            cls._display = Display()
        return cls._display

    def _name_to_keysym(self, name: str) -> int:
        from Xlib import XK
        # reverse normalize: common name → X11 keysym
        rev_map = {
            "enter": "Return", "esc": "Escape", "backspace": "BackSpace",
            "tab": "Tab", "space": "space",
            "caps_lock": "Caps_Lock", "num_lock": "Num_Lock",
            "scroll_lock": "Scroll_Lock",
            "page_up": "Page_Up", "page_down": "Page_Down",
            "home": "Home", "end": "End",
            "left": "Left", "right": "Right", "up": "Up", "down": "Down",
            "insert": "Insert", "delete": "Delete",
            "print_screen": "Print", "pause": "Pause",
            "shift": "Shift_L", "ctrl": "Control_L", "alt": "Alt_L",
            "super": "Super_L", "cmd": "Super_L",
            "kp_enter": "KP_Enter", "kp+": "KP_Add", "kp-": "KP_Subtract",
            "kp*": "KP_Multiply", "kp/": "KP_Divide", "kp.": "KP_Decimal",
            "media_play_pause": "XF86AudioPlay",
            "media_stop": "XF86AudioStop",
            "media_next": "XF86AudioNext",
            "media_previous": "XF86AudioPrev",
            "media_volume_mute": "XF86AudioMute",
            "media_volume_down": "XF86AudioLowerVolume",
            "media_volume_up": "XF86AudioRaiseVolume",
        }
        x11_name = rev_map.get(name, name)
        # Try string_to_keysym
        ks = XK.string_to_keysym(x11_name)
        if ks != 0:
            return ks
        # Try as single character
        if len(name) == 1:
            return XK.string_to_keysym(name)
        return 0

    def press(self, name: str) -> None:
        from Xlib import X
        keysym = self._name_to_keysym(name)
        if keysym:
            keycode = self._disp().keysym_to_keycode(keysym)
            if keycode:
                self._disp().xtest_fake_input(X.KeyPress, keycode)
                self._disp().flush()

    def release(self, name: str) -> None:
        from Xlib import X
        keysym = self._name_to_keysym(name)
        if keysym:
            keycode = self._disp().keysym_to_keycode(keysym)
            if keycode:
                self._disp().xtest_fake_input(X.KeyRelease, keycode)
                self._disp().flush()

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        self._disp().warp_pointer(x, y)
        self._disp().flush()

    def _mouse_btn(self, down: bool, button: str):
        from Xlib import X
        btn_map = {"left": 1, "middle": 2, "right": 3}
        btn = btn_map.get(button, 1)
        ev = X.ButtonPress if down else X.ButtonRelease
        self._disp().xtest_fake_input(ev, btn)
        self._disp().flush()

    def mouse_down(self, button: str = "left") -> None:
        self._mouse_btn(True, button)

    def mouse_up(self, button: str = "left") -> None:
        self._mouse_btn(False, button)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        from Xlib import X
        d = self._disp()
        if dy > 0:
            for _ in range(abs(dy)):
                d.xtest_fake_input(X.ButtonPress, 4)
                d.xtest_fake_input(X.ButtonRelease, 4)
        elif dy < 0:
            for _ in range(abs(dy)):
                d.xtest_fake_input(X.ButtonPress, 5)
                d.xtest_fake_input(X.ButtonRelease, 5)
        if dx > 0:
            for _ in range(abs(dx)):
                d.xtest_fake_input(X.ButtonPress, 6)
                d.xtest_fake_input(X.ButtonRelease, 6)
        elif dx < 0:
            for _ in range(abs(dx)):
                d.xtest_fake_input(X.ButtonPress, 7)
                d.xtest_fake_input(X.ButtonRelease, 7)
        d.flush()

    def set_modifier(self, name: str, on: bool) -> None:
        self.press(name) if on else self.release(name)


# --- Linux X11 foreground window --------------------------------------------


def _get_foreground_window_x11() -> WindowInfo:
    try:
        from Xlib.display import Display
        from Xlib import X
        d = Display()
        root = d.screen().root

        # Get _NET_ACTIVE_WINDOW
        net_active = d.get_atom("_NET_ACTIVE_WINDOW", only_if_exists=True)
        if net_active is None:
            return WindowInfo()
        active_prop = root.get_full_property(net_active, X.AnyPropertyType)
        if active_prop is None:
            return WindowInfo()
        win_id = active_prop.value[0]

        win = d.create_resource_object("window", win_id)

        # Window title
        net_name = d.get_atom("_NET_WM_NAME", only_if_exists=True)
        wm_name = d.get_atom("WM_NAME", only_if_exists=True)
        title = ""
        for atom in (net_name, wm_name):
            if atom is None:
                continue
            prop = win.get_full_property(atom, X.AnyPropertyType)
            if prop and prop.value:
                title = prop.value.decode("utf-8", errors="replace") if isinstance(prop.value, bytes) else str(prop.value)
                break

        # PID
        net_pid = d.get_atom("_NET_WM_PID", only_if_exists=True)
        pid = 0
        proc_name = ""
        if net_pid is not None:
            pid_prop = win.get_full_property(net_pid, X.AnyPropertyType)
            if pid_prop and pid_prop.value:
                pid = pid_prop.value[0]
                try:
                    proc_name = os.readlink(f"/proc/{pid}/exe").rsplit("/", 1)[-1]
                except Exception:
                    pass

        # Window class
        wnd_class = ""
        try:
            cls_hint = win.get_wm_class()
            if cls_hint:
                wnd_class = cls_hint[1] if cls_hint[1] else cls_hint[0]
        except Exception:
            pass

        d.close()
        return WindowInfo(
            pid=pid, process_name=proc_name, title=title,
            window_class=wnd_class, bundle_id="",
        )
    except Exception:
        return WindowInfo()


# ====================================================================
#  convenience API
# ====================================================================

_CTRL = ...


def _controller():
    """Lazy singleton returning the platform input controller."""
    global _CTRL
    if _CTRL is ...:
        if _OS == "darwin":
            _CTRL = _MacController()
        elif _OS == "win32":
            _CTRL = _WinController()
        elif _OS.startswith("linux"):
            _CTRL = _X11Controller()
        else:
            raise OSError(f"Unsupported platform: {_OS}")
    return _CTRL


def get_foreground_window() -> WindowInfo:
    """Return the foreground (active) window metadata.

    Returns a :class:`WindowInfo` with ``pid``, ``process_name``, ``title``,
    ``window_class``, and (on macOS) ``bundle_id``.
    """
    if _OS == "darwin":
        return _get_foreground_window_darwin()
    elif _OS == "win32":
        return _get_foreground_window_win()
    elif _OS.startswith("linux"):
        return _get_foreground_window_x11()
    else:
        return WindowInfo()


def press(name: str) -> None:
    """Press (hold down) a key by normalized name.  E.g. ``press("shift")``."""
    _controller().press(_normalize(name))


def release(name: str) -> None:
    """Release a key by normalized name."""
    _controller().release(_normalize(name))


def tap(name: str) -> None:
    """Press and immediately release a key."""
    _controller().tap(_normalize(name))


def hotkey(combo: str) -> None:
    """Send a modifier+key combo, e.g. ``hotkey("ctrl+shift+esc")``.

    Modifiers are pressed in order, the trigger is tapped, then modifiers are
    released in reverse order.
    """
    parts = [_normalize(p) for p in combo.lower().replace(" ", "").split("+")]
    if len(parts) < 2:
        raise ValueError(f"hotkey combo needs at least one modifier: {combo!r}")
    trigger = parts[-1]
    mods = parts[:-1]
    ctrl = _controller()
    for m in mods:
        ctrl.press(m)
        time.sleep(0.01)
    ctrl.tap(trigger)
    time.sleep(0.01)
    for m in reversed(mods):
        ctrl.release(m)


def send(sequence: list) -> None:
    """Send a sequence of key / mouse events.

    Each element in *sequence* is one of:

    * ``str`` or :class:`Key` — tap the key (press + release)
    * ``(str|Key, "down")`` / ``(str|Key, True)`` — press only
    * ``(str|Key, "up")`` / ``(str|Key, False)`` — release only
    * ``(str|Key, float)`` — press, hold for duration, release
    * ``int`` or ``float`` — sleep seconds (delay)
    """
    for item in sequence:
        if isinstance(item, (int, float)):
            time.sleep(item)
            continue
        if isinstance(item, (str, Key)):
            k = item if isinstance(item, Key) else Key(item)
            k.tap()
            continue
        if isinstance(item, tuple):
            if len(item) == 2:
                key, action = item
                k = key if isinstance(key, Key) else Key(key)
                if action in ("down", True):
                    k.press()
                elif action in ("up", False):
                    k.release()
                elif isinstance(action, (int, float)):
                    k.press()
                    time.sleep(action)
                    k.release()
            continue


def move(x: int, y: int) -> None:
    """Move the mouse pointer to absolute pixel coordinates *(x, y)*."""
    _controller().move(x, y)


def click(button: str = "left", count: int = 1) -> None:
    """Click a mouse button at the current pointer position."""
    _controller().click(_normalize(button), count)


def mouse_down(button: str = "left") -> None:
    """Press a mouse button (hold)."""
    _controller().mouse_down(_normalize(button))


def mouse_up(button: str = "left") -> None:
    """Release a mouse button."""
    _controller().mouse_up(_normalize(button))


def scroll(dx: int = 0, dy: int = 0) -> None:
    """Scroll by *(dx, dy)* units."""
    _controller().scroll(dx, dy)


def toggle_modifier(name: str) -> None:
    """Toggle a lock key (caps_lock / num_lock / scroll_lock).

    Sends a press+release pair to flip the hardware state.
    """
    n = _normalize(name)
    c = _controller()
    c.press(n)
    c.release(n)


# ====================================================================
#  main
# ====================================================================

def main():
    global _show_event_device

    Console.set_locale_utf8()

    print()
    print(f"{FLYellow}╔{'═' * 46}╗{CRst}")
    print(f"{FLYellow}║{CRst}  {FLWhite}{CBold}KEYBOARD & MOUSE HOOK MONITOR{CRst}         {FLYellow}║{CRst}")
    print(f"{FLYellow}╚{'═' * 46}╝{CRst}")
    print()

    print(f"{FLYellow}Enumerating input devices...{CRst}")
    devices = enumerate_devices()
    _state["kbd_devs"] = [d for d in devices if d.kind == "KBD"]
    _state["mou_devs"] = [d for d in devices if d.kind == "MOU"]

    if devices:
        print()
        print(f"{FLCyan}{'─' * 60}{CRst}")
        print(f"{FLYellow}  Detected input devices:{CRst}")
        print()
        for d in devices:
            kind_color = FLCyan if d.kind == "KBD" else FLMagenta
            parts = [
                f"  {FLYellow}[{d.idx}]{CRst} {kind_color}[{d.kind}]{CRst} "
                f"{FLWhite}{d.name}{CRst}",
            ]
            if d.vendor_id or d.product_id:
                vid_pid = f"{d.vendor_id}:{d.product_id}" if d.product_id else d.vendor_id
                parts.append(f"{FGray}{vid_pid}{CRst}")
            if d.serial:
                parts.append(f"{FGray}S/N:{d.serial}{CRst}")
            if d.path:
                parts.append(f"{FGray}{d.path}{CRst}")
            print("  ".join(parts))
        print()
        print(f"{FLCyan}{'─' * 60}{CRst}")
        print()
    else:
        print(f"  {FGray}Device enumeration not supported on this platform.{CRst}")
        print()

    if _OS == "darwin":
        show_device_choice = Menu.select(
            [
                MenuOption(["Y"], "Yes", True, FLGreen),
                MenuOption(["N"], "No", False, FLYellow),
            ],
            prompt="Show event source device?",
            default_key="Y",
            inline=True,
            separator=False,
        )
        _show_event_device = bool(show_device_choice)
        print()

    print(f"{FLYellow}Starting hooks...{CRst}")
    print(f"  {FLGreen}↓{CRst} press/down    {FLYellow}↑{CRst} release/up")
    print(f"  {FLRed}Ctrl+C{CRst} to stop")
    print()
    print(f"{FLCyan}{'─' * 60}{CRst}")

    # --- create hook ----------------------------------------------------------
    try:
        hook = _create_hook()
    except (ImportError, OSError, NotImplementedError) as e:
        Console.print_error_and_exit(str(e))
        raise  # unreachable — satisfies the type checker

    # --- run hook -------------------------------------------------------------
    hook_thread = threading.Thread(
        target=hook.start, daemon=True, name="input-hook",
    )
    hook_thread.start()

    if not hook._ready.wait(timeout=5):
        print(f"{FLCyan}  Waiting for hook permission...{CRst}")

    # Print initial foreground window
    _check_win_change()

    try:
        hook_thread.join()
    except KeyboardInterrupt:
        pass
    hook.stop()
    Console.print_exit_message("Bye.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
