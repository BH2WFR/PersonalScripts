#!/usr/bin/env python3
"""Create a Windows, macOS or Linux desktop Open With Python launcher.

Windows creates a UTF-8 CMD launcher in %ProgramFiles%/PersonalScripts and
tries same-terminal elevation before prompting. A writable `--output-dir` works
when elevation is unavailable. macOS creates an AppleScript application in
`~/Applications/PersonalScripts`, runs the script in Terminal, and requires no
elevation. Linux X11/Wayland desktops create a .desktop entry and a companion
.desktop.sh runner in $XDG_DATA_HOME/applications/PersonalScripts (default:
~/.local/share/applications/PersonalScripts), without elevation. Entries use
Terminal=true and %F for local file arguments; a desktop terminal is required.
Linux offers explicit MIME types (semicolon-separated, with examples) or an
attempt to offer the launcher for all files (not guaranteed). CLI equivalents
are repeated --mime-type options or --all-files, which are mutually exclusive.
All-files mode omits MimeType; it is an unrestricted manual candidate, not a
standard wildcard association. Look under Other Applications / All Applications;
visibility and recommendations depend on the file manager. No MIME definitions
or defaults are changed. This tool makes no assumptions about the target script.
An optional update-desktop-database refreshes application recommendations.
--output-dir overrides the destination on every platform; Linux entries outside
an XDG applications directory are not automatically discovered by the desktop.
Keep Linux runners at their recorded paths; regenerate after moving them.

Choose current Python, a named environment from a chosen Conda installation,
or a custom Python executable. The launcher records and validates that exact
environment and passes opened file paths as command-line arguments. The target
script must accept those arguments. Python and dependencies are not bundled.
The target script and interpreter must remain at their recorded locations.
macOS supports Unicode names and paths, and its .app can be moved or renamed.
Regenerate existing launchers to apply changes. Creation prints the destination
and instructions for selecting the launcher as a file's Open With application;
it does not change default file associations automatically.

Requirements:
    - Windows 10+, macOS or a Linux X11/Wayland desktop; Python 3.13+.
    - macOS: osacompile and Terminal (built in).
    - Windows: gsudo or sudo (optional, for same-terminal elevation).
    - Linux: /bin/bash and a desktop terminal; update-desktop-database from
      desktop-file-utils (optional, for refreshing MIME recommendations).
    - Conda executable (only when selecting a Conda Python).

Usage:
    python script-to-app.py
    python script-to-app.py --target-script /path/to/tool.py --app-name MyTool
    python script-to-app.py --target-script /path/to/tool.py --output-dir /path/to/launchers
    python script-to-app.py --target-script /path/to/tool.py --mime-type text/plain --mime-type text/csv
    python script-to-app.py --target-script /path/to/tool.py --all-files
"""

import argparse
from enum import StrEnum
import os
import plistlib
import shlex
import sys
from typing import Optional, Union
from unicodedata import normalize
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402

SUBDIR = "PersonalScripts"
DESKTOP_CACHE_TIMEOUT = 15
LINUX_ALL_FILES_DESCRIPTION = "All files attempt (not guaranteed; no MIME restriction declared)"


class LinuxFileScope(StrEnum):
    """Linux file-selection modes offered by the interactive launcher builder."""

    MIME_TYPES = "mime-types"
    ALL_FILES = "all-files"

