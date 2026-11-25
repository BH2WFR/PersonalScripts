# AGENTS.md

PersonalScripts is a personal, cross-platform Python toolkit. This file is the
authoritative project instruction entry; `CLAUDE.md` only routes here.
After context compaction, reread this file before project work.

## Project baseline

- Target Python 3.13+; the project development environment is Conda `base`.
- Project text files use UTF-8 without BOM. Preserve existing line endings;
  new cross-platform files use LF, while Windows-only scripts may use CRLF.
- Windows support starts at Windows 10; do not add legacy Windows fallbacks.
- Avoid creating many temporary files or writing large volumes of temporary data.
  Prefer streaming or bounded in-memory buffers for intermediate results.

## Directory layout

- `tools/`: runnable scripts grouped by category; use `tools/others/` when none
  fits. Some scripts are thin entries with implementations in separate private
  packages. Keep internal modules out of launcher lists and preserve
  their source layout in release archives.
- `utils/`: shared helpers; [utils/README.md](utils/README.md) indexes their APIs.
- Store extra resource packs downloaded by tools under the project root in `deps/`
  (e.g. `deps/ocr-models/` for OCR models). Resolve it with `Paths.dependencies_directory()`.
- `test/`: tests and verification helpers.
- `output/`: generated results; `tmp/`: scratch work; `BUILD/`: release
  artifacts. All three are gitignored.
- Root `run-script.py` discovers and launches scripts; `package-project.py`
  packages the working tree and a shared portable runtime.
  Run `package-project.py` only when the user explicitly requests packaging. Use Conda for routine development and verification.
- Root `launcher-config.yaml` defines launcher discovery rules;
  `launcher-config.patch.yaml` is an optional gitignored override. User
  `launcher.yaml` stores extra script roots. When using Conda, the shell wrappers
  read the environment name from `conda-env.txt` in the shared user configuration directory.
- Whenever adding a feature, renaming a tool, or converting a tool to a GUI,
  update `launcher-config.yaml` in the same change, including affected discovery,
  platform exclusions, `gui-tools-list` and `elevation-needed-list`. Never add
  unnecessary comments when editing `launcher-config.yaml`.
- Read the affected module/package's README and sample configuration as needed.
  Keep implementation details there rather than expanding this project prompt.

```text
conda run -n base python run-script.py --list
conda run -n base python run-script.py <name> [args...]
```

## Shared utilities and configuration

- Before adding a helper or repeated block, search `utils/` and existing scripts
  for equivalent behavior. Reuse the canonical implementation instead of
  rebuilding prompts, validation, paths, formatting or platform integration.
- Put behavior reusable across scripts in the appropriate `utils/` module.
  If an existing helper is almost suitable, extend it compatibly or compose it;
  do not create a script-local fork. Consolidate duplicate callers within the
  affected scope. Keep genuinely application-specific models/workflows local.
- Implement shared behavior in its owning module, not `utils/__init__.py`.
  Scripts use `from utils import *` after adding the repository root to
  `sys.path`; calculate the root from the file's actual depth. Keep the facade
  free of eager Qt, PDF/image-engine and application imports.
- When editing `utils/`, update the corresponding `utils/docs/*.md` in the
  same change, covering the affected API, behavior and important internal reuse
  boundaries. Keep [utils/README.md](utils/README.md) aligned with module
  ownership and public exports; API details belong in those docs, not here.
- Use `ConfigStore` for user settings and its directory resolver for per-user configuration paths.
  Do not introduce custom environment variables or script-local configuration
  I/O. Encrypted-value keys belong to the consuming module. Document settings
  and supported native variables in
  [Environmental_Variables.md](Environmental_Variables.md).
- On Linux and macOS, elevated scripts must resolve reads and writes of
  home-relative user files, including configuration, against the invoking
  user's home directory (under `sudo`, look up `SUDO_UID` in the OS account database).

## Script structure and platforms

- Entry filenames use lowercase kebab-case, with related tools sharing a
  subject prefix for alphabetical grouping. Prefer natural tool nouns such as
  `viewer`, `editor`, `trimmer` and `cleaner`; concise action names are allowed
  when clearer. Include distinctive backend names, such as `ffmpeg`, `yt-dlp`
  or `ntfs-3g`, when they identify the tool. Platform names belong in directories.
- When renaming entries, update launcher/packaging rules, internal entry paths,
  tests, HELP and both READMEs together. Preserve private import aliases,
  persisted config keys/filenames and document formats unless explicitly migrated.
