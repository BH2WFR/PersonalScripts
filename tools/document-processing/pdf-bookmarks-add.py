#!/usr/bin/env python3
"""Open the PDF directory recognition, bookmark editor and page-label desktop tool.

Mark TOC pages with editable red crop boxes, rotate recognition inputs, and run
a serial LiteLLM vision queue using compatible endpoints. Edit per-page YAML or the final tree.
Inspect page-specific model problems and request history, add missing information,
then retry that page or all TOC pages in order. Keep or clear the book's conversation;
limit context images (default 5 including the current page, 0 for unlimited).
Select provider presets or a custom API URL, fetch model choices, and fill TOC/body
page fields from the viewer with Use current page. Local Ollama/LM Studio presets
connect to an already running vision server; API keys are optional for local use.
HTTP local endpoints are supported; per-source Skip certificate verification defaults to off.
Display API account balances with automatic/manual refresh on supported services.
Shared model requests and PDF operations are provided by utils.Llm and utils.Pdf.
Drafts and PDF passwords stay in memory; no project files are used. API settings
and encrypted keys persist per source in llm.yaml. Startup/Load reads; Save and
window close write. Source switches restore in-memory drafts without file I/O.
Cached previews, current-page insertion, Ctrl/Shift batch selection and two modes
each for indent/outdent aid editing. Drag any selected subtrees together, including
nonconsecutive selections. Tooltips wrap within 250 logical pixels.
Click the viewer to use PgUp/PgDn or arrow keys for page navigation.
Exports preserve page content, suggest numbered filenames, confirm replacement
of existing outputs, and display a completion dialog. Close releases the PDF and
resets the window without exiting the application.
One physical book page per PDF page; split multi-page scans before recognition.

Requirements:
    - pip: PySide6, PyMuPDF, PyYAML, cryptography, litellm, openai, httpx, truststore.
Usage:
    conda run -n base python tools/document-processing/pdf-bookmarks-add.py
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


def load_app(module: str = "bookmarks.app") -> ModuleType:
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
    """Start the desktop UI or its private worker; no terminal conversion mode."""
    if "--help" in sys.argv or "-h" in sys.argv:
        Console.print_banner("PDF BOOKMARKS & PAGE LABELS")
        print(f"""Usage:
  python pdf-bookmarks-add.py

Description:
  Recognize cropped TOC pages with a vision API, edit YAML/bookmarks and page labels,
  and export a new PDF. Includes API testing, cached previews, clear/undo bookmarks
  and two indent/outdent modes. Ctrl/Shift selects multiple bookmarks; drag selected
  subtrees together, including nonconsecutive selections. Indent can move descendants
  or just the selected items while keeping reading order. Tooltips wrap at 250 px.
  Drafts stay in memory; there are no project files. API settings and encrypted
  keys persist per source in llm.yaml. Startup/Load reads; Save/window close writes.
  Switching sources restores drafts without I/O. Busy config errors appear in tooltips.
  Click the viewer to turn pages with PgUp/PgDn or the arrow keys.
  API presets include Kimi, Alibaba Model Studio, OpenRouter, SiliconFlow, Ollama
  and LM Studio. Local use requires a running vision server; keys may be empty.
  Custom/LAN URLs and model names are supported. Get models sends no PDF content.
  HTTP local endpoints need no TLS setting. Skip certificate verification is per source,
  off by default, and applies to HTTPS inference, API tests, catalogs and balances.
  Use current page fills the first/last TOC page or first body PDF page field.
  API balance stays visible; refresh after editing credentials or completing a run.
  DeepSeek/Kimi China are supported; OpenRouter requires an optional balance-only
  management key. Unsupported providers show a reason. Balance queries send no PDF.
  Shared model requests and PDF operations are reusable through utils.Llm / utils.Pdf.
  Model problems retain page-specific request/reply history; add page information
  and retry this page or all TOC pages. Keep or clear conversation before a run.
  Each page waits for the previous response; unresolved drafts block export.
  Context images default to 5 INCLUDING the current image; 1 keeps only the current
  image, 0 is unlimited. Older images are omitted while text/replies remain.
  Close releases the PDF and resets the window. Export suggests numbered filenames,
  asks before replacing existing outputs, and shows a completion dialog.

Options:
  -h, --help  Show this help.

Requirements:
  pip: PySide6, PyMuPDF, PyYAML, cryptography, litellm, openai, httpx, truststore.
""")
        return 0
    try:
        importlib.import_module("truststore")
        if "--pdf-tools-worker" in sys.argv:
            return cast(Callable[[], int], load_app("bookmarks.worker").main)()
        return cast(Callable[[Path], int], load_app().main)(Path(__file__).resolve())
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
        print(f"{FGray}Install: pip install PySide6 PyMuPDF PyYAML cryptography litellm openai httpx truststore{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