help_message = f'''
{FLYellow}Description:{CRst}
  Create a file's Open With launcher using a selected Python environment.
  Windows: `.cmd` in `%ProgramFiles%/PersonalScripts`; tries elevation first.
  macOS: `.app` in `~/Applications/PersonalScripts`; opens Terminal, no elevation.
  Linux desktop: .desktop and .desktop.sh in
  $XDG_DATA_HOME/applications/PersonalScripts (default ~/.local/share/...);
  opens the desktop's terminal, without elevation. Requires X11 or Wayland.
  Override the destination with --output-dir. Creation prints the full path.
  Choose current Python, custom Conda Python, custom Python, or exit.
  Custom Conda selection asks for its executable and an environment name.
  Invalid selections return to the menu; missing runtime/script errors remain
  visible when opening a generated launcher. Bundled apps need external Python.
  File paths are passed as arguments; the target script must accept them.
  Python and dependencies are referenced, not packaged. The target script and
  interpreter must stay in place. macOS app names and paths support Unicode;
  its .app can be moved or renamed. Regenerate launchers to apply fixes.
  Default file associations are chosen manually after creation.
  Linux offers: enter one or more MIME types, or try all files (not guaranteed).
  MIME examples: text/plain; text/csv; image/png; application/pdf.
  CLI: repeat --mime-type, or use --all-files; these options cannot be combined.
  All-files mode declares no MIME restriction. Choose it under Other / All
  Applications; availability and recommendations depend on the file manager.
  No wildcard type, MIME definitions or default associations are installed.
  Linux .desktop entries outside XDG applications directories may not appear
  in Open With. Keep companion runners in place or regenerate the launcher.

{FLYellow}Usage:{CRst}
  python script-to-app.py
  python script-to-app.py --target-script /path/to/tool.py --app-name MyTool
  python script-to-app.py --target-script /path/to/tool.py --output-dir /path/to/launchers
  python script-to-app.py --target-script /path/to/tool.py --mime-type text/plain --mime-type text/csv
  python script-to-app.py --target-script /path/to/tool.py --all-files

{FLYellow}Requirements:{CRst}
  Windows 10+, macOS or a Linux X11/Wayland desktop; Python 3.13+.
  macOS: osacompile and Terminal (included with macOS).
  Windows: gsudo or sudo (optional, for elevation); if unavailable, choose a
  writable `--output-dir` or run as Administrator.
  Conda executable (required only when selecting a Conda Python).
  Linux: /bin/bash and a desktop terminal; update-desktop-database from
  desktop-file-utils (optional, for refreshing MIME recommendations).
'''


def _build_arg_parser() -> argparse.ArgumentParser:
    """Return the shared CLI parser, including platform defaults in its help."""
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}SCRIPT TO APP{CRst}",
        epilog=help_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target-script", help="Python script to wrap; prompts when omitted")
    parser.add_argument("--app-name", help="Launcher filename; defaults to the script name")
    parser.add_argument(
        "--output-dir",
        help="Destination directory (Windows: %%ProgramFiles%%/PersonalScripts; "
             "macOS: ~/Applications/PersonalScripts; Linux: XDG applications/PersonalScripts)",
    )
    file_scope = parser.add_mutually_exclusive_group()
    file_scope.add_argument(
        "--mime-type", action="append", type=_validate_mime_type, default=None,
        help="Linux only: supported MIME type; repeat for multiple types. Otherwise choose interactively",
    )
    file_scope.add_argument(
        "--all-files", action="store_true",
        help="Linux only: try an unrestricted manual candidate for all files; visibility is not guaranteed",
    )
    return parser


def _title_case(name: str) -> str:
    """Return a compact default launcher name from a script filename stem."""
    return name.replace("_", " ").replace("-", " ").title().replace(" ", "")


def _resolve_target_script(arg_value: Optional[str]) -> str:
    """Resolve a supplied or prompted .py file, exiting on an invalid target."""
    if arg_value:
        p = os.path.abspath(os.path.expanduser(arg_value))
        if not os.path.isfile(p):
            Console.print_error_and_exit(f"Target script not found: {p}")
        if os.path.splitext(p)[1].lower() != ".py":
            Console.print_error_and_exit(f"Target script must be a .py file: {p}")
        return p
    p = Input.resolve_input_path(
        default_path=os.path.expanduser("~"),
        prompt="Path to the Python script to wrap",
        path_type="file",
    )
    if os.path.splitext(p)[1].lower() != ".py":
        Console.print_error_and_exit(f"Target script must be a .py file: {p}")
    return p


def _resolve_app_name(arg_value: Optional[str], script_path: str) -> str:
    """Return the supplied name or prompt using the target filename as default."""
    if arg_value:
        return arg_value
    stem = os.path.splitext(os.path.basename(script_path))[0]
    default_name = _title_case(stem)
    name = input(
        f"{FLYellow}Launcher name {FGray}[{default_name}]{CRst}: "
    ).strip()
    return name or default_name


def _launcher_suffix() -> str:
    """Return the launcher extension for the already validated host platform."""
    if sys.platform == "win32":
        return ".cmd"
    return ".desktop" if sys.platform == "linux" else ".app"


def _linux_data_home() -> str:
    """Return the absolute XDG user data directory, ignoring invalid relative values."""
    configured = os.environ.get("XDG_DATA_HOME", "")
    return os.path.normpath(configured) if os.path.isabs(configured) else os.path.expanduser("~/.local/share")


