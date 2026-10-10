"""On-demand settings for a 1D Laplace plane or its contour-based inverse.

Requirements: numpy and PySide6. Usage: opened modally by WorkspaceWindow.
No transform runs until Generate is pressed; calculations use the existing worker.
"""

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .data_model import Crop, Document, Selection, ViewMode, is_phase_view
from .fourier import TransformRange
from .qt_widgets import NoWheelComboBox
from .laplace import (DEFAULT_SIGMA_COUNT, MAX_OUTPUT_BYTES, LaplaceDirection,
                      LaplaceOptions, default_sigma_range, sigma_values)


class LaplaceDialog(QtWidgets.QDialog):
    """Collect one stable source's Laplace sampling or inverse contour settings.

    Args:
        document: Source numeric document, retained while the dialog is open.
        selection: Current signal/XY or complex-plane interpretation.
        crop: Applied sample-index crop, offered for forward transforms only.
        source_name: Session label shown to the user.
        parent: Owning viewer window.

    Side effects:
        Emits generate_requested(options, name); never computes on control changes.
    """

    generate_requested = QtCore.Signal(object, str)

    def __init__(self, document: Document, selection: Selection, crop: Crop,
                 source_name: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.document, self.selection, self.crop = document, selection, crop
        self._busy = False
        self.inverse = selection.mode == ViewMode.MATRIX
        record = document.laplace
        self.paired = self.inverse and record is not None and record.direction == LaplaceDirection.FORWARD
        self.setWindowTitle("Inverse Laplace transform" if self.inverse else "Laplace transform")
        self.setModal(True)
        self.resize(630, 590)
        layout = QtWidgets.QVBoxLayout(self)
        source = QtWidgets.QLabel(f"Source: {source_name}\n{document.array.shape} · {document.array.dtype}")
        source.setWordWrap(True)
        layout.addWidget(source)
        self.settings = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(self.settings)
        layout.addWidget(self.settings)
        self.range_selector = NoWheelComboBox()
        for value in (TransformRange.FULL, TransformRange.CROP):
            self.range_selector.addItem(value.value, value)
        self.spacing = QtWidgets.QLineEdit(f"{document.axes[selection.x_axis].spacing:.15g}" if document.axes else "1")
        self.spacing.setEnabled(selection.mode != ViewMode.XY)
        if selection.mode == ViewMode.XY:
            self.spacing.setToolTip("Uses the actual sorted, unique, uniformly spaced X coordinates.")
        self.unit = QtWidgets.QLineEdit(document.axes[selection.x_axis].unit if document.axes else "sample")
        self.auto_sigma = QtWidgets.QCheckBox("Automatic sigma range (±4 / signal duration)")
        self.auto_sigma.setChecked(True)
        self.sigma_min = QtWidgets.QLineEdit()
        self.sigma_max = QtWidgets.QLineEdit()
        self.sigma_count = QtWidgets.QSpinBox()
        self.sigma_count.setRange(2, 65536)
        self.sigma_count.setValue(DEFAULT_SIGMA_COUNT)
        self.fft_size = QtWidgets.QSpinBox()
        self.fft_size.setRange(0, 2_147_483_647)
        self.fft_size.setSpecialValueText("Same as input")
        self.component = QtWidgets.QCheckBox(f"Transform current display component ({selection.component.value})")
        self.bounds = QtWidgets.QCheckBox("Apply current value bounds before transforming")
        self.fill_zero = QtWidgets.QCheckBox("Replace NaN / Inf / filtered samples with zero")
        self.single = QtWidgets.QCheckBox("Single precision (complex64)")
        self.row = QtWidgets.QSpinBox()
        row_count = record.sigma_count if self.paired and record is not None else document.array.shape[selection.y_axis or 0]
        self.row.setRange(-1 if self.paired else 0, max(0, row_count - 1))
        if self.paired:
            self.row.setSpecialValueText("Automatic: sigma nearest zero")
            self.row.setValue(-1)
        self.inverse_sigma = QtWidgets.QLineEdit("0")
        self.omega_spacing = QtWidgets.QLineEdit("1")
        self.output_count = QtWidgets.QSpinBox()
        frequency_count = record.fft_size if self.paired and record is not None else document.array.shape[selection.x_axis]
        self.output_count.setRange(1, frequency_count)
        self.output_count.setValue(document.array.shape[selection.x_axis])
        self.origin = QtWidgets.QLineEdit("0")
        self.inverse_unit = QtWidgets.QLineEdit("sample")
        self.centered = QtWidgets.QCheckBox("Frequency columns use centered order (fftshift)")
        self.centered.setChecked(True)
        if self.inverse:
            form.addRow("Sigma row (zero-based)", self.row)
            form.addRow("Sigma of this row (1 / time unit)", self.inverse_sigma)
            form.addRow("Angular-frequency step (rad / time unit)", self.omega_spacing)
            form.addRow("Original sample count (without padding)", self.output_count)
            form.addRow("Output coordinate origin", self.origin)
            form.addRow("Output time unit", self.inverse_unit)
            form.addRow(self.centered)
            if self.paired and record is not None:
                self.omega_spacing.setText(f"{2 * np.pi / (record.fft_size * record.time_grid.spacing):.15g}")
                self.output_count.setValue(record.input_count)
                self.origin.setText(f"{record.time_grid.origin:.15g}")
                self.inverse_unit.setText(record.time_grid.unit)
                for widget in (self.inverse_sigma, self.omega_spacing, self.output_count, self.origin, self.inverse_unit, self.centered):
                    widget.setEnabled(False)
        else:
            form.addRow("Input range", self.range_selector)
            form.addRow("Sampling interval dt", self.spacing)
            form.addRow("Time / sample unit", self.unit)
            form.addRow(self.auto_sigma)
            form.addRow("Sigma minimum", self.sigma_min)
            form.addRow("Sigma maximum", self.sigma_max)
            form.addRow("Sigma rows", self.sigma_count)
            form.addRow("Frequency columns (optional zero padding)", self.fft_size)
            if np.iscomplexobj(document.array):
                form.addRow(self.component)
            form.addRow(self.bounds)
            form.addRow(self.fill_zero)
            form.addRow(self.single)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("Automatic: source · channel · Laplace / Inverse Laplace")
        form.addRow("Result name", self.name)
        self.note = QtWidgets.QLabel(
            ("Recorded plane: sampling and length are restored automatically. " if self.paired else
             "External plane: enter the original spectrum parameters. An arbitrary complex matrix cannot supply them automatically. ") +
            "Inversion uses one complete sigma row; other rows are not averaged. "
            "Columns must cover the full uniform DFT angular-frequency grid, with normalization dt × FFT. "
            "A row nearer sigma = 0 usually reduces numerical error. Cropping and value bounds are ignored."
            if self.inverse else
            "Output: rows = sigma, columns = omega (rad / time unit). Full complex values are retained by default. "
            "Kernel time starts at the first selected sample; its original coordinate is restored by inversion. "
            "This computes a finite-record numerical Laplace transform. XY input must have unique, uniformly spaced X values. "
            "Exponential weighting can amplify roundoff; use a moderate sigma range.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.estimate = QtWidgets.QLabel()
        self.estimate.setWordWrap(True)
        layout.addWidget(self.estimate)
        persistence = QtWidgets.QLabel("NPY / MAT / CSV / TXT exports save values only. After reloading, enter the inverse parameters manually.")
        persistence.setWordWrap(True)
        layout.addWidget(persistence)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.generate = self.buttons.addButton("Generate matrix", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.generate.clicked.connect(self._generate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.range_selector.currentIndexChanged.connect(self._summary)
        for widget in (self.spacing, self.omega_spacing, self.inverse_sigma):
            widget.textChanged.connect(self._summary)
        for widget in (self.auto_sigma, self.single, self.component):
            widget.toggled.connect(self._summary)
        for widget in (self.sigma_count, self.fft_size, self.row, self.output_count):
            widget.valueChanged.connect(self._summary)
        self._summary()

    def _source_count(self) -> int:
        count = self.document.array.shape[self.selection.x_axis]
        if self.range_selector.currentData() == TransformRange.CROP:
            count = (count - 1 if self.crop.x_end is None else self.crop.x_end) - self.crop.x_start + 1
        return count

    def _summary(self) -> None:
        if self.inverse:
            record = self.document.laplace
            if self.paired and record is not None:
                sigmas = sigma_values(record)
                index = int(np.argmin(np.abs(sigmas))) if self.row.value() < 0 else self.row.value()
                with QtCore.QSignalBlocker(self.inverse_sigma):
                    self.inverse_sigma.setText(f"{float(sigmas[index]):.15g}")
                dt = record.time_grid.spacing
            else:
                try:
                    dt = 2 * np.pi / (self.document.array.shape[self.selection.x_axis] * float(self.omega_spacing.text()))
                except (ValueError, ZeroDivisionError):
                    dt = float("nan")
            self.estimate.setText(f"Output: {self.output_count.value()} complex samples; dt = {dt:.9g}. Full complex input; double-precision inverse.")
            return
        self.bounds.setEnabled((not np.iscomplexobj(self.document.array) or self.component.isChecked())
                               and not is_phase_view(self.document, self.selection))
        auto = self.auto_sigma.isChecked()
        self.sigma_min.setEnabled(not auto)
        self.sigma_max.setEnabled(not auto)
        count = self._source_count()
        if auto:
            try:
                low, high = default_sigma_range(count, float(self.spacing.text()))
                self.sigma_min.setText(f"{low:.9g}")
                self.sigma_max.setText(f"{high:.9g}")
            except ValueError:
                pass
        size = self.fft_size.value() or count
        memory = self.sigma_count.value() * size * (8 if self.single.isChecked() else 16)
        extra = " Automatic sigma bounds use actual X spacing." if self.selection.mode == ViewMode.XY and auto else ""
        self.estimate.setText(f"Output: ({self.sigma_count.value()}, {size}) complex values; {memory / 1024**2:.2f} MiB. "
                              f"Limit: {MAX_OUTPUT_BYTES / 1024**3:g} GiB; reduce rows or crop large inputs.{extra}")

    def _generate(self) -> None:
        try:
            if self.inverse:
                options = LaplaceOptions(direction=LaplaceDirection.INVERSE,
                    inverse_row=None if self.row.value() < 0 else self.row.value(),
                    omega_spacing=float(self.omega_spacing.text()), external_sigma=float(self.inverse_sigma.text()),
                    output_count=self.output_count.value(), output_origin=float(self.origin.text()),
                    unit=self.inverse_unit.text().strip() or "sample", input_centered=self.centered.isChecked())
            else:
                spacing = 1.0 if self.selection.mode == ViewMode.XY else float(self.spacing.text())
                if not math.isfinite(spacing) or spacing <= 0:
                    raise ValueError("Sampling interval dt must be positive and finite.")
                options = LaplaceOptions(range=TransformRange(self.range_selector.currentData()), spacing=spacing,
                    unit=self.unit.text().strip() or "sample",
                    sigma_min=None if self.auto_sigma.isChecked() else float(self.sigma_min.text()),
                    sigma_max=None if self.auto_sigma.isChecked() else float(self.sigma_max.text()),
                    sigma_count=self.sigma_count.value(), fft_size=self.fft_size.value(),
                    single_precision=self.single.isChecked(), display_component=self.component.isChecked(),
                    apply_bounds=self.bounds.isEnabled() and self.bounds.isChecked(), fill_zero=self.fill_zero.isChecked())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Laplace settings", str(exc))
            return
        self.generate_requested.emit(options, self.name.text().strip())

    def set_busy(self, busy: bool) -> None:
        """Disable settings and closing while the owner's worker is computing."""
        self._busy = busy
        self.settings.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.generate.setText("Computing…" if busy else "Generate matrix")

    def reject(self) -> None:
        """Keep the captured source alive until the worker completes."""
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
