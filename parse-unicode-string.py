# Parse and display Unicode character info for each character in the input string
from my_utils import *
import unicodedata

# Character display names for special/whitespace/control characters
REPLACE_MAP = {
    "\x00":"[NUL]",  "\x01":"[SOH]",  "\x02":"[STX]",  "\x03":"[ETX]",
    "\x04":"[EOT]",  "\x05":"[ENQ]",  "\x06":"[ACK]",  "\x07":"[\\a]",
    "\x08":"[\\b]",  "\x09":"[\\t]",  "\x0a":"[\\n]",  "\x0b":"[\\v]",
    "\x0c":"[\\f]",  "\x0d":"[\\r]",  "\x0e":"[SO]",   "\x0f":"[SI]",
    "\x10":"[DLE]",  "\x11":"[DC1]",  "\x12":"[DC2]",  "\x13":"[DC3]",
    "\x14":"[DC4]",  "\x15":"[NAK]",  "\x16":"[SYN]",  "\x17":"[ETB]",
    "\x18":"[CAN]",  "\x19":"[EM]",   "\x1a":"[SUB]",  "\x1b":"[ESC]",
    "\x1c":"[FS]",   "\x1d":"[GS]",   "\x1e":"[RS]",   "\x1f":"[US]",
    " ":   "[sp]",   "\x7f":"[DEL]",

    "\u3000": "[ideographic sp]",   "\u2002": "[en sp]",
    "\u2003": "[em sp]",            "\u2007": "[figure sp]",
    "\u2008": "[punct sp]",         "\u2009": "[thin sp]",
    "\u200A": "[hair sp]",          "\u200D": "[ZWJ]",
    "\uFFF9": "[interlinear]",     "\uFFFA": "[annot sep]",
    "\uFFFB": "[annot end]",
    "\u00A0":"[no-break sp] ",      "\u2000":"[en quad]",
    "\u2001":"[em quad]",           "\u2004":"[1/3em sp]",
    "\u2005":"[1/4em sp]",          "\u2006":"[1/6em sp]",
    "\u200B":"[ZWSP] ",             "\u200C":"[ZWNJ] ",
    "\u200E":"[LRM] ",              "\u200F":"[RLM] ",
    "\u202A":"[LRE]",               "\u202B":"[RLE]",
    "\u202C":"[PDF]",               "\u202D":"[LRO]",
    "\u202E":"[RLO]",               "\u202F":"[narrow NBSP]",
    "\u2028":"[LSEP]",              "\u2029":"[PSEP]",
    "\u205F":"[med math sp] ",      "\u2060":"[WJ] ",
    "\uFEFF":"[ZWNBSP]",
}

DESC_CONTROL = {
    0x00: "NULL",                   0x01: "START OF HEADING",
    0x02: "START OF TEXT",          0x03: "END OF TEXT",
    0x04: "END OF TRANSMISSION",    0x05: "ENQUIRY",
    0x06: "ACKNOWLEDGE",            0x07: "BELL",
    0x08: "BACKSPACE",              0x09: "HORIZONTAL TABULATION",
    0x0A: "LINE FEED",              0x0B: "VERTICAL TABULATION",
    0x0C: "FORM FEED",              0x0D: "CARRIAGE RETURN",
    0x0E: "SHIFT OUT",              0x0F: "SHIFT IN",
    0x10: "DATA LINK ESCAPE",       0x11: "DEVICE CONTROL ONE",
    0x12: "DEVICE CONTROL TWO",     0x13: "DEVICE CONTROL THREE",
    0x14: "DEVICE CONTROL FOUR",    0x15: "NEGATIVE ACKNOWLEDGE",
    0x16: "SYNCHRONOUS IDLE",       0x17: "END OF TRANSMISSION BLOCK",
    0x18: "CANCEL",                 0x19: "END OF MEDIUM",
    0x1A: "SUBSTITUTE",             0x1B: "ESCAPE",
    0x1C: "FILE SEPARATOR",         0x1D: "GROUP SEPARATOR",
    0x1E: "RECORD SEPARATOR",       0x1F: "UNIT SEPARATOR",
    0x7F: "DELETE",
}

def display_width(s: str) -> int:
    """Calculate the display width of a string in a terminal (CJK chars = 2 columns)."""
    w = 0
    for ch in s:
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w


def pad_to_width(s: str, target_width: int) -> str:
    """Pad a string to a fixed display width, accounting for CJK wide characters."""
    current = display_width(s)
    return s + " " * (target_width - current)


print(f"{FLYellow}=========== UNICODE STRING PARSER ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}UNICODE STRING PARSER{CRst}
=====================

Usage:
  python {script_name} <string>       parse the given string
  python {script_name}                no arguments, interactive multi-line input
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  Print each character's Unicode info: index, char, hex, decimal, and description.
  Special characters (spaces, control chars, zero-width chars) are shown in brackets.
""")
    sys.exit(0)


#============ 用户交互 ===========
if len(sys.argv) > 1:
    text = " ".join(sys.argv[1:])
else:
    print(f"{FLYellow}Enter text to parse (one or more lines).{CRst}")
    print(f"{FLCyan}End with {FLYellow}Ctrl+Z then Enter (Windows) or Ctrl+D (Linux/macOS){FLCyan}:{CRst}")
    lines = []
    while True:
        try:
            line = input()
            lines.append(line)
        except EOFError:
            break
    text = "\n".join(lines)
    if not text:
        print(f"{FLRed}No input provided. EXIT...{CRst}\n")
        sys.exit(1)

text_len = len(text)
print(f"\n{FLYellow}Input length: {text_len} character(s){CRst}")
print(f"{FLYellow}Input string: {CRst}{FLCyan}{repr(text)}{CRst}\n")


#============ 打印表头 ===========
print(f"┌───────┬────────────────────┬──────────┬───────────┬──────────────────────────────────┐")
print(f"│ Index │ Char               │   Hex    │    Dec    │ Description                      │")
print(f"├───────┼────────────────────┼──────────┼───────────┼──────────────────────────────────┤")


#============ 解析 ===========
for idx, ch in enumerate(text):
    cp = ord(ch)

    display_char = REPLACE_MAP.get(ch, ch)
    is_special = ch in REPLACE_MAP
    is_control = cp in DESC_CONTROL

    if is_control:
        desc = DESC_CONTROL[cp]
        char_color = FLRed
        desc_color = FLRed
    else:
        try:
            desc = unicodedata.name(ch)
        except ValueError:
            desc = "<no name>"
        char_color = FLCyan if is_special else FLYellow
        desc_color = FGray

    hex_str = f"0x{cp:04X}" if cp <= 0xFFFF else f"0x{cp:06X}"
    desc_display = desc if len(desc) <= 32 else desc[:29] + "..."

    char_str = pad_to_width(display_char, 18)

    print(f"│ {FLGreen}{idx:>5}{CRst} │ {char_color}{char_str}{CRst} │ {FLBlue}{hex_str:<8}{CRst} │ {FLMagenta}{cp:>9}{CRst} │ {desc_color}{desc_display:<32}{CRst} │")


total = f"Total: {text_len} character(s)"
print(f"├───────┴────────────────────┴──────────┴───────────┴──────────────────────────────────┤")
print(f"│     {FLYellow}{total:<80}{CRst} │")
print(f"└──────────────────────────────────────────────────────────────────────────────────────┘\n")
