"""Colored, numbered crop overlays on the shared zoom/pan/page-key viewer."""

from PySide6 import QtCore, QtGui, QtWidgets
from ..common.viewer import PageViewer
from ..common.viewer import ViewMode
from .model import Box

CROP_COLORS = ("#dd2929", "#1769cc", "#168b36", "#995a2b", "#717171", "#9b35ad", "#008b8b")
NUMBER_PIXELS = 44


class SplitViewer(PageViewer):
    """Draw crop order independently of the cached raster and exported PDF content."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.crop_items: list[QtWidgets.QGraphicsItem] = []

    def clear_crops(self) -> None:
        """Remove overlay objects before replacing the page or its crop plan."""
        for item in self.crop_items:
            self._scene.removeItem(item)
        self.crop_items.clear()
        self._scene.setSceneRect(self._bounds)

    def clear(self) -> None:
        """Clear both the inherited page raster and splitter-specific overlays."""
        self.clear_crops()
        super().clear()

    def set_pixmap(self, pixmap: QtGui.QPixmap, token: object) -> None:
        """Replace raster pixels; the host then installs the current page's crop plan."""
        self.clear_crops()
        super().set_pixmap(pixmap, token)

    def set_crops(self, boxes: tuple[Box, ...], selected: int = -1) -> None:
        """Replace colored outlines and fixed-size order numbers without rendering a PDF.

        Args:
            boxes: Normalized displayed-page rectangles, in output order.
            selected: Zero-based selected rectangle to emphasize; -1 selects none.
        """
        self.clear_crops()
        if self._bounds.isEmpty():
            return
        font = QtGui.QFont()
        font.setPixelSize(NUMBER_PIXELS)
        font.setBold(True)
        for index, box in enumerate(boxes):
            color = QtGui.QColor(CROP_COLORS[index % len(CROP_COLORS)])
            rect = QtCore.QRectF(box.x0 * self._bounds.width(), box.y0 * self._bounds.height(),
                (box.x1 - box.x0) * self._bounds.width(), (box.y1 - box.y0) * self._bounds.height())
            pen = QtGui.QPen(color, 4 if index == selected else 2)
            pen.setCosmetic(True)
            outline = self._scene.addRect(rect, pen)
            outline.setOpacity(.5)
            outline.setZValue(2)
            path = QtGui.QPainterPath()
            path.addText(0, 0, font, str(index + 1))
            bounds = path.boundingRect()
            path.translate(-bounds.center().x(), -bounds.center().y())
            number = self._scene.addPath(path, QtGui.QPen(QtGui.QColor("white"), 2), QtGui.QBrush(color))
            number.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            number.setPos(rect.center())
            number.setZValue(3)
            for item in (outline, number):
                item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
                self.crop_items.append(item)
            self._scene.setSceneRect(self._scene.sceneRect().united(rect))
        if self.mode == ViewMode.PAGE:
            self._fit()

    def _fit(self) -> None:
        if self.mode == ViewMode.PAGE and not self._scene.sceneRect().isEmpty():
            self.fitInView(self._scene.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._report()
        else:
            super()._fit()
