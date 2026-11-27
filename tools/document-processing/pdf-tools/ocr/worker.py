"""Serial OCR worker with reusable page results and additive PDF export."""

from collections.abc import Callable
from contextlib import ExitStack, closing, redirect_stdout
import json
from pathlib import Path
import sys
from typing import cast

import pymupdf
from utils import Pdf, Input
from ..common.pixel_transfer import preview_reply
from ..common.protocol import Json
from ..common.task_control import Cancelled, TaskControl
from .backend import Recognizer
from .engine import TextLayer, recognition_image
from .model import Result, Settings, adjusted_result
from . import models


class Worker:
    """Keep the source read-only and cache only results for the current OCR settings."""

    def __init__(self, progress: Callable[[dict[str, Json]], None] | None = None) -> None:
        self.progress = progress or (lambda message: None)
        self.inputs = ExitStack()
        self.source: pymupdf.Document | None = None
        self.identity: tuple[str, int, int, str] | None = None
        self.password = ""
        self.settings: Settings | None = None
        self.recognizer: Recognizer | None = None
        self.results: dict[int, Result] = {}
        self.control = TaskControl()

    def close(self) -> None:
        """Release source handles, models and cached recognition."""
        self.inputs.close()
        self.source = None
        self.identity = None
        self.results.clear()
        self.recognizer = None
        self.settings = None

    def recognize(self, index: int) -> Result:
        """Reuse a completed page, or recognize it once with the current settings."""
        self.control.checkpoint()
        if index not in self.results:
            assert self.source is not None and self.settings is not None
            self.progress({"kind": "progress", "stage": f"Recognizing page {index + 1}..."})
            if self.recognizer is None:
                self.recognizer = Recognizer(self.settings, self.control.checkpoint)
            pixels = recognition_image(self.source[index], self.settings)
            result = self.recognizer.recognize(pixels, self.control.checkpoint)
            self.results[index] = result
        return self.results[index]

    def run(self, request: dict[str, Json]) -> dict[str, Json]:
        """Handle inspect/preview/scan/export requests; only export writes a PDF."""
        self.control = TaskControl.from_request(request, self.progress)
        self.control.checkpoint()
        operation = request["operation"]
        if str(operation).startswith("model-"):
            action = str(operation).removeprefix("model-")
            if request.get("formula_models"):
                from .local_formula import manage
                manage(action, self.control)
                return {"kind": "models", "action": action}
            if action != "list":
                model = models.catalog()[str(request["model"])]
                if action in ("download", "delete"):
                    self.recognizer = None  # Release Windows model handles first.
                if action == "download":
                    models.download(model, self.control)
                elif action == "delete":
                    models.delete(model)
                elif action == "verify":
                    models.verify(model, self.control)
                else:
                    raise ValueError(f"Unknown model action: {action}")
                # Results remain valid: downloaded files must have the same official
                # digest. Deleting a model does not erase already recognized pages.
            return cast(dict[str, Json], {"kind": "models", "action": action,
                "rows": models.inventory(), "directory": str(models.cache_directory())})
        if operation == "vision-image":
            from io import BytesIO
            from utils import Llm
            from .image_batch import image_rgb
            with BytesIO() as stream, image_rgb(Path(str(request["path"]))) as pixels:
                pixels.save(stream, format="PNG")
                image = Llm.image_content(stream.getvalue(), mime_type="image/png")
                return {"kind": "vision-image", "image": cast(dict[str, Json], image)}
        if operation == "scan" and "images" in request:
            if request.get("local_formula"):
                from .local_formula import recognizer
                from .image_batch import scan_batch
                recognize = recognizer(self.control, bool(request.get("brackets")))
                return scan_batch(cast(list[str], request["images"]), recognize, self.control)
            from .image_batch import scan_images
            settings = Settings.from_data(cast(dict, request["settings"]))
            if self.settings != settings or self.recognizer is None:
                self.recognizer = Recognizer(settings, self.control.checkpoint)
                self.settings = settings
            return scan_images(cast(list[str], request["images"]), settings, self.recognizer, self.control)
        path = Path(str(request["path"]))
        password = str(request.get("password", ""))
        stat = path.stat()
        identity = (str(path.resolve()), stat.st_mtime_ns, stat.st_size, password)
        if self.identity != identity:
            self.close()
            self.source, self.password = self.inputs.enter_context(
                Pdf.open_document(path, password=password, interactive=False))
            self.identity = identity
        source = self.source
        assert source is not None
        if not source.page_count:
            raise ValueError("The PDF has no pages.")
        if operation == "inspect":
            return cast(dict[str, Json], {"kind": "opened", "page_count": source.page_count,
                "labels": Pdf.read_page_labels(source), "bookmarks": source.get_toc(), "password": self.password})
        settings = Settings.from_data(cast(dict, request.get("settings", {})))
        if self.settings is None or settings.for_recognition() != self.settings.for_recognition():
            self.results.clear()
            self.recognizer = None
        self.settings = settings
        number = int(cast(int, request.get("page", 1)))
        if not 1 <= number <= source.page_count:
            raise ValueError("Page number is outside this PDF.")
        if operation == "preview":
            pixmap = Pdf.render_page(source[number - 1])
            return preview_reply({"kind": "preview", "page": number,
                "width": pixmap.width, "height": pixmap.height},
                pixmap.samples if request.get("pixel_buffer") else pixmap.tobytes("png"), request)
        ignored = set(Input.parse_index_ranges(str(request.get("ignored", "none")) or "none", item_count=source.page_count))
        if operation == "scan":
            if number - 1 in ignored:
                raise ValueError("This page is ignored. Include it before running OCR.")
            result = self.recognize(number - 1)
            return {"kind": "recognized", "page": number, "result": result.to_data()}
        if operation == "export":
            output = Path(str(request["output"]))
            if output.resolve() == path.resolve() or (output.exists() and output.samefile(path)):
                raise FileExistsError("The source PDF cannot be overwritten.")
            if output.exists() and request.get("overwrite") is not True:
                raise FileExistsError(f"Output already exists: {output}")
            pages = [index for index in range(source.page_count) if index not in ignored]
            for done, index in enumerate(pages, 1):
                result = self.recognize(index)
                self.progress({"kind": "progress", "page": index + 1, "result": result.to_data(),
                               "done": done, "total": len(pages)})
            self.control.checkpoint()
            self.progress({"kind": "progress", "stage": "Building the invisible text layer..."})
            results = [self.results[index] for index in pages]
            layer = TextLayer(results) if any(result.tokens for result in results) else None
            self.control.checkpoint()
            count = 0
            with Pdf.open_document(path, password=self.password, interactive=False) as (document, _):
                # A changed input must never receive stale recognition coordinates.
                current = path.stat()
                if (current.st_mtime_ns, current.st_size) != (stat.st_mtime_ns, stat.st_size):
                    raise ValueError("The source PDF changed during recognition. Reopen it and retry.")
                if layer is not None:
                    for index in pages:
                        count += layer.write(document[index], adjusted_result(self.results[index], settings), self.control.checkpoint)
                self.control.save(document, output, path, compact=False, overwrite=request.get("overwrite") is True)
            return {"kind": "exported", "path": str(output), "count": count, "pages": len(pages)}
        raise ValueError(f"Unknown operation: {operation}")


def main() -> int:
    """Serve JSON lines, keeping inference diagnostics off the protocol stream."""
    stream = sys.stdout

    def send(message: dict[str, Json]) -> None:
        stream.write(json.dumps(message, ensure_ascii=True, allow_nan=False) + "\n")
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
