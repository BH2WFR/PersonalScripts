#!/usr/bin/env python3
"""Load the platform's nonactivating keyboard only after parsing the command line."""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """SCREEN KEYBOARD

Type into the focused window with a floating keyboard near the pointer.
Held keys repeat at the system rate until release. On macOS, compatible apps
can show the accent menu for held letters.
The left key defaults to Caps Lock and can act as a custom layer key.

Requirements:
  Windows 10+ with Tkinter and administrator privileges, or macOS with
  pyobjc-framework-Cocoa, pyobjc-framework-Quartz and Accessibility permission.
  Settings use PyYAML.
  For custom layer actions, enable the matching alias in custom-autohotkey-config
  or use the CGEventTap fallback in custom-karabiner-config.

Usage:
  python screen-keyboard.py [--force-layer=capslock|f1|f24]
  --force-layer overrides Prefs for this launch or reopen. F24 is Windows-only.
"""


def main() -> int:
    """Open the keyboard using native input for the current desktop."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.allow_abbrev = False
    parser.exit_on_error = False
    parser.add_argument("--force-layer", nargs="?", action="append", const="", type=str.lower)
    try:
        args, unknown = parser.parse_known_args()
        values = args.force_layer or []
    except argparse.ArgumentError:
        unknown, values = sys.argv[1:], []
    if sys.platform not in {"win32", "darwin"}:
        print("Screen Keyboard requires Windows or macOS.", file=sys.stderr)
        return 1
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from screen_keyboard.state import LeftKeyMode

    choices = {m.value.lower(): m for m in LeftKeyMode.supported(sys.platform == "darwin") if m != LeftKeyMode.NATIVE}
    warning = ""
    force_layer = None
    if unknown or len(values) > 1 or (values and values[0] not in choices):
        warning = (f"Invalid arguments: {' '.join(sys.argv[1:])}\n"
                   f"Use --force-layer with one of: {', '.join(choices)}.\nUsing the saved left key preference.")
    elif values:
        force_layer = choices[values[0]]
    if sys.platform == "win32":
        System.restart_elevated()
    try:
        if sys.platform == "win32":
            from screen_keyboard.windows_ui import run
        else:
            from screen_keyboard.mac_ui import run
        return run(force_layer, warning)
    except ImportError as exc:
        print(f"Screen Keyboard could not load {exc}. See --help for the platform requirements.", file=sys.stderr)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Screen Keyboard: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
