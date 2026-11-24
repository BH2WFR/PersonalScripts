#!/usr/bin/env python3
"""Desktop entry for the screen mask tool."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """SCREEN MASK

Cover subtitles with a movable, resizable, always-on-top block, or right-click
and choose Hollow frame to read and interact with the content inside. Drag a
frame by its sides and resize it from a corner.

Requirements:
  PySide6 on Windows 10+, macOS, or a Linux desktop. macOS also requires
  pyobjc-framework-Cocoa. On X11, translucency requires compositing. On
  Wayland, placement and keeping a block above other apps depend on the compositor.

Usage:
  python screen-mask.py [--solid | --hollow]
  Open a solid block (default) or a hollow reading frame. Run again to add one.
"""


def main() -> int:
    """Start a screen mask or add one to the running application."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--solid", dest="hollow", action="store_false")
    modes.add_argument("--hollow", dest="hollow", action="store_true")
    parser.set_defaults(hollow=False)
    args = parser.parse_args()
    if sys.platform not in ("win32", "darwin", "linux"):
        print("Screen Mask requires Windows, macOS, or a Linux desktop.", file=sys.stderr)
        return 1
    if sys.platform == "linux" and System.is_headless():
        print("Screen Mask requires an X11 or Wayland display.", file=sys.stderr)
        return 1
    System.enable_dpi_awareness()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from screen_mask.app import run

        return run(hollow=args.hollow)
    except ImportError as exc:
        print(f"Screen Mask could not load {exc}. Install the packages in requirements.txt.", file=sys.stderr)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Screen Mask: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
