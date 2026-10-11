#!/usr/bin/env python3
"""Convert scanned PDFs to thresholded, 1-bit black-and-white PDFs.

PyMuPDF renders visible pages in memory; Pillow applies a fixed threshold
without dithering and writes lossless CCITT Group 4 images. pypdf assembles the
pages, retaining displayed page sizes, document metadata, and bookmark titles,
hierarchy, and target pages. Bookmark coordinates reset to fit the target page.
Converted pages do not retain searchable text or interactive features. Selected
pages can be skipped: their original page content is copied without rendering
or binarization, in its original position. Skip selections use physical PDF page
numbers, not printed labels: 1-3,4 selects the first four pages; -1,-2 selects the
last two. Empty input skips nothing. No page images or decrypted PDFs are written
to disk. Page thresholding and CCITT encoding run in a bounded thread pool;
PyMuPDF rendering and pypdf assembly stay on the main thread, in page order.
--workers controls the maximum number of page encoding tasks (default: up to
eight CPU cores; 1 disables parallel encoding). Raster memory is bounded by this
queue; the assembled compressed PDF still grows in memory with the document.
Final PDF writing reports elapsed time and bytes every few seconds; output
copying reports byte progress.

Permission-only protection is opened automatically. An opening password, when
needed, is requested without echo and used only in memory. One completed PDF is stored temporarily
beside the output, then removed on success, failure, or Ctrl+C. Existing files
are not overwritten. Input is always preserved.

Requirements:
    - pip: PyMuPDF, Pillow (with libtiff support), pypdf.
    - pip: cryptography (optional, needed for AES-encrypted input).

Usage:
    python pdf-binarize.py
    python pdf-binarize.py input.pdf -o output.pdf --dpi 300 --threshold 180
    python pdf-binarize.py input.pdf --skip-pages="1,-1"
"""

import argparse
from collections import deque
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

from PIL import Image, features
import pymupdf
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.generic import Destination, IndirectObject


DEFAULT_DPI = 300
MIN_DPI = 36
MAX_DPI = 1200
DEFAULT_THRESHOLD = 180
MIN_THRESHOLD = 1
MAX_THRESHOLD = 255
GRAY_LEVELS = 256
RIGHT_ANGLE = 90
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)
MAX_WORKERS = 32
PROGRESS_INTERVAL_SECONDS = 3.0
COPY_CHUNK_BYTES = 1024 * 1024
UNTITLED_BOOKMARK = "Untitled bookmark"

type _Outline = list[Destination | _Outline]


def _unlock_pdf(reader: PdfReader) -> str:
    """Unlock an encrypted reader, prompting privately until the password works.

    Args:
        reader: Input reader; unencrypted and empty-password inputs need no prompt.

    Returns:
        Accepted password for the in-memory renderer, or an empty string when
        no opening password is required. Never logged or persisted.

    Raises:
        ValueError: If the user submits an empty opening password to cancel.
        PyPdfError: If the encryption cannot be processed.
    """
    if not reader.is_encrypted or reader.decrypt(""):
        return ""
    while True:
        password = Input.input_password("PDF opening password (empty to cancel)")
        if not password:
            raise ValueError("No password provided. Conversion cancelled.")
        if reader.decrypt(password):
            return password
        print(f"{FLRed}Incorrect password. Please try again.{CRst}")


def _copy_bookmarks(
    reader: PdfReader,
    writer: PdfWriter,
    outline: _Outline,
    parent: IndirectObject | None = None,
) -> None:
    """Copy bookmark titles, nesting, and target pages into a rebuilt document.

    Args:
        reader: Original document used to resolve destinations.
        writer: Output document, with all converted pages already added.
        outline: Original outline or one nested outline list.
        parent: Output parent bookmark, or None for root entries.

    Bookmark positions use the default fit-page destination. Heading-only
    bookmarks remain without a page target.
    """
    last_parent = parent
    for item in outline:
        if isinstance(item, list):
            _copy_bookmarks(reader, writer, item, last_parent)
        else:
            title = item.title
            if title is None:
                title = UNTITLED_BOOKMARK
            page_number = reader.get_destination_page_number(item)
            if page_number is not None and not 0 <= page_number < len(writer.pages):
                page_number = None
            last_parent = writer.add_outline_item(
                title, page_number=page_number, parent=parent,
            )


def _encode_page(rendered: Image.Image, dpi: int, threshold: int) -> bytes:
    """Threshold one rendered page and return an independent CCITT PDF buffer.

    Takes ownership of rendered and closes it even on failure. Each worker owns
    its image and PDF buffer; no PyMuPDF or pypdf objects enter worker threads.
    """
    threshold_lut = [0 if value < threshold else 255 for value in range(GRAY_LEVELS)]
    with rendered, io.BytesIO() as page_pdf:
        with rendered.convert("L") as gray:
            with gray.point(threshold_lut, mode="1") as binary:
                binary.save(page_pdf, format="PDF", resolution=dpi)
        encoded = page_pdf.getvalue()
    return encoded


