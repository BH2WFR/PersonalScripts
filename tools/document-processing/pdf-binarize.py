#!/usr/bin/env python3
"""Interactively compress scanned PDFs with a 1-bit text layer and image crops.

Run without arguments. After selecting the input, a guided setup always asks
about text processing, illustration preservation/compression and noise cleanup.
Advanced output options (workers, preview viewer and region files) expand on
request. The main menu offers 1: preview, 2: repeat setup, 3: convert, 0: quit.
Preview uses physical page numbers (-1 = last); conversion prompts for skips.

Fixed thresholding is the default; Sauvola uses window=31, k=0.2, R=128.
Processing order: levels, Lanczos upscale, Unsharp Mask, binarization, optional
background cleanup, isolated-speck removal, then crop overlays. Levels,
sharpening, denoising, cleanup and detection default to off; upscale defaults
to 1x. Window/radius scale with upscaling, but are specified in base pixels.
Denoise area/distance scale from 240 DPI and protect neighboring punctuation.
Cleanup requires Sauvola. It removes gradient fills using local text polarity,
including vertical labels; flat reversed labels retain white-on-black. Uncertain
shaded text avoids text cleanup but follows the selected image mode and dithering
(without contrast enhancement), even with illustration detection off. Explicit
page region lists override these automatic crops. Preview remains essential.

Detection profiles text-first/balanced/image-first use thresholds 1.0/0.8/0.6.
Higher custom thresholds retain fewer boxes; scores are heuristic, not
probabilities. The text exclusion gate remains fixed. Opaque crops cover white
holes in the background, which always uses lossless 1-bit CCITT Group 4.
CCITT has no quality setting. KEEP retains rendered colors before JPEG encoding
(default quality 30); choose Flate for lossless KEEP. gray8 only converts to 8-bit
grayscale (up to 256 levels), with JPEG/Flate compression and no dithering.
gray2/gray4 and color2/color4
use actual packed 2/4-bit Flate images; color modes use 4/16 palette colors.
Dithering and crop contrast are optional and off by default. Crops retain base
DPI; levels/upscaling/sharpening affect only the binary background.

Advanced output settings can import source-SHA256-bound region JSON and export resolved JSON or
annotated PNGs beside each PDF. A listed page replaces detection; [] means no
boxes, omitted pages use automatic detection if enabled. Rectangles use
rect=[x0,y0,x1,y1], normalized 0..1, origin top-left, x right/y down.
Optional mode/dither/contrast/quality/codec fields override menu settings;
page objects may contain {"defaults": {...}, "regions": [...]}.
Precedence: built-in defaults -> profile -> menu -> page -> region.
Later boxes paint on top. Region modes text/text-invert remove shaded text-panel
backgrounds into 1-bit overlays. Preview exports only its physical page;
skipped pages are omitted. Sidecar paths derive from each selected PDF path.

Displayed page sizes, metadata and bookmark hierarchy/targets are retained;
bookmark positions reset to fit-page and PDF/A identification is removed.
Converted pages lose searchable text and interactive features. Skipped pages
retain their original contents and order. Page selections use physical numbers:
1-3,4 selects four pages; -1,-2 selects the last two; Enter skips nothing.
Rendering/assembly stay on the main thread; a bounded worker queue encodes
pages in memory. Reduce workers for large pages. Preview uses the same pipeline.
Passwords are requested privately and retained only in memory. Temporary final
PDFs are cleaned up; sources and existing outputs are never overwritten.

Requirements:
    - pip: PyMuPDF, Pillow (with libtiff), numpy, opencv-python, tqdm.

Usage:
    conda run -n base python tools/document-processing/pdf-binarize.py
    conda run -n base python run-script.py pdf-binarize
"""

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

# The launcher imports scripts by path; explicitly expose the private sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PIL import Image, ImageFilter, features
    import numpy as np
    from numpy.typing import NDArray
    import pymupdf
    from pymupdf.mupdf import FzErrorBase
    from tqdm import tqdm
    import _pdf_regions as regions
