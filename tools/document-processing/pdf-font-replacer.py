#!/usr/bin/env python3
"""Implementation notes.

Load personal_pdf_tools.font_replace through the shared package loader.
Matching uses original text and the first ordered rule; keep preview/export
on the same engine. Ownership and supported encodings: pdf-tools/font_replace/README.md.
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

HELP = f"""{FLYellow}PDF FONT REPLACER{CRst}

Replace fonts or recolor text using ordered rules and page ranges, with previews.
Preserves text positions and document features without reflow or rasterization.
Missing glyphs/styles fail explicitly; exports remove encryption and PDF/A tags.

{FLYellow}Requirements:{CRst}
  PySide6, PyMuPDF>=1.28, fonttools, tqdm, PyYAML, cryptography.

{FLYellow}Usage:{CRst}
  python pdf-font-replacer.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


PACKAGE_NAME = "personal_pdf_tools"


def load_app(module: str = "font_replace.app") -> ModuleType:
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
    """Start the desktop UI or its private worker; replacement settings are GUI-only."""
    if "--help" in sys.argv or "-h" in sys.argv:
        Console.print_banner("PDF FONT REPLACER")
        print(HELP)
        return 0
    try:
        if "--pdf-tools-worker" in sys.argv:
            return cast(Callable[[], int], load_app("font_replace.worker").main)()
        return cast(Callable[[Path], int], load_app().main)(Path(__file__).resolve())
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF fonttools tqdm PyYAML cryptography{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
