# Unicode text

[Utility index](../README.md)

Implementation: [unicode_text.py](../unicode_text.py).

| API | Behavior |
| --- | --- |
| `UnicodeText.statistics(text) -> TextStatistics` | Code-point count, UTF-8 and UTF-16 byte lengths, regex word count and line count |
| `UnicodeText.inspect(text) -> UnicodeReport` | Immutable original text, statistics and one `UnicodeCharacter` per code point |
| `UnicodeCharacter.columns() -> tuple[str, ...]` | Index, safe character label, U+ code, decimal value, UTF-8 bytes, category and name; column order is `UnicodeText.COLUMNS` |
| `TextStatistics.items()` | Stable English labels and numeric values for summaries |
| `UnicodeText.format_report(report) -> str` | Original text, statistics and tab-separated character rows |

Indexes start at zero. Characters mean Python Unicode code points, not grapheme
clusters: a combining sequence or joined emoji can span several rows. Unicode
names/categories come from the running Python's `unicodedata` database.

Input is never stripped or normalized. CRLF counts as one line separator; lone
CR and LF each count as one. Empty text has zero lines. UTF-16 counts bytes in
little-endian encoding without a BOM. Words follow `\w+(?:['\u2019]\w+)*`, retained
from the source inspector; this is not language-specific word segmentation.

Controls and known invisible characters use readable labels; other nonprintable
characters use escapes, and combining marks use a dotted circle. Display labels
never replace the report's original text. Lone surrogate code points are retained
for inspection, with `<invalid surrogate>` instead of UTF-8 bytes and `None` for
encoded byte totals. `style` provides semantic table tags, not ANSI escapes.

These helpers use only the standard library and perform no GUI, clipboard,
process or configuration access. The Tk interface and its native clipboard
operations belong to [unicode-inspector.py](../../tools/others/unicode-inspector.py).
Its inspector layout/lookup tables were adapted from the user's `text_actions.py`;
macOS-specific hooks and launch helpers are not dependencies of this project.

Verification: `test/test_unicode_text.py`, `test/test_unicode_inspector.py`.
