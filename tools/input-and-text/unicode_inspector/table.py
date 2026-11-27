"""Character table navigation and interactive column sizing."""

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QResizeEvent
from PySide6.QtWidgets import QTableView

from utils import UnicodeText


class CharacterTable(QTableView):
    """Keep columns draggable and share spare width among the three text columns."""

    copyRequested = Signal()
    FLEX_COLUMNS = (1, 5, 6)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copyRequested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        header = self.horizontalHeader()
        if header.count() != len(UnicodeText.COLUMNS):
            return
        remaining = self.viewport().width() - header.length()
        for i, column in enumerate(self.FLEX_COLUMNS):
            width = header.sectionSize(column)
            target = max(header.minimumSectionSize(), width + round(remaining / (len(self.FLEX_COLUMNS) - i)))
            header.resizeSection(column, target)
            remaining -= target - width