except ImportError as exc:
    print(f"{FLRed}Missing PDF/image dependency: {exc.name}{CRst}")
    print(f"{FGray}Install with: pip install PyMuPDF Pillow numpy opencv-python tqdm{CRst}")
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
_RegionSettings = regions._Settings
_PROFILE_LABELS: dict[regions._Profile, str] = {
    regions._Profile.TEXT_FIRST: "Text first - fewer protected illustrations",
    regions._Profile.BALANCED: "Balanced protection",
    regions._Profile.IMAGE_FIRST: "Image first - more protected illustrations",
}
_IMAGE_MODE_LABELS: dict[regions._Mode, str] = {
    regions._Mode.KEEP: "Keep original colors / grayscale",
    regions._Mode.GRAY2: "2-bit grayscale (4 gray levels)",
    regions._Mode.GRAY4: "4-bit grayscale (16 gray levels)",
    regions._Mode.GRAY8: "8-bit grayscale (256 gray levels; remove color only)",
    regions._Mode.COLOR2: "2-bit color (4 palette colors)",
    regions._Mode.COLOR4: "4-bit color (16 palette colors)",
}
_CODEC_LABELS: dict[regions._Codec, str] = {
    regions._Codec.JPEG: "JPEG - smaller files, lossy",
    regions._Codec.FLATE: "Flate - lossless",
}
_DITHER_LABELS: dict[regions._Dither, str] = {
    regions._Dither.NONE: "No dithering - usually smaller files",
    regions._Dither.ORDERED: "Ordered dithering - regular dot pattern",
    regions._Dither.DIFFUSION: "Error diffusion - smoother tones, may increase size",
}


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
    regions: _RegionSettings = dataclasses.field(default_factory=_RegionSettings)


DEFAULT_PROCESSING = _Processing()


@dataclasses.dataclass(frozen=True)
class _OutputOptions:
    """Interactive session choices, separate from per-page image settings."""

    workers: int = DEFAULT_WORKERS
    open_preview: bool = True
    export_regions: bool = False
    annotate_regions: bool = False


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
    regions._validate(processing.regions)
    if processing.regions.clean_background and processing.mode is not _BinarizeMode.SAUVOLA:
        raise ValueError("Background cleanup requires Sauvola mode; repeat setup to change the mode or disable cleanup.")


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


def _replace_page(document: pymupdf.Document, index: int, encoded: bytes | regions._Page) -> None:
    """Replace one page's contents while retaining its identity and incoming links.

    Uses the displayed dimensions (including crop, rotation and UserUnit).
    Removes this page's interactive objects, then places the encoded PDF without
    decoding its 1-bit image. Other pages and document metadata are unchanged.
    """
    if isinstance(encoded, regions._Page):
        encoded = regions._assemble(encoded)
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
    overrides: tuple[regions._Region, ...] | None = None,
) -> bytes | regions._Page:
    """Threshold one rendered page and return an independent CCITT PDF buffer.

    Takes ownership of rendered and closes it even on failure. Each worker owns
    its image and PDF buffer; no PyMuPDF objects enter worker threads.
    """
    settings = processing.regions
    with rendered, io.BytesIO() as page_pdf, ExitStack() as images:
        boxes = overrides if overrides is not None else (regions._detect(rendered, settings) if settings.enabled else ())
        panels = regions._text_panels(rendered) if settings.clean_background else ()
        if overrides is None:
            # Leave imported page lists authoritative, including explicit [].
            # Existing protected illustrations take priority over panel guesses.
            for panel in panels:
                box = regions._pixel_box(panel.rect, rendered.size)
                if not panel.reliable and not any(
                    regions._intersection(box, regions._pixel_box(region.rect, rendered.size)) > 0 for region in boxes
                ):
                    boxes += (regions._Region(panel.rect, mode=settings.mode, dither=settings.dither,
                                              quality=settings.quality, codec=settings.codec),)
        layers: list[regions._Layer] = []
        # Crops retain their native rendered resolution, unaffected by text-only
        # levels, enlargement and sharpening. Map bounds to the enlarged base.
        output_size = (rendered.width * processing.upscale, rendered.height * processing.upscale)
        for region in boxes:
            box = regions._pixel_box(region.rect, rendered.size)
            with rendered.crop(box) as crop:
                layer = regions._encode_crop(crop, regions._pixel_box(region.rect, output_size), region)
                layers.append(layer)
        with rendered.convert("L") as gray:
            binary = images.enter_context(_threshold_image(gray, threshold, processing))
            if settings.clean_background:
                original = images.enter_context(gray.resize(output_size, Image.Resampling.LANCZOS))
                binary = images.enter_context(regions._clean_background(original, binary, panels))
            if settings.denoise:
                binary = images.enter_context(regions._denoise(binary, dpi * processing.upscale, settings))
            for region in boxes:
                binary.paste(1, regions._pixel_box(region.rect, output_size))
            binary.save(page_pdf, format="PDF", resolution=dpi * processing.upscale)
        encoded = page_pdf.getvalue()
        if settings.active:
            annotation = regions._annotation(rendered, boxes) if settings.preview_dir else None
            return regions._Page(encoded, output_size, tuple(layers), boxes, annotation)
        return encoded


