"""Interactive matrix image with source-pixel readout and profile marker.

Requirements: PySide6, pyqtgraph, numpy and matplotlib colormaps.
Usage: embedded in the viewer's matrix tab.
"""

import math
import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox

from .data_model import DEFAULT_CLIP_COLOR, Frame, format_sample
from .plot_support import graphics_scene, pyside_graphics_view


class ImageView(QtWidgets.QWidget):
    """Zoomable row-major image; x is column and y is row, starting at zero.

    Args:
        parent: Optional owning Qt widget.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.frame: Frame | None = None
        self.clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.readout = QtWidgets.QLabel("Move over the image to inspect a pixel")
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.readout)
        self.graphics = pg.GraphicsLayoutWidget()
        native_view = pyside_graphics_view(self.graphics)
        layout.addWidget(native_view)
        self.view_box = ViewBox()
        self.plot = PlotItem(viewBox=self.view_box)
        self.graphics.ci.addItem(self.plot)
        self.plot.setLabel("bottom", "Column (x)")
        self.plot.setLabel("left", "Row (y)")
        self.view_box.invertY(True)
        self.view_box.setAspectLocked(True)
        self.plot.setMenuEnabled(False)
        self.view_box.setMouseMode(ViewBox.PanMode)
        self.item = pg.ImageItem(axisOrder="row-major")
        self.item.setOpts(autoDownsample=True)
        self.plot.addItem(self.item)
        self.clip_overlay = pg.ImageItem(axisOrder="row-major")
        self.clip_overlay.setOpts(autoDownsample=True)
        self.plot.addItem(self.clip_overlay)
        self.bar = pg.ColorBarItem(values=(0, 1), colorMap=pg.colormap.get("viridis"), interactive=False)
        self.bar.setImageItem(self.item, insert_in=self.plot)
        self.marker = pg.InfiniteLine(angle=0, pen=pg.mkPen("#ff1111", width=2))
        self.plot.addItem(self.marker)
        self.marker.hide()
        graphics_scene(native_view).sigMouseMoved.connect(self._hover)

    def set_frame(self, frame: Frame, cmap: str, levels: tuple[float, float], reset: bool) -> None:
        """Display a prepared matrix and optionally fit its complete bounds.

        Args:
            frame: Matrix frame with a display image.
            cmap: Matplotlib colormap name.
            levels: Color mapping minimum and maximum.
            reset: Fit the image if True; otherwise preserve zoom and pan.

        Side effects:
            Updates the image, colorbar and cursor label.
        """
        self.frame = frame
        self.readout.setText("Move over the image to inspect a pixel")
        self.item.setImage(frame.image, autoLevels=False, levels=(0, 255) if frame.composite else levels)
        # Pixel centers coincide with the integer coordinates of the 3D mesh.
        h, w = frame.scalar.shape
        self.item.setRect(frame.x_start - 0.5, frame.y_start - 0.5, w, h)
        self._update_clip_overlay()
        self.bar.setVisible(not frame.composite)
        if frame.composite:
            # setOpts supports clearing the LUT; setLookupTable's annotation omits None.
            # Override any initial deferred colorbar levels after setImage, so
            # the first RGB(A) image is not saturated into an all-white preview.
            self.item.setOpts(lut=None, levels=(0, 255))
        else:
            self.bar.setColorMap(pg.colormap.get(cmap, source="matplotlib"))
            self.bar.setLevels(levels)
        if reset:
            self.reset_view()

    def set_profile(self, by_row: bool, index: int | None) -> None:
        """Mark the selected row or column in image coordinates.

        Args:
            by_row: True for a horizontal row, False for a vertical column.
            index: Zero-based source index, or None to clear the marker.
        """
        if index is None:
            self.marker.hide()
            return
        self.marker.setAngle(0 if by_row else 90)
        self.marker.setValue(index)
        self.marker.show()

    def set_profile_color(self, color: QtGui.QColor) -> None:
        """Change the row/column marker color without changing its visibility.

        Args:
            color: Color selected with Qt's native color dialog.
        """
        self.marker.setPen(pg.mkPen(color, width=2))

    def set_clip_color(self, color: QtGui.QColor) -> None:
        """Recolor the image's clipping-region outlines.

        Args:
            color: Opaque color for threshold-region boundaries.
        """
        self.clip_color = color
        self._update_clip_overlay()

    def _update_clip_overlay(self) -> None:
        frame = self.frame
        if frame is None or frame.clip_outline is None:
            self.clip_overlay.clear()
            self.clip_overlay.hide()
            return
        rgba = np.zeros((*frame.scalar.shape, 4), dtype=np.uint8)
        color = self.clip_color
        rgba[frame.clip_outline] = (color.red(), color.green(), color.blue(), color.alpha())
        self.clip_overlay.setImage(rgba, autoLevels=False)
        h, w = frame.scalar.shape
        self.clip_overlay.setRect(frame.x_start - 0.5, frame.y_start - 0.5, w, h)
        self.clip_overlay.show()

    def reset_view(self) -> None:
        """Fit the complete matrix bounds, excluding the infinite profile line."""
        if self.frame is not None:
            h, w = self.frame.scalar.shape
            x, y = self.frame.x_start, self.frame.y_start
            self.view_box.setRange(xRange=(x - 0.5, x + w - 0.5),
                                    yRange=(y - 0.5, y + h - 0.5), padding=0.02)

    def set_theme(self, dark: bool) -> None:
        """Set plot background and axis colors for the requested UI theme.

        Args:
            dark: True selects a dark background.
        """
        self.graphics.setBackground("#151b25" if dark else "#ffffff")
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen("#adb9cb" if dark else "#465368")
            axis.setTextPen("#dce5f2" if dark else "#263247")

    def _hover(self, position: QtCore.QPointF) -> None:
        if self.frame is None or not self.plot.sceneBoundingRect().contains(position.x(), position.y()):
            self.readout.setText("Outside image")
            return
        point = self.item.mapFromScene(position.x(), position.y())
        # mapFromScene is in image-local coordinates (pixel edges, not centers).
        x, y = math.floor(point.x()), math.floor(point.y())
        h, w = self.frame.scalar.shape
        if not (0 <= x < w and 0 <= y < h):
            self.readout.setText("Outside image")
            return
        value = format_sample(self.frame.scalar, y, x)
        suffix = "  [filtered / nonfinite]" if not self.frame.valid[y, x] else ""
        if self.frame.clip_kind[y, x]:
            suffix = f"  [clamped to {format_sample(self.frame.display_scalar, y, x)}]"
        label = "luminance" if self.frame.composite else "value"
        self.readout.setText(f"x={x + self.frame.x_start}   y={y + self.frame.y_start}   {label}={value}{suffix}")
