# AGENTS.md

PersonalScripts is a personal, cross-platform Python toolkit. This file is the
authoritative project instruction entry; `CLAUDE.md` only routes here.
After context compaction, reread this file before project work.

## Project baseline

- Target Python 3.13+; the project development environment is Conda `base`.
- Project text files use UTF-8 without BOM. Preserve existing line endings;
  new cross-platform files use LF, while Windows-only scripts may use CRLF.
- Windows support starts at Windows 10; do not add legacy Windows fallbacks.

## Directory layout

- `tools/`: runnable scripts grouped by category; use `tools/others/` when none
  fits. Some scripts are thin entries with implementations in separate private
  packages. Keep internal modules out of launcher/compiler lists and preserve
  package loading and build staging.
- `utils/`: shared helpers; [utils/README.md](utils/README.md) indexes their APIs.
- `test/`: tests and verification helpers.
- `output/`: generated results; `tmp/`: scratch work; `BUILD/`: compiled
  applications. All three are gitignored.
- Root `run-script.py` discovers and launches scripts; `compile-script.py`
  builds standalone applications.
- Root `launcher-config.yaml` defines launcher discovery rules;
  `launcher-config.patch.yaml` is an optional gitignored override. User
  `launcher.yaml` in the shared user configuration directory stores environment
  choices and extra script roots.
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
- Use `ConfigStore` for user settings and its directory resolver for paths.
  Do not introduce custom environment variables or script-local configuration
  I/O. Encrypted-value keys belong to the consuming module. Document settings
  and supported native variables in
  [Environmental_Variables.md](Environmental_Variables.md).

## Script structure and platforms

- Put platform-exclusive tools in `tools/windows/`, `tools/macos/` or
  `tools/linux/`. Check `sys.platform` before platform-specific work or imports,
  with a clear unsupported-platform message. Other categories should work
  cross-platform unless their purpose inherently requires one OS; branch within
  shared code instead of maintaining platform copies.
- Runnable Python entries expose `main() -> int`, returning an exit status.
  Long-running GUI/hook entries may use `main() -> None`. Importing an entry must
  not start its operational work.
- Handle `--help`/`-h` before prompts, dependency probes, elevation or work.
  Check hard dependencies before interactive work; use
  `Environment.check_commands()` with `CmdCheck` for external tools and give
  actionable hints for missing Python packages. Load optional integrations only
  when their feature is needed.
- For required privileges use `System.restart_elevated()`; for a usable fallback
  use `System.try_restart_elevated()`. Check before privileged work, keeping
  help available without elevation.
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
- Simple GUI tools may use Tkinter; reserve PySide6 for complex interfaces.
  PySide6 tools use Fusion and the shared no-wheel form controls; follow
  [Qt conventions](utils/docs/qt.md) and import Qt-only APIs explicitly from
  `utils.qt_widgets`.

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

- When new code imports a third-party Python library, first decide whether the
  library is a hard runtime dependency, an optional integration, or only a
  development/build dependency. Standard-library modules are not dependencies.
- Add hard dependencies used by the launcher or ordinary tools to
  `requirements.txt`. Do not add a library merely because it might be useful.
- Put dependencies used only by scripts under `tools/research/` in
  `requirements-research.txt`. Do not duplicate them in `requirements.txt`
  unless non-research code also requires them.
- Put optional platform integrations, test-only libraries, and standalone
  executable builders in `requirements-optional.txt`.
- Prefer unpinned requirements or a justified compatible version range. Do not
  use exact `==` pins by default. Keep the relevant README, module docstring,
  and `--help` dependency descriptions consistent with these files.
