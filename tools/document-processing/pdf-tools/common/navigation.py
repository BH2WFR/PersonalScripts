"""Reusable physical-page, bookmark and image trees for PDF desktop tools."""

import math
from PySide6 import QtCore, QtGui, QtWidgets

from .pdf_images import ImageElement

PAGE_ROLE = QtCore.Qt.ItemDataRole.UserRole


class NavigationPane(QtWidgets.QTabWidget):
    """Show all pages and the original bookmark hierarchy without owning a PDF.

    Signals:
        pageRequested: Zero-based physical page selected by the user. The host
            decides when navigation is permitted and how to schedule its rendering.
        imageSelected: Normalized image placement selected by the user, or None.
    """

    pageRequested = QtCore.Signal(int)
    imageSelected = QtCore.Signal(object)  # Normalized visible bounds, or None.

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.pages = QtWidgets.QTreeWidget()
        self.pages.setHeaderLabels(["Page", "Title", "Profile"])
        self.pages.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pages.setToolTip("Click a page to preview. Ctrl/Shift-select multiple pages for batch actions.")
        self.bookmarks = QtWidgets.QTreeWidget()
        self.bookmarks.setHeaderLabels(["Bookmark", "Page"])
        self.images = QtWidgets.QTreeWidget()
        self.images.setHeaderLabels(["Image / pixels", "Format", "DPI", "Position (pt)"])
        self.images.setRootIsDecorated(False)
        self.images.setToolTip("Images on the displayed page. Click to outline one in blue; click again, empty space, or Esc to clear.")
        self.image_tab = QtWidgets.QWidget()
        image_layout = QtWidgets.QVBoxLayout(self.image_tab)
        image_layout.setContentsMargins(6, 6, 6, 6)
        image_layout.setSpacing(3)
        self.page_size_label = QtWidgets.QLabel("Page: —")
        self.scan_dpi_label = QtWidgets.QLabel("Main scan: —")
        self.preview_dpi_label = QtWidgets.QLabel("Preview: —")
        self.scan_dpi_label.setToolTip("Effective DPI of an image covering at least 80% of the page. PDF pages have no intrinsic DPI.")
        self.preview_dpi_label.setToolTip("Actual preview pixels divided by the PDF page size; the display renderer may cap pixel count.")
        for label in (self.page_size_label, self.scan_dpi_label, self.preview_dpi_label):
            label.setWordWrap(True)
            image_layout.addWidget(label)
        image_layout.addWidget(self.images, 1)
        self.addTab(self.pages, "Pages")
        self.addTab(self.bookmarks, "Bookmarks")
        self.addTab(self.image_tab, "Images")
        self.page_items: list[QtWidgets.QTreeWidgetItem] = []
        self.bookmark_items: list[tuple[int, QtWidgets.QTreeWidgetItem]] = []
        for tree in (self.pages, self.bookmarks):
            tree.setAlternatingRowColors(True)
            tree.setUniformRowHeights(True)
            tree.itemClicked.connect(self._activate)
            tree.itemActivated.connect(self._activate)
        self.images.setAlternatingRowColors(True)
        self.images.setUniformRowHeights(True)
        self.images.itemClicked.connect(self._image_clicked)
        self.images.itemSelectionChanged.connect(self._image_selection_changed)
        self.images.viewport().installEventFilter(self)
        QtGui.QShortcut(QtCore.Qt.Key.Key_Escape, self.images,
                        activated=self.images.clearSelection)
        self._last_image_click: QtWidgets.QTreeWidgetItem | None = None
        self.setMinimumWidth(190)

    def load(self, labels: list[str], bookmarks: list[tuple[int, str, int]]) -> None:
        """Replace navigation data; bookmark page numbers are one-based, as in PDFs."""
        self.pages.clear()
        self.bookmarks.clear()
        self.load_images(())
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

    @staticmethod
    def _dpi_text(x: float, y: float) -> str:
        return f"{x:.0f}" if abs(x - y) < .5 else f"{x:.0f} × {y:.0f}"

    def load_images(self, images: tuple[ImageElement, ...], *,
                    page_size: tuple[float, float] | None = None,
                    preview_pixels: tuple[int, int] | None = None) -> None:
        """Replace the displayed page's summary and images; clear its outline."""
        self.images.clearSelection()
        self.images.clear()
        self._last_image_click = None
        self.imageSelected.emit(None)
        self.page_size_label.setText("Page: —")
        self.scan_dpi_label.setText("Main scan: —")
        self.preview_dpi_label.setText("Preview: —")
        if page_size is not None and all(math.isfinite(value) and value > 0 for value in page_size):
            width, height = page_size
            self.page_size_label.setText(
                f"Page: {width:.1f} × {height:.1f} pt ({width * 25.4 / 72:.1f} × {height * 25.4 / 72:.1f} mm)")
            if preview_pixels is not None:
                px_width, px_height = preview_pixels
                self.preview_dpi_label.setText(
                    f"Preview: {self._dpi_text(px_width * 72 / width, px_height * 72 / height)} DPI"
                    f" · {px_width} × {px_height} px")
            dominant = max(images, key=lambda image: (image.bounds[2] - image.bounds[0])
                           * (image.bounds[3] - image.bounds[1]), default=None)
            if dominant is not None:
                coverage = (dominant.bounds[2] - dominant.bounds[0]) * (dominant.bounds[3] - dominant.bounds[1])
                if coverage >= .8:
                    self.scan_dpi_label.setText(
                        f"Main scan: {self._dpi_text(dominant.dpi_x, dominant.dpi_y)} DPI")
        for number, image in enumerate(images, 1):
            x0, y0, x1, y1 = image.position
            dpi = self._dpi_text(image.dpi_x, image.dpi_y)
            item = QtWidgets.QTreeWidgetItem([
                f"{number}. {image.width} × {image.height}", image.codec, dpi,
                f"{x0:.1f}, {y0:.1f} · {x1 - x0:.1f} × {y1 - y0:.1f}"])
            item.setData(0, PAGE_ROLE, image.bounds)
            item.setToolTip(3, f"x={x0:.2f}, y={y0:.2f}, width={x1-x0:.2f}, height={y1-y0:.2f} pt")
            self.images.addTopLevelItem(item)
        for column in range(3):
            self.images.resizeColumnToContents(column)

    def _image_selection_changed(self) -> None:
        self._last_image_click = None
        selected = self.images.selectedItems()
        self.imageSelected.emit(selected[0].data(0, PAGE_ROLE) if selected else None)

    def _image_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if item is self._last_image_click:
            self.images.clearSelection()
            self._last_image_click = None
        else:
            self._last_image_click = item

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if (watched is self.images.viewport()
                and event.type() == QtCore.QEvent.Type.MouseButtonPress
                and self.images.itemAt(event.position().toPoint()) is None):
            self.images.clearSelection()
        return super().eventFilter(watched, event)

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
