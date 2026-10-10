"""Checked PySide6 boundaries and compact, automatically measured plot axes.

Requirements: PySide6 and pyqtgraph.
Usage: viewer widgets use these checks before embedding a graph or connecting
its extended scene signals. No global type-checker overrides are required.
"""

from PySide6 import QtWidgets
from pyqtgraph.GraphicsScene.GraphicsScene import GraphicsScene
from pyqtgraph.graphicsItems.AxisItem import AxisItem

AXIS_TICK_TEXT_OFFSET = 2


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
