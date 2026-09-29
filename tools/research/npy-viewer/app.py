"""Qt application coordinating asynchronous data loading and linked views.

Requirements: numpy, opencv-python, matplotlib, PySide6, pyqtgraph,
pyvista, pyvistaqt and vtk. Usage: run the npy-viewer.py launcher.
"""

from collections.abc import Callable
from enum import StrEnum
import math
from pathlib import Path
import sys
from typing import cast

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .data_model import (COLORMAPS, DEFAULT_CLIP_COLOR, IMAGE_EXTENSIONS, Component, Crop, Document, FilterMode, Frame,
                         Limits, Selection, ViewMode, default_selection,
                         load_document, prepare_frame)
from .image_view import ImageView
from .profile_view import ProfileView
from .surface_view import (DEFAULT_PROFILE_COLOR, DEFAULT_PROFILE_LIFT,
                           DEFAULT_SECTION_OPACITY, ProfileStyle, SurfaceView)

DEFAULT_MAX_EDGE = 512
MAX_QT_INDEX = 2_147_483_647
REBUILD_DELAY_MS = 120
HEIGHT_SLIDER_STEPS_PER_DECADE = 100
HEIGHT_MIN_EXPONENT = -9
HEIGHT_MAX_EXPONENT = 9
FILE_FILTER = "Matrices and images (*.npy *.npz *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)"


class JobKind(StrEnum):
    """Independent task generations for disk loading and frame preparation."""

    LOAD = "load"
    FRAME = "frame"


class JobSignals(QtCore.QObject):
    """Deliver worker results to slots on the GUI thread."""

    done = QtCore.Signal(int, str, object)
    failed = QtCore.Signal(int, str, str)


class Job(QtCore.QRunnable):
    """Run one immutable operation with queued result/error signals.

    Args:
        number: Unique generation identifier.
        kind: Load or frame task category.
        work: CPU/file operation; must not access Qt widgets or VTK objects.
    """

    def __init__(self, number: int, kind: JobKind, work: Callable[[], object]) -> None:
        super().__init__()
        self.number, self.kind, self.work = number, kind, work
        self.signals = JobSignals()

    def run(self) -> None:
        """Execute work in the pool and emit a result or readable failure."""
        try:
            result = self.work()
        except Exception as exc:
            self.signals.failed.emit(self.number, self.kind.value, f"{type(exc).__name__}: {exc}")
        else:
            self.signals.done.emit(self.number, self.kind.value, result)