def _validate_mime_type(value: str) -> str:
    """Validate one concrete MIME type without parameters, wildcards or delimiters.

    Args:
        value: MIME type such as text/plain, optionally surrounded by whitespace.

    Returns:
        Lowercase MIME type suitable for the desktop entry's semicolon list.

    Raises:
        argparse.ArgumentTypeError: The input is not a concrete type/subtype.
    """
    value = value.strip().lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*", value) is None:
        raise argparse.ArgumentTypeError(f"Invalid MIME type: {value!r}. Use a concrete type such as text/plain.")
    return value


def _select_linux_mime_types(values: list[str] | None, *, all_files: bool = False) -> tuple[str, ...]:
    """Choose specific MIME types or an unrestricted manual application candidate.

    Args:
        values: Optional repeated CLI values, already checked by argparse.
        all_files: Explicit CLI choice to omit MIME declarations; mutually
            exclusive with values at the argument-parser level.

    Returns:
        Deduplicated MIME types in input order. An empty tuple means the user
        explicitly selected the all-files attempt, not a wildcard MIME type.

    Side effects:
        Shows a mode menu, examples and validation errors unless a CLI mode
        was supplied. Empty MIME input is rejected; B returns to the mode menu.
    """
    if values:
        return tuple(dict.fromkeys(values))
    if all_files:
        return ()
    while True:
        scope = Menu.select([
            MenuOption(["1"], "Enter MIME types (one or more, with examples)", LinuxFileScope.MIME_TYPES),
            MenuOption(["2"], "Try all files (not guaranteed)", LinuxFileScope.ALL_FILES),
        ], prompt="File types", default_key="1")
        if scope == LinuxFileScope.ALL_FILES:
            return ()
        print(f"{FGray}Examples: text/plain (text), text/csv (CSV), image/png (PNG), application/pdf (PDF).{CRst}")
        print(f"{FGray}Multiple types: text/plain; text/csv; application/pdf{CRst}")
        while True:
            value = input(f"{FLYellow}MIME types (semicolon-separated; B = back) > {CRst}").strip()
            if value.casefold() == "b":
                break
            try:
                parts = [part.strip() for part in value.split(";") if part.strip()]
                if not parts:
                    raise argparse.ArgumentTypeError("Enter at least one MIME type, or B to choose another mode.")
                return tuple(dict.fromkeys(_validate_mime_type(part) for part in parts))
            except argparse.ArgumentTypeError as exc:
                print(f"{FLRed}{exc}{CRst}")


def _resolve_output_dir(arg_value: str | None) -> str:
    """Resolve a destination override or the current platform's default.

    Args:
        arg_value: Optional directory, with relative paths based on the current
            working directory and a leading tilde expanded.

    Returns:
        Absolute output directory. Defaults to the user's Applications folder
        on macOS, Program Files on Windows or XDG user applications on Linux,
        each containing PersonalScripts.
    """
    if arg_value:
        return Paths.resolve_path(os.path.expanduser(arg_value), os.getcwd(),
                                  expand_environment=False)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Applications/{SUBDIR}")
    if sys.platform == "linux":
        return os.path.join(_linux_data_home(), "applications", SUBDIR)
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), SUBDIR)


def _resolve_launcher_path(output_dir: str, app_name: str) -> str | None:
    """Choose a launcher filename inside the destination, confirming overwrites.

    Args:
        output_dir: Destination directory.
        app_name: Suggested filename, with or without its platform suffix.

    Returns:
        Absolute launcher path, or None when the user cancels. No files change.

    Raises:
        SystemExit: The name points outside the destination directory.

    Side effects:
        Prompts when the destination already exists and prints validation errors.
    """
    suffix = _launcher_suffix()
    while True:
        has_suffix = (app_name.lower().endswith(suffix) if sys.platform == "win32"
                      else app_name.endswith(suffix))
        if not has_suffix:
            app_name += suffix
        launcher_path = os.path.abspath(os.path.join(output_dir, app_name))
        if os.path.normcase(os.path.dirname(launcher_path)) != os.path.normcase(os.path.abspath(output_dir)):
            Console.print_error_and_exit("App name must be a filename inside the output directory.")
        existing_paths = [launcher_path]
        if sys.platform == "linux":
            existing_paths.append(f"{launcher_path}.sh")
        existing_paths = [path for path in existing_paths if os.path.lexists(path)]
        if not existing_paths:
            return launcher_path
        for path in existing_paths:
            print(f"\n{FLYellow}{path}{CRst} {FLRed}already exists.{CRst}")
        choice = input("Overwrite? [y/N] or enter a new name: ").strip()
        if choice.lower() in ("y", "yes"):
            return launcher_path
        if not choice:
            return None
        app_name = choice


