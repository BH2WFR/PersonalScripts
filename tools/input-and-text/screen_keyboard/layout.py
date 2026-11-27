"""Key positions and colours from the original screen keyboards."""

ROW_UNITS = 16
WINDOW_TITLE = "Screen Keyboard"
DEFAULT_SIZE = (512, 197)
MINIMUM_SIZE = (426, 166)
MODIFIERS = {"LControl", "RControl", "LShift", "RShift", "LAlt", "RAlt", "LWin", "RWin"}
ACCENT_LOCK_KEYS = {"NumLock", "ScrollLock"}
ROWS = [
    [("Esc", "Esc", 1)] + [(f"F{i}", f"F{i}", 1) for i in range(1, 13)]
    + [("language", "Lang", 1), ("Insert", "Ins", 1), ("Delete", "Del", 1)],
    [(c, label, 1) for c, label in zip("`1234567890-=",
     ["` ~", "1 !", "2 @", "3 #", "4 $", "5 %", "6 ^", "7 &", "8 *", "9 (", "0 )", "- _", "= +"])]
    + [("Backspace", "⌫", 2), ("Home", "Home", 1)],
    [("Tab", "Tab", 1.5)] + [(c, c.upper(), 1) for c in "qwertyuiop"]
    + [("[", "[ {", 1), ("]", "] }", 1), ("\\", "\\ |", 1.5), ("End", "End", 1)],
    [("Layer", "Layer", 2)] + [(c, c.upper(), 1) for c in "asdfghjkl"]
    + [(";", "; :", 1), ("'", "' \"", 1), ("Enter", "Enter", 2), ("PgUp", "PgUp", 1)],
    [("LShift", "Shift", 1.5), ("vkE2sc056", "§ ±", 1)]
    + [(c, c.upper(), 1) for c in "zxcvbnm"]
    + [(",", ", <", 1), (".", ". >", 1), ("/", "/ ?", 1), ("RShift", "Shift", 1.5),
       ("Up", "↑", 1), ("PgDn", "PgDn", 1)],
    [("LControl", "Ctrl", 1.25), ("LWin", "Win", 1.25), ("LAlt", "Alt", 1.25),
     ("Space", "Space", 5.5), ("RAlt", "Alt", 1.25), ("AppsKey", "Menu", 1.25),
     ("RControl", "Ctrl", 1.25), ("Left", "←", 1), ("Down", "↓", 1), ("Right", "→", 1)],
]
EXTENDED_KEYS = [("PrintScreen", "PrtSc"), ("ScrollLock", "ScrLk"), ("Pause", "Pause"),
                 ("CapsLock", "Caps"), ("RWin", "RWin"),
                 *[(f"F{i}", f"F{i}") for i in range(13, 25)]]
# 名称、标签、列、行、列跨度、行跨度。
NUMPAD_KEYS = [
    ("NumLock", "Num", 0, 0, 1, 1), ("NumpadDiv", "/", 1, 0, 1, 1),
    ("NumpadMult", "*", 2, 0, 1, 1), ("NumpadSub", "−", 3, 0, 1, 1),
    ("Numpad7", "7", 0, 1, 1, 1), ("Numpad8", "8", 1, 1, 1, 1),
    ("Numpad9", "9", 2, 1, 1, 1), ("NumpadAdd", "+", 3, 1, 1, 2),
    ("Numpad4", "4", 0, 2, 1, 1), ("Numpad5", "5", 1, 2, 1, 1),
    ("Numpad6", "6", 2, 2, 1, 1), ("Numpad1", "1", 0, 3, 1, 1),
    ("Numpad2", "2", 1, 3, 1, 1), ("Numpad3", "3", 2, 3, 1, 1),
    ("NumpadEnter", "Enter", 3, 3, 1, 2), ("Numpad0", "0", 0, 4, 2, 1),
    ("NumpadDot", ".", 2, 4, 1, 1),
]
NUMPAD_NAVIGATION = {
    "Numpad0": ("NumpadIns", "Ins"), "Numpad1": ("NumpadEnd", "End"),
    "Numpad2": ("NumpadDown", "↓"), "Numpad3": ("NumpadPgDn", "PgDn"),
    "Numpad4": ("NumpadLeft", "←"), "Numpad5": ("NumpadClear", "Clear"),
    "Numpad6": ("NumpadRight", "→"), "Numpad7": ("NumpadHome", "Home"),
    "Numpad8": ("NumpadUp", "↑"), "Numpad9": ("NumpadPgUp", "PgUp"),
    "NumpadDot": ("NumpadDel", "Del"),
}
PALETTE = {"letters": "#aadef6", "symbols": "#ffdc68", "modifiers": "#59c1e7",
           "layer": "#f78bb5", "arrows": "#eba7f4", "navigation": "#99db9d",
           "commands": "#64cd7c", "language": "#36794f", "locks": "#e8a07d"}


DARK_PALETTE = {"letters": "#264b60", "symbols": "#594a22", "modifiers": "#20526a",
                "layer": "#643750", "arrows": "#583c64", "navigation": "#34513b",
                "commands": "#205138", "language": "#305d46", "locks": "#66422e"}


def key_color(name: str, *, dark: bool = False) -> str:
    if name == "Layer":
        group = "layer"
    elif name in ACCENT_LOCK_KEYS:
        group = "locks"
    elif name in MODIFIERS or name == "Fn":
        group = "modifiers"
    elif name in {"Left", "Right", "Up", "Down"}:
        group = "arrows"
    elif name == "language":
        group = "language"
    elif len(name) == 1 and name.isalpha():
        group = "letters"
    elif name in {"Esc", "Tab", "Enter", "NumpadEnter", "Backspace", "Delete", "Insert", "AppsKey"}:
        group = "commands"
    elif len(name) == 1 or name in {"Space", "vkE2sc056"} or name.startswith("Numpad"):
        group = "symbols"
    else:
        group = "navigation"
    return (DARK_PALETTE if dark else PALETTE)[group]



