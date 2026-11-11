#!/usr/bin/env python3
"""Implementation notes.

Load keyboard-hook-viewer as personal_keyboard_hook_viewer; preserve compiler
staging and the valid package alias. Runtime/backend ownership and code-space
distinctions: keyboard-hook-viewer/README.md.
"""

"""
    本人想做 Caps+Shift+A, Caps+A 这样的热键，故做技术测试
"""

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

HELP = f"""{FLYellow}KEYBOARD AND MOUSE MONITOR{CRst}

Inspect global keyboard/mouse events, key codes and scroll input without blocking
input; macOS also reports native pinch gestures. For authorized input testing only.

{FLYellow}Requirements:{CRst}
  Windows: built-in APIs. macOS: pyobjc-framework-Quartz and input permissions.
  Linux X11: python-xlib and XRecord; Wayland is unsupported.

{FLYellow}Usage:{CRst}
  python keyboard-hook-viewer.py
"""


PACKAGE_NAME = "personal_keyboard_hook_viewer"


def load_app() -> ModuleType:
    """Load the private viewer without starting hooks or sending input.

    Returns:
        Application module; call main() to run it.

    Raises:
        ImportError: The private package cannot be loaded.

    Side effects:
        Registers the source package under its import alias in sys.modules.
        Compiled applications use the package staged by compile-script.py.
    """
    if PACKAGE_NAME not in sys.modules and not IS_FROZEN:
        directory = SCRIPT_DIR / "keyboard-hook-viewer"
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, directory / "__init__.py",
            submodule_search_locations=[str(directory)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load keyboard hook viewer from {directory}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.app")


def main() -> int:
    """Run the viewer and return its exit status; help never starts a hook."""
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(HELP)
        return 0
    return cast(Callable[[], int], load_app().main)()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