def _escape_cmd_set_value(value: str) -> str:
    """Escape a value embedded in a batch ``set "NAME=value"`` statement."""
    return value.replace("%", "%%")


def _select_python_environment() -> tuple[PythonEnvironment, str | None] | None:
    """Use the shared cross-platform environment selection menu."""
    return Environment.select_python_environment()


def _build_launcher_content(
    target_script: str, runtime: PythonEnvironment | None = None,
    conda_executable: str | None = None,
) -> str:
    """Build Windows CMD text pinned to the selected interpreter and environment."""
    runtime = runtime or Environment.get_python_environment()
    if runtime.frozen:
        raise ValueError("A bundled application is not a Python interpreter. Run this source with the desired Python.")
    if runtime.conda_env is not None:
        conda_executable = conda_executable or Environment.find_conda_executable()
        if conda_executable is None:
            raise ValueError("Cannot find conda.exe for this Conda Python. Make Conda available and regenerate the launcher.")
    escaped_python_exe = _escape_cmd_set_value(runtime.executable)
    escaped_target_script = _escape_cmd_set_value(target_script)
    prefix = _escape_cmd_set_value(runtime.prefix)
    conda_name = _escape_cmd_set_value(runtime.conda_env or "")
    conda_runner = _escape_cmd_set_value(conda_executable or "")
    python_command = '"%ZL_APP_PYTHON%"'
    conda_checks = ""
    if runtime.conda_env is not None:
        python_command = '"%ZL_APP_CONDA%" run --no-capture-output --prefix "%ZL_APP_PREFIX%" "%ZL_APP_PYTHON%"'
        conda_checks = '''if not exist "%ZL_APP_CONDA%" goto environment_error
if not exist "%ZL_APP_PREFIX%\\conda-meta\\" goto environment_error
'''
    probe = (
        "import os,sys; "
        "sys.exit(not (os.path.normcase(os.path.realpath(sys.prefix)) == "
        "os.path.normcase(os.path.realpath(sys.argv[1])) and "
        "os.path.isdir(os.path.join(sys.prefix, 'conda-meta')) == (sys.argv[2] == '1')))"
    )
    is_conda = "1" if runtime.conda_env is not None else "0"
    return f'''@echo off
setlocal DisableDelayedExpansion
REM ============================================
REM  Python script launcher generated by script-to-app.py
REM ============================================

chcp 65001 >nul

set "ZL_APP_PYTHON={escaped_python_exe}"
set "ZL_APP_TARGET={escaped_target_script}"
set "ZL_APP_PREFIX={prefix}"
set "ZL_APP_CONDA_NAME={conda_name}"
set "ZL_APP_CONDA={conda_runner}"

if not exist "%ZL_APP_TARGET%" goto script_error
if exist "%ZL_APP_TARGET%\\" goto script_error
if not exist "%ZL_APP_PYTHON%" goto environment_error
{conda_checks}{python_command} -I -c "{probe}" "%ZL_APP_PREFIX%" {is_conda}
if not "%ERRORLEVEL%"=="0" goto environment_error

{python_command} -E "%ZL_APP_TARGET%" %*
set "ZL_APP_EXIT_CODE=%ERRORLEVEL%"
if not "%ZL_APP_EXIT_CODE%"=="0" goto execution_error
if "%~1"=="" pause
exit /b 0

:script_error
echo ERROR: Target script is missing or is not a file: "%ZL_APP_TARGET%"
goto invalid_launcher

:environment_error
echo ERROR: The recorded Python environment is missing, changed, or cannot start.
echo Python: "%ZL_APP_PYTHON%"
echo Environment directory: "%ZL_APP_PREFIX%"
if defined ZL_APP_CONDA_NAME echo Conda environment: "%ZL_APP_CONDA_NAME%"
goto invalid_launcher

:invalid_launcher
echo Delete this .cmd file and regenerate it using script-to-app.py with the intended Python environment.
echo Launcher: "%~f0"
pause
exit /b 1

:execution_error
echo.
echo Script execution failed with exit code: %ZL_APP_EXIT_CODE%
pause
exit /b %ZL_APP_EXIT_CODE%
'''


def _write_launcher(
    launcher_path: str, target_script: str, runtime: PythonEnvironment | None = None,
    conda_executable: str | None = None,
) -> None:
    content = _build_launcher_content(target_script, runtime, conda_executable)
    with open(launcher_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)

