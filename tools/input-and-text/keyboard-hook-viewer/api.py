"""Convenience input-sending API and key wrapper.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.

Only for legitimate keyboard testing, custom hotkeys and authorized automation.
Obtain permission from affected users; never use for covert surveillance or
credential collection. Users are responsible for their use and its consequences.
"""

from __future__ import annotations

from utils import *
from collections.abc import Sequence
from typing import Literal
from . import backend
from .models import Hotkey, KeyEvent, MouseEvent, WindowInfo, InputController
from .runtime import setup

__all__ = [
    "Hotkey", "KeyEvent", "MouseEvent", "WindowInfo", "Key", "setup",
    "get_foreground_window", "press", "release", "tap", "hotkey", "send",
    "move", "click", "mouse_down", "mouse_up", "scroll", "toggle_modifier",
]


class Key:
    """Represents a key that can be pressed, released, or tapped.

    ``name`` is normalised so ``"caps"``, ``"Caps_Lock"``, and ``"caps_lock"``
    are all equivalent.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = Keyboard.normalize_name(name)

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

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Key):
            return self._name == other._name
        if isinstance(other, str):
            return self._name == Keyboard.normalize_name(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._name)

_CTRL: InputController | None = None


def _controller() -> InputController:
    """Return the lazily initialized platform input controller."""
    global _CTRL
    if _CTRL is None:
        _CTRL = backend.create_controller()
    return _CTRL


get_foreground_window = backend.get_foreground_window


def press(name: str) -> None:
    """Press (hold down) a key by normalized name.  E.g. ``press("shift")``."""
    _controller().press(Keyboard.normalize_name(name))


def release(name: str) -> None:
    """Release a key by normalized name."""
    _controller().release(Keyboard.normalize_name(name))


def tap(name: str) -> None:
    """Press and immediately release a key."""
    _controller().tap(Keyboard.normalize_name(name))


def hotkey(combo: str) -> None:
    """Send a modifier+key combo, e.g. ``hotkey("ctrl+shift+esc")``.

    Modifiers are pressed in order, the trigger is tapped, then modifiers are
    released in reverse order.
    """
    parts = [Keyboard.normalize_name(p) for p in combo.lower().replace(" ", "").split("+")]
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


def send(sequence: Sequence[str | Key | int | float | tuple[str | Key, Literal["down", "up"] | bool | float]]) -> None:
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
    _controller().click(Keyboard.normalize_name(button), count)


def mouse_down(button: str = "left") -> None:
    """Press a mouse button (hold)."""
    _controller().mouse_down(Keyboard.normalize_name(button))


def mouse_up(button: str = "left") -> None:
    """Release a mouse button."""
    _controller().mouse_up(Keyboard.normalize_name(button))


def scroll(dx: int = 0, dy: int = 0) -> None:
    """Scroll by *(dx, dy)* units."""
    _controller().scroll(dx, dy)


def toggle_modifier(name: str) -> None:
    """Toggle a lock key (caps_lock / num_lock / scroll_lock).

    Sends a press+release pair to flip the hardware state.
    """
    n = Keyboard.normalize_name(name)
    c = _controller()
    c.press(n)
    c.release(n)
