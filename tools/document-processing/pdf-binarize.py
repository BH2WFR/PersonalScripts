#!/usr/bin/env python3
"""Convert scanned PDFs to thresholded, 1-bit black-and-white PDFs.

Choose a fixed threshold (default) or Sauvola local adaptive thresholding.
Optional processing order: black/white levels, Lanczos upscaling, Unsharp Mask,
then binarization. Levels and sharpening default to off; upscaling defaults to
1x. Levels map the black point to 0 and white point to 255, linearly stretching
between them and clipping outside; defaults 0/255 are an identity mapping.
Use --levels with --black-point / --white-point to enhance faded scans.
The interactive menu exports a single-page preview PDF, changes settings, or
converts the whole document. Preview opens in the default PDF viewer and returns
to the menu; --no-open-preview disables opening. --preview-page N exports just
one physical page (-1 = last), ignoring skip selections. --batch converts the
whole PDF without the settings/action menus; omitted settings use defaults.
Sauvola uses an odd pixel window (default 31), k=0.2 and R=128 for 8-bit gray;
smaller k generally retains more dark pixels. Window size and sharpening radius
are in base rendered pixels, so their physical scale changes with DPI. Upscaling
automatically scales the sharpening radius and window (rounded up to odd).
--upscale 2 doubles raster dimensions without changing PDF page dimensions;
it interpolates existing pixels, cannot recover missing detail, and uses roughly
four times the image-processing memory. Integer factors 1-4 are supported.

PyMuPDF renders visible pages in memory; Pillow/NumPy apply the selected method
without dithering and write lossless CCITT Group 4 images. PyMuPDF assembles the
pages, retaining displayed page sizes, document metadata, and bookmark titles,
hierarchy, and target pages. Bookmark coordinates reset to fit the target page.
Converted pages do not retain searchable text or interactive features. Selected
pages can be skipped: their original page content is copied without rendering
or binarization, in its original position. Skip selections use physical PDF page
numbers, not printed labels: 1-3,4 selects the first four pages; -1,-2 selects the
last two. Empty input skips nothing. No page images or decrypted PDFs are written
to disk. Page thresholding and CCITT encoding run in a bounded thread pool;
PyMuPDF rendering and assembly stay on the main thread, in page order.
--workers controls the maximum number of page encoding tasks (default: up to
eight CPU cores; 1 disables parallel encoding). Raster memory is bounded by this
queue; the assembled compressed PDF still grows in memory with the document.
tqdm displays page progress and output-copy byte progress with speed and ETA.
Final PDF writing shows bytes written and elapsed time without a guessed total.

Permission-only protection is opened automatically. An opening password, when
needed, is requested without echo and used only in memory. One completed PDF is stored temporarily
beside the output, then removed on success, failure, or Ctrl+C. Existing files
are not overwritten. Input is always preserved.

Requirements:
    - pip: PyMuPDF, Pillow (with libtiff support), numpy, tqdm.

Usage:
    python pdf-binarize.py
    python pdf-binarize.py input.pdf -o output.pdf --dpi 300 --threshold 180
    python pdf-binarize.py input.pdf --skip-pages="1,-1"
    python pdf-binarize.py input.pdf --preview-page 12 --mode sauvola --sharpen
    python pdf-binarize.py input.pdf --batch --mode sauvola --skip-pages=
    python pdf-binarize.py input.pdf --preview-page 1 --mode sauvola --levels --black-point 110 --white-point 250 --upscale 2 --sharpen --sharpen-radius 0.7 --sharpen-percent 50
"""

import argparse
from collections import deque
from collections.abc import Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, closing
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

try:
    from PIL import Image, ImageFilter, features
    import numpy as np
    from numpy.typing import NDArray
    import pymupdf
    from pymupdf.mupdf import FzErrorBase
    from tqdm import tqdm
except ImportError as exc:
    print(f"{FLRed}Missing PDF/image dependency: {exc.name}{CRst}")
    print(f"{FGray}Install with: pip install PyMuPDF Pillow numpy tqdm{CRst}")
    sys.exit(1)


