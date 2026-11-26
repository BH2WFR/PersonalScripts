#!/usr/bin/env python3
"""Desktop entry for the native window inspector."""

import argparse
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
  Windows 10+ or macOS, PySide6 and psutil. Windows requires administrator
  privileges. On macOS, run as the current user with PyObjC Cocoa, Quartz
  and ApplicationServices. Grant Accessibility for window actions and
  control inspection.

Usage:
  python window-inspector.py [--top]
  --pid <PID>  macOS only. Inspect a specific running application.
  --top  Keep the inspector above other windows on startup.
  --startup-window <ID> <PID>  Inspect the captured window by its Windows
    HWND or macOS WindowServer ID and process ID. Use 0 0 to open blank.
"""


def main() -> int:
    """Capture the foreground window before showing the inspector."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("--top", action="store_true")
    if sys.platform == "win32":
        parser.add_argument("--startup-window", nargs=2, type=int, metavar=("HWND", "PID"))
        parser.add_argument("--_console-pages", type=int, help=argparse.SUPPRESS)
    elif sys.platform == "darwin":
        target = parser.add_mutually_exclusive_group()
        target.add_argument("--pid", type=int)
        target.add_argument("--startup-window", nargs=2, type=int, metavar=("ID", "PID"))
    args = parser.parse_args()
    if sys.platform not in ("win32", "darwin"):
        print("Window Inspector requires Windows or macOS.", file=sys.stderr)
        return 1
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    if sys.platform == "win32" and args._console_pages is not None:
        from window_inspector.console_pages import probe
        return probe(args._console_pages)
    try:
        if sys.platform == "win32":
            from window_inspector import windows as backend
            from window_inspector.model import Window

            # Preserve the original target when the elevation prompt moves focus.
            if args.startup_window is None:
                foreground = backend.foreground()
            else:
                hwnd, pid = args.startup_window
                foreground = Window(hwnd, pid, "", "") if hwnd else None
            identity = (foreground.id, foreground.pid) if foreground else (0, 0)
            restart_args = ["--startup-window", *map(str, identity)]
            if args.top:
                restart_args.append("--top")
            System.restart_elevated(entry=__file__, args=restart_args)
        else:
            from window_inspector import macos as backend

            if args.startup_window is not None:
                from window_inspector.model import Window

                number, pid = args.startup_window
                if (number, pid) != (0, 0) and not (0 < number < 2**32 and pid > 0):
                    parser.error("--startup-window requires a positive window ID and PID, or 0 0.")
                foreground = Window(number, pid, "", "") if number else None
            elif args.pid is not None:
                foreground = backend.application_target(args.pid)
                if foreground is None:
                    parser.error("No running application has that PID.")
            else:
                foreground = backend.foreground()
        System.enable_dpi_awareness()
        from window_inspector.view import run
    except ImportError as exc:
        print(f"Window Inspector could not load {exc}. Install the packages in requirements.txt.", file=sys.stderr)
        return 1
    if sys.platform == "darwin" and args.startup_window is not None:
        return run(backend, foreground, top=args.top, launched_in_foreground=True)
    return run(backend, foreground, top=args.top)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
