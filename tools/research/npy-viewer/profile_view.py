"""Signal/profile plots with an optional, lazily computed derivative tab.

Color image profiles overlay source R/G/B/A or M/A channels in fixed colors.
RGBA/MA color profiles multiply R/G/B/M by normalized alpha before filtering
and differentiating; the independent A curve retains original opacity samples.
Actual derivative calculations print their source, channel, indices and timing;
cached tab revisits do not emit calculation diagnostics.
The tab bar can be hidden when the standalone viewer supplies the page tabs.

Requirements: PySide6, pyqtgraph and numpy.
Usage: embedded below matrix views or used alone for signal data.
"""

from enum import IntEnum
from dataclasses import dataclass, replace
from collections.abc import Sequence
from time import perf_counter

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox
from pyqtgraph.graphicsItems.AxisItem import AxisItem

from .data_model import (DEFAULT_CLIP_COLOR, FloatArray, ImageMember, Limits, RealArray, BoolArray,
                         apply_value_limits, format_sample, normalize_image_alpha)
from .clipping import ClippedCurve, clip_curve
from .derivatives import DerivativeResult, differentiate
from .plot_support import graphics_scene, pyside_graphics_view

WHEEL_ZOOM_FACTOR = 1.15
DERIVATIVE_DELAY_MS = 70
UNDEFINED_COLOR = "#e53935"
CLIP_LINE_WIDTH = 4
CLIP_POINT_SIZE = 6
TICK_SIGNIFICANT_DIGITS = 10
HOVER_SIGNIFICANT_DIGITS = 8
FLOAT_NOISE_RELATIVE_TOLERANCE = 64 * float(np.finfo(np.float64).eps)
CONSTANT_Y_PADDING_FRACTION = 0.01
ZERO_Y_PADDING = 0.5
CHANNEL_COLORS: dict[ImageMember, str] = {
    ImageMember.RED: "#ff0000", ImageMember.GREEN: "#00ff00", ImageMember.BLUE: "#0000ff",
    ImageMember.MONO: "#000000", ImageMember.ALPHA: "#b8860b",
}
MONO_OUTLINE_COLOR = "#dce5f2"
MONO_OUTLINE_WIDTH = 3
ANNOTATION_Z_VALUE = 1
MIN_PROFILE_PLOT_HEIGHT = 160
CHANNEL_LEGEND_COLUMNS = 4


def _channel_label(channel: ImageMember | None, alpha_weighted: bool) -> str:
    """Name one profile quantity, identifying multiplication by normalized A."""
    label = "M" if channel == ImageMember.MONO else channel.value if channel else "Signal"
    return f"{label}×α" if alpha_weighted and channel not in (None, ImageMember.ALPHA) else label


def _compact_sample(values: RealArray, index: int) -> str:
    """Shorten a floating-point hover value; preserve integer precision."""
    if values.dtype.kind == "f":
        return f"{float(values[index]):.{HOVER_SIGNIFICANT_DIGITS}g}"
    return format_sample(values, index)


@dataclass(frozen=True)
class ProfileTrace:
    """One source channel and its display-only filtering/clipping geometry.

    A None channel represents the ordinary single curve. Image channel arrays
    retain source units; optional alpha weighting is applied before bounds.
    The independent alpha channel is never weighted by itself.
    """

    channel: ImageMember | None
    values: RealArray
    valid: BoolArray
    shown: RealArray
    clipped: BoolArray | None
    curve: ClippedCurve | None
    alpha_weighted: bool = False

    @property
    def label(self) -> str:
        """Return the short legend/debug label, using M for monochrome."""
        return _channel_label(self.channel, self.alpha_weighted)


class CurveStyle(IntEnum):
    """Available line and sample-marker combinations."""

    LINE = 0
    POINTS = 1
    BOTH = 2


class JumpMode(IntEnum):
    """Presets for the maximum allowed neighboring sample difference."""

    RADIANS = 0
    DEGREES = 1
    CUSTOM = 2
    GAPS_ONLY = 3


