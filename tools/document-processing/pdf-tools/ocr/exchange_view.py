"""Read-only HTTP bodies for the most recent image OCR API batch."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import tempfile

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_widgets import NoWheelComboBox


@dataclass
class Exchange:
    headings: dict[str, str] = field(default_factory=dict)
    error: str = ""


class ExchangeView(QtWidgets.QWidget):
    """Keep large request bodies in the image queue's private temporary directory."""

    def __init__(self, scratch: Path) -> None:
        super().__init__()
        self.scratch = scratch
        self.storage: tempfile.TemporaryDirectory | None = None
        self.entries: list[Exchange] = []
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        self.images = NoWheelComboBox()
        self.images.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.images.setMinimumContentsLength(12)
        row.addWidget(self.images, 1)
        self.direction = NoWheelComboBox()
        self.direction.addItem("Request", "request")
        self.direction.addItem("Response", "response")
        row.addWidget(self.direction)
        self.copy = QtWidgets.QPushButton("Copy raw body")
        self.copy.setEnabled(False)
        row.addWidget(self.copy)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.body = QtWidgets.QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlaceholderText("Run Vision API recognition to inspect the HTTP exchange.")
        layout.addWidget(self.body)
        self.images.currentIndexChanged.connect(self.refresh)
        self.direction.currentIndexChanged.connect(self.refresh)
        self.copy.clicked.connect(self._copy_raw)

    def reset(self) -> None:
        """Discard the previous batch before submitting new images."""
        self.entries.clear()
        self.images.clear()
        self.body.clear()
        self.status.clear()
        self.copy.setEnabled(False)
        if self.storage:
            self.storage.cleanup()
        self.storage = tempfile.TemporaryDirectory(dir=self.scratch, prefix="api-")

    def begin(self, name: str) -> None:
        """Label an HTTP exchange with the new images in its batch."""
        follow = self.images.currentIndex() == self.images.count() - 1
        self.entries.append(Exchange())
        self.images.addItem(f"{len(self.entries)}. {name}")
        if follow:
            self.images.setCurrentIndex(self.images.count() - 1)

    def _path(self, index: int, part: str) -> Path:
        assert self.storage is not None
        return Path(self.storage.name) / f"{index}-{part}.body"

    @QtCore.Slot(str, str, object)
    def record(self, part: str, heading: str, data: bytes) -> None:
        """Receive actual transport bytes on the GUI thread in submission order."""
        index = len(self.entries) - 1
        if index < 0:
            return
        try:
            self._path(index, part).write_bytes(data)
            self.entries[index].headings[part] = heading
        except OSError as exc:
            self.entries[index].error = f"Could not store API body: {exc}"
        if index == self.images.currentIndex() and part == self.direction.currentData():
            self.refresh()

    def failed(self, message: str) -> None:
        if self.entries:
            self.entries[-1].error = message
            self.refresh()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        index = self.images.currentIndex()
        if not self.isVisible() or not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        part = self.direction.currentData()
        heading = entry.headings.get(part, "")
        self.copy.setEnabled(bool(heading))
        self.status.setText("\n".join(filter(None, [heading or f"No HTTP {part} captured yet.", entry.error])))
        if not heading:
            self.body.clear()
            return
        try:
            raw = self._path(index, part).read_bytes()
            if part == "request":
                raw = re.sub(rb'(data:image/[^";]+;base64,)([a-zA-Z0-9+/=]+)',
                             lambda m: m[1] + f"[{len(m[2]):,} base64 characters; Copy raw body for full data]".encode(), raw)
            try:
                display = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
            except (ValueError, RecursionError):
                display = raw.decode("utf-8", errors="replace")
            self.body.setPlainText(display)
        except OSError as exc:
            self.body.setPlainText(str(exc))

    def _copy_raw(self) -> None:
        try:
            raw = self._path(self.images.currentIndex(), self.direction.currentData()).read_bytes()
            QtWidgets.QApplication.clipboard().setText(raw.decode("utf-8", errors="replace"))
        except OSError as exc:
            self.status.setText(str(exc))
