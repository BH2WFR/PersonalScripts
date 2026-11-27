"""Shared page navigation and zoom controls for PDF preview windows."""

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from utils.qt_widgets import NoWheelDoubleSpinBox, NoWheelSpinBox
from .viewer import MAX_SCALE, MIN_SCALE, PageViewer


TOOLBAR_STYLE = "QToolBar::separator { background: palette(mid); width: 1px; margin: 4px 6px; }"


def set_preview_tab_order(*sections: QtWidgets.QWidget) -> None:
    """Keep runtime toolbar and task controls in their visual section's tab order."""
    window = sections[0].window()
    groups: list[list[QtWidgets.QWidget]] = [[] for _ in sections]
    widget = window.nextInFocusChain()
    while widget is not None and widget is not window:
        if widget.focusPolicy() & QtCore.Qt.FocusPolicy.TabFocus and widget.focusProxy() is None:
            for section, group in zip(sections, groups):
                if widget is section or section.isAncestorOf(widget):
                    group.append(widget)
                    break
        widget = widget.nextInFocusChain()
    order = [widget for group in groups for widget in group]
    for first, second in zip(order, order[1:]):
        QtWidgets.QWidget.setTabOrder(first, second)


class PageToolbar(QtWidgets.QToolBar):
    """Control a preview and request one-based page numbers or relative page steps."""

    pageRequested = QtCore.Signal(int)
    stepRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(TOOLBAR_STYLE)
        self.previous = self._page_button(-1, QtWidgets.QStyle.StandardPixmap.SP_ArrowBack, "Previous page")
        self.next = self._page_button(1, QtWidgets.QStyle.StandardPixmap.SP_ArrowForward, "Next page")
        self.page_number = NoWheelSpinBox()
        self.page_number.setRange(1, 1)
        self.page_number.setFixedWidth(48)
        self.page_number.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.page_number.setAccessibleName("Physical page number")
        self.page_number.setToolTip("Press Enter or leave this field to jump to the physical page.")
        self.page_number.setKeyboardTracking(False)
        self.page_number.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_number.editingFinished.connect(lambda: self.pageRequested.emit(self.page_number.value()))
        self.addWidget(self.page_number)
        self.page_total = QtWidgets.QLabel("/ 0")
        self.page_total.setContentsMargins(4, 0, 4, 0)
        self.addWidget(self.page_total)

    def bind_viewer(self, viewer: PageViewer, *, editable_zoom: bool = True) -> None:
        """Attach the preview and configure its zoom controls once during setup."""
        self.viewer = viewer
        viewer.pageStepRequested.connect(self.stepRequested)
        self.addSeparator()
        self.addAction("Fit page", viewer.fit_page)
        self.addAction("Fit width", viewer.fit_width)
        self.addAction("100%", viewer.actual_pixels)
        if editable_zoom:
            self.zoom = NoWheelDoubleSpinBox()
            self.zoom.setRange(MIN_SCALE * 100, MAX_SCALE * 100)
            self.zoom.setValue(100)
            self.zoom.setSuffix(" %")
            self.zoom.setFixedWidth(85)
            self.zoom.setKeyboardTracking(False)
            self.zoom.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.zoom.setToolTip("Press Enter or leave this field to apply the zoom percentage.")
            self.zoom.editingFinished.connect(lambda: viewer.set_zoom(self.zoom.value()))
            viewer.zoomChanged.connect(self.zoom.setValue)
            self.addWidget(self.zoom)
        else:
            zoom_label = QtWidgets.QLabel(" 100% ")
            viewer.zoomChanged.connect(lambda value: zoom_label.setText(f" {value:.0f}% "))
            self.addWidget(zoom_label)

    def _page_button(self, step: int, icon: QtWidgets.QStyle.StandardPixmap, title: str) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setFixedWidth(26)
        button.setAccessibleName(title)
        button.setToolTip(title)
        button.clicked.connect(lambda: self.stepRequested.emit(step))
        self.addWidget(button)
        return button

    def set_page_count(self, count: int) -> None:
        """Update the jump range and physical page count, including an empty document."""
        self.page_number.setRange(1, max(1, count))
        self.page_total.setText(f"/ {count}")

    def set_navigation_enabled(self, enabled: bool, page: int, count: int) -> None:
        """Apply the window's browsing policy to jumps, arrow buttons and viewer keys."""
        self.page_number.setEnabled(enabled)
        self.previous.setEnabled(enabled and page > 1)
        self.next.setEnabled(enabled and page < count)
        self.viewer.navigation_enabled = enabled

    def add_auto_fit(self, on_change: Callable[[bool], None] | None = None) -> QtWidgets.QCheckBox:
        """Append the page-turn fit option, optionally managed by the tool's project."""
        checkbox = QtWidgets.QCheckBox("Auto fit")
        checkbox.setChecked(self.viewer.auto_fit)
        checkbox.setToolTip("Automatically fit the whole page after every page turn")
        checkbox.toggled.connect(on_change or self._set_auto_fit)
        self.addWidget(checkbox)
        return checkbox

    def _set_auto_fit(self, enabled: bool) -> None:
        self.viewer.auto_fit = enabled


class PreviewPane(QtWidgets.QMainWindow):
    """Embed a native toolbar area in a splitter, including its overflow controls."""

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, viewer: PageViewer | None = None,
                 editable_zoom: bool = True) -> None:
        # Programmatic callers can pass the viewer directly. Designer supplies the
        # splitter parent and creates the toolbar and central widget from the form.
        if isinstance(parent, PageViewer):
            viewer, parent = parent, None
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.WindowType.Widget)
        if viewer is not None:
            self.toolbar = PageToolbar(self)
            self.toolbar.bind_viewer(viewer, editable_zoom=editable_zoom)
            self.toolbar.setMovable(False)
            self.addToolBar(self.toolbar)
            body = QtWidgets.QWidget()
            self.setCentralWidget(body)
            self.body_layout = QtWidgets.QVBoxLayout(body)
            self.body_layout.setContentsMargins(0, 0, 0, 0)

    def add_tool_toolbar(self, first: QtWidgets.QWidget, *others: QtWidgets.QWidget) -> QtWidgets.QToolBar:
        """Append a separate toolbar for options supplied by a programmatic caller."""
        toolbar = PreviewOptionsToolbar(self)
        toolbar.setWindowTitle("Preview options")
        toolbar.setMovable(False)
        for widget in (first, *others):
            toolbar.addWidget(widget)
        self.addToolBar(toolbar)
        return toolbar


class PreviewOptionsToolbar(QtWidgets.QToolBar):
    """Separate tool-specific preview controls from the page toolbar on their left."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QToolBar { border-left: 1px solid palette(mid); padding-left: 4px; }")
