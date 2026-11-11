"""Display labels and scan-word input for the remapper; no duplicate code tables.

Uses utils.Keyboard's public catalog. Standard-library only; no Windows calls.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from utils import *

_FRIENDLY: dict[str, str] = {
    "international1": "JIS Ro / Brazilian extra key",
    "international3": "JIS Yen",
    "kana": "JIS Hiragana / Katakana / Romaji",
    "convert": "JIS Henkan (Convert)", "nonconvert": "JIS Muhenkan (Non-convert)",
    "hangul": "Korean Hangul / English", "hanja": "Korean Hanja",
    "hangul_legacy": "Korean Hangul (legacy message code)",
    "hanja_legacy": "Korean Hanja (legacy message code)",
    "non_us_backslash": "ISO extra key (near Left Shift)",
    "non_us_hash": "ISO Hash (shared with ANSI Backslash)",
    "zenkaku_hankaku": "JIS Zenkaku / Hankaku (Grave position)",
    "zenkaku_hankaku_usb": "USB LANG5 Zenkaku / Hankaku (shared with F24)",
    "eisu": "JIS Eisu (Caps Lock position)",
    "kp_enter": "Keypad Enter", "left_super": "Left Windows", "right_super": "Right Windows",
}
_HEX_INPUT = re.compile(r"(?:0x)?([0-9a-f]{2,4})", re.IGNORECASE)


@dataclass(frozen=True)
class KeyChoice:
    """A display entry; aliases may share the same encoded scan word."""

    code: int
    name: str

    @property
    def label(self) -> str:
        """Return searchable human-readable text that always includes the code."""
        description = _FRIENDLY.get(self.name, self.name.replace("_", " ").title())
        return f"0x{self.code:04X}  |  {description}  [{self.name}]"


def choices() -> tuple[KeyChoice, ...]:
    """Return selectable known keys and aliases from the shared utility catalog."""
    return tuple(KeyChoice(code.value, name) for name, code in Keyboard.windows_scan_entries())


def key_label(code: int) -> str:
    """Label a stored word without losing unknown values; zero means Disable.

    Args:
        code: A validated 16-bit word from a mapping.

    Returns:
        Code plus name, with an explicit unknown label for unsupported prefixes.
    """
    if code == 0:
        return "0x0000  |  Disable key"
    try:
        name = Keyboard.windows_scan_name(WindowsScanCode.from_value(code))
    except ValueError:
        return f"0x{code:04X}  |  Unknown scan word (preserved)"
    return KeyChoice(code, name).label


def parse_key(text: str) -> int:
    """Parse a selection, hexadecimal word or known key alias.

    Args:
        text: Combo label, 2-4 hex digits (optional 0x), or a shared key name.

    Returns:
        A 16-bit word; zero is allowed here, but invalid as a mapping source.

    Raises:
        ValueError: No unambiguous known name or hexadecimal word was supplied.
    """
    stripped = text.strip()
    for item in choices():
        if stripped == item.label:
            return item.code
    # Explicit hex takes precedence; otherwise a key name such as 'f1' does.
    if not stripped.lower().startswith("0x"):
        known = Keyboard.windows_scan_code(stripped)
        if known is not None:
            return known.value
    match = _HEX_INPUT.fullmatch(stripped)
    if match is not None:
        return int(match.group(1), 16)
    raise ValueError("Select a key, enter a known name, or enter a scan word such as 0xE01D.")