class ProfileViewBox(ViewBox):
    """Pan normally; use the wheel for X zoom and Ctrl+wheel for both axes."""

    def childrenBounds(self, frac: Sequence[float] | None = None,
                       orthoRange: Sequence[Sequence[float] | None] = (None, None),
                       items: Sequence[QtWidgets.QGraphicsItem] | None = None) -> list[list[float] | None]:
        """Pad nearly constant Y bounds instead of auto-fitting roundoff noise.

        Args:
            frac: Optional visible data fractions for X and Y, passed to QtGraph.
            orthoRange: Optional perpendicular ranges for visible-data fitting.
            items: Optional graphics items to include; None uses all data items.

        Returns:
            X/Y bounds, with None for an empty axis. Only automatic fitting
            uses the padded bounds; manual zoom and source values are unchanged.
        """
        raw_bounds = super().childrenBounds(frac=frac, orthoRange=orthoRange, items=items)
        bounds: list[list[float] | None] = [
            None if axis is None else [float(axis[0]), float(axis[1])] for axis in raw_bounds
        ]
        y_range = bounds[1]
        if y_range is not None:
            lower, upper = y_range
            magnitude = max(abs(lower), abs(upper))
            if upper - lower <= magnitude * FLOAT_NOISE_RELATIVE_TOLERANCE:
                padding = magnitude * CONSTANT_Y_PADDING_FRACTION if magnitude else ZERO_Y_PADDING
                padded = [lower - padding, upper + padding]
                if all(np.isfinite(value) for value in padded):
                    bounds[1] = padded
        return bounds

    def wheelEvent(self, ev: object, axis: int | None = None) -> None:
        """Zoom about the pointer without letting X-only zoom alter the Y range.

        Args:
            ev: Native PySide6 graphics-scene wheel event.
            axis: Optional originating axis; the same modifier mapping applies.
        """
        if not isinstance(ev, QtWidgets.QGraphicsSceneWheelEvent):
            return
        both = bool(ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)
        factor = WHEEL_ZOOM_FACTOR ** (-ev.delta() / 120)
        center = self.mapSceneToView(ev.scenePos())
        self.disableAutoRange()
        self.scaleBy(x=factor, y=factor if both else 1.0, center=center)
        ev.accept()
        self.sigRangeChangedManually.emit([True, both])


class ProfileValueAxis(AxisItem):
    """Compact Y tick labels without rounding the plotted or exported data."""

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        """Format tick labels with bounded precision and scientific notation.

        Args:
            values: Tick positions in data coordinates.
            scale: Display multiplier, including the axis SI prefix.
            spacing: Tick interval passed through for logarithmic axes.

        Returns:
            Labels with at most ten significant digits and no trailing zeros.
            Logarithmic labels keep PyQtGraph's exponent formatting.
        """
        if self.logMode:
            return self.logTickStrings(values, scale, spacing)
        labels = [f"{value * scale:.{TICK_SIGNIFICANT_DIGITS}g}" for value in values]
        return ["0" if label == "-0" else label for label in labels]


