#!/usr/bin/env python3
"""Cross-platform PDF compression using Ghostscript."""

import os
import sys
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


# ============ system checks ============
_gs = CmdCheck(
    ["gswin64c", "gs"] if sys.platform == "win32" else "gs",
    hints={
        "any": f"{FGray}Installation guide:{CRst}",
        "windows": f"{FLCyan}  scoop install ghostscript{CRst}\n  {FGray}or download from: https://ghostscript.com/releases/gsdnld.html{CRst}",
        "macos": f"{FLCyan}  brew install ghostscript{CRst}",
        "linux": f"{FLCyan}  sudo apt install ghostscript{CRst}",
    },
)
if not Environment.check_commands(_gs):
    sys.exit(1)
GS_BIN = _gs.path


# ============ help ============
if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}PDF COMPRESS{CRst}
============

Usage:
  python {script_name}                interactive mode
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  Compress PDF files using Ghostscript.

  Two compression modes:
    [E] Ebook    — standard compression, balanced quality/size (gs -dPDFSETTINGS=/ebook)
    [C] Custom   — fine-tune image DPI, compression quality, and downsampling

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install ghostscript{CRst}
  Linux (apt):      {FGray}sudo apt install ghostscript{CRst}
  macOS (brew):     {FGray}brew install ghostscript{CRst}
""")
    sys.exit(0)


# ============ helpers ============
def _build_ebook_cmd(input_path, output_path):
    """Build the Ghostscript command line for Ebook compression."""
    return [
        GS_BIN, "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/ebook",
        "-dNOPAUSE", "-dBATCH", "-dSAFER",
        f"-sOutputFile={output_path}",
        input_path,
    ]


def _build_custom_cmd(input_path, output_path):
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
        GS_BIN, "-sDEVICE=pdfwrite",
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
        input_path,
    ]


def _run_gs(cmd: list[str], input_path: str, output_path: str) -> None:
    """Execute the Ghostscript command and print the result."""
    print(f"\n{FGray}Running:{CRst} {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        in_size = os.path.getsize(input_path)
        out_size = os.path.getsize(output_path)
        ratio = (1 - out_size / in_size) * 100 if in_size > 0 else 0
        print(f"\n{FLGreen}Compressed successfully.{CRst}")
        print(f"{FGray}Before:{CRst} {FLYellow}{Console.format_size(in_size)}{CRst}")
        print(f"{FGray}After: {CRst} {FLYellow}{Console.format_size(out_size)}{CRst}  "
              f"{FGray}({FLGreen}-{ratio:.1f}%{FGray}){CRst}\n")
    else:
        print(f"\n{FLRed}Ghostscript exited with code {result.returncode}.{CRst}\n")


# ============ main ============
def main():
    Console.print_banner("PDF COMPRESS")
    print()

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

        # 2. output file
        _stem, _ext = os.path.splitext(os.path.basename(input_path))
        default_output = os.path.join(os.path.dirname(input_path), f"{_stem}_compressed{_ext or '.pdf'}")
        output_path = Input.resolve_output_path(default_output, prompt="Output path", path_type="file")
        print(f"{FGray}Output:{CRst} {FLGreen}{output_path}{CRst}\n")

        # 3. compression mode
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
            sys.exit(0)
        print()

        if choice == "E":
            cmd = _build_ebook_cmd(input_path, output_path)
        else:
            cmd = _build_custom_cmd(input_path, output_path)

        # 4. run
        _run_gs(cmd, input_path, output_path)

        # Loop back to input step
        Console.print_separator(width=60, color_ansi_esc=FLCyan)
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
