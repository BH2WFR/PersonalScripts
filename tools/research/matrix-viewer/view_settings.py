"""Central appearance dialog shared by plot buttons and context menus.

Requirements: PySide6 and the existing viewer modules. Usage: WorkspaceWindow
owns one persistent dialog. It hosts the original setting widgets, preserving
their signals and per-channel storage without a second copy of settings.
The sidebar retains data interpretation, cropping, sampling and alignment.
Changes apply immediately; Close retains them. Opening a page never selects a
plot tab or calculates derivatives. Background, slice markers and axes options
are shared; channel colors and point sizes target the visible active entry.
"""

from enum import IntEnum
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

from .data_model import ViewMode
from .figure_export import FigureView

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow


class AppearancePage(IntEnum):
    """Stable pages for dimension-specific and shared appearance settings."""

    SIGNAL = 0
    IMAGE = 1
    SURFACE = 2
    COLORS = 3
    MARKERS = 4


class ViewSettingsDialog(QtWidgets.QDialog):
    """Edit appearance with a single discoverable entry beside each viewer.

    Args:
        window: Constructed workspace whose existing controls are reparented
            into this dialog. The dialog lives for the workspace's lifetime.
    """

    def __init__(self, window: "WorkspaceWindow") -> None:
        super().__init__(window)
        self.workspace = window
        self.setWindowTitle("View settings")
        self.setModal(True)
        self.resize(570, 570)
        self.setMinimumSize(460, 420)
        layout = QtWidgets.QVBoxLayout(self)
        self.source = QtWidgets.QLabel()
        self.source.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        layout.addWidget(self.source)
        note = QtWidgets.QLabel("Changes apply immediately. Background, slice markers and axes options are shared across matrices.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.profile_stack = QtWidgets.QStackedWidget()
        self.profile_stack.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        for profile in (window.profile_view, window.overlay_profile):
            self.profile_stack.addWidget(profile.appearance_controls)
        axes = QtWidgets.QGroupBox("Axes")
        axes_layout = QtWidgets.QVBoxLayout(axes)
        self.signal_grid = QtWidgets.QCheckBox("Signal grid")
        self.derivative_grid = QtWidgets.QCheckBox("Derivative grid")
        self.signal_grid.toggled.connect(lambda enabled: self._grid(False, enabled))
        self.derivative_grid.toggled.connect(lambda enabled: self._grid(True, enabled))
        self.auto_y = QtWidgets.QCheckBox("Auto Y on slice change")
        self.auto_y.toggled.connect(window._set_profile_auto_y)
        for checkbox in (self.signal_grid, self.derivative_grid, self.auto_y):
            axes_layout.addWidget(checkbox)
        self._page("1D", self.profile_stack, axes)
        self._page("2D", window.image_controls)
        self._page("3D", window.surface_controls, window.slice_appearance)
        self._page("Colors", window.display_box, window.overlay_appearance)
        self._page("Markers", window.marker_controls)
        layout.addWidget(window.background_controls)
        window.background_controls.show()
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _page(self, title: str, *widgets: QtWidgets.QWidget) -> None:
        """Host a scrollable page so high-DPI/small screens retain every field."""
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        for widget in widgets:
            layout.addWidget(widget)
            widget.show()
        layout.addStretch()
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)

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
        entry = window._entry()
        ready = self._ready()
        mode = entry.selection.mode if entry is not None else None
        matrix = mode == ViewMode.MATRIX
        spatial = mode in (ViewMode.MATRIX, ViewMode.POINTS)
        overlay = window._overlay()
        self.source.setText(f"Editing: {window._channel_label(entry)}" if entry else "No matrix selected")
        self.profile_stack.setCurrentIndex(int(window._profile_uses_overlay))
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        for checkbox, pane in ((self.signal_grid, profile.signal_pane), (self.derivative_grid, profile.derivative_pane)):
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(bool(pane.plot_item.getAxis("bottom").grid))
        with QtCore.QSignalBlocker(self.auto_y):
            self.auto_y.setChecked(window._profile_auto_y)
        self.auto_y.setVisible(matrix)
        for page in AppearancePage:
            available = (mode != ViewMode.POINTS if page == AppearancePage.SIGNAL else
                         matrix if page == AppearancePage.IMAGE else
                         spatial if page == AppearancePage.SURFACE else
                         spatial or overlay if page == AppearancePage.COLORS else True)
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
