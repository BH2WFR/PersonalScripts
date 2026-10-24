#!/usr/bin/env python3
"""Interactively compress PDF images while retaining native page objects.

Images use fixed/Sauvola thresholding, optional denoising and separate illustration
crops. The binary background uses CCITT Group 4; crops support keep, gray8,
gray2/4 and color2/4. Optional vector conversion maps non-white paint to black.
Text, OCR, links, annotations, geometry and bookmark destinations are retained.
Run without arguments; preview, skip pages and output settings are interactive.
See pdf-binarize/README.md for processing details and supported PDF constructs.

Requirements:
    - pip: PyMuPDF>=1.28, Pillow with libtiff, numpy, opencv-python, tqdm, pypdf.

Usage:
    conda run -n base python tools/document-processing/pdf-binarize.py
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

PACKAGE_NAME = "personal_pdf_binarize"


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
        package_dir = SCRIPT_DIR / "pdf-binarize"
        spec = importlib.util.spec_from_file_location(
            PACKAGE_NAME, package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load PDF binarizer from {package_dir}")
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE_NAME] = package
        try:
            spec.loader.exec_module(package)
        except BaseException:
            sys.modules.pop(PACKAGE_NAME, None)
            raise
    return importlib.import_module(f"{PACKAGE_NAME}.app")


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
