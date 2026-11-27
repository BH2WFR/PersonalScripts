"""Notify the text processor after a paste through any Qt editor action."""

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtWidgets import QPlainTextEdit


class InputEditor(QPlainTextEdit):
    """Notify the processor after a paste through any of Qt's editor actions."""

    pasted = Signal()

    def insertFromMimeData(self, source: QMimeData) -> None:
        if self.canInsertFromMimeData(source):
            super().insertFromMimeData(source)
            self.pasted.emit()
