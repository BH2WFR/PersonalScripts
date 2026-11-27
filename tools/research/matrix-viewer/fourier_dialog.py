"""Modal, on-demand Fourier settings; changing controls never computes an FFT.

Requirements: numpy and PySide6. Usage: constructed by WorkspaceWindow.
The owner runs immutable requests on its worker pool and completes the dialog.
Input scopes distinguish full/cropped matrices or signals and full/cropped 1D
slices. Crop scopes automatically include the active value bounds; full scopes
ignore both spatial and value bounds. Full complex and phase inputs ignore Z
bounds in every scope and zero-fill invalid samples. Real channels offer
independent zero/valid-extremum treatments for NaN, +/-Inf and finite outliers,
with clamp-to-boundary as the outlier default, independently of display Hide.
No samples are removed from the input grid; statistics run only on Generate.
Real sources offer FFT only. IFFT locks full complex input and excludes cropped
frequency scopes; switching from FFT cannot retain a display-component input.
"""

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .coordinates import AxisCoordinates
from .data_model import Crop, Document, ImageMember, Limits, Selection, ViewMode, is_phase_view
from .fourier import (TransformDirection, TransformNorm, TransformOptions,
                      TransformRange, TransformWindow)
from .fourier_values import FourierValuePolicy, ValueReplacement
from .ui_fourier_dialog import Ui_FourierDialog