class CurvePane(QtWidgets.QWidget):
    """One curve canvas with matching zoom behavior and a movable crosshair.

    Args:
        y_label: Label describing the vertical quantity.
        parent: Optional owning widget.
    """

    def __init__(self, y_label: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.view_box = ProfileViewBox()
        self.plot_item = PlotItem(viewBox=self.view_box, axisItems={"left": ProfileValueAxis("left")})
        self.plot = pg.PlotWidget(plotItem=self.plot_item)
        self.plot_item.setMenuEnabled(False)
        self.plot_item.setLabel("bottom", "Index (x)")
        self.plot_item.setLabel("left", y_label)
        self.plot_item.showGrid(x=True, y=True, alpha=0.2)
        self.view_box.setMouseMode(ViewBox.PanMode)
        self.curve = pg.PlotDataItem()
        self.plot_item.addItem(self.curve)
        self.channel_curves: dict[ImageMember, pg.PlotDataItem] = {}
        self._alpha_weighted = False
        self.legend = self.plot_item.addLegend(offset=(5, 5), colCount=CHANNEL_LEGEND_COLUMNS)
        self.legend.hide()
        self._dark = False
        self.crosshair = pg.InfiniteLine(angle=90, pen=pg.mkPen("#9c9c9c", style=QtCore.Qt.PenStyle.DashLine))
        self.plot_item.addItem(self.crosshair, ignoreBounds=True)
        self.crosshair.hide()
        self.native_view = pyside_graphics_view(self.plot)
        self.native_view.setMinimumHeight(MIN_PROFILE_PLOT_HEIGHT)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.native_view)
        self.setToolTip("Wheel: zoom X only. Ctrl+wheel: zoom X and Y. Left drag: pan.")

    def set_samples(self, values: RealArray, valid: BoolArray,
                    color: QtGui.QColor, mode: CurveStyle, x_start: int = 0,
                    x_values: RealArray | None = None, *, channel: ImageMember | None = None) -> None:
        """Render samples with gaps, optional markers and a common curve style.

        Args:
            values: One-dimensional sample values.
            valid: Same-length visibility mask.
            color: Line and marker color.
            mode: Line, points or both.
            x_start: Source index of the first sample; defaults to zero.
            x_values: Optional coordinates including interpolated clip crossings.
            channel: Named image curve, or None for the ordinary single curve.
        """
        y = np.where(valid, values, np.nan)
        ordered = x_values is None or bool(np.all(np.isfinite(x_values)) and np.all(x_values[1:] >= x_values[:-1]))
        curve = self.curve if channel is None else self.channel_curves[channel]
        outlined = self._dark and channel == ImageMember.MONO
        curve.setData(
            np.arange(x_start, x_start + len(y)) if x_values is None else x_values, y, connect="finite",
            pen=pg.mkPen(color, width=1) if mode != CurveStyle.POINTS else None,
            symbol="o" if mode != CurveStyle.LINE or len(y) == 1 else None,
            symbolSize=5, symbolBrush=color, symbolPen=MONO_OUTLINE_COLOR if outlined else None,
            shadowPen=pg.mkPen(MONO_OUTLINE_COLOR, width=MONO_OUTLINE_WIDTH)
            if outlined and mode != CurveStyle.POINTS else None,
            autoDownsample=ordered and bool(np.all(valid)), downsampleMethod="peak", clipToView=ordered,
        )

    def set_channels(self, channels: tuple[ImageMember, ...], *, alpha_weighted: bool = False) -> None:
        """Select named overlay curves and their legend without plotting data.

        Args:
            channels: Image channels to display in order. Empty restores the
                single curve. Removed channels release their graph items.
            alpha_weighted: Label color/monochrome curves as multiplied by
                normalized alpha. The A label remains unchanged.
        """
        if tuple(self.channel_curves) != channels or self._alpha_weighted != alpha_weighted:
            for item in self.channel_curves.values():
                self.plot_item.removeItem(item)
            self.channel_curves.clear()
            self.legend.clear()
            for channel in channels:
                label = _channel_label(channel, alpha_weighted)
                item = pg.PlotDataItem(name=label)
                self.plot_item.addItem(item)
                self.channel_curves[channel] = item
        self._alpha_weighted = alpha_weighted
        self.curve.setVisible(not channels)
        self.legend.setVisible(bool(channels))

    def clear_curves(self) -> None:
        """Clear all plotted data while retaining channel items and styling."""
        self.curve.clear()
        for item in self.channel_curves.values():
            item.clear()

    def set_theme(self, dark: bool) -> None:
        """Change only this plotting canvas and axes, leaving Qt widgets native.

        Args:
            dark: True selects a dark plot background.
        """
        self._dark = dark
        self.plot.setBackground("#151b25" if dark else "#ffffff")
        self.legend.setLabelTextColor("#dce5f2" if dark else "#263247")
        # QtGraph updates label defaults without rebuilding existing text HTML.
        for _, label in self.legend.items:
            label.setText(label.text)
        self.legend.setBrush("#151b25" if dark else "#ffffff")
        monochrome = self.channel_curves.get(ImageMember.MONO)
        if monochrome is not None:
            monochrome.setShadowPen(pg.mkPen(MONO_OUTLINE_COLOR, width=MONO_OUTLINE_WIDTH) if dark else None)
            monochrome.setSymbolPen(MONO_OUTLINE_COLOR if dark else None)
        for name in ("left", "bottom"):
            self.plot_item.getAxis(name).setPen("#adb9cb" if dark else "#465368")
            self.plot_item.getAxis(name).setTextPen("#dce5f2" if dark else "#263247")


