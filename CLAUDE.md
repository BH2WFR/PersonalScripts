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

General agent behaviour rules live in the shared prompt
`D:\Data\OneDrive\Backups\prompts\cc-python-programming.md`.  This file should
only add rules specific to this Python script toolkit.

Project-specific reminders:

- Reply in the user's language.
- Before editing code, read the surrounding file and follow the local style.
- Keep edits scoped to the requested script or shared utility.
- After behavioural code changes, run the smallest relevant check available:
  `--help`, a launcher dry-run, an import check, or a script-specific test.
- Do not run status-only shell commands such as `echo "done"`; report status in
  the reply.

## Environment

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
- `Utils.find_conda()` already does the project-specific conda search — prefer
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
  4. `Utils.find_bash()` already does this search — prefer it over a manual hunt.
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

```bash
conda run -n base python run-script.py                # interactive list
conda run -n base python run-script.py --list         # list scripts and exit
conda run -n base python run-script.py <name>         # fuzzy-matched run
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
    scripts under `windows/` may use CRLF.
- **Windows console encoding** — if console output shows garbled characters,
  use `chcp 65001` (UTF-8 codepage) and set the locale to `en-US.UTF-8` via
  `Utils.set_locale_utf8()`.  Prefer Unicode / UTF-8 APIs over ANSI / GBK
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
- Keep edits narrowly scoped to the requested script, `utils/__init__.py`, or
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

## Shared utility library — `utils/__init__.py`

**Every script in this project imports `utils`.** The canonical import block is:

```python
import os
import sys
# ... other stdlib imports ...

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402
```

This makes ALL names from `utils` available: ANSI color constants (`FRed`,
`FLGreen`, `CRst`, …), classes (`Utils`, `Input`, `Menu`, `MenuOption`,
`Cursor`, `CmdCheck`), and any new additions. Scripts never import from utils
piecemeal.

### When `utils/__init__.py` gets too large — new sub-modules

If a group of utilities is **domain-specific** (e.g. image processing, network
tools, PDF helpers), it should become a new file under `utils/` (e.g.
`utils/pdf_utils.py`, `utils/image_utils.py`).  `utils/__init__.py` stays the
home for cross-cutting, broadly-used utilities.  **Stop and ask before creating
a new sub-module** — I (the project owner) will confirm the split.

### When to use the wheel — ALWAYS

Before writing anything, check if `utils/__init__.py` already has it. The
canonical implementations live here; do not duplicate them in individual scripts.

#### `Utils` class — static methods

| Need | Use |
|---|---|
| Admin / root detection | `Utils.is_elevated() -> bool` |
| Re-execute as admin (force) | `Utils.restart_elevated()` — never returns on success |
| Re-execute as admin (soft, can fallback) | `Utils.try_restart_elevated() -> bool` |
| Check if a CLI tool is in PATH | `Utils.check_commands(*CmdCheck)` or `Utils.which(name)` |
| OS name / arch / hostname | `Utils.get_os_name()`, `Utils.get_arch()`, `Utils.get_computer_name()` |
| Print a box-drawing banner | `Utils.print_banner("TITLE")` |
| Print a horizontal separator | `Utils.print_separator(width=..., color_ansi_esc=...)` |
| Print env info (conda, python, shell) | `Utils.print_env_info()` |
| Standard KeyboardInterrupt exit | `Utils.print_keyboard_interrupt_message_and_exit()` |
| Standard exit message | `Utils.print_exit_message_and_exit()` or `Utils.print_error_and_exit()` |
| Desktop notification | `Utils.notify(title, body)` |
| Open a file in the default app | `Utils.open_with_default_app(path)` |
| Open a URL safely (headless-safe) | `Utils.open_browser_safe(url)` |
| Resolve `$VAR` / `{{placeholders}}` in paths | `Utils.resolve_path_vars(path, schema_dir=..., script_dir=...)` |
| DPI awareness (Windows) | `Utils.enable_dpi_awareness()` |
| Find bash / pwsh / conda | `Utils.find_bash()`, `Utils.find_pwsh()`, `Utils.find_conda()` |
| Conda environment name | `Utils.get_conda_env() -> Optional[str]` |
| Terminal width / CJK display width | `Utils.get_terminal_width()`, `Utils.display_width(s)` |
| Headless detection | `Utils.is_headless()` |
| Current time string | `Utils.get_time_str()` |
| Print argv for debugging | `Utils.print_argv_list()` |
| Set console to UTF-8 | `Utils.set_locale_utf8()` |

#### `Input` class — interactive prompts (static methods)

| Need | Use |
|---|---|
| General text input | `Input.prompt(prompt, default=..., transform=...)` |
| Numeric input with validation | `Input.input_number(prompt, default=..., min_value=..., allow_float=...)` |
| Number + unit (e.g. `90deg`) | `Input.input_number_with_unit(prompt, ..., allowed_units=("deg","rad"))` |
| Password / masked input | `Input.input_password(prompt)` |
| Output path (auto collision avoidance) | `Input.resolve_output_path(default_path, prompt=..., path_type="file")` |
| Input path (existence validation) | `Input.resolve_input_path(default_path, ..., path_type="file")` |
| Multiple input paths (glob expand) | `Input.resolve_input_paths_multi(..., glob=True)` |
| Multi-line text from stdin | `Input.read_stdin_multiline(...)` |

#### `Menu` + `MenuOption` — interactive selection menus

```python
choice = Menu.select(
    [MenuOption(["1", "R"], "Do the thing", some_value),
     MenuOption(["2", "X"], "Exit", None)],
    prompt="Choice", required=True, default_key="1",
)
# Menu.from_enum(MyEnum) — builds MenuOption list from an enum.
```

#### `Cursor` class — ANSI cursor escapes (returns strings, does not print)

`up`, `down`, `forward`, `back`, `next_line`, `prev_line`, `column`, `position`,
`erase_display`, `erase_line`, `scroll_up`, `scroll_down`.

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
| Banner / separator / section heading | `FLYellow` | `Utils.print_banner("TITLE")` |
| Key hints in menus | `FLGreen` | `[Y]` inside bracket notation |
| Important / highlight (sparingly) | `FLCyan` | Highlighting a key value in output |

**Don't over-colour.** A wall of rainbow text is worse than no colour at all.
One colour per semantic role per line. When in doubt, err on the side of fewer
colors — the user should be able to scan output and instantly know what's a
prompt, what's an error, and what's informational.

### When to add a function to `utils`

If a piece of logic looks like it could be useful in **more than one script**
(interactive prompts, platform detection, path helpers, formatting, etc.),
extract it into `utils/__init__.py` rather than duplicating it. Add a new
`@staticmethod` to `Utils`, `Input`, or another appropriate class following the
existing patterns. This is encouraged — `utils` is meant to grow.

**After adding to `utils`**, update this `CLAUDE.md` file — add the new method
to the relevant quick-reference table. An out-of-date table means the AI will
miss useful utilities or re-implement them.

### When a `utils` function is almost right but not quite

**Stop and ask me.** Do not fork the utility into a script-local copy. Either:

- Extend the existing `utils` function with an optional parameter
  (backward-compatible), or
- Write a new `@staticmethod` that wraps or composes the existing one.

I'll decide whether to modify utils or handle it differently.

## Code style

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

**System tools** — use `Utils.check_commands()` with `CmdCheck` entries.  This
prints per-platform install hints for missing tools and returns `False` when a
required tool is absent:

```python
if not Utils.check_commands(
    CmdCheck("ffmpeg", required=True, hints={
        "windows": f"  {FGray}scoop install ffmpeg{CRst}",
        "macos":   f"  {FGray}brew install ffmpeg{CRst}",
        "linux":   f"  {FGray}sudo apt install ffmpeg{CRst}",
        "any":     f"  {FGray}https://ffmpeg.org/download.html{CRst}",
    }),
):
    Utils.print_error_and_exit("Missing required dependencies.")
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

    Utils.print_banner("SCRIPT TITLE")

    # ── dependency checks ──────────────────────────────────
    # validate hard dependencies here (pip imports / system tools)

    # ── elevation check (if needed) ──
    if not Utils.is_elevated():
        ...

    # ... logic ...

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
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
Utils.restart_elevated()  # never returns if already elevated or on success
```

**Soft-try (the script can partially work without it):**

```python
if not Utils.is_elevated():
    elevated = Utils.try_restart_elevated()
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
        Utils.print_keyboard_interrupt_message_and_exit()
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
- **Platform guard** — scripts under `windows/`, `macos/`, or `linux/` are
  platform-specific and **must** validate early.  Check `sys.platform` at the top
  of `main()` (or at module level, before imports of OS-specific modules) and
  call `Utils.print_error_and_exit()` with a clear message stating which platform
  the script requires and what the current platform is:

  ```python
  if sys.platform != "win32":
      Utils.print_error_and_exit(
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
- **Type annotations must be rigorous.** The project uses Pylance — keep it
  clean. Use `typing.Optional`, `typing.Union`, `Protocol`, `dataclasses.dataclass`
  as appropriate. No `# type: ignore` unless truly unavoidable.
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
    if not Utils.is_elevated():
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