DEFAULT_DPI = 300
MIN_DPI = 36
MAX_DPI = 1200
DEFAULT_THRESHOLD = 180
MIN_THRESHOLD = 1
MAX_THRESHOLD = 255
GRAY_LEVELS = 256
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)
MAX_WORKERS = 32
PROGRESS_INTERVAL_SECONDS = 3.0
COPY_CHUNK_BYTES = 1024 * 1024
UNTITLED_BOOKMARK = "Untitled bookmark"
DEFAULT_SAUVOLA_WINDOW = 31
MAX_SAUVOLA_WINDOW = 501
DEFAULT_SAUVOLA_K = 0.2
SAUVOLA_R = 128.0
SAUVOLA_STRIP_ROWS = 256
DEFAULT_SHARPEN_RADIUS = 1.0
DEFAULT_SHARPEN_PERCENT = 100
SHARPEN_NOISE_THRESHOLD = 3
MAX_SHARPEN_RADIUS = 10.0
MAX_SHARPEN_PERCENT = 500
DEFAULT_BLACK_POINT = 0
DEFAULT_WHITE_POINT = GRAY_LEVELS - 1
DEFAULT_UPSCALE = 1
MAX_UPSCALE = 4


class _BinarizeMode(enum.StrEnum):
    FIXED = "fixed"
    SAUVOLA = "sauvola"


class _Action(enum.StrEnum):
    PREVIEW = "preview"
    SETTINGS = "settings"
    CONVERT = "convert"
    QUIT = "quit"


@dataclasses.dataclass(frozen=True)
class _Processing:
    """Immutable image-processing settings shared by preview and page workers."""

    mode: _BinarizeMode = _BinarizeMode.FIXED
    window: int = DEFAULT_SAUVOLA_WINDOW
    k: float = DEFAULT_SAUVOLA_K
    sharpen: bool = False
    sharpen_radius: float = DEFAULT_SHARPEN_RADIUS
    sharpen_percent: int = DEFAULT_SHARPEN_PERCENT
    levels: bool = False
    black_point: int = DEFAULT_BLACK_POINT
    white_point: int = DEFAULT_WHITE_POINT
    upscale: int = DEFAULT_UPSCALE


DEFAULT_PROCESSING = _Processing()


