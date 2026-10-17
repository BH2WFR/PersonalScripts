#!/usr/bin/env python3
"""Remove PDF encryption, permission restrictions, and PDF/A identification.

Permission-only protection opens automatically; opening passwords are requested
privately. Retains pages, bookmarks, named destinations, metadata and attachments.
Unencrypted, unrestricted PDFs with PDF/A identification are also supported;
the script explains that only this identification will be removed. Other metadata
is retained. If none of these features is present, choose another input or exit
without requesting an output path or writing a copy.
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
    """Remove protection and/or PDF/A identification; return 0 on success or exit.

    Prompts for paths/password and writes a new ordinary PDF when needed.
    An unrestricted input without PDF/A offers reopen/exit instead of saving.
    Returns 1 on input, metadata, authentication, or save failure.
    """
    Console.print_banner("PDF DECRYPT / PDF/A REMOVAL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
PDF DECRYPT / PDF/A REMOVAL

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
  Also removes PDF/A identification from PDFs with no encryption or restrictions.
  When only PDF/A identification is present, prints an informational message.
  When none of these features is present, warns and offers another input or exit;
  no output is requested or written for that file.
  Preserves document structure (pages, bookmarks, named destinations, attachments)
  and other metadata. Saves a new PDF without encryption or PDF/A identification.

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
    while True:
        filepath = _arg_path or Input.resolve_input_path(
            DEFAULT_INPUT, prompt="Enter input PDF file path", path_type="file",
        )
        _arg_path = None  # A retry must request a new path, even with a CLI input.
        if not filepath or not os.path.exists(filepath):
            print(f"{FLRed}Invalid input file path. EXIT...{CRst}\n")
            return 1

        try:
            with Pdf.open_document(filepath) as (document, _):
                print(f"{FLGreen}PDF loaded successfully. Total pages: {document.page_count}{CRst}")
                # is_encrypted becomes False after authentication; the trailer
                # still identifies encryption, including owner-only protection.
                protected = document.xref_get_key(-1, "Encrypt")[0] != "null"
                has_pdfa = Pdf.has_pdfa_identification(document)
                if not protected and not has_pdfa:
                    print(f"{FLYellow}WARNING: No encryption, permission restrictions, or PDF/A identification found."
                          f" No processing is needed.{CRst}")
                    reopen = Menu.select(
                        [MenuOption(["R"], "Open another PDF", True),
                         MenuOption(["X"], "Exit", False)],
                        prompt="Next action", required=True, default_key="X", separator=False,
                    )
                    if reopen:
                        continue
                    Console.print_exit_message("No PDF written.")
                    return 0
                if has_pdfa and not protected:
                    print("No encryption or permission restrictions found; only PDF/A identification will be removed.")
                elif has_pdfa:
                    print("PDF/A identification will also be removed.")

                _stem, _ext = os.path.splitext(os.path.basename(filepath))
                default_output = os.path.join(os.path.dirname(filepath) or ".", f"{_stem}_decrypted{_ext or '.pdf'}")
                output_path = Input.resolve_output_path(
                    _arg_output or default_output, prompt="Enter output PDF file path", path_type="file",
                )
                print("  -> writing an unprotected PDF without PDF/A identification...")
                Pdf.save_new(document, output_path)
        except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
            print(f"{FLRed}PDF processing failed: {exc}{CRst}")
            return 1

        print(f"{FLGreen}Processed PDF saved to: {output_path}{CRst}\n")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        Console.print_keyboard_interrupt_message_and_exit()
