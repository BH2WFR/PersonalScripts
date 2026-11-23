"""Unicode typography and plain-text layout conversions for pasted text."""

from collections.abc import Callable
from functools import cache
import re
from string import ascii_uppercase, ascii_lowercase, digits
import unicodedata as ud
from urllib.parse import urlsplit


_ALPHABET = ascii_uppercase + ascii_lowercase + digits
_MATH_STYLES = {
    "Bold": ("𝐀", "𝐚", "𝟎"), "Italic": ("𝐴", "𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧", "0"),
    "Bold italic": ("𝑨", "𝒂", "0"),
    "Script": ("𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵", "𝒶𝒷𝒸𝒹ℯ𝒻ℊ𝒽𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝓌𝓍𝓎𝓏", "0"),
    "Bold script": ("𝓐", "𝓪", "0"), "Fraktur": ("𝔄𝔅ℭ𝔇𝔈𝔉𝔊ℌℑ𝔍𝔎𝔏𝔐𝔑𝔒𝔓𝔔ℜ𝔖𝔗𝔘𝔙𝔚𝔛𝔜ℨ", "𝔞", "0"),
    "Bold Fraktur": ("𝕬", "𝖆", "0"), "Double-struck": ("𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ", "𝕒", "𝟘"),
    "Sans-serif": ("𝖠", "𝖺", "𝟢"), "Sans-serif bold": ("𝗔", "𝗮", "𝟬"),
    "Sans-serif italic": ("𝘈", "𝘢", "𝟢"), "Sans-serif bold italic": ("𝘼", "𝙖", "𝟬"),
    "Monospace": ("𝙰", "𝚊", "𝟶"), "Fullwidth": ("Ａ", "ａ", "０"),
}


def _sequence(letters: str, length: int) -> str:
    """Expand contiguous blocks, or use the explicit alphabet for Unicode gaps."""
    if len(letters) != 1:
        return letters
    return "".join(chr(ord(letters) + i) for i in range(length))


_STYLED = {
    style: _sequence(upper, 26) + _sequence(lower, 26) + _sequence(zero, 10)
    for style, (upper, lower, zero) in _MATH_STYLES.items()
}
_STYLED.update({
    "Circled": _sequence("Ⓐ", 26) + _sequence("ⓐ", 26) + "⓪①②③④⑤⑥⑦⑧⑨",
    "Negative circled": _sequence("🅐", 26) * 2 + "⓿❶➋➌➍➎➏➐➑➒",
    "Squared": _sequence("🄰", 26) * 2 + digits,
    "Negative squared": _sequence("🅰", 26) * 2 + digits,
    "Superscript": "ᴬᴮᶜᴰᴱᶠᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾQᴿˢᵀᵁⱽᵂˣʸᶻᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ⁰¹²³⁴⁵⁶⁷⁸⁹",
    "Subscript": ascii_uppercase + "ₐbcdₑfgₕᵢⱼₖₗₘₙₒₚqᵣₛₜᵤᵥwₓyz₀₁₂₃₄₅₆₇₈₉",
})
LETTER_STYLES = ("Normal", *_STYLED)


def style_letters(text: str, style: str) -> str:
    """Restore styled letters and digits, then apply the requested alphabet."""
    plain = plain_letters(text)
    if style == "Normal":
        return plain
    return plain.translate(str.maketrans(_ALPHABET, _STYLED[style]))


def plain_letters(text: str) -> str:
    """Decode mixed Unicode styles without normalizing unrelated punctuation or units."""
    def decode(char: str) -> str:
        tag = ud.decomposition(char).partition(" ")[0]
        if tag in {"<font>", "<super>", "<sub>", "<wide>", "<circle>"}:
            plain = ud.normalize("NFKC", char)
            if plain.isalnum():
                return plain
        for first in ("🅐", "🅰", "🄰", "⒜"):
            offset = ord(char) - ord(first)
            if 0 <= offset < 26:
                return (ascii_lowercase if first == "⒜" else ascii_uppercase)[offset]
        if "①" <= char <= "⓿" or "❶" <= char <= "➓":
            if char.isnumeric():
                return str(int(ud.numeric(char)))
        if "🄐" <= char <= "🄩":
            return ascii_uppercase[ord(char) - ord("🄐")]
        return char

    # Enclosed letters pasted from emoji pickers can include a presentation selector.
    text = re.sub(r"([🄰-🅉🅐-🅩🅰-🆉])[\ufe0e\ufe0f]", r"\1", text)
    return text.translate({ord(char): decode(char) for char in set(text) if not char.isascii()})


