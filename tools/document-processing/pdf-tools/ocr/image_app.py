"""Batch image OCR window using the PDF tool's recognition settings and model cache."""

from collections.abc import Callable
from pathlib import Path
import tempfile

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
from utils import Console, System, Llm
from utils.qt_widgets import NoWheelComboBox
from ..common.llm_window import LlmWindow
from .vision import OUTPUTS, SYSTEM_PROMPT, VisionTask, batch_results, document_source, vision_request
from .vision_panel import VisionPanel
from .formula_preview import FormulaPreview, preview_resources
from .exchange_view import ExchangeView
from utils.qt_widgets import install_no_wheel_controls
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.preferences import read_preferences, save_preferences, choose_save_file, dialog_directory, remember_directory
from ..common.task_buttons import TaskButtons
from ..common.viewer import PageViewer, install_preview_menu
from .image_batch import FORMATS, SUFFIXES, image_rgb
from . import local_formula
from .model import Settings
from .model_dialog import ModelDialog
from .panel import SettingsPanel


class ImageWindow(LlmWindow):
    """Apply one recognition profile to the queue and retain text for each source."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.setWindowTitle("Image to Text and Formula")
        self.resize(1160, 780)
        self._loading = self._closing = self._close_when_idle = self._running = False
        self._init_api_state()
        self._init_api_clients()
        self.queue: list[str] = []
        self.position = 0
        self.failed = 0
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
        split = QtWidgets.QSplitter()
        self.setCentralWidget(split)
        self.panel = SettingsPanel(settings, images=True)
        self.settings = self.panel.settings()
        self.panel.recognitionChanged.connect(self._settings_changed)
        self.panel.manageModelsRequested.connect(self._models)
        left = QtWidgets.QWidget()
        controls = QtWidgets.QVBoxLayout(left)
        self.mode = NoWheelComboBox()
        self.mode.addItems(["Local OCR", "Vision API — text", "Vision API — formulas / documents",
                            "Local formula — PaddleOCR"])
        controls.addWidget(self.mode)
        self.delimiter = NoWheelComboBox()
        self.delimiter.addItem("Display math: $$ … $$")
        self.delimiter.addItem(r"Display math: \[ … \]")
        controls.addWidget(self.delimiter)
        self.formula_ready = False
        self.formula_present = False
        self.formula_action = ""
        self.formula_controls = QtWidgets.QWidget()
        formula_buttons = QtWidgets.QHBoxLayout(self.formula_controls)
        formula_buttons.setContentsMargins(0, 0, 0, 0)
        self.formula_install = actions_button(formula_buttons, "Install model (99 MiB)", lambda: self._change_formula_model("download"))
        self.formula_remove = actions_button(formula_buttons, "Uninstall model", lambda: self._change_formula_model("delete"))
        controls.addWidget(self.formula_controls)
        self.formula_hint = QtWidgets.QLabel()
        self.formula_hint.setWordWrap(True)
        controls.addWidget(self.formula_hint)
        self.api_form = self._api_form(SYSTEM_PROMPT)
        self.vision_options = VisionPanel(preferences.get("vision"))
        for page in (self.vision_options.text_page, self.vision_options.formula_page):
            page.clearRequested.connect(self._clear_context)
            page.reset_each.toggled.connect(self._reset_changed)
            page.output.currentIndexChanged.connect(self._sync_preview_tab)
        self.saved_vision = self.vision_options.to_data()
        self.api_tabs = QtWidgets.QTabWidget()
        self.api_tabs.addTab(self.vision_options, "Recognition")
        self.api_tabs.addTab(self.api_form, "API settings")
        controls.addWidget(self.panel, 1)
        controls.addWidget(self.api_tabs, 1)
        self.balance_summary = QtWidgets.QLabel()
        self.balance_summary.hide()
        self.balance_summary.setParent(left)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        split.addWidget(left)
        body = QtWidgets.QWidget()
        split.addWidget(body)
        split.setSizes([350, 810])
        layout = QtWidgets.QVBoxLayout(body)
        actions = QtWidgets.QHBoxLayout()
        layout.addLayout(actions)
        self.open_button = actions_button(actions, "Add images...", self._open)
        self.paste_button = actions_button(actions, "Paste image", self._paste)
        self.paste_button.setShortcut(QtGui.QKeySequence.StandardKey.Paste)
        self.remove_button = actions_button(actions, "Remove selected", self._remove)
        self.current_button = actions_button(actions, "Recognize current", self._run_current)
        self.run_button = actions_button(actions, "Recognize all", self._run)
        self.list = QtWidgets.QTreeWidget()
        self.list.setHeaderLabels(["Image", "Pixels", "File size", "Status"])
        self.list.setRootIsDecorated(False)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.list.header().setStretchLastSection(False)
        self.list.currentItemChanged.connect(self._show)
        layout.addWidget(self.list, 1)
        self.tabs = QtWidgets.QTabWidget()
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("Select an image and run recognition to see its text.")
        self.tabs.addTab(self.text, "Recognized text")
        self.viewer = PageViewer()
        install_preview_menu(self.viewer, reset=self.viewer.fit_page,
                             fit=self.viewer.fit_page, original=self._original_image_size)
        self.tabs.addTab(self.viewer, "Image preview")
        assets, preview_hint = preview_resources()
        self.rendered = FormulaPreview(assets) if assets else None
        if self.rendered is not None:
            self.text.textChanged.connect(self._update_rendered)
            preview_tab = self.rendered
        else:
            preview_tab = QtWidgets.QLabel(preview_hint)
            preview_tab.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            preview_tab.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            preview_tab.setWordWrap(True)
        self.preview_index = self.tabs.addTab(preview_tab, "Formula preview")
        self.api_log = ExchangeView(Path(self.scratch.name))
        self.tabs.addTab(self.api_log, "API exchange")
        self.tabs.setTabVisible(self.tabs.indexOf(self.api_log), False)
        self.client.exchangePart.connect(self.api_log.record)
        self.tabs.currentChanged.connect(self._show)
        layout.addWidget(self.tabs, 2)
        output = QtWidgets.QHBoxLayout()
        layout.addLayout(output)
        self.copy = actions_button(output, "Copy current", lambda: self._copy(self._source(self.results.get(self._current_key(), ""))))
        self.copy_all = actions_button(output, "Copy all", lambda: self._copy(self._all_text()))
        self.save = actions_button(output, "Save all as TXT...", self._save)
        footer = QtWidgets.QHBoxLayout()
        layout.addLayout(footer)
        self.status = QtWidgets.QLabel("Add or drop images, or paste from the clipboard.")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.tasks = TaskButtons(self.runner, with_progress=True, external_stop=self._stop_vision)
        footer.addWidget(self.tasks)
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
        self.tabs.setTabVisible(self.tabs.indexOf(self.api_log), mode in (1, 2))
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
        self.tasks.set_external_state(self._running and not self.stopping)
        self.copy.setEnabled(bool(self.results.get(self._current_key())))
        self.copy_all.setEnabled(bool(self.results))
        self.save.setEnabled(bool(self.results))

    def _settings_changed(self) -> None:
        settings = self.panel.settings()
        if settings != self.settings:
            self.settings = settings
            self.results.clear()
            for item in self.rows.values():
                item.setText(3, "Ready")
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
            self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(item))
        self._show()

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
        if self.rendered is not None:
            self.rendered.reset_view()
        for item in self.rows.values():
            item.setText(3, "Ready")
            item.setToolTip(3, "")
        self.text.clear()
        if vision:
            self.vision_task = self.vision_options.active().task()
            self.output_format = self.vision_task.output
        else:
            self.output_format = "markdown" if self.mode.currentIndex() == 3 else "text"
        self.save.setText(f"Save as {OUTPUTS[self.output_format][0]}...")
        self.status.setText("Recognizing images...")
        if vision:
            self.api_log.reset()
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
        self.api_log.begin(", ".join(self.rows[path].text(0) for path in self.batch_paths))
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
            item.setText(3, "Failed")
            item.setToolTip(3, message["error"])
        else:
            self.results[path] = message["text"].strip()
            item.setText(3, "Recognized" if self.results[path] else "No text found")
            item.setToolTip(3, "")
        self.status.setText(f"{message['done']} / {message['total']} images")
        self.text.setPlainText(self._all_text())
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
            self.tabs.setCurrentWidget(self.text)
            if self.output_format in ("markdown", "fragment") and self.rendered is not None and self.rendered.browser is not None:
                self.rendered.display(self.text.toPlainText(), fragment=self.output_format == "fragment")
            empty = [self.rows[path].text(0) for path, text in self.results.items() if not text]
            if empty or not self.results:
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
        item = self.list.currentItem()
        key = item.data(0, QtCore.Qt.ItemDataRole.UserRole) if item else ""
        result = self._all_text()
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
            pixels = image.tobytes()
            preview = QtGui.QImage(pixels, image.width, image.height, image.width * 3, QtGui.QImage.Format.Format_RGB888)
            self.viewer.set_pixmap(QtGui.QPixmap.fromImage(preview.copy()), key)
            return True
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            self.status.setText(str(exc))
            return False

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
            text = self.text.toPlainText() if self.output_format in ("markdown", "fragment") else ""
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


def actions_button(layout: QtWidgets.QHBoxLayout, title: str, callback: Callable[[], None]) -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(title)
    button.clicked.connect(callback)
    layout.addWidget(button)
    return button


def main(entry: Path) -> int:
    """Open the image queue using the same DPI and control conventions as PDF OCR."""
    import rapidocr
    import onnxruntime

    System.enable_dpi_awareness()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    if not isinstance(app, QtWidgets.QApplication):
        raise RuntimeError("Image to Text and Formula requires a QApplication.")
    app.setStyle("Fusion")
    install_no_wheel_controls(app)
    window = ImageWindow(entry)
    window.show()
    return app.exec()
