"""One persistent subprocess with one outstanding request and no task queue.

Uses Qt's asynchronous process I/O. The worker owns all MuPDF calls; the GUI
receives JSON messages; preview pixels use a separate shared-memory slot.
No PDF object crosses a thread boundary.
"""

import json
from pathlib import Path
import sys
import tempfile
from typing import cast

from PySide6 import QtCore
from .protocol import Json

WORKER_ARGUMENT = "--pdf-tools-worker"
MAX_STDERR_BYTES = 16_384


class JobRunner(QtCore.QObject):
    """Run at most one request; reject concurrent submissions instead of queuing.

    Args:
        entry: Source launcher, or current bundled executable in a frozen build.
        parent: Owner controlling the process lifetime.

    Signals:
        completed: Terminal result/error object; busy is already false.
        progress: Intermediate progress object; busy remains true.
        busyChanged: True on submission, False on terminal reply or process failure.
        controlChanged: Pause acknowledgement or user control state changed.
        controlStatus: Pending/acknowledged control status for the window footer.
    """

    completed = QtCore.Signal(dict)
    progress = QtCore.Signal(dict)
    busyChanged = QtCore.Signal(bool)
    controlChanged = QtCore.Signal()
    controlStatus = QtCore.Signal(str)

    def __init__(self, entry: Path, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        self.process.started.connect(self._send)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.errorOccurred.connect(self._error)
        self.process.finished.connect(self._finished)
        self.busy = False
        self._request: bytes | None = None
        self._buffer = bytearray()
        self._diagnostic = bytearray()
        self.controllable = False
        self.paused = False
        self.pause_requested = False
        self.stopping = False
        self.pause_marker: Path | None = None
        self.cancel_marker: Path | None = None
        self._controls: tempfile.TemporaryDirectory | None = None

    def start(self, request: dict[str, Json]) -> bool:
        """Submit one JSON request, returning False if work is already running."""
        if self.busy:
            return False
        request = dict(request)
        # Reject non-JSON values before allocating task controls or changing state.
        json.dumps(request, ensure_ascii=True, allow_nan=False)
        self.controllable = request.get("operation") in ("export", "export-page", "scan", "catalog", "font_file")
        if self.controllable:
            self._controls = tempfile.TemporaryDirectory(prefix="pdf-tools-control-", ignore_cleanup_errors=True)
            self.pause_marker = Path(self._controls.name) / "pause"
            self.cancel_marker = Path(self._controls.name) / "stop"
            request.update(pause=str(self.pause_marker), cancel=str(self.cancel_marker))
        self._request = f"{json.dumps(request, ensure_ascii=True, allow_nan=False)}\n".encode("utf-8")
        self._diagnostic.clear()
        self.busy = True
        self.busyChanged.emit(True)
        if self.process.state() == QtCore.QProcess.ProcessState.Running:
            self._send()
        else:
            self._buffer.clear()
            environment = QtCore.QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONUTF8", "1")
            environment.insert("PYTHONIOENCODING", "utf-8")
            self.process.setProcessEnvironment(environment)
            frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
            self.process.start(sys.executable, [WORKER_ARGUMENT] if frozen else [str(self.entry), WORKER_ARGUMENT])
        return True

    def _send(self) -> None:
        if self._request is not None:
            self.process.write(self._request)
            self._request = None

    def _read(self) -> None:
        self._buffer.extend(self.process.readAllStandardOutput().data())
        while b"\n" in self._buffer:
            line, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or "kind" not in message:
                    continue
            except (ValueError, UnicodeError):
                continue
            if message["kind"] == "progress":
                if "paused" in message:
                    self.paused = message["paused"] is True
                    self.controlChanged.emit()
                self.progress.emit(message)
                self._control_status()
            elif self.busy:
                self._complete(cast(dict[str, Json], message))

    def _stderr(self) -> None:
        self._diagnostic.extend(self.process.readAllStandardError().data())
        self._diagnostic = self._diagnostic[-MAX_STDERR_BYTES:]

    def _complete(self, message: dict[str, Json]) -> None:
        self.busy = False
        self.controllable = self.paused = self.pause_requested = self.stopping = False
        self.pause_marker = self.cancel_marker = None
        if self._controls is not None:
            self._controls.cleanup()
            self._controls = None
        self.controlChanged.emit()
        self._request = None
        self.busyChanged.emit(False)
        self.completed.emit(message)

    def _control_status(self) -> None:
        if self.stopping:
            self.controlStatus.emit("Stopping after the current step...")
        elif self.paused:
            self.controlStatus.emit("Paused. Resume or Stop." if self.pause_requested else "Resuming...")
        elif self.pause_requested:
            self.controlStatus.emit("Pausing after the current step...")

    def toggle_pause(self) -> None:
        """Request/withdraw a pause without blocking the GUI or the worker pipe."""
        if not self.busy or self.pause_marker is None or self.stopping:
            return
        try:
            if self.pause_requested:
                self.pause_marker.unlink(missing_ok=True)
                self.pause_requested = False
                self.controlStatus.emit("Resuming...")
            else:
                self.pause_marker.touch(exist_ok=False)
                self.pause_requested = True
            self.controlChanged.emit()
            self._control_status()
        except OSError as exc:
            self.controlStatus.emit(f"Cannot change pause state: {exc}")

    def stop(self) -> None:
        """Stop remains usable while the worker sleeps on a pause marker."""
        if not self.busy or self.cancel_marker is None or self.stopping:
            return
        try:
            self.cancel_marker.touch(exist_ok=False)
            self.stopping = True
            self.controlChanged.emit()
            self._control_status()
        except OSError as exc:
            self.controlStatus.emit(f"Cannot stop task: {exc}")

    def _error(self, error: QtCore.QProcess.ProcessError) -> None:
        if self.busy and error == QtCore.QProcess.ProcessError.FailedToStart:
            self._complete({"kind": "error", "message": self.process.errorString()})

    def _finished(self, exit_code: int, status: QtCore.QProcess.ExitStatus) -> None:
        self._read()
        if self.busy:
            details = self._diagnostic.decode("utf-8", errors="replace").strip()
            self._complete({"kind": "error", "message": f"PDF worker exited ({exit_code}). {details}"})

    def shutdown(self) -> None:
        """Stop an idle worker. Active exports must first finish or cancel gracefully."""
        if self.busy:
            raise RuntimeError("Wait for the active job before closing its worker.")
        self.process.closeWriteChannel()
        if not self.process.waitForFinished(1000):
            self.process.kill()
            self.process.waitForFinished(1000)
