"""Checked PySide6 boundaries and compact, automatically measured plot axes.

Requirements: PySide6 and pyqtgraph.
Usage: viewer widgets use these checks before embedding a graph or connecting
its extended scene signals. No global type-checker overrides are required.
Range captions distinguish source infinities from finite display bounds, which
remain governed by manual range and lock settings.
Axis footer captions follow the X-title row and reflow with exported plots.
"""

import math
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from pyqtgraph.GraphicsScene.GraphicsScene import GraphicsScene
from pyqtgraph.graphicsItems.AxisItem import AxisItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem

AXIS_TICK_TEXT_OFFSET = 2
type LineSpec = tuple[QtGui.QPen, QtCore.QPointF, QtCore.QPointF]
type TextSpec = tuple[QtCore.QRectF, int, str]
type AxisSpecs = tuple[LineSpec, list[LineSpec], list[TextSpec]]


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
        return QtCore.QRectF(self.plot.boundingRect())

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
        if (specs is None or not self.endpoint_ticks or self.logMode
                or self.orientation not in ("left", "right") or not self.style["showValues"]):
            return specs
        bounds = self.mapRectFromParent(self.geometry())
        values = self.range
        if not all(math.isfinite(value) for value in values) or values[0] == values[1]:
            return specs
        axis_line, ticks, texts = specs
        offset = max(0, self.style["tickLength"]) + self.style["tickTextOffset"][0]
        scale = self.autoSIPrefixScale * self.scale
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
        self._updateMaxTextSize(max(rect.width() for rect, _, _ in endpoints))
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