class FourierDialog(QtWidgets.QDialog, Ui_FourierDialog):
    """Collect transform settings for one stable source interpretation.

    Args:
        document: Source whose data/metadata stay alive during the operation.
        selection: Selected source axes and complex component.
        crop: Current applied crop, with inclusive ends.
        source_name: Session alias shown as input identity.
        row: Current profile direction.
        index: Source row/column index; None disables slice input.
        parent: Owning viewer window.
        limits: Current value bounds, automatically applied by cropped scopes.
            Defaults to no value bounds. Full scopes always ignore them.

    Side effects:
        Emits generate_requested with immutable options and a result alias.
        No numerical transform runs until the user presses Generate.
    """

    generate_requested = QtCore.Signal(object, str)

    def __init__(self, document: Document, selection: Selection, crop: Crop, source_name: str,
                 row: bool, index: int | None, parent: QtWidgets.QWidget | None = None,
                 *, limits: Limits = Limits()) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.document, self.selection, self.crop = document, selection, crop
        self.limits = limits
        self._apply_bounds = False
        self.row, self.index = row, index
        self._busy = False
        self._shape: tuple[int, ...] = ()
        self._source_axes: tuple[int, ...] = ()
        self.setModal(True)
        source = self.form_source
        source.setText(f"Source: {source_name}\n{document.array.shape} · {document.array.dtype}")
        form = self.form_form
        for value in TransformDirection:
            if value == TransformDirection.FORWARD or document.is_complex:
                self.direction.addItem(value.value, value)
        if document.is_complex and document.transform is not None and document.transform.direction == TransformDirection.FORWARD:
            self.direction.setCurrentIndex(self.direction.findData(TransformDirection.INVERSE))
        matrix = selection.mode == ViewMode.MATRIX
        self.range.addItem("Full 2D matrix" if matrix else "Full 1D signal", TransformRange.FULL)
        self.range.addItem("Cropped 2D matrix (X/Y + Z bounds)" if matrix else
                           "Cropped 1D signal (X + value bounds)", TransformRange.CROP)
        if selection.mode == ViewMode.MATRIX and index is not None:
            identity = f"{'Row' if row else 'Column'} {index}"
            self.range.addItem(f"Full 1D Slice — {identity}", TransformRange.FULL_SLICE)
            self.range.addItem(f"Cropped 1D Slice — {identity} (X/Y + Z bounds)", TransformRange.SLICE)
        for key in document.keys:
            if key not in (ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR, ImageMember.MONO_COLOR):
                self.channel.addItem(key, key)
        preferred = (ImageMember.RGBA_GRAY if document.key == ImageMember.RGBA_COLOR else
                     ImageMember.RGB_GRAY if document.key == ImageMember.RGB_COLOR else
                     (ImageMember.MONO if ImageMember.MONO in document.keys else ImageMember.RGB_GRAY)
                     if document.key == ImageMember.MONO_COLOR else document.key)
        self.channel.setCurrentIndex(max(0, self.channel.findData(preferred)))
        form.setRowVisible(self.channel, document.is_image)
        self.component.addItem("Full complex values (preserve phase)", False)
        self.component.addItem(f"Current display: {selection.component.value}", True)
        form.setRowVisible(self.component, np.iscomplexobj(document.array))
        self.axis_fields = [
            (self.first_axis_label, self.first_spacing, self.first_unit, self.first_size, self.first_fields),
            (self.second_axis_label, self.second_spacing, self.second_unit, self.second_size, self.second_fields),
        ]
        for _, _, _, size, _ in self.axis_fields:
            size.setRange(1, 2_147_483_647)
            size.setKeyboardTracking(False)
            size.valueChanged.connect(self._summary)
        for value in TransformNorm:
            self.norm.addItem(value.value, value)
        self.centered.setChecked(True)
        for value in TransformWindow:
            self.window_selector.addItem(value.value, value)
        for combo in (self.nan_replacement, self.positive_replacement, self.negative_replacement, self.clipped_replacement):
            if combo is self.clipped_replacement:
                combo.addItem(ValueReplacement.BOUNDARY.value, ValueReplacement.BOUNDARY)
            for method in (ValueReplacement.ZERO, ValueReplacement.MAXIMUM, ValueReplacement.MINIMUM):
                combo.addItem(method.value, method)
        self.single.toggled.connect(self._summary)
        self.generate = self.buttons.addButton("Generate matrix", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.generate.clicked.connect(self._generate)
        self.buttons.rejected.connect(self.reject)
        for combo in (self.direction, self.range, self.component):
            combo.currentIndexChanged.connect(self._reconfigure)
        self.axes.currentIndexChanged.connect(self._axes_changed)
        self._reconfigure()

    def _paired(self) -> bool:
        record = self.document.transform
        return (self.direction.currentData() == TransformDirection.INVERSE and record is not None
                and record.direction == TransformDirection.FORWARD and not self.component.currentData())

    def _reconfigure(self) -> None:
        inverse = self.direction.currentData() == TransformDirection.INVERSE
        if inverse:
            with QtCore.QSignalBlocker(self.component), QtCore.QSignalBlocker(self.range):
                self.component.setCurrentIndex(0)
                if TransformRange(self.range.currentData()).uses_crop:
                    self.range.setCurrentIndex(self.range.findData(TransformRange.FULL))
        self.component.setEnabled(not inverse)
        self.component.setToolTip("IFFT requires both original complex parts; display channels cannot restore the signal."
                                 if inverse else "Choose the full complex source or its current scalar display channel.")
        range_model = self.range.model()
        if isinstance(range_model, QtGui.QStandardItemModel):
            for index in range(self.range.count()):
                item = range_model.item(index)
                if item is not None:
                    item.setEnabled(not inverse or not TransformRange(self.range.itemData(index)).uses_crop)
        paired = self._paired()
        selection, document = self.selection, self.document
        scope = TransformRange(self.range.currentData())
        axes = (selection.y_axis, selection.x_axis) if selection.y_axis is not None else (selection.x_axis,)
        region = self.crop if scope.uses_crop else Crop()
        sizes: list[int] = []
        for axis, start, end in ((selection.y_axis, region.y_start, region.y_end), (selection.x_axis, region.x_start, region.x_end)):
            if axis is not None:
                sizes.append((document.array.shape[axis] - 1 if end is None else end) - start + 1)
        if scope.is_slice:
            along = 1 if self.row else 0
            axes, sizes = (axes[along],), [sizes[along]]
        self._source_axes = tuple(axis for axis in axes if axis is not None)
        self._shape = tuple(sizes)
        record = document.transform
        with QtCore.QSignalBlocker(self.axes):
            self.axes.clear()
            self.axes.addItem("Slice (1D)" if scope.is_slice else "X" if len(sizes) == 1 else
                              "Both X and Y (2D)", tuple(range(len(sizes))))
            if len(sizes) == 2:
                self.axes.addItem("X only (each row)", (1,))
                self.axes.addItem("Y only (each column)", (0,))
            if paired and record is not None:
                recorded = tuple(i for i, axis in enumerate(self._source_axes) if axis in record.axes)
                for i in range(self.axes.count()):
                    if self.axes.itemData(i) == recorded:
                        self.axes.setCurrentIndex(i)
        for i, (label, spacing, unit, size, fields) in enumerate(self.axis_fields):
            visible = i < len(sizes)
            fields.setVisible(visible)
            label.setVisible(visible)
            if not visible:
                continue
            axis = self._source_axes[i]
            grid = document.axes[axis] if document.axes else AxisCoordinates(
                unit="cycles/sample" if inverse else "pixel" if document.is_image else "sample")
            label.setText("Y" if (len(sizes) == 2 and i == 0) or (scope.is_slice and not self.row) else "X")
            spacing.setText(f"{grid.spacing:.15g}")
            unit.setText(grid.unit)
            spacing.setEnabled(not paired and selection.mode != ViewMode.XY)
            unit.setEnabled(not paired)
            if selection.mode == ViewMode.XY:
                spacing.setText("From actual X")
            with QtCore.QSignalBlocker(size):
                size.setMinimum(sizes[i])
                size.setValue(sizes[i])
        self.norm.setEnabled(not paired)
        if paired and record is not None:
            self.norm.setCurrentIndex(self.norm.findData(record.norm))
        self.centered.setVisible(inverse)
        self.centered.setEnabled(not paired)
        if paired:
            self.centered.setChecked(True)
        self.mean.setEnabled(not inverse)
        self.window_selector.setEnabled(not inverse)
        self.trim.setVisible(paired)
        self._configure_values(scope)
        self.note.setText(
            ("Paired IFFT restores recorded coordinates and normalization. Use the complete frequency axes. "
             "Windows, mean removal and value bounds are not undone.\n" if paired else
             "External IFFT: use full complex frequency axes. Δ is the frequency-bin spacing. Choose the input order and matching normalization.\n" if inverse else
             "FFT produces a centered, complete complex spectrum. Δ is the source sampling interval; use s for time or pixel for images.\n")
            + "The source is unchanged. XY input is sorted by X and must be unique and uniformly sampled. "
            "Source crop starts define the phase origin. NPY/MAT/XLSX/CSV/TXT array exports do not store transform metadata.")
        if paired and record is not None:
            self.note.setToolTip(record.description)
        self._axes_changed()

    def _configure_values(self, scope: TransformRange) -> None:
        """Show the applicable treatment policy without scanning source arrays."""
        full_complex = self.document.is_complex and not self.component.currentData()
        phase = is_phase_view(self.document, self.selection) and bool(self.component.currentData())
        restricted = full_complex or phase
        matrix = self.selection.mode == ViewMode.MATRIX
        extent = ("X/Y only" if matrix else "X only") if restricted else ("X/Y + Z bounds" if matrix else "X + value bounds")
        self.range.setItemText(self.range.findData(TransformRange.CROP),
                               f"Cropped {'2D matrix' if matrix else '1D signal'} ({extent})")
        sliced = self.range.findData(TransformRange.SLICE)
        if sliced >= 0:
            self.range.setItemText(sliced, f"Cropped 1D Slice — {'Row' if self.row else 'Column'} {self.index} ({extent})")
        self._apply_bounds = (not restricted and scope.uses_crop
                              and (self.limits.lower is not None or self.limits.upper is not None))
        bounds_text = ("Not applied to full complex / phase input" if restricted else
                       f"Minimum={self.limits.lower}, maximum={self.limits.upper}" if self._apply_bounds else
                       "None set" if scope.uses_crop else "Not applied (full input)")
        self.bounds.setText(bounds_text)
        for combo in (self.nan_replacement, self.positive_replacement, self.negative_replacement, self.clipped_replacement):
            self.treatment_form.setRowVisible(combo, not restricted)
        self.clipped_replacement.setEnabled(self._apply_bounds)
        self.treatment_note.setText(
            "Nonfinite real or imaginary part: replace the whole sample with 0+0j. Valid complex samples retain both components."
            if full_complex else "Invalid phase samples become 0. Phase uses no Z/value bounds."
            if phase else "Extrema use finite, in-bound samples from this input before replacement. "
            "With no valid samples, choose 0. Outside-bound treatment also applies to samples hidden in the viewer.")

    def _axes_changed(self) -> None:
        selected = self.axes.currentData() or ()
        inverse = self.direction.currentData() == TransformDirection.INVERSE
        for i, (_, _, _, size, _) in enumerate(self.axis_fields):
            if i >= len(self._shape):
                continue
            size.setEnabled(not inverse and i in selected)
            if not size.isEnabled():
                size.setValue(self._shape[i])
        self._summary()

    def _summary(self) -> None:
        if not hasattr(self, "estimate"):
            return
        shape = tuple(fields[3].value() for fields in self.axis_fields[:len(self._shape)])
        memory = math.prod(shape) * (8 if self.single.isChecked() else 16)
        self.estimate.setText(f"Output: {shape} · {memory / 1024**2:,.2f} MiB for complex data alone. "
                              "Calculation and views need additional working memory. Full resolution; no 3D downsampling.")

    def _generate(self) -> None:
        try:
            fields = self.axis_fields[:len(self._shape)]
            intervals = (() if self.selection.mode == ViewMode.XY else tuple(float(field[1].text()) for field in fields))
            if any(not math.isfinite(value) or value <= 0 for value in intervals):
                raise ValueError("Each sampling interval must be positive and finite.")
            inverse = self.direction.currentData() == TransformDirection.INVERSE
            options = TransformOptions(
                direction=TransformDirection(self.direction.currentData()), range=TransformRange(self.range.currentData()),
                axes=tuple(self.axes.currentData()), spacing=intervals, units=tuple(field[2].text().strip() or "sample" for field in fields),
                output_shape=tuple(field[3].value() for field in fields), norm=TransformNorm(self.norm.currentData()),
                window=TransformWindow.NONE if inverse else TransformWindow(self.window_selector.currentData()),
                subtract_mean=not inverse and self.mean.isChecked(),
                value_policy=FourierValuePolicy(
                    nan=ValueReplacement(self.nan_replacement.currentData()),
                    positive=ValueReplacement(self.positive_replacement.currentData()),
                    negative=ValueReplacement(self.negative_replacement.currentData()),
                    clipped=ValueReplacement(self.clipped_replacement.currentData())),
                single_precision=self.single.isChecked(), display_component=bool(self.component.currentData()),
                apply_bounds=self._apply_bounds, input_centered=self.centered.isChecked(),
                image_key=self.channel.currentData() if self.document.is_image else None,
                row=self.row, index=self.index or 0, trim_padding=self._paired() and self.trim.isChecked())
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Fourier settings", str(exc))
            return
        self.generate_requested.emit(options, self.name.text().strip())

    def set_busy(self, busy: bool) -> None:
        """Disable edits during the owner's worker operation; no polling is used."""
        self._busy = busy
        self.settings.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.generate.setText("Computing…" if busy else "Generate matrix")

    def reject(self) -> None:
        """Close only before/after a worker operation, retaining its source snapshot."""
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
