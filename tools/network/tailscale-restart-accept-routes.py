#!/usr/bin/env python3
"""Restart Tailscale subnet routes by toggling --accept-routes off then on."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
{FLYellow}TAILSCALE RESTART ACCEPT ROUTES{CRst}
==================================

Usage:
  python {script_name}          restart subnet routes acceptance
  python {script_name} --help   show this help

{FLYellow}Description:{CRst}
  Restart Tailscale subnet routes by toggling --accept-routes off then on.
  Useful when subnet routes stop working after network changes.

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install tailscale{CRst}
  Linux (apt):      {FGray}sudo apt install tailscale{CRst}
  macOS (brew):     {FGray}brew install tailscale{CRst}
""")
        return 0

    if not Environment.check_commands(CmdCheck("tailscale", hints={
        "any": f"Is {FLYellow}Tailscale{CRst} installed?",
    })):
        return 1

    print("Disabling accept-routes...")
    subprocess.run(["tailscale", "set", "--accept-routes=false"], check=True)

    print("Enabling accept-routes...")
    subprocess.run(["tailscale", "set", "--accept-routes"], check=True)

    print(f"{FLGreen}Done{CRst}. Subnet routes acceptance restarted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
