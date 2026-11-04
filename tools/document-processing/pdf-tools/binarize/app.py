"""PySide6 binarizer: profiles, lazy previews, shared navigation and JSON projects.

The left column owns file actions and profiles/settings for its full height.
A compact right toolbar owns page/view actions. PDF work uses one subprocess;
completed previews are cached in the GUI for immediate page revisits.
"""

import base64
from enum import StrEnum
from pathlib import Path
import sys
from typing import Callable, cast
from uuid import uuid4

from PySide6 import QtCore, QtGui, QtWidgets

from utils import *
from ..common.jobs import JobRunner
from ..common.file_drop import FileDropFilter
from ..common.file_actions import choose_pdf_output
from ..common.tooltips import TooltipFilter
from ..common.navigation import NavigationPane
from ..common.pdf_images import ImageElement
from ..common.protocol import Json
from ..common.preview_buffer import PreviewBuffer
from ..common.viewer import MAX_SCALE, MIN_SCALE, PageViewer, ViewMode
from .panel import SettingsPanel
from .preview_cache import PreviewCache, PreviewFrame, PreviewState, Rectangle
from .project import BUILTIN_IDS, DEFAULT_ID, SKIP_ID, Config, Project
from .settings import MAX_WORKERS

PREVIEW_DELAY_MS = 300
PROFILE_ROLE = QtCore.Qt.ItemDataRole.UserRole
ADMIN_DROP_HINT = ("Windows blocks Explorer drops into administrator windows. "
                   "Use Open PDF, or restart this app without administrator rights.")
PROFILE_VISIBLE_ROWS = 6
TOOLBAR_STYLE = "QToolBar::separator { background: palette(mid); width: 1px; margin: 4px 6px; }"


class Operation(StrEnum):
    NONE = "none"
    INSPECT = "inspect"
    PREVIEW = "preview"
    EXPORT = "export"
    EXPORT_PAGE = "export-page"


class ProfileTree(QtWidgets.QTreeWidget):
    """Two-column profile list; right-click actions do not assign a profile."""

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)


