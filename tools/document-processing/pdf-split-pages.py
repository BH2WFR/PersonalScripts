#!/usr/bin/env python3
"""Split PDF pages with a visual, non-rasterizing PySide6 desktop application.

Open or drop a PDF; choose strip count, direction, order and physical page range.
Preview colored numbered crops. Keep individual pages whole or adjust their crop
boxes/shared dividers in displayed-page points. Per-page overrides stay independent
of global rules. Move all frames or one frame; equal-size output pages pad outside
areas with white and center smaller crops. Page lists include output start indexes.
Original previews are cached; geometry edits update 50%-opacity overlays only.
The Crop selector defaults to All; X/Y/width/height have +/-10 pt buttons.
Parameter labels and controls provide wrapped tooltips.
Exports retain original PDF resources, annotations and metadata, remap bookmarks
and supported links, and remove all navigation page labels. Ambiguous destinations
target the first crop and are reported. Sources cannot be overwritten.
Settings stay in memory; use Export PDF to save beside the input.

Requirements:
    - pip: PySide6, PyMuPDF, tqdm, PyYAML, cryptography.
Usage:
    conda run -n base python tools/document-processing/pdf-split-pages.py
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
        Console.print_banner("PDF SPLIT PAGES")
        print("""Usage:
  python pdf-split-pages.py

Description:
  Open/drop a PDF. Set pieces per page, left/right or top/bottom arrangement,
  output order and first/last physical page. Pages outside the range stay whole.
  Per-page controls keep pages whole, move shared dividers, or edit crop rectangles.
  Move all frames or one frame. Output paper stays equal-sized; out-of-page areas
  are blank, and smaller crops are centered at their original scale.
  50%-opacity colored frames and large numbers show order; they are never exported.
  The page list shows whole/custom status and the first resulting output page.
  Crop defaults to All; choose a number for single-frame edits. X/Y/width/height
  have +/-10 pt buttons. Hover parameter labels/controls for wrapped hints.
  Coordinates are displayed-page points (1/72 inch), independent of preview zoom.
  Reuse cached originals, zoom/pan, and viewer-focused PgUp/PgDn/arrow page keys.
  Pages/bookmarks are read-only navigation. Settings are session-only.
  Export crops existing PDF resources without resampling images or rasterizing text.
  Bookmarks and supported links are remapped; ambiguous targets use the first crop.
  All page labels are removed, including those on whole pages; printed numbers stay.
  Save beside the source by default. Sources are protected; replacing an existing
  output requires confirmation. Output has no encryption or PDF/A identification.

Options:
  -h, --help  Show this help. Open/drop PDFs in the GUI.

Requirements:
  pip: PySide6, PyMuPDF, tqdm, PyYAML, cryptography.
""")
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
