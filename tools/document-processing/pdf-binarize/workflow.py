"""Safe file output, page selection, previews and review sidecars."""

from contextlib import closing
from pathlib import Path
import sys
import tempfile
import threading
import time
from PIL import Image, features
import pymupdf
from tqdm import tqdm
from utils import *
from . import objects, regions
from .settings import *
from .settings import _Processing, _validate_settings

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
    """Process PDF image objects and optional vector colors without overwriting existing files.

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
        objects._isolate_skipped(reader, skipped)
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
                    f"{FLCyan}Processing images on {render_count} pages at {dpi} DPI; "
                    f"encoding with {workers} worker(s). No temporary page images...{CRst}", flush=True,
                )
            else:
                print(f"{FLCyan}All pages skipped; rendering and binarization are unnecessary.{CRst}", flush=True)
            with closing(objects._Engine(reader, dpi, threshold, processing, workers)) as engine, tqdm(
                total=page_count, desc="Processing pages", unit="page",
                file=sys.stdout, dynamic_ncols=True, postfix={"skipped": len(skipped)},
            ) as progress:
                for index in range(page_count):
                    if index not in skipped:
                        original: Image.Image | None = None
                        if processing.regions.preview_dir:
                            page = reader[index]
                            pix = page.get_pixmap(dpi=min(dpi, 120), alpha=False)
                            original = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                        try:
                            records[index] = engine.page(index, overrides.get(index))
                            if original is not None:
                                annotations[index] = regions._annotation(original, records[index])
                        finally:
                            if original is not None:
                                original.close()
                    progress.update(1)
                print(f"{FLCyan}Processed {engine.images} image invocation(s); native text and page features retained.{CRst}")
                for notice in sorted(engine.notices):
                    print(f"{FLYellow}{notice}{CRst}")

            print(f"{FLCyan}Preserving document metadata and exact bookmark destinations...{CRst}", flush=True)
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
    """Export a single processed page with its native text and page annotations.

    Uses the same engine as full conversion. A one-page extract cannot retain
    destinations on other pages or the whole-document outline; full output does.
    Invalid settings/pages fail before creating output; existing files are safe.
    """
    _validate_settings(dpi, threshold, 1, processing)
    if input_path.resolve() == output_path.resolve() or output_path.exists():
        raise FileExistsError(f"Output must be a new file: {output_path}")
    if not features.check("libtiff"):
        raise RuntimeError("Pillow libtiff is required for CCITT Group 4.")
    with Pdf.open_document(input_path) as (source, _):
        page_count = source.page_count
        if not page_count:
            raise ValueError("The input PDF has no pages.")
        overrides = _prepare_region_files(input_path, output_path, page_count, processing.regions)
        index = Input.parse_index_ranges(str(page_number), item_count=page_count)[0]
        Image.init()
        annotations: dict[int, bytes] = {}
        with closing(objects._Engine(source, dpi, threshold, processing, 1)) as engine:
            original: Image.Image | None = None
            if processing.regions.preview_dir:
                pix = source[index].get_pixmap(dpi=min(dpi, 120), alpha=False)
                original = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            try:
                boxes = engine.page(index, overrides.get(index))
                if original is not None:
                    annotations[index] = regions._annotation(original, boxes)
            finally:
                if original is not None:
                    original.close()
            for notice in sorted(engine.notices):
                print(f"{FLYellow}{notice}{CRst}")
        with pymupdf.open() as preview:
            preview.insert_pdf(source, from_page=index, to_page=index, links=True, annots=True, widgets=True)
            preview.set_metadata(source.metadata or {})
            Pdf.save_new(preview, output_path)
        _publish_region_files(input_path, output_path, page_count, processing.regions, {index: boxes}, annotations)

