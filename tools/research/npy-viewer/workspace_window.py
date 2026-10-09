"""Channel-checkbox workspace with independent controls and automatic overlays.

Requirements: the existing viewer dependencies; no additional packages.
Usage: constructed by app.run. Open replaces the session; Add file appends one
file and selects NPZ/MAT/Excel members before loading. Excel/CSV/TXT offer per-table
row/column ranges and headers. Dropping a file into a populated session appends.
Numeric 2-by-N/N-by-2 sources (N > 2) prompt for XY or matrix interpretation;
3-by-N/N-by-3 sources (N > 3) prompt for XYZ point cloud or matrix interpretation
before insertion, unless --mode was supplied. Cancel preserves the workspace.
Single-matrix mode is the default: clicking a channel clears other selections.
Multiple-matrix mode permits compatible checkbox selections to overlay.
Hide controls are exposed only in multiple mode. Auto Y on slice change is
enabled by default; disabling it fixes both signal and derivative Y ranges.
Multichannel matrices are noncheckable expandable groups; single-channel matrices
are checkable leaves without a child row. In multiple mode, row clicks only edit.
Removal only releases session entries.
Raw data has an independent matrix-name dropdown; unchecked channels stay hidden.
After Fourier calculation, Yes displays only the new result; No adds it unchecked
and retains the current selection, visibility and views.
The Transform menu also offers finite-record 1D Laplace planes and contour-based
inversion; both use the same background jobs and result-selection question.
Data conversion adds dB, angle, magnitude, logarithm and affine operations with
full/crop/slice scopes; results retain sample coordinates and are separate entries.
Export figure opens a modal preview for current 2D/3D/signal/derivative views,
including overlays, titles and legends, with pixel width and print DPI settings.
File commands and Fit views share the matrix panel; the old top bar is hidden.
Rename is available through the tree context menu/F2; Remove all is in Remove's
arrow menu. Numeric export settings live in a separate modal window. Multichannel
and complex sources offer Export channel, retaining just the selected component.
Whole image/numeric-channel exports preserve source channels; PNG/BMP normalize
one real 2D matrix to 8-bit grayscale, independently of plot image exports.
Native context menus reuse processing/export controls. Tree right-click chooses
an editing target without altering visibility; canvas clicks open menus while
right drags retain the existing 3D camera gesture.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import cast

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .app import DEFAULT_MAX_EDGE, FILE_FILTER, JobKind, ViewerWindow
from .coordinates import AxisMap
from .channel_tree import ChannelTree
from .context_menus import WorkspaceMenus
from .data_model import (DEFAULT_MAX_POINTS, Component, Document, FilterMode, Frame, ImageMember, Limits,
                         Selection, ViewMode, default_selection, prepare_frame, select_image_member)
from .overlay_profile import OverlayProfile
from .fourier import TransformDirection, TransformOptions, TransformResult, run_transform
from .fourier_dialog import FourierDialog
from .laplace import LaplaceDirection, LaplaceOptions, run_laplace
from .laplace_dialog import LaplaceDialog
from .complex_merge import MergeInput, MergeMatrix, MergeMode, PhaseUnit, run_merge
from .complex_merge_dialog import ComplexMergeDialog
from .data_conversion import ConversionOptions, run_conversion
from .data_conversion_dialog import DataConversionDialog
from .import_catalog import INSPECT_EXTENSIONS, ImportCatalog, ImportChoice, inspect_source
from .import_dialog import ImportDialog
from .exporting import ExportFormat, ExportLayout, ExportSnapshot, ExportTarget
from .excel_io import serialize_excel
from .figure_dialog import FigureExportDialog
from .figure_export import FigureSource, FigureView, figure_stem, plot_source, surface_source
from .plot_support import pyside_graphics_view
from .qt_widgets import NoWheelComboBox
from .profile_view import CHANNEL_COLORS, JumpMode
from .surface_view import ProfileStyle
from .workspace import (COLORS, Alignment, ChannelChoice, LoadedFile, MatrixEntry, RenderLayer, Setting,
                        active_channel, align_axis, channel_choices, coordinate_bounds, family, height_bounds, load_file,
                        overlay_auto_height, profile_series)
from .workspace_export import (ExportScope, default_stem, mat_variable_names,
                               prepare_displayed_export, serialize_displayed_mat)

SETTINGS: tuple[str, ...] = (
    "filter_low", "filter_high", "filter_mode", "color_low", "color_high", "colormap",
    "max_edge", "max_points", "point_size", "auto_height", "height_scale", "db_floor",
    "crop_x_start", "crop_x_end", "crop_y_start", "crop_y_end",
)
PROFILE_SETTINGS: tuple[str, ...] = ("jump_mode", "jump_threshold", "curve_style", "curve_color")


@dataclass(frozen=True)
class PreparedEntry:
    """One worker result, guarded by a per-entry revision token."""

    uid: int
    revision: int
    frame: Frame | None
    error: str = ""
    document: Document | None = None
    selection: Selection | None = None


class WorkspaceWindow(ViewerWindow):
    """Extend the single-matrix workbench with independently configured entries.

    Args:
        max_edge: Initial maximum 3D sampling edge for each matrix.
        initial_mode: Optional interpretation override for the first source.
        initial_channel_axis: Optional channel axis for the first source.
    """

    def __init__(self, max_edge: int = DEFAULT_MAX_EDGE, initial_mode: str | None = None,
                 initial_channel_axis: int | None = None) -> None:
        self.entries: list[MatrixEntry] = []
        self.active_uid: int | None = None
        self._view_override: MatrixEntry | None = None
        self._raw_matrix_uid: int | None = None
        self.reference_uid: int | None = None
        self._uid = 0
        self._restoring = False
        self._painting_active = False
        self._rendering = False
        self._append_pending = False
        self._workspace_ready = False
        self._profile_uses_overlay = False
        self._render_layers: tuple[RenderLayer, ...] = ()
        self._default_edge = max_edge
        self._preparing: dict[int, int] = {}
        self._preparation_jobs: dict[int, tuple[tuple[int, int], ...]] = {}
        self._fourier_dialog: FourierDialog | None = None
        self._laplace_dialog: LaplaceDialog | None = None
        self._merge_dialog: ComplexMergeDialog | None = None
        self._conversion_dialog: DataConversionDialog | None = None
        self._import_dialog: ImportDialog | None = None
        self._single_render_key: tuple[int, int] | None = None
        self._loading_channel_uid: int | None = None
        super().__init__(max_edge, initial_mode, initial_channel_axis)
        self.overlay_profile = OverlayProfile()
        self.profile_layout.addWidget(self.overlay_profile)
        self.overlay_profile.hide()
        self.overlay_profile.settings_changed.connect(self._profile_settings_changed)
        self._defaults = self._read_settings()
        for name in tuple(self._defaults):
            if name.startswith("crop_"):
                self._defaults.pop(name)
        self._build_workspace()
        self.raw_view.matrix_combo.currentIndexChanged.connect(self._raw_matrix_changed)
        self.export_scope = NoWheelComboBox()
        for scope in ExportScope:
            self.export_scope.addItem(scope.value, scope.value)
        self.export_form.insertRow(0, "Scope", self.export_scope)
        self.export_scope.currentIndexChanged.connect(self._export_scope_changed)
        self.figure_export_button = QtWidgets.QPushButton("Export figure…")
        self.figure_export_button.setToolTip("Save the current plot/camera, including visible overlays, as an image.")
        self.figure_export_button.clicked.connect(self._export_figure)
        self.export_form.addRow(self.figure_export_button)
        self._workspace_ready = True
        self.context_menus = WorkspaceMenus(self)
        self._theme_changed()

    def _build_workspace(self) -> None:
        self.matrix_box = QtWidgets.QGroupBox("Matrices / channels")
        layout = QtWidgets.QVBoxLayout(self.matrix_box)
        self.single_matrix_mode = QtWidgets.QRadioButton("Single matrix")
        self.multiple_matrix_mode = QtWidgets.QRadioButton("Multiple matrices")
        self.selection_modes = QtWidgets.QButtonGroup(self)
        self.selection_modes.addButton(self.single_matrix_mode)
        self.selection_modes.addButton(self.multiple_matrix_mode)
        self.single_matrix_mode.setChecked(True)
        self.single_matrix_mode.setToolTip("Click a channel or single-channel matrix to show it exclusively. Click a multichannel matrix to expand its channels.")
        self.multiple_matrix_mode.setToolTip("Use channel checkboxes to overlay compatible matrices/channels. Row clicks only choose the editing target.")
        self.multiple_matrix_mode.toggled.connect(self._display_mode_changed)
        self.open_file_action = QtGui.QAction("Open file…", self)
        self.open_file_action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        self.open_file_action.setToolTip("Open a file and replace the current session.")
        self.open_file_action.triggered.connect(self._choose_file)
        self.addAction(self.open_file_action)
        self.open_file_button.setShortcut(QtGui.QKeySequence())
        self.add_file_action = QtGui.QAction("Add file…", self)
        self.add_file_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+O"))
        self.add_file_action.triggered.connect(self._choose_overlay)
        self.addAction(self.add_file_action)
        bar = QtWidgets.QHBoxLayout()
        self.add_overlay = QtWidgets.QToolButton()
        self.add_overlay.setDefaultAction(self.add_file_action)
        self.add_overlay.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        file_menu = QtWidgets.QMenu(self.add_overlay)
        file_menu.addActions([self.open_file_action, self.add_file_action])
        self.add_overlay.setMenu(file_menu)
        self.add_overlay.setToolTip("Add a file, or use the arrow menu to Open and replace the session. Files can also be dropped anywhere in the window.")
        bar.addWidget(self.add_overlay)
        self.fourier_button = QtWidgets.QPushButton("Transform…")
        self.fourier_button.setEnabled(False)
        transform_menu = QtWidgets.QMenu(self.fourier_button)
        self.conversion_action = transform_menu.addAction("Data conversion…")
        self.conversion_action.triggered.connect(self._choose_data_conversion)
        transform_menu.addSeparator()
        self.fourier_action = transform_menu.addAction("Fourier…")
        self.fourier_action.triggered.connect(self._choose_fourier)
        self.laplace_action = transform_menu.addAction("Laplace…")
        self.laplace_action.triggered.connect(self._choose_laplace)
        transform_menu.addSeparator()
        self.merge_action = transform_menu.addAction("Complex matrix merge…")
        self.merge_action.setEnabled(False)
        self.merge_action.triggered.connect(self._choose_complex_merge)
        self.fourier_button.setMenu(transform_menu)
        bar.addWidget(self.fourier_button)
        bar.addWidget(self.single_matrix_mode)
        bar.addWidget(self.multiple_matrix_mode)
        bar.addStretch()
        layout.addLayout(bar)
        actions = QtWidgets.QHBoxLayout()
        self.none_visible = QtWidgets.QPushButton("Hide all")
        self.none_visible.setVisible(self.multiple_matrix_mode.isChecked())
        self.none_visible.clicked.connect(self._hide_all)
        actions.addWidget(self.none_visible)
        self.remove_action = QtGui.QAction("Remove", self)
        self.remove_action.triggered.connect(self._remove_selected)
        self.remove_matrix = QtWidgets.QToolButton()
        self.remove_matrix.setDefaultAction(self.remove_action)
        self.remove_matrix.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.remove_matrix.setToolTip("Remove from this session; the source file is unchanged.")
        actions.addWidget(self.remove_matrix)
        self.remove_all = QtGui.QAction("Remove all", self)
        self.remove_all.triggered.connect(self._remove_all)
        self.remove_all.setToolTip("Remove all matrices from this session; source files are unchanged.")
        remove_menu = QtWidgets.QMenu(self.remove_matrix)
        remove_menu.addActions([self.remove_action, self.remove_all])
        self.remove_matrix.setMenu(remove_menu)
        old_bar = self.file_bar.layout()
        assert old_bar is not None
        old_bar.removeWidget(self.fit_views_button)
        actions.addWidget(self.fit_views_button)
        self.file_bar.hide()
        layout.addLayout(actions)
        self.matrix_list = ChannelTree()
        self.matrix_list.setColumnCount(3)
        self.matrix_list.setHeaderLabels(["Matrix / channel", "Shape · type", "Color"])
        self.matrix_list.setRootIsDecorated(True)
        self.matrix_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.matrix_list.setMinimumHeight(90)
        self.matrix_list.setIndentation(14)
        self.matrix_list.setToolTip("Single matrix: click a channel or single-channel matrix to show it. Multichannel matrices expand without changing visibility. Multiple matrices: click rows to edit and use checkboxes to combine channels. F2 renames the matrix.")
        self.matrix_list.header().setStretchLastSection(False)
        self.matrix_list.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.matrix_list.setColumnWidth(1, 100)
        self.matrix_list.setColumnWidth(2, 45)
        self.matrix_list.itemClicked.connect(self._list_clicked)
        self.matrix_list.itemActivated.connect(self._list_activated)
        self.matrix_list.itemChanged.connect(self._list_checked)
        self.matrix_list.itemDoubleClicked.connect(self._list_color)
        layout.addWidget(self.matrix_list)
        self.rename_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F2"), self.matrix_list)
        self.rename_shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.rename_shortcut.activated.connect(self._rename_selected)
        left = self.controls.layout()
        assert isinstance(left, QtWidgets.QVBoxLayout)
        left.removeWidget(self.info)
        self.info.setParent(self.matrix_box)
        layout.addWidget(self.info)
        self.workspace_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.main_split.replaceWidget(0, self.workspace_split)
        self.workspace_split.addWidget(self.matrix_box)
        self.workspace_split.addWidget(self.control_scroll)
        self.workspace_split.setChildrenCollapsible(False)
        self.workspace_split.setSizes([270, 570])
        self.workspace_split.setStretchFactor(1, 1)
        self.archive_label.hide()
        self.archive_key.hide()
        self.display_label.hide()
        self.display_channel.hide()

        self.alignment_box = QtWidgets.QGroupBox("Selected channel — overlay appearance")
        form = QtWidgets.QFormLayout(self.alignment_box)
        self.reference = NoWheelComboBox()
        self.reference.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.reference.setMinimumContentsLength(16)
        self.reference.currentIndexChanged.connect(self._reference_changed)
        self.reference.setToolTip("Shared reference for checked channels. Clicking matrix/channel rows does not change the reference.")
        form.addRow("Align relative to", self.reference)
        self.alignment_x = NoWheelComboBox()
        self.alignment_y = NoWheelComboBox()
        self.alignment_z = NoWheelComboBox()
        self.alignment_z.setToolTip("Align visible Z ranges to the reference after height scaling. Affects 3D geometry only; images, profiles and numeric exports keep source values.")
        for combo, start, end in ((self.alignment_x, "Left", "Right"),
                                  (self.alignment_y, "Top / minimum Y", "Bottom / maximum Y"),
                                  (self.alignment_z, "Minimum Z", "Maximum Z")):
            for mode in Alignment:
                label = start if mode == Alignment.START else end if mode == Alignment.END else mode.value
                combo.addItem(label, mode.value)
            combo.currentIndexChanged.connect(self._alignment_changed)
        form.addRow("X alignment", self.alignment_x)
        form.addRow("Y alignment", self.alignment_y)
        form.addRow("Z alignment (3D)", self.alignment_z)
        self.layer_color = QtWidgets.QPushButton("Solid color…")
        self.layer_color.clicked.connect(self._choose_layer_color)
        form.addRow(self.layer_color)
        self.layer_opacity = QtWidgets.QDoubleSpinBox()
        self.layer_opacity.setRange(0.05, 1)
        self.layer_opacity.setSingleStep(0.05)
        self.layer_opacity.setDecimals(2)
        self.layer_opacity.setValue(0.65)
        self.layer_opacity.valueChanged.connect(self._alignment_changed)
        form.addRow("2D / 3D opacity", self.layer_opacity)
        note = QtWidgets.QLabel("X/Y alignment is included in visible-matrix exports. Z alignment and height scaling affect only 3D geometry. Data and derivatives retain source values. 2D values control opacity.")
        note.setWordWrap(True)
        form.addRow(note)
        left.insertWidget(0, self.alignment_box)
        self.alignment_box.hide()

    def _entry(self, uid: int | None = None) -> MatrixEntry | None:
        if uid is None and self._view_override is not None:
            return self._view_override
        wanted = self.active_uid if uid is None else uid
        return next((entry for entry in self.entries if entry.uid == wanted), None)

    @contextmanager
    def _single_view_context(self) -> Iterator[None]:
        """Render the checked source while retaining an unchecked editing target.

        Temporarily supplies the existing single-view renderer with its source
        and settings. Signals are blocked by _restore_settings; editing controls
        are restored before Qt paints, while curve controls belong to the view.
        """
        shown = next((entry for entry in self.entries if entry.visible), None)
        edited = self._entry()
        if (not self._workspace_ready or self._view_override is not None or self._overlay()
                or shown is None or shown is edited or shown.frame is None or edited is None):
            yield
            return
        saved = self.document, self.frame, self.frame_selection, self._restoring
        editing_settings = self._read_settings()
        self._store_visible_profile_settings()
        self._view_override = shown
        self._restoring = True
        try:
            self.document, self.frame, self.frame_selection = shown.document, shown.frame, shown.selection
            self._restore_settings(shown)
            yield
        finally:
            self.document, self.frame, self.frame_selection, restoring = saved
            self._restore_settings(replace(edited, settings=editing_settings), restore_views=False)
            self._view_override = None
            self._restoring = restoring

    def _overlay(self) -> bool:
        checked = [entry for entry in self.entries if entry.visible]
        return (self._workspace_ready and self.multiple_matrix_mode.isChecked()
                and (len(checked) > 1 or bool(checked and checked[0].uid != self.active_uid)))

    def _display_mode_changed(self, multiple: bool) -> None:
        """Switch selection policy, retaining at most one checked channel in single mode."""
        if not self._workspace_ready:
            return
        self._store_entry()
        self.add_overlay.setText("Add overlay…" if multiple else "Add file…")
        if not multiple:
            selected = self._entry()
            retained = selected if selected is not None and selected.visible else next(
                (entry for entry in self.entries if entry.visible), None)
            if retained is not None:
                for entry in self.entries:
                    entry.visible = entry.uid == retained.uid
                self.reference_uid = retained.uid
                self._activate(retained)
                return
        self._refresh_list()
        self._sync_alignment()
        self._prepare_missing()
        self._render_workspace(reset=True)

    def _groups(self) -> dict[int, list[MatrixEntry]]:
        groups: dict[int, list[MatrixEntry]] = {}
        for entry in self.entries:
            groups.setdefault(entry.matrix_uid or entry.uid, []).append(entry)
        return groups

    def _expand_channels(self, entry: MatrixEntry) -> None:
        """Create lightweight channel states; hidden images are decoded only on use."""
        group = entry.matrix_uid or entry.uid
        entry.matrix_uid = group
        existing = {active_channel(item) for item in self.entries if (item.matrix_uid or item.uid) == group}
        for choice in channel_choices(entry):
            if choice in existing:
                continue
            self._uid += 1
            color = self._default_color(self._uid, choice.image_key)
            clone = replace(entry, uid=self._uid, matrix_uid=group, visible=False, frame=None,
                            selection=replace(entry.selection, component=choice.component, channel=choice.channel),
                            color=color, settings=entry.settings.copy(), image_key=choice.image_key)
            self.entries.append(clone)

    @staticmethod
    def _default_color(uid: int, image_key: str | None = None) -> str:
        fallback = COLORS[(uid - 1) % len(COLORS)]
        return CHANNEL_COLORS.get(ImageMember(image_key), fallback) if image_key is not None else fallback

    @staticmethod
    def _channel_selection(document: Document, selection: Selection) -> Selection:
        if document.image_source is None:
            return selection
        color = document.array.ndim == 3
        if color and selection.mode != ViewMode.MATRIX:
            return default_selection(document, ViewMode.MATRIX)
        return replace(selection, channel_axis=2 if color else None, channel=-1 if color else 0,
                       slices=(0,) * document.array.ndim)

    @staticmethod
    def _channel_label(entry: MatrixEntry) -> str:
        return f"{entry.label} / {active_channel(entry).label}"

    @staticmethod
    def _channel_loaded(entry: MatrixEntry) -> bool:
        return entry.image_key is None or entry.image_key == entry.document.key

    def _read_profile_settings(self) -> dict[str, Setting]:
        """Read curve controls from the visible single/overlay profile widget."""
        profile = self.overlay_profile if self._profile_uses_overlay else self.profile_view
        return {"jump_mode": profile.jump_mode.currentIndex(),
                "jump_threshold": profile.jump_threshold.value(),
                "curve_style": profile.style_selector.currentIndex(),
                "curve_color": self.profile_view.color.name()}

    def _store_visible_profile_settings(self) -> None:
        """Keep curve settings with the checked source while editing a hidden one."""
        entry = self._entry()
        if entry is not None and not entry.visible and not self._overlay():
            shown = next((member for member in self.entries if member.visible), None)
            if shown is not None:
                shown.settings.update(self._read_profile_settings())

    def _read_settings(self) -> dict[str, Setting]:
        settings: dict[str, Setting] = {}
        for name in SETTINGS:
            widget = getattr(self, name)
            if isinstance(widget, QtWidgets.QLineEdit):
                settings[name] = widget.text()
            elif isinstance(widget, QtWidgets.QComboBox):
                settings[name] = widget.currentText()
            elif isinstance(widget, QtWidgets.QCheckBox):
                settings[name] = widget.isChecked()
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                settings[name] = widget.value()
        settings.update(self._read_profile_settings())
        settings["clip_color"] = self._clip_color.name()
        entry = self._entry()
        if self._workspace_ready and not self._overlay() and entry is not None and not entry.visible:
            for name in PROFILE_SETTINGS:
                settings[name] = entry.settings.get(name, settings[name])
        return settings

    def _store_entry(self) -> None:
        entry = self._entry()
        if entry is None or self._restoring or entry.uid == self._loading_channel_uid or not self._channel_loaded(entry):
            return
        self._store_visible_profile_settings()
        entry.settings = self._read_settings()
        entry.crop = self._crop
        try:
            selection = self._selection()
            limits = Limits(self._bound(self.filter_low), self._bound(self.filter_high), FilterMode(self.filter_mode.currentText()))
        except ValueError:
            return
        previous = entry.selection
        entry.selection = selection
        entry.limits = limits
        # Axis interpretation belongs to the source, while each channel keeps
        # its own component, crop, value bounds and rendering settings.
        if (entry.document.image_source is None and
                replace(previous, component=selection.component, channel=selection.channel,
                        db_floor=selection.db_floor) != selection):
            self._reconcile_channels(entry)

    def _reconcile_channels(self, entry: MatrixEntry) -> None:
        """Rebuild a numeric source's channel choices after axis/mode changes."""
        group = entry.matrix_uid or entry.uid
        members = self._groups()[group]
        selection = entry.selection
        count = entry.document.array.shape[selection.channel_axis] if selection.channel_axis is not None else 1
        kept: dict[ChannelChoice, MatrixEntry] = {active_channel(entry): entry}
        removed: set[int] = set()
        for member in members:
            if member is entry:
                continue
            member.selection = replace(selection, component=member.selection.component,
                                       channel=min(max(member.selection.channel, 0), count - 1),
                                       db_floor=member.selection.db_floor)
            choice = active_channel(member)
            if choice in kept:
                kept[choice].visible |= member.visible
                removed.add(member.uid)
                continue
            kept[choice] = member
            member.frame = None
            member.revision += 1
            member.crop = entry.crop
            for name in SETTINGS:
                if name.startswith("crop_") and name in entry.settings:
                    member.settings[name] = entry.settings[name]
        self.entries[:] = [member for member in self.entries if member.uid not in removed]
        if self.reference_uid in removed:
            self.reference_uid = entry.uid
        self._expand_channels(entry)

    def _restore_settings(self, entry: MatrixEntry, *, restore_views: bool = True) -> None:
        for name in SETTINGS:
            if name not in entry.settings:
                continue
            value = entry.settings[name]
            widget = getattr(self, name)
            with QtCore.QSignalBlocker(widget):
                if isinstance(widget, QtWidgets.QLineEdit):
                    widget.setText(str(value))
                elif isinstance(widget, QtWidgets.QComboBox):
                    widget.setCurrentText(str(value))
                elif isinstance(widget, QtWidgets.QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QtWidgets.QSpinBox):
                    widget.setValue(int(value))
                elif isinstance(widget, QtWidgets.QDoubleSpinBox):
                    widget.setValue(float(value))
        for profile in (self.profile_view, self.overlay_profile) if restore_views else ():
            previous_jump = (profile.jump_mode.currentIndex(), profile.jump_threshold.value())
            with QtCore.QSignalBlocker(profile.jump_mode), QtCore.QSignalBlocker(profile.jump_threshold), QtCore.QSignalBlocker(profile.style_selector):
                profile.jump_mode.setCurrentIndex(int(entry.settings.get("jump_mode", JumpMode.GAPS_ONLY)))
                profile.jump_threshold.setValue(float(entry.settings.get("jump_threshold", 1.0)))
                profile.style_selector.setCurrentIndex(int(entry.settings.get("curve_style", 0)))
                profile.jump_threshold.setEnabled(profile.jump_mode.currentIndex() == JumpMode.CUSTOM)
            if profile is self.profile_view and previous_jump != (profile.jump_mode.currentIndex(), profile.jump_threshold.value()):
                profile._invalidate_derivative()
        self._clip_color = QtGui.QColor(str(entry.settings.get("clip_color", "#ff0000")))
        self._set_color_icon(self.clip_color_button, self._clip_color)
        if restore_views:
            self.profile_view.color = QtGui.QColor(str(entry.settings.get("curve_color", "#48b9ff")))
            self.image_view.set_clip_color(self._clip_color)
            self.profile_view.set_clip_color(self._clip_color)
            self.surface_view.set_clip_color(self._clip_color.name())
        self._sync_height_slider()
        self.height_scale.setEnabled(not self.auto_height.isChecked())
        self.height_slider.setEnabled(not self.auto_height.isChecked())

    def _activate(self, entry: MatrixEntry, *, reset_selection: bool = False) -> None:
        self._store_entry()
        selected_profile = self._profile_selected
        previous = self._entry()
        if previous is not None and (self._rebuild.isActive() or not self._export_ready):
            previous.frame = None
            previous.revision += 1
        self._rebuild.stop()
        self._latest[JobKind.FRAME] = -1
        self._latest[JobKind.LOAD] = -1
        self.active_uid = entry.uid
        self._raw_matrix_uid = entry.matrix_uid or entry.uid
        self._loading_channel_uid = None
        if entry.document.image_source is not None and entry.image_key is not None and entry.document.key != entry.image_key:
            self._loading_channel_uid = entry.uid
            self.document, self.frame, self.frame_selection = entry.document, None, None
            self.controls.setEnabled(False)
            self.raw_view.clear(f"Loading {self._channel_label(entry)}…")
            self._refresh_list()
            self._render_workspace(reset=entry.visible)
            self._submit(JobKind.LOAD, partial(select_image_member, entry.document, entry.image_key))
            self._prepare_missing()
            return
        self._restoring = True
        try:
            super()._document_loaded(entry.document)
            if not entry.visible:
                self._reset_pending = False
            self._configure_selection(entry.selection)
            self._profile_selected = True if reset_selection else selected_profile
            self._restore_settings(entry, restore_views=entry.visible or self._overlay())
            self._crop = entry.crop
            self.frame, self.frame_selection = entry.frame, entry.selection
            self._sync_source_selectors(entry.selection.component)
            self._update_matrix_info()
            self._sync_alignment()
        finally:
            self._restoring = False
        self._refresh_list()
        if entry.frame is not None:
            self._show_frame(False)
        else:
            self._request_frame()
            self._render_workspace(reset=entry.visible)
        self._prepare_missing()

    def _refresh_list(self) -> None:
        for members in tuple(self._groups().values()):
            self._expand_channels(next((item for item in members if item.uid == self.active_uid), members[0]))
        groups = self._groups()
        with QtCore.QSignalBlocker(self.matrix_list), QtCore.QSignalBlocker(self.reference):
            existing: list[int] = []
            for row in range(self.matrix_list.topLevelItemCount()):
                item = self.matrix_list.topLevelItem(row)
                if item is not None:
                    existing.append(int(item.data(0, QtCore.Qt.ItemDataRole.UserRole)))
            rebuild = existing != list(groups)
            if rebuild:
                self.matrix_list.clear()
            self.reference.clear()
            for row, (group, members) in enumerate(groups.items()):
                entry = next((member for member in members if member.uid == self.active_uid), members[0])
                if rebuild:
                    item = QtWidgets.QTreeWidgetItem()
                    self.matrix_list.addTopLevelItem(item)
                else:
                    item = self.matrix_list.topLevelItem(row)
                    assert item is not None
                for column, text in enumerate((entry.label, f"{entry.document.array.shape} · {entry.document.array.dtype}", "")):
                    item.setText(column, text)
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, group)
                multiple_channels = len(members) > 1
                if multiple_channels:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(0, QtCore.Qt.ItemDataRole.CheckStateRole, None)
                    item.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, None)
                    font = item.font(0)
                    font.setBold(False)
                    item.setFont(0, font)
                    if self.matrix_list.itemWidget(item, 2) is not None:
                        self.matrix_list.removeItemWidget(item, 2)
                detail = (f"{entry.source_label}\n{entry.document.path}\n"
                          f"Shape: {entry.document.array.shape}\nDtype: {entry.document.array.dtype}\n"
                          f"Size: {entry.document.array.nbytes / 1024**2:,.3f} MiB\n"
                          f"Interpretation: {entry.selection.mode.value}\nIndices start at 0.")
                if entry.document.transform is not None:
                    detail = f"{detail}\n\n{entry.document.transform.description}"
                if entry.document.laplace is not None:
                    detail = f"{detail}\n\n{entry.document.laplace.description}"
                if entry.document.complex_provenance:
                    detail = f"{detail}\n\n{entry.document.complex_provenance}"
                if entry.document.conversion_provenance:
                    detail = f"{detail}\n\n{entry.document.conversion_provenance}"
                if entry.document.import_provenance:
                    detail = f"{detail}\n\n{entry.document.import_provenance}"
                item.setToolTip(0, detail)
                item.setToolTip(1, detail)
                children = {int(child.data(0, QtCore.Qt.ItemDataRole.UserRole)): child
                            for index in range(item.childCount()) if (child := item.child(index)) is not None}
                valid_uids = {member.uid for member in members} if multiple_channels else set()
                for uid, child in children.items():
                    if uid not in valid_uids:
                        item.takeChild(item.indexOfChild(child))
                for member in members:
                    choice = active_channel(member)
                    child = children.get(member.uid) if multiple_channels else item
                    if child is None:
                        child = QtWidgets.QTreeWidgetItem(item)
                        child.setData(0, QtCore.Qt.ItemDataRole.UserRole, member.uid)
                    child.setFlags(child.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    if multiple_channels:
                        child.setText(0, choice.label)
                    child.setData(0, QtCore.Qt.ItemDataRole.UserRole + 1, choice)
                    hint = (f"{entry.label} / {choice.label}\nSingle matrix: click to show only this channel. "
                            "Multiple matrices: click to edit; checkbox to add/remove from the overlay.")
                    child.setToolTip(0, hint if multiple_channels else f"{detail}\n\n{hint}")
                    child.setCheckState(0, QtCore.Qt.CheckState.Checked if member.visible else QtCore.Qt.CheckState.Unchecked)
                    chosen = member.uid == self.active_uid
                    font = child.font(0)
                    font.setBold(chosen)
                    child.setFont(0, font)
                    if multiple_channels:
                        child.setText(1, "Editing" if chosen else "")
                    swatch = self.matrix_list.itemWidget(child, 2)
                    if not isinstance(swatch, QtWidgets.QPushButton) or swatch.property("entry_uid") != member.uid:
                        swatch = QtWidgets.QPushButton()
                        swatch.setProperty("entry_uid", member.uid)
                        swatch.clicked.connect(partial(self._choose_entry_color, member.uid))
                        self.matrix_list.setItemWidget(child, 2, swatch)
                    self._set_color_icon(swatch, QtGui.QColor(member.color))
                    swatch.setToolTip(f"Change color — {self._channel_label(member)}")
                    self.reference.addItem(self._channel_label(member), member.uid)
                    if chosen:
                        self.matrix_list.setCurrentItem(child)
                if rebuild:
                    item.setExpanded(any(member.uid == self.active_uid for member in members))
            self.reference.setCurrentIndex(self.reference.findData(self.reference_uid))
        self.alignment_box.setVisible(self._overlay())
        self.none_visible.setVisible(self.multiple_matrix_mode.isChecked())
        self.remove_matrix.setEnabled(bool(self.entries))
        self.remove_action.setEnabled(bool(self.entries))
        self.remove_all.setEnabled(bool(self.entries))
        selected = self._entry()
        self.fourier_action.setEnabled(selected is not None and self._channel_loaded(selected)
                                       and selected.selection.mode != ViewMode.POINTS)
        self.merge_action.setEnabled(bool(self._merge_sources()))
        self.conversion_action.setEnabled(selected is not None and self._channel_loaded(selected))
        self.fourier_button.setEnabled(self.fourier_action.isEnabled() or self.merge_action.isEnabled()
                                       or self.conversion_action.isEnabled())
        self.laplace_action.setEnabled(selected is not None and self._channel_loaded(selected)
            and not selected.document.is_image and (selected.selection.mode in (ViewMode.SIGNAL, ViewMode.XY)
                or (selected.selection.mode == ViewMode.MATRIX and np.iscomplexobj(selected.document.array))))
        self._update_matrix_info()

        self._sync_raw_view()

    def _update_matrix_info(self) -> None:
        entry = self._entry()
        if entry is None:
            self.info.setText("No data loaded")
            self.info.setToolTip("")
            return
        document = entry.document
        summary = f"{document.array.shape} · {document.array.dtype} · {document.array.nbytes / 1024**2:,.3f} MiB"
        source = document.image_source
        if source is not None:
            summary = f"{summary}\n{source.layout} · {source.metadata.depth}"
        self.info.setText(summary)
        detail = f"{entry.source_label}\n{document.path}\nDisplay: {active_channel(entry).label}\nIndices start at 0."
        if document.transform is not None:
            detail = f"{detail}\n\n{document.transform.description}"
        if document.laplace is not None:
            detail = f"{detail}\n\n{document.laplace.description}"
        if document.is_complex:
            detail = f"{detail}\nComplex source: full real + imaginary values available for export."
        if document.complex_provenance:
            detail = f"{detail}\n\n{document.complex_provenance}"
        if document.conversion_provenance:
            detail = f"{detail}\n\n{document.conversion_provenance}"
        if document.import_provenance:
            detail = f"{detail}\n\n{document.import_provenance}"
        self.info.setToolTip(detail)

    def _rename_selected(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        name, accepted = QtWidgets.QInputDialog.getText(self, "Rename matrix", "Session name (source file is unchanged):",
                                                       text=entry.label)
        if accepted and name.strip():
            for member in self._groups()[entry.matrix_uid or entry.uid]:
                member.name = name.strip()
            self._refresh_list()
            self._render_workspace()
            self._sync_export_controls()

    def _refresh_control_visibility(self) -> None:
        super()._refresh_control_visibility()
        if self._workspace_ready:
            self.axes_form.setRowVisible(self.channel, False)

    def _sync_alignment(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        with QtCore.QSignalBlocker(self.alignment_x), QtCore.QSignalBlocker(self.alignment_y), QtCore.QSignalBlocker(self.alignment_z), QtCore.QSignalBlocker(self.layer_opacity):
            self.alignment_x.setCurrentIndex(self.alignment_x.findData(entry.align_x.value))
            self.alignment_y.setCurrentIndex(self.alignment_y.findData(entry.align_y.value))
            self.alignment_z.setCurrentIndex(self.alignment_z.findData(entry.align_z.value))
            self.layer_opacity.setValue(entry.opacity)
        self.alignment_x.setEnabled(entry.uid != self.reference_uid)
        self.alignment_y.setEnabled(entry.uid != self.reference_uid and family(entry.selection.mode) != ViewMode.SIGNAL)
        spatial = family(entry.selection.mode) != ViewMode.SIGNAL
        self.alignment_z.setEnabled(entry.uid != self.reference_uid and spatial)
        form = self.alignment_box.layout()
        if isinstance(form, QtWidgets.QFormLayout):
            form.setRowVisible(self.alignment_z, spatial)
        self._set_color_icon(self.layer_color, QtGui.QColor(entry.color))

    def _list_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column == 2 or self.matrix_list.checkbox_click:
            return
        self._list_activated(item, column)

    def _list_activated(self, item: QtWidgets.QTreeWidgetItem, column: int = 0) -> None:
        if column == 2 or self.matrix_list.checkbox_click:
            return
        if item.parent() is None:
            members = self._groups().get(int(item.data(0, QtCore.Qt.ItemDataRole.UserRole)), [])
            if len(members) > 1:
                item.setExpanded(True)
                entry = next((member for member in members if member.uid == self.active_uid), None)
                entry = entry or next((member for member in members if member.visible), members[0])
                if entry.uid != self.active_uid:
                    self._activate(entry)
                self.matrix_list.setCurrentItem(item)
                return
        entry = self._tree_entry(item)
        if entry is None:
            return
        if self.single_matrix_mode.isChecked():
            if entry.uid != self.active_uid or not entry.visible:
                self._show_only(entry)
        elif entry.uid != self.active_uid:
            self._activate(entry)

    def _tree_entry(self, item: QtWidgets.QTreeWidgetItem) -> MatrixEntry | None:
        """Resolve a channel leaf, including a flattened single-channel matrix.

        Root rows store matrix-group IDs, which can differ from the remaining
        channel's ID after changing its interpretation. Group rows return None.
        """
        uid = int(item.data(0, QtCore.Qt.ItemDataRole.UserRole))
        if item.parent() is not None:
            return self._entry(uid)
        members = self._groups().get(uid, [])
        return members[0] if len(members) == 1 else None

    def _show_only(self, entry: MatrixEntry) -> None:
        self._raw_matrix_uid = entry.matrix_uid or entry.uid
        for member in self.entries:
            member.visible = member.uid == entry.uid
        self.reference_uid = entry.uid
        if entry.uid != self.active_uid:
            self._activate(entry)
        else:
            self._refresh_list()
            self._render_workspace(reset=True)

    def _compatible(self, entry: MatrixEntry) -> str | None:
        other = next((item for item in self.entries if item.visible and item.uid != entry.uid), None)
        if other is not None and family(other.selection.mode) != family(entry.selection.mode):
            return (f"Cannot overlay {entry.label} ({entry.selection.mode.value}) with "
                    f"{other.label} ({other.selection.mode.value}).\nChange the selected matrix's interpretation or hide conflicting entries. "
                    "Indexed 1D and XY signals are compatible.")
        if other is not None and not self._same_domain(entry, other):
            return (f"Cannot overlay {entry.label} with {other.label}: coordinate domains or units differ. "
                    "Hide the conflicting source/frequency matrices first.")
        return None

    @staticmethod
    def _domain(entry: MatrixEntry) -> tuple[tuple[bool, str | None], ...]:
        selection, document = entry.selection, entry.document
        axes = (selection.y_axis, selection.x_axis) if selection.y_axis is not None else (selection.x_axis,)
        grids = (document.axes[axis] if document.axes and axis is not None else None for axis in axes)
        return tuple((grid.frequency, grid.unit) if grid is not None else (False, None) for grid in grids)

    @classmethod
    def _same_domain(cls, first: MatrixEntry, second: MatrixEntry) -> bool:
        a, b = cls._domain(first), cls._domain(second)
        return len(a) == len(b) and all(fa == fb and (ua is None or ub is None or ua == ub)
                                       for (fa, ua), (fb, ub) in zip(a, b, strict=True))

    def _list_checked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column != 0 or not item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable:
            return
        entry = self._tree_entry(item)
        if entry is None:
            return
        checked = item.checkState(0) == QtCore.Qt.CheckState.Checked
        self._set_entry_visible(entry, checked)

    def _set_entry_visible(self, entry: MatrixEntry, checked: bool) -> None:
        """Apply a checkbox/menu visibility change with the same overlay validation."""
        if checked and self.single_matrix_mode.isChecked():
            self._show_only(entry)
            return
        problem = self._compatible(entry) if checked else None
        entry.visible = checked and problem is None
        if problem:
            QtWidgets.QMessageBox.warning(self, "Incompatible overlay", problem)
        if entry.visible and entry.uid != self.active_uid:
            self._activate(entry)
            return
        self._refresh_list()
        self._prepare_missing()
        self._render_workspace(reset=True)

    def _list_color(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        entry = self._tree_entry(item)
        if column == 2 and entry is not None:
            self._choose_entry_color(entry.uid)

    def _choose_layer_color(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        self._choose_entry_color(entry.uid)

    def _choose_entry_color(self, uid: int, checked: bool = False) -> None:
        entry = self._entry(uid)
        if entry is None:
            return
        chosen = QtWidgets.QColorDialog.getColor(QtGui.QColor(entry.color), self, f"Overlay color — {entry.label}")
        if chosen.isValid():
            entry.color = chosen.name()
            self._sync_alignment()
            self._refresh_list()
            self._render_workspace()

    def _alignment_changed(self) -> None:
        if self._restoring:
            return
        entry = self._entry()
        if entry is not None:
            entry.align_x = Alignment(self.alignment_x.currentData())
            entry.align_y = Alignment(self.alignment_y.currentData())
            entry.align_z = Alignment(self.alignment_z.currentData())
            entry.opacity = self.layer_opacity.value()
            self._render_workspace(reset=True)

    def _reference_changed(self) -> None:
        uid = self.reference.currentData()
        entry = self._entry(int(uid)) if uid is not None else None
        visible = next((item for item in self.entries if item.visible), None)
        if entry is not None and visible is not None and (family(entry.selection.mode) != family(visible.selection.mode)
                                                          or not self._same_domain(entry, visible)):
            QtWidgets.QMessageBox.warning(self, "Incompatible reference", "The alignment reference must have the same interpreted type as the displayed matrices.")
            self._refresh_list()
            return
        self.reference_uid = entry.uid if entry else None
        self._sync_alignment()
        self._prepare_missing()
        self._render_workspace(reset=True)

    def _hide_all(self) -> None:
        for entry in self.entries:
            entry.visible = False
        self._refresh_list()
        self._render_workspace()

    def _remove_selected(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        index = self.entries.index(entry)
        self._rebuild.stop()
        self._latest[JobKind.FRAME] = -1
        self._latest[JobKind.LOAD] = -1
        group = entry.matrix_uid or entry.uid
        removed = {member.uid for member in self.entries if (member.matrix_uid or member.uid) == group}
        self.entries[:] = [member for member in self.entries if member.uid not in removed]
        self.active_uid = None
        self._loading_channel_uid = None
        if self.reference_uid in removed:
            self.reference_uid = self.entries[0].uid if self.entries else None
        self._refresh_list()
        if self.entries:
            self._activate(next((member for member in self.entries if member.visible), self.entries[min(index, len(self.entries) - 1)]))
        else:
            self._remove_all()

    def _remove_all(self) -> None:
        self._rebuild.stop()
        for kind in (JobKind.FRAME, JobKind.LOAD, JobKind.BUNDLE, JobKind.INSPECT, JobKind.FOURIER, JobKind.LAPLACE, JobKind.COMPLEX_MERGE, JobKind.DATA_CONVERSION):
            self._latest[kind] = -1
        self.entries.clear()
        self._preparing.clear()
        self._preparation_jobs.clear()
        self.active_uid = self.reference_uid = self._loading_channel_uid = None
        self._raw_matrix_uid = None
        self.document = self.frame = self.frame_selection = None
        self._export_ready = False
        self.controls.setEnabled(False)
        self.matrix_box.setEnabled(True)
        self.display_channel.clear()
        self.path_label.clear()
        self._refresh_list()
        self._clear_views()
        self.statusBar().showMessage("All matrices removed from the session.")

    def _open_dropped_path(self, path: Path) -> None:
        self.open_path(path, append=bool(self.entries))

    def _choose_overlay(self) -> None:
        start = str(self.document.path.parent) if self.document else ""
        title = "Add one overlay file" if self.multiple_matrix_mode.isChecked() else "Add one matrix file"
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, start, FILE_FILTER)
        if path:
            self.open_path(Path(path), append=True)

    def _choose_fourier(self) -> None:
        self._store_entry()
        entry = self._entry()
        if entry is None or not self._channel_loaded(entry) or entry.selection.mode == ViewMode.POINTS:
            return
        # Capture settings now; workers only receive these immutable values.
        document, selection, crop, limits, label = entry.document, entry.selection, entry.crop, entry.limits, entry.label
        index = self._export_profile_index() if self._profile_selected else None
        dialog = FourierDialog(document, selection, crop, label,
                               self.profile_direction.currentIndex() == 0, index, self)
        self._fourier_dialog = dialog

        def generate(options: TransformOptions, name: str) -> None:
            dialog.set_busy(True)
            self._submit(JobKind.FOURIER, partial(run_transform, document, selection, crop, limits, options, label, name))

        dialog.generate_requested.connect(generate)
        dialog.exec()
        self._fourier_dialog = None
        dialog.deleteLater()

    def _choose_laplace(self) -> None:
        """Capture a signal/plane and open on-demand Laplace settings."""
        self._store_entry()
        entry = self._entry()
        if entry is None or not self._channel_loaded(entry) or entry.document.is_image:
            return
        if (entry.selection.mode not in (ViewMode.SIGNAL, ViewMode.XY)
                and not (entry.selection.mode == ViewMode.MATRIX and np.iscomplexobj(entry.document.array))):
            return
        document, selection, crop, limits, label = entry.document, entry.selection, entry.crop, entry.limits, entry.label
        dialog = LaplaceDialog(document, selection, crop, label, self)
        self._laplace_dialog = dialog

        def generate(options: LaplaceOptions, name: str) -> None:
            dialog.set_busy(True)
            self._submit(JobKind.LAPLACE, partial(run_laplace, document, selection, crop, limits, options, label, name))

        dialog.generate_requested.connect(generate)
        dialog.exec()
        self._laplace_dialog = None
        dialog.deleteLater()

    def _merge_sources(self) -> tuple[MergeMatrix, ...]:
        """Offer stored channel interpretations, including unchecked source rows."""
        matrices: list[MergeMatrix] = []
        for members in self._groups().values():
            channels: list[MergeInput] = []
            for entry in members:
                channel = active_channel(entry)
                if entry.selection.mode == ViewMode.POINTS or channel.image_key in (
                    ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR, ImageMember.MONO_COLOR,
                ):
                    continue
                channels.append(MergeInput(entry.document, entry.selection, self._channel_label(entry),
                                           channel.image_key, channel.label))
            if channels:
                matrices.append(MergeMatrix(members[0].label, tuple(channels)))
        return tuple(matrices)

    def _choose_complex_merge(self) -> None:
        self._store_entry()
        matrices = self._merge_sources()
        if not matrices:
            return
        entry = self._entry()
        initial = next((index for index, item in enumerate(matrices) if entry is not None and item.label == entry.label), 0)
        dialog = ComplexMergeDialog(matrices, initial, self)
        self._merge_dialog = dialog

        def generate(first: MergeInput, second: MergeInput, mode: MergeMode, unit: PhaseUnit, name: str) -> None:
            dialog.set_busy(True)
            self._submit(JobKind.COMPLEX_MERGE, partial(run_merge, first, second, mode, unit, name))

        dialog.generate_requested.connect(generate)
        dialog.exec()
        self._merge_dialog = None
        dialog.deleteLater()

    def _choose_data_conversion(self) -> None:
        """Capture the active channel and open pointwise conversion settings."""
        self._store_entry()
        entry = self._entry()
        if entry is None or not self._channel_loaded(entry):
            return
        document, selection, crop, limits = entry.document, entry.selection, entry.crop, entry.limits
        label = self._channel_label(entry)
        index = self._export_profile_index() if self._profile_selected else None
        dialog = DataConversionDialog(document, selection, label,
                                      self.profile_direction.currentIndex() == 0, index, self)
        self._conversion_dialog = dialog

        def generate(options: ConversionOptions, name: str) -> None:
            dialog.set_busy(True)
            self._submit(JobKind.DATA_CONVERSION, partial(run_conversion, document, selection, crop, limits, options, label, name))

        dialog.generate_requested.connect(generate)
        dialog.exec()
        self._conversion_dialog = None
        dialog.deleteLater()

    def _operation_dialog(self, kind: JobKind) -> FourierDialog | LaplaceDialog | ComplexMergeDialog | DataConversionDialog | None:
        if kind == JobKind.DATA_CONVERSION:
            return self._conversion_dialog
        if kind == JobKind.COMPLEX_MERGE:
            return self._merge_dialog
        return self._laplace_dialog if kind == JobKind.LAPLACE else self._fourier_dialog

    def _transform_done(self, result: TransformResult, kind: JobKind = JobKind.FOURIER) -> None:
        """Add a completed result and ask whether to display it exclusively."""
        dialog = self._operation_dialog(kind)
        operation = ("Data conversion" if kind == JobKind.DATA_CONVERSION else
                     "Complex matrix merge" if kind == JobKind.COMPLEX_MERGE else
                     "Laplace transform" if kind == JobKind.LAPLACE else "Fourier transform")
        if dialog is not None:
            dialog.set_busy(False)
            dialog.accept()
        self._store_entry()
        self._uid += 1
        document = result.document
        mode = ViewMode.SIGNAL if document.array.ndim == 1 else ViewMode.MATRIX
        forward = ((document.transform is not None and document.transform.direction == TransformDirection.FORWARD)
                   or (document.laplace is not None and document.laplace.direction == LaplaceDirection.FORWARD))
        selection = result.selection or replace(default_selection(document, mode),
                            component=Component.MAGNITUDE if forward or kind == JobKind.COMPLEX_MERGE else Component.REAL)
        entry = MatrixEntry(self._uid, document, selection, COLORS[(self._uid - 1) % len(COLORS)],
                            limits=Limits(mode=FilterMode(str(self._defaults["filter_mode"]))),
                            settings=self._defaults.copy(), name=result.name, visible=False)
        self.entries.append(entry)
        answer = QtWidgets.QMessageBox.question(
            self, f"{operation} complete",
            f"Created: {entry.label}\n\nDisplay only this new matrix?\n"
            "Yes: uncheck all other matrices and select this result.\n"
            "No: keep the current display and add the result unchecked.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            self._refresh_list()
            self.statusBar().showMessage(f"{operation} complete: {entry.label} added unchecked. Current display retained.")
            return
        for previous in self.entries:
            previous.visible = False
        entry.visible = True
        self.reference_uid = entry.uid
        self._activate(entry, reset_selection=True)

    def open_path(self, path: Path, key: str | None = None, *, append: bool = False) -> None:
        """Load one file asynchronously, replacing or appending session entries.

        Args:
            path: Supported numeric/image file.
            key: Optional archive member to select first.
            append: True retains loaded matrices. Single mode displays only the
                new file's first member; multiple mode adds compatible overlays.
        """
        self._store_entry()
        self._append_pending = append and bool(self.entries)
        self._rebuild.stop()
        self._latest[JobKind.FRAME] = -1
        self._latest[JobKind.LOAD] = -1
        self.controls.setEnabled(False)
        self.matrix_box.setEnabled(False)
        self.display_channel.setEnabled(False)
        self.statusBar().showMessage(f"Loading {path.name}…")
        self._latest[JobKind.BUNDLE] = -1
        self._latest[JobKind.INSPECT] = -1
        if path.suffix.lower() in INSPECT_EXTENSIONS:
            self._submit(JobKind.INSPECT, partial(inspect_source, path, key))
        else:
            self._submit(JobKind.BUNDLE, partial(load_file, path, key))

    def _choose_import(self, catalog: ImportCatalog, number: int) -> None:
        """Select archive members/ranges before allocating their numeric arrays."""
        if catalog.tabular or len(catalog.members) > 1:
            dialog = ImportDialog(catalog, self)
            self._import_dialog = dialog
            try:
                accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
                choices = dialog.choices() if accepted else ()
            finally:
                self._import_dialog = None
                dialog.deleteLater()
        else:
            member = catalog.members[0]
            choices = (ImportChoice(member.key),) if not member.error else ()
        if self._closing or self._latest.get(JobKind.INSPECT) != number:
            return
        if not choices:
            self._cancel_opening()
            return
        self.statusBar().showMessage(f"Loading {len(choices)} selected matrices from {catalog.path.name}…")
        self._submit(JobKind.BUNDLE, partial(load_file, catalog.path, choices=choices))

    def _cancel_opening(self) -> None:
        """Restore the unchanged workspace after cancelling an import dialog."""
        self.matrix_box.setEnabled(True)
        self.controls.setEnabled(self.document is not None)
        self._sync_source_selectors(self.frame_selection.component if self.frame_selection else Component.REAL)
        self._refresh_list()
        self._render_workspace()
        entry = self._entry()
        if entry is not None and entry.frame is None:
            self._request_frame()
        self.statusBar().showMessage("Opening canceled; the current workspace was kept.")

    def _opening_selection(self, document: Document, mode: ViewMode | None = None,
                           channel_axis: int | None = None) -> Selection | None:
        """Resolve an incoming source's interpretation before changing the session.

        Args:
            document: Newly loaded file or archive member.
            mode: Explicit initial CLI mode; skips the ambiguity prompt.
            channel_axis: Optional initial CLI channel-axis assignment.

        Returns:
            Chosen axis selection, or None when the user cancels opening.
            Numeric 2-by-N/N-by-2 with N > 2 offer XY; 3-by-N/N-by-3
            with N > 3 offer XYZ. Images and other shapes retain their usual
            defaults. Complex arrays cannot supply XY/XYZ coordinates.
        """
        try:
            selection = default_selection(document, mode, channel_axis)
        except ValueError:
            selection = default_selection(document)
        shape = document.array.shape
        if mode is not None or document.is_image or len(shape) != 2:
            return selection
        count = 2 if 2 in shape and max(shape) > 2 else 3 if 3 in shape and max(shape) > 3 else 0
        if not count:
            return selection
        source = f"{document.path.name} :: {document.key}" if document.key is not None else document.path.name
        coordinates = "columns" if shape[1] == count else "rows"
        coordinate_mode = ViewMode.XY if count == 2 else ViewMode.POINTS
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle("Choose matrix interpretation")
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Question)
        dialog.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        dialog.setText(f"{source}\nShape: {shape[0]} × {shape[1]}\nHow should this matrix be opened?")
        explanation = (f"1D XY: use the two {coordinates} as X and Y (first = X, second = Y). You can swap X/Y later."
                       if count == 2 else
                       f"Point cloud: use the three {coordinates} as X, Y and Z (in that order). You can change the coordinate assignments later.")
        explanation = f"{explanation}\n2D matrix: keep rows and columns as a matrix for image, surface and slice views."
        coordinate_button = dialog.addButton("1D XY" if count == 2 else "Point cloud (XYZ)",
                                             QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        matrix = dialog.addButton("2D matrix", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        if document.is_complex:
            coordinate_button.setEnabled(False)
            explanation = f"{explanation}\n\n{'XY' if count == 2 else 'XYZ'} coordinates require real values; this complex matrix can be opened in 2D mode."
        dialog.setInformativeText(explanation)
        dialog.setDefaultButton(matrix)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        chosen = dialog.clickedButton()
        if chosen is not coordinate_button and chosen is not matrix:
            return None
        return default_selection(document, coordinate_mode if chosen is coordinate_button else ViewMode.MATRIX)

    def _job_done(self, number: int, kind_text: str, result: object) -> None:
        kind = JobKind(kind_text)
        if kind == JobKind.INSPECT:
            self._jobs.pop(number, None)
            if not self._closing and self._latest.get(kind) == number:
                self._choose_import(cast(ImportCatalog, result), number)
            return
        if kind in (JobKind.FOURIER, JobKind.LAPLACE, JobKind.COMPLEX_MERGE, JobKind.DATA_CONVERSION):
            self._jobs.pop(number, None)
            if not self._closing and self._latest.get(kind) == number:
                self._transform_done(cast(TransformResult, result), kind)
            return
        if kind not in (JobKind.BUNDLE, JobKind.OVERLAY_FRAMES):
            super()._job_done(number, kind_text, result)
            return
        self._jobs.pop(number, None)
        if self._closing or (kind == JobKind.BUNDLE and self._latest.get(kind) != number):
            return
        if kind == JobKind.OVERLAY_FRAMES:
            self._finish_preparation(number)
            problems: list[str] = []
            for prepared in cast(tuple[PreparedEntry, ...], result):
                entry = self._entry(prepared.uid)
                if entry is None or entry.revision != prepared.revision:
                    continue
                entry.frame = prepared.frame
                if prepared.document is not None and prepared.selection is not None:
                    entry.document, entry.selection = prepared.document, prepared.selection
                if prepared.error:
                    entry.visible = False
                    problems.append(f"{entry.label}: {prepared.error}")
            self._refresh_list()
            self._render_workspace(reset=True)
            if problems:
                QtWidgets.QMessageBox.warning(self, "Cannot prepare overlays", "\n".join(problems))
            return
        loaded = cast(LoadedFile, result)
        selections: list[tuple[Document, Selection]] = []
        for document in loaded.documents:
            selection = self._opening_selection(document, self._initial_mode if not selections else None,
                                                 self._initial_channel_axis if not selections else None)
            # A modal dialog runs Qt events; discard choices for superseded loads.
            if self._closing or self._latest.get(kind) != number:
                return
            if selection is None:
                self._cancel_opening()
                return
            selections.append((document, selection))
        self.matrix_box.setEnabled(True)
        if not self._append_pending:
            self.entries.clear()
            self.active_uid = self.reference_uid = None
        multiple = self.multiple_matrix_mode.isChecked()
        if not multiple:
            for previous in self.entries:
                previous.visible = False
        added: list[MatrixEntry] = []
        problems = list(loaded.errors)
        for document, selection in selections:
            self._uid += 1
            entry = MatrixEntry(self._uid, document, selection, self._default_color(self._uid, document.key if document.is_image else None),
                                visible=multiple or not added,
                                limits=Limits(mode=FilterMode(str(self._defaults["filter_mode"]))), settings=self._defaults.copy())
            duplicates = [item.instance for item in self.entries
                          if item.document.path.name == document.path.name
                          and (item.document.key if not item.document.is_image else None) == (document.key if not document.is_image else None)]
            entry.instance = max(duplicates, default=0) + 1
            problem = self._compatible(entry) if multiple else None
            if problem:
                entry.visible = False
                problems.append(problem)
            self.entries.append(entry)
            self._expand_channels(entry)
            added.append(entry)
        self.reference_uid = (self.reference_uid or self.entries[0].uid) if multiple else added[0].uid
        self._initial_mode = None
        self._initial_channel_axis = None
        self._activate(added[0], reset_selection=not self._append_pending)
        if problems:
            QtWidgets.QMessageBox.warning(self, "Some matrices were not displayed", "\n\n".join(problems))

    def _job_failed(self, number: int, kind_text: str, message: str) -> None:
        kind = JobKind(kind_text)
        if kind == JobKind.LOAD and not self._closing and self._latest.get(kind) == number:
            super()._job_failed(number, kind_text, message)
            entry = self._entry()
            if entry is not None:
                entry.visible = False
            self._loading_channel_uid = None
            self.controls.setEnabled(False)
            self._refresh_list()
            self._render_workspace()
            return
        if kind in (JobKind.FOURIER, JobKind.LAPLACE, JobKind.COMPLEX_MERGE, JobKind.DATA_CONVERSION):
            self._jobs.pop(number, None)
            if not self._closing and self._latest.get(kind) == number:
                dialog = self._operation_dialog(kind)
                if dialog is not None:
                    dialog.set_busy(False)
                QtWidgets.QMessageBox.warning(dialog or self, "Cannot merge components" if kind == JobKind.COMPLEX_MERGE else "Cannot transform matrix", message)
            return
        if kind not in (JobKind.BUNDLE, JobKind.OVERLAY_FRAMES, JobKind.INSPECT):
            super()._job_failed(number, kind_text, message)
            return
        self._jobs.pop(number, None)
        if self._closing or (kind in (JobKind.BUNDLE, JobKind.INSPECT) and self._latest.get(kind) != number):
            return
        if kind == JobKind.OVERLAY_FRAMES:
            self._finish_preparation(number)
        self.matrix_box.setEnabled(True)
        self.controls.setEnabled(self.document is not None)
        self._sync_source_selectors(self.frame_selection.component if self.frame_selection else Component.REAL)
        QtWidgets.QMessageBox.warning(self, "Cannot open file" if kind in (JobKind.BUNDLE, JobKind.INSPECT) else "Cannot prepare overlays", message)
        self.statusBar().showMessage(f"Error: {message}")

    def _document_loaded(self, document: Document) -> None:
        entry = self._entry()
        if entry is not None:
            entry.document = document
            entry.image_key = document.key if document.image_source is not None else None
            entry.selection = self._channel_selection(document, entry.selection)
            entry.frame = None
            entry.revision += 1
            self._loading_channel_uid = None
            self._restoring = True
            try:
                self._activate(entry)
            finally:
                self._restoring = False
            return
        super()._document_loaded(document)
        self._update_matrix_info()

    def _request_frame(self) -> None:
        if self._restoring:
            return
        self._store_entry()
        entry = self._entry()
        if entry is not None:
            entry.revision += 1
            problem = self._compatible(entry) if self._overlay() and entry.visible else None
            if problem:
                entry.visible = False
                QtWidgets.QMessageBox.warning(self, "Incompatible overlay", problem)
        super()._request_frame()
        self._prepare_missing()

    def _mode_changed(self) -> None:
        entry = self._entry()
        component = entry.selection.component if entry is not None else Component.REAL
        super()._mode_changed()
        if entry is not None and np.iscomplexobj(entry.document.array):
            with QtCore.QSignalBlocker(self.display_channel):
                self.display_channel.setCurrentIndex(self.display_channel.findData(component.value))

    def _schedule_frame(self) -> None:
        if not self._restoring:
            super()._schedule_frame()

    def _prepare_missing(self) -> None:
        requested = [(entry.uid, entry.revision, entry.document, entry.selection, entry.image_key, entry.limits, entry.crop,
                      int(entry.settings.get("max_edge", self._default_edge)), int(entry.settings.get("max_points", DEFAULT_MAX_POINTS)))
                     for entry in self.entries if entry.uid != self.active_uid and entry.frame is None
                     and self._preparing.get(entry.uid) != entry.revision
                     and (entry.visible or entry.uid == self.reference_uid)]
        if not requested:
            return

        def prepare() -> tuple[PreparedEntry, ...]:
            results: list[PreparedEntry] = []
            for uid, revision, document, selection, image_key, limits, crop, edge, points in requested:
                try:
                    if image_key is not None and document.key != image_key:
                        document = select_image_member(document, image_key)
                        selection = self._channel_selection(document, selection)
                    frame = prepare_frame(document, selection, limits, edge if selection.mode == ViewMode.MATRIX else 0, crop, max_points=points)
                    results.append(PreparedEntry(uid, revision, frame, document=document, selection=selection))
                except (ValueError, MemoryError) as exc:
                    results.append(PreparedEntry(uid, revision, None, str(exc)))
            return tuple(results)

        for uid, revision, *_ in requested:
            self._preparing[uid] = revision
        self._submit(JobKind.OVERLAY_FRAMES, prepare)
        self._preparation_jobs[self._serial] = tuple((item[0], item[1]) for item in requested)

    def _finish_preparation(self, number: int) -> None:
        for uid, revision in self._preparation_jobs.pop(number, ()):
            if self._preparing.get(uid) == revision:
                self._preparing.pop(uid)

    def _show_frame(self, reset: bool) -> None:
        entry = self._entry()
        if entry is not None and self.frame is not None and self.frame_selection is not None:
            entry.frame, entry.selection = self.frame, self.frame_selection
            self._store_entry()
        self._export_ready = self.frame is not None
        self._sync_frame_controls()
        self._single_render_key = None
        if self._workspace_ready:
            self._refresh_list()
            self._render_workspace(reset and (entry is None or entry.visible))

    def _raw_source_name(self) -> str:
        entry = self._entry()
        return self._channel_label(entry) if entry is not None else ""

    def _raw_matrix_changed(self, index: int) -> None:
        """Browse a source group without changing editing or plot state."""
        groups = list(self._groups())
        if 0 <= index < len(groups):
            self._raw_matrix_uid = groups[index]
            self._sync_raw_view()

    def _sync_raw_view(self) -> None:
        """Keep raw source names and data synchronized with workspace groups."""
        if self._view_override is not None:
            return
        groups = self._groups()
        group_ids = list(groups)
        active = self._entry()
        if self._raw_matrix_uid not in groups:
            self._raw_matrix_uid = (active.matrix_uid or active.uid) if active is not None else next(iter(groups), None)
        index = group_ids.index(self._raw_matrix_uid) if self._raw_matrix_uid is not None else -1
        self.raw_view.set_matrices(tuple(members[0].label for members in groups.values()), index)
        members = groups.get(self._raw_matrix_uid, []) if self._raw_matrix_uid is not None else []
        entry = next((member for member in members if member.uid == self.active_uid), None)
        if entry is None:
            entry = next((member for member in members if member.visible), members[0] if members else None)
        if entry is None or not entry.visible or entry.frame is None:
            message = (f"Hidden: {self._channel_label(entry)}. Check this channel to view its raw data."
                       if entry is not None and not entry.visible else
                       f"Loading raw data: {self._channel_label(entry)}…" if entry is not None else "No data loaded")
            self.raw_view.clear(message)
            return
        if self.raw_view.frame is not entry.frame:
            labels = entry.document.csv_headers if entry.selection.x_axis == 1 else ()
            self.raw_view.set_frame(entry.frame, labels, image_source=entry.document.image_source,
                                    source_name=self._channel_label(entry))
        else:
            self.raw_view.set_source_name(self._channel_label(entry))

    def _clear_views(self) -> None:
        self._render_layers = ()
        self._single_render_key = None
        self._surface_dirty = True
        self.image_view.set_layers(())
        self.image_view.set_profile(True, None)
        self.surface_view.set_layers(())
        self.profile_view.clear_selection()
        self.overlay_profile.clear_selection()
        self.profile_controls.setEnabled(False)
        self._sync_raw_view()
        self._sync_export_controls()

    def _set_view_layout(self, mode: ViewMode) -> None:
        if not (self._overlay() and self._painting_active):
            super()._set_view_layout(mode)

    def _sync_frame_controls(self) -> None:
        if self._view_override is None:
            super()._sync_frame_controls()

    def _show_signal_tab(self) -> None:
        super()._show_signal_tab()
        if self._overlay() and self.tabs.currentIndex() in (0, 1):
            self.overlay_profile.tabs.setCurrentIndex(self.tabs.currentIndex())

    def _make_layers(self) -> tuple[RenderLayer, ...]:
        visible = [entry for entry in self.entries if entry.visible and entry.frame is not None]
        if not visible:
            return ()
        reference = self._entry(self.reference_uid)
        if reference is None or (family(reference.selection.mode) != family(visible[0].selection.mode)
                                  or not self._same_domain(reference, visible[0])):
            reference = visible[0]
            self.reference_uid = reference.uid
            self._refresh_list()
            self._sync_alignment()
        if reference.frame is None:
            return ()
        rx, ry = coordinate_bounds(reference.frame)
        auto_height = overlay_auto_height(visible, reference)
        reference_height = auto_height if reference.settings.get("auto_height", True) else float(reference.settings.get("height_scale", 1))
        align_heights = family(reference.selection.mode) != ViewMode.SIGNAL and any(
            entry.uid != reference.uid and entry.align_z != Alignment.ORIGINAL for entry in visible)
        rz = height_bounds(reference.frame, reference_height) if align_heights else (0.0, 0.0)
        layers: list[RenderLayer] = []
        for entry in visible:
            frame = entry.frame
            assert frame is not None
            x, y = coordinate_bounds(frame)
            own_reference = entry.uid == reference.uid
            height = auto_height if entry.settings.get("auto_height", True) else float(entry.settings.get("height_scale", 1))
            z = (align_axis(height_bounds(frame, height), rz, entry.align_z)
                 if align_heights and not own_reference and entry.align_z != Alignment.ORIGINAL else AxisMap())
            jump = JumpMode(int(entry.settings.get("jump_mode", JumpMode.GAPS_ONLY)))
            threshold = (None if jump == JumpMode.GAPS_ONLY else float(np.pi) if jump == JumpMode.RADIANS
                         else 180.0 if jump == JumpMode.DEGREES else float(entry.settings.get("jump_threshold", 1)))
            layers.append(RenderLayer(entry.uid, self._channel_label(entry), frame, entry.color, entry.opacity,
                align_axis(x, rx, Alignment.ORIGINAL if own_reference else entry.align_x),
                align_axis(y, ry, Alignment.ORIGINAL if own_reference else entry.align_y),
                height,
                float(entry.settings.get("point_size", 2)), str(entry.settings.get("clip_color", "#ff0000")), threshold,
                (id(entry.document.array), entry.selection, frame.x_start, frame.y_start, frame.scalar.shape, frame.value_limits), z))
        return tuple(layers)

    def _render_workspace(self, reset: bool = False) -> None:
        if not self._workspace_ready or self._restoring or self._painting_active or self._rendering:
            return
        self._rendering = True
        try:
            overlay = self._overlay()
            self._profile_uses_overlay = overlay
            self.profile_view.setVisible(not overlay)
            self.overlay_profile.setVisible(overlay)
            if not any(entry.visible for entry in self.entries):
                self._clear_views()
                return
            if not overlay:
                self._render_layers = ()
                entry = next((member for member in self.entries if member.visible), None)
                if entry is not None and entry.frame is not None:
                    key = (entry.uid, id(entry.frame))
                    if self._single_render_key != key or reset:
                        self._painting_active = True
                        try:
                            with self._single_view_context():
                                super()._show_frame(reset)
                        finally:
                            self._painting_active = False
                        self._single_render_key = key
                    if entry.selection.mode in (ViewMode.SIGNAL, ViewMode.XY):
                        self.profile_view.title.setText(self._channel_label(entry))
                        self.profile_view.title.setToolTip(self._channel_label(entry))
                else:
                    self._clear_views()
                self._sync_raw_view()
                self._sync_export_controls()
                return
            self._single_render_key = None
            layers = self._make_layers()
            changed = tuple(layer.signature for layer in layers) != tuple(layer.signature for layer in self._render_layers)
            self._render_layers = layers
            selected_layer = next((layer for layer in layers if layer.uid == self.active_uid), None)
            if selected_layer is not None and self.auto_height.isChecked():
                with QtCore.QSignalBlocker(self.height_scale):
                    self.height_scale.setValue(selected_layer.height)
                self._sync_height_slider()
            if changed:
                self._surface_dirty = True
            visible = next((entry for entry in self.entries if entry.visible), None)
            mode = family(visible.selection.mode) if visible is not None else self._layout_mode or ViewMode.MATRIX
            super()._set_view_layout(mode)
            self.overlay_profile.set_external_tabs(mode == ViewMode.SIGNAL)
            self.overlay_profile.set_derivative_enabled(mode != ViewMode.POINTS)
            if mode == ViewMode.SIGNAL and self.tabs.currentIndex() in (0, 1):
                self.overlay_profile.tabs.setCurrentIndex(self.tabs.currentIndex())
            self.profile_controls.setVisible(mode == ViewMode.MATRIX)
            self.profile_controls.setEnabled(mode == ViewMode.MATRIX)
            self._sync_raw_view()
            if mode == ViewMode.MATRIX:
                self.image_view.set_layers(layers, reset)
                self._configure_profile_range()
                if reset:
                    self.overlay_profile.reset_view()
            elif mode == ViewMode.SIGNAL:
                series = tuple(item for layer in layers if (item := profile_series(layer)) is not None)
                self.overlay_profile.set_series(series, reset)
            else:
                self.overlay_profile.clear_selection()
            if mode != ViewMode.SIGNAL and self.tabs.currentIndex() == 1:
                self.surface_view.set_layers(layers, reset)
                self._surface_dirty = False
                if mode == ViewMode.MATRIX:
                    self.surface_view.set_layer_profiles(self.profile_direction.currentIndex() == 0,
                                                        self._profile_position() if self._profile_selected else None)
            self._sync_export_controls()
        finally:
            self._rendering = False

    def _configure_profile_range(self) -> None:
        if not self._overlay():
            with self._single_view_context():
                super()._configure_profile_range()
            return
        if self._painting_active:
            return
        row = self.profile_direction.currentIndex() == 0
        bounds: list[tuple[float, float]] = []
        for layer in self._render_layers:
            if layer.frame.scalar.ndim != 2:
                continue
            x, y = coordinate_bounds(layer.frame)
            a, b = y if row else x
            mapping = layer.y if row else layer.x
            bounds.append((mapping.forward(a), mapping.forward(b)))
        if bounds:
            mapping = self._profile_mapping()
            low = int(np.floor(mapping.inverse(min(a for a, _ in bounds))))
            high = int(np.ceil(mapping.inverse(max(b for _, b in bounds))))
            with QtCore.QSignalBlocker(self.profile_index), QtCore.QSignalBlocker(self.profile_slider):
                self.profile_index.setRange(low, high)
                self.profile_slider.setRange(low, high)
                self.profile_slider.setValue(self.profile_index.value())
        self._update_profile()

    def _update_profile(self) -> None:
        if not self._overlay():
            with self._single_view_context():
                entry = self._entry()
                if entry is not None and entry.visible:
                    super()._update_profile()
            return
        if self._restoring or self._painting_active:
            return
        row, position = self.profile_direction.currentIndex() == 0, self._profile_position()
        self.profile_toggle.setText("Clear selection" if self._profile_selected else "Select current")
        series = tuple(item for layer in self._render_layers
                       if self._profile_selected and (item := profile_series(layer, row, position)) is not None)
        self.overlay_profile.set_series(series)
        self._sync_export_controls()
        self.image_view.set_profile(row, position if self._profile_selected else None)
        if self.tabs.currentIndex() == 1 and not self._surface_dirty:
            self.surface_view.set_layer_profiles(row, position if self._profile_selected else None)

    def _set_profile_auto_y(self, enabled: bool) -> None:
        super()._set_profile_auto_y(enabled)
        if self._workspace_ready:
            self.overlay_profile.set_y_auto_range(enabled)

    def _profile_mapping(self) -> AxisMap:
        reference = (self._entry(self.reference_uid) if self._overlay() else
                     next((entry for entry in self.entries if entry.visible), None))
        if reference is None or reference.frame is None:
            return AxisMap()
        frame = reference.frame
        return frame.y_mapping if self.profile_direction.currentIndex() == 0 else frame.x_mapping

    def _profile_position(self) -> float:
        return self._profile_mapping().forward(self.profile_index.value())

    def _export_profile_index(self) -> int:
        if self._overlay():
            series = next((item for item in self.overlay_profile._series if item.layer.uid == self.active_uid), None)
            if series is not None and series.index is not None:
                return series.index
        return super()._export_profile_index()

    def _sync_export_controls(self) -> None:
        if self._view_override is not None:
            return
        if hasattr(self, "export_scope"):
            scopes = [ExportScope.SELECTED]
            if self._has_export_channels():
                scopes.append(ExportScope.CHANNEL)
            scopes.append(ExportScope.VISIBLE)
            if [self.export_scope.itemData(index) for index in range(self.export_scope.count())] != scopes:
                previous_scope = self.export_scope.currentData()
                with QtCore.QSignalBlocker(self.export_scope):
                    self.export_scope.clear()
                    for scope in scopes:
                        self.export_scope.addItem(scope.value, scope.value)
                    self.export_scope.setCurrentIndex(max(0, self.export_scope.findData(previous_scope)))
        previous_layout = self.export_layout.currentText()
        previous_target = self.export_target.currentText()
        super()._sync_export_controls()
        if not hasattr(self, "export_scope"):
            return
        if hasattr(self, "figure_export_button"):
            ready = any(entry.visible and entry.frame is not None for entry in self.entries)
            self.figure_export_button.setEnabled(ready and not self._preparing and not self._rebuild.isActive())
        displayed = self.export_scope.currentData() == ExportScope.VISIBLE
        for field in (self.export_xy, self.export_z):
            self.export_form.setRowVisible(field, not displayed)
        if displayed:
            self._sync_displayed_export_controls(previous_layout, previous_target)
            return
        entry = self._entry()
        if self.document is not None and (self._overlay() or (entry is not None and not entry.visible)):
            self.export_box.setTitle("Export selected matrix")
            if entry is not None:
                self.export_hint.setText(f"{entry.label}\n{self.export_hint.text()}")
            if self.export_target.currentText() == ExportTarget.SLICE:
                series = next((item for item in self.overlay_profile._series if item.layer.uid == self.active_uid), None)
                if entry is None or not entry.visible or series is None or series.index is None:
                    self.export_save.setEnabled(False)
                    self.export_hint.setText("The selected matrix has no visible slice at this aligned position.")
        elif hasattr(self, "export_box"):
            self.export_box.setTitle("Export")
        if entry is not None:
            label = self._channel_label(entry) if self._export_channel_only() else entry.label
            self.export_box.setTitle("Export selected channel" if self._export_channel_only() else "Export selected matrix")
            self.export_dialog.setWindowTitle(f"Export — {label}")

    def _has_export_channels(self) -> bool:
        entry = self._entry()
        return entry is not None and (entry.document.is_complex or len(channel_choices(entry)) > 1)

    def _export_channel_only(self) -> bool:
        return hasattr(self, "export_scope") and self.export_scope.currentData() == ExportScope.CHANNEL

    def _export_all_channels(self) -> bool:
        if not hasattr(self, "export_scope") or self.export_scope.currentData() != ExportScope.SELECTED:
            return False
        entry = self._entry()
        if entry is None:
            return False
        source = entry.document.image_source
        return (source is not None and len(source.channels) > 1) or entry.selection.channel_axis is not None

    def _export_scope_changed(self) -> None:
        with QtCore.QSignalBlocker(self.export_complex):
            self.export_complex.setChecked(not self._export_channel_only())
        self._sync_export_controls()

    def _open_export_dialog(self, target: ExportTarget | None = None, *, channel: bool = False) -> None:
        """Show persistent export settings for the active matrix or its channel.

        Args:
            target: Optional menu-selected result/original/slice target. None
                retains the dialog's current scope and target.
            channel: With a target, select the real-valued active channel.

        Side effects:
            Runs a modal dialog; saves still use the existing background worker.
        """
        self._sync_export_controls()
        if target is not None:
            scope = ExportScope.CHANNEL if channel and self._has_export_channels() else ExportScope.SELECTED
            self.export_scope.setCurrentIndex(self.export_scope.findData(scope))
            self.export_complex.setChecked(scope != ExportScope.CHANNEL)
            self.export_target.setCurrentText(target)
        self._sync_export_controls()
        self.export_dialog.status.clear()
        self.export_dialog.exec()

    def _visible_export_layers(self) -> tuple[RenderLayer, ...]:
        if self._overlay():
            return self._render_layers
        entry = next((member for member in self.entries if member.visible), None)
        if entry is None or entry.frame is None:
            return ()
        return (RenderLayer(entry.uid, entry.label, entry.frame, entry.color, entry.opacity),)

    def _sync_displayed_export_controls(self, previous_layout: str, previous_target: str) -> None:
        self.export_box.setTitle("Export visible matrices")
        self.export_dialog.setWindowTitle("Export — all visible matrices")
        self.export_form.setRowVisible(self.export_complex, False)
        layers = self._visible_export_layers()
        first = self._entry(layers[0].uid) if layers else None
        mode = family(first.selection.mode) if first is not None else self._layout_mode
        targets = [ExportTarget.RESULT, ExportTarget.SLICE] if mode == ViewMode.MATRIX else [ExportTarget.RESULT]
        with QtCore.QSignalBlocker(self.export_target):
            self.export_target.clear()
            self.export_target.addItems([target.value for target in targets])
            self.export_target.setCurrentText(previous_target if previous_target in targets else ExportTarget.RESULT)
        sliced = self.export_target.currentText() == ExportTarget.SLICE
        choices = ((ExportLayout.XY_COLUMNS, ExportLayout.XY_ROWS) if sliced or mode == ViewMode.SIGNAL
                   else (ExportLayout.XYZ_COLUMNS, ExportLayout.XYZ_ROWS))
        with QtCore.QSignalBlocker(self.export_layout):
            self.export_layout.clear()
            self.export_layout.addItems([choice.value for choice in choices])
            self.export_layout.setCurrentText(previous_layout if previous_layout in choices else choices[0])
        format_ = ExportFormat(self.export_format.currentData())
        storage = ("One MAT file, with one named variable per matrix." if format_ == ExportFormat.MAT
                   else "One XLSX workbook, with one worksheet per matrix." if format_ == ExportFormat.XLSX
                   else "One file per matrix; choose each filename in sequence. Cancel cancels the entire batch.")
        hint = (f"{len(layers)} visible matrices. Current channels, crop, value bounds and XY alignment are applied. "
                "Full-resolution values; camera zoom, 3D height scaling and 3D Z alignment are excluded. "
                "XY gaps remain NaN; nonfinite XYZ points are omitted. "
                f"{storage}")
        if any(layer.frame.composite for layer in layers):
            hint = f"{hint}\nColor views export grayscale values; select a channel to export its values."
        if any((entry := self._entry(layer.uid)) is not None and entry.document.is_complex for layer in layers):
            hint = f"{hint}\nComplex sources export their displayed components here. Choose Selected matrix and Export complex matrix to retain real + imaginary values."
        if sliced:
            hint = f"{hint}\nOnly matrices intersecting the current slice are included."
        image_format = format_ in (ExportFormat.PNG, ExportFormat.BMP)
        if image_format:
            hint = f"{hint}\nPNG/BMP need one real 2D array: choose Selected matrix/channel. Use Export figure for an image of the overlay."
        self.export_hint.setText(hint)
        pending = bool(self._preparing) or self._rebuild.isActive() or not self._export_ready
        self.export_save.setEnabled(bool(layers) and not pending and not self._export_busy and not image_format
                                    and (not sliced or self._profile_selected))

    def _export_stem(self, suggested: str) -> str:
        entry = self._entry()
        if entry is not None and entry.name:
            return default_stem(entry, ExportTarget(self.export_target.currentText()),
                                row=self.profile_direction.currentIndex() == 0, index=self._export_profile_index(),
                                preserve_complex=self.export_complex.isChecked() and not self._export_channel_only(),
                                preserve_channels=self._export_all_channels())
        return suggested

    def _export_figure(self, checked: bool = False, *, preferred: FigureView | None = None) -> None:
        """Open the figure preview without changing selection or numeric exports.

        Args:
            checked: Unused checked state supplied by Qt button/action signals.
            preferred: Canvas requested by a context menu; None uses the active
                main tab. Unavailable choices fall back to the active view.

        Side effects:
            Opens a modal dialog and restores the previous tabs when it closes.
        """
        visible = [entry for entry in self.entries if entry.visible and entry.frame is not None]
        if not visible:
            QtWidgets.QMessageBox.information(self, "No visible data", "Select a matrix or channel before exporting a figure.")
            return
        if self._preparing or self._rebuild.isActive():
            QtWidgets.QMessageBox.information(self, "Data is updating", "Wait for the current matrix update before exporting a figure.")
            return
        mode = family(visible[0].selection.mode)
        profile = self.overlay_profile if self._profile_uses_overlay else self.profile_view
        choices: list[FigureView] = []
        if mode == ViewMode.MATRIX:
            choices.extend((FigureView.IMAGE, FigureView.SURFACE))
        elif mode == ViewMode.POINTS:
            choices.append(FigureView.SURFACE)
        has_curve = bool(self.overlay_profile._series) if self._profile_uses_overlay else profile.values is not None
        if mode != ViewMode.POINTS and has_curve:
            choices.append(FigureView.SIGNAL)
            if profile.tabs.isTabEnabled(1):
                choices.append(FigureView.DERIVATIVE)
        if not choices:
            return
        original_tab = self.tabs.currentIndex()
        original_profile_tab = profile.tabs.currentIndex()
        if mode == ViewMode.SIGNAL:
            initial = FigureView.DERIVATIVE if original_tab == 1 else FigureView.SIGNAL
        else:
            initial = FigureView.SURFACE if original_tab == 1 else choices[0]
        if preferred is not None and preferred in choices:
            initial = preferred
        directory = self._export_directory or visible[0].document.path.parent
        dialog = FigureExportDialog(tuple(choices), initial, self._prepare_figure, directory, self._export_parent())
        try:
            dialog.exec()
            if dialog.saved_path is not None:
                self._export_directory = dialog.saved_path.parent
                self.statusBar().showMessage(f"Figure saved: {dialog.saved_path}")
        finally:
            profile.tabs.setCurrentIndex(original_profile_tab)
            self.tabs.setCurrentIndex(original_tab)
            dialog.deleteLater()

    def _prepare_figure(self, view: FigureView) -> FigureSource:
        """Activate only the requested canvas; lazily calculate a derivative.

        Args:
            view: A view offered by the modal export dialog.

        Returns:
            Painter and full legend names for the currently visible data.

        Raises:
            ValueError: The workspace has no visible, prepared matrices.
            RuntimeError: A requested 3D frame could not be rendered.
        """
        visible = [entry for entry in self.entries if entry.visible and entry.frame is not None]
        if not visible:
            raise ValueError("No visible matrices are ready to export.")
        mode = family(visible[0].selection.mode)
        profile = self.overlay_profile if self._profile_uses_overlay else self.profile_view
        names = tuple(self._channel_label(entry) for entry in visible)
        title = names[0] if len(names) == 1 else f"Overlay: {len(names)} channels"
        stem = figure_stem(title, view)
        legend = tuple((name, entry.color) for name, entry in zip(names, visible)) if len(names) > 1 else ()
        if view in (FigureView.IMAGE, FigureView.SURFACE):
            self.tabs.setCurrentIndex(0 if view == FigureView.IMAGE else 1)
            self._tab_changed()
        else:
            index = 1 if view == FigureView.DERIVATIVE else 0
            # Showing a signal page also resumes the existing derivative cache;
            # a matrix slice keeps the upper plot selected while its page changes.
            if mode == ViewMode.SIGNAL:
                self.tabs.setCurrentIndex(index)
                self._show_signal_tab()
            profile.tabs.setCurrentIndex(index)
            if view == FigureView.DERIVATIVE:
                profile._ensure_derivative()
        # Settle tab/layout and automatic axis sizing before measuring the plot.
        # This is a one-off UI event flush, not a polling timer.
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if view == FigureView.IMAGE:
            return plot_source(view, self.image_view.plot, pyside_graphics_view(self.image_view.graphics),
                               title, stem, legend)
        if view == FigureView.SURFACE:
            if self._surface_dirty:
                raise RuntimeError("The 3D scene is not ready. Open the 3D tab and check its rendering status.")
            return surface_source(self.surface_view.canvas, title, stem, legend,
                                  f"Uses the current 3D mesh / point sampling. {self.surface_view.resolution.text()}")
        pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
        if len(names) == 1:
            title = f"{title} / {profile.title.text()}" if mode == ViewMode.MATRIX else title
        elif mode == ViewMode.MATRIX:
            row = self.profile_direction.currentIndex() == 0
            title = f"{title} / {'Row at Y' if row else 'Column at X'}={self._profile_position():g}"
        stem = figure_stem(title, view)
        if view == FigureView.DERIVATIVE:
            title = f"{title} / Derivative"
        legend = profile.legend_bar.entries
        if not legend:
            legend = ((profile.title.text(), profile.color.name()),)
        source = plot_source(view, pane.plot_item, pane.native_view, title, stem, legend, (pane.crosshair,))
        return replace(source, note="Red derivative dots mark undefined / omitted samples, not zero values."
                       if view == FigureView.DERIVATIVE else "")

    def _save_export(self) -> None:
        if self.export_scope.currentData() == ExportScope.VISIBLE:
            self._save_displayed_export()
            return
        entry = self._entry()
        if self.export_target.currentText() == ExportTarget.SLICE and (self._overlay() or (entry is not None and not entry.visible)):
            self._sync_export_controls()
            if not self.export_save.isEnabled():
                return
        super()._save_export()

    def _save_displayed_export(self) -> None:
        self._sync_export_controls()
        if not self.export_save.isEnabled():
            return
        target = ExportTarget(self.export_target.currentText())
        row = self.profile_direction.currentIndex() == 0
        position = self._profile_position()
        layout = ExportLayout(self.export_layout.currentText())
        snapshots: list[ExportSnapshot] = []
        try:
            for layer in self._visible_export_layers():
                entry = self._entry(layer.uid)
                assert entry is not None
                snapshot = prepare_displayed_export(entry, layer, target, row=row, position=position)
                if snapshot is not None:
                    if layout in (ExportLayout.XY_ROWS, ExportLayout.XYZ_ROWS):
                        snapshot = replace(snapshot, values=snapshot.values.T)
                    snapshots.append(snapshot)
        except (ValueError, MemoryError) as exc:
            QtWidgets.QMessageBox.warning(self._export_parent(), "Cannot export visible matrices", str(exc))
            return
        if not snapshots:
            QtWidgets.QMessageBox.warning(self._export_parent(), "Nothing to export", "No displayed matrix intersects the selected slice.")
            return
        captured = tuple(snapshots)
        format_ = ExportFormat(self.export_format.currentData())
        directory = self._export_directory or (self.document.path.parent if self.document else Path.cwd())
        if format_ in (ExportFormat.MAT, ExportFormat.XLSX):
            stem = f"{captured[0].stem[:100]}_and_{len(captured)-1}_matrices" if len(captured) > 1 else captured[0].stem
            defaults = (directory / f"{stem}.{format_.value}",)
        else:
            defaults = tuple(directory / f"{snapshot.stem}.{format_.value}" for snapshot in captured)
        choices = self._choose_export_files(defaults, format_, "Export visible matrices")
        if choices is None:
            return
        paths = tuple(path for path, _ in choices)
        if not self._confirm_export_destinations(paths):
            return
        self._export_directory = paths[-1].parent
        self._export_busy = True
        self.export_box.setEnabled(False)
        self.statusBar().showMessage(f"Exporting {len(captured)} visible matrices…")
        if format_ == ExportFormat.MAT:
            def write_mat() -> str:
                self._write_payloads(((paths[0], serialize_displayed_mat(captured)),))
                return f"Saved: {paths[0]} | Variables: {', '.join(mat_variable_names(captured))}"
            self._submit(JobKind.EXPORT, write_mat)
        elif format_ == ExportFormat.XLSX:
            def write_excel() -> str:
                data = serialize_excel(tuple((snapshot.stem, snapshot.values) for snapshot in captured))
                self._write_payloads(((paths[0], data),))
                return f"Saved: {paths[0]} | {len(captured)} matrix worksheets"
            self._submit(JobKind.EXPORT, write_excel)
        else:
            outputs = tuple((snapshot.values, path, selected_format)
                            for snapshot, (path, selected_format) in zip(captured, choices, strict=True))
            self._submit(JobKind.EXPORT, lambda: self._write_arrays(outputs))

    def _refresh_surface(self) -> None:
        if self._overlay():
            self._render_workspace()
        else:
            with self._single_view_context():
                if (entry := self._entry()) is not None and entry.visible:
                    super()._refresh_surface()

    def _presentation_changed(self, *, reset: bool = False) -> None:
        if self._overlay():
            if not self._restoring and not self._painting_active:
                self._store_entry()
                self._render_workspace(reset)
        else:
            with self._single_view_context():
                if (entry := self._entry()) is not None and entry.visible:
                    super()._presentation_changed(reset=reset)

    def _height_changed(self) -> None:
        if self._overlay():
            self._sync_height_slider()
            self._store_entry()
            self._render_workspace()
        else:
            with self._single_view_context():
                super()._height_changed()

    def _choose_clip_color(self) -> None:
        super()._choose_clip_color()
        if self._overlay() or ((entry := self._entry()) is not None and not entry.visible):
            self._store_entry()
            self._single_render_key = None
            self._render_workspace()

    def _profile_appearance_changed(self) -> None:
        if self._overlay():
            style = ProfileStyle(self.profile_style.currentText())
            self.profile_style_options.setCurrentIndex(0 if style == ProfileStyle.RAISED_CURVE else 1)
            self.surface_view.profile_style = style
            self.surface_view.profile_color = self._profile_color_3d.name()
            self.surface_view.profile_lift = self.profile_lift.value() / 100
            self.surface_view.section_opacity = self.profile_opacity.value() / 100
            self._render_workspace()
        else:
            with self._single_view_context():
                super()._profile_appearance_changed()

    def _profile_settings_changed(self) -> None:
        if not self._restoring:
            self._store_entry()
            self._render_workspace()

    def _theme_changed(self) -> None:
        super()._theme_changed()
        if self._workspace_ready:
            self.overlay_profile.set_theme(self.theme.currentIndex() == 0)

    def _fit_views(self) -> None:
        if self._overlay():
            self._render_workspace(reset=True)
            self.overlay_profile.reset_view()
        else:
            with self._single_view_context():
                super()._fit_views()
