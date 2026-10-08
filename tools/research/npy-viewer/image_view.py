"""Interactive matrix image with source-pixel readout and profile marker.

Requirements: PySide6, pyqtgraph, numpy and matplotlib colormaps.
Usage: embedded in the viewer's matrix tab.
Laplace sigma/omega planes fit their axes independently for readable contours.
"""

import math
import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
from pyqtgraph.graphicsItems.PlotItem.PlotItem import PlotItem
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox

from .data_model import DEFAULT_CLIP_COLOR, Frame, format_sample
from .plot_support import compact_axis, graphics_scene, pyside_graphics_view
from .workspace import RenderLayer

PLOT_CONTENT_MARGIN = 2


class ImageView(QtWidgets.QWidget):
    """Zoomable row-major image; x is column and y is row, starting at zero.

    Args:
        parent: Optional owning Qt widget.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.frame: Frame | None = None
        self._independent_axes = False
        self._layers: tuple[RenderLayer, ...] = ()
        self._layer_items: dict[int, pg.ImageItem] = {}
        self._layer_keys: dict[int, tuple[object, ...]] = {}
        self.clip_color = QtGui.QColor(DEFAULT_CLIP_COLOR)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.readout = QtWidgets.QLabel("Move over the image to inspect a pixel")
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readout.setWordWrap(True)
        layout.addWidget(self.readout)
        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.ci.layout.setContentsMargins(*(PLOT_CONTENT_MARGIN,) * 4)
        native_view = pyside_graphics_view(self.graphics)
        layout.addWidget(native_view)
        self.view_box = ViewBox()
        self.plot = PlotItem(viewBox=self.view_box)
        self.graphics.ci.addItem(self.plot)
        self.plot.setLabel("bottom", "Column (x)")
        self.plot.setLabel("left", "Row (y)")
        for name in ("bottom", "left"):
            compact_axis(self.plot.getAxis(name))
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
        # ColorBarItem otherwise reserves 45 px even for one-digit labels.
        self.bar.axis.setWidth(None)
        compact_axis(self.bar.axis)
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
        self._clear_layers()
        self.item.show()
        self.frame = frame
        self._axis_labels(frame)
        self.readout.setText("Move over the image to inspect a pixel")
        self.item.setImage(frame.image, autoLevels=False, levels=(0, 255) if frame.composite else levels)
        # Pixel centers coincide with the integer coordinates of the 3D mesh.
        h, w = frame.scalar.shape
        self.item.setRect(frame.x_mapping.forward(frame.x_start - 0.5), frame.y_mapping.forward(frame.y_start - 0.5),
                          w * frame.x_mapping.scale, h * frame.y_mapping.scale)
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

    def _clear_layers(self) -> None:
        for item in self._layer_items.values():
            self.plot.removeItem(item)
        self._layer_items.clear()
        self._layer_keys.clear()
        self._layers = ()

    def _axis_labels(self, frame: Frame) -> None:
        independent = bool(frame.x_grid and frame.x_grid.symbol == "ω"
                           and frame.y_grid and frame.y_grid.symbol == "σ")
        if independent != self._independent_axes:
            self.view_box.setAspectLocked(not independent)
            self._independent_axes = independent
        self.plot.setLabel("bottom", frame.x_grid.label() if frame.x_grid else "Column (x)")
        self.plot.setLabel("left", frame.y_grid.label("Y") if frame.y_grid else "Row (y)")
        self.plot.getAxis("bottom").enableAutoSIPrefix(frame.x_grid is None)
        self.plot.getAxis("left").enableAutoSIPrefix(frame.y_grid is None)
        self.view_box.invertY(not (frame.y_grid and frame.y_grid.frequency))

    def set_layers(self, layers: tuple[RenderLayer, ...], reset: bool = False) -> None:
        """Overlay scalar matrices using fixed RGB colors and value-based opacity.

        Args:
            layers: Compatible matrix snapshots with independent XY transforms.
            reset: Fit all aligned extents when True.
        """
        self.frame = None
        self._layers = layers
        if layers:
            self._axis_labels(layers[0].frame)
        self.item.hide()
        self.clip_overlay.hide()
        self.bar.hide()
        wanted = {layer.uid for layer in layers}
        for uid in tuple(self._layer_items):
            if uid not in wanted:
                self.plot.removeItem(self._layer_items.pop(uid))
                self._layer_keys.pop(uid, None)
        for order, layer in enumerate(layers):
            frame = layer.frame
            item = self._layer_items.get(layer.uid)
            if item is None:
                item = pg.ImageItem(axisOrder="row-major")
                item.setOpts(autoDownsample=True)
                self.plot.addItem(item)
                self._layer_items[layer.uid] = item
            image_key = (layer.data_key or id(frame), layer.color, layer.clip_color)
            if self._layer_keys.get(layer.uid) != image_key:
                low, high = frame.limits
                intensity = np.nan_to_num(np.clip((frame.display_scalar.astype(np.float64) - low) / (high - low), 0, 1))
                rgba = np.empty((*frame.scalar.shape, 4), dtype=np.uint8)
                color = QtGui.QColor(layer.color)
                rgba[..., :3] = (color.red(), color.green(), color.blue())
                rgba[..., 3] = np.asarray((0.08 + 0.92 * intensity) * frame.valid * 255, dtype=np.uint8)
                if frame.clip_outline is not None:
                    cap = QtGui.QColor(layer.clip_color)
                    rgba[frame.clip_outline] = (cap.red(), cap.green(), cap.blue(), 255)
                item.setImage(rgba, autoLevels=False)
                self._layer_keys[layer.uid] = image_key
            height, width = frame.scalar.shape
            xm, ym = frame.x_mapping.then(layer.x), frame.y_mapping.then(layer.y)
            item.setRect(xm.forward(frame.x_start - 0.5), ym.forward(frame.y_start - 0.5),
                         width * xm.scale, height * ym.scale)
            item.setOpacity(layer.opacity)
            item.setZValue(order)
        self.marker.setZValue(len(layers) + 1)
        self.readout.setText("Move over the overlay to inspect source and display coordinates")
        if reset:
            self.reset_view()

    def set_profile(self, by_row: bool, index: float | None) -> None:
        """Mark the selected row or column in image coordinates.

        Args:
            by_row: True for a horizontal row, False for a vertical column.
            index: Zero-based source index, or None to clear the marker.
        """
        if index is None:
            self.marker.hide()
            return
        self.marker.setAngle(0 if by_row else 90)
        value = index
        if self.frame is not None:
            value = (self.frame.y_mapping if by_row else self.frame.x_mapping).forward(index)
        self.marker.setValue(value)
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
        self.clip_overlay.setRect(frame.x_mapping.forward(frame.x_start - 0.5), frame.y_mapping.forward(frame.y_start - 0.5),
                                  w * frame.x_mapping.scale, h * frame.y_mapping.scale)
        self.clip_overlay.show()

    def reset_view(self) -> None:
        """Fit the complete matrix bounds, excluding the infinite profile line."""
        if self._layers:
            xs = [(layer.frame.x_mapping.then(layer.x).forward(layer.frame.x_start - 0.5),
                   layer.frame.x_mapping.then(layer.x).forward(layer.frame.x_start + layer.frame.scalar.shape[1] - 0.5)) for layer in self._layers]
            ys = [(layer.frame.y_mapping.then(layer.y).forward(layer.frame.y_start - 0.5),
                   layer.frame.y_mapping.then(layer.y).forward(layer.frame.y_start + layer.frame.scalar.shape[0] - 0.5)) for layer in self._layers]
            self.view_box.setRange(xRange=(min(x[0] for x in xs), max(x[1] for x in xs)),
                                   yRange=(min(y[0] for y in ys), max(y[1] for y in ys)), padding=0.02)
            return
        if self.frame is not None:
            h, w = self.frame.scalar.shape
            x, y = self.frame.x_start, self.frame.y_start
            xm, ym = self.frame.x_mapping, self.frame.y_mapping
            self.view_box.setRange(xRange=(xm.forward(x - 0.5), xm.forward(x + w - 0.5)),
                                    yRange=(ym.forward(y - 0.5), ym.forward(y + h - 0.5)), padding=0.02)

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
        if self._layers:
            point = self.view_box.mapSceneToView(position)
            labels = [f"Display x={point.x():.6g}, y={point.y():.6g}"]
            for layer in self._layers:
                frame = layer.frame
                column = math.floor(frame.x_mapping.then(layer.x).inverse(point.x()) + 0.5)
                row = math.floor(frame.y_mapping.then(layer.y).inverse(point.y()) + 0.5)
                x, y = column - frame.x_start, row - frame.y_start
                if 0 <= x < frame.scalar.shape[1] and 0 <= y < frame.scalar.shape[0]:
                    suffix = " [hidden/nonfinite]" if not frame.valid[y, x] else ""
                    labels.append(f"{layer.label}: source ({column}, {row}), value={format_sample(frame.scalar, y, x)}{suffix}")
            self.readout.setText(" | ".join(labels))
            return
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
        column, row = x + self.frame.x_start, y + self.frame.y_start
        coordinates = (f"{self.frame.x_grid.label()}={self.frame.x_mapping.forward(column):.6g}   "
                       f"{self.frame.y_grid.label('Y')}={self.frame.y_mapping.forward(row):.6g}   "
                       if self.frame.x_grid is not None and self.frame.y_grid is not None else "")
        self.readout.setText(f"{coordinates}column={column}   row={row}   {label}={value}{suffix}")
