"""Compact global/current-page group boxes; geometry edits commit on editingFinished."""

from PySide6 import QtCore, QtWidgets
from utils.qt_widgets import NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox
from .model import Axis, Box, Settings, MAX_PIECES, dividers

NUDGE_POINTS = 10.0
MAX_PAGE_POINTS = 10_000_000.0

TIPS: dict[str, str] = {
    "count": "Number of equal output pages produced from each source page. Start at 2 for a scanned two-page spread. Explicit custom pages retain their saved crops and paper size.",
    "axis": "Arrange equal crops from left to right or top to bottom, following the displayed page rotation. Choose left/right for facing book pages and top/bottom for stacked pages.",
    "order": "Output order of spatial crops, numbered from the left/top. Leave blank for automatic order, or enter every number exactly once, such as 2,1 or 3,1,2. Custom pages retain their saved order.",
    "reverse": "Reverse the automatic or explicitly entered output sequence. This changes reading order without moving the crops. Custom pages retain their saved order.",
    "start": "First physical source page to split, counting from 1. Earlier pages remain whole unless explicitly customized. Set this after the cover/front matter if they should remain unsplit.",
    "end": "Last physical source page to split, inclusive. Last page uses the end of the document. Later pages remain whole unless explicitly customized.",
    "keep": "Keep this source page whole in the output. Its saved custom crops are restored when unchecked. The page list and output start numbers update immediately.",
    "reset": "Remove this page's override and use the current general count, arrangement, order and range. This also restores equal default crops and their output paper size.",
    "selection": "Choose All to edit every crop together, or a numbered crop to edit only that frame. All displays the first crop's values. X/Y move all crops by the same offset; typed width/height assigns that dimension to all crops, while +/-10 adjusts each crop by 10 pt.",
    "X": "Left edge of the crop, in PDF points measured from the displayed page's left edge. Larger values move right; negative values extend beyond the page. All uses the first crop as its reference and preserves spacing when moving.",
    "Y": "Top edge of the crop, in PDF points measured from the displayed page's top edge. Larger values move down; negative values extend above the page. Areas outside the source become blank in the output.",
    "Width": "Width of the selected crop, or all crops when All is selected. Smaller crops are centered at original scale on the fixed output paper, with blank margins. Resizing keeps the crop's left edge fixed and cannot exceed its output paper width.",
    "Height": "Height of the selected crop, or all crops when All is selected. Smaller crops are centered at original scale on the fixed output paper, with blank margins. Resizing keeps the crop's top edge fixed and cannot exceed its output paper height.",
    "divider": "Choose an edge shared by neighboring crops; numbers refer to their output order. After independent moves or resizing, some crops no longer share an edge. Use X/Y to adjust those crops instead.",
    "position": "Position of the chosen shared divider, measured from the left/top along the general arrangement axis. Changing it translates All crops or the selected numbered crop without resizing. Out-of-source areas become blank.",
}


