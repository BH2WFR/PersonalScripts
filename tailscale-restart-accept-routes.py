#!/usr/bin/env python3
"""Restart Tailscale subnet routes by toggling --accept-routes off then on."""

import subprocess
import sys
import shutil
from utils import *

if shutil.which("tailscale") is None:
    print(f"{FLRed}ERROR{CRst}: tailscale command not found. Is Tailscale installed?")
    sys.exit(1)

print("Disabling accept-routes...")
subprocess.run(["tailscale", "set", "--accept-routes=false"], check=True)

print("Enabling accept-routes...")
subprocess.run(["tailscale", "set", "--accept-routes"], check=True)

print(f"{FLGreen}Done{CRst}. Subnet routes acceptance restarted.")
