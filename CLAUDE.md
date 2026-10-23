# CLAUDE.md

> **Context-compression guard**: if the visible context contains a summary,
> compressed-context marker, or you are unsure whether project rules are still
> loaded, re-read this file from
> `D:\Projects\Python_Projects\PersonalScripts\CLAUDE.md` (Windows) or
> the equivalent path on the current platform **before running project commands
> or editing files**. Without this rulebook you will make wrong assumptions
> about conventions, utilities, and environment.

A personal cross-platform Python script toolkit. This file is the
authoritative coding standard for the project — Claude Code loads it
automatically as a project prompt.

GitHub: https://github.com/BH2WFR/PersonalScripts

## Agent workflow

Project-specific reminders:

- Reply in the user's language.
- Before editing code, read the surrounding file and follow the local style.
- Keep edits scoped to the requested script or shared utility.
- After behavioural code changes, run the smallest relevant check available:
  `--help`, a launcher dry-run, an import check, or a script-specific test.
- Do not run status-only shell commands such as `echo "done"`; report status in
  the reply.

## Environment

### Project-specific environment variables

- All project-specific environment variables must start with `ZL_`.
  Standard system and third-party variables retain their original names.
- Whenever a script adds, uses, renames, or changes a project-specific
  environment variable, document it in the repository-root
  `Environmental_Variables.md` in the same change. Include the variable name,
  owning script, purpose, whether it is required, and relevant value format,
  defaults, and precedence. Identify internal-only variables as such.
- Keep code, help text, configuration samples, and this registry consistent.
  Use placeholder values in documentation, never real credentials or private
  machine-specific paths.

### Python — CRITICAL: conda first, never system Python

- **Whenever Python is needed, use conda / Anaconda Python.** System Python on
  Windows points to the Microsoft Store stub and doesn't exist; on macOS it's
  ancient 3.9. **Never run bare `python` or `python3` — always locate the
  conda install first.**
- Lookup order — try each in sequence until one works:
  1. **`conda run -n base python <script>`** — if `conda` is in PATH, this is
     the simplest and most portable method.  No need to know where Python is
     installed; conda resolves it automatically.

     Keep-alive / retry note: after running a conda command, occasionally the
     first invocation fails with a PATH or DLL resolution error.  If that
     happens, retry once — the second run usually succeeds.

  2. **Find conda via `shutil.which("conda")`, `Get-Command conda`, or
     `command -v conda`**, then run `conda info --base` to locate the base
     environment. Derive Python from that base path:
     - Windows: `<base>\python.exe`
     - macOS / Linux: `<base>/bin/python`
  3. **Check common install paths** (see below) — only fall back to these if
     `conda` itself cannot be found on PATH.
  4. **System Python** — **last resort, ask me first.**  Windows system Python
     is a Microsoft Store stub that doesn't work; macOS system Python is
     ancient 3.9.  Do not silently fall back to these.
