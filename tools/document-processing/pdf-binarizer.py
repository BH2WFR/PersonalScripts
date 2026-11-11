#!/usr/bin/env python3
"""Implementation notes.

Load pdf-tools as personal_pdf_tools; keep private modules out of launcher
and compiler discovery. Stage the package recursively for bundled builds.
Processing ownership and invariants: pdf-tools/binarize/README.md and the
shared pdf-tools/README.md.
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

HELP = f"""{FLYellow}PDF BINARIZER{CRst}

Reduce scanned PDF size with binary text images and separate illustration settings,
while retaining native text, OCR, links and bookmarks. Supports per-page profiles.
Output removes encryption and PDF/A identification; source PDFs are preserved.

{FLYellow}Requirements:{CRst}
  PySide6, PyMuPDF>=1.28, pypdf>=6, Pillow with libtiff, numpy,
  opencv-python, tqdm, PyYAML, cryptography.

{FLYellow}Usage:{CRst}
  python pdf-binarizer.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


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
    if "--help" in sys.argv or "-h" in sys.argv:
        Console.print_banner("PDF BINARIZER")
        print(HELP)
        return 0
    try:
        if WORKER_ARGUMENT in sys.argv:
            return cast(Callable[[], int], load_app("binarize.worker").main)()
        application = load_app()
    except ImportError as exc:
        print(f"{FLRed}Missing PDF/image dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF Pillow numpy opencv-python tqdm pypdf PyYAML cryptography{CRst}")
        return 1
    return cast(Callable[[Path], int], application.main)(Path(__file__).resolve())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
