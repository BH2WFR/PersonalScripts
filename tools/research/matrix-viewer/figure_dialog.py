"""Modal figure export with an on-demand preview and lossless image formats.

Requirements: existing PySide6 and viewer rendering dependencies.
Usage: WorkspaceWindow supplies available views and a source-preparation callback.
Preview updates are debounced single-shot events, not background polling.
The shared ImagePreview provides pan/zoom without changing exported dimensions.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .figure_export import (FigureFormat, FigureOptions, FigureSource, FigureView,
                            figure_size, render_figure, save_figure)
from .ui_figure_export_dialog import Ui_FigureExportDialog

PREVIEW_WIDTH = 1000
PREVIEW_DELAY_MS = 180


class FigureExportDialog(QtWidgets.QDialog, Ui_FigureExportDialog):
    """Choose one currently displayed view, preview it, and save a figure.

    Args:
        views: Available 2D/3D/signal/derivative views, in selector order.
        initial: Initially selected view.
        prepare: UI-thread callback that activates the requested view and
            returns its live rendering source. Derivatives remain lazy.
        directory: Initial save location.
        parent: Owning workspace, blocked while this dialog is open.
    """

    def __init__(self, views: tuple[FigureView, ...], initial: FigureView,
                 prepare: Callable[[FigureView], FigureSource], directory: Path,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.prepare = prepare
        self.directory = directory
        self.source: FigureSource | None = None
        self.saved_path: Path | None = None
        self._suggested_title = ""
        for view in views:
            self.view_selector.addItem(view.value, view.value)
        self.view_selector.setCurrentIndex(views.index(initial))
        self.pixel_width.setRange(64, 12000)
        self.pixel_width.setValue(2400)
        self.pixel_width.setSuffix(" px")
        self.pixel_width.setKeyboardTracking(False)
        self.pixel_height.setRange(64, 12000)
        self.pixel_height.setSuffix(" px")
        self.pixel_height.setKeyboardTracking(False)
        self.lock_aspect.setChecked(True)
        self.dpi.setRange(36, 2400)
        self.dpi.setValue(300)
        self.dpi.setKeyboardTracking(False)
        self.legend.setChecked(True)
        self.annotation_size.setRange(6, 28)
        self.annotation_size.setValue(10)
        self.annotation_size.setSuffix(" pt")
        buttons = self.form_buttons
        self.save_button = buttons.addButton("Save figure…", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Close).setDefault(True)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._update_preview)
        self.view_selector.currentIndexChanged.connect(self._select_view)
        self.format_selector.currentIndexChanged.connect(self._format_changed)
        for control in (self.pixel_width, self.dpi, self.annotation_size):
            control.valueChanged.connect(self._schedule_preview)
        self.pixel_height.valueChanged.connect(self._height_changed)
        self.lock_aspect.toggled.connect(self._schedule_preview)
        self.title.textChanged.connect(self._schedule_preview)
        self.legend.toggled.connect(self._schedule_preview)
        self.transparent.toggled.connect(self._schedule_preview)
        QtCore.QTimer.singleShot(0, self._select_view)

    def _options(self) -> FigureOptions:
        return FigureOptions(self.pixel_width.value(), self.dpi.value(), self.transparent.isChecked(),
                             self.title.text(), self.legend.isChecked(), self.annotation_size.value(),
                             None if self.lock_aspect.isChecked() else self.pixel_height.value())

    def _height_changed(self) -> None:
        if self.lock_aspect.isChecked() and self.source is not None:
            try:
                size = figure_size(self.source, self._options())
                width = round(self.pixel_height.value() * size.width() / size.height())
                with QtCore.QSignalBlocker(self.pixel_width):
                    self.pixel_width.setValue(width)
            except ValueError:
                pass  # The preview reports invalid settings consistently.
        self._schedule_preview()

    def _select_view(self) -> None:
        self._preview_timer.stop()
        self.save_button.setEnabled(False)
        self.source = None
        self.preview.set_image(QtGui.QImage())
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            self.source = self.prepare(FigureView(self.view_selector.currentData()))
            if not self.title.text() or self.title.text() == self._suggested_title:
                self.title.setText(self.source.title)
            self._suggested_title = self.source.title
            previous = self.format_selector.currentData()
            with QtCore.QSignalBlocker(self.format_selector):
                self.format_selector.clear()
                for format_ in FigureFormat:
                    if format_ != FigureFormat.SVG or self.source.vector:
                        self.format_selector.addItem(format_.name, format_.value)
                self.format_selector.setCurrentIndex(max(0, self.format_selector.findData(previous)))
            self.legend.setEnabled(bool(self.source.legend))
            self.source_note.setText(self.source.note)
            self._format_changed()
        except (ValueError, RuntimeError, TypeError, MemoryError) as exc:
            self.status.setText(f"Cannot preview this view: {exc}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _format_changed(self) -> None:
        jpeg = self.format_selector.currentData() == FigureFormat.JPEG
        if jpeg:
            self.transparent.setChecked(False)
        self.transparent.setEnabled(not jpeg)
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        self.save_button.setEnabled(False)
        if self.source is not None:
            if self.lock_aspect.isChecked():
                try:
                    size = figure_size(self.source, self._options())
                    with QtCore.QSignalBlocker(self.pixel_height):
                        self.pixel_height.setValue(size.height())
                except ValueError:
                    pass  # Leave the entered values for the preview error.
            self.status.setText("Updating preview…")
            self._preview_timer.start()

    def _update_preview(self) -> None:
        source = self.source
        if source is None:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            options = self._options()
            size = figure_size(source, options)
            self.dimensions.setText(f"Output: {size.width():,} × {size.height():,} px\n"
                                    f"Print: {size.width() / options.dpi * 2.54:.2f} × "
                                    f"{size.height() / options.dpi * 2.54:.2f} cm at {options.dpi} DPI")
            self.preview.set_image(render_figure(source, options, preview_width=PREVIEW_WIDTH))
            self.status.setText("Drag to pan; wheel to zoom; double-click to fit. Saved dimensions follow the settings above.")
            self.save_button.setEnabled(True)
        except (ValueError, RuntimeError, TypeError, MemoryError) as exc:
            self.preview.set_image(QtGui.QImage())
            self.status.setText(f"Cannot render preview: {exc}")
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _save(self) -> None:
        source = self.source
        if source is None:
            return
        format_ = FigureFormat(self.format_selector.currentData())
        dialog = QtWidgets.QFileDialog(self, "Save figure", str(self.directory / f"{source.stem}.{format_.value}"))
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter(f"{format_.name} image (*.{format_.value})")
        dialog.setDefaultSuffix(format_.value)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        path = Path(dialog.selectedFiles()[0])
        valid_suffixes = {f".{format_.value}"}
        if format_ == FigureFormat.TIFF:
            valid_suffixes.add(".tif")
        elif format_ == FigureFormat.JPEG:
            valid_suffixes.add(".jpeg")
        if path.suffix.lower() not in valid_suffixes:
            QtWidgets.QMessageBox.warning(self, "Wrong file extension", f"Use the .{format_.value} extension for {format_.name} output.")
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            save_figure(path, format_, source, self._options())
            self.saved_path = path
            self.directory = path.parent
            self.status.setText(f"Saved: {path}")
        except (OSError, ValueError, RuntimeError, TypeError, MemoryError) as exc:
            QtWidgets.QMessageBox.critical(self, "Figure export failed", str(exc))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
