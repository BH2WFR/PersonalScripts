"""Headless, serial PDF worker for inspection, preview and profile-aware export.

The desktop process sends JSON lines through stdin. All MuPDF operations happen
on this process's main thread; existing image encoders may use their own threads.
Processed previews use fresh page extracts; originals render the retained source
directly. Exports reopen the untouched input. GUI pixels use a shared-memory slot.
"""

from contextlib import ExitStack, closing, redirect_stdout
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
from typing import Callable, cast

from PIL import Image
import pymupdf

from utils import *
from ..common.protocol import Json, MAX_PREVIEW_PIXELS
from ..common.pdf_images import inspect_images
from ..common.pixel_transfer import preview_reply
from . import objects, regions, workflow
from .project import Config, Project, SKIP_ID, mapping, text_value
from .settings import _Processing

DISPLAY_DPI = 300
MAX_DISPLAY_PIXELS = MAX_PREVIEW_PIXELS
COPY_BYTES = 1024 * 1024


class Cancelled(RuntimeError):
    """Cooperative cancellation before publication or at a page boundary."""


def _check_cancel(path: Path | None) -> None:
    if path is not None and path.exists():
        raise Cancelled("Conversion cancelled.")


def _overrides(project: Project, config: Config) -> dict[int, tuple[regions._Region, ...]]:
    settings = replace(config.processing.regions, input=project.output.region_input)
    return regions._read_config(project.output.region_input, project.source, project.page_count, settings)


def _processing(project: Project, config: Config) -> _Processing:
    return replace(config.processing, regions=replace(config.processing.regions, input=project.output.region_input))


def _preview_document(project: Project, password: str,
                      source: pymupdf.Document | None = None) -> tuple[pymupdf.Document, tuple[regions._Region, ...]]:
    """Extract clean input, then apply the selected profile once; caller closes it."""
    index = project.current_page
    profile = project.profiles[project.assignments[index]]
    preview = pymupdf.open()
    try:
        with ExitStack() as inputs:
            if source is None:
                source, _ = inputs.enter_context(Pdf.open_document(project.source, password=password, interactive=False))
            if source.page_count != project.page_count:
                raise ValueError("The PDF page count no longer matches the project.")
            preview.insert_pdf(source, from_page=index, to_page=index, links=False, annots=True, widgets=True)
        boxes: tuple[regions._Region, ...] = ()
        if not project.show_original and profile.id != SKIP_ID:
            config = profile.config
            overrides = _overrides(project, config)
            with closing(objects._Engine(preview, config.dpi, config.threshold, _processing(project, config), 1)) as engine:
                boxes = engine.page(0, overrides.get(index))
        return preview, boxes
    except BaseException:
        preview.close()
        raise


def _preview(project: Project, password: str, source: pymupdf.Document, raw: bool = False) -> tuple[dict[str, Json], bytes]:
    """Render originals directly; only processed results need a copied page."""
    original = project.show_original or project.assignments[project.current_page] == SKIP_ID
    boxes: tuple[regions._Region, ...] = ()
    with ExitStack() as documents:
        page = source[project.current_page]
        if not original or project.show_regions and project.assignments[project.current_page] != SKIP_ID:
            document, boxes = _preview_document(replace(project, show_original=False), password, source)
            documents.enter_context(document)
            if not original:
                page = document[0]
        pixmap = Pdf.render_page(page, dpi=DISPLAY_DPI, max_pixels=MAX_DISPLAY_PIXELS)
        images = inspect_images(page)
        return {"kind": "preview", "page": project.current_page, "width": pixmap.width, "height": pixmap.height,
                "page_size": [page.rect.width, page.rect.height],
                "regions": [list(box.rect) for box in boxes],
                "images": [image.to_data() for image in images],
                "regions_available": not original or project.show_regions}, (
                    pixmap.samples if raw else pixmap.pil_tobytes(format="PNG", compress_level=1))


