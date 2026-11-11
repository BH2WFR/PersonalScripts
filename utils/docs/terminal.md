# Console and interaction

[Utility index](../README.md)

Implementation: [console.py](../console.py), [input.py](../input.py), [menu.py](../menu.py), [menu_option.py](../menu_option.py), [cursor.py](../cursor.py), [cmd_check.py](../cmd_check.py), [ansi.py](../ansi.py).

## API reference

| Need | Use |
| --- | --- |
| Create a CLI parser with authored help | `Console.argument_parser(help_text) -> argparse.ArgumentParser`; pass the entry's top-level HELP, then add arguments and parse normally. -h/--help prints that text verbatim; validation, error usage and exit statuses retain argparse behavior |
| Print a box-drawing banner | `Console.print_banner("TITLE")` |
| Print a horizontal separator | `Console.print_separator(width=..., color_ansi_esc=...)` |
| Resolve an ANSI color constant name | `Console.resolve_ansi_color("FLYellow")` |
| Standard KeyboardInterrupt exit | `Console.print_keyboard_interrupt_message_and_exit()` |
| Standard exit message | `Console.print_exit_message_and_exit()` or `Console.print_error_and_exit()` |
| Terminal width / CJK display width | `Console.get_terminal_width()`, `Console.display_width(s)` |
| Detect interactive stdin (including Windows NUL) | `Console.has_interactive_input() -> bool` |
| Human-readable byte size | `Console.format_size(size_bytes, precision=1)` |
| Current time string | `Console.get_time_str()` |
| Print argv for debugging | `Console.print_argv_list()` |
| Set console to UTF-8 | `Console.set_locale_utf8()` |

## `Input` class — interactive prompts (static methods)

| Need | Use |
|---|---|
| General text or separated-list input | `Input.prompt(prompt, default=..., transform=..., separator=",", deduplicate=True)` |
| Parse an RGB color | `Input.parse_color(text) -> tuple[float, float, float]`; pure parser returning channels in [0, 1]. Accepts `R,G,B` (0-255), `#RGB`, `#RRGGBB`, and CSS-style `rgb()` with commas or spaces and numeric/percentage channels. Rejects malformed/out-of-range values, alpha, names and other color spaces with ValueError; numeric 1 means 1/255, not full intensity |
| Numeric input with validation | `Input.input_number(prompt, default=..., min_value=..., allow_float=...)` |
| Merge consecutive integers into ranges | `Input.merge_integer_ranges(values: Iterable[int]) -> tuple[tuple[int, int], ...]`; sorts and deduplicates any integer iterable, supports negatives and zero, returns inclusive endpoint pairs; singletons have equal endpoints; empty input returns () |
| Format integer ranges as text | `Input.format_integer_ranges(ranges: Iterable[tuple[int, int]]) -> str`; `((1, 3), (5, 5))` becomes `"1-3,5"`; preserves order, duplicates, and descending ranges; supports signed endpoints; empty input returns `""`; output uses parse_integer_ranges syntax |
| Parse arbitrary integer sequences | `Input.parse_integer_ranges(text, allow_zero=True, parity=None, allow_parity=True) -> tuple[int, ...]`; signed inclusive ascending/descending ranges; preserves order and duplicates; empty text returns (); False rejects zero even inside a range; accepts `\|odd` / `\|even` suffixes |
| Interactive integer sequences | `Input.input_integer_ranges(prompt, allow_zero=True, default=None, parity=None, allow_parity=True) -> tuple[int, ...] \| None`; retries invalid input; Enter returns None unless the default produces values; literal zero returns (0,) when allowed; accepts `\|odd` / `\|even` suffixes |
| Parse continuous real ranges | `Input.parse_real_ranges(text, allow_zero=True, allow_infinity=True) -> tuple[tuple[float, float], ...]`; accepts `13.5,14.5-15`, `-2.5--1`, `0-3`, scientific notation, and `-inf-inf`; returns inclusive lower/upper pairs without enumeration; reversals such as `1--1` normalize to (-1.0, 1.0); keeps interval order/duplicates, empty text returns (); zero policy includes interval interiors; infinity may bound intervals but cannot stand alone |
| Interactive real ranges | `Input.input_real_ranges(prompt, allow_zero=True, allow_infinity=True, default=None) -> tuple[tuple[float, float], ...] \| None`; same continuous-interval semantics; validates defaults before prompting, retries invalid input, Enter returns None without a nonempty default |
| Parse item numbers and inclusive ranges | `Input.parse_index_ranges(text, item_count=..., allow_zero=False, parity=None, allow_parity=True) -> tuple[int, ...]`; signed ranges, all/none and `\|odd` / `\|even` suffixes; negatives count from the end; returns sorted, unique zero-based indexes; empty text returns (); False uses one-based input, True uses zero-based input; reversed resolved ranges and out-of-range values raise ValueError |
| Interactive item/range selection | `Input.input_index_ranges(prompt, item_count=..., allow_zero=False, default=None, parity=None, allow_parity=True) -> tuple[int, ...] \| None`; same index parser and numbering modes; retries invalid input; Enter returns None unless the default produces values |
| Number + unit (e.g. `90deg`) | `Input.input_number_with_unit(prompt, ..., allowed_units=("deg","rad"))` |
| Password / masked input | `Input.input_password(prompt)` |
| Output path (auto collision avoidance) | `Input.resolve_output_path(default_path, prompt=..., path_type="file")` |
| Input path (existence validation) | `Input.resolve_input_path(default_path, ..., path_type="file")` |
| Multiple input paths (glob expand) | `Input.resolve_input_paths_multi(..., glob=True)` |
| Multi-line text from stdin | `Input.read_stdin_multiline(...)` |

