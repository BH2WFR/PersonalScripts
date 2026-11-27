"""Three-column local OCR desktop with explicit recognition and cached previews."""

from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from utils import *
from utils.qt_styles import set_button_style, set_text_style
from utils.qt_widgets import configure_qt_application
from ..common.file_actions import choose_pdf_output
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.page_toolbar import set_preview_tab_order
from ..common.navigation import PAGE_ROLE
from ..common.page_cache import PageCache, pixmap_bytes
from ..common.preferences import choose_open_file, read_preferences, save_preferences, remember_directory
from ..common.preview_buffer import PreviewBuffer
from ..common.protocol import Json
from ..common.range_input import PageRangeDialog
from ..common.tooltips import TooltipFilter
from .model import Result, Settings, adjusted_result
from .panel import overlay_text
from .model_dialog import ModelDialog
from .ui_pdf_mainwindow import Ui_OcrWindow


class OcrWindow(QtWidgets.QMainWindow, Ui_OcrWindow):
    """Keep OCR results in session memory; exporting adds an invisible text layer."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.source: Path | None = None
        self.password = ""
        self.page_count = 0
        self.current_page = 1
        self.results: dict[int, Result] = {}
        self.ignored: set[int] = set()
        self._cursor_busy = False
        self._request: dict[str, Json] = {}
        self.model_dialog: ModelDialog | None = None
        self.runner = JobRunner(entry, self)
        self.runner.completed.connect(self._completed)
        self.runner.progress.connect(self._progress)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.controlChanged.connect(self._enabled)
        self.runner.controlStatus.connect(lambda text: self.status.setText(text))
        self.preview_buffer = PreviewBuffer()
        self.cache = PageCache[QtGui.QPixmap](pixmap_bytes)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._render)
        preferences = read_preferences(self, "ocr")
        try:
            self.settings = Settings.from_data(preferences.get("settings", {}))
        except (ValueError, TypeError):
            self.settings = Settings()
        self._build()
        self.settings = self.panel.settings()
        color = QtGui.QColor(str(preferences.get("color", "#dc2020")))
        if color.isValid():
            self.panel.color = color
        if isinstance(preferences.get("font"), str):
            self.panel.preview_font.fromString(preferences["font"])
            self.panel.preview_font.setPixelSize(40)
        self.panel.update_appearance()
        self.drop_filter = FileDropFilter(self, self.open_path, lambda: not self.runner.busy, suffixes=(".pdf",))
        self.tooltips = TooltipFilter(self)
        self._enabled()

    def _build(self) -> None:
        self.setupUi(self)
        self.open_button.clicked.connect(self._open_dialog)
        self.close_button.clicked.connect(self._close_pdf)
        self.panel.configure(self.settings)
        self.panel.recognitionChanged.connect(self._settings_changed)
        self.panel.manageModelsRequested.connect(self._manage_models)
        self.panel.appearanceChanged.connect(self._appearance_changed)
        self.panel.addPagesRequested.connect(self._add_ignored_pages)
        self.panel.addCurrentRequested.connect(lambda: self._set_ignored([self.current_page - 1], True))
        self.panel.removePagesRequested.connect(self._remove_ignored_pages)
        self.panel.clearPagesRequested.connect(lambda: self._set_ignored(list(self.ignored), False))
        self.panel.ignored_list.itemSelectionChanged.connect(self._enabled)
        self.scan_button.clicked.connect(self._scan)
        self.toolbar.bind_viewer(self.viewer, editable_zoom=False)
        self.toolbar.stepRequested.connect(lambda step: self.go_page(self.current_page + step))
        self.toolbar.pageRequested.connect(self.go_page)
        self.original = QtWidgets.QCheckBox("Show original")
        self.original.setToolTip("Unchecked: overlay recognized text in the preview color. No OCR runs automatically.")
        self.original.toggled.connect(self._show_cached)
        self.tool_toolbar.addWidget(self.original)
        self.text_scope.addItems(["Current page", "All recognized pages"])
        self.text_scope.currentIndexChanged.connect(self._update_text)
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("Run OCR to view and copy recognized text.")
        self.navigation.removeTab(self.navigation.indexOf(self.navigation.image_tab))
        self.navigation.pages.setHeaderLabels(["Page", "Title", "OCR"])
        self.navigation.bookmarks.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.navigation.pageRequested.connect(lambda index: self.go_page(index + 1))
        self.navigation.contextActionsRequested.connect(self._context_actions)
        self.content.setSizes([740, 250])
        self.content.setStretchFactor(0, 1)
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.task_buttons.bind_runner(self.runner, with_progress=True)
        self.export_button.clicked.connect(self._export)
        set_button_style(self.export_button, "blue")
        self.splitter.setSizes([365, 1055])
        set_preview_tab_order(self.open_button, self.close_button, self.panel, self.scan_button, self.toolbar,
                              self.tool_toolbar, self.content, self.task_buttons, self.export_button)

    def _enabled(self, *_args: object) -> None:
        if not hasattr(self, "export_button"):
            return
        idle, loaded = not self.runner.busy, self.source is not None
        self.left.setEnabled(idle)
        self.close_button.setEnabled(loaded)
        self.scan_button.setEnabled(loaded and self.current_page - 1 not in self.ignored)
        self.export_button.setEnabled(loaded and idle)
        self.panel.add_pages.setEnabled(loaded)
        self.panel.add_current.setEnabled(loaded and self.current_page - 1 not in self.ignored)
        self.panel.remove_pages.setEnabled(bool(self.panel.ignored_list.selectedItems()))
        self.panel.clear_pages.setEnabled(bool(self.ignored))
        self.navigation.setEnabled(loaded and idle)
        self.original.setEnabled(loaded and idle)
        self.toolbar.set_navigation_enabled(loaded and idle, self.current_page, self.page_count)
        working = self.runner.busy and not self.runner.paused
        if working and not self._cursor_busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            self._cursor_busy = True
        elif not working and self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False

    def _preferences(self) -> None:
        save_preferences(self, "ocr", {"settings": self.settings.to_data(),
            "color": self.panel.color.name(), "font": self.panel.preview_font.toString()})

    def _settings_changed(self) -> None:
        settings = self.panel.settings()
        if settings != self.settings:
            if settings.for_recognition() != self.settings.for_recognition():
                self.results.clear()
            self.settings = settings
            self._update_statuses()
            self._update_text()
            self._show_cached()
            self._preferences()

    def _appearance_changed(self) -> None:
        self._show_cached()
        self._preferences()

    def _manage_models(self) -> None:
        if self.runner.busy:
            return
        self.timer.stop()
        dialog = ModelDialog(self.runner, self._start, self)
        self.model_dialog = dialog
        dialog.refresh()
        dialog.exec()
        self.model_dialog = None
        dialog.deleteLater()
        self.panel.refresh_languages()
        if self.source is not None and not self._show_cached():
            self.timer.start()
        elif self.source is None:
            self.status.setText("Open or drop a PDF. OCR runs only when requested.")

    def _add_ignored_pages(self) -> None:
        """Validate a batch expression before merging it into the ignored-page list."""
        if self.source is None or self.runner.busy:
            return
        self.timer.stop()
        text = ""
        while True:
            text, accepted = PageRangeDialog.get_text(self, "Ignore pages",
                "Physical pages to add (1,2,5-10; -1 = last):", text=text)
            if not accepted:
                break
            try:
                pages = Input.parse_index_ranges(text.strip() or "none", item_count=self.page_count)
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Invalid pages", str(exc))
                continue
            self._set_ignored(list(pages), True)
            break
        if not self._show_cached():
            self.timer.start()

    def _remove_ignored_pages(self) -> None:
        """Include all selected ignored rows again without discarding OCR results."""
        self._set_ignored([int(item.data(0, PAGE_ROLE)) for item in self.panel.ignored_list.selectedItems()], False)

    def _context_actions(self, menu: QtWidgets.QMenu, tree: QtWidgets.QTreeWidget, point: QtCore.QPoint) -> None:
        if self.runner.busy:
            return
        item = tree.itemAt(point)
        if item is not None and not item.isSelected():
            tree.clearSelection()
            item.setSelected(True)
        pages = sorted({item.data(0, PAGE_ROLE) for item in tree.selectedItems()
                        if isinstance(item.data(0, PAGE_ROLE), int)})
        if not pages:
            return
        menu.addAction("Ignore selected pages", lambda: self._set_ignored(pages, True))
        menu.addAction("Include selected pages", lambda: self._set_ignored(pages, False))

    def _set_ignored(self, pages: list[int], ignored: bool) -> None:
        if self.runner.busy or self.source is None:
            return
        indexes = {index for index in pages if 0 <= index < self.page_count}
        self.ignored = self.ignored | indexes if ignored else self.ignored - indexes
        selected = {item.data(0, PAGE_ROLE) for item in self.panel.ignored_list.selectedItems()}
        with QtCore.QSignalBlocker(self.panel.ignored_list):
            self.panel.ignored_list.clear()
            for index in sorted(self.ignored):
                source_item = self.navigation.page_items[index]
                item = QtWidgets.QTreeWidgetItem([source_item.text(0), source_item.text(1)])
                item.setData(0, PAGE_ROLE, index)
                item.setToolTip(1, source_item.text(1))
                self.panel.ignored_list.addTopLevelItem(item)
                item.setSelected(index in selected)
        self._update_statuses()
        self._update_text()
        self._show_cached()
        self._enabled()

    def _update_statuses(self) -> None:
        self.navigation.set_profiles(["Ignored" if index in self.ignored else "Recognized" if index + 1 in self.results else "Not run"
                                      for index in range(self.page_count)])

    def _update_text(self, *_args: object) -> None:
        if self.text_scope.currentIndex() == 0:
            result = self.results.get(self.current_page)
            value = result.text if result is not None else ""
        else:
            value = "\n\n".join(f"--- Page {number}{' (ignored)' if number - 1 in self.ignored else ''} ---\n{result.text}"
                                   for number, result in sorted(self.results.items()))
        if value != self.text.toPlainText():
            self.text.setPlainText(value)

    def _start(self, request: dict[str, Json]) -> bool:
        if self.runner.busy:
            return False
        self.timer.stop()
        self._request = {"path": str(self.source or ""), "password": self.password,
            "settings": self.settings.to_data(),
            "ignored": Input.format_integer_ranges(Input.merge_integer_ranges(index + 1 for index in self.ignored)) or "none", **request}
        self.status.setText(f"Working: {request['operation']}...")
        return self.runner.start(self._request)

    def _open_dialog(self) -> None:
        self.timer.stop()
        selected = choose_open_file(self, "Open PDF", "PDF files (*.pdf)")
        if selected:
            self.open_path(Path(selected))
        elif self.source is not None:
            self.timer.start()

    def open_path(self, path: Path) -> None:
        """Open a dropped or selected PDF without losing the current book on failure."""
        if not self.runner.busy:
            self._start({"operation": "inspect", "path": str(path), "password": ""})

    def _reset(self) -> None:
        self.timer.stop()
        self.source = None
        self.password = ""
        self.page_count = 0
        self.current_page = 1
        self.results.clear()
        self.ignored.clear()
        self.panel.ignored_list.clear()
        self.cache.clear()
        self.viewer.clear()
        self.navigation.load([], [])
        self.text.clear()
        self.toolbar.set_page_count(0)
        self.setWindowTitle("PDF OCR")

    def _close_pdf(self) -> None:
        if self.runner.busy:
            return
        self.runner.shutdown()
        self._reset()
        self.status.setText("Open or drop a PDF.")
        self._enabled()

    def go_page(self, number: int) -> None:
        """Navigate only when idle; debounce rendering without queuing page tasks."""
        if self.runner.busy or not 1 <= number <= self.page_count:
            return
        self.current_page = number
        self.toolbar.page_number.setValue(number)
        self.navigation.select_page(number - 1)
        self._update_text()
        if not self._show_cached():
            self.viewer.clear()
            self.status.setText(f"Page {number}: waiting for preview...")
            self.timer.start()
        else:
            self.timer.stop()
        self._enabled()

    def _show_cached(self, *_args: object) -> bool:
        raw = self.cache.get(self.current_page)
        if raw is None:
            return False
        result = self.results.get(self.current_page)
        if self.original.isChecked() or result is None:
            shown = raw
        else:
            shown = overlay_text(raw, adjusted_result(result, self.settings), self.panel.preview_font, self.panel.color)
        self.viewer.set_pixmap(shown, (str(self.source), self.current_page))
        state = "Ignored" if self.current_page - 1 in self.ignored else "Not recognized" if result is None else f"{len(result.tokens)} text anchors"
        self.status.setText(f"Page {self.current_page} / {self.page_count} — {state}")
        set_text_style(self.original, "orange" if self.original.isChecked() else None)
        return True

    def _render(self) -> None:
        if self.source is None or self.runner.busy:
            return
        if QtWidgets.QApplication.activeModalWidget() is not None:
            self.timer.start()
            return
        if not self._show_cached():
            self._start({"operation": "preview", "page": self.current_page, "pixel_buffer": self.preview_buffer.name})

    def _scan(self) -> None:
        if self.source is not None and self.current_page - 1 not in self.ignored:
            self._start({"operation": "scan", "page": self.current_page})

    def _export(self) -> None:
        if self.source is None or self.runner.busy:
            return
        self.timer.stop()
        selected = choose_pdf_output(self, self.source, self.source.with_name(f"{self.source.stem}_ocr.pdf"))
        if selected:
            output, overwrite = selected
            self._start({"operation": "export", "output": str(output), "overwrite": overwrite})
        else:
            self.timer.start()

    def _store_result(self, message: dict[str, Json]) -> None:
        number = int(cast(int, message["page"]))
        self.results[number] = Result.from_data(cast(dict, message["result"]))
        if 1 <= number <= len(self.navigation.page_items):
            self.navigation.page_items[number - 1].setText(2, "Ignored" if number - 1 in self.ignored else "Recognized")
        if number == self.current_page or self.text_scope.currentIndex() == 1:
            self._update_text()

    def _progress(self, message: dict[str, Json]) -> None:
        if "result" in message:
            self._store_result(message)
        if "stage" in message:
            self.status.setText(str(message["stage"]))
        elif "done" in message:
            self.status.setText(f"Recognized {message['done']} / {message['total']} pages")

    def _completed(self, message: dict[str, Json]) -> None:
        if str(self._request.get("operation", "")).startswith("model-"):
            if self.model_dialog is not None:
                self.model_dialog.completed(message)
            self.status.setText("Model operation finished." if message.get("kind") == "models" else
                                str(message.get("message", "Model operation stopped.")))
            self._enabled()
            return
        kind = message.get("kind")
        if kind == "opened":
            self._reset()
            self.source = Path(str(self._request["path"]))
            self.password = str(message.get("password", ""))
            self.page_count = int(cast(int, message["page_count"]))
            self.toolbar.set_page_count(self.page_count)
            self.navigation.load(cast(list[str], message["labels"]), cast(list[tuple[int, str, int]], message["bookmarks"]))
            remember_directory(self, "open-pdf", self.source)
            self.setWindowTitle(f"PDF OCR — {self.source.name}")
            self._update_statuses()
            self.go_page(1)
        elif kind == "preview":
            number = int(cast(int, message["page"]))
            pixmap = self.preview_buffer.read(int(cast(int, message["width"])), int(cast(int, message["height"])))
            self.cache.put(number, pixmap)
            self._show_cached()
        elif kind == "recognized":
            self._store_result(message)
            self.original.setChecked(False)
            if not self._show_cached():
                self.timer.start()
        elif kind == "exported":
            self._show_cached()
            self.status.setText(f"Saved: {message['path']}")
            QtWidgets.QMessageBox.information(self, "OCR complete", f"Added {message['count']} invisible text anchors.\n{message['path']}")
        elif kind == "cancelled":
            self._show_cached()
            self.status.setText("Stopped. Completed OCR results remain available.")
        elif kind == "error":
            text = str(message.get("message", "Operation failed."))
            self.status.setText(text)
            if message.get("code") == "password" and self._request.get("operation") == "inspect":
                password, accepted = QtWidgets.QInputDialog.getText(self, "PDF password", "Password:", QtWidgets.QLineEdit.EchoMode.Password)
                if accepted:
                    self._start({**self._request, "password": password})
            else:
                QtWidgets.QMessageBox.warning(self, "PDF OCR", text)
        self._enabled()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Wait for active work and release the worker before releasing shared pixels."""
        if self.runner.busy:
            self.status.setText("Stop the task or wait for it to finish before closing.")
            event.ignore()
            return
        self.timer.stop()
        self._preferences()
        self.runner.shutdown()
        self.preview_buffer.close()
        self.cache.clear()
        event.accept()


def main(entry: Path) -> int:
    """Check dependencies before opening a Fusion GUI with native high-DPI support."""
    import pymupdf
    import fontTools
    import rapidocr
    import onnxruntime

    System.enable_dpi_awareness()
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert isinstance(application, QtWidgets.QApplication)
    configure_qt_application(application)
    window = OcrWindow(entry)
    window.show()
    return application.exec()
