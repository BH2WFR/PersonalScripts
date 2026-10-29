"""Hook event dispatch, callbacks and hotkey matching.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
import threading
from typing import Callable, cast
from collections.abc import Sequence
from .models import KeyEvent, MouseEvent, InputDevice, Hotkey, Hook, EventSink
from . import backend, ui


_TOGGLE_NAMES: frozenset[str] = frozenset({"caps_lock", "num_lock", "scroll_lock"})

_on_key_cb: "Callable[[KeyEvent], None] | None" = None
_on_mouse_cb: "Callable[[MouseEvent], None] | None" = None
_hotkeys: list[Hotkey] = []
_held: set[str] = set()       # currently held momentary keys
_physical_held: set[str] = set()
_toggled: set[str] = set()    # toggle keys currently in "on" state

def _emit_key(
    name: str,
    pressed: bool,
    raw_vk: int = 0,
    device: "InputDevice | None" = None,
    *,
    scan_code: WindowsScanCode | None = None,
    raw_flags: int = 0,
) -> None:
    """Called by every platform hook for key events.

    Normalises the name, updates held/toggled state, checks hotkeys,
    calls the user callback, and prints the default formatting.
    """
    ui._check_win_change()
    norm = Keyboard.normalize_name(name, collapse_modifiers=True)
    physical = Keyboard.normalize_name(name)

    if norm in _TOGGLE_NAMES:
        # Toggle keys: each physical press flips the logical state.
        # Ignore the corresponding release — only the press matters.
        if not pressed:
            return
        if norm in _toggled:
            _toggled.discard(norm)
        else:
            _toggled.add(norm)
        ui._print_key(physical, True, device, scan_code)
        ui._print_key(physical, False, device, scan_code)
        if _on_key_cb:
            event_device = device or InputDevice.empty()
            _on_key_cb(KeyEvent(
                norm, True, name, raw_vk,
                event_device.name, event_device.serial, event_device.path,
                scan_code, raw_flags,
            ))
            _on_key_cb(KeyEvent(
                norm, False, name, raw_vk,
                event_device.name, event_device.serial, event_device.path,
                scan_code, raw_flags,
            ))
        return

    if pressed:
        if physical in _physical_held:
            return  # skip auto-repeat
        _physical_held.add(physical)
        _held.add(norm)
        # Hotkey matching: trigger must match, all modifiers must be held/toggled
        for hk in _hotkeys:
            if hk._trigger == norm and hk._mods.issubset(_held | _toggled):
                hk._callback()
    else:
        _physical_held.discard(physical)
        if not any(Keyboard.normalize_name(key, collapse_modifiers=True) == norm for key in _physical_held):
            _held.discard(norm)

    ui._print_key(physical, pressed, device, scan_code)
    if _on_key_cb:
        event_device = device or InputDevice.empty()
        _on_key_cb(KeyEvent(
            norm, pressed, name, raw_vk,
            event_device.name, event_device.serial, event_device.path,
            scan_code, raw_flags,
        ))


def _emit_mouse(x: int, y: int, btn: str, pressed: bool) -> None:
    """Called by every platform hook for mouse button events."""
    ui._check_win_change()
    ui._print_mouse(x, y, btn, pressed)
    if _on_mouse_cb:
        _on_mouse_cb(MouseEvent(x=x, y=y, button=btn, pressed=pressed))


def _emit_scroll(dx: int, dy: int) -> None:
    """Called by every platform hook for scroll events."""
    ui._check_win_change()
    ui._print_scroll(dx, dy)
    if _on_mouse_cb:
        _on_mouse_cb(MouseEvent(scroll_dx=dx, scroll_dy=dy, is_scroll=True))


# ============ public setup ============

def setup(
    *, on_key: Callable[[KeyEvent], None] | None = None,
    on_mouse: Callable[[MouseEvent], None] | None = None,
    hotkeys: Sequence[Hotkey] | None = None, blocking: bool = True,
) -> tuple[Hook, threading.Thread]:
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

    _held.clear()
    _physical_held.clear()
    _toggled.clear()
    hook = backend.create_hook(cast(EventSink, sys.modules[__name__]))
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
