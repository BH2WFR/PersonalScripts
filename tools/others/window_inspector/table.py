"""Property and argument columns fill spare width and scroll for long values."""

from PySide6.QtWidgets import QTreeWidget


class ValueTable(QTreeWidget):
    """Fit the value column to the viewport or its widest content."""

    def sizeHintForColumn(self, column: int) -> int:
        content_width = super().sizeHintForColumn(column)
        if column == 1:
            return max(content_width, self.viewport().width() - self.columnWidth(0))
        return content_width
