"""Pointer interaction shared by the nonactivating Tk and Cocoa windows."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from time import monotonic
from typing import Protocol

from utils import ConfigStore
from .layout import ACCENT_LOCK_KEYS, DEFAULT_SIZE, MAC_LABELS, MODIFIERS, NUMPAD_NAVIGATION, key_color


@dataclass(frozen=True)
class WindowLayout:
    """Keyboard client size in logical units, including any open panels."""

    width: int = DEFAULT_SIZE[0]
    height: int = DEFAULT_SIZE[1]
    expanded: bool = False
    numpad: bool = False

    @classmethod
    def from_config(cls, value: object) -> "WindowLayout":
        if not isinstance(value, dict):
            return cls()
        width, height = value.get("width"), value.get("height")
        if (type(width) is not int or type(height) is not int
                or not (0 < width <= 32767 and 0 < height <= 32767)):
            return cls()
        return cls(width, height, value.get("expanded") is True, value.get("numpad") is True)


class LeftKeyMode(StrEnum):
    NATIVE = "native"
    CAPS = "CapsLock"
    F1 = "F1"
    F24 = "F24"

    @classmethod
    def supported(cls, mac: bool) -> tuple["LeftKeyMode", ...]:
        return (cls.NATIVE, cls.CAPS, cls.F1) if mac else tuple(cls)

    @property
    def menu_label(self) -> str:
        return "Left key: Caps Lock (default)" if self is LeftKeyMode.NATIVE else f"Left key: Layer ({self.value})"


@dataclass(frozen=True)
class KeyRepeat:
    """A backend's repeat event and its system delay and interval in seconds."""

    delay: float
    interval: float
    send: Callable[[], None]


class Output(Protocol):
    mac: bool
    mode: LeftKeyMode

    def target(self) -> int: ...
    def locks(self) -> dict[str, bool]: ...
    def hold(self, name: str, down: bool) -> None: ...
    def key_down(self, name: str, modifiers: list[str]) -> KeyRepeat | None: ...
    def key_up(self) -> None: ...
    def language(self) -> None: ...
    def reset(self) -> None: ...