def _render_page(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
    """Render one zero-based page into an independently owned grayscale image.

    Call only on the main thread. get_pixmap respects the visible crop, rotation,
    and UserUnit. frombytes copies the pixels, so workers never share a MuPDF
    buffer. The caller must close the returned image or transfer it to an encoder.
    """
    page = document.load_page(index)
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)


def _encoded_pages(
    input_path: Path, page_indexes: list[int], dpi: int, threshold: int,
    workers: int, password: str = "",
) -> Generator[bytes, None, None]:
    """Render in memory and yield encoded pages with a bounded worker queue.

    Only this generator's calling thread uses PyMuPDF. Workers receive independent
    Pillow images. Closing the generator waits for encoders and closes even the
    images belonging to cancelled tasks, then closes the renderer. No page images
    or decrypted PDFs are written to disk. One worker takes the serial path.
    """
    if not page_indexes:
        return
    with pymupdf.open(input_path) as document:
        if document.needs_pass and not document.authenticate(password):
            raise ValueError("The rendering engine could not unlock the PDF with the supplied password.")
        if workers == 1:
            for index in page_indexes:
                yield _encode_page(_render_page(document, index, dpi), dpi, threshold)
            return

        indexes = iter(page_indexes)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-encode")
        pending: deque[tuple[Future[bytes], Image.Image]] = deque()

        def submit(index: int) -> None:
            rendered = _render_page(document, index, dpi)
            try:
                future = executor.submit(_encode_page, rendered, dpi, threshold)
            except BaseException:
                rendered.close()
                raise
            pending.append((future, rendered))

        try:
            for _ in range(min(workers, len(page_indexes))):
                submit(next(indexes))
            while pending:
                future, rendered = pending.popleft()
                try:
                    encoded = future.result()
                finally:
                    rendered.close()
                yield encoded
                index = next(indexes, None)
                if index is not None:
                    submit(index)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            for _, rendered in pending:
                rendered.close()


def _write_pdf_with_progress(writer: PdfWriter, completed_pdf: Path) -> None:
    """Write the assembled PDF, reporting time and actual file size periodically.

    Only the calling thread touches writer. The reporting thread reads the
    output file size and is stopped even if writing fails or is interrupted.
    """
    started = time.monotonic()
    finished = threading.Event()

    def report() -> None:
        while not finished.wait(PROGRESS_INTERVAL_SECONDS):
            try:
                size = completed_pdf.stat().st_size
            except OSError:
                size = 0
            print(
                f"{FGray}Writing final PDF: {time.monotonic() - started:.1f}s elapsed, "
                f"{Console.format_size(size)} written...{CRst}", flush=True,
            )

    print(f"{FLCyan}Writing final PDF (all pages are encoded; assembling the file)...{CRst}", flush=True)
    reporter = threading.Thread(target=report, name="pdf-write-progress", daemon=True)
    reporter.start()
    try:
        writer.write(completed_pdf)
    finally:
        finished.set()
        reporter.join()
    print(f"{FLGreen}Final PDF written in {time.monotonic() - started:.1f}s.{CRst}", flush=True)


