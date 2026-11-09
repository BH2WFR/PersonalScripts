"""Three-column PDF splitter desktop with cached originals and immediate crop overlays."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_widgets import NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls
from utils import *
from ..common.file_actions import choose_pdf_output
from ..common.preferences import choose_open_file, remember_directory
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.task_buttons import TaskButtons
from ..common.navigation import NavigationPane
from ..common.page_cache import PageCache, pixmap_bytes
from ..common.preview_buffer import PreviewBuffer
from ..common.protocol import Json
from ..common.tooltips import TooltipFilter
from .model import Axis, Box, PageOverride, Settings, page_boxes, move_divider
from .panel import SplitPanel
from .viewer import SplitViewer

PT_TO_MM = 25.4 / 72
STATUS_WHOLE = "不处理"
STATUS_CUSTOM = "特殊处理"


@dataclass(frozen=True)
class CachedPage:
    """An original raster plus displayed page dimensions in PDF points."""

    pixmap: QtGui.QPixmap
    width: float
    height: float


class SplitWindow(QtWidgets.QMainWindow):
    """Own session-only crop rules; all PDF work goes through one serial worker."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.source: Path | None = None
        self.password = ""
        self.page_count = 0
        self.current_page = 1
        self.settings = Settings()
        self.overrides: dict[int, PageOverride] = {}
        self.dirty = False
        self._cursor_busy = False
        self._request: dict[str, Json] = {}
        self._shown: CachedPage | None = None
        self.runner = JobRunner(entry, self)
        self.runner.completed.connect(self._completed)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.progress.connect(self._progress)
        self.runner.controlChanged.connect(self._enabled)
        self.runner.controlStatus.connect(lambda text: self.status.setText(text))
        self.preview_buffer = PreviewBuffer()
        self.cache = PageCache[CachedPage](lambda page: pixmap_bytes(page.pixmap))
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._render)
        self.setWindowTitle("PDF Split Pages")
        self.resize(1420, 900)
        self._build()
        self.drop_filter = FileDropFilter(self, self.open_path, lambda: not self.runner.busy, suffixes=(".pdf",))
        self.tooltips = TooltipFilter(self)
        self._enabled()

    def _build(self) -> None:
        splitter = QtWidgets.QSplitter()
        self.setCentralWidget(splitter)
        # ── independent left settings column ──────────────────
        self.left = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(self.left)
        left.setContentsMargins(6, 6, 3, 6)
        files = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open PDF")
        self.open_button.clicked.connect(self._open_dialog)
        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self._close_pdf)
        files.addWidget(self.open_button)
        files.addWidget(self.close_button)
        left.addLayout(files)
        self.page_info = QtWidgets.QLabel("Page: —\nSize: —")
        self.page_info.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.page_info.setWordWrap(True)
        left.addWidget(self.page_info)
        self.panel = SplitPanel()
        self.panel.globalEdited.connect(self._global_changed)
        self.panel.keepChanged.connect(self._keep_changed)
        self.panel.resetRequested.connect(self._reset_page)
        self.panel.cropsEdited.connect(self._crops_changed)
        self.panel.dividerEdited.connect(self._divider_changed)
        self.panel.moveRequested.connect(self._move_frames)
        self.panel.selectionChanged.connect(self._draw_crops)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self.panel)
        left.addWidget(scroll, 1)
        self.left.setMinimumWidth(340)
        splitter.addWidget(self.left)

        # ── compact viewer toolbar and navigation ─────────────
        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(3, 6, 6, 6)
        self.toolbar = QtWidgets.QToolBar()
        self.previous = self.toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowBack),
            "Previous page", lambda: self.go_page(self.current_page - 1))
        self.next = self.toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward),
            "Next page", lambda: self.go_page(self.current_page + 1))
        self.page_number = NoWheelSpinBox()
        self.page_number.setRange(1, 1)
        self.page_number.setFixedWidth(55)
        self.page_number.setKeyboardTracking(False)
        self.page_number.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_number.editingFinished.connect(lambda: self.go_page(self.page_number.value()))
        self.toolbar.addWidget(self.page_number)
        self.page_total = QtWidgets.QLabel(" / 0 ")
        self.toolbar.addWidget(self.page_total)
        self.toolbar.addSeparator()
        self.viewer = SplitViewer()
        self.viewer.pageStepRequested.connect(lambda step: self.go_page(self.current_page + step))
        self.toolbar.addAction("Fit page", self.viewer.fit_page)
        self.toolbar.addAction("Fit width", self.viewer.fit_width)
        self.toolbar.addAction("100%", self.viewer.actual_pixels)
        self.zoom = NoWheelDoubleSpinBox()
        self.zoom.setRange(2.5, 1600)
        self.zoom.setSuffix(" %")
        self.zoom.setFixedWidth(85)
        self.zoom.setKeyboardTracking(False)
        self.zoom.editingFinished.connect(lambda: self.viewer.set_zoom(self.zoom.value()))
        self.viewer.zoomChanged.connect(self.zoom.setValue)
        self.toolbar.addWidget(self.zoom)
        self.fit = QtWidgets.QCheckBox("Auto fit")
        self.fit.setChecked(True)
        self.fit.toggled.connect(lambda value: setattr(self.viewer, "auto_fit", value))
        self.toolbar.addWidget(self.fit)
        self.toolbar.addSeparator()
        self.show_boxes = QtWidgets.QCheckBox("Show crops")
        self.show_boxes.setChecked(True)
        self.show_boxes.toggled.connect(self._draw_crops)
        self.toolbar.addWidget(self.show_boxes)
        layout.addWidget(self.toolbar)
        content = QtWidgets.QSplitter()
        content.addWidget(self.viewer)
        self.navigation = NavigationPane()
        self.navigation.removeTab(self.navigation.indexOf(self.navigation.image_tab))
        self.navigation.pages.setHeaderLabels(["Page", "Title", "Processing", "Output start"])
        self.navigation.pages.header().setStretchLastSection(False)
        self.navigation.pages.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.navigation.pages.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.navigation.pages.setToolTip("Click a physical page to preview. Orange: no processing; blue: custom crops.")
        self.navigation.pageRequested.connect(lambda index: self.go_page(index + 1))
        content.addWidget(self.navigation)
        content.setStretchFactor(0, 1)
        content.setSizes([740, 260])
        layout.addWidget(content, 1)
        footer = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Open or drop a PDF to begin.")
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.task_buttons = TaskButtons(self.runner, with_progress=True)
        self.progress_bar = self.task_buttons.progress_bar
        footer.addWidget(self.task_buttons)
        self.export_button = QtWidgets.QPushButton("Export PDF")
        self.export_button.clicked.connect(self._export)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
        splitter.addWidget(right)
        splitter.setSizes([350, 1070])

    def _enabled(self, *_args: object) -> None:
        idle, loaded = not self.runner.busy, self.source is not None
        self.left.setEnabled(idle)
        self.close_button.setEnabled(loaded)
        self.panel.general.setEnabled(loaded)
        self.panel.current.setEnabled(loaded and self._shown is not None)
        self.navigation.setEnabled(loaded and idle)
        self.page_number.setEnabled(loaded and idle)
        self.previous.setEnabled(loaded and idle and self.current_page > 1)
        self.next.setEnabled(loaded and idle and self.current_page < self.page_count)
        self.export_button.setEnabled(loaded and idle)
        self.viewer.navigation_enabled = loaded and idle
        working = self.runner.busy and not self.runner.paused
        if working and not self._cursor_busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            self._cursor_busy = True
        elif not working and self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False

    def _start(self, request: dict[str, Json]) -> bool:
        if self.runner.busy:
            return False
        self.timer.stop()
        self._request = {"path": str(self.source or ""), "password": self.password, **request}
        self.status.setText(f"Working: {request['operation']}…")
        return self.runner.start(self._request)

    def _discard(self) -> bool:
        return not self.dirty or QtWidgets.QMessageBox.question(self, "Unexported settings",
            "Discard unexported split settings?",
            QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel) == QtWidgets.QMessageBox.StandardButton.Discard

    def _open_dialog(self) -> None:
        self.timer.stop()
        path = choose_open_file(self, "Open PDF", "PDF (*.pdf)")
        if path:
            self.open_path(Path(path))
        else:
            self._schedule_preview()

    def open_path(self, path: Path) -> None:
        """Inspect a dropped/chosen input; replace session state only on successful open."""
        if self.runner.busy:
            return
        self.timer.stop()
        if self._discard():
            self._start({"operation": "inspect", "path": str(path), "password": ""})
        else:
            self._schedule_preview()

    def _reset(self) -> None:
        self.source = None
        self.password = ""
        self.page_count = 0
        self.current_page = 1
        self.settings = Settings()
        self.overrides.clear()
        self.dirty = False
        self._shown = None
        self.cache.clear()
        self.viewer.clear()
        self.navigation.load([], [])
        self.panel.load_settings(self.settings, 0)
        self.panel.load_page((), self.settings.axis, 1, 1, False, False)
        self.page_number.setRange(1, 1)
        self.page_total.setText(" / 0 ")
        self.page_info.setText("Page: —\nSize: —")
        self.setWindowTitle("PDF Split Pages")

    def _close_pdf(self) -> None:
        if self.runner.busy:
            return
        self.timer.stop()
        if not self._discard():
            self._schedule_preview()
            return
        self.runner.shutdown()
        self.preview_buffer.close()
        self._reset()
        self.status.setText("Open or drop a PDF to begin.")
        self._enabled()

    def _boxes(self) -> tuple[Box, ...]:
        return page_boxes(self.settings, self.overrides, self.current_page, self.page_count)

    def _kept(self, page: int) -> bool:
        override = self.overrides.get(page)
        return override.keep if override is not None else not self.settings.applies(page, self.page_count)

    def _load_page_controls(self, *, reset_selection: bool = False) -> None:
        if self._shown is None:
            return
        page = self._shown
        override = self.overrides.get(self.current_page)
        canvas = (1.0, 1.0) if self._kept(self.current_page) else (
            override.canvas if override and override.canvas else self.settings.canvas_size())
        self.page_info.setText(f"Page {self.current_page} / {self.page_count}\n"
            f"{page.width:.2f} × {page.height:.2f} pt  ({page.width * PT_TO_MM:.1f} × {page.height * PT_TO_MM:.1f} mm)\n"
            f"Output page: {page.width * canvas[0]:.2f} × {page.height * canvas[1]:.2f} pt")
        self.panel.load_page(self._boxes(), self.settings.axis, self._shown.width, self._shown.height,
                             self._kept(self.current_page), self.current_page in self.overrides,
                             reset_selection=reset_selection)
        self._draw_crops()

    def _draw_crops(self, *_args: object) -> None:
        boxes = self._boxes() if self._shown is not None and self.show_boxes.isChecked() and not self._kept(self.current_page) else ()
        self.viewer.set_crops(boxes, self.panel.selected_index())

    def _refresh_markers(self) -> None:
        output_start = 1
        for page, item in enumerate(self.navigation.page_items, 1):
            kept, custom = self._kept(page), page in self.overrides
            label = STATUS_WHOLE if kept else STATUS_CUSTOM if custom else ""
            item.setText(2, label)
            item.setForeground(2, QtGui.QBrush(QtGui.QColor("#9c5200" if kept else "#1557a0")) if label else QtGui.QBrush())
            item.setBackground(2, QtGui.QBrush(QtGui.QColor("#fff0cf" if kept else "#e2efff")) if label else QtGui.QBrush())
            font = item.font(2)
            font.setBold(bool(label))
            item.setFont(2, font)
            item.setText(3, str(output_start))
            item.setToolTip(3, "First physical output page produced by this source page.")
            output_start += len(page_boxes(self.settings, self.overrides, page, self.page_count))
        self.navigation.pages.resizeColumnToContents(2)
        self.navigation.pages.resizeColumnToContents(3)
        self._summary()

    def _summary(self) -> None:
        if not self.page_count:
            return
        count = sum(len(page_boxes(self.settings, self.overrides, page, self.page_count)) for page in range(1, self.page_count + 1))
        kept = sum(self._kept(page) for page in range(1, self.page_count + 1))
        self.status.setText(f"Output: {count} pages; {kept} kept whole. Export removes page labels.")

    def _global_changed(self) -> None:
        if self.source is None or self.runner.busy:
            return
        proposed = self.panel.read_settings()
        if proposed == self.settings:
            return
        try:
            proposed.validate(self.page_count)
        except ValueError as exc:
            self.panel.load_settings(self.settings, self.page_count)
            QtWidgets.QMessageBox.warning(self, "Invalid settings", str(exc))
            return
        self.settings = proposed
        self.dirty = True
        self._load_page_controls(reset_selection=True)
        self._refresh_markers()

    def _keep_changed(self, keep: bool) -> None:
        if self._shown is None or self.runner.busy:
            return
        previous = self.overrides.get(self.current_page)
        if keep:
            self.overrides[self.current_page] = PageOverride(True, previous.boxes if previous else (), previous.canvas if previous else None)
        elif previous and previous.boxes:
            self.overrides[self.current_page] = PageOverride(boxes=previous.boxes, canvas=previous.canvas)
        elif self.settings.applies(self.current_page, self.page_count):
            self.overrides.pop(self.current_page, None)
        else:
            self.overrides[self.current_page] = PageOverride(boxes=self.settings.boxes(), canvas=self.settings.canvas_size())
        self._page_changed()

    def _reset_page(self) -> None:
        if self.current_page in self.overrides:
            del self.overrides[self.current_page]
            self._page_changed()

    def _page_changed(self) -> None:
        self.dirty = True
        self._load_page_controls()
        self._refresh_markers()

    def _crops_changed(self, proposed: tuple[Box, ...]) -> None:
        if self._shown is None or self.runner.busy:
            return
        if proposed != self._boxes():
            self._save_crops(proposed)

    def _save_crops(self, boxes: tuple[Box, ...]) -> None:
        previous = self.overrides.get(self.current_page)
        canvas = previous.canvas if previous and previous.canvas else self.settings.canvas_size()
        override = PageOverride(boxes=boxes, canvas=canvas)
        try:
            override.validate()
        except ValueError as exc:
            self._load_page_controls()
            QtWidgets.QMessageBox.warning(self, "Invalid crop", str(exc))
            return
        self.overrides[self.current_page] = override
        self._page_changed()

    def _move_frames(self, dx: float, dy: float, all_frames: bool) -> None:
        if self._shown is None or self.runner.busy:
            return
        selected = self.panel.selected_index()
        boxes = tuple(box.moved(dx, dy) if all_frames or index == selected else box
                      for index, box in enumerate(self._boxes()))
        self._save_crops(boxes)

    def _divider_changed(self, pair: tuple[int, int], position: float) -> None:
        if self._shown is None or self.runner.busy:
            return
        try:
            if self.panel.selected_index() >= 0:
                box = self._boxes()[pair[0]]
                horizontal = self.settings.axis == Axis.LEFT_RIGHT
                delta = position - (box.x1 if horizontal else box.y1)
                self._move_frames(delta if horizontal else 0, 0 if horizontal else delta, False)
                return
            boxes = move_divider(self._boxes(), self.settings.axis, pair, position)
        except ValueError as exc:
            self._load_page_controls()
            QtWidgets.QMessageBox.warning(self, "Invalid divider", str(exc))
            return
        if boxes != self._boxes():
            self._save_crops(boxes)

    def go_page(self, page: int) -> None:
        """Jump to a one-based original page, using cached originals without a delay."""
        if self.runner.busy or not 1 <= page <= self.page_count:
            return
        changed = page != self.current_page
        self.current_page = page
        self.page_number.setValue(page)
        self.navigation.select_page(page - 1)
        self._schedule_preview(reset_selection=changed)

    def _schedule_preview(self, *, reset_selection: bool = False) -> None:
        self.timer.stop()
        if self.source is None or self.runner.busy:
            return
        cached = self.cache.get(self.current_page)
        if cached is not None:
            self._show(cached, reset_selection=reset_selection)
        else:
            self._shown = None
            self.viewer.clear()
            self.page_info.setText(f"Page {self.current_page} / {self.page_count}\nSize: loading…")
            # Original-only previews have no artificial debounce. One timer and
            # a busy guard prevent render queues during fast navigation.
            self.timer.start(0)
        self._enabled()

    def _render(self) -> None:
        if QtWidgets.QApplication.activeModalWidget() is not None:
            self.timer.start(100)
            return
        if self.source is not None and not self.runner.busy:
            self._start({"operation": "preview", "page": self.current_page, "pixel_buffer": self.preview_buffer.name})

    def _show(self, page: CachedPage, *, reset_selection: bool = False) -> None:
        self._shown = page
        self.viewer.set_pixmap(page.pixmap, (str(self.source), self.current_page))
        self._load_page_controls(reset_selection=reset_selection)
        self._summary()

    def _progress(self, message: dict[str, Json]) -> None:
        self.status.setText(str(message.get("stage") or f"Splitting: {message.get('done', 0)} / {message.get('total', 0)} source pages…"))

    def _completed(self, message: dict[str, Json]) -> None:
        kind = message.get("kind")
        if kind == "cancelled":
            self.status.setText("Task cancelled. Adjust settings and export again.")
        elif kind == "error":
            if message.get("code") == "password" and self._request.get("operation") == "inspect":
                password, accepted = QtWidgets.QInputDialog.getText(self, "PDF password", "Password:", QtWidgets.QLineEdit.EchoMode.Password)
                if accepted:
                    self._start({**self._request, "password": password})
                    return
                self.status.setText("Opening cancelled.")
            else:
                self.status.setText(str(message.get("message", "Operation failed.")))
                QtWidgets.QMessageBox.warning(self, "PDF Split Pages", str(message.get("message")))
        elif kind == "opened":
            path = Path(str(self._request["path"]))
            self._reset()
            self.source = path
            remember_directory(self, "open-pdf", path)
            self.password = str(message.get("password", ""))
            self.page_count = int(cast(int, message["page_count"]))
            self.page_number.setRange(1, self.page_count)
            self.page_total.setText(f" / {self.page_count} ")
            self.navigation.load(cast(list[str], message["labels"]), cast(list[tuple[int, str, int]], message["bookmarks"]))
            self.panel.load_settings(self.settings, self.page_count)
            self._refresh_markers()
            self.setWindowTitle(f"PDF Split Pages — {path.name}")
            self.go_page(1)
        elif kind == "preview":
            if message.get("page") != self.current_page:
                self._schedule_preview()
                return
            pixmap = self.preview_buffer.read(int(cast(int, message["width"])), int(cast(int, message["height"])))
            cached = CachedPage(pixmap, float(cast(float, message["page_width"])), float(cast(float, message["page_height"])))
            self.cache.put(self.current_page, cached)
            self._show(cached, reset_selection=True)
        elif kind == "exported":
            self.dirty = False
            details = f"Saved {message['page_count']} pages:\n{message['path']}\n\nAll page labels were removed."
            if message.get("ambiguous"):
                details += f"\nCheck {message['ambiguous']} bookmarks mapped to the first crop."
            if message.get("skipped_links"):
                details += f"\nSkipped {message['skipped_links']} unsupported/unresolved links."
            self.status.setText(f"Saved: {message['path']}")
            QtWidgets.QMessageBox.information(self, "Export complete", details)
        self._enabled()

    def _export(self) -> None:
        if self.source is None or self.runner.busy:
            return
        self.timer.stop()
        selected = choose_pdf_output(self, self.source, self.source.with_name(f"{self.source.stem}_split.pdf"))
        if selected:
            output, overwrite = selected
            self._start({"operation": "export", "output": str(output), "overwrite": overwrite,
                "page_count": self.page_count, "settings": self.settings.to_data(),
                "overrides": {str(page): override.to_data() for page, override in self.overrides.items()}})
        else:
            self._schedule_preview()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Finish active operations before closing; release the worker and bounded pixel storage."""
        if self.runner.busy:
            self.status.setText("Wait for the current operation to finish before closing.")
            event.ignore()
            return
        self.timer.stop()
        if not self._discard():
            event.ignore()
            self._schedule_preview()
            return
        self.runner.shutdown()
        self.preview_buffer.close()
        self.cache.clear()
        event.accept()


def main(entry: Path) -> int:
    """Check PDF dependencies and launch the Fusion desktop application."""
    import pymupdf
    import tqdm

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert isinstance(application, QtWidgets.QApplication)
    application.setStyle("Fusion")
    install_no_wheel_controls(application)
    window = SplitWindow(entry)
    window.show()
    return application.exec()
