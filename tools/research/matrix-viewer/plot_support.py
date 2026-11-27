"""Checked PySide6 boundaries and compact, automatically measured plot axes.

Requirements: PySide6 and pyqtgraph.
Usage: viewer widgets use these checks before embedding a graph or connecting
its extended scene signals. No global type-checker overrides are required.
Range captions distinguish source infinities from finite display bounds, which
remain governed by manual range and lock settings.
Axis footer captions follow the X-title row and reflow with exported plots.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast

from PySide6 import QtCore, QtGui, QtWidgets
from pyqtgraph.Qt import QtCore as GraphQtCore
from pyqtgraph.GraphicsScene.GraphicsScene import GraphicsScene
from pyqtgraph.graphicsItems.AxisItem import AxisItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem

AXIS_TICK_TEXT_OFFSET = 2
PAN_MARGIN_PIXELS = 10.0
type LineSpec = tuple[QtGui.QPen, QtCore.QPointF, QtCore.QPointF]
type TextSpec = tuple[QtCore.QRectF, int, str]
type AxisSpecs = tuple[LineSpec, list[LineSpec], list[TextSpec]]
type PlotBounds = tuple[tuple[float, float], tuple[float, float]]


def minimum_axis_pixels(fitted_pixels: float) -> float:
    """Return the zoom-out floor for a full data axis, in Qt logical pixels."""
    return min(30.0, fitted_pixels / 2)


@dataclass
class NavigationLimits:
    """Mouse navigation preferences shared by the plots in one workspace."""

    zoom_out: bool = True
    pan: bool = True


class NavigationViewBox(ViewBox):
    """Bound interactive scale/translation using full data bounds, independent of manual ranges."""

    def __init__(self, bounds: Callable[[], PlotBounds | None], *, fit_padding: float | None = None,
                 constrain_after_zoom: bool = False) -> None:
        self.navigation = NavigationLimits()
        self._navigation_bounds = bounds
        self._fit_padding = fit_padding
        self._constrain_after_zoom = constrain_after_zoom
        self._sample_pitch: tuple[float, float | None] | None = None
        self._sample_target: GraphQtCore.QRectF | None = None
        super().__init__()
        self.sigResized.connect(self._reflow_sample_size)

    def set_sample_size(self, dx: float, dy: float | None) -> None:
        """Set coordinates per physical pixel, keeping the center as axis labels reflow."""
        view = self.getViewWidget()
        if view is None:
            raise RuntimeError("Sample scaling requires a plot attached to a graphics view.")
        viewport = view.viewport()
        if self._sample_pitch is None:
            viewport.installEventFilter(self)
        dpr = viewport.devicePixelRatioF()
        center = self.viewRect().center()
        half_x = self.width() * dpr * dx / 2
        half_y = self.height() * dpr * dy / 2 if dy is not None else None
        self._sample_target = None
        self.setRange(xRange=(center.x() - half_x, center.x() + half_x),
                      yRange=(center.y() - half_y, center.y() + half_y) if half_y is not None else None,
                      padding=0)
        self._sample_pitch = (dx, dy)
        self._sample_target = self.targetRect()

    def _reflow_sample_size(self) -> None:
        if self._sample_target is None or self._sample_pitch is None or self.signalsBlocked():
            return
        previous, current = self._sample_target, self.targetRect()
        if (previous.left() != current.left() or previous.right() != current.right()
                or (self._sample_pitch[1] is not None and previous != current)
                or self.state["autoRange"][0]):
            self._sample_target = None
        elif self.width() > 0 and self.height() > 0:
            self.set_sample_size(*self._sample_pitch)

    def eventFilter(self, a0: GraphQtCore.QObject | None, a1: GraphQtCore.QEvent | None) -> bool:
        if (a1 is not None and a1.type() == GraphQtCore.QEvent.Type.DevicePixelRatioChange
                and self._sample_target is not None):
            self._reflow_sample_size()
        return super().eventFilter(a0, a1)

    def _zoom_caps(self, bounds: PlotBounds) -> tuple[float, float]:
        """Measure each axis at the current and fully fitted scales, accounting for aspect lock."""
        lengths = []
        fit_factors = []
        for axis, ((lo, hi), (left, right), pixels) in enumerate(zip(bounds, self.viewRange(),
                                                                     (self.width(), self.height()))):
            length = pixels * ((hi - lo) / (right - left)) if right > left else 0.0
            lengths.append(length)
            padding = self.suggestPadding(axis) if self._fit_padding is None else self._fit_padding
            fit_factors.append(pixels / ((1 + 2 * padding) * length) if length > 0 else math.inf)
        locked = self.state["aspectLocked"] is not False
        if locked:
            fit_factors = [min(fit_factors)] * 2
        caps = [length / minimum_axis_pixels(length * fit) if length > 0 and fit > 0 else math.inf
                for length, fit in zip(lengths, fit_factors)]
        return (min(caps), min(caps)) if locked else (caps[0], caps[1])

    def scaleBy(self, s: Sequence[float | None] | None = None, center: QtCore.QPointF | None = None,
                x: float | None = None, y: float | None = None) -> None:
        if s is not None:
            x, y = s
        if self.navigation.zoom_out and any(f is not None and f > 1 for f in (x, y)):
            bounds = self._navigation_bounds()
            if bounds is not None:
                caps = self._zoom_caps(bounds)
                x = min(x, caps[0]) if x is not None and x > 1 else x
                y = min(y, caps[1]) if y is not None and y > 1 else y
        super().scaleBy(center=center, x=x, y=y)
        if self._constrain_after_zoom and self.navigation.pan:
            self.translateBy(x=0.0, y=0.0)

    def translateBy(self, t: QtCore.QPointF | Sequence[float] | None = None, x: float | None = None,
                    y: float | None = None) -> None:
        if isinstance(t, QtCore.QPointF):
            x, y = t.x(), t.y()
        elif t is not None:
            x, y = t
        bounds = self._navigation_bounds() if self.navigation.pan else None
        if bounds is not None:
            shifts = []
            for shift, (lo, hi), (left, right), pixels in zip((x, y), bounds, self.viewRange(),
                                                              (self.width(), self.height())):
                first, last = sorted((lo - left, hi - right))
                margin = min(PAN_MARGIN_PIXELS * (right - left) / max(1.0, pixels),
                             (hi - lo) / 2, (right - left) / 2)
                shifts.append(None if shift is None else min(max(shift, first - margin), last + margin))
            x, y = shifts
        if x or y:
            self._resetTarget()
            super().translateBy(x=x, y=y)


def range_endpoint(value: float, infinite: bool, *, maximum: bool, precision: int = 10,
                   has_finite: bool = True) -> str:
    """Annotate an infinite source extreme with its finite display bound."""
    finite = f"{value:.{precision}g}" if has_finite else "N/A"
    return f"{'inf' if maximum else '-inf'} ({finite})" if infinite else finite


def range_texts(limits: tuple[float, float], infinite: tuple[bool, bool], *,
                has_finite: bool = True, precision: int = 10) -> tuple[str, str]:
    """Return maximum/minimum captions, including entirely nonfinite samples."""
    if not has_finite:
        maximum = "inf (N/A)" if infinite[1] else "-inf (N/A)" if infinite[0] else "N/A"
        minimum = "-inf (N/A)" if infinite[0] else "inf (N/A)" if infinite[1] else "N/A"
        return maximum, minimum
    return (range_endpoint(limits[1], infinite[1], maximum=True, precision=precision),
            range_endpoint(limits[0], infinite[0], maximum=False, precision=precision))


class RangeLabel(QtWidgets.QLabel):
    """Single-line range in a view's information strip, using the UI font."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Fixed)

    def set_limits(self, limits: tuple[float, float] | None,
                   infinite: tuple[bool, bool] = (False, False), *, has_finite: bool = True) -> None:
        """Show finite min/max bounds together, or clear an unavailable range."""
        text = ""
        if limits is not None and all(math.isfinite(value) for value in limits):
            maximum, minimum = range_texts(limits, infinite, has_finite=has_finite)
            text = f"{self.title} max:{maximum} min:{minimum}"
        self.setText(text)
        self.setToolTip(f"{text}\nParentheses show finite display bounds; infinity describes source samples."
                        if any(infinite) else text)


