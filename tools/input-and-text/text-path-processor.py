#!/usr/bin/env python3
"""Desktop entry for the text and path processor."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """TEXT AND PATH PROCESSOR

Extract full paths from copied or dragged files and convert paths line by line. Clean copied PDF text,
transform Unicode typography and indentation, or replace text with a regular expression.

Requirements:
  PySide6 and a graphical desktop.
  Optional on macOS: pyobjc-framework-Cocoa for native Finder filename lists.

Usage:
  python text-path-processor.py [--clip]
  Use --clip to load copied text or file paths when the window opens.
"""


def main() -> int:
    """Start the desktop editor after handling CLI help."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("--clip", action="store_true")
    args = parser.parse_args()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from text_processor.window import run
    except ImportError as exc:
        print(f"Text and Path Processor could not load {exc}. Install PySide6 in this environment.",
              file=sys.stderr)
        return 1
    System.enable_dpi_awareness()
    return run(from_clipboard=args.clip)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