@cache
def _width_tables() -> tuple[dict[int, str], dict[int, str]]:
    half: dict[int, str] = {}
    full: dict[int, str] = {}
    for point in (0x3000, *range(0xFF00, 0xFFF0)):
        tag, _, base = ud.decomposition(chr(point)).partition(" ")
        if tag not in {"<wide>", "<narrow>"}:
            continue
        wide, narrow = (point, int(base, 16)) if tag == "<wide>" else (int(base, 16), point)
        half[wide], full[narrow] = chr(narrow), chr(wide)
    # Voiced kana have one fullwidth code point and two halfwidth code points.
    for point in range(0x30A0, 0x3100):
        parts = ud.normalize("NFD", chr(point))
        if len(parts) == 2 and all(ord(char) in half for char in parts):
            half[point] = parts.translate(half)
    return half, full


def to_halfwidth(text: str) -> str:
    """Convert characters with halfwidth equivalents, including voiced katakana."""
    return text.translate(_width_tables()[0])


def to_fullwidth(text: str) -> str:
    """Convert width variants and compose halfwidth kana with their voicing marks."""
    full = _width_tables()[1]
    text = re.sub(r"[\uff66-\uff9d][\uff9e\uff9f]",
                  lambda m: ud.normalize("NFC", m[0].translate(full)), text)
    return text.translate(full)


def normalize_spaces(text: str) -> str:
    """Replace Unicode space separators with one ASCII space each."""
    return text.translate({ord(c): " " for c in set(text) if ud.category(c) == "Zs"})


def title_words(text: str) -> str:
    """Titlecase words without splitting at an accent mark or internal apostrophe."""
    pieces: list[str] = []
    start = 0
    for i, char in enumerate(text):
        if char.isalpha():
            continue
        if i > start and (ud.category(char).startswith("M") or
                          (char in "'’" and i + 1 < len(text) and text[i + 1].isalpha())):
            continue
        pieces.append(text[start:i].capitalize())
        pieces.append(char)
        start = i + 1
    pieces.append(text[start:].capitalize())
    return "".join(pieces)


def expand_ligatures(text: str) -> str:
    """Expand Latin typographic ligatures U+FB00 through U+FB06."""
    return text.translate({cp: ud.normalize("NFKC", chr(cp)) for cp in range(0xFB00, 0xFB07)})


def map_lines(text: str, transform: Callable[[str], str]) -> str:
    """Transform each nonempty line while preserving CR, LF, CRLF and blank lines."""
    return re.sub(r"[^\r\n]+", lambda m: transform(m[0]), text)


def remove_blank_lines(text: str) -> str:
    """Remove whitespace-only lines, retaining the other lines' terminators."""
    return re.sub(r"(?:\A|(?<=\n)|(?<=\r)(?!\n))[^\S\r\n]*(?:\r\n|[\r\n]|\Z)", "", text)


def url_hostname(line: str) -> str:
    """Extract the host without credentials or port. Keep non-URL lines intact."""
    value = line.strip()
    if not value or any(c.isspace() for c in value):
        return line
    implicit = "://" not in value and not value.startswith("//")
    try:
        parsed = urlsplit("//" + value if implicit else value)
        host = parsed.hostname
        if not host or (implicit and "." not in host and ":" not in host and host != "localhost"):
            return line
        if "\\" in parsed.netloc:
            return line
        return host
    except ValueError:
        return line


def expand_tabs(line: str, width: int) -> str:
    """Expand tabs on a single line, counting wide CJK characters as two columns."""
    column = 0
    result: list[str] = []
    for char in line:
        if char == "\t":
            spaces = width - column % width
            result.append(" " * spaces)
            column += spaces
        else:
            result.append(char)
            if not ud.combining(char):
                column += 2 if ud.east_asian_width(char) in {"W", "F"} else 1
    return "".join(result)


def _cjk(char: str) -> bool:
    return ud.east_asian_width(char) in {"W", "F"} or "\uff61" <= char <= "\uff9f"


_PDF_TRAILING = "".join(map(chr, (*range(33), *range(0x7F, 0xA0), *range(0x200B, 0x2010),
                                   *range(0x202A, 0x202F), *range(0x2060, 0x2070), 0xFEFF)))


def clean_pdf(text: str) -> str:
    """Join copied PDF lines, keeping period-ended paragraphs and CJK word spacing."""
    pieces: list[str] = []
    previous = ""
    join_word = False
    cleaned = normalize_spaces(expand_ligatures(text))
    for raw in re.split(r"\r\n|[\r\n\u2028\u2029]", cleaned):
        trimmed = raw.rstrip(_PDF_TRAILING)
        line = trimmed.lstrip()
        if not line:
            continue
        if previous:
            if previous.rstrip("\"'”’）)]」』").endswith((".", "。", "．")):
                pieces.append("\n")
            elif not join_word and not (_cjk(previous[-1]) or _cjk(line[0])):
                pieces.append(" ")
        # Edge PDF copies may represent a discretionary hyphen with STX.
        join_word = line.endswith(("-", "\u00ad")) or "\x02" in raw[len(trimmed):]
        pieces.append(line.rstrip("\u00ad"))
        previous = line
    return "".join(pieces)
