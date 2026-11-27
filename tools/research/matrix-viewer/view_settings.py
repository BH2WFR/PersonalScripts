"""Central appearance dialog shared by plot buttons and context menus.

Requirements: PySide6 and the existing viewer modules. Usage: WorkspaceWindow
owns one persistent dialog. It hosts the original setting widgets, preserving
their signals and per-channel storage without a second copy of settings.
The sidebar retains data interpretation, cropping, sampling and alignment.
Changes apply immediately; Close retains them. Opening a page never selects a
plot tab or calculates derivatives. Background, slice markers and axes options
are shared. Dimension-specific appearance locks default on; locked styles and
sizes survive matrix/channel switches without replacing saved local settings.
Value marker flags/sizes have a shared lock. Colors have a separate single-mode
lock, suspended during multiple mode; ranges remain independent of appearance.
Dimension pages link to the shared Scaling editor. Hidden 3D/unopened derivative
scaling is disabled until that view is displayed, retaining lazy rendering.
"""

from enum import IntEnum
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from .data_model import ViewMode
from .figure_export import FigureView
from .ui_view_settings_dialog import Ui_ViewSettingsDialog

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow


class AppearancePage(IntEnum):
    """Stable pages for dimension-specific and shared appearance settings."""

    SIGNAL = 0
    IMAGE = 1
    SURFACE = 2
    COLORS = 3
    MARKERS = 4