def _render_page(document: pymupdf.Document, index: int, dpi: int, color: bool = False) -> Image.Image:
    """Render one zero-based page into an independently owned grayscale image.

    Call only on the main thread. get_pixmap respects the visible crop, rotation,
    and UserUnit. frombytes copies the pixels, so workers never share a MuPDF
    buffer. The caller must close the returned image or transfer it to an encoder.
    """
    page = document.load_page(index)
    pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB if color else pymupdf.csGRAY, alpha=False)
    return Image.frombytes("RGB" if color else "L", (pixmap.width, pixmap.height), pixmap.samples)


def _encoded_pages(
    input_path: Path, page_indexes: list[int], dpi: int, threshold: int,
    workers: int, password: str = "",
    processing: _Processing = DEFAULT_PROCESSING,
    overrides: dict[int, tuple[regions._Region, ...]] | None = None,
) -> Generator[bytes | regions._Page, None, None]:
    """Render in memory and yield encoded pages with a bounded worker queue.

    Only this generator's calling thread uses PyMuPDF. Workers receive independent
    Pillow images. Closing the generator waits for encoders and closes even the
    images belonging to cancelled tasks, then closes the renderer. No page images
    or decrypted PDFs are written to disk. One worker takes the serial path.
    """
    if not page_indexes:
        return
    overrides = overrides or {}
    def render(document: pymupdf.Document, index: int) -> Image.Image:
        # Preserve the legacy three-argument call for callers/instrumentation.
        return (_render_page(document, index, dpi, color=True) if processing.regions.active
                else _render_page(document, index, dpi))

    def encode(image: Image.Image, index: int) -> bytes | regions._Page:
        if processing.regions.active:
            return _encode_page(image, dpi, threshold, processing, overrides.get(index))
        return _encode_page(image, dpi, threshold, processing)

    with Pdf.open_document(input_path, password=password, interactive=False) as (document, _):
        if workers == 1:
            for index in page_indexes:
                yield encode(render(document, index), index)
            return

        indexes = iter(page_indexes)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-encode")
        pending: deque[tuple[Future[bytes | regions._Page], Image.Image]] = deque()

        def submit(index: int) -> None:
            rendered = render(document, index)
            try:
                future = executor.submit(encode, rendered, index)
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


def _prepare_region_files(
    input_path: Path, output_path: Path, page_count: int, settings: regions._Settings,
) -> dict[int, tuple[regions._Region, ...]]:
    """Preflight sidecar destinations and validate source-bound page overrides."""
    destinations = [output_path, *[path for path in (settings.export, settings.preview_dir) if path is not None]]
    if len({path.resolve() for path in destinations}) != len(destinations):
        raise ValueError("PDF, region JSON and annotation directory must have different paths.")
    for path in destinations[1:]:
        if path.exists() or path.resolve() == input_path.resolve():
            raise FileExistsError(f"Region output must be a new path: {path}")
        if not path.parent.is_dir():
            raise FileNotFoundError(f"Region output parent directory not found: {path.parent}")
    return regions._read_config(settings.input, input_path, page_count, settings)


