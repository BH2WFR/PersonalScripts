#!/usr/bin/env python3
"""Save an unencrypted copy of a PDF, preserving its document structure.

Permission-only protection opens automatically; opening passwords are requested
privately. Retains pages, bookmarks, named destinations, metadata and attachments.
Existing output files are never overwritten. Requires PyMuPDF (including AES).

Usage:
    python pdf-decrypt.py input.pdf -o output.pdf
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

import pymupdf
from pymupdf.mupdf import FzErrorBase
from typing import Optional


def main() -> int:
    """Prompt for paths/password, save a decrypted copy, and return 0 or 1.

    Writes a new PDF and prints progress; returns 1 on input or save failure.
    """
    Console.print_banner("PDF DECRYPTING TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
PDF DECRYPTING TOOL
===================

Usage:
  python {script_name} <input.pdf>                     specify input PDF, output interactive
  python {script_name} <input.pdf> -o <output.pdf>     specify both input and output
  python {script_name} --help                          show this help

{FLYellow}Arguments:{CRst}
  <input.pdf>          input PDF file path
  -o, --output <path>  output PDF file path
  -h, --help           show this help

{FLYellow}Description:{CRst}
  Decrypt password-protected PDFs (including permission-only protection).
  Clones the full document structure (pages, bookmarks, named destinations)
  and outputs a completely decrypted PDF.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install PyMuPDF{CRst}
""")
        return 0

    #============ 命令行参数解析 ===========
    _arg_path: Optional[str] = None
    _arg_output: Optional[str] = None
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "-o" or arg == "--output":
            i += 1
            if i < len(sys.argv):
                _arg_output = sys.argv[i]
        elif not arg.startswith("-"):
            _arg_path = arg
        i += 1

    #============ 默认路径 (OS-aware) ===========
    if sys.platform == "win32":
        DEFAULT_INPUT = "D:/input.pdf"
    else:
        DEFAULT_INPUT = os.path.expanduser("~/input.pdf")

    #============ 用户交互 ===========
    filepath = _arg_path if _arg_path else Input.resolve_input_path(
        DEFAULT_INPUT,
        prompt="Enter input PDF file path",
        path_type="file",
    )

    if not filepath or not os.path.exists(filepath):
        print(f"{FLRed}Invalid input file path. EXIT...{CRst}\n")
        return 1

    # 默认输出路径：输入文件名 + _decrypted 后缀
    _stem, _ext = os.path.splitext(os.path.basename(filepath))
    _default_output = os.path.join(os.path.dirname(filepath) or ".", f"{_stem}_decrypted{_ext or '.pdf'}")

    output_path = Input.resolve_output_path(
        _arg_output if _arg_output else _default_output,
        prompt="Enter output PDF file path",
        path_type="file",
    )

    print(f"{FLYellow}  -> start parsing...{CRst}")
    try:
        with pymupdf.open(filepath) as document:
            Pdf.unlock(document)
            print(f"{FLGreen}PDF loaded successfully. Total pages: {document.page_count}{CRst}")
            print("  -> writing decrypted document (pages + outline + structure)...")
            Pdf.save_new(document, output_path)
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}Decryption failed: {exc}{CRst}")
        return 1

    # 结束
    print(f"{FLGreen}Decrypted PDF saved to: {output_path}{CRst}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
