"""Modal, on-demand pointwise conversion settings for the active channel.

Requirements: PySide6 and the viewer data model. Usage: opened by WorkspaceWindow;
Generate submits a worker job, while changing settings never recomputes arrays.
"""

import math

from PySide6 import QtCore, QtGui, QtWidgets

from .data_conversion import (COMPLEX_CONVERSIONS, DB_CONVERSIONS, DEFAULT_DB_FLOOR,
                              Conversion, ConversionOptions, DBReference)
from .data_model import Component, Document, Selection, ViewMode
from .fourier import TransformRange
from .qt_widgets import NoWheelComboBox


class DataConversionDialog(QtWidgets.QDialog):
    """Collect scope and arithmetic parameters without reading full arrays.

    Args:
        document: Active source document.
        selection: Current interpretation and component.
        source_name: Matrix/channel identity shown above the settings.
        row: Current slice direction, True for a row.
        index: Selected source slice index, or None if no slice is selected.
        parent: Owning viewer.

    Side effects:
        Emits generate_requested(options, name) after validating numeric inputs.
    """

    generate_requested = QtCore.Signal(object, str)

    def __init__(self, document: Document, selection: Selection, source_name: str,
                 row: bool = True, index: int | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._busy = False
        self.document, self.selection = document, selection
        self.row, self.index = row, index
        self.setWindowTitle("Data conversion")
        self.setModal(True)
        self.resize(650, 530)
        layout = QtWidgets.QVBoxLayout(self)
        source = QtWidgets.QLabel(f"Source: {source_name}\n{document.array.shape} · {document.array.dtype}")
        source.setWordWrap(True)
        layout.addWidget(source)
        self.settings = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.settings)
        layout.addWidget(self.settings)
        self.operation = NoWheelComboBox()
        for operation in Conversion:
            self.operation.addItem(operation.value, operation)
        self.form.addRow("Operation", self.operation)
        self.range_selector = NoWheelComboBox()
        for scope in TransformRange:
            if scope != TransformRange.SLICE or (selection.mode == ViewMode.MATRIX and index is not None):
                self.range_selector.addItem(scope.value, scope)
        self.form.addRow("Input range", self.range_selector)
        self.full_complex = QtWidgets.QCheckBox("Use full complex values (instead of selected component)")
        self.full_complex.setChecked(document.is_complex)
        self.form.addRow(self.full_complex)
        self.form.setRowVisible(self.full_complex, document.is_complex)
        self.bounds = QtWidgets.QCheckBox("Apply current value bounds before conversion")
        self.form.addRow(self.bounds)
        self.reference_mode = NoWheelComboBox()
        for mode in DBReference:
            self.reference_mode.addItem(mode.value, mode)
        self.form.addRow("dB reference", self.reference_mode)
        self.reference = QtWidgets.QLineEdit("1")
        self.reference.setToolTip("Reference amplitude or power in the same units as the input; must be positive.")
        self.form.addRow("Reference value", self.reference)
        self.use_floor = QtWidgets.QCheckBox("Clamp dB output below this floor")
        self.use_floor.setChecked(True)
        self.form.addRow(self.use_floor)
        self.floor = QtWidgets.QLineEdit(f"{DEFAULT_DB_FLOOR:g}")
        self.form.addRow("dB floor", self.floor)
        self.gain = QtWidgets.QLineEdit("1")
        self.offset = QtWidgets.QLineEdit("0")
        self.form.addRow("Scale", self.gain)
        self.form.addRow("Offset", self.offset)
        self.result_name = QtWidgets.QLineEdit()
        self.result_name.setPlaceholderText("Automatic: source · channel · operation")
        self.form.addRow("Result name", self.result_name)
        self.formula = QtWidgets.QLabel()
        self.formula.setWordWrap(True)
        layout.addWidget(self.formula)
        note = QtWidgets.QLabel(
            "Creates a new matrix. Original arrays are unchanged. XY converts Y only; point clouds convert Z only. "
            "Source coordinates, repeated X values and record order are preserved. Color composites use grayscale height. "
            "NaN / Inf and undefined results remain gaps. Peak dB uses the selected range after optional value bounds; "
            "all-zero input uses reference 1. Transformed values can be exported through the Export group.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.generate = self.buttons.addButton("Generate matrix", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.generate.clicked.connect(self._generate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.operation.currentIndexChanged.connect(self._update_controls)
        self.reference_mode.currentIndexChanged.connect(self._update_controls)
        self.full_complex.toggled.connect(self._update_controls)
        self.use_floor.toggled.connect(self._update_controls)
        if document.is_complex and selection.component == Component.PHASE:
            self.operation.setCurrentIndex(self.operation.findData(Conversion.RAD2DEG))
        self._update_controls()

    def _update_controls(self) -> None:
        operation = Conversion(self.operation.currentData())
        db = operation in DB_CONVERSIONS
        self.full_complex.setEnabled(self.document.is_complex and operation in COMPLEX_CONVERSIONS)
        full_complex = self.full_complex.isEnabled() and self.full_complex.isChecked()
        self.bounds.setEnabled(not full_complex)
        for widget in (self.reference_mode, self.reference, self.use_floor, self.floor):
            self.form.setRowVisible(widget, db)
        self.reference.setEnabled(self.reference_mode.currentData() == DBReference.FIXED)
        self.floor.setEnabled(self.use_floor.isChecked())
        for widget in (self.gain, self.offset):
            self.form.setRowVisible(widget, operation == Conversion.AFFINE)
        formulas = {
            Conversion.AMPLITUDE_DB: "y = 20 × log10(abs(x) / reference). Uses amplitude magnitude; sign and complex phase are discarded.",
            Conversion.POWER_DB: "y = 10 × log10(x / reference). Input must already represent power; negative samples become NaN. No implicit squaring.",
            Conversion.DEG2RAD: "y = x × π / 180. Input: degrees; output: radians.",
            Conversion.RAD2DEG: "y = x × 180 / π. Input: radians; output: degrees.",
            Conversion.ABSOLUTE: "y = abs(x). Complex input produces a real magnitude matrix.",
            Conversion.LOG10: "y = log10(x). Real input only; zero and negative samples become NaN.",
            Conversion.LN: "y = ln(x). Real input only; zero and negative samples become NaN.",
            Conversion.AFFINE: "y = x × scale + offset. For full complex input, the real offset is added to the real part only.",
        }
        self.formula.setText(formulas[operation])

    def _generate(self) -> None:
        try:
            operation = Conversion(self.operation.currentData())
            db = operation in DB_CONVERSIONS
            reference_mode = DBReference(self.reference_mode.currentData())
            reference = float(self.reference.text()) if db and reference_mode == DBReference.FIXED else 1.0
            floor = float(self.floor.text()) if db and self.use_floor.isChecked() else None
            gain = float(self.gain.text()) if operation == Conversion.AFFINE else 1.0
            offset = float(self.offset.text()) if operation == Conversion.AFFINE else 0.0
            if not math.isfinite(reference) or reference <= 0:
                raise ValueError("The dB reference must be finite and greater than zero.")
            if floor is not None and (not math.isfinite(floor) or floor >= 0):
                raise ValueError("The dB floor must be finite and negative.")
            if not math.isfinite(gain) or not math.isfinite(offset):
                raise ValueError("Scale and offset must be finite numbers.")
            options = ConversionOptions(
                operation, TransformRange(self.range_selector.currentData()),
                self.full_complex.isEnabled() and self.full_complex.isChecked(),
                self.bounds.isEnabled() and self.bounds.isChecked(), reference_mode, reference,
                floor, gain, offset, self.row, self.index if self.index is not None else 0,
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid conversion settings", str(exc))
            return
        self.generate_requested.emit(options, self.result_name.text().strip())

    def set_busy(self, busy: bool) -> None:
        """Disable editing and closing while the captured worker is running."""
        self._busy = busy
        self.settings.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.generate.setText("Converting…" if busy else "Generate matrix")

    def reject(self) -> None:
        """Allow cancellation only before or after a conversion job."""
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
