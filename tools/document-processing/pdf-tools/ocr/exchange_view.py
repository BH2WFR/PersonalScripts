"""Read-only HTTP exchanges shared by the images submitted in each request."""

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
from pathlib import Path
import re

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_styles import set_text_style
from utils.qt_widgets import NoWheelComboBox


@dataclass(eq=False)
class Exchange:
    number: int
    name: str
    headings: dict[str, str] = field(default_factory=dict)
    error: str = ""


class ExchangeView(QtWidgets.QWidget):
    """Keep large request bodies in the image queue's private temporary directory."""

    scratch: Path

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._by_image: dict[str | None, Exchange] = {}
        self._serial = 0
        self._active: Exchange | None = None
        self._shown: Exchange | None = None
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        self.request_name = QtWidgets.QLabel()
        self.request_name.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.request_name.setWordWrap(True)
        row.addWidget(self.request_name, 1)
        self.direction = NoWheelComboBox()
        self.direction.addItem("Request", "request")
        self.direction.addItem("Response", "response")
        self.direction.setEnabled(False)
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
        layout.addWidget(self.body)
        self.direction.currentIndexChanged.connect(self.refresh)
        self.copy.clicked.connect(self._copy_raw)

    def forget(self, keys: Iterable[str | None]) -> None:
        """Release bodies once the last image referencing a request is removed or rerun."""
        removed = {self._by_image.pop(key) for key in keys if key in self._by_image}
        for entry in removed.difference(self._by_image.values()):
            if self._active is entry:
                self._active = None
            if self._shown is entry:
                self._shown = None
                self.refresh()
            for part in entry.headings:
                self._path(entry, part).unlink(missing_ok=True)

    def begin(self, name: str, keys: Iterable[str | None]) -> None:
        """Capture one exchange for all submitted images, or None for an API test."""
        self._serial += 1
        self._active = Exchange(self._serial, name)
        self._by_image.update(dict.fromkeys(keys, self._active))

    def select_image(self, key: str | None) -> None:
        """Show the selected image's exchange. None explicitly selects the API test."""
        entry = self._by_image.get(key)
        if entry is not self._shown:
            self._shown = entry
            self.refresh()

    def _path(self, entry: Exchange, part: str) -> Path:
        return self.scratch / f"api-{entry.number}-{part}.body"

    @QtCore.Slot(str, str, object)
    def record(self, part: str, heading: str, data: bytes) -> None:
        """Receive actual transport bytes on the GUI thread in submission order."""
        entry = self._active
        if entry is None:
            return
        try:
            self._path(entry, part).write_bytes(data)
            entry.headings[part] = heading
        except OSError as exc:
            entry.error = f"Could not store API body: {exc}"
        if entry is self._shown and part == self.direction.currentData():
            self.refresh()

    def failed(self, message: str) -> None:
        if self._active is not None:
            self._active.error = message
            if self._shown is self._active:
                self.refresh()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        entry = self._shown
        self.request_name.setText(entry.name if entry else "")
        self.direction.setEnabled(entry is not None)
        if entry is None:
            self.copy.setEnabled(False)
            self.body.clear()
            self.body.setPlaceholderText("")
            self.status.clear()
            return
        if not self.isVisible():
            return
        part = self.direction.currentData()
        heading = entry.headings.get(part, "")
        self.copy.setEnabled(bool(heading))
        missing = f"No HTTP {part} captured." if entry.error else f"No HTTP {part} captured yet."
        self.body.setPlaceholderText(f"The HTTP {part} body is empty." if heading else "")
        set_text_style(self.status, "red" if entry.error else None)
        self.status.setText("\n".join(filter(None, [heading or missing, entry.error])))
        if not heading:
            self.body.clear()
            return
        try:
            raw = self._path(entry, part).read_bytes()
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
        if self._shown is None:
            return
        try:
            raw = self._path(self._shown, self.direction.currentData()).read_bytes()
            QtWidgets.QApplication.clipboard().setText(raw.decode("utf-8", errors="replace"))
        except OSError as exc:
            self.status.setText(str(exc))
