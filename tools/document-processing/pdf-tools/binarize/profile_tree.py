"""Profile list that leaves the active assignment untouched on a context click."""

from PySide6 import QtCore, QtGui, QtWidgets


class ProfileTree(QtWidgets.QTreeWidget):
    """Two-column profile list; right-click actions do not assign a profile."""

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)
