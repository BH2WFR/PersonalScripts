"""Modal matrix/channel selection for Cartesian or polar complex reconstruction.

Requirements: PySide6 and the viewer data model. Usage: WorkspaceWindow opens
this dialog; Generate submits immutable inputs to its existing worker pool.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .complex_merge import MergeInput, MergeMatrix, MergeMode, PhaseUnit
from .data_model import Component
from .ui_complex_merge_dialog import Ui_ComplexMergeDialog


class ComplexMergeDialog(QtWidgets.QDialog, Ui_ComplexMergeDialog):
    """Choose two numeric channels without loading derived pixels in the GUI.

    Args:
        matrices: Session sources with available real-valued channel choices.
        initial: Index of the initially active source matrix.
        parent: Owning viewer.

    Side effects:
        Emits generate_requested(first, second, mode, phase_unit, name). Heavy
        extraction, validation and reconstruction run only after Generate.
    """

    generate_requested = QtCore.Signal(object, object, object, object, str)

    def __init__(self, matrices: tuple[MergeMatrix, ...], initial: int = 0,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.matrices = matrices
        self._busy = False
        self.setModal(True)
        for mode in MergeMode:
            self.mode_selector.addItem(mode.value, mode)
        self.input_boxes = [self.first_input, self.second_input]
        self.matrix_selectors = [self.first_matrix, self.second_matrix]
        self.channel_selectors = [self.first_channel, self.second_channel]
        self.details = [self.first_detail, self.second_detail]
        for side, (matrix, channel) in enumerate(zip(self.matrix_selectors, self.channel_selectors)):
            matrix.addItems([item.label for item in matrices])
            matrix.currentIndexChanged.connect(lambda _index, side=side: self._matrix_changed(side))
            channel.currentIndexChanged.connect(lambda _index, side=side: self._channel_changed(side))
        for unit in PhaseUnit:
            self.phase_unit.addItem(unit.value, unit)
        self.generate = self.buttons.addButton("Generate complex matrix", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self.generate.clicked.connect(self._generate)
        self.buttons.rejected.connect(self.reject)
        self.mode_selector.currentIndexChanged.connect(self._mode_changed)
        for side, matrix in enumerate(self.matrix_selectors):
            with QtCore.QSignalBlocker(matrix):
                matrix.setCurrentIndex(min(initial + side, len(matrices) - 1))
            self._matrix_changed(side)
        self._mode_changed()

    def _input(self, side: int) -> MergeInput | None:
        matrix = self.matrix_selectors[side].currentIndex()
        channel = self.channel_selectors[side].currentIndex()
        return self.matrices[matrix].channels[channel] if matrix >= 0 and channel >= 0 else None

    def _matrix_changed(self, side: int) -> None:
        index = self.matrix_selectors[side].currentIndex()
        combo = self.channel_selectors[side]
        with QtCore.QSignalBlocker(combo):
            combo.clear()
            if index >= 0:
                for item in self.matrices[index].channels:
                    combo.addItem(item.channel_label)
        self._select_component(side)
        self._channel_changed(side)

    def _select_component(self, side: int) -> None:
        index = self.matrix_selectors[side].currentIndex()
        if index < 0:
            return
        polar = self.mode_selector.currentData() == MergeMode.POLAR
        wanted = ((Component.MAGNITUDE, Component.PHASE) if polar
                  else (Component.REAL, Component.IMAGINARY))[side]
        for channel, item in enumerate(self.matrices[index].channels):
            if item.document.is_complex and item.selection.component == wanted:
                self.channel_selectors[side].setCurrentIndex(channel)
                break

    def _channel_changed(self, side: int) -> None:
        item = self._input(side)
        if item is not None:
            self.details[side].setText(f"{item.document.array.shape} · {item.document.array.dtype} · {item.selection.mode.value}")
            self.details[side].setToolTip(item.label)
            if side == 1 and item.document.is_complex:
                if item.selection.component == Component.PHASE:
                    self.phase_unit.setCurrentIndex(self.phase_unit.findData(PhaseUnit.RADIANS))
        self.generate.setEnabled(all(self._input(index) is not None for index in range(2)))

    def _mode_changed(self) -> None:
        polar = self.mode_selector.currentData() == MergeMode.POLAR
        for side, title in enumerate(("Magnitude", "Phase") if polar else ("Real part", "Imaginary part")):
            self.input_boxes[side].setTitle(title)
            self._select_component(side)
        self.phase_unit.setEnabled(polar)

    def _generate(self) -> None:
        first, second = self._input(0), self._input(1)
        if first is not None and second is not None:
            self.generate_requested.emit(first, second, MergeMode(self.mode_selector.currentData()),
                                         PhaseUnit(self.phase_unit.currentData()), self.result_name.text().strip())

    def set_busy(self, busy: bool) -> None:
        """Keep the dialog and source snapshots alive while its worker runs."""
        self._busy = busy
        self.settings.setEnabled(not busy)
        self.buttons.setEnabled(not busy)
        self.generate.setText("Merging…" if busy else "Generate complex matrix")

    def reject(self) -> None:
        """Permit closing only when no merge operation is in flight."""
        if not self._busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
