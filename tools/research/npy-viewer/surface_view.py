"""Embedded VTK height field with explicit mouse bindings and source picking.

Requirements: PySide6, numpy, pyvista, pyvistaqt and vtk.
Usage: SurfaceView is the matrix viewer's 3D tab.
"""

import math
from enum import StrEnum

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyvista as pv
from pyvistaqt import QtInteractor
from vtkmodules.vtkRenderingCore import vtkActor, vtkCellPicker

from .data_model import DEFAULT_CLIP_COLOR, ColorArray, FilterMode, FloatArray, Frame, format_sample

HOVER_INTERVAL_MS = 35
ROTATION_DEGREES_PER_PIXEL = 0.45
ZOOM_FACTOR = 1.15
DEFAULT_PROFILE_COLOR = "#ff1111"
DEFAULT_PROFILE_LIFT = 0.01
DEFAULT_SECTION_OPACITY = 0.65
DEFAULT_POINT_SIZE = 2.0
SECTION_HEIGHT_PADDING = 0.05
SOURCE_COLOR_FIELD = "SourceColor"
SOURCE_INDEX_FIELD = "SourceIndex"


class ProfileStyle(StrEnum):
    """Geometry used to mark a selected row or column in the 3D view."""

    RAISED_CURVE = "Raised curve"
    SECTION_PLANE = "Translucent section"


class Gesture(StrEnum):
    """Camera operation captured when a mouse button is pressed."""

    PAN = "pan"
    ORBIT = "orbit"
    ROLL = "roll"


