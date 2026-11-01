"""View-wide axis scaling for images, signals, derivatives and 3D scenes.

Requirements: PySide6, pyqtgraph and the viewer's existing rendering modules.
Usage: WorkspaceWindow owns ViewScaling; plot menus and View settings open its
modal editor. Edits change presentation, never source arrays or numeric exports.
Apply auto scaling is a one-shot fit. Flat views accept explicit ranges; manual
single-axis edits release the XY lock and manual Y edits disable slice Auto Y.
3D multipliers compose after per-matrix height/alignment and affect every layer.
Equal-axis presets match coordinate units, not axis spans, and remain editable.
Axis menus offer coarse/fine zoom and reset only the selected axis: fit its
displayed data in flat views, or restore its scene multiplier to 1 in 3D.
3D defaults to a persistent XY unit lock: X/Y zoom, reset and manual edits act
on both axes together until unlocked; Z remains independent.
Opening menus/dialogs never computes an unopened derivative or prepares meshes.
Scalar 2D/3D views share per-channel color bounds, exposed here alongside spatial
scaling. Blank color bounds use the data range; manual bounds never crop data.
Independent 3D Z bounds fix the geometry box and clip display only; Auto Z clears
the override. They are view-wide and survive camera fits and matrix changes.
The editor shows read-only plotted extents and automatic color/geometry bounds
alongside manual entries, so publication ranges can be chosen without refitting.
An opt-in workspace-wide checkbox adds value-axis/colorbar endpoint ticks;
automatic tick selection remains the default and manual ranges are preserved.
The optional Y-range lock shares signal/slice history across files and overlays,
with separate lazy derivative history. Unlocking restores slice Auto Y policy.
"""

import math
from enum import IntEnum, StrEnum
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets
from pyqtgraph.graphicsItems.ViewBox.ViewBox import ViewBox

from .data_model import ViewMode
from .figure_export import FigureView
from .surface_view import MAX_AXIS_SCALE, MIN_AXIS_SCALE
from .plot_support import EndpointAxis
from .profile_view import ExpandingYRange

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow

ZOOM_STEP = 2.0
FINE_ZOOM_STEP = 1.2
IMAGE_FIT_PADDING = 0.02


class Axis(IntEnum):
    """Coordinate indices used consistently by range and scene editors."""

    X = 0
    Y = 1
    Z = 2


class EqualAxes(StrEnum):
    """One-shot 3D unit-scale presets; flat views additionally retain an XY lock."""

    XY = "X:Y = 1:1"
    YZ = "Y:Z = 1:1"
    ZX = "Z:X = 1:1"
    XYZ = "X:Y:Z = 1:1:1"

    @property
    def axes(self) -> tuple[Axis, ...]:
        """Return the reference axis first, followed by axes to match."""
        return {EqualAxes.XY: (Axis.X, Axis.Y), EqualAxes.YZ: (Axis.Y, Axis.Z),
                EqualAxes.ZX: (Axis.Z, Axis.X), EqualAxes.XYZ: (Axis.X, Axis.Y, Axis.Z)}[self]


