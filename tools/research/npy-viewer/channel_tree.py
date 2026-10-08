"""Native Qt channel tree distinguishing checkbox clicks from row activation.

Requirements: PySide6. Usage: embedded by WorkspaceWindow. No custom widget theme.
"""

from typing import Protocol, cast

from PySide6 import QtCore, QtGui, QtWidgets


class _ViewItemOptionFields(Protocol):
    """Native view-item fields omitted by some PySide6 stub versions."""

    rect: QtCore.QRect
    features: QtWidgets.QStyleOptionViewItem.ViewItemFeature
    checkState: QtCore.Qt.CheckState


class ChannelTree(QtWidgets.QTreeWidget):
    """Expose whether the current mouse click targeted a native check indicator."""

    checkbox_click: bool = False

    def check_rect(self, item: QtWidgets.QTreeWidgetItem) -> QtCore.QRect:
        """Return the native checkbox rectangle, or an empty rectangle for groups."""
        if not item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
            return QtCore.QRect()
        option = QtWidgets.QStyleOptionViewItem()
        self.initViewItemOption(option)
        fields = cast(_ViewItemOptionFields, option)
        fields.rect = self.visualItemRect(item)
        # visualItemRect starts after the branch indentation, like the delegate.
        fields.features |= QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        fields.checkState = item.checkState(0)
        return self.style().subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        self.checkbox_click = bool(item is not None and self.columnAt(int(event.position().x())) == 0
                                   and self.check_rect(item).contains(event.position().toPoint()))
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        item = self.currentItem()
        self.checkbox_click = bool(event.key() == QtCore.Qt.Key.Key_Space and item is not None
                                   and item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        super().keyPressEvent(event)
