"""Checked PySide6 boundaries for PyQtGraph's dynamically selected Qt backend.

Requirements: PySide6 and pyqtgraph.
Usage: viewer widgets use these checks before embedding a graph or connecting
its extended scene signals. No global type-checker overrides are required.
"""

from PySide6 import QtWidgets
from pyqtgraph.GraphicsScene.GraphicsScene import GraphicsScene


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
