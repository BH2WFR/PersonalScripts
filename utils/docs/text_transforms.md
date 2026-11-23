# Path and text transformations

[Utility index](../README.md) · [Text Processor](../../tools/others/text-processor.py)

Import [path_text](../path_text.py) and [text_transforms](../text_transforms.py) explicitly. The modules operate on strings. The desktop interface owns the clipboard, operation selection and input/result chaining.

## Paths

Each path function accepts one line. Use `map_lines` to process a list and `transform_quoted_path` to keep surrounding quotes and whitespace during a conversion.

| Function | Behavior |
| --- | --- |
| `convert_separators` | Converts the chosen literal separator. `forward_path` accepts mixed single and escaped backslashes and preserves the UNC introducer. |
| `remove_quotes`, `add_quotes` | Remove matching outer pairs of allowed quotes after trimming for comparison, or apply a chosen pair once. Interior quotes are preserved. |
| `to_msys`, `from_msys` | Convert drive-absolute paths between `C:/work` and `/c/work`. The latter accepts an output separator. Only a complete one-letter mount component represents a drive. |
| `add_file_prefix`, `remove_file_prefix` | Encode/decode file URLs, including spaces, literal percent signs and UNC authorities. Drive paths use `file:///C:/…`. The tool uses `file://./` as its own reversible prefix for relative paths, without resolving them against the working directory. |
| `shorten_environment`, `expand_environment` | Shorten the longest matching whole directory prefix using cmd, Bash or PowerShell syntax. Expand a leading variable once using `Paths.expand_template`. Unknown references are preserved. |
| `home_path` | Convert among `~`, an absolute path and a shell variable. Windows cmd uses `%USERPROFILE%`, Windows PowerShell uses `$env:USERPROFILE`, and Bash uses `$HOME`. Absolute conversion resolves relative paths against the working directory. Only paths within the home directory can be shortened to its alias. |

Directory shortening considers `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `ProgramData`, `ProgramFiles`, `ProgramW6432`, `CommonProgramFiles`, `SystemRoot`, `windir`, `SystemDrive`, `PUBLIC`, `OneDrive`, `OneDriveConsumer`, `OneDriveCommercial`, `TEMP`, `TMP` and `HOME` when set. Prefix matching folds case for drive and UNC paths.

## Text

| Function | Behavior |
| --- | --- |
| `style_letters`, `plain_letters` | `style_letters` first restores mixed Unicode alphabets with `plain_letters`, then applies the selected style to ASCII letters and digits. The first entry in `LETTER_STYLES`, `Normal`, returns the restored text. Some styles share one glyph across cases or have no styled digit. Restoration uses the case represented by the glyph. |
| `to_halfwidth`, `to_fullwidth` | Convert Unicode width variants, including ASCII punctuation, ideographic space and voiced katakana. |
| `expand_ligatures`, `normalize_spaces` | Expand Latin presentation ligatures FB00–FB06, or replace each Unicode space separator with one ordinary space. |
| `clean_pdf` | Join soft line wraps, remove trailing control marks, expand ligatures and normalize spaces. A period, including a Chinese full stop, ends a paragraph. CJK line joins need no extra space. |
| `map_lines`, `remove_blank_lines` | Apply a callable to each nonempty line or delete whitespace-only lines. Preserve the original CR, LF or CRLF terminators of retained lines. |
| `expand_tabs` | Convert tabs to the specified tab stops on a single line, accounting for wide characters. |
| `title_words` | Apply Unicode title case to the first letter of each word. Combining accents and internal apostrophes stay within the word. |
| `url_hostname` | Extract one hostname per URL, including subdomains and IPv6 addresses. Preserve unrecognized lines. |
