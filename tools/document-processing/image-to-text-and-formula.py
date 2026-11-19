#!/usr/bin/env python3
"""Launch batch image OCR or its private serial worker."""

import importlib
from importlib.util import find_spec
from pathlib import Path
import sys

ENTRY = Path(__file__).resolve()
sys.path.insert(0, str(ENTRY.parents[2]))
from utils import *

HELP = """IMAGE TO TEXT AND FORMULA

Extract text or formulas from files and clipboard images, individually or in batches.
Use local OCR or a vision API with separate text and formula conversations. Export text, Markdown or LaTeX.

Requirements:
  Python packages: PySide6, Pillow, RapidOCR, ONNX Runtime, NumPy, OpenCV, PyMuPDF,
  litellm, openai, httpx and truststore.
  API recognition requires a cloud or local vision endpoint.
  Optional offline formulas: PaddlePaddle CPU, tokenizers and the PaddleOCR LaTeX_OCR_rec model.
  Optional Markdown/math preview: markdown-it-py, Qt WebEngine and local MathJax 2 SVG assets.

Usage:
  python image-to-text-and-formula.py
"""


def main() -> int:
    if "-h" in sys.argv or "--help" in sys.argv:
        print(HELP)
        return 0
    worker = "--pdf-tools-worker" in sys.argv
    module = "ocr.worker" if worker else "ocr.image_app"
    if not worker:
        missing = [name for name in ("litellm", "openai", "httpx", "truststore") if find_spec(name) is None]
        if missing:
            print("Missing required Python packages. Install with: python -m pip install " + " ".join(missing))
            return 1
    try:
        if getattr(sys, "frozen", False) or "__compiled__" in globals():
            app = importlib.import_module(f"personal_pdf_tools.{module}")
        else:
            app = importlib.import_module("pdf-ocr").load_app(module)
        return app.main() if worker else app.main(ENTRY)
    except ImportError as exc:
        print(f"Missing dependency: {exc.name}. Install the packages listed in --help.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