- Common conda install paths (for fallback #3 only):
  - Windows: `~/miniconda3/python.exe`, `C:\ProgramData\miniconda3\python.exe`,
    `~/anaconda3/python.exe`, `C:\ProgramData\anaconda3\python.exe`
  - macOS: `~/miniconda3/bin/python`, `~/anaconda3/bin/python`,
    `/opt/miniconda3/bin/python`, `/opt/anaconda3/bin/python`
  - Linux: `~/miniconda3/bin/python`, `~/anaconda3/bin/python`,
    `/opt/miniconda3/bin/python`, `/opt/anaconda3/bin/python`
- `Environment.find_conda()` already does the project-specific conda search — prefer
  it over a manual search inside project scripts.
- Default environment is **`base`**. Install packages into it with `pip`.
- Target **Python 3.13+**. Use modern syntax freely.

### Shells

- **Windows** — prefer **PowerShell** (pwsh or powershell.exe) over cmd.exe for
  running commands. Bash is also available via Git Bash.  To find it:
  1. Check for `bash` on PATH (Git Bash may register it).
  2. Run `where git` (cmd) or `(Get-Command git).Source` (PowerShell) to find
     the git executable, then derive the bash path from the same directory:
     `<git_dir>\..\bin\bash.exe` (e.g. `C:\Program Files\Git\cmd\git.exe` →
     `C:\Program Files\Git\bin\bash.exe`).
  3. Check common install locations: `C:\Program Files\Git\bin\bash.exe`,
     `C:\Program Files (x86)\Git\bin\bash.exe`.
  4. `Environment.find_bash()` already does this search — prefer it over a manual hunt.
- **macOS / Linux** — bash is the primary shell, but pwsh can be installed.
- Scripts should be runnable on at least one platform; **cross-platform is
  preferred** unless the task is inherently OS-specific.

### Windows version

**Windows 10+ only.** There is no need to maintain compatibility with Windows 7,
8, or 8.1. Use modern APIs (e.g. `SetProcessDpiAwarenessContext` for
Per-Monitor-V2 DPI, `PackageManager` APIs for winget, etc.) without legacy
fallbacks.

### Package managers

| Platform | Package manager |
|---|---|
| Windows | `scoop` and `winget` |
| macOS | `brew` |

Use the platform-appropriate package manager when suggesting external tool
installations.

### Installed system tools (all platforms)

These tools are expected to be present on my machines.  If a task needs one of
them and it cannot be found, **pause and tell me** to install it manually with
the appropriate package manager — do not install it yourself.

| Category | Tools |
|---|---|
| Download / network | `aria2c`, `wget`, `curl`, `git` |
| Archive | `7z` (7-Zip) |
| Media | `ffmpeg` |
| Cloud | `rclone` |
| Build | `ninja`, `cmake`, `make` |
| Crypto / TLS | `openssl` |
| Runtimes | `node` (Node.js), `deno`, `lua`, `conda`, `java` |
| Mobile | `adb` (Android Debug Bridge) |
| Editors | `nano` (preferred over `vim`) |
| Stats / data | `tokei`, `cloc`, `sqlite3` (SQLite CLI) |
| Documents | `ghostscript` (gs) |
| **Windows only** | `gsudo`, `upx`, `nssm` |
| **macOS only** | `ncdu` |

### Launcher

`run-script.py` is the unified entry point. Use it to list or launch other
scripts in the project:

Launcher settings come from `launcher-config.yaml`. An optional Gitignored
`launcher-config.patch.yaml` deep-merges personal overrides when present.

```bash
conda run -n base python run-script.py                # interactive list
conda run -n base python run-script.py --list         # list scripts and exit
conda run -n base python run-script.py <name>         # recursive basename match
```

### Plan before implementing

For new features, broad refactors, dependency changes, public API changes, or
edits touching multiple files, **propose the plan first** and wait for my
approval before writing any code. For small bug fixes, typo fixes, formatting
fixes, or clearly requested local edits, proceed directly. The plan should
cover:

- What files will be created / modified.
- The approach (algorithm, architecture, libraries).
- Any new dependencies or changes to existing APIs.
- Trade-offs or alternatives considered.

I'll confirm or adjust the plan before you start implementing.

### File encoding

- **All text files must be UTF-8 without BOM** unless I explicitly ask otherwise.
- **Line endings** — keep the existing LF / CRLF style of each file unchanged.
  - Exception: new cross-platform code defaults to **LF**.  New Windows-only
    scripts under `tools/windows/` may use CRLF.
- **Windows console encoding** — if console output shows garbled characters,
  use `chcp 65001` (UTF-8 codepage) and set the locale to `en-US.UTF-8` via
  `Console.set_locale_utf8()`.  Prefer Unicode / UTF-8 APIs over ANSI / GBK
  everywhere.
- **Windows path encoding** — always use Unicode paths; never encode paths as
  GBK / ANSI.  Python's `os.fsencode` / surrogate-escaping handles this
  correctly on Windows when using modern Python (3.6+).

### Project safety

The shared prompt contains the full rules for installs, git safety, recursive
delete/move operations, scope control, failure reporting, and secrets.

Project-specific reminders:

- This repository is public. Never add real credentials, private hostnames,
  account-specific paths, or machine-specific secrets to scripts, docs, or
  examples.
- Do not install Python packages or system tools without explicit approval.
- Keep edits narrowly scoped to the requested script, the relevant `utils/` module, or
  the relevant README entries.
- If a change touches `utils`, also update the quick-reference table below.

## Running scripts

### Via the launcher

```bash
conda run -n base python run-script.py <name> [args...]
```

The launcher discovers scripts by walking the project tree. It auto-hides:

- Platform-mismatched subdirectories (`windows/` on non-Windows, etc.)
- Shell scripts when the required interpreter is missing
- Files starting with `_`

### Requirements for a script to work with the launcher

1. **`.py` scripts** — must define a `main() -> int` function. The launcher calls
   `main()` with `sys.argv` set to `[script_path] + args`.
2. **`.sh` / `.ps1` scripts** — no special requirement; the launcher runs them
   as subprocesses.

### Direct invocation

```bash
conda run -n base python path/to/script.py [args...]
```

Prefer the launcher for interactive exploration, direct invocation for
development / debugging.

## Shared utility library — `utils/`

**Every script in this project imports `utils`.** For scripts in a category
directory such as `tools/filesystem/`, the canonical import block is:

```python
import os
import sys
# ... other stdlib imports ...

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402
```

Scripts directly under `tools/` use one `".."` component instead of two.

This makes ALL names from `utils` available: ANSI color constants (`FRed`,
`FLGreen`, `CRst`, …), responsibility classes (`Console`, `Environment`,
`System`, `Paths`), interactive classes (`Input`, `Menu`, `MenuOption`,
`Cursor`), `CmdCheck`, and any new additions. Scripts never import from utils
piecemeal. The former catch-all `Utils` class no longer exists.

### Utility package structure

Each shared class has one canonical module. Cross-cutting helpers are divided
by responsibility into `console.py`, `environment.py`, `system.py`, and
`paths.py`; `system.py` also owns macOS TCC permission checks and requests.
Interactive helpers live in `input.py`, `cursor.py`, `menu_option.py`, and
`menu.py`, while `CmdCheck` lives in `cmd_check.py`. ANSI color, style, cursor,
and screen-control constants live in `ansi.py`. `utils/__init__.py` re-exports
the public classes and ANSI constants.

`system.py` owns the internal `_disk_*` native-query and parser helpers shared
by disk inspection and volume-backed synchronization. `DiskInfo`/`DiskScan`
retain unknown metadata and partial-scan warnings; callers deciding whether to
write to a volume must validate completeness and current mount identity.

If a group of utilities is **domain-specific** (e.g. image processing, network
tools, PDF helpers), it should become a new file under `utils/` (e.g.
`pdf.py`, `image.py`). **Stop and ask before creating another
sub-module** — I (the project owner) will confirm the split.

### When to use the wheel — ALWAYS

Before writing anything, check the relevant class module under `utils/`.
Canonical implementations live there; do not add implementations to the
`__init__.py` compatibility facade or duplicate them in individual scripts.

#### Responsibility classes — static methods

| Need | Use |
|---|---|
| Admin / root detection | `System.is_elevated() -> bool` |
| Re-execute as admin (force) | `System.restart_elevated()` — supports source/bundled apps and paths containing spaces; gsudo uses a Windows PowerShell bootstrap |
| Re-execute as admin (soft, can fallback) | `System.try_restart_elevated() -> bool` — never re-runs after a helper starts |
| Check if a CLI tool is in PATH | `Environment.check_commands(*CmdCheck)` or `Environment.which(name)` |
| OS name / arch / hostname / Linux GUI | `System.get_os_name()`, `System.get_arch()`, `System.get_computer_name()`, `System.get_linux_gui() -> LinuxGui \| None` |
| Native disk inventory | `System.scan_disks() -> DiskScan`; returns `DiskInfo` trees with mounts, labels, filesystems, native IDs, platform details, and partial-query warnings. Windows uses PowerShell 7 Storage/CIM; Linux uses lsblk; macOS uses diskutil. Read-only, never mounts/elevates. Each query times out after 60 seconds. |
| Print a box-drawing banner | `Console.print_banner("TITLE")` |
| Print a horizontal separator | `Console.print_separator(width=..., color_ansi_esc=...)` |
| Resolve an ANSI color constant name | `Console.resolve_ansi_color("FLYellow")` |
| Print env info (conda, python, shell) | `Environment.print_env_info(probe_versions=...)`; disabling probes avoids starting external tools; Python gets a yellow Conda tag only for an actual Conda interpreter, otherwise Conda details are hidden |
| Standard KeyboardInterrupt exit | `Console.print_keyboard_interrupt_message_and_exit()` |
| Standard exit message | `Console.print_exit_message_and_exit()` or `Console.print_error_and_exit()` |
| Desktop notification | `System.notify(title, body)` |
| Open a file in the default app | `System.open_with_default_app(path)` |
| Open a URL safely (headless-safe) | `System.open_browser_safe(url)` |
| Resolve `$VAR` / `{{placeholders}}` in paths | `Paths.resolve_vars(path, schema_dir=..., script_dir=...)` |
| Open a PDF for processing | `with Pdf.open_document(path, password=None, interactive=True) as (document, password): ...`; all PDF tools use this authenticated context manager for input files; closes on success, failure, or cancellation; reuse the returned password with `interactive=False` for secondary/background readers |
| Authenticate an already open PDF | `Pdf.unlock(document, password=None, interactive=True) -> str`; validates PDF input, silently handles empty-password protection, tries a supplied password, otherwise prompts privately with retry and cancellation; False raises instead of prompting; does not recover a password from an already authenticated document |
| Detect PDF/A identification | `Pdf.has_pdfa_identification(document) -> bool`; read-only check for XMP identification elements/attributes, independent of encryption; namespace declarations alone do not count; malformed PDF/A XMP raises ValueError; does not validate PDF/A conformance |
| Save a new ordinary PDF | `Pdf.save_new(document, output_path, compact=True) -> None`; always removes encryption and PDF/A identification from XMP, including for unencrypted input, while retaining other metadata; exclusive output creation, removes its partial output on failure, drops unused objects; use `compact=False` for continued editing/repeated saves to preserve live object references; PyMuPDF is imported lazily in `utils/pdf.py` |
| Read effective PDF page labels | `Pdf.read_page_labels(document) -> list[str]`; preserves blank labels, falls back to physical page numbers when no label rules exist |
| Discover installed font files | `Font.system_font_paths() -> list[Path]`; sorted unique absolute TTF/OTF/TTC/OTC paths from Windows registry/directories, macOS directories, or Linux fontconfig/directories; `Font.FILE_SUFFIXES` contains supported suffixes |
| Read font names and styles | `Font.read_faces(path: Path) -> list[FontFace]`; collection order, canonical name, family, all readable aliases, full_names/family_names classified by name-table role and language, and `FontStyle` regular/bold/italic/bold-italic; imports fonttools lazily |
| Build a font catalog | `Font.read_catalog(paths: Sequence[Path], show_progress=False) -> list[FontFace]`; sorts by family/style/name, skips unreadable files with an aggregate warning; True shows a tqdm bar on interactive stderr; fonttools and tqdm are imported lazily |
| Search font names and aliases | `Font.search_faces(faces, query) -> list[FontFace]`; case-insensitive substrings across canonical/family/localized names, all whitespace-separated terms must match, blank query returns all faces in input order |
| Match a font family's styles | `Font.family_faces(base, catalog) -> dict[FontStyle, FontFace]`; selected face wins its own style, other styles prefer nearby files, unavailable styles are omitted |
| Format a font face label | `FontFace.label() -> str`; canonical name uses FLCyan, full names use the terminal default color, family names use FGray, localized aliases use FLGreen, slash separators are uncolored, and style uses FGray; returns text without printing |
| Set literal PDF page labels | `Pdf.write_page_labels(document, labels: Sequence[str]) -> None`; requires one string per page, empty strings mean blank labels; changes memory only and retains page content/bookmarks |
| Resolve a path against an explicit base directory | `Paths.resolve_path(path, base_dir, expand_environment=True, resolve_symlinks=False) -> str`; native variable expansion preserves undefined references, False avoids re-expanding literal/template results |
| Resolve and deduplicate existing directories | `Paths.resolve_directories(paths, base_dir, on_missing=None) -> tuple[str, ...]`; first occurrence wins, optional callback reports each distinct missing directory once |
| DPI awareness (Windows) | `System.enable_dpi_awareness()` |
| Find bash / pwsh / conda | `Environment.find_bash()`, `Environment.find_pwsh()`, `Environment.find_conda()` |
| Discover a strict runtime and verify its version | `Environment.resolve_runtime(RuntimeKind, executable=..., environment=..., cwd=...) -> tuple[str, str]`; `runtime_candidates(kind, environment, cwd=...)` discovers paths without probes; relative PATH uses cwd, launch paths preserve symlinks |
| Find a program using a child environment | `Environment.which(name, environment=..., cwd=...) -> str \| None`; explicit PATH/PATHEXT search relative to cwd, absolute result preserves symlinks; no options retains native shutil.which behavior |
| Expand templates using an explicit environment | `Paths.expand_template(text, environment, placeholders)`; one pass, undefined references are errors |
| Resolve dependent child environment values | `Paths.resolve_environment(inherited, overrides, literals, placeholders)`; cycles rejected, literal inputs win, self-reference reads inherited value |
| Conda environment name | `Environment.get_conda_env() -> Optional[str]`; checks current `sys.prefix/conda-meta`, not activation variables or path keywords; frozen apps return None; base is identified by its Conda package record, other prefixes use directory names |
| Actual running or selected Python | `Environment.get_python_environment(executable=None, timeout=15) -> PythonEnvironment`; immutable executable, prefix, version, frozen status and optional Conda label. No argument describes the current process without probes; an explicit executable is inspected in an isolated subprocess and invalid results raise ValueError. Prefix, not name, is the authoritative identity. Frozen executable paths are applications, not reusable Python interpreters |
| Interactive Python selection | `Environment.select_python_environment() -> tuple[PythonEnvironment, str \| None] \| None`; shared Windows/macOS current/custom-Conda/custom-Python menu. Validates the chosen installation and interpreter, returns identity plus optional Conda executable, retries invalid choices, and returns None on exit. Internal choice enums keep both menus identical |
| Native Conda launcher | `Environment.find_conda_executable(prefix=None) -> str \| None`; current or supplied prefix locations, then `CONDA_EXE` and PATH; resolves Windows batch wrappers to `Scripts/conda.exe`, searches `bin/conda` and `condabin/conda` on macOS/Linux and checks executability; discovery never classifies the running interpreter |
| Resolve a named Conda environment's Python | `Environment.resolve_conda_python(env_name, timeout=15, conda_executable=None) -> str`; current-environment fast path, otherwise Conda JSON discovery with ambiguity/existence checks. An explicit Conda executable bypasses the fast path and queries only that installation; resolves only, does not activate |
| Prepend literal directories to this process's PATH | `Environment.prepend_path(paths)`; preserves order and the previous PATH, no expansion/deduplication, no trailing empty entry for unset/empty PATH |
| Terminal width / CJK display width | `Console.get_terminal_width()`, `Console.display_width(s)` |
| Detect interactive stdin (including Windows NUL) | `Console.has_interactive_input() -> bool` |
| Human-readable byte size | `Console.format_size(size_bytes, precision=1)` |
| Headless detection | `System.is_headless()` |
| macOS Accessibility permission | `System.check_macos_accessibility_permission(prompt=...)` |
| macOS Screen Recording permission | `System.check_macos_screen_recording_permission(request=...)` |
| Ensure required macOS permissions | `System.ensure_macos_permissions(accessibility=..., screen_recording=...)` |
| Wait for macOS direct-capture approval | `System.wait_for_macos_screen_capture_approval(capture_probe)` |
| Current time string | `Console.get_time_str()` |
| Print argv for debugging | `Console.print_argv_list()` |
| Set console to UTF-8 | `Console.set_locale_utf8()` |

#### `Input` class — interactive prompts (static methods)

| Need | Use |
|---|---|
| General text or separated-list input | `Input.prompt(prompt, default=..., transform=..., separator=",", deduplicate=True)` |
| Numeric input with validation | `Input.input_number(prompt, default=..., min_value=..., allow_float=...)` |
| Merge consecutive integers into ranges | `Input.merge_integer_ranges(values: Iterable[int]) -> tuple[tuple[int, int], ...]`; sorts and deduplicates any integer iterable, supports negatives and zero, returns inclusive endpoint pairs; singletons have equal endpoints; empty input returns () |
| Format integer ranges as text | `Input.format_integer_ranges(ranges: Iterable[tuple[int, int]]) -> str`; `((1, 3), (5, 5))` becomes `"1-3,5"`; preserves order, duplicates, and descending ranges; supports signed endpoints; empty input returns `""`; output uses parse_integer_ranges syntax |
| Parse arbitrary integer sequences | `Input.parse_integer_ranges(text, allow_zero=True) -> tuple[int, ...]`; signed integers and inclusive ascending/descending ranges; preserves order and duplicates; empty text returns (); False rejects zero even inside a range |
| Interactive integer sequences | `Input.input_integer_ranges(prompt, allow_zero=True, default=None) -> tuple[int, ...] \| None`; retries invalid input; Enter returns None unless a nonempty expression is supplied as the default; literal zero returns (0,) when allowed |
| Parse continuous real ranges | `Input.parse_real_ranges(text, allow_zero=True, allow_infinity=True) -> tuple[tuple[float, float], ...]`; accepts `13.5,14.5-15`, `-2.5--1`, `0-3`, scientific notation, and `-inf-inf`; returns inclusive lower/upper pairs without enumeration; reversals such as `1--1` normalize to (-1.0, 1.0); keeps interval order/duplicates, empty text returns (); zero policy includes interval interiors; infinity may bound intervals but cannot stand alone |
| Interactive real ranges | `Input.input_real_ranges(prompt, allow_zero=True, allow_infinity=True, default=None) -> tuple[tuple[float, float], ...] \| None`; same continuous-interval semantics; validates defaults before prompting, retries invalid input, Enter returns None without a nonempty default |
| Parse item numbers and inclusive ranges | `Input.parse_index_ranges(text, item_count=..., allow_zero=False) -> tuple[int, ...]`; accepts `1,2`, `1-3,4`, `-1,-2`, and `-3--1`; negatives count from the end; returns sorted, unique zero-based indexes; empty text returns (); False uses one-based input, True switches to zero-based input; reversed resolved ranges and out-of-range values raise ValueError |
| Interactive item/range selection | `Input.input_index_ranges(prompt, item_count=..., allow_zero=False, default=None) -> tuple[int, ...] \| None`; same index parser and numbering modes; retries invalid input; Enter returns None unless a nonempty expression is supplied as the default |
| Number + unit (e.g. `90deg`) | `Input.input_number_with_unit(prompt, ..., allowed_units=("deg","rad"))` |
| Password / masked input | `Input.input_password(prompt)` |
| Output path (auto collision avoidance) | `Input.resolve_output_path(default_path, prompt=..., path_type="file")` |
| Input path (existence validation) | `Input.resolve_input_path(default_path, ..., path_type="file")` |
| Multiple input paths (glob expand) | `Input.resolve_input_paths_multi(..., glob=True)` |
| Multi-line text from stdin | `Input.read_stdin_multiline(...)` |

The range APIs share internal `_parse_range_tokens()` for signed endpoint syntax
and generic `_input_ranges()` for default validation, blank input, and retries.
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

#### `Menu` + `MenuOption` — interactive selection menus

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

#### `Cursor` class — ANSI cursor escapes (returns strings, does not print)

`Cursor.up()`, `Cursor.down()`, `Cursor.forward()`, `Cursor.back()`,
`Cursor.next_line()`, `Cursor.prev_line()`, `Cursor.column()`,
`Cursor.position()`, `Cursor.erase_display()`, `Cursor.erase_line()`,
`Cursor.scroll_up()`, and `Cursor.scroll_down()`.

#### `CmdCheck` dataclass — command-in-PATH descriptor

```python
CmdCheck(cmd="ffmpeg", required=True, hints={"any": "brew install ffmpeg"})
# cmd can also be a list: ["yt-dlp", "yt-dlp.exe"] — first found wins
```

### Console colour — semantic conventions

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

### When to add a function to `utils`

If a piece of logic looks like it could be useful in **more than one script**
(interactive prompts, platform detection, path helpers, formatting, etc.),
extract it into the relevant class module under `utils/` rather than duplicating
it. Add a new `@staticmethod` to `Console`, `Environment`, `System`, `Paths`,
`Input`, or another appropriate class following the existing patterns. This is
encouraged — `utils` is meant to grow.

### Reuse is mandatory

Before adding a script-local private helper, search both `utils/` and the whole
repository for equivalent or substantially similar behavior. Reuse or extend
the existing implementation whenever possible.

- Do **not** maintain multiple private functions that perform the same or
  nearly the same task in different scripts. Move the shared behavior into the
  appropriate class under `utils/` and migrate every duplicate caller.
- Do **not** leave large repeated code blocks in two or more functions. Extract
  their common normalization, validation, formatting, prompting, or platform
  handling into one appropriately scoped helper.
- A script-local private function is appropriate only when its behavior is
  genuinely specific to that script and is not already represented elsewhere.
- When discovering an existing duplicate during unrelated work, remove the
  duplicate within the authorized scope instead of adding another variation.

Code review should treat avoidable duplicate helpers or substantial duplicated
function bodies as a design defect, not merely a style preference.

**Every new or expanded public `utils` function must update this `CLAUDE.md` in
the same change.** Add or revise its quick-reference entry with a short purpose,
the canonical call, important optional parameters, and any non-obvious return
behavior. A utility change is incomplete until this documentation is current;
otherwise later work may miss the API and re-implement it.

New private helpers under `utils` must also receive a short architectural note
when they coordinate shared behavior or define an important reuse boundary.
Mark them as internal so scripts do not treat them as public API. Trivial local
implementation details do not need individual quick-reference rows.

`utils/pdf.py` uses an internal `_OutputStream` adapter without a filename so
PyMuPDF writes through the exclusively opened handle instead of reopening it.
Scripts use `Pdf.save_new()` and never construct this adapter themselves.
All tools that open an existing PDF use `Pdf.open_document()`; generated in-memory
page buffers and new empty documents may use PyMuPDF directly. Passwords stay in
memory and are never passed to external command lines. Ghostscript compression
stages an unprotected input in its temporary directory and publishes the validated
result through `Pdf.save_new()`. All saved PDFs omit encryption, permission
restrictions, and PDF/A identification; existing files are never overwritten.
Internal `_process_pdfa_identification()` shares namespace-aware detection/removal
between `has_pdfa_identification()` and `save_new()`, retaining unrelated XMP.
`pdf-decrypt.py` also accepts PDF/A-only input with an ordinary informational
message. If neither encryption/protection nor PDF/A identification is present,
it warns and offers another input or exit before requesting an output path.
Page-label helpers decode the PDF number tree and encode literal prefixes through
PyMuPDF's PDF-string encoder, preserving Unicode, escapes, and blank labels.

`Environment._conda_environment_name` is the internal metadata classifier shared
by current-process identity and external Python probes. Scripts use the public
environment methods rather than duplicating this classification.

`utils/font.py` scopes its internal `_quiet_font_timestamps()` logging filter to
font metadata reads. It suppresses only fontTools' automatically corrected legacy
created/modified timestamp warning, leaves other diagnostics visible, and always
removes the filter afterward. Font files are never rewritten to silence warnings.

### When a `utils` function is almost right but not quite

**Stop and ask me.** Do not fork the utility into a script-local copy. Either:

- Extend the existing `utils` function with an optional parameter
  (backward-compatible), or
- Write a new `@staticmethod` that wraps or composes the existing one.

I'll decide whether to modify utils or handle it differently.

## Code style

### PDF processing — required for every PDF tool

- Open existing inputs through `Pdf.open_document()` as a context manager.
  Do not duplicate open/password prompts in individual scripts. New empty
  documents and in-memory generated page buffers may use PyMuPDF directly.
- Use the shared authentication flow: empty-password protection is handled
  automatically; otherwise try the supplied password, then privately prompt
  with retry/cancellation. Use `Pdf.unlock()` for an already open document.
  Reuse the returned password with `interactive=False` for secondary readers;
  never place passwords on external command lines.
- Save final output through `Pdf.save_new()`. Output must be decrypted and
  editable without password or permission restrictions. Remove PDF/A
  identification even when input is not encrypted, retaining unrelated metadata.
  Never reapply the source encryption, restrictions, or PDF/A identification.
- Preserve the source and never overwrite an existing output. Use the shared
  save function's exclusive creation and partial-output cleanup.

### Progress output — all scripts

- Prefer `tqdm` for progress through pages, files, or other repeated work.
  Do not print a new status line per item unless it conveys necessary information.
- Use meaningful stage labels, totals, and units where available. Avoid terminal
  redraw sequences in redirected output; disable bars outside interactive terminals.
- Keep prompts, actionable warnings/errors, and the final result visible. When
  a message must appear during an active bar, use `tqdm.write()` to avoid breaking it.

### GUI framework and theme

- Use **PySide6** for GUI programs in this project.
- Use the **Fusion** theme on every platform. After creating or obtaining the
  `QApplication`, call `application.setStyle("Fusion")` before creating windows
  or widgets, including when reusing an existing application instance.

### File header — module docstring on every script

After `#!/usr/bin/env python3`, every `.py` file must have a **module-level
docstring** that serves as the file header. It covers:

1. **What** — one-line summary, then details (purpose, workflow, use case).
2. **Requirements** — every **hard** dependency (pip package, external CLI tool)
   that the script cannot function without.  Optional / fallback dependencies
   may be noted but should be clearly labelled as optional.
3. **Usage** — one or two example invocations so the reader immediately knows
   how to run it.

```python
#!/usr/bin/env python3
"""One-line summary of what this script does.

Detailed description of the workflow, scope, and any platform-specific
behaviour.  Keep it concise but complete — someone reading this should
understand the script's purpose without opening the rest of the file.

Requirements:
    - pip: opencv-python, numpy
    - system: ffmpeg (for audio extraction; optional — script falls back to
      silent mode without it)

Usage:
    python script.py
    python script.py --output ./generated/
"""
```

The module docstring and the `--help` output share overlapping content (what
the script does, what it depends on, how to run it).  When you change one,
**update the other as well** so they don't drift apart.

### Dependency check — validate hard requirements at startup

If a script has **hard** third-party dependencies (Python packages or system
tools it cannot function without), the check must happen **early** in `main()`,
before any interactive prompts or heavy lifting:

**Python packages** — guard the import with a `try/except` that prints the
install command and exits:

```python
try:
    import cv2
    import numpy as np
except ImportError as e:
    print(f"{FLRed}ERROR: Missing dependency: {e.name}{CRst}")
    print(f"  Install with: {FGray}pip install opencv-python numpy{CRst}")
    sys.exit(1)
```

**System tools** — use `Environment.check_commands()` with `CmdCheck` entries.  This
prints per-platform install hints for missing tools and returns `False` when a
required tool is absent:

```python
if not Environment.check_commands(
    CmdCheck("ffmpeg", required=True, hints={
        "windows": f"  {FGray}scoop install ffmpeg{CRst}",
        "macos":   f"  {FGray}brew install ffmpeg{CRst}",
        "linux":   f"  {FGray}sudo apt install ffmpeg{CRst}",
        "any":     f"  {FGray}https://ffmpeg.org/download.html{CRst}",
    }),
):
    Console.print_error_and_exit("Missing required dependencies.")
```

Place these checks right after the banner in `main()`, grouped in a
`# ── dependency checks ──` section.  Do **not** check for optional/fallback
tools at startup — detect their absence later and gracefully degrade.

### `main() -> int` skeleton — every `.py` script follows this

```python
#!/usr/bin/env python3
"""One-line description of what this script does.

Requirements:
    - pip: somepackage

Usage:
    python script.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402


def main() -> int:
    # ── help text ──────────────────────────────────────────
    if "--help" in sys.argv or "-h" in sys.argv:
        # print formatted help text (FLYellow title + FGray body)
        # must list: description, usage, all CLI flags, dependencies
        return 0

    Console.print_banner("SCRIPT TITLE")

    # ── dependency checks ──────────────────────────────────
    # validate hard dependencies here (pip imports / system tools)

    # ── elevation check (if needed) ──
    if not System.is_elevated():
        ...

    # ... logic ...

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
```

Exceptions:

- GUI / hook scripts that run forever may use `main() -> None`.
- Older scripts may not follow this exactly — update them toward this pattern
  when touching them.

### `--help` output — what it must contain

Every script's `--help` output must include each of these sections:

1. **Title** — `FLYellow` script name, centred.
2. **Usage** — one or more `python <script> [options]` lines.
3. **Description** — what the script does in plain English.
4. **Options** — every CLI flag / argument with a short explanation.
5. **Requirements** — hard dependencies (pip packages, system tools, platform).
   If a dependency is optional, label it `(optional)`.

For simple scripts (≤3 flags), print `--help` manually as a triple-quoted
f-string (the existing project convention).  For complex scripts with many
arguments, use **`argparse`** — but ensure the output is still colored.  The
easiest way is to set `formatter_class=argparse.RawDescriptionHelpFormatter`
and embed ANSI codes in the `description` and `epilog` fields.

```python
parser = argparse.ArgumentParser(
    description=f"{FLYellow}MY TOOL{CRst}\n\nDescription here.",
    epilog=f"{FGray}Requirements: ...{CRst}",
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
```

No matter which approach you use, the five sections listed above must all be
present.

### Elevation — check FIRST in `main()`

If a script needs admin/root privileges, the elevation check must be the **very
first thing** in `main()`, right after the banner. There are two patterns:

**Force-elevate (the script cannot work without it):**

```python
System.restart_elevated()  # returns if already elevated; exits after re-launch
```

**Soft-try (the script can partially work without it):**

```python
if not System.is_elevated():
    elevated = System.try_restart_elevated()
    if not elevated:
        warn_msg("Elevation unavailable. Some sections will be skipped.")
```

**IMPORTANT — sudo password:**
If the current terminal is NOT already running under `sudo`, and `sudo` requires
a password (no `NOPASSWD` in sudoers), `os.execv` / `subprocess.run` will fail
silently or hang. In this case, **tell me to re-launch the whole command from a
`sudo`-ed shell before continuing.**

### Ctrl+C handling — required for every script

Every `.py` script **must** include a `KeyboardInterrupt` handler at the module
level. The canonical pattern is:

```python
if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
```

This prints `[Exit by Ctrl+C]` in green/yellow and calls `sys.exit(0)`. Do
**not** catch `KeyboardInterrupt` inside `main()` unless the script has a
specific reason (e.g. cleanup before exit). The module-level handler is the
safety net that ensures Ctrl+C always produces a clean, consistent message
instead of a bare traceback.

**Never** use bare `except:` or `except Exception:` that silently swallows
`KeyboardInterrupt`. If a try/except block legitimately catches broad exceptions
inside a loop, re-raise `KeyboardInterrupt` as a separate, earlier clause so it
is not caught by the broader handler:

```python
try:
    ...
except KeyboardInterrupt:
    raise
except Exception as e:
    ...
```

### General conventions — always use f-strings for string formatting

- **All interactive prompts and CLI text must be in English.** No Chinese in
  console output, help text, error messages, or menu descriptions.
- **Use f-strings for all string formatting.** No `.format()`, no `%`-style
  formatting, no string concatenation for building output. f-strings are more
  readable and less error-prone. Use `f"{FLGreen}Done:{CRst} {FGray}{path}{CRst}"`
  throughout.
- **Every script must support `--help` / `-h`.** For simple scripts (≤3 flags),
  print it manually as a triple-quoted f-string.  For complex scripts, use
  **`argparse`** with `RawDescriptionHelpFormatter` — embed ANSI codes in
  `description` and `epilog` so the output stays colored.  See the `--help`
  section above for the five required subsections.
- **Platform guard** — scripts under `tools/windows/`, `tools/macos/`, or `tools/linux/` are
  platform-specific and **must** validate early.  Check `sys.platform` at the top
  of `main()` (or at module level, before imports of OS-specific modules) and
  call `Console.print_error_and_exit()` with a clear message stating which platform
  the script requires and what the current platform is:

  ```python
  if sys.platform != "win32":
      Console.print_error_and_exit(
          f"This script only runs on Windows. Current platform: {sys.platform}"
      )
  ```

  Cross-platform scripts may check `sys.platform` for branching, but should not
  hard-exit on a platform mismatch.
- **No magic numbers / magic strings** — promote them to module-level
  `UPPER_CASE` constants or a class/enum near the top after imports.
- **Constrained parameter values** — use `enum.Enum` (or `enum.IntEnum` /
  `enum.StrEnum`), never raw strings like `"horizontal"` / `"vertical"`. This
  gives IDE autocomplete and catches typos.
- **Type annotations must be rigorous.** The project uses Pylance as the
  primary type-checking signal; new or modified code should not introduce
  Pylance errors or warnings. Annotate every public function/method signature,
  non-trivial helper function, callback, dataclass, enum, and module-level
  structured constant. Use precise standard typing (`Optional`, `Union`,
  `Literal`, `Protocol`, `TypedDict`, `Callable`, `Iterable`, `Mapping`,
  `Sequence`, `PathLike`, etc.) and `dataclasses.dataclass` where appropriate.
  Avoid broad `Any`, untyped containers (`dict`, `list`, `tuple` without
  parameters), and implicit `None` returns in functions that should return a
  value. No `# type: ignore` unless truly unavoidable; if used, add a short
  reason and keep it scoped to one line.
- **Verify Pylance-relevant changes.** When editing type-heavy code, new
  helpers, public APIs, or modules under `utils/`, check for Pylance diagnostics
  in the touched files if the environment exposes them. If CLI diagnostics are
  available (for example via pyright/Pylance-compatible tooling), run the
  smallest relevant check. If diagnostics cannot be queried from the agent
  environment, say so and still write code to be Pylance-clean by inspection.
- **Code must be maintainable.** This is a personal toolkit, but not throwaway
  code. Write for readability, extensibility, and configurability. Prefer more
  CLI flags and interaction options over hardcoded behaviour. Think "what if I
  need this to work slightly differently next time?"

### Docstrings — detailed and structured

Every public function, method, and class must have a **Google-style docstring**
(or NumPy-style — be consistent within a file) that covers:

1. **What** the function does (one-liner, then details if needed).
2. **Args** — every parameter with its type, meaning, default value, and valid
   range / choices.
3. **Returns** — the return type and what the value means.
4. **Raises** — every exception the function may deliberately raise and under
   what conditions.
5. **Side effects** — if the function prints to stdout, writes files, modifies
   `sys.argv`, calls `sys.exit()`, etc.

Example:

```python
def resolve_output_path(
    default_path: str,
    prompt: str = "Enter output path",
    path_type: str = "file",
) -> str:
    """Resolve an output path interactively with collision avoidance.

    Prompts the user for a file/directory path with a suggested default.
    Automatically appends ``_2``, ``_3``, ... if the path already exists.
    Prompts to create missing parent directories.

    Args:
        default_path: Suggested path shown as the default.
        prompt: Label shown before the path input.
        path_type: ``"file"`` (checks parent dir + file collision),
            ``"dir"`` (checks the directory itself), or ``"link"`` (checks
            for an existing symlink).

    Returns:
        Absolute resolved path string.  Guaranteed not to collide with an
        existing entry at the time of resolution.

    Raises:
        SystemExit: If the user chooses to quit (types ``e`` at the
            collision menu or ``Ctrl+C``).
    """
```

Do **not** write "placeholder" docstrings like `"""Handle the thing."""` and
intend to fill them in later. Write the real docstring when you write the code.

### Inline comments — section markers for large blocks

Functions longer than ~30 lines should be broken into logical sections with a
`# ──` separator comment explaining what the next block does. This makes the
code scannable and simplifies future refactoring:

```python
def main() -> int:
    # ── help text ──────────────────────────────────────────
    if "--help" in sys.argv or "-h" in sys.argv:
        ...

    # ── elevation check ────────────────────────────────────
    if not System.is_elevated():
        ...

    # ── gather inputs ──────────────────────────────────────
    pattern_type = _select_pattern_type()
    ...

    # ── processing loop ────────────────────────────────────
    while True:
        ...

    # ── summary ────────────────────────────────────────────
    print(...)
    return 0
```

Follow the existing project style: `# ── label ── N×─` with a short label
centered in a ~48-char-wide comment line.

### After creating or modifying a script

When you create a new script or change an existing one's behaviour, **update
ALL of these** so they stay consistent:

1. **Module docstring** — the triple-quoted string between `#!/usr/bin/env
   python3` and the imports. Cover what, requirements, and usage.
2. **`--help` output** — the formatted help text inside `main()`. Must list
   description, usage, all CLI flags, and dependencies.
3. **[README.md](README.md)** — English. Add or update the entry in the correct
   category table.
4. **[README_zh.md](README_zh.md)** — Chinese. Same as above.

These four places must agree on the script's purpose and requirements, but
their level of detail differs. Keep detailed usage examples, options, and
technical behavior in the module docstring, `--help`, or example configuration,
not in the README.

### README scope and Highlights ownership

- **`README.md` and `README_zh.md` are quick overviews for first-time users.
  They are not technical documentation or API documentation.**
- Introduce each script **only in its category table**, using **no more than
  two sentences** to describe its purpose and key highlights. Do not add
  standalone detailed script explanations outside the table.
- Do not include implementation details, API descriptions, special parameters,
  or interaction details that do not help a new user understand what the script
  does. Detailed command options, prompt/menu behavior, configuration precedence,
  inheritance rules, and other technical specifics belong in script-level
  documentation or example configuration files.
- **The Highlights section in either language is authored exclusively by the
  project owner.** Do not independently add, remove, rewrite, reorder, or polish
  its content. Only translate owner-written content into the other language,
  faithfully preserving the owner's wording, style, structure, and meaning.

## Directory layout

`tools/network/rclone-sync.py` is a thin entry for the private
`tools/network/rclone-sync/` package, loaded as `personal_rclone_sync`.
See that package's README.md for module ownership. Keep its internal modules
out of launcher/compiler script lists. The compiler stages the package under
its import name for Nuitka/PyInstaller; source launches use the file-based loader.
Keep `{{script_dir}}` anchored to the entry directory. PathPairConfig stores
unchanged YAML endpoints; ResolvedPathPair holds runtime addresses and volume
bindings. Do not reintroduce parallel per-pair metadata lists or export a legacy
API facade from the entry. Run rclone tests with `-p "test_rclone*.py"`.

```text
./
├── run-script.py          # Unified launcher
├── launcher-config.yaml   # Launcher paths, script types, colors, patterns, ignores
├── launcher-config.patch.yaml  # Optional Gitignored personal overrides
├── compile-script.py      # Script → standalone exe (Nuitka / PyInstaller)
├── tools/                 # Runnable scripts discovered by run-script.py
│   ├── document-processing/
│   ├── download/
│   ├── filesystem/
│   ├── multimedia/
│   ├── network/
│   ├── research/
│   ├── windows/           # Windows-only scripts
│   ├── macos/             # macOS-only scripts
│   └── linux/             # Linux-only scripts
├── utils/
│   ├── __init__.py         # Compatibility facade; preserves `from utils import *`
│   ├── ansi.py             # ANSI color/style/cursor constants
│   ├── cmd_check.py        # CmdCheck
│   ├── console.py          # Console formatting and terminal interaction
│   ├── environment.py      # Runtime environment and executable discovery
│   ├── system.py           # OS integration, privilege, and macOS permissions
│   ├── paths.py            # Path placeholder and environment expansion
│   ├── pdf.py              # Lazy PyMuPDF authentication and safe new-file output
│   ├── font.py             # Installed font discovery, localized names, and style matching
│   ├── input.py            # Input
│   ├── cursor.py           # Cursor
│   ├── menu_option.py      # MenuOption
│   └── menu.py             # Menu
├── test/                  # Test helpers
├── tmp/                   # Temporary / scratch scripts (GITIGNORED)
├── output/                # General output directory (GITIGNORED)
├── BUILD/                 # Compiled executables (GITIGNORED)
├── requirements.txt       # Launcher and ordinary tool dependencies
├── requirements-research.txt
├── README.md              # English documentation
├── README_zh.md           # Chinese documentation
└── CLAUDE.md              # This file
```

- **Temporary / scratch files** — Use this order:
  1. If `./tmp/` exists, use `./tmp/`.
  2. Otherwise, if `./BUILD/` exists, use `./BUILD/claude-code-tmp/`.
  3. Otherwise, if `./build/` exists, use `./build/claude-code-tmp/`.
  4. Otherwise, if `./out/` exists, use `./out/claude-code-tmp/`.
  5. Otherwise, ask where temporary files should go.

  Do not silently use system temp directories such as `/tmp/claude-code-tmp`,
  `/var/tmp`, `%TEMP%`, or `%TMP%`; ask first.
- **`./tmp/`** — Preferred location for temporary, scratch, and one-off
  scripts. Gitignored.
- **Importing project modules from `./tmp/`** — Scripts under `./tmp/` sit one
  level deeper than the project root, so `sys.path` needs `../..` instead of
  `..`.  Additionally, some project Python files have hyphens in their names
  (e.g. `run-script.py`, `compile-script.py`), which makes them unimportable
  with a regular `import` statement — Python identifiers cannot contain `-`.
  Use `importlib.util` to load them instead:

  ```python
  import importlib.util
  import sys
  from pathlib import Path

  PROJECT_ROOT = Path(__file__).resolve().parent.parent
  MODULE_PATH = PROJECT_ROOT / "run-script.py"
  MODULE_NAME = "run_script"          # must be a valid Python identifier

  spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
  mod = importlib.util.module_from_spec(spec)
  sys.modules[MODULE_NAME] = mod
  spec.loader.exec_module(mod)
  # Now use mod.main(), mod.some_function(), etc.
  ```

  For `utils/`, use a regular `sys.path` insertion — it has a valid module name:

  ```python
  sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
  from utils import *  # noqa: E402
  ```

- **Temporary verification scripts are still code** — Scripts under `./tmp/`
  may be disposable, but they must still be readable, type-annotated where
  non-trivial, and safe. Follow the same console-output rules as real scripts:
  English CLI text, no Chinese output, avoid emoji, and prefer ASCII unless
  Unicode handling is the subject being tested. Do not use scratch status as an
  excuse for throwaway-quality code when the script verifies project behaviour.
- **`./tools/research/`** — Research / experimental scripts. When they generate output
  files, default to `./output/` (or `./tools/research/output/`) unless I specify
  otherwise.
- **`./output/`** — General output directory, gitignored.
- **`./BUILD/`** — Compiled executables from `compile-script.py`, gitignored.
- Non-platform-specific new scripts go in `tools/` or the appropriate category
  under `tools/`.

## Platform & cross-platform rules

1. Scripts in `tools/windows/`, `tools/macos/`, `tools/linux/` are inherently platform-specific.
2. All other scripts should work **cross-platform** unless the task itself is
   OS-specific. When a cross-platform script needs OS-specific behaviour, branch
   on `sys.platform` (`"win32"`, `"darwin"`, `"linux"`) rather than creating
   platform copies.
3. **Windows**: prefer PowerShell over cmd.exe. Bash (Git Bash) is also
   available — find via `bash` on PATH, `where git` + derive path, or
   `Environment.find_bash()`.

## Privacy & open source

This project is **public on GitHub**. Never hardcode:

- Passwords, tokens, API keys, S3 credentials, access secrets
- Internal hostnames, IP addresses, usernames, or machine names
- File paths containing personally identifying info (real names, company names,
  account GUIDs, etc.)

Use environment variables, `Input.input_password()`, or config files for
sensitive data. When writing example paths in docstrings or help text, use
placeholders like `/path/to/…` or `C:\Users\<you>\…`.
