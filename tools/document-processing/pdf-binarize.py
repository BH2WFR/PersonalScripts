#!/usr/bin/env python3
"""Open the PDF binarizer desktop application.

Images use fixed/Sauvola thresholding, optional denoising and separate illustration
crops. The binary background uses CCITT Group 4; crops support keep, gray8,
gray2/4 and color2/4. Optional vector conversion maps non-white paint to black.
Text, OCR, links, annotations, geometry and bookmark destinations are retained.
Drag in a PDF or open a JSON project. Assign reusable profiles to physical pages,
preview originals/results, and export beside the source. All pages start with
default; Ctrl/Shift-select pages to apply a profile together. Completed previews
are cached for immediate revisits; original views skip the navigation delay.
The viewer supports auto-fit on page turns, editable zoom, focused page keys and
optional red region outlines that stay out of exported PDFs.
On Windows, start without administrator rights to accept Explorer file drops;
Open PDF also works when launched by an elevated terminal/editor.
See pdf-tools/README.md for processing, project and navigation details.

Requirements:
    - pip: PySide6, PyMuPDF>=1.28, Pillow with libtiff, numpy, opencv-python,
      tqdm, pypdf>=6.

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

PACKAGE_NAME = "personal_pdf_tools"
WORKER_ARGUMENT = "--pdf-tools-worker"


def load_app(module: str = "binarize.app") -> ModuleType:
    """Load the private application once, using its valid Python package alias.

    Args:
        module: Relative module inside the private PDF tools package.

    Returns:
        The application module. Frozen builds import the staged package directly.

    Raises:
        ImportError: Package files or a required import cannot be loaded.

    Side effects:
        Registers source packages in sys.modules; performs no disk scan or sync.
    """
    if PACKAGE_NAME not in sys.modules and not IS_FROZEN:
        package_dir = SCRIPT_DIR / "pdf-tools"
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
    return importlib.import_module(f"{PACKAGE_NAME}.{module}")


def main() -> int:
    """Start the desktop app or its private worker, returning an exit status."""
    try:
        if WORKER_ARGUMENT in sys.argv:
            return cast(Callable[[], int], load_app("binarize.worker").main)()
        application = load_app()
    except ImportError as exc:
        print(f"{FLRed}Missing PDF/image dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF Pillow numpy opencv-python tqdm pypdf{CRst}")
        return 1
    return cast(Callable[[Path], int], application.main)(Path(__file__).resolve())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
