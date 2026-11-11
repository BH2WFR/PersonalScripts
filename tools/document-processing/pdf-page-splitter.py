#!/usr/bin/env python3
"""Implementation notes.

Load personal_pdf_tools.split_pages through the shared package loader.
Crop coordinates are displayed-page points; preserve output-paper origins
when remapping destinations. Ownership: pdf-tools/split_pages/README.md.
"""

import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Callable, cast

SCRIPT_DIR = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
if not IS_FROZEN:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))
from utils import *

HELP = f"""{FLYellow}PDF PAGE SPLITTER{CRst}

Split PDF pages into equal-size cropped pages with per-page overrides and padding,
without rasterizing text or resampling images. Remaps bookmarks and supported links.
Exports remove page labels, encryption and PDF/A identification; sources are kept.

{FLYellow}Requirements:{CRst}
  PySide6, PyMuPDF, tqdm, PyYAML, cryptography.

{FLYellow}Usage:{CRst}
  python pdf-page-splitter.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


PACKAGE_NAME = "personal_pdf_tools"


def load_app(module: str = "split_pages.app") -> ModuleType:
    """Load the shared private PDF package in source or packaged builds."""
    if PACKAGE_NAME not in sys.modules and not IS_FROZEN:
        directory = SCRIPT_DIR / "pdf-tools"
        spec = importlib.util.spec_from_file_location(PACKAGE_NAME, directory / "__init__.py",
                                                      submodule_search_locations=[str(directory)])
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load PDF tools from {directory}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.{module}")


def main() -> int:
    """Start the GUI or its private worker; split settings are edited in the window."""
    if "--help" in sys.argv or "-h" in sys.argv:
        Console.print_banner("PDF PAGE SPLITTER")
        print(HELP)
        return 0
    try:
        if "--pdf-tools-worker" in sys.argv:
            return cast(Callable[[], int], load_app("split_pages.worker").main)()
        return cast(Callable[[Path], int], load_app().main)(Path(__file__).resolve())
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF tqdm PyYAML cryptography{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