def _publish_region_files(
    input_path: Path, output_path: Path, page_count: int, settings: regions._Settings,
    records: dict[int, tuple[regions._Region, ...]], annotations: dict[int, bytes],
) -> None:
    """Publish optional review artifacts after a successful PDF; never overwrite."""
    try:
        if settings.export:
            regions._write_config(settings.export, input_path, page_count, records)
            print(f"{FLGreen}Region configuration saved to:{CRst} {FGray}{settings.export}{CRst}")
        if settings.preview_dir:
            settings.preview_dir.mkdir(exist_ok=False)
            for index, png in sorted(annotations.items()):
                with (settings.preview_dir / f"page-{index + 1:04d}.png").open("xb") as stream:
                    stream.write(png)
            print(f"{FLGreen}Region annotations saved to:{CRst} {FGray}{settings.preview_dir}{CRst}")
    except OSError as exc:
        raise OSError(f"PDF was saved to {output_path}, but region review output failed: {exc}") from exc
    if settings.active:
        print(f"{FLCyan}Protected regions: {sum(map(len, records.values()))}; "
              f"background: lossless 1-bit CCITT Group 4.{CRst}")


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
    with Pdf.open_document(input_path) as (reader, password):
        if not reader.page_count:
            raise ValueError("The input PDF has no pages.")
        page_count = reader.page_count
        overrides = _prepare_region_files(input_path, output_path, page_count, processing.regions)
        records: dict[int, tuple[regions._Region, ...]] = {}
        annotations: dict[int, bytes] = {}
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
            encoded_pages = _encoded_pages(input_path, render_pages, dpi, threshold, workers, password, processing, overrides)
            with closing(encoded_pages), tqdm(
                total=page_count, desc="Processing pages", unit="page",
                file=sys.stdout, dynamic_ncols=True, miniters=1,
                postfix={"skipped": len(skipped)},
            ) as progress:
                for number in range(1, page_count + 1):
                    if number - 1 not in skipped:
                        encoded = next(encoded_pages)
                        if isinstance(encoded, regions._Page):
                            records[number - 1] = encoded.regions
                            if encoded.annotation is not None:
                                annotations[number - 1] = encoded.annotation
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
        _publish_region_files(input_path, output_path, page_count, processing.regions, records, annotations)


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
    with Pdf.open_document(input_path) as (source, _):
        if not source.page_count:
            raise ValueError("The input PDF has no pages.")
        overrides = _prepare_region_files(input_path, output_path, source.page_count, processing.regions)
        index = Input.parse_index_ranges(str(page_number), item_count=source.page_count)[0]
        rect = source[index].rect
        print(f"{FLCyan}Converting preview page {index + 1} of {source.page_count}...{CRst}", flush=True)
        Image.init()
        if processing.regions.active:
            encoded = _encode_page(_render_page(source, index, dpi, color=True), dpi, threshold, processing,
                                   overrides.get(index))
        else:
            encoded = _encode_page(_render_page(source, index, dpi), dpi, threshold, processing)
        with pymupdf.open() as preview:
            preview.new_page(width=rect.width, height=rect.height)
            _replace_page(preview, 0, encoded)
            preview.set_metadata(source.metadata or {})
            Pdf.save_new(preview, output_path)
        if isinstance(encoded, regions._Page):
            _publish_region_files(input_path, output_path, source.page_count, processing.regions,
                                  {index: encoded.regions}, {index: encoded.annotation} if encoded.annotation else {})


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
    return dpi, threshold, dataclasses.replace(processing,
        mode=mode, window=window, k=k, sharpen=sharpen, sharpen_radius=radius,
        sharpen_percent=percent, levels=levels, black_point=black_point,
        white_point=white_point, upscale=upscale,
    )


