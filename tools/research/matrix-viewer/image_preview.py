"""Shared raster preview for image composition and figure-export dialogs.

Requirements: PySide6. Usage: ImagePreview.set_image(QImage) accepts an owned
Qt image; numeric matrix renderers remain separate. Left/middle drag pans and
the wheel zooms around the cursor. Same-size updates preserve the view; new
dimensions fit automatically. Double-click or the context menu restores fit.
Only the displayed preview changes; saved image dimensions are unaffected.
"""

from PySide6 import QtCore, QtGui, QtWidgets

CHECKER_SIZE = 12
ZOOM_STEP = 1.2
MIN_ZOOM = 0.01
MAX_ZOOM = 100.0
PAN_BUTTONS = (QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.MiddleButton)


class ImagePreview(QtWidgets.QWidget):
    """Display a raster over a checkerboard, with cursor-centered zoom and pan.

    Args:
        parent: Optional owning widget. No image is loaded or saved by this class.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.image = QtGui.QImage()
        self._zoom = 1.0
        self._offset = QtCore.QPointF()
        self._fit = True
        self._drag_position: QtCore.QPointF | None = None
        self._drag_button = QtCore.Qt.MouseButton.NoButton
        self.setMinimumSize(250, 180)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setToolTip("Left / middle drag: pan · Wheel: zoom · Double-click: fit image")

    def set_image(self, image: QtGui.QImage) -> None:
        """Cache a Qt image, fitting new dimensions and retaining same-size views.

        Args:
            image: Qt-owned image (implicitly shared); a null image clears the view.
        """
        changed_size = image.size() != self.image.size()
        self.image = QtGui.QImage(image)
        if changed_size or self._fit:
            self.fit_image()
        self.update()

    def fit_image(self) -> None:
        """Center and fit the image, following subsequent widget resizing."""
        self._fit = True
        self._offset = QtCore.QPointF()
        if not self.image.isNull():
            self._zoom = min(self.width() / self.image.width(), self.height() / self.image.height())
        self.update()

    def _origin(self) -> QtCore.QPointF:
        return QtCore.QPointF((self.width() - self.image.width() * self._zoom) / 2,
                             (self.height() - self.image.height() * self._zoom) / 2) + self._offset

    def _actual_size(self) -> None:
        self._fit = False
        self._zoom = 1.0
        self._offset = QtCore.QPointF()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint cached pixels only; resizing never regenerates scientific data."""
        painter = QtGui.QPainter(self)
        for y in range(0, self.height(), CHECKER_SIZE):
            for x in range(0, self.width(), CHECKER_SIZE):
                color = "#ededed" if (x // CHECKER_SIZE + y // CHECKER_SIZE) % 2 else "#ffffff"
                painter.fillRect(x, y, CHECKER_SIZE, CHECKER_SIZE, QtGui.QColor(color))
        if not self.image.isNull():
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 1)
            target = QtCore.QRectF(self._origin(), QtCore.QSizeF(self.image.size()) * self._zoom)
            painter.drawImage(target, self.image)
        painter.end()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Refit only while fit mode is active, retaining manual zoom and pan."""
        super().resizeEvent(event)
        if self._fit:
            self.fit_image()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Zoom about the pointer without changing any output image dimensions."""
        delta = event.angleDelta().y() / 120 if event.angleDelta().y() else event.pixelDelta().y() / 120
        if self.image.isNull() or delta == 0:
            event.ignore()
            return
        relative = event.position() - self._origin()
        point = QtCore.QPointF(relative.x() / self._zoom, relative.y() / self._zoom)
        self._zoom = min(MAX_ZOOM, max(MIN_ZOOM, self._zoom * ZOOM_STEP ** max(-10.0, min(10.0, delta))))
        self._fit = False
        self._offset = QtCore.QPointF()
        self._offset = event.position() - point * self._zoom - self._origin()
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Start a left/middle drag, including when the image fits the viewport."""
        if not self.image.isNull() and event.button() in PAN_BUTTONS:
            self._drag_position = event.position()
            self._drag_button = event.button()
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Translate the cached image by the drag distance in widget pixels."""
        if self._drag_position is not None:
            self._offset += event.position() - self._drag_position
            self._drag_position = event.position()
            self._fit = False
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Finish the active drag and restore the normal cursor."""
        if event.button() == self._drag_button:
            self._drag_position = None
            self._drag_button = QtCore.Qt.MouseButton.NoButton
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """Restore fit with a left/middle double-click."""
        if event.button() in PAN_BUTTONS:
            self.fit_image()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """Offer fit and actual-pixel-size actions for both preview callers."""
        menu = QtWidgets.QMenu(self)
        menu.addAction("Fit image", self.fit_image)
        menu.addAction("Actual size (100%)", self._actual_size)
        menu.setEnabled(not self.image.isNull())
        menu.exec(event.globalPos())
