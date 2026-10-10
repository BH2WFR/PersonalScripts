"""Qt application coordinating asynchronous data loading and linked views.

Signal/XY modes use full-height plot, derivative and raw-data tabs in one row.
Matrix modes restore the image/surface viewer above its linked profile.
Optional Inf/-Inf/NaN markers use blue/green/magenta by default in 1D/2D;
1D marker size is adjustable from 0.5 to 20 pixels, defaulting to 3 pixels.
clipping emphasis defaults on and can be disabled without changing bounds.
Slice-index changes automatically fit Y by default; the profile context menu
can disable this to retain Y scale. Manual Fit commands still fit data.
The workspace selects source entries and retains their image channels or complex
components independently. The base window also supports ordinary single views.
Raw-table synchronization is separate from plot selection for workspace browsing.
The workspace Fourier dialog creates complex FFT/IFFT entries with physical
coordinates shared by plots, surface picking, profiles and exports.
The Transform menu also provides 1D Laplace planes (sigma/omega) and inverse
contour reconstruction, retaining sampling metadata in the current session.
Pointwise dB, angle, logarithm and affine conversions create separate matrices.
The modal Export dialog saves originals, processed results or slices as numeric
files, or real 2D matrices as normalized 8-bit PNG/BMP. Export settings stay
outside the left sidebar; save workers report their status inside the dialog.
Workspace bundles reuse the save-file dialog and atomic writer; NPZ is offered
by the workspace bundle menu, not by the single-array export format selector.
Value bounds share one input row and can be reverted independently of XY/color limits.
Complex Phase disables Z/value-bound controls; X/Y cropping remains available.
Fusion keeps native widget painting with 2 px layout padding/vertical gaps and
4 px horizontal gaps; the main content margins are 6 px except 2 px at the top.
Splitter handles are blue, turning amber on hover and orange while dragging.

Requirements: numpy, opencv-python, Pillow, matplotlib, PySide6, pyqtgraph,
pyvista, pyvistaqt, vtk, scipy and h5py. Usage: run the npy-viewer.py launcher.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from enum import StrEnum
import math
from pathlib import Path
import sys
from typing import Protocol, cast

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .coordinates import AxisCoordinates
from .data_model import (COLORMAPS, DEFAULT_CLIP_COLOR, DEFAULT_MAX_POINTS, IMAGE_EXTENSIONS, TEXT_EXTENSIONS, Array, Component, Crop, Document, FilterMode, Frame, ImageMember,
                         Limits, RealArray, Selection, ViewMode, default_selection,
                         is_phase_view, load_document, prepare_frame, select_image_member)
from .excel_io import EXCEL_EXTENSIONS
from .export_dialog import MatrixExportDialog
from .exporting import (ExportFormat, ExportLayout, ExportOptions, ExportTarget,
                        output_paths, prepare_export, serialize_array)
from .image_view import ImageView
from .profile_view import ProfileView
from .raw_view import RawDataView
from .qt_widgets import NoWheelComboBox
from .surface_view import (DEFAULT_POINT_SIZE, DEFAULT_PROFILE_COLOR, DEFAULT_PROFILE_LIFT,
                           DEFAULT_SECTION_OPACITY, ProfileStyle, SurfaceView)
from .value_markers import DEFAULT_MARKER_SIZE, MAX_MARKER_SIZE, MIN_MARKER_SIZE, MarkerStyle, NonfiniteKind

DEFAULT_MAX_EDGE = 512
MAX_QT_INDEX = 2_147_483_647
REBUILD_DELAY_MS = 120
HEIGHT_SLIDER_STEPS_PER_DECADE = 100
HEIGHT_MIN_EXPONENT = -9
HEIGHT_MAX_EXPONENT = 9
DEFAULT_MATRIX_SPLIT: tuple[int, int] = (580, 290)
ARRAY_SELECTOR_CHARACTERS = 12
DISPLAY_SELECTOR_CHARACTERS = 18
CONTENT_MARGIN = 2
VERTICAL_SPACING = 2
HORIZONTAL_SPACING = 4
SPLITTER_COLOR = "#2496ed"
SPLITTER_HOVER_COLOR = "#f5ae27"
SPLITTER_DRAG_COLOR = "#f47721"
WINDOW_MARGINS: tuple[int, int, int, int] = (6, 2, 6, 6)
LAYOUT_MARGIN_METRICS: frozenset[QtWidgets.QStyle.PixelMetric] = frozenset((
    QtWidgets.QStyle.PixelMetric.PM_LayoutLeftMargin,
    QtWidgets.QStyle.PixelMetric.PM_LayoutTopMargin,
    QtWidgets.QStyle.PixelMetric.PM_LayoutRightMargin,
    QtWidgets.QStyle.PixelMetric.PM_LayoutBottomMargin,
))
SIGNAL_HINT = "1D wheel: zoom X · Ctrl+wheel: zoom XY · Left drag: pan"
SURFACE_HINT = "3D middle / Ctrl+left: orbit · Ctrl+middle: pan · Right / Alt+middle: roll"
FILE_FILTER = "Matrices and images (*.npy *.npz *.mat *.xlsx *.xlsm *.xls *.csv *.txt *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;Excel workbooks (*.xlsx *.xlsm *.xls);;MATLAB arrays (*.mat);;Text tables (*.csv *.txt);;All files (*)"


class _StyleOptionFields(Protocol):
    """Native QStyleOption fields omitted by some PySide6 stub versions."""

    state: QtWidgets.QStyle.StateFlag
    rect: QtCore.QRect


class CompactFusionStyle(QtWidgets.QProxyStyle):
    """Use compact Fusion layouts with colored splitter handles.

    Applies to existing and lazily created controls, including group boxes,
    scroll-area content layouts and dialogs. Native title and control sizes
    remain intact; explicitly zero-margin plot layouts retain their settings.
    Only splitter backgrounds use custom colors; other painting stays native.
    """

    def __init__(self) -> None:
        super().__init__("Fusion")

    def pixelMetric(self, metric: QtWidgets.QStyle.PixelMetric,
                    option: QtWidgets.QStyleOption | None = None,
                    widget: QtWidgets.QWidget | None = None) -> int:
        """Return compact layout metrics and delegate other metrics to Fusion.

        Args:
            metric: Requested Qt style measurement.
            option: Optional native control style context.
            widget: Optional widget requesting the measurement.

        Returns:
            Size in logical pixels; Qt handles display scaling.
        """
        if metric in LAYOUT_MARGIN_METRICS:
            return CONTENT_MARGIN
        if metric == QtWidgets.QStyle.PixelMetric.PM_LayoutVerticalSpacing:
            return VERTICAL_SPACING
        if metric == QtWidgets.QStyle.PixelMetric.PM_LayoutHorizontalSpacing:
            return HORIZONTAL_SPACING
        return super().pixelMetric(metric, option, widget)

    def drawControl(self, element: QtWidgets.QStyle.ControlElement,
                    option: QtWidgets.QStyleOption, painter: QtGui.QPainter,
                    widget: QtWidgets.QWidget | None = None) -> None:
        """Highlight splitter handles without changing their native drag behavior.

        Args:
            element: Native control element being painted.
            option: Paint rectangle and current hover/pressed state.
            painter: Active Qt painter for the control.
            widget: Optional control owning the painted element.
        """
        if element == QtWidgets.QStyle.ControlElement.CE_Splitter:
            fields = cast(_StyleOptionFields, option)
            if fields.state & QtWidgets.QStyle.StateFlag.State_Sunken:
                color = SPLITTER_DRAG_COLOR
            elif fields.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
                color = SPLITTER_HOVER_COLOR
            else:
                color = SPLITTER_COLOR
            painter.fillRect(fields.rect, QtGui.QColor(color))
            return
        super().drawControl(element, option, painter, widget)


class JobKind(StrEnum):
    """Independent task generations for disk loading and frame preparation."""

    LOAD = "load"
    FRAME = "frame"
    EXPORT = "export"
    BUNDLE = "bundle"
    INSPECT = "inspect"
    OVERLAY_FRAMES = "overlay_frames"
    FOURIER = "fourier"
    LAPLACE = "laplace"
    COMPLEX_MERGE = "complex_merge"
    DATA_CONVERSION = "data_conversion"


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
        self.setWindowTitle("Matrix Viewer — NPY / NPZ / MAT / CSV / TXT / Images")
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
        self._profile_auto_y = True
        self._layout_mode: ViewMode | None = None
        self._export_busy = False
        self._export_ready = False
        self._export_directory: Path | None = None
        self._matrix_split = list(DEFAULT_MATRIX_SPLIT)
        self._matrix_tab = 0
        self._crop = Crop()
        self._clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        self._nonfinite_colors: dict[NonfiniteKind, QtGui.QColor] = {
            kind: QtGui.QColor(color) for kind, color in MarkerStyle().colors()}
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
        layout.setContentsMargins(*WINDOW_MARGINS)
        self.file_bar = QtWidgets.QWidget(root)
        self.file_bar.setLayout(self._file_bar())
        layout.addWidget(self.file_bar)
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)
        scroll = QtWidgets.QScrollArea()
        self.control_scroll = scroll
        self.main_split = split
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.controls = self._controls(max_edge)
        scroll.setWidget(self.controls)
        split.addWidget(scroll)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(CONTENT_MARGIN, 0, 0, 0)
        self.vertical = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.tabs = QtWidgets.QTabWidget()
        self.image_view = ImageView()
        self.surface_view = SurfaceView()
        self.raw_view = RawDataView()
        self.primary_view = QtWidgets.QStackedWidget()
        self.primary_view.addWidget(self.image_view)
        self.secondary_view = QtWidgets.QStackedWidget()
        self.secondary_view.addWidget(self.surface_view)
        self.tabs.addTab(self.primary_view, "2D image")
        self.tabs.addTab(self.secondary_view, "3D surface")
        self.tabs.addTab(self.raw_view, "Raw data")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.vertical.addWidget(self.tabs)
        profile_area = QtWidgets.QWidget()
        self.profile_area = profile_area
        profile_layout = QtWidgets.QVBoxLayout(profile_area)
        self.profile_layout = profile_layout
        profile_layout.setContentsMargins(0, CONTENT_MARGIN, 0, 0)
        self.profile_controls = self._profile_controls()
        profile_layout.addWidget(self.profile_controls)
        self.profile_view = ProfileView()
        profile_layout.addWidget(self.profile_view)
        self.vertical.addWidget(profile_area)
        self.vertical.setSizes(self._matrix_split)
        self.vertical.setChildrenCollapsible(False)
        right_layout.addWidget(self.vertical)
        self.hint = QtWidgets.QLabel(f"{SIGNAL_HINT} · {SURFACE_HINT}")
        self.hint.setWordWrap(True)
        right_layout.addWidget(self.hint)
        split.addWidget(right)
        split.setSizes([370, 1010])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(root)
        self.export_dialog = MatrixExportDialog(self.export_box, self)
        self.statusBar().messageChanged.connect(self.export_dialog.status.setText)
        self.statusBar().showMessage("Open or drop an NPY, NPZ, MAT, CSV, TXT or image file. All indices are zero-based.")
        self.controls.setEnabled(False)
        self.profile_controls.setEnabled(False)
        self._theme_changed()

    def _file_bar(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        button = self.open_file_button = QtWidgets.QPushButton("Open file…")
        button.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        button.clicked.connect(self._choose_file)
        layout.addWidget(button)
        self.path_label = QtWidgets.QLineEdit()
        self.path_label.setReadOnly(True)
        self.path_label.setPlaceholderText("Drop an NPY, NPZ, MAT, CSV, TXT or image file here")
        layout.addWidget(self.path_label, 1)
        self.archive_label = QtWidgets.QLabel("Array")
        layout.addWidget(self.archive_label)
        self.archive_key = NoWheelComboBox()
        self.archive_key.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.archive_key.setMinimumContentsLength(ARRAY_SELECTOR_CHARACTERS)
        self.archive_key.setEnabled(False)
        self.archive_key.currentIndexChanged.connect(self._key_changed)
        layout.addWidget(self.archive_key)
        self.display_label = QtWidgets.QLabel("Display")
        layout.addWidget(self.display_label)
        self.display_channel = NoWheelComboBox()
        self.display_channel.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.display_channel.setMinimumContentsLength(DISPLAY_SELECTOR_CHARACTERS)
        self.display_channel.setEnabled(False)
        self.display_channel.currentIndexChanged.connect(self._display_channel_changed)
        layout.addWidget(self.display_channel)
        fit = self.fit_views_button = QtWidgets.QPushButton("Fit views")
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
        self.axes_box, self.axes_form = axes_box, form
        self.mode = NoWheelComboBox()
        self.mode.addItem("2D matrix", ViewMode.MATRIX.value)
        self.mode.addItem("1D signal", ViewMode.SIGNAL.value)
        self.mode.addItem("1D XY", ViewMode.XY.value)
        self.mode.addItem("3D point cloud", ViewMode.POINTS.value)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("View as", self.mode)
        self.x_axis = NoWheelComboBox()
        self.y_axis = NoWheelComboBox()
        self.channel_axis = NoWheelComboBox()
        form.addRow("Column / sample axis", self.x_axis)
        form.addRow("Row axis", self.y_axis)
        form.addRow("Channel axis", self.channel_axis)
        for combo in (self.x_axis, self.y_axis, self.channel_axis):
            combo.currentIndexChanged.connect(self._axes_changed)
        self.channel = QtWidgets.QSpinBox()
        self.channel.setKeyboardTracking(False)
        self.channel.valueChanged.connect(self._schedule_frame)
        form.addRow("Channel index", self.channel)
        self.slice_box = QtWidgets.QGroupBox("Other-axis slices")
        self.slice_form = QtWidgets.QFormLayout(self.slice_box)
        layout.addWidget(axes_box)
        layout.addWidget(self.slice_box)
        self.coordinate_box = QtWidgets.QGroupBox("Coordinate layout")
        coordinate_form = QtWidgets.QFormLayout(self.coordinate_box)
        self.coordinate_axis = NoWheelComboBox()
        self.coordinate_axis.currentIndexChanged.connect(self._coordinate_layout_changed)
        coordinate_form.addRow("Coordinates stored in", self.coordinate_axis)
        self.coordinate_columns: list[QtWidgets.QComboBox] = []
        self.coordinate_labels: list[QtWidgets.QLabel] = []
        for name in ("X", "Y", "Z"):
            combo = NoWheelComboBox()
            combo.currentIndexChanged.connect(self._schedule_frame)
            label = QtWidgets.QLabel(name)
            coordinate_form.addRow(label, combo)
            self.coordinate_columns.append(combo)
            self.coordinate_labels.append(label)
        swap = QtWidgets.QPushButton("Swap X / Y")
        swap.clicked.connect(self._swap_coordinates)
        coordinate_form.addRow(swap)
        self.coordinate_box.hide()
        layout.addWidget(self.coordinate_box)
        layout.addWidget(self._crop_controls())

        # ── shared filter and color controls ───────────────
        filter_box = QtWidgets.QGroupBox("Crop by value bounds")
        filter_box.setToolTip("Minimum and maximum are inclusive. Empty fields leave the corresponding bound open.")
        filters = QtWidgets.QFormLayout(filter_box)
        self.filter_low = QtWidgets.QLineEdit()
        self.filter_high = QtWidgets.QLineEdit()
        self.filter_low.setPlaceholderText("No lower bound")
        self.filter_high.setPlaceholderText("No upper bound")
        bounds_row = QtWidgets.QHBoxLayout()
        bounds_row.addWidget(QtWidgets.QLabel("Minimum"))
        bounds_row.addWidget(self.filter_low, 1)
        bounds_row.addWidget(QtWidgets.QLabel("Maximum"))
        bounds_row.addWidget(self.filter_high, 1)
        filters.addRow(bounds_row)
        self.filter_mode = NoWheelComboBox()
        self.filter_mode.addItems([mode.value for mode in FilterMode])
        self.filter_mode.currentIndexChanged.connect(self._schedule_frame)
        filters.addRow("Outside bounds", self.filter_mode)
        self.clip_color_button = QtWidgets.QPushButton("Clipping color")
        self._set_color_icon(self.clip_color_button, self._clip_color)
        self.clip_color_button.clicked.connect(self._choose_clip_color)
        self.highlight_clipped = QtWidgets.QCheckBox("Highlight clipped values")
        self.highlight_clipped.setChecked(True)
        self.highlight_clipped.setToolTip("Emphasize clamped samples in 1D, 2D and 3D. Turning this off keeps value clamping active.")
        self.highlight_clipped.toggled.connect(self._markers_changed)
        highlight_row = QtWidgets.QHBoxLayout()
        highlight_row.addWidget(self.highlight_clipped)
        highlight_row.addWidget(self.clip_color_button)
        filters.addRow(highlight_row)
        self.show_nonfinite = QtWidgets.QCheckBox("Show Inf / -Inf / NaN markers (1D / 2D)")
        self.show_nonfinite.setToolTip(
            "1D: Inf at the visible finite maximum, -Inf at the minimum, NaN at zero. "
            "No finite samples: use zero. 2D: color the original pixel. Source values and derivatives are unchanged."
        )
        self.show_nonfinite.toggled.connect(self._markers_changed)
        filters.addRow(self.show_nonfinite)
        self.nonfinite_color_row = QtWidgets.QWidget()
        nonfinite_colors = QtWidgets.QHBoxLayout(self.nonfinite_color_row)
        nonfinite_colors.setContentsMargins(0, 0, 0, 0)
        self.nonfinite_color_buttons: dict[NonfiniteKind, QtWidgets.QPushButton] = {}
        for kind, color in self._nonfinite_colors.items():
            button = QtWidgets.QPushButton(f"{kind.value} color")
            self._set_color_icon(button, color)
            button.clicked.connect(lambda _checked=False, selected=kind: self._choose_nonfinite_color(selected))
            nonfinite_colors.addWidget(button)
            self.nonfinite_color_buttons[kind] = button
        self.nonfinite_color_row.setEnabled(False)
        filters.addRow(self.nonfinite_color_row)
        self.nonfinite_size = QtWidgets.QDoubleSpinBox()
        self.nonfinite_size.setRange(MIN_MARKER_SIZE, MAX_MARKER_SIZE)
        self.nonfinite_size.setDecimals(1)
        self.nonfinite_size.setSingleStep(0.5)
        self.nonfinite_size.setValue(DEFAULT_MARKER_SIZE)
        self.nonfinite_size.setSuffix(" px")
        self.nonfinite_size.setKeyboardTracking(False)
        self.nonfinite_size.setEnabled(False)
        self.nonfinite_size.setToolTip("Inf / -Inf / NaN dot diameter in 1D plots, including slices. 2D retains whole-pixel coloring.")
        self.nonfinite_size.valueChanged.connect(self._markers_changed)
        filters.addRow("1D nonfinite marker size", self.nonfinite_size)
        filter_hint = QtWidgets.QLabel("Clamp retains boundary values. Highlighting is optional; nonfinite and clipped samples stay excluded from derivatives.")
        self.filter_hint = filter_hint
        filter_hint.setWordWrap(True)
        filters.addRow(filter_hint)
        apply_filter = QtWidgets.QPushButton("Apply")
        self.apply_value_bounds = apply_filter
        apply_filter.clicked.connect(self._schedule_frame)
        self.revert_value_bounds = QtWidgets.QPushButton("Revert")
        self.revert_value_bounds.setToolTip("Clear minimum and maximum and restore values within the current X/Y crop.")
        self.revert_value_bounds.clicked.connect(self._reset_value_bounds)
        bounds_buttons = QtWidgets.QHBoxLayout()
        bounds_buttons.addWidget(apply_filter)
        bounds_buttons.addWidget(self.revert_value_bounds)
        filters.addRow(bounds_buttons)
        for entry in (self.filter_low, self.filter_high):
            entry.returnPressed.connect(self._schedule_frame)
        layout.addWidget(filter_box)
        self._export_controls()

        display_box = QtWidgets.QGroupBox("Color and appearance")
        display = QtWidgets.QFormLayout(display_box)
        self.display_box, self.display_form = display_box, display
        self.db_floor = QtWidgets.QDoubleSpinBox()
        self.db_floor.setRange(-600, -1)
        self.db_floor.setValue(-120)
        self.db_floor.setSuffix(" dB")
        self.db_floor.setKeyboardTracking(False)
        self.db_floor.setToolTip("Magnitude relative to the selected region's peak (0 dB). Source complex values are unchanged.")
        self.db_floor.valueChanged.connect(self._schedule_frame)
        display.addRow("Magnitude floor", self.db_floor)
        display.setRowVisible(self.db_floor, False)
        self.colormap = NoWheelComboBox()
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
        self.theme = NoWheelComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentIndex(1)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        display.addRow("Plot background", self.theme)
        reset_limits = QtWidgets.QPushButton("Reset filter / color limits")
        self.reset_limits_button = reset_limits
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
        self.max_points = QtWidgets.QSpinBox()
        self.max_points.setRange(0, MAX_QT_INDEX)
        self.max_points.setSpecialValueText("All points")
        self.max_points.setValue(DEFAULT_MAX_POINTS)
        self.max_points.setKeyboardTracking(False)
        self.max_points.valueChanged.connect(self._schedule_frame)
        surface.addRow("Maximum cloud points", self.max_points)
        self.point_size = QtWidgets.QDoubleSpinBox()
        self.point_size.setRange(1, 32)
        self.point_size.setValue(DEFAULT_POINT_SIZE)
        self.point_size.valueChanged.connect(self._presentation_changed)
        surface.addRow("Point size (pixels)", self.point_size)
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

    def _marker_style(self) -> MarkerStyle:
        return MarkerStyle(self.show_nonfinite.isChecked(), self.highlight_clipped.isChecked(),
                           self._nonfinite_colors[NonfiniteKind.POSITIVE].name(),
                           self._nonfinite_colors[NonfiniteKind.NEGATIVE].name(),
                           self._nonfinite_colors[NonfiniteKind.NAN].name(), self.nonfinite_size.value())

    def _sync_marker_controls(self) -> None:
        cloud = self.mode.currentData() == ViewMode.POINTS.value
        phase = (self.document is not None and self.document.is_complex
                 and self.display_channel.currentData() == Component.PHASE)
        for widget in (self.filter_low, self.filter_high, self.filter_mode, self.apply_value_bounds,
                       self.revert_value_bounds, self.highlight_clipped):
            widget.setEnabled(not phase)
        self.filter_hint.setText("Phase does not use Z/value bounds. X/Y cropping remains available." if phase else
                                "Clamp retains boundary values. Highlighting is optional; nonfinite and clipped samples stay excluded from derivatives.")
        self.show_nonfinite.setEnabled(not cloud)
        self.nonfinite_color_row.setEnabled(self.show_nonfinite.isChecked() and not cloud)
        self.nonfinite_size.setEnabled(self.show_nonfinite.isChecked() and not cloud)
        self.clip_color_button.setEnabled(self.highlight_clipped.isChecked() and not phase)

    def _choose_nonfinite_color(self, kind: NonfiniteKind) -> None:
        color = QtWidgets.QColorDialog.getColor(self._nonfinite_colors[kind], self, f"{kind.value} marker color")
        if color.isValid():
            self._nonfinite_colors[kind] = color
            self._set_color_icon(self.nonfinite_color_buttons[kind], color)
            self._markers_changed()

    def _markers_changed(self) -> None:
        """Apply appearance options without rebuilding samples or derivatives."""
        self._sync_marker_controls()
        style = self._marker_style()
        self.image_view.set_marker_style(style)
        self.profile_view.set_marker_style(style)
        if self.surface_view.highlight_clipped != style.highlight_clipped:
            self._surface_dirty = True
            self._refresh_surface()

    def _crop_controls(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Crop by source index (inclusive)")
        form = QtWidgets.QFormLayout(box)
        self.crop_form = form
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

    def _export_controls(self) -> QtWidgets.QGroupBox:
        """Build the single export entry point, using the applied viewer settings."""
        self.export_box = QtWidgets.QGroupBox("Export")
        self.export_form = QtWidgets.QFormLayout(self.export_box)
        self.export_target = NoWheelComboBox()
        self.export_target.addItems([target.value for target in ExportTarget])
        self.export_form.addRow("Data", self.export_target)
        self.export_xy = QtWidgets.QCheckBox("Apply X / Y crop")
        self.export_xy.setChecked(True)
        self.export_form.addRow(self.export_xy)
        self.export_z = QtWidgets.QCheckBox("Apply value bounds (Z / signal Y)")
        self.export_z.setChecked(True)
        self.export_form.addRow(self.export_z)
        self.export_complex = QtWidgets.QCheckBox("Export complex matrix (real + imaginary)")
        self.export_complex.setChecked(True)
        self.export_complex.setToolTip("Checked: preserve both source components, with optional XY crop/slice. Unchecked: export only the displayed component. Ordered value bounds require a real display component.")
        self.export_form.addRow(self.export_complex)
        self.export_complex.hide()
        self.export_layout = NoWheelComboBox()
        self.export_form.addRow("Layout", self.export_layout)
        self.export_format = NoWheelComboBox()
        for format_ in ExportFormat:
            if format_ != ExportFormat.NPZ:
                self.export_format.addItem(format_.value.upper(), format_.value)
        self.export_form.addRow("Format", self.export_format)
        self.export_hint = QtWidgets.QLabel()
        self.export_hint.setWordWrap(True)
        self.export_form.addRow(self.export_hint)
        self.export_save = QtWidgets.QPushButton("Export…")
        self.export_save.clicked.connect(self._save_export)
        self.export_form.addRow(self.export_save)
        self.export_target.currentIndexChanged.connect(self._sync_export_controls)
        self.export_format.currentIndexChanged.connect(self._sync_export_controls)
        self.export_layout.currentIndexChanged.connect(self._sync_export_controls)
        self.export_complex.toggled.connect(self._sync_export_controls)
        self.export_box.setEnabled(False)
        return self.export_box

    def _sync_export_controls(self) -> None:
        """Offer slice and coordinate layouts only for compatible current data."""
        document, frame, selection = self.document, self.frame, self.frame_selection
        if document is None or frame is None or selection is None:
            self.export_save.setEnabled(False)
            return
        matrix = selection.mode == ViewMode.MATRIX
        channel_only = self._export_channel_only()
        all_channels = self._export_all_channels()
        previous = self.export_target.currentText()
        targets = [ExportTarget.RESULT] if channel_only else [ExportTarget.RESULT, ExportTarget.ORIGINAL]
        if matrix:
            targets.insert(1, ExportTarget.SLICE)
        with QtCore.QSignalBlocker(self.export_target):
            self.export_target.clear()
            self.export_target.addItems([target.value for target in targets])
            self.export_target.setCurrentText(previous if previous in targets else ExportTarget.RESULT.value)
        target = ExportTarget(self.export_target.currentText())
        original = target == ExportTarget.ORIGINAL
        all_channels = all_channels and target != ExportTarget.SLICE
        complex_input = document.is_complex
        keep_complex = complex_input and not channel_only and (original or all_channels or self.export_complex.isChecked())
        self.export_xy.setEnabled(not original)
        self.export_z.setEnabled(not original and not keep_complex)
        self.export_form.setRowVisible(self.export_complex, complex_input and not original and not channel_only and not all_channels)
        self.export_xy.setText("Apply X / Y crop" if matrix else "Apply sample-index crop")
        choices = [ExportLayout.ARRAY]
        shape = ((document.image_source.pixels.shape if document.image_source is not None else document.array.shape)
                 if all_channels else document.array.shape if original else frame.scalar.shape)
        complex_source = keep_complex
        signal = (len(shape) == 1 if original else
                  target == ExportTarget.SLICE or selection.mode in (ViewMode.SIGNAL, ViewMode.XY))
        if not complex_source and not all_channels:
            if signal:
                choices.extend((ExportLayout.XY_COLUMNS, ExportLayout.XY_ROWS))
            elif (len(shape) == 2 if original else matrix or selection.mode == ViewMode.POINTS):
                choices.extend((ExportLayout.XYZ_COLUMNS, ExportLayout.XYZ_ROWS))
        previous_layout = self.export_layout.currentText()
        with QtCore.QSignalBlocker(self.export_layout):
            self.export_layout.clear()
            self.export_layout.addItems([layout.value for layout in choices])
            self.export_layout.setCurrentText(previous_layout if previous_layout in choices else ExportLayout.ARRAY.value)
        format_ = ExportFormat(self.export_format.currentData())
        text_format = format_ in (ExportFormat.CSV, ExportFormat.TXT)
        image_format = format_ in (ExportFormat.PNG, ExportFormat.BMP)
        supported = not (len(shape) > 2
                         and (text_format or format_ == ExportFormat.XLSX))
        hint = ("Original source values; ignores crop and bounds. Array layout keeps the source shape."
                if original else "Full resolution, current displayed component. Bounds use the applied Clamp / Hide mode; gaps become NaN.")
        if all_channels:
            hint = ("All source channels, preserving their original order and axes."
                    " Crop applies to the spatial/sample axes; value bounds apply independently to every channel."
                    if not original else "All original source channels; ignores crop and bounds.")
        elif frame.composite and not original:
            hint = f"{hint}\nColor views export grayscale. Select an individual image channel to export it."
        if keep_complex and not original:
            hint = "Full-resolution complex values, with optional XY crop. Value bounds are not applied."
        if complex_input:
            hint = f"{hint}\n" + ("Complex source detected: NPY / MAT retain both real and imaginary parts in one matrix." if keep_complex else
                                    f"Exports {selection.component.value}; choose Selected matrix to preserve complex source values.")
        if complex_source and text_format:
            hint = f"{hint}\nCreates two files: *_real.{format_.value} and *_imag.{format_.value}."
        if complex_source and format_ == ExportFormat.XLSX:
            hint = f"{hint}\nOne workbook with matrix_real and matrix_imag worksheets."
        if not supported:
            hint = f"{hint}\nText / Excel support 1D/2D only. Select an image channel or use NPY / MAT."
        if self.export_layout.currentText() in (ExportLayout.XYZ_COLUMNS, ExportLayout.XYZ_ROWS):
            hint = f"{hint}\nXYZ = source column, row, value. Nonfinite points are omitted."
        if format_ == ExportFormat.MAT:
            hint = f"{hint}\nMAT variable: matrix. 1D arrays are saved as column vectors."
        if format_ == ExportFormat.XLSX:
            hint = f"{hint}\n1D arrays become columns. Large integers and NaN/Inf use numeric text to preserve values."
        if image_format:
            supported = matrix and target != ExportTarget.SLICE and len(shape) == 2 and not keep_complex and self.export_layout.currentText() == ExportLayout.ARRAY
            hint = f"{hint}\nPNG/BMP: 8-bit grayscale, finite min/max normalized to 0/255 after crop/bounds. Constant values and NaN/Inf are black. One source cell per pixel; no axes or colormap."
            if not supported:
                hint = f"{hint}\nRequires a real 2D array in Array layout. Select a scalar channel for multichannel/complex data. For plots or overlays, use Export figure."
        self.export_hint.setText(hint)
        self.export_save.setEnabled(supported and not self._export_busy
                                    and (target != ExportTarget.SLICE or self._profile_selected))

    def _export_channel_only(self) -> bool:
        """Return whether the workspace explicitly requested its current channel."""
        return False

    def _export_all_channels(self) -> bool:
        """Return whether the workspace requested all stored source channels."""
        return False

    def _export_parent(self) -> QtWidgets.QWidget:
        """Parent save dialogs to the visible modal export window, if any."""
        return self.export_dialog if self.export_dialog.isVisible() else self

    def _configure_crop(self) -> None:
        document = self.document
        if document is None:
            return
        x_axis, y_axis = self.x_axis.currentIndex(), self.y_axis.currentIndex()
        if self.mode.currentData() in (ViewMode.XY.value, ViewMode.POINTS.value):
            axis = self.coordinate_axis.currentData()
            if axis is None:
                return
            x_axis = 1 - int(axis)
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
        self.crop_form.setRowVisible(1, matrix)
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
        self.profile_direction = NoWheelComboBox()
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
        self.profile_style = NoWheelComboBox()
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
        # Apply the Y fitting preference before replacing samples so disabling
        # automatic fitting preserves the previous slice's scale.
        self._set_profile_auto_y(self._profile_auto_y)
        self._profile_selected = True
        self._update_profile()

    def _set_profile_auto_y(self, enabled: bool) -> None:
        """Choose whether slice movements refit Y; X zoom is unaffected."""
        self._profile_auto_y = enabled
        self.profile_view.set_y_auto_range(enabled)

    def _export_profile_index(self) -> int:
        """Return the selected source index, independently of display alignment."""
        return self.profile_index.value()

    def _export_stem(self, suggested: str) -> str:
        """Allow the workspace to include a session alias in the default name."""
        return suggested

    def _save_export(self) -> None:
        """Capture export choices, confirm actual destinations, and save in a worker.

        Each file is staged with QSaveFile before replacement. Complex text has
        two actual destinations, both included in the overwrite confirmation.
        Cancelling the dialog writes nothing. Errors are reported by the job.
        """
        document, frame, selection = self.document, self.frame, self.frame_selection
        if document is None or frame is None or selection is None or self._export_busy or not self._export_ready:
            return
        self._sync_export_controls()
        if not self.export_save.isEnabled():
            return
        target = ExportTarget(self.export_target.currentText())
        all_channels = self._export_all_channels() and target != ExportTarget.SLICE
        options = ExportOptions(target,
                                ExportLayout(self.export_layout.currentText()),
                                self.export_xy.isChecked(), self.export_z.isChecked() and self.export_z.isEnabled(),
                                self.profile_direction.currentIndex() == 0, self._export_profile_index(),
                                not self._export_channel_only() and (self.export_complex.isChecked() or all_channels),
                                all_channels)
        if options.target == ExportTarget.SLICE and not self._profile_selected:
            return
        try:
            snapshot = prepare_export(document, selection, frame, options)
            snapshot = replace(snapshot, stem=self._export_stem(snapshot.stem))
        except (ValueError, MemoryError) as exc:
            QtWidgets.QMessageBox.warning(self._export_parent(), "Cannot export array", str(exc))
            return
        format_ = ExportFormat(self.export_format.currentData())
        directory = self._export_directory or document.path.parent
        default_path = directory / f"{snapshot.stem}.{format_.value}"
        # Avoid suggesting a name that already exists, including split text files.
        suffix = 2
        while any(path.exists() for path in output_paths(default_path, snapshot.values, format_)):
            default_path = directory / f"{snapshot.stem}_{suffix}.{format_.value}"
            suffix += 1
        defaults = output_paths(default_path, snapshot.values, format_)
        choices = self._choose_export_files(defaults, format_, "Export array")
        if choices is None:
            return
        destinations = tuple(path for path, _ in choices)
        if not self._confirm_export_destinations(destinations):
            return
        self._export_directory = destinations[-1].parent
        self._export_busy = True
        self.export_box.setEnabled(False)
        self.statusBar().showMessage(f"Exporting {snapshot.values.shape} as {format_.value.upper()}…")
        arrays = (snapshot.values.real, snapshot.values.imag) if len(choices) == 2 else (snapshot.values,)
        outputs = tuple((array, path, selected_format)
                        for array, (path, selected_format) in zip(arrays, choices, strict=True))
        self._submit(JobKind.EXPORT, lambda: self._write_arrays(outputs))

    def _choose_export_files(self, defaults: tuple[Path, ...], format_: ExportFormat,
                             title: str) -> tuple[tuple[Path, ExportFormat], ...] | None:
        """Collect distinct destinations sequentially; cancellation cancels the batch.

        Each proposed name avoids existing files and earlier choices. No writes
        occur here. CSV/TXT extensions may be selected independently per file.
        """
        choices: list[tuple[Path, ExportFormat]] = []
        reserved: set[Path] = set()
        directory = defaults[0].parent if defaults else Path.cwd()
        for index, default in enumerate(defaults):
            proposal = directory / default.name
            suffix = 2
            while proposal.exists() or proposal.resolve() in reserved:
                proposal = directory / f"{default.stem}_{suffix}{default.suffix}"
                suffix += 1
            while True:
                chosen = self._choose_export_destination(proposal, format_, f"{title} ({index + 1}/{len(defaults)}) — {default.stem}")
                if chosen is None:
                    return None
                path, selected_format = chosen
                resolved = path.resolve()
                if resolved not in reserved:
                    break
                QtWidgets.QMessageBox.warning(self._export_parent(), "Duplicate export path", "Each matrix needs a different output filename.")
            reserved.add(resolved)
            choices.append((path, selected_format))
            directory = path.parent
        return tuple(choices)

    def _choose_export_destination(self, default_path: Path, format_: ExportFormat,
                                   title: str) -> tuple[Path, ExportFormat] | None:
        """Ask for one filename; cancellation or an invalid extension writes nothing."""
        dialog = QtWidgets.QFileDialog(self._export_parent(), title, str(default_path),
                                      f"{format_.value.upper()} files (*.{format_.value})")
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        dialog.setDefaultSuffix(format_.value)
        dialog.setOption(QtWidgets.QFileDialog.Option.DontConfirmOverwrite, True)
        accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        paths = dialog.selectedFiles() if accepted else []
        dialog.deleteLater()
        if not paths:
            return None
        target = Path(paths[0])
        # CSV/TXT are interchangeable text extensions; other mismatches are explicit.
        if target.suffix.lower() in (".csv", ".txt") and format_ in (ExportFormat.CSV, ExportFormat.TXT):
            format_ = ExportFormat(target.suffix.lower()[1:])
        elif target.suffix.lower() != f".{format_.value}":
            QtWidgets.QMessageBox.warning(self._export_parent(), "Cannot export array",
                                          f"Choose a .{format_.value} filename or change the export format.")
            return None
        return target, format_

    def _confirm_export_destinations(self, destinations: tuple[Path, ...]) -> bool:
        """Confirm every existing destination together before staging any files."""
        existing = [str(path) for path in destinations if path.exists()]
        if existing:
            message = "Replace the following files?\n\n" + "\n".join(existing)
            answer = QtWidgets.QMessageBox.question(self._export_parent(), "Confirm overwrite", message,
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No)
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return False
        return True

    @staticmethod
    def _write_export(values: Array, destinations: tuple[Path, ...], format_: ExportFormat) -> str:
        """Stage all outputs before committing, reporting any partial commit precisely.

        Args:
            values: Owned numeric snapshot.
            destinations: Confirmed single output or real/imaginary pair.
            format_: Serialization format, consistent with destination suffixes.

        Returns:
            Success message including paths, shape and dtype.

        Raises:
            OSError: Staging/commit failure; already committed paths are listed.
            ValueError: The selected format cannot represent this array.
        """
        arrays = (values.real, values.imag) if len(destinations) == 2 else (values,)
        return ViewerWindow._write_arrays(tuple((array, path, format_)
                                               for path, array in zip(destinations, arrays, strict=True)))

    @staticmethod
    def _write_arrays(outputs: tuple[tuple[Array, Path, ExportFormat], ...]) -> str:
        """Write already-confirmed arrays, allowing CSV/TXT choices per destination."""
        ViewerWindow._write_payloads((path, serialize_array(array, format_)) for array, path, format_ in outputs)
        saved = ", ".join(f"{path} [{array.shape}, {array.dtype}]" for array, path, _ in outputs)
        return f"Saved: {saved}"

    @staticmethod
    def _write_payloads(payloads: Iterable[tuple[Path, bytes]]) -> None:
        """Stage all files before committing and report any partial commit.

        Args:
            payloads: Lazily serialized destinations and complete file contents.

        Raises:
            OSError: Staging or commit failure; already committed paths are listed.
            ValueError: A serializer rejected the requested format.

        Side effects:
            Replaces the previously confirmed destination files on success.
        """
        staged: list[QtCore.QSaveFile] = []
        destinations: list[Path] = []
        committed: list[Path] = []
        try:
            for path, payload in payloads:
                destinations.append(path)
                output = QtCore.QSaveFile(str(path))
                staged.append(output)
                if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError(f"{path}: {output.errorString()}")
                if output.write(payload) != len(payload):
                    raise OSError(f"{path}: {output.errorString()}")
            for path, output in zip(destinations, staged, strict=True):
                if not output.commit():
                    raise OSError(f"{path}: {output.errorString()}")
                committed.append(path)
        except Exception as exc:
            for output in staged:
                output.cancelWriting()
            if committed:
                saved = ", ".join(str(path) for path in committed)
                raise OSError(f"Export incomplete. Already saved: {saved}. Failure: {exc}") from exc
            raise

    def open_path(self, path: Path, key: str | None = None) -> None:
        """Load a file asynchronously, leaving the current view intact on failure.

        Args:
            path: NPY, NPZ, MAT, CSV/TXT or image path.
            key: NPZ member, MAT variable or image matrix; None selects the default.

        Side effects:
            Starts background I/O, disables data controls and updates status.
        """
        self._rebuild.stop()
        self._export_ready = False
        self._latest[JobKind.FRAME] = -1
        self.controls.setEnabled(False)
        self.archive_key.setEnabled(False)
        self.display_channel.setEnabled(False)
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
        if kind == JobKind.EXPORT:
            self._export_busy = False
            self.export_box.setEnabled(self._export_ready)
            self._sync_export_controls()
            self.statusBar().showMessage(str(result))
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
        if kind == JobKind.EXPORT:
            self._export_busy = False
            self.export_box.setEnabled(self._export_ready)
            self._sync_export_controls()
            self.statusBar().showMessage(f"Export failed: {message}")
            QtWidgets.QMessageBox.warning(self._export_parent(), "Cannot export array", message)
            return
        self.controls.setEnabled(self.document is not None)
        if kind == JobKind.LOAD:
            self._sync_source_selectors(self.frame_selection.component if self.frame_selection else Component.REAL)
            self._export_ready = self.frame is not None
            self.export_box.setEnabled(self._export_ready and not self._export_busy)
            print(f"[Viewer] Load failed: {message}", flush=True)
        self.statusBar().showMessage(f"Error: {message}")
        title = "Cannot open file" if kind == JobKind.LOAD else "Cannot update viewer"
        QtWidgets.QMessageBox.warning(self, title, message)

    def _document_loaded(self, document: Document) -> None:
        previous = self.document
        previous_selection = self.frame_selection
        same_image = (document.image_source is not None and previous is not None
                      and document.image_source is previous.image_source)
        saved_crop, saved_selected = self._crop, self._profile_selected
        self.document = document
        self._profile_selected = saved_selected if same_image else True
        self.frame = None
        self.frame_selection = None
        self._reset_pending = True
        self.path_label.setText(str(document.path))
        self.path_label.setCursorPosition(0)
        self.setWindowTitle(f"{document.path.name} — Matrix Viewer")
        self._sync_source_selectors()
        details = ""
        source = document.image_source
        if source is not None:
            channels = ", ".join(channel.value for channel in source.channels)
            details = (f"Image: {source.metadata.format} | {source.layout}\nChannels: {channels}\n"
                       f"File mode: {source.metadata.mode}\nFile depth: {source.metadata.depth}\n"
                       f"Decoded: {source.pixels.dtype.itemsize * 8}-bit per channel ({source.pixels.dtype})\n"
                       f"Matrix: {document.key}\n")
            if document.key == ImageMember.RGBA_GRAY:
                details += "Grayscale x normalized alpha; black background.\n"
            elif document.key == ImageMember.RGB_GRAY:
                details += "Grayscale = 0.2126 R + 0.7152 G + 0.0722 B.\n"
            elif document.key == ImageMember.MONO_COLOR:
                details += "2D / 3D use black and white at the source bit-depth scale; height = grayscale.\nAlpha is ignored.\n"
            elif document.key in (ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR):
                details += "2D / 3D use image colors; height = RGB grayscale.\n"
                details += "Alpha is ignored.\n" if document.key == ImageMember.RGB_COLOR else "Alpha controls opacity, not height.\n"
                details += "Profiles and derivatives show each displayed channel separately.\n"
                if document.key == ImageMember.RGBA_COLOR:
                    details += "Profile R/G/B/M are multiplied by normalized alpha; A remains a separate source-value curve.\n"
        self.info.setText(f"{details}Shape: {document.array.shape}\nDtype: {document.array.dtype}\n"
                          f"Size: {document.array.nbytes / (1024 ** 2):,.2f} MiB\nIndices start at 0.")
        if document.path.suffix.lower() in TEXT_EXTENSIONS | EXCEL_EXTENSIONS:
            header_text = ", ".join(document.csv_headers) if document.csv_headers else "none"
            self.info.setText(f"{self.info.text()}\nTable headers: {header_text}\nEmpty cells are NaN.")
        try:
            selection = default_selection(document, self._initial_mode, self._initial_channel_axis)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            selection = default_selection(document)
        self._initial_mode = None
        self._initial_channel_axis = None
        preserve_crop = (same_image and previous_selection is not None
                         and previous_selection.mode == ViewMode.MATRIX
                         and {previous_selection.x_axis, previous_selection.y_axis} == {0, 1})
        if preserve_crop and previous_selection is not None:
            selection = replace(selection, x_axis=previous_selection.x_axis, y_axis=previous_selection.y_axis)
        self._configure_selection(selection)
        if preserve_crop:
            self._crop = saved_crop
            self.crop_x_start.setValue(saved_crop.x_start)
            self.crop_x_end.setValue(saved_crop.x_end if saved_crop.x_end is not None else self.crop_x_end.maximum())
            self.crop_y_start.setValue(saved_crop.y_start)
            self.crop_y_end.setValue(saved_crop.y_end if saved_crop.y_end is not None else self.crop_y_end.maximum())
        self.controls.setEnabled(True)
        self._request_frame()

    def _sync_source_selectors(self, component: Component = Component.REAL) -> None:
        """Refresh array and display choices without issuing load/frame requests.

        Args:
            component: Complex component to select, including restoration after
                a failed file/member load. Images instead use their member key.
        """
        document = self.document
        with QtCore.QSignalBlocker(self.archive_key), QtCore.QSignalBlocker(self.display_channel):
            self.archive_key.clear()
            self.display_channel.clear()
            self.archive_key.setEnabled(False)
            self.display_channel.setEnabled(False)
            self.archive_label.setText("Source")
            self.archive_key.setToolTip("Current source file.")
            self.display_channel.setToolTip("")
            if document is None:
                return
            if document.keys and not document.is_image:
                self.archive_label.setText("MAT variable" if document.path.suffix.lower() == ".mat" else
                                           "Worksheet" if document.path.suffix.lower() in EXCEL_EXTENSIONS else "NPZ array")
                self.archive_key.addItems(list(document.keys))
                self.archive_key.setCurrentText(document.key or "")
                self.archive_key.setEnabled(True)
                self.archive_key.setToolTip(f"Choose the source array. Current: {document.key}")
            else:
                self.archive_key.addItem(document.path.name)
            if document.image_source is not None:
                self.display_channel.addItems(list(document.keys))
                self.display_channel.setCurrentText(document.key or "")
                self.display_channel.setEnabled(True)
                self.display_channel.setToolTip(f"Choose an image channel or combination. Current: {document.key}")
            elif np.iscomplexobj(document.array):
                for item in Component:
                    self.display_channel.addItem(item.value, item.value)
                self.display_channel.setCurrentIndex(self.display_channel.findData(component.value))
                self.display_channel.setEnabled(True)
                self.display_channel.setToolTip("Display Real, Imaginary, Magnitude, Phase (rad), or Magnitude (dB). Use Data conversion for degrees or custom dB references.")
            else:
                self.display_channel.addItem("Value", Component.REAL.value)
                self.display_channel.setToolTip("This real-valued array has no image channels or complex components.")

    def _configure_selection(self, selection: Selection) -> None:
        document = self.document
        if document is None:
            return
        self.profile_view.set_derivative_enabled(selection.mode != ViewMode.POINTS)
        self._updating = True
        self.mode.setCurrentIndex(self.mode.findData(selection.mode.value))
        mode_model = self.mode.model()
        if isinstance(mode_model, QtGui.QStandardItemModel):
            for mode, count in ((ViewMode.XY, 2), (ViewMode.POINTS, 3)):
                item = mode_model.item(self.mode.findData(mode.value))
                if item is not None:
                    item.setEnabled(document.array.ndim == 2 and count in document.array.shape
                                    and not np.iscomplexobj(document.array))
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
        self.channel_axis.setEnabled(document.image_source is None)
        self.mode.setEnabled(document.image_source is None or document.key not in (
            ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR, ImageMember.MONO_COLOR,
        ))
        self.y_axis.setEnabled(selection.mode == ViewMode.MATRIX)
        if np.iscomplexobj(document.array):
            self.display_channel.setCurrentIndex(self.display_channel.findData(selection.component.value))
        with QtCore.QSignalBlocker(self.db_floor):
            self.db_floor.setValue(selection.db_floor)
        coordinates = selection.mode in (ViewMode.XY, ViewMode.POINTS)
        self.coordinate_box.setVisible(coordinates)
        if coordinates:
            count = 2 if selection.mode == ViewMode.XY else 3
            self.coordinate_axis.clear()
            for axis, label in ((1, "Columns (N x coordinates)"), (0, "Rows (coordinates x N)")):
                if document.array.shape[axis] == count:
                    self.coordinate_axis.addItem(label, axis)
            self.coordinate_axis.setCurrentIndex(self.coordinate_axis.findData(selection.coordinate_axis))
            for index, combo in enumerate(self.coordinate_columns):
                combo.clear()
                combo.addItems([str(i) for i in range(count)])
                combo.setCurrentIndex(selection.coordinate_order[index] if index < count else 0)
                combo.setVisible(index < count)
                self.coordinate_labels[index].setVisible(index < count)
        self._updating = False
        self._refresh_axis_controls()
        with QtCore.QSignalBlocker(self.channel):
            self.channel.setValue(selection.channel)
        self._configure_crop()

    def _mode_changed(self) -> None:
        if self._updating or self.document is None:
            return
        mode = ViewMode(self.mode.currentData())
        try:
            selection = default_selection(self.document, mode)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc))
            with QtCore.QSignalBlocker(self.mode):
                self.mode.setCurrentIndex(self.mode.findData(self.frame_selection.mode.value) if self.frame_selection else 0)
            return
        self._configure_selection(selection)
        self._reset_pending = True
        self._schedule_frame()

    def _coordinate_layout_changed(self) -> None:
        if not self._updating and self.document is not None:
            self._configure_crop()
            self._reset_pending = True
            self._schedule_frame()

    def _swap_coordinates(self) -> None:
        x, y = self.coordinate_columns[:2]
        a, b = x.currentIndex(), y.currentIndex()
        with QtCore.QSignalBlocker(x), QtCore.QSignalBlocker(y):
            x.setCurrentIndex(b)
            y.setCurrentIndex(a)
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
        coordinates = self.mode.currentData() in (ViewMode.XY.value, ViewMode.POINTS.value)
        for widget in (self.x_axis, self.y_axis, self.channel_axis, self.channel):
            widget.setEnabled(not coordinates)
        if coordinates:
            self.slice_box.hide()
            self._refresh_control_visibility()
            return
        self.channel_axis.setEnabled(self.document.image_source is None)
        channel_axis = self.channel_axis.currentIndex() - 1
        matrix = self.mode.currentIndex() == 0
        self.y_axis.setEnabled(matrix)
        self._updating = True
        self.channel.setEnabled(channel_axis >= 0 and self.document.image_source is None)
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
        self._refresh_control_visibility()

    def _refresh_control_visibility(self) -> None:
        """Hide irrelevant signal controls while preserving editable axes/channels."""
        document = self.document
        if document is None:
            return
        mode = ViewMode(self.mode.currentData())
        signal = mode in (ViewMode.SIGNAL, ViewMode.XY)
        indexed = mode == ViewMode.SIGNAL
        multiple_axes = document.array.ndim > 1
        rows = (
            (self.mode, not signal or multiple_axes),
            (self.x_axis, not signal or (indexed and multiple_axes)),
            (self.y_axis, not signal),
            (self.channel_axis, not signal or (indexed and multiple_axes and document.image_source is None)),
            (self.channel, not signal or (indexed and self.channel_axis.currentIndex() > 0)),
        )
        for field, visible in rows:
            self.axes_form.setRowVisible(field, visible)
        self.axes_box.setVisible(any(visible for _, visible in rows))
        for field in (self.colormap, self.color_low, self.color_high):
            self.display_form.setRowVisible(field, not signal)
        self.display_box.setTitle("Plot appearance" if signal else "Color and appearance")
        self.display_form.setRowVisible(self.db_floor, np.iscomplexobj(document.array)
                                        and self.display_channel.currentData() == Component.MAGNITUDE_DB)
        self.reset_limits_button.setText("Reset value bounds" if signal else "Reset filter / color limits")
        self.surface_controls.setVisible(not signal)
        self._sync_marker_controls()

    def _selection(self) -> Selection:
        assert self.document is not None
        mode = ViewMode(self.mode.currentData())
        if mode in (ViewMode.XY, ViewMode.POINTS):
            count = 2 if mode == ViewMode.XY else 3
            axis = int(self.coordinate_axis.currentData())
            return Selection(mode, 1 - axis, None, None, 0, (0, 0), coordinate_axis=axis,
                             coordinate_order=tuple(combo.currentIndex() for combo in self.coordinate_columns[:count]))
        channel_axis = self.channel_axis.currentIndex() - 1
        matrix = self.mode.currentIndex() == 0
        slices = tuple(self._slice_spins[axis].value() if axis in self._slice_spins else 0
                       for axis in range(self.document.array.ndim))
        return Selection(ViewMode.MATRIX if matrix else ViewMode.SIGNAL,
                         self.x_axis.currentIndex(), self.y_axis.currentIndex() if matrix else None,
                         channel_axis if channel_axis >= 0 else None, self.channel.value(), slices,
                         Component(self.display_channel.currentData()) if np.iscomplexobj(self.document.array) else Component.REAL,
                         db_floor=self.db_floor.value())

    @staticmethod
    def _bound(entry: QtWidgets.QLineEdit) -> float | None:
        text = entry.text().strip()
        if not text:
            return None
        value = float(text)
        if not np.isfinite(value):
            raise ValueError("Bounds must be finite numbers, or blank for automatic limits.")
        return value

    def _value_limits(self, selection: Selection) -> Limits:
        """Read current bounds, ignoring any stale settings for complex phase."""
        if self.document is not None and is_phase_view(self.document, selection):
            return Limits()
        return Limits(self._bound(self.filter_low), self._bound(self.filter_high),
                      FilterMode(self.filter_mode.currentText()))

    def _schedule_frame(self) -> None:
        if not self._updating and self.document is not None:
            self._export_ready = False
            self.export_box.setEnabled(False)
            self._latest[JobKind.FRAME] = -1
            self._rebuild.start()

    def _request_frame(self) -> None:
        document = self.document
        if document is None or self._closing:
            return
        self._export_ready = False
        self.export_box.setEnabled(False)
        try:
            selection = self._selection()
            limits = self._value_limits(selection)
            # Reject invalid color fields before starting expensive work.
            if selection.mode in (ViewMode.MATRIX, ViewMode.POINTS):
                self._color_levels(self.frame.limits if self.frame else (0, 1))
            axes = [selection.x_axis, selection.y_axis, selection.channel_axis]
            active = [axis for axis in axes if axis is not None]
            if len(set(active)) != len(active):
                raise ValueError("Row, column/sample and channel axes must be different.")
            if selection.mode in (ViewMode.XY, ViewMode.POINTS):
                if len(set(selection.coordinate_order)) != len(selection.coordinate_order):
                    raise ValueError("X, Y and Z must use distinct source rows/columns.")
        except ValueError as exc:
            self.statusBar().showMessage(f"Invalid setting: {exc}")
            return
        self._next_selection = selection
        edge = self.max_edge.value() if selection.mode == ViewMode.MATRIX else 0
        points = self.max_points.value()
        crop = self._crop
        self.statusBar().showMessage("Preparing views…")
        self._submit(JobKind.FRAME, lambda: prepare_frame(document, selection, limits, edge, crop, max_points=points))

    def _color_levels(self, automatic: tuple[float, float]) -> tuple[float, float]:
        if self.frame is not None and self.frame.composite:
            return automatic
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
        cloud = selection.mode == ViewMode.POINTS
        self._sync_frame_controls()
        style = self._marker_style()
        self.image_view.set_marker_style(style)
        self.profile_view.set_marker_style(style)
        self._set_view_layout(selection.mode)
        self.profile_controls.setVisible(matrix)
        self.profile_controls.setEnabled(matrix)
        self._sync_raw_view()
        self._surface_dirty = True
        self._surface_reset |= reset
        self._presentation_changed(reset=reset)
        if matrix:
            self._configure_profile_range()
            if reset:
                self.profile_view.reset_view()
        elif not cloud:
            self.profile_view.set_data(frame.scalar, frame.valid, "XY signal" if frame.xy else "Signal", reset, x_start=frame.x_start,
                                       display_values=frame.display_scalar, clipped=frame.clip_kind != 0,
                                       limits=frame.value_limits, x_values=frame.x_values)
            self._profile_axis_label(frame.x_grid)
        else:
            self.profile_view.clear_selection()

    def _sync_frame_controls(self) -> None:
        """Refresh settings/export availability without drawing a data view."""
        frame, selection = self.frame, self.frame_selection
        if frame is None or selection is None:
            return
        matrix = selection.mode == ViewMode.MATRIX
        cloud = selection.mode == ViewMode.POINTS
        self._export_ready = True
        self.export_box.setEnabled(not self._export_busy)
        self._sync_export_controls()
        self._refresh_control_visibility()
        self.surface_controls.setEnabled(matrix or cloud)
        self.max_edge.setEnabled(matrix)
        self.max_points.setEnabled(cloud)
        self.point_size.setEnabled(cloud)
        crop_text = f"X: {frame.x_start}..{frame.x_start + frame.scalar.shape[-1] - 1}"
        if matrix:
            crop_text = f"{crop_text}; Y: {frame.y_start}..{frame.y_start + frame.scalar.shape[0] - 1}"
        self.crop_info.setText(f"Displayed {crop_text}\nShape: {frame.scalar.shape}. Ends included; original indices.")
        visible = int(np.count_nonzero(frame.valid))
        self.statusBar().showMessage(
            f"Ready | Visible samples: {visible:,} / {frame.scalar.size:,}"
            + (f" | Clamped: {np.count_nonzero(frame.clip_kind):,}" if np.any(frame.clip_kind) else "")
            + (" | Image colors; surface height uses grayscale" if frame.composite else "")
        )

    def _sync_raw_view(self) -> None:
        """Display the base window's single source; workspaces choose their own."""
        frame, selection = self.frame, self.frame_selection
        self.raw_view.set_matrices((self._raw_source_name(),) if self.document is not None else (),
                                   0 if self.document is not None else -1)
        if frame is None or selection is None:
            self.raw_view.clear()
            return
        labels = self.document.csv_headers if self.document is not None and selection.x_axis == 1 else ()
        self.raw_view.set_frame(frame, labels, image_source=self.document.image_source if self.document is not None else None,
                                source_name=self._raw_source_name())

    def _raw_source_name(self) -> str:
        document = self.document
        return (f"{document.path.name} / {document.key}" if document.key else document.path.name) if document is not None else ""

    def _set_view_layout(self, mode: ViewMode) -> None:
        """Expose flat signal/derivative tabs or restore the linked matrix split."""
        signal = mode in (ViewMode.SIGNAL, ViewMode.XY)
        was_signal = self._layout_mode in (ViewMode.SIGNAL, ViewMode.XY)
        matrix, cloud = mode == ViewMode.MATRIX, mode == ViewMode.POINTS
        changed = mode != self._layout_mode
        if self._layout_mode == ViewMode.MATRIX and changed:
            self._matrix_split = self.vertical.sizes()
            self._matrix_tab = self.tabs.currentIndex()
        with QtCore.QSignalBlocker(self.tabs):
            self.profile_view.set_external_tabs(signal)
            if signal and changed:
                # Reset the page before reparenting: showing an old derivative
                # must not compute it while the new frame is being installed.
                with QtCore.QSignalBlocker(self.profile_view.tabs):
                    self.profile_view.tabs.setCurrentIndex(0)
                self.profile_layout.setContentsMargins(0, 0, 0, 0)
            elif not signal and was_signal:
                self.profile_area.hide()
                for host in (self.primary_view, self.secondary_view):
                    host.removeWidget(self.profile_area)
                self.primary_view.setCurrentWidget(self.image_view)
                self.secondary_view.setCurrentWidget(self.surface_view)
                self.vertical.addWidget(self.profile_area)
                self.profile_layout.setContentsMargins(0, CONTENT_MARGIN, 0, 0)
            self.tabs.setTabText(0, "1D plot" if signal else "2D image")
            self.tabs.setTabText(1, "1D Derivative" if signal else "3D point cloud" if cloud else "3D surface")
            self.tabs.setTabVisible(0, not cloud)
            self.tabs.setTabEnabled(0, not cloud)
            self.tabs.setTabVisible(1, True)
            self.tabs.setTabEnabled(1, True)
            if changed:
                self.tabs.setCurrentIndex(self._matrix_tab if matrix else 1 if cloud else 0)
            if signal:
                self._show_signal_tab()
            self.profile_area.setVisible(not cloud)
            if changed and matrix:
                self.vertical.setSizes(self._matrix_split)
        self._layout_mode = mode
        self.hint.setText(SIGNAL_HINT if signal else SURFACE_HINT if cloud else f"{SIGNAL_HINT} · {SURFACE_HINT}")

    def _show_signal_tab(self) -> None:
        """Move the shared profile/toolbar into the selected full-height page.

        Keeping one profile preserves plot ranges and derivative caches. The
        inactive host hides it on Raw data, pausing pending derivative work.
        """
        index = self.tabs.currentIndex()
        if index not in (0, 1):
            return
        host = self.primary_view if index == 0 else self.secondary_view
        other = self.secondary_view if index == 0 else self.primary_view
        if host.indexOf(self.profile_area) < 0:
            self.profile_area.hide()
            other.removeWidget(self.profile_area)
            host.addWidget(self.profile_area)
        host.setCurrentWidget(self.profile_area)
        self.profile_area.show()
        self.profile_view.tabs.setCurrentIndex(index)

    def _presentation_changed(self, *, reset: bool = False) -> None:
        if self._updating or self.frame is None:
            return
        if self.frame_selection is not None and self.frame_selection.mode in (ViewMode.SIGNAL, ViewMode.XY):
            return
        for control in (self.colormap, self.color_low, self.color_high):
            control.setEnabled(not self.frame.composite)
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
        elif self.frame.point_coordinates is not None:
            self._surface_dirty = True
            self._surface_reset |= reset
            self._refresh_surface()

    def _update_height_controls(self) -> None:
        automatic = self.auto_height.isChecked()
        self.height_scale.setEnabled(not automatic)
        self.height_slider.setEnabled(not automatic)
        if automatic and self.frame is not None and self.frame.scalar.ndim == 2:
            span = self.frame.limits[1] - self.frame.limits[0]
            frame = self.frame
            extent = max(frame.scalar.shape[1] * frame.x_mapping.scale,
                         frame.scalar.shape[0] * frame.y_mapping.scale)
            value = extent * 0.3 / span
            with QtCore.QSignalBlocker(self.height_scale):
                self.height_scale.setValue(value)
        elif automatic and self.frame is not None and self.frame.point_coordinates is not None:
            with QtCore.QSignalBlocker(self.height_scale):
                self.height_scale.setValue(1.0)
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
        if self.frame is None or self.frame.surface is None:
            return
        if not self._surface_dirty:
            self.surface_view.set_height_scale(self.height_scale.value())

    def _refresh_surface(self) -> None:
        if (self._layout_mode not in (ViewMode.MATRIX, ViewMode.POINTS)
                or self.frame is None or self.frame.surface is None or self.tabs.currentIndex() != 1):
            return
        if self._surface_dirty:
            try:
                self.surface_view.set_frame(self.frame, self.colormap.currentText(),
                                            self._color_levels(self.frame.limits), self.height_scale.value(),
                                            self._surface_reset, self.point_size.value(),
                                            highlight_clipped=self.highlight_clipped.isChecked())
            except (ValueError, RuntimeError) as exc:
                self.statusBar().showMessage(f"3D rendering error: {exc}")
                return
            self._surface_dirty = False
            self._surface_reset = False
        self._update_profile()

    def _tab_changed(self) -> None:
        if self._layout_mode in (ViewMode.SIGNAL, ViewMode.XY):
            self._show_signal_tab()
        else:
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
        self._sync_export_controls()
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
        grid = frame.x_grid if row else frame.y_grid
        start = frame.x_start if row else frame.y_start
        channel_values: RealArray | None = None
        channel_names: tuple[ImageMember, ...] = ()
        document = self.document
        if (document is not None and document.image_source is not None
                and document.key in (ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR)
                and frame.raw is not None and frame.raw.ndim == 3):
            # Color members contain real source RGB(A), even for gray+alpha.
            pixels = cast(RealArray, frame.raw)
            channel_values = pixels[local_index, :, :] if row else pixels[:, local_index, :]
            if ImageMember.MONO in document.image_source.channels:
                channel_values = channel_values[:, (0, 3)]
                channel_names = (ImageMember.MONO, ImageMember.ALPHA)
            else:
                channel_names = (ImageMember.RED, ImageMember.GREEN, ImageMember.BLUE)
                if channel_values.shape[1] == 4:
                    channel_names += (ImageMember.ALPHA,)
        self.profile_view.set_data(values, valid, f"{'Row' if row else 'Column'} {index}",
                                    reset=self._reset_pending, x_start=frame.x_start if row else frame.y_start,
                                    display_values=shown, clipped=clipped, limits=frame.value_limits,
                                    channel_values=channel_values, channel_names=channel_names,
                                    x_values=grid.values(start, len(values)) if grid is not None else None,
                                    alpha_weighted=bool(channel_names) and document is not None and document.key == ImageMember.RGBA_COLOR)
        self._profile_axis_label(grid)
        self.image_view.set_profile(row, index)
        if self.tabs.currentIndex() == 1 and not self._surface_dirty:
            self.surface_view.set_profile(row, index)

    def _profile_axis_label(self, grid: "AxisCoordinates | None") -> None:
        for pane in (self.profile_view.signal_pane, self.profile_view.derivative_pane):
            pane.plot_item.getAxis("bottom").enableAutoSIPrefix(grid is None)
            if grid is not None:
                pane.plot_item.setLabel("bottom", grid.label())

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

    def _reset_value_bounds(self) -> None:
        """Clear both value bounds and refresh views, retaining spatial/color settings."""
        for entry in (self.filter_low, self.filter_high):
            entry.clear()
        self._schedule_frame()

    def _reset_limits(self) -> None:
        for entry in (self.color_low, self.color_high):
            entry.clear()
        self._reset_value_bounds()

    def _fit_views(self) -> None:
        mode = self.frame_selection.mode if self.frame_selection is not None else None
        if mode == ViewMode.MATRIX:
            self.image_view.reset_view()
        if mode != ViewMode.POINTS:
            self.profile_view.reset_view()
        if mode in (ViewMode.MATRIX, ViewMode.POINTS):
            self.surface_view.reset_view()

    def _choose_file(self) -> None:
        start = str(self.document.path.parent) if self.document else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open matrix or image", start, FILE_FILTER)
        if path:
            self.open_path(Path(path))

    def _key_changed(self) -> None:
        document = self.document
        if document is None or document.is_image or not document.keys or self.archive_key.currentIndex() < 0:
            return
        key = self.archive_key.currentText()
        if key == document.key:
            return
        self.open_path(document.path, key)

    def _display_channel_changed(self) -> None:
        """Change image composition or complex projection within the source array."""
        document = self.document
        if self._updating or document is None or self.display_channel.currentIndex() < 0:
            return
        if document.image_source is not None:
            key = self.display_channel.currentText()
            if key == document.key:
                return
            self._rebuild.stop()
            self._latest[JobKind.FRAME] = -1
            self.controls.setEnabled(False)
            self.archive_key.setEnabled(False)
            self.display_channel.setEnabled(False)
            self.statusBar().showMessage(f"Preparing image matrix: {key}…")
            self._submit(JobKind.LOAD, lambda: select_image_member(document, key))
        elif np.iscomplexobj(document.array):
            self._schedule_frame()

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept a local numeric/image file dragged into the window.

        Args:
            event: Native Qt drag-enter event.
        """
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS | TEXT_EXTENSIONS | EXCEL_EXTENSIONS | {".npy", ".npz", ".mat"}:
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Open the first local file from a drop asynchronously.

        Args:
            event: Native Qt drop event.
        """
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self._open_dropped_path(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def _open_dropped_path(self, path: Path) -> None:
        self.open_path(path)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Stop preparation and release VTK before closing the Qt window.

        Args:
            event: Native Qt close event.
        """
        self._closing = True
        self._rebuild.stop()
        if not self._export_busy:
            self._pool.clear()
        self._pool.waitForDone()
        self.surface_view.shutdown()
        event.accept()


def run(path: Path | None, key: str | None, mode: str | None,
        channel_axis: int | None, max_edge: int) -> int:
    """Create the Qt application and run the viewer until its window closes.

    Args:
        path: Optional initial file.
        key: Optional NPZ member, MAT variable or image matrix label.
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
    application.setStyle(CompactFusionStyle())
    from .workspace_window import WorkspaceWindow
    window = WorkspaceWindow(max_edge, mode, channel_axis)
    window.show()
    if path is not None:
        QtCore.QTimer.singleShot(0, lambda: window.open_path(path, key))
    return application.exec()