def _build_bundle_id(app_name: str) -> str:
    """Build a stable ASCII bundle identifier independently of the display name.

    Args:
        app_name: Application filename, including its optional .app suffix.
            Unicode, whitespace and punctuation are accepted.

    Returns:
        Reverse-DNS identifier containing only ASCII letters, digits, periods
        and hyphens. Canonically equivalent Unicode names share an identifier;
        distinct names are hashed rather than stripped to a common fallback.
    """
    name = normalize("NFC", app_name.removesuffix(".app"))
    identifier = uuid5(NAMESPACE_URL, f"script-to-app:{name}")
    return f"com.script-to-app.{identifier}"


def _format_process_output(value: Optional[Union[bytes, str]]) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()

def _build_shell_launcher(
    target_script: str, runtime: PythonEnvironment, conda_executable: str | None,
    *, launcher_description: str = ".app",
) -> str:
    """Build a macOS/Linux Bash runner preserving arguments and exit codes.

    Args:
        target_script: Absolute path to the Python script.
        runtime: Validated interpreter identity to record.
        conda_executable: Conda command, required for Conda environments.
        launcher_description: Human-readable artifact name in recovery advice.

    Returns:
        Bash source with exact runtime validation and safely quoted file paths.

    Raises:
        ValueError: The runtime is frozen or its required Conda command is absent.
    """
    if runtime.frozen:
        raise ValueError("Select an external Python interpreter for a bundled application.")
    command = [runtime.executable]
    if runtime.conda_env is not None:
        if not conda_executable:
            raise ValueError("A Conda executable is required for the selected environment.")
        command = [conda_executable, "run", "--no-capture-output", "--prefix", runtime.prefix, *command]
    invocation = shlex.join(command)
    check = (
        "import os,sys; sys.exit(not (os.path.realpath(sys.prefix) == "
        "os.path.realpath(sys.argv[1]) and os.path.isdir(os.path.join(sys.prefix, "
        "'conda-meta')) == (sys.argv[2] == '1')))"
    )
    probe = shlex.join(["-I", "-c", check, runtime.prefix, "1" if runtime.conda_env is not None else "0"])
    recovery = shlex.quote(
        f"Delete this {launcher_description} and regenerate it using script-to-app.py with the intended Python environment."
    )
    return f'''#!/bin/bash
invalid_launcher() {{
    printf '%s\\n' "$1" {recovery}
    read -r -p 'Press Enter to close...' || true
    exit 1
}}
[[ -f {shlex.quote(target_script)} ]] || invalid_launcher 'ERROR: Target script is missing or is not a file.'
[[ -x {shlex.quote(runtime.executable)} ]] || invalid_launcher 'ERROR: The selected Python executable is unavailable.'
{invocation} {probe} || invalid_launcher 'ERROR: The recorded Python environment is missing, changed, or cannot start.'
cd -- {shlex.quote(os.path.dirname(target_script))} || invalid_launcher 'ERROR: Cannot access the script directory.'
{invocation} -E {shlex.quote(target_script)} "$@"
ZL_APP_EXIT_CODE=$?
if [[ "$ZL_APP_EXIT_CODE" -ne 0 ]]; then
    printf 'Script execution failed with exit code: %s\\n' "$ZL_APP_EXIT_CODE"
    read -r -p 'Press Enter to close...' || true
fi
exit "$ZL_APP_EXIT_CODE"
'''


