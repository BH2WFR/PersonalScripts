"""Select archive members or worksheet/text ranges before loading numeric data.

Requirements: PySide6. Usage: shown after background metadata inspection;
the dialog performs no disk I/O and never materializes source arrays.
NPZ imports choose whether display names include the source filename.
"""

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from .import_catalog import ImportCatalog, ImportChoice, ImportMember, SplitAxis
from .table_data import HeaderMode, TableRange
from .ui_import_dialog import Ui_ImportDialog
from .ui_split_array_dialog import Ui_SplitArrayDialog


class ImportDialog(QtWidgets.QDialog, Ui_ImportDialog):
    """Checkbox list with source dimensions and independently editable ranges.

    Args:
        catalog: File metadata and small top-left previews from the worker.
        parent: Owning viewer.

    Side effects:
        Acceptance exposes choices(); cancellation leaves the workspace intact.
    """

    def __init__(self, catalog: ImportCatalog, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.catalog = catalog
        self._current = -1
        self._choices = [ImportChoice(item.key, delimiter=catalog.delimiter) for item in catalog.members]
        self.setModal(True)
        self.resize(780, 690 if catalog.tabular else 400)
        source = self.form_source
        source.setText(str(catalog.path))
        source.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.include_file_prefix.setChecked(True)
        self.include_file_prefix.setVisible(catalog.path.suffix.lower() == ".npz")
        self.select_all.clicked.connect(lambda: self._check_all(True))
        self.select_none.clicked.connect(lambda: self._check_all(False))
        self.members.setRootIsDecorated(False)
        self.members.setColumnCount(4)
        self.members.setHeaderLabels(["Matrix / worksheet", "Rows", "Columns", "Type / status"])
        self.members.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.members.setColumnWidth(1, 80)
        self.members.setColumnWidth(2, 80)
        self.members.setColumnWidth(3, 220)
        for index, member in enumerate(catalog.members):
            rows = str(member.shape[0]) if member.shape else "—"
            columns = str(member.shape[1]) if len(member.shape) > 1 else "1" if member.shape else "—"
            status = f"Unsupported: {member.error}" if member.error else f"{member.kind}{' · 1D' if len(member.shape) == 1 else ''}"
            if not member.error and len(member.shape) == 3:
                status = f"{member.kind} · {member.shape} · split required"
            elif not member.error and (member.kind == "char" or member.kind.lstrip("<>=|").startswith(("U", "S"))):
                status = f"{member.kind} · Raw data only"
            item = QtWidgets.QTreeWidgetItem([member.label, rows, columns, status])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, index)
            item.setToolTip(3, status)
            item.setToolTip(1, f"Original shape: {member.shape}")
            if member.error:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled)
            else:
                checked = catalog.preferred_key is None or member.key == catalog.preferred_key
                item.setCheckState(0, QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
            self.members.addTopLevelItem(item)
        for field in (self.start_row, self.start_column, self.end_row, self.end_column):
            field.setMaximum(2_147_483_647)
            field.setKeyboardTracking(False)
        for field in (self.start_row, self.start_column):
            field.setMinimum(1)
        for field in (self.end_row, self.end_column):
            field.setSpecialValueText("Last")
        for mode in HeaderMode:
            self.header.addItem(mode.value, mode)
        for label, value in (("Automatic", None), ("Comma", ","), ("Semicolon", ";"), ("Tab", "\t")):
            self.delimiter.addItem(label, value)
        self.form.setRowVisible(self.delimiter, catalog.text)
        self.range_box.setVisible(catalog.tabular)
        self.preview.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setDefaultSectionSize(78)
        self.preview_box.setVisible(catalog.tabular)
        self.note.setText("Each worksheet has its own range. Dimensions include headings/notes and may include formatted empty cells. "
                    "Only checked items are loaded. Excel formulas need saved numeric results. "
                    "For CSV/TXT, row numbers count parsed records (including blanks); columns depend on the selected delimiter."
                    if catalog.tabular else "Only checked matrices are loaded. Unsupported members are disabled; hover over the status for details.")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.members.currentItemChanged.connect(self._current_changed)
        self.members.itemChanged.connect(self._update_open)
        initial = next((index for index, member in enumerate(catalog.members)
                        if not member.error and (catalog.preferred_key is None or member.key == catalog.preferred_key)), 0)
        initial_item = self.members.topLevelItem(initial)
        if initial_item is not None:
            self.members.setCurrentItem(initial_item)
        self._update_open()

    def _store_current(self) -> None:
        if self._current < 0 or not self.catalog.tabular:
            return
        self._choices[self._current] = ImportChoice(
            self.catalog.members[self._current].key,
            TableRange(self.start_row.value(), self.start_column.value(), self.end_row.value() or None, self.end_column.value() or None),
            HeaderMode(self.header.currentData()), self.delimiter.currentData() if self.catalog.text else None)

    def _current_changed(self, current: QtWidgets.QTreeWidgetItem | None, previous: QtWidgets.QTreeWidgetItem | None) -> None:
        self._store_current()
        self._current = int(current.data(0, QtCore.Qt.ItemDataRole.UserRole)) if current is not None else -1
        if self._current < 0 or not self.catalog.tabular:
            return
        choice = self._choices[self._current]
        self.start_row.setValue(choice.region.row_start)
        self.start_column.setValue(choice.region.column_start)
        self.end_row.setValue(choice.region.row_end or 0)
        self.end_column.setValue(choice.region.column_end or 0)
        self.header.setCurrentIndex(self.header.findData(choice.header))
        self.delimiter.setCurrentIndex(self.delimiter.findData(choice.delimiter))
        rows = self.catalog.members[self._current].preview
        self.preview.setRowCount(len(rows))
        self.preview.setColumnCount(max((len(row) for row in rows), default=0))
        self.preview.clearContents()
        for y, row in enumerate(rows):
            for x, value in enumerate(row):
                self.preview.setItem(y, x, QtWidgets.QTableWidgetItem(value))

    def _check_all(self, checked: bool) -> None:
        for index, member in enumerate(self.catalog.members):
            item = self.members.topLevelItem(index)
            if item is not None and not member.error:
                item.setCheckState(0, QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)

    def _update_open(self) -> None:
        button = self.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Open)
        assert button is not None
        button.setEnabled(any((item := self.members.topLevelItem(index)) is not None
                             and item.checkState(0) == QtCore.Qt.CheckState.Checked
                             for index in range(self.members.topLevelItemCount())))

    def choices(self) -> tuple[ImportChoice, ...]:
        """Return checked source snapshots with their individually stored ranges."""
        self._store_current()
        prefix = self.catalog.path.suffix.lower() != ".npz" or self.include_file_prefix.isChecked()
        return tuple(replace(choice, include_file_prefix=prefix) for index, choice in enumerate(self._choices)
                     if (item := self.members.topLevelItem(index)) is not None
                     and item.checkState(0) == QtCore.Qt.CheckState.Checked)

    def accept(self) -> None:
        """Validate each checked range before closing; invalid input stays editable."""
        try:
            choices = self.choices()
            if not choices:
                raise ValueError("Select at least one matrix or worksheet.")
            for choice in choices:
                choice.region.validate()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid input range", str(exc))
            return
        super().accept()


