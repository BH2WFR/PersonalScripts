"""Interactive terminal workflow for the hook viewer.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
import threading
from typing import cast
from .models import EventSink
from . import backend, runtime, ui
from . import USAGE_NOTICE
from .devices import enumerate_devices
_OS = sys.platform


def print_help() -> None:
    """Print usage and platform requirements without creating native hooks."""
    Console.print_banner("KEYBOARD & MOUSE HOOK MONITOR")
    print(f"""
Usage:
  python keyboard-hook-viewer.py
  python keyboard-hook-viewer.py --help

Description:
  Monitor global keyboard and mouse events; input passes through unchanged.
  Windows displays scan codes and preserves sided keys and keypad Enter.
  Windows scroll (dx, dy): right/up are positive; small nonzero deltas show
  at least one integer step, not precise physical wheel distance.
  macOS can display the physical HID device identity when available.

Options:
  -h, --help   Show this help and exit.

Requirements:
  Windows 10+: standard-library ctypes; no additional package.
  macOS: pyobjc-framework-Quartz; Accessibility/Input Monitoring permission.
  Linux X11: python-xlib and XRecord. Wayland is unsupported.

{FLYellow}Responsible use:{CRst}
{USAGE_NOTICE}

{FGray}Shared key names and scan codes: utils.Keyboard and WindowsScanCode.
Private implementation: keyboard-hook-viewer/.{CRst}
""")


def main() -> int:

    """Run the viewer; return zero after a clean stop or help display."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        return 0
    Console.set_locale_utf8()

    print()
    print(f"{FLYellow}╔{'═' * 46}╗{CRst}")
    print(f"{FLYellow}║{CRst}  {FLWhite}{CBold}KEYBOARD & MOUSE HOOK MONITOR{CRst}         {FLYellow}║{CRst}")
    print(f"{FLYellow}╚{'═' * 46}╝{CRst}")
    print()

    print(f"{FLYellow}{USAGE_NOTICE}{CRst}")
    print()

    print(f"{FLYellow}Enumerating input devices...{CRst}")
    devices = enumerate_devices()
    ui._state["kbd_devs"] = [d for d in devices if d.kind == "KBD"]
    ui._state["mou_devs"] = [d for d in devices if d.kind == "MOU"]

    if devices:
        print()
        print(f"{FLCyan}{'─' * 60}{CRst}")
        print(f"{FLYellow}  Detected input devices:{CRst}")
        print()
        for d in devices:
            kind_color = FLCyan if d.kind == "KBD" else FLMagenta
            parts = [
                f"  {FLYellow}[{d.idx}]{CRst} {kind_color}[{d.kind}]{CRst} "
                f"{FLWhite}{d.name}{CRst}",
            ]
            if d.vendor_id or d.product_id:
                vid_pid = f"{d.vendor_id}:{d.product_id}" if d.product_id else d.vendor_id
                parts.append(f"{FGray}{vid_pid}{CRst}")
            if d.serial:
                parts.append(f"{FGray}S/N:{d.serial}{CRst}")
            if d.path:
                parts.append(f"{FGray}{d.path}{CRst}")
            print("  ".join(parts))
        print()
        print(f"{FLCyan}{'─' * 60}{CRst}")
        print()
    else:
        print(f"  {FGray}Device enumeration not supported on this platform.{CRst}")
        print()

    if _OS == "darwin":
        show_device_choice = Menu.select(
            [
                MenuOption(["Y"], "Yes", True, FLGreen),
                MenuOption(["N"], "No", False, FLYellow),
            ],
            prompt="Show event source device?",
            default_key="Y",
            inline=True,
            separator=False,
        )
        ui._show_event_device = bool(show_device_choice)
        print()

    print(f"{FLYellow}Starting hooks...{CRst}")
    print(f"  {FLGreen}↓{CRst} press/down    {FLYellow}↑{CRst} release/up")
    print(f"  {FLRed}Ctrl+C{CRst} to stop")
    print()
    print(f"{FLCyan}{'─' * 60}{CRst}")

    # --- create hook ----------------------------------------------------------
    try:
        hook = backend.create_hook(cast(EventSink, runtime))
    except (ImportError, OSError, NotImplementedError) as e:
        Console.print_error_and_exit(str(e))
        raise  # unreachable — satisfies the type checker

    # --- run hook -------------------------------------------------------------
    hook_thread = threading.Thread(
        target=hook.start, daemon=True, name="input-hook",
    )
    hook_thread.start()

    if not hook._ready.wait(timeout=5):
        print(f"{FLCyan}  Waiting for hook permission...{CRst}")

    # Print initial foreground window
    ui._check_win_change()

    try:
        hook_thread.join()
    except KeyboardInterrupt:
        pass
    hook.stop()
    print(f"{FLGreen}Bye.{CRst}")
    return 0