def _publish(staged: Path, output: Path, cancel: Path | None, overwrite: bool = False) -> None:
    """Publish a completed stage exclusively, or replace an explicitly approved output."""
    _check_cancel(cancel)
    if overwrite:
        staged.replace(output)
        return
    with output.open("xb") as destination:
        try:
            with staged.open("rb") as source:
                while chunk := source.read(COPY_BYTES):
                    _check_cancel(cancel)
                    destination.write(chunk)
        except BaseException:
            destination.close()
            output.unlink(missing_ok=True)
            raise


def export_project(project: Project, output: Path, password: str = "", *,
                   progress: Callable[[dict[str, Json]], None] | None = None,
                   cancel: Path | None = None, one_page: bool = False, overwrite: bool = False) -> None:
    """Export current profiles while preserving source objects and original order.

    Args:
        project: Validated project snapshot; never modified during this operation.
        output: New PDF in an existing directory, distinct from the input.
        password: In-memory input password, never written to project files.
        progress: Optional receiver of page/save stage messages.
        cancel: Optional marker file checked at page and publication boundaries.
        one_page: Export only the current page, including its chosen viewing mode.
        overwrite: Explicit GUI approval to atomically replace an existing output.

    Raises:
        ValueError: Source page count or parameters no longer match the project.
        FileExistsError: Destination is the source, an unapproved PDF already
            exists, or requested review sidecars already exist.
        Cancelled: Cancellation was requested before completion.
        OSError: Input/output access fails. A sidecar error reports an already
            published PDF explicitly, matching the terminal workflow.

    Writes a new PDF and optional review files; never overwrites the source.
    """
    if (output.resolve() == project.source.resolve()
            or output.exists() and (output.samefile(project.source) or not overwrite)):
        raise FileExistsError(f"Output must be a new PDF: {output}")
    review = regions._Settings(enabled=True,
        export=output.with_suffix(".regions.json") if project.output.export_regions else None,
        preview_dir=output.with_name(f"{output.stem}_regions") if project.output.annotate_regions else None)
    workflow._prepare_region_files(project.source, output, project.page_count, review)
    records: dict[int, tuple[regions._Region, ...]] = {}
    annotations: dict[int, bytes] = {}
    send = progress or (lambda message: None)
    _check_cancel(cancel)
    # ── stage the PDF before publishing a new destination ──
    with tempfile.TemporaryDirectory(prefix=".pdf-tools-", dir=output.parent) as directory:
        staged = Path(directory) / "result.pdf"
        if one_page:
            document, boxes = _preview_document(project, password)
            with document:
                _check_cancel(cancel)
                if project.assignments[project.current_page] != SKIP_ID and not project.show_original:
                    records[project.current_page] = boxes
                    if review.preview_dir:
                        with Pdf.open_document(project.source, password=password, interactive=False) as (source, _):
                            pixmap = source[project.current_page].get_pixmap(dpi=100, alpha=False)
                            with Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples) as image:
                                annotations[project.current_page] = regions._annotation(image, boxes)
                Pdf.save_new(document, staged)
        else:
            with Pdf.open_document(project.source, password=password, interactive=False) as (document, _):
                if document.page_count != project.page_count:
                    raise ValueError("The PDF page count no longer matches the project.")
                skipped = {index for index, identity in enumerate(project.assignments) if identity == SKIP_ID}
                objects._isolate_skipped(document, skipped)
                completed = len(skipped)
                send({"kind": "progress", "done": completed, "total": project.page_count, "stage": "Processing pages"})
                # Each engine has immutable settings and a private result cache.
                for identity, profile in project.profiles.items():
                    selected = [index for index, value in enumerate(project.assignments) if value == identity]
                    if identity == SKIP_ID or not selected:
                        continue
                    config = profile.config
                    overrides = _overrides(project, config)
                    with closing(objects._Engine(document, config.dpi, config.threshold,
                                                 _processing(project, config), project.output.workers)) as engine:
                        for index in selected:
                            _check_cancel(cancel)
                            original: Image.Image | None = None
                            try:
                                if review.preview_dir:
                                    pix = document[index].get_pixmap(dpi=100, alpha=False)
                                    original = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                                records[index] = engine.page(index, overrides.get(index))
                                if original is not None:
                                    annotations[index] = regions._annotation(original, records[index])
                            finally:
                                if original is not None:
                                    original.close()
                            completed += 1
                            send({"kind": "progress", "done": completed, "total": project.page_count,
                                  "stage": f"Processed page {index + 1}"})
                _check_cancel(cancel)
                send({"kind": "progress", "stage": "Writing PDF", "done": project.page_count, "total": project.page_count})
                Pdf.save_new(document, staged)
        _publish(staged, output, cancel, overwrite)
    if review.export or review.preview_dir:
        workflow._publish_region_files(project.source, output, project.page_count, review, records, annotations)


