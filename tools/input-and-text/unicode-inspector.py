#!/usr/bin/env python3
"""Desktop entry for the Unicode inspector."""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = f"""{FLYellow}UNICODE INSPECTOR{CRst}

Inspect code points, UTF-8 bytes, Unicode names and categories, including
invisible characters, with text statistics and copyable reports.

{FLYellow}Requirements:{CRst}
  PySide6 and a graphical desktop.

{FLYellow}Usage:{CRst}
  python unicode-inspector.py [TEXT ... | --clip]
  Omit TEXT to enter text in the window; --clip reads the clipboard.
"""


def main() -> int:
    """Open the inspector after handling help and validating arguments."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("text", nargs="*", metavar="TEXT")
    parser.add_argument("--clip", "--from-clipboard", action="store_true", dest="clipboard")
    parser.add_argument("--pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.clipboard and args.text:
        parser.error("TEXT and --clip cannot be combined")

    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from unicode_inspector.window import run
    except ImportError as exc:
        print(f"Unicode Inspector could not load {exc}. Install PySide6 in this environment.", file=sys.stderr)
        return 1
    System.enable_dpi_awareness()
    return run(" ".join(args.text), args.clipboard)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
