#!/usr/bin/env python3
"""Implementation notes.

Keep the two tailscale setting changes ordered and surface command failures.
"""


import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}TAILSCALE REFRESH ROUTES{CRst}

Toggle Tailscale subnet-route acceptance off and on to recover routes after
network changes. Route connectivity is briefly interrupted.

{FLYellow}Requirements:{CRst}
  Tailscale CLI and permission to change its settings.

{FLYellow}Usage:{CRst}
  python tailscale-refresh-routes.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:

        print(HELP)
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