- Put platform-exclusive tools in `tools/windows/`, `tools/macos/` or
  `tools/linux/`. Check `sys.platform` before platform-specific work or imports,
  with a clear unsupported-platform message. Other categories should work
  cross-platform unless their purpose inherently requires one OS; branch within
  shared code instead of maintaining platform copies.
- Runnable Python entries expose `main() -> int`, returning an exit status.
  Long-running GUI/hook entries may use `main() -> None`. Importing an entry must
  not start its operational work.
- Start each runnable Python entry's `main()` with `Console.initialize_ansi_output()`.
  In layered tools, the outer script owns console setup, public help, elevation
  and final Ctrl+C handling. Private app and worker functions called by that
  script inherit this setup, even when named `main()`. Direct help paths that
  exit before the entry's `main()` use `Console.print_help_and_exit(HELP)`.
- Handle `--help`/`-h` before prompts, dependency probes, elevation or work.
  Check hard dependencies before interactive work; use
  `Environment.check_commands()` with `CmdCheck` for external tools and give
  actionable hints for missing Python packages. Load optional integrations only
  when their feature is needed.
- A tool may require elevation on only some supported operating systems.
  Request elevation only on those platforms and use the caller's existing
  privileges elsewhere. On platforms requiring elevation, Python entries
  call `System.restart_elevated()` once in `main()` after
  help, argument validation and platform checks, before output, prompts or work.
  Entries accepting explicit `argv` pass `entry=__file__, args=argv` to preserve
  the invocation. Windows console tools must keep the caller's console and return
  the elevated child's exit status. The helper returns only when already elevated and exits on failure. Bash
  entries that require elevation on the current platform check `EUID` and use
  `exec sudo -u root bash "$0" "$@"` with the original arguments. Keep the tool's
  path and platform scope in sync with `elevation-needed-list` in `launcher-config.yaml`.
- Catch Ctrl+C at the entry boundary with
  `Console.print_keyboard_interrupt_message_and_exit()`; allow cleanup before
  it and do not swallow cancellation in retry loops.

Minimal entry pattern for `tools/<category>/<script>.py`; add functional
arguments, dependency/platform checks and processing as needed:

```python
#!/usr/bin/env python3
"""Implementation notes for maintainers, when needed; do not repeat HELP."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402


HELP = """TOOL NAME

One sentence about the core task.

Requirements:
  Required Python packages or external tools.

Usage:
  python script.py
"""


def main() -> int:
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.parse_args()  # Help exits before operational checks or work.
    Console.print_banner("TOOL NAME")
    # Check platform/dependencies/privileges, then gather inputs and process.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
```

For argparse-based entries use `Console.argument_parser(HELP)`; simple entries
can print `HELP` directly. Private implementation modules do not need a CLI.

## Console, input and GUI conventions

- CLI text, help, prompts, errors and menu descriptions are English. Prefer
  f-strings and shared formatting helpers.
- Use named ANSI Escape constants from `utils`, not literal escape sequences;
  terminate each colored segment with `CRst`, for example
  `f"{FLGreen}Saved:{CRst} {FGray}{path}{CRst}"`. Keep coloring sparse:
  `FLYellow` for prompts/warnings/headings, `FLGreen` for success/menu keys,
  `FLRed` for errors, `FGray` for paths/defaults/secondary text, and `FLCyan`
  for progress labels or occasional highlights. Use `Console.print_banner()`
  and `Console.print_separator()` for headings/separators.
- Reuse `Input` for prompts and validation, `Menu`/`MenuOption` for choices,
  and `Input.input_password()` for masked password entry. Use the shared path
  and range input helpers instead of writing new interactive validators.
- Use `tqdm` for repeated work with meaningful units/totals, disable redraws
  outside interactive terminals, and use `tqdm.write()` for messages during a bar.
- For project console-encoding diagnosis, `Console.set_locale_utf8()` supplies
  the shared Windows setup and prints a diagnostic line; do not duplicate that
  setup or call it unconditionally in every entry.
- For PDF tools follow the [shared PDF policy](utils/docs/pdf.md): use
  `Pdf.open_document()` for existing inputs and `Pdf.save_new()` for output.
- Show GUI errors in tooltips or dialogs by default. If an error message appears
  inline, hide it or clear its text as soon as the error condition is resolved.
