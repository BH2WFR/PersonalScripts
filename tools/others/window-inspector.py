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
  Windows 10+ or macOS, PySide6 and psutil. Windows requires administrator
  privileges. On macOS, run as the current user with PyObjC Cocoa, Quartz
  and ApplicationServices. Grant Accessibility for window actions and
  control inspection.

Usage:
  python window-inspector.py [--top]
  --pid <PID>  macOS only. Inspect a specific running application.
  --top  Keep the inspector above other windows on startup.
  --startup-window <HWND> <PID>  Windows only. Inspect the window with the
    given handle and owning process ID. Supply both as decimal integers.
"""


def main() -> int:
    """Capture the foreground window before showing the inspector."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("--top", action="store_true")
    if sys.platform == "win32":
        parser.add_argument("--startup-window", nargs=2, type=int, metavar=("HWND", "PID"))
    elif sys.platform == "darwin":
        parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    if sys.platform not in ("win32", "darwin"):
        print("Window Inspector requires Windows or macOS.", file=sys.stderr)
        return 1
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
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

            foreground = backend.application_target(args.pid) if args.pid is not None else backend.foreground()
            if args.pid is not None and foreground is None:
                parser.error("No running application has that PID.")
        System.enable_dpi_awareness()
        from window_inspector.view import run
    except ImportError as exc:
        print(f"Window Inspector could not load {exc}. Install the packages in requirements.txt.", file=sys.stderr)
        return 1
    return run(backend, foreground, top=args.top)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
