#!/usr/bin/env python3
"""Implementation notes.

Load personal_pdf_tools.bookmarks through the shared package loader. Keep
model transport/settings in utils.Llm and document operations in utils.Pdf.
Recognition/session ownership and export invariants: pdf-tools/bookmarks/README.md.
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

HELP = f"""{FLYellow}PDF BOOKMARK EDITOR{CRst}

Recognize a table of contents with a vision model, edit bookmarks and page labels,
and export a new PDF without changing page content. Selected TOC images are sent
to the configured API; recognition drafts stay in memory.

{FLYellow}Requirements:{CRst}
  PySide6, PyMuPDF, PyYAML, cryptography, litellm, openai, httpx, truststore.
  A vision API or running local vision model is required for recognition.

{FLYellow}Usage:{CRst}
  python pdf-bookmark-editor.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


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
        Console.print_banner("PDF BOOKMARK EDITOR")
        print(HELP)
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
