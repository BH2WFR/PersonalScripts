#!/usr/bin/env python3
"""Monitor global keyboard and mouse events without suppressing input.

Windows events retain virtual keys, scan codes and low-level hook flags.
Scroll output shows one (x, y) pair and cyan up/down/left/right labels.
Windows displays raw wheel deltas (120 per notch, right/up positive); macOS
shows precise NSEvent scrolling deltas, including fractional trackpad movement.
X11 and callback step values remain unchanged. Zero native deltas are not printed.
macOS also shows native pinch magnification deltas, zoom direction and phase;
zero-delta pinch start/end events remain visible. On a Windows remote host,
pinch is visible only when translated to wheel input; these are not physical
touchpad distances or an application's current zoom level.
macOS supports CGEvent/IOHID device identity; Linux requires an X11 session.
Implementation modules live in keyboard-hook-viewer/ and are not commands.

Responsible use:
    Only for legitimate keyboard testing, custom hotkeys and authorized
    automation. Obtain permission from affected users; do not use for covert
    surveillance, credential collection or other unauthorized activity.
    Users are responsible for their use and its consequences.

Requirements:
    Windows: standard-library ctypes. macOS: pyobjc-framework-Quartz.
    Linux X11: python-xlib. Wayland is unsupported.

Usage:
    python tools/others/keyboard-hook-viewer.py
    python tools/others/keyboard-hook-viewer.py --help
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
    return cast(Callable[[], int], load_app().main)()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