The range APIs share internal `_parse_range_tokens()` for signed endpoint syntax
and generic `_input_ranges()` for default validation, blank input, and retries.
Integer/index parsers share `_range_parity()` for suffix validation and
`_filter_range_parity()` for filtering. `parity` accepts exported `RangeParity.ODD`,
`RangeParity.EVEN`, or None; `allow_parity=False` disables only textual suffixes.
One case-insensitive `|odd` / `|even` suffix must follow a selection and agree
with any explicit filter. Validate first, then filter integer values or resolved
item numbers in the selected numbering mode; real intervals are unchanged.
`_parse_integer_spans()` converts integer tokens for the integer/index parsers.
Integer sequences expand literal endpoints; index selections resolve endpoints
against the collection before expanding. Indexes never accept floating-point
values; `allow_zero=True` selects zero-based numbering (0 = first).
Real ranges return continuous float endpoint pairs, including optional infinite
bounds, without expanding or merging intervals. All parsers are pure; interactive
helpers validate defaults before prompting and propagate EOFError / KeyboardInterrupt.

Path resolution shares private implementation helpers inside `Input`:
`_normalize_path()` normalizes one path, `_prompt_and_normalize_path()` handles
the interactive single-path prompt, `_path_status()` checks existence and type,
`_describe_path_kind()` produces diagnostics, and `_select_path_action()` owns
the common action menu. These are internal composition points; scripts call the
public `resolve_input_path()`, `resolve_output_path()`, or
`resolve_input_paths_multi()` methods instead.

## `Menu` + `MenuOption` — interactive selection menus

```python
choice = Menu.select(
    [MenuOption(["1", "R"], "Do the thing", some_value),
     MenuOption(["2", "X"], "Exit", None)],
    prompt="Choice", required=True, default_key="1",
)
# Menu.from_enum(MyEnum) — builds MenuOption list from an enum.

choices = Menu.select(
    [MenuOption(["1", "A"], "First", first_value),
     MenuOption(["2", "B"], "Second", second_value)],
    allow_multiple=True, required=True,
)
# Input "1,2" returns [first_value, second_value].
```

