#!/usr/bin/env python3
"""Launch the metadata editor and its isolated PDF worker."""

import argparse
import importlib
from pathlib import Path
import sys

ENTRY = Path(__file__).resolve()
sys.path.insert(0, str(ENTRY.parents[2]))
from utils import *  # noqa: E402

HELP = """PDF METADATA EDITOR

Edit document properties, multilingual titles, custom fields and XMP in a separate PDF. Set or remove
PDF/A identification, permissions or opening passwords. PDF/A tags alone do
not establish archival conformance.

Requirements:
  PySide6, PyMuPDF >= 1.28, PyYAML.

Usage:
  python pdf-metadata-editor.py [INPUT.pdf]
"""


def main() -> int:
    """Start the GUI or serve requests from its private worker."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--pdf-tools-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    module = "metadata.worker" if args.pdf_tools_worker else "metadata.app"
    try:
        if not args.pdf_tools_worker:
            importlib.import_module("yaml")
        if getattr(sys, "frozen", False) or "__compiled__" in globals():
            app = importlib.import_module(f"personal_pdf_tools.{module}")
        else:
            app = importlib.import_module("pdf-ocr").load_app(module)
        return app.main() if args.pdf_tools_worker else app.main(ENTRY, args.source)
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}. Install the packages listed in --help.{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
