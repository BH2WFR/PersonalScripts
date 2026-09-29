"""Signal/profile plots with an optional, lazily computed derivative tab.

Actual derivative calculations print their source, sample indices and timing;
cached tab revisits do not emit calculation diagnostics.

Requirements: PySide6, pyqtgraph and numpy.
Usage: embedded below matrix views or used alone for signal data.
"""

from enum import IntEnum
from dataclasses import replace
from time import perf_counter

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox

from .data_model import DEFAULT_CLIP_COLOR, FloatArray, Limits, RealArray, BoolArray, format_sample
from .clipping import ClippedCurve, clip_curve
from .derivatives import DerivativeResult, differentiate
from .plot_support import graphics_scene, pyside_graphics_view

WHEEL_ZOOM_FACTOR = 1.15
DERIVATIVE_DELAY_MS = 70
UNDEFINED_COLOR = "#e53935"
CLIP_LINE_WIDTH = 4
CLIP_POINT_SIZE = 6


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


class CurvePane(QtWidgets.QWidget):
    """One curve canvas with matching zoom behavior and a movable crosshair.

    Args:
        y_label: Label describing the vertical quantity.
        parent: Optional owning widget.
    """

    def __init__(self, y_label: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.view_box = ProfileViewBox()
        self.plot_item = PlotItem(viewBox=self.view_box)
        self.plot = pg.PlotWidget(plotItem=self.plot_item)
        self.plot_item.setMenuEnabled(False)
        self.plot_item.setLabel("bottom", "Index (x)")
        self.plot_item.setLabel("left", y_label)
        self.plot_item.showGrid(x=True, y=True, alpha=0.2)
        self.view_box.setMouseMode(ViewBox.PanMode)
        self.curve = pg.PlotDataItem()
        self.plot_item.addItem(self.curve)
        self.crosshair = pg.InfiniteLine(angle=90, pen=pg.mkPen("#9c9c9c", style=QtCore.Qt.PenStyle.DashLine))
        self.plot_item.addItem(self.crosshair, ignoreBounds=True)
        self.crosshair.hide()
        self.native_view = pyside_graphics_view(self.plot)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.native_view)
        self.setToolTip("Wheel: zoom X only. Ctrl+wheel: zoom X and Y. Left drag: pan.")

    def set_samples(self, values: RealArray, valid: BoolArray,
                    color: QtGui.QColor, mode: CurveStyle, x_start: int = 0,
                    x_values: RealArray | None = None) -> None:
        """Render samples with gaps, optional markers and a common curve style.

        Args:
            values: One-dimensional sample values.
            valid: Same-length visibility mask.
            color: Line and marker color.
            mode: Line, points or both.
            x_start: Source index of the first sample; defaults to zero.
            x_values: Optional coordinates including interpolated clip crossings.
        """
        y = np.where(valid, values, np.nan)
        ordered = x_values is None or bool(np.all(np.isfinite(x_values)) and np.all(x_values[1:] >= x_values[:-1]))
        self.curve.setData(
            np.arange(x_start, x_start + len(y)) if x_values is None else x_values, y, connect="finite",
            pen=pg.mkPen(color, width=1) if mode != CurveStyle.POINTS else None,
            symbol="o" if mode != CurveStyle.LINE or len(y) == 1 else None,
            symbolSize=5, symbolBrush=color, symbolPen=None,
            autoDownsample=ordered and bool(np.all(valid)), downsampleMethod="peak", clipToView=ordered,
        )

    def set_theme(self, dark: bool) -> None:
        """Change only this plotting canvas and axes, leaving Qt widgets native.

        Args:
            dark: True selects a dark plot background.
        """
        self.plot.setBackground("#151b25" if dark else "#ffffff")
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
        self.clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        self.color = QtGui.QColor("#48b9ff")
        self._has_data = False
        self._derivative_reset = True
        self._derivative_dirty = True
        self._limits = Limits()
        self.derivative_result: DerivativeResult | None = None
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
        color_button = QtWidgets.QPushButton("Line color")
        color_button.clicked.connect(self._choose_color)
        bar.addWidget(color_button)
        fit = QtWidgets.QPushButton("Fit curve")
        fit.clicked.connect(self.reset_view)
        bar.addWidget(fit)
        bar.addStretch()
        self.readout = QtWidgets.QLabel("Move over the curve to inspect a sample")
        self.readout.setMinimumWidth(190)
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        bar.addWidget(self.readout)
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
                 limits: Limits = Limits(), x_values: RealArray | None = None) -> None:
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
        """
        shown = values if display_values is None else display_values
        unchanged = self._has_data and self.x_start == x_start and self._limits == limits and all(
            previous is current or (
                previous is not None and current is not None
                and previous.dtype == current.dtype
                and np.array_equal(previous, current, equal_nan=True)
            )
            for previous, current in (
                (self.values, values), (self.valid, valid), (self.x_values, x_values),
                (self.display_values, shown), (self.clipped, clipped),
            )
        )
        self.title.setText(title)
        if unchanged:
            if reset:
                self.view_box.enableAutoRange()
                self.derivative_pane.view_box.enableAutoRange()
            return
        self.values, self.valid = values, valid
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
        self._clipped_curve = clip_curve(values, valid, limits, x_start) if clipped is not None and np.any(clipped) else None
        if self._clipped_curve is not None and x_values is not None:
            curve = self._clipped_curve
            indices = np.arange(x_start, x_start + len(values), dtype=np.float64)
            coordinates = np.asarray(x_values, dtype=np.float64)
            self._clipped_curve = replace(curve, x=np.interp(curve.x, indices, coordinates),
                                          cap_x=np.interp(curve.cap_x, indices, coordinates))
        self.readout.setText("Move over the curve to inspect a sample")
        self.crosshair.hide()
        self._invalidate_derivative()
        self._redraw()
        if reset or not self._has_data:
            self.view_box.enableAutoRange()
            self._derivative_reset = True
        self._has_data = True

    def set_derivative_enabled(self, enabled: bool) -> None:
        """Enable derivative inspection only for ordered signal/profile modes.

        Args:
            enabled: False disables the tab, cancels pending work and clears
                cached derivatives. True restores the tab without opening it
                or computing derivatives until the user selects it.
        """
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
        self.derivative_result = None
        self._has_data = False
        self._derivative_reset = True
        self._derivative_dirty = True
        self.signal_pane.curve.clear()
        self.clip_curve_item.clear()
        self.clip_points_item.clear()
        self.derivative_pane.curve.clear()
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

    def _redraw(self) -> None:
        if self.values is None or self.valid is None or self.display_values is None:
            return
        mode = CurveStyle(self.style_selector.currentIndex())
        clipped_curve = self._clipped_curve
        if clipped_curve is not None and mode != CurveStyle.POINTS:
            self.signal_pane.set_samples(clipped_curve.y, np.isfinite(clipped_curve.y), self.color,
                                          mode, self.x_start, clipped_curve.x)
        else:
            self.signal_pane.set_samples(self.display_values, self.valid, self.color, mode, self.x_start, self.x_values)
        if clipped_curve is not None and self.clipped is not None:
            self.clip_curve_item.setData(clipped_curve.cap_x, clipped_curve.cap_y, connect="finite",
                                         pen=pg.mkPen(self.clip_color, width=CLIP_LINE_WIDTH), autoDownsample=False)
            marked = self.clipped.copy()
            if mode == CurveStyle.LINE:
                # Continuous caps remain solid lines; isolated samples need dots.
                connected = np.zeros_like(self.valid)
                paired = self.valid[:-1] & self.valid[1:]
                connected[:-1] |= paired
                connected[1:] |= paired
                marked &= ~connected
            marked_x = np.flatnonzero(marked) + self.x_start if self.x_values is None else self.x_values[marked]
            self.clip_points_item.setData(marked_x,
                                          self.display_values[marked], pen=None, symbol="o",
                                          symbolSize=CLIP_POINT_SIZE, symbolPen=None, symbolBrush=self.clip_color)
        else:
            self.clip_curve_item.clear()
            self.clip_points_item.clear()
        self._derivative_dirty = True
        self._redraw_derivative()

    def _redraw_derivative(self) -> None:
        """Render a changed derivative only when its tab is selected."""
        result = self.derivative_result
        if result is None or not self._derivative_dirty or self.tabs.currentIndex() != 1:
            return
        mode = CurveStyle(self.style_selector.currentIndex())
        if self.x_values is None:
            self.derivative_pane.set_samples(result.values, result.valid, self.color, mode, self.x_start)
            marker_x = result.undefined_indices + self.x_start
        else:
            # Keep the signal/table in source order; only dy/dx is drawn by X.
            order = self._x_order
            self.derivative_pane.set_samples(result.values[order], result.valid[order], self.color,
                                             mode, x_values=self.x_values[order])
            marker_x = self.x_values[result.undefined_indices]
        self.undefined_markers.setData(marker_x, np.zeros(len(result.undefined_indices)))
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
        self._derivative_dirty = True
        self.derivative_pane.curve.clear()
        self.undefined_markers.clear()
        self.derivative_pane.crosshair.hide()
        self._derivative_timer.stop()
        if self.tabs.isTabEnabled(1) and self.tabs.currentIndex() == 1:
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
        if not self.tabs.isTabEnabled(1) or self.tabs.currentIndex() != 1 or self.values is None or self.valid is None:
            return
        if self.derivative_result is not None:
            self._redraw_derivative()
            return
        mode = JumpMode(self.jump_mode.currentIndex())
        threshold: float | None = self.jump_threshold.value()
        if mode == JumpMode.GAPS_ONLY:
            threshold = None
        elif mode == JumpMode.RADIANS:
            threshold = float(np.pi)
        analysis_valid = self.valid if self.clipped is None else self.valid & ~self.clipped
        source = self.title.text()
        spacing = "sorted actual X" if self.x_values is not None else "sample index (dx=1)"
        threshold_text = "disabled (gaps only)" if threshold is None else f"{threshold:g}"
        print(
            f"[Derivative] Computing: {source}; samples={self.values.size:,}; dtype={self.values.dtype}; "
            f"sample indices={self.x_start}..{self.x_start + self.values.size - 1} "
            f"(all indices zero-based); spacing={spacing}; jump threshold={threshold_text}",
            flush=True,
        )
        started = perf_counter()
        result = differentiate(self.values, analysis_valid, threshold, x_values=self.x_values)
        elapsed_ms = (perf_counter() - started) * 1000
        print(
            f"[Derivative] Finished: {source}; valid={np.count_nonzero(result.valid):,}; "
            f"undefined markers={len(result.undefined_indices):,}; suspected jumps={result.jump_count:,}; "
            f"calculation time={elapsed_ms:.3f} ms",
            flush=True,
        )
        self.derivative_result = result
        self._redraw_derivative()
        self.derivative_note.setText(
            f"Red dots at y=0: undefined / omitted, not zero. "
            f"{len(result.undefined_indices):,} markers; {result.jump_count:,} suspected jumps. "
            + ("Sorted by X with actual spacing; repeated X treated as gaps." if self.x_values is not None else "dx=1;")
            + " Original values, clipped samples omitted."
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