def _binarize_pdf(
    input_path: Path,
    output_path: Path,
    dpi: int,
    threshold: int,
    workers: int = DEFAULT_WORKERS,
    skip_pages: str | None = "",
) -> None:
    """Render, threshold, and rebuild a PDF without overwriting existing files.

    Args:
        input_path: Existing source PDF.
        output_path: New PDF path with an existing parent directory.
        dpi: Raster resolution, between MIN_DPI and MAX_DPI inclusive.
        threshold: Gray values below this become black; all others become white.
            Must be between MIN_THRESHOLD and MAX_THRESHOLD inclusive.
        workers: Parallel page encoders, from 1 to MAX_WORKERS. Defaults to
            DEFAULT_WORKERS; 1 uses serial encoding. PDF assembly is serial.
        skip_pages: Selection parsed by Input.parse_index_ranges, or None to
            prompt after opening the PDF. Empty/default skips nothing. Skipped
            pages retain their original contents and position in the output.

    Raises:
        ValueError: Invalid settings, empty document, or cancelled password input.
        FileExistsError: Output exists or resolves to the source file.
        RuntimeError: Pillow lacks lossless 1-bit PDF support.
        OSError: Reading, rendering, or writing a file fails.
        PyPdfError: A PDF cannot be read or written.

    Prints page progress. Owns and cleans temporary files beside the output.
    """
    # ── validate before creating any files ──────────────
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise ValueError(f"Threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"Workers must be between 1 and {MAX_WORKERS}.")
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise FileExistsError(f"Output must be a new file: {output_path}")
    reader = PdfReader(input_path)
    try:
        password = _unlock_pdf(reader)
        if not reader.pages:
            raise ValueError("The input PDF has no pages.")
        page_count = len(reader.pages)
        selection = (
            Input.input_index_ranges("PDF pages to skip binarizing (Enter = none)", item_count=page_count)
            if skip_pages is None else Input.parse_index_ranges(skip_pages, item_count=page_count)
        )
        skipped = set(selection or ())
        render_pages = [index for index in range(page_count) if index not in skipped]
        render_count = len(render_pages)
        if render_count and not features.check("libtiff"):
            raise RuntimeError("This mode requires Pillow built with libtiff (CCITT Group 4) support.")
        print(f"{FLCyan}Pages: {render_count} to binarize, {len(skipped)} to copy without changes.{CRst}", flush=True)
        with tempfile.TemporaryDirectory(prefix=".pdf-binary-", dir=output_path.parent) as directory:
            work_dir = Path(directory)
            # ── render in memory, threshold, and encode losslessly ──
            Image.init()  # Initialize Pillow plugins before starting worker threads.
            workers = min(workers, max(1, render_count))
            if render_count:
                print(
                    f"{FLCyan}Rendering {render_count} pages in memory at {dpi} DPI; "
                    f"encoding with {workers} worker(s). No temporary page images...{CRst}", flush=True,
                )
            else:
                print(f"{FLCyan}All pages skipped; rendering and binarization are unnecessary.{CRst}", flush=True)
            encoding_started = time.monotonic()
            encoded_pages = _encoded_pages(input_path, render_pages, dpi, threshold, workers, password)
            with PdfWriter() as writer, closing(encoded_pages):
                for number, source_page in enumerate(reader.pages, start=1):
                    if number - 1 in skipped:
                        writer.add_page(source_page)
                        print(f"{FLCyan}Copied original page {number}/{page_count} (binarization skipped).{CRst}", flush=True)
                        continue
                    encoded = next(encoded_pages)
                    with io.BytesIO(encoded) as page_pdf, PdfReader(page_pdf) as page_reader:
                        page = writer.add_page(page_reader.pages[0])
                        width = float(source_page.cropbox.width) * source_page.user_unit
                        height = float(source_page.cropbox.height) * source_page.user_unit
                        if (source_page.rotation // RIGHT_ANGLE) % 2:
                            width, height = height, width
                        page.scale_to(width, height)
                        writer.reset_translation(page_reader)
                    print(
                        f"{FLCyan}Encoded and merged page {number}/{len(reader.pages)} "
                        f"({time.monotonic() - encoding_started:.1f}s elapsed).{CRst}", flush=True,
                    )

                print(f"{FLCyan}Copying document metadata and bookmarks...{CRst}", flush=True)
                bookmarks_started = time.monotonic()
                if reader.metadata:
                    writer.add_metadata(reader.metadata)
                _copy_bookmarks(reader, writer, cast(_Outline, reader.outline))
                print(f"{FLGreen}Metadata and bookmarks copied in {time.monotonic() - bookmarks_started:.1f}s.{CRst}", flush=True)
                completed_pdf = work_dir / "completed.pdf"
                _write_pdf_with_progress(writer, completed_pdf)

            # ── publish only after conversion succeeds ──────
            total_bytes = completed_pdf.stat().st_size
            copied_bytes = 0
            last_report = time.monotonic()
            print(f"{FLCyan}Copying {Console.format_size(total_bytes)} to the output path...{CRst}", flush=True)
            with output_path.open("xb") as destination:
                try:
                    with completed_pdf.open("rb") as source:
                        while chunk := source.read(COPY_CHUNK_BYTES):
                            destination.write(chunk)
                            copied_bytes += len(chunk)
                            now = time.monotonic()
                            if now - last_report >= PROGRESS_INTERVAL_SECONDS or copied_bytes == total_bytes:
                                print(
                                    f"{FGray}Output copy: {Console.format_size(copied_bytes)} / "
                                    f"{Console.format_size(total_bytes)} "
                                    f"({copied_bytes / total_bytes:.0%}).{CRst}", flush=True,
                                )
                                last_report = now
                    destination.flush()
                except BaseException:
                    # Only remove the new file opened by this call, never user data.
                    destination.close()
                    output_path.unlink(missing_ok=True)
                    raise
            print(f"{FLCyan}Cleaning up temporary files...{CRst}", flush=True)
    finally:
        reader.close()


def main() -> int:
    """Run interactive or argument-driven PDF binarization.

    Returns:
        Zero on success, or one on a dependency, input, or conversion failure.
        argparse exits with its standard status for help or invalid CLI options.

    Prompts for omitted paths/settings and opening passwords, prints progress,
    and writes a new PDF. Does not modify the source.
    """
    # ── help and arguments ──────────────────────────────
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}{'PDF BINARIZE':^60}{CRst}\n"
        "Convert scanned PDFs to 1-bit black-and-white images with lossless compression.\n"
        "Retains displayed page sizes, metadata, and bookmark titles/hierarchy/page targets.\n"
        "Bookmark positions reset to fit-page. Converted pages lose searchable text and interactivity.\n"
        "Skipped pages are copied with their original contents and page order.\n"
        "Protected PDFs prompt for an opening password when needed.\n"
        "Pages are rendered in memory; no temporary page images or decrypted PDFs are written.",
        epilog=f"{FGray}Requirements: PyMuPDF, Pillow with libtiff, pypdf.\n"
        f"AES-encrypted input also needs cryptography (optional).\n"
        f"Omitted paths/settings are prompted interactively; defaults: {DEFAULT_DPI} DPI, "
        f"threshold {DEFAULT_THRESHOLD}.\n"
        f"Parallel page encoding defaults to {DEFAULT_WORKERS} workers; --workers 1 is serial.\n"
        "Rendering stays on the main thread; a bounded queue feeds parallel Pillow encoders.\n"
        "The assembled PDF grows in memory; one temporary completed PDF is used for safe output.\n"
        "Higher thresholds make more pixels black; no dithering is used.\n"
        "Skip PDF pages with 1,2 or 1-3,4; -1,-2 means the last two pages; Enter skips none.\n"
        "Use --skip-pages=-1,-2 for negative CLI selections; --skip-pages= disables the prompt.\n"
        f"Example: pdf-binarize.py input.pdf -o output.pdf --dpi 300 --threshold 180{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="input PDF path")
    parser.add_argument("-o", "--output", help="new output PDF path (existing files are rejected)")
    parser.add_argument("--dpi", type=int, help=f"raster DPI, {MIN_DPI}-{MAX_DPI}")
    parser.add_argument("--threshold", type=int, help=f"black/white cutoff, {MIN_THRESHOLD}-{MAX_THRESHOLD}")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"parallel page encoders, 1-{MAX_WORKERS} (default: {DEFAULT_WORKERS})")
    parser.add_argument("--skip-pages", metavar="PAGES",
                        help="pages to leave unconverted (e.g. 1-3,4,-1); omitted: prompt; empty: none")
    args = parser.parse_args()
    if args.dpi is not None and not MIN_DPI <= args.dpi <= MAX_DPI:
        parser.error(f"--dpi must be between {MIN_DPI} and {MAX_DPI}")
    if args.threshold is not None and not MIN_THRESHOLD <= args.threshold <= MAX_THRESHOLD:
        parser.error(f"--threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}")
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")

    # ── dependencies and input ──────────────────────────
    Console.print_banner("PDF BINARIZE")
    try:
        input_path = Path(args.input or Input.resolve_input_path("", prompt="Input PDF path"))
        default_output = input_path.with_name(f"{input_path.stem}_binary.pdf")
        output_path = Path(args.output) if args.output else Path(Input.resolve_output_path(
            str(default_output), prompt="Output PDF path",
        ))
        dpi = args.dpi if args.dpi is not None else int(Input.input_number(
            "Output DPI", default=DEFAULT_DPI, min_value=MIN_DPI, max_value=MAX_DPI, allow_float=False,
        ))
        threshold = args.threshold if args.threshold is not None else int(Input.input_number(
            "Threshold (higher = more black)", default=DEFAULT_THRESHOLD,
            min_value=MIN_THRESHOLD, max_value=MAX_THRESHOLD, allow_float=False,
        ))
        print(f"{FLYellow}Converted pages become images: searchable text and interactive features are lost.{CRst}")
        _binarize_pdf(input_path, output_path, dpi, threshold, args.workers, args.skip_pages)
    except (OSError, ValueError, RuntimeError, PyPdfError, pymupdf.FileDataError) as exc:
        print(f"{FLRed}Binarization failed: {exc}{CRst}")
        return 1

    print(f"{FLGreen}Black-and-white PDF saved to:{CRst} {FGray}{output_path}{CRst}")
    print(f"{FGray}Size: {Console.format_size(input_path.stat().st_size)}"
          f" -> {Console.format_size(output_path.stat().st_size)}{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
