#!/usr/bin/env python3
"""Compress PDFs with Ghostscript after shared opening-password authentication.

Requires Ghostscript and PyMuPDF. Writes a new PDF without password or permission
restrictions. Temporary decrypted input and compressed output are cleaned up on
success, failure, or interruption; existing files are never overwritten.

Usage: python pdf-compress.py
"""

import os
import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

if TYPE_CHECKING:
    import pymupdf


# ============ help ============
def _print_help() -> None:
    """Print usage without probing external dependencies."""
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}PDF COMPRESS{CRst}
============

Usage:
  python {script_name}                interactive mode
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  Compress PDF files using Ghostscript.
  Opens protected PDFs through the shared password prompt, with retry/cancellation.
  Writes a new PDF without password or editing restrictions; never overwrites files.
  Temporary decrypted input and compressed output are removed after processing.

  Two compression modes:
    [E] Ebook    — standard compression, balanced quality/size (gs -dPDFSETTINGS=/ebook)
    [C] Custom   — fine-tune image DPI, compression quality, and downsampling

{FLYellow}Options:{CRst}
  -h, --help       show this help

{FLYellow}Requirements:{CRst}
  Python:          {FGray}pip install PyMuPDF{CRst}
  Windows (scoop):  {FGray}scoop install ghostscript{CRst}
  Linux (apt):      {FGray}sudo apt install ghostscript{CRst}
  macOS (brew):     {FGray}brew install ghostscript{CRst}
