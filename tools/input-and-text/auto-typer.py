#!/usr/bin/env python3
"""Launch the floating keyboard panel after checking the platform and dependencies."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = f"""{FLYellow}AUTO TYPER{CRst}

Type clipboard or edited text into the focused window, including web VNC
sessions that do not support pasting.
Use a US keyboard layout and direct English input for ASCII. Unicode input
depends on the browser, VNC client and remote application.

{FLYellow}Requirements:{CRst}
  PySide6 on Windows 10+ or macOS. Windows requests administrator privileges.
  macOS requires pyobjc-framework-Cocoa, pyobjc-framework-Quartz and
  Accessibility permission for the typing process.

{FLYellow}Usage:{CRst}
  python auto-typer.py
"""


def main() -> int:
    """Run the auto typer on a supported desktop."""
    Console.argument_parser(HELP).parse_args()
    if sys.platform not in ("win32", "darwin"):
        print("Auto Typer requires Windows or macOS.", file=sys.stderr)
        return 1
    if sys.platform == "win32":
        System.restart_elevated()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))  # The launcher can import this entry in-process.
    try:
        from auto_typer.panel import run
        if sys.platform == "win32":
            from auto_typer.windows import WindowsSender, show_panel
            System.enable_dpi_awareness()
            return run(WindowsSender(), show_panel)
        from auto_typer.macos import run_macos
        return run_macos()
    except ImportError as exc:
        print(f"Auto Typer could not load {exc}. Install PySide6"
              " and, on macOS, pyobjc-framework-Cocoa and pyobjc-framework-Quartz.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
