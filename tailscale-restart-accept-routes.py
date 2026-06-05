#!/usr/bin/env python3
"""Restart Tailscale subnet routes by toggling --accept-routes off then on."""

import subprocess
import sys
from utils import *

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
    sys.exit(0)

if not Utils.check_commands(CmdCheck("tailscale", hints={
    "any": f"Is {FLYellow}Tailscale{CRst} installed?",
})):
    sys.exit(1)

print("Disabling accept-routes...")
subprocess.run(["tailscale", "set", "--accept-routes=false"], check=True)

print("Enabling accept-routes...")
subprocess.run(["tailscale", "set", "--accept-routes"], check=True)

print(f"{FLGreen}Done{CRst}. Subnet routes acceptance restarted.")
