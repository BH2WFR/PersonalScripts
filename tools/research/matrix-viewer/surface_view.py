"""Embedded VTK height field with explicit mouse bindings and source picking.

Requirements: PySide6, numpy, pyvista, pyvistaqt and vtk.
Usage: SurfaceView is the matrix viewer's 3D tab.
Single and overlaid slice markers use the shared 3D selection color.
Clipping caps retain their geometry when optional highlight coloring is off.
Point rendering uses sampled source vertices without interpolated mesh edges;
its pixel size applies to matrices and XYZ clouds, including overlay layers.
Z tick labels show source Value, undoing both height and scene scaling. Small
or large ranges use an explicit power-of-ten suffix. Overlays use the alignment
reference's value coordinates (first visible layer if the reference is hidden).
Scene axis multipliers are a separate display transform shared by meshes,
clipping caps and slice markers. Picking and tick ranges undo that transform;
per-matrix height/alignment remains independent and numeric exports are untouched.
The default-on XY scene lock keeps X/Y multipliers equal; either axis's scale
edits/reset apply to both, while Z remains independent. Unlock allows stretching.
Optional view-wide Z bounds clip only rendering and set the axis/camera box.
They use displayed height/alignment coordinates before scene multipliers, are
independent of scalar color bounds, and survive geometry and slice updates.
Rounded XYZ ticks run across their axes; precise color/Z ranges use compact Qt
information strips above/below the scene, with the normal application font.
Tick density follows scaled axis lengths: compressed axes use fewer labels at
correct source coordinates; long axes keep VTK's rounded automatic steps.
Automatic Z axes round the annotation box with a fixed four-tick budget, so
scene scaling cannot change its source-value extent. Strongly compressed Z axes
omit intermediate labels; enlarged axes use denser native rounded ticks.
Manual/locked Z boxes retain their exact bounds.
Optional endpoint-inclusive Z/color ticks survive scene rebuilds, default off.
An independent expand-only Z range lock accumulates the geometry box across
matrices, overlays and height changes. Turning it off restores manual/auto Z
bounds; scalar color locking remains shared by 2D/3D and entirely separate.
Alt+left, Alt+middle and right drag all roll the camera.
"""

import math
from enum import StrEnum

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyvista as pv
from pyvistaqt import QtInteractor
from vtkmodules.vtkRenderingCore import vtkActor, vtkCellPicker
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonDataModel import vtkPlane
from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkStringArray

from .data_model import DEFAULT_CLIP_COLOR, ColorArray, FilterMode, FloatArray, Frame, format_sample
from .coordinates import AxisMap
from .workspace import RenderLayer, profile_series
from .render_style import DEFAULT_POINT_SIZE, SurfaceStyle
from .plot_support import RangeLabel

HOVER_INTERVAL_MS = 35
ROTATION_DEGREES_PER_PIXEL = 0.45
ZOOM_FACTOR = 1.15
DEFAULT_PROFILE_COLOR = "#ff1111"
DEFAULT_PROFILE_LIFT = 0.01
DEFAULT_SECTION_OPACITY = 0.65
SECTION_HEIGHT_PADDING = 0.05
SOURCE_COLOR_FIELD = "SourceColor"
SOURCE_INDEX_FIELD = "SourceIndex"
AXIS_LABEL_FORMAT = "%.6g"
Z_SCIENTIFIC_MIN = 0.1
Z_SCIENTIFIC_MAX = 10_000.0
MIN_LABEL_EXPONENT = -308
MIN_AXIS_SCALE = 1e-12
MAX_AXIS_SCALE = 1e12
FULL_AXIS_TICK_BUDGET = 8
AUTO_Z_TICK_BUDGET = 4
COMPRESSED_Z_AXIS_RATIO = 0.1


