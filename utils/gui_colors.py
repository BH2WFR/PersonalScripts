"""Semantic UI colors shared by native and Qt frontends."""

from typing import Literal

type TextColor = Literal["red", "brown", "blue", "cyan", "green", "magenta", "orange", "gray"]
type ButtonColor = Literal["blue", "red", "green", "orange", "magenta"]

_TEXT: dict[TextColor, tuple[str, str]] = {
    "red": ("#bc1431", "#ff8296"), "brown": ("#80471c", "#e4aa73"),
    "blue": ("#075bbc", "#73b6ff"), "cyan": ("#006a75", "#4edbe5"),
    "green": ("#087039", "#69dd92"), "magenta": ("#a11485", "#fa82df"),
    "orange": ("#a04700", "#ffab58"), "gray": ("#565e67", "#b9c1cb"),
}

# Enabled, hovered and pressed fills; all three carry white text.
_BUTTON: dict[ButtonColor, tuple[tuple[str, str, str], tuple[str, str, str]]] = {
    "blue": (("#116fc3", "#1985de", "#093c70"), ("#2277c9", "#318ce6", "#123f70")),
    "red": (("#c52f45", "#e24958", "#7d172a"), ("#ce3b50", "#ec5263", "#811f32")),
    "green": (("#137c48", "#169357", "#104d2e"), ("#208353", "#299962", "#145435")),
    "orange": (("#bd5307", "#d96c0f", "#793406"), ("#bf550b", "#dd6a10", "#803909")),
    "magenta": (("#b52e96", "#d547b2", "#72195e"), ("#be39a0", "#de50be", "#7c2068")),
}


TEXT_COLORS: tuple[TextColor, ...] = tuple(_TEXT)
BUTTON_COLORS: tuple[ButtonColor, ...] = tuple(_BUTTON)


def windows_apps_use_dark_theme() -> bool:
    """Read the current Windows user's app appearance; Windows defaults to light."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return False


def text_hex(color: TextColor, *, dark: bool) -> str:
    """Return a foreground for the specified light or dark surface."""
    return _TEXT[color][dark]


def button_fills(color: ButtonColor, *, dark: bool) -> tuple[str, str, str]:
    """Return normal, hover and pressed backgrounds for white button text."""
    return _BUTTON[color][dark]
