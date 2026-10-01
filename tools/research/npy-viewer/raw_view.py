"""Virtual, read-only array spreadsheet with exact source-value formatting.

8-bit integer image data optionally uses channel-ordered hexadecimal labels.
Requirements: PySide6 and numpy. Usage: embedded as the Raw data tab.
"""

from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets

from .data_model import Array, Frame, ImageMember, ImageSource

MAX_COPY_CELLS = 1_000_000
DEFAULT_COLUMN_WIDTH = 48
MIN_COLUMN_WIDTH = 16
MAX_COLUMN_WIDTH = 1024
HEX_DIGITS_PER_BYTE = 2


class ArrayTableModel(QtCore.QAbstractTableModel):
    """Read only requested cells, retaining the original NumPy buffer and dtype.

    Args:
        parent: Qt owner. No per-cell Qt items or formatted array copies are made.
    """

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.array: Array | None = None
        self.row_start = 0
        self.column_start = 0
        self.column_labels: tuple[str, ...] = ()
        self.hexadecimal = False
        self.hex_available = False
        self.hex_description = ""
        self._hex_digits = HEX_DIGITS_PER_BYTE
        self._hex_channels: tuple[int, ...] = ()

    def set_frame(self, frame: Frame, labels: tuple[str, ...] = (), *, image_source: ImageSource | None = None) -> None:
        """Reset the table to unfiltered, unclamped source cells for a frame.

        Args:
            frame: Prepared selection retaining its raw, possibly complex values.
            labels: Optional source column headers for a CSV matrix.
            image_source: Original image metadata enabling 8-bit integer hex display.
                Gray+alpha color views pack gray and alpha without repeating RGB.
        """
        self.beginResetModel()
        raw = frame.raw if frame.raw is not None else frame.scalar
        self.array = raw[:, None] if raw.ndim == 1 else raw
        coordinates = frame.point_coordinates is not None or frame.x_values is not None
        self.row_start = frame.x_start if raw.ndim == 1 or coordinates else frame.y_start
        self.column_start = 0 if raw.ndim == 1 or coordinates else frame.x_start
        self.column_labels = (("X", "Y", "Z") if frame.point_coordinates is not None else
                              ("X", "Y") if frame.x_values is not None else labels)
        self.hex_available = (image_source is not None and self.array.dtype.kind in "bu"
                              and self.array.dtype.itemsize == 1)
        self.hexadecimal &= self.hex_available
        self._hex_digits = max(HEX_DIGITS_PER_BYTE, self.array.dtype.itemsize * HEX_DIGITS_PER_BYTE)
        self._hex_channels = ()
        self.hex_description = "Hex display is available only for 8-bit integer image values; floating-point and 16-bit data remain decimal."
        if self.hex_available:
            letters = "V"
            channel_text = "single channel"
            if self.array.ndim == 3:
                count = self.array.shape[-1]
                self._hex_channels = tuple(range(count))
                if image_source is not None and ImageMember.MONO in image_source.channels and count == 4:
                    self._hex_channels = (0, 3)
                    letters, channel_text = "GA", "gray then alpha; repeated RGB components omitted"
                elif count == 2:
                    letters, channel_text = "GA", "gray then alpha"
                else:
                    letters = "RGBA"[:count]
                    channel_text = "RGB; alpha last" if count == 4 else "RGB"
            pattern = f"#{''.join(letter * self._hex_digits for letter in letters)}"
            self.hex_description = f"{pattern}: {channel_text}; {self.array.dtype.itemsize * 8}-bit values, no scaling."
        self.endResetModel()

    def set_hexadecimal(self, enabled: bool) -> None:
        """Toggle image cell formatting without resetting the data or selection.

        Args:
            enabled: Use uppercase, fixed-width hex for 8-bit integer images.
                Floating-point, 16-bit and non-image arrays remain decimal.

        Side effects:
            Notifies views that display and tooltip text changed; values and
            full-precision buffers are retained without conversion or copying.
        """
        enabled = enabled and self.hex_available
        if enabled == self.hexadecimal:
            return
        self.hexadecimal = enabled
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1),
                                  [QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.ToolTipRole])

    def rowCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
        """Return source rows for the root; table cells have no children."""
        return 0 if parent.isValid() or self.array is None else self.array.shape[0]

    def columnCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
        """Return source columns without allocating column items."""
        return 0 if parent.isValid() or self.array is None else self.array.shape[1]

    def data(self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
             role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> str | int | None:
        """Format a source value or pixel tuple, optionally as 8-bit image hex."""
        if not index.isValid() or self.array is None:
            return None
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            if self.hexadecimal:
                # The unsigned/bool dtype guard makes item() return Python int/bool.
                if self._hex_channels:
                    channels = (cast(int, self.array.item(index.row(), index.column(), channel))
                                for channel in self._hex_channels)
                    return f"#{''.join(f'{channel:0{self._hex_digits}X}' for channel in channels)}"
                scalar = cast(int, self.array.item(index.row(), index.column()))
                return f"#{scalar:0{self._hex_digits}X}"
            value = self.array[index.row(), index.column()]
            if self.array.ndim == 3:
                return f"({', '.join(str(channel) for channel in value)})"
            return str(value)
        return None

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation,
                   role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> str | None:
        """Show zero-based original indices and available column labels."""
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == QtCore.Qt.Orientation.Vertical:
            return str(self.row_start + section)
        source_column = self.column_start + section
        if source_column < len(self.column_labels):
            return f"{source_column}: {self.column_labels[source_column]}"
        return str(source_column)


class RawDataView(QtWidgets.QWidget):
    """Scrollable source table with index navigation and TSV clipboard copying.

    Args:
        parent: Optional owner. Data cannot be edited through this view.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.note = QtWidgets.QLabel("No data loaded")
        self.note.setWordWrap(True)
        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(self.note, 1)
        self.hex_checkbox = QtWidgets.QCheckBox("Hexadecimal")
        self.hex_checkbox.setVisible(False)
        self.hex_checkbox.toggled.connect(self._hexadecimal_changed)
        heading.addWidget(self.hex_checkbox)
        layout.addLayout(heading)
        self.model = ArrayTableModel(self)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setMinimumSectionSize(MIN_COLUMN_WIDTH)
        self.table.horizontalHeader().setDefaultSectionSize(DEFAULT_COLUMN_WIDTH)
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.setWordWrap(False)
        layout.addWidget(self.table)
        bar = QtWidgets.QHBoxLayout()
        self.row = QtWidgets.QSpinBox()
        self.column = QtWidgets.QSpinBox()
        for label, widget in (("Row", self.row), ("Column", self.column)):
            bar.addWidget(QtWidgets.QLabel(label))
            bar.addWidget(widget)
        go = QtWidgets.QPushButton("Go to cell")
        go.clicked.connect(self._go_to)
        bar.addWidget(go)
        copy = QtWidgets.QPushButton("Copy selection")
        copy.clicked.connect(self._copy)
        bar.addWidget(copy)
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        bar.addWidget(separator)
        bar.addWidget(QtWidgets.QLabel("Column width"))
        self.column_width = QtWidgets.QSpinBox()
        self.column_width.setRange(MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH)
        self.column_width.setValue(DEFAULT_COLUMN_WIDTH)
        self.column_width.setSuffix(" px")
        self.column_width.setKeyboardTracking(False)
        bar.addWidget(self.column_width)
        self.width_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.width_slider.setRange(MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH)
        self.width_slider.setValue(DEFAULT_COLUMN_WIDTH)
        self.width_slider.valueChanged.connect(self.column_width.setValue)
        self.column_width.valueChanged.connect(self.width_slider.setValue)
        self.column_width.valueChanged.connect(self._set_column_width)
        bar.addWidget(self.width_slider, 1)
        layout.addLayout(bar)
        action = QtGui.QAction("Copy selection", self.table)
        action.setShortcut(QtGui.QKeySequence.StandardKey.Copy)
        action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(self._copy)
        self.table.addAction(action)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.ActionsContextMenu)

    def set_frame(self, frame: Frame, labels: tuple[str, ...] = (), *, image_source: ImageSource | None = None) -> None:
        """Display raw selected cells with an optional image-only hex checkbox.

        Args:
            frame: Prepared data preserving dtype, gaps and source indices.
            labels: Optional CSV column names.
            image_source: Image channel metadata; None hides the hex checkbox.
                Floating-point and 16-bit image matrices show a disabled,
                unchecked checkbox.
        """
        self.model.set_frame(frame, labels, image_source=image_source)
        self.hex_checkbox.setVisible(image_source is not None)
        self.hex_checkbox.setEnabled(self.model.hex_available)
        self.hex_checkbox.setToolTip(self.model.hex_description)
        with QtCore.QSignalBlocker(self.hex_checkbox):
            self.hex_checkbox.setChecked(self.model.hexadecimal)
        self._update_note()
        array = self.model.array
        if array is None:
            return
        self.row.setRange(self.model.row_start, self.model.row_start + self.model.rowCount() - 1)
        self.column.setRange(self.model.column_start, self.model.column_start + self.model.columnCount() - 1)
        self._set_column_width(self.column_width.value())

    def _hexadecimal_changed(self) -> None:
        self.model.set_hexadecimal(self.hex_checkbox.isChecked())
        self._update_note()

    def _update_note(self) -> None:
        array = self.model.array
        if array is None:
            return
        text = (f"Raw selected data | Shape: {array.shape} | Dtype: {array.dtype}\n"
                "Read-only; before value filtering, clamping and complex-component conversion. "
                "Ctrl+C copies the displayed cell text.")
        if self.model.hexadecimal:
            text = f"{text}\nHex: {self.model.hex_description}"
        self.note.setText(text)

    def _set_column_width(self, width: int) -> None:
        header = self.table.horizontalHeader()
        header.setDefaultSectionSize(width)
        # Also reset any columns that the user individually resized by dragging.
        for column in range(self.model.columnCount()):
            if header.sectionSize(column) != width:
                header.resizeSection(column, width)

    def _go_to(self) -> None:
        index = self.model.index(self.row.value() - self.model.row_start, self.column.value() - self.model.column_start)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)

    def _copy(self) -> None:
        selection = self.table.selectionModel()
        if selection is None or not selection.hasSelection():
            return
        selected_ranges = selection.selection()
        # Use Qt's typed accessors; PySide6 stubs do not declare an iterator.
        ranges = [selected_ranges.at(index) for index in range(selected_ranges.count())]
        top, bottom = min(r.top() for r in ranges), max(r.bottom() for r in ranges)
        left, right = min(r.left() for r in ranges), max(r.right() for r in ranges)
        if (bottom - top + 1) * (right - left + 1) > MAX_COPY_CELLS:
            QtWidgets.QMessageBox.information(self, "Selection too large", f"Select at most {MAX_COPY_CELLS:,} cells to copy.")
            return
        rows: list[str] = []
        for row in range(top, bottom + 1):
            cells: list[str] = []
            for column in range(left, right + 1):
                index = self.model.index(row, column)
                cells.append(str(self.model.data(index)) if selection.isSelected(index) else "")
            rows.append("\t".join(cells))
        QtWidgets.QApplication.clipboard().setText("\n".join(rows))