def _validate_settings(dpi: int, threshold: int, workers: int, processing: _Processing) -> None:
    """Reject invalid conversion settings before rendering or creating files."""
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise ValueError(f"Threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"Workers must be between 1 and {MAX_WORKERS}.")
    if not isinstance(processing.mode, _BinarizeMode):
        raise ValueError("Choose fixed or sauvola mode.")
    if not 3 <= processing.window <= MAX_SAUVOLA_WINDOW or processing.window % 2 != 1:
        raise ValueError(f"Sauvola window must be an odd integer from 3 to {MAX_SAUVOLA_WINDOW}.")
    if not 0 < processing.k <= 1:
        raise ValueError("Sauvola k must be greater than 0 and at most 1.")
    if not 0 < processing.sharpen_radius <= MAX_SHARPEN_RADIUS:
        raise ValueError(f"Sharpening radius must be greater than 0 and at most {MAX_SHARPEN_RADIUS}.")
    if not 1 <= processing.sharpen_percent <= MAX_SHARPEN_PERCENT:
        raise ValueError(f"Sharpening amount must be between 1 and {MAX_SHARPEN_PERCENT} percent.")
    if not 0 <= processing.black_point < processing.white_point < GRAY_LEVELS:
        raise ValueError("Levels must satisfy 0 <= black point < white point <= 255.")
    if not isinstance(processing.upscale, int) or not 1 <= processing.upscale <= MAX_UPSCALE:
        raise ValueError(f"Upscaling must be an integer from 1 to {MAX_UPSCALE}.")


def _window_mean(values: NDArray[np.float64], window: int) -> NDArray[np.float64]:
    """Return valid square-window means using a strip-local integral image."""
    integral = np.pad(values, ((1, 0), (1, 0)), mode="constant")
    np.cumsum(integral, axis=0, out=integral)
    np.cumsum(integral, axis=1, out=integral)
    return (integral[window:, window:] - integral[:-window, window:]
            - integral[window:, :-window] + integral[:-window, :-window]) / (window * window)


def _sauvola(gray: Image.Image, window: int, k: float) -> Image.Image:
    """Return a 1-bit Sauvola image, using reflected edges and bounded float strips.

    Input is an 8-bit grayscale image retained by the caller. R is fixed at 128.
    Strips include the entire neighborhood halo so boundaries introduce no seams.
    The caller owns the returned image. No images are written to disk.
    """
    values = np.asarray(gray, dtype=np.uint8)
    radius = window // 2
    padded = np.pad(values, ((radius, radius), (radius, radius)), mode="reflect")
    result = np.empty(values.shape, dtype=np.uint8)
    for start in range(0, gray.height, SAUVOLA_STRIP_ROWS):
        end = min(start + SAUVOLA_STRIP_ROWS, gray.height)
        strip = padded[start:end + window - 1].astype(np.float64)
        mean = _window_mean(strip, window)
        np.square(strip, out=strip)
        variance = np.maximum(_window_mean(strip, window) - mean * mean, 0)
        cutoff = mean * (1 + k * (np.sqrt(variance) / SAUVOLA_R - 1))
        result[start:end] = (values[start:end] > cutoff).astype(np.uint8) * 255
    with Image.fromarray(result) as binary_gray:
        return binary_gray.convert("1", dither=Image.Dither.NONE)


def _threshold_image(gray: Image.Image, threshold: int, processing: _Processing) -> Image.Image:
    """Return an owned 1-bit image after levels, upscaling and optional sharpening.

    Retains the caller's grayscale image and closes intermediates on success or
    failure. Output dimensions are multiplied by upscale. Window/radius settings
    use base rendered pixels; both scale automatically, with the window rounded
    up to odd. No dithering or temporary image files are used.
    """
    with ExitStack() as images:
        working = gray
        if processing.levels:
            span = processing.white_point - processing.black_point
            levels_lut = [round(max(0, min(GRAY_LEVELS - 1,
                (value - processing.black_point) * (GRAY_LEVELS - 1) / span)))
                for value in range(GRAY_LEVELS)]
            working = images.enter_context(working.point(levels_lut))
        scale = processing.upscale
        if scale != DEFAULT_UPSCALE:
            working = images.enter_context(working.resize(
                (working.width * scale, working.height * scale), Image.Resampling.LANCZOS,
            ))
        if processing.sharpen:
            working = images.enter_context(working.filter(ImageFilter.UnsharpMask(
                radius=processing.sharpen_radius * scale, percent=processing.sharpen_percent,
                threshold=SHARPEN_NOISE_THRESHOLD,
            )))
        if processing.mode is _BinarizeMode.SAUVOLA:
            window = processing.window * scale
            if window % 2 == 0:
                window += 1
            return _sauvola(working, window, processing.k)
        threshold_lut = [0 if value < threshold else 255 for value in range(GRAY_LEVELS)]
        return working.point(threshold_lut, mode="1")

def _reset_bookmark_positions(document: pymupdf.Document) -> None:
    """Keep bookmark hierarchy and targets, resetting internal targets to /Fit.

    Missing titles receive a readable fallback. Heading-only and external
    destinations stay intact. Updates the in-memory outline dictionaries.
    """
    for entry, xref in zip(document.get_toc(), document.get_outline_xrefs()):
        if document.xref_get_key(xref, "Title")[0] == "null":
            document.xref_set_key(xref, "Title", pymupdf.get_pdf_str(UNTITLED_BOOKMARK))
        page_number = entry[2]
        if 1 <= page_number <= document.page_count:
            page_xref = document.page_xref(page_number - 1)
            document.xref_set_key(xref, "A", "null")
            document.xref_set_key(xref, "Dest", f"[{page_xref} 0 R /Fit]")


def _replace_page(document: pymupdf.Document, index: int, encoded: bytes) -> None:
    """Replace one page's contents while retaining its identity and incoming links.

    Uses the displayed dimensions (including crop, rotation and UserUnit).
    Removes this page's interactive objects, then places the encoded PDF without
    decoding its 1-bit image. Other pages and document metadata are unchanged.
    """
    page = document[index]
    rect = page.rect
    for widget in list(page.widgets() or ()):
        # widgets() yields Widget instances; load_widget's inferred union is broader.
        page.delete_widget(cast(pymupdf.Widget, widget))
    parent = document.xref_get_key(page.xref, "Parent")[1]
    document.update_object(
        page.xref,
        f"<< /Type /Page /Parent {parent} "
        f"/MediaBox [0 0 {rect.width} {rect.height}] /Rotate 0 /UserUnit 1 /Resources <<>> >>",
    )
    page = document.reload_page(page)
    with pymupdf.open(stream=encoded, filetype="pdf") as encoded_document:
        page.show_pdf_page(page.rect, encoded_document, 0, keep_proportion=False)


def _encode_page(
    rendered: Image.Image, dpi: int, threshold: int, processing: _Processing = DEFAULT_PROCESSING,
) -> bytes:
    """Threshold one rendered page and return an independent CCITT PDF buffer.

    Takes ownership of rendered and closes it even on failure. Each worker owns
    its image and PDF buffer; no PyMuPDF objects enter worker threads.
    """
    with rendered, io.BytesIO() as page_pdf:
        with rendered.convert("L") as gray:
            with _threshold_image(gray, threshold, processing) as binary:
                binary.save(page_pdf, format="PDF", resolution=dpi * processing.upscale)
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
    processing: _Processing = DEFAULT_PROCESSING,
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
                yield _encode_page(_render_page(document, index, dpi), dpi, threshold, processing)
            return

        indexes = iter(page_indexes)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-encode")
        pending: deque[tuple[Future[bytes], Image.Image]] = deque()

        def submit(index: int) -> None:
            rendered = _render_page(document, index, dpi)
            try:
                future = executor.submit(_encode_page, rendered, dpi, threshold, processing)
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


def _write_pdf_with_progress(writer: pymupdf.Document, completed_pdf: Path) -> None:
    """Write the assembled PDF, reporting time and actual file size periodically.

    Only the calling thread touches writer. The reporting thread reads the
    output file size and is stopped even if writing fails or is interrupted.
    """
    started = time.monotonic()
    finished = threading.Event()

    with tqdm(
        desc="Writing final PDF", unit="B", unit_scale=True, unit_divisor=1024,
        file=sys.stdout, dynamic_ncols=True,
        bar_format="{desc}: {n_fmt}{unit} written [{elapsed} elapsed, {rate_fmt}]",
    ) as progress:
        def report() -> None:
            while not finished.wait(PROGRESS_INTERVAL_SECONDS):
                try:
                    size = completed_pdf.stat().st_size
                except OSError:
                    size = 0
                progress.update(max(0, size - progress.n))
                progress.refresh()  # Refresh elapsed time even before the first bytes.

        reporter = threading.Thread(target=report, name="pdf-write-progress", daemon=True)
        reporter.start()
        try:
            Pdf.save_new(writer, completed_pdf)
        finally:
            finished.set()
            reporter.join()
        progress.update(max(0, completed_pdf.stat().st_size - progress.n))
    print(f"{FLGreen}Final PDF written in {time.monotonic() - started:.1f}s.{CRst}", flush=True)


def _binarize_pdf(
    input_path: Path,
    output_path: Path,
    dpi: int,
    threshold: int,
    workers: int = DEFAULT_WORKERS,
    skip_pages: str | None = "",
    *, processing: _Processing = DEFAULT_PROCESSING,
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
        processing: Thresholding mode and optional sharpening; shared with preview.

    Raises:
        ValueError: Invalid settings, empty document, or cancelled password input.
        FileExistsError: Output exists or resolves to the source file.
        RuntimeError: Pillow lacks lossless 1-bit PDF support.
        OSError: Reading, rendering, or writing a file fails.
        pymupdf.FileDataError: A PDF cannot be read.

    Prints page progress. Owns and cleans temporary files beside the output.
    """
    # ── validate before creating any files ──────────────
    _validate_settings(dpi, threshold, workers, processing)
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise FileExistsError(f"Output must be a new file: {output_path}")
    reader = pymupdf.open(input_path)
    try:
        password = Pdf.unlock(reader)
        if not reader.page_count:
            raise ValueError("The input PDF has no pages.")
        page_count = reader.page_count
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
            encoded_pages = _encoded_pages(input_path, render_pages, dpi, threshold, workers, password, processing)
            with closing(encoded_pages), tqdm(
                total=page_count, desc="Processing pages", unit="page",
                file=sys.stdout, dynamic_ncols=True, miniters=1,
                postfix={"skipped": len(skipped)},
            ) as progress:
                for number in range(1, page_count + 1):
                    if number - 1 not in skipped:
                        encoded = next(encoded_pages)
                        _replace_page(reader, number - 1, encoded)
                    progress.update(1)

            print(f"{FLCyan}Copying document metadata and bookmarks...{CRst}", flush=True)
            bookmarks_started = time.monotonic()
            # Editing the original document in memory retains custom metadata,
            # page identities and cross-page links on all skipped pages.
            _reset_bookmark_positions(reader)
            print(f"{FLGreen}Metadata and bookmarks copied in {time.monotonic() - bookmarks_started:.1f}s.{CRst}", flush=True)
            completed_pdf = work_dir / "completed.pdf"
            _write_pdf_with_progress(reader, completed_pdf)

            # ── publish only after conversion succeeds ──────
            total_bytes = completed_pdf.stat().st_size
            with output_path.open("xb") as destination:
                try:
                    with completed_pdf.open("rb") as source, tqdm(
                        total=total_bytes, desc="Copying output", unit="B",
                        unit_scale=True, unit_divisor=1024, file=sys.stdout, dynamic_ncols=True,
                    ) as progress:
                        while chunk := source.read(COPY_CHUNK_BYTES):
                            destination.write(chunk)
                            progress.update(len(chunk))
                    destination.flush()
                except BaseException:
                    # Only remove the new file opened by this call, never user data.
                    destination.close()
                    output_path.unlink(missing_ok=True)
                    raise
            print(f"{FLCyan}Cleaning up temporary files...{CRst}", flush=True)
    finally:
        reader.close()


def _preview_pdf(
    input_path: Path, output_path: Path, page_number: int, dpi: int, threshold: int,
    processing: _Processing = DEFAULT_PROCESSING,
) -> None:
    """Convert one physical page to a new PDF using the full-conversion encoder.

    Negative page numbers count from the end. Preserves displayed dimensions,
    including crop, rotation and UserUnit. Preview contains only the rendered
    page and standard metadata, without the source outline or attachments.
    No temporary files are created; existing input/output files are protected.
    Invalid settings/pages raise ValueError before rendering.
    """
    _validate_settings(dpi, threshold, 1, processing)
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise FileExistsError(f"Output must be a new file: {output_path}")
    if not features.check("libtiff"):
        raise RuntimeError("This mode requires Pillow built with libtiff (CCITT Group 4) support.")
    with pymupdf.open(input_path) as source:
        Pdf.unlock(source)
        if not source.page_count:
            raise ValueError("The input PDF has no pages.")
        index = Input.parse_index_ranges(str(page_number), item_count=source.page_count)[0]
        rect = source[index].rect
        print(f"{FLCyan}Converting preview page {index + 1} of {source.page_count}...{CRst}", flush=True)
        Image.init()
        encoded = _encode_page(_render_page(source, index, dpi), dpi, threshold, processing)
        with pymupdf.open() as preview:
            preview.new_page(width=rect.width, height=rect.height)
            _replace_page(preview, 0, encoded)
            preview.set_metadata(source.metadata or {})
            Pdf.save_new(preview, output_path)


def _configure(
    dpi: int, threshold: int, processing: _Processing,
) -> tuple[int, int, _Processing]:
    """Prompt for current image settings, retaining each value on Enter."""
    mode = cast(_BinarizeMode, Menu.select(
        [MenuOption(["F"], "Fixed threshold", _BinarizeMode.FIXED),
         MenuOption(["S"], "Sauvola adaptive threshold", _BinarizeMode.SAUVOLA)],
        prompt="Binarization mode", default_key="F" if processing.mode is _BinarizeMode.FIXED else "S",
        separator=False,
    ))
    dpi = int(Input.input_number("Base render DPI", default=dpi, min_value=MIN_DPI, max_value=MAX_DPI,
                                 allow_float=False))
    window, k = processing.window, processing.k
    if mode is _BinarizeMode.FIXED:
        threshold = int(Input.input_number(
            "Threshold (higher = more black)", default=threshold,
            min_value=MIN_THRESHOLD, max_value=MAX_THRESHOLD, allow_float=False,
        ))
    else:
        while True:
            window = int(Input.input_number(
                "Sauvola window (odd, in base rendered pixels)", default=window,
                min_value=3, max_value=MAX_SAUVOLA_WINDOW, allow_float=False,
            ))
            if window % 2:
                break
            print(f"{FLRed}Window size must be odd.{CRst}")
        k = float(Input.input_number(
            "Sauvola k (smaller generally retains more black)", default=k,
            min_value=0, min_value_allowed=False, max_value=1,
        ))
    levels = bool(Menu.select(
        [MenuOption(["N"], "Off", False), MenuOption(["Y"], "On (black/white points)", True)],
        prompt="Adjust levels before binarizing?", default_key="Y" if processing.levels else "N",
        inline=True, separator=False,
    ))
    black_point, white_point = processing.black_point, processing.white_point
    if levels:
        black_point = int(Input.input_number(
            "Black point (darker values become black)", default=black_point,
            min_value=0, max_value=GRAY_LEVELS - 2, allow_float=False,
        ))
        white_point = int(Input.input_number(
            "White point (lighter values become white)", default=max(white_point, black_point + 1),
            min_value=black_point + 1, max_value=GRAY_LEVELS - 1, allow_float=False,
        ))
    upscale = int(Input.input_number(
        "Upscale factor (Lanczos; 2x uses about 4x image memory)", default=processing.upscale,
        min_value=DEFAULT_UPSCALE, max_value=MAX_UPSCALE, allow_float=False,
    ))
    sharpen = bool(Menu.select(
        [MenuOption(["N"], "Off", False), MenuOption(["Y"], "On (Unsharp Mask)", True)],
        prompt="Sharpen before binarizing?", default_key="Y" if processing.sharpen else "N",
        inline=True, separator=False,
    ))
    radius, percent = processing.sharpen_radius, processing.sharpen_percent
    if sharpen:
        radius = float(Input.input_number(
            "Sharpening radius (base rendered pixels)", default=radius, min_value=0,
            min_value_allowed=False, max_value=MAX_SHARPEN_RADIUS,
        ))
        percent = int(Input.input_number(
            "Sharpening amount (%)", default=percent, min_value=1,
            max_value=MAX_SHARPEN_PERCENT, allow_float=False,
        ))
    return dpi, threshold, _Processing(
        mode=mode, window=window, k=k, sharpen=sharpen, sharpen_radius=radius,
        sharpen_percent=percent, levels=levels, black_point=black_point,
        white_point=white_point, upscale=upscale,
    )


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
        "Choose fixed (default) or Sauvola adaptive thresholding.\n"
        "Optional levels -> Lanczos upscale -> sharpening -> binarization.\n"
        "Levels/sharpening default to off; upscaling defaults to 1x.\n"
        "Menu: export/open a single-page preview, change settings, convert all, or quit.\n"
        "Retains displayed page sizes, metadata, and bookmark titles/hierarchy/page targets.\n"
        "Bookmark positions reset to fit-page. Converted pages lose searchable text and interactivity.\n"
        "Skipped pages are copied with their original contents and page order.\n"
        "Protected PDFs prompt for an opening password when needed.\n"
        "Pages are rendered in memory; no temporary page images or decrypted PDFs are written.",
        epilog=f"{FGray}Requirements: PyMuPDF, Pillow with libtiff, numpy, tqdm.\n"
        f"Interactive settings use CLI values as initial defaults: {DEFAULT_DPI} DPI, "
        f"threshold {DEFAULT_THRESHOLD}.\n"
        f"Parallel page encoding defaults to {DEFAULT_WORKERS} workers; --workers 1 is serial.\n"
        "Rendering stays on the main thread; a bounded queue feeds parallel Pillow encoders.\n"
        "The assembled PDF grows in memory; one temporary completed PDF is used for safe output.\n"
        "tqdm shows page/copy progress with speed and ETA; saving shows bytes and elapsed time.\n"
        "Higher thresholds make more pixels black; no dithering is used.\n"
        "Sauvola uses R=128; smaller k generally retains more black. Its window and sharpening\n"
        "radius are measured in base rendered pixels; adjust them when changing DPI.\n"
        "Upscaling automatically scales radius/window (window rounded up to odd).\n"
        "Levels map black/white points to 0/255, clipping outside; 0/255 changes nothing.\n"
        "Upscaling preserves PDF page sizes and cannot recover lost detail; 2x uses roughly\n"
        "4x image-processing memory per worker. Reduce --workers for large pages.\n"
        "Preview uses the same processing as full conversion, renders ONLY the chosen page,\n"
        "ignores skip selections, and exports a one-page PDF without source bookmarks/attachments.\n"
        "It opens in the default PDF viewer unless --no-open-preview is specified.\n"
        "--batch or --preview-page bypasses menus and uses defaults for omitted settings.\n"
        "Skip PDF pages with 1,2 or 1-3,4; -1,-2 means the last two pages; Enter skips none.\n"
        "Use --skip-pages=-1,-2 for negative CLI selections; --skip-pages= disables the prompt.\n"
        f"Example: pdf-binarize.py input.pdf -o output.pdf --dpi 300 --threshold 180{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="input PDF path")
    parser.add_argument("-o", "--output", help="new output PDF path (existing files are rejected)")
    parser.add_argument("--dpi", type=int, help=f"base render DPI before upscaling, {MIN_DPI}-{MAX_DPI}")
    parser.add_argument("--threshold", type=int, help=f"fixed-mode cutoff, {MIN_THRESHOLD}-{MAX_THRESHOLD}")
    parser.add_argument("--mode", choices=[mode.value for mode in _BinarizeMode], default="fixed",
                        help="threshold method (default: fixed)")
    parser.add_argument("--sauvola-window", type=int, default=DEFAULT_SAUVOLA_WINDOW,
                        help=f"odd base-pixel window, 3-{MAX_SAUVOLA_WINDOW} (default: {DEFAULT_SAUVOLA_WINDOW})")
    parser.add_argument("--sauvola-k", type=float, default=DEFAULT_SAUVOLA_K,
                        help="Sauvola k, 0 < k <= 1 (default: 0.2)")
    parser.add_argument("--levels", action=argparse.BooleanOptionalAction, default=False,
                        help="stretch black/white levels before upscaling/sharpening (default: off)")
    parser.add_argument("--black-point", type=int, default=DEFAULT_BLACK_POINT,
                        help="levels black point, 0-254, below white point (default: 0); requires --levels")
    parser.add_argument("--white-point", type=int, default=DEFAULT_WHITE_POINT,
                        help="levels white point, 1-255, above black point (default: 255); requires --levels")
    parser.add_argument("--upscale", type=int, default=DEFAULT_UPSCALE,
                        help=f"Lanczos enlargement, integer 1-{MAX_UPSCALE} (default: 1); auto-scales window/radius")
    parser.add_argument("--sharpen", action=argparse.BooleanOptionalAction, default=False,
                        help="apply Unsharp Mask before thresholding (default: off)")
    parser.add_argument("--sharpen-radius", type=float, default=DEFAULT_SHARPEN_RADIUS,
                        help=f"Unsharp Mask radius in base pixels, 0 < radius <= {MAX_SHARPEN_RADIUS} (default: 1)")
    parser.add_argument("--sharpen-percent", type=int, default=DEFAULT_SHARPEN_PERCENT,
                        help=f"Unsharp Mask amount, 1-{MAX_SHARPEN_PERCENT} (default: 100); requires --sharpen")
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--batch", action="store_true", help="convert the whole PDF without menus")
    action_group.add_argument("--preview-page", type=int, metavar="N",
                              help="export only physical PDF page N; -1 = last; bypass menus")
    parser.add_argument("--open-preview", action=argparse.BooleanOptionalAction, default=True,
                        help="open the preview PDF in the default viewer (default: on)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"parallel page encoders, 1-{MAX_WORKERS} (default: {DEFAULT_WORKERS})")
    parser.add_argument("--skip-pages", metavar="PAGES",
                        help="pages to leave unconverted (e.g. 1-3,4,-1); omitted: prompt in menu mode, none in batch")
    args = parser.parse_args()
    dpi = args.dpi if args.dpi is not None else DEFAULT_DPI
    threshold = args.threshold if args.threshold is not None else DEFAULT_THRESHOLD
    processing = _Processing(
        mode=_BinarizeMode(args.mode), window=args.sauvola_window, k=args.sauvola_k,
        sharpen=args.sharpen, sharpen_radius=args.sharpen_radius, sharpen_percent=args.sharpen_percent,
        levels=args.levels, black_point=args.black_point, white_point=args.white_point, upscale=args.upscale,
    )
    try:
        _validate_settings(dpi, threshold, args.workers, processing)
        if args.preview_page == 0:
            raise ValueError("Preview page cannot be zero; use 1 for first or -1 for last.")
    except ValueError as exc:
        parser.error(str(exc))

    # ── dependencies and input ──────────────────────────
    Console.print_banner("PDF BINARIZE")
    try:
        input_path = Path(args.input or Input.resolve_input_path("", prompt="Input PDF path"))
        if not input_path.is_file():
            raise FileNotFoundError(f"Input PDF not found: {input_path}")
        direct = args.batch or args.preview_page is not None
        if not direct:
            dpi, threshold, processing = _configure(dpi, threshold, processing)
        print(f"{FLYellow}Converted pages become images: searchable text and interactive features are lost.{CRst}")

        # ── preview / adjustment / final conversion loop ─────────
        while True:
            if direct:
                action = _Action.PREVIEW if args.preview_page is not None else _Action.CONVERT
            else:
                details = (f"threshold={threshold}" if processing.mode is _BinarizeMode.FIXED
                           else f"window={processing.window}, k={processing.k:g}")
                levels_info = f"{processing.black_point}/{processing.white_point}" if processing.levels else "off"
                print(f"\n{FLCyan}{dpi} base DPI; {processing.mode.value}; {details}; "
                      f"levels={levels_info}; upscale={processing.upscale}x ({dpi * processing.upscale} DPI); "
                      f"sharpen={'on' if processing.sharpen else 'off'}{CRst}")
                action = Menu.select(
                    [MenuOption(["P"], "Export and view one-page preview", _Action.PREVIEW),
                     MenuOption(["S"], "Change processing settings", _Action.SETTINGS),
                     MenuOption(["F"], "Convert full PDF", _Action.CONVERT),
                     MenuOption(["Q"], "Quit", _Action.QUIT)],
                    prompt="Choose action", default_key="F",
                )
            if action is _Action.QUIT:
                return 0
            if action is _Action.SETTINGS:
                dpi, threshold, processing = _configure(dpi, threshold, processing)
                continue
            try:
                if action is _Action.PREVIEW:
                    if args.preview_page is not None:
                        page_number = int(args.preview_page)
                    else:
                        page_number = int(Input.input_number(
                            "Physical PDF page to preview (-1 = last)", default=1, allow_float=False,
                        ))
                    default_output = input_path.with_name(
                        f"{input_path.stem}_preview_p{page_number}_{processing.mode.value}.pdf",
                    )
                    output_path = Path(args.output) if direct and args.output else Path(Input.resolve_output_path(
                        str(default_output), prompt="Preview PDF path",
                    ))
                    _preview_pdf(input_path, output_path, page_number, dpi, threshold, processing)
                    print(f"{FLGreen}Preview PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    if args.open_preview:
                        try:
                            System.open_with_default_app(str(output_path))
                        except OSError as exc:
                            print(f"{FLYellow}Preview saved; could not open the viewer: {exc}{CRst}")
                    if direct:
                        return 0
                else:
                    default_output = input_path.with_name(f"{input_path.stem}_binary.pdf")
                    output_path = Path(args.output) if direct and args.output else Path(Input.resolve_output_path(
                        args.output or str(default_output), prompt="Output PDF path",
                    ))
                    skip_pages = (args.skip_pages or "") if direct else args.skip_pages
                    _binarize_pdf(input_path, output_path, dpi, threshold, args.workers, skip_pages,
                                  processing=processing)
                    print(f"{FLGreen}Black-and-white PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    print(f"{FGray}Size: {Console.format_size(input_path.stat().st_size)}"
                          f" -> {Console.format_size(output_path.stat().st_size)}{CRst}")
                    return 0
            except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
                if direct:
                    raise
                print(f"{FLRed}Conversion failed: {exc}. Adjust settings or choose another output.{CRst}")
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}Binarization failed: {exc}{CRst}")
        return 1



if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
