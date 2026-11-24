#!/usr/bin/env python3
"""Desktop entry for the native window inspector."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from utils import *  # noqa: E402


HELP = """WINDOW INSPECTOR

The inspector opens on the current foreground window. Drag the finder onto
a popup or search the window list to identify its process, inspect its
controls, close the window, or terminate an unresponsive process.

Requirements:
  Windows 10+ or macOS, PySide6 and psutil. macOS also requires PyObjC
  Cocoa, Quartz and ApplicationServices. Accessibility permission enables
  window actions and control inspection.

Usage:
  python window-inspector.py
"""


def main() -> int:
    """Capture the foreground window before showing the inspector."""
    Console.argument_parser(HELP).parse_args()
    if sys.platform not in ("win32", "darwin"):
        print("Window Inspector requires Windows or macOS.", file=sys.stderr)
        return 1
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    System.enable_dpi_awareness()
    try:
        if sys.platform == "win32":
            from window_inspector import windows as backend
        else:
            from window_inspector import macos as backend
        foreground = backend.foreground()
        from window_inspector.view import run
    except ImportError as exc:
        print(f"Window Inspector could not load {exc}. Install the packages in requirements.txt.", file=sys.stderr)
        return 1
    return run(backend, foreground)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
