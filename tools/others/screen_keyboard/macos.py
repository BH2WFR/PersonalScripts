"""Session-level Mac input and Karabiner's primary/secondary HID route."""

from collections.abc import Callable
from functools import cache
from math import isfinite
import time
from typing import Any, cast

import AppKit  # pyright: ignore[reportMissingImports]
import Quartz  # pyright: ignore[reportMissingImports]

from utils import Keyboard
from utils.macos_input import frontmost_target, post_key as post
from .input_sources import switch_input_source
from .state import KeyRepeat, LeftKeyMode

# PyObjC supplies these framework members dynamically.
A = cast(Any, AppKit)
Q = cast(Any, Quartz)

# Key code, generic flag and side flag from IOLLEvent.h.
DIRECT = {
    "LControl": (59, 1 << 18, 1), "RControl": (62, 1 << 18, 0x2000),
    "LShift": (56, 1 << 17, 2), "RShift": (60, 1 << 17, 4),
    "LAlt": (58, 1 << 19, 0x20), "RAlt": (61, 1 << 19, 0x40),
    "LWin": (55, 1 << 20, 8), "RWin": (54, 1 << 20, 0x10), "Fn": (63, 1 << 23, 0),
}
ADAPTED = {**DIRECT, "LControl": DIRECT["Fn"], "RAlt": DIRECT["RControl"], "Fn": (110, 0, 0)}
CAPS_KEYCODE = 57
LANGUAGE_F18_DELAY_MS = 80
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

    def __init__(self, call_later: Callable[[int, Callable[[], None]], object]) -> None:
        self.call_later = call_later
        self.mode = LeftKeyMode.NATIVE
        self.numeric = True
        self.held: list[str] = []
        self.pressed_key: tuple[int, int, int] | None = None
        self.previous_source: str | None = None

    def target(self) -> int:
        return frontmost_target()

    def locks(self) -> dict[str, bool]:
        return {"CapsLock": bool(Q.CGEventSourceFlagsState(0) & Q.kCGEventFlagMaskAlphaShift),
                "NumLock": self.numeric}

    @property
    def tap(self) -> int:
        return Q.kCGSessionEventTap if self.mode is LeftKeyMode.NATIVE else Q.kCGHIDEventTap

    def flags(self, held: list[str]) -> int:
        table = DIRECT if self.mode is LeftKeyMode.NATIVE else ADAPTED
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
            code = keycode("F1") if self.mode is LeftKeyMode.F1 else CAPS_KEYCODE
            post(code, down, self.flags(held), self.tap)
        else:
            code, generic, _ = (DIRECT if self.mode is LeftKeyMode.NATIVE else ADAPTED)[name]
            post(code, down, self.flags(held), self.tap, modifier=bool(generic))
        self.held = held

    def key_down(self, name: str, modifiers: list[str]) -> KeyRepeat | None:
        """Press the resolved key and supply AppKit's cadence for Quartz autorepeat events."""
        if "Layer" in self.held and name == self.mode.value:
            return None
        if name == "NumLock":
            self.numeric = not self.numeric
            return None
        if name == "NumpadClear":
            return None  # Centre keypad position has no navigation output on macOS.
        if not Q.CGPreflightPostEventAccess():
            raise RuntimeError("Allow Accessibility access for this application in System Settings.")
        if name == "CapsLock":
            post(CAPS_KEYCODE, True, None, Q.kCGSessionEventTap)
            try:
                time.sleep(0.2)
            finally:
                post(CAPS_KEYCODE, False, None, Q.kCGSessionEventTap)
            return None
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
        self.pressed_key = code, flags, tap

        # Karabiner holds this key on its virtual HID keyboard; macOS generates its repeats.
        if tap == Q.kCGHIDEventTap:
            return None
        delay, interval = A.NSEvent.keyRepeatDelay(), A.NSEvent.keyRepeatInterval()
        if not (isfinite(delay) and isfinite(interval) and delay >= 0 and interval > 0):
            return None
        return KeyRepeat(delay, interval, lambda: post(code, True, flags, tap, repeat=True))

    def key_up(self) -> None:
        if self.pressed_key is not None:
            code, flags, tap = self.pressed_key
            post(code, False, flags, tap)
            self.pressed_key = None

    def language(self) -> None:
        self.previous_source, pid = switch_input_source(self.previous_source)

        def tap_f18() -> None:
            if self.target() == pid:
                code = keycode("F18")
                post(code, True, 0)
                post(code, False, 0)

        self.call_later(LANGUAGE_F18_DELAY_MS, tap_f18)

    def reset(self) -> None:
        errors = []
        try:
            self.key_up()
        except Exception as exc:
            errors.append(str(exc))
        for key in reversed(self.held.copy()):
            try:
                self.hold(key, False)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("\n".join(errors))
