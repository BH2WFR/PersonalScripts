"""Shared Qt controls for the matrix viewer.

Requirements: PySide6. Usage: use the NoWheel combo/spin subclasses for viewer
forms and dialogs. Wheel events propagate to scroll areas without changing a
value, even with keyboard focus; typing, arrow keys and buttons remain enabled.
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


class NoWheelSpinBox(QtWidgets.QSpinBox):
    """Integer input that leaves wheel scrolling to its containing widget."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel event without modifying the integer value."""
        event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Floating-point input that leaves wheel scrolling to its container."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel event without modifying the numeric value."""
        event.ignore()
