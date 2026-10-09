"""Native context menus for workspace matrices and linked plot canvases.

Requirements: PySide6 and the existing viewer modules. Usage: WorkspaceMenus
attaches to WorkspaceWindow. Actions reuse its normal controls and validation;
opening a menu does not calculate derivatives or change channel visibility.
"""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from .data_model import ViewMode
from .exporting import ExportTarget
from .figure_export import FigureView
from .plot_support import pyside_graphics_view
from .workspace import MatrixEntry

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow


class CanvasContextMenu(QtCore.QObject):
    """Distinguish a right click from a drag without replacing camera gestures.

    Args:
        canvas: Native widget receiving the plot's mouse events.

    Signals:
        requested: Global menu position after a click or keyboard request.

    Small right-button movements are withheld until Qt's drag threshold is
    reached. Native mouse context events are consumed to avoid duplicate menus
    on platforms that generate them on press rather than release.
    """

    requested = QtCore.Signal(QtCore.QPoint)

    def __init__(self, canvas: QtWidgets.QWidget) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self._origin: QtCore.QPointF | None = None
        self._dragged = False
        canvas.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Track right-button gestures, passing other camera/plot events through.

        Args:
            watched: Canvas on which this filter was installed.
            event: Native Qt event; mouse and keyboard menu requests are handled.

        Returns:
            True for consumed context events or sub-threshold right drags.
        """
        if isinstance(event, QtGui.QContextMenuEvent):
            if event.reason() == QtGui.QContextMenuEvent.Reason.Keyboard:
                self.requested.emit(self.canvas.mapToGlobal(self.canvas.rect().center()))
            event.accept()
            return True
        if isinstance(event, QtGui.QMouseEvent):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.RightButton:
                self._origin = event.position()
                self._dragged = False
            elif event.type() == QtCore.QEvent.Type.MouseMove and self._origin is not None:
                self._dragged |= (event.position() - self._origin).manhattanLength() >= QtWidgets.QApplication.startDragDistance()
                if not self._dragged:
                    return True
            elif event.type() == QtCore.QEvent.Type.MouseButtonRelease and event.button() == QtCore.Qt.MouseButton.RightButton:
                clicked = self._origin is not None and not self._dragged
                if self._origin is not None:
                    clicked &= (event.position() - self._origin).manhattanLength() < QtWidgets.QApplication.startDragDistance()
                self._origin = None
                if clicked:
                    self.requested.emit(event.globalPosition().toPoint())
        if event.type() in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.WindowDeactivate):
            self._origin = None
        return False


class WorkspaceMenus(QtCore.QObject):
    """Build context-appropriate actions without duplicating data operations.

    Args:
        window: Fully constructed workspace with its standard controls/actions.

    Side effects:
        Installs tree and canvas event handlers and owns their popup menus.
    """

    def __init__(self, window: "WorkspaceWindow") -> None:
        super().__init__(window)
        self.window = window
        self.menu: QtWidgets.QMenu | None = None
        self.filters: list[CanvasContextMenu] = []
        window.matrix_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        window.matrix_list.customContextMenuRequested.connect(self._tree_requested)
        self._attach(pyside_graphics_view(window.image_view.graphics).viewport(), FigureView.IMAGE)
        self._attach(window.surface_view.canvas, FigureView.SURFACE)
        for profile in (window.profile_view, window.overlay_profile):
            self._attach(profile.signal_pane.native_view.viewport(), FigureView.SIGNAL)
            self._attach(profile.derivative_pane.native_view.viewport(), FigureView.DERIVATIVE)

    def _attach(self, canvas: object, view: FigureView) -> None:
        # Third-party Qt stubs may select PyQt even though runtime is PySide6.
        if not isinstance(canvas, QtWidgets.QWidget):
            raise TypeError("Plot context menus require a PySide6 widget.")
        handler = CanvasContextMenu(canvas)
        handler.requested.connect(partial(self._view_requested, view))
        self.filters.append(handler)

    @staticmethod
    def _add(menu: QtWidgets.QMenu, text: str, callback: Callable[[], object], *,
             enabled: bool = True, checked: bool | None = None) -> QtGui.QAction:
        action = menu.addAction(text)
        action.setEnabled(enabled)
        if checked is not None:
            action.setCheckable(True)
            action.setChecked(checked)
        action.triggered.connect(lambda _checked=False: callback())
        return action

    def _popup(self, menu: QtWidgets.QMenu, position: QtCore.QPoint) -> None:
        if self.menu is not None:
            self.menu.close()
            self.menu.deleteLater()
        self.menu = menu
        menu.popup(position)

    def _tree_requested(self, point: QtCore.QPoint) -> None:
        tree = self.window.matrix_list
        if not tree.isEnabled():
            return
        item = tree.itemAt(point)
        entry = self.window._tree_entry(item) if item is not None else None
        if item is not None and entry is None:
            members = self.window._groups().get(int(item.data(0, QtCore.Qt.ItemDataRole.UserRole)), [])
            entry = next((member for member in members if member.uid == self.window.active_uid), None)
            entry = entry or next((member for member in members if member.visible), None) or (members[0] if members else None)
        if entry is not None and entry.uid != self.window.active_uid:
            self.window._activate(entry)
        self._popup(self.matrix_menu(entry), tree.viewport().mapToGlobal(point))

    def _view_requested(self, view: FigureView, point: QtCore.QPoint) -> None:
        self._popup(self.view_menu(view), point)

    def _processing(self, menu: QtWidgets.QMenu) -> None:
        window = self.window
        entry = window._entry()
        title = f"Process active matrix — {window._channel_label(entry)}" if entry else "Process active matrix"
        processing = menu.addMenu(title[:100])
        processing.setEnabled(entry is not None and window.matrix_box.isEnabled())
        processing.addActions([window.conversion_action, window.fourier_action, window.laplace_action])
        processing.addSeparator()
        processing.addAction(window.merge_action)

    def _export(self, target: ExportTarget, *, channel: bool = False) -> None:
        self.window._open_export_dialog(target, channel=channel)

    def _export_settings(self) -> None:
        self.window._open_export_dialog()

    def _hide_matrix(self, entry: MatrixEntry) -> None:
        for member in self.window._groups().get(entry.matrix_uid or entry.uid, []):
            member.visible = False
        self.window._refresh_list()
        self.window._render_workspace()

    def _file_actions(self, menu: QtWidgets.QMenu) -> None:
        menu.addActions([self.window.open_file_action, self.window.add_file_action])

    def matrix_menu(self, entry: MatrixEntry | None) -> QtWidgets.QMenu:
        """Create a menu for the active tree target, or for empty list space.

        Args:
            entry: Already activated channel, or None for an empty tree area.

        Returns:
            A window-owned menu; the caller retains it while displayed.
        """
        window = self.window
        menu = QtWidgets.QMenu(window)
        multiple = window.multiple_matrix_mode.isChecked()
        if entry is not None:
            menu.addSection(window._channel_label(entry)[:100])
            self._add(menu, "Show only this channel", partial(window._show_only, entry))
            if multiple:
                self._add(menu, "Hide channel" if entry.visible else "Show channel",
                          partial(window._set_entry_visible, entry, not entry.visible))
            if multiple and len(window._groups().get(entry.matrix_uid or entry.uid, [])) > 1:
                self._add(menu, "Hide whole matrix", partial(self._hide_matrix, entry))
            self._add(menu, "Set as alignment reference", lambda: window.reference.setCurrentIndex(window.reference.findData(entry.uid)),
                      enabled=window.multiple_matrix_mode.isChecked())
            self._add(menu, "Channel color…", partial(window._choose_entry_color, entry.uid))
            self._add(menu, "Rename matrix…", window._rename_selected)
            menu.addSeparator()
            self._processing(menu)
            ready = entry.frame is not None and window._export_ready and not window._rebuild.isActive() and not window._export_busy
            self._add(menu, "Export matrix…", partial(self._export, ExportTarget.RESULT), enabled=ready)
            if window._has_export_channels():
                self._add(menu, "Export channel…", partial(self._export, ExportTarget.RESULT, channel=True), enabled=ready)
            self._add(menu, "Export original matrix…", partial(self._export, ExportTarget.ORIGINAL), enabled=ready)
            self._add(menu, "Export settings…", self._export_settings, enabled=ready)
            self._add(menu, "Copy source path", lambda: QtWidgets.QApplication.clipboard().setText(str(entry.document.path)))
            menu.addSeparator()
            self._add(menu, "Remove matrix", window._remove_selected)
            menu.addSeparator()
        self._file_actions(menu)
        self._add(menu, "Fit all views", window._fit_views, enabled=any(member.visible for member in window.entries))
        if multiple:
            self._add(menu, "Hide all", window._hide_all, enabled=bool(window.entries))
        self._add(menu, "Remove all", window._remove_all, enabled=bool(window.entries))
        return menu

    def _combo_menu(self, menu: QtWidgets.QMenu, title: str, combo: QtWidgets.QComboBox, enabled: bool = True) -> None:
        submenu = menu.addMenu(title)
        submenu.setEnabled(enabled and combo.isEnabled())
        group = QtGui.QActionGroup(submenu)
        for index in range(combo.count()):
            action = self._add(submenu, combo.itemText(index), partial(combo.setCurrentIndex, index), checked=index == combo.currentIndex())
            group.addAction(action)

    def _projection(self) -> None:
        canvas = self.window.surface_view.canvas
        canvas.camera.SetParallelProjection(not canvas.camera.GetParallelProjection())
        canvas.reset_camera_clipping_range()
        canvas.render()

    def view_menu(self, view: FigureView) -> QtWidgets.QMenu:
        """Offer plot-specific actions without computing hidden derivatives.

        Args:
            view: Image, surface, signal or derivative canvas requesting a menu.

        Returns:
            A window-owned menu with actions enabled for the current data state.
        """
        window = self.window
        profile = window.overlay_profile if window._profile_uses_overlay else window.profile_view
        visible = any(entry.visible and entry.frame is not None for entry in window.entries)
        ready = visible and window.matrix_box.isEnabled() and not window._preparing and not window._rebuild.isActive()
        matrix = window._layout_mode == ViewMode.MATRIX
        menu = QtWidgets.QMenu(window)
        menu.addSection(view.value)
        reset = (window.image_view.reset_view if view == FigureView.IMAGE else
                 window.surface_view.reset_view if view == FigureView.SURFACE else profile.reset_view)
        self._add(menu, "Fit this view", reset, enabled=ready)
        self._add(menu, "Fit all views", window._fit_views, enabled=ready)
        self._add(menu, "Export this view as image…", partial(window._export_figure, preferred=view), enabled=ready)
        menu.addSeparator()
        if view == FigureView.SURFACE:
            camera = menu.addMenu("Camera")
            camera.setEnabled(ready)
            canvas = window.surface_view.canvas
            for text, callback in (("Isometric", canvas.view_isometric), ("XY / top", canvas.view_xy),
                                   ("XZ / front", canvas.view_xz), ("YZ / side", canvas.view_yz)):
                self._add(camera, text, callback)
            self._add(camera, "Parallel projection", self._projection, checked=bool(canvas.camera.GetParallelProjection()))
        if view in (FigureView.IMAGE, FigureView.SURFACE):
            self._combo_menu(menu, "Color map (active matrix)", window.colormap,
                             ready and not window._overlay() and window.frame is not None and not window.frame.composite)
        else:
            self._combo_menu(menu, "Curve style", profile.style_selector, ready)
            self._add(menu, "Line color…", profile.color_button.click, enabled=ready and not window._profile_uses_overlay)
            pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
            grid = bool(pane.plot_item.getAxis("bottom").grid)
            self._add(menu, "Grid", lambda: pane.plot_item.showGrid(x=not grid, y=not grid, alpha=.2), enabled=ready, checked=grid)
        if matrix:
            if view in (FigureView.SIGNAL, FigureView.DERIVATIVE):
                self._add(menu, "Auto Y on slice change",
                          partial(window._set_profile_auto_y, not window._profile_auto_y),
                          enabled=ready, checked=window._profile_auto_y)
            self._combo_menu(menu, "Slice direction", window.profile_direction, ready)
            self._add(menu, "Clear slice selection" if window._profile_selected else "Select slice",
                      window.profile_toggle.click, enabled=ready)
            if view == FigureView.SURFACE:
                self._combo_menu(menu, "3D slice style", window.profile_style, ready)
                self._add(menu, "3D slice color…", window._choose_profile_color_3d, enabled=ready)
            elif view == FigureView.IMAGE:
                self._add(menu, "2D slice color…", window._choose_profile_color_2d, enabled=ready)
            self._add(menu, "Export slice (active matrix)…", partial(self._export, ExportTarget.SLICE, channel=True),
                      enabled=ready and window._profile_selected and window._export_ready and not window._export_busy)
        menu.addSeparator()
        active = window._entry()
        editable = active is not None and window.controls.isEnabled() and window.matrix_box.isEnabled()
        self._add(menu, "Revert crop (active matrix)", window._reset_crop, enabled=editable)
        self._add(menu, "Revert value bounds (active matrix)", window._reset_value_bounds, enabled=editable)
        self._processing(menu)
        self._add(menu, "Export settings…", self._export_settings, enabled=editable)
        return menu
