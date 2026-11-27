"""Designer widgets for drag-reordering mappings and choosing physical keys."""

from PySide6 import QtCore, QtGui, QtWidgets

from .capture import CaptureDialog
from .catalog import choices, key_label, parse_key
from .ui_key_picker import Ui_KeyPicker


class MappingTable(QtWidgets.QTableWidget):
    """Request whole-row moves within this table without Qt moving cell data.

    The owning window updates the authoritative draft through move_requested.
    External drops and copy operations are rejected; cancellation changes nothing.
    """

    move_requested = QtCore.Signal(int, int)
    MIME_TYPE = "application/x-personal-keyboard-remap-row"
    INSERTION_COLOR = "#2878d0"

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_row: int | None = None
        self._insertion: int | None = None
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(False)  # Paint a full-width insertion line.
        self.setDragDropOverwriteMode(False)

    def startDrag(self, supportedActions: QtCore.Qt.DropAction) -> None:
        """Start a move-only drag; the drop handler alone requests draft changes."""
        if not self.dragEnabled() or self.currentRow() < 0:
            return
        self._drag_row = self.currentRow()
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(self.MIME_TYPE, b"row")
        drag.setMimeData(mime)
        try:
            drag.exec(QtCore.Qt.DropAction.MoveAction)
        finally:
            self._drag_row = None
            self._insertion = None
            self.viewport().update()
            drag.deleteLater()

    def _accepts(self, event: QtGui.QDropEvent) -> bool:
        return (self.dragEnabled() and event.source() is self and self._drag_row is not None
                and event.mimeData().hasFormat(self.MIME_TYPE)
                and bool(event.possibleActions() & QtCore.Qt.DropAction.MoveAction))

    def _slot_at(self, point: QtCore.QPoint) -> int:
        row = self.rowAt(point.y())
        if row < 0:
            return 0 if point.y() < 0 else self.rowCount()
        return row + int(point.y() >= self.rowViewportPosition(row) + self.rowHeight(row) / 2)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept only a move originating from this table's active drag."""
        self.dragMoveEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        """Update the insertion marker without changing any mappings."""
        if self._accepts(event):
            self._insertion = self._slot_at(event.position().toPoint())
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            self._insertion = None
            event.ignore()
        self.viewport().update()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        """Hide the insertion marker when the pointer leaves the table."""
        self._insertion = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Emit one source-row/insertion-slot request; never overwrite cells."""
        if self._accepts(event) and self._drag_row is not None:
            self.move_requested.emit(self._drag_row, self._slot_at(event.position().toPoint()))
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()
        self._insertion = None
        self.viewport().update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Draw the table and a high-contrast, full-width insertion marker."""
        super().paintEvent(event)
        if self._insertion is None:
            return
        slot = self._insertion
        y = (self.rowViewportPosition(slot) if slot < self.rowCount() else
             self.rowViewportPosition(slot - 1) + self.rowHeight(slot - 1) if slot else 0)
        painter = QtGui.QPainter(self.viewport())
        painter.setPen(QtGui.QPen(QtGui.QColor(self.INSERTION_COLOR), 2))
        painter.drawLine(0, max(1, y), self.viewport().width(), max(1, y))
        painter.end()


class KeyPicker(QtWidgets.QWidget, Ui_KeyPicker):
    """Editable scan-code dropdown with an independent visible capture action.

    Args:
        allow_disable: Include a target-only Disable option (scan word zero).
        parent: Owning mapping dialog.
    """

    def __init__(self, allow_disable: bool, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.allow_disable = allow_disable
        self.setupUi(self)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.combo.setMaxVisibleItems(18)
        if allow_disable:
            self.combo.addItem(key_label(0), 0)
        for item in choices():
            self.combo.addItem(item.label, item.code)
        completer = self.combo.completer()
        if completer is not None:
            completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.combo.setCurrentIndex(-1)
        edit = self.combo.lineEdit()
        if edit is not None:
            edit.setPlaceholderText("Search key name / scan code, or enter 0xE01D")
        self.capture_button.clicked.connect(self._capture)

    def code(self) -> int:
        """Return the selected/input word, rejecting blank and disabled source keys.

        Raises:
            ValueError: Input is unrecognized or source zero was requested.
        """
        index = self.combo.currentIndex()
        if index >= 0 and self.combo.currentText() == self.combo.itemText(index):
            value = int(self.combo.itemData(index))
        else:
            value = parse_key(self.combo.currentText())
        if value == 0 and not self.allow_disable:
            raise ValueError("A source key cannot be 0x0000 (Disable).")
        return value

    def set_code(self, code: int) -> None:
        """Select a code, retaining unknown words as explicit custom entries."""
        index = self.combo.findData(code)
        if index < 0:
            self.combo.addItem(key_label(code), code)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)

    def _capture(self) -> None:
        dialog = CaptureDialog(self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.result_key is not None:
            self.set_code(dialog.result_key.code)


class SourceKeyPicker(KeyPicker):
    """Select a physical source key for the mapping."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(False, parent)


class TargetKeyPicker(KeyPicker):
    """Include Disable among the replacement choices."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(True, parent)
