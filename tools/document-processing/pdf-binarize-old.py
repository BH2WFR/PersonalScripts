#!/usr/bin/env python3
"""Interactively compress PDF images while retaining native page objects.

Images use fixed/Sauvola thresholding, optional denoising and separate illustration
crops. The binary background uses CCITT Group 4; crops support keep, gray8,
gray2/4 and color2/4. Optional vector conversion maps non-white paint to black.
Text, OCR, links, annotations, geometry and bookmark destinations are retained.
Run without arguments; preview, skip pages and output settings are interactive.
Full conversion defaults to skipping physical pages 1,2; enter none to process all.
See pdf-tools/binarize/README.md for the shared processing engine.

Requirements:
    - pip: PyMuPDF>=1.28, Pillow with libtiff, numpy, opencv-python, tqdm, pypdf.

Usage:
    conda run -n base python tools/document-processing/pdf-binarize-old.py
"""

import importlib
import runpy
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

PACKAGE_NAME = "personal_pdf_tools"


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
        entry = runpy.run_path(str(SCRIPT_DIR / "pdf-binarize.py"))
        loader = cast(Callable[[str], ModuleType], entry["load_app"])
        return loader("binarize.cli")
    return importlib.import_module(f"{PACKAGE_NAME}.binarize.cli")


def main() -> int:
    """Run the interactive PDF workflow and return its exit status."""
    try:
        application = load_app()
    except ImportError as exc:
        print(f"{FLRed}Missing PDF/image dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PyMuPDF Pillow numpy opencv-python tqdm pypdf{CRst}")
        return 1
    return cast(Callable[[], int], application.main)()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
