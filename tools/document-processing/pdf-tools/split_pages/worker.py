"""Single-process PDF inspection, original-page previews and crop export."""

from collections.abc import Callable
from contextlib import ExitStack, closing, redirect_stdout
import json
from pathlib import Path
import sys
from typing import cast

import pymupdf
from utils import *
from ..common.pixel_transfer import preview_reply
from ..common.protocol import Json
from ..common.task_control import Cancelled, TaskControl
from .engine import build_plan, _split_document
from .model import Settings, PageOverride


class Worker:
    """Own a read-only authenticated source; PDF calls stay on this process's main thread."""

    def __init__(self, progress: Callable[[dict[str, Json]], None] | None = None) -> None:
        self._inputs = ExitStack()
        self._source: pymupdf.Document | None = None
        self._identity: tuple[str, int, int, str] | None = None
        self.password = ""
        self.progress = progress
        self.control = TaskControl()

    def close(self) -> None:
        """Release source handles and authentication state; never write the input."""
        self._inputs.close()
        self._source = None
        self._identity = None

    def _progress(self, done: int, total: int) -> None:
        if self.progress is not None:
            self.progress({"kind": "progress", "done": done, "total": total})
        self.control.checkpoint()

    def run(self, request: dict[str, Json]) -> dict[str, Json]:
        """Execute inspect, preview or export with one-based physical page numbers.

        Args:
            request: JSON values containing path/password and operation-specific settings.
        Returns:
            JSON reply; previews use the caller's shared RGB buffer or encoded PNG.
        Raises:
            ValueError, OSError: Invalid settings, authentication or file operations.
        Only export writes a new or explicitly replaceable output through Pdf.save_new.
        """
        self.control = TaskControl.from_request(request, self.progress)
        self.control.checkpoint()
        path = Path(str(request["path"]))
        password = str(request.get("password", ""))
        stat = path.stat()
        identity = (str(path), stat.st_mtime_ns, stat.st_size, password)
        if self._source is None or self._identity != identity:
            self.close()
            self._source, self.password = self._inputs.enter_context(
                Pdf.open_document(path, password=password, interactive=False))
            self._identity = identity
        source = self._source
        assert source is not None
        if not source.page_count:
            raise ValueError("The PDF has no pages.")
        operation = request["operation"]
        if operation == "inspect":
            return cast(dict[str, Json], {"kind": "opened", "page_count": source.page_count,
                "labels": Pdf.read_page_labels(source), "bookmarks": source.get_toc(), "password": self.password})
        if operation == "preview":
            number = int(cast(int, request["page"]))
            if not 1 <= number <= source.page_count:
                raise ValueError("Page is outside the PDF.")
            page = source[number - 1]
            pixmap = Pdf.render_page(page)
            return preview_reply({"kind": "preview", "page": number, "width": pixmap.width,
                "height": pixmap.height, "page_width": page.rect.width, "page_height": page.rect.height},
                pixmap.samples if request.get("pixel_buffer") else pixmap.tobytes("png"), request)
        if operation == "export":
            output_path = Path(str(request["output"]))
            if output_path.resolve() == path.resolve() or (output_path.exists() and output_path.samefile(path)):
                raise ValueError("The source PDF cannot be overwritten.")
            if source.page_count != request["page_count"]:
                raise ValueError("The source page count changed. Reopen the PDF before exporting.")
            settings = Settings.from_data(cast(dict[str, Json], request["settings"]))
            overrides = {int(key): PageOverride.from_data(cast(dict[str, Json], value))
                         for key, value in cast(dict[str, Json], request.get("overrides", {})).items()}
            plan = build_plan(source, settings, overrides)
            with pymupdf.open() as output:
                ambiguous, skipped = _split_document(source, output, plan, on_progress=self._progress)
                count = output.page_count
                self.control.save(output, output_path, path, overwrite=request.get("overwrite") is True)
            return {"kind": "exported", "path": str(output_path), "page_count": count,
                    "ambiguous": ambiguous, "skipped_links": skipped}
        raise ValueError(f"Unknown operation: {operation}")


def main() -> int:
    """Serve serial JSON lines; stdout carries protocol replies only, never diagnostics."""
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
