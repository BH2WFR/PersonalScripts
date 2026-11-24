"""Events and hotkey definitions shared by viewer modules.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import IntFlag
from typing import Protocol
import threading
from utils import *


class GesturePhase(IntFlag):
    """Native NSEvent phase flags retained for gesture display, including zero."""

    NONE = 0
    BEGAN = 1
    STATIONARY = 2
    CHANGED = 4
    ENDED = 8
    CANCELLED = 16
    MAY_BEGIN = 32


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
    scan_code: WindowsScanCode | None = None
    raw_flags: int = 0

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

@dataclasses.dataclass
class InputDevice:
    """Input device identity as reported by the operating system."""
    idx: int
    name: str
    kind: str
    vendor_id: str
    product_id: str
    serial: str
    path: str

    @classmethod
    def empty(cls) -> "InputDevice":
        """Return an empty identity for an event without device information."""
        return cls(0, "", "", "", "", "", "")

class Hotkey:
    """A key combination that triggers *callback* when all modifiers are held
    and the trigger key is pressed.

    *combo* is a ``+``-separated string, e.g. ``"caps+a"`` or ``"ctrl+shift+k"``.
    The last segment is the trigger; preceding segments are modifiers.
    Key names are normalized so ``"caps"``, ``"Caps_Lock"``, and
    ``"caps_lock"`` are all equivalent.

    Modifiers may include toggle keys (``caps_lock``, ``num_lock``,
    ``scroll_lock``) — these are treated as held while their toggle state is on.
    """

    __slots__ = ("_mods", "_trigger", "_callback")

    def __init__(self, combo: str, callback: Callable[[], None]) -> None:
        parts = [Keyboard.normalize_name(p, collapse_modifiers=True) for p in combo.lower().replace(" ", "").split("+")]
        if len(parts) < 2:
            raise ValueError(
                f"Hotkey combo must have at least one modifier: {combo!r}"
            )
        self._mods: frozenset[str] = frozenset(parts[:-1])
        self._trigger: str = parts[-1]
        self._callback = callback

    def __repr__(self) -> str:
        return f"Hotkey({'+'.join(sorted(self._mods))}+{self._trigger})"


class EventSink(Protocol):
    """Callbacks accepted by native backends; raw fields are never OS-converted."""

    def _emit_key(
        self, name: str, pressed: bool, raw_vk: int = 0,
        device: InputDevice | None = None, *,
        scan_code: WindowsScanCode | None = None, raw_flags: int = 0,
    ) -> None: ...

    def _emit_mouse(self, x: int, y: int, btn: str, pressed: bool) -> None: ...

    def _emit_scroll(
        self, dx: int, dy: int, *, raw_delta: tuple[float, float] | None = None,
    ) -> None: ...

    def _emit_magnify(self, delta: float, phase: GesturePhase) -> None: ...


class Hook(Protocol):
    """Native monitor lifecycle, with readiness signaling from its worker."""

    _ready: threading.Event
    running: bool

    def start(self) -> None: ...

    def stop(self) -> None: ...


class InputController(Protocol):
    """Input operations implemented by each native controller."""

    def press(self, name: str) -> None: ...
    def release(self, name: str) -> None: ...
    def tap(self, name: str) -> None: ...
    def move(self, x: int, y: int) -> None: ...
    def click(self, button: str = "left", count: int = 1) -> None: ...
    def mouse_down(self, button: str = "left") -> None: ...
    def mouse_up(self, button: str = "left") -> None: ...
    def scroll(self, dx: int = 0, dy: int = 0) -> None: ...
    def set_modifier(self, name: str, on: bool) -> None: ...
