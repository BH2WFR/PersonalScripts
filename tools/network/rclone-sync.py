#!/usr/bin/env python3
"""Run YAML-defined rclone tasks through the sibling rclone-sync private package.

Supports directory/file actions, ordered path1/path2 pairs, literal paths,
mounted-volume selection, temporary SFTP/WebDAV addresses, checks, and retries.
Task groups and their tasks are displayed in schema order, including ungrouped.
linux-gui-required: true requires a Linux GUI via project utils; false imposes no requirement.
The task menu can show the active rclone config path or open its file, then exit.
Encrypt/Decrypt opens rclone's native config menu, then exits this script.
Configuration reference: rclone-sync-schema-sample.yaml beside this entry point.
Internal architecture: rclone-sync/README.md. The private package is loaded as
personal_rclone_sync; internal modules are not standalone scripts.

Requirements:
    Python 3.13+, project utils, PyYAML, and rclone. Volume endpoints additionally
    use Windows PowerShell 7 Storage/CIM, Linux lsblk, or macOS diskutil.

Usage:
    python rclone-sync.py --help
    python rclone-sync.py
    python rclone-sync.py --schema-file /path/to/schema.yaml --task group/name
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
from utils import *

PACKAGE_NAME = "personal_rclone_sync"


def load_app() -> ModuleType:
    """Load the private application once, using its valid Python package alias.

    Returns:
        The application module. Frozen builds import the staged package directly.

    Raises:
        ImportError: Package files or a required import cannot be loaded.

    Side effects:
        Registers source packages in sys.modules; performs no disk scan or sync.
    """
    if PACKAGE_NAME not in sys.modules and not IS_FROZEN:
        package_dir = SCRIPT_DIR / "rclone-sync"
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load rclone runner from {package_dir}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.app")


def main() -> int:
    """Run the application with the entry directory as the script_dir placeholder.

    Returns:
        Application exit status; synchronization follows its explicit task flow.
    """
    application = load_app()
    run = cast(Callable[[str | None], int], application.main)
    directory = Path(sys.executable).resolve().parent if IS_FROZEN else SCRIPT_DIR
    return run(str(directory))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