class AxisFooterLabel(QtWidgets.QGraphicsObject):
    """Right-aligned plot note on the X-title row, including image exports.

    Args:
        plot: Owning plot; the note never participates in data auto-ranging.
    """

    def __init__(self, plot: PlotItem) -> None:
        parent: object = plot
        if not isinstance(parent, QtWidgets.QGraphicsWidget):
            raise TypeError("Axis footer labels require a PySide6 plot.")
        super().__init__(parent)
        self.plot = plot
        self._text = ""
        self.setZValue(1000)
        parent.geometryChanged.connect(self._resized)

    def _resized(self) -> None:
        self.prepareGeometryChange()
        self.update()

    def text(self) -> str:
        """Return the full caption, including text elided in a narrow view."""
        return self._text

    def setText(self, text: str) -> None:
        """Set a caption without changing the plot's layout or data bounds."""
        self._text = text
        self.update()

    def clear(self) -> None:
        """Remove a previously calculated caption."""
        self.setText("")

    def boundingRect(self) -> QtCore.QRectF:
        """Cover the plot so axis layout and export resizing remain dynamic."""
        return cast(QtCore.QRectF, self.plot.boundingRect())

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
              widget: QtWidgets.QWidget | None = None) -> None:
        """Align with the actual X title; elide before overlapping its text."""
        axis = self.plot.getAxis("bottom")
        title = axis.label
        title_rect = title.mapRectToItem(self, title.boundingRect())
        area = self.boundingRect()
        left = title_rect.right() + AXIS_TICK_TEXT_OFFSET
        width = max(0.0, area.right() - AXIS_TICK_TEXT_OFFSET - left)
        painter.save()
        painter.setFont(title.font())
        painter.setPen(axis.textPen())
        height = painter.fontMetrics().height()
        rect = QtCore.QRectF(left, title_rect.center().y() - height / 2, width, height)
        text = painter.fontMetrics().elidedText(self._text, QtCore.Qt.TextElideMode.ElideRight, int(width))
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class _AxisTickStyle(TypedDict):
    showValues: bool
    tickLength: int
    tickTextOffset: Sequence[int]


