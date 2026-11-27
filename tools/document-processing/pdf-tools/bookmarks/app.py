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
from utils.qt_images import copy_image_to_clipboard
from utils.gui_colors import TextColor
from utils.qt_styles import on_theme_change, set_button_style, set_text_style, theme_text_color
from utils.qt_widgets import configure_qt_application, monospace_ui_font

from utils import *
from ..common.bookmark_editor import BookmarkEditor, OutlineRow
from ..common.crop_viewer import Rectangle
from ..common.file_drop import FileDropFilter
from ..common.file_actions import choose_pdf_output
from ..common.tooltips import TooltipFilter
from ..common.jobs import JobRunner
from ..common.page_toolbar import set_preview_tab_order
from ..common.llm_window import LlmWindow
from ..common.task_buttons import TaskButtons
from ..common.preferences import choose_open_file, remember_directory
from ..common.protocol import Json
from ..common.page_cache import PageCache, pixmap_bytes
from ..common.preview_buffer import PreviewBuffer
from ..common.range_input import RangeInput
from .recognition import SYSTEM_PROMPT, build_request
from .model import MAX_DRAFT, Bookmark, BookSession, ConversationTurn, NeedsInformation, Status, TocPage
from .ui_mainwindow import Ui_BookmarksWindow

STATUS_COLORS: dict[Status, TextColor] = {
    Status.PENDING: "blue", Status.DONE: "green", Status.MODIFIED: "green",
    Status.ERROR: "red", Status.NEEDS_INFO: "red",
}



