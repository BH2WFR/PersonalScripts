"""Native context menus for workspace matrices and linked plot canvases.

Requirements: PySide6 and the existing viewer modules. Usage: WorkspaceMenus
attaches to WorkspaceWindow. Actions reuse its normal controls and validation;
opening a menu does not calculate derivatives or change channel visibility.
The 3D menu offers equal XYZ data-unit scaling for all visible layers.
Image, signal and derivative menus independently toggle equal X:Y unit scaling.
The matrix's signal menu can add visible slices as independent in-memory matrices.
The tree menu also packages every source matrix, checked or hidden, in one archive.
2D/3D Appearance menus reuse active-channel rendering, diameter, colormap,
overlay color/opacity and clipping-color controls. Hidden editing targets are
disabled here to avoid changing an unseen matrix from a displayed plot. Plot
background remains global. Numeric menu editors ignore the wheel and synchronize
with their original controls; signal/derivative menus share the 1D point size.
Every canvas also opens the centralized View settings dialog on its own page.
Quick style/color actions consistently live in Appearance submenus.
Plot menus group view, appearance, slice, processing and export commands in a
fixed order. Tree menus group file, selection/display, data and close actions.
Raw menus offer selection/navigation/table controls without activating a matrix.
Menu captions omit source names; full matrix identity stays in tooltips/UI headers.
"""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from .data_model import ViewMode
from .bundle_export import BUNDLE_FORMATS
from .exporting import ExportTarget
from .figure_export import FigureView
from .plot_support import pyside_graphics_view
from .qt_widgets import NoWheelDoubleSpinBox, NoWheelSpinBox
from .raw_view import DEFAULT_COLUMN_WIDTH
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
        window.raw_view.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        window.raw_view.table.customContextMenuRequested.connect(self._raw_requested)

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

    def _raw_requested(self, point: QtCore.QPoint) -> None:
        self._popup(self.raw_menu(), self.window.raw_view.table.viewport().mapToGlobal(point))

    def _processing(self, menu: QtWidgets.QMenu) -> None:
        window = self.window
        entry = window._entry()
        processing = menu.addMenu("Process active matrix")
        processing.menuAction().setToolTip(window._channel_label(entry) if entry else "No active matrix")
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
        menu.addActions([self.window.add_file_action, self.window.open_file_action])

    def _data_exports(self, menu: QtWidgets.QMenu) -> None:
        """Add numeric exports for the active entry, retaining scope choices."""
        window = self.window
        entry = window._entry()
        ready = (entry is not None and entry.frame is not None and window._export_ready
                 and window.matrix_box.isEnabled() and not window._rebuild.isActive()
                 and not window._export_busy)
        menu.addSection("Active matrix")
        self._add(menu, "Matrix…", partial(self._export, ExportTarget.RESULT), enabled=ready)
        if window._has_export_channels():
            self._add(menu, "Current channel…", partial(self._export, ExportTarget.RESULT, channel=True), enabled=ready)
        if entry is not None and entry.selection.mode == ViewMode.MATRIX:
            self._add(menu, "Current slice…", partial(self._export, ExportTarget.SLICE, channel=True),
                      enabled=ready and window._profile_selected)
        self._add(menu, "Original matrix…", partial(self._export, ExportTarget.ORIGINAL), enabled=ready)
        self._add(menu, "Export options…", self._export_settings, enabled=ready).setToolTip(
            "Choose a single matrix/channel or all visible matrices, plus crop, layout and file format."
        )

    def _bundle_exports(self, menu: QtWidgets.QMenu) -> None:
        """Reuse the existing archive writer for checked and hidden matrices."""
        window = self.window
        menu.addSection("Session")
        bundle = menu.addMenu("All matrices as…")
        bundle.setEnabled(bool(window.entries) and window.matrix_box.isEnabled() and not window._export_busy)
        bundle.setToolTipsVisible(True)
        for format_ in BUNDLE_FORMATS:
            action = self._add(bundle, f"{format_.value.upper()}…", partial(window._save_all_matrices, format_))
            action.setToolTip("All source matrices, including hidden ones, without crop or value bounds. Images split native channels; NPZ/MAT preserve complex arrays, XLSX splits real/imaginary sheets. View settings are not saved.")

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
        menu.addSection("File")
        self._file_actions(menu)
        if entry is not None:
            menu.addSection("Selected matrix")
            self._add(menu, "Rename…", window._rename_selected)
            self._add(menu, "Copy source path", lambda: QtWidgets.QApplication.clipboard().setText(str(entry.document.path)))
            display = menu.addMenu("Display")
            self._add(display, "Show only this channel", partial(window._show_only, entry))
            if multiple:
                self._add(display, "Hide channel" if entry.visible else "Show channel",
                          partial(window._set_entry_visible, entry, not entry.visible))
            if multiple and len(window._groups().get(entry.matrix_uid or entry.uid, [])) > 1:
                self._add(display, "Hide whole matrix", partial(self._hide_matrix, entry))
            display.addSeparator()
            self._add(display, "Channel color…", partial(window._choose_entry_color, entry.uid))
            self._add(display, "Set as alignment reference", lambda: window.reference.setCurrentIndex(window.reference.findData(entry.uid)),
                      enabled=multiple)
            display.addSeparator()
            self._add(display, "Fit all views", window._fit_views, enabled=any(member.visible for member in window.entries))
            if multiple:
                self._add(display, "Hide all", window._hide_all, enabled=bool(window.entries))
            menu.addSection("Data")
            self._processing(menu)
        export = menu.addMenu("Export")
        if entry is not None:
            self._data_exports(export)
        self._bundle_exports(export)
        menu.addSeparator()
        if entry is not None:
            menu.addAction(window.remove_action)
        menu.addAction(window.remove_all)
        return menu

    def _combo_menu(self, menu: QtWidgets.QMenu, title: str, combo: QtWidgets.QComboBox, enabled: bool = True) -> None:
        submenu = menu.addMenu(title)
        submenu.setEnabled(enabled and combo.isEnabled())
        group = QtGui.QActionGroup(submenu)
        for index in range(combo.count()):
            action = self._add(submenu, combo.itemText(index), partial(combo.setCurrentIndex, index), checked=index == combo.currentIndex())
            group.addAction(action)

    @staticmethod
    def _number_editor(field: QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox) -> QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox:
        """Mirror a live numeric field without moving it or accepting the wheel."""
        editor: QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox
        if isinstance(field, QtWidgets.QDoubleSpinBox):
            editor = NoWheelDoubleSpinBox()
            editor.setDecimals(field.decimals())
            editor.setRange(field.minimum(), field.maximum())
            editor.setSingleStep(field.singleStep())
            editor.setValue(field.value())
            editor.valueChanged.connect(field.setValue)
            field.valueChanged.connect(editor.setValue)
        else:
            editor = NoWheelSpinBox()
            editor.setRange(field.minimum(), field.maximum())
            editor.setSingleStep(field.singleStep())
            editor.setValue(field.value())
            editor.valueChanged.connect(field.setValue)
            field.valueChanged.connect(editor.setValue)
        editor.setPrefix(field.prefix())
        editor.setSuffix(field.suffix())
        editor.setKeyboardTracking(False)
        editor.setToolTip(field.toolTip())
        return editor

    def _number_menu(self, menu: QtWidgets.QMenu, title: str, field: QtWidgets.QSpinBox | QtWidgets.QDoubleSpinBox,
                     enabled: bool = True) -> None:
        """Expose a numeric field with validation/drawing in its existing slots."""
        submenu = menu.addMenu(title)
        submenu.setEnabled(enabled and field.isEnabled())
        action = QtWidgets.QWidgetAction(submenu)
        editor = self._number_editor(field)
        editor.setToolTip(field.toolTip() or title)
        action.setDefaultWidget(editor)
        submenu.addAction(action)

    def raw_menu(self) -> QtWidgets.QMenu:
        """Build table actions for the currently browsed raw matrix.

        Returns:
            A window-owned menu. Navigation/formatting reuse RawDataView and do
            not activate its matrix or change plot selection.
        """
        raw = self.window.raw_view
        ready = raw.model.rowCount() > 0 and raw.model.columnCount() > 0
        selection = raw.table.selectionModel()
        selected = selection is not None and selection.hasSelection()
        menu = QtWidgets.QMenu(self.window)
        menu.addSection("Selection")
        menu.addAction(raw.copy_action)
        self._add(menu, "Select all", raw.table.selectAll, enabled=ready)
        self._add(menu, "Clear selection", raw.table.clearSelection, enabled=selected)

        menu.addSection("Navigation")
        navigation = menu.addMenu("Go to cell…")
        navigation.setEnabled(ready)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(content)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        for label, field in (("Row", raw.row), ("Column", raw.column)):
            editor = self._number_editor(field)
            editor.setAccessibleName(label)
            layout.addRow(label, editor)
        go = QtWidgets.QPushButton("Go to cell")
        go.clicked.connect(raw._go_to)
        go.clicked.connect(menu.close)
        layout.addRow(go)
        action = QtWidgets.QWidgetAction(navigation)
        action.setDefaultWidget(content)
        navigation.addAction(action)

        menu.addSection("Table")
        self._number_menu(menu, "Column width", raw.column_width)
        self._add(menu, "Reset column width", partial(raw.column_width.setValue, DEFAULT_COLUMN_WIDTH))
        if not raw.hex_checkbox.isHidden():
            self._add(menu, "Hexadecimal", raw.hex_checkbox.toggle,
                      enabled=raw.hex_checkbox.isEnabled(), checked=raw.hex_checkbox.isChecked())
        return menu

    def _matrix_appearance(self, menu: QtWidgets.QMenu, view: FigureView, ready: bool) -> QtWidgets.QMenu:
        """Offer applicable 2D/3D appearance settings for the visible active entry."""
        window = self.window
        active = window._entry()
        editable = (ready and active is not None and active.visible and active.frame is not None
                    and window.controls.isEnabled())
        appearance = menu.addMenu("Appearance")
        appearance.setEnabled(editable)
        appearance.setToolTipsVisible(True)
        appearance.menuAction().setToolTip("Select a visible matrix/channel to edit its appearance. Background applies to all plots.")
        is_image = view == FigureView.IMAGE
        self._combo_menu(appearance, "Rendering style", window.image_style if is_image else window.surface_style)
        self._number_menu(appearance, "Point size", window.image_point_size if is_image else window.point_size)
        overlay = window._overlay()
        scalar = active is not None and active.frame is not None and not active.frame.composite
        self._combo_menu(appearance, "Color map", window.colormap, not overlay and scalar)
        color = self._add(appearance, "Solid color…", window._choose_layer_color, enabled=overlay)
        color.setToolTip("Per-channel solid color used for overlaid matrices.")
        self._number_menu(appearance, "Opacity", window.layer_opacity, overlay)
        appearance.addSeparator()
        self._combo_menu(appearance, "Plot background (all views)", window.theme)
        return appearance

    def _projection(self) -> None:
        self.window.parallel.toggle()

    def _equal_xy(self, view: FigureView, enabled: bool) -> None:
        """Apply the viewport's aspect choice in single and overlay modes."""
        window = self.window
        if view == FigureView.IMAGE:
            window.image_view.set_equal_xy(enabled)
            return
        for profile in (window.profile_view, window.overlay_profile):
            pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
            pane.view_box.setAspectLocked(enabled, ratio=1.0)

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
        menu.addSection("View")
        pane = profile.derivative_pane if view == FigureView.DERIVATIVE else profile.signal_pane
        reset = (window.image_view.reset_view if view == FigureView.IMAGE else
                 window.surface_view.reset_view if view == FigureView.SURFACE else pane.view_box.enableAutoRange)
        self._add(menu, "Fit this view", reset, enabled=ready)
        self._add(menu, "Fit all views", window._fit_views, enabled=ready)
        active = window._entry()
        appearance_ready = (ready and active is not None and active.visible and active.frame is not None
                            and window.controls.isEnabled())
        scale = menu.addMenu("Scale / camera" if view == FigureView.SURFACE else "Axis scale")
        scale.setEnabled(ready)
        if view != FigureView.SURFACE:
            box = window.image_view.view_box if view == FigureView.IMAGE else pane.view_box
            locked = box.state["aspectLocked"] is not False
            equal_xy = self._add(scale, "X:Y scale 1:1 (data units)", partial(self._equal_xy, view, not locked),
                                 enabled=ready, checked=locked)
            equal_xy.setToolTip("Equal lengths for one X unit and one Y unit. Zoom links both axes while locked; uncheck for free scaling.")
        if view == FigureView.SURFACE:
            equal_scale = self._add(scale, "XYZ scale 1:1:1 (data units)", window._equal_xyz_scale, enabled=ready)
            equal_scale.setToolTip(
                "Apply to all visible layers: disable Auto height scale, set Height multiplier to 1, "
                "and reset stretched XYZ alignments to original coordinates. Translation alignments remain. "
                "One data unit has the same length on every axis; pixel coordinates are not calibrated distances."
            )
            scale.addSeparator()
            canvas = window.surface_view.canvas
            for text, callback in (("Isometric", canvas.view_isometric), ("XY / top", canvas.view_xy),
                                   ("XZ / front", canvas.view_xz), ("YZ / side", canvas.view_yz)):
                self._add(scale, text, callback)
            scale.addSeparator()
            self._add(scale, "Parallel projection", self._projection, checked=bool(canvas.camera.GetParallelProjection()))

        # Appearance edits the active channel; navigation applies to the view.
        if view in (FigureView.IMAGE, FigureView.SURFACE):
            appearance = self._matrix_appearance(menu, view, ready)
        else:
            appearance = menu.addMenu("Appearance")
            appearance.setEnabled(appearance_ready)
            appearance.menuAction().setToolTip("Appearance of the active matrix/channel; background applies to all plots.")
            self._combo_menu(appearance, "Rendering style", profile.style_selector)
            self._number_menu(appearance, "Point size", profile.point_size)
            if window._profile_uses_overlay:
                self._add(appearance, "Solid color…", window._choose_layer_color)
            else:
                self._add(appearance, "Line color…", profile.color_button.click, enabled=profile.color_button.isEnabled())
            grid = bool(pane.plot_item.getAxis("bottom").grid)
            self._add(appearance, "Grid", lambda: pane.plot_item.showGrid(x=not grid, y=not grid, alpha=.2), checked=grid)
            self._combo_menu(appearance, "Plot background (all views)", window.theme)

        if view != FigureView.DERIVATIVE:
            markers = appearance.addMenu("Value markers")
            if view in (FigureView.IMAGE, FigureView.SIGNAL):
                self._add(markers, "Show Inf / -Inf / NaN", window.show_nonfinite.toggle,
                          checked=window.show_nonfinite.isChecked())
            self._add(markers, "Highlight clipped values", window.highlight_clipped.toggle,
                      enabled=window.highlight_clipped.isEnabled(), checked=window.highlight_clipped.isChecked())
            self._add(markers, "Clipping color…", window.clip_color_button.click,
                      enabled=window.clip_color_button.isEnabled())
        appearance.addSeparator()
        self._add(appearance, "View settings…", partial(window.view_settings.show_for, view), enabled=appearance_ready)

        # A source slice is distinct from its derivative's rendered curve.
        if matrix:
            slice_menu = menu.addMenu("Slice")
            slice_menu.setEnabled(ready)
            self._combo_menu(slice_menu, "Direction", window.profile_direction)
            self._add(slice_menu, "Clear selection" if window._profile_selected else "Select slice", window.profile_toggle.click)
            slice_menu.addSeparator()
            if view == FigureView.SURFACE:
                self._combo_menu(slice_menu, "3D slice style", window.profile_style)
                self._add(slice_menu, "3D slice color…", window._choose_profile_color_3d)
            elif view == FigureView.IMAGE:
                self._add(slice_menu, "2D slice color…", window._choose_profile_color_2d)
            else:
                self._add(slice_menu, "Auto Y on slice change",
                          partial(window._set_profile_auto_y, not window._profile_auto_y), checked=window._profile_auto_y)
            if view == FigureView.SIGNAL:
                slice_menu.addSeparator()
                freeze = self._add(slice_menu, "Add visible slices to matrices", window._add_slice_matrices,
                                   enabled=window._can_add_slices())
                freeze.setToolTip("Copy current slices into independent 1D matrices. Complex sources ask for the current channel or both complex parts (without value bounds). Added unchecked; no file is saved.")

        menu.addSection("Data")
        self._processing(menu)
        editable = active is not None and window.controls.isEnabled() and window.matrix_box.isEnabled()
        limits = menu.addMenu("Reset data limits")
        limits.setEnabled(editable)
        limits.menuAction().setToolTip("Reset limits for the active matrix/channel.")
        self._add(limits, "Index crop", window._reset_crop)
        self._add(limits, "Value bounds", window._reset_value_bounds,
                  enabled=editable and window.revert_value_bounds.isEnabled())

        export = menu.addMenu("Export")
        export.addSection("Rendered view")
        self._add(export, "This view as image…", partial(window._export_figure, preferred=view), enabled=ready)
        self._data_exports(export)
        return menu