class KeyboardState:
    """Keep pointer, one-shot modifier and long-press state across redraws."""

    def __init__(self, output: Output, schedule: Callable[[int, Callable[[], None]], None],
                 cancel: Callable[[], None], refresh: Callable[[], None], force_layer: LeftKeyMode | None = None) -> None:
        self.output = output
        self.space_modifiers = ("LWin", "RWin") if output.mac else ("LAlt", "RAlt")
        self.schedule = schedule
        self.cancel = cancel
        self.refresh = refresh
        self.store = ConfigStore("screen-keyboard.yaml")
        settings = self.store.load()
        self.setting = "macos_left_key" if output.mac else "windows_left_key"
        self.modes = LeftKeyMode.supported(output.mac)
        saved = settings.get(self.setting)
        self.preferred_mode = next((mode for mode in self.modes if mode.value == saved), LeftKeyMode.NATIVE)
        self.force_layer = force_layer
        self.output.mode = force_layer or self.preferred_mode
        self.window_setting = "macos_window" if output.mac else "windows_window"
        window = settings.get(self.window_setting)
        self.remember_size = isinstance(window, dict) and window.get("remember_size") is True
        self.window_layout = WindowLayout.from_config(window) if self.remember_size else WindowLayout()
        self.target = output.target()
        self.held: list[str] = []
        self.locked: set[str] = set()
        self.pressed: str | None = None
        self.lock_states = output.locks()

    @property
    def adapted(self) -> bool:
        return self.output.mode is not LeftKeyMode.NATIVE

    def set_mode(self, mode: LeftKeyMode) -> None:
        """Release the old route before switching and persisting the preference."""
        if mode not in self.modes:
            raise ValueError(f"Unsupported left key mode: {mode}")
        if self.force_layer is not None or mode == self.output.mode:
            return
        self.reset()
        self.store.update({self.setting: mode.value})
        self.preferred_mode = mode
        self.output.mode = mode
        self.refresh()

    def apply_launch_mode(self, force_layer: LeftKeyMode | None) -> None:
        """Apply a relaunch override without saving it or retaining keys from the old route."""
        mode = force_layer or self.preferred_mode
        if mode != self.output.mode:
            self.reset()
        self.force_layer = force_layer
        self.output.mode = mode
        self.refresh()

    def set_remember_size(self, enabled: bool, layout: WindowLayout) -> None:
        """Save the current size on opt-in and discard the saved layout on opt-out."""
        if enabled == self.remember_size:
            return
        window = {"remember_size": enabled, **(asdict(layout) if enabled else {})}
        self.store.edit(lambda settings: settings.update({self.window_setting: window}))
        self.remember_size = enabled
        self.window_layout = layout if enabled else WindowLayout()

    def save_window(self, layout: WindowLayout) -> None:
        """Persist the current platform's layout after a completed resize."""
        if self.remember_size and layout != self.window_layout:
            self.store.update({self.window_setting: asdict(layout)})
            self.window_layout = layout

    def modifiers(self) -> list[str]:
        return [key for key in self.held if key != "Layer"]

    def sticky(self, name: str) -> bool:
        return name in MODIFIERS or name == "Fn" or (self.adapted and name == "Layer")

    def reset(self) -> None:
        self.cancel()
        self.pressed = None
        try:
            self.output.reset()
        finally:
            self.held.clear()
            self.locked.clear()
            self.refresh()

    def check_target(self) -> bool:
        target = self.output.target()
        if target == self.target:
            return False
        self.target = target
        self.reset()
        return True

    def press_key(self, name: str) -> KeyRepeat | None:
        if name == "Layer":
            name = "CapsLock"
        if name in NUMPAD_NAVIGATION and not self.output.locks()["NumLock"]:
            name = NUMPAD_NAVIGATION[name][0]
        return self.output.key_down(name, self.modifiers())

    def press(self, name: str) -> None:
        self.check_target()
        if self.pressed is not None:
            self.release()
        self.cancel()
        if not self.target:
            return
        self.pressed = name
        if name == "language":
            self.reset()
            self.output.language()
            self.pressed = name
        elif self.sticky(name):
            down = name not in self.held
            self.output.hold(name, down)
            if down:
                self.held.append(name)
                self.schedule(500, lambda: self.lock(name))
            else:
                self.held.remove(name)
                self.locked.discard(name)
        else:
            repeat = self.press_key(name)
            if repeat is not None:
                self.schedule_repeat(name, repeat, monotonic() + repeat.delay)
            if name in {"Layer", "CapsLock", "ScrollLock", "NumLock"}:
                self.lock_states = self.output.locks()
        self.refresh()

    def schedule_repeat(self, name: str, repeat: KeyRepeat, deadline: float) -> None:
        """Follow the system cadence without accumulating dispatch time or replaying missed events."""
        def fire() -> None:
            if self.pressed != name or self.check_target():
                return
            repeat.send()
            now = monotonic()
            following = deadline + repeat.interval
            self.schedule_repeat(name, repeat, following if following > now else now + repeat.interval)

        self.schedule(max(1, round((deadline - monotonic()) * 1000)), fire)

    def lock(self, name: str) -> None:
        if self.pressed == name and name in self.held:
            self.locked.add(name)
            self.refresh()

    def release(self) -> None:
        self.cancel()
        name, self.pressed = self.pressed, None
        if name and not self.check_target() and not self.sticky(name):
            if name != "language":
                self.output.key_up()
            for held in reversed(self.held.copy()):
                if held not in self.locked:
                    self.output.hold(held, False)
                    self.held.remove(held)
        self.refresh()

    def status(self) -> str:
        if not self.adapted or "Layer" not in self.held:
            return "Normal"
        shift = "LShift" in self.held or "RShift" in self.held
        upper_layer = any(key in self.space_modifiers or key in ("LAlt", "RAlt") for key in self.held)
        return f"Layer {1 + shift + 2 * upper_layer}"

    def shows_layer_hint(self, name: str) -> bool:
        """Show the hint while the keyboard holds Layer across pointer clicks."""
        return self.adapted and "Layer" in self.held and name in self.space_modifiers

    def label(self, name: str, label: str) -> str:
        if self.shows_layer_hint(name):
            return "L3/4"
        if name == "Layer":
            return "Layer" if self.adapted else "⇪" if self.output.mac else "CapsLock"
        if self.output.mac and not self.lock_states["NumLock"]:
            if name == "NumLock":
                return "Nav"
            if name == "Numpad5":
                return "·"
        if name in NUMPAD_NAVIGATION and not self.lock_states["NumLock"]:
            return NUMPAD_NAVIGATION[name][1]
        return MAC_LABELS.get(name, label) if self.output.mac else label

    def colors(self, name: str) -> tuple[str, str]:
        active = name in self.held or name == self.pressed
        if name == "language":
            return ("#185337" if active else key_color(name)), "white"
        lock = "CapsLock" if name == "Layer" and not self.adapted else name
        palette_key = "NumLock" if lock == "CapsLock" and not self.adapted else name
        if lock in self.lock_states:
            accent = palette_key in ACCENT_LOCK_KEYS
            if active:
                return ("#f4bd9d" if accent else "#99db9d"), "#202124"
            if self.lock_states[lock]:
                return ("#9f4929" if accent else "#185337"), "white"
        if name in self.locked:
            return "#7a202a", "#ffe160"
        if self.shows_layer_hint(name):
            palette_key = "Layer"
        return ("#34657c", "white") if active else (key_color(palette_key), "#202124")


def hover_color(color: str) -> str:
    """Brighten the current key colour using the Windows palette."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    blend = 0.18 if max(rgb) < 128 else 0.35
    return "#" + "".join(f"{round(c + (255 - c) * blend):02x}" for c in rgb)