def _create_app_bundle(
    app_path: str, target_script: str, runtime: PythonEnvironment,
    conda_executable: str | None,
) -> None:
    """Create the .app using osacompile so it receives Apple Events (odoc).

    Uses ``osacompile`` to build a native AppleScript applet with both
    ``on run`` (direct launch) and ``on open`` (drag-and-drop / "Open With"
    from Finder) handlers. The app resolves its internal runner at launch so
    moving or renaming the bundle does not invalidate its resource path.
    """
    import tempfile
    import subprocess

    runner = _build_shell_launcher(target_script, runtime, conda_executable)
    runner_path = os.path.join(app_path, "Contents", "Resources", "python-launcher.sh")

    # AppleScript applet — needs both on run AND on open to receive files
    # from Finder's "Open With" context menu (which sends an odoc Apple Event).
    #
    # We avoid "tell application Terminal" because it triggers a TCC
    # automation permission prompt (-1743). Instead we write the command
    # to a temp .command file and use "open -a Terminal" to run it.
    applescript = f'''\
on runPythonScript(fileArgs)
    set bundlePath to POSIX path of (path to me)
    set runnerPath to bundlePath & "Contents/Resources/python-launcher.sh"
    set shellCmd to "/bin/bash " & quoted form of runnerPath
    repeat with a in fileArgs
        set shellCmd to shellCmd & " " & quoted form of a
    end repeat
    set scriptContent to "#!/bin/bash" & linefeed & "trap 'rm -f -- \\"$0\\"' EXIT" & linefeed & shellCmd & linefeed
    set tmpPath to "/tmp/script_launcher_" & (do shell script "uuidgen") & ".command"
    do shell script "printf '%s' " & quoted form of scriptContent & " > " & quoted form of tmpPath & " && chmod +x " & quoted form of tmpPath & " && open -a Terminal " & quoted form of tmpPath
end runPythonScript

on run argv
    runPythonScript(argv)
end run

on open theFiles
    set fileArgs to {{}}
    repeat with f in theFiles
        set end of fileArgs to POSIX path of f
    end repeat
    runPythonScript(fileArgs)
end open'''

    # Write AppleScript to a temp file, then compile into the .app bundle.
    # Keep the script readable so generated apps can be inspected/debugged.
    fd, tmp_path = tempfile.mkstemp(suffix=".applescript")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(applescript)
        try:
            subprocess.run(
                ["osacompile", "-o", app_path, tmp_path],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = _format_process_output(e.stderr)
            stdout = _format_process_output(e.stdout)
            detail = stderr or stdout or str(e)
            Console.print_error_and_exit(f"osacompile failed: {detail}")
    finally:
        os.unlink(tmp_path)

    os.makedirs(os.path.dirname(runner_path), exist_ok=True)
    with open(runner_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(runner)


def _write_info_plist(app_contents: str, app_name: str, bundle_id: str) -> None:
    """Update the Info.plist (created by osacompile) with custom keys.

    Reads the existing plist to preserve keys set by osacompile
    (e.g. CFBundleExecutable) and merges our additions on top.
    """
    plist_path = os.path.join(app_contents, "Info.plist")
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    display_name = app_name.removesuffix(".app")
    plist.update({
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": display_name,
        "CFBundleDisplayName": display_name,
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "All Files",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [
                    "public.item",
                    "public.data",
                    "public.content",
                    "public.text",
                    "public.html",
                    "public.xhtml",
                ],
            }
        ],
    })

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)


def _desktop_string(value: str) -> str:
    """Escape a desktop-entry scalar value without interpreting its Unicode text."""
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace("\r", "\\r").replace("\t", "\\t"))


def _desktop_exec_argument(value: str) -> str:
    """Quote one literal Exec argument using desktop-entry rules, not shell rules.

    Args:
        value: Literal executable or argument path, potentially containing spaces,
            Unicode, quotes, dollar signs, backticks, backslashes or percent signs.

    Returns:
        Double-quoted argument with Exec-level escaping followed by key-file
        escaping. Literal percent signs become %% to avoid field-code expansion.
        File field codes such as %F must be appended separately, without quotes.
    """
    escaped = "".join(f"\\{char}" if char in '\\"`$' else char for char in value)
    return _desktop_string(f'"{escaped.replace("%", "%%")}"')


