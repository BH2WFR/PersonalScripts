"""Reusable single-region raster viewer; red crop coordinates follow the displayed image."""

from PySide6 import QtCore, QtGui, QtWidgets
from .viewer import PageViewer

type Rectangle = tuple[float, float, float, float]
MIN_CROP_PIXELS = 8


class CropViewer(PageViewer):
    """Show a conspicuous red recognition box and optionally drag a replacement.

    Editing is opt-in. Coordinates are normalized to the already rotated image;
    callers reset the crop when changing its rotation. Wheel zoom remains active.
    """

    cropChanged = QtCore.Signal(tuple)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.crop_editing = False
        self._crop: Rectangle | None = None
        self._start: QtCore.QPointF | None = None
        self._crop_item = QtWidgets.QGraphicsRectItem()
        pen = QtGui.QPen(QtGui.QColor("#ff1717"), 4)
        pen.setCosmetic(True)
        self._crop_item.setPen(pen)
        self._crop_item.setZValue(10)
        self._crop_item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        self._scene.addItem(self._crop_item)
        self._crop_item.hide()

    def set_crop(self, crop: Rectangle | None) -> None:
        """Show a full-page/sub-page red box, or hide it for non-directory pages."""
        self._crop = crop
        self._crop_item.setVisible(crop is not None)
        if crop is not None:
            x0, y0, x1, y1 = crop
            self._crop_item.setRect(x0 * self._bounds.width(), y0 * self._bounds.height(),
                                    (x1 - x0) * self._bounds.width(), (y1 - y0) * self._bounds.height())

    def set_crop_editing(self, enabled: bool) -> None:
        """Switch left-drag between a new crop rectangle and ordinary page panning."""
        self.crop_editing = enabled
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag if enabled
                         else QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(QtCore.Qt.CursorShape.CrossCursor if enabled else QtCore.Qt.CursorShape.OpenHandCursor)

    def _point(self, event: QtGui.QMouseEvent) -> QtCore.QPointF:
        point = self.mapToScene(event.position().toPoint())
        return QtCore.QPointF(max(0, min(self._bounds.width(), point.x())),
                             max(0, min(self._bounds.height(), point.y())))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Start drawing only on a marked page in explicit crop-edit mode."""
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        if self.crop_editing and self._crop is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._start = self._point(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Update the red rectangle during a drag without changing project state."""
        if self._start is not None:
            self._crop_item.setRect(QtCore.QRectF(self._start, self._point(event)).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Commit one normalized rectangle after mouse release; reject tiny drags."""
        if self._start is not None:
            rect = QtCore.QRectF(self._start, self._point(event)).normalized()
            self._start = None
            if rect.width() >= MIN_CROP_PIXELS and rect.height() >= MIN_CROP_PIXELS:
                self.set_crop((rect.left() / self._bounds.width(), rect.top() / self._bounds.height(),
                               rect.right() / self._bounds.width(), rect.bottom() / self._bounds.height()))
                self.cropChanged.emit(self._crop)
            else:
                self.set_crop(self._crop)
            event.accept()
            return
        super().mouseReleaseEvent(event)
