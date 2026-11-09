#!/usr/bin/env python3
"""Preview and replace PDF fonts in a PySide6 desktop application.

Open/drop a PDF; maintain ordered source/target rules on the left. Add, update,
delete, clear and reorder rules. The first match against original text wins.
Find source fonts/colors with Scan in pages (input dialog, default all), Scan all,
or Scan current for the viewed page. Source rows show type, embedding and sizes;
tooltips include PDF names, encodings, used pages and colors within the scan scope.
Load installed fonts or TTF/OTF/TTC/OTC files, then search names/localized aliases.
Visible results show aliases/styles; click one to assign its available family faces.
Filter sizes and original text colors; change fonts
and/or recolor text. Color-only mode keeps original fonts without re-embedding.
Apply to pages defaults to all; accepts 1,2,5-10,-1 via utils.Input, minus ignored
pages. Choose exact style faces, subset embedding (default) or full font embedding.
Page inputs offer All/Odd/Even controls synchronized with |odd / |even suffixes.
Compare raw/current results using cached previews, zoom/pan and page shortcuts.
Mark current draft filters on the visible page without Add / Update or a target
font; choose a preview-only color. Applied replacements supply the displayed fonts,
while matching still uses original text. Page turns update automatically; export is unchanged.
Page/bookmark navigation is read-only. Commit drafts with Add / Update.
Export preserves text positions, advances, drawing order and document features.
No reflow or rasterization; missing glyphs/styles and unsupported encodings fail.
Sources are protected. Outputs follow the unencrypted/non-PDF-A save policy.
Rules stay in memory. Active jobs finish before closing.

Requirements:
    - pip: PySide6, PyMuPDF>=1.28, fonttools, tqdm, PyYAML, cryptography.
Usage:
    conda run -n base python tools/document-processing/pdf-font-replace.py
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
        Console.print_banner("PDF FONT REPLACE")
        print("""Usage:
  python pdf-font-replace.py

Description:
  Ordered source/target rules, cached raw/result previews and read-only navigation.
  Add / Update commits a draft and refreshes the current page.
  Mark matches checks current draft font/size/source-color filters on the visible
  page using original text. Applied rules supply target fonts within their page
  scopes; draft filters need no Add / Update or target and ignore draft page ranges.
  Choose a preview-only color; page turns update automatically.
  Filter fonts, effective sizes and original text colors. Color-only mode keeps
  original fonts and needs no target font. Color fields accept hex/RGB or a picker.
  Apply to pages defaults to all; use 1,2,5-10,-1 (last), or none. Ignore pages
  is subtracted. Discovery pages only scope the font/color scan.
  Page inputs offer All/Odd/Even controls, or append |odd / |even to a range.
  Scan in pages opens a page input dialog defaulting to all. Scan all searches the
  whole PDF; Scan current immediately searches the viewed physical page.
  Source rows show PDF type, embedding and sizes; hover for names/encoding/pages/colors.
  Load installed fonts or a font file, type a search, then click a visible result.
  Result rows include localized aliases/styles; missing catalogs and no matches
  are reported explicitly. Search alone does not change the selected target.
  Search installed fonts/localized aliases or load font files; assign matching
  styles, subset (default) or full embedding, output color and original cleanup.
  First matching rule wins. Positions, advances and PDF features remain;
  no reflow or rasterization. Missing glyphs/styles fail without fallback.
  Click the viewer for PgUp/PgDn and arrow page keys. Rules stay in memory.
  Only Export writes PDFs. Outputs default beside the input; replacement of
  existing outputs requires confirmation. Sources are protected; outputs have
  no encryption or PDF/A identification.

Options:
  -h, --help  Show this help. Open/drop PDFs in the GUI.

Requirements:
  pip: PySide6, PyMuPDF>=1.28, fonttools, tqdm, PyYAML, cryptography.
""")
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
