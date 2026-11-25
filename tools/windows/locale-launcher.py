#!/usr/bin/env python3
"""Windows entry point for the per-application locale launcher."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from utils import *  # noqa: E402

HELP = """LOCALE LAUNCHER

Launch a Windows executable with independent region, code page, UI language
and time zone settings. Each option defaults to the host setting.

Requirements:
  Windows 10+, PySide6. Locale overrides support native x86 and x64 programs.

Usage:
  python locale-launcher.py
"""


def main() -> int:
    """Open the launcher with the caller's privileges."""
    Console.initialize_ansi_output()
    Console.argument_parser(HELP).parse_args()
    if sys.platform != "win32":
        Console.print_error_and_exit("Locale Launcher requires Windows 10 or later.")
    try:
        from locale_launcher.ui import run
    except ImportError as exc:
        Console.print_error_and_exit(f"Cannot load Locale Launcher: {exc}. Install PySide6.")
        return 1
    System.enable_dpi_awareness()
    return run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