`Menu.select(..., allow_multiple=False)` preserves the single-value API.
Option descriptions default to FLCyan (`default_desc_color`); prompts remain
FLYellow. An option's explicit `desc_color` overrides the fallback.
With `allow_multiple=True`, comma-separated keys return a list even for one
selection. Keys are case-insensitive; aliases of the same option are deduplicated
in input order. Blank input returns [] unless required=True or a default exists.
`default_key="1,2"` supplies a multi-selection default, validated before prompting.
An invalid item or empty comma-separated item retries the whole entry.
`accept_custom_string=True` accepts unmatched tokens as raw strings in the list,
deduplicating exact repeats. Exact keys take precedence over comma splitting.
Numeric ranges remain the caller's responsibility: use `Input.parse_index_ranges()`
when the returned strings represent item numbers/ranges. Action keys such as R/E
are ordinary options; callers decide whether mixing them with selections is valid.
The internal `multiple_values()` resolver inside `Menu.select()` shares parsing
and deduplication between defaults and entered multi-selections.

## `Cursor` class — ANSI cursor escapes (returns strings, does not print)

`Cursor.up()`, `Cursor.down()`, `Cursor.forward()`, `Cursor.back()`,
`Cursor.next_line()`, `Cursor.prev_line()`, `Cursor.column()`,
`Cursor.position()`, `Cursor.erase_display()`, `Cursor.erase_line()`,
`Cursor.scroll_up()`, and `Cursor.scroll_down()`.

## `CmdCheck` dataclass — command-in-PATH descriptor

```python
CmdCheck(cmd="ffmpeg", required=True, hints={"any": "brew install ffmpeg"})
# cmd can also be a list: ["yt-dlp", "yt-dlp.exe"] — first found wins
```

## Console colour — semantic conventions

Use the named ANSI constants from `utils`. Every colour segment **must** be
closed with `CRst`. Here is the semantic mapping — stick to these roles so
output stays consistent across scripts:

| Role | Colour | Example |
| --- | --- | --- |
| Prompt / question / emphasis | `FLYellow` | `f"{FLYellow}Choice > {CRst}"` |
| Success / OK / done | `FLGreen` | `f"{FLGreen}Done.{CRst}"` |
| Error / fatal | `FLRed` | `f"{FLRed}Error: file not found.{CRst}"` |
| Warning / caution (non-fatal) | `FLYellow` | `f"{FLYellow}Elevation unavailable.{CRst}"` |
| Secondary info / file paths / defaults | `FGray` | `f"{FGray}C:\\Users\\...{CRst}"` |
| Step marker / progress label | `FLCyan` | `f"  {FLCyan}[*]{CRst} Section 1"` |
| Banner / separator / section heading | `FLYellow` | `Console.print_banner("TITLE")` |
| Key hints in menus | `FLGreen` | `[Y]` inside bracket notation |
| Important / highlight (sparingly) | `FLCyan` | Highlighting a key value in output |

**Don't over-colour.** A wall of rainbow text is worse than no colour at all.
One colour per semantic role per line. When in doubt, err on the side of fewer
colors — the user should be able to scan output and instantly know what's a
prompt, what's an error, and what's informational.

## CLI conventions

Keep console text and prompts in English. Prefer f-strings and the shared ANSI
constants, resetting colored segments with `CRst`. Use `tqdm` for repeated work,
with useful totals/units; disable redraws outside interactive terminals and use
`tqdm.write()` for messages during a bar.

Handle CLI cancellation at the entry boundary with
`Console.print_keyboard_interrupt_message_and_exit()`, after any required cleanup.
Do not catch cancellation in a retry loop.

Check required external tools with `Environment.check_commands(*CmdCheck(...))`
before prompts or work. Missing hard dependencies should produce an actionable
install hint; optional dependencies are checked when their feature is selected.

Use `Input.input_password()` for masked password prompts and the existing Input
path/range helpers for interactive validation. Keep authored help in a top-level
`HELP` string: short functional introduction, Requirements and Usage. Separate
maintainer notes from that user-facing text. When editing a script, rewrite
excessive or nonconforming help; see [AGENTS.md](../../AGENTS.md).

The internal `_HelpArgumentParser` overrides only `format_help()`. Use the public
`Console.argument_parser(HELP)` factory rather than duplicating parser subclasses. Subparsers without authored
help retain native argparse help formatting.

`Console.set_locale_utf8()` runs the shared Windows code-page/locale setup and
prints a Unicode diagnostic line on all platforms. It is useful for encoding
diagnosis, not a silent initializer to add to every script.