class ProfileView(QtWidgets.QWidget):
    """Signal and derivative tabs sharing source samples and appearance controls.

    Args:
        parent: Optional owning widget.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: RealArray | None = None
        self.valid: BoolArray | None = None
        self.x_start = 0
        self.x_values: RealArray | None = None
        self._x_order = np.empty(0, dtype=np.int64)
        self._sorted_x = np.empty(0, dtype=np.float64)
        self.display_values: RealArray | None = None
        self.clipped: BoolArray | None = None
        self._clipped_curve: ClippedCurve | None = None
        self.channel_values: RealArray | None = None
        self.channel_names: tuple[ImageMember, ...] = ()
        self.alpha_weighted = False
        self._traces: tuple[ProfileTrace, ...] = ()
        self.clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        self.color = QtGui.QColor("#48b9ff")
        self._has_data = False
        self._external_tabs = False
        self._derivative_reset = True
        self._derivative_dirty = True
        self._limits = Limits()
        self.derivative_result: DerivativeResult | None = None
        self.derivative_results: dict[ImageMember | None, DerivativeResult] = {}
        self._derivative_timer = QtCore.QTimer(self)
        self._derivative_timer.setSingleShot(True)
        self._derivative_timer.setInterval(DERIVATIVE_DELAY_MS)
        self._derivative_timer.timeout.connect(self._ensure_derivative)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("Signal / profile")
        self.title.setMinimumWidth(105)
        bar.addWidget(self.title)
        self.style_selector = QtWidgets.QComboBox()
        self.style_selector.addItems(["Line", "Points", "Line + points"])
        self.style_selector.currentIndexChanged.connect(self._redraw)
        bar.addWidget(self.style_selector)
        self.color_button = QtWidgets.QPushButton("Line color")
        self.color_button.clicked.connect(self._choose_color)
        bar.addWidget(self.color_button)
        fit = QtWidgets.QPushButton("Fit curve")
        fit.clicked.connect(self.reset_view)
        bar.addWidget(fit)
        self.readout = QtWidgets.QLabel("Move over the curve to inspect a sample")
        self.readout.setMinimumWidth(190)
        self.readout.setWordWrap(True)
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.readout, 1)
        layout.addLayout(bar)
        self.tabs = QtWidgets.QTabWidget()
        self.signal_pane = CurvePane("Value (y)")
        self.tabs.addTab(self.signal_pane, "Signal")
        # Keep the signal canvas accessible to linked views and coordinate probes.
        self.view_box, self.plot_item = self.signal_pane.view_box, self.signal_pane.plot_item
        self.plot, self.curve = self.signal_pane.plot, self.signal_pane.curve
        self.crosshair = self.signal_pane.crosshair
        self.clip_curve_item = pg.PlotDataItem()
        self.clip_points_item = pg.PlotDataItem()
        # Channel curves are added later; keep caps above all signal colors.
        self.clip_curve_item.setZValue(ANNOTATION_Z_VALUE)
        self.clip_points_item.setZValue(ANNOTATION_Z_VALUE)
        self.plot_item.addItem(self.clip_curve_item)
        self.plot_item.addItem(self.clip_points_item)
        graphics_scene(self.signal_pane.native_view).sigMouseMoved.connect(self._hover)

        # ── derivative settings and lazy canvas ────────────
        page = QtWidgets.QWidget()
        derivative_layout = QtWidgets.QVBoxLayout(page)
        derivative_layout.setContentsMargins(0, 0, 0, 0)
        settings = QtWidgets.QHBoxLayout()
        self.jump_mode = QtWidgets.QComboBox()
        self.jump_mode.addItems(["Phase (radians)", "Phase (degrees)", "Custom threshold", "Gaps only"])
        self.jump_mode.setCurrentIndex(JumpMode.GAPS_ONLY)
        settings.addWidget(self.jump_mode)
        settings.addWidget(QtWidgets.QLabel("Jump |Δy| >"))
        self.jump_threshold = QtWidgets.QDoubleSpinBox()
        self.jump_threshold.setDecimals(9)
        self.jump_threshold.setRange(1e-9, 1e100)
        self.jump_threshold.setValue(1.0)
        self.jump_threshold.setKeyboardTracking(False)
        self.jump_threshold.setEnabled(False)
        settings.addWidget(self.jump_threshold)
        settings.addStretch()
        derivative_layout.addLayout(settings)
        self.derivative_pane = CurvePane("dy / dx")
        self.undefined_markers = pg.ScatterPlotItem(
            pen=None, brush=UNDEFINED_COLOR, size=8, symbol="o",
        )
        self.undefined_markers.setZValue(ANNOTATION_Z_VALUE)
        self.derivative_pane.plot_item.addItem(self.undefined_markers)
        graphics_scene(self.derivative_pane.native_view).sigMouseMoved.connect(self._hover_derivative)
        derivative_layout.addWidget(self.derivative_pane)
        self.derivative_note = QtWidgets.QLabel(
            "Red dots at y=0: undefined / omitted derivatives; not zero derivatives."
        )
        self.derivative_note.setWordWrap(True)
        derivative_layout.addWidget(self.derivative_note)
        self.tabs.addTab(page, "Derivative")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.jump_mode.currentIndexChanged.connect(self._jump_mode_changed)
        self.jump_threshold.valueChanged.connect(self._invalidate_derivative)
        layout.addWidget(self.tabs)

    def set_data(self, values: RealArray, valid: BoolArray, title: str,
                 reset: bool = False, *, x_start: int = 0,
                 display_values: RealArray | None = None, clipped: BoolArray | None = None,
                 limits: Limits = Limits(), x_values: RealArray | None = None,
                 channel_values: RealArray | None = None, channel_names: tuple[ImageMember, ...] = (),
                 alpha_weighted: bool = False) -> None:
        """Set source samples; preserve cached plots when the data is unchanged.

        Inputs are retained without copying and must not be modified in place.
        Derivatives are calculated only while their tab is selected. Equivalent
        frames (for example after changing 3D sampling) reuse the existing plots.

        Args:
            values: Original one-dimensional numeric data.
            valid: Same-length visibility mask.
            title: Human-readable source description.
            reset: Fit the new curve instead of retaining the current ranges.
            x_start: Original source index of the first sample, before cropping.
            display_values: Visually clamped samples, or None to use the source.
            clipped: Mask of visually clamped samples; omitted from derivatives.
            limits: Applied bounds used to interpolate horizontal cap segments.
            x_values: Optional actual X coordinates, in original sample order.
            channel_values: Optional (samples, channels) image data, drawn instead
                of the scalar curve. The scalar remains available for 1D export.
            channel_names: Unique R/G/B/M/A channels matching channel_values.
                Bounds and derivatives apply independently to each channel.
            alpha_weighted: Multiply R/G/B/M by normalized A before filtering
                and differentiating. Requires a named A channel, which is shown
                separately in original units. Defaults to False.

        Raises:
            ValueError: Channel names, dimensions or sample coordinates disagree.
        """
        if channel_values is not None:
            if (channel_values.shape != (len(values), len(channel_names)) or not channel_names
                    or len(set(channel_names)) != len(channel_names)
                    or any(channel not in CHANNEL_COLORS for channel in channel_names) or x_values is not None):
                raise ValueError("Image profiles require matching sample/channel arrays and unique R/G/B/M/A channels.")
        elif channel_names:
            raise ValueError("Channel names require image channel values.")
        if alpha_weighted and (channel_values is None or ImageMember.ALPHA not in channel_names):
            raise ValueError("Alpha-weighted profiles require an A channel.")
        shown = values if display_values is None else display_values
        unchanged = self._has_data and self.x_start == x_start and self._limits == limits and self.channel_names == channel_names and self.alpha_weighted == alpha_weighted and all(
            previous is current or (
                previous is not None and current is not None
                and previous.dtype == current.dtype
                and np.array_equal(previous, current, equal_nan=True)
            )
            for previous, current in (
                (self.values, values), (self.valid, valid), (self.x_values, x_values),
                (self.display_values, shown), (self.clipped, clipped),
                (self.channel_values, channel_values),
            )
        )
        self.title.setText(title)
        if unchanged:
            if reset:
                self.view_box.enableAutoRange()
                self.derivative_pane.view_box.enableAutoRange()
            return
        self.values, self.valid = values, valid
        self.channel_values, self.channel_names = channel_values, channel_names
        self.alpha_weighted = alpha_weighted
        self.color_button.setEnabled(not channel_names)
        self.color_button.setToolTip("Image channel colors are fixed by R/G/B/M/A." if channel_names else "Choose the curve color.")
        for pane in (self.signal_pane, self.derivative_pane):
            pane.set_channels(channel_names, alpha_weighted=alpha_weighted)
        self.readout.setToolTip(
            "R/G/B/M are multiplied by normalized alpha before filtering and differentiating; A retains its source value."
            if alpha_weighted else "Channel values use source units."
        )
        self._limits = limits
        self.x_start = x_start
        self.x_values = x_values
        if x_values is not None:
            finite_x = np.flatnonzero(np.isfinite(x_values))
            self._x_order = finite_x[np.argsort(x_values[finite_x], kind="stable")]
            self._sorted_x = np.asarray(x_values[self._x_order], dtype=np.float64)
        for pane in (self.signal_pane, self.derivative_pane):
            pane.plot_item.setLabel("bottom", "X" if x_values is not None else "Index (x)")
        self.display_values = shown
        self.clipped = clipped
        self._clipped_curve = (clip_curve(values, valid, limits, x_start)
                               if channel_values is None and clipped is not None and np.any(clipped) else None)
        if self._clipped_curve is not None and x_values is not None:
            curve = self._clipped_curve
            indices = np.arange(x_start, x_start + len(values), dtype=np.float64)
            coordinates = np.asarray(x_values, dtype=np.float64)
            self._clipped_curve = replace(curve, x=np.interp(curve.x, indices, coordinates),
                                          cap_x=np.interp(curve.cap_x, indices, coordinates))
        if channel_values is None:
            self._traces = (ProfileTrace(None, values, valid, shown, clipped, self._clipped_curve),)
        else:
            alpha = (normalize_image_alpha(channel_values[:, channel_names.index(ImageMember.ALPHA)])
                     if alpha_weighted else None)
            traces: list[ProfileTrace] = []
            for column, channel in enumerate(channel_names):
                samples = channel_values[:, column]
                if alpha is not None and channel != ImageMember.ALPHA:
                    samples = np.asarray(samples, dtype=np.float64) * alpha
                channel_shown, visible, clip_kind = apply_value_limits(samples, np.isfinite(samples), limits)
                bounded = clip_kind != 0
                curve = clip_curve(samples, visible, limits, x_start) if np.any(bounded) else None
                traces.append(ProfileTrace(channel, samples, visible, channel_shown, bounded, curve, alpha_weighted))
            self._traces = tuple(traces)
        self.readout.setText("Move over the curve to inspect a sample")
        self.crosshair.hide()
        self._invalidate_derivative()
        self._redraw()
        if reset or not self._has_data:
            self.view_box.enableAutoRange()
            self._derivative_reset = True
        self._has_data = True

    def set_external_tabs(self, external: bool) -> None:
        """Hide nested tabs when the main viewer controls the selected page.

        Args:
            external: True for standalone signal/XY pages; False restores the
                Signal/Derivative tab bar below the matrix slice controls.
        """
        self._external_tabs = external
        self.tabs.tabBar().setVisible(not external)

    def set_derivative_enabled(self, enabled: bool) -> None:
        """Enable derivative inspection only for ordered signal/profile modes.

        Args:
            enabled: False disables the tab, cancels pending work and clears
                cached derivatives. True restores the tab without opening it
                or computing derivatives until the user selects it.
        """
        # Enabling a Qt tab does not restore its visibility. Explicitly retain
        # both pages and their tab bar when the profile returns to a 1D view.
        self.tabs.setTabBarAutoHide(False)
        self.tabs.setTabVisible(0, True)
        self.tabs.setTabVisible(1, True)
        self.tabs.tabBar().setVisible(not self._external_tabs)
        self.tabs.setTabEnabled(1, enabled)
        if not enabled:
            self._derivative_timer.stop()
            self.tabs.setCurrentIndex(0)
            self._invalidate_derivative()
            self.derivative_note.setText("Derivatives are unavailable in point-cloud mode.")

    def clear_selection(self) -> None:
        """Clear both curves and cancel derivative work after deselection.

        Keeps appearance and derivative settings for the next selected profile.
        """
        self._derivative_timer.stop()
        self.values = None
        self.x_values = None
        self.valid = None
        self.display_values = None
        self.clipped = None
        self._clipped_curve = None
        self.channel_values = None
        self.channel_names = ()
        self.alpha_weighted = False
        self._traces = ()
        self.derivative_result = None
        self.derivative_results.clear()
        self._has_data = False
        self._derivative_reset = True
        self._derivative_dirty = True
        self.signal_pane.clear_curves()
        self.signal_pane.set_channels(())
        self.derivative_pane.set_channels(())
        self.color_button.setEnabled(True)
        self.clip_curve_item.clear()
        self.clip_points_item.clear()
        self.derivative_pane.clear_curves()
        self.undefined_markers.clear()
        self.signal_pane.crosshair.hide()
        self.derivative_pane.crosshair.hide()
        self.title.setText("No selection")
        self.readout.setText("Select a row or column to inspect its profile")
        self.derivative_note.setText("No row or column selected.")

    def reset_view(self) -> None:
        """Fit the current tab without calculating an unopened derivative."""
        pane = self.signal_pane if self.tabs.currentIndex() == 0 else self.derivative_pane
        pane.view_box.enableAutoRange()

    def set_theme(self, dark: bool) -> None:
        """Set plot background and axis colors.

        Args:
            dark: True selects the dark theme.
        """
        self.signal_pane.set_theme(dark)
        self.derivative_pane.set_theme(dark)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Resume pending derivative work when its containing plot becomes visible.

        Args:
            event: Native Qt show event, including return from the raw-data tab.
        """
        super().showEvent(event)
        if (self.values is not None and self.tabs.isTabEnabled(1) and self.tabs.currentIndex() == 1
                and (not self.derivative_results or self._derivative_dirty)):
            self._derivative_timer.start()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        """Pause deferred derivative work while another viewer tab is visible.

        Args:
            event: Native Qt hide event; cached results remain available.
        """
        self._derivative_timer.stop()
        super().hideEvent(event)

    def _redraw(self) -> None:
        if self.values is None or self.valid is None or self.display_values is None:
            return
        mode = CurveStyle(self.style_selector.currentIndex())
        caps_x: list[FloatArray] = []
        caps_y: list[FloatArray] = []
        points_x: list[RealArray] = []
        points_y: list[RealArray] = []
        for trace in self._traces:
            color = QtGui.QColor(CHANNEL_COLORS[trace.channel]) if trace.channel else self.color
            curve = trace.curve
            if curve is not None and mode != CurveStyle.POINTS:
                self.signal_pane.set_samples(curve.y, np.isfinite(curve.y), color, mode,
                                              self.x_start, curve.x, channel=trace.channel)
            else:
                self.signal_pane.set_samples(trace.shown, trace.valid, color, mode,
                                              self.x_start, self.x_values, channel=trace.channel)
            if curve is not None and trace.clipped is not None:
                caps_x.append(curve.cap_x)
                caps_y.append(curve.cap_y)
                marked = trace.clipped.copy()
                if mode == CurveStyle.LINE:
                    # Continuous caps remain solid lines; isolated samples need dots.
                    connected = np.zeros_like(trace.valid)
                    paired = trace.valid[:-1] & trace.valid[1:]
                    connected[:-1] |= paired
                    connected[1:] |= paired
                    marked &= ~connected
                points_x.append(np.flatnonzero(marked) + self.x_start if self.x_values is None else self.x_values[marked])
                points_y.append(trace.shown[marked])
        if caps_x:
            self.clip_curve_item.setData(np.concatenate(caps_x), np.concatenate(caps_y), connect="finite",
                                         pen=pg.mkPen(self.clip_color, width=CLIP_LINE_WIDTH), autoDownsample=False)
            self.clip_points_item.setData(np.concatenate(points_x), np.concatenate(points_y), pen=None, symbol="o",
                                          symbolSize=CLIP_POINT_SIZE, symbolPen=None, symbolBrush=self.clip_color)
        else:
            self.clip_curve_item.clear()
            self.clip_points_item.clear()
        self._derivative_dirty = True
        self._redraw_derivative()

    def _redraw_derivative(self) -> None:
        """Render a changed derivative only when its tab is selected."""
        if not self.isVisible() or not self.derivative_results or not self._derivative_dirty or self.tabs.currentIndex() != 1:
            return
        mode = CurveStyle(self.style_selector.currentIndex())
        markers: list[RealArray] = []
        for channel, result in self.derivative_results.items():
            color = QtGui.QColor(CHANNEL_COLORS[channel]) if channel else self.color
            if self.x_values is None:
                self.derivative_pane.set_samples(result.values, result.valid, color, mode, self.x_start, channel=channel)
                markers.append(result.undefined_indices + self.x_start)
            else:
                # Keep the signal/table in source order; only dy/dx is drawn by X.
                order = self._x_order
                self.derivative_pane.set_samples(result.values[order], result.valid[order], color,
                                                 mode, x_values=self.x_values[order], channel=channel)
                markers.append(self.x_values[result.undefined_indices])
        marker_x = np.concatenate(markers)
        self.undefined_markers.setData(marker_x, np.zeros(len(marker_x)))
        self._derivative_dirty = False

    def set_clip_color(self, color: QtGui.QColor) -> None:
        """Recolor clipping markers without recalculating derivatives.

        Args:
            color: Solid color used by the thick cap lines and clipped samples.
        """
        self.clip_color = color
        self._redraw()

    def _jump_mode_changed(self) -> None:
        mode = JumpMode(self.jump_mode.currentIndex())
        self.jump_threshold.setEnabled(mode == JumpMode.CUSTOM)
        with QtCore.QSignalBlocker(self.jump_threshold):
            if mode == JumpMode.RADIANS:
                self.jump_threshold.setValue(float(np.pi))
            elif mode == JumpMode.DEGREES:
                self.jump_threshold.setValue(180)
        self._invalidate_derivative()

    def _invalidate_derivative(self) -> None:
        self.derivative_result = None
        self.derivative_results.clear()
        self._derivative_dirty = True
        self.derivative_pane.clear_curves()
        self.undefined_markers.clear()
        self.derivative_pane.crosshair.hide()
        self._derivative_timer.stop()
        if self.isVisible() and self.tabs.isTabEnabled(1) and self.tabs.currentIndex() == 1:
            self.readout.setText("Updating derivative…")
            self._derivative_timer.start()

    def _tab_changed(self) -> None:
        self._derivative_timer.stop()
        if self.values is None:
            self.readout.setText("Select a row or column to inspect its profile")
            return
        self.readout.setText("Move over the curve to inspect a sample")
        if self.tabs.currentIndex() == 1:
            self._ensure_derivative()

    def _ensure_derivative(self) -> None:
        if not self.isVisible() or not self.tabs.isTabEnabled(1) or self.tabs.currentIndex() != 1 or self.values is None or self.valid is None:
            return
        if self.derivative_results:
            self._redraw_derivative()
            return
        mode = JumpMode(self.jump_mode.currentIndex())
        threshold: float | None = self.jump_threshold.value()
        if mode == JumpMode.GAPS_ONLY:
            threshold = None
        elif mode == JumpMode.RADIANS:
            threshold = float(np.pi)
        spacing = "sorted actual X" if self.x_values is not None else "sample index (dx=1)"
        threshold_text = "disabled (gaps only)" if threshold is None else f"{threshold:g}"
        results: dict[ImageMember | None, DerivativeResult] = {}
        for trace in self._traces:
            analysis_valid = trace.valid if trace.clipped is None else trace.valid & ~trace.clipped
            source = f"{self.title.text()} / {trace.label}" if trace.channel else self.title.text()
            print(
                f"[Derivative] Computing: {source}; samples={trace.values.size:,}; dtype={trace.values.dtype}; "
                f"sample indices={self.x_start}..{self.x_start + trace.values.size - 1} "
                f"(all indices zero-based); spacing={spacing}; jump threshold={threshold_text}",
                flush=True,
            )
            started = perf_counter()
            result = differentiate(trace.values, analysis_valid, threshold, x_values=self.x_values)
            elapsed_ms = (perf_counter() - started) * 1000
            print(
                f"[Derivative] Finished: {source}; valid={np.count_nonzero(result.valid):,}; "
                f"undefined markers={len(result.undefined_indices):,}; suspected jumps={result.jump_count:,}; "
                f"calculation time={elapsed_ms:.3f} ms",
                flush=True,
            )
            results[trace.channel] = result
        self.derivative_results = results
        self.derivative_result = results.get(None)
        self._redraw_derivative()
        marker_count = sum(len(result.undefined_indices) for result in results.values())
        jump_count = sum(result.jump_count for result in results.values())
        self.derivative_note.setText(
            f"Red dots at y=0: undefined / omitted, not zero. "
            f"{marker_count:,} markers; {jump_count:,} suspected jumps. "
            + ("Sorted by X with actual spacing; repeated X treated as gaps." if self.x_values is not None else "dx=1;")
            + (" Color/gray multiplied by alpha; A in source units; clipped samples omitted."
               if self.alpha_weighted else " Original values, clipped samples omitted.")
            + (" Each channel is differentiated independently; markers can overlap." if self.channel_names else "")
        )
        if self._derivative_reset:
            self.derivative_pane.view_box.enableAutoRange()
            self._derivative_reset = False

    def _choose_color(self) -> None:
        chosen = QtWidgets.QColorDialog.getColor(self.color, self, "Curve color")
        if chosen.isValid():
            self.color = chosen
            self._redraw()

    def _hover(self, position: QtCore.QPointF) -> None:
        self._inspect(position, self.signal_pane, derivative=False)

    def _hover_derivative(self, position: QtCore.QPointF) -> None:
        self._inspect(position, self.derivative_pane, derivative=True)

    def _inspect(self, position: QtCore.QPointF, pane: CurvePane, *, derivative: bool) -> None:
        if self.values is None or self.valid is None or not pane.plot_item.sceneBoundingRect().contains(position.x(), position.y()):
            pane.crosshair.hide()
            return
        point = pane.view_box.mapSceneToView(position)
        if self.x_values is None:
            source_index = int(np.floor(point.x() + 0.5))
            index = source_index - self.x_start
        else:
            if not len(self._sorted_x) or not self._sorted_x[0] <= point.x() <= self._sorted_x[-1]:
                pane.crosshair.hide()
                self.readout.setText("Outside signal")
                return
            insert = int(np.searchsorted(self._sorted_x, point.x()))
            candidates = [min(insert, len(self._sorted_x) - 1), max(0, insert - 1)]
            nearest = min(candidates, key=lambda item: abs(float(self._sorted_x[item]) - point.x()))
            index = int(self._x_order[nearest])
            source_index = index + self.x_start
        if not 0 <= index < len(self.values):
            pane.crosshair.hide()
            self.readout.setText("Outside signal")
            return
        source_x = str(source_index) if self.x_values is None else format_sample(self.x_values, index)
        pane.crosshair.setValue(source_index if self.x_values is None else float(self.x_values[index]))
        pane.crosshair.show()
        if self.channel_names:
            readings: list[str] = []
            full_readings: list[str] = []
            for trace in self._traces:
                if derivative:
                    result = self.derivative_results.get(trace.channel)
                    if result is not None:
                        value = _compact_sample(result.values, index) if result.valid[index] else "undefined"
                        full_value = format_sample(result.values, index) if result.valid[index] else "undefined"
                        quantity = f"({trace.label})" if trace.alpha_weighted and trace.channel != ImageMember.ALPHA else trace.label
                        readings.append(f"d{quantity}/dx={value}")
                        full_readings.append(f"d{quantity}/dx={full_value}")
                else:
                    suffix = " [filtered]" if not trace.valid[index] else ""
                    if trace.clipped is not None and trace.clipped[index]:
                        suffix = f" [clamped to {format_sample(trace.shown, index)}]"
                    readings.append(f"{trace.label}={_compact_sample(trace.values, index)}{suffix}")
                    full_readings.append(f"{trace.label}={format_sample(trace.values, index)}{suffix}")
            self.readout.setText(f"x={source_x}   {'   '.join(readings)}")
            self.readout.setToolTip("\n".join((f"x={source_x}", *full_readings)))
            return
        if derivative:
            result = self.derivative_result
            if result is not None:
                value = format_sample(result.values, index) if result.valid[index] else "undefined / omitted"
                self.readout.setText(f"x={source_x}   dy/dx={value}   [sample {source_index}]")
            return
        suffix = "  [filtered / nonfinite]" if not self.valid[index] else ""
        if self.clipped is not None and self.clipped[index] and self.display_values is not None:
            suffix = f"  [clamped to {format_sample(self.display_values, index)}]"
        self.readout.setText(f"x={source_x}   y={format_sample(self.values, index)}{suffix}   [sample {source_index}]")
