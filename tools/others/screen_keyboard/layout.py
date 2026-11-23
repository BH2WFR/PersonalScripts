"""Key positions and colours from the original screen keyboards."""

ROW_UNITS = 16
DEFAULT_SIZE = (512, 197)
MINIMUM_SIZE = (426, 166)
MODIFIERS = {"LControl", "RControl", "LShift", "RShift", "LAlt", "RAlt", "LWin", "RWin"}
ACCENT_LOCK_KEYS = {"NumLock", "ScrollLock"}
ROWS = [
    [("Esc", "Esc", 1)] + [(f"F{i}", f"F{i}", 1) for i in range(1, 13)]
    + [("language", "语言", 1), ("Insert", "Ins", 1), ("Delete", "Del", 1)],
    [(c, label, 1) for c, label in zip("`1234567890-=",
     ["` ~", "1 !", "2 @", "3 #", "4 $", "5 %", "6 ^", "7 &", "8 *", "9 (", "0 )", "- _", "= +"])]
    + [("Backspace", "⌫", 2), ("Home", "Home", 1)],
    [("Tab", "Tab", 1.5)] + [(c, c.upper(), 1) for c in "qwertyuiop"]
    + [("[", "[ {", 1), ("]", "] }", 1), ("\\", "\\ |", 1.5), ("End", "End", 1)],
    [("Layer", "Layer", 2)] + [(c, c.upper(), 1) for c in "asdfghjkl"]
    + [(";", "; :", 1), ("'", "' \"", 1), ("Enter", "Enter", 2), ("PgUp", "PgUp", 1)],
    [("LShift", "Shift", 1.5), ("vkE2sc056", "\\ |", 1)]
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
           "commands": "#64cd7c", "language": "#438a62", "locks": "#e8a07d"}


def key_color(name: str) -> str:
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
    return PALETTE[group]



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
TOOLBAR = [("settings", "设置"), ("extended", "更多"), ("numpad", "数字"),
           ("reset", "释放"), ("redraw", "重绘"), ("size", "复位")]
EXTRA_HEIGHT = 30


def panel_width(width: int, opening: bool, scale: float) -> int:
    """Retain the main keys' widths when the four keypad columns change."""
    edges = 2 * round(4 * scale) - round(3 * scale)
    ratio = (ROW_UNITS + 4) / ROW_UNITS
    return round((width - edges) * (ratio if opening else 1 / ratio)) + edges


def frames(width: int, height: int, scale: float, expanded: bool, numpad: bool,
           mac: bool) -> dict[str, tuple[int, int, int, int]]:
    """Return top-left client rectangles in pixels (Windows) or points (Cocoa)."""
    margin, gap, header = (round(v * scale) for v in (4, 3, 25))
    step, top, tool_w, tool_h = (round(v * scale) for v in (37, 2, 35, 20))
    extra = round(EXTRA_HEIGHT * scale) if expanded else 0
    unit = (width - 2 * margin + gap) / (ROW_UNITS + 4 * numpad)
    body = height - header - margin - extra
    toolbar_x = width - margin - step * len(TOOLBAR)
    result = {"status": (margin, top, max(0, toolbar_x - margin), tool_h)}
    for i, (name, _) in enumerate(TOOLBAR):
        result[name] = (toolbar_x + i * step, top, tool_w, tool_h)
    for r, row in enumerate(MAC_ROWS if mac else ROWS):
        x = float(margin)
        for name, _, units in row:
            result[name] = (round(x), round(header + r * body / 6), round(units * unit - gap),
                            max(round(12 * scale), round(body / 6 - gap)))
            x += units * unit
    if expanded:
        keys = MAC_EXTENDED if mac else EXTENDED_KEYS
        cell = (width - 2 * margin + gap) / len(keys)
        for i, (name, _) in enumerate(keys):
            result[name] = (round(margin + i * cell), height - extra, round(cell - gap), extra - gap - margin)
    if numpad:
        for name, _, col, r, cols, rows in NUMPAD_KEYS:
            result[name] = (round(margin + (ROW_UNITS + col) * unit), round(header + r * body / 5),
                            round(cols * unit - gap), round(rows * body / 5 - gap))
    return result
