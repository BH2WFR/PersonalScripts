#!/usr/bin/env python3
"""Desktop entry for the text processor."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """TEXT PROCESSOR

Extract copied file paths or convert paths line by line. Clean copied PDF text,
transform Unicode typography and indentation, or replace text with a regular expression.

Requirements:
  PySide6 and a graphical desktop.
  Optional on macOS: pyobjc-framework-Cocoa for native Finder filename lists.

Usage:
  python text-processor.py
"""


def main() -> int:
    """Start the desktop editor after handling CLI help."""
    Console.initialize_ansi_output()
    Console.argument_parser(HELP).parse_args()
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from text_processor.window import run
    except ImportError as exc:
        print(f"Text Processor could not load {exc}. Install PySide6 in this environment.",
              file=sys.stderr)
        return 1
    System.enable_dpi_awareness()
    return run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
