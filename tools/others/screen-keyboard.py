#!/usr/bin/env python3
"""Load the platform's nonactivating keyboard only after parsing the command line."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """SCREEN KEYBOARD

Type into the focused window with a floating keyboard that remembers its size.
Choose CapsLock or Layer in Settings. Layer sends F24 on Windows or Caps Lock
through the HID event tap on macOS for the active remapper to interpret.

Requirements:
  Windows 10+ with Tkinter and administrator privileges, or macOS with
  pyobjc-framework-Cocoa, pyobjc-framework-Quartz and Accessibility permission.
  Settings use PyYAML.
  For custom layer actions, enable the F24 alias in custom-autohotkey-config
  or the CGEventTap fallback in custom-karabiner-config.

Usage:
  python screen-keyboard.py
"""


def main() -> int:
    """Open the keyboard using native input for the current desktop."""
    Console.argument_parser(HELP).parse_args()
    if sys.platform not in {"win32", "darwin"}:
        print("Screen Keyboard requires Windows or macOS.", file=sys.stderr)
        return 1
    if sys.platform == "win32":
        System.restart_elevated()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        if sys.platform == "win32":
            from screen_keyboard.windows_ui import run
        else:
            from screen_keyboard.mac_ui import run
        return run()
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
