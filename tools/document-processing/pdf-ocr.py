#!/usr/bin/env python3
"""Load the shared OCR GUI or its serial worker without starting work on import."""

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

HELP = f"""{FLYellow}PDF OCR{CRst}

Add invisible, selectable text to scanned PDFs using small local PaddleOCR models.
Supports CJK, English and downloadable language models; preserves page content.
Exports remove encryption and PDF/A tags.

{FLYellow}Requirements:{CRst}
  PySide6, PyMuPDF>=1.28, fonttools, rapidocr>=3.10,<4, onnxruntime,
  OpenCV, NumPy, PyYAML, httpx, cryptography.

{FLYellow}Usage:{CRst}
  python pdf-ocr.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    Console.print_help_and_exit(HELP)

PACKAGE_NAME = "personal_pdf_tools"


def load_app(module: str = "ocr.app") -> ModuleType:
    """Load the private PDF package in source and compiled applications."""
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
    """Start the GUI or its private worker; all OCR settings are GUI-only."""
    Console.initialize_ansi_output()
    if "--help" in sys.argv or "-h" in sys.argv:
        print(HELP)
        return 0
    try:
        if "--pdf-tools-worker" in sys.argv:
            return cast(Callable[[], int], load_app("ocr.worker").main)()
        return cast(Callable[[Path], int], load_app().main)(Path(__file__).resolve())
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF fonttools rapidocr onnxruntime PyYAML cryptography{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