class SurfaceCanvas(QtInteractor):
    """VTK canvas whose Qt events implement the viewer's exact mouse bindings.

    Args:
        parent: Owning Qt widget.

    Signals:
        coordinate_changed: Source sample text, or an explicit no-hit message.
    """

    coordinate_changed = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent=parent, auto_update=False, multi_samples=0)
        self.frame: Frame | None = None
        self._last = QtCore.QPointF()
        self._action: Gesture | None = None
        self._pending_hover: QtCore.QPointF | None = None
        self._hover_timer = QtCore.QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_INTERVAL_MS)
        self._hover_timer.timeout.connect(self._pick_pending)
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.008)
        self.picker.PickFromListOn()
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(False)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Start pan, orbit or roll according to button and modifier state.

        Args:
            event: Native Qt mouse press; handled without VTK default bindings.
        """
        self._last = event.position()
        self._hover_timer.stop()
        modifiers = event.modifiers()
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._action = (Gesture.ORBIT if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier
                            else Gesture.PAN)
        elif event.button() == QtCore.Qt.MouseButton.RightButton:
            self._action = Gesture.ROLL
        elif event.button() == QtCore.Qt.MouseButton.MiddleButton:
            if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
                self._action = Gesture.PAN
            elif modifiers & QtCore.Qt.KeyboardModifier.AltModifier:
                self._action = Gesture.ROLL
            else:
                self._action = Gesture.ORBIT
        else:
            self._action = None
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """End the active camera gesture and schedule a coordinate readout.

        Args:
            event: Native Qt release event.
        """
        self._action = None
        self._pending_hover = event.position()
        self._hover_timer.start()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Move the camera during a drag, or throttle continuous hover picking.

        Args:
            event: Native Qt movement event in logical widget pixels.
        """
        position = event.position()
        delta = position - self._last
        if self._action == Gesture.PAN:
            self._pan(self._last, position)
        elif self._action == Gesture.ORBIT:
            self.camera.Azimuth(-delta.x() * ROTATION_DEGREES_PER_PIXEL)
            self.camera.Elevation(delta.y() * ROTATION_DEGREES_PER_PIXEL)
            self.camera.OrthogonalizeViewUp()
        elif self._action == Gesture.ROLL:
            center = QtCore.QPointF(self.width() / 2, self.height() / 2)
            old, new = self._last - center, position - center
            angle = math.degrees(math.atan2(new.y(), new.x()) - math.atan2(old.y(), old.x()))
            self.camera.Roll(-angle)
            self.camera.OrthogonalizeViewUp()
        else:
            self._pending_hover = position
            if not self._hover_timer.isActive():
                self._hover_timer.start()
        if self._action is not None:
            self.reset_camera_clipping_range()
            self.render()
        self._last = position
        event.accept()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """Zoom using wheel steps, supporting perspective and parallel cameras.

        Args:
            event: Qt wheel event; trackpad pixel deltas are also accepted.
        """
        steps = event.angleDelta().y() / 120
        if not steps:
            steps = event.pixelDelta().y() / 120
        factor = ZOOM_FACTOR ** steps
        if self.camera.GetParallelProjection():
            self.camera.SetParallelScale(self.camera.GetParallelScale() / factor)
        else:
            self.camera.Dolly(factor)
        self.reset_camera_clipping_range()
        self.render()
        event.accept()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Keep VTK shortcuts from changing interaction or closing the canvas.

        Args:
            event: Native key press. F resets the camera; other keys propagate.
        """
        if event.key() == QtCore.Qt.Key.Key_F:
            self.reset_camera()
            event.accept()
        else:
            event.ignore()

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        """Release keys without forwarding them to VTK's default shortcut map.

        Args:
            event: Native Qt key release.
        """
        event.ignore()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        """Clear stale hover text when the cursor leaves the canvas.

        Args:
            event: Qt widget leave notification.
        """
        self._hover_timer.stop()
        self.coordinate_changed.emit("Outside surface")
        event.accept()

    def _display_point(self, position: QtCore.QPointF) -> tuple[float, float]:
        width, height = self.render_window.GetSize()
        return (position.x() * width / max(self.width(), 1),
                (self.height() - position.y() - 1) * height / max(self.height(), 1))

    def _pan(self, old: QtCore.QPointF, new: QtCore.QPointF) -> None:
        renderer = self.renderer
        focal = np.asarray(self.camera.GetFocalPoint())
        renderer.SetWorldPoint(*focal, 1)
        renderer.WorldToDisplay()
        depth = renderer.GetDisplayPoint()[2]
        coordinates: list[FloatArray] = []
        for position in (old, new):
            x, y = self._display_point(position)
            renderer.SetDisplayPoint(x, y, depth)
            renderer.DisplayToWorld()
            world = renderer.GetWorldPoint()
            coordinates.append(np.asarray(world[:3]) / world[3])
        shift = coordinates[0] - coordinates[1]
        self.camera.SetFocalPoint(*(focal + shift))
        self.camera.SetPosition(*(np.asarray(self.camera.GetPosition()) + shift))

    def _pick_pending(self) -> None:
        frame = self.frame
        if frame is None or frame.surface is None or self._pending_hover is None:
            return
        x, y = self._display_point(self._pending_hover)
        hit = self.picker.Pick(x, y, 0, self.renderer)
        if not hit:
            self.coordinate_changed.emit("No visible surface under cursor")
            return
        if frame.point_coordinates is not None:
            dataset = self.picker.GetDataSet()
            point_id = self.picker.GetPointId()
            indices = dataset.GetPointData().GetArray(SOURCE_INDEX_FIELD) if dataset is not None else None
            if indices is None or not 0 <= point_id < indices.GetNumberOfTuples():
                self.coordinate_changed.emit("No point under cursor")
                return
            index = int(indices.GetTuple1(point_id))
            values = frame.point_coordinates
            suffix = f" [Z clamped to {format_sample(frame.display_scalar, index)}]" if frame.clip_kind[index] else ""
            self.coordinate_changed.emit(
                f"Point {index + frame.x_start}: x={format_sample(values, index, 0)}   "
                f"y={format_sample(values, index, 1)}   z={format_sample(values, index, 2)}{suffix}"
            )
            return
        # Clipping inserts vertices, so recover the nearest original pixel from
        # world X/Y rather than interpreting an actor-local point ID as a source ID.
        world = self.picker.GetPickPosition()
        column, row = int(math.floor(world[0] + 0.5)), int(math.floor(world[1] + 0.5))
        local_y, local_x = row - frame.y_start, column - frame.x_start
        if not (0 <= local_y < frame.scalar.shape[0] and 0 <= local_x < frame.scalar.shape[1]):
            self.coordinate_changed.emit("Outside source region")
            return
        value = format_sample(frame.scalar, local_y, local_x)
        suffix = ""
        if frame.clip_kind[local_y, local_x]:
            suffix = f" [clamped to {format_sample(frame.display_scalar, local_y, local_x)}]"
        self.coordinate_changed.emit(
            f"x={column}   y={row}   z={value}  [source sample]{suffix}"
        )


class SurfaceView(QtWidgets.QWidget):
    """Height field and linked profile marker with source-value coordinates.

    Args:
        parent: Optional owner.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.dark = True
        self.z_scale = 1.0
        self._by_row = True
        self._index: int | None = 0
        self.profile_color = DEFAULT_PROFILE_COLOR
        self.profile_style = ProfileStyle.RAISED_CURVE
        self.profile_lift = DEFAULT_PROFILE_LIFT
        self.section_opacity = DEFAULT_SECTION_OPACITY
        self._surface_actor: vtkActor | None = None
        self._profile_actor: vtkActor | None = None
        self._clip_actors: list[vtkActor] = []
        self._colored_caps: list[pv.PolyData] = []
        self.clip_color = DEFAULT_CLIP_COLOR
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.readout = QtWidgets.QLabel("Move over the surface to inspect a source sample")
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.readout)
        self.canvas = SurfaceCanvas(self)
        self.canvas.coordinate_changed.connect(self.readout.setText)
        layout.addWidget(self.canvas)
        self.resolution = QtWidgets.QLabel("3D preview: no data")
        self.resolution.setWordWrap(True)
        layout.addWidget(self.resolution)

    def set_frame(self, frame: Frame, cmap: str, levels: tuple[float, float],
                  z_scale: float, reset: bool, point_size: float = DEFAULT_POINT_SIZE) -> None:
        """Replace surface geometry while optionally retaining the camera.

        Args:
            frame: Prepared matrix frame with original-index mesh mappings.
            cmap: Matplotlib colormap name.
            levels: Scalar color limits, independent of the visibility mask.
            z_scale: Positive visual height multiplier; readouts stay unscaled.
            reset: Fit a new isometric view when True.
            point_size: Pixel diameter for point-cloud samples.
        """
        surface = frame.surface
        if surface is None:
            return
        camera = self.canvas.camera_position
        self.canvas.clear()
        self._surface_actor = None
        self._profile_actor = None
        self._clip_actors.clear()
        self._colored_caps.clear()
        self.canvas.picker.InitializePickList()
        self.canvas.frame = frame
        self.z_scale = z_scale
        self.readout.setText("Move over the surface to inspect a source sample")
        if len(surface.points):
            mesh = pv.PolyData(surface.points, surface.faces) if surface.faces.size else pv.PolyData(surface.points)
            mesh.point_data["Value"] = surface.points[:, 2]
            if frame.point_coordinates is not None:
                mesh.point_data[SOURCE_INDEX_FIELD] = surface.rows - frame.x_start
            if surface.colors is not None:
                mesh.point_data[SOURCE_COLOR_FIELD] = surface.colors
            remaining, caps = self._partition_surface(mesh, frame)
            if remaining.n_points:
                actor = self.canvas.add_mesh(
                    remaining, scalars=SOURCE_COLOR_FIELD if surface.colors is not None else "Value",
                    rgb=surface.colors is not None, cmap=cmap, clim=levels,
                    style="surface" if surface.faces.size else "points", point_size=point_size,
                    lighting=False, show_scalar_bar=surface.colors is None, reset_camera=False, render=False,
                    scalar_bar_args={"title": "Luminance" if frame.composite else "Value",
                                     "color": "#dce5f2" if self.dark else "#263247",
                                     "vertical": True, "position_x": 0.88, "position_y": 0.18,
                                     "width": 0.07, "height": 0.65, "title_font_size": 12,
                                     "label_font_size": 10, "n_labels": 5, "fmt": "%.3g"},
                )
                actor.SetScale(1, 1, z_scale)
                self._surface_actor = actor
                self.canvas.picker.AddPickList(actor)
            for cap in caps:
                colored = SOURCE_COLOR_FIELD in cap.point_data
                if colored:
                    self._paint_cap(cap)
                    self._colored_caps.append(cap)
                actor = self.canvas.add_mesh(cap, color=None if colored else self.clip_color,
                                             scalars=SOURCE_COLOR_FIELD if colored else None, rgb=colored, lighting=False,
                                             point_size=max(6, point_size), show_scalar_bar=False,
                                             reset_camera=False, render=False)
                actor.SetScale(1, 1, z_scale)
                self._clip_actors.append(actor)
                self.canvas.picker.AddPickList(actor)
                if self._surface_actor is None:
                    self._surface_actor = actor
            cloud = frame.point_coordinates is not None
            self.canvas.show_grid(xtitle="X" if cloud else "Column (x)", ytitle="Y" if cloud else "Row (y)",
                                  ztitle="Z" if cloud and z_scale == 1 else "Scaled height",
                                  color="#adb9cb" if self.dark else "#465368", font_size=10)
            if reset:
                self.canvas.view_isometric()
                self.canvas.reset_camera()
            else:
                self.canvas.camera_position = camera
        self._render_profile()
        self._update_resolution()
        if not len(surface.points):
            self.readout.setText("No finite samples within the filter interval")
        self.canvas.reset_camera_clipping_range()
        self.canvas.render()

    @staticmethod
    def _partition_surface(mesh: pv.PolyData, frame: Frame) -> tuple[pv.PolyData, list[pv.PolyData]]:
        """Split threshold-crossing faces, projecting excess geometry onto caps."""
        if frame.value_limits.mode != FilterMode.CLAMP:
            return mesh, []
        remaining = mesh
        caps: list[pv.PolyData] = []
        for bound, lower in ((frame.value_limits.lower, True), (frame.value_limits.upper, False)):
            if bound is None or not remaining.n_points:
                continue
            values = np.asarray(remaining.point_data["Value"])
            outside = values < bound if lower else values > bound
            if not np.any(outside):
                continue
            if not remaining.faces.size:
                points: FloatArray = np.asarray(remaining.points, dtype=np.float64)
                cap = pv.PolyData(points[outside].copy())
                kept = pv.PolyData(points[~outside].copy())
                for name in remaining.point_data.keys():
                    data = np.asarray(remaining.point_data[name])
                    cap.point_data[name] = data[outside]
                    kept.point_data[name] = data[~outside]
            elif np.all(outside):
                cap, kept = remaining.copy(deep=True), pv.PolyData()
            else:
                parts = remaining.clip_scalar(scalars="Value", value=bound, invert=lower, both=True)
                if not isinstance(parts, tuple):
                    raise RuntimeError("Surface clipping did not return polygonal geometry.")
                cap, kept = parts
                if not isinstance(cap, pv.PolyData) or not isinstance(kept, pv.PolyData):
                    raise RuntimeError("Surface clipping did not return polygonal geometry.")
                # Complementary VTK outputs can share point storage.
                cap = cap.clean().copy(deep=True)
                kept = kept.clean()
            # PyVista's clean/copy return annotations also include other datasets.
            if not isinstance(cap, pv.PolyData) or not isinstance(kept, pv.PolyData):
                raise RuntimeError("Surface clipping did not return polygonal geometry.")
            if cap.n_points:
                cap_points: FloatArray = np.array(cap.points, dtype=np.float64, copy=True)
                cap_points[:, 2] = bound
                cap.points = cap_points
                caps.append(cap)
            remaining = kept
        if caps and remaining.n_points:
            # VTK's interpolated boundary vertices can overshoot by roundoff.
            # Keep both geometry and color values inside the exact user bounds.
            kept_points: FloatArray = np.array(remaining.points, dtype=np.float64, copy=True)
            heights = np.clip(kept_points[:, 2], frame.value_limits.lower,
                              frame.value_limits.upper)
            kept_points[:, 2] = heights
            remaining.points = kept_points
            remaining.point_data["Value"] = heights
        return remaining, caps

    def set_clip_color(self, color: str) -> None:
        """Recolor solid clipping caps without rebuilding the surface.

        Args:
            color: Hex RGB color selected in the shared clipping controls.
        """
        self.clip_color = color
        chosen = QtGui.QColor(color)
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        for actor in self._clip_actors:
            actor.GetProperty().SetColor(*rgb)
        for cap in self._colored_caps:
            self._paint_cap(cap)
        self.canvas.render()

    def _paint_cap(self, cap: pv.PolyData) -> None:
        """Replace a clipped region's RGB while retaining per-vertex opacity."""
        colors: ColorArray = np.array(cap.point_data[SOURCE_COLOR_FIELD], dtype=np.uint8, copy=True)
        color = QtGui.QColor(self.clip_color)
        colors[:, :3] = (color.red(), color.green(), color.blue())
        cap.point_data[SOURCE_COLOR_FIELD] = colors

    def set_profile(self, by_row: bool, index: int | None) -> None:
        """Mark a selected full-resolution row/column, or clear the selection.

        Args:
            by_row: True selects a row; False a column.
            index: Source row/column index, or None to remove the marker.
        """
        self._by_row, self._index = by_row, index
        self._render_profile()

    def set_profile_style(self, style: ProfileStyle, color: str,
                          lift: float, opacity: float) -> None:
        """Configure the 3D selection marker without modifying source samples.

        Args:
            style: Raised source curve or vertical translucent section plane.
            color: Hex RGB marker color.
            lift: Nonnegative curve offset as a fraction of the visible Z span.
            opacity: Section opacity between zero and one, inclusive.

        Raises:
            ValueError: If lift or opacity is nonfinite or out of range.
        """
        if not math.isfinite(lift) or lift < 0:
            raise ValueError("Profile lift must be finite and nonnegative.")
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("Section opacity must be between zero and one.")
        self.profile_style, self.profile_color = style, color
        self.profile_lift, self.section_opacity = lift, opacity
        self._render_profile()

    def _render_profile(self) -> None:
        frame = self.canvas.frame
        self.canvas.remove_actor("profile", reset_camera=False, render=False)
        self._profile_actor = None
        index, by_row = self._index, self._by_row
        if frame is None or index is None or frame.scalar.ndim != 2:
            self.canvas.render()
            return
        h, w = frame.scalar.shape
        local_index = index - (frame.y_start if by_row else frame.x_start)
        if not 0 <= local_index < (h if by_row else w):
            self.canvas.render()
            return
        valid = frame.valid[local_index, :] if by_row else frame.valid[:, local_index]
        visible = np.any(frame.valid) if self.profile_style == ProfileStyle.SECTION_PLANE else np.any(valid)
        if not visible:
            self.canvas.render()
            return

        # ── vertical section through the selected source coordinates ──
        if self.profile_style == ProfileStyle.SECTION_PLANE:
            lower, upper = frame.limits
            padding = (upper - lower) * SECTION_HEIGHT_PADDING
            low, high = lower - padding, upper + padding
            start = (frame.x_start if by_row else frame.y_start) - 0.5
            end = start + (w if by_row else h)
            points = np.array(
                [[start, index, low], [end, index, low], [end, index, high], [start, index, high]]
                if by_row else
                [[index, start, low], [index, end, low], [index, end, high], [index, start, high]],
                dtype=np.float64,
            )
            mesh = pv.PolyData(points, np.array([4, 0, 1, 2, 3], dtype=np.int64))
            self._profile_actor = self.canvas.add_mesh(
                mesh, color=self.profile_color, opacity=self.section_opacity,
                lighting=False, name="profile", pickable=False,
                reset_camera=False, render=False,
            )
        else:
            self._add_profile_curve(frame, by_row, index)
        self._position_profile()
        # add_mesh updates the axes before actor scaling/translation; refresh
        # them again so a small crop is not framed using unscaled Z bounds.
        self.canvas.renderer.update_bounds_axes()
        self.canvas.reset_camera_clipping_range()
        self.canvas.render()

    def _add_profile_curve(self, frame: Frame, by_row: bool, index: int) -> None:
        local_index = index - (frame.y_start if by_row else frame.x_start)
        values = frame.display_scalar[local_index, :] if by_row else frame.display_scalar[:, local_index]
        valid = frame.valid[local_index, :] if by_row else frame.valid[:, local_index]
        visible = np.flatnonzero(valid)
        varying = visible + (frame.x_start if by_row else frame.y_start)
        fixed = np.full(len(varying), index)
        points = np.asarray(np.column_stack((varying if by_row else fixed, fixed if by_row else varying,
                                             values[valid])), dtype=np.float64)
        starts = np.flatnonzero(valid[:-1] & valid[1:])
        point_indices = np.full(len(values), -1, dtype=np.int64)
        point_indices[visible] = np.arange(len(visible))
        lines = np.column_stack((np.full(len(starts), 2), point_indices[starts], point_indices[starts + 1])).ravel()
        vertices = np.column_stack((np.ones(len(varying), dtype=np.int64), np.arange(len(varying)))).ravel()
        # Vertices retain isolated valid samples without joining across gaps.
        mesh = pv.PolyData(points, lines=lines, verts=vertices)
        self._profile_actor = self.canvas.add_mesh(
            mesh, color=self.profile_color, line_width=3, point_size=3,
            lighting=False, name="profile", pickable=False, reset_camera=False, render=False,
        )

    def _position_profile(self) -> None:
        actor, frame = self._profile_actor, self.canvas.frame
        if actor is None or frame is None:
            return
        actor.SetScale(1, 1, self.z_scale)
        lift = (frame.limits[1] - frame.limits[0]) * self.profile_lift if self.profile_style == ProfileStyle.RAISED_CURVE else 0.0
        actor.SetPosition(0, 0, lift * self.z_scale)

    def set_height_scale(self, value: float) -> None:
        """Rescale existing actors in place, keeping geometry and source values.

        Args:
            value: Positive finite visual height multiplier.

        Raises:
            ValueError: If the multiplier is nonfinite or nonpositive.
        """
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Height multiplier must be positive and finite.")
        self.z_scale = value
        for actor in (self._surface_actor, self._profile_actor, *self._clip_actors):
            if actor is not None:
                actor.SetScale(1, 1, value)
        self._position_profile()
        self.canvas.renderer.update_bounds_axes()
        self.canvas.reset_camera_clipping_range()
        self._update_resolution()
        self.canvas.render()

    def _update_resolution(self) -> None:
        frame = self.canvas.frame
        if frame is None or frame.surface is None:
            return
        if frame.point_coordinates is not None:
            self.resolution.setText(
                f"Point cloud: {len(frame.surface.points):,} rendered / {np.count_nonzero(frame.valid):,} valid "
                f"/ {len(frame.scalar):,} source points | Z multiplier: {self.z_scale:g} | Bounds apply to Z"
            )
            return
        ny, nx = frame.surface.sampled_shape
        h, w = frame.scalar.shape
        self.resolution.setText(
            f"3D grid: {nx} x {ny} | Region: {w} x {h} | "
            f"X: {frame.x_start}..{frame.x_start + w - 1}, Y: {frame.y_start}..{frame.y_start + h - 1} | "
            f"Visible cells: {frame.surface.faces.size // 5:,} | Height scale: {self.z_scale:g}"
            + (" | Image colors; grayscale height" if frame.surface.colors is not None else "")
        )

    def reset_view(self) -> None:
        """Restore an isometric camera fitted to the current surface."""
        self.canvas.view_isometric()
        self.canvas.reset_camera()

    def set_theme(self, dark: bool) -> None:
        """Change the 3D background; mesh labels refresh on the next frame.

        Args:
            dark: True for a dark background.
        """
        self.dark = dark
        self.canvas.set_background("#151b25" if dark else "#ffffff")

    def shutdown(self) -> None:
        """Stop cursor timers and release the native VTK render window."""
        self.canvas._hover_timer.stop()
        self.canvas.close()