class ViewScaling(QtCore.QObject):
    """Share scaling actions between menus and the modal editor.

    Args:
        window: Fully constructed workspace with all plot widgets available.
    """

    def __init__(self, window: "WorkspaceWindow") -> None:
        super().__init__(window)
        self.window = window
        self.endpoint_ticks = False
        self.y_range_lock = False
        self._y_histories = (ExpandingYRange(), ExpandingYRange())
        for profile in (window.profile_view, window.overlay_profile):
            for pane, history in zip((profile.signal_pane, profile.derivative_pane), self._y_histories):
                pane.view_box.y_range_lock = history

    def set_y_range_lock(self, enabled: bool) -> None:
        """Start/end expanding Y ranges across slices, files and overlay modes.

        Signal and derivative use independent histories, seeded from currently
        plotted panes. Unlocking restores the saved slice Auto Y preference.
        """
        if enabled == self.y_range_lock:
            return
        self.y_range_lock = enabled
        window = self.window
        active = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        for pane, history in zip((active.signal_pane, active.derivative_pane), self._y_histories):
            history.enabled = enabled
            low, high = pane.view_box.viewRange()[1]
            history.bounds = ((low, high) if enabled and pane.view_box.childrenBounds()[1] is not None else None)
        for profile in (window.profile_view, window.overlay_profile):
            for pane in (profile.signal_pane, profile.derivative_pane):
                if enabled:
                    pane.view_box.setAspectLocked(False)
                auto_y = enabled or window._layout_mode != ViewMode.MATRIX or window._profile_auto_y
                pane.view_box.enableAutoRange(axis=ViewBox.YAxis, enable=auto_y)
                if not enabled and auto_y:
                    pane.view_box.updateAutoRange()
        if hasattr(window, "view_settings"):
            window.view_settings.refresh()

    def set_endpoint_ticks(self, enabled: bool) -> None:
        """Share optional value-axis endpoints across all views in this workspace.

        Defaults to automatic ticks. Changes annotation only, including hidden
        signal/derivative panes; no lazy data computation or refitting occurs.
        """
        self.endpoint_ticks = enabled
        self.window.image_view.color_axis.set_endpoint_ticks(enabled)
        for profile in (self.window.profile_view, self.window.overlay_profile):
            for pane in (profile.signal_pane, profile.derivative_pane):
                axis = pane.plot_item.getAxis("left")
                if isinstance(axis, EndpointAxis):
                    axis.set_endpoint_ticks(enabled)
        self.window.surface_view.set_endpoint_ticks(enabled)

    def set_z_range_lock(self, enabled: bool) -> None:
        """Toggle the separate 3D geometry lock and synchronize its controls."""
        self.window.surface_view.set_z_range_lock(enabled)
        if hasattr(self.window, "view_settings"):
            self.window.view_settings.refresh()

    def available(self, view: FigureView) -> bool:
        """Check prepared view data without triggering lazy computations."""
        window = self.window
        if (not window.matrix_box.isEnabled() or window._preparing or window._rebuild.isActive()
                or not any(entry.visible and entry.frame is not None for entry in window.entries)):
            return False
        mode = window._layout_mode
        if view == FigureView.SURFACE:
            return mode in (ViewMode.MATRIX, ViewMode.POINTS) and window.tabs.currentIndex() == 1
        if view == FigureView.IMAGE:
            return mode == ViewMode.MATRIX
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        if mode in (ViewMode.POINTS, ViewMode.RAW):
            return False
        if view == FigureView.DERIVATIVE:
            return profile.tabs.currentIndex() == 1 and profile.tabs.isTabEnabled(1)
        return bool(window.overlay_profile._series) if window._profile_uses_overlay else profile.values is not None

    def box(self, view: FigureView) -> ViewBox:
        """Return the active flat viewport; never creates or calculates data."""
        if view == FigureView.SURFACE:
            raise ValueError("A 3D scene has no flat viewport range.")
        window = self.window
        if view == FigureView.IMAGE:
            return window.image_view.view_box
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        return profile.derivative_pane.view_box if view == FigureView.DERIVATIVE else profile.signal_pane.view_box

    def equal_xy(self, view: FigureView, enabled: bool) -> None:
        """Set a persistent flat/3D unit lock, shared across overlay modes."""
        window = self.window
        if view == FigureView.SURFACE:
            window.surface_view.set_equal_xy_locked(enabled)
        elif view == FigureView.IMAGE:
            window.image_view.set_equal_xy(enabled)
        else:
            for profile in (window.profile_view, window.overlay_profile):
                pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
                pane.view_box.setAspectLocked(enabled, ratio=1.0)

    def apply_auto(self, view: FigureView) -> None:
        """Fit once; 3D also restores automatic Z bounds and height balance."""
        if not self.available(view):
            return
        if view == FigureView.SURFACE:
            self.window.surface_view.set_z_view_range(None)
            self.window._auto_3d_scale()
            return
        box = self.box(view)
        self.equal_xy(view, False)
        box.disableAutoRange()
        if view == FigureView.IMAGE:
            self.window.image_view.reset_view()
        else:
            box.autoRange()
        box.disableAutoRange()

    def set_ranges(self, view: FigureView, x: tuple[float, float], y: tuple[float, float], *, manual_y: bool = True) -> None:
        """Apply exact flat ranges, releasing locks and conflicting Y fitting.

        Args:
            view: Image, signal or derivative viewport.
            x: Increasing finite horizontal bounds.
            y: Increasing finite vertical bounds.
            manual_y: Disable slice Auto Y when the user explicitly adjusts Y.

        Raises:
            ValueError: A range is empty, reversed or nonfinite.
        """
        for lower, upper in (x, y):
            if not all(math.isfinite(value) for value in (lower, upper, upper - lower)) or lower >= upper:
                raise ValueError("Each axis needs finite Minimum < Maximum values.")
        if not self.available(view):
            return
        box = self.box(view)
        box.disableAutoRange()
        self.equal_xy(view, False)
        if manual_y and view in (FigureView.SIGNAL, FigureView.DERIVATIVE) and self.window._layout_mode == ViewMode.MATRIX:
            self.window._set_profile_auto_y(False)
            self.window.view_settings.refresh()
        box.setRange(xRange=x, yRange=y, padding=0, disableAutoRange=True)

    def zoom_axis(self, view: FigureView, axis: Axis, factor: float) -> None:
        """Enlarge one axis about the view center; factor > 1 zooms in.

        For 3D this edits a scene multiplier, preserving the camera direction.
        Invalid/overflowing scales raise ValueError before changing the view.
        """
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be positive and finite.")
        if not self.available(view):
            return
        if view == FigureView.SURFACE:
            values = list(self.window.surface_view.canvas.axis_scale)
            values[axis] *= factor
            self.window.surface_view.set_axis_scale((values[0], values[1], values[2]))
            return
        if axis == Axis.Z:
            raise ValueError("Flat views have only X and Y axes.")
        ranges = self.box(view).viewRange()
        lower, upper = ranges[axis]
        center, half = lower / 2 + upper / 2, (upper - lower) / (2 * factor)
        ranges[axis] = [center - half, center + half]
        self.set_ranges(view, (ranges[0][0], ranges[0][1]), (ranges[1][0], ranges[1][1]), manual_y=axis == Axis.Y)

    def reset_axis(self, view: FigureView, axis: Axis) -> None:
        """Reset one axis while preserving the other axis ranges/multipliers.

        Args:
            view: Prepared image, signal, derivative or surface view.
            axis: X/Y for flat views, or X/Y/Z for a surface.

        Flat views fit displayed data once and release the XY lock; resetting
        slice Y also disables continuous Auto Y. 3D restores the selected scene
        multiplier to 1, retaining matrix heights, alignment and camera direction.
        Empty flat bounds leave the view unchanged.

        Raises:
            ValueError: Z is requested for a flat view or bounds are not finite.
        """
        if not self.available(view):
            return
        if view == FigureView.SURFACE:
            values = list(self.window.surface_view.canvas.axis_scale)
            values[axis] = 1.0
            self.window.surface_view.set_axis_scale((values[0], values[1], values[2]))
            return
        if axis == Axis.Z:
            raise ValueError("Flat views have only X and Y axes.")
        box = self.box(view)
        bounds = self.window.image_view.fit_bounds() if view == FigureView.IMAGE else box.childrenBounds()
        if bounds is None:
            return
        selected = bounds[axis]
        if selected is None:
            return
        lower, upper = float(selected[0]), float(selected[1])
        if lower == upper:
            lower, upper = lower - 0.5, upper + 0.5
        padding = IMAGE_FIT_PADDING if view == FigureView.IMAGE else box.suggestPadding(axis)
        margin = (upper - lower) * padding
        ranges = box.viewRange()
        ranges[axis] = [lower - margin, upper + margin]
        self.set_ranges(view, (ranges[0][0], ranges[0][1]), (ranges[1][0], ranges[1][1]), manual_y=axis == Axis.Y)

    def reset_from_menu(self, view: FigureView, axis: Axis) -> None:
        """Reset a menu axis, reporting invalid bounds in a warning dialog."""
        try:
            self.reset_axis(view, axis)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self.window, "Scaling limit", str(exc))

    def equal_axes(self, view: FigureView, preset: EqualAxes) -> None:
        """Match selected coordinate-unit scales, preserving source samples."""
        if not self.available(view):
            return
        if view == FigureView.SURFACE:
            self.window._equal_xyz_scale(preset.axes)
        elif preset == EqualAxes.XY:
            self.equal_xy(view, True)

    def zoom_from_menu(self, view: FigureView, axis: Axis, factor: float) -> None:
        """Run a menu zoom with a visible range-limit error instead of a traceback."""
        try:
            self.zoom_axis(view, axis, factor)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self.window, "Scaling limit", str(exc))

    def show_for(self, view: FigureView) -> None:
        """Open the scaling editor for prepared data only, preserving plot tabs."""
        if self.available(view):
            dialog = ScalingDialog(self, view)
            dialog.exec()
            dialog.deleteLater()

    def color_available(self) -> bool:
        """Allow scalar color editing only for the visible active matrix/channel."""
        window = self.window
        entry = window._entry()
        return (entry is not None and entry.visible and entry.frame is not None
                and entry.selection.mode in (ViewMode.MATRIX, ViewMode.POINTS)
                and not entry.frame.composite and not window._overlay()
                and window.controls.isEnabled() and window.matrix_box.isEnabled())

    def set_color_range(self, lower: float | None, upper: float | None) -> None:
        """Apply shared 2D/3D color bounds; None restores the automatic endpoint.

        Invalid bounds raise ValueError before changing widgets or renderers.
        Color settings stay with the active channel and never alter its samples.
        """
        entry = self.window._entry()
        if not self.color_available() or entry is None or entry.frame is None:
            return
        low = entry.frame.limits[0] if lower is None else lower
        high = entry.frame.limits[1] if upper is None else upper
        if not all(math.isfinite(value) for value in (low, high, high - low)) or low >= high:
            raise ValueError("Color range needs finite Minimum < Maximum values.")
        self.window.color_low.setText("" if lower is None else repr(lower))
        self.window.color_high.setText("" if upper is None else repr(upper))
        self.window._store_entry()
        self.window._presentation_changed()


