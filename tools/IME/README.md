# Rime dictionary tools

Run either tool without arguments for command-line interaction:

```text
conda run -n base python run-script.py rime-aux-code-generator
conda run -n base python run-script.py rime-userdict-to-dict
```

Both work on Windows, macOS and Linux, using PyYAML and tqdm from the project
requirements. `--help` works without either package. Inputs must be UTF-8;
outputs use UTF-8 without BOM and LF endings. Output paths are checked through
the shared path prompts, and inputs cannot be overwritten.

## Auxiliary codes

`rime-aux-code-generator.py` reads a Rime `.dict.yaml` or tab-separated
`text<TAB>code[<TAB>weight]` shape table. It writes `text=auxiliary-code` lines
in the format used by
[rime-lua-aux-code](https://github.com/HowcanoeWang/rime-lua-aux-code).
Each line contains one text/code pair; multiple codes for the same character
can occupy separate lines, which the project's Lua reader combines.

| Rule | `abc` | `a` |
| --- | --- | --- |
| First code | `a` | `a` |
| First/last, keep single | `ac` | `a` |
| First/last, repeat single | `ac` | `aa` |
| First/last, prefix single with `x` | `ac` | `xa` |

The prefix can be any one ASCII letter. Single-character filtering is enabled
by default, including supplementary Unicode characters. Optional phrases,
excluded code prefixes (for example `x,z,yyy` for the original Cangjie setup),
and a reference dictionary's single-character set are selectable. An empty
reference set matches nothing. Codes containing whitespace are excluded.
No Cangjie-specific exclusions are applied by default.

Rows follow original-code ordering. Identical output pairs are deduplicated;
distinct codes for the same character are preserved. Weights are ignored.
Rime headers and declared column order are handled, but `import_tables` are
not expanded: choose the actual table containing the characters.

## User dictionaries

`rime-userdict-to-dict.py` supports two text layouts:

```text
# Sync snapshot (*.userdb.txt):
ni hao <TAB>你好<TAB>c=12 d=1.5 t=100

# User dictionary text export or ordinary dictionary:
你好<TAB>ni hao<TAB>12
```

`<TAB>` denotes a real tab. Auto-detection recognizes snapshot metadata or the
`c=` field; explicit format selection is also available. Binary `.userdb`
directories, `.kct` and binary snapshots must first be exported or synchronized
to text in Rime. These layouts follow the original `loadSyncUserDB` and
`loadDictionary` methods and Rime's
[snapshot implementation](https://github.com/rime/librime/blob/master/src/rime/dict/user_db.cc)
and [export implementation](https://github.com/rime/librime/blob/master/src/rime/lever/user_dict_manager.cc).

Negative counts are excluded even when weights are omitted. Remaining weights
can be retained, multiplied by a finite non-negative factor (fractional results
truncate toward zero), or omitted. Zero weights produce two-column rows.
Duplicate text/code pairs retain the first non-deleted occurrence, matching the
original converter. Output sorts by code then text.

The generated `.dict.yaml` has a configurable name, `sort: by_weight`, explicit
columns, and `use_preset_vocabulary: false` so it contains only the converted
entries. Malformed rows are counted and skipped; invalid headers and empty
conversion results fail without creating an output.
