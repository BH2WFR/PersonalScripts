#!/usr/bin/env python3
"""Cross-platform PDF compression using Ghostscript."""

import os
import sys
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
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
if not Utils.check_commands(_gs):
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
def _fmt_size(size_bytes):
    """Format file size in human-readable form."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _prompt_numeric(prompt: str, default: int, lo: int, hi: int) -> int:
    """Prompt for an integer within [lo, hi], return default on empty input."""
    while True:
        raw = input(f"{FLCyan}{prompt} {FGray}[{default}]{CRst}: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if lo <= val <= hi:
                return val
            print(f"{FLRed}Value out of range [{lo}–{hi}].{CRst}")
        except ValueError:
            print(f"{FLRed}Invalid number.{CRst}")


def _prompt_input_path() -> str:
    """Prompt for a PDF input path. Returns a valid absolute path, or
    exits the process via ``sys.exit(0)`` when the user presses Enter."""
    while True:
        try:
            raw = input(
                f"{FLYellow}Input PDF path {FGray}[Enter to exit]{CRst}: "
            ).strip()
        except EOFError:
            print()
            Utils.print_exit_message("Bye.")
            sys.exit(0)
        if not raw:
            Utils.print_exit_message("Bye.")
            sys.exit(0)

        raw = raw.strip("'\"")
        path = os.path.expanduser(raw)
        path = os.path.expandvars(path)
        path = os.path.abspath(path)

        if not os.path.isfile(path):
            print(f"{FLRed}File does not exist: {FGray}{path}{CRst}\n")
            continue
        if not path.lower().endswith(".pdf"):
            print(f"{FLRed}Not a PDF file:{CRst} {FGray}{path}{CRst}\n")
            continue
        return path


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
    color_dpi    = _prompt_numeric("Color image DPI", 200, 36, 2400)
    gray_dpi     = _prompt_numeric("Gray image DPI",  200, 36, 2400)
    mono_dpi     = _prompt_numeric("Mono image DPI",  300, 36, 2400)
    jpeg_quality = _prompt_numeric("JPEG quality (1–100)", 50, 1, 100)
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
        print(f"{FGray}Before:{CRst} {FLYellow}{_fmt_size(in_size)}{CRst}")
        print(f"{FGray}After: {CRst} {FLYellow}{_fmt_size(out_size)}{CRst}  "
              f"{FGray}({FLGreen}-{ratio:.1f}%{FGray}){CRst}\n")
    else:
        print(f"\n{FLRed}Ghostscript exited with code {result.returncode}.{CRst}\n")


# ============ main ============
def main():
    Utils.print_banner("PDF COMPRESS")
    print()

    while True:
        # 1. input file
        input_path = _prompt_input_path()
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
            Utils.print_exit_message("Bye.")
            sys.exit(0)
        print()

        if choice == "E":
            cmd = _build_ebook_cmd(input_path, output_path)
        else:
            cmd = _build_custom_cmd(input_path, output_path)

        # 4. run
        _run_gs(cmd, input_path, output_path)

        # Loop back to input step
        Utils.print_separator(width=60, color_ansi_esc=FLCyan)
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