class ScalingDialog(QtWidgets.QDialog):
    """Edit one view's ranges or scene multipliers with explicit Apply buttons.

    Args:
        controller: Workspace scaling controller; actions use existing views.
        view: Requested image, surface, signal or derivative viewport.

    Changes apply immediately on buttons; Close retains applied settings.
    Text entry accepts scientific notation and has no mouse-wheel behavior.
    """

    def __init__(self, controller: ViewScaling, view: FigureView) -> None:
        super().__init__(controller.window)
        self.controller, self.view = controller, view
        self.setWindowTitle(f"Scaling — {view.value}")
        self.setModal(True)
        self.resize(600, 320)
        layout = QtWidgets.QVBoxLayout(self)
        spatial = view == FigureView.SURFACE
        note = QtWidgets.QLabel(
            "Applies to all visible layers in this view. Scene multipliers act after each matrix's height and alignment. "
            "Axis labels and source values are unchanged." if spatial else
            "Change display ranges without cropping data. Single-axis edits release the X:Y lock. "
            "Manual Y changes turn off Auto Y on slice change."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        auto = QtWidgets.QPushButton("Apply auto scaling")
        auto.setToolTip("Fit once. In 3D, restore automatic Z bounds and matrix-height balance without changing camera direction.")
        auto.clicked.connect(self._auto)
        layout.addWidget(auto)
        self.endpoint_ticks = QtWidgets.QCheckBox("Show range endpoints on value axes / color bars (all views)")
        self.endpoint_ticks.setChecked(controller.endpoint_ticks)
        self.endpoint_ticks.setToolTip("Off: automatic ticks. On: include minimum/maximum on 1D Y, 3D Z and 2D/3D color scales. Does not change manual ranges.")
        self.endpoint_ticks.toggled.connect(controller.set_endpoint_ticks)
        layout.addWidget(self.endpoint_ticks)
        self.y_lock = QtWidgets.QCheckBox("Lock Y range (expand only, across slices and matrices)")
        self.y_lock.setChecked(controller.y_range_lock)
        self.y_lock.setVisible(view in (FigureView.SIGNAL, FigureView.DERIVATIVE))
        self.y_lock.setToolTip("Signal and derivative accumulate separate ranges. Turn off/on to start again. While locked, Y fitting and manual edits can only expand the range.")
        self.y_lock.toggled.connect(controller.set_y_range_lock)
        layout.addWidget(self.y_lock)
        grid = QtWidgets.QGridLayout()
        grid.setColumnMinimumWidth(0, 36)
        layout.addLayout(grid)
        headings = ("Axis", "Multiplier", "", "Zoom in", "Zoom out") if spatial else ("Axis", "Minimum", "Maximum", "Zoom in", "Zoom out")
        for column, text in enumerate(headings):
            grid.addWidget(QtWidgets.QLabel(text), 0, column)
        self.fields: dict[Axis, tuple[QtWidgets.QLineEdit, ...]] = {}
        for row, axis in enumerate(tuple(Axis) if spatial else (Axis.X, Axis.Y), start=1):
            grid.addWidget(QtWidgets.QLabel(axis.name), row, 0)
            fields = tuple(QtWidgets.QLineEdit() for _ in range(1 if spatial else 2))
            self.fields[axis] = fields
            for column, field in enumerate(fields, start=1):
                field.setToolTip("Finite numbers; scientific notation such as 1e-6 is accepted.")
                field.setAccessibleName(f"{axis.name} {headings[column]}")
                grid.addWidget(field, row, column, 1, 2 if spatial else 1)
            for column, text, factor in ((3, "×2", ZOOM_STEP), (4, "÷2", 1 / ZOOM_STEP)):
                button = QtWidgets.QPushButton(text)
                button.setToolTip(f"Scale {axis.name}; X/Y move together while the 3D XY lock is on." if spatial
                                  else f"{axis.name} axis only; enlarge" if factor > 1 else f"{axis.name} axis only; shrink")
                button.clicked.connect(partial(self._zoom, axis, factor))
                grid.addWidget(button, row, column)
        apply = QtWidgets.QPushButton("Apply multipliers" if spatial else "Apply ranges")
        apply.clicked.connect(self._apply)
        layout.addWidget(apply)
        self.axis_extents: dict[Axis, QtWidgets.QLabel] = {}
        if not spatial:
            for axis in (Axis.X, Axis.Y):
                label = self._range_label()
                self.axis_extents[axis] = label
                layout.addWidget(label)
        presets = QtWidgets.QHBoxLayout()
        layout.addLayout(presets)
        if spatial:
            for preset in EqualAxes:
                button = QtWidgets.QPushButton(preset.value)
                button.setToolTip("Match unit scales once. Z presets reset per-matrix height to 1; matched stretch alignments are reset. Afterwards every axis remains editable.")
                button.clicked.connect(partial(self._equal, preset))
                presets.addWidget(button)
        self.equal_lock = QtWidgets.QCheckBox("Lock X:Y = 1:1 (data units)")
        if spatial:
            self.equal_lock.setToolTip("Lock scene X/Y scales together. Enabling matches Y to X; Z and per-matrix overlay alignment stay independent.")
            for axis in (Axis.X, Axis.Y):
                self.fields[axis][0].textEdited.connect(partial(self._mirror_xy_text, axis))
        self.equal_lock.toggled.connect(self._lock)
        layout.addWidget(self.equal_lock)
        self.geometry_box = QtWidgets.QGroupBox("Geometry Z range (all visible layers)")
        geometry_layout = QtWidgets.QGridLayout(self.geometry_box)
        self.z_minimum, self.z_maximum = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for column, (label, field) in enumerate((("Minimum", self.z_minimum), ("Maximum", self.z_maximum))):
            geometry_layout.addWidget(QtWidgets.QLabel(label), 0, column * 2)
            geometry_layout.addWidget(field, 0, column * 2 + 1)
            field.setPlaceholderText("Automatic")
            field.setToolTip("Enter both bounds, or leave both blank for automatic bounds. Scientific notation is accepted.")
        self.apply_geometry = QtWidgets.QPushButton("Apply Z range")
        self.apply_geometry.clicked.connect(self._apply_geometry)
        self.auto_geometry = QtWidgets.QPushButton("Auto Z range")
        self.auto_geometry.clicked.connect(self._auto_geometry)
        geometry_layout.addWidget(self.apply_geometry, 1, 0, 1, 2)
        geometry_layout.addWidget(self.auto_geometry, 1, 2, 1, 2)
        geometry_note = QtWidgets.QLabel(
            "Display only: geometry outside this interval is hidden. Use full Z coordinates after "
            "height/alignment, before scene multipliers (not the abbreviated scientific ticks). "
            "Color bounds and source data are unchanged. Applies across matrix switches.")
        geometry_note.setWordWrap(True)
        geometry_layout.addWidget(geometry_note, 2, 0, 1, 4)
        self.geometry_extents = self._range_label()
        geometry_layout.addWidget(self.geometry_extents, 3, 0, 1, 4)
        self.z_lock = QtWidgets.QCheckBox("Lock Z range (expand only)")
        self.z_lock.setToolTip("Independent of the shared 2D/3D color lock. Keeps geometry bounds across matrices, overlays and height changes. Turn off/on to restart.")
        self.z_lock.toggled.connect(self._z_lock_changed)
        geometry_layout.addWidget(self.z_lock, 4, 0, 1, 4)
        self.effective_geometry_extents = self._range_label()
        geometry_layout.addWidget(self.effective_geometry_extents, 5, 0, 1, 4)
        self.geometry_box.setVisible(spatial)
        layout.addWidget(self.geometry_box)
        self.color_box = QtWidgets.QGroupBox("Color scale (shared by 2D and 3D)")
        color_layout = QtWidgets.QGridLayout(self.color_box)
        self.color_minimum, self.color_maximum = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        for column, (label, field) in enumerate((("Minimum", self.color_minimum), ("Maximum", self.color_maximum))):
            color_layout.addWidget(QtWidgets.QLabel(label), 0, column * 2)
            color_layout.addWidget(field, 0, column * 2 + 1)
            field.setPlaceholderText("Automatic")
            field.setToolTip("Blank uses the data bound. Scientific notation is accepted. Does not clip data.")
        self.apply_colors = QtWidgets.QPushButton("Apply color range")
        self.apply_colors.clicked.connect(self._apply_colors)
        self.auto_colors = QtWidgets.QPushButton("Auto color range")
        self.auto_colors.clicked.connect(self._auto_colors)
        color_layout.addWidget(self.apply_colors, 1, 0, 1, 2)
        color_layout.addWidget(self.auto_colors, 1, 2, 1, 2)
        color_note = QtWidgets.QLabel(
            "Stored for the active channel. Use the same bounds for comparable figures. "
            "Unavailable for original image colors or solid-color overlays.")
        color_note.setWordWrap(True)
        color_layout.addWidget(color_note, 2, 0, 1, 4)
        self.color_extents = self._range_label()
        color_layout.addWidget(self.color_extents, 3, 0, 1, 4)
        self.color_lock = QtWidgets.QCheckBox("Lock color range (expand only, shared by 2D / 3D)")
        self.color_lock.setToolTip(controller.window.color_range_lock.toolTip())
        self.color_lock.toggled.connect(self._color_lock_changed)
        color_layout.addWidget(self.color_lock, 4, 0, 1, 4)
        self.effective_color_extents = self._range_label()
        color_layout.addWidget(self.effective_color_extents, 5, 0, 1, 4)
        self.color_box.setVisible(view in (FigureView.IMAGE, FigureView.SURFACE))
        layout.addWidget(self.color_box)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    @staticmethod
    def _range_label() -> QtWidgets.QLabel:
        """Create a compact selectable reference that cannot modify plot ranges."""
        label = QtWidgets.QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _show_extents(label: QtWidgets.QLabel, title: str,
                      bounds: tuple[float, float] | None) -> None:
        """Show bounded-precision extrema, retaining full precision in the tooltip."""
        if bounds is None or not all(math.isfinite(value) for value in bounds) or bounds[0] > bounds[1]:
            label.setText(f"{title}: unavailable")
            label.setToolTip("No finite plotted bounds are available.")
            return
        lower, upper = bounds
        label.setText(f"{title}: Minimum {lower:.12g}   Maximum {upper:.12g}")
        label.setToolTip(f"{title}\nMinimum: {lower!r}\nMaximum: {upper!r}")

    def _curve_extents(self, axis: Axis) -> tuple[float, float] | None:
        """Read plotted samples without the pen/symbol padding used by auto-fit.

        Includes visible channel/overlay curves and markers, but not cursor
        lines. Uses existing plot data and never computes a hidden derivative.
        """
        window = self.controller.window
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        pane = profile.derivative_pane if self.view == FigureView.DERIVATIVE else profile.signal_pane
        ranges: list[tuple[float, float]] = []
        for item in pane.plot_item.listDataItems():
            if not item.isVisible():
                continue
            low, high = item.dataBounds(int(axis), frac=1.0)
            if low is not None and high is not None and math.isfinite(low) and math.isfinite(high):
                ranges.append((float(low), float(high)))
        return (min(low for low, _ in ranges), max(high for _, high in ranges)) if ranges else None

    def _refresh(self) -> None:
        self.color_box.setEnabled(self.controller.color_available())
        self.color_minimum.setText(self.controller.window.color_low.text())
        self.color_maximum.setText(self.controller.window.color_high.text())
        entry = self.controller.window._entry()
        color_bounds = (entry.frame.limits if self.controller.color_available()
                        and entry is not None and entry.frame is not None else None)
        self._show_extents(self.color_extents, "Automatic color range", color_bounds)
        self._refresh_color_lock()
        if self.view == FigureView.SURFACE:
            surface = self.controller.window.surface_view
            with QtCore.QSignalBlocker(self.equal_lock):
                self.equal_lock.setChecked(surface.equal_xy_locked)
            with QtCore.QSignalBlocker(self.z_lock):
                self.z_lock.setChecked(surface.z_range_lock)
            limits = surface.z_view_range
            for field, value in zip((self.z_minimum, self.z_maximum), limits or (None, None)):
                field.setText("" if value is None else repr(value))
            for axis, fields in self.fields.items():
                fields[0].setText(f"{surface.canvas.axis_scale[axis]:.15g}")
            renderer = surface.canvas.renderer
            axes = renderer.cube_axes_actor
            # Mapper clipping leaves actor bounds intact. Exclude the axes box,
            # whose Z bounds may themselves have been set manually.
            bounds = renderer.compute_bounds(ignore_actors=[axes] if axes is not None else [])
            scale_z = surface.canvas.axis_scale[Axis.Z]
            self._show_extents(self.geometry_extents, "Scene Z before view clipping",
                               (bounds[4] / scale_z, bounds[5] / scale_z))
            self._show_extents(self.effective_geometry_extents, "Displayed Z range",
                               None if axes is None else (axes.bounds[4] / scale_z, axes.bounds[5] / scale_z))
        else:
            box = self.controller.box(self.view)
            extents = (self.controller.window.image_view.fit_bounds()
                       if self.view == FigureView.IMAGE else None)
            for axis, fields in self.fields.items():
                for field, value in zip(fields, box.viewRange()[axis]):
                    field.setText(f"{value!r}")
                selected = (extents[axis] if extents is not None else None) if self.view == FigureView.IMAGE else self._curve_extents(axis)
                self._show_extents(self.axis_extents[axis], f"Plotted {axis.name} extents",
                                   None if selected is None else (float(selected[0]), float(selected[1])))
            with QtCore.QSignalBlocker(self.equal_lock):
                self.equal_lock.setChecked(box.state["aspectLocked"] is not False)

    def _refresh_color_lock(self) -> None:
        """Show the actual color bounds separately from per-channel manual fields."""
        window = self.controller.window
        with QtCore.QSignalBlocker(self.color_lock):
            self.color_lock.setChecked(window.color_range_lock.isChecked())
        entry = window._entry()
        levels = None
        if self.controller.color_available() and entry is not None and entry.frame is not None:
            try:
                levels = window._color_levels(entry.frame.limits)
                if window.color_range_lock.isChecked() and window._locked_color_limits is not None:
                    levels = window._locked_color_limits
            except ValueError:
                pass
        self._show_extents(self.effective_color_extents, "Displayed color range", levels)

    def _color_lock_changed(self, enabled: bool) -> None:
        """Toggle the workspace lock while preserving unsubmitted text edits."""
        self.controller.window.color_range_lock.setChecked(enabled)
        self._refresh_color_lock()

    def _auto(self) -> None:
        self.controller.apply_auto(self.view)
        self._refresh()

    def _apply_colors(self) -> None:
        try:
            low, high = self.color_minimum.text().strip(), self.color_maximum.text().strip()
            self.controller.set_color_range(float(low) if low else None, float(high) if high else None)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid color range", str(exc))
            return
        self._refresh()

    def _auto_colors(self) -> None:
        self.controller.set_color_range(None, None)
        self._refresh()

    def _apply_geometry(self) -> None:
        try:
            low, high = self.z_minimum.text().strip(), self.z_maximum.text().strip()
            if bool(low) != bool(high):
                raise ValueError("Enter both Z bounds, or leave both blank for automatic bounds.")
            self.controller.window.surface_view.set_z_view_range((float(low), float(high)) if low else None)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid geometry range", str(exc))
            return
        self._refresh()

    def _auto_geometry(self) -> None:
        self.controller.window.surface_view.set_z_view_range(None)
        self._refresh()

    def _z_lock_changed(self, enabled: bool) -> None:
        self.controller.set_z_range_lock(enabled)
        self._refresh()

    def _zoom(self, axis: Axis, factor: float) -> None:
        self.controller.zoom_from_menu(self.view, axis, factor)
        self._refresh()

    def _equal(self, preset: EqualAxes) -> None:
        self.controller.equal_axes(self.view, preset)
        self._refresh()

    def _lock(self, enabled: bool) -> None:
        self.controller.equal_xy(self.view, enabled)
        self._refresh()

    def _mirror_xy_text(self, axis: Axis, text: str) -> None:
        """Keep pending X/Y text consistent while the 3D scene lock is enabled."""
        if self.controller.window.surface_view.equal_xy_locked:
            other = Axis.Y if axis == Axis.X else Axis.X
            self.fields[other][0].setText(text)

    def _apply(self) -> None:
        try:
            values = {axis: tuple(float(field.text()) for field in fields) for axis, fields in self.fields.items()}
            if self.view == FigureView.SURFACE:
                scale = (values[Axis.X][0], values[Axis.Y][0], values[Axis.Z][0])
                if any(not math.isfinite(value) or not MIN_AXIS_SCALE <= value <= MAX_AXIS_SCALE for value in scale):
                    raise ValueError(f"Multipliers must be between {MIN_AXIS_SCALE:g} and {MAX_AXIS_SCALE:g}.")
                self.controller.window.surface_view.set_axis_scale(scale)
            else:
                x, y = values[Axis.X], values[Axis.Y]
                old_y = self.controller.box(self.view).viewRange()[Axis.Y]
                self.controller.set_ranges(self.view, (x[0], x[1]), (y[0], y[1]), manual_y=list(y) != old_y)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid scaling", str(exc))
            return
        self._refresh()