""")


# ============ helpers ============
def _build_ebook_cmd(gs_binary: str, input_path: Path, output_path: Path) -> list[str]:
    """Build the Ghostscript command line for Ebook compression."""
    return [
        gs_binary, "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/ebook",
        "-dNOPAUSE", "-dBATCH", "-dSAFER",
        f"-sOutputFile={output_path}",
        str(input_path),
    ]


def _build_custom_cmd(gs_binary: str, input_path: Path, output_path: Path) -> list[str]:
    """Prompt for downsampling settings, then build the Ghostscript command line."""
    print(f"\n{FLYellow}Image downsampling settings:{CRst}\n")
    color_dpi = int(Input.input_number(
        "Color image DPI",
        default=200,
        min_value=36,
        max_value=2400,
        allow_float=False,
        allow_negative=False,
    ))
    gray_dpi = int(Input.input_number(
        "Gray image DPI",
        default=200,
        min_value=36,
        max_value=2400,
        allow_float=False,
        allow_negative=False,
    ))
    mono_dpi = int(Input.input_number(
        "Mono image DPI",
        default=300,
        min_value=36,
        max_value=2400,
        allow_float=False,
        allow_negative=False,
    ))
    jpeg_quality = int(Input.input_number(
        "JPEG quality",
        default=50,
        min_value=1,
        max_value=100,
        allow_float=False,
        allow_negative=False,
    ))
    print()
    return [
        gs_binary, "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={color_dpi}",
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={gray_dpi}",
        "-dDownsampleMonoImages=true",
        f"-dMonoImageResolution={mono_dpi}",
        f"-dJPEGQ={jpeg_quality}",
        f"-sOutputFile={output_path}",
        str(input_path),
    ]


def _compress_document(
    document: "pymupdf.Document", input_path: Path, output_path: Path, gs_binary: str,
    build_command: Callable[[str, Path, Path], list[str]],
) -> None:
    """Stage authenticated input/output; publish only a valid unprotected PDF.

    No password is passed in command arguments or printed. Shared exclusive save
    protects existing files, including a destination created during compression.
    The caller owns the input document; this function changes it only as save_new
    normally does. Raises on Ghostscript, validation, or output failure.
    """
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise FileExistsError(f"Output must be a new file: {output_path}")
    with TemporaryDirectory(prefix=".pdf-compress-", dir=output_path.parent) as folder:
        prepared = Path(folder) / "input.pdf"
        compressed = Path(folder) / "compressed.pdf"
        Pdf.save_new(document, prepared, compact=False)
        cmd = build_command(gs_binary, prepared, compressed)
        print(f"\n{FGray}Running:{CRst} {' '.join(cmd)}\n")
        subprocess.run(cmd, check=True)
        with Pdf.open_document(compressed, interactive=False) as (result, _):
            Pdf.save_new(result, output_path)
    in_size = input_path.stat().st_size
    out_size = output_path.stat().st_size
    ratio = (1 - out_size / in_size) * 100 if in_size > 0 else 0
    print(f"\n{FLGreen}Compressed successfully.{CRst}")
    print(f"{FGray}Before:{CRst} {FLYellow}{Console.format_size(in_size)}{CRst}")
    print(f"{FGray}After: {CRst} {FLYellow}{Console.format_size(out_size)}{CRst}  "
          f"{FGray}(size reduction: {ratio:.1f}%){CRst}\n")


# ============ main ============
def main() -> int:
    """Prompt for PDFs and compression settings; return 0 on exit or 1 on failure.

    Authenticates before processing. Prints progress and writes new unprotected
    PDFs, retaining the input files. EOF / Ctrl+C propagate to the entry point.
    """
    if "--help" in sys.argv or "-h" in sys.argv:
        _print_help()
        return 0
    Console.print_banner("PDF COMPRESS")

    # ── dependency checks ──────────────────────────────────
    try:
        import pymupdf
        from pymupdf.mupdf import FzErrorBase
    except ImportError as exc:
        print(f"{FLRed}ERROR: Missing dependency: {exc.name}{CRst}")
        print(f"  Install with: {FGray}pip install PyMuPDF{CRst}")
        return 1
    gs = CmdCheck(
        ["gswin64c", "gs"] if sys.platform == "win32" else "gs",
        hints={
            "windows": f"{FGray}scoop install ghostscript{CRst}",
            "macos": f"{FGray}brew install ghostscript{CRst}",
            "linux": f"{FGray}sudo apt install ghostscript{CRst}",
        },
    )
    if not Environment.check_commands(gs) or gs.path is None:
        return 1

    while True:
        # 1. input file
        while True:
            input_path = Input.resolve_input_path(
                "",
                prompt="Input PDF path",
                path_type="file",
            )
            if input_path.casefold().endswith(".pdf"):
                break
            print(f"{FLRed}Not a PDF file:{CRst} {FGray}{input_path}{CRst}\n")
        print(f"{FGray}Input:{CRst}  {FLGreen}{input_path}{CRst}")

        try:
            with Pdf.open_document(input_path) as (document, _):
                if not document.page_count:
                    raise ValueError("The PDF contains no pages.")
                source = Path(input_path)
                default_output = str(source.with_name(f"{source.stem}_compressed.pdf"))
                output_path = Input.resolve_output_path(default_output, prompt="Output path", path_type="file")
                print(f"{FGray}Output:{CRst} {FLGreen}{output_path}{CRst}\n")
                print(f"{FLYellow}Compression mode:{CRst}")
                choice = Menu.select(
                    [
                        MenuOption(["E", "EBOOK"], f"{FGray}Ebook{CRst}    — standard compression (gs -dPDFSETTINGS=/ebook)"),
                        MenuOption(["C", "CUSTOM"], f"{FGray}Custom{CRst}   — control image DPI, quality, and downsampling"),
                    ],
                    prompt="Select mode", separator=False,
                )
                if choice is None:
                    Console.print_exit_message("Bye.")
                    return 0
                builder = _build_ebook_cmd if choice == "E" else _build_custom_cmd
                _compress_document(document, source, Path(output_path), gs.path, builder)
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, pymupdf.FileDataError, FzErrorBase) as exc:
            print(f"{FLRed}PDF compression failed: {exc}{CRst}")
            return 1

        # Loop back to input step
        Console.print_separator(width=60, color_ansi_esc=FLCyan)
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        Console.print_keyboard_interrupt_message_and_exit()