def _rounded_axis_ticks(lower: float, upper: float, count: int) -> tuple[float, ...]:
    """Cover a finite range with at most four evenly spaced, rounded labels.

    Annotation bounds may expand, but data and clipping bounds never change.
    Two-label budgets use rounded endpoints; other budgets use 1/2/5 steps.
    Empty output leaves extreme/unrepresentable ranges to VTK's automatic path.
    """
    span = upper - lower
    if not math.isfinite(span) or span <= 0:
        return ()
    desired = span / (count - 1)
    decade = 10.0 ** math.floor(math.log10(desired)) if desired > 0 else 0.0
    if not decade:
        return ()
    for _ in range(4):
        for factor in (1.0, 2.0, 5.0):
            step = factor * decade
            if (step < desired and not math.isclose(step, desired, rel_tol=1e-12)) or not math.isfinite(step) or step == 0:
                continue
            if not all(math.isfinite(value / step) for value in (lower, upper)):
                return ()
            endpoints: list[float] = []
            for value in (lower / step, upper / step):
                nearest = round(value)
                endpoints.append(float(nearest) if abs(value - nearest) <= 8 * math.ulp(value) else value)
            first, last = math.floor(endpoints[0]), math.ceil(endpoints[1])
            if last <= first:
                return ()
            if count == 2:
                values = (first * step, last * step)
            elif last - first + 1 <= count:
                values = tuple((first + index) * step for index in range(last - first + 1))
            else:
                continue
            return values if all(math.isfinite(value) for value in values) else ()
        decade *= 10
    return ()


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
    fit_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent=parent, auto_update=False, multi_samples=0)
        self.frame: Frame | None = None
        self.layers: list[tuple[vtkActor, RenderLayer]] = []
        self.axis_scale = (1.0, 1.0, 1.0)
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
            self._action = (Gesture.ROLL if modifiers & QtCore.Qt.KeyboardModifier.AltModifier else
                            Gesture.ORBIT if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier
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
            self.fit_requested.emit()
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
        layer = next((layer for actor, layer in self.layers if actor == self.picker.GetActor()), None)
        prefix = ""
        if layer is not None:
            frame = layer.frame
            world = self.display_position(self.picker.GetPickPosition())
            prefix = f"{layer.label} | Display ({world[0]:.6g}, {world[1]:.6g}, {world[2]:.6g}) | "
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
                f"{prefix}Point {index + frame.x_start}: x={format_sample(values, index, 0)}   "
                f"y={format_sample(values, index, 1)}   z={format_sample(values, index, 2)}{suffix}"
            )
            return
        # Clipping inserts vertices, so recover the nearest original pixel from
        # world X/Y rather than interpreting an actor-local point ID as a source ID.
        world = self.display_position(self.picker.GetPickPosition())
        world_x = layer.x.inverse(world[0]) if layer is not None else world[0]
        world_y = layer.y.inverse(world[1]) if layer is not None else world[1]
        column = int(math.floor(frame.x_mapping.inverse(world_x) + 0.5))
        row = int(math.floor(frame.y_mapping.inverse(world_y) + 0.5))
        local_y, local_x = row - frame.y_start, column - frame.x_start
        if not (0 <= local_y < frame.scalar.shape[0] and 0 <= local_x < frame.scalar.shape[1]):
            self.coordinate_changed.emit("Outside source region")
            return
        value = format_sample(frame.scalar, local_y, local_x)
        suffix = ""
        if frame.clip_kind[local_y, local_x]:
            suffix = f" [clamped to {format_sample(frame.display_scalar, local_y, local_x)}]"
        self.coordinate_changed.emit(
            f"{prefix}x={frame.x_mapping.forward(column):.6g}   y={frame.y_mapping.forward(row):.6g}   "
            f"z={value}  [column={column}, row={row}]{suffix}"
        )

    def display_position(self, world: tuple[float, float, float]) -> tuple[float, float, float]:
        """Undo scene stretching on a picked world point, retaining alignment.

        Args:
            world: VTK pick position after the scene display transformation.

        Returns:
            Coordinates before scene scaling, for source index lookup/readout.
        """
        return (world[0] / self.axis_scale[0], world[1] / self.axis_scale[1], world[2] / self.axis_scale[2])