def _toggle(prompt: str, current: bool) -> bool:
    """Prompt for an on/off choice, retaining the current value on Enter."""
    return bool(Menu.select([MenuOption(["N"], "Off", False), MenuOption(["Y"], "On", True)],
                            prompt=prompt, default_key="Y" if current else "N", inline=True, separator=False))


def _configure_enhancements(processing: _Processing) -> _Processing:
    """Guide illustration protection first, then independent noise cleanup."""
    settings = processing.regions
    print(f"\n{FLYellow}Illustration preservation{CRst}")
    print(f"{FGray}Protect detected illustrations from text binarization and compress them separately.\n"
          f"When off, illustrations are binarized; shaded-text cleanup can still protect uncertain text panels.{CRst}")
    enabled = _toggle("Automatically preserve illustrations?", settings.enabled)
    profile, threshold = settings.profile, settings.threshold
    mode, dither, contrast, quality, codec = settings.mode, settings.dither, settings.contrast, settings.quality, settings.codec
    if enabled or settings.input is not None:
        if enabled:
            profile = cast(regions._Profile, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _PROFILE_LABELS.items()],
                prompt="Detection profile", default_key=profile.value, separator=False))
            cutoff = (regions._PROFILE_THRESHOLDS[profile]
                      if threshold is None or profile != settings.profile else threshold)
            threshold = float(Input.input_number("Region threshold (higher = fewer boxes)", default=cutoff,
                                                 min_value=.1, max_value=2))
        mode = cast(regions._Mode, Menu.select(
            [MenuOption([value.value], label, value) for value, label in _IMAGE_MODE_LABELS.items()],
            prompt="Protected image mode", default_key=mode.value, separator=False))
        if mode in (regions._Mode.KEEP, regions._Mode.GRAY8):
            codec = cast(regions._Codec, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _CODEC_LABELS.items()],
                prompt="Illustration compression", default_key=codec.value, separator=False))
            if codec is regions._Codec.JPEG:
                quality = int(Input.input_number("JPEG crop quality (CCITT background is always lossless)",
                    default=quality, min_value=1, max_value=95, allow_float=False))
        else:
            dither = cast(regions._Dither, Menu.select(
                [MenuOption([value.value], label, value) for value, label in _DITHER_LABELS.items()],
                prompt="Dithering (can increase size)", default_key=dither.value, separator=False))
        contrast = float(Input.input_number("Crop contrast (1 = off)", default=contrast, min_value=1, max_value=4))
    print(f"\n{FLYellow}Noise and background cleanup{CRst}")
    denoise = _toggle("Remove isolated binary specks (also works without illustration protection)?", settings.denoise)
    area, distance = settings.denoise_area, settings.denoise_distance
    if denoise:
        area = float(Input.input_number("Maximum speck area at 240 DPI", default=area,
                                       min_value=0, min_value_allowed=False, max_value=100))
        distance = float(Input.input_number("Required distance from other ink at 240 DPI", default=distance,
                                           min_value=1, max_value=100))
    clean = _toggle("Clean shaded text (auto polarity; preserve uncertain panels; requires Sauvola)?", settings.clean_background)
    if clean:
        effective_codec = codec if mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else regions._Codec.FLATE
        print(f"{FGray}Gradient fills become white; flat reversed labels stay white-on-black.\n"
              f"Uncertain text panels use {mode.value}/{effective_codec.value} without contrast enhancement"
              f"{f' (quality {quality})' if effective_codec is regions._Codec.JPEG else ''}. Preview to check lettering.{CRst}")
    if clean and processing.mode is not _BinarizeMode.SAUVOLA:
        print(f"{FLCyan}Switching to Sauvola for background cleanup.{CRst}")
        processing = dataclasses.replace(processing, mode=_BinarizeMode.SAUVOLA)
    settings = dataclasses.replace(settings, enabled=enabled, profile=profile, threshold=threshold, mode=mode,
        dither=dither, contrast=contrast, quality=quality, codec=codec, denoise=denoise, denoise_area=area,
        denoise_distance=distance, clean_background=clean)
    return dataclasses.replace(processing, regions=settings)


