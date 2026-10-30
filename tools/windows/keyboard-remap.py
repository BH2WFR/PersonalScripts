#!/usr/bin/env python3
"""Edit Windows registry keyboard mappings in a SharpKeys-style GUI.

Read current machine-wide Scancode Map entries, select keys by searchable
scan-code dropdown or visible-window capture, and edit/disable mappings.
Drag rows to reorder the draft; inspect and copy its exact final hex bytes.
Writes require explicit confirmation, elevation, a new JSON backup and a
matching baseline. Restore loads a backup into the draft; it never auto-applies.
Restart Windows after saving. No background input logging or automatic reboot.

Requirements:
    Windows 10+, Python 3.13+, PySide6 (pip). Registry access uses stdlib winreg.
    Administrator privileges only when saving. Optional gsudo for elevation.

Usage:
    python tools/windows/keyboard-remap.py
    python tools/windows/keyboard-remap.py --read-only
    python tools/windows/keyboard-remap.py --help

Internal --admin-draft passes a validated draft to an elevated editor; it never
writes automatically. Implementation lives in keyboard-remap/ and is excluded
from launcher/compiler lists. Only legitimate keyboard testing, custom hotkeys
and authorized automation are permitted; no covert surveillance or credential
collection. Capture may observe already-remapped keys and cannot recover them.
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
            raise ImportError(f"Cannot load keyboard-remap package from {directory}")
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
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}KEYBOARD REMAP{CRst}\n\nDescription:\n"
                    "  Edit Windows registry scan-code mappings with dropdown selection and key capture.\n"
                    "  Drag rows to reorder; expand the final hexadecimal view to inspect/copy draft bytes.\n"
                    "  Save only after confirmation and backup; restart Windows to apply.\n"
                    "  Capture is window-scoped and for legitimate, authorized use only.",
        epilog=f"{FGray}Requirements:\n  Windows 10+, PySide6; administrator only for writing.\n"
               f"  Optional: gsudo. No background key recording or automatic reboot.{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter)
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
        print(f"{FLRed}Keyboard Remap could not start: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
