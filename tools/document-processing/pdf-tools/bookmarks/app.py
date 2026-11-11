"""Compact PySide6 GUI for TOC recognition, YAML drafts, bookmark trees and page tags.

MuPDF runs in one serial subprocess; HTTP uses cancellable Qt network requests.
Recognition is explicit and one page at a time. Drafts and crop geometry stay in memory; only edited PDFs are saved.
Problems pause the queue on the current page; Information collects clarification
before an explicit retry resumes the remaining pages.
"""

from dataclasses import asdict, replace
import datetime
from pathlib import Path
import sys
from typing import Callable, cast

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls

from utils import *
from ..common.bookmark_editor import BookmarkEditor, OutlineRow
from ..common.crop_viewer import CropViewer, Rectangle
from ..common.file_drop import FileDropFilter
from ..common.file_actions import choose_pdf_output
from ..common.tooltips import TooltipFilter
from ..common.jobs import JobRunner
from ..common.task_buttons import TaskButtons
from ..common.preferences import choose_open_file, remember_directory, report_config_error
from ..common.protocol import Json
from ..common.page_cache import PageCache, pixmap_bytes
from ..common.navigation import PageTree
from ..common.preview_buffer import PreviewBuffer
from ..common.range_input import RangeInput
from .recognition import SYSTEM_PROMPT, build_request
from .model import MAX_DRAFT, Bookmark, BookSession, ConversationTurn, NeedsInformation, Status, TocPage

STATUS_COLORS: dict[Status, str] = {
    Status.PENDING: "#1769c2", Status.DONE: "#16803c", Status.MODIFIED: "#16803c",
    Status.ERROR: "#c02020", Status.NEEDS_INFO: "#c02020",
}