- All GUIs must scale on high-DPI screens and update automatically when moved
  between monitors with different DPI. Scale fonts, controls, spacing and images
  together without clipping or losing input/state; do not hard-code physical
  pixels or apply a startup-only scale. Use toolkit-native DPI support and shared
  helpers; Windows requires per-monitor awareness before creating windows.
  Tk tools use [TkDpi](utils/docs/tk_dpi.md); Qt uses logical coordinates without
  double scaling. Verify initial scaling and repeated mixed-DPI transitions.
- Simple GUI tools may use Tkinter; reserve PySide6 for complex interfaces.
  Every PySide6 tool must call `configure_qt_application(application)` from
  `utils.qt_widgets` before creating widgets, including with a reused application.
  It configures Fusion, font fallback for simplified/traditional Chinese,
  Japanese and Korean, system glyph fallback for other scripts, and wheel guards.
  Use `with_cjk_fallbacks(font)` for custom UI font families and the shared
  [no-wheel form controls](utils/docs/qt.md) for Qt inputs.
- In scrollable containers, every combo box and spin box must ignore wheel
  input by default, even when focused, so scrolling the container preserves
  the current selection or value. Shared setup calls `install_no_wheel_controls`
  for this. Keep open combo-box lists scrollable.
- In PySide6 GUIs, avoid `PIL.ImageQt` because it can load PyQt6 first and cause
  a Qt version conflict at startup. Build a PySide6 `QImage` from Pillow pixel
  bytes with the matching format and stride, then call `.copy()` before releasing
  the buffer.

## Code and module documentation

- Annotate public APIs, non-trivial helpers, callbacks and structured data
  precisely; keep touched code free of new Pylance diagnostics. Use named
  constants/enums for meaningful repeated values and constrained choices.
- Public APIs use concise Google-style or NumPy-style docstrings, consistently
  within a module. Explain non-obvious arguments, returns, deliberate errors
  and side effects; do not repeat obvious signatures or implementation steps.
- Put user-facing help in a module-level `HELP` string near the top of the file,
  after only the imports needed to construct it. `main()` and help handlers
  reference that string; do not embed another help document in functions.
  Thin runtime wrappers forward help to the canonical entry without copying it.
- Put extra agent/maintainer instructions in a separate top-of-file multiline
  comment or module docstring. Keep it focused on implementation/maintenance,
  without repeating HELP's introduction, requirements or usage. Private package
  documentation can hold longer architecture notes.

## README and help writing

- `README.md` and `README_zh.md` are concise first-use overviews. Introduce each
  script only in its category table, using at most two short sentences explaining
  what it does, the problem it solves and its defining capabilities.
- Put dependencies and platform requirements in the Requirements column.
  Exclude menus, buttons, gestures, preview controls, confirmations, retries,
  exit behavior, implementation details and exhaustive feature inventories.
  A UI-only improvement does not warrant a root README change.
- Whenever editing a script, review its top-level `HELP` and help entry point.
  If it is too long or violates these rules, rewrite it in the same change,
  even when the requested edit does not otherwise affect help.
- HELP contains a short functional introduction, `Requirements` and `Usage`.
  The introduction covers what the feature does, the problem it solves,
  distinguishing capabilities and essential caveats, in as few sentences as
  possible. Requirements names hard dependencies/platforms and labels optional
  ones; Usage gives minimal invocations and necessary argument guidance.
  Remove interaction tutorials, incidental UI/implementation details, repeated
  explanations and exhaustive feature inventories.
- Keep both README languages, module docstrings, help and dependency declarations
  consistent. Update affected descriptions when purpose, capabilities or
  requirements change; put detailed configuration/usage in local docs or examples.
- The root READMEs' Highlights sections belong to the project owner; do not
  independently add, remove, rewrite or reorder them. Translate owner-written
  content faithfully without changing its wording, style, structure or meaning.

## Verification

- Run the smallest relevant check after behavior changes: entry `--help`,
  targeted tests under `test/`, or an import check. For example:
  `conda run -n base python -m unittest discover -s test -p "test_input*.py"`.
- Check available Pylance-compatible diagnostics for type-heavy or utility
  changes. Documentation-only changes need link/content checks.

## Python dependency declarations

- Declare third-party Python runtime dependencies for the launcher and all tools
  in `requirements.txt`, including research scripts and optional features. Use
  environment markers for platform-specific packages.
- Put dependencies used only for internal development, testing, or building
  executables in `requirements-internal.txt`.
- Prefer unpinned requirements or a justified compatible version range. Do not
  use exact `==` pins by default. Keep the relevant README, module docstring,
  and `--help` dependency descriptions consistent with these files.