class ViewSettingsDialog(QtWidgets.QDialog, Ui_ViewSettingsDialog):
    """Edit appearance with a single discoverable entry beside each viewer.

    Args:
        window: Constructed workspace whose existing controls are reparented
            into this dialog. The dialog lives for the workspace's lifetime.
    """

    def __init__(self, window: "WorkspaceWindow") -> None:
        super().__init__(window)
        self.setupUi(self)
        self.workspace = window
        self.setModal(True)
        self.source.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        for profile in (window.profile_view, window.overlay_profile):
            self.profile_stack.addWidget(profile.appearance_controls)
        self.signal_grid.toggled.connect(lambda enabled: self._grid(False, enabled))
        self.derivative_grid.toggled.connect(lambda enabled: self._grid(True, enabled))
        self.auto_y.toggled.connect(window._set_profile_auto_y)
        self.y_lock.toggled.connect(window.scaling.set_y_range_lock)
        self.z_lock.toggled.connect(window.scaling.set_z_range_lock)
        self.scaling_buttons = {
            FigureView.SIGNAL: self.signal_scaling_button, FigureView.DERIVATIVE: self.derivative_scaling_button,
            FigureView.IMAGE: self.image_scaling_button, FigureView.SURFACE: self.surface_scaling_button,
        }
        for view, button in self.scaling_buttons.items():
            button.clicked.connect(partial(window.scaling.show_for, view))
        for layout, control in (
            (self.signal_lock_slot, window.appearance_locks[AppearancePage.SIGNAL]),
            (self.image_lock_slot, window.appearance_locks[AppearancePage.IMAGE]),
            (self.image_controls_slot, window.image_controls),
            (self.surface_lock_slot, window.appearance_locks[AppearancePage.SURFACE]),
            (self.surface_controls_slot, window.surface_controls),
            (self.slice_appearance_slot, window.slice_appearance),
            (self.colors_lock_slot, window.appearance_locks[AppearancePage.COLORS]),
            (self.display_box_slot, window.display_box),
            (self.overlay_appearance_slot, window.overlay_appearance),
            (self.markers_lock_slot, window.appearance_locks[AppearancePage.MARKERS]),
            (self.marker_controls_slot, window.marker_controls),
            (self.background_slot, window.background_controls),
        ):
            layout.addWidget(control)
            control.show()
        self.form_buttons.rejected.connect(self.reject)

    def _ready(self) -> bool:
        entry = self.workspace._entry()
        return (entry is not None and entry.visible and entry.frame is not None
                and self.workspace.controls.isEnabled() and self.workspace.matrix_box.isEnabled()
                and not self.workspace._preparing and not self.workspace._rebuild.isActive())

    def _grid(self, derivative: bool, enabled: bool) -> None:
        """Change the chosen plot's grid without preparing derivative samples."""
        profile = self.workspace.overlay_profile if self.workspace._profile_uses_overlay else self.workspace.profile_view
        pane = profile.derivative_pane if derivative else profile.signal_pane
        pane.plot_item.showGrid(x=enabled, y=enabled, alpha=.2)

    def refresh(self, _index: int = -1) -> None:
        """Synchronize availability/scope without changing data or plot tabs.

        Args:
            _index: Optional Qt tab-change index; current workspace state is
                authoritative, so this signal argument is deliberately unused.
        """
        window = self.workspace
        signal_tab = window._layout_mode == ViewMode.SIGNAL and window.tabs.currentIndex() in (0, 1)
        window.profile_fit_button.setVisible(signal_tab)
        window.profile_y_lock_button.setVisible(signal_tab)
        spatial_tab = window._layout_mode in (None, ViewMode.MATRIX, ViewMode.POINTS) and window.tabs.currentIndex() in (0, 1)
        window.spatial_fit_button.setVisible(spatial_tab)
        if spatial_tab:
            view = FigureView.SURFACE if window.tabs.currentIndex() == 1 else FigureView.IMAGE
            window.spatial_fit_button.setEnabled(window.scaling.available(view))
        window.extrema_button.setVisible(window.tabs.currentWidget() is not window.raw_view)
        if hasattr(window, "view_extrema"):
            window.view_extrema.sync_buttons()
        window.tab_actions_separator.setVisible(window.tabs.currentWidget() is not window.raw_view)
        window.color_lock_button.setVisible(spatial_tab)
        entry = window._entry()
        ready = self._ready()
        mode = entry.selection.mode if entry is not None else None
        matrix = mode == ViewMode.MATRIX
        spatial = mode in (ViewMode.MATRIX, ViewMode.POINTS)
        window.color_lock_button.setEnabled(ready and spatial)
        overlay = window._overlay()
        for view, button in self.scaling_buttons.items():
            button.setEnabled(window.scaling.available(view))
        self.source.setText(f"Editing: {window._channel_label(entry)}" if entry else "No matrix selected")
        self.profile_stack.setCurrentIndex(int(window._profile_uses_overlay))
        self.profile_scope.setVisible(window.multiple_matrix_mode.isChecked())
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        for checkbox, pane in ((self.signal_grid, profile.signal_pane), (self.derivative_grid, profile.derivative_pane)):
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(bool(pane.plot_item.getAxis("bottom").grid))
        with QtCore.QSignalBlocker(self.auto_y):
            self.auto_y.setChecked(window._profile_auto_y)
        for control in (self.y_lock, window.profile_y_lock_button, window.profile_view.y_lock_button,
                        window.overlay_profile.y_lock_button):
            with QtCore.QSignalBlocker(control):
                control.setChecked(window.scaling.y_range_lock)
            control.setEnabled(ready and mode != ViewMode.POINTS)
        self.auto_y.setEnabled(not window.scaling.y_range_lock)
        with QtCore.QSignalBlocker(self.z_lock):
            self.z_lock.setChecked(window.surface_view.z_range_lock)
        self.auto_y.setVisible(matrix)
        for page in AppearancePage:
            available = (mode != ViewMode.POINTS if page == AppearancePage.SIGNAL else
                         matrix if page == AppearancePage.IMAGE else
                         spatial if page == AppearancePage.SURFACE else
                         True)
            self.tabs.setTabEnabled(page, ready and available)
        # Scalar coloring is shared by 2D and 3D. Image composites keep their
        # original colors; overlay color/opacity belong to the active entry.
        window.display_box.setVisible(spatial and not overlay)
        window.display_box.setEnabled(ready and entry is not None and entry.frame is not None
                                      and not entry.frame.composite)
        window.overlay_appearance.setVisible(overlay)
        window.overlay_appearance.setEnabled(ready)
        window.layer_opacity.setEnabled(spatial)
        window.image_controls.setVisible(matrix)
        window.surface_controls.setVisible(spatial)
        window.slice_appearance.setVisible(matrix)
        window.image_form.setRowVisible(window.profile_color_2d_button, matrix)
        window.background_controls.setEnabled(ready)
        if hasattr(window, "view_settings_button"):
            window.view_settings_button.setEnabled(ready and window.tabs.currentWidget() is not window.raw_view)
            window.view_settings_button.setToolTip("Styles, colors and markers for the selected visible matrix/channel. Raw data has its own table controls.")
        for profile in (window.profile_view, window.overlay_profile):
            profile.settings_button.setEnabled(ready and mode != ViewMode.POINTS)

    def show_for(self, view: FigureView) -> None:
        """Open on a view's appearance page without changing the visible plot.

        Args:
            view: Requested 1D, derivative, 2D or 3D appearance page.
        """
        self.refresh()
        if not self._ready():
            return
        page = (AppearancePage.IMAGE if view == FigureView.IMAGE else
                AppearancePage.SURFACE if view == FigureView.SURFACE else AppearancePage.SIGNAL)
        if self.tabs.isTabEnabled(page):
            self.tabs.setCurrentIndex(page)
        self.exec()

    def show_current(self) -> None:
        """Open from the main tab bar, using the currently displayed view."""
        window = self.workspace
        if window._layout_mode in (ViewMode.SIGNAL, ViewMode.XY):
            view = FigureView.DERIVATIVE if window.tabs.currentIndex() == 1 else FigureView.SIGNAL
        else:
            view = FigureView.SURFACE if window.tabs.currentIndex() == 1 else FigureView.IMAGE
        self.show_for(view)

    def show_profile(self) -> None:
        """Open 1D appearance from a signal or slice's compact toolbar."""
        self.show_for(FigureView.SIGNAL)
