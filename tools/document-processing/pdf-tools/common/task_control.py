"""Cooperative PDF task control and staged publication, without Qt dependencies."""

from collections.abc import Callable
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING

from utils import *
from .protocol import Json

if TYPE_CHECKING:
    import pymupdf


class Cancelled(RuntimeError):
    """A task stopped at a safe boundary before publishing its result."""


class TaskControl:
    """Wait on task-private pause markers; Stop always wins over Pause."""

    def __init__(self, cancel: Path | None = None, pause: Path | None = None,
                 progress: Callable[[dict[str, Json]], None] | None = None) -> None:
        self.cancel, self.pause = cancel, pause
        self.progress = progress or (lambda message: None)

    @classmethod
    def from_request(cls, request: dict[str, Json], progress: Callable[[dict[str, Json]], None] | None = None) -> "TaskControl":
        return cls(Path(str(request["cancel"])) if request.get("cancel") else None,
                   Path(str(request["pause"])) if request.get("pause") else None, progress)

    def checkpoint(self) -> None:
        def check_stop() -> None:
            if self.cancel is not None and self.cancel.exists():
                raise Cancelled("Task cancelled.")
        check_stop()
        if self.pause is None or not self.pause.exists():
            return
        self.progress({"kind": "progress", "paused": True, "stage": "Paused. Resume or Stop."})
        while self.pause.exists():
            check_stop()
            time.sleep(.1)
        check_stop()
        self.progress({"kind": "progress", "paused": False, "stage": "Resuming..."})

    def save(self, document: "pymupdf.Document", output: Path, source: Path, *,
             compact: bool = True, overwrite: bool = False) -> None:
        """Save privately, check Stop after MuPDF returns, then publish safely."""
        if output.resolve() == source.resolve() or (output.exists() and output.samefile(source)):
            raise FileExistsError("The source PDF cannot be overwritten.")
        if output.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {output}")
        self.checkpoint()
        with tempfile.TemporaryDirectory(prefix=".pdf-tools-", dir=output.parent) as directory:
            staged = Path(directory) / "result.pdf"
            self.progress({"kind": "progress", "stage": "Writing PDF..."})
            self.checkpoint()
            Pdf.save_new(document, staged, compact=compact)
            publish(staged, output, self.cancel, overwrite, self.checkpoint)


def publish(staged: Path, output: Path, cancel: Path | None, overwrite: bool = False,
            checkpoint: Callable[[], None] | None = None) -> None:
    """Keep old outputs until a completed stage can be atomically substituted."""
    check = checkpoint or TaskControl(cancel).checkpoint
    check()
    if overwrite:
        staged.replace(output)
        return
    with output.open("xb") as destination:
        try:
            with staged.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    check()
                    destination.write(chunk)
                check()
        except BaseException:
            destination.close()
            output.unlink(missing_ok=True)
            raise
