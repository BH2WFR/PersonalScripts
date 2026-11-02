"""Reusable physical-page and bookmark trees for PDF desktop tools."""

from PySide6 import QtCore, QtWidgets

PAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole


class NavigationPane(QtWidgets.QTabWidget):
    """Show all pages and the original bookmark hierarchy without owning a PDF.

    Signals:
        pageRequested: Zero-based physical page selected by the user. The host
            decides when navigation is permitted and how to schedule its rendering.
    """

    pageRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.pages = QtWidgets.QTreeWidget()
        self.pages.setHeaderLabels(["Page", "Title", "Profile"])
        self.pages.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pages.setToolTip("Click a page to preview. Ctrl/Shift-select multiple pages for batch actions.")
        self.bookmarks = QtWidgets.QTreeWidget()
        self.bookmarks.setHeaderLabels(["Bookmark", "Page"])
        self.addTab(self.pages, "Pages")
        self.addTab(self.bookmarks, "Bookmarks")
        self.page_items: list[QtWidgets.QTreeWidgetItem] = []
        self.bookmark_items: list[tuple[int, QtWidgets.QTreeWidgetItem]] = []
        for tree in (self.pages, self.bookmarks):
            tree.setAlternatingRowColors(True)
            tree.setUniformRowHeights(True)
            tree.itemClicked.connect(self._activate)
            tree.itemActivated.connect(self._activate)
        self.setMinimumWidth(190)

    def load(self, labels: list[str], bookmarks: list[tuple[int, str, int]]) -> None:
        """Replace navigation data; bookmark page numbers are one-based, as in PDFs."""
        self.pages.clear()
        self.bookmarks.clear()
        self.page_items.clear()
        self.bookmark_items.clear()
        titles: dict[int, list[str]] = {}
        parents: list[QtWidgets.QTreeWidgetItem] = []
        for level, title, number in bookmarks:
            if 1 <= number <= len(labels):
                titles.setdefault(number - 1, []).append(title)
            item = QtWidgets.QTreeWidgetItem([title, str(number) if number > 0 else ""])
            if 1 <= number <= len(labels):
                item.setData(0, PAGE_ROLE, number - 1)
                self.bookmark_items.append((number - 1, item))
            parents = parents[:max(0, level - 1)]
            if parents:
                parents[-1].addChild(item)
            else:
                self.bookmarks.addTopLevelItem(item)
            parents.append(item)
        for index, label in enumerate(labels):
            number = str(index + 1) if label == str(index + 1) or not label else f"{index + 1} [{label}]"
            item = QtWidgets.QTreeWidgetItem([number, " / ".join(titles.get(index, [])), ""])
            item.setData(0, PAGE_ROLE, index)
            self.pages.addTopLevelItem(item)
            self.page_items.append(item)
        self.bookmarks.expandToDepth(1)
        self.pages.resizeColumnToContents(0)

    def set_profiles(self, labels: list[str]) -> None:
        """Attach optional tool-specific profile labels to the all-pages view."""
        for item, label in zip(self.page_items, labels):
            item.setText(2, label)

    def selected_pages(self) -> tuple[int, ...]:
        """Return sorted, zero-based page indexes selected for host batch actions."""
        return tuple(sorted(int(item.data(0, PAGE_ROLE)) for item in self.pages.selectedItems()))

    def select_page(self, index: int, *, preserve_selection: bool = False) -> None:
        """Highlight a host-selected page without emitting a navigation request."""
        if 0 <= index < len(self.page_items):
            flags = (QtCore.QItemSelectionModel.SelectionFlag.NoUpdate if preserve_selection and self.pages.selectedItems()
                     else QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.pages.setCurrentItem(self.page_items[index], 0, flags)
            self.pages.scrollToItem(self.page_items[index])
        matching = [item for page, item in self.bookmark_items if page == index]
        if matching:
            self.bookmarks.setCurrentItem(matching[0])
        else:
            self.bookmarks.clearSelection()

    def _activate(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if item.treeWidget() is self.pages and modifiers & (
                QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier):
            return  # Multi-selection never starts PDF work or locks the next click.
        number = item.data(0, PAGE_ROLE)
        if isinstance(number, int):
            self.pageRequested.emit(number)