class SplitPanel(QtWidgets.QWidget):
    """Edit split rules without PDF access; the window validates and owns all changes.

    Signals report proposed changes, never mutate the session directly. Loading
    values suppresses signals. Coordinate units are displayed-page points (1/72 inch).
    """

    globalEdited = QtCore.Signal()
    keepChanged = QtCore.Signal(bool)
    resetRequested = QtCore.Signal()
    cropsEdited = QtCore.Signal(object)
    dividerEdited = QtCore.Signal(object, float)
    selectionChanged = QtCore.Signal(int)
    moveRequested = QtCore.Signal(float, float, bool)

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        self._width = 1.0
        self._height = 1.0
        self._boxes: tuple[Box, ...] = ()
        self._axis = Axis.LEFT_RIGHT
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.general = QtWidgets.QGroupBox("General")
        form = QtWidgets.QFormLayout(self.general)
        self.count = NoWheelSpinBox()
        self.count.setRange(1, MAX_PIECES)
        self.count.setKeyboardTracking(False)
        self.count.setValue(2)
        self.count.editingFinished.connect(self._global_commit)
        form.addRow("Pieces per page", self.count)
        self.axis = NoWheelComboBox()
        self.axis.addItem("Left / right", Axis.LEFT_RIGHT)
        self.axis.addItem("Top / bottom", Axis.TOP_BOTTOM)
        self.axis.currentIndexChanged.connect(self._global_commit)
        form.addRow("Arrangement", self.axis)
        self.order = QtWidgets.QLineEdit()
        self.order.setPlaceholderText("Automatic: 1,2,…")
        self.order.setToolTip("Spatial boxes are numbered from left/top. Enter each number exactly once, for example 2,1 or 3,1,2. Custom pages retain their saved order.")
        self.order.editingFinished.connect(self._global_commit)
        form.addRow("Output order", self.order)
        self.reverse = QtWidgets.QCheckBox("Reverse order")
        self.reverse.toggled.connect(self._global_commit)
        form.addRow(self.reverse)
        self.start = NoWheelSpinBox()
        self.start.setRange(1, 1)
        self.end = NoWheelSpinBox()
        self.end.setRange(0, 1)
        self.end.setSpecialValueText("Last page")
        for title, spin in (("First split page", self.start), ("Last split page", self.end)):
            spin.setKeyboardTracking(False)
            spin.editingFinished.connect(self._global_commit)
            form.addRow(title, spin)
        note = QtWidgets.QLabel("Outside this range: keep whole.\nCustom pages retain their own crops and order.")
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(self.general)

        self.current = QtWidgets.QGroupBox("Current page")
        current_layout = QtWidgets.QVBoxLayout(self.current)
        self.keep = QtWidgets.QCheckBox("No processing (keep whole)")
        self.keep.toggled.connect(self._keep_changed)
        current_layout.addWidget(self.keep)
        self.reset = QtWidgets.QPushButton("Reset to general settings")
        self.reset.clicked.connect(self.resetRequested)
        current_layout.addWidget(self.reset)
        self.geometry_controls = QtWidgets.QWidget()
        controls = QtWidgets.QFormLayout(self.geometry_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.selection = NoWheelComboBox()
        self.selection.currentIndexChanged.connect(self._select_box)
        self.selection.addItem("All")
        controls.addRow("Crop", self.selection)
        self.coordinates: list[QtWidgets.QDoubleSpinBox] = []
        self.coordinate_buttons: list[tuple[QtWidgets.QPushButton, QtWidgets.QPushButton]] = []
        for index, label in enumerate(("X", "Y", "Width", "Height")):
            spin = self._point_spin()
            if index < 2:
                spin.setMinimum(-MAX_PAGE_POINTS)
            spin.editingFinished.connect(lambda i=index: self._box_commit(i))
            self.coordinates.append(spin)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(spin, 1)
            buttons: list[QtWidgets.QPushButton] = []
            for step in (-NUDGE_POINTS, NUDGE_POINTS):
                button = QtWidgets.QPushButton(f"{step:+.0f}")
                button.setFixedWidth(40)
                button.setToolTip(f"Adjust {label} by {step:+.0f} pt for All crops or the selected numbered crop.\n{TIPS[label]}")
                button.clicked.connect(lambda checked=False, i=index, delta=step: self._nudge_box(i, delta))
                row.addWidget(button)
                buttons.append(button)
            self.coordinate_buttons.append((buttons[0], buttons[1]))
            controls.addRow(label, row)
            spin.setToolTip(TIPS[label])
            self._label_tip(controls, row, TIPS[label])
        self.divider = NoWheelComboBox()
        self.divider.currentIndexChanged.connect(self._select_divider)
        controls.addRow("Shared divider", self.divider)
        row = QtWidgets.QHBoxLayout()
        self.position = self._point_spin()
        self.position.setMinimum(-MAX_PAGE_POINTS)
        self.position.editingFinished.connect(self._divider_commit)
        row.addWidget(self.position, 1)
        self.divider_buttons: list[QtWidgets.QPushButton] = []
        for step in (-NUDGE_POINTS, NUDGE_POINTS):
            button = QtWidgets.QPushButton(f"{step:+.0f}")
            button.setFixedWidth(40)
            button.setToolTip(f"Move the chosen divider by {step:+.0f} pt.\n{TIPS['position']}")
            button.clicked.connect(lambda checked=False, delta=step: self._nudge_divider(delta))
            row.addWidget(button)
            self.divider_buttons.append(button)
        controls.addRow("Divider position", row)
        self._label_tip(controls, row, TIPS["position"])
        note = QtWidgets.QLabel("Coordinates: top-left origin, in pt (1/72 inch).\nOutside the source: blank. Smaller crops: centered on the same paper size.")
        note.setWordWrap(True)
        controls.addRow(note)
        current_layout.addWidget(self.geometry_controls)
        layout.addWidget(self.current)
        layout.addStretch(1)
        for key, editor in (("count", self.count), ("axis", self.axis), ("order", self.order),
                            ("reverse", self.reverse), ("start", self.start), ("end", self.end)):
            editor.setToolTip(TIPS[key])
            self._label_tip(form, editor, TIPS[key])
        for key, editor in (("selection", self.selection), ("divider", self.divider)):
            editor.setToolTip(TIPS[key])
            self._label_tip(controls, editor, TIPS[key])
        self.keep.setToolTip(TIPS["keep"])
        self.reset.setToolTip(TIPS["reset"])
        self.position.setToolTip(TIPS["position"])

    @staticmethod
    def _label_tip(form: QtWidgets.QFormLayout, field: QtWidgets.QWidget | QtWidgets.QLayout, text: str) -> None:
        label = form.labelForField(field)
        if label is not None:
            label.setToolTip(text)

    def selected_index(self) -> int:
        """Return the zero-based crop index, or -1 for the combined All choice."""
        return self.selection.currentIndex() - 1

    @staticmethod
    def _point_spin() -> QtWidgets.QDoubleSpinBox:
        spin = NoWheelDoubleSpinBox()
        spin.setRange(0, MAX_PAGE_POINTS)
        spin.setDecimals(3)
        spin.setSingleStep(1)
        spin.setSuffix(" pt")
        spin.setKeyboardTracking(False)
        spin.setMinimumWidth(70)
        return spin

    def read_settings(self) -> Settings:
        """Read a proposed global configuration; validation belongs to the window."""
        return Settings(self.count.value(), Axis(self.axis.currentData()), self.reverse.isChecked(),
                        self.order.text().strip(), self.start.value(), self.end.value())

    def load_settings(self, settings: Settings, pages: int) -> None:
        """Restore committed global controls without emitting edits."""
        self._loading = True
        try:
            self.count.setValue(settings.count)
            self.axis.setCurrentIndex(self.axis.findData(settings.axis))
            self.reverse.setChecked(settings.reverse)
            self.order.setText(settings.order)
            self.start.setMaximum(max(1, pages))
            self.end.setMaximum(max(1, pages))
            self.start.setValue(settings.start)
            self.end.setValue(settings.end)
        finally:
            self._loading = False

    def load_page(self, boxes: tuple[Box, ...], axis: Axis, width: float, height: float,
                  keep: bool, custom: bool, *, reset_selection: bool = False) -> None:
        """Load current geometry; preserve crop selection on edits, reset it on page turns."""
        self._loading = True
        try:
            selected = 0 if reset_selection else max(0, self.selection.currentIndex())
            divider = max(0, self.divider.currentIndex())
            self._boxes, self._axis = boxes, axis
            self._width, self._height = width, height
            self.keep.setChecked(keep)
            self.geometry_controls.setEnabled(not keep)
            self.reset.setEnabled(custom)
            self.selection.clear()
            self.selection.addItem("All")
            self.selection.addItems([str(i + 1) for i in range(len(boxes))])
            self.selection.setCurrentIndex(min(selected, len(boxes)))
            self.divider.clear()
            for pair in dividers(boxes, axis):
                self.divider.addItem(f"{pair[0] + 1} | {pair[1] + 1}", pair)
            self.divider.setCurrentIndex(min(divider, self.divider.count() - 1))
            self.position.setEnabled(self.divider.count() > 0)
            for button in self.divider_buttons:
                button.setEnabled(self.divider.count() > 0)
        finally:
            self._loading = False
        self._select_box()
        self._select_divider()

    def _global_commit(self, *_args: object) -> None:
        if not self._loading:
            self.globalEdited.emit()

    def _keep_changed(self, value: bool) -> None:
        if not self._loading:
            self.keepChanged.emit(value)

    def _select_box(self, *_args: object) -> None:
        if self._loading or not self._boxes:
            return
        box = self._boxes[max(0, self.selected_index())]
        for spin, value in zip(self.coordinates, (box.x0 * self._width, box.y0 * self._height,
                (box.x1 - box.x0) * self._width, (box.y1 - box.y0) * self._height)):
            spin.setValue(value)
        self.selectionChanged.emit(self.selected_index())

    def _select_divider(self, *_args: object) -> None:
        if self._loading or self.divider.currentIndex() < 0:
            return
        first, _ = self.divider.currentData()
        box = self._boxes[first]
        self.position.setValue(box.x1 * self._width if self._axis == Axis.LEFT_RIGHT else box.y1 * self._height)

    def _box_commit(self, index: int) -> None:
        if self._loading or not self._boxes:
            return
        box = self._boxes[max(0, self.selected_index())]
        values = [box.x0 * self._width, box.y0 * self._height,
                  (box.x1 - box.x0) * self._width, (box.y1 - box.y0) * self._height]
        proposed = self.coordinates[index].value()
        if proposed == round(values[index], self.coordinates[index].decimals()):
            return
        if index < 2:
            delta = proposed - values[index]
            self.moveRequested.emit(delta / self._width if index == 0 else 0,
                                    delta / self._height if index == 1 else 0,
                                    self.selected_index() < 0)
            return
        self._resize_boxes(index, proposed, relative=False)

    def _resize_boxes(self, index: int, value: float, *, relative: bool) -> None:
        boxes = list(self._boxes)
        selected = self.selected_index()
        for i, box in enumerate(boxes):
            if selected >= 0 and i != selected:
                continue
            if index == 2:
                width = box.x1 - box.x0 + value / self._width if relative else value / self._width
                boxes[i] = Box(box.x0, box.y0, box.x0 + width, box.y1)
            else:
                height = box.y1 - box.y0 + value / self._height if relative else value / self._height
                boxes[i] = Box(box.x0, box.y0, box.x1, box.y0 + height)
        self.cropsEdited.emit(tuple(boxes))

    def _nudge_box(self, index: int, delta: float) -> None:
        if not self._boxes:
            return
        if index >= 2:
            self._resize_boxes(index, delta, relative=True)
            return
        dx, dy = (delta / self._width, 0) if index == 0 else (0, delta / self._height)
        self.moveRequested.emit(dx, dy, self.selected_index() < 0)

    def _divider_commit(self) -> None:
        if not self._loading and self.divider.currentIndex() >= 0:
            dimension = self._width if self._axis == Axis.LEFT_RIGHT else self._height
            first, _ = self.divider.currentData()
            current = self._boxes[first].x1 if self._axis == Axis.LEFT_RIGHT else self._boxes[first].y1
            if self.position.value() == round(current * dimension, self.position.decimals()):
                return
            self.dividerEdited.emit(self.divider.currentData(), self.position.value() / dimension)

    def _nudge_divider(self, delta: float) -> None:
        if self.divider.currentIndex() >= 0:
            dimension = self._width if self._axis == Axis.LEFT_RIGHT else self._height
            self.dividerEdited.emit(self.divider.currentData(), (self.position.value() + delta) / dimension)
