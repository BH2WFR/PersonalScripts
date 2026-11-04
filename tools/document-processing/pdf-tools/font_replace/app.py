"""PDF font replacement desktop: ordered rules, cached comparison and safe export."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from utils import *
from ..common.file_actions import choose_pdf_output
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.navigation import NavigationPane
from ..common.page_cache import PageCache, pixmap_bytes
from ..common.preview_buffer import PreviewBuffer
from ..common.protocol import Json
from ..common.tooltips import TooltipFilter
from ..common.viewer import PageViewer
from .model import ReplacementRule, read_face
from .panel import RulePanel

PREVIEW_DELAY_MS = 300


@dataclass(frozen=True)
class CachedPage:
    """One original and one latest processed view within a shared per-page budget."""

    raw: QtGui.QPixmap | None = None
    result: QtGui.QPixmap | None = None
    revision: int = -1
    count: int = 0
    recolored_runs: int = 0

    def bytes(self) -> int:
        """Count both retained pixmaps, including scanline alignment."""
        return sum(pixmap_bytes(pixmap) for pixmap in (self.raw, self.result) if pixmap is not None)


class FontReplaceWindow(QtWidgets.QMainWindow):
    """Keep rules and previews in memory; only Export PDF writes document changes."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.source: Path | None = None
        self.password = ""
        self.page_count = 0
        self.current_page = 1
        self.rules: list[ReplacementRule] = []
        self.revision = 0
        self.dirty = False
        self._cursor_busy = False
        self._request: dict[str, Json] = {}
        self.runner = JobRunner(entry, self)
        self.runner.completed.connect(self._completed)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.progress.connect(self._progress)
        self.preview_buffer = PreviewBuffer()
        self.cache = PageCache[CachedPage](lambda page: page.bytes())
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PREVIEW_DELAY_MS)
        self.timer.timeout.connect(self._render)
        self.setWindowTitle("PDF Font Replace")
        self.resize(1420, 900)
        self._build()
        self.drop_filter = FileDropFilter(self, self.open_path, lambda: not self.runner.busy, suffixes=(".pdf",))
        self.tooltips = TooltipFilter(self)
        self._enabled()

    def _build(self) -> None:
        splitter = QtWidgets.QSplitter()
        self.setCentralWidget(splitter)
        # ── independent left column ───────────────────────────
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
        left.addWidget(QtWidgets.QLabel("Replacement rules — first match wins"))
        self.rule_list = QtWidgets.QTreeWidget()
        self.rule_list.setHeaderLabels(["Replace from", "Replace with"])
        self.rule_list.setRootIsDecorated(False)
        self.rule_list.setAlternatingRowColors(True)
        self.rule_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rule_list.setMinimumHeight(100)
        self.rule_list.setMaximumHeight(260)
        self.rule_list.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.rule_list.itemSelectionChanged.connect(self._select_rule)
        self.rule_list.setToolTip("Rules match original text. The first matching row wins; later rules do not reprocess earlier replacements.")
        left.addWidget(self.rule_list, 1)
        actions = QtWidgets.QHBoxLayout()
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self._delete_rules)
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_rules)
        self.up_button = QtWidgets.QPushButton("↑")
        self.up_button.setToolTip("Move selected rule earlier")
        self.up_button.clicked.connect(lambda: self._move_rule(-1))
        self.down_button = QtWidgets.QPushButton("↓")
        self.down_button.setToolTip("Move selected rule later")
        self.down_button.clicked.connect(lambda: self._move_rule(1))
        for button in (self.delete_button, self.clear_button, self.up_button, self.down_button):
            actions.addWidget(button)
        left.addLayout(actions)
        self.panel = RulePanel()
        self.panel.commitRequested.connect(self._commit_rule)
        self.panel.scanRequested.connect(lambda pages: self._start({"operation": "scan", "pages": pages}))
        self.panel.scanPagesRequested.connect(self._scan_pages)
        self.panel.scanCurrentRequested.connect(self._scan_current)
        self.panel.catalogRequested.connect(lambda: self._start({"operation": "catalog"}))
        self.panel.fileRequested.connect(lambda path: self._start({"operation": "font_file", "font_path": path}))
        left.addWidget(self.panel, 3)
        self.left.setMinimumWidth(350)
        splitter.addWidget(self.left)

        # ── compact grouped viewer controls ───────────────────
        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(3, 6, 6, 6)
        self.toolbar = QtWidgets.QToolBar()
        self.previous = self.toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowBack),
            "Previous page", lambda: self.go_page(self.current_page - 1))
        self.next = self.toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward),
            "Next page", lambda: self.go_page(self.current_page + 1))
        self.page_number = QtWidgets.QSpinBox()
        self.page_number.setRange(1, 1)
        self.page_number.setFixedWidth(55)
        self.page_number.setKeyboardTracking(False)
        self.page_number.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_number.editingFinished.connect(lambda: self.go_page(self.page_number.value()))
        self.toolbar.addWidget(self.page_number)
        self.page_total = QtWidgets.QLabel(" / 0 ")
        self.toolbar.addWidget(self.page_total)
        self.toolbar.addSeparator()
        self.viewer = PageViewer()
        self.viewer.pageStepRequested.connect(lambda step: self.go_page(self.current_page + step))
        self.toolbar.addAction("Fit page", self.viewer.fit_page)
        self.toolbar.addAction("Fit width", self.viewer.fit_width)
        self.toolbar.addAction("100%", self.viewer.actual_pixels)
        self.zoom = QtWidgets.QDoubleSpinBox()
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
        self.raw = QtWidgets.QCheckBox("Show original (raw)")
        self.raw.setToolTip("Display the unchanged input. The selection persists when turning pages; rules still apply on export.")
        self.raw.toggled.connect(self._schedule_preview)
        self.toolbar.addWidget(self.raw)
        layout.addWidget(self.toolbar)
        content = QtWidgets.QSplitter()
        content.addWidget(self.viewer)
        self.navigation = NavigationPane()
        self.navigation.removeTab(self.navigation.indexOf(self.navigation.image_tab))
        self.navigation.pages.hideColumn(2)
        self.navigation.pages.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.navigation.pages.setToolTip("Click a physical page to preview it.")
        self.navigation.pageRequested.connect(lambda index: self.go_page(index + 1))
        content.addWidget(self.navigation)
        content.setStretchFactor(0, 1)
        content.setSizes([720, 240])
        layout.addWidget(content, 1)
        footer = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Open or drop a PDF to begin.")
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.export_button = QtWidgets.QPushButton("Export PDF")
        self.export_button.clicked.connect(self._export)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
        splitter.addWidget(right)
        splitter.setSizes([380, 1040])

    def _enabled(self, *_args: object) -> None:
        if not hasattr(self, "export_button"):
            return
        idle = not self.runner.busy
        loaded = self.source is not None
        self.left.setEnabled(idle)
        self.close_button.setEnabled(loaded)
        self.panel.setEnabled(loaded)
        self.rule_list.setEnabled(loaded)
        selected = self.rule_list.selectedItems()
        self.panel.update.setEnabled(len(selected) == 1)
        self.delete_button.setEnabled(bool(selected))
        self.clear_button.setEnabled(bool(self.rules))
        index = self.rule_list.indexOfTopLevelItem(selected[0]) if len(selected) == 1 else -1
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < len(self.rules) - 1)
        self.navigation.setEnabled(loaded and idle)
        self.page_number.setEnabled(loaded and idle)
        self.raw.setEnabled(loaded and idle)
        self.previous.setEnabled(loaded and idle and self.current_page > 1)
        self.next.setEnabled(loaded and idle and self.current_page < self.page_count)
        self.export_button.setEnabled(loaded and idle and bool(self.rules))
        self.viewer.navigation_enabled = loaded and idle
        if self.runner.busy and not self._cursor_busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            self._cursor_busy = True
        elif idle and self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False

    def _start(self, request: dict[str, Json]) -> bool:
        if self.runner.busy:
            return False
        self.timer.stop()
        self._request = {"path": str(self.source or ""), "password": self.password, **request}
        self.status.setText(f"Working: {request['operation']}…")
        return self.runner.start(self._request)

    def _scan_pages(self) -> None:
        if self.source is None or self.runner.busy:
            return
        self.timer.stop()
        pages = "all"
        while True:
            pages, accepted = QtWidgets.QInputDialog.getText(
                self, "Scan in pages", "Physical pages (all, 1,2,5-10; -1 = last):", text=pages)
            if not accepted:
                self._schedule_preview()
                return
            pages = pages.strip() or "all"
            try:
                Input.parse_index_ranges(pages, item_count=self.page_count)
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Invalid pages", str(exc))
                continue
            self._start({"operation": "scan", "pages": pages})
            return

    def _scan_current(self) -> None:
        if self.source is None or self.runner.busy:
            return
        pages = str(self.current_page)
        self._start({"operation": "scan", "pages": pages})

    def _open_dialog(self) -> None:
        self.timer.stop()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf)")
        if path:
            self.open_path(Path(path))
        else:
            self._schedule_preview()

    def _discard(self) -> bool:
        if not self.dirty:
            return True
        return QtWidgets.QMessageBox.question(self, "Unexported rules", "Discard unexported rule changes?",
            QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel) == QtWidgets.QMessageBox.StandardButton.Discard

    def open_path(self, path: Path) -> None:
        """Inspect a dropped/chosen PDF; adopt it only after successful authentication."""
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
        self.rules.clear()
        self.dirty = False
        self.revision += 1
        self.cache.clear()
        self.viewer.clear()
        self.rule_list.clear()
        self.panel.load_rule(ReplacementRule())
        self.panel.set_sources([], [])
        self.navigation.load([], [])
        self.page_number.setRange(1, 1)
        self.page_total.setText(" / 0 ")
        self.setWindowTitle("PDF Font Replace")

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

    def _select_rule(self) -> None:
        selected = self.rule_list.selectedItems()
        if len(selected) == 1:
            self.panel.load_rule(self.rules[self.rule_list.indexOfTopLevelItem(selected[0])])
        self._enabled()

    def _refresh_rules(self, selected: int = -1) -> None:
        blocker = QtCore.QSignalBlocker(self.rule_list)
        self.rule_list.clear()
        for rule in self.rules:
            item = QtWidgets.QTreeWidgetItem(list(rule.labels()))
            details = f"Pages: {rule.pages or 'all'}; ignored: {rule.ignored or 'none'}; sizes: {rule.sizes or 'all'}\nOriginal colors: {rule.source_colors or 'all'}; output color: {rule.color or 'unchanged'}"
            item.setToolTip(0, details)
            item.setToolTip(1, details)
            self.rule_list.addTopLevelItem(item)
        if 0 <= selected < len(self.rules):
            self.rule_list.setCurrentItem(self.rule_list.topLevelItem(selected))
        del blocker
        self._select_rule()

    def _rules_changed(self, selected: int = -1) -> None:
        self.revision += 1
        self.dirty = True
        self._refresh_rules(selected)
        self._schedule_preview()

    def _commit_rule(self, add: bool) -> None:
        if self.runner.busy or self.source is None:
            return
        try:
            rule = self.panel.read_rule()
            rule.compile(self.page_count)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid rule", str(exc))
            return
        selected = self.rule_list.selectedItems()
        if add:
            self.rules.append(rule)
            index = len(self.rules) - 1
        elif len(selected) == 1:
            index = self.rule_list.indexOfTopLevelItem(selected[0])
            self.rules[index] = rule
        else:
            return
        self._rules_changed(index)

    def _delete_rules(self) -> None:
        indexes = {self.rule_list.indexOfTopLevelItem(item) for item in self.rule_list.selectedItems()}
        if indexes:
            self.rules = [rule for index, rule in enumerate(self.rules) if index not in indexes]
            self._rules_changed()

    def _clear_rules(self) -> None:
        if self.rules:
            self.rules.clear()
            self._rules_changed()

    def _move_rule(self, offset: int) -> None:
        selected = self.rule_list.selectedItems()
        if len(selected) != 1:
            return
        index = self.rule_list.indexOfTopLevelItem(selected[0])
        other = index + offset
        if 0 <= other < len(self.rules):
            self.rules[index], self.rules[other] = self.rules[other], self.rules[index]
            self._rules_changed(other)

    def go_page(self, page: int) -> None:
        """Navigate a one-based physical page, retaining raw/fit choices."""
        if self.runner.busy or not 1 <= page <= self.page_count:
            return
        self.current_page = page
        self.page_number.setValue(page)
        self.navigation.select_page(page - 1)
        self._enabled()
        self._schedule_preview()

    def _schedule_preview(self, *_args: object) -> None:
        self.timer.stop()
        self.raw.setStyleSheet("QCheckBox { color: #bf6500; font-weight: bold; }" if self.raw.isChecked() else "")
        if self.source is None or self.runner.busy:
            return
        raw = self.raw.isChecked()
        cached = self.cache.get(self.current_page)
        if cached is not None:
            pixmap = cached.raw if raw else cached.result if cached.revision == self.revision else None
            if pixmap is not None:
                self._show(pixmap, cached.count, cached.recolored_runs)
                return
        self.status.setText(f"Page {self.current_page}: waiting for {'original' if raw else 'processed'} preview…")
        self.timer.start(0 if raw or not self.rules else PREVIEW_DELAY_MS)

    def _render(self) -> None:
        if QtWidgets.QApplication.activeModalWidget() is not None:
            self.timer.start(PREVIEW_DELAY_MS)
            return
        if self.source is not None and not self.runner.busy:
            self._start({"operation": "preview", "page": self.current_page, "raw": self.raw.isChecked(),
                "revision": self.revision, "rules": [rule.to_data() for rule in self.rules],
                "pixel_buffer": self.preview_buffer.name})

    def _show(self, pixmap: QtGui.QPixmap, count: int, recolored_runs: int = 0) -> None:
        self.viewer.set_pixmap(pixmap, (str(self.source), self.current_page))
        view = "Original — replacement rules are not shown" if self.raw.isChecked() else f"Processed — {self._result_summary(count, recolored_runs)}"
        self.status.setText(f"Page {self.current_page} / {self.page_count} · {view}")

    @staticmethod
    def _result_summary(count: int, recolored_runs: int) -> str:
        summary = f"{count} characters font-replaced"
        return f"{summary}; {recolored_runs} text runs recolored (font kept)" if recolored_runs else summary

    def _progress(self, message: dict[str, Json]) -> None:
        self.status.setText(f"Replacing fonts: {message.get('done', 0)} / {message.get('total', 0)} pages")

    def _completed(self, message: dict[str, Json]) -> None:
        kind = message.get("kind")
        if kind == "error":
            if message.get("code") == "password" and self._request.get("operation") == "inspect":
                password, accepted = QtWidgets.QInputDialog.getText(self, "PDF password", "Password:", QtWidgets.QLineEdit.EchoMode.Password)
                if accepted:
                    self._start({**self._request, "password": password})
                    return
            else:
                self.status.setText(str(message.get("message", "Operation failed.")))
                if self._request.get("operation") == "preview":
                    self.viewer.clear()
                QtWidgets.QMessageBox.warning(self, "PDF Font Replace", str(message.get("message")))
        elif kind == "opened":
            self._reset()
            self.source = Path(str(self._request["path"]))
            self.password = str(message.get("password", ""))
            self.page_count = int(cast(int, message["page_count"]))
            self.page_number.setRange(1, self.page_count)
            self.page_total.setText(f" / {self.page_count} ")
            self.navigation.load(cast(list[str], message["labels"]), cast(list[tuple[int, str, int]], message["bookmarks"]))
            self.setWindowTitle(f"PDF Font Replace — {self.source.name}")
            self.go_page(1)
        elif kind == "scan":
            names = cast(list[str], message["names"])
            self.panel.set_sources(names, cast(list[int], message["colors"]), cast(dict[str, str], message.get("details", {})))
            self.status.setText(f"Found {len(names)} original fonts. Select names or leave Source fonts blank for all.")
            if not names:
                self.status.setText("No fonts found in the selected pages.")
                QtWidgets.QMessageBox.warning(self, "No fonts found",
                    "No fonts were found in the selected pages.\n\n"
                    "The pages may be blank or contain only scanned images or outlined text. "
                    "Try scanning other pages or the whole PDF.")
            self._schedule_preview()
        elif kind == "fonts":
            faces = [read_face(cast(dict[str, Json], row)) for row in cast(list[Json], message["faces"])]
            self.panel.add_faces(faces)
            if faces and self._request.get("operation") == "font_file":
                self.panel.search.clear()
                self.panel.select_face(faces[0])
            self.status.setText(f"Loaded {len(faces)} font faces. Choose a target, then Add / Update.")
            self._schedule_preview()
        elif kind == "preview":
            if message.get("revision") != self.revision or message.get("page") != self.current_page:
                self._schedule_preview()
                return
            pixmap = self.preview_buffer.read(int(cast(int, message["width"])), int(cast(int, message["height"])))
            previous = self.cache.get(self.current_page) or CachedPage()
            raw = message.get("raw") is True
            count = int(cast(int, message.get("count", 0)))
            recolored_runs = int(cast(int, message.get("recolored_runs", 0)))
            cached = CachedPage(pixmap if raw else previous.raw, previous.result if raw else pixmap,
                                previous.revision if raw else self.revision, previous.count if raw else count,
                                previous.recolored_runs if raw else recolored_runs)
            self.cache.put(self.current_page, cached)
            if raw == self.raw.isChecked():
                self._show(pixmap, count, recolored_runs)
        elif kind == "exported":
            self.dirty = False
            self.status.setText(f"Saved: {message['path']}")
            summary = self._result_summary(int(cast(int, message["count"])), int(cast(int, message.get("recolored_runs", 0))))
            QtWidgets.QMessageBox.information(self, "Export complete", f"{summary}\n{message['path']}")
        elif kind == "no_matches":
            self.status.setText("No matching text; no PDF was written.")
            QtWidgets.QMessageBox.information(self, "No matching text", "No text matched these rules. No PDF was written.")
        self._enabled()

    def _export(self) -> None:
        if self.source is None or self.runner.busy or not self.rules:
            return
        self.timer.stop()
        selected = choose_pdf_output(self, self.source, self.source.with_name(f"{self.source.stem}_fonts.pdf"))
        if selected:
            output, overwrite = selected
            self._start({"operation": "export", "output": str(output), "overwrite": overwrite,
                         "rules": [rule.to_data() for rule in self.rules]})
        else:
            self._schedule_preview()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Wait for active work; release the worker and shared pixels on accepted close."""
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
    """Start the Fusion desktop UI; font/PDF imports fail before opening a window."""
    import pymupdf
    import fontTools
    import tqdm

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert isinstance(application, QtWidgets.QApplication)
    application.setStyle("Fusion")
    window = FontReplaceWindow(entry)
    window.show()
    return application.exec()
