"""Pointer interaction shared by the nonactivating Tk and Cocoa windows."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from utils import ConfigStore
from .layout import DEFAULT_SIZE, MAC_LABELS, MODIFIERS, NUMPAD_NAVIGATION, key_color


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


class Output(Protocol):
    mac: bool
    adapted: bool

    def target(self) -> int: ...
    def locks(self) -> dict[str, bool]: ...
    def layer_status(self, held: list[str]) -> str: ...
    def hold(self, name: str, down: bool) -> None: ...
    def key(self, name: str, modifiers: list[str]) -> None: ...
    def language(self) -> None: ...
    def reset(self) -> None: ...


class KeyboardState:
    """Keep pointer, one-shot modifier and long-press state across redraws."""

    def __init__(self, output: Output, schedule: Callable[[int, Callable[[], None]], None],
                 cancel: Callable[[], None], refresh: Callable[[], None]) -> None:
        self.output = output
        self.schedule = schedule
        self.cancel = cancel
        self.refresh = refresh
        self.store = ConfigStore("screen-keyboard.yaml")
        self.setting = "adapt_to_custom_karabiner_config" if output.mac else "adapt_to_custom_autohotkey_config"
        settings = self.store.load()
        self.output.adapted = settings.get(self.setting) is True
        self.window_setting = "macos_window" if output.mac else "windows_window"
        self.window_layout = WindowLayout.from_config(settings.get(self.window_setting))
        self.target = output.target()
        self.held: list[str] = []
        self.locked: set[str] = set()
        self.pressed: str | None = None
        self.lock_states = output.locks()

    @property
    def adapted(self) -> bool:
        return self.output.adapted

    def set_adapted(self, enabled: bool) -> None:
        """Release the old route before switching and persisting the preference."""
        if enabled == self.adapted:
            return
        self.reset()
        self.store.update({self.setting: enabled})
        self.output.adapted = enabled
        self.refresh()

    def save_window(self, layout: WindowLayout) -> None:
        """Persist the current platform's layout after a completed resize."""
        if layout != self.window_layout:
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

    def send_key(self, name: str) -> None:
        if name == "Layer":
            name = "CapsLock"
        if name in NUMPAD_NAVIGATION and not self.output.locks()["NumLock"]:
            name = NUMPAD_NAVIGATION[name][0]
        self.output.key(name, self.modifiers())

    def press(self, name: str) -> None:
        self.check_target()
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
            self.send_key(name)
            if name not in {"Layer", "CapsLock", "ScrollLock", "NumLock"}:
                self.schedule(450, lambda: self.repeat(name))
            else:
                self.lock_states = self.output.locks()
        self.refresh()

    def repeat(self, name: str) -> None:
        if not self.check_target() and self.pressed == name:
            self.send_key(name)
            self.schedule(45, lambda: self.repeat(name))

    def lock(self, name: str) -> None:
        if self.pressed == name and name in self.held:
            self.locked.add(name)
            self.refresh()

    def release(self) -> None:
        self.cancel()
        name, self.pressed = self.pressed, None
        if name and not self.check_target() and not self.sticky(name):
            for held in reversed(self.held.copy()):
                if held not in self.locked:
                    self.output.hold(held, False)
                    self.held.remove(held)
        self.refresh()

    def status(self) -> str:
        if not self.adapted or "Layer" not in self.held:
            return "普通输入"
        return self.output.layer_status(self.held)

    def label(self, name: str, label: str) -> str:
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
        if lock in self.lock_states:
            accent = lock in {"NumLock", "ScrollLock"}
            if active:
                return ("#f4bd9d" if accent else "#99db9d"), "#202124"
            if self.lock_states[lock]:
                return ("#9f4929" if accent else "#185337"), "white"
        if name in self.locked:
            return "#7a202a", "#ffe160"
        return ("#34657c", "white") if active else (key_color(name), "#202124")


def hover_color(color: str) -> str:
    """Brighten the current key colour using the Windows palette."""
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    blend = 0.18 if max(rgb) < 128 else 0.35
    return "#" + "".join(f"{round(c + (255 - c) * blend):02x}" for c in rgb)
