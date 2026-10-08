"""Shared signal/slice curves with lazy, per-matrix derivative caches.

Requirements: numpy, PySide6 and pyqtgraph. Usage: embedded in the workspace;
uses the ordinary profile's controls, zoom behavior and compact numeric axes.
"""

from time import perf_counter

import numpy as np
from PySide6 import QtCore, QtGui
import pyqtgraph as pg

from .clipping import clip_curve
from .data_model import FloatArray, RealArray
from .derivatives import DerivativeResult, differentiate
from .profile_view import CurvePane, CurveStyle, ProfileView, _compact_sample
from .workspace import ProfileSeries


class OverlayProfile(ProfileView):
    """Overlay independent matrices while retaining the normal profile controls."""

    settings_changed = QtCore.Signal()

    def __init__(self) -> None:
        self._series: tuple[ProfileSeries, ...] = ()
        self._cache: dict[tuple[object, ...], DerivativeResult] = {}
        self._drawn: list[tuple[object, ...] | None] = [None, None]
        self._items: list[list[pg.PlotDataItem]] = [[], []]
        super().__init__()
        self.color_button.hide()
        self.title.setText("Overlay")
        self.derivative_note.setText("Derivatives use original X coordinates; red dots mark undefined samples.")
        self.jump_mode.setToolTip("Derivative settings for the selected matrix only.")
        self.jump_threshold.setToolTip("Jump threshold for the selected matrix only.")

    def set_series(self, series: tuple[ProfileSeries, ...], reset: bool = False) -> None:
        """Update visible series without calculating derivatives on hidden pages.

        Args:
            series: Original samples and their display-only alignment.
            reset: Fit the currently visible curve canvas.
        """
        self._series = series
        self.title.setText("Overlay")
        self.legend_bar.set_entries(tuple((item.label, item.layer.color) for item in series))
        physical = bool(series and (series[0].layer.frame.x_grid is not None or series[0].layer.frame.y_grid is not None))
        for pane in (self.signal_pane, self.derivative_pane):
            pane.plot_item.getAxis("bottom").enableAutoSIPrefix(not physical)
        active = {item.key for item in series}
        self._cache = {key: value for key, value in self._cache.items() if key in active}
        self._draw_signal()
        if self.isVisible() and self.tabs.currentIndex() == 1:
            self._derivative_timer.start()
        if reset:
            self.reset_view()

    def clear_selection(self) -> None:
        """Clear overlay curves and derivative caches after deselection."""
        self._derivative_timer.stop()
        self._cache.clear()
        self.set_series(())
        self._draw_derivatives()

    def _signature(self) -> tuple[object, ...]:
        return (self.style_selector.currentIndex(), *(
            (series.key, series.mapping, series.layer.color, series.layer.clip_color, series.label)
            for series in self._series))

    def _clear_pane(self, pane: CurvePane, index: int) -> None:
        for item in self._items[index]:
            pane.plot_item.removeItem(item)
        self._items[index].clear()
        pane.curve.hide()

    def _curve(self, pane: CurvePane, index: int, x: FloatArray, y: RealArray,
               color: str, name: str | None = None, *, cap: bool = False) -> None:
        mode = CurveStyle(self.style_selector.currentIndex())
        points = mode != CurveStyle.LINE or len(x) == 1
        curve = pg.PlotDataItem(x=x, y=y, name=name, connect="finite",
            pen=pg.mkPen(color, width=3 if cap else 1) if cap or mode != CurveStyle.POINTS else None,
            symbol="o" if points else None, symbolSize=6 if cap else 5,
            symbolBrush=color, symbolPen=None)
        pane.plot_item.addItem(curve)
        self._items[index].append(curve)

    def _draw_signal(self) -> None:
        signature = self._signature()
        if signature == self._drawn[0]:
            return
        pane = self.signal_pane
        self._clear_pane(pane, 0)
        pane.plot_item.setLabel("bottom", self._axis_label())
        for series in self._series:
            x = series.mapping.array(series.source_x)
            y = np.where(series.valid, series.shown, np.nan)
            if np.any(series.clipped):
                capped = clip_curve(series.values, series.valid, series.layer.frame.value_limits, 0)
                indices = np.arange(len(series.values), dtype=np.float64)
                x = series.mapping.array(np.interp(capped.x, indices, series.source_x))
                y = capped.y
                self._curve(pane, 0, x, y, series.layer.color, series.label)
                cap_x = series.mapping.array(np.interp(capped.cap_x, indices, series.source_x))
                self._curve(pane, 0, cap_x, capped.cap_y, series.layer.clip_color, cap=True)
            else:
                self._curve(pane, 0, x, y, series.layer.color, series.label)
        self._drawn[0] = signature

    def _redraw(self) -> None:
        self._draw_signal()
        if self.isVisible() and self.tabs.currentIndex() == 1:
            self._draw_derivatives()

    def _invalidate_derivative(self) -> None:
        # Settings belong to the selected entry; its owner supplies an updated
        # snapshot. Unaffected matrices retain their numeric derivative caches.
        self.settings_changed.emit()

    def _tab_changed(self) -> None:
        self._derivative_timer.stop()
        self.readout.setText("Move over a curve to inspect its matrix and source coordinates")
        if self.tabs.currentIndex() == 1:
            self._ensure_derivative()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Resume pending derivative work only when this profile is visible."""
        super().showEvent(event)
        if self.tabs.currentIndex() == 1:
            self._derivative_timer.start()

    def _ensure_derivative(self) -> None:
        if not self.isVisible() or self.tabs.currentIndex() != 1 or not self.tabs.isTabEnabled(1):
            return
        for series in self._series:
            if series.key in self._cache:
                continue
            started = perf_counter()
            print(f"[Derivative] Computing: {series.label}; samples={len(series.values):,}; "
                  f"spacing=original X; jump threshold={series.layer.threshold}", flush=True)
            result = differentiate(series.values, series.valid & ~series.clipped,
                                   series.layer.threshold, x_values=series.source_x)
            self._cache[series.key] = result
            print(f"[Derivative] Finished: {series.label}; undefined={len(result.undefined_indices):,}; "
                  f"calculation time={(perf_counter() - started) * 1000:.3f} ms", flush=True)
        self._draw_derivatives()

    def _draw_derivatives(self) -> None:
        signature = self._signature()
        if signature == self._drawn[1] or any(series.key not in self._cache for series in self._series):
            return
        pane = self.derivative_pane
        self._clear_pane(pane, 1)
        pane.plot_item.setLabel("bottom", self._axis_label())
        markers: list[FloatArray] = []
        for series in self._series:
            result = self._cache[series.key]
            order = np.argsort(series.source_x, kind="stable")
            x = series.mapping.array(series.source_x)
            y = np.where(result.valid, result.values, np.nan)
            self._curve(pane, 1, x[order], y[order], series.layer.color, series.label)
            markers.append(x[result.undefined_indices])
        points = np.concatenate(markers) if markers else np.empty(0)
        self.undefined_markers.setData(points, np.zeros(len(points)))
        self._drawn[1] = signature

    def _axis_label(self) -> str:
        if self._series:
            first = self._series[0]
            grid = first.layer.frame.x_grid if first.row else first.layer.frame.y_grid
            if grid is not None:
                return f"{grid.label('X' if first.row else 'Y')} (aligned; derivative uses source coordinates)"
        return "Display X (aligned; derivative uses source X)"

    def _hover_series(self, position: QtCore.QPointF, derivative: bool) -> None:
        pane = self.derivative_pane if derivative else self.signal_pane
        if not pane.plot_item.sceneBoundingRect().contains(position.x(), position.y()):
            return
        point = pane.view_box.mapSceneToView(position)
        pane.crosshair.setValue(point.x())
        pane.crosshair.show()
        labels = [f"Display X={point.x():.6g}"]
        nearest: tuple[float, str, str] | None = None
        for series in self._series:
            source_x = np.asarray(series.source_x, dtype=np.float64)
            finite = np.flatnonzero(np.isfinite(source_x))
            if not len(finite):
                continue
            target = series.mapping.inverse(point.x())
            if target < np.min(source_x[finite]) or target > np.max(source_x[finite]):
                continue
            index = int(finite[np.argmin(np.abs(source_x[finite] - target))])
            result = self._cache.get(series.key)
            value = (f"dy/dx={result.values[index]:.8g}" if result is not None and result.valid[index] else "undefined") if derivative else f"Y={_compact_sample(series.values, index)}"
            reading = f"X={_compact_sample(series.source_x, index)}, {value}"
            labels.append(f"{series.label}: source {reading}")
            shown = (float(result.values[index]) if result is not None and result.valid[index] else float("nan")) if derivative else float(series.shown[index])
            distance = abs(shown - point.y()) if np.isfinite(shown) and series.valid[index] else float("inf")
            if nearest is None or distance < nearest[0]:
                nearest = (distance, series.label, reading)
        if nearest is None:
            self.readout.setText(labels[0])
        else:
            name = self.readout.fontMetrics().elidedText(nearest[1], QtCore.Qt.TextElideMode.ElideMiddle, self.readout.width())
            self.readout.setText(f"{name}\n{nearest[2]}")
        self.readout.setToolTip("\n".join(labels))

    def _hover(self, position: QtCore.QPointF) -> None:
        self._hover_series(position, False)

    def _hover_derivative(self, position: QtCore.QPointF) -> None:
        self._hover_series(position, True)
