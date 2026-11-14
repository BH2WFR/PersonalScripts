# Rime text dictionaries

[Utility index](../README.md) · [Implementation](../rime.py)

Import `Rime`, `RimeEntry`, `RimeFormat` and `RimeReadResult` explicitly from
`utils.rime`. Importing the module needs only the standard library; reading
tables loads the already-declared PyYAML and tqdm dependencies lazily.

`Rime.read(path: Path, *, format=RimeFormat.AUTO, read_weights=True,
progress=False) -> RimeReadResult` reads UTF-8 text with or without a BOM.

- `DICT`: tab-separated text, code, optional integer weight. A `.dict.yaml`
  header may supply reordered `columns`; text and code are required.
- `USERDB`: tab-separated code, text, `c=<integer> d=... t=...`. Surrounding
  whitespace is trimmed while spaces within multi-syllable codes are preserved.
- `AUTO`: recognizes the snapshot comment `# Rime user dictionary` or a `c=`
  field in the first tab-separated data row; otherwise assumes `DICT`.
  Explicit selection resolves ambiguous/headerless files.

Blank lines, comments and YAML metadata are excluded. Missing text/code and bad
integer weights count as malformed rows. The result includes `entries`,
`invalid_rows`, and up to five `invalid_lines` (one-based). `read_weights=False`
ignores dictionary weight fields, including percentage weights, for auxiliary
code extraction. Negative weights remain available to the conversion policy.
`RimeEntry` is immutable and contains `text`, `code` and `weight` (default 0).

Invalid YAML headers, missing required columns, unterminated headers and NUL
bytes raise `ValueError`; filesystem and UTF-8 decoding errors propagate.
Binary database directories/files and imported subordinate dictionaries are
not read. Progress is in lines and disabled unless requested and stderr is a TTY.

`Rime.write_rows(path: Path, rows: Iterable[str], *, sources=(), overwrite=False)`
adds a newline per row and writes UTF-8 without BOM using LF endings. The parent
must exist. Source paths, symlinks and hard-link aliases cannot be overwritten.
An existing output raises `FileExistsError` unless replacement was authorized
with `overwrite=True`. A temporary sibling file is fully written before
replacement; errors and cancellation remove the temporary file and preserve the
previous destination. Without overwrite, an atomic hard link publishes the
file without replacing an output created concurrently (the filesystem must
support hard links).

The shared module owns text parsing, column interpretation and file writing.
Auxiliary extraction, filtering, deduplication, frequency scaling and CLI
prompts belong to the [IME tools](../../tools/IME/README.md). User settings and
configuration I/O continue to belong to `ConfigStore`.
