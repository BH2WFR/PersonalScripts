"""Shared Qt controls for the matrix viewer.

Requirements: PySide6. Usage: instantiate NoWheelComboBox instead of QComboBox
for viewer selectors; scrolling a form must not change a selected parameter.
"""

from PySide6 import QtGui, QtWidgets


class NoWheelComboBox(QtWidgets.QComboBox):
    """Keep mouse/keyboard selection but ignore wheel changes, even with focus.

    An ignored wheel event can propagate to a containing scroll area. The
    opened popup retains its normal list scrolling and click selection.
    """

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Leave the value unchanged and allow the parent to handle scrolling.

        Args:
            event: Mouse-wheel or touchpad event delivered to this selector.
        """
        event.ignore()
