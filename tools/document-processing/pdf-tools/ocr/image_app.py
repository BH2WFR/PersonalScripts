"""Batch image OCR window using the PDF tool's recognition settings and model cache."""

from pathlib import Path
import tempfile

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
from utils import Console, System, Llm
from utils.qt_images import copy_image_to_clipboard, qimage_from_pillow, save_png
from utils.qt_styles import on_theme_change, set_button_style, theme_text_color
from utils.qt_widgets import configure_qt_application
from ..common.llm_window import LlmWindow
from .vision import OUTPUTS, SYSTEM_PROMPT, VisionTask, batch_results, document_source, vision_request
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.preferences import read_preferences, save_preferences, choose_save_file, dialog_directory, remember_directory
from ..common.viewer import install_preview_menu
from .image_batch import FORMATS, SUFFIXES, image_rgb, read_image
from . import local_formula
from .model import Settings
from .model_dialog import ModelDialog
from .ui_image_mainwindow import Ui_ImageWindow


class ImageWindow(LlmWindow, Ui_ImageWindow):
    """Apply one recognition profile to the queue and retain text for each source."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.setupUi(self)
        self._loading = self._closing = self._close_when_idle = self._running = False
        self._init_api_state()
        self._init_api_clients()
        self.queue: list[str] = []
        self.position = 0
        self.failed = 0
        self._failed_image: str | None = None
        self.stopping = False
        self.output_format = "text"
        self.vision_task: VisionTask
        self.histories: dict[tuple[str, int], list[dict]] = {}
        self.batch_images: list[dict] = []
        self.batch_paths: list[str] = []
        self.sent_messages: list[dict] = []
        self.runner = JobRunner(entry, self)
        self.scratch = tempfile.TemporaryDirectory(prefix="image-ocr-")
        self.pastes = 0
        self.rows: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self.results: dict[str, str] = {}
        self.manager: ModelDialog | None = None
        preferences = read_preferences(self, "image-ocr")
        try:
            settings = Settings.from_data(preferences.get("settings", {}))
        except (TypeError, ValueError):
            settings = Settings()
        self.panel.configure(settings, images=True)
        self.settings = self.panel.settings()
        self.panel.recognitionChanged.connect(self._settings_changed)
        self.panel.manageModelsRequested.connect(self._models)
        self.mode.addItems(["Local OCR", "Vision API — text", "Vision API — formulas / documents",
                            "Local formula — PaddleOCR"])
        self.delimiter.addItem("Display math: $$ … $$")
        self.delimiter.addItem(r"Display math: \[ … \]")
        self.formula_ready = False
        self.formula_present = False
        self.formula_action = ""
        self.formula_install.clicked.connect(lambda: self._change_formula_model("download"))
        self.formula_remove.clicked.connect(lambda: self._change_formula_model("delete"))
        self._bind_api_form(self.api_form, SYSTEM_PROMPT)
        self.vision_options.load_modes(preferences.get("vision"))
        for page in (self.vision_options.text_page, self.vision_options.formula_page):
            page.clearRequested.connect(self._clear_context)
            page.reset_each.toggled.connect(self._reset_changed)
            page.output.currentIndexChanged.connect(self._sync_preview_tab)
        self.saved_vision = self.vision_options.to_data()
        self.balance_summary = QtWidgets.QLabel(self.left)
        self.balance_summary.hide()
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.splitter.setSizes([350, 810])
        self.open_button.clicked.connect(self._open)
        self.paste_button.clicked.connect(self._paste)
        self.paste_button.setShortcut(QtGui.QKeySequence.StandardKey.Paste)
        self.remove_button.clicked.connect(self._remove)
        self.current_button.clicked.connect(self._run_current)
        self.run_button.clicked.connect(self._run)
        on_theme_change(self.list, self._refresh_status_colors)
        self.list.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.list.header().setStretchLastSection(False)
        self.list.currentItemChanged.connect(self._show)
        self.list.customContextMenuRequested.connect(self._list_menu)
        install_preview_menu(self.viewer, reset=self.viewer.fit_page,
                             fit=self.viewer.fit_page, original=self._original_image_size)
        self.copy_image = self.viewer.addAction("Copy image", lambda: self._export_source(False))
        self.save_image = self.viewer.addAction("Save image...", lambda: self._export_source(True))
        self.rendered = self.preview_tab if self.preview_tab.root is not None else None
        if self.rendered is not None:
            self.rendered.imageReady.connect(lambda image, save: self._output_image(image, save, Path("formula.png")))
            self.rendered.exportFailed.connect(self._image_error)
        self.preview_index = self.tabs.indexOf(self.preview_tab)
        self.api_log.scratch = Path(self.scratch.name)
        self.list.itemClicked.connect(lambda: self.api_log.select_image(self._current_key()))
        self.client.exchangePart.connect(self.api_log.record)
        self.tabs.currentChanged.connect(self._show)
        self.copy.clicked.connect(lambda: self._copy(self._current_text()))
        self.copy_all.clicked.connect(lambda: self._copy(self._all_text()))
        for button in (self.copy, self.copy_all):
            set_button_style(button, "blue")
        self.save.clicked.connect(self._save)
        self.tasks.bind_runner(self.runner, with_progress=True, external_stop=self._stop_vision)
        self.drop_filter = FileDropFilter(self, self.add_file, lambda: not self.runner.busy and not self._api_busy,
                                          suffixes=SUFFIXES, multiple=True)
        self.runner.progress.connect(self._progress)
        self.runner.completed.connect(self._completed)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.controlStatus.connect(self.status.setText)
        self._mode_changed()
        self._load_api_preferences()
        self._enabled()
        if self.rendered is not None and QtGui.QGuiApplication.platformName() == "windows":
            # Attach WebEngine's compositor before show() chooses the native HWND surface.
            self.rendered.display("")

    def _mode_changed(self) -> None:
        mode = self.mode.currentIndex()
        self.panel.setVisible(mode == 0)
        self.api_tabs.setVisible(mode in (1, 2))
        self.vision_options.setCurrentWidget(self.vision_options.formula_page if mode == 2 else self.vision_options.text_page)
        self._sync_preview_tab()
        self.formula_controls.setVisible(mode == 3)
        self.formula_hint.setVisible(mode == 3)
        self.delimiter.setVisible(mode == 3)
        if mode == 3:
            hint = self._refresh_formula()
            if hint:
                QtWidgets.QMessageBox.warning(self, "Offline formula OCR", hint)
        self._enabled()

    def _sync_preview_tab(self) -> None:
        """Show the preview for formats that support local math typesetting."""
        mode = self.mode.currentIndex()
        visible = mode == 3 or (mode in (1, 2) and self.vision_options.active().output.currentData() in ("markdown", "fragment"))
        self.tabs.setTabVisible(self.preview_index, visible)

    def _refresh_formula(self) -> str:
        hint = local_formula.runtime_hint()
        try:
            model = local_formula.inventory()
            self.formula_present = bool(model.size)
            installed = model.complete
            status = ("Model installed." if installed else "Model incomplete. Select Repair model."
                      if self.formula_present else "Model not installed.")
        except (OSError, ValueError) as exc:
            self.formula_present = installed = False
            status = str(exc)
        self.formula_ready = installed and not hint
        self.formula_install.setText("Repair model" if self.formula_present else "Install model (99 MiB)")
        self.formula_hint.setText("\n".join(filter(None, ["Use one cropped formula per image.", status, hint])))
        return hint

    def _change_formula_model(self, action: str) -> None:
        if self.runner.busy or self._api_busy:
            return
        if action == "delete" and QtWidgets.QMessageBox.question(
                self, "Uninstall formula model", "Remove the downloaded LaTeX_OCR_rec model from this computer?"
                ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.formula_action = action
        if not self.runner.start({"operation": "model-" + action, "formula_models": True}):
            self.formula_action = ""


    def _current_key(self) -> str:
        item = self.list.currentItem()
        return item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item is not None else ""

    def _current_text(self) -> str:
        item = self.list.currentItem()
        return (item.data(3, QtCore.Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def _context_key(self) -> tuple[str, int]:
        return self._api_source_id(self._api_base()), self.mode.currentIndex()

    def _clear_context(self) -> None:
        self.histories.pop(self._context_key(), None)
        self._sync_api()

    def _reset_changed(self, checked: bool) -> None:
        if checked:
            self._clear_context()

    def _sync_api(self) -> None:
        if hasattr(self, "vision_options") and self.mode.currentIndex() in (1, 2):
            history = self.histories.get(self._context_key(), [])
            page = self.vision_options.active()
            page.context.setText(f"{len(history) // 2} turns · {Llm.image_count(history)} images")
            page.clear.setEnabled(bool(history))

    def _enabled(self, *_args: object) -> None:
        if not hasattr(self, "tasks"):
            return
        idle = not self.runner.busy and not self._api_busy
        self._sync_api()
        self.formula_install.setEnabled(idle)
        self.formula_remove.setEnabled(idle and self.formula_present)
        can_run = idle and (self.mode.currentIndex() != 3 or self.formula_ready)
        for widget in (self.mode, self.delimiter, self.api_tabs, self.panel, self.open_button, self.paste_button):
            widget.setEnabled(idle)
        self.remove_button.setEnabled(idle and bool(self.rows))
        self.run_button.setEnabled(can_run and bool(self.rows))
        self.current_button.setEnabled(can_run and bool(self._current_key()))
        self.copy_image.setEnabled(bool(self._current_key()))
        self.save_image.setEnabled(bool(self._current_key()))
        self.tasks.set_external_state(self._running and not self.stopping)
        self.copy.setEnabled(bool(self._current_text()))
        self.copy_all.setEnabled(bool(self.results))
        self.save.setEnabled(bool(self.results))

    def _settings_changed(self) -> None:
        settings = self.panel.settings()
        if settings != self.settings:
            self.settings = settings
            self.results.clear()
            self.api_log.forget(self.rows)
            for item in self.rows.values():
                item.setData(3, QtCore.Qt.ItemDataRole.UserRole, None)
                self._set_row_status(item, "Ready")
                item.setToolTip(3, "")
            self._show()
            save_preferences(self, "image-ocr", {"settings": settings.to_data()})

    def _models(self) -> None:
        dialog = ModelDialog(self.runner, self.runner.start, self)
        self.manager = dialog
        dialog.refresh()
        dialog.exec()
        self.manager = None
        dialog.deleteLater()
        self.panel.refresh_languages()

    def _open(self) -> None:
        pattern = " ".join("*" + ext for ext in SUFFIXES)
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add images", dialog_directory(self, "open-image"),
                                                          f"Images ({pattern})")
        for path in files:
            self.add_file(Path(path))
        if files:
            remember_directory(self, "open-image", Path(files[0]))

    def add_file(self, path: Path, label: str = "") -> None:
        """Inspect the image header and add a local file once, keeping input order."""
        try:
            key = str(path.resolve())
            if key in self.rows:
                self.list.setCurrentItem(self.rows[key])
                self.tabs.setCurrentWidget(self.viewer)
                return
            with Image.open(path, formats=FORMATS) as source:
                width, height = source.size
                if source.getexif().get(274) in (5, 6, 7, 8):
                    width, height = height, width
            size = path.stat().st_size
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.status.setText(f"Could not add {path.name}: {exc}")
            return
        item = QtWidgets.QTreeWidgetItem([label or path.name, f"{width} × {height}", Console.format_size(size), "Ready"])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
        item.setData(1, QtCore.Qt.ItemDataRole.UserRole, QtCore.QSize(width, height))
        item.setToolTip(0, label or key)
        item.setToolTip(2, f"{size:,} bytes" + (" (clipboard PNG)" if label else ""))
        self.rows[key] = item
        self.list.addTopLevelItem(item)
        self.list.setCurrentItem(item)
        self.tabs.setCurrentWidget(self.viewer)
        self._enabled()

    def _paste(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            urls = clipboard.mimeData().urls() if clipboard.mimeData() else []
            paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
            if not paths:
                self.status.setText("The clipboard contains no image.")
            for path in paths:
                self.add_file(path)
            return
        self.pastes += 1
        path = Path(self.scratch.name) / f"clipboard-{self.pastes}.png"
        if image.save(str(path)):
            self.add_file(path, f"Clipboard {self.pastes}")
        else:
            self.status.setText("Could not save the clipboard image.")

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
            self.rows.pop(key)
            self.results.pop(key, None)
            self.api_log.forget([key])
            self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))
        self._show()

    def _list_menu(self, pos: QtCore.QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is not None:
            flag = (QtCore.QItemSelectionModel.SelectionFlag.NoUpdate if item.isSelected() else
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.list.setCurrentItem(item, 0, flag)
        menu = QtWidgets.QMenu(self.list)
        menu.addAction("Add images...", self.open_button.click).setEnabled(self.open_button.isEnabled())
        menu.addAction("Paste image", self.paste_button.click).setEnabled(self.paste_button.isEnabled())
        menu.addSeparator()
        editable = item is not None and self.remove_button.isEnabled()
        menu.addAction("Delete image", self._remove).setEnabled(editable)
        menu.addAction("Rename image...", self._rename_image).setEnabled(editable)
        menu.addAction("Copy image", self.copy_image.trigger).setEnabled(item is not None)
        menu.addAction("Save image...", self.save_image.trigger).setEnabled(item is not None)
        menu.addSeparator()
        menu.addAction("Recognize current", self.current_button.click).setEnabled(item is not None and self.current_button.isEnabled())
        menu.addAction("Recognize all", self.run_button.click).setEnabled(self.run_button.isEnabled())
        menu.exec(self.list.viewport().mapToGlobal(pos))
        menu.deleteLater()

    def _rename_image(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename image", "Name in this list:", text=item.text(0))
            if ok and name.strip():
                item.setText(0, name.strip())

    def _refresh_status_colors(self) -> None:
        for item in self.rows.values():
            self._set_row_status(item, item.text(3))

    def _set_row_status(self, item: QtWidgets.QTreeWidgetItem, status: str) -> None:
        color = "green" if status == "Recognized" else "red" if status == "Failed" else None
        font = item.font(3)
        font.setBold(color is not None)
        item.setFont(3, font)
        item.setForeground(3, QtGui.QBrush(theme_text_color(color, self.list)) if color else QtGui.QBrush())
        item.setText(3, status)

    def _run(self) -> None:
        self._start_images(list(self.rows))

    def _run_current(self) -> None:
        key = self._current_key()
        if key:
            self._start_images([key])

    def _start_images(self, paths: list[str]) -> None:
        if not paths or self.runner.busy or self._api_busy:
            return
        if self.mode.currentIndex() == 3:
            self._refresh_formula()
            self._enabled()
            if not self.formula_ready:
                return
        vision = self.mode.currentIndex() in (1, 2)
        if vision:
            try:
                Llm.validate_settings(self._read_api())
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Vision API", str(exc))
                return
        self.results.clear()
        self._failed_image = None
        self.api_log.forget(paths)
        if self.rendered is not None:
            self.rendered.reset_view()
        for path in paths:
            item = self.rows[path]
            item.setData(3, QtCore.Qt.ItemDataRole.UserRole, None)
            self._set_row_status(item, "Ready")
            item.setToolTip(3, "")
        self._show()
        if vision:
            self.vision_task = self.vision_options.active().task()
            self.output_format = self.vision_task.output
        else:
            self.output_format = "markdown" if self.mode.currentIndex() == 3 else "text"
        self.save.setText(f"Save as {OUTPUTS[self.output_format][0]}...")
        self.status.setText("Recognizing images...")
        if vision:
            self.queue = paths
            self.position = self.failed = 0
            self._running = True
            self.stopping = False
            self._next_image()
        else:
            self.runner.start({"operation": "scan", "images": paths, "settings": self.settings.to_data(),
                               "local_formula": self.mode.currentIndex() == 3, "brackets": self.delimiter.currentIndex() == 1})
        self._enabled()

    def _next_image(self) -> None:
        limit = self.context_images.value()
        at_end = self.position == len(self.queue)
        limit_reached = limit > 0 and len(self.batch_images) >= limit
        if not self.stopping and self.batch_images and (at_end or limit_reached):
            self._send_batch()
            return
        if self.stopping or at_end:
            self.batch_images.clear()
            self.batch_paths.clear()
            self.sent_messages.clear()
            self._running = False
            self._completed({"kind": "cancelled", "message": "Stopped."} if self.stopping else
                            {"kind": "images-complete", "total": len(self.queue), "failed": self.failed})
            return
        path = self.queue[self.position]
        self.runner.start({"operation": "vision-image", "path": path})

    def _send_batch(self) -> None:
        self.api_log.begin(", ".join(self.rows[path].text(0) for path in self.batch_paths), self.batch_paths)
        self.api_log.select_image(self._current_key())
        try:
            settings = self._read_api()
            history = self.histories.get(self._context_key(), [])
            body = vision_request(settings, history, self.batch_images, self.vision_task)
            self.sent_messages = body["messages"][1:]
            self.client.send(settings, self.api_key.text(), body, capture=True)
        except (ValueError, RuntimeError) as exc:
            self._recognized("", 0, str(exc))

    def _stop_vision(self) -> None:
        self.stopping = True
        if self.client.reply is not None:
            self.api_log.failed("Recognition stopped.")
            self.client.cancel("Recognition stopped.")
        self._enabled()

    def _begin_api_test(self) -> bool:
        self.api_log.forget([None])
        self.api_log.begin("Vision API test", [None])
        return True

    def _client_completed(self, text: str, tokens: int, error: str) -> None:
        if self._testing:
            if error:
                self.api_log.failed(error)
            self._show_response(None)
        super()._client_completed(text, tokens, error)

    def _show_response(self, key: str | None) -> None:
        if key is not None:
            self.list.setCurrentItem(self.rows[key])
        self.tabs.setCurrentWidget(self.api_log)
        self.api_log.select_image(key)
        self.api_log.direction.setCurrentIndex(self.api_log.direction.findData("response"))
        self.api_log.body.setFocus()

    def _recognized(self, text: str, tokens: int, error: str) -> None:
        if not self._running:
            return
        if not self.stopping:
            values: list[str] = []
            if not error:
                try:
                    values = batch_results(text, len(self.batch_paths), self.vision_task)
                except ValueError as exc:
                    error = str(exc)
            if error:
                self.api_log.failed(error)
                current = self._current_key()
                self._failed_image = current if current in self.batch_paths else self.batch_paths[0]
                self._show_response(self._failed_image)
            elif not self.vision_options.active().reset_each.isChecked():
                self.histories[self._context_key()] = [*self.sent_messages, {"role": "assistant", "content": text}]
            for i, key in enumerate(self.batch_paths):
                self._vision_result(key, "" if error else values[i], error)
        self.batch_images.clear()
        self.batch_paths.clear()
        self.sent_messages.clear()
        QtCore.QTimer.singleShot(0, self._next_image)

    def _vision_result(self, path: str, text: str, error: str) -> None:
        self.failed += int(bool(error))
        self._progress({"image": path, "done": len(self.results) + self.failed + int(not error),
                        "total": len(self.queue), **({"error": error} if error else {"text": text})})

    def _progress(self, message: dict) -> None:
        if self.formula_action and "stage" in message:
            self.status.setText(str(message["stage"]))
        path = message.get("image")
        if path not in self.rows:
            return
        item = self.rows[path]
        if "error" in message:
            self.results.pop(path, None)
            self._set_row_status(item, "Failed")
            item.setToolTip(3, message["error"])
        else:
            self.results[path] = message["text"].strip()
            self._set_row_status(item, "Recognized" if self.results[path] else "No text found")
            item.setToolTip(3, "")
        self.status.setText(f"{message['done']} / {message['total']} images")
        item.setData(3, QtCore.Qt.ItemDataRole.UserRole, self._source(self.results.get(path, "")))
        if path == self._current_key():
            self.text.setPlainText(self._current_text())
        self._update_rendered()
        self._enabled()

    def _completed(self, message: dict) -> None:
        if self.formula_action:
            self.formula_action = ""
            self._refresh_formula()
            if message.get("kind") == "models":
                self.status.setText(self.formula_hint.text())
            else:
                detail = str(message.get("message", "Model operation stopped."))
                self.status.setText(detail)
                if message.get("kind") == "error":
                    QtWidgets.QMessageBox.warning(self, "Offline formula model", detail)
        elif self.manager:
            self.manager.completed(message)
        elif self._running:
            if self.stopping:
                self._next_image()
            else:
                path = self.queue[self.position]
                self.position += 1
                if message.get("kind") == "vision-image":
                    self.batch_paths.append(path)
                    self.batch_images.append(message["image"])
                else:
                    self._vision_result(path, "", str(message.get("message", "Could not read image.")))
                QtCore.QTimer.singleShot(0, self._next_image)
        elif message.get("kind") == "images-complete":
            if self._failed_image is None:
                self.tabs.setCurrentWidget(self.text)
            else:
                self._show_response(self._failed_image)
            if self.output_format in ("markdown", "fragment") and self.rendered is not None and self.rendered.browser is not None:
                self.rendered.display(self._all_text(), fragment=self.output_format == "fragment")
            empty = [self.rows[path].text(0) for path, text in self.results.items() if not text]
            if empty or (not self.results and self._failed_image is None):
                failed = message.get("failed", 0)
                detail = "No text was recognized in this run."
                if empty:
                    detail = "No text found in " + ", ".join(empty[:8])
                    if len(empty) > 8:
                        detail += f" and {len(empty) - 8} more"
                if failed:
                    reason = next((row.toolTip(3) for row in self.rows.values() if row.toolTip(3)), "")
                    detail += f"\n{failed} image(s) failed. {reason}"
                QtWidgets.QMessageBox.information(self, "No recognized text", detail)
            self.status.setText(f"Finished {message['total']} images. Failed: {message['failed']}.")
        else:
            if self.results:
                self.tabs.setCurrentWidget(self.text)
            self.status.setText(str(message.get("message", "Recognition stopped.")))
            if message.get("kind") == "error" and self.mode.currentIndex() == 3:
                QtWidgets.QMessageBox.warning(self, "Offline formula OCR", self.status.text())
        self._enabled()

    def _show(self, *_args: object) -> None:
        key = self._current_key()
        self.api_log.select_image(key)
        result = self._current_text()
        if self.text.toPlainText() != result:
            self.text.setPlainText(result)
        self._update_rendered()
        if self.tabs.currentWidget() is self.viewer:
            self.viewer.clear()
            if key:
                self._load_image_preview(key, (2048, 2048))
        self._enabled()

    def _load_image_preview(self, key: str, thumbnail: tuple[int, int] | None) -> bool:
        try:
            image = image_rgb(Path(key), thumbnail)
            self.viewer.set_pixmap(QtGui.QPixmap.fromImage(qimage_from_pillow(image)), key)
            return True
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.status.setText(str(exc))
            return False

    def _image_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Image export", message)

    def _export_source(self, save: bool) -> None:
        key = self._current_key()
        if not key:
            return
        try:
            image = qimage_from_pillow(read_image(Path(key)))
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self._image_error(str(exc))
            return
        name = Path(self.rows[key].text(0)).stem or "image"
        self._output_image(image, save, Path(name + ".png"))

    def _output_image(self, image: QtGui.QImage, save: bool, default: Path) -> None:
        if not save:
            copy_image_to_clipboard(image)
            return
        path = choose_save_file(self, "Save image", default, "PNG image (*.png)", kind="ocr-image")
        if not path:
            return
        try:
            save_png(image, path)
        except OSError as exc:
            self._image_error(str(exc))

    def _original_image_size(self) -> None:
        """Use source pixels and preserve the point at the center of the thumbnail."""
        key = self._current_key()
        bounds = self.viewer.sceneRect()
        if not key or bounds.isEmpty():
            return
        center = self.viewer.mapToScene(self.viewer.viewport().rect().center())
        source_size = self.rows[key].data(1, QtCore.Qt.ItemDataRole.UserRole)
        if bounds.size().toSize() != source_size and not self._load_image_preview(key, None):
            return
        self.viewer.actual_pixels()
        full = self.viewer.sceneRect()
        self.viewer.centerOn(center.x() * full.width() / bounds.width(), center.y() * full.height() / bounds.height())

    def _update_rendered(self) -> None:
        if self.rendered is not None and self.tabs.currentWidget() is self.rendered:
            text = self._all_text() if self.output_format in ("markdown", "fragment") else ""
            self.rendered.display(text, fragment=self.output_format == "fragment")

    def _all_text(self) -> str:
        return self._source("\n\n".join(self.results[key] for key in self.rows if self.results.get(key)))

    def _source(self, body: str) -> str:
        return document_source(body) if self.output_format == "document" else body

    def _copy(self, text: str) -> None:
        if text:
            QtWidgets.QApplication.clipboard().setText(text)

    def _save(self) -> None:
        label, ext = OUTPUTS[self.output_format]
        filename, filters = f"recognized.{ext}", f"{label} (*.{ext})"
        path = choose_save_file(self, "Save recognized text", Path(filename), filters, kind="ocr-text")
        if path:
            try:
                Path(path).write_text(self._all_text(), encoding="utf-8")
            except OSError as exc:
                self.status.setText(str(exc))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.rendered is not None and self.rendered.exporting:
            self.status.setText("Finishing image export...")
            event.ignore()
            return
        if self.runner.busy or self._api_busy:
            self.status.setText("Stop recognition or wait for it to finish before closing.")
            event.ignore()
            return
        if self._api_preferences_dirty and not self._save_api_preferences():
            event.ignore()
            return
        changed = {key: value for key, value in self.vision_options.to_data().items()
                   if value != self.saved_vision[key]}
        if changed and not save_preferences(self, "image-ocr", {"vision": changed}):
            event.ignore()
            return
        self._closing = True
        self.balance_client.cancel("Window closed.")
        self.runner.shutdown()
        self.histories.clear()
        self.scratch.cleanup()
        event.accept()


def main(entry: Path) -> int:
    """Open the image queue using the same DPI and control conventions as PDF OCR."""
    import rapidocr
    import onnxruntime

    System.enable_dpi_awareness()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if not isinstance(app, QtWidgets.QApplication):
        raise RuntimeError("Image to Text and Formula requires a QApplication.")
    configure_qt_application(app)
    window = ImageWindow(entry)
    window.show()
    return app.exec()
