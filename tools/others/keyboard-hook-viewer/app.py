"""Implementation notes.

Private lifecycle coordinator. User help belongs to ../keyboard-hook-viewer.py;
load platform backends only when monitoring starts.
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


def main() -> int:

    """Run the viewer; return zero after a clean stop or help display."""

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