def _configure_output(
    processing: _Processing, options: _OutputOptions,
) -> tuple[_Processing, _OutputOptions]:
    """Configure workers, viewer and region files through interactive prompts."""
    workers = int(Input.input_number(
        "Parallel page encoders (1 = serial)", default=options.workers,
        min_value=1, max_value=MAX_WORKERS, allow_float=False,
    ))
    open_preview = _toggle("Open exported previews in the default viewer?", options.open_preview)
    region_input = processing.regions.input
    if _toggle("Import a region JSON configuration?", region_input is not None):
        region_input = Path(Input.resolve_input_path(
            str(region_input or ""), prompt="Region JSON path",
        ))
    else:
        region_input = None
    export_regions = _toggle("Save region JSON beside each PDF?", options.export_regions)
    annotate_regions = _toggle("Save box annotations beside each PDF?", options.annotate_regions)
    settings = dataclasses.replace(processing.regions, input=region_input)
    return dataclasses.replace(processing, regions=settings), _OutputOptions(
        workers=workers, open_preview=open_preview,
        export_regions=export_regions, annotate_regions=annotate_regions,
    )


def _processing_for_output(
    processing: _Processing, options: _OutputOptions, output_path: Path,
) -> _Processing:
    """Derive per-export sidecar paths so repeated previews use fresh destinations."""
    settings = dataclasses.replace(
        processing.regions,
        export=output_path.with_suffix(".regions.json") if options.export_regions else None,
        preview_dir=output_path.with_name(f"{output_path.stem}_regions") if options.annotate_regions else None,
    )
    regions._validate(settings)
    return dataclasses.replace(processing, regions=settings)


def _configure_session(
    dpi: int, threshold: int, processing: _Processing, options: _OutputOptions,
) -> tuple[int, int, _Processing, _OutputOptions]:
    """Run the same complete, ordered setup on first use and later adjustments."""
    print(f"\n{FLYellow}Text processing{CRst}")
    dpi, threshold, processing = _configure(dpi, threshold, processing)
    processing = _configure_enhancements(processing)
    if _toggle("Change advanced output settings (workers, viewer, region files)?", False):
        processing, options = _configure_output(processing, options)
    return dpi, threshold, processing, options