class BookmarksWindow(LlmWindow, Ui_BookmarksWindow):
    """Own a single book and its ordered recognition queue, with explicit PDF export."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.session: BookSession | None = None
        self.password = ""
        self.dirty = False
        self._loading = False
        self._init_api_state()
        self._source: Path | None = None
        self._running = False
        self._queue_pause_requested = False
        self._recognition_paused = False
        self._problem_page: int | None = None
        self._after_export: Callable[[], object] | None = None
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
        self._init_api_clients()
        self.runner.completed.connect(self._completed)
        self.runner.busyChanged.connect(self._enabled)
        self.runner.controlChanged.connect(self._enabled)
        self.runner.controlStatus.connect(lambda text: self.status.setText(text))
        self.runner.progress.connect(lambda message: self.status.setText(str(message.get("stage", "Processing..."))))
        self.draft_timer = QtCore.QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(400)
        self.draft_timer.timeout.connect(self._apply_yaml)
        self._build()
        self.tooltips = TooltipFilter(self)
        self.setAcceptDrops(True)
        self.file_drops = FileDropFilter(self, self.open_path, lambda: not self._api_busy and not self.runner.busy, suffixes=(".pdf",))
        self._enabled()

    def _build(self, *, preserve_size: bool = False) -> None:
        size = self.size()
        self.setupUi(self)
        if preserve_size:
            self.resize(size)
        self.open_button.clicked.connect(self._open_dialog)
        self.close_pdf_button.clicked.connect(self._close_pdf)
        for spin in (self.toc_first, self.toc_last, self.body_pdf):
            spin.setRange(1, 1)
            spin.setKeyboardTracking(False)
        self.body_book.setRange(1, 1_000_000)
        self.body_book.setKeyboardTracking(False)
        self.current_page_buttons = [self.toc_first_current_button, self.toc_last_current_button, self.body_pdf_current_button]
        for button, spin in zip(self.current_page_buttons, (self.toc_first, self.toc_last, self.body_pdf)):
            button.clicked.connect(lambda _checked=False, target=spin: self._use_current_page(target))
            button.setToolTip("Fill this field with the currently displayed physical PDF page.")
        self.body_pdf.editingFinished.connect(self._mapping_changed)
        self.body_book.editingFinished.connect(self._mapping_changed)
        self.mark_toc_button.clicked.connect(self._mark_toc)
        self.clear_toc_button.clicked.connect(self._clear_toc)
        self.clear_toc_button.setToolTip("Clear all TOC tasks and recognition settings; keep existing bookmarks.")
        self.angle.setRange(-180, 180)
        self.angle.setDecimals(1)
        self.angle.setSuffix(" °")
        self.angle.setKeyboardTracking(False)
        self.angle.editingFinished.connect(self._rotation_changed)
        self.draw_crop.toggled.connect(self._enabled)
        self.whole_page.clicked.connect(self._whole_page)
        self.unmark.clicked.connect(self._unmark_toc)
        self.requirement_scope.addItems(["Whole book", "Current TOC page"])
        self.requirement_scope.currentIndexChanged.connect(self._load_requirements)
        self.requirements.setPlaceholderText("Transcription requirements or retry corrections (whole book / current page)")
        self.requirements.textChanged.connect(self._requirements_changed)
        self.clear_context.setToolTip("Clear previous LLM exchanges once before the queue starts. Keeps recognized results, drafts and your requirements. Current-page diagnostics still accompany retries.")
        self.only_pending.setChecked(True)
        self.append_existing.setToolTip("Keep original bookmarks alongside recognized entries when applying YAML.")
        for check in (self.clear_context, self.only_pending, self.append_existing):
            check.toggled.connect(self._options_changed)
        self.add_roots.clicked.connect(self._add_roots)
        self.clear_bookmarks.clicked.connect(self._clear_bookmarks)
        self.undo_bookmarks.clicked.connect(self._undo_bookmarks)

        self.tabs.insertTab(1, self._api_form(SYSTEM_PROMPT), "API")

        self.label_range = QtWidgets.QLineEdit()
        self.label_range.setPlaceholderText("1,2,5-10,-1; append |odd or |even")
        self.label_first.setRange(-1_000_000, 1_000_000)
        self.label_first.setValue(1)
        self.label_first.setKeyboardTracking(False)
        self.label_range_input = RangeInput(self.label_range)
        self.range_slot.addWidget(self.label_range_input)
        self.label_numbered.clicked.connect(self._label_numbered)
        self.label_clear.clicked.connect(self._label_clear)
        self.label_clear_all.clicked.connect(lambda: self._label_clear(True))
        self.generate_labels.clicked.connect(self._label_generate)
        set_button_style(self.generate_labels, "blue")

        self.run_button.clicked.connect(lambda: self._request_recognition(self._run_all))
        set_button_style(self.run_button, "blue")
        self.retry_button.clicked.connect(lambda: self._request_recognition(self._retry))
        self.retry_all_button.clicked.connect(lambda: self._request_recognition(self._retry_all))
        self.retry_all_button.setToolTip("Resend every marked TOC page in page order, even accepted pages. Ignores the pending-only checkbox; each reply replaces only its source page's results.")
        for button in (self.run_button, self.retry_button, self.retry_all_button):
            # Receive mouse clicks before committing the focused editor. Its
            # focus-out may start a render and disable this button mid-click.
            # Tab focus keeps keyboard activation available.
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.TabFocus)
        self.yaml.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.yaml.setFont(monospace_ui_font())
        self.yaml.setPlaceholderText('- {page: 1, level: 1, index: "", title: "Introduction"}')
        self.yaml.textChanged.connect(self._yaml_changed)
        self.trace.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.trace.setReadOnly(True)
        self.trace.setPlaceholderText("Request settings, problems and original replies for this page appear here. Kept in memory only.")
        self.information_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.information.setReadOnly(True)
        self.information.setPlaceholderText("Questions, requested information and errors for this page.")
        self.information_input.setPlaceholderText("Answer the questions above or correct this page's instructions. Connection errors can be retried without an answer.")
        self.information_input.textChanged.connect(self._information_changed)
        self.information_retry.clicked.connect(self._retry_information)
        self.yaml_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.apply_yaml.clicked.connect(self._apply_yaml)
        self.supplement_button.clicked.connect(self._supplement)
        self.copy_image.clicked.connect(self._copy_image)
        self.result_tabs.currentChanged.connect(self._result_tab_changed)

        self.viewer.cropChanged.connect(self._crop_changed)
        self.toolbar.bind_viewer(self.viewer)
        self.toolbar.stepRequested.connect(self._step)
        self.toolbar.pageRequested.connect(self.go_page)
        self.page_number = self.toolbar.page_number
        self.tree = BookmarkEditor(editable=True, show_level=True,
                                   current_page=lambda: self.session.current_page if self.session else 1)
        self.tree.changed.connect(self._tree_changed)
        self.tree.pageRequested.connect(lambda index: self.go_page(index + 1))
        on_theme_change(self.pages, self._refresh_page_colors)
        self.pages.pageRequested.connect(lambda index: self.go_page(index + 1))
        self.pages.setToolTip("Click or use arrow/PgUp/PgDn keys to turn pages. Ctrl/Shift selects multiple pages.")
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
        self.delete_pages_button.clicked.connect(self._delete_pages)
        self.navigation.insertTab(0, self.tree, "Bookmarks")
        self.navigation.setCurrentIndex(0)
        self.content.setStretchFactor(0, 1)
        self.content.setSizes([650, 320])
        self.progress_bar.setVisible(False)
        self.balance_summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.task_buttons = TaskButtons(self.runner, external_pause=self._toggle_queue_pause, external_stop=self._stop)
        self.pause_button = self.task_buttons.pause_button
        self.stop_button = self.task_buttons.stop_button
        self.task_slot.addWidget(self.task_buttons)
        self.export_button.clicked.connect(self._export)
        set_button_style(self.export_button, "blue")
        self.splitter.setSizes([420, 1080])
        set_preview_tab_order(self.left, self.toolbar, self.content, self.task_buttons, self.export_button)
        if self._api_loaded:
            self._show_api_profiles()
        else:
            self._load_api_preferences()

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
        self.recognition_scroll.setEnabled(loaded and not waiting)
        self.labels_tab.setEnabled(loaded and not waiting)
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
        self.toolbar.set_navigation_enabled(loaded and browsing, session.current_page if session else 1,
                                            session.page_count if session else 0)
        self.task_buttons.set_external_state(
            self._api_busy or self.balance_client.reply is not None or self._pending_recognition is not None,
            pausable=self._running and not (self._recognition_paused and self.runner.busy),
            pause_requested=self._queue_pause_requested)
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
        self._build(preserve_size=True)
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

    def _api_edited(self) -> None:
        if self.session:
            self._sync_api()
            self._mark_dirty()

    def _sync_api(self) -> None:
        if self.session:
            self.session.api = self._read_api()

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
                item.setToolTip(2, task.error)
                if task.status in (Status.DONE, Status.MODIFIED, Status.ERROR, Status.NEEDS_INFO):
                    font = item.font(2)
                    font.setBold(True)
                    item.setFont(2, font)
            self.pages.addTopLevelItem(item)
            item.setSelected(page in selected)
        self._refresh_page_colors()
        self.pages.select_page(self.session.current_page - 1, preserve_selection=True)

    def _refresh_page_colors(self) -> None:
        if self.session is None:
            return
        for page, task in self.session.toc.items():
            item = self.pages.topLevelItem(page - 1)
            if item is not None:
                item.setForeground(0, QtGui.QBrush(theme_text_color("red", self.pages)))
                if color := STATUS_COLORS.get(task.status):
                    item.setForeground(2, QtGui.QBrush(theme_text_color(color, self.pages)))

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
        set_text_style(self.yaml_status, "red" if task and task.error else None)
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
        for spin in (self.toc_first, self.toc_last, self.body_pdf):
            spin.setRange(1, session.page_count)
        self.toolbar.set_page_count(session.page_count)
        self.body_pdf.setValue(session.body_pdf)
        self.body_book.setValue(session.body_book)
        self.toc_first.setValue(min(session.toc) if session.toc else session.current_page)
        self.toc_last.setValue(max(session.toc) if session.toc else session.current_page)
        self.label_range.clear()
        self._loading = False
        self.pages.clearSelection()
        self._refresh_pages()
        page_item = self.pages.topLevelItem(session.current_page - 1)
        if page_item is not None:
            page_item.setSelected(True)
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
            set_text_style(self.yaml_status, None)
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
            set_text_style(self.yaml_status, "red")
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
            copy_image_to_clipboard(self._image())
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
            for spin in (self.toc_first, self.toc_last, self.body_pdf):
                spin.setRange(1, count)
            self.toolbar.set_page_count(count)
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
    configure_qt_application(application)
    window = BookmarksWindow(entry)
    window.tabs.setCurrentIndex(initial_tab)
    window.show()
    if owns:
        return application.exec()
    application.setProperty("pdfBookmarksWindow", window)
    return 0