class SurfaceView(QtWidgets.QWidget):
    """Height field and linked profile marker with source-value coordinates.

    Args:
        parent: Optional owner.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.dark = True
        self.z_scale = 1.0
        self.equal_xy_locked = True
        self.z_view_range: tuple[float, float] | None = None
        self.z_range_lock = False
        self._locked_z_range: tuple[float, float] | None = None
        self.endpoint_ticks = False
        self._color_limits: tuple[float, float] | None = None
        self.extrema_generation = 0
        self._extrema_key: tuple[int, ...] = ()
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
        self.highlight_clipped = True
        self._layers: tuple[RenderLayer, ...] = ()
        self._z_reference_uid: int | None = None
        self._layer_signature: tuple[tuple[object, ...], ...] = ()
        self._layer_profiles: list[vtkActor] = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.readout = QtWidgets.QLabel("Move over the surface to inspect a source sample")
        self.readout.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.readout.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readout.setWordWrap(True)
        header = QtWidgets.QHBoxLayout()
        self.color_range_label = RangeLabel("Color range")
        header.addWidget(self.color_range_label)
        header.addWidget(self.readout, 1)
        layout.addLayout(header)
        self.canvas = SurfaceCanvas(self)
        self.canvas.coordinate_changed.connect(self.readout.setText)
        self.canvas.fit_requested.connect(self.fit_camera)
        layout.addWidget(self.canvas)
        self.resolution = QtWidgets.QLabel("3D preview: no data")
        self.resolution.setWordWrap(True)
        footer = QtWidgets.QHBoxLayout()
        self.z_range_label = RangeLabel("Value range")
        self.z_range_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        footer.addWidget(self.resolution, 1)
        self.extrema_label = QtWidgets.QLabel()
        self.extrema_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.extrema_label.hide()
        footer.addWidget(self.extrema_label)
        footer.addSpacing(8)
        footer.addWidget(self.z_range_label)
        layout.addLayout(footer)

    def set_frame(self, frame: Frame, cmap: str, levels: tuple[float, float],
                  z_scale: float, reset: bool, point_size: float = DEFAULT_POINT_SIZE, *,
                  highlight_clipped: bool = True, style: SurfaceStyle = SurfaceStyle.SURFACE) -> None:
        """Replace surface geometry while optionally retaining the camera.

        Args:
            frame: Prepared matrix frame with original-index mesh mappings.
            cmap: Matplotlib colormap name.
            levels: Scalar color limits, independent of the visibility mask.
            z_scale: Positive visual height multiplier; readouts stay unscaled.
            reset: Fit a new isometric view when True.
            point_size: Pixel diameter for matrix/cloud samples.
            style: Connected surface or unconnected sampled points.
            highlight_clipped: Paint caps in the clipping color; False keeps
                normal scalar/image colors without removing clamping.
        """
        surface = frame.surface
        if surface is None:
            return
        self._invalidate_extrema((id(frame),))
        camera = self.canvas.camera.copy()
        self._layers = ()
        self._layer_signature = ()
        self._layer_profiles.clear()
        self.canvas.layers.clear()
        self.canvas.clear()
        self.z_range_label.set_limits(None)
        self._color_limits = None if frame.composite else levels
        self.color_range_label.set_limits(self._color_limits)
        self._surface_actor = None
        self._profile_actor = None
        self._clip_actors.clear()
        self._colored_caps.clear()
        self.canvas.picker.InitializePickList()
        self.canvas.frame = frame
        self.z_scale = z_scale
        self.highlight_clipped = highlight_clipped
        self.readout.setText("Move over the surface to inspect a source sample")
        if len(surface.points):
            points = style == SurfaceStyle.POINTS or not surface.faces.size
            mesh = pv.PolyData(surface.points) if points else pv.PolyData(surface.points, surface.faces)
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
                    style="points" if points else "surface", point_size=point_size,
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
                if surface.colors is None:
                    self.canvas.scalar_bar.SetVerticalTitleSeparation(12)
            for cap in caps:
                colored = SOURCE_COLOR_FIELD in cap.point_data
                if colored and highlight_clipped:
                    self._paint_cap(cap)
                    self._colored_caps.append(cap)
                cap.point_data["Value"] = np.asarray(cap.points)[:, 2]
                actor = self.canvas.add_mesh(cap, color=self.clip_color if highlight_clipped and not colored else None,
                                             scalars=SOURCE_COLOR_FIELD if colored else None if highlight_clipped else "Value",
                                             rgb=colored, cmap=cmap, clim=levels, lighting=False,
                                             style="points" if points else "surface", point_size=point_size, show_scalar_bar=False,
                                             reset_camera=False, render=False)
                actor.SetScale(1, 1, z_scale)
                self._clip_actors.append(actor)
                self.canvas.picker.AddPickList(actor)
                if self._surface_actor is None:
                    self._surface_actor = actor
            cloud = frame.point_coordinates is not None
            self.canvas.show_grid(xtitle=frame.x_grid.label() if frame.x_grid else "X" if cloud else "Column (x)",
                                  ytitle=frame.y_grid.label("Y") if frame.y_grid else "Y" if cloud else "Row (y)",
                                  ztitle="Value",
                                  color="#adb9cb" if self.dark else "#465368", font_size=10,
                                  fmt=AXIS_LABEL_FORMAT, render=False)
            self._update_axes()
            if reset:
                self.canvas.view_isometric()
                self.fit_camera()
            else:
                self.canvas.camera.DeepCopy(camera)
        self._render_profile()
        self._update_resolution()
        if not len(surface.points):
            self.readout.setText("No finite samples within the filter interval")
        self.canvas.reset_camera_clipping_range()
        self.canvas.render()

    def set_layers(self, layers: tuple[RenderLayer, ...], reset: bool = False, *, reference_uid: int | None = None) -> None:
        """Render aligned surfaces/clouds in independent solid colors.

        Args:
            layers: Compatible snapshots; XYZ alignment only affects actors.
            reset: Fit all geometry instead of retaining the shared camera.
            reference_uid: Visible alignment reference supplying Z value units;
                defaults to the first visible layer when absent or hidden.
        """
        self._invalidate_extrema(tuple(id(layer.frame) for layer in layers))
        signature = tuple(layer.signature for layer in layers)
        same_reference = self._z_reference_uid == reference_uid
        self._z_reference_uid = reference_uid
        if signature == self._layer_signature and layers and same_reference:
            if reset:
                self.reset_view()
            return
        # A lazily opened 3D tab may never have fitted a camera to any data.
        # Preserve an existing data view, but fit the first nonempty overlay.
        reset = reset or (self._surface_actor is None and not self.canvas.layers)
        camera = self.canvas.camera_position
        self.canvas.clear()
        self.z_range_label.set_limits(None)
        self._color_limits = None
        self.color_range_label.set_limits(None)
        self.canvas.picker.InitializePickList()
        self.canvas.layers.clear()
        self._layer_profiles.clear()
        self._surface_actor = self._profile_actor = None
        self._clip_actors.clear()
        self._colored_caps.clear()
        self._layers = layers
        self._layer_signature = signature
        self.canvas.frame = layers[0].frame if layers else None
        for layer in layers:
            frame, surface = layer.frame, layer.frame.surface
            if surface is None or not len(surface.points):
                continue
            points = layer.surface_style == SurfaceStyle.POINTS or not surface.faces.size
            mesh = pv.PolyData(surface.points) if points else pv.PolyData(surface.points, surface.faces)
            mesh.point_data["Value"] = surface.points[:, 2]
            if frame.point_coordinates is not None:
                mesh.point_data[SOURCE_INDEX_FIELD] = surface.rows - frame.x_start
            remaining, caps = self._partition_surface(mesh, frame)
            cap_color = layer.clip_color if layer.markers.highlight_clipped else layer.color
            for part, color in ((remaining, layer.color), *((cap, cap_color) for cap in caps)):
                if not part.n_points:
                    continue
                actor = self.canvas.add_mesh(part, color=color, scalars=None, lighting=False,
                    opacity=layer.opacity, show_scalar_bar=False, reset_camera=False, render=False,
                    style="points" if points else "surface", point_size=layer.point_size)
                actor.SetScale(layer.x.scale, layer.y.scale, layer.z_mapping.scale)
                actor.SetPosition(layer.x.offset, layer.y.offset, layer.z_mapping.offset)
                self.canvas.layers.append((actor, layer))
                self.canvas.picker.AddPickList(actor)
        if self.canvas.layers:
            first_frame = self.canvas.layers[0][1].frame
            self.canvas.show_grid(xtitle=first_frame.x_grid.label() if first_frame.x_grid else "Display X",
                                  ytitle=first_frame.y_grid.label("Y") if first_frame.y_grid else "Display Y", ztitle="Value",
                                  color="#adb9cb" if self.dark else "#465368", font_size=10,
                                  fmt=AXIS_LABEL_FORMAT, render=False)
            self._update_axes()
            if reset:
                self.canvas.view_isometric()
                self.fit_camera()
            else:
                self.canvas.camera_position = camera
        self.readout.setText("Move over a surface to inspect its matrix and original value")
        self.resolution.setText(" | ".join(f"{layer.label}: {len(layer.frame.surface.points):,} points"
                                          for layer in layers if layer.frame.surface is not None))
        self.canvas.reset_camera_clipping_range()
        self.canvas.render()

    def set_layer_profiles(self, row: bool, position: float | None) -> None:
        """Mark the nearest source slice using the shared 3D selection color.

        Args:
            row: True selects rows, False columns.
            position: Shared display coordinate; None clears the selection.
        """
        for actor in self._layer_profiles:
            self.canvas.remove_actor(actor, reset_camera=False, render=False)
        self._layer_profiles.clear()
        if position is None:
            self._update_axes()
            self.canvas.render()
            return
        for layer in self._layers:
            series = profile_series(layer, row, position)
            if series is None or series.index is None:
                continue
            frame = layer.frame
            along = series.mapping.array(series.source_x)
            across = (frame.y_mapping.then(layer.y) if row else frame.x_mapping.then(layer.x)).forward(series.index)
            low, high = frame.limits
            if self.profile_style == ProfileStyle.SECTION_PLANE:
                ends = [float(along[0]), float(along[-1])]
                z0 = layer.z_mapping.forward(low - (high - low) * SECTION_HEIGHT_PADDING)
                z1 = layer.z_mapping.forward(high + (high - low) * SECTION_HEIGHT_PADDING)
                vertices = np.array([[ends[0], across, z0], [ends[1], across, z0],
                                     [ends[1], across, z1], [ends[0], across, z1]])
                if not row:
                    vertices[:, [0, 1]] = vertices[:, [1, 0]]
                mesh = pv.PolyData(vertices, np.array([4, 0, 1, 2, 3]))
                actor = self.canvas.add_mesh(mesh, color=self.profile_color, opacity=self.section_opacity,
                                            lighting=False, reset_camera=False, render=False)
            else:
                z = np.where(series.valid, series.shown, 0).astype(np.float64)
                z = layer.z_mapping.array(z + (high - low) * self.profile_lift)
                vertices = np.column_stack((along, np.full(len(along), across), z))
                if not row:
                    vertices[:, [0, 1]] = vertices[:, [1, 0]]
                indices = np.flatnonzero(series.valid[:-1] & series.valid[1:])
                if not len(indices):
                    continue
                mesh = pv.PolyData(vertices)
                mesh.lines = np.column_stack((np.full(len(indices), 2), indices, indices + 1)).ravel()
                actor = self.canvas.add_mesh(mesh, color=self.profile_color, line_width=3, lighting=False,
                                            reset_camera=False, render=False)
            self._layer_profiles.append(actor)
        self._update_axes()
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
        if not self.highlight_clipped:
            return
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
            self._update_axes()
            self.canvas.render()
            return
        h, w = frame.scalar.shape
        local_index = index - (frame.y_start if by_row else frame.x_start)
        if not 0 <= local_index < (h if by_row else w):
            self._update_axes()
            self.canvas.render()
            return
        valid = frame.valid[local_index, :] if by_row else frame.valid[:, local_index]
        visible = np.any(frame.valid) if self.profile_style == ProfileStyle.SECTION_PLANE else np.any(valid)
        if not visible:
            self._update_axes()
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
            points[:, 0] = frame.x_mapping.array(points[:, 0])
            points[:, 1] = frame.y_mapping.array(points[:, 1])
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
        self._update_axes()
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
        points[:, 0] = frame.x_mapping.array(points[:, 0])
        points[:, 1] = frame.y_mapping.array(points[:, 1])
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
        self._update_axes()
        self.canvas.reset_camera_clipping_range()
        self._update_resolution()
        self.canvas.render()

    @property
    def value_z_mapping(self) -> AxisMap:
        """Map the Z axis's source values to geometry before scene stretching.

        Independently aligned overlays cannot share every layer's source scale.
        The visible alignment reference defines the common annotation units.
        Geometry clipping remains explicitly in height/alignment coordinates.
        """
        if self._layers:
            layer = next((item for item in self._layers if item.uid == self._z_reference_uid), self._layers[0])
            return layer.z_mapping
        return AxisMap(self.z_scale)

    def _update_axes(self) -> None:
        """Refresh geometry bounds and keep Z tick magnitudes explicit.

        Axis annotations undo height/alignment and the scientific multiplier;
        actor coordinates, camera proportions and source samples stay intact.
        Recompute after geometry changes because PyVista resets annotation
        ranges when bounds are updated. Disable VTK's additional automatic
        scaling to avoid a second, potentially hidden exponent.
        """
        self._apply_axis_scale()
        self.canvas.renderer.update_bounds_axes()
        axes = self.canvas.renderer.cube_axes_actor
        if axes is None:
            return
        sx, sy, sz = self.canvas.axis_scale
        if self.z_range_lock:
            candidate = self.z_view_range or (axes.bounds[4] / sz, axes.bounds[5] / sz)
            if all(math.isfinite(value) for value in candidate) and candidate[0] <= candidate[1]:
                previous = self._locked_z_range
                self._locked_z_range = (candidate if previous is None else
                                        (min(previous[0], candidate[0]), max(previous[1], candidate[1])))
        limits = self.effective_z_range
        self._apply_z_clipping()
        if limits is not None:
            bounds = axes.bounds
            axes.bounds = (bounds[0], bounds[1], bounds[2], bounds[3],
                           limits[0] * sz, limits[1] * sz)
        bounds = axes.bounds
        axes.x_axis_range = (bounds[0] / sx, bounds[1] / sx)
        axes.y_axis_range = (bounds[2] / sy, bounds[3] / sy)
        mapping = self.value_z_mapping
        lower, upper = mapping.inverse(bounds[4] / sz), mapping.inverse(bounds[5] / sz)
        if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
            return
        peak = max(abs(lower), abs(upper))
        exponent = (max(MIN_LABEL_EXPONENT, math.floor(math.log10(peak)))
                    if peak and (peak < Z_SCIENTIFIC_MIN or peak >= Z_SCIENTIFIC_MAX) else 0)
        multiplier = 10.0 ** exponent
        title = "Value"
        reference = next((item for item in self._layers if item.uid == self._z_reference_uid),
                         self._layers[0] if self._layers else None)
        self.z_range_label.setToolTip(
            f"Z values use the alignment reference: {reference.label}" if reference is not None
            else "Source values before height and XYZ scaling.")
        axes.SetLabelScaling(False, 0, 0, 0)
        # Bounds updates regenerate PyVista's X/Y labels and scaled Z range.
        # X/Y always use native rounded ticks; optional endpoint labels apply
        # only to Z/color. This preserves fractional coordinates when needed.
        axes.x_label_format = AXIS_LABEL_FORMAT
        axes.y_label_format = AXIS_LABEL_FORMAT
        axes.SetAxisLabels(0, None)
        axes.SetAxisLabels(1, None)
        axes.SetXLabelFormat("%.4g")
        axes.SetYLabelFormat("%.4g")
        axes.z_label_format = AXIS_LABEL_FORMAT
        axes.z_axis_range = (lower / multiplier, upper / multiplier)
        axes.z_title = f"{title} (x 10^{exponent})" if exponent else title
        # PyVista otherwise supplies evenly spaced strings, often with awkward
        # decimals. Let VTK choose rounded ticks; turn Z labels across the axis
        # so adjacent labels do not run into one another along its length.
        axes.SetUse2DMode(False)
        for axis in range(3):
            axes.GetLabelTextProperty(axis).SetOrientation(90)
        if not self.endpoint_ticks:
            axes.SetAxisLabels(2, None)
            axes.SetZLabelFormat("%.4g")
        self._space_axis_labels()
        self._update_color_ticks()
        self._update_range_notes(lower, upper)

    def _space_axis_labels(self) -> None:
        """Thin labels on short scaled axes without changing coordinate ranges.

        VTK's automatic step depends only on the numeric range. On compressed
        axes use two to four evenly spaced labels instead; the longest axes
        retain its rounded automatic ticks. Keeping the custom count below five
        makes VTK place these labels at exactly uniform positions across the
        original range. Automatic Z boxes round with a scale-independent budget;
        above one tenth of the longest axis they retain intermediate labels.
        manual/locked Z boxes use native ticks unless endpoint ticks are enabled.
        Integer X/Y endpoints prefer integer intermediate labels.
        Endpoint-inclusive Z remains explicit, including when the axis is long.
        """
        axes = self.canvas.renderer.cube_axes_actor
        if axes is None:
            return
        bounds = axes.bounds
        lengths = tuple(max(0.0, bounds[2 * axis + 1] - bounds[2 * axis]) for axis in range(3))
        longest = max(lengths)
        if not math.isfinite(longest) or longest <= 0:
            return
        ranges = (axes.GetXAxisRange(), axes.GetYAxisRange(), axes.GetZAxisRange())
        for axis, (length, limits) in enumerate(zip(lengths, ranges)):
            lower, upper = limits
            count = max(2, math.ceil(FULL_AXIS_TICK_BUDGET * length / longest))
            if not all(math.isfinite(value) for value in (lower, upper, upper - lower)) or upper <= lower:
                continue
            if axis == 2 and not self.endpoint_ticks:
                if self.effective_z_range is not None:
                    continue
                # Tick density must not feed back into the annotation bounds:
                # changing Z scale should stretch the same box, not re-round it.
                values = _rounded_axis_ticks(lower, upper, AUTO_Z_TICK_BUDGET)
                if not values:
                    continue
                # Expand only the annotation box, mapping label units (including
                # the explicit Z exponent) back to stretched world coordinates.
                scale = length / (upper - lower)
                z_low = bounds[4] + (values[0] - lower) * scale
                z_high = bounds[5] + (values[-1] - upper) * scale
                if not all(math.isfinite(value) for value in (z_low, z_high)):
                    continue
                axes.SetBounds(*bounds[:4], z_low, z_high)
                axes.SetZAxisRange(values[0], values[-1])
                if count >= 5:
                    axes.SetAxisLabels(axis, None)
                    continue
                if length / longest < COMPRESSED_Z_AXIS_RATIO:
                    values = (values[0], values[-1])
                labels = vtkStringArray()
                for value in values:
                    labels.InsertNextValue(f"{value:.4g}")
                axes.SetAxisLabels(axis, labels)
                continue
            if count >= 5 and not (axis == 2 and self.endpoint_ticks):
                continue
            count = min(count, 4)
            if float(lower).is_integer() and float(upper).is_integer():
                while count > 2 and (upper - lower) % (count - 1):
                    count -= 1
            labels = vtkStringArray()
            for index in range(count):
                value = lower + (upper - lower) * index / (count - 1)
                labels.InsertNextValue(f"{value:.4g}")
            axes.SetAxisLabels(axis, labels)

    def set_endpoint_ticks(self, enabled: bool) -> None:
        """Toggle explicit Z/color endpoints without changing ranges or camera."""
        self.endpoint_ticks = enabled
        self._update_axes()
        self.canvas.render()

    def _update_color_ticks(self) -> None:
        """Use endpoint-inclusive color ticks only when explicitly requested."""
        for bar in self.canvas.scalar_bars.values():
            enabled = self.endpoint_ticks and self._color_limits is not None
            bar.SetUseCustomLabels(enabled)
            bar.SetLabelFormat("%.8g" if enabled else "%.3g")
            if enabled and self._color_limits is not None:
                labels = vtkDoubleArray()
                for value in np.linspace(*self._color_limits, 5):
                    labels.InsertNextValue(float(value))
                bar.SetCustomLabels(labels)

    def _update_range_notes(self, lower: float, upper: float) -> None:
        """Keep precise ranges outside the scene, independent of VTK font scaling."""
        self.color_range_label.set_limits(self._color_limits)
        self.z_range_label.set_limits((lower, upper))

    def _invalidate_extrema(self, key: tuple[int, ...]) -> None:
        """Invalidate source-value statistics without scanning geometry or arrays."""
        if key != self._extrema_key:
            self._extrema_key = key
            self.extrema_generation += 1
            self.extrema_label.clear()
            self.extrema_label.hide()

    def _apply_z_clipping(self) -> None:
        """Clip mapper output in world coordinates; actor input arrays stay intact."""
        planes: list[vtkPlane] = []
        limits = self.effective_z_range
        if limits is not None and limits[0] < limits[1]:
            for value, normal in zip(limits, (1.0, -1.0)):
                plane = vtkPlane()
                plane.SetOrigin(0, 0, value * self.canvas.axis_scale[2])
                plane.SetNormal(0, 0, normal)
                planes.append(plane)
        for actor in (self._surface_actor, self._profile_actor, *self._clip_actors,
                      *(actor for actor, _layer in self.canvas.layers), *self._layer_profiles):
            if actor is not None and (mapper := actor.GetMapper()) is not None:
                mapper.RemoveAllClippingPlanes()
                for plane in planes:
                    mapper.AddClippingPlane(plane)

    @property
    def effective_z_range(self) -> tuple[float, float] | None:
        """Current full-unit Z override, with lock history taking precedence."""
        return self._locked_z_range if self.z_range_lock and self._locked_z_range is not None else self.z_view_range

    def set_z_range_lock(self, enabled: bool) -> None:
        """Start/end expand-only geometry bounds independently of scalar colors.

        History uses height/alignment coordinates before scene multipliers and
        survives matrix, overlay and slice rebuilds. Unlock restores the saved
        manual Z range (or automatic bounds); toggling on starts fresh history.
        """
        if enabled == self.z_range_lock:
            return
        self.z_range_lock = enabled
        self._locked_z_range = None
        self.fit_camera()

    def set_z_view_range(self, limits: tuple[float, float] | None) -> None:
        """Set exact displayed Z bounds, or restore automatic bounds with None.

        Bounds use full displayed Z coordinates after height/alignment but before
        scene axis multipliers. All meshes, points and slice markers are clipped
        for display only. Color levels and numerical exports are unchanged.
        Raises ValueError for reversed, empty, nonfinite or overflowing ranges.
        """
        if limits is not None:
            low, high = limits
            scale = self.canvas.axis_scale[2]
            if low >= high or not all(math.isfinite(value) for value in
                                     (low, high, high - low, low * scale, high * scale, (high - low) * scale)):
                raise ValueError("Geometry Z range needs finite Minimum < Maximum values within the scene scale.")
        self.z_view_range = limits
        self.fit_camera()

    def fit_camera(self) -> None:
        """Fit the current camera direction to the geometry display box."""
        self._update_axes()
        axes = self.canvas.renderer.cube_axes_actor
        bounds = axes.bounds if axes is not None else None
        self.canvas.reset_camera(bounds=bounds, render=False)
        self.canvas.render()

    def _apply_axis_scale(self) -> None:
        """Compose scene stretching after each actor's height and alignment."""
        matrix = vtkMatrix4x4()
        for axis, value in enumerate(self.canvas.axis_scale):
            matrix.SetElement(axis, axis, value)
        for actor in (self._surface_actor, self._profile_actor, *self._clip_actors,
                      *(actor for actor, _layer in self.canvas.layers), *self._layer_profiles):
            if actor is not None:
                actor.SetUserMatrix(matrix)

    def set_equal_xy_locked(self, enabled: bool) -> None:
        """Lock scene X/Y units together, using the current X scale on enabling.

        Args:
            enabled: True matches Y to X immediately; False retains both current
                scales and permits subsequent independent edits. Z is unchanged.

        Side effects:
            Updates geometry and the camera focal point without resetting its
            direction. Source arrays and per-layer alignment are unaffected.
        """
        self.equal_xy_locked = enabled
        if enabled:
            x, _y, z = self.canvas.axis_scale
            self.set_axis_scale((x, x, z))

    def set_axis_scale(self, values: tuple[float, float, float], *, fit: bool = False) -> None:
        """Stretch each scene axis without changing samples or actor-local data.

        Args:
            values: Positive X/Y/Z multipliers in [1e-12, 1e12]. Applied after
                per-matrix height and alignment to every visible layer/marker.
                With XY locked, an isolated Y edit drives X; otherwise X drives
                Y. The scaling editor mirrors text edits so the last edit wins.
            fit: Fit the camera after applying; otherwise keep its distance
                and orientation, moving its focus with the stretched scene.

        Raises:
            ValueError: A multiplier is nonfinite or outside the allowed range.

        Side effects:
            Updates geometry transforms, coordinate labels, picking and render.
        """
        if any(not math.isfinite(value) or not MIN_AXIS_SCALE <= value <= MAX_AXIS_SCALE for value in values):
            raise ValueError(f"Axis multipliers must be between {MIN_AXIS_SCALE:g} and {MAX_AXIS_SCALE:g}.")
        limits = self.effective_z_range
        if limits is not None and not all(math.isfinite(value * values[2])
                for value in (*limits, limits[1] - limits[0])):
            raise ValueError("Z multiplier overflows the manual geometry range.")
        previous = self.canvas.axis_scale
        if self.equal_xy_locked:
            xy = values[1] if values[0] == previous[0] and values[1] != previous[1] else values[0]
            values = (xy, xy, values[2])
        camera = self.canvas.camera
        focus, position = camera.GetFocalPoint(), camera.GetPosition()
        shift = tuple(focus[axis] * (values[axis] / previous[axis] - 1) for axis in range(3))
        self.canvas.axis_scale = values
        self._update_axes()
        camera.SetFocalPoint(*(focus[axis] + shift[axis] for axis in range(3)))
        camera.SetPosition(*(position[axis] + shift[axis] for axis in range(3)))
        if fit:
            self.fit_camera()
        self.canvas.reset_camera_clipping_range()
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
        self.fit_camera()

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