def main() -> int:
    """Run the interactive scan-compression menu without command-line options.

    Returns:
        Zero after conversion or quitting, or one if the input cannot be opened.

    Prompts for paths, settings and opening passwords; writes new PDFs and
    optional region review files. Conversion errors return to the menu.
    Existing files and the source are never overwritten.
    """
    # ── introduction and input ──────────────────────────
    Console.print_banner("PDF BINARIZE")
    description = (
        "Compress scans with 1-bit text and optional illustration crops.\n"
        "Setup covers text, illustration preservation and noise cleanup in order.\n"
        "Preview a page before converting; page sizes and bookmarks are retained.\n"
        "CCITT is lossless; JPEG crop quality defaults to 30.\n"
        "Converted pages lose searchable text and interactive features."
    )
    print(f"{FGray}{description}{CRst}")
    dpi, threshold, processing = DEFAULT_DPI, DEFAULT_THRESHOLD, DEFAULT_PROCESSING
    options = _OutputOptions()
    try:
        input_path = Path(Input.resolve_input_path("", prompt="Input PDF path"))
        if not input_path.is_file():
            raise FileNotFoundError(f"Input PDF not found: {input_path}")
        dpi, threshold, processing, options = _configure_session(dpi, threshold, processing, options)

        # ── preview / adjustment / final conversion loop ─────────
        while True:
            details = (f"threshold={threshold}" if processing.mode is _BinarizeMode.FIXED
                       else f"window={processing.window}, k={processing.k:g}")
            levels_info = f"{processing.black_point}/{processing.white_point}" if processing.levels else "off"
            settings = processing.regions
            print(f"\n{FLCyan}{dpi} base DPI; {processing.mode.value}; {details}; "
                  f"levels={levels_info}; upscale={processing.upscale}x ({dpi * processing.upscale} DPI); "
                  f"sharpen={'on' if processing.sharpen else 'off'}{CRst}")
            if settings.enabled or settings.input is not None:
                codec = settings.codec if settings.mode in (regions._Mode.KEEP, regions._Mode.GRAY8) else regions._Codec.FLATE
                quality_info = f"; JPEG quality={settings.quality}" if codec is regions._Codec.JPEG else ""
                detection_info = (f"auto ({settings.profile.value}, threshold={settings.cutoff:g})"
                                  if settings.enabled else "imported regions only")
                print(f"{FLCyan}Illustration protection: {detection_info}; "
                      f"image={settings.mode.value}/{codec.value}{quality_info}{CRst}")
            else:
                print(f"{FLCyan}Illustration protection: off; illustrations will be binarized with text.{CRst}")
            print(f"{FGray}Denoise={'on' if settings.denoise else 'off'}; "
                  f"background cleanup={'on' if settings.clean_background else 'off'}{CRst}")
            if settings.clean_background:
                fallback_codec = (settings.codec if settings.mode in (regions._Mode.KEEP, regions._Mode.GRAY8)
                                  else regions._Codec.FLATE)
                fallback_info = (f"{settings.mode.value}/{fallback_codec.value}, quality {settings.quality}"
                                 if fallback_codec is regions._Codec.JPEG else f"{settings.mode.value}/{fallback_codec.value}")
                print(f"{FGray}Shaded text: local polarity; uncertain panels follow image mode "
                      f"({fallback_info}); imported page regions take priority.{CRst}")
            print(f"{FGray}Workers={options.workers}; open preview={'yes' if options.open_preview else 'no'}; "
                  f"region input={settings.input or 'none'}; "
                  f"save JSON={'yes' if options.export_regions else 'no'}; "
                  f"annotations={'yes' if options.annotate_regions else 'no'}{CRst}")
            action = Menu.select(
                [MenuOption(["1"], "Preview one page", _Action.PREVIEW),
                 MenuOption(["2"], "Change settings", _Action.SETTINGS),
                 MenuOption(["3"], "Convert full PDF", _Action.CONVERT),
                 MenuOption(["0"], "Quit", _Action.QUIT)],
                prompt="Choose action", default_key="3",
            )
            if action is _Action.QUIT:
                return 0
            try:
                if action is _Action.SETTINGS:
                    dpi, threshold, processing, options = _configure_session(dpi, threshold, processing, options)
                    continue
                _validate_settings(dpi, threshold, options.workers, processing)
                if action is _Action.PREVIEW:
                    page_number = int(Input.input_number(
                        "Physical PDF page to preview (-1 = last)", default=1, allow_float=False,
                    ))
                    default_output = input_path.with_name(
                        f"{input_path.stem}_preview_p{page_number}_{processing.mode.value}.pdf",
                    )
                    output_path = Path(Input.resolve_output_path(str(default_output), prompt="Preview PDF path"))
                    effective = _processing_for_output(processing, options, output_path)
                    _preview_pdf(input_path, output_path, page_number, dpi, threshold, effective)
                    print(f"{FLGreen}Preview PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    if options.open_preview:
                        try:
                            System.open_with_default_app(str(output_path))
                        except OSError as exc:
                            print(f"{FLYellow}Preview saved; could not open the viewer: {exc}{CRst}")
                else:
                    default_output = input_path.with_name(f"{input_path.stem}_binary.pdf")
                    output_path = Path(Input.resolve_output_path(str(default_output), prompt="Output PDF path"))
                    effective = _processing_for_output(processing, options, output_path)
                    _binarize_pdf(input_path, output_path, dpi, threshold, options.workers, None,
                                  processing=effective)
                    print(f"{FLGreen}Compressed PDF saved to:{CRst} {FGray}{output_path}{CRst}")
                    print(f"{FGray}Size: {Console.format_size(input_path.stat().st_size)}"
                          f" -> {Console.format_size(output_path.stat().st_size)}{CRst}")
                    return 0
            except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
                print(f"{FLRed}Conversion failed: {exc}. Adjust settings or choose another output.{CRst}")
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}Binarization failed: {exc}{CRst}")
        return 1



if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
