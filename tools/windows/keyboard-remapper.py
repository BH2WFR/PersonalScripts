#!/usr/bin/env python3
"""Implementation notes.

Load keyboard-remapper as personal_keyboard_remap and preserve compiler staging.
The internal --admin-draft handoff only stages a validated draft, never applies
it. Registry conflict checks, backup/readback and capture boundaries are
documented in keyboard-remapper/README.md.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if not getattr(sys, "frozen", False) and "__compiled__" not in globals():
    sys.path.insert(0, str(PROJECT_ROOT))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}KEYBOARD REMAPPER{CRst}

Edit machine-wide scan-code mappings to remap or disable physical keys.
Writes require review and backup; restart Windows to apply saved changes.
Key capture is limited to the focused window and authorized testing.

{FLYellow}Requirements:{CRst}
  Windows 10+, PySide6; administrator privileges for writing. gsudo is optional.

{FLYellow}Usage:{CRst}
  python keyboard-remapper.py [--read-only]
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


PACKAGE_NAME = "personal_keyboard_remap"


def load_app() -> ModuleType:
    """Load the private package without starting a GUI, capture or registry access.

    Returns:
        Startup module. Frozen builds use the compiler's staged import alias.

    Raises:
        ImportError: The implementation package cannot be located.

    Side effects:
        Registers the source package's import alias in sys.modules.
    """
    frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    if PACKAGE_NAME not in sys.modules and not frozen:
        directory = Path(__file__).with_suffix("")
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, directory / "__init__.py", submodule_search_locations=[str(directory)])
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load keyboard-remapper package from {directory}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.app")


def main() -> int:
    """Parse options and launch the editor; --help never imports Qt or reads HKLM.

    Returns:
        Zero on normal exit, nonzero for unsupported platform/startup failures.

    Side effects:
        Prints help/errors, opens the GUI, and requests elevation only for an
        explicit internal draft handoff. No startup path writes the registry.
    """
    parser = Console.argument_parser(HELP)
    parser.add_argument("--read-only", action="store_true", help="Disable registry writing and elevation")
    parser.add_argument("--admin-draft", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        Console.print_error_and_exit(f"This script only runs on Windows. Current platform: {sys.platform}")
        return 1
    try:
        app = load_app()
        if args.read_only and args.admin_draft:
            parser.error("--read-only cannot be combined with an administrator draft")
        handoff = app.decode_handoff(args.admin_draft) if args.admin_draft else None
        # Shared privilege API must run before GUI startup; the elevated child
        # only reopens the draft and still requires an explicit Write click.
        if handoff is not None:
            System.restart_elevated()
        importlib.import_module("PySide6")
        return int(app.run(handoff, read_only=args.read_only))
    except ImportError as exc:
        print(f"{FLRed}Cannot load GUI dependency: {exc}{CRst}")
        print(f"{FLYellow}Install dependencies with: conda run -n base python -m pip install PySide6{CRst}")
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"{FLRed}Keyboard Remapper could not start: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