class BookmarksWindow(QtWidgets.QMainWindow):
    """Own a single book and its ordered recognition queue, with explicit PDF export."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.session: BookSession | None = None
        self.password = ""
        self.dirty = False
        self._loading = False
        self._api_source_base = ""
        self._api_preferences_dirty = False
        self._api_source_dirty = False
        self._api_profiles = LlmProfiles()
        self._api_loaded = False
        self._source: Path | None = None
        self._running = False
        self._queue_pause_requested = False
        self._recognition_paused = False
        self._problem_page: int | None = None
        self._after_export: Callable[[], object] | None = None
        self._testing = False
        self._fetching = False
        self._test_elapsed = QtCore.QElapsedTimer()
        self._queue: list[int] = []
        self._queue_total = 0
        self._queue_done = 0
        self._active: int | None = None
        self._pending_turn: ConversationTurn | None = None
        self._pending_recognition: Callable[[], None] | None = None
        self._retry_run = False
        self._last_image_count = 0
        self._purpose = ""
        self._shown: tuple[int, float] | None = None
        self._closing = False
        self._close_when_idle = False
        self._cursor_busy = False
        self._undo: list[list[Bookmark]] = []
        self.runner = JobRunner(entry, self)
        self.preview_buffer = PreviewBuffer()
        self.preview_cache = PageCache[tuple[float, QtGui.QPixmap]](lambda frame: pixmap_bytes(frame[1]))
        self.client = Llm.create_qt_client(self)
        self.balance_client = Llm.create_qt_client(self)
        self._balance_identity: tuple[str, str] | None = None
        self.balance_client.balanceCompleted.connect(self._balance_completed)
        self.runner.completed.connect(self._completed)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.controlChanged.connect(self._enabled)
        self.runner.controlStatus.connect(lambda text: self.status.setText(text))
        self.runner.progress.connect(lambda message: self.status.setText(str(message.get("stage", "Processing..."))))
        self.client.completed.connect(self._client_completed)
        self.client.modelsCompleted.connect(self._models_completed)
        self.draft_timer = QtCore.QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(400)
        self.draft_timer.timeout.connect(self._apply_yaml)
        self.setWindowTitle("PDF Bookmark Editor")
        self.resize(1500, 950)
        self.setMinimumSize(1050, 650)
        self._build()
        self.tooltips = TooltipFilter(self)
        self.setAcceptDrops(True)
        self.file_drops = FileDropFilter(self, self.open_path, lambda: not self._api_busy and not self.runner.busy, suffixes=(".pdf",))
        self._enabled()

    def _button(self, text: str, callback: Callable[[], object]) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _spin(self, low: int, high: int, value: int = 1) -> QtWidgets.QSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def _build(self) -> None:
        splitter = QtWidgets.QSplitter()
        self.setCentralWidget(splitter)
        self.left = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(self.left)
        left.setContentsMargins(6, 6, 6, 6)
        self.files = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.files)
        row.setContentsMargins(0, 0, 0, 0)
        for text, action in (("Open PDF", self._open_dialog),):
            row.addWidget(self._button(text, action))
        self.close_pdf_button = self._button("Close", self._close_pdf)
        row.addWidget(self.close_pdf_button)
        left.addWidget(self.files)
        self.tabs = QtWidgets.QTabWidget()
        recognition = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(recognition)
        self.toc_first = self._spin(1, 1)
        self.toc_last = self._spin(1, 1)
        self.body_pdf = self._spin(1, 1)
        self.body_book = self._spin(1, 1_000_000)
        self.current_page_buttons: list[QtWidgets.QPushButton] = []
        for text, spin in (("First TOC PDF page", self.toc_first), ("Last TOC PDF page", self.toc_last),
                           ("First body PDF page", self.body_pdf)):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(spin, 1)
            button = self._button("Use current", lambda _checked=False, target=spin: self._use_current_page(target))
            button.setToolTip("Fill this field with the currently displayed physical PDF page.")
            self.current_page_buttons.append(button)
            row.addWidget(button)
            form.addRow(text, row)
        form.addRow("Its printed page number", self.body_book)
        self.body_pdf.editingFinished.connect(self._mapping_changed)
        self.body_book.editingFinished.connect(self._mapping_changed)
        mark_toc_button = self._button("Mark TOC", self._mark_toc)
        primary_button_font = mark_toc_button.font()
        primary_button_font.setBold(True)
        mark_toc_button.setFont(primary_button_font)
        toc_actions = QtWidgets.QHBoxLayout()
        toc_actions.addWidget(mark_toc_button)
        self.clear_toc_button = self._button("Clear TOC", self._clear_toc)
        self.clear_toc_button.setToolTip("Clear all TOC tasks and recognition settings; keep existing bookmarks.")
        toc_actions.addWidget(self.clear_toc_button)
        form.addRow(toc_actions)
        self.angle = NoWheelDoubleSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setDecimals(1)
        self.angle.setSuffix(" °")
        self.angle.setKeyboardTracking(False)
        self.angle.editingFinished.connect(self._rotation_changed)
        form.addRow("Current TOC rotation", self.angle)
        crop_row = QtWidgets.QHBoxLayout()
        self.draw_crop = QtWidgets.QCheckBox("Draw recognition box")
        self.draw_crop.toggled.connect(self._enabled)
        crop_row.addWidget(self.draw_crop)
        crop_row.addWidget(self._button("Whole page", self._whole_page))
        crop_row.addWidget(self._button("Unmark", self._unmark_toc))
        form.addRow(crop_row)
        self.requirement_scope = NoWheelComboBox()
        self.requirement_scope.addItems(["Whole book", "Current TOC page"])
        self.requirement_scope.currentIndexChanged.connect(self._load_requirements)
        self.requirements = QtWidgets.QPlainTextEdit()
        self.requirements.setPlaceholderText("Transcription requirements or retry corrections (whole book / current page)")
        self.requirements.setMaximumHeight(105)
        self.requirements.textChanged.connect(self._requirements_changed)
        form.addRow(self.requirement_scope)
        form.addRow(self.requirements)
        self.clear_context = QtWidgets.QCheckBox("Clear conversation before this run / retry")
        self.clear_context.setToolTip("Clear previous LLM exchanges once before the queue starts. Keeps recognized results, drafts and your requirements. Current-page diagnostics still accompany retries.")
        self.only_pending = QtWidgets.QCheckBox("Run only pending / failed pages")
        self.only_pending.setChecked(True)
        self.append_existing = QtWidgets.QCheckBox("Keep existing PDF bookmarks")
        self.append_existing.setToolTip("Keep original bookmarks alongside recognized entries when applying YAML.")
        for check in (self.clear_context, self.only_pending, self.append_existing):
            form.addRow(check)
            check.toggled.connect(self._options_changed)
        outline_actions = QtWidgets.QHBoxLayout()
        outline_actions.addWidget(self._button("Add Cover + TOC", self._add_roots))
        outline_actions.addWidget(self._button("Clear bookmarks", self._clear_bookmarks))
        outline_actions.addWidget(self._button("Undo", self._undo_bookmarks))
        form.addRow(outline_actions)
        recognition_scroll = QtWidgets.QScrollArea()
        recognition_scroll.setWidgetResizable(True)
        recognition_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        recognition_scroll.setWidget(recognition)
        self.tabs.addTab(recognition_scroll, "Recognition")

        api = QtWidgets.QWidget()
        settings = QtWidgets.QFormLayout(api)
        settings.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        api_actions = QtWidgets.QHBoxLayout()
        self.save_api_button = self._button("Save", self._save_api_preferences)
        self.load_api_button = self._button("Load", self._load_api_preferences)
        self.save_api_button.setToolTip("Save all changed source settings to llm.yaml. Closing this window also saves them.")
        self.load_api_button.setToolTip("Reload llm.yaml, replacing unsaved API drafts for all sources.")
        api_actions.addWidget(self.save_api_button)
        api_actions.addWidget(self.load_api_button)
        settings.addRow(api_actions)
        self.api_config_status = QtWidgets.QLabel("API settings are loaded at startup; Save or close this window to write changes.")
        self.api_config_status.setWordWrap(True)
        settings.addRow(self.api_config_status)
        self.api_url = NoWheelComboBox()
        self.api_url.setEditable(True)
        self.api_url.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.api_url.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.api_url.setMinimumContentsLength(20)
        for name, url in Llm.PRESETS:
            self.api_url.addItem(name, url)
        self.api_url.setEditText(LlmSettings().base_url)
        self.api_url.setToolTip("Select a provider or custom URL. Switching sources restores its in-memory draft; Save commits all changed sources.")
        self.api_model = NoWheelComboBox()
        self.api_model.setEditable(True)
        self.api_model.addItems(["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"])
        self.api_model.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.api_model.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.api_model.setMinimumContentsLength(20)
        self.api_key = QtWidgets.QLineEdit()
        self.api_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Saved encrypted in user configuration")
        api_defaults = LlmSettings()
        self.temperature = NoWheelDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(.1)
        self.temperature.setValue(api_defaults.temperature)
        self.max_tokens = self._spin(1, 65536, api_defaults.max_tokens)
        self.timeout = self._spin(5, 1800, api_defaults.timeout_seconds)
        self.context_images = self._spin(0, 10000, api_defaults.max_context_images)
        self.context_images.setSpecialValueText("0 — unlimited")
        self.context_images.setToolTip("Maximum images in each request, including the current page. Keeps the newest images; older image parts are omitted but text/replies remain. Use 5 for a five-image model, 1 for only the current image, or 0 for no limit.")
        self.reasoning_effort = NoWheelComboBox()
        self.reasoning_effort.setToolTip("Saved per API source. Enabled uses the provider's default effort (medium for generic compatible APIs). Server default sends no reasoning controls. Available levels vary by API and model; generic options are not a guarantee of model support. The API test uses this selected reasoning mode.")
        self._refresh_reasoning_options(api_defaults.reasoning_effort)
        self.skip_certificate_verification = QtWidgets.QCheckBox("Skip certificate verification")
        self.skip_certificate_verification.setToolTip("Off by default. Applies to HTTPS recognition, API tests, model lists and balances for this source. HTTP local servers work without enabling this. Enabling skips certificate and hostname checks.")
        self.fetch_button = self._button("Get models", self._fetch_models)
        self.fetch_button.setToolTip("Request the provider's model catalog with this key. No PDF content is sent; select a vision-capable model.")
        model_row = QtWidgets.QHBoxLayout()
        model_row.addWidget(self.api_model, 1)
        model_row.addWidget(self.fetch_button)
        settings.addRow("API preset / URL", self.api_url)
        settings.addRow("Model", model_row)
        self.vision_models_only = QtWidgets.QCheckBox("Vision models only (strict)")
        self.vision_models_only.setToolTip("Get models includes only models explicitly reporting image input. Unknown capabilities are excluded; image-generation-only models are excluded. Some APIs do not publish this metadata.")
        self.vision_models_only.toggled.connect(self._model_filter_changed)
        settings.addRow(self.vision_models_only)
        self.models_status = QtWidgets.QLabel("Get models or enter a vision model name. Local servers may leave API key empty.")
        self.models_status.setWordWrap(True)
        settings.addRow(self.models_status)
        for label, widget in (("API key", self.api_key),
                              ("Temperature", self.temperature), ("Max output tokens", self.max_tokens),
                              ("Timeout (seconds)", self.timeout), ("Context images", self.context_images)):
            settings.addRow(label, widget)
        settings.addRow("Reasoning effort", self.reasoning_effort)
        self.reset_api_parameters_button = self._button("Reset parameters", self._reset_api_parameters)
        self.reset_api_parameters_button.setToolTip("Restore default temperature, output-token limit, timeout, context-image limit and reasoning effort for this source. Save or close to persist.")
        settings.addRow(self.reset_api_parameters_button)
        settings.addRow(self.skip_certificate_verification)
        self.balance_key = QtWidgets.QLineEdit()
        self.balance_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.balance_key.setPlaceholderText("Optional; defaults to API key")
        self.balance_key.setToolTip("OpenRouter account balance requires a management key. Used only for balance queries; never for recognition.")
        settings.addRow("Balance key", self.balance_key)
        self.balance_button = self._button("Refresh API balance", self._refresh_balance)
        settings.addRow(self.balance_button)
        self.balance_status = QtWidgets.QLabel("Enter an API key to display the account balance.")
        self.balance_status.setWordWrap(True)
        self.balance_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        settings.addRow(self.balance_status)
        self.usage = QtWidgets.QLabel("Context: no request yet")
        self.usage.setWordWrap(True)
        settings.addRow(self.usage)
        self.test_button = self._button("Test API (small image)", self._test_api)
        self.test_button.setToolTip("Send a generated color square to verify credentials, model and image input. No PDF content is sent.")
        settings.addRow(self.test_button)
        self.test_status = QtWidgets.QLabel("API not tested")
        self.test_status.setWordWrap(True)
        self.test_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        settings.addRow(self.test_status)
        settings.addRow(self._button("Copy system prompt", lambda: QtWidgets.QApplication.clipboard().setText(SYSTEM_PROMPT)))
        self._previous_api_url = LlmSettings().base_url
        self.api_url.activated.connect(self._select_api_preset)
        self.api_url.currentTextChanged.connect(self._endpoint_changed)
        api_url_editor = self.api_url.lineEdit()
        assert api_url_editor is not None
        api_url_editor.editingFinished.connect(self._refresh_balance)
        for key_field in (self.api_key, self.balance_key):
            key_field.textChanged.connect(self._invalidate_balance)
            key_field.textChanged.connect(self._api_changed)
            key_field.editingFinished.connect(self._refresh_balance)
        self.api_model.currentTextChanged.connect(self._api_changed)
        self.temperature.valueChanged.connect(self._api_changed)
        self.max_tokens.valueChanged.connect(self._api_changed)
        self.timeout.valueChanged.connect(self._api_changed)
        self.context_images.valueChanged.connect(self._api_changed)
        self.reasoning_effort.currentIndexChanged.connect(self._api_changed)
        self.skip_certificate_verification.toggled.connect(self._api_changed)
        self.skip_certificate_verification.toggled.connect(self._invalidate_balance)
        api_scroll = QtWidgets.QScrollArea()
        api_scroll.setWidgetResizable(True)
        api_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        api_scroll.setWidget(api)
        self.tabs.addTab(api_scroll, "API")

        labels = QtWidgets.QWidget()
        label_form = QtWidgets.QFormLayout(labels)
        self.label_range = QtWidgets.QLineEdit()
        self.label_range.setPlaceholderText("1,2,5-10,-1; append |odd or |even")
        self.label_first = self._spin(-1_000_000, 1_000_000)
        self.label_prefix = QtWidgets.QLineEdit()
        self.label_range_input = RangeInput(self.label_range)
        label_form.addRow("PDF pages", self.label_range_input)
        label_form.addRow("Starting number", self.label_first)
        label_form.addRow("Prefix", self.label_prefix)
        label_buttons = QtWidgets.QGridLayout()
        for index, (text, callback) in enumerate((
                ("Apply numbered labels", self._label_numbered),
                ("Clear selected labels", self._label_clear),
                ("Clear all labels", lambda: self._label_clear(True)))):
            label_buttons.addWidget(self._button(text, callback), index // 2, index % 2)
        generate_labels = self._button("Generate TOC + body labels", self._label_generate)
        generate_labels.setFont(primary_button_font)
        label_buttons.addWidget(generate_labels, 1, 1)
        label_buttons.setColumnStretch(0, 1)
        label_buttons.setColumnStretch(1, 1)
        label_form.addRow(label_buttons)
        label_note = QtWidgets.QLabel("Navigation labels only; printed page content stays unchanged.")
        label_note.setWordWrap(True)
        label_form.addRow(label_note)
        self.labels_tab = labels
        self.tabs.addTab(labels, "Page labels")
        left.addWidget(self.tabs)

        actions = QtWidgets.QHBoxLayout()
        self.run_button = self._button("Run TOC", lambda: self._request_recognition(self._run_all))
        self.run_button.setFont(primary_button_font)
        self.retry_button = self._button("Retry page", lambda: self._request_recognition(self._retry))
        self.retry_all_button = self._button("Retry all", lambda: self._request_recognition(self._retry_all))
        self.retry_all_button.setToolTip("Resend every marked TOC page in page order, even accepted pages. Ignores the pending-only checkbox; each reply replaces only its source page's results.")
        for button in (self.run_button, self.retry_button, self.retry_all_button):
            # Receive mouse clicks before committing the focused editor. Its
            # focus-out may start a render and disable this button mid-click.
            # Tab focus keeps keyboard activation available.
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.TabFocus)
            actions.addWidget(button)
        left.addLayout(actions)
        self.yaml_label = QtWidgets.QLabel("YAML draft — current TOC page")
        left.addWidget(self.yaml_label)
        self.yaml = QtWidgets.QPlainTextEdit()
        self.yaml.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        editor_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        if sys.platform == "win32":
            editor_font.setFamilies(["Consolas", editor_font.family()])
        editor_font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self.yaml.setFont(editor_font)
        self.yaml.setPlaceholderText('- {page: 1, level: 1, index: "", title: "Introduction"}')
        self.yaml.textChanged.connect(self._yaml_changed)
        self.result_tabs = QtWidgets.QTabWidget()
        self.result_tabs.addTab(self.yaml, "YAML draft")
        self.trace = QtWidgets.QPlainTextEdit()
        self.trace.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.trace.setReadOnly(True)
        self.trace.setPlaceholderText("Request settings, problems and original replies for this page appear here. Kept in memory only.")
        self.result_tabs.addTab(self.trace, "Request / errors")
        self.information_tab = QtWidgets.QWidget()
        information_layout = QtWidgets.QVBoxLayout(self.information_tab)
        self.information_status = QtWidgets.QLabel("No page selected.")
        self.information_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.information_status.setWordWrap(True)
        information_layout.addWidget(self.information_status)
        self.information = QtWidgets.QPlainTextEdit()
        self.information.setReadOnly(True)
        self.information.setPlaceholderText("Questions, requested information and errors for this page.")
        information_layout.addWidget(self.information, 1)
        information_layout.addWidget(QtWidgets.QLabel("Additional instructions for this page"))
        self.information_input = QtWidgets.QPlainTextEdit()
        self.information_input.setPlaceholderText("Answer the questions above or correct this page's instructions. Connection errors can be retried without an answer.")
        self.information_input.setMaximumHeight(100)
        self.information_input.textChanged.connect(self._information_changed)
        information_layout.addWidget(self.information_input)
        self.information_retry = self._button("Retry page", self._retry_information)
        information_layout.addWidget(self.information_retry)
        self.result_tabs.addTab(self.information_tab, "Information")
        left.addWidget(self.result_tabs, 1)
        self.yaml_status = QtWidgets.QLabel("Valid YAML updates the tree. Export uses the tree.")
        self.yaml_status.setWordWrap(True)
        self.yaml_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.yaml_status.setMaximumHeight(65)
        left.addWidget(self.yaml_status)
        self.yaml_actions = QtWidgets.QWidget()
        yaml_actions = QtWidgets.QHBoxLayout(self.yaml_actions)
        yaml_actions.setContentsMargins(0, 0, 0, 0)
        yaml_actions.addWidget(self._button("Apply YAML", self._apply_yaml))
        self.supplement_button = self._button("Add page information", self._supplement)
        yaml_actions.addWidget(self.supplement_button)
        yaml_actions.addWidget(self._button("Copy recognition image", self._copy_image))
        left.addWidget(self.yaml_actions)
        self.result_tabs.currentChanged.connect(self._result_tab_changed)
        splitter.addWidget(self.left)

        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(3, 6, 6, 6)
        toolbar = QtWidgets.QToolBar()
        self.previous = toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowBack),
                                          "Previous page", lambda: self._step(-1))
        self.next = toolbar.addAction(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ArrowForward),
                                      "Next page", lambda: self._step(1))
        self.page_number = self._spin(1, 1)
        self.page_number.setFixedWidth(55)
        self.page_number.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_number.editingFinished.connect(lambda: self.go_page(self.page_number.value()))
        toolbar.addWidget(self.page_number)
        self.page_total = QtWidgets.QLabel(" / 0 ")
        toolbar.addWidget(self.page_total)
        toolbar.addSeparator()
        self.viewer = CropViewer()
        self.viewer.pageStepRequested.connect(self._step)
        self.viewer.cropChanged.connect(self._crop_changed)
        toolbar.addAction("Fit page", self.viewer.fit_page)
        toolbar.addAction("Fit width", self.viewer.fit_width)
        toolbar.addAction("100%", self.viewer.actual_pixels)
        self.zoom = NoWheelDoubleSpinBox()
        self.zoom.setRange(2.5, 1600)
        self.zoom.setSuffix(" %")
        self.zoom.setFixedWidth(85)
        self.zoom.setKeyboardTracking(False)
        self.zoom.editingFinished.connect(lambda: self.viewer.set_zoom(self.zoom.value()))
        self.viewer.zoomChanged.connect(self.zoom.setValue)
        toolbar.addWidget(self.zoom)
        layout.addWidget(toolbar)
        content = QtWidgets.QSplitter()
        content.addWidget(self.viewer)
        self.navigation = QtWidgets.QTabWidget()
        self.tree = BookmarkEditor(editable=True, show_level=True,
                                   current_page=lambda: self.session.current_page if self.session else 1)
        self.tree.changed.connect(self._tree_changed)
        self.tree.pageRequested.connect(lambda index: self.go_page(index + 1))
        self.pages = PageTree()
        self.pages.pageRequested.connect(lambda index: self.go_page(index + 1))
        self.pages.setToolTip("Click or use arrow/PgUp/PgDn keys to turn pages. Ctrl/Shift selects multiple pages.")
        self.pages.setHeaderLabels(["Page", "Label", "TOC task"])
        self.pages.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pages.itemClicked.connect(self._page_clicked)
        self.pages.itemSelectionChanged.connect(self._enabled)
        self.page_toc_action = QtGui.QAction("This page is TOC", self.pages)
        self.page_toc_action.setCheckable(True)
        self.page_toc_action.triggered.connect(self._toggle_selected_toc)
        self.pages.addAction(self.page_toc_action)
        self.page_mapping_actions: list[QtGui.QAction] = []
        for text, target in (("Set as first TOC PDF page", self.toc_first),
                             ("Set as last TOC PDF page", self.toc_last),
                             ("Set as first body PDF page...", self.body_pdf)):
            action = QtGui.QAction(text, self.pages)
            action.triggered.connect(lambda _checked=False, spin=target: self._set_selected_page(spin))
            self.pages.addAction(action)
            self.page_mapping_actions.append(action)
        self.page_mapping_separator = QtGui.QAction(self.pages)
        self.page_mapping_separator.setSeparator(True)
        self.pages.addAction(self.page_mapping_separator)
        self.edit_label_action = QtGui.QAction("Edit label...", self.pages)
        self.edit_label_action.triggered.connect(lambda: self._page_labels())
        self.pages.addAction(self.edit_label_action)
        self.clear_label_action = QtGui.QAction("Clear label", self.pages)
        self.clear_label_action.triggered.connect(lambda: self._page_labels(clear=True))
        self.pages.addAction(self.clear_label_action)
        label_separator = QtGui.QAction(self.pages)
        label_separator.setSeparator(True)
        self.pages.addAction(label_separator)
        self.delete_pages_action = QtGui.QAction("Delete selected pages...", self.pages)
        self.delete_pages_action.setShortcut(QtGui.QKeySequence.StandardKey.Delete)
        self.delete_pages_action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.delete_pages_action.triggered.connect(self._delete_pages)
        self.pages.addAction(self.delete_pages_action)
        self.pages.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)
        pages_panel = QtWidgets.QWidget()
        pages_layout = QtWidgets.QVBoxLayout(pages_panel)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        pages_layout.addWidget(self.pages)
        self.delete_pages_button = self._button("Delete selected pages...", self._delete_pages)
        pages_layout.addWidget(self.delete_pages_button)
        self.navigation.addTab(self.tree, "Bookmarks")
        self.navigation.addTab(pages_panel, "Pages")
        content.addWidget(self.navigation)
        content.setStretchFactor(0, 1)
        content.setSizes([650, 320])
        layout.addWidget(content, 1)
        footer = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("Open or drop a PDF.")
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        footer.addWidget(self.status, 1)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedWidth(180)
        self.progress_bar.setVisible(False)
        footer.addWidget(self.progress_bar)
        self.balance_summary = QtWidgets.QLabel("API balance: not queried")
        self.balance_summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.task_buttons = TaskButtons(self.runner, external_pause=self._toggle_queue_pause, external_stop=self._stop)
        self.pause_button = self.task_buttons.pause_button
        self.stop_button = self.task_buttons.stop_button
        footer.addWidget(self.task_buttons)
        footer.addWidget(self.balance_summary)
        self.export_button = self._button("Export PDF", self._export)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
        splitter.addWidget(right)
        splitter.setSizes([420, 1080])
        if self._api_loaded:
            self._show_api_profiles()
        else:
            self._load_api_preferences()

    @staticmethod
    def _api_source_id(base: str) -> str:
        try:
            return Llm.source_id(base)
        except ValueError:
            return ""

    def _api_config_feedback(self, text: str, error: Exception | None = None) -> None:
        self.api_config_status.setText(text)
        self.api_config_status.setToolTip(text)
        self.api_config_status.setStyleSheet("color: #c02020;" if error else "")
        if error is not None:
            report_config_error(self.api_config_status, error)

    def _load_api_preferences(self, *_args: object) -> bool:
        try:
            profiles = Llm.load_profiles()
        except (OSError, ValueError) as exc:
            self._api_config_feedback(f"Load failed: {exc}", exc)
            return False
        self._api_profiles = profiles
        self._api_loaded = True
        self._show_api_profiles()
        self._api_config_feedback("LLM settings loaded. Editing and switching sources do not write to disk.")
        self._invalidate_balance()
        self._sync_api()
        return True

    def _show_api_profiles(self) -> None:
        self._loading = True
        self.api_url.clear()
        for name, base in self._api_profiles.providers():
            self.api_url.addItem(name, base)
        self.api_url.setEditText(self._api_profiles.active_source)
        self._loading = False
        self._load_api_source(self._api_base())
        self._api_preferences_dirty = bool(self._api_profiles.changed)

    def _add_api_source_option(self, base: str) -> None:
        source_id = self._api_source_id(base)
        if source_id and not any(self._api_source_id(str(self.api_url.itemData(index))) == source_id
                                 for index in range(self.api_url.count())):
            self.api_url.addItem(base, base)

    def _load_api_source(self, base: str) -> None:
        source_id = self._api_source_id(base)
        profile = self._api_profiles.get_api(base) if source_id else LlmProfile(LlmSettings(base_url=base))
        values = asdict(profile.settings)
        values.update(api_key=profile.api_key, balance_key=profile.balance_key)
        self._loading = True
        try:
            self.api_model.clear()
            fields = {"model": self.api_model, "api_key": self.api_key,
                      "balance_key": self.balance_key, "temperature": self.temperature,
                      "max_tokens": self.max_tokens, "timeout_seconds": self.timeout,
                      "max_context_images": self.context_images}
            for name, widget in fields.items():
                value = values[name]
                if isinstance(widget, QtWidgets.QComboBox) and isinstance(value, str):
                    widget.setCurrentText(value)
                elif isinstance(widget, QtWidgets.QLineEdit) and isinstance(value, str):
                    widget.setText(value)
                elif isinstance(widget, QtWidgets.QDoubleSpinBox) and type(value) in (int, float):
                    widget.setValue(value)
                elif isinstance(widget, QtWidgets.QSpinBox) and type(value) is int:
                    widget.setValue(value)
            self._refresh_reasoning_options(profile.settings.reasoning_effort)
            self.skip_certificate_verification.setChecked(profile.settings.skip_certificate_verification)
            self._api_source_base = base if source_id else ""
            self._previous_api_url = base
            self._api_source_dirty = False
        finally:
            self._loading = False

    def _capture_api_source(self, *, force: bool = False) -> None:
        """Keep outgoing fields in memory, even after the URL widget has changed."""
        if self._loading or not self._api_source_base or not (force or self._api_source_dirty):
            return
        settings = replace(self._read_api(), base_url=self._api_source_base)
        self._api_profiles.set_api(settings, self.api_key.text(), self.balance_key.text())

    def _save_api_preferences(self, *_args: object) -> bool:
        if self._loading:
            return False
        try:
            self._capture_api_source(force=True)
            self._api_profiles.active_source = self._api_base()
            Llm.save_profiles(self._api_profiles)
        except (OSError, ValueError) as exc:
            self._api_config_feedback(f"Save failed: {exc}", exc)
            return False
        self._api_loaded = True
        self._add_api_source_option(self._api_base())
        self._api_preferences_dirty = False
        self._api_source_dirty = False
        self._api_config_feedback("LLM settings saved to llm.yaml.")
        return True

    @property
    def _api_busy(self) -> bool:
        return self._running or self._testing or self._fetching

    def _enabled(self, *_args: object) -> None:
        if not hasattr(self, "export_button"):
            return
        session = self.session
        loaded = session is not None
        idle = not self.runner.busy and not self._api_busy and self._pending_recognition is None
        waiting = self._problem_page is not None and self._recognition_paused and not self.runner.busy
        browsing = idle or (self._running and self._recognition_paused
                            and self.client.reply is None and not self.runner.busy)
        self.files.setEnabled(idle)
        self.close_pdf_button.setEnabled(loaded and idle)
        self.tabs.setEnabled(idle or waiting)
        self.tabs.widget(0).setEnabled(loaded and not waiting)
        self.tabs.widget(2).setEnabled(loaded and not waiting)
        self.test_button.setEnabled(idle)
        self.fetch_button.setEnabled(idle)
        self.balance_button.setEnabled(not self._api_busy and self.balance_client.reply is None)
        self.tree.set_editing_enabled(idle)
        self.tree.setEnabled(loaded and browsing)
        self.pages.setEnabled(loaded and browsing)
        single_page = loaded and len(self.pages.selectedItems()) == 1
        self.page_toc_action.setVisible(single_page)
        self.page_toc_action.setEnabled(single_page and idle)
        with QtCore.QSignalBlocker(self.page_toc_action):
            self.page_toc_action.setChecked(bool(single_page and session
                and int(self.pages.selectedItems()[0].text(0)) in session.toc))
        for action in self.page_mapping_actions:
            action.setVisible(single_page)
            action.setEnabled(single_page and idle)
        self.page_mapping_separator.setVisible(single_page)
        can_delete = loaded and idle and bool(self.pages.selectedItems())
        self.edit_label_action.setEnabled(can_delete)
        self.clear_label_action.setEnabled(can_delete)
        self.delete_pages_action.setEnabled(can_delete)
        self.delete_pages_button.setEnabled(can_delete)
        self.yaml.setEnabled(idle and session.current_page in session.toc if session else False)
        can_supplement = bool(session and session.current_page in session.toc
                              and (idle or waiting and session.current_page == self._problem_page))
        self.supplement_button.setEnabled(can_supplement)
        self.information_input.setEnabled(can_supplement)
        self.information_retry.setEnabled(can_supplement)
        self.information_retry.setText("Retry && continue" if self._problem_page is not None else "Retry page")
        has_toc = bool(session and session.toc)
        self.clear_toc_button.setEnabled(idle and has_toc)
        self.run_button.setEnabled(idle and has_toc)
        self.retry_all_button.setEnabled(idle and has_toc)
        self.retry_button.setEnabled(idle and session.current_page in session.toc if session else False)
        self.export_button.setEnabled(loaded and idle)
        self.page_number.setEnabled(loaded and browsing)
        self.previous.setEnabled(browsing and session.current_page > 1 if session else False)
        self.next.setEnabled(browsing and session.current_page < session.page_count if session else False)
        self.task_buttons.set_external_state(
            self._api_busy or self.balance_client.reply is not None or self._pending_recognition is not None,
            pausable=self._running and not (self._recognition_paused and self.runner.busy),
            pause_requested=self._queue_pause_requested)
        self.viewer.navigation_enabled = loaded and browsing
        marked = bool(session and session.current_page in session.toc)
        if not marked:
            with QtCore.QSignalBlocker(self.draw_crop):
                self.draw_crop.setChecked(False)
        self.draw_crop.setEnabled(marked and idle)
        self.viewer.set_crop_editing(marked and idle and self.draw_crop.isChecked())
        active = self._api_busy or self.runner.busy or self._pending_recognition is not None
        self.progress_bar.setVisible(active)
        if self._running:
            self.progress_bar.setRange(0, self._queue_total)
            self.progress_bar.setValue(self._queue_done)
            self.progress_bar.setFormat("%v / %m pages")
            self.progress_bar.setToolTip("Pages successfully completed in this run. Retries do not advance progress twice.")
        elif active:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setToolTip("Waiting for the current operation; progress is not available yet.")
        busy = (self.runner.busy and not self.runner.paused) or (self._api_busy and not self._recognition_paused)
        if busy and not self._cursor_busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            self._cursor_busy = True
        elif not busy and self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False

    def _mark_dirty(self) -> None:
        self.dirty = True
        if self.session:
            self.setWindowTitle(f"* {self.session.source.name} — PDF Bookmark Editor")

    def _error(self, message: str) -> None:
        self.status.setText(message)
        self.information_status.setText("Action needs attention")
        self.information.setPlainText(message)
        QtWidgets.QMessageBox.critical(self, "PDF Bookmark Editor", message)
        self._show_information()

    def _open_dialog(self) -> None:
        path = choose_open_file(self, "Open PDF", "PDF (*.pdf)")
        if path:
            self.open_path(Path(path))

    def _show_recognition_warning(self, page: int, status: str, error: str) -> None:
        """Show complete plain-text errors in a resizable, copyable modal dialog."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Recognition paused")
        layout = QtWidgets.QVBoxLayout(dialog)
        heading = QtWidgets.QLabel(f"PDF page {page}: {status}.\nThe queue is paused; earlier results are retained.")
        heading.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        details = QtWidgets.QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(error or "Review the page details.")
        layout.addWidget(details, 1)
        layout.addWidget(QtWidgets.QLabel("Review Information, then retry this page to continue."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        copy = buttons.addButton("Copy error", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(details.toPlainText()))
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.resize(720, 420)
        dialog.exec()
        dialog.deleteLater()

    def _close_pdf(self) -> None:
        if self.session is None or self._api_busy or self.runner.busy or not self._discard(self._close_pdf):
            return
        self._capture_api_source()
        self.draft_timer.stop()
        self._balance_identity = None
        self.balance_client.cancel("PDF closed.")
        self.runner.shutdown()
        self.preview_cache.clear()
        self.preview_buffer.close()
        self.preview_buffer = PreviewBuffer()
        self.session = None
        self.password = ""
        self.dirty = False
        self._source = None
        self._shown = None
        self._after_export = None
        self._purpose = ""
        self._queue.clear()
        self._active = None
        self._pending_turn = None
        self._undo.clear()
        self._pending_recognition = None
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()
        self._build()
        self.setWindowTitle("PDF Bookmark Editor")
        self._enabled()

    def _discard(self, after_export: Callable[[], object]) -> bool:
        if self.draft_timer.isActive():
            self._apply_yaml()
        if not self.dirty:
            return True
        answer = QtWidgets.QMessageBox.question(self, "Unexported changes",
            "Export the edited PDF before continuing? Recognition drafts are kept only in this session.",
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard | QtWidgets.QMessageBox.StandardButton.Cancel)
        if answer == QtWidgets.QMessageBox.StandardButton.Save:
            if self._export():
                self._after_export = after_export
            return False
        return answer == QtWidgets.QMessageBox.StandardButton.Discard

    def open_path(self, path: Path) -> None:
        """Open a PDF after resolving unexported changes; JSON projects are unsupported."""
        if self._api_busy or self.runner.busy:
            return
        if path.suffix.lower() != ".pdf" or not path.is_file():
            self._error("Choose an existing PDF file.")
            return
        if not self._discard(lambda: self.open_path(path)):
            return
        self._source = path
        self._purpose = "inspect"
        self.runner.start({"operation": "inspect", "path": str(path), "password": ""})

    def _read_api(self) -> LlmSettings:
        return LlmSettings(self._api_base(), self.api_model.currentText().strip(),
                           self.temperature.value(), self.max_tokens.value(), self.timeout.value(), self.context_images.value(),
                           reasoning_effort=LlmReasoning(self.reasoning_effort.currentData() or LlmReasoning.AUTO),
                           skip_certificate_verification=self.skip_certificate_verification.isChecked())

    def _reset_api_parameters(self) -> None:
        """Restore generation defaults in the active source's in-memory draft."""
        if not self.reset_api_parameters_button.isEnabled():
            return
        defaults = LlmSettings()
        with (QtCore.QSignalBlocker(self.temperature), QtCore.QSignalBlocker(self.max_tokens),
              QtCore.QSignalBlocker(self.timeout), QtCore.QSignalBlocker(self.context_images)):
            self.temperature.setValue(defaults.temperature)
            self.max_tokens.setValue(defaults.max_tokens)
            self.timeout.setValue(defaults.timeout_seconds)
            self.context_images.setValue(defaults.max_context_images)
            self._refresh_reasoning_options(defaults.reasoning_effort)
        self._api_changed()

    def _refresh_reasoning_options(self, selected: LlmReasoning | None = None) -> None:
        """Rebuild API/model choices without silently changing a saved effort."""
        selected = selected or LlmReasoning(self.reasoning_effort.currentData() or LlmReasoning.AUTO)
        with QtCore.QSignalBlocker(self.reasoning_effort):
            self.reasoning_effort.clear()
            for label, value in Llm.reasoning_options(self._api_base(), self.api_model.currentText()):
                self.reasoning_effort.addItem(label, value.value)
            index = self.reasoning_effort.findData(selected.value)
            if index < 0:
                self.reasoning_effort.addItem(f"{selected.value} (not supported; choose another)", selected.value)
                index = self.reasoning_effort.count() - 1
            self.reasoning_effort.setCurrentIndex(index)

    def _api_base(self) -> str:
        index = self.api_url.currentIndex()
        if index >= 0 and self.api_url.currentText() == self.api_url.itemText(index):
            return str(self.api_url.itemData(index))
        return self.api_url.currentText().strip()

    def _select_api_preset(self, index: int) -> None:
        self.api_url.setEditText(str(self.api_url.itemData(index)))

    def _endpoint_changed(self, *_args: object) -> None:
        base = self._api_base()
        if not self._loading and base != self._previous_api_url:
            self._capture_api_source()
            self._load_api_source(base)
            if self._api_source_id(base):
                self._api_profiles.active_source = base
            self._api_preferences_dirty = True
            self.models_status.setText("Provider changed. Source draft restored; Get models or enter a model name.")
            self.test_status.setText("API not tested")
            self.test_status.setStyleSheet("")
            self._invalidate_balance()
            if self.session:
                self._sync_api()
        self._previous_api_url = base

    def _model_filter_changed(self) -> None:
        """Discard the old catalog until an explicit fetch applies the new filter."""
        current = self.api_model.currentText()
        with QtCore.QSignalBlocker(self.api_model):
            self.api_model.clear()
            self.api_model.setEditText(current)
        self.models_status.setText("Filter changed. Click Get models to refresh the list.")

    def _fetch_models(self) -> None:
        if self._api_busy or self.runner.busy:
            return
        self._fetching = True
        self.models_status.setText("Fetching models…")
        try:
            self.client.fetch_models(self._read_api(), self.api_key.text(), vision_only=self.vision_models_only.isChecked())
            self._enabled()
        except (ValueError, RuntimeError) as exc:
            self._models_completed([], str(exc))

    def _set_balance(self, summary: str, detail: str, *, error: bool = False,
                     available: bool = False) -> None:
        self.balance_summary.setText(f"API balance: {summary}")
        self.balance_summary.setToolTip(detail)
        self.balance_status.setText(detail)
        for label in (self.balance_summary, self.balance_status):
            label.setStyleSheet("color: #c02020;" if error else
                               "color: #1769c2; font-weight: bold;" if available else "")

    def _invalidate_balance(self, *_args: object) -> None:
        # Invalidate before abort: Qt may deliver cancellation synchronously.
        self._balance_identity = None
        self.balance_client.cancel("Balance credentials changed.")
        self._set_balance("not queried", "Credentials changed. Finish editing or refresh to query the current account.")

    def _refresh_balance(self) -> None:
        if self._closing or self._close_when_idle or self._api_busy or self.balance_client.reply is not None:
            return
        settings = self._read_api()
        key = self.balance_key.text() or self.api_key.text()
        try:
            Llm.balance_url(settings.base_url)
            if not key.strip():
                self._set_balance("not queried", "Enter an API key to display the account balance.")
                return
            self._balance_identity = (settings.base_url, key)
            self._set_balance("checking…", "Querying API account balance; no PDF or model request is sent.")
            self.balance_client.fetch_balance(settings, key)
            self._enabled()
        except NotImplementedError as exc:
            self._balance_identity = None
            self._set_balance("unsupported", str(exc))
        except (ValueError, RuntimeError) as exc:
            self._balance_identity = (settings.base_url, key)
            self._balance_completed([], str(exc))

    def _balance_completed(self, balances: list[tuple[str, str]], error: str) -> None:
        identity, self._balance_identity = self._balance_identity, None
        current = (self._api_base(), self.balance_key.text() or self.api_key.text())
        if identity is not None and identity == current:
            if error:
                hint = (" OpenRouter requires a management key in Balance key."
                        if QtCore.QUrl(identity[0]).host() == "openrouter.ai" else "")
                self._set_balance("unavailable", f"Balance query failed: {error}{hint}", error=True)
            else:
                value = "; ".join(f"{currency} {amount}" for currency, amount in balances)
                self._set_balance(value, f"API account balance: {value}", available=True)
        self._enabled()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _models_completed(self, models: list[str], error: str) -> None:
        self._fetching = False
        if error:
            self.models_status.setText(f"Cannot fetch models: {error} You can still enter a model name manually.")
        else:
            current = self.api_model.currentText()
            with QtCore.QSignalBlocker(self.api_model):
                self.api_model.clear()
                self.api_model.addItems(models)
                if current and (not self.vision_models_only.isChecked() or current in models):
                    self.api_model.setCurrentText(current)
            self._api_changed()
            self.models_status.setText(
                f"{len(models)} confirmed image-input models. Unknown capabilities are excluded; API Test checks access."
                if self.vision_models_only.isChecked() and models else
                "No models explicitly report image input. This API may omit capability metadata; uncheck the filter or enter a model manually."
                if self.vision_models_only.isChecked() else
                f"{len(models)} models reported. Select one with image input; API Test checks vision access.")
        self._enabled()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _sync_api(self) -> None:
        if self.session:
            self.session.api = self._read_api()

    def _test_api(self) -> None:
        if self._api_busy or self.runner.busy:
            return
        settings = self._read_api()
        self._testing = True
        self._test_elapsed.start()
        try:
            body = Llm.vision_test_request(settings)
            self.test_status.setText("Testing image input…")
            self.test_status.setStyleSheet("")
            self.client.send(settings, self.api_key.text(), body)
            self._enabled()
        except (ValueError, RuntimeError) as exc:
            self._client_completed("", 0, str(exc))

    def _client_completed(self, text: str, tokens: int, error: str) -> None:
        if not self._testing:
            self._recognized(text, tokens, error)
            return
        self._testing = False
        elapsed = self._test_elapsed.elapsed() / 1000
        passed = not error and text.strip().strip('.!\"').lower() == "red"
        if error:
            message = f"API test failed ({elapsed:.2f}s): {error}"
        elif passed:
            message = f"API test passed: image recognized ({elapsed:.2f}s, {tokens} input tokens)."
        else:
            message = f"API connected ({elapsed:.2f}s), but unexpected image response: {text[:200]}"
        self.test_status.setText(message)
        color = "#16803a" if passed else "#c02020"
        self.test_status.setStyleSheet(f"color: {color}; font-weight: bold;")
        self.status.setText(message)
        self._enabled()
        self._refresh_balance()
        if self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _api_changed(self, *_args: object) -> None:
        if not self._loading:
            self._refresh_reasoning_options()
            self._api_preferences_dirty = True
            self._api_source_dirty = True
            self._api_config_feedback("Unsaved API settings. Save or close this window to write changes.")
        if self.session and not self._loading:
            self._sync_api()
            self._mark_dirty()

    def _options_changed(self, *_args: object) -> None:
        if self.session and not self._loading:
            self.session.keep_existing = self.append_existing.isChecked()
            self.session.pending_only = self.only_pending.isChecked()
            self.session.clear_context = self.clear_context.isChecked()
            self._mark_dirty()

    def _refresh_tree(self) -> None:
        if self.session:
            self.tree.load([OutlineRow(item.id, item.title, item.page, item.level) for item in self.session.bookmarks])

    def _refresh_pages(self) -> None:
        if self.session is None:
            return
        selected = {int(item.text(0)) for item in self.pages.selectedItems()}
        self.pages.clear()
        for page, label in enumerate(self.session.labels, 1):
            task = self.session.toc.get(page)
            item = QtWidgets.QTreeWidgetItem([str(page), label, task.status.value if task else ""])
            if task:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#e00000")))
                item.setToolTip(2, task.error)
                if color := STATUS_COLORS.get(task.status):
                    item.setForeground(2, QtGui.QBrush(QtGui.QColor(color)))
                if task.status in (Status.DONE, Status.MODIFIED, Status.ERROR, Status.NEEDS_INFO):
                    font = item.font(2)
                    font.setBold(True)
                    item.setFont(2, font)
            self.pages.addTopLevelItem(item)
            item.setSelected(page in selected)
        self.pages.select_page(self.session.current_page - 1, preserve_selection=True)

    def _load_page(self) -> None:
        if self.session is None:
            return
        index = self.session.current_page - 1
        self.pages.select_page(index, preserve_selection=self.pages.displayed_page == index)
        self._loading = True
        task = self.session.toc.get(self.session.current_page)
        self.page_number.setValue(self.session.current_page)
        self.angle.setValue(task.angle if task else 0)
        self.yaml.setPlainText(task.draft if task else "")
        self.trace.setPlainText("\n\n".join(reversed(task.history)) if task else "")
        self.yaml_label.setText(f"YAML draft — PDF page {self.session.current_page}" if task else "This page is not marked as TOC")
        self.yaml_status.setText(task.error if task and task.error else
            "Tree edits are final. Applying YAML replaces this page's tree entries.")
        self.yaml_status.setToolTip(task.error if task else "")
        self.yaml_status.setStyleSheet("color: #c02020;" if task and task.error else "")
        self._load_requirements()
        self._load_information()
        self._loading = False
        self._enabled()

    def _delete_pages(self) -> None:
        """Confirm deletion policies, then commit one irreversible session edit."""
        session = self.session
        if session is None or self.runner.busy or self._api_busy:
            return
        pages = sorted({int(item.text(0)) for item in self.pages.selectedItems()})
        if not pages:
            return
        if len(pages) == session.page_count:
            self._error("Retain at least one page in the PDF.")
            return
        buttons = QtWidgets.QMessageBox.StandardButton
        ranges = Input.format_integer_ranges(Input.merge_integer_ranges(pages))
        answer = QtWidgets.QMessageBox.question(self, "Delete pages",
            f"Delete pages {ranges}? This cannot be undone; bookmark undo history will be cleared.\n"
            "The source file is unchanged. Export writes the remaining pages.\n\n"
            "Shift subsequent bookmark targets forward to follow their original pages?\n"
            "No keeps their numeric targets; targets outside the remaining PDF must be fixed before export.",
            buttons.Yes | buttons.No | buttons.Cancel, buttons.Cancel)
        if answer not in (buttons.Yes, buttons.No):
            return
        shift = answer == buttons.Yes
        delete_bookmarks = True
        affected = sum(item.page in pages for item in session.bookmarks)
        if affected:
            dialog = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Warning, "Bookmarks on deleted pages",
                f"{affected} bookmark(s) target a deleted page.\n"
                "Delete these bookmarks, or move them to the preceding retained page?\n"
                "If none precedes it, use the first retained page. Retained children are promoted.",
                buttons.Cancel, self)
            delete = dialog.addButton("Delete bookmarks", QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
            move = dialog.addButton("Move to preceding page", QtWidgets.QMessageBox.ButtonRole.ActionRole)
            dialog.exec()
            if dialog.clickedButton() not in (delete, move):
                return
            delete_bookmarks = dialog.clickedButton() is delete
        self.draft_timer.stop()
        self._store_draft()
        session.delete_pages(pages, shift=shift, delete_bookmarks=delete_bookmarks)
        self._undo.clear()
        self._queue.clear()
        self._active = None
        self._pending_turn = None
        self._last_image_count = 0
        self.usage.setText("Context: no request yet")
        self.preview_cache.clear()
        self._shown = None
        self.viewer.clear()
        self._loading = True
        for spin in (self.page_number, self.toc_first, self.toc_last, self.body_pdf):
            spin.setRange(1, session.page_count)
        self.page_total.setText(f" / {session.page_count} ")
        self.body_pdf.setValue(session.body_pdf)
        self.body_book.setValue(session.body_book)
        self.toc_first.setValue(min(session.toc) if session.toc else session.current_page)
        self.toc_last.setValue(max(session.toc) if session.toc else session.current_page)
        self.label_range.clear()
        self._loading = False
        self.pages.clearSelection()
        self._refresh_pages()
        self.pages.topLevelItem(session.current_page - 1).setSelected(True)
        self._refresh_tree()
        self._load_page()
        self._mark_dirty()
        self._render("preview")
        if session.mapping_required:
            QtWidgets.QMessageBox.information(self, "Body mapping",
                "The body anchor was deleted and no positive printed body page remains.\n"
                "Choose a new body page and printed start before scanning or applying YAML.")

    def _supplement(self) -> None:
        self._show_information()

    def _show_information(self) -> None:
        """Reveal the problem and focus the answer editor when it is available."""
        self.result_tabs.setCurrentWidget(self.information_tab)
        target = self.information_input if self.information_input.isEnabled() else self.information
        target.setFocus()

    def _result_tab_changed(self, _index: int) -> None:
        """Give Information the space used by YAML-only controls and duplicate errors."""
        show_yaml_controls = self.result_tabs.currentWidget() is not self.information_tab
        for widget in (self.yaml_label, self.yaml_status, self.yaml_actions):
            widget.setVisible(show_yaml_controls)

    def _load_information(self) -> None:
        """Display this page's parsed questions or local/transport error, without raw YAML."""
        task = self.session.toc.get(self.session.current_page) if self.session else None
        if task is None:
            self.information_status.setText("This page is not marked as TOC.")
            self.information.clear()
        else:
            suffix = " — paused; retry this page to continue" if self._problem_page == task.page else ""
            self.information_status.setText(f"PDF page {task.page} · {task.status.value}{suffix}")
            details = "\n\n".join(f"Location: {issue.location}\nProblem: {issue.error_message}\nNeeded: {issue.needs}"
                                    for issue in task.issues)
            self.information.setPlainText(details or task.error or "No outstanding questions or errors.")
        with QtCore.QSignalBlocker(self.information_input):
            self.information_input.setPlainText(task.requirements if task else "")

    def _information_changed(self) -> None:
        """Keep the inline answer and current-page requirement editor on one draft."""
        if self._loading or self.session is None:
            return
        if task := self.session.toc.get(self.session.current_page):
            task.requirements = self.information_input.toPlainText()
            self._load_requirements()
            self._mark_dirty()

    def _retry_information(self) -> None:
        if self._problem_page is not None:
            self._resume_problem()
        else:
            self._request_recognition(self._retry)

    def _load_requirements(self, *_args: object) -> None:
        if self.session is None:
            return
        task = self.session.toc.get(self.session.current_page)
        text = self.session.requirements if self.requirement_scope.currentIndex() == 0 else task.requirements if task else ""
        with QtCore.QSignalBlocker(self.requirements):
            self.requirements.setPlainText(text)
        self.requirements.setEnabled(self.requirement_scope.currentIndex() == 0 or task is not None)

    def _requirements_changed(self) -> None:
        if self._loading or self.session is None:
            return
        if self.requirement_scope.currentIndex() == 0:
            self.session.requirements = self.requirements.toPlainText()
        elif task := self.session.toc.get(self.session.current_page):
            task.requirements = self.requirements.toPlainText()
            with QtCore.QSignalBlocker(self.information_input):
                self.information_input.setPlainText(task.requirements)
        self._mark_dirty()

    def _use_current_page(self, target: QtWidgets.QSpinBox) -> None:
        """Fill a physical-page field; remap body targets immediately when requested."""
        if self.session is None or self.runner.busy or self._api_busy:
            return
        target.setValue(self.session.current_page)
        if target is self.body_pdf:
            self._mapping_changed()

    def _set_selected_page(self, target: QtWidgets.QSpinBox) -> None:
        """Set a TOC bound or atomically commit a physical/printed body anchor."""
        if self.session is None or self.runner.busy or self._api_busy or self._pending_recognition is not None:
            return
        selected = self.pages.selectedItems()
        if len(selected) != 1:
            return
        page = int(selected[0].text(0))
        if target is self.body_pdf:
            printed, accepted = QtWidgets.QInputDialog.getInt(
                self, "First body PDF page", f"Physical PDF page {page}\nPrinted (logical) page number:",
                self.body_book.value(), self.body_book.minimum(), self.body_book.maximum())
            if not accepted:
                return
            with QtCore.QSignalBlocker(self.body_pdf), QtCore.QSignalBlocker(self.body_book):
                self.body_pdf.setValue(page)
                self.body_book.setValue(printed)
            self._mapping_changed()
            self.status.setText(f"Body: PDF page {page} = printed page {printed}")
        else:
            target.setValue(page)
            self.status.setText("TOC range updated. Click Mark TOC to apply.")

    def _mark_toc(self) -> None:
        if self.session is None or self.runner.busy or self._api_busy or self._pending_recognition is not None:
            return
        first, last = self.toc_first.value(), self.toc_last.value()
        if last < first:
            self._error("The last TOC page must not precede the first.")
            return
        self._replace_toc_tasks({page: TocPage(page) for page in range(first, last + 1)})
        self.go_page(first, force=True)

    def _clear_toc(self) -> None:
        """Clear all recognition tasks while retaining the current page and bookmarks."""
        if (self.session is None or not self.session.toc or self.runner.busy
                or self._api_busy or self._pending_recognition is not None):
            return
        self._replace_toc_tasks({})
        self._render("preview")

    def _replace_toc_tasks(self, tasks: dict[int, TocPage]) -> None:
        """Commit task changes, detach removed sources and discard stale task context."""
        assert self.session is not None
        self.draft_timer.stop()
        self._active = None
        self._pending_turn = None
        changed = {page for page, task in self.session.toc.items() if tasks.get(page) is not task}
        self.session.toc = tasks
        self.session.conversation = [turn for turn in self.session.conversation if turn.page not in changed]
        if changed:
            self._last_image_count = 0
            self.usage.setText("Context: updated; applies to next request")
        for item in self.session.bookmarks:
            if item.source_page is not None and item.source_page not in tasks:
                item.source_page = None
                item.logical_page = None
        self._undo.clear()
        self._refresh_pages()
        # Reload before navigation can store the old editor into a fresh task.
        self._load_page()
        self._mark_dirty()

    def _toggle_selected_toc(self, checked: bool) -> None:
        """Toggle only the single selected page; preserve all other TOC tasks."""
        if self.session is None or self.runner.busy or self._api_busy or self._pending_recognition is not None:
            self._enabled()
            return
        selected = self.pages.selectedItems()
        if len(selected) != 1:
            return
        self._set_toc_page(int(selected[0].text(0)), checked)

    def _set_toc_page(self, page: int, marked: bool) -> None:
        """Apply one page's TOC membership and refresh its possibly rotated preview."""
        assert self.session is not None
        if marked == (page in self.session.toc):
            return
        self._store_draft()
        tasks = dict(self.session.toc)
        if marked:
            tasks[page] = TocPage(page)
        else:
            del tasks[page]
        self._replace_toc_tasks(tasks)
        self._render("preview")

    def _mapping_changed(self) -> None:
        if self._loading or self.session is None:
            return
        self.session.remap(self.body_pdf.value(), self.body_book.value())
        self._refresh_tree()
        self._mark_dirty()

    def _unmark_toc(self) -> None:
        if self.session is None or self.runner.busy or self._api_busy or self._pending_recognition is not None:
            return
        self._set_toc_page(self.session.current_page, False)

    def _rotation_changed(self) -> None:
        if self._loading or self.session is None:
            return
        task = self.session.toc.get(self.session.current_page)
        if task and task.angle != self.angle.value():
            task.angle = self.angle.value()
            task.crop = (0, 0, 1, 1)
            self._mark_dirty()
            self._render("preview")

    def _crop_changed(self, crop: Rectangle) -> None:
        if self.session and (task := self.session.toc.get(self.session.current_page)):
            task.crop = crop
            self._mark_dirty()

    def _whole_page(self) -> None:
        self._crop_changed((0, 0, 1, 1))
        if self.session and self.session.current_page in self.session.toc:
            self.viewer.set_crop((0, 0, 1, 1))

    def _step(self, delta: int) -> None:
        if self.session:
            self.go_page(self.session.current_page + delta)

    def _page_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if not QtWidgets.QApplication.keyboardModifiers() & (QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier):
            self.go_page(int(item.text(0)))

    def go_page(self, page: int, *, force: bool = False) -> None:
        """Navigate to a physical page; a single serial render prevents task buildup."""
        paused = self._running and self._recognition_paused and self.client.reply is None
        if (self.session is None or self.runner.busy or self._api_busy and not paused
                or not 1 <= page <= self.session.page_count):
            return
        if page == self.session.current_page and not force:
            return
        if self.draft_timer.isActive():
            self._apply_yaml()
        self._store_draft()
        self.session.current_page = page
        self._load_page()
        self._render("preview")

    def _render(self, purpose: str) -> None:
        if self.session is None or self.runner.busy:
            return
        self._purpose = purpose
        task = self.session.toc.get(self.session.current_page)
        angle = task.angle if task else 0
        cached = self.preview_cache.get(self.session.current_page)
        if cached is not None and cached[0] == angle:
            self._show_preview(self.session.current_page, angle, cached[1])
            return
        self.runner.start({"operation": "preview", "path": str(self.session.source), "password": self.password,
                           "page": self.session.current_page, "angle": angle,
                           "source_page": self.session.source_pages[self.session.current_page - 1],
                           "pixel_buffer": self.preview_buffer.name})

    def _show_preview(self, page: int, angle: float, pixmap: QtGui.QPixmap) -> None:
        assert self.session is not None
        self.viewer.set_pixmap(pixmap, (str(self.session.source), page, angle))
        self._shown = page, angle
        task = self.session.toc.get(page)
        self.viewer.set_crop(task.crop if task else None)
        if self._purpose == "recognize" and self._running:
            self._send_image()
        else:
            self.status.setText(f"PDF page {page} / {self.session.page_count}" + (" — TOC recognition area in red" if task else ""))

    def _store_draft(self) -> None:
        if self.session and not self._loading and (task := self.session.toc.get(self.session.current_page)):
            task.draft = self.yaml.toPlainText()

    def _yaml_changed(self) -> None:
        if not self._loading and not self._running:
            self._store_draft()
            if self.session and (task := self.session.toc.get(self.session.current_page)):
                task.edited = True
            self._mark_dirty()
            self.draft_timer.start()

    def _apply_yaml(self) -> bool:
        self.draft_timer.stop()
        if self._loading or self.session is None or self.session.current_page not in self.session.toc or self._running:
            return False
        page = self.session.current_page
        task = self.session.toc[page]
        self._store_draft()
        try:
            self._accept_draft(page, task.draft)
            task.status = Status.MODIFIED
            self._refresh_pages()
            self.yaml_status.setStyleSheet("")
            self.yaml_status.setText("YAML applied. Comments retained; tree targets are physical PDF pages.")
            self._load_information()
            return True
        except ValueError as exc:
            task.error = str(exc)
            task.issues = list(exc.issues) if isinstance(exc, NeedsInformation) else []
            task.status = Status.NEEDS_INFO if isinstance(exc, NeedsInformation) else Status.ERROR
            task.draft_invalid = True
            self.yaml_status.setText(str(exc))
            self.yaml_status.setToolTip(str(exc))
            self.yaml_status.setStyleSheet("color: #c02020;")
            self._refresh_pages()
            self._load_information()
            return False

    def _accept_draft(self, page: int, text: str) -> None:
        assert self.session is not None
        before = [replace(item) for item in self.session.bookmarks]
        self.session.apply_draft(page, text)
        self._undo.append(before)
        self._undo = self._undo[-50:]
        if not self.append_existing.isChecked():
            self.session.bookmarks = [item for item in self.session.bookmarks if item.original_xref is None]
        self._refresh_tree()
        self._refresh_pages()
        self._mark_dirty()

    def _tree_changed(self, rows: list[OutlineRow]) -> None:
        if self._loading or self.session is None:
            return
        existing = {item.id: item for item in self.session.bookmarks}
        self._remember_outline()
        if list(existing) != [value.id for value in rows]:
            for entry in existing.values():
                if entry.source_page:
                    self.session.toc[entry.source_page].edited = True
        entries: list[Bookmark] = []
        for row in rows:
            before = existing.get(row.id)
            item = replace(before) if before else Bookmark(row.title, row.page, row.level, id=row.id)
            if item.page != row.page:
                item.logical_page = None
            item.title, item.page, item.level = row.title, row.page, row.level
            if item.source_page and before != item:
                self.session.toc[item.source_page].edited = True
            entries.append(item)
        self.session.bookmarks = entries
        self._mark_dirty()

    def _add_roots(self) -> None:
        if self.session:
            self._remember_outline()
            first = min(self.session.toc) if self.session.toc else self.toc_first.value()
            self.session.bookmarks[:0] = [Bookmark("Cover", 1), Bookmark("Table of Contents", first)]
            self._refresh_tree()
            self._mark_dirty()

    def _remember_outline(self) -> None:
        if self.session:
            self._undo.append([replace(item) for item in self.session.bookmarks])
            self._undo = self._undo[-50:]

    def _clear_bookmarks(self) -> None:
        if self.session:
            self.draft_timer.stop()
            self._remember_outline()
            self.session.bookmarks.clear()
            for task in self.session.toc.values():
                task.draft_invalid = False
            self._refresh_tree()
            self._mark_dirty()
            self.status.setText("Bookmarks cleared. YAML drafts retained; Undo restores the outline.")

    def _undo_bookmarks(self) -> None:
        if self.session and self._undo:
            self.draft_timer.stop()
            self.session.bookmarks = self._undo.pop()
            if not self.session.mapping_required:
                self.session.remap(self.session.body_pdf, self.session.body_book)
            self._refresh_tree()
            self._mark_dirty()

    def _page_labels(self, *, clear: bool = False) -> None:
        """Edit labels for the Pages selection, independent of the tab's range."""
        session = self.session
        if session is None or self.runner.busy or self._api_busy or self._pending_recognition is not None:
            return
        pages = sorted(int(item.text(0)) for item in self.pages.selectedItems())
        if not pages:
            return
        if clear:
            Pdf.clear_page_labels(session.labels, [page - 1 for page in pages])
        elif len(pages) == 1:
            index = pages[0] - 1
            label, accepted = QtWidgets.QInputDialog.getText(
                self, "Edit page label", f"Label for page {pages[0]}:", text=session.labels[index])
            if not accepted or label == session.labels[index]:
                return
            session.labels[index] = label
        else:
            self.label_range.setText(Input.format_integer_ranges(Input.merge_integer_ranges(pages)))
            self.tabs.setCurrentWidget(self.labels_tab)
            self.label_range.setFocus()
            QtWidgets.QToolTip.showText(
                self.label_range.mapToGlobal(self.label_range.rect().bottomLeft()),
                "Edit labels for the selected pages in Page labels, then click Apply numbered labels.",
                self.label_range)
            return
        self._refresh_pages()
        self._mark_dirty()

    def _selected_label_pages(self) -> tuple[int, ...]:
        assert self.session is not None
        if self.label_range.text().strip():
            return Input.parse_index_ranges(self.label_range.text(), item_count=self.session.page_count)
        selected = tuple(sorted(int(item.text(0)) - 1 for item in self.pages.selectedItems()))
        return selected or (self.session.current_page - 1,)

    def _label_numbered(self) -> None:
        if self.session:
            try:
                Pdf.number_page_labels(self.session.labels, self._selected_label_pages(), self.label_first.value(), self.label_prefix.text())
                self._refresh_pages()
                self._mark_dirty()
            except ValueError as exc:
                self._error(str(exc))

    def _label_clear(self, all_pages: bool = False) -> None:
        if self.session:
            try:
                Pdf.clear_page_labels(self.session.labels, list(range(self.session.page_count)) if all_pages else self._selected_label_pages())
                self._refresh_pages()
                self._mark_dirty()
            except ValueError as exc:
                self._error(str(exc))

    def _label_generate(self) -> None:
        if self.session:
            self._mapping_changed()
            Pdf.generate_page_labels(self.session.labels, self.session.body_pdf, self.session.body_book, list(self.session.toc))
            # Printed numbers retain gaps where source pages were deleted.
            anchor = self.session.source_pages[self.session.body_pdf - 1]
            for index in range(self.session.body_pdf - 1, self.session.page_count):
                if index + 1 not in self.session.toc:
                    self.session.labels[index] = str(self.session.body_book + self.session.source_pages[index] - anchor)
            self._refresh_pages()
            self._mark_dirty()

    def _image(self) -> QtGui.QImage:
        if self.session is None or self.session.current_page not in self.session.toc:
            raise ValueError("Mark this page as TOC first.")
        task = self.session.toc[self.session.current_page]
        if self._shown != (task.page, task.angle):
            raise ValueError("Wait for this page's preview before using its image.")
        image = self.viewer._original.toImage()
        x0, y0, x1, y1 = task.crop
        rect = QtCore.QRectF(x0 * image.width(), y0 * image.height(),
                             (x1 - x0) * image.width(), (y1 - y0) * image.height()).toAlignedRect()
        return image.copy(rect.intersected(image.rect()))

    def _copy_image(self) -> None:
        try:
            QtWidgets.QApplication.clipboard().setImage(self._image())
        except ValueError as exc:
            self._error(str(exc))

    def _request_recognition(self, action: Callable[[], None]) -> None:
        """Accept one click before editor focus-out can start a preview render."""
        if self.session is None or self._api_busy or self.runner.busy or self._pending_recognition is not None:
            return
        self._pending_recognition = action
        focused = self.focusWidget()
        if focused is not None:
            focused.clearFocus()
        self._enabled()
        if self.runner.busy:
            self.status.setText("Waiting for preview...")
        self._continue_recognition()

    def _continue_recognition(self) -> None:
        """Consume the accepted action once, after any focus-out render finishes."""
        if self.runner.busy or self._pending_recognition is None:
            return
        action, self._pending_recognition = self._pending_recognition, None
        try:
            if self.session is not None and not self._api_busy and not self._closing and not self._close_when_idle:
                action()
        finally:
            self._enabled()

    def _run_all(self) -> None:
        if self.session:
            pages = [page for page in sorted(self.session.toc)
                     if not self.only_pending.isChecked() or self.session.toc[page].status not in (Status.DONE, Status.MODIFIED)]
            self._start_queue(pages)

    def _retry(self) -> None:
        if self.session:
            self._start_queue([self.session.current_page] if self.session.current_page in self.session.toc else [], retry=True)

    def _retry_all(self) -> None:
        if self.session:
            self._start_queue(sorted(self.session.toc), retry=True)

    def _start_queue(self, pages: list[int], *, retry: bool = False) -> None:
        if self.session is None or self._api_busy or self.runner.busy:
            return
        if self.session.mapping_required:
            self._error("Choose a new body page and printed start before recognition.")
            return
        self.draft_timer.stop()
        self._store_draft()
        if not pages:
            self.status.setText("No pages to run. Mark TOC pages, or disable pending-only mode.")
            return
        if any(self.session.toc[page].edited or self.session.toc[page].status == Status.MODIFIED for page in pages):
            choice = QtWidgets.QMessageBox.question(self, "Replace edited results", "Recognition will replace edited entries on the selected TOC pages. Continue?")
            if choice != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._sync_api()
        try:
            Llm.validate_settings(self.session.api)
        except ValueError as exc:
            self._error(str(exc))
            return
        if self.clear_context.isChecked():
            self.session.conversation.clear()
            self.session.context_start = min(pages)
        self._retry_run = retry
        self._pending_turn = None
        self._queue = sorted(set(pages))
        self._queue_total = len(self._queue)
        self._queue_done = 0
        self._queue_pause_requested = self._recognition_paused = False
        self._problem_page = None
        self._running = True
        self._enabled()
        self._next_task()

    def _toggle_queue_pause(self) -> None:
        """Pause between requests; never discard a response already in flight."""
        if not self._running or self._recognition_paused and self.runner.busy:
            return
        if self._problem_page is not None:
            self._resume_problem()
            return
        self._queue_pause_requested = not self._queue_pause_requested
        if self._queue_pause_requested:
            self.status.setText("Pausing after this page...")
        elif self._recognition_paused:
            self._recognition_paused = False
            self._next_task()
        else:
            self.status.setText("Continuing...")
        self._enabled()

    def _resume_problem(self) -> None:
        """Retry the blocked page with current instructions, retaining the original queue."""
        if (self.session is None or not self._running or self._problem_page is None
                or not self._recognition_paused or self.runner.busy or self.client.reply is not None):
            return
        self._sync_api()
        try:
            Llm.validate_settings(self.session.api)
        except ValueError as exc:
            self._error(str(exc))
            return
        # The failed page stays at the queue head. Do not clear conversation,
        # recompute pending pages, or discard results from earlier pages.
        self._problem_page = None
        self._queue_pause_requested = self._recognition_paused = False
        self._next_task()

    def _next_task(self) -> None:
        if not self._running or self.session is None:
            return
        if not self._queue:
            self._running = False
            self._queue_pause_requested = self._recognition_paused = False
            self._active = None
            self._enabled()
            failures = sum(task.status in (Status.ERROR, Status.NEEDS_INFO) for task in self.session.toc.values())
            self.status.setText(f"Done · {failures} failed")
            self._refresh_balance()
            return
        if self._queue_pause_requested:
            self._recognition_paused = True
            self.status.setText("Waiting for information" if self._problem_page is not None else "Paused")
            self._enabled()
            return
        self._active = self._queue.pop(0)
        self._pending_turn = None
        self._last_image_count = 0
        self.session.current_page = self._active
        task = self.session.toc[self._active]
        task.status = Status.RUNNING
        task.request_trace = (f"PDF page {task.page} — {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n"
                              + json.dumps({"api": asdict(self.session.api), "crop": task.crop, "rotation": task.angle,
                                            "body_pdf": self.session.body_pdf, "body_book": self.session.body_book,
                                            "book_requirements": self.session.requirements,
                                            "page_requirements": task.requirements}, ensure_ascii=False, indent=2))
        self._load_page()
        self._refresh_pages()
        self.status.setText(f"Preparing page {self._active}...")
        self._render("recognize")

    def _send_image(self) -> None:
        if not self._running or self.session is None or self._active is None:
            return
        try:
            buffer = QtCore.QBuffer()
            buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
            # QImageWriter's QByteArray format agrees with both Qt's runtime and stubs.
            writer = QtGui.QImageWriter(buffer, b"JPEG")
            writer.setQuality(92)
            if not writer.write(self._image()):
                raise ValueError("Cannot encode the recognition crop.")
            image = bytes(buffer.data().data())
            body = build_request(self.session, self._active, image, retry=self._retry_run)
            # Trace text/context exactly as sent, without image bytes or credentials.
            messages = cast(list[dict[str, object]], body["messages"])
            content = cast(list[dict[str, object]], messages[-1]["content"])
            self._last_image_count = Llm.image_count(messages)
            self.session.toc[self._active].request_trace += (f"\nConversation turns: {len(self.session.conversation)}"
                f"\nImages sent (including current): {self._last_image_count}\nImage limit: {self.session.api.max_context_images}"
                f"\nSystem prompt:\n{SYSTEM_PROMPT}\nUser prompt:\n{content[0]['text']}")
            self.client.send(self.session.api, self.api_key.text(), body)
            self._pending_turn = ConversationTurn(self._active, str(content[0]["text"]), image)
            self.status.setText(f"Reading page {self._active}...")
        except (ValueError, RuntimeError) as exc:
            self._recognized("", 0, str(exc))

    def _recognized(self, text: str, tokens: int, error: str) -> None:
        if self.session is None or self._active is None:
            return
        task = self.session.toc[self._active]
        task.issues.clear()
        if text:
            task.raw_response = text
            task.draft = text
        self.session.last_prompt_tokens = tokens
        self.usage.setText(f"Last request: {tokens} input tokens (API reported); {self._last_image_count} image(s) sent.")
        if not self._running:
            task.status = Status.INTERRUPTED
            task.error = error or "Recognition stopped."
        elif error:
            task.status, task.error = Status.ERROR, error
        else:
            try:
                self._accept_draft(task.page, text)
                task.status = Status.DONE
            except ValueError as exc:
                task.status = Status.NEEDS_INFO if isinstance(exc, NeedsInformation) else Status.ERROR
                task.error = str(exc)
                task.issues = list(exc.issues) if isinstance(exc, NeedsInformation) else []
        if task.status != Status.DONE:
            task.draft_invalid = True
        if self._pending_turn is not None:
            self._pending_turn.response, self._pending_turn.error = text, task.error
            self.session.conversation.append(self._pending_turn)
            self._pending_turn = None
        record = (f"PDF page {task.page} | Result: {task.status.value}\nError: {task.error or '(none)'}"
                  f"\nInput tokens: {tokens}\nOriginal response:\n{text or '(no response)'}"
                  f"\n\nRequest details:\n{task.request_trace}")
        key = self.api_key.text()
        if key:
            record = record.replace(key, "[redacted]")
        if len(record) > MAX_DRAFT:
            record = record[:MAX_DRAFT] + "\n[History record truncated; latest response remains in the YAML draft.]"
        task.history.append(record)
        while len(task.history) > 1 and (len(task.history) > 10 or sum(len(record) for record in task.history) > 2 * MAX_DRAFT):
            task.history.pop(0)
        task.request_trace = ""
        blocked = self._running and task.status in (Status.ERROR, Status.NEEDS_INFO)
        if blocked:
            self._queue.insert(0, task.page)
            self._problem_page = task.page
            self._queue_pause_requested = self._recognition_paused = True
            self.status.setText(f"Paused · page {task.page} needs attention")
        elif self._running:
            self._queue_done += 1
        self._mark_dirty()
        self._load_page()
        self._refresh_pages()
        self._enabled()
        if blocked:
            self._show_recognition_warning(task.page, task.status.value, task.error)
            self._show_information()
        elif self._running:
            QtCore.QTimer.singleShot(0, self._next_task)
        elif self._close_when_idle:
            QtCore.QTimer.singleShot(0, self.close)

    def _stop(self) -> None:
        self._pending_recognition = None
        if self.balance_client.reply is not None:
            self.balance_client.cancel("Balance lookup stopped.")
            if not self._api_busy:
                return
        if self._fetching:
            self.client.cancel("Model lookup stopped.")
            return
        if self._testing:
            self.client.cancel("API test stopped.")
            return
        self._running = False
        self._queue_pause_requested = self._recognition_paused = False
        self._problem_page = None
        self._queue.clear()
        if self.session and self._active is not None and self.session.toc[self._active].status == Status.RUNNING:
            self.session.toc[self._active].status = Status.INTERRUPTED
            self._mark_dirty()
            self._refresh_pages()
        self.client.cancel()
        self.status.setText("Stopped")
        self._load_information()
        self._enabled()

    def _completed(self, message: dict[str, Json]) -> None:
        kind = message.get("kind")
        if kind == "cancelled":
            self._after_export = None
            self.status.setText("Export cancelled. Edit settings and export again.")
        elif kind == "error":
            self._pending_recognition = None
            self._after_export = None
            if self._purpose == "inspect" and message.get("code") == "password":
                key, accepted = QtWidgets.QInputDialog.getText(self, "PDF password", "Password:", QtWidgets.QLineEdit.EchoMode.Password)
                if accepted:
                    self.runner.start({"operation": "inspect", "path": str(self._source), "password": key})
            elif self._purpose == "recognize":
                self._recognized("", 0, str(message.get("message")))
            else:
                self._error(str(message.get("message")))
        elif kind == "opened":
            assert self._source is not None
            remember_directory(self, "open-pdf", self._source)
            count = int(cast(int, message["page_count"]))
            self.session = BookSession.from_data({
                "format": "pdf-bookmarks-session", "version": 1, "source": str(self._source),
                "page_count": count, "labels": message["labels"], "bookmarks": message["bookmarks"]}, Path.cwd())
            self.session.api = self._read_api()
            self.pages.clearSelection()
            self._undo.clear()
            self.password = str(message.get("password", ""))
            self._shown = None
            self.preview_cache.clear()
            self.viewer.clear()
            self.viewer.set_crop(None)
            self._loading = True
            for spin in (self.page_number, self.toc_first, self.toc_last, self.body_pdf):
                spin.setRange(1, count)
            self.page_total.setText(f" / {count} ")
            self.body_pdf.setValue(self.session.body_pdf)
            self.body_book.setValue(self.session.body_book)
            self.toc_first.setValue(min(self.session.toc) if self.session.toc else 1)
            self.toc_last.setValue(max(self.session.toc) if self.session.toc else 1)
            self.api_url.setEditText(self.session.api.base_url)
            self.api_model.setCurrentText(self.session.api.model)
            self.temperature.setValue(self.session.api.temperature)
            self.max_tokens.setValue(self.session.api.max_tokens)
            self.timeout.setValue(self.session.api.timeout_seconds)
            self.context_images.setValue(self.session.api.max_context_images)
            self._refresh_reasoning_options(self.session.api.reasoning_effort)
            self.skip_certificate_verification.setChecked(self.session.api.skip_certificate_verification)
            self.append_existing.setChecked(self.session.keep_existing)
            self.only_pending.setChecked(self.session.pending_only)
            self.clear_context.setChecked(self.session.clear_context)
            self._loading = False
            self.dirty = False
            self._refresh_tree()
            self._refresh_pages()
            self._load_page()
            self.setWindowTitle(f"{self.session.source.name} — PDF Bookmark Editor")
            self._render("preview")
        elif kind == "preview" and self.session:
            page = int(cast(int, message["page"]))
            angle = float(cast(float, message["angle"]))
            pixmap = self.preview_buffer.read(int(cast(int, message["width"])), int(cast(int, message["height"])))
            self.preview_cache.put(page, (angle, pixmap))
            self._show_preview(page, angle, pixmap)
            self._continue_recognition()
        elif kind == "exported":
            assert self.session is not None
            self.status.setText(f"PDF saved: {message['path']}")
            self.dirty = False
            self.setWindowTitle(f"{self.session.source.name} — PDF Bookmark Editor")
            QtWidgets.QMessageBox.information(self, "PDF processing complete", f"Saved:\n{message['path']}")
            callback, self._after_export = self._after_export, None
            if callback:
                QtCore.QTimer.singleShot(0, callback)
        self._enabled()
        if self._close_when_idle and not self.runner.busy and not self._running and self.client.reply is None:
            QtCore.QTimer.singleShot(0, self.close)

    def _export(self) -> bool:
        if self.session is None or self.runner.busy or self._api_busy:
            return False
        if self.draft_timer.isActive() and not self._apply_yaml():
            self._error("Fix the current YAML draft before exporting, or restore its previous valid contents.")
            return False
        invalid = [str(page) for page, task in sorted(self.session.toc.items())
                   if task.draft_invalid]
        if invalid:
            self._error(f"Fix or reapply invalid YAML on TOC page(s): {', '.join(invalid)}.")
            return False
        try:
            self.tree.rows()  # Invalid inline edits must not export the previous value silently.
            self.session.validate_export()
        except ValueError as exc:
            self._error(str(exc))
            return False
        try:
            choice = choose_pdf_output(self, self.session.source,
                self.session.source.with_name(f"{self.session.source.stem}_bookmarked.pdf"))
        except OSError as exc:
            self._error(str(exc))
            return False
        if choice:
            selected, overwrite = choice
            self._purpose = "export"
            return self.runner.start(cast(dict[str, Json], {"operation": "export", "path": str(self.session.source),
                "password": self.password, "output": str(selected), "session": self.session.to_data(),
                "overwrite": overwrite}))
        return False

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Stop network work, retain results, and offer PDF export before exit."""
        self._pending_recognition = None
        if self.balance_client.reply is not None:
            self._close_when_idle = True
            self.balance_client.cancel("Balance lookup stopped.")
            event.ignore()
            return
        if self._api_busy or self.client.reply is not None:
            self._close_when_idle = True
            self._stop()
        if self.runner.busy or self.client.reply is not None or self.balance_client.reply is not None:
            self._close_when_idle = True
            self.runner.stop()
            event.ignore()
            return
        if not self._discard(self.close):
            self._close_when_idle = False
            event.ignore()
            return
        if not self._save_api_preferences():
            self._close_when_idle = False
            event.ignore()
            return
        self._closing = True
        self.runner.shutdown()
        self.preview_cache.clear()
        self.preview_buffer.close()
        if self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False
        event.accept()


def main(entry: Path, initial_tab: int = 0) -> int:
    """Launch the Fusion-themed bookmarks/labels desktop application."""
    application = QtWidgets.QApplication.instance()
    owns = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A GUI QApplication is required.")
    application.setStyle("Fusion")
    install_no_wheel_controls(application)
    window = BookmarksWindow(entry)
    window.tabs.setCurrentIndex(initial_tab)
    window.show()
    if owns:
        return application.exec()
    application.setProperty("pdfBookmarksWindow", window)
    return 0
