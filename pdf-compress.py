#!/usr/bin/env python3
"""Cross-platform PDF compression using Ghostscript."""

import os
import sys
import subprocess
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
from utils import *  # noqa: E402


# ============ system checks ============
GS_EXE = "gswin64c" if sys.platform == "win32" else "gs"
GS_MISSING = shutil.which(GS_EXE) is None and shutil.which("gs") is None

if GS_MISSING:
    print(f"{FLRed}ERROR: Ghostscript not found in PATH.{CRst}\n")
    print(f"{FGray}Installation guide:{CRst}")
    if sys.platform == "darwin":
        print(f"  {FLCyan}brew install ghostscript{CRst}")
    elif sys.platform == "win32":
        print(f"  {FLCyan}scoop install ghostscript{CRst}")
        print(f"  {FGray}or download from: https://ghostscript.com/releases/gsdnld.html{CRst}")
    else:
        print(f"  {FLCyan}apt install ghostscript{CRst}")
    print()
    sys.exit(1)

GS_BIN = shutil.which(GS_EXE) or shutil.which("gs")


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
  Ghostscript
""")
    sys.exit(0)


# ============ helpers ============
def _generate_output_path(input_path: str) -> str:
    """Generate default output path: input_compressed.pdf, avoiding overwrite."""
    dir_name = os.path.dirname(input_path) or "."
    base = os.path.basename(input_path)
    stem, ext = os.path.splitext(base)
    if not ext:
        ext = ".pdf"

    n = 0
    while True:
        suffix = "_compressed" if n == 0 else f"_compressed_{n}"
        candidate = os.path.join(dir_name, f"{stem}{suffix}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


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


def _fmt_size(size_bytes):
    """Format file size in human-readable form."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ============ main ============
def main():
    print(f"{FLYellow}============== PDF COMPRESS =============={CRst}\n")

    # 1. input file
    while True:
        raw = input(f"{FLCyan}Input PDF path{CRst}: ").strip()
        if not raw:
            print(f"{FLRed}Input path cannot be empty.{CRst}")
            continue
        raw = raw.strip("'\"")
        raw = os.path.expanduser(raw)
        if not os.path.isfile(raw):
            print(f"{FLRed}File not found:{CRst} {raw}")
            continue
        if not raw.lower().endswith(".pdf"):
            print(f"{FLRed}Not a PDF file:{CRst} {raw}")
            continue
        input_path = os.path.abspath(raw)
        break

    print(f"{FGray}Input:{CRst}  {FLGreen}{input_path}{CRst}")

    # 2. output file
    default_output = _generate_output_path(input_path)
    while True:
        default_name = os.path.basename(default_output)
        raw = input(f"{FLCyan}Output path {FGray}[{default_name}]{CRst}: ").strip()
        if not raw:
            output_path = default_output
            break
        raw = raw.strip("'\"")
        raw = os.path.expanduser(raw)
        if os.path.dirname(raw) == "":
            raw = os.path.join(os.path.dirname(input_path), raw)
        if not raw.lower().endswith(".pdf"):
            raw += ".pdf"
        output_path = os.path.abspath(raw)
        break

    print(f"{FGray}Output:{CRst} {FLGreen}{output_path}{CRst}\n")

    # 3. compression mode
    print(f"{FLYellow}Compression mode:{CRst}")
    print(f"  {FLCyan}[E]{CRst} {FGray}Ebook{CRst}    — standard compression (gs -dPDFSETTINGS=/ebook)")
    print(f"  {FLCyan}[C]{CRst} {FGray}Custom{CRst}   — control image DPI, quality, and downsampling\n")

    while True:
        choice = input(f"{FLCyan}Select mode{CRst} {FGray}[E]{CRst}: ").strip().lower() or "e"

        if choice in ("e", "ebook"):
            cmd = [
                GS_BIN, "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/ebook",
                "-dNOPAUSE", "-dBATCH", "-dSAFER",
                f"-sOutputFile={output_path}",
                input_path,
            ]
            break

        elif choice in ("c", "custom"):
            print(f"\n{FLYellow}Image downsampling settings:{CRst}\n")
            color_dpi    = _prompt_numeric("Color image DPI", 200, 36, 2400)
            gray_dpi     = _prompt_numeric("Gray image DPI",  200, 36, 2400)
            mono_dpi     = _prompt_numeric("Mono image DPI",  300, 36, 2400)
            jpeg_quality = _prompt_numeric("JPEG quality (1–100)", 50, 1, 100)
            print()

            cmd = [
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
            break

        else:
            print(f"{FLRed}Invalid choice. Enter E or C.{CRst}")

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
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
