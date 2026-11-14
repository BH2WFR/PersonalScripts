#!/usr/bin/env python3
"""Implementation notes.

Load rclone-sync as personal_rclone_sync and keep its modules out of launcher/
compiler discovery. Preserve the entry directory as the script_dir placeholder.
Architecture: rclone-sync/README.md; schema: rclone-sync-schema-sample.yaml.
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

HELP = f"""{FLYellow}RCLONE SYNC RUNNER{CRst}

Run YAML-defined copy, move, sync, bisync and comparison tasks across local or
remote paths, with ordered batches and mounted-volume checks. Sync can delete
destination files; move deletes sources. Bisync initialization requires --resync.

{FLYellow}Requirements:{CRst}
  rclone, PyYAML, cryptography for encrypted settings.
  Volume endpoints: Windows PowerShell 7 Storage/CIM, Linux lsblk or macOS diskutil.

{FLYellow}Usage:{CRst}
  python rclone-sync.py [--schema-file FILE] [--task GROUP/NAME] [--dry-run]
  python rclone-sync.py --task GROUP/NAME --action ACTION [--comparison MODE]
  Sync actions: push-sync (path1 to path2), pull-sync (path2 to path1).
  Actions/schema options: rclone-sync-schema-sample.yaml beside the entry.
"""


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
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(HELP)
        return 0
    application = load_app()
    run = cast(Callable[[str | None], int], application.main)
    directory = Path(sys.executable).resolve().parent if IS_FROZEN else SCRIPT_DIR
    return run(str(directory))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
