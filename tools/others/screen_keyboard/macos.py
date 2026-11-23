"""Session-level Mac input and Karabiner's primary/secondary HID route."""

from functools import cache
import time

import Quartz as Q  # pyright: ignore[reportMissingImports]

from utils import Keyboard
from utils.macos_input import frontmost_target, post_key as post
from .input_sources import switch_input_source

# Key code, generic flag and side flag from IOLLEvent.h.
DIRECT = {
    "LControl": (59, 1 << 18, 1), "RControl": (62, 1 << 18, 0x2000),
    "LShift": (56, 1 << 17, 2), "RShift": (60, 1 << 17, 4),
    "LAlt": (58, 1 << 19, 0x20), "RAlt": (61, 1 << 19, 0x40),
    "LWin": (55, 1 << 20, 8), "RWin": (54, 1 << 20, 0x10), "Fn": (63, 1 << 23, 0),
}
ADAPTED = {**DIRECT, "LControl": DIRECT["Fn"], "RAlt": DIRECT["RControl"], "Fn": (110, 0, 0)}
CAPS_KEYCODE = 57
ALIASES = {"PgUp": "page_up", "PgDn": "page_down", "Insert": "help", "Application": "menu",
           "NumpadDiv": "kp/", "NumpadMult": "kp*", "NumpadSub": "kp-", "NumpadAdd": "kp+",
           "NumpadEnter": "kp_enter", "NumpadDot": ".", "NumpadDel": "delete", "NumpadIns": "help",
           "NumpadPgUp": "page_up", "NumpadPgDn": "page_down", "NumpadHome": "home", "NumpadEnd": "end",
           **{f"Numpad{k}": k.lower() for k in ("Left", "Right", "Up", "Down")},
           **{f"Numpad{n}": str(n) for n in range(10)}}


@cache
def keycode(name: str) -> int:
    if name == "vkE2sc056":
        return 10
    code = Keyboard.macos_virtual_key(ALIASES.get(name, name))
    if code is None:
        raise ValueError(f"Unknown macOS key {name!r}")
    return code


class MacOutput:
    mac = True

    def __init__(self) -> None:
        self.adapted = False
        self.numeric = True
        self.held: list[str] = []
        self.secondary: set[str] = set()
        self.previous_source: str | None = None

    def target(self) -> int:
        return frontmost_target()

    def locks(self) -> dict[str, bool]:
        return {"CapsLock": bool(Q.CGEventSourceFlagsState(0) & Q.kCGEventFlagMaskAlphaShift),
                "NumLock": self.numeric}

    def layer_status(self, held: list[str]) -> str:
        return "Secondary" if self.secondary else "Primary"

    @property
    def tap(self) -> int:
        return Q.kCGHIDEventTap if self.adapted else Q.kCGSessionEventTap

    def flags(self, held: list[str]) -> int:
        table = ADAPTED if self.adapted else DIRECT
        flags = Q.CGEventSourceFlagsState(0) & Q.kCGEventFlagMaskAlphaShift
        for key in held:
            if key == "Layer":
                continue
            _, generic, side = table[key]
            flags |= generic | side
        return flags

    def hold(self, name: str, down: bool) -> None:
        held = [key for key in self.held if key != name]
        if down:
            held.append(name)
        if name == "Layer":
            post(CAPS_KEYCODE, down, self.flags(held), self.tap)
        else:
            code, generic, _ = (ADAPTED if self.adapted else DIRECT)[name]
            post(code, down, self.flags(held), self.tap, modifier=bool(generic))
        self.held = held
        if name == "Layer" and not down:
            self.secondary.clear()
        elif "Layer" in held and name in {"LAlt", "LWin", "RWin"}:
            if down:
                self.secondary.add(name)
            else:
                self.secondary.clear()

    def key(self, name: str, modifiers: list[str]) -> None:
        if name == "NumLock":
            self.numeric = not self.numeric
            return
        if name == "NumpadClear":
            return  # Centre keypad position has no navigation output on macOS.
        if not Q.CGPreflightPostEventAccess():
            raise RuntimeError("Allow Accessibility access for this application in System Settings.")
        if name == "CapsLock":
            post(CAPS_KEYCODE, True, None, Q.kCGSessionEventTap)
            try:
                time.sleep(0.2)
            finally:
                post(CAPS_KEYCODE, False, None, Q.kCGSessionEventTap)
            return
        direct = name.startswith("Numpad") or name in {"Screenshot", "Application", "F13"}
        tap = Q.kCGSessionEventTap if direct else self.tap
        flags = Q.CGEventSourceFlagsState(0) if direct else self.flags(modifiers)
        if name == "Screenshot":
            code, flags = keycode("5"), flags | Q.kCGEventFlagMaskCommand | Q.kCGEventFlagMaskShift
        else:
            code = keycode(name)
        if ALIASES.get(name, "").startswith("kp"):
            flags |= Q.kCGEventFlagMaskNumericPad
        post(code, True, flags, tap)
        post(code, False, flags, tap)

    def language(self) -> None:
        self.previous_source = switch_input_source(self.previous_source)

    def reset(self) -> None:
        errors = []
        for key in reversed(self.held.copy()):
            try:
                self.hold(key, False)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("\n".join(errors))
