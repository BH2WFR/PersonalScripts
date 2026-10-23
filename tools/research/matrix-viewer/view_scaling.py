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
Opening menus/dialogs never computes an unopened derivative or prepares meshes.
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
        if mode == ViewMode.POINTS:
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
        """Set the persistent flat-view unit lock, shared across overlay modes."""
        window = self.window
        if view == FigureView.IMAGE:
            window.image_view.set_equal_xy(enabled)
        else:
            for profile in (window.profile_view, window.overlay_profile):
                pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
                pane.view_box.setAspectLocked(enabled, ratio=1.0)

    def apply_auto(self, view: FigureView) -> None:
        """Fit data once; 3D also restores the default automatic height balance."""
        if not self.available(view):
            return
        if view == FigureView.SURFACE:
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
        auto.setToolTip("Fit once. In 3D, restore automatic matrix-height balance without changing camera direction.")
        auto.clicked.connect(self._auto)
        layout.addWidget(auto)
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
                button.setToolTip(f"{axis.name} axis only; enlarge" if factor > 1 else f"{axis.name} axis only; shrink")
                button.clicked.connect(partial(self._zoom, axis, factor))
                grid.addWidget(button, row, column)
        apply = QtWidgets.QPushButton("Apply multipliers" if spatial else "Apply ranges")
        apply.clicked.connect(self._apply)
        layout.addWidget(apply)
        presets = QtWidgets.QHBoxLayout()
        layout.addLayout(presets)
        if spatial:
            for preset in EqualAxes:
                button = QtWidgets.QPushButton(preset.value)
                button.setToolTip("Match unit scales once. Z presets reset per-matrix height to 1; matched stretch alignments are reset. Afterwards every axis remains editable.")
                button.clicked.connect(partial(self._equal, preset))
                presets.addWidget(button)
        self.equal_lock = QtWidgets.QCheckBox("Lock X:Y = 1:1 (data units)")
        self.equal_lock.setVisible(not spatial)
        self.equal_lock.toggled.connect(self._lock)
        layout.addWidget(self.equal_lock)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    def _refresh(self) -> None:
        if self.view == FigureView.SURFACE:
            for axis, fields in self.fields.items():
                fields[0].setText(f"{self.controller.window.surface_view.canvas.axis_scale[axis]:.15g}")
        else:
            box = self.controller.box(self.view)
            for axis, fields in self.fields.items():
                for field, value in zip(fields, box.viewRange()[axis]):
                    field.setText(f"{value!r}")
            with QtCore.QSignalBlocker(self.equal_lock):
                self.equal_lock.setChecked(box.state["aspectLocked"] is not False)

    def _auto(self) -> None:
        self.controller.apply_auto(self.view)
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
