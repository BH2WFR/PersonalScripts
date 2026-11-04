"""Optional bookmark editing with batch selection, hierarchy modes and drag moves.

The host owns PDF meaning and persistence; this widget emits edited rows. The
default is read-only, so other tools need not expose editing functionality.
"""

from dataclasses import dataclass, replace
from collections.abc import Callable
from uuid import uuid4
from PySide6 import QtCore, QtGui, QtWidgets

IDENTITY_ROLE = QtCore.Qt.ItemDataRole.UserRole


class _BookmarkTree(QtWidgets.QTreeWidget):
    """Keep multi-selection on right-click and publish internal moves exactly once."""

    def __init__(self, editor: "BookmarkEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self.editor._navigation_timer.stop()
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                if not item.isSelected():
                    self.clearSelection()
                    item.setSelected(True)
                self.setCurrentItem(item, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)
            event.accept()
            return
        super().mousePressEvent(event)

    def startDrag(self, supported: QtCore.Qt.DropAction) -> None:
        self.editor._navigation_timer.stop()
        if not self.selectedItems():
            return
        # Own the drag lifecycle: QAbstractItemView's default move cleanup would
        # otherwise remove rows a second time after our validated tree rebuild.
        drag = QtGui.QDrag(self)
        drag.setMimeData(self.mimeData(self.selectedItems()))
        drag.exec(QtCore.Qt.DropAction.MoveAction)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        super().dragMoveEvent(event)
        if event.source() is not self or not self.editor._can_drop(self.itemAt(event.position().toPoint())):
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        if (event.source() is self and self.editor._drop(
                self.itemAt(event.position().toPoint()), self.dropIndicatorPosition())):
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()


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
        self.tree = _BookmarkTree(self)
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
            self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
            self.tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
            self.tree.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
            self.tree.setDropIndicatorShown(True)
            self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._context_menu)
            toolbar = QtWidgets.QToolBar()
            for text, tip, callback in (("+", "Add after selection", self._add), ("−", "Delete selected subtree", self._delete),
                                       ("↑", "Move subtree up", lambda: self._move(-1)), ("↓", "Move subtree down", lambda: self._move(1)),
                                       ("→", "Indent selected bookmarks with descendants", lambda: self._indent()),
                                       ("→¹", "Indent selected items only; children keep their levels and reading order", lambda: self._indent(False)),
                                       ("←", "Outdent, keeping reading order", lambda: self._outdent())):
                action = toolbar.addAction(text)
                action.setToolTip(tip)
                action.triggered.connect(callback)
            layout.addWidget(toolbar)
            self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                                      | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        layout.addWidget(self.tree)

    def load(self, rows: list[OutlineRow]) -> None:
        """Replace displayed rows without emitting edits; preserve selected IDs."""
        selected = self.tree.currentItem()
        identity = selected.data(0, IDENTITY_ROLE) if selected else None
        selected_ids = self._selected_ids()
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
                self.tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)
            item.setSelected(row.id in selected_ids)
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
        self.tree.setToolTip("Ctrl/Shift selects without jumping. Double-click edits. Drag selected subtrees to reorder, including nonconsecutive selections. Right-click offers both indent and outdent modes.")
        self.changed.emit(rows)

    def _navigate(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        self._navigation_timer.stop()
        if self.editable and QtWidgets.QApplication.keyboardModifiers() & (
                QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier):
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
        rows = self.rows()
        indexes = {index for start, end in self._spans(rows) for index in range(start, end)}
        if indexes:
            self._apply_rows([row for index, row in enumerate(rows) if index not in indexes])

    def _move(self, delta: int) -> None:
        self._navigation_timer.stop()
        selected_ids = self._selected_ids()
        current = self.tree.currentItem()
        roots = self._selected_roots()
        selected = {str(item.data(0, IDENTITY_ROLE)) for item in roots}
        changed = False
        # Process in movement order so adjacent selected siblings move together.
        for item in roots if delta < 0 else reversed(roots):
            parent = item.parent() or self.tree.invisibleRootItem()
            index = parent.indexOfChild(item)
            neighbor = index + delta
            if 0 <= neighbor < parent.childCount() and str(parent.child(neighbor).data(0, IDENTITY_ROLE)) not in selected:
                parent.takeChild(index)
                parent.insertChild(neighbor, item)
                item.setSelected(True)
                changed = True
        if changed:
            self._restore_selection(selected_ids, current)
            self._edited()

    def _indent(self, with_children: bool = True) -> None:
        self._navigation_timer.stop()
        rows = self.rows()
        selected = self._selected_ids()
        indexes = ({index for start, end in self._spans(rows) for index in range(start, end)}
                   if with_children else {index for index, row in enumerate(rows) if row.id in selected})
        if indexes:
            updated = [replace(row, level=row.level + 1) if index in indexes else row for index, row in enumerate(rows)]
            self._apply_rows(updated)

    def _outdent(self, keep_order: bool = True) -> None:
        self._navigation_timer.stop()
        if keep_order:
            rows = self.rows()
            spans = self._spans(rows)
            indexes = {index for start, end in spans if rows[start].level > 1 for index in range(start, end)}
            if indexes:
                self._apply_rows([replace(row, level=row.level - 1) if index in indexes else row
                                  for index, row in enumerate(rows)])
        else:
            # Reverse order prevents siblings being reversed when each is placed
            # immediately after their former parent. Descendants move once.
            changed = False
            selected_ids = self._selected_ids()
            current = self.tree.currentItem()
            for item in reversed(self._selected_roots()):
                parent = item.parent()
                if parent is None:
                    continue
                grandparent = parent.parent() or self.tree.invisibleRootItem()
                parent.takeChild(parent.indexOfChild(item))
                grandparent.insertChild(grandparent.indexOfChild(parent) + 1, item)
                item.setSelected(True)
                changed = True
            if changed:
                self._restore_selection(selected_ids, current)
                self._edited()

    def _restore_selection(self, identities: set[str], current: QtWidgets.QTreeWidgetItem | None) -> None:
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value() is not None:
            item = iterator.value()
            item.setSelected(str(item.data(0, IDENTITY_ROLE)) in identities)
            iterator += 1
        if current is not None:
            self.tree.setCurrentItem(current, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)

    def _selected_ids(self) -> set[str]:
        return {str(item.data(0, IDENTITY_ROLE)) for item in self.tree.selectedItems()}

    def _selected_roots(self) -> list[QtWidgets.QTreeWidgetItem]:
        selected = self._selected_ids()
        result: list[QtWidgets.QTreeWidgetItem] = []
        def visit(parent: QtWidgets.QTreeWidgetItem) -> None:
            for index in range(parent.childCount()):
                item = parent.child(index)
                if str(item.data(0, IDENTITY_ROLE)) in selected:
                    result.append(item)
                else:
                    visit(item)
        visit(self.tree.invisibleRootItem())
        return result

    def _spans(self, rows: list[OutlineRow]) -> list[tuple[int, int]]:
        """Return nonoverlapping selected subtree spans in document order."""
        selected = self._selected_ids()
        spans: list[tuple[int, int]] = []
        index = 0
        while index < len(rows):
            if rows[index].id not in selected:
                index += 1
                continue
            end = index + 1
            while end < len(rows) and rows[end].level > rows[index].level:
                end += 1
            spans.append((index, end))
            index = end
        return spans

    def _reject(self, reason: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Bookmark operation", reason)

    def _apply_rows(self, rows: list[OutlineRow]) -> bool:
        """Validate an entire operation before emitting a single undoable edit."""
        if not self.editable:
            return False
        previous = 0
        for row in rows:
            if not 1 <= row.level <= previous + 1:
                self._reject("Cannot indent this selection: a preceding parent is required. No bookmarks were changed.")
                return False
            previous = row.level
        if rows == self.rows():
            return False
        self.load(rows)
        self._edited()
        return True

    def _can_drop(self, target: QtWidgets.QTreeWidgetItem | None) -> bool:
        selected = self._selected_ids()
        if not selected:
            return False
        while target is not None:
            if str(target.data(0, IDENTITY_ROLE)) in selected:
                return False
            target = target.parent()
        return True

    def _drop(self, target: QtWidgets.QTreeWidgetItem | None,
              position: QtWidgets.QAbstractItemView.DropIndicatorPosition) -> bool:
        """Move selected subtrees to one location, retaining their relative order."""
        self._navigation_timer.stop()
        if not self._can_drop(target):
            return False
        rows = self.rows()
        spans = self._spans(rows)
        if target is None:
            insertion, level = len(rows), 1
        else:
            identity = str(target.data(0, IDENTITY_ROLE))
            start = next(index for index, row in enumerate(rows) if row.id == identity)
            level = rows[start].level
            insertion = start
            if position != QtWidgets.QAbstractItemView.DropIndicatorPosition.AboveItem:
                insertion += 1
                while insertion < len(rows) and rows[insertion].level > level:
                    insertion += 1
            if position == QtWidgets.QAbstractItemView.DropIndicatorPosition.OnItem:
                level += 1
        removed = {index for start, end in spans for index in range(start, end)}
        moved = [replace(rows[index], level=rows[index].level + level - rows[start].level)
                 for start, end in spans for index in range(start, end)]
        remaining = [row for index, row in enumerate(rows) if index not in removed]
        offset = sum(index not in removed for index in range(insertion))
        return self._apply_rows(remaining[:offset] + moved + remaining[offset:])

    def _set_selected_targets(self) -> None:
        page = self._current_page()
        selected = self._selected_ids()
        self._apply_rows([replace(row, page=page) if row.id in selected else row for row in self.rows()])

    def _context_menu(self, point: QtCore.QPoint) -> None:
        self._navigation_timer.stop()
        item = self.tree.itemAt(point)
        if item is not None:
            if not item.isSelected():
                self.tree.clearSelection()
                item.setSelected(True)
            self.tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)
        menu = self._make_context_menu(item)
        menu.exec(self.tree.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _make_context_menu(self, item: QtWidgets.QTreeWidgetItem | None) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        menu.addAction("Add bookmark at current page", self._add)
        if item is not None:
            menu.addAction("Go to bookmark", lambda: self._go_selected(item))
            menu.addAction("Set target to current page", self._set_selected_targets)
            menu.addSeparator()
            menu.addAction("Rename", lambda: self.tree.editItem(item, 0))
            menu.addAction("Edit target page", lambda: self.tree.editItem(item, 1))
            menu.addAction("Move up", lambda: self._move(-1))
            menu.addAction("Move down", lambda: self._move(1))
            menu.addAction("Indent (with descendants)", lambda: self._indent())
            menu.addAction("Indent (selected items only)", lambda: self._indent(False))
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