class Worker:
    """Serial dispatcher owning one read-only document; the GUI caches previews."""

    def __init__(self) -> None:
        self._inputs = ExitStack()
        self._document: pymupdf.Document | None = None
        self._source_key: tuple[str, int, int, str] | None = None
        self._password = ""

    def close(self) -> None:
        """Release the read-only source handle and its authentication state."""
        self._inputs.close()
        self._document = None
        self._source_key = None
        self._password = ""

    def _source(self, path: Path, password: str) -> pymupdf.Document:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, password)
        if key != self._source_key or self._document is None:
            self.close()
            self._document, self._password = self._inputs.enter_context(
                Pdf.open_document(path, password=password, interactive=False))
            self._source_key = key
        return self._document

    def run(self, request: dict[str, Json], send: Callable[[dict[str, Json]], None]) -> dict[str, Json]:
        """Execute one request; raise errors for the protocol loop to report."""
        operation = text_value(request.get("operation"), "Operation")
        password = str(request.get("password", ""))
        if operation == "inspect":
            document = self._source(Path(text_value(request.get("path"), "PDF path")), password)
            if document.page_count == 0:
                raise ValueError("The PDF has no pages.")
            return {"kind": "opened", "page_count": document.page_count,
                    "labels": cast(list[Json], Pdf.read_page_labels(document)),
                    "bookmarks": cast(list[Json], document.get_toc()), "password": self._password}
        project = Project.from_data(mapping(request.get("project"), "Project"), Path.cwd())
        if operation == "preview":
            document = self._source(project.source, password)
            if document.page_count != project.page_count:
                raise ValueError("The PDF page count no longer matches the project.")
            raw = bool(request.get("pixel_buffer"))
            result, pixels = _preview(project, password, document, raw)
            return preview_reply(result, pixels, request)
        if operation not in ("export", "export-page"):
            raise ValueError(f"Unknown operation: {operation}")
        output = Path(text_value(request.get("output"), "Output PDF"))
        marker = request.get("cancel")
        export_project(project, output, password, progress=send,
                       cancel=Path(str(marker)) if marker else None, one_page=operation == "export-page",
                       overwrite=request.get("overwrite") is True)
        return {"kind": "exported", "path": str(output), "one_page": operation == "export-page",
                "before_bytes": project.source.stat().st_size, "after_bytes": output.stat().st_size}


def main() -> int:
    """Serve JSON-line requests until stdin closes; no Qt application or prompts."""
    stream = sys.stdout
    def send(message: dict[str, Json]) -> None:
        stream.write(f"{json.dumps(message, ensure_ascii=True, allow_nan=False)}\n")
        stream.flush()

    Image.init()
    with closing(Worker()) as worker:
        for line in sys.stdin:
            try:
                request = mapping(json.loads(line), "Request")
                with redirect_stdout(sys.stderr):
                    response = worker.run(request, send)
                send(response)
            except Cancelled as exc:
                send({"kind": "cancelled", "message": str(exc)})
            except Exception as exc:
                # Task boundary: report the error and keep the worker available.
                message = str(exc)
                code = "password" if "password" in message.lower() else "error"
                send({"kind": "error", "code": code, "message": message})
    return 0
