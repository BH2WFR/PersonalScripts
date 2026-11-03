"""Optional bookmark editing with reusable tree rows, navigation and subtree moves.

The host owns PDF meaning and persistence; this widget emits edited rows. The
default is read-only, so other tools need not expose editing functionality.
"""

from dataclasses import dataclass
from collections.abc import Callable
from uuid import uuid4
from PySide6 import QtCore, QtWidgets

IDENTITY_ROLE = QtCore.Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class OutlineRow:
    """One physical target page and hierarchy level with a host-owned stable ID."""

    id: str
    title: str
    page: int
    level: int


class BookmarkEditor(QtWidgets.QWidget):
    """Display/edit bookmark titles, targets, order and hierarchy without PDF I/O."""

    changed = QtCore.Signal(list)
    pageRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, editable: bool = False,
                 current_page: Callable[[], int] | None = None) -> None:
        super().__init__(parent)
        self.editable = editable
        self._current_page = current_page or (lambda: 1)
        self._loading = False
        self._pending_page = 0
        self._navigation_timer = QtCore.QTimer(self)
        self._navigation_timer.setSingleShot(True)
        self._navigation_timer.timeout.connect(lambda: self.pageRequested.emit(self._pending_page))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Bookmark", "PDF page"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemChanged.connect(self._edited)
        self.tree.itemClicked.connect(self._navigate)
        self.tree.itemDoubleClicked.connect(lambda *_args: self._navigation_timer.stop())
        if editable:
            self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._context_menu)
            toolbar = QtWidgets.QToolBar()
            for text, tip, callback in (("+", "Add after selection", self._add), ("−", "Delete selected subtree", self._delete),
                                       ("↑", "Move subtree up", lambda: self._move(-1)), ("↓", "Move subtree down", lambda: self._move(1)),
                                       ("→", "Indent under previous sibling", self._indent),
                                       ("←", "Outdent, keeping reading order", lambda: self._outdent())):
                action = toolbar.addAction(text)
                action.setToolTip(tip)
                action.triggered.connect(callback)
            layout.addWidget(toolbar)
            self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                                      | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        layout.addWidget(self.tree)

    def load(self, rows: list[OutlineRow]) -> None:
        """Replace displayed rows without emitting edits; preserve the selected ID."""
        selected = self.tree.currentItem()
        identity = selected.data(0, IDENTITY_ROLE) if selected else None
        self._loading = True
        self._navigation_timer.stop()
        self.tree.clear()
        parents: list[QtWidgets.QTreeWidgetItem] = []
        for row in rows:
            item = self._item(row)
            parents = parents[:max(0, row.level - 1)]
            (parents[-1].addChild(item) if parents else self.tree.addTopLevelItem(item))
            parents.append(item)
            if row.id == identity:
                self.tree.setCurrentItem(item)
        self.tree.expandAll()
        self._loading = False

    def _item(self, row: OutlineRow) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([row.title, str(row.page)])
        item.setData(0, IDENTITY_ROLE, row.id)
        if self.editable:
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        return item

    def rows(self) -> list[OutlineRow]:
        """Return depth-first rows, raising ValueError for invalid target text."""
        result: list[OutlineRow] = []
        def visit(parent: QtWidgets.QTreeWidgetItem, level: int) -> None:
            for i in range(parent.childCount()):
                item = parent.child(i)
                page = int(item.text(1))
                title = item.text(0).strip()
                if not title:
                    raise ValueError("Bookmark titles cannot be empty.")
                result.append(OutlineRow(str(item.data(0, IDENTITY_ROLE)), title, page, level))
                visit(item, level + 1)
        visit(self.tree.invisibleRootItem(), 1)
        return result

    def _edited(self, *_args: object) -> None:
        if self._loading or not self.editable:
            return
        try:
            rows = self.rows()
        except ValueError:
            self.tree.setToolTip("Enter a nonempty title and an integer physical PDF page.")
            return
        self.tree.setToolTip("Ctrl+click or right-click selects without jumping. Double-click edits. Right-click offers both outdent modes.")
        self.changed.emit(rows)

    def _navigate(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        self._navigation_timer.stop()
        if self.editable and QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            return
        try:
            page = int(item.text(1))
        except ValueError:
            return
        if page > 0:
            if self.editable:
                self._pending_page = page - 1
                self._navigation_timer.start(QtWidgets.QApplication.doubleClickInterval())
            else:
                self.pageRequested.emit(page - 1)

    def _add(self) -> None:
        self._navigation_timer.stop()
        selected = self.tree.currentItem()
        parent = (selected.parent() or self.tree.invisibleRootItem()) if selected else self.tree.invisibleRootItem()
        index = parent.indexOfChild(selected) + 1 if selected else parent.childCount()
        item = self._item(OutlineRow(uuid4().hex, "New bookmark", self._current_page(), 1))
        parent.insertChild(index, item)
        self.tree.setCurrentItem(item)
        self._edited()
        self.tree.editItem(item, 0)

    def _delete(self) -> None:
        self._navigation_timer.stop()
        item = self.tree.currentItem()
        if item is not None:
            parent = item.parent() or self.tree.invisibleRootItem()
            parent.takeChild(parent.indexOfChild(item))
            self._edited()

    def _move(self, delta: int) -> None:
        self._navigation_timer.stop()
        item = self.tree.currentItem()
        if item is None:
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        if 0 <= index + delta < parent.childCount():
            parent.takeChild(index)
            parent.insertChild(index + delta, item)
            self.tree.setCurrentItem(item)
            self._edited()

    def _indent(self) -> None:
        self._navigation_timer.stop()
        item = self.tree.currentItem()
        if item is None:
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        if index > 0:
            target = parent.child(index - 1)
            parent.takeChild(index)
            target.addChild(item)
            target.setExpanded(True)
            self.tree.setCurrentItem(item)
            self._edited()

    def _outdent(self, keep_order: bool = True) -> None:
        self._navigation_timer.stop()
        item = self.tree.currentItem()
        if item is None or item.parent() is None:
            return
        parent = item.parent()
        assert parent is not None
        grandparent = parent.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        # Keep depth-first reading order: following siblings retain their level
        # by becoming children of the promoted item, after its existing children.
        trailing = []
        while keep_order and parent.childCount() > index + 1:
            trailing.append(parent.takeChild(index + 1))
        parent.takeChild(index)
        for sibling in trailing:
            item.addChild(sibling)
        grandparent.insertChild(grandparent.indexOfChild(parent) + 1, item)
        item.setExpanded(True)
        self.tree.setCurrentItem(item)
        self._edited()

    def _context_menu(self, point: QtCore.QPoint) -> None:
        self._navigation_timer.stop()
        item = self.tree.itemAt(point)
        self.tree.setCurrentItem(item)
        menu = self._make_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _make_context_menu(self, item: QtWidgets.QTreeWidgetItem | None) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.addAction("Add bookmark at current page", self._add)
        if item is not None:
            menu.addAction("Go to bookmark", lambda: self._go_selected(item))
            menu.addAction("Set target to current page", lambda: item.setText(1, str(self._current_page())))
            menu.addSeparator()
            menu.addAction("Rename", lambda: self.tree.editItem(item, 0))
            menu.addAction("Edit target page", lambda: self.tree.editItem(item, 1))
            menu.addAction("Move up", lambda: self._move(-1))
            menu.addAction("Move down", lambda: self._move(1))
            menu.addAction("Indent", self._indent)
            menu.addAction("Outdent (keep order)", lambda: self._outdent())
            menu.addAction("Outdent (move below parent)", lambda: self._outdent(False))
            menu.addSeparator()
            menu.addAction("Delete subtree", self._delete)
        return menu

    def _go_selected(self, item: QtWidgets.QTreeWidgetItem) -> None:
        try:
            page = int(item.text(1))
        except ValueError:
            return
        if page > 0:
            self.pageRequested.emit(page - 1)