class EndpointAxis(AxisItem):
    """Vertical automatic axis with optional, collision-free endpoint labels.

    The option defaults off. When enabled, range endpoints replace nearby tick
    labels, stay inside the axis rectangle, and participate in width measuring.
    Viewport limits, data and ordinary interior ticks remain unchanged.
    """

    def __init__(self, orientation: str) -> None:
        self.endpoint_ticks = False
        super().__init__(orientation)

    def set_endpoint_ticks(self, enabled: bool) -> None:
        """Toggle endpoint annotations and invalidate the cached axis picture."""
        self.endpoint_ticks = enabled
        self.setStyle(autoReduceTextSpace=not enabled)
        self.picture = None
        self.update()

    def generateDrawSpecs(self, p: QtGui.QPainter) -> AxisSpecs | None:
        """Add exact endpoint texts to native QtGraph specs, including exports."""
        # QtGraph can type its Qt objects against another installed binding;
        # the application selects PySide6 before importing it.
        specs = cast(AxisSpecs | None, super().generateDrawSpecs(p))
        # AxisItem stores instance data under the inherited Qt method names style and scale.
        style = cast(_AxisTickStyle, self.style)
        if (specs is None or not self.endpoint_ticks or self.logMode
                or self.orientation not in ("left", "right") or not style["showValues"]):
            return specs
        bounds = self.mapRectFromParent(self.geometry())
        values = self.range
        if not all(math.isfinite(value) for value in values) or values[0] == values[1]:
            return specs
        axis_line, ticks, texts = specs
        offset = max(0, style["tickLength"]) + style["tickTextOffset"][0]
        scale = self.autoSIPrefixScale * cast(float, self.scale)
        endpoints: list[TextSpec] = []
        for value, top in ((values[1], True), (values[0], False)):
            text = f"{value * scale:.10g}"
            size = p.fontMetrics().boundingRect(text)
            width, height = float(size.width() + 2), float(size.height())
            x = bounds.right() - offset - width if self.orientation == "left" else bounds.left() + offset
            y = bounds.top() if top else bounds.bottom() - height
            rect = QtCore.QRectF(x, y, width, height)
            flags = QtCore.Qt.AlignmentFlag.AlignVCenter | (
                QtCore.Qt.AlignmentFlag.AlignRight if self.orientation == "left" else QtCore.Qt.AlignmentFlag.AlignLeft)
            endpoints.append((rect, int(flags), text))
        self._updateMaxTextSize(math.ceil(max(rect.width() for rect, _, _ in endpoints)))
        texts = [spec for spec in texts if not any(
            rect.adjusted(-2, -2, 2, 2).intersects(spec[0]) for rect, _, _ in endpoints)]
        return axis_line, ticks, [*texts, *endpoints]