def _write_linux_launcher(
    launcher_path: str, target_script: str, runtime: PythonEnvironment,
    conda_executable: str | None, mime_types: tuple[str, ...],
) -> None:
    """Write a desktop entry and a companion Bash runner at the chosen paths.

    Args:
        launcher_path: Absolute .desktop destination; its parent must exist.
        target_script: Absolute Python script path.
        runtime: Selected interpreter identity.
        conda_executable: Required only for Conda Python.
        mime_types: Validated concrete types recognized by the file manager,
            or an empty tuple for the all-files attempt (no MimeType key).

    Side effects:
        Writes UTF-8/LF files and enables owner execution. The desktop opens a
        terminal and passes all selected local files as separate arguments.
        Existing files are overwritten only after the caller's confirmation.

    Raises:
        OSError: A destination cannot be written or its permissions cannot be set.
        ValueError: The selected runtime cannot be used by a generated launcher.
    """
    runner_path = f"{launcher_path}.sh"
    runner = _build_shell_launcher(
        target_script, runtime, conda_executable,
        launcher_description=".desktop launcher and its companion .desktop.sh file",
    )
    name = os.path.basename(launcher_path).removesuffix(".desktop")
    mime_list = ";".join(mime_types)
    content = (
        f"[Desktop Entry]\nType=Application\nVersion=1.0\n"
        f"Name={_desktop_string(name)}\n"
        f"Comment=Open files with a Python script\n"
        f"Exec=/bin/bash {_desktop_exec_argument(runner_path)} %F\n"
        f"Terminal=true\nIcon=application-x-executable\nCategories=Utility;\n"
    )
    if mime_types:
        content += f"MimeType={mime_list};\n"
    with open(runner_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(runner)
    os.chmod(runner_path, 0o700)
    with open(launcher_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    os.chmod(launcher_path, 0o700)


def _refresh_linux_desktop_database(output_dir: str) -> None:
    """Refresh MIME recommendations, reporting optional-tool or discovery limits.

    Args:
        output_dir: Absolute directory containing the generated desktop entry.

    Side effects:
        Runs update-desktop-database, when available, on the containing XDG
        applications directory (or the explicit custom output directory).
        Prints warnings for unindexed locations or cache failures. Does not
        modify default file associations or install MIME type definitions.
    """
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    roots = [os.path.join(_linux_data_home(), "applications")]
    roots.extend(os.path.join(path, "applications") for path in data_dirs.split(os.pathsep) if os.path.isabs(path))
    output_dir = os.path.realpath(output_dir)
    root = next((path for path in roots if os.path.commonpath((os.path.realpath(path), output_dir))
                 == os.path.realpath(path)), None)
    if root is None:
        print(f"{FLYellow}Custom output is outside XDG applications directories; it may not appear in Open With.{CRst}")
        print(f"{FLYellow}Regenerate without --output-dir to install it in your user applications directory.{CRst}")
    updater = Environment.which("update-desktop-database")
    cache_dir = root or output_dir
    if updater is None:
        print(f"{FLYellow}Optional update-desktop-database is unavailable; MIME recommendations may need a refresh.{CRst}")
        print(f"{FLYellow}When available, run: {shlex.join(['update-desktop-database', cache_dir])}{CRst}")
        return
    try:
        result = subprocess.run(
            [updater, cache_dir], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=DESKTOP_CACHE_TIMEOUT, check=False,
        )
        if result.returncode:
            print(f"{FLYellow}Desktop MIME cache refresh failed: {result.stderr.strip() or result.returncode}{CRst}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"{FLYellow}Desktop entry was created, but its MIME cache could not be refreshed: {exc}{CRst}")


def main(argv: list[str] | None = None) -> int:
    """Interactively create the current platform's Open With launcher.

    Args:
        argv: Optional CLI arguments; None uses sys.argv[1:].

    Returns:
        Zero after creation or cancellation.

    Raises:
        SystemExit: Unsupported platform, invalid arguments, invalid target or
            destination, permission failure, or AppleScript compilation failure.

    Side effects:
        Prompts for paths, runtime and confirmation. Windows may relaunch with
        elevation. Writes the launcher after confirmation; registers macOS apps
        with Launch Services or refreshes Linux desktop MIME recommendations,
        and prints the resulting paths and usage instructions.
    """
    Console.print_banner("SCRIPT TO APP")
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if sys.platform not in ("win32", "darwin", "linux"):
        Console.print_error_and_exit("This script supports Windows, macOS and Linux desktops only.")
    windows = sys.platform == "win32"
    linux = sys.platform == "linux"
    suffix = _launcher_suffix()
    if (args.mime_type is not None or args.all_files) and not linux:
        parser.error("--mime-type and --all-files are supported on Linux only")
    if linux:
        if System.get_linux_gui() not in (LinuxGui.X11, LinuxGui.WAYLAND):
            Console.print_error_and_exit("A Linux X11 or Wayland desktop session is required (DISPLAY or WAYLAND_DISPLAY).")
        if not Environment.check_commands(CmdCheck("/bin/bash", required=True)):
            Console.print_error_and_exit("Linux desktop launchers require /bin/bash.")

    # ── Windows elevation ─────────────────────────────────
    if windows and not System.is_elevated():
        original_argv = sys.argv
        sys.argv = [os.path.abspath(__file__), *(sys.argv[1:] if argv is None else argv)]
        try:
            elevated = System.try_restart_elevated()
        finally:
            sys.argv = original_argv
        if not elevated:
            print(
                f"{FLYellow}Elevation unavailable. Continuing with current permissions; "
                f"use a writable --output-dir if needed.{CRst}"
            )

    # ── shared inputs and interpreter selection ───────────
    if not (sys.argv[1:] if argv is None else argv):
        print(help_message)
    target_script = _resolve_target_script(args.target_script)
    app_name = _resolve_app_name(args.app_name, target_script)
    output_dir = _resolve_output_dir(args.output_dir)
    launcher_path = _resolve_launcher_path(output_dir, app_name)
    if launcher_path is None:
        print(f"{FLYellow}Cancelled.{CRst}")
        return 0
    mime_types = _select_linux_mime_types(args.mime_type, all_files=args.all_files) if linux else ()
    selection = _select_python_environment()
    if selection is None:
        print(f"{FLYellow}Cancelled.{CRst}")
        return 0
    runtime, conda_executable = selection

    # ── confirm the exact runtime and destination ─────────
    print()
    print(f"{FLYellow}  Target script  :{CRst} {FLCyan}{target_script}{CRst}")
    print(f"{FLYellow}  Launcher path  :{CRst} {FLCyan}{launcher_path}{CRst}")
    if linux:
        print(f"{FLYellow}  Runner path    :{CRst} {FLCyan}{launcher_path}.sh{CRst}")
        scope_description = '; '.join(mime_types) if mime_types else LINUX_ALL_FILES_DESCRIPTION
        print(f"{FLYellow}  File types     :{CRst} {FLCyan}{scope_description}{CRst}")
    environment_type = "Conda" if runtime.conda_env is not None else "Non-Conda Python"
    print(f"{FLYellow}  Environment    :{CRst} {FLCyan}{environment_type}{CRst}")
    print(f"{FLYellow}  Python version :{CRst} {FLCyan}{runtime.version}{CRst}")
    print(f"{FLYellow}  Python path    :{CRst} {FLCyan}{runtime.executable}{CRst}")
    print(f"{FLYellow}  Environment dir:{CRst} {FLCyan}{runtime.prefix}{CRst}")
    if runtime.conda_env is not None:
        print(f"{FLYellow}  Conda env      :{CRst} {FLCyan}{runtime.conda_env}{CRst}")
        print(f"{FLYellow}  Conda path     :{CRst} {FLCyan}{conda_executable}{CRst}")
    confirm = input(f"\n{FLYellow}Create this {suffix} launcher?{CRst} [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        print(f"{FLYellow}Cancelled.{CRst}")
        return 0

    # ── platform-specific output ──────────────────────────
    try:
        os.makedirs(output_dir, exist_ok=True)
        if windows:
            _write_launcher(launcher_path, target_script, runtime, conda_executable)
        elif linux:
            _write_linux_launcher(launcher_path, target_script, runtime, conda_executable, mime_types)
            _refresh_linux_desktop_database(output_dir)
        else:
            if os.path.exists(launcher_path):
                shutil.rmtree(launcher_path)
            _create_app_bundle(launcher_path, target_script, runtime, conda_executable)
            app_name = os.path.basename(launcher_path)
            _write_info_plist(
                os.path.join(launcher_path, "Contents"), app_name, _build_bundle_id(app_name),
            )
            lsregister = (
                "/System/Library/Frameworks/CoreServices.framework"
                "/Frameworks/LaunchServices.framework/Support/lsregister"
            )
            if os.path.exists(lsregister):
                subprocess.run([lsregister, "-f", launcher_path], capture_output=True)
    except PermissionError:
        advice = ("Run as Administrator or use a writable --output-dir."
                  if windows else "Use a writable --output-dir.")
        Console.print_error_and_exit(f"Permission denied: {output_dir}. {advice}")

    # ── creation result and file association instructions ─
    print(f"{FLGreen}Created:{CRst} {FLCyan}{launcher_path}{CRst}")
    if linux:
        print(f"{FLGreen}Runner:{CRst} {FLCyan}{launcher_path}.sh{CRst}")
    print(f"\n{FLYellow}Usage:{CRst}")
    if windows:
        print("  Right-click a file -> Open with -> Choose another app ->")
        print(f"  select {FLCyan}{launcher_path}{CRst}")
    elif linux:
        name = os.path.basename(launcher_path).removesuffix(".desktop")
        if mime_types:
            print("  In your file manager: right-click a matching file -> Open With ->")
        else:
            print("  In your file manager: right-click a file -> Open With -> Other / All Applications ->")
            print(f"{FLYellow}  All-files availability is not guaranteed; the file manager may still filter this application.{CRst}")
        print(f"  choose {FLCyan}{name}{CRst}. Set it as default in file properties if desired.")
    else:
        print("  Right-click a file in Finder -> Get Info -> Open With ->")
        print(f"  select {FLCyan}{launcher_path}{CRst}, then click {FLYellow}Change All...{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
