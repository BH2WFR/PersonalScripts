#!/usr/bin/env python3
"""Load the private system-event-viewer package; see its README for source coverage."""

import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Callable, cast

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
if not IS_FROZEN:
    sys.path.insert(0, str(PROJECT_ROOT))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}SYSTEM EVENT VIEWER{CRst}

Inspect and export power, login, failure and system activity history, including
devices, networks, updates and resource/service problems. Includes incoming SSH,
Windows RDP, SMB/share auditing, Modern Standby and blocked device ejections.
Coverage depends on retained logs; diagnostic reports alone do not establish a
crash or its cause.

{FLYellow}Requirements:{CRst}
  PySide6; Windows PowerShell, macOS log/pmset/last/sysctl, or Linux journalctl.
  Security log access and prior auditing for Windows lock/logon/authentication history.
  File Share / Detailed File Share auditing for Windows shared-object access logs.
  OpenSSH server logs for SSH; file-only SSH logs are not read. Linux locks and
  hang detection are limited; macOS diagnostics require readable report files.
  Activity coverage varies with OS version, services and retained native logs.

{FLYellow}Usage:{CRst}
  python system-event-viewer.py
"""


PACKAGE_NAME = "personal_system_event_viewer"


def load_app() -> ModuleType:
    """Load the private viewer without querying system logs.

    Returns:
        Application module; call main() to run it.

    Raises:
        ImportError: The private package cannot be loaded.

    Side effects:
        Registers the source package under its import alias in sys.modules.
        Compiled applications use the package staged by compile-script.py.
    """
    if PACKAGE_NAME not in sys.modules and not IS_FROZEN:
        directory = SCRIPT_DIR / "system-event-viewer"
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, directory / "__init__.py",
            submodule_search_locations=[str(directory)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load system event viewer from {directory}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.app")


def main() -> int:
    """Run the viewer and return its exit status; help never queries logs."""
    Console.argument_parser(HELP).parse_args()
    return cast(Callable[[], int], load_app().main)()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