class RangeNotes(QtWidgets.QGraphicsObject):
    """Compact range notes in viewport corners, independent of axis ticks.

    Paint in viewport pixels, including PNG/SVG export reflows. This item is
    outside the data transform and never contributes to automatic data bounds.
    """

    def __init__(self, view: ViewBox, label: str, *, follow_y: bool = False,
                 footer: PlotItem | None = None) -> None:
        parent: object = view if footer is None else footer
        if not isinstance(parent, QtWidgets.QGraphicsWidget):
            raise TypeError("Range notes require a PySide6 viewport.")
        super().__init__(parent)
        self.view, self.label, self.follow_y = view, label, follow_y
        self.footer = footer
        self.limits: tuple[float, float] | None = None
        self.infinite_extrema = (False, False)
        self.has_finite = True
        self.data_extrema: tuple[str, str] | None = None
        self.dark = False
        self.setZValue(1000)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        view.sigResized.connect(self._resized)
        view.sigRangeChanged.connect(self._range_changed)

    def _range_changed(self, *_args: object) -> None:
        self.update()

    def _resized(self) -> None:
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self) -> QtCore.QRectF:
        """Use viewport geometry rather than source data coordinates."""
        rect = (self.view if self.footer is None else self.footer).boundingRect()
        return QtCore.QRectF(rect.x(), rect.y(), rect.width(), rect.height())

    def texts(self) -> tuple[str, str]:
        """Return full-unit maximum/minimum text with bounded significant digits."""
        bounds = self.view.viewRange()[1] if self.follow_y else self.limits
        if bounds is None or not all(math.isfinite(value) for value in bounds):
            return "", ""
        maximum, minimum = range_texts((bounds[0], bounds[1]), self.infinite_extrema,
                                       has_finite=self.has_finite, precision=6)
        high, low = f"{self.label} range max: {maximum}", f"{self.label} range min: {minimum}"
        if self.data_extrema is not None:
            high = f"Data max: {self.data_extrema[0]} | {high}"
            low = f"Data min: {self.data_extrema[1]} | {low}"
        return high, low

    def set_limits(self, limits: tuple[float, float] | None) -> None:
        """Update scalar bounds, or hide notes where a color scale is meaningless."""
        self.limits = limits
        self.setVisible(limits is not None or self.follow_y)
        self.update()

    def set_theme(self, dark: bool) -> None:
        """Keep labels legible over both data pixels and light/dark canvases."""
        self.dark = dark
        self.update()

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem,
              widget: QtWidgets.QWidget | None = None) -> None:
        """Draw extrema in corners, or below the canvas beside the X-axis title."""
        area = self.boundingRect().adjusted(5, 4, -5, -2 if self.footer is not None else -4)
        painter.save()
        painter.setPen(QtGui.QColor("#dce5f2" if self.dark else "#263247"))
        background = QtGui.QColor("#151b25" if self.dark else "#ffffff")
        background.setAlpha(205)
        for text, top in zip(self.texts(), (True, False)):
            if not text:
                continue
            flags = ((QtCore.Qt.AlignmentFlag.AlignLeft if top else QtCore.Qt.AlignmentFlag.AlignRight)
                     | (QtCore.Qt.AlignmentFlag.AlignTop if top and self.footer is None
                        else QtCore.Qt.AlignmentFlag.AlignBottom))
            rect = painter.boundingRect(area, flags, text)
            painter.fillRect(rect.adjusted(-2, -1, 2, 1), background)
            painter.drawText(area, flags, text)
        painter.restore()


def compact_axis(axis: AxisItem) -> None:
    """Let a new axis measure its tick labels instead of reserving default space.

    Args:
        axis: Newly created plot or colorbar axis, before its first paint.

    Side effects:
        Resets the initial tick-text size estimates and reduces tick padding.
        Automatic sizing remains enabled for larger fonts and longer numbers.
        The title keeps its native margins and positioning to avoid clipping.
    """
    # PyQtGraph keeps its 18 px height / 30 px width estimates until a measured
    # label differs by more than 10 px. Start at zero so the first paint grows
    # these estimates to the actual text size, including at different DPIs.
    axis.textHeight = 0
    axis.textWidth = 0
    axis.setStyle(tickTextOffset=AXIS_TICK_TEXT_OFFSET,
                  autoExpandTextSpace=True, autoReduceTextSpace=True)


def pyside_graphics_view(view: object) -> QtWidgets.QGraphicsView:
    """Validate and expose the native PySide6 view behind a PyQtGraph widget.

    Args:
        view: GraphicsLayoutWidget or PlotWidget created by PyQtGraph.

    Returns:
        The same object, with its checked PySide6 QGraphicsView interface.

    Raises:
        TypeError: The widget uses another Qt binding or is not a graphics view.
    """
    if not isinstance(view, QtWidgets.QGraphicsView):
        raise TypeError("PyQtGraph must use PySide6; select it before importing pyqtgraph.")
    return view


def graphics_scene(view: QtWidgets.QGraphicsView) -> GraphicsScene:
    """Get a live PyQtGraph scene with its extended mouse-movement signal.

    Args:
        view: The validated PySide6 graphics view containing the graph.

    Returns:
        The concrete PyQtGraph GraphicsScene owned by the view.

    Raises:
        TypeError: The scene is missing or has no PyQtGraph scene interface.
    """
    scene: object = view.scene()
    if not isinstance(scene, GraphicsScene):
        raise TypeError("The plot must have an initialized PyQtGraph GraphicsScene.")
    return scene
