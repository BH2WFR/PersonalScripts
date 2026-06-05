import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

import argparse
import shlex
import plistlib


help_message = f'''
{FLYellow}==================== SCRIPT TO APP ===================={CRst}
{FLYellow}Description:{CRst}
  Create a macOS .app bundle that wraps a Python script as a
  double-clickable application.  The generated .app can be
  associated with file types via Finder "Get Info" -> "Open With".

  When launched, the .app opens a Terminal window and runs the
  target Python script, passing any file paths as arguments.

{FLYellow}Examples:{CRst}
  {FGray}# Full CLI usage{CRst}
  python script-to-app.py --target-script ~/my-tool.py --app-name MyTool

  {FGray}# Interactive mode (no arguments){CRst}
  python script-to-app.py

{FLYellow}macOS only.{CRst}
'''


def _title_case(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title().replace(" ", "")


def _escape_applescript(s: str) -> str:
    """Escape a string for embedding in an AppleScript double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a macOS .app bundle wrapping a Python script.",
        epilog=help_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target-script", dest="target_script",
        help="Path to the Python script to wrap into an .app",
    )
    parser.add_argument(
        "--app-name", dest="app_name",
        help="Name for the .app bundle (default: derived from script filename)",
    )
    return parser


def _resolve_target_script(arg_value: str | None) -> str:
    if arg_value:
        p = os.path.abspath(os.path.expanduser(arg_value))
        if not os.path.isfile(p):
            Utils.print_error_and_exit(f"Target script not found: {p}")
        return p
    return Input.resolve_input_path(
        default_path=os.path.expanduser("~"),
        prompt="Path to the Python script to wrap",
        path_type="file",
    )


def _resolve_app_name(arg_value: str | None, script_path: str) -> str:
    if arg_value:
        return arg_value
    stem = os.path.splitext(os.path.basename(script_path))[0]
    default_name = _title_case(stem)
    name = input(
        f"{FLYellow}App name {FGray}[{default_name}]{CRst}: "
    ).strip()
    return name or default_name


def _write_launcher(app_contents: str, target_script: str) -> None:
    """Write the executable launcher script inside the .app bundle.

    The launcher uses osascript to open a Terminal window, then runs the
    target Python script with forwarded arguments (e.g. file paths from Finder).
    """
    macos_dir = os.path.join(app_contents, "MacOS")
    os.makedirs(macos_dir, exist_ok=True)
    launcher_path = os.path.join(macos_dir, "launcher")

    workdir = os.path.dirname(target_script)
    python_exe = sys.executable

    # Shell command that Terminal will execute
    shell_cmd = (
        f"cd {shlex.quote(workdir)} && "
        f"{shlex.quote(python_exe)} {shlex.quote(target_script)}"
    )

    # AppleScript fragment — shell_cmd is embedded as a string literal
    applescript = (
        "on run argv\n"
        '    tell application "Terminal"\n'
        "        activate\n"
        f'        set cmd to "{_escape_applescript(shell_cmd)}"\n'
        '        repeat with a in argv\n'
        '            set cmd to cmd & " " & quoted form of a\n'
        "        end repeat\n"
        '        do script cmd & "; exit"\n'
        "    end tell\n"
        "end run"
    )

    # shlex.quote wraps the entire AppleScript as a single shell argument to osascript -e
    script = f"#!/bin/bash\nexec osascript -e {shlex.quote(applescript)} -- \"$@\"\n"

    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(launcher_path, os.stat(launcher_path).st_mode | 0o111)


def _write_info_plist(app_contents: str, app_name: str, bundle_id: str) -> None:
    plist_path = os.path.join(app_contents, "Info.plist")
    display_name = app_name.replace(".app", "")
    plist = {
        "CFBundleExecutable": "launcher",
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": display_name,
        "CFBundleDisplayName": display_name,
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
    }
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "darwin":
        Utils.print_error_and_exit("This script only works on macOS.")

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if len(sys.argv) == 1:
        print(help_message)

    # ----- resolve inputs -----
    target_script = _resolve_target_script(args.target_script)
    app_name = _resolve_app_name(args.app_name, target_script)

    if not app_name.endswith(".app"):
        app_name += ".app"

    # ----- resolve output path -----
    output_dir = os.path.expanduser("~/Applications")
    os.makedirs(output_dir, exist_ok=True)
    app_path = Input._find_available_path(os.path.join(output_dir, app_name))

    # ----- confirm & create -----
    print()
    print(f"{FLYellow}  Target script  :{CRst} {FLCyan}{target_script}{CRst}")
    print(f"{FLYellow}  App path       :{CRst} {FLCyan}{app_path}{CRst}")
    print()

    confirm = input(f"{FLYellow}Create this .app?{CRst} [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        print(f"{FLRed}Cancelled.{CRst}")
        return 0

    app_contents = os.path.join(app_path, "Contents")
    os.makedirs(app_contents, exist_ok=True)

    bundle_id = f"com.script-to-app.{app_name.replace('.app', '').lower()}"
    _write_launcher(app_contents, target_script)
    _write_info_plist(app_contents, app_name, bundle_id)

    print(f"{FLGreen}Created:{CRst} {FLCyan}{app_path}{CRst}")
    print()
    print(f"{FLYellow}Usage:{CRst}")
    print(f"  Right-click a file in Finder -> Get Info -> Open With ->")
    print(f"  select {FLCyan}{os.path.basename(app_path)}{CRst}, then click {FLYellow}Change All...{CRst}")
    return 0


if __name__ == "__main__":
    raise sys.exit(main())
