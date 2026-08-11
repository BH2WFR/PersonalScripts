"""Interactive menu option descriptor."""

class MenuOption:
    """A single option in an interactive selection menu.

    Attributes:
        keys: Trigger keys, case-insensitive (e.g. ``["N"]`` or ``["1", "+"]``).
        description: Human-readable label (may contain ANSI color codes).
        value: Value returned when selected (defaults to *keys[0]* if ``None``).
        desc_color: ANSI color to wrap *description* (empty → use *default_desc_color*).
    """
    __slots__ = ("keys", "description", "value", "desc_color")

    def __init__(self, keys, description, value=None, desc_color=""):
        self.keys = [k.upper() for k in keys]
        self.description = description
        self.value = value if value is not None else keys[0]
        self.desc_color = desc_color