MAC_LABELS = {
    "Esc": "⎋", "Tab": "⇥", "Backspace": "⌫", "Delete": "⌦", "Enter": "↩",
    "Space": "␣", "Home": "↖", "End": "↘", "PgUp": "⇞", "PgDn": "⇟",
    "LControl": "⌃", "LAlt": "⌥", "RAlt": "⌥", "LWin": "⌘", "RWin": "⌘",
    "LShift": "⇧", "RShift": "⇧", "NumpadEnter": "↩",
}
MAC_ROWS = [
    *ROWS[:-1],
    [("LControl", "⌃", 1.25), ("LAlt", "⌥", 1.25), ("LWin", "⌘", 1.25),
     ("Space", "␣", 5.5), ("RWin", "⌘", 1.25), ("Fn", "Fn", 1.25),
     ("RAlt", "⌥", 1.25), ("Left", "←", 1), ("Down", "↓", 1), ("Right", "→", 1)],
]
MAC_EXTENDED = [("Screenshot", "Screenshot"), ("Application", "Menu"), ("F13", "F13")]
TOOLBAR = [("settings", "Prefs"), ("extended", "Ext"), ("numpad", "Num"),
           ("reset", "Release"), ("redraw", "Redraw"), ("size", "Reset")]
TOOLBAR_DIVIDERS = {"settings": "after_settings", "numpad": "after_numpad"}
TOOLBAR_TIPS = {
    "settings": "Keyboard preferences",
    "extended": "Toggle extra keys",
    "numpad": "Toggle number pad",
    "reset": "Release held keys",
    "redraw": "Refresh keyboard",
    "size": "Restore default size",
}
EXTRA_HEIGHT = 30


def mac_frame_near_pointer(pointer: tuple[float, float], visible_frame: tuple[tuple[float, float], tuple[float, float]],
                           size: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    """Place the panel in Cocoa coordinates using the Karabiner keyboard's margins."""
    (x0, y0), (screen_w, screen_h) = visible_frame
    margin, gap = 8, 16
    left, bottom = x0 + margin, y0 + margin
    right, top = x0 + screen_w - margin, y0 + screen_h - margin
    width, height = min(size[0], right - left), min(size[1], top - bottom)
    mx, my = pointer
    x, y = mx + gap, my - gap - height
    if x + width > right:
        x = mx - gap - width
    if y < bottom:
        y = my + gap
    return ((max(left, min(x, right - width)), max(bottom, min(y, top - height))), (width, height))


def panel_width(width: int, opening: bool, scale: float) -> int:
    """Retain the main keys' widths when the four keypad columns change."""
    edges = 2 * round(4 * scale) - round(3 * scale)
    ratio = (ROW_UNITS + 4) / ROW_UNITS
    return round((width - edges) * (ratio if opening else 1 / ratio)) + edges


def frames(width: int, height: int, scale: float, expanded: bool, numpad: bool,
           mac: bool) -> dict[str, tuple[int, int, int, int]]:
    """Return top-left client rectangles in pixels (Windows) or points (Cocoa)."""
    margin, gap, header = (round(v * scale) for v in (4, 3, 25))
    top, tool_h = round(2 * scale), round(20 * scale)
    extra = round(EXTRA_HEIGHT * scale) if expanded else 0
    unit = (width - 2 * margin + gap) / (ROW_UNITS + 4 * numpad)
    compact = unit * ROW_UNITS < 640 * scale or height < 260 * scale
    footer = round((10.5 if compact else 12) * scale)
    footer_top = height - footer
    # Each row pitch includes a gap; only interior rows need that space.
    body = footer_top - extra - header + gap
    result = {"header": (0, 0, width, header), "footer": (0, footer_top, width, footer)}
    x_right = width - margin
    for name, _ in reversed(TOOLBAR):
        if name in TOOLBAR_DIVIDERS:
            line_w = max(1, round(scale))
            x_right -= gap + line_w
            result[TOOLBAR_DIVIDERS[name]] = (x_right, top + gap, line_w, tool_h - 2 * gap)
            x_right -= gap
        tool_w = round({"reset": 54, "redraw": 48}.get(name, 35) * scale)
        x_right -= tool_w
        result[name] = (x_right, top, tool_w, tool_h)
        x_right -= round(2 * scale)
    result["status"] = (margin, top, max(0, x_right - margin), tool_h)
    for r, row in enumerate(MAC_ROWS if mac else ROWS):
        x = float(margin)
        y = round(header + r * body / 6)
        bottom = round(header + (r + 1) * body / 6) - gap
        for name, _, units in row:
            result[name] = (round(x), y, round(units * unit - gap), max(round(12 * scale), bottom - y))
            x += units * unit
    if expanded:
        keys = MAC_EXTENDED if mac else EXTENDED_KEYS
        cell = (width - 2 * margin + gap) / len(keys)
        for i, (name, _) in enumerate(keys):
            result[name] = (round(margin + i * cell), footer_top - extra + gap, round(cell - gap), extra - gap)
    if numpad:
        for name, _, col, r, cols, rows in NUMPAD_KEYS:
            y = round(header + r * body / 5)
            bottom = round(header + (r + rows) * body / 5) - gap
            result[name] = (round(margin + (ROW_UNITS + col) * unit), y, round(cols * unit - gap), bottom - y)
    return result
