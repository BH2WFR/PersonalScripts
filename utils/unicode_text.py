"""Pure Unicode inspection, adapted from the text_actions inspector.

No normalization, GUI imports, clipboard access or process startup occurs here.
Counts and indexes refer to Python Unicode code points, not grapheme clusters.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal

_WORDS = re.compile(r"\w+(?:['\u2019]\w+)*")

_CHARACTER_LABELS = {'\x00': '[NUL]',
 '\x01': '[SOH]',
 '\x02': '[STX]',
 '\x03': '[ETX]',
 '\x04': '[EOT]',
 '\x05': '[ENQ]',
 '\x06': '[ACK]',
 '\x07': '[BEL]',
 '\x08': '[BS]',
 '\t': '[TAB]',
 '\n': '[LF]',
 '\x0b': '[VT]',
 '\x0c': '[FF]',
 '\r': '[CR]',
 '\x0e': '[SO]',
 '\x0f': '[SI]',
 '\x10': '[DLE]',
 '\x11': '[DC1]',
 '\x12': '[DC2]',
 '\x13': '[DC3]',
 '\x14': '[DC4]',
 '\x15': '[NAK]',
 '\x16': '[SYN]',
 '\x17': '[ETB]',
 '\x18': '[CAN]',
 '\x19': '[EM]',
 '\x1a': '[SUB]',
 '\x1b': '[ESC]',
 '\x1c': '[FS]',
 '\x1d': '[GS]',
 '\x1e': '[RS]',
 '\x1f': '[US]',
 ' ': '[SPACE]',
 '\x7f': '[DEL]',
 '\xa0': '[NBSP]',
 '\u2000': '[EN QUAD]',
 '\u2001': '[EM QUAD]',
 '\u2002': '[EN SPACE]',
 '\u2003': '[EM SPACE]',
 '\u2004': '[THREE-PER-EM SPACE]',
 '\u2005': '[FOUR-PER-EM SPACE]',
 '\u2006': '[SIX-PER-EM SPACE]',
 '\u2007': '[FIGURE SPACE]',
 '\u2008': '[PUNCTUATION SPACE]',
 '\u2009': '[THIN SPACE]',
 '\u200a': '[HAIR SPACE]',
 '\u200b': '[ZWSP]',
 '\u200c': '[ZWNJ]',
 '\u200d': '[ZWJ]',
 '\u200e': '[LRM]',
 '\u200f': '[RLM]',
 '\u2028': '[LSEP]',
 '\u2029': '[PSEP]',
 '\u202a': '[LRE]',
 '\u202b': '[RLE]',
 '\u202c': '[PDF]',
 '\u202d': '[LRO]',
 '\u202e': '[RLO]',
 '\u202f': '[NARROW NBSP]',
 '\u205f': '[MEDIUM MATHEMATICAL SPACE]',
 '\u2060': '[WJ]',
 '\u3000': '[IDEOGRAPHIC SPACE]',
 '\ufeff': '[BOM/ZWNBSP]',
 '\ufff9': '[INTERLINEAR ANNOTATION ANCHOR]',
 '\ufffa': '[INTERLINEAR ANNOTATION SEPARATOR]',
 '\ufffb': '[INTERLINEAR ANNOTATION TERMINATOR]',
 '￼': '[OBJECT]',
 '�': '[REPLACEMENT]',
 '\ufffe': '[NONCHARACTER]',
 '\uffff': '[NONCHARACTER]'}

_CATEGORY_NAMES = {'Cc': 'Control',
 'Cf': 'Format',
 'Cn': 'Unassigned',
 'Co': 'Private use',
 'Cs': 'Surrogate',
 'Ll': 'Lowercase letter',
 'Lm': 'Modifier letter',
 'Lo': 'Other letter',
 'Lt': 'Titlecase letter',
 'Lu': 'Uppercase letter',
 'Mc': 'Spacing mark',
 'Me': 'Enclosing mark',
 'Mn': 'Nonspacing mark',
 'Nd': 'Decimal number',
 'Nl': 'Letter number',
 'No': 'Other number',
 'Pc': 'Connector punctuation',
 'Pd': 'Dash punctuation',
 'Pe': 'Close punctuation',
 'Pf': 'Final punctuation',
 'Pi': 'Initial punctuation',
 'Po': 'Other punctuation',
 'Ps': 'Open punctuation',
 'Sc': 'Currency symbol',
 'Sk': 'Modifier symbol',
 'Sm': 'Math symbol',
 'So': 'Other symbol',
 'Zl': 'Line separator',
 'Zp': 'Paragraph separator',
 'Zs': 'Space separator'}

_CONTROL_NAMES = {0: 'NULL',
 1: 'START OF HEADING',
 2: 'START OF TEXT',
 3: 'END OF TEXT',
 4: 'END OF TRANSMISSION',
 5: 'ENQUIRY',
 6: 'ACKNOWLEDGE',
 7: 'BELL',
 8: 'BACKSPACE',
 9: 'HORIZONTAL TABULATION',
 10: 'LINE FEED',
 11: 'VERTICAL TABULATION',
 12: 'FORM FEED',
 13: 'CARRIAGE RETURN',
 14: 'SHIFT OUT',
 15: 'SHIFT IN',
 16: 'DATA LINK ESCAPE',
 17: 'DEVICE CONTROL ONE',
 18: 'DEVICE CONTROL TWO',
 19: 'DEVICE CONTROL THREE',
 20: 'DEVICE CONTROL FOUR',
 21: 'NEGATIVE ACKNOWLEDGE',
 22: 'SYNCHRONOUS IDLE',
 23: 'END OF TRANSMISSION BLOCK',
 24: 'CANCEL',
 25: 'END OF MEDIUM',
 26: 'SUBSTITUTE',
 27: 'ESCAPE',
 28: 'FILE SEPARATOR',
 29: 'GROUP SEPARATOR',
 30: 'RECORD SEPARATOR',
 31: 'UNIT SEPARATOR',
 127: 'DELETE'}


@dataclass(frozen=True)
class TextStatistics:
    """Code-point/word/line counts and strict encoded byte lengths without BOMs.

    A byte length is None when the text contains an unpaired surrogate.
    Words follow the source inspector's Unicode-aware word/apostrophe pattern.
    """

    characters: int
    utf8_bytes: int | None
    utf16_bytes: int | None
    words: int
    lines: int

    def items(self) -> tuple[tuple[str, int | None], ...]:
        """Return stable English labels and values for reports and GUI summaries."""
        return (("Characters", self.characters), ("UTF-8 bytes", self.utf8_bytes),
                ("UTF-16 bytes", self.utf16_bytes), ("Words", self.words), ("Lines", self.lines))


@dataclass(frozen=True)
class UnicodeCharacter:
    """One original code point plus a safe display representation and metadata."""

    index: int
    character: str
    display: str
    codepoint: int
    utf8: str
    category: str
    name: str
    style: Literal["", "control", "special", "non_ascii", "non_bmp"]

    def columns(self) -> tuple[str, ...]:
        """Return index, display, U+ code, decimal, UTF-8, category and name."""
        return (str(self.index), self.display, f"U+{self.codepoint:04X}", str(self.codepoint),
                self.utf8, f"{self.category} - {_CATEGORY_NAMES[self.category]}", self.name)


@dataclass(frozen=True)
class UnicodeReport:
    """Immutable inspection of the exact input text, including whitespace."""

    text: str
    statistics: TextStatistics
    characters: tuple[UnicodeCharacter, ...]


class UnicodeText:
    """Shared, GUI-independent character analysis and report formatting."""

    COLUMNS = ("Index", "Character", "Code point", "Decimal", "UTF-8", "Category", "Name")

    @staticmethod
    def statistics(text: str) -> TextStatistics:
        """Count code points, encoded bytes, regex words and CR/LF-aware lines.

        UTF-16 is measured in little-endian bytes without a BOM. Empty input has
        zero lines; CRLF counts as one separator. Encoding errors yield None
        for both byte totals instead of silently replacing invalid code points.
        """
        try:
            utf8: int | None = len(text.encode("utf-8"))
            utf16: int | None = len(text.encode("utf-16-le"))
        except UnicodeEncodeError:
            utf8 = utf16 = None
        return TextStatistics(len(text), utf8, utf16, len(_WORDS.findall(text)),
                              text.replace("\r\n", "\n").replace("\r", "\n").count("\n") + 1 if text else 0)

    @staticmethod
    def inspect(text: str) -> UnicodeReport:
        """Inspect each code point without normalization or grapheme merging.

        Controls/format characters are labelled or escaped; combining marks use
        a dotted circle for display. Isolated surrogates remain inspectable, but
        are marked as unencodable rather than assigned fabricated UTF-8 bytes.
        """
        rows: list[UnicodeCharacter] = []
        for index, character in enumerate(text):
            cp = ord(character)
            category = unicodedata.category(character)
            name = _CONTROL_NAMES.get(cp, unicodedata.name(character, "<no Unicode name>"))
            if 0xFDD0 <= cp <= 0xFDEF or cp & 0xFFFF in (0xFFFE, 0xFFFF):
                name = "NONCHARACTER"
            display = _CHARACTER_LABELS.get(character)
            if display is None:
                if category.startswith("M"):
                    display = "\u25cc" + character
                else:
                    display = character if character.isprintable() else ascii(character)[1:-1]
            try:
                utf8 = character.encode("utf-8").hex(" ").upper()
            except UnicodeEncodeError:
                utf8 = "<invalid surrogate>"
            style: Literal["", "control", "special", "non_ascii", "non_bmp"] = ""
            if category == "Cc":
                style = "control"
            elif character in _CHARACTER_LABELS or category[0] in ("C", "Z", "M"):
                style = "special"
            elif cp > 0xFFFF:
                style = "non_bmp"
            elif not character.isascii():
                style = "non_ascii"
            rows.append(UnicodeCharacter(index, character, display, cp, utf8, category, name, style))
        return UnicodeReport(text, UnicodeText.statistics(text), tuple(rows))

    @staticmethod
    def format_report(report: UnicodeReport) -> str:
        """Format the exact original text, statistics and tab-separated rows."""
        stats = "\n".join(f"{label}: {value if value is not None else '<invalid surrogate>'}"
                          for label, value in report.statistics.items())
        rows = "\n".join("\t".join(row.columns()) for row in report.characters)
        return f"Original text:\n{report.text}\n\n{stats}\n\n" + "\t".join(UnicodeText.COLUMNS) + "\n" + rows