class BinarizeWindow(QtWidgets.QMainWindow):
    """Own the editable project and orchestrate one outstanding PDF operation.

    Args:
        entry: Path to the GUI launcher, used to start the isolated worker.

    The window never opens a PDF in its own process. User edits are committed to
    a validated project before a snapshot is sent to the worker. Navigation is
    delayed by 300 ms on processed cache misses. Original views and cache hits
    skip that delay. PDF-changing controls are locked while the worker runs.
    """

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.project: Project | None = None
        self.project_path: Path | None = None
        self.password = ""
        self.labels: list[str] = []
        self.dirty = False
        self._loading = False
        self._original_warning = False
        self._cursor_busy = False
        self._close_after_job = False
        self._closing = False
        self._operation = Operation.NONE
        self._pending_project: Project | None = None
        self._pending_project_path: Path | None = None
        self._pending_source: Path | None = None
        self._pending_password = ""
        self._pending_relocated = False
        self._cancel_marker: Path | None = None
        self._cancel_created = False
        self._displayed_page: int | None = None
        self._preview_requested = False
        self._preview_revision = 0
        self._inflight_preview: PreviewState | None = None
        self.preview_cache = PreviewCache()
        self._region_boxes: list[tuple[float, float, float, float]] = []
        self._regions_available = False
        self._elevated = sys.platform == "win32" and System.is_elevated()
        self.runner = JobRunner(entry, self)
        self.preview_buffer = PreviewBuffer()
        self.runner.busyChanged.connect(self._busy_changed)
        self.runner.completed.connect(self._completed)
        self.runner.progress.connect(self._progress)
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._start_preview)
        self.setWindowTitle("PDF Binarize [Administrator]" if self._elevated else "PDF Binarize")
        self.resize(1440, 900)
        self.setMinimumSize(980, 600)
        self.setAcceptDrops(True)
        self._build()
        self.tooltips = TooltipFilter(self)
        self.file_drops = FileDropFilter(self, self.open_path, lambda: not self.runner.busy)
        self._refresh_enabled()

    def _button(self, label: str, handler: Callable[[], object], *, compact: bool = False) -> QtWidgets.QAbstractButton:
        button = QtWidgets.QToolButton() if compact else QtWidgets.QPushButton()
        button.setText(label)
        button.clicked.connect(lambda: self._invoke(handler))
        return button

    def _invoke(self, handler: Callable[[], object]) -> None:
        """Suspend pending previews while dialogs run their nested event loops."""
        remaining = max(0, self.preview_timer.remainingTime())
        self.preview_timer.stop()
        try:
            handler()
        finally:
            if self._preview_requested and not self.runner.busy and not self.preview_timer.isActive():
                self._schedule_preview(remaining)

    def _build(self) -> None:
        # ── independent left column ──
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        self.left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(self.left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(4)
        self.file_toolbar = QtWidgets.QToolBar()
        self.file_toolbar.setStyleSheet(TOOLBAR_STYLE)
        self.open_pdf_button = self._button("Open PDF", self._choose_pdf, compact=True)
        self.open_project_button = self._button("Open project", self._choose_project, compact=True)
        self.save_project_button = self._button("Save", self._save_project, compact=True)
        self.save_as_button = self._button("Save as...", lambda: self._save_project(True), compact=True)
        self.close_pdf_button = self._button("Close", self._close_pdf, compact=True)
        self.open_pdf_button.setToolTip(ADMIN_DROP_HINT if self._elevated else "Open a PDF or drop one anywhere in this window")
        self.save_project_button.setToolTip("Save project")
        for button in (self.open_pdf_button, self.open_project_button):
            self.file_toolbar.addWidget(button)
        self.file_toolbar.addSeparator()
        for button in (self.save_project_button, self.save_as_button):
            self.file_toolbar.addWidget(button)
        self.file_toolbar.addSeparator()
        self.file_toolbar.addWidget(self.close_pdf_button)
        left_layout.addWidget(self.file_toolbar)
        self.profiles_box = QtWidgets.QGroupBox("Profiles")
        profile_layout = QtWidgets.QVBoxLayout(self.profiles_box)
        profile_layout.setContentsMargins(6, 6, 6, 6)
        profile_layout.setSpacing(4)
        self.profile_list = ProfileTree()
        self.profile_list.setHeaderLabels(["Profile", "Pages"])
        self.profile_list.setRootIsDecorated(False)
        self.profile_list.setUniformRowHeights(True)
        self.profile_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._profile_menu)
        self._resize_profile_list()
        self.profile_list.currentItemChanged.connect(self._profile_selected)
        # Clicking the already-current profile must also apply it to a selection.
        self.profile_list.itemClicked.connect(lambda item, column: self._profile_selected(item, None))
        profile_actions = QtWidgets.QHBoxLayout()
        self.add_profile_button = self._button("Add copy", self._add_profile)
        self.apply_profile_button = self._button("Apply to pages…", self._apply_profile_pages)
        profile_actions.addWidget(self.add_profile_button)
        profile_actions.addWidget(self.apply_profile_button)
        profile_actions.addStretch()
        profile_layout.addLayout(profile_actions)
        profile_layout.addWidget(self.profile_list)
        left_layout.addWidget(self.profiles_box)
        self.settings = SettingsPanel()
        self.settings.configChanged.connect(self._settings_changed)
        self.settings.validityChanged.connect(self._validity_changed)
        self.settings.interactionFinished.connect(self._resume_preview)
        self.output_tab = self._build_output()
        self.settings.addTab(self.output_tab, "Output")
        left_layout.addWidget(self.settings, 1)
        self.left.setMinimumWidth(330)
        splitter.addWidget(self.left)
        # ── right column: controls, preview/navigation, status ──
        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(4, 6, 6, 6)
        layout.setSpacing(4)
        self.view_toolbar = QtWidgets.QToolBar()
        self.view_toolbar.setStyleSheet(TOOLBAR_STYLE)
        self.previous_button = self._button("", lambda: self._step_page(-1), compact=True)
        self.next_button = self._button("", lambda: self._step_page(1), compact=True)
        for button, icon, label in ((self.previous_button, QtWidgets.QStyle.StandardPixmap.SP_ArrowLeft, "Previous page (PgUp)"),
                                    (self.next_button, QtWidgets.QStyle.StandardPixmap.SP_ArrowRight, "Next page (PgDown)")):
            button.setIcon(self.style().standardIcon(icon))
            button.setFixedWidth(26)
            button.setToolTip(label)
            button.setAccessibleName(label)
        self.page_number = QtWidgets.QSpinBox()
        self.page_number.setFixedWidth(48)
        self.page_number.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.page_number.setAccessibleName("Physical page number")
        self.page_number.setToolTip("Physical page number; press Enter or leave this field to jump")
        self.page_number.setRange(1, 1)
        self.page_number.setKeyboardTracking(False)
        self.page_number.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.page_number.editingFinished.connect(self._jump_page)
        self.page_total = QtWidgets.QLabel("/ 0")
        self.page_total.setContentsMargins(4, 0, 4, 0)
        self.original = QtWidgets.QCheckBox("Show original")
        self.original.toggled.connect(self._original_changed)
        for widget in (self.previous_button, self.next_button, self.page_number, self.page_total):
            self.view_toolbar.addWidget(widget)
        self.view_toolbar.addSeparator()
        self.viewer = PageViewer()
        self.viewer.pageStepRequested.connect(self._step_page)
        for label, handler in (("Fit page", self.viewer.fit_page), ("Fit width", self.viewer.fit_width),
                               ("100%", self.viewer.actual_pixels)):
            self.view_toolbar.addWidget(self._button(label, handler, compact=True))
        self.zoom = QtWidgets.QDoubleSpinBox()
        self.zoom.setRange(MIN_SCALE * 100, MAX_SCALE * 100)
        self.zoom.setDecimals(1)
        self.zoom.setValue(100)
        self.zoom.setSuffix(" %")
        self.zoom.setFixedWidth(82)
        self.zoom.setKeyboardTracking(False)
        self.zoom.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.zoom.setToolTip("Zoom percentage; press Enter or leave this field to apply")
        self.zoom.editingFinished.connect(lambda: self.viewer.set_zoom(self.zoom.value()))
        self.viewer.zoomChanged.connect(self.zoom.setValue)
        self.view_toolbar.addWidget(self.zoom)
        self.auto_fit = QtWidgets.QCheckBox("Auto fit")
        self.auto_fit.setChecked(True)
        self.auto_fit.setToolTip("Automatically fit the whole page after every page turn")
        self.auto_fit.toggled.connect(self._auto_fit_changed)
        self.view_toolbar.addWidget(self.auto_fit)
        self.view_toolbar.addSeparator()
        self.view_toolbar.addWidget(self.original)
        self.show_regions = QtWidgets.QCheckBox("Red boxes")
        self.show_regions.setToolTip("Overlay detected image regions; exported PDFs never include these boxes")
        self.show_regions.toggled.connect(self._show_regions_changed)
        self.view_toolbar.addWidget(self.show_regions)
        layout.addWidget(self.view_toolbar)
        content = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        content.addWidget(self.viewer)
        self.navigation = NavigationPane()
        self.navigation.pageRequested.connect(lambda index: self.go_page(index, preserve_selection=True))
        self.navigation.imageSelected.connect(self.viewer.set_image_highlight)
        self.navigation.pages.itemSelectionChanged.connect(self._selection_summary)
        content.addWidget(self.navigation)
        content.setStretchFactor(0, 1)
        content.setSizes([720, 240])
        layout.addWidget(content, 1)
        self.status = QtWidgets.QLabel("Ready. No PDF loaded." if not self._elevated
                                      else "Administrator: Explorer drops blocked. Use Open PDF.")
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        bottom = QtWidgets.QHBoxLayout()
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(120)
        self.cancel_button = self._button("Cancel", self._cancel_export)
        self.preview_export_button = self._button("Save shown page", lambda: self._export(True))
        self.export_button = self._button("Export PDF", lambda: self._export(False))
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.progress_bar)
        for button in (self.cancel_button, self.preview_export_button, self.export_button):
            bottom.addWidget(button)
        layout.addLayout(bottom)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1050])

    def _resize_profile_list(self) -> None:
        """Double the former list height, bounded to four through twelve rows."""
        row_height = max(self.profile_list.sizeHintForRow(0), self.profile_list.fontMetrics().height() + 4)
        rows = 2 * min(PROFILE_VISIBLE_ROWS, max(2, self.profile_list.topLevelItemCount()))
        self.profile_list.setFixedHeight(rows * row_height + self.profile_list.header().sizeHint().height()
                                        + 2 * self.profile_list.frameWidth())

    def _build_output(self) -> QtWidgets.QWidget:
        body = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(body)
        general = QtWidgets.QGroupBox("Export")
        layout = QtWidgets.QFormLayout(general)
        outer.addWidget(general)
        self.workers = QtWidgets.QSpinBox()
        self.workers.setRange(1, MAX_WORKERS)
        self.workers.setKeyboardTracking(False)
        self.workers.editingFinished.connect(self._output_changed)
        layout.addRow("Image encoders", self.workers)
        self.save_regions = QtWidgets.QCheckBox("Export region JSON")
        self.save_annotations = QtWidgets.QCheckBox("Export box annotation PNGs")
        self.open_saved_preview = QtWidgets.QCheckBox("Open saved page in external viewer")
        self.open_saved_preview.setChecked(True)
        layout.addRow(self.open_saved_preview)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        outer.addWidget(line)
        review = QtWidgets.QGroupBox("Optional region review files")
        layout = QtWidgets.QFormLayout(review)
        outer.addWidget(review)
        for widget in (self.save_regions, self.save_annotations, self.open_saved_preview):
            widget.toggled.connect(self._output_changed)
            if widget is not self.open_saved_preview:
                layout.addRow(widget)
        self.region_path = QtWidgets.QLineEdit()
        self.region_path.setPlaceholderText("Optional region JSON")
        self.region_path.editingFinished.connect(self._output_changed)
        layout.addRow("Region input", self.region_path)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._button("Browse regions...", self._browse_regions))
        row.addWidget(self._button("Clear", self._clear_regions))
        layout.addRow(row)
        note = QtWidgets.QLabel("These settings apply to the whole project.\nExport defaults to the source PDF folder.\nExisting outputs require overwrite confirmation; the source is protected.")
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    def _refresh_enabled(self) -> None:
        loaded = self.project is not None
        idle = not self.runner.busy
        self.profiles_box.setEnabled(loaded and idle)
        self.settings.setEnabled(loaded and idle)
        for button in (self.open_pdf_button, self.open_project_button):
            button.setEnabled(idle)
        for widget in (self.save_project_button, self.save_as_button, self.page_number,
                       self.original, self.auto_fit, self.show_regions, self.navigation, self.close_pdf_button):
            widget.setEnabled(loaded and idle)
        for button in (self.preview_export_button, self.export_button):
            button.setEnabled(loaded and idle and self.settings.valid)
        exporting = self.runner.busy and self._operation in (Operation.EXPORT, Operation.EXPORT_PAGE)
        self.cancel_button.setEnabled(exporting and not self._cancel_created)
        self.cancel_button.setVisible(exporting)
        self.progress_bar.setVisible(exporting)
        index = self.project.current_page if self.project else 0
        count = self.project.page_count if self.project else 0
        self.previous_button.setEnabled(loaded and idle and index > 0)
        self.next_button.setEnabled(loaded and idle and index + 1 < count)
        self.viewer.navigation_enabled = loaded and idle
        identity = self.project.assignments[index] if self.project else SKIP_ID
        for tab in range(self.settings.count() - 1):
            self.settings.widget(tab).setEnabled(loaded and idle and identity != SKIP_ID)

    def _busy_changed(self, busy: bool) -> None:
        if busy and not self._cursor_busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.BusyCursor)
            self._cursor_busy = True
        elif not busy and self._cursor_busy:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_busy = False
        self._refresh_enabled()

    def _validity_changed(self, valid: bool) -> None:
        if not hasattr(self, "export_button"):
            return
        if not valid:
            self.preview_timer.stop()
            self.status.setText(f"Invalid settings: {self.settings.error.text()}")
        self._refresh_enabled()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._title()

    def _title(self) -> None:
        name = self.project.source.name if self.project else "No document"
        elevation = " [Administrator]" if self._elevated else ""
        self.setWindowTitle(f"{'* ' if self.dirty else ''}{name} - PDF Binarize{elevation}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        choice = QtWidgets.QMessageBox.question(self, "Unsaved project", "Save your profile and page changes?",
            QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard |
            QtWidgets.QMessageBox.StandardButton.Cancel, QtWidgets.QMessageBox.StandardButton.Save)
        if choice == QtWidgets.QMessageBox.StandardButton.Save:
            return self._save_project()
        return choice == QtWidgets.QMessageBox.StandardButton.Discard

    def _choose_pdf(self) -> None:
        if self.runner.busy:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if path:
            self.open_path(Path(path))

    def _choose_project(self) -> None:
        if self.runner.busy:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open project", "", "PDF projects (*.json)")
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        """Open a dropped/chosen PDF or project asynchronously, preserving old state on failure."""
        if self.runner.busy:
            return
        self.preview_timer.stop()
        if not self._confirm_discard():
            self._resume_preview()
            return
        try:
            self._pending_relocated = False
            pending = Project.load(path) if path.suffix.lower() == ".json" else None
            source = pending.source if pending else path
            if pending is not None and not source.is_file():
                replacement, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, f"Locate missing PDF: {source.name}", str(path.parent), "PDF files (*.pdf)")
                if not replacement:
                    return
                source = Path(replacement)
                pending.source = source
                self._pending_relocated = True
            self._pending_project = pending
            self._pending_project_path = path if pending else None
            self._pending_source = source.resolve()
            self._pending_password = ""
            self._inspect_pending()
        except (OSError, ValueError) as exc:
            self._error(str(exc))

    def _inspect_pending(self) -> None:
        if self._pending_source is None:
            return
        self._operation = Operation.INSPECT
        self.preview_timer.stop()
        self._preview_requested = False
        self.status.setText(f"Opening {self._pending_source.name}...")
        self.runner.start({"operation": self._operation.value, "path": str(self._pending_source),
                           "password": self._pending_password})

    def _adopt(self, message: dict[str, Json]) -> None:
        if self._pending_source is None:
            return
        count = int(cast(int, message["page_count"]))
        if self._pending_project and count != self._pending_project.page_count:
            dialog = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Critical, "Page count mismatch",
                f"This project expects {self._pending_project.page_count} pages; the PDF has {count}.", parent=self)
            choose = dialog.addButton("Choose PDF again", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
            another = dialog.addButton("Open another project", QtWidgets.QMessageBox.ButtonRole.ActionRole)
            dialog.addButton("Exit", QtWidgets.QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is choose:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select matching PDF", "", "PDF files (*.pdf)")
                if path:
                    self._pending_source = Path(path)
                    self._pending_project.source = Path(path)
                    self._pending_relocated = True
                    self._pending_password = ""
                    self._inspect_pending()
            elif dialog.clickedButton() is another:
                self._choose_project()
            return
        self.project = self._pending_project or Project.create(self._pending_source, count)
        self.project_path = self._pending_project_path
        self.password = str(message.get("password", ""))
        self.labels = cast(list[str], message["labels"])
        bookmarks = [(int(row[0]), str(row[1]), int(row[2])) for row in cast(list[list[Json]], message["bookmarks"])]
        self.navigation.load(self.labels, bookmarks)
        self.viewer.clear()
        self.preview_cache.clear()
        self._inflight_preview = None
        self._displayed_page = None
        self.open_pdf_button.setToolTip(f"{self.project.source}\n{ADMIN_DROP_HINT}" if self._elevated else str(self.project.source))
        self.page_number.setRange(1, count)
        self._original_warning = False
        self._load_profiles()
        self._load_current_page()
        self.dirty = self._pending_relocated
        self._title()
        self._schedule_preview()

    def _load_profiles(self) -> None:
        if self.project is None:
            return
        self._loading = True
        try:
            self.profile_list.clear()
            for identity, profile in self.project.profiles.items():
                item = QtWidgets.QTreeWidgetItem([profile.name, ""])
                item.setData(0, PROFILE_ROLE, identity)
                self.profile_list.addTopLevelItem(item)
            self._resize_profile_list()
        finally:
            self._loading = False

    def _load_current_page(self) -> None:
        if self.project is None:
            return
        self._loading = True
        try:
            project = self.project
            index = project.current_page
            identity = project.assignments[index]
            for row in range(self.profile_list.topLevelItemCount()):
                if self.profile_list.topLevelItem(row).data(0, PROFILE_ROLE) == identity:
                    self.profile_list.setCurrentItem(self.profile_list.topLevelItem(row))
                    break
            self.settings.imported_regions = project.output.region_input is not None
            self.settings.set_config(project.profiles[identity].config)
            self.page_number.setValue(index + 1)
            label = self.labels[index] if index < len(self.labels) else ""
            self.page_total.setText(f"/ {project.page_count}")
            self.page_total.setToolTip(f"PDF page label: {label}" if label else "Physical page count")
            self.original.setChecked(project.show_original)
            self.auto_fit.setChecked(project.auto_fit)
            self.viewer.auto_fit = project.auto_fit
            self.show_regions.setChecked(project.show_regions)
            self.workers.setValue(project.output.workers)
            self.save_regions.setChecked(project.output.export_regions)
            self.save_annotations.setChecked(project.output.annotate_regions)
            self.open_saved_preview.setChecked(project.output.open_preview)
            self.region_path.setText(str(project.output.region_input or ""))
            self.navigation.select_page(index, preserve_selection=True)
            self._profile_summary()
        finally:
            self._loading = False
        self._warning_style()
        self._refresh_enabled()

    def _profile_summary(self) -> None:
        if self.project is None:
            return
        self._selection_summary()
        self.navigation.set_profiles([self.project.profiles[value].name for value in self.project.assignments])

    def _selection_summary(self) -> None:
        if self.project is None:
            return
        for row in range(self.profile_list.topLevelItemCount()):
            item = self.profile_list.topLevelItem(row)
            identity = item.data(0, PROFILE_ROLE)
            pages = [index + 1 for index, value in enumerate(self.project.assignments) if value == identity]
            if identity == DEFAULT_ID:
                item.setText(1, "")
                item.setToolTip(1, f"Default profile: {len(pages)} page(s).")
                continue
            ranges = Input.format_integer_ranges(Input.merge_integer_ranges(pages))
            item.setText(1, ranges or "—")
            item.setToolTip(1, f"{len(pages)} page(s): {ranges}")

    def _profile_selected(self, current: QtWidgets.QTreeWidgetItem | None,
                          previous: QtWidgets.QTreeWidgetItem | None) -> None:
        if self._loading or self.runner.busy or self.project is None or current is None:
            return
        identity = str(current.data(0, PROFILE_ROLE))
        selected = self.navigation.selected_pages() or (self.project.current_page,)
        if all(self.project.assignments[index] == identity for index in selected):
            return
        if not self.settings.commit_pending():
            self._load_current_page()
            return
        for index in selected:
            self.project.assignments[index] = identity
        if self.project.current_page not in selected:
            self.project.current_page = selected[0]
        self._mark_dirty()
        self._load_current_page()
        self._profile_changed_preview()

    def _add_profile(self) -> None:
        if self.project is None or self.runner.busy:
            return
        if not self.settings.commit_pending():
            return
        try:
            name, accepted = QtWidgets.QInputDialog.getText(self, "Add profile", "Name:",
                                                           text=str(self.project.current_page + 1))
            if not accepted:
                return
            identity = self.project.add_profile(name, self.project.assignments[self.project.current_page])
            selected = self.navigation.selected_pages() or (self.project.current_page,)
            for index in selected:
                self.project.assignments[index] = identity
            if self.project.current_page not in selected:
                self.project.current_page = selected[0]
            self._load_profiles()
            self._load_current_page()
            self._mark_dirty()
            self._profile_changed_preview()
        except ValueError as exc:
            self._error(str(exc))

    def _rename_profile(self, identity: str | None = None) -> None:
        if self.project is None or self.runner.busy:
            return
        identity = identity or self.project.assignments[self.project.current_page]
        if identity in BUILTIN_IDS:
            return
        name, accepted = QtWidgets.QInputDialog.getText(self, "Rename profile", "Name:",
                                                       text=self.project.profiles[identity].name)
        if accepted:
            try:
                self.project.rename(identity, name)
                self._load_profiles()
                self._load_current_page()
                self._mark_dirty()
            except ValueError as exc:
                self._error(str(exc))

    def _delete_profile(self, identity: str | None = None) -> None:
        if self.project is None or self.runner.busy:
            return
        identity = identity or self.project.assignments[self.project.current_page]
        if identity in BUILTIN_IDS:
            return
        alternatives = [profile for profile in self.project.profiles.values() if profile.id != identity]
        name, accepted = QtWidgets.QInputDialog.getItem(self, "Delete profile",
            f"Replace it on {self.project.assignments.count(identity)} page(s) with:",
            [profile.name for profile in alternatives], 0, False)
        if accepted:
            replacement = next(profile.id for profile in alternatives if profile.name == name)
            self.project.remove(identity, replacement)
            self._load_profiles()
            self._load_current_page()
            self._mark_dirty()
            self._profile_changed_preview()

    def _apply_profile_pages(self, identity: str | None = None) -> None:
        if self.project is None or self.runner.busy or not self.settings.commit_pending():
            return
        identity = identity or self.project.assignments[self.project.current_page]
        value, accepted = QtWidgets.QInputDialog.getText(
            self, "Apply profile to pages", "Physical pages (1,2,4-10 or all):")
        if not accepted:
            return
        try:
            self.project.assign(identity, value)
            self._mark_dirty()
            self._load_current_page()
            self._profile_changed_preview()
        except ValueError as exc:
            self._error(str(exc))

    def _profile_menu(self, point: QtCore.QPoint) -> None:
        item = self.profile_list.itemAt(point)
        if item is None or self.project is None or self.runner.busy:
            return
        identity = str(item.data(0, PROFILE_ROLE))
        menu = QtWidgets.QMenu(self)
        menu.addAction("Apply to pages…", lambda: self._invoke(lambda: self._apply_profile_pages(identity)))
        menu.addSeparator()
        for label, callback in (("Rename", self._rename_profile), ("Delete", self._delete_profile)):
            action = menu.addAction(label, lambda checked=False, action=callback: self._invoke(lambda: action(identity)))
            action.setEnabled(identity not in BUILTIN_IDS)
        self._invoke(lambda: menu.exec(self.profile_list.viewport().mapToGlobal(point)))

    def _close_pdf(self) -> None:
        if self.project is None or self.runner.busy or not self._confirm_discard():
            return
        self.preview_timer.stop()
        self._preview_requested = False
        self.runner.shutdown()
        self.preview_buffer.close()
        self.preview_buffer = PreviewBuffer()
        self.preview_cache.clear()
        self.project = self.project_path = None
        self.password = ""
        self.labels = []
        self.dirty = False
        self._pending_project = self._pending_project_path = self._pending_source = None
        self._pending_password = ""
        self._pending_relocated = False
        self._displayed_page = self._inflight_preview = None
        self._original_warning = False
        self._region_boxes = []
        self._regions_available = False
        self._preview_revision += 1
        old = self.takeCentralWidget()
        if old:
            old.deleteLater()
        self._build()
        self.setWindowTitle("PDF Binarize [Administrator]" if self._elevated else "PDF Binarize")
        self._refresh_enabled()

    def _settings_changed(self, config: Config) -> None:
        if self._loading or self.runner.busy or self.project is None:
            return
        identity = self.project.assignments[self.project.current_page]
        if identity == SKIP_ID:
            return
        self.project.profiles[identity].config = config
        self._mark_dirty()
        self._profile_changed_preview()

    def _output_changed(self) -> None:
        if self._loading or self.runner.busy or self.project is None:
            return
        options = self.project.output
        old_region = options.region_input
        options.workers = self.workers.value()
        options.export_regions = self.save_regions.isChecked()
        options.annotate_regions = self.save_annotations.isChecked()
        options.open_preview = self.open_saved_preview.isChecked()
        text = self.region_path.text().strip()
        options.region_input = Path(text).expanduser().resolve() if text else None
        self.settings.imported_regions = options.region_input is not None
        self.settings._availability()
        self._mark_dirty()
        if old_region != options.region_input:
            self._profile_changed_preview()

    def _browse_regions(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import region JSON", "", "JSON files (*.json)")
        if path:
            self.region_path.setText(path)
            self._output_changed()

    def _clear_regions(self) -> None:
        self.region_path.clear()
        self._output_changed()

    def go_page(self, index: int, *, preserve_selection: bool = False) -> None:
        """Select a page, showing cache hits immediately and delaying processed misses.

        Args:
            index: Zero-based physical page number.
            preserve_selection: Keep the page-tree batch selection during tree navigation.
        """
        if self.project is None or self.runner.busy or not 0 <= index < self.project.page_count:
            return
        if index == self.project.current_page:
            return
        if not self.settings.commit_pending():
            self.page_number.setValue(self.project.current_page + 1)
            return
        self.project.current_page = index
        self.navigation.select_page(index, preserve_selection=preserve_selection)
        if self.project.show_original:
            self._original_warning = True
        self._load_current_page()
        self._schedule_preview()

    def _step_page(self, delta: int) -> None:
        if self.project is not None:
            self.go_page(self.project.current_page + delta)

    def _jump_page(self) -> None:
        self.go_page(self.page_number.value() - 1)

    def _original_changed(self, checked: bool) -> None:
        if self._loading or self.runner.busy or self.project is None:
            return
        if not self.settings.commit_pending():
            with QtCore.QSignalBlocker(self.original):
                self.original.setChecked(self.project.show_original)
            return
        self.project.show_original = checked
        self._original_warning = False
        self._warning_style()
        self._schedule_preview(0)

    def _auto_fit_changed(self, checked: bool) -> None:
        if self._loading or self.project is None:
            return
        self.project.auto_fit = checked
        self.viewer.auto_fit = checked
        if checked:
            self.viewer.fit_page()
        else:
            self.viewer.mode = ViewMode.FREE
        self._mark_dirty()

    def _show_regions_changed(self, checked: bool) -> None:
        if self._loading or self.project is None:
            return
        self.project.show_regions = checked
        self._mark_dirty()
        self.viewer.set_regions(self._region_boxes if checked else [])
        if checked and not self._regions_available:
            self._schedule_preview(0)

    def _profile_changed_preview(self) -> None:
        if self.project is None:
            return
        if self.project.show_original:
            self._original_warning = True
            self._warning_style()
        self._schedule_preview(0)

    def _warning_style(self) -> None:
        skipped = bool(self.project and self.project.assignments[self.project.current_page] == SKIP_ID)
        warning = self.original.isChecked() and self._original_warning and not skipped
        self.original.setStyleSheet("QCheckBox { color: #b06b00; font-weight: bold; }" if warning else "")
        self.original.setToolTip("This page uses no-processing; its original content is retained." if skipped
                                else "Showing the original page. The processing changes are not displayed." if warning
                                else "Show the unprocessed source page")

    def _schedule_preview(self, delay: int = PREVIEW_DELAY_MS) -> None:
        if self.project is None or not self.settings.valid:
            return
        self._preview_requested = True
        self._preview_revision += 1
        self.preview_timer.stop()
        state = PreviewState.from_project(self.project)
        if not self.runner.busy and (frame := self.preview_cache.get(state)) is not None:
            self._preview_requested = False
            self._display_preview(frame, cached=True)
            return
        self._regions_available = False
        self._region_boxes = []
        self.viewer.set_regions([])
        self.navigation.load_images(())
        if not self.runner.busy:
            self.preview_timer.start(0 if state.original else delay)
        previous = f"; displaying page {self._displayed_page + 1}" if self._displayed_page is not None else ""
        self.status.setText(f"Waiting to preview page {self.project.current_page + 1}{previous}...")

    def _start_preview(self) -> None:
        if self.project is None or self.runner.busy or not self.settings.valid or self.settings.has_active_edit():
            return
        self.preview_timer.stop()
        self._preview_requested = False
        self._inflight_preview = PreviewState.from_project(self.project)
        self._operation = Operation.PREVIEW
        self.status.setText(f"Rendering page {self.project.current_page + 1}...")
        try:
            self.runner.start({"operation": self._operation.value, "project": self.project.to_data(),
                               "password": self.password, "revision": self._preview_revision,
                               "pixel_buffer": self.preview_buffer.name})
        except OSError as exc:
            self._error(f"Cannot allocate the preview buffer: {exc}")

    def _resume_preview(self) -> None:
        if self._preview_requested and not self._loading and not self.runner.busy:
            self._schedule_preview(0)

    def _display_preview(self, frame: PreviewFrame, *, cached: bool = False) -> None:
        if self.project is None:
            return
        state = PreviewState.from_project(self.project)
        self.viewer.set_pixmap(frame.pixmap, (str(self.project.source), state.page))
        self.navigation.load_images(frame.images, page_size=frame.page_size,
                                    preview_pixels=(frame.pixmap.width(), frame.pixmap.height()))
        self._regions_available = frame.matches_regions(state)
        self._region_boxes = list(frame.regions) if self._regions_available else []
        self.viewer.set_regions(self._region_boxes if state.show_regions else [])
        self._displayed_page = state.page
        profile = self.project.profiles[self.project.assignments[state.page]]
        mode = "Original" if state.original else "Processed"
        suffix = " (cached)" if cached else ""
        self.status.setText(f"{mode} page {state.page + 1} / {self.project.page_count} - {profile.name}{suffix}")

    def _save_project(self, save_as: bool = False) -> bool:
        if self.project is None:
            return False
        if not self.runner.busy and not self.settings.commit_pending():
            return False
        # Committing a focused editor may have scheduled a preview again.
        self.preview_timer.stop()
        path = self.project_path
        if save_as or path is None:
            default = path or self.project.source.with_suffix(".binarize.json")
            selected, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save project", str(default), "JSON project (*.json)")
            if not selected:
                return False
            path = Path(selected)
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
        try:
            self.project.save(path)
            self.project_path = path
            self.dirty = False
            self._title()
            self.status.setText(f"Project saved: {path}")
            return True
        except (ValueError, OSError) as exc:
            self._error(str(exc))
            return False

    def _export(self, one_page: bool) -> None:
        if self.project is None or self.runner.busy or not self.settings.valid:
            return
        if not self.settings.commit_pending():
            return
        self.preview_timer.stop()
        suffix = f"_preview_p{self.project.current_page + 1}" if one_page else "_binary"
        default = self.project.source.with_name(f"{self.project.source.stem}{suffix}.pdf")
        try:
            choice = choose_pdf_output(self, self.project.source, default)
        except OSError as exc:
            self._error(str(exc))
            return
        if choice is None:
            return
        output, overwrite = choice
        self._cancel_marker = output.parent / f".pdf-tools-cancel-{uuid4().hex}"
        self._cancel_created = False
        self._preview_requested = False
        self._operation = Operation.EXPORT_PAGE if one_page else Operation.EXPORT
        self.progress_bar.setRange(0, self.project.page_count)
        self.progress_bar.setValue(0)
        self.status.setText("Starting PDF export...")
        self.runner.start({"operation": self._operation.value, "project": self.project.to_data(),
                           "password": self.password, "output": str(output), "cancel": str(self._cancel_marker),
                           "overwrite": overwrite})

    def _cancel_export(self) -> None:
        if self._cancel_marker is not None and self.runner.busy and not self._cancel_created:
            try:
                self._cancel_marker.touch(exist_ok=False)
                self._cancel_created = True
                self.status.setText("Cancelling after the current processing step...")
                self._refresh_enabled()
            except OSError as exc:
                self._error(str(exc))

    def _progress(self, message: dict[str, Json]) -> None:
        self.progress_bar.setRange(0, int(cast(int, message.get("total", 1))))
        self.progress_bar.setValue(int(cast(int, message.get("done", 0))))
        if not self._cancel_created:
            self.status.setText(str(message.get("stage", "Processing...")))

    def _completed(self, message: dict[str, Json]) -> None:
        operation = self._operation
        self._operation = Operation.NONE
        if self._cancel_created and self._cancel_marker is not None:
            self._cancel_marker.unlink(missing_ok=True)
        self._cancel_created = False
        self._cancel_marker = None
        kind = message.get("kind")
        if self._close_after_job:
            self._closing = True
            self.close()
            return
        if kind == "opened":
            self._adopt(message)
        elif kind == "preview" and self.project is not None:
            try:
                if message.get("revision") != self._preview_revision:
                    self._resume_preview()
                    return
                state = self._inflight_preview
                if state is None or int(cast(int, message["page"])) != state.page:
                    raise ValueError("The preview worker returned an unexpected page.")
                if message.get("pixel_buffer"):
                    pixmap = self.preview_buffer.read(int(cast(int, message["width"])), int(cast(int, message["height"])))
                else:
                    pixmap = QtGui.QPixmap()
                    if not pixmap.loadFromData(base64.b64decode(str(message["png"])), "PNG"):
                        raise ValueError("The preview worker returned an invalid image.")
                boxes = tuple(cast(Rectangle, tuple(float(value) for value in row))
                              for row in cast(list[list[float]], message.get("regions", [])))
                images = tuple(ImageElement.from_data(row) for row in
                               cast(list[dict[str, object]], message.get("images", [])))
                page_size = tuple(float(value) for value in cast(list[float], message["page_size"]))
                if len(page_size) != 2 or any(value <= 0 for value in page_size):
                    raise ValueError("The preview worker returned an invalid page size.")
                frame = PreviewFrame(state, pixmap, boxes, bool(message.get("regions_available", False)),
                                     images, cast(tuple[float, float], page_size))
                self.preview_cache.put(frame)
                self._inflight_preview = None
                self._display_preview(frame)
            except (ValueError, KeyError) as exc:
                self._error(str(exc))
        elif kind == "exported":
            path = str(message["path"])
            self.status.setText(f"PDF saved: {path}")
            self.progress_bar.setValue(self.progress_bar.maximum())
            before, after = int(cast(int, message.get("before_bytes", 0))), int(cast(int, message.get("after_bytes", 0)))
            sizes = f"Before: {before:,} bytes ({before / 1048576:.2f} MiB)\nAfter: {after:,} bytes ({after / 1048576:.2f} MiB)"
            if before:
                sizes += f"\nSize change: {(after / before - 1) * 100:+.1f}%"
            if message.get("one_page"):
                sizes += "\nBefore size refers to the complete source PDF; after size is this page only."
            QtWidgets.QMessageBox.information(self, "PDF processing complete", f"Saved:\n{path}\n\n{sizes}")
            if message.get("one_page") and self.open_saved_preview.isChecked():
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
        elif kind == "cancelled":
            self.status.setText("Conversion cancelled.")
        elif kind == "error":
            if operation == Operation.INSPECT and message.get("code") == "password":
                password, accepted = QtWidgets.QInputDialog.getText(self, "PDF password", "Password:",
                                                                   QtWidgets.QLineEdit.EchoMode.Password)
                if accepted:
                    self._pending_password = password
                    self._inspect_pending()
                else:
                    self.status.setText("Opening cancelled.")
            else:
                self._error(str(message.get("message", "PDF operation failed.")))
        self._refresh_enabled()
        if self._preview_requested and not self.runner.busy:
            self._resume_preview()

    def _error(self, message: str) -> None:
        remaining = max(0, self.preview_timer.remainingTime())
        self.preview_timer.stop()
        self.status.setText(message)
        QtWidgets.QMessageBox.critical(self, "PDF Binarize", message)
        if self._preview_requested and not self.runner.busy:
            self._schedule_preview(remaining)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Save/discard edits and wait for cooperative cancellation before closing."""
        if self._closing:
            self.runner.shutdown()
            self.preview_buffer.close()
            self.preview_cache.clear()
            event.accept()
            return
        self.preview_timer.stop()
        if not self._confirm_discard():
            self._resume_preview()
            event.ignore()
            return
        if self.runner.busy:
            choice = QtWidgets.QMessageBox.question(self, "Task running", "Close after the current task stops?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if choice == QtWidgets.QMessageBox.StandardButton.Yes:
                self._close_after_job = True
                self._cancel_export()
            event.ignore()
            return
        self.runner.shutdown()
        self.preview_buffer.close()
        self.preview_cache.clear()
        event.accept()


def main(entry: Path) -> int:
    """Create the Fusion-themed application and run its event loop.

    Args:
        entry: GUI launcher used by the private worker subprocess.

    Returns:
        Qt event-loop exit status. Opens a desktop window; does not prompt in a terminal.
    """
    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A GUI QApplication is required.")
    application.setStyle("Fusion")
    window = BinarizeWindow(entry)
    window.show()
    if owns_application:
        return application.exec()
    # Keep the window alive when a host already owns the Qt event loop.
    application.setProperty("pdfBinarizeWindow", window)
    return 0
