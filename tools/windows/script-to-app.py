#!/usr/bin/env python3
"""Create a Windows .cmd launcher for a Python script under Program Files.

Try same-terminal elevation before prompting; writable output directories can
still be used when elevation is unavailable.
Select the current Python, a named environment from a chosen Conda installation,
or a custom Python executable. Invalid selections return to the menu.
Record the selected interpreter and, for Conda, its name and exact prefix.
Launchers validate that environment and the target before running, and keep
errors visible with instructions to delete and regenerate an invalid launcher.

Requirements:
    - Windows 10+ and Python 3.13+.
    - system: gsudo or sudo (optional, for same-terminal elevation).
    - system: conda.exe (required only when selecting a Conda Python).

Usage:
    python script-to-app.py
    python script-to-app.py --target-script C:/tools/my-tool.py --app-name MyTool
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *

import argparse
from typing import Optional


SUBDIR = "PersonalScripts"


help_message = f'''
{FLYellow}Description:{CRst}
  Create a Windows .cmd launcher for a Python script under Program Files.
  The generated .cmd can be selected from "Open with" and receives opened
  file paths as command-line arguments.
  Choose current Python, custom Conda Python, custom Python, or exit before confirming.
  Custom Conda selection asks for conda.exe and an environment name; invalid
  executables or environments return to the selection menu.
  Records the selected Python interpreter, or its exact Conda environment and name.
  Invalid environments or missing scripts display an error and regeneration advice.
  Bundled executables must select an external Python interpreter.

{FLYellow}Examples:{CRst}
  {FGray}# Full CLI usage{CRst}
  python script-to-app.py --target-script C:\\tools\\my-tool.py --app-name MyTool

  {FGray}# Interactive mode (no arguments){CRst}
  python script-to-app.py

{FLYellow}Requirements:{CRst}
  Windows 10+ and Python 3.13+.
  gsudo or sudo (optional): tries same-terminal elevation before prompting.
  conda.exe (required only for a Conda Python environment).
  If elevation is unavailable, use a writable --output-dir or run as Administrator.
'''


def _title_case(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title().replace(" ", "")


def _escape_cmd_set_value(value: str) -> str:
    """Escape a value embedded in a batch ``set "NAME=value"`` statement."""
    return value.replace("%", "%%")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a Windows .cmd launcher wrapping a Python script.",
        epilog=help_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target-script", dest="target_script",
        help="Path to the Python script to wrap into a .cmd launcher",
    )
    parser.add_argument(
        "--app-name", dest="app_name",
        help="Name for the .cmd launcher (default: derived from script filename)",
    )
    parser.add_argument(
        "--output-dir", dest="output_dir",
        help=r"Directory for the launcher (default: %%ProgramFiles%%\PersonalScripts)",
    )
    return parser


def _resolve_target_script(arg_value: Optional[str]) -> str:
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
    if arg_value:
        return arg_value
    stem = os.path.splitext(os.path.basename(script_path))[0]
    default_name = _title_case(stem)
    name = input(
        f"{FLYellow}Launcher name {FGray}[{default_name}]{CRst}: "
    ).strip()
    return name or default_name


def _resolve_output_dir(arg_value: Optional[str]) -> str:
    if arg_value:
        return os.path.abspath(os.path.expanduser(arg_value))
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return os.path.join(program_files, SUBDIR)


def _select_python_environment() -> tuple[PythonEnvironment, str | None] | None:
    """Use the shared cross-platform environment selection menu."""
    return Environment.select_python_environment()


def _build_launcher_content(
    target_script: str, runtime: PythonEnvironment | None = None,
    conda_executable: str | None = None,
) -> str:
    """Build a launcher pinned to the current interpreter and environment."""
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


def main(argv: Optional[list[str]] = None) -> int:
    Console.print_banner("SCRIPT TO APP")

    if sys.platform != "win32":
        Console.print_error_and_exit("This script only works on Windows.")

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not System.is_elevated():
        # The shared helper replays sys.argv, including calls through main(argv).
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

    if len(sys.argv) == 1:
        print(help_message)

    target_script = _resolve_target_script(args.target_script)
    app_name = _resolve_app_name(args.app_name, target_script)

    if not app_name.lower().endswith(".cmd"):
        app_name += ".cmd"

    output_dir = _resolve_output_dir(args.output_dir)
    launcher_path = os.path.join(output_dir, app_name)

    while os.path.exists(launcher_path):
        print()
        print(f"{FLYellow}{launcher_path}{CRst} {FLRed}already exists.{CRst}")
        choice = input(f"Overwrite? [y/N] or enter a new name: ").strip()
        if choice.lower() in ("y", "yes"):
            break
        elif choice:
            if not choice.lower().endswith(".cmd"):
                choice += ".cmd"
            launcher_path = os.path.join(output_dir, choice)
        else:
            print(f"{FLRed}Cancelled.{CRst}")
            return 0

    selection = _select_python_environment()
    if selection is None:
        print(f"{FLYellow}Cancelled.{CRst}")
        return 0
    runtime, conda_executable = selection

    print()
    print(f"{FLYellow}  Target script  :{CRst} {FLCyan}{target_script}{CRst}")
    print(f"{FLYellow}  Launcher path  :{CRst} {FLCyan}{launcher_path}{CRst}")
    environment_type = "Conda" if runtime.conda_env is not None else "Non-Conda Python"
    print(f"{FLYellow}  Environment    :{CRst} {FLCyan}{environment_type}{CRst}")
    print(f"{FLYellow}  Python version :{CRst} {FLCyan}{runtime.version}{CRst}")
    print(f"{FLYellow}  Python path    :{CRst} {FLCyan}{runtime.executable}{CRst}")
    print(f"{FLYellow}  Environment dir:{CRst} {FLCyan}{runtime.prefix}{CRst}")
    if runtime.conda_env is not None:
        print(f"{FLYellow}  Conda env      :{CRst} {FLCyan}{runtime.conda_env}{CRst}")
        print(f"{FLYellow}  Conda path     :{CRst} {FLCyan}{conda_executable}{CRst}")
    print()

    confirm = input(f"{FLYellow}Create this .cmd launcher?{CRst} [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        print(f"{FLRed}Cancelled.{CRst}")
        return 0

    try:
        os.makedirs(output_dir, exist_ok=True)
        _write_launcher(launcher_path, target_script, runtime, conda_executable)
    except PermissionError:
        Console.print_error_and_exit(
            f"Permission denied: {output_dir}. Run this script as Administrator or use --output-dir."
        )

    print(f"{FLGreen}Created:{CRst} {FLCyan}{launcher_path}{CRst}")
    print()
    print(f"{FLYellow}Usage:{CRst}")
    print("  Right-click a file -> Open with -> Choose another app ->")
    print(f"  select {FLCyan}{launcher_path}{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