class SplitArrayDialog(QtWidgets.QDialog, Ui_SplitArrayDialog):
    """Choose the channel axis of a numeric 3D array, or skip that member.

    Args:
        source: Source filename for identification.
        member: Metadata for one nonempty numeric rank-3 array.
        parent: Owning workspace; no file access occurs in this dialog.

    Acceptance exposes axis(); Escape and window close skip only this member.
    The smallest dimension is suggested, preferring the last axis
    on ties. An explicit split/skip can apply to later arrays with the same
    length on the chosen axis, within the current import only.
    """

    def __init__(self, source: str, member: ImportMember, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.skipped_explicitly = False
        if len(member.shape) != 3 or any(size <= 0 for size in member.shape):
            raise ValueError("Channel splitting requires a nonempty 3D array.")
        self.setModal(True)
        label = self.form_label
        label.setText(f"{source}\n{member.label}\nShape: {member.shape} · {member.kind}")
        label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        for axis in SplitAxis:
            rows, columns = tuple(size for index, size in enumerate(member.shape) if index != axis)
            self.channel_axis.addItem(f"Axis {axis.value}: {member.shape[axis]} channels → {rows} × {columns} each", axis)
        default = min(SplitAxis, key=lambda axis: (member.shape[axis], -axis.value))
        self.channel_axis.setCurrentIndex(int(default))

        def update_match_description() -> None:
            axis = self.axis()
            self.match_description.setText(
                f"Matches 3D arrays where Axis {axis.value} has {member.shape[axis]} elements.")

        self.channel_axis.currentIndexChanged.connect(update_match_description)
        update_match_description()
        buttons = self.form_buttons
        self.split_button = buttons.addButton("Split and open", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.skip_button = buttons.addButton("Don't open", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        self.skip_button.clicked.connect(self._skip)

    def _skip(self) -> None:
        """Distinguish an explicit batch skip from Escape or window close."""
        self.skipped_explicitly = True
        self.reject()

    def axis(self) -> SplitAxis:
        """Return the chosen zero-based channel axis without decoding arrays."""
        return SplitAxis(self.channel_axis.currentIndex())
