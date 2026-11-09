"""Serial MuPDF worker: inspect, rotate preview images, and export bookmarks/labels.

Page images are recognition inputs only. Export never rasterizes page content.
Existing outline destinations/actions/styles are retained unless a target changes.
"""

from contextlib import ExitStack, closing, redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import cast
from collections.abc import Callable

import pymupdf
from utils import *
from ..common.protocol import Json
from ..common.pixel_transfer import preview_reply
from ..common.task_control import Cancelled, TaskControl
from .model import Bookmark, BookSession

PREVIEW_DPI = 200
MAX_PIXELS = 12_000_000


def export_project(project: BookSession, output: Path, password: str = "", *, overwrite: bool = False,
                   control: TaskControl | None = None) -> None:
    """Write the outline and labels while preserving original page objects.

    Args:
        project: Validated in-memory book session to export.
        output: Destination PDF with an existing parent directory.
        password: In-memory input password, empty for unprotected files.
        overwrite: Explicit permission to replace an output after successful staging.
        control: Optional shared pause/stop checkpoints and save-stage progress.
    Raises:
        ValueError: Invalid session or attempt to overwrite its source.
        FileExistsError: Output exists without replacement permission.
        OSError: Reading, saving or publishing the PDF fails.
    Writes a decrypted PDF; failed staged saves retain the previous output.
    """
    control = control or TaskControl()
    control.checkpoint()
    project.validate_export()
    with Pdf.open_document(project.source, password=password, interactive=False) as (document, _):
        if document.page_count != project.source_page_count:
            raise ValueError("The PDF page count no longer matches this project.")
        retained = set(project.source_pages)
        removed = [index for index in range(document.page_count) if index + 1 not in retained]
        if removed:
            # MuPDF disables deleted-page destinations and grays their outlines.
            # Preserve styles for bookmarks the user elects to retarget instead.
            styles = {entry.original_xref: {
                key: document.xref_get_key(entry.original_xref, key)[1] for key in ("C", "F", "Count")
            } for entry in project.bookmarks if entry.original_xref is not None}
            document.delete_pages(removed)
            for xref, values in styles.items():
                for key, value in values.items():
                    document.xref_set_key(xref, key, value)
        control.checkpoint()
        Pdf.write_bookmarks(document, [
            PdfBookmark(entry.title, entry.page, entry.level, entry.original_xref)
            for entry in project.bookmarks
        ])
        control.checkpoint()
        Pdf.write_page_labels(document, project.labels)
        control.save(document, output, project.source, overwrite=overwrite)


class Worker:
    """Own one authenticated read-only input across serial preview requests."""

    def __init__(self, progress: Callable[[dict[str, Json]], None] | None = None) -> None:
        self._inputs = ExitStack()
        self._source: pymupdf.Document | None = None
        self._identity: tuple[str, int, int, str] | None = None
        self.password = ""
        self.progress = progress

    def close(self) -> None:
        """Release the retained read-only source."""
        self._inputs.close()
        self._source = None
        self._identity = None

    def run(self, request: dict[str, Json]) -> dict[str, Json]:
        """Process one inspect, preview or export request; report errors to the caller."""
        control = TaskControl.from_request(request, self.progress)
        control.checkpoint()
        path = Path(str(request["path"]))
        password = str(request.get("password", ""))
        stat = path.stat()
        identity = (str(path), stat.st_mtime_ns, stat.st_size, password)
        if self._source is None or self._identity != identity:
            self.close()
            self._source, self.password = self._inputs.enter_context(Pdf.open_document(path, password=password, interactive=False))
            self._identity = identity
        source = self._source
        assert source is not None
        operation = request["operation"]
        if operation == "inspect":
            if source.page_count < 1:
                raise ValueError("The PDF has no pages.")
            entries = [asdict(Bookmark(entry.title, entry.page, entry.level, original_xref=entry.original_xref))
                       for entry in Pdf.read_bookmarks(source)]
            return cast(dict[str, Json], {"kind": "opened", "page_count": source.page_count,
                    "labels": Pdf.read_page_labels(source), "bookmarks": entries, "password": self.password})
        if operation == "preview":
            page_number = int(cast(int, request["page"]))
            source_page = request.get("source_page", page_number)
            if type(source_page) is not int or not 1 <= source_page <= source.page_count:
                raise ValueError("Preview source page is outside the PDF.")
            page = source[source_page - 1]
            angle = float(cast(float, request.get("angle", 0)))
            pixmap = Pdf.render_page(page, dpi=PREVIEW_DPI, max_pixels=MAX_PIXELS)
            pixmap = Pdf.rotate_pixmap(pixmap, angle)
            return preview_reply({"kind": "preview", "page": page_number, "angle": angle,
                                  "width": pixmap.width, "height": pixmap.height},
                                 pixmap.samples if request.get("pixel_buffer") else pixmap.tobytes("png"), request)
        if operation == "export":
            project = BookSession.from_data(cast(dict[str, object], request["session"]), Path.cwd())
            export_project(project, Path(str(request["output"])), password,
                           overwrite=request.get("overwrite") is True, control=control)
            return {"kind": "exported", "path": request["output"]}
        raise ValueError(f"Unknown operation: {operation}")


def main() -> int:
    """Serve JSON-line requests on the worker main thread until stdin closes."""
    stream = sys.stdout
    def send(message: dict[str, Json]) -> None:
        stream.write(f"{json.dumps(message, ensure_ascii=True)}\n")
        stream.flush()

    with closing(Worker(send)) as worker:
        for line in sys.stdin:
            try:
                with redirect_stdout(sys.stderr):
                    reply: dict[str, Json] = worker.run(json.loads(line))
            except Cancelled as exc:
                reply = {"kind": "cancelled", "message": str(exc)}
            except Exception as exc:
                reply = {"kind": "error", "message": str(exc),
                         "code": "password" if "password" in str(exc).lower() else "error"}
            send(reply)
    return 0
