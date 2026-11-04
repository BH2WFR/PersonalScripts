"""Reusable raster page viewer with cursor-centered zoom and hand panning."""

from enum import StrEnum
import math
from PySide6 import QtCore, QtGui, QtWidgets

MIN_SCALE = .025
MAX_SCALE = 16.0
ZOOM_STEP = 1.2


class ViewMode(StrEnum):
    PAGE = "page"
    WIDTH = "width"
    FREE = "free"


class PageViewer(QtWidgets.QGraphicsView):
    """Display a page image without owning a PDF document or processing settings.

    Signals:
        zoomChanged: Current image-to-view percentage after fitting or zooming.
        pageStepRequested: Previous (-1) or next (+1) page from focused page keys.
    """

    zoomChanged = QtCore.Signal(float)
    pageStepRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = QtWidgets.QGraphicsPixmapItem()
        self._item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self._original = QtGui.QPixmap()
        self._bounds = QtCore.QRectF()
        self._mipmaps: dict[int, QtGui.QPixmap] = {}
        self._level = 0
        self._region_items: list[QtWidgets.QGraphicsRectItem] = []
        self._image_highlight: QtWidgets.QGraphicsRectItem | None = None
        self.auto_fit = True
        self.navigation_enabled = True
        self._token: object = None
        self.mode = ViewMode.PAGE
        self.setBackgroundBrush(QtGui.QColor("#45484d"))
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setMinimumSize(180, 180)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setToolTip("Click the page to focus. PgUp / Left / Up: previous page; PgDn / Right / Down: next page.")

    def set_image(self, png: bytes, token: object) -> None:
        """Show encoded PNG bytes; retain zoom/position when comparing the same page."""
        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(png, "PNG"):
            raise ValueError("The preview worker returned an invalid image.")
        self.set_pixmap(pixmap, token)

    def set_pixmap(self, pixmap: QtGui.QPixmap, token: object) -> None:
        """Show detached image pixels; a changed token identifies a page turn."""
        same_page = token == self._token
        had_page = self._token is not None
        self.set_regions([])
        self.set_image_highlight(None)
        center = self.mapToScene(self.viewport().rect().center())
        self._original = pixmap
        self._bounds = QtCore.QRectF(0, 0, pixmap.width(), pixmap.height())
        self._mipmaps = {0: pixmap}
        self._level = 0
        self._item.setTransform(QtGui.QTransform())
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(self._bounds)
        self._token = token
        if not same_page and self.auto_fit:
            self.mode = ViewMode.PAGE
        elif not same_page and had_page:
            self.mode = ViewMode.FREE
        if self.mode != ViewMode.FREE:
            self._fit()
        elif same_page:
            self.centerOn(center)
        else:
            self.centerOn(self._bounds.center())
        self._report()

    def clear(self) -> None:
        """Remove the displayed page when a new document is adopted."""
        self._item.setPixmap(QtGui.QPixmap())
        self._original = QtGui.QPixmap()
        self._bounds = QtCore.QRectF()
        self._mipmaps.clear()
        self._scene.setSceneRect(QtCore.QRectF())
        self._token = None
        self.set_regions([])
        self.set_image_highlight(None)

    def set_regions(self, rectangles: list[tuple[float, float, float, float]]) -> None:
        """Replace normalized red overlays without changing the page pixels or PDF.

        Coordinates use the displayed page's top-left origin with x/y in [0, 1].
        Cosmetic pens retain a readable width at any zoom. Empty input hides boxes.
        """
        for item in self._region_items:
            self._scene.removeItem(item)
        self._region_items.clear()
        pen = QtGui.QPen(QtGui.QColor("red"), 1.5)
        pen.setCosmetic(True)
        for x0, y0, x1, y1 in rectangles:
            rect = QtCore.QRectF(x0 * self._bounds.width(), y0 * self._bounds.height(),
                                (x1 - x0) * self._bounds.width(), (y1 - y0) * self._bounds.height())
            item = self._scene.addRect(rect, pen)
            item.setZValue(1)
            item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            self._region_items.append(item)

    def set_image_highlight(self, bounds: tuple[float, float, float, float] | None) -> None:
        """Outline one displayed image in blue, independently of red region boxes."""
        if self._image_highlight is not None:
            self._scene.removeItem(self._image_highlight)
            self._image_highlight = None
        if bounds is None or self._bounds.isEmpty():
            return
        x0, y0, x1, y1 = bounds
        rect = QtCore.QRectF(x0 * self._bounds.width(), y0 * self._bounds.height(),
                            (x1 - x0) * self._bounds.width(), (y1 - y0) * self._bounds.height())
        pen = QtGui.QPen(QtGui.QColor("#1677ff"), 2)
        pen.setCosmetic(True)
        self._image_highlight = self._scene.addRect(rect, pen)
        self._image_highlight.setZValue(2)
        self._image_highlight.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

    def set_zoom(self, percent: float) -> None:
        """Apply a bounded percentage without moving the current page center."""
        if not math.isfinite(percent):
            raise ValueError("Zoom must be finite.")
        center = self.mapToScene(self.viewport().rect().center())
        factor = min(MAX_SCALE, max(MIN_SCALE, percent / 100))
        self.mode = ViewMode.FREE
        self.resetTransform()
        self.scale(factor, factor)
        self.centerOn(center)
        self._report()

    def fit_page(self) -> None:
        """Fit the entire page and continue fitting on resize."""
        self.mode = ViewMode.PAGE
        self._fit()

    def fit_width(self) -> None:
        """Fit the page width and continue fitting on resize."""
        self.mode = ViewMode.WIDTH
        self._fit()

    def actual_pixels(self) -> None:
        """Use one image pixel per Qt logical view pixel, preserving the center."""
        self.set_zoom(100)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Turn pages only for unmodified navigation keys focused on this viewer."""
        previous = (QtCore.Qt.Key.Key_PageUp, QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Up)
        following = (QtCore.Qt.Key.Key_PageDown, QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_Down)
        if event.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier and event.key() in (*previous, *following):
            if self.navigation_enabled:
                self.pageStepRequested.emit(-1 if event.key() in previous else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _fit(self) -> None:
        rect = self._bounds
        if rect.isEmpty():
            return
        if self.mode == ViewMode.PAGE:
            self.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        elif self.mode == ViewMode.WIDTH:
            factor = max(1, self.viewport().width() - 4) / rect.width()
            center = self.mapToScene(self.viewport().rect().center())
            self.resetTransform()
            self.scale(factor, factor)
            self.centerOn(rect.center().x(), center.y())
        self._report()

    def _report(self) -> None:
        self._update_mipmap()
        self.zoomChanged.emit(self.transform().m11() * 100)

    def _update_mipmap(self) -> None:
        """Area-downsample dense scan text before the final view transform.

        Bilinear scene scaling alone can drop thin black strokes when fitting a
        high-DPI binary scan to a small window. A small image pyramid preserves
        ink coverage while keeping the original raster available at 100%.
        """
        if self._original.isNull():
            return
        level = min(6, max(0, int(math.floor(-math.log2(max(MIN_SCALE, self.transform().m11()))))))
        if level == self._level:
            return
        if level not in self._mipmaps:
            factor = 2 ** level
            self._mipmaps[level] = self._original.scaled(
                max(1, self._original.width() // factor), max(1, self._original.height() // factor),
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        pixmap = self._mipmaps[level]
        self._item.setPixmap(pixmap)
        self._item.setTransform(QtGui.QTransform.fromScale(
            self._original.width() / pixmap.width(), self._original.height() / pixmap.height()))
        self._level = level

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Zoom at the cursor rather than using the wheel to turn pages."""
        if self._item.pixmap().isNull():
            event.ignore()
            return
        self.mode = ViewMode.FREE
        before = self.mapToScene(event.position().toPoint())
        old_scale = self.transform().m11()
        target = min(MAX_SCALE, max(MIN_SCALE, old_scale * ZOOM_STEP ** (event.angleDelta().y() / 120)))
        self.scale(target / old_scale, target / old_scale)
        after = self.mapToScene(event.position().toPoint())
        offset = after - before
        self.translate(offset.x(), offset.y())
        self._report()
        event.accept()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """Refit automatically only while a fit mode is selected."""
        super().resizeEvent(event)
        if self.mode != ViewMode.FREE:
            self._fit()
