"""Matrix-specific Qt controls and shared no-wheel control imports.

Requirements: PySide6. Usage: use the NoWheel combo/spin subclasses for viewer
forms and dialogs. Wheel events propagate to scroll areas without changing a
value, even with keyboard focus; typing, arrow keys and buttons remain enabled.
OptionalIndexSpinBox displays an unselected index as blank without reserving an
integer sentinel, so cropped/negative aligned index ranges remain valid.
"""

from PySide6 import QtCore, QtWidgets
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox


class VerticalSeparator(QtWidgets.QFrame):
    """Native Fusion divider for compact horizontal control bars."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)


class OptionalIndexSpinBox(NoWheelSpinBox):
    """Keep the last index internally while displaying a blank unselected state.

    The owner controls selection via set_empty. Explicitly entering the same
    index or stepping at a bound emits selection_requested without requiring
    valueChanged. No integer value is reserved as a sentinel.
    """

    selection_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        self._empty = True
        self._edited = False
        super().__init__(parent)
        self.lineEdit().textEdited.connect(self._text_edited)
        self.editingFinished.connect(self._finish_edit)
        self.set_empty(True)

    def set_empty(self, empty: bool) -> None:
        """Show blank or the retained numeric index without changing its value."""
        self._empty = empty
        self._edited = False
        self.lineEdit().setText(self.textFromValue(self.value()))

    def textFromValue(self, value: int) -> str:
        """Preserve blank presentation across focus and index-range changes."""
        return "" if self._empty else super().textFromValue(value)

    def _text_edited(self, text: str) -> None:
        self._edited = bool(text.strip())
        if self._edited:
            self._empty = False

    def _finish_edit(self) -> None:
        if self._edited:
            self._edited = False
            self.selection_requested.emit()

    def stepBy(self, steps: int) -> None:
        """Select an index even if a step leaves the numeric value unchanged."""
        previous = self.value()
        self.set_empty(False)
        super().stepBy(steps)
        if self.value() == previous:
            self.selection_requested.emit()