class ViewerWindow(QtWidgets.QMainWindow):
    """A matrix/signal workbench with synchronized source coordinates.

    Args:
        max_edge: Initial 3D edge limit; zero means original resolution.
        initial_mode: Optional CLI interpretation override for the first file.
        initial_channel_axis: Optional CLI channel-axis override.
    """

    def __init__(self, max_edge: int = DEFAULT_MAX_EDGE, initial_mode: str | None = None,
                 initial_channel_axis: int | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Matrix Viewer — NPY / NPZ / Images")
        self.resize(1400, 930)
        self.setMinimumSize(980, 680)
        self.setAcceptDrops(True)
        self.document: Document | None = None
        self.frame: Frame | None = None
        self.frame_selection: Selection | None = None
        self._next_selection: Selection | None = None
        self._initial_mode = ViewMode(initial_mode) if initial_mode else None
        self._initial_channel_axis = initial_channel_axis
        self._updating = False
        self._closing = False
        self._reset_pending = True
        self._surface_dirty = True
        self._surface_reset = True
        self._serial = 0
        self._latest: dict[JobKind, int] = {}
        self._jobs: dict[int, Job] = {}
        self._slice_spins: dict[int, QtWidgets.QSpinBox] = {}
        self._profile_selected = True
        self._crop = Crop()
        self._clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        self._profile_color_2d = QtGui.QColor(DEFAULT_PROFILE_COLOR)
        self._profile_color_3d = QtGui.QColor(DEFAULT_PROFILE_COLOR)
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._rebuild = QtCore.QTimer(self)
        self._rebuild.setSingleShot(True)
        self._rebuild.setInterval(REBUILD_DELAY_MS)
        self._rebuild.timeout.connect(self._request_frame)

        # ── window layout ─────────────────────────────────
        root = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addLayout(self._file_bar())
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.controls = self._controls(max_edge)
        scroll.setWidget(self.controls)
        split.addWidget(scroll)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.vertical = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.tabs = QtWidgets.QTabWidget()
        self.image_view = ImageView()
        self.surface_view = SurfaceView()
        self.tabs.addTab(self.image_view, "2D image")
        self.tabs.addTab(self.surface_view, "3D surface")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.vertical.addWidget(self.tabs)
        profile_area = QtWidgets.QWidget()
        profile_layout = QtWidgets.QVBoxLayout(profile_area)
        profile_layout.setContentsMargins(0, 6, 0, 0)
        self.profile_controls = self._profile_controls()
        profile_layout.addWidget(self.profile_controls)
        self.profile_view = ProfileView()
        profile_layout.addWidget(self.profile_view)
        self.vertical.addWidget(profile_area)
        self.vertical.setSizes([580, 290])
        self.vertical.setChildrenCollapsible(False)
        right_layout.addWidget(self.vertical)
        self.hint = QtWidgets.QLabel(
            "1D wheel: zoom X · Ctrl+wheel: zoom XY · Left drag: pan · "
            "3D middle: orbit · Ctrl+middle: pan · Right / Alt+middle: roll"
        )
        self.hint.setWordWrap(True)
        right_layout.addWidget(self.hint)
        split.addWidget(right)
        split.setSizes([370, 1010])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Open or drop an NPY, NPZ or image file. All indices are zero-based.")
        self.controls.setEnabled(False)
        self.profile_controls.setEnabled(False)
        self._theme_changed()

    def _file_bar(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        button = QtWidgets.QPushButton("Open file…")
        button.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        button.clicked.connect(self._choose_file)
        layout.addWidget(button)
        self.path_label = QtWidgets.QLineEdit()
        self.path_label.setReadOnly(True)
        self.path_label.setPlaceholderText("Drop an NPY, NPZ or image file here")
        layout.addWidget(self.path_label, 1)
        layout.addWidget(QtWidgets.QLabel("NPZ array"))
        self.archive_key = QtWidgets.QComboBox()
        self.archive_key.setMinimumWidth(180)
        self.archive_key.setEnabled(False)
        self.archive_key.currentIndexChanged.connect(self._key_changed)
        layout.addWidget(self.archive_key)
        fit = QtWidgets.QPushButton("Fit views")
        fit.clicked.connect(self._fit_views)
        layout.addWidget(fit)
        return layout

    def _controls(self, max_edge: int) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        self.info = QtWidgets.QLabel("No data loaded")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)
        axes_box = QtWidgets.QGroupBox("Data interpretation")
        form = QtWidgets.QFormLayout(axes_box)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("2D matrix", ViewMode.MATRIX.value)
        self.mode.addItem("1D signal", ViewMode.SIGNAL.value)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("View as", self.mode)
        self.x_axis = QtWidgets.QComboBox()
        self.y_axis = QtWidgets.QComboBox()
        self.channel_axis = QtWidgets.QComboBox()
        form.addRow("Column / sample axis", self.x_axis)
        form.addRow("Row axis", self.y_axis)
        form.addRow("Channel axis", self.channel_axis)
        for combo in (self.x_axis, self.y_axis, self.channel_axis):
            combo.currentIndexChanged.connect(self._axes_changed)
        self.channel = QtWidgets.QSpinBox()
        self.channel.setKeyboardTracking(False)
        self.channel.valueChanged.connect(self._schedule_frame)
        form.addRow("Channel index", self.channel)
        self.component = QtWidgets.QComboBox()
        self.component.addItems([item.value for item in Component])
        self.component.currentIndexChanged.connect(self._schedule_frame)
        form.addRow("Complex component", self.component)
        self.slice_box = QtWidgets.QGroupBox("Other-axis slices")
        self.slice_form = QtWidgets.QFormLayout(self.slice_box)
        layout.addWidget(axes_box)
        layout.addWidget(self.slice_box)
        layout.addWidget(self._crop_controls())

        # ── shared filter and color controls ───────────────
        filter_box = QtWidgets.QGroupBox("Value bounds (inclusive)")
        filters = QtWidgets.QFormLayout(filter_box)
        self.filter_low = QtWidgets.QLineEdit()
        self.filter_high = QtWidgets.QLineEdit()
        self.filter_low.setPlaceholderText("No lower bound")
        self.filter_high.setPlaceholderText("No upper bound")
        filters.addRow("Minimum", self.filter_low)
        filters.addRow("Maximum", self.filter_high)
        self.filter_mode = QtWidgets.QComboBox()
        self.filter_mode.addItems([mode.value for mode in FilterMode])
        self.filter_mode.currentIndexChanged.connect(self._schedule_frame)
        filters.addRow("Outside bounds", self.filter_mode)
        self.clip_color_button = QtWidgets.QPushButton("Clipping color")
        self._set_color_icon(self.clip_color_button, self._clip_color)
        self.clip_color_button.clicked.connect(self._choose_clip_color)
        filters.addRow(self.clip_color_button)
        filter_hint = QtWidgets.QLabel("Clamp: thick cap lines / solid 3D planes. NaN/Inf stay gaps; derivatives omit clipped samples.")
        filter_hint.setWordWrap(True)
        filters.addRow(filter_hint)
        apply_filter = QtWidgets.QPushButton("Apply filter")
        apply_filter.clicked.connect(self._schedule_frame)
        filters.addRow(apply_filter)
        for entry in (self.filter_low, self.filter_high):
            entry.returnPressed.connect(self._schedule_frame)
        layout.addWidget(filter_box)

        display_box = QtWidgets.QGroupBox("Color and appearance")
        display = QtWidgets.QFormLayout(display_box)
        self.colormap = QtWidgets.QComboBox()
        self.colormap.addItems(COLORMAPS)
        self.colormap.currentIndexChanged.connect(self._presentation_changed)
        display.addRow("Colormap", self.colormap)
        self.color_low, self.color_high = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.color_low.setPlaceholderText("Auto minimum")
        self.color_high.setPlaceholderText("Auto maximum")
        display.addRow("Color minimum", self.color_low)
        display.addRow("Color maximum", self.color_high)
        for entry in (self.color_low, self.color_high):
            entry.editingFinished.connect(self._presentation_changed)
        self.theme = QtWidgets.QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentIndex(1)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        display.addRow("Plot background", self.theme)
        reset_limits = QtWidgets.QPushButton("Reset filter / color limits")
        reset_limits.clicked.connect(self._reset_limits)
        display.addRow(reset_limits)
        layout.addWidget(display_box)

        surface_box = QtWidgets.QGroupBox("3D rendering")
        surface = QtWidgets.QFormLayout(surface_box)
        self.max_edge = QtWidgets.QSpinBox()
        self.max_edge.setRange(0, MAX_QT_INDEX)
        self.max_edge.setSingleStep(128)
        self.max_edge.setSpecialValueText("Full resolution")
        self.max_edge.setValue(max_edge)
        self.max_edge.setKeyboardTracking(False)
        self.max_edge.valueChanged.connect(self._schedule_frame)
        surface.addRow("Maximum grid edge", self.max_edge)
        self.auto_height = QtWidgets.QCheckBox("Auto height scale")
        self.auto_height.setChecked(True)
        self.auto_height.toggled.connect(self._auto_height_changed)
        surface.addRow(self.auto_height)
        self.height_scale = QtWidgets.QDoubleSpinBox()
        self.height_scale.setDecimals(9)
        self.height_scale.setRange(10.0 ** HEIGHT_MIN_EXPONENT, 10.0 ** HEIGHT_MAX_EXPONENT)
        self.height_scale.setValue(1)
        self.height_scale.setKeyboardTracking(False)
        self.height_scale.setEnabled(False)
        self.height_scale.valueChanged.connect(self._height_changed)
        surface.addRow("Height multiplier", self.height_scale)
        self.height_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.height_slider.setRange(HEIGHT_MIN_EXPONENT * HEIGHT_SLIDER_STEPS_PER_DECADE,
                                    HEIGHT_MAX_EXPONENT * HEIGHT_SLIDER_STEPS_PER_DECADE)
        self.height_slider.setValue(0)
        self.height_slider.setEnabled(False)
        self.height_slider.setToolTip("Logarithmic height multiplier, synchronized with the numeric value.")
        self.height_slider.valueChanged.connect(self._height_slider_changed)
        surface.addRow(self.height_slider)
        self.parallel = QtWidgets.QCheckBox("Orthographic projection")
        self.parallel.toggled.connect(self._projection_changed)
        surface.addRow(self.parallel)
        hint = QtWidgets.QLabel("Grid size affects 3D rendering only. Profiles and pixel readouts use original data.")
        hint.setWordWrap(True)
        surface.addRow(hint)
        layout.addWidget(surface_box)
        self.surface_controls = surface_box
        layout.addStretch()
        return widget

    def _choose_clip_color(self) -> None:
        color = QtWidgets.QColorDialog.getColor(self._clip_color, self, "Clipping color")
        if color.isValid():
            self._clip_color = color
            self._set_color_icon(self.clip_color_button, color)
            self.image_view.set_clip_color(color)
            self.profile_view.set_clip_color(color)
            self.surface_view.set_clip_color(color.name())

    def _crop_controls(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Crop by source index (inclusive)")
        form = QtWidgets.QFormLayout(box)
        self.crop_x_start, self.crop_x_end = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        self.crop_y_start, self.crop_y_end = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
        for spin in (self.crop_x_start, self.crop_x_end, self.crop_y_start, self.crop_y_end):
            spin.setRange(0, MAX_QT_INDEX)
            spin.setKeyboardTracking(False)
        for label, start, end in (("X range", self.crop_x_start, self.crop_x_end),
                                  ("Y range", self.crop_y_start, self.crop_y_end)):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(start)
            row.addWidget(QtWidgets.QLabel("to"))
            row.addWidget(end)
            form.addRow(label, row)
        self.crop_apply = QtWidgets.QPushButton("Apply crop")
        self.crop_apply.clicked.connect(self._apply_crop)
        self.crop_reset = QtWidgets.QPushButton("Restore full range")
        self.crop_reset.clicked.connect(self._reset_crop)
        form.addRow(self.crop_apply, self.crop_reset)
        self.crop_info = QtWidgets.QLabel("X: columns / samples; Y: rows. Source indices are retained.")
        self.crop_info.setWordWrap(True)
        form.addRow(self.crop_info)
        return box

    def _configure_crop(self) -> None:
        document = self.document
        if document is None:
            return
        x_axis, y_axis = self.x_axis.currentIndex(), self.y_axis.currentIndex()
        if x_axis < 0 or y_axis < 0:
            return
        matrix = self.mode.currentIndex() == 0
        width = document.array.shape[x_axis]
        height = document.array.shape[y_axis] if matrix else 1
        for start, end, extent in ((self.crop_x_start, self.crop_x_end, width),
                                    (self.crop_y_start, self.crop_y_end, height)):
            start.setRange(0, min(extent - 1, MAX_QT_INDEX))
            end.setRange(0, min(extent - 1, MAX_QT_INDEX))
            start.setValue(0)
            end.setValue(min(extent - 1, MAX_QT_INDEX))
        self.crop_y_start.setEnabled(matrix)
        self.crop_y_end.setEnabled(matrix)
        self._crop = Crop()

    def _apply_crop(self) -> None:
        if self.document is None:
            return
        matrix = self.mode.currentIndex() == 0
        x_start, x_end = self.crop_x_start.value(), self.crop_x_end.value()
        y_start, y_end = self.crop_y_start.value(), self.crop_y_end.value()
        if x_start > x_end or (matrix and y_start > y_end):
            self.statusBar().showMessage("Invalid crop: each start index must be no greater than its end index.")
            return
        self._crop = Crop(x_start, x_end, y_start if matrix else 0, y_end if matrix else None)
        self._reset_pending = True
        self._schedule_frame()

    def _reset_crop(self) -> None:
        self._configure_crop()
        self._reset_pending = True
        self._schedule_frame()

    def _profile_controls(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        selector = QtWidgets.QHBoxLayout()
        self.profile_direction = QtWidgets.QComboBox()
        self.profile_direction.addItems(["Row", "Column"])
        self.profile_direction.currentIndexChanged.connect(self._profile_direction_changed)
        self.profile_index = QtWidgets.QSpinBox()
        self.profile_index.setKeyboardTracking(False)
        self.profile_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.profile_index.valueChanged.connect(self.profile_slider.setValue)
        self.profile_slider.valueChanged.connect(self.profile_index.setValue)
        self.profile_index.valueChanged.connect(self._profile_index_changed)
        selector.addWidget(QtWidgets.QLabel("Profile"))
        selector.addWidget(self.profile_direction)
        selector.addWidget(self.profile_index)
        selector.addWidget(self.profile_slider, 1)
        self.profile_toggle = QtWidgets.QPushButton("Clear selection")
        self.profile_toggle.clicked.connect(self._toggle_profile_selection)
        selector.addWidget(self.profile_toggle)
        layout.addLayout(selector)

        # ── independent image/3D marker appearance ──────────
        appearance = QtWidgets.QHBoxLayout()
        self.profile_color_2d_button = QtWidgets.QPushButton("2D color")
        self.profile_color_3d_button = QtWidgets.QPushButton("3D color")
        self._set_color_icon(self.profile_color_2d_button, self._profile_color_2d)
        self._set_color_icon(self.profile_color_3d_button, self._profile_color_3d)
        self.profile_color_2d_button.clicked.connect(self._choose_profile_color_2d)
        self.profile_color_3d_button.clicked.connect(self._choose_profile_color_3d)
        appearance.addWidget(self.profile_color_2d_button)
        appearance.addWidget(self.profile_color_3d_button)
        self.profile_style = QtWidgets.QComboBox()
        self.profile_style.addItems([style.value for style in ProfileStyle])
        self.profile_style.currentIndexChanged.connect(self._profile_appearance_changed)
        appearance.addWidget(self.profile_style)
        self.profile_lift = QtWidgets.QDoubleSpinBox()
        self.profile_lift.setRange(0, 1000)
        self.profile_lift.setDecimals(2)
        self.profile_lift.setValue(DEFAULT_PROFILE_LIFT * 100)
        self.profile_lift.setPrefix("Lift: ")
        self.profile_lift.setSuffix(" %")
        self.profile_lift.setKeyboardTracking(False)
        self.profile_lift.setToolTip("Raise the 3D curve by this percentage of the visible height range. Source values stay unchanged.")
        self.profile_lift.valueChanged.connect(self._profile_appearance_changed)
        self.profile_opacity = QtWidgets.QSpinBox()
        self.profile_opacity.setRange(1, 100)
        self.profile_opacity.setValue(round(DEFAULT_SECTION_OPACITY * 100))
        self.profile_opacity.setPrefix("Opacity: ")
        self.profile_opacity.setSuffix(" %")
        self.profile_opacity.valueChanged.connect(self._profile_appearance_changed)
        self.profile_style_options = QtWidgets.QStackedWidget()
        self.profile_style_options.addWidget(self.profile_lift)
        self.profile_style_options.addWidget(self.profile_opacity)
        self.profile_style_options.setMaximumWidth(165)
        appearance.addWidget(self.profile_style_options)
        appearance.addStretch()
        layout.addLayout(appearance)
        return widget

    @staticmethod
    def _set_color_icon(button: QtWidgets.QPushButton, color: QtGui.QColor) -> None:
        swatch = QtGui.QPixmap(16, 16)
        swatch.fill(color)
        button.setIcon(QtGui.QIcon(swatch))

    def _choose_profile_color_2d(self) -> None:
        color = QtWidgets.QColorDialog.getColor(self._profile_color_2d, self, "2D selection color")
        if color.isValid():
            self._profile_color_2d = color
            self._set_color_icon(self.profile_color_2d_button, color)
            self.image_view.set_profile_color(color)

    def _choose_profile_color_3d(self) -> None:
        color = QtWidgets.QColorDialog.getColor(self._profile_color_3d, self, "3D selection color")
        if color.isValid():
            self._profile_color_3d = color
            self._set_color_icon(self.profile_color_3d_button, color)
            self._profile_appearance_changed()

    def _profile_appearance_changed(self) -> None:
        style = ProfileStyle(self.profile_style.currentText())
        self.profile_style_options.setCurrentIndex(0 if style == ProfileStyle.RAISED_CURVE else 1)
        self.surface_view.set_profile_style(style, self._profile_color_3d.name(),
                                            self.profile_lift.value() / 100,
                                            self.profile_opacity.value() / 100)

    def _toggle_profile_selection(self) -> None:
        self._profile_selected = not self._profile_selected
        self._update_profile()

    def _profile_index_changed(self) -> None:
        self._profile_selected = True
        self._update_profile()

    def open_path(self, path: Path, key: str | None = None) -> None:
        """Load a file asynchronously, leaving the current view intact on failure.

        Args:
            path: NPY, NPZ or image path.
            key: NPZ member name; None selects the first.

        Side effects:
            Starts background I/O, disables data controls and updates status.
        """
        self._rebuild.stop()
        self._latest[JobKind.FRAME] = -1
        self.controls.setEnabled(False)
        self.archive_key.setEnabled(False)
        self.statusBar().showMessage(f"Loading {path.name}…")
        self._submit(JobKind.LOAD, lambda: load_document(path, key))

    def _submit(self, kind: JobKind, work: Callable[[], object]) -> None:
        self._serial += 1
        number = self._serial
        self._latest[kind] = number
        task = Job(number, kind, work)
        task.signals.done.connect(self._job_done)
        task.signals.failed.connect(self._job_failed)
        self._jobs[number] = task
        self._pool.start(task)

    @QtCore.Slot(int, str, object)
    def _job_done(self, number: int, kind_text: str, result: object) -> None:
        self._jobs.pop(number, None)
        kind = JobKind(kind_text)
        if self._closing or self._latest.get(kind) != number:
            return
        if kind == JobKind.LOAD:
            self._document_loaded(cast(Document, result))
        else:
            self.frame = cast(Frame, result)
            self.frame_selection = self._next_selection
            self._show_frame(self._reset_pending)
            self._reset_pending = False

    @QtCore.Slot(int, str, str)
    def _job_failed(self, number: int, kind_text: str, message: str) -> None:
        self._jobs.pop(number, None)
        kind = JobKind(kind_text)
        if self._closing or self._latest.get(kind) != number:
            return
        self.controls.setEnabled(self.document is not None)
        self.archive_key.setEnabled(bool(self.document and self.document.keys))
        if kind == JobKind.LOAD and self.document is not None:
            with QtCore.QSignalBlocker(self.archive_key):
                self.archive_key.setCurrentText(self.document.key or "")
        self.statusBar().showMessage(f"Error: {message}")
        QtWidgets.QMessageBox.warning(self, "Cannot update viewer", message)

    def _document_loaded(self, document: Document) -> None:
        self.document = document
        self._profile_selected = True
        self.frame = None
        self.frame_selection = None
        self._reset_pending = True
        self.path_label.setText(str(document.path))
        self.path_label.setCursorPosition(0)
        self.setWindowTitle(f"{document.path.name} — Matrix Viewer")
        with QtCore.QSignalBlocker(self.archive_key):
            self.archive_key.clear()
            self.archive_key.addItems(list(document.keys))
            self.archive_key.setCurrentText(document.key or "")
        self.archive_key.setEnabled(bool(document.keys))
        self.info.setText(f"Shape: {document.array.shape}\nDtype: {document.array.dtype}\n"
                          f"Size: {document.array.nbytes / (1024 ** 2):,.2f} MiB\nIndices start at 0.")
        try:
            selection = default_selection(document, self._initial_mode, self._initial_channel_axis)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            selection = default_selection(document)
        self._initial_mode = None
        self._initial_channel_axis = None
        self._configure_selection(selection)
        self.controls.setEnabled(True)
        self._request_frame()

    def _configure_selection(self, selection: Selection) -> None:
        document = self.document
        if document is None:
            return
        self._updating = True
        self.mode.setCurrentIndex(0 if selection.mode == ViewMode.MATRIX else 1)
        for combo in (self.x_axis, self.y_axis, self.channel_axis):
            combo.clear()
        self.channel_axis.addItem("None", -1)
        for axis, size in enumerate(document.array.shape):
            label = f"Axis {axis} ({size})"
            for combo in (self.x_axis, self.y_axis, self.channel_axis):
                combo.addItem(label, axis)
        self.x_axis.setCurrentIndex(selection.x_axis)
        self.y_axis.setCurrentIndex(selection.y_axis if selection.y_axis is not None else 0)
        self.channel_axis.setCurrentIndex(0 if selection.channel_axis is None else selection.channel_axis + 1)
        self.y_axis.setEnabled(selection.mode == ViewMode.MATRIX)
        self.component.setEnabled(np.iscomplexobj(document.array))
        self.component.setCurrentText(selection.component.value)
        self._updating = False
        self._refresh_axis_controls()
        with QtCore.QSignalBlocker(self.channel):
            self.channel.setValue(selection.channel)
        self._configure_crop()

    def _mode_changed(self) -> None:
        if self._updating or self.document is None:
            return
        mode = ViewMode.MATRIX if self.mode.currentIndex() == 0 else ViewMode.SIGNAL
        try:
            selection = default_selection(self.document, mode)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(self.mode):
                self.mode.setCurrentIndex(0 if self.frame_selection and self.frame_selection.mode == ViewMode.MATRIX else 1)
            return
        self._configure_selection(selection)
        self._reset_pending = True
        self._schedule_frame()

    def _axes_changed(self) -> None:
        if self._updating:
            return
        self._refresh_axis_controls()
        self._configure_crop()
        self._reset_pending = True
        self._schedule_frame()

    def _refresh_axis_controls(self) -> None:
        if self.document is None:
            return
        shape = self.document.array.shape
        channel_axis = self.channel_axis.currentIndex() - 1
        matrix = self.mode.currentIndex() == 0
        self._updating = True
        self.channel.setEnabled(channel_axis >= 0)
        count = shape[channel_axis] if channel_axis >= 0 else 1
        rgb = matrix and channel_axis >= 0 and count in (3, 4) and not np.iscomplexobj(self.document.array)
        self.channel.setSpecialValueText("RGB / luminance" if rgb else "")
        self.channel.setRange(-1 if rgb else 0, min(count - 1, MAX_QT_INDEX))
        if not rgb and self.channel.value() < 0:
            self.channel.setValue(0)
        previous = {axis: widget.value() for axis, widget in self._slice_spins.items()}
        while self.slice_form.rowCount():
            self.slice_form.removeRow(0)
        self._slice_spins.clear()
        used = {self.x_axis.currentIndex(), channel_axis}
        if matrix:
            used.add(self.y_axis.currentIndex())
        for axis, size in enumerate(shape):
            if axis in used:
                continue
            spin = QtWidgets.QSpinBox()
            spin.setRange(0, min(size - 1, MAX_QT_INDEX))
            spin.setValue(previous.get(axis, 0))
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self._schedule_frame)
            self._slice_spins[axis] = spin
            self.slice_form.addRow(f"Axis {axis}", spin)
        self.slice_box.setVisible(bool(self._slice_spins))
        self._updating = False

    def _selection(self) -> Selection:
        assert self.document is not None
        channel_axis = self.channel_axis.currentIndex() - 1
        matrix = self.mode.currentIndex() == 0
        slices = tuple(self._slice_spins[axis].value() if axis in self._slice_spins else 0
                       for axis in range(self.document.array.ndim))
        return Selection(ViewMode.MATRIX if matrix else ViewMode.SIGNAL,
                         self.x_axis.currentIndex(), self.y_axis.currentIndex() if matrix else None,
                         channel_axis if channel_axis >= 0 else None, self.channel.value(), slices,
                         Component(self.component.currentText()))

    @staticmethod
    def _bound(entry: QtWidgets.QLineEdit) -> float | None:
        text = entry.text().strip()
        if not text:
            return None
        value = float(text)
        if not np.isfinite(value):
            raise ValueError("Bounds must be finite numbers, or blank for automatic limits.")
        return value

    def _schedule_frame(self) -> None:
        if not self._updating and self.document is not None:
            self._latest[JobKind.FRAME] = -1
            self._rebuild.start()

    def _request_frame(self) -> None:
        document = self.document
        if document is None or self._closing:
            return
        try:
            selection = self._selection()
            limits = Limits(self._bound(self.filter_low), self._bound(self.filter_high),
                            FilterMode(self.filter_mode.currentText()))
            # Reject invalid color fields before starting expensive work.
            self._color_levels(self.frame.limits if self.frame else (0, 1))
            axes = [selection.x_axis, selection.y_axis, selection.channel_axis]
            active = [axis for axis in axes if axis is not None]
            if len(set(active)) != len(active):
                raise ValueError("Row, column/sample and channel axes must be different.")
        except ValueError as exc:
            self.statusBar().showMessage(f"Invalid setting: {exc}")
            return
        self._next_selection = selection
        edge = self.max_edge.value()
        crop = self._crop
        self.statusBar().showMessage("Preparing views…")
        self._submit(JobKind.FRAME, lambda: prepare_frame(document, selection, limits, edge, crop))

    def _color_levels(self, automatic: tuple[float, float]) -> tuple[float, float]:
        lower, upper = self._bound(self.color_low), self._bound(self.color_high)
        lower = automatic[0] if lower is None else lower
        upper = automatic[1] if upper is None else upper
        if lower >= upper:
            raise ValueError("Color minimum must be less than color maximum.")
        return lower, upper

    def _show_frame(self, reset: bool) -> None:
        frame, selection = self.frame, self.frame_selection
        if frame is None or selection is None:
            return
        matrix = selection.mode == ViewMode.MATRIX
        self.tabs.setVisible(matrix)
        self.profile_controls.setVisible(matrix)
        self.profile_controls.setEnabled(matrix)
        self.surface_controls.setEnabled(matrix)
        self._surface_dirty = True
        self._surface_reset |= reset
        self._presentation_changed(reset=reset)
        if matrix:
            self._configure_profile_range()
            if reset:
                self.profile_view.reset_view()
        else:
            self.profile_view.set_data(frame.scalar, frame.valid, "Signal", reset, x_start=frame.x_start,
                                       display_values=frame.display_scalar, clipped=frame.clip_kind != 0,
                                       limits=frame.value_limits)
        crop_text = f"X: {frame.x_start}..{frame.x_start + frame.scalar.shape[-1] - 1}"
        if matrix:
            crop_text = f"{crop_text}; Y: {frame.y_start}..{frame.y_start + frame.scalar.shape[0] - 1}"
        self.crop_info.setText(f"Displayed {crop_text}\nShape: {frame.scalar.shape}. Ends included; original indices.")
        visible = int(np.count_nonzero(frame.valid))
        self.statusBar().showMessage(
            f"Ready | Visible samples: {visible:,} / {frame.scalar.size:,}"
            + (f" | Clamped: {np.count_nonzero(frame.clip_kind):,}" if np.any(frame.clip_kind) else "")
            + (" | RGB composition; surface/profile show luminance" if frame.composite else "")
        )

    def _presentation_changed(self, *, reset: bool = False) -> None:
        if self._updating or self.frame is None:
            return
        try:
            levels = self._color_levels(self.frame.limits)
        except ValueError as exc:
            self.statusBar().showMessage(f"Invalid setting: {exc}")
            return
        matrix = self.frame.scalar.ndim == 2
        self._update_height_controls()
        if matrix:
            self.image_view.set_frame(self.frame, self.colormap.currentText(), levels, reset)
            self._surface_dirty = True
            self._surface_reset |= reset
            self._refresh_surface()

    def _update_height_controls(self) -> None:
        automatic = self.auto_height.isChecked()
        self.height_scale.setEnabled(not automatic)
        self.height_slider.setEnabled(not automatic)
        if automatic and self.frame is not None and self.frame.scalar.ndim == 2:
            span = self.frame.limits[1] - self.frame.limits[0]
            value = max(self.frame.scalar.shape) * 0.3 / span
            with QtCore.QSignalBlocker(self.height_scale):
                self.height_scale.setValue(value)
        self._sync_height_slider()

    def _sync_height_slider(self) -> None:
        position = round(math.log10(self.height_scale.value()) * HEIGHT_SLIDER_STEPS_PER_DECADE)
        with QtCore.QSignalBlocker(self.height_slider):
            self.height_slider.setValue(position)

    def _auto_height_changed(self) -> None:
        self._update_height_controls()
        self._height_changed()

    def _height_slider_changed(self, position: int) -> None:
        self.height_scale.setValue(10.0 ** (position / HEIGHT_SLIDER_STEPS_PER_DECADE))

    def _height_changed(self) -> None:
        self._sync_height_slider()
        if self.frame is None or self.frame.scalar.ndim != 2:
            return
        if not self._surface_dirty:
            self.surface_view.set_height_scale(self.height_scale.value())

    def _refresh_surface(self) -> None:
        if self.frame is None or self.frame.scalar.ndim != 2 or self.tabs.currentIndex() != 1:
            return
        if self._surface_dirty:
            try:
                self.surface_view.set_frame(self.frame, self.colormap.currentText(),
                                            self._color_levels(self.frame.limits), self.height_scale.value(),
                                            self._surface_reset)
            except (ValueError, RuntimeError) as exc:
                self.statusBar().showMessage(f"3D rendering error: {exc}")
                return
            self._surface_dirty = False
            self._surface_reset = False
        self._update_profile()

    def _tab_changed(self) -> None:
        self._refresh_surface()

    def _profile_direction_changed(self) -> None:
        self._profile_selected = True
        self._configure_profile_range()

    def _configure_profile_range(self) -> None:
        if self.frame is None or self.frame.scalar.ndim != 2:
            return
        by_row = self.profile_direction.currentIndex() == 0
        extent = self.frame.scalar.shape[0 if by_row else 1]
        start = self.frame.y_start if by_row else self.frame.x_start
        with QtCore.QSignalBlocker(self.profile_index), QtCore.QSignalBlocker(self.profile_slider):
            self.profile_index.setRange(start, min(start + extent - 1, MAX_QT_INDEX))
            self.profile_slider.setRange(start, min(start + extent - 1, MAX_QT_INDEX))
            self.profile_slider.setValue(self.profile_index.value())
        self._update_profile()

    def _update_profile(self) -> None:
        frame = self.frame
        if frame is None or frame.scalar.ndim != 2:
            return
        row = self.profile_direction.currentIndex() == 0
        self.profile_toggle.setText("Clear selection" if self._profile_selected else "Select current")
        if not self._profile_selected:
            self.profile_view.clear_selection()
            self.image_view.set_profile(row, None)
            self.surface_view.set_profile(row, None)
            return
        index = self.profile_index.value()
        local_index = index - (frame.y_start if row else frame.x_start)
        if not 0 <= local_index < frame.scalar.shape[0 if row else 1]:
            return
        values = frame.scalar[local_index, :] if row else frame.scalar[:, local_index]
        valid = frame.valid[local_index, :] if row else frame.valid[:, local_index]
        shown = frame.display_scalar[local_index, :] if row else frame.display_scalar[:, local_index]
        clipped = (frame.clip_kind[local_index, :] if row else frame.clip_kind[:, local_index]) != 0
        self.profile_view.set_data(values, valid, f"{'Row' if row else 'Column'} {index}",
                                    reset=self._reset_pending, x_start=frame.x_start if row else frame.y_start,
                                    display_values=shown, clipped=clipped, limits=frame.value_limits)
        self.image_view.set_profile(row, index)
        if self.tabs.currentIndex() == 1 and not self._surface_dirty:
            self.surface_view.set_profile(row, index)

    def _projection_changed(self) -> None:
        if self.parallel.isChecked():
            self.surface_view.canvas.enable_parallel_projection()
        else:
            self.surface_view.canvas.disable_parallel_projection()
        self.surface_view.canvas.render()

    def _theme_changed(self) -> None:
        dark = self.theme.currentIndex() == 0
        self.image_view.set_theme(dark)
        self.profile_view.set_theme(dark)
        self.surface_view.set_theme(dark)
        self._presentation_changed()

    def _reset_limits(self) -> None:
        for entry in (self.filter_low, self.filter_high, self.color_low, self.color_high):
            entry.clear()
        self._schedule_frame()

    def _fit_views(self) -> None:
        self.image_view.reset_view()
        self.profile_view.reset_view()
        self.surface_view.reset_view()

    def _choose_file(self) -> None:
        start = str(self.document.path.parent) if self.document else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open matrix or image", start, FILE_FILTER)
        if path:
            self.open_path(Path(path))

    def _key_changed(self) -> None:
        if self.document is not None and self.document.keys and self.archive_key.currentIndex() >= 0:
            self.open_path(self.document.path, self.archive_key.currentText())

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept a local numeric/image file dragged into the window.

        Args:
            event: Native Qt drag-enter event.
        """
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS | {".npy", ".npz"}:
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Open the first local file from a drop asynchronously.

        Args:
            event: Native Qt drop event.
        """
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.open_path(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Stop preparation and release VTK before closing the Qt window.

        Args:
            event: Native Qt close event.
        """
        self._closing = True
        self._rebuild.stop()
        self._pool.clear()
        self._pool.waitForDone()
        self.surface_view.shutdown()
        event.accept()


def run(path: Path | None, key: str | None, mode: str | None,
        channel_axis: int | None, max_edge: int) -> int:
    """Create the Qt application and run the viewer until its window closes.

    Args:
        path: Optional initial file.
        key: Optional NPZ member.
        mode: Optional matrix/signal interpretation.
        channel_axis: Optional initial channel axis.
        max_edge: 3D maximum sampling edge; zero means full resolution.

    Returns:
        Qt event-loop exit code.

    Side effects:
        Creates and shows a desktop window; starts asynchronous file loading.
    """
    existing = QtWidgets.QApplication.instance()
    if isinstance(existing, QtWidgets.QApplication):
        application = existing
    else:
        application = QtWidgets.QApplication([sys.argv[0]])
    application.setStyle("Fusion")
    window = ViewerWindow(max_edge, mode, channel_axis)
    window.show()
    if path is not None:
        QtCore.QTimer.singleShot(0, lambda: window.open_path(path, key))
    return application.exec()