These four places describe the same script; they must not drift apart. A reader
should get the same dependency list and usage examples whether they look at the
module docstring, run `--help`, or read the README.

## Directory layout

```text
./
├── run-script.py          # Unified launcher
├── compile-script.py      # Script → standalone exe (Nuitka / PyInstaller)
├── utils/
│   └── __init__.py         # Shared library (Utils, Input, Menu, Cursor, colors)
├── windows/               # Windows-only scripts
├── macos/                 # macOS-only scripts
├── linux/                 # Linux-only scripts
├── research/              # Research / experimental scripts
│   └── output/            # Default output for generated research artifacts
├── test/                  # Test helpers (keyboard hook, etc.)
├── tmp/                   # Temporary / scratch scripts (GITIGNORED)
├── output/                # General output directory (GITIGNORED)
├── BUILD/                 # Compiled executables (GITIGNORED)
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
- **`./research/`** — Research / experimental scripts. When they generate output
  files, default to `./output/` (or `./research/output/`) unless I specify
  otherwise.
- **`./output/`** — General output directory, gitignored.
- **`./BUILD/`** — Compiled executables from `compile-script.py`, gitignored.
- Non-platform-specific new scripts go in the **project root**.

## Platform & cross-platform rules

1. Scripts in `windows/`, `macos/`, `linux/` are inherently platform-specific.
2. All other scripts should work **cross-platform** unless the task itself is
   OS-specific. When a cross-platform script needs OS-specific behaviour, branch
   on `sys.platform` (`"win32"`, `"darwin"`, `"linux"`) rather than creating
   platform copies.
3. **Windows**: prefer PowerShell over cmd.exe. Bash (Git Bash) is also
   available — find via `bash` on PATH, `where git` + derive path, or
   `Utils.find_bash()`.

## Privacy & open source

This project is **public on GitHub**. Never hardcode:

- Passwords, tokens, API keys, S3 credentials, access secrets
- Internal hostnames, IP addresses, usernames, or machine names
- File paths containing personally identifying info (real names, company names,
  account GUIDs, etc.)

Use environment variables, `Input.input_password()`, or config files for
sensitive data. When writing example paths in docstrings or help text, use
placeholders like `/path/to/…` or `C:\Users\<you>\…`.
