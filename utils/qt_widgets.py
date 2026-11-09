"""Shared PySide6 controls that reserve the wheel for scrolling, not value edits.

GUI modules import this module explicitly; the utils facade stays Qt-free.
Use NoWheelComboBox, NoWheelSpinBox and NoWheelDoubleSpinBox for forms, then
install_no_wheel_controls(application) once to cover Qt-created dialog editors.
Keyboard editing, arrow buttons and open combo-popup scrolling remain available.
Requires PySide6, already a project GUI dependency.
"""

from PySide6 import QtCore, QtGui, QtWidgets


class NoWheelComboBox(QtWidgets.QComboBox):
    """Ignore wheel changes even with focus; retain popup and keyboard selection."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Leave the selection unchanged and let the parent handle scrolling."""
        event.ignore()


class NoWheelSpinBox(QtWidgets.QSpinBox):
    """Integer input that leaves wheel scrolling to its containing widget."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel without modifying the integer value."""
        event.ignore()


class NoWheelDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Floating-point input that leaves wheel scrolling to its container."""

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Ignore the wheel without modifying the numeric value."""
        event.ignore()


class _NoWheelFilter(QtCore.QObject):
    """Cover native dialogs and editable fields, without blocking popup lists."""

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.Wheel:
            return False
        control = watched.parent() if isinstance(watched, QtWidgets.QLineEdit) else watched
        if isinstance(control, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
            event.ignore()
            return True
        return False


def install_no_wheel_controls(application: QtWidgets.QApplication) -> None:
    """Enforce no-wheel value editing, including controls made by QInputDialog.

    Args:
        application: Existing GUI application; owns the filter until shutdown.
    Returns:
        None. Repeated installation on the same application is harmless.
    Side effects:
        Installs an application event filter. Wheel events over combo/spin
        editors are ignored so ancestor scroll areas can handle them. Does not
        change Qt classes, keyboard/mouse-click behavior or popup-list scrolling.
    """
    if application.findChild(_NoWheelFilter) is None:
        application.installEventFilter(_NoWheelFilter(application))
