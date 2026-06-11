#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

import argparse
import shlex
import plistlib
from typing import Optional, Union

SUBDIR = "PersonalScripts"

help_message = f'''
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


def _format_process_output(value: Optional[Union[bytes, str]]) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


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


def _resolve_target_script(arg_value: Optional[str]) -> str:
    if arg_value:
        p = os.path.abspath(os.path.expanduser(arg_value))
        if not os.path.isfile(p):
            Utils.print_error_and_exit(f"Target script not found: {p}")
        if os.path.splitext(p)[1].lower() != ".py":
            Utils.print_error_and_exit(f"Target script must be a .py file: {p}")
        return p
    p = Input.resolve_input_path(
        default_path=os.path.expanduser("~"),
        prompt="Path to the Python script to wrap",
        path_type="file",
    )
    if os.path.splitext(p)[1].lower() != ".py":
        Utils.print_error_and_exit(f"Target script must be a .py file: {p}")
    return p


def _resolve_app_name(arg_value: Optional[str], script_path: str) -> str:
    if arg_value:
        return arg_value
    stem = os.path.splitext(os.path.basename(script_path))[0]
    default_name = _title_case(stem)
    name = input(
        f"{FLYellow}App name {FGray}[{default_name}]{CRst}: "
    ).strip()
    return name or default_name


def _create_app_bundle(app_path: str, target_script: str) -> None:
    """Create the .app using osacompile so it receives Apple Events (odoc).

    Uses ``osacompile`` to build a native AppleScript applet with both
    ``on run`` (direct launch / drag-and-drop) and ``on open`` ("Open With"
    from Finder) handlers.
    """
    import tempfile
    import subprocess

    workdir = os.path.dirname(target_script)
    python_exe = sys.executable

    # Shell command that Terminal will execute
    shell_cmd = (
        f"cd {shlex.quote(workdir)} && "
        f"{shlex.quote(python_exe)} {shlex.quote(target_script)}"
    )

    # AppleScript applet — needs both on run AND on open to receive files
    # from Finder's "Open With" context menu (which sends an odoc Apple Event).
    #
    # We avoid "tell application Terminal" because it triggers a TCC
    # automation permission prompt (-1743). Instead we write the command
    # to a temp .command file and use "open -a Terminal" to run it.
    applescript = f'''\
on runPythonScript(fileArgs)
    set shellCmd to "{_escape_applescript(shell_cmd)}"
    repeat with a in fileArgs
        set shellCmd to shellCmd & " " & quoted form of a
    end repeat
    set scriptContent to "#!/bin/bash" & linefeed & shellCmd & "; rm \\"$0\\"; exit" & linefeed
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
            Utils.print_error_and_exit(f"osacompile failed: {detail}")
    finally:
        os.unlink(tmp_path)


def _write_info_plist(app_contents: str, app_name: str, bundle_id: str) -> None:
    """Update the Info.plist (created by osacompile) with custom keys.

    Reads the existing plist to preserve keys set by osacompile
    (e.g. CFBundleExecutable) and merges our additions on top.
    """
    plist_path = os.path.join(app_contents, "Info.plist")
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    display_name = app_name.replace(".app", "")
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


def main(argv: Optional[list[str]] = None) -> int:
    Utils.print_banner("SCRIPT TO APP")

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
    output_dir = os.path.expanduser(f"~/Applications/{SUBDIR}")
    os.makedirs(output_dir, exist_ok=True)

    app_path = os.path.join(output_dir, app_name)
    while os.path.exists(app_path):
        print()
        print(f"{FLYellow}{app_path}{CRst} {FLRed}already exists.{CRst}")
        choice = input(f"Overwrite? [y/N] or enter a new name: ").strip()
        if choice.lower() in ("y", "yes"):
            import shutil
            shutil.rmtree(app_path)
            break
        elif choice:
            # Treat as a new name
            if not choice.endswith(".app"):
                choice += ".app"
            app_path = os.path.join(output_dir, choice)
        else:
            # Empty input = don't overwrite, cancel
            print(f"{FLRed}Cancelled.{CRst}")
            return 0

    # ----- confirm & create -----
    print()
    print(f"{FLYellow}  Target script  :{CRst} {FLCyan}{target_script}{CRst}")
    print(f"{FLYellow}  App path       :{CRst} {FLCyan}{app_path}{CRst}")
    print(f"{FLYellow}  Python path    :{CRst} {FLCyan}{sys.executable}{CRst}")
    print()

    confirm = input(f"{FLYellow}Create this .app?{CRst} [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        print(f"{FLRed}Cancelled.{CRst}")
        return 0

    bundle_id = f"com.script-to-app.{app_name.replace('.app', '').lower()}"
    _create_app_bundle(app_path, target_script)
    _write_info_plist(os.path.join(app_path, "Contents"), app_name, bundle_id)

    # Register with Launch Services so it shows in "Open With" immediately
    import subprocess
    lsregister = (
        "/System/Library/Frameworks/CoreServices.framework"
        "/Frameworks/LaunchServices.framework/Support/lsregister"
    )
    if os.path.exists(lsregister):
        subprocess.run([lsregister, "-f", app_path], capture_output=True)

    print(f"{FLGreen}Created:{CRst} {FLCyan}{app_path}{CRst}")
    print()
    print(f"{FLYellow}Usage:{CRst}")
    print(f"  Right-click a file in Finder -> Get Info -> Open With ->")
    print(f"  select {FLCyan}{app_path}{CRst}, then click {FLYellow}Change All...{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
