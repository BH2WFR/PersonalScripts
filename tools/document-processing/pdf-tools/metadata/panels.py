"""Document property and output settings panels for the metadata editor."""

from pymupdf import mupdf
from PySide6 import QtCore, QtWidgets
from utils import PdfProtection
from ..common.protocol import Json
from .engine import Property
from .xmp import FIELDS, PROFILES
from .ui_output_options import Ui_OutputOptions
from .ui_properties import Ui_Properties


class Properties(QtWidgets.QWidget, Ui_Properties):
    """Edit the Info dictionary. Keep original row identity across key renames."""

    changed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.fields = {
            "Title": self.title_field,
            "Author": self.author_field,
            "Subject": self.subject_field,
            "Keywords": self.keywords_field,
            "Creator": self.creator_field,
            "Producer": self.producer_field,
        }
        for field in self.fields.values():
            field.setMaxLength(2**31 - 1)
            field.textEdited.connect(self.changed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self.changed)
        self.add.clicked.connect(self._add)
        self.remove.clicked.connect(self._remove)

    def append(self, row: Property) -> None:
        """Add an editable row with its original name and PDF value format."""
        index = self.table.rowCount()
        self.table.insertRow(index)
        key = QtWidgets.QTableWidgetItem(row["key"])
        key.setData(QtCore.Qt.ItemDataRole.UserRole, row["original"])
        kind = QtWidgets.QTableWidgetItem("PDF syntax" if row["raw"] else "Text")
        kind.setFlags(kind.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(index, 0, key)
        self.table.setItem(index, 1, kind)
        self.table.setItem(index, 2, QtWidgets.QTableWidgetItem(row["value"]))

    def rows(self) -> list[Property]:
        """Collect the current table in display order."""
        rows: list[Property] = []
        for i in range(self.table.rowCount()):
            key = self._cell(i, 0)
            rows.append(Property(key=key.text(), original=key.data(QtCore.Qt.ItemDataRole.UserRole),
                                 value=self._cell(i, 2).text(), raw=self._cell(i, 1).text() == "PDF syntax"))
        return rows

    def _cell(self, row: int, column: int) -> QtWidgets.QTableWidgetItem:
        item = self.table.item(row, column)
        assert item is not None
        return item

    def _add(self) -> None:
        keys = {row["key"] for row in self.rows()}
        choices = ["", *(name for name in ("CreationDate", "ModDate", "Trapped") if name not in keys)]
        key, accepted = QtWidgets.QInputDialog.getItem(self, "Add property", "Property name", choices, 0, True)
        if not accepted:
            return
        if not key or key in keys or key in FIELDS:
            QtWidgets.QMessageBox.warning(self, "Property name", "Choose a new, nonempty property name.")
            return
        self.append(Property(original="", key=key, value="/Unknown" if key == "Trapped" else "", raw=key == "Trapped"))
        self.table.setCurrentCell(self.table.rowCount() - 1, 2)
        self.table.editItem(self._cell(self.table.currentRow(), 2))

    def _remove(self) -> None:
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.changed.emit()

    def _menu(self, point: QtCore.QPoint) -> None:
        item = self.table.itemAt(point)
        menu = QtWidgets.QMenu()
        menu.addAction("Add property", self._add)
        if item is not None:
            self.table.setCurrentItem(item)
            menu.addAction("Rename", lambda: self.table.editItem(self._cell(item.row(), 0)))
            menu.addAction("Edit value", lambda: self.table.editItem(self._cell(item.row(), 2)))
            kind = self._cell(item.row(), 1)
            target = "Text" if kind.text() == "PDF syntax" else "PDF syntax"
            menu.addAction(f"Use {target.lower()}", lambda: kind.setText(target))
            menu.addAction("Remove", self._remove)
        menu.exec(self.table.viewport().mapToGlobal(point))


class OutputOptions(QtWidgets.QWidget, Ui_OutputOptions):
    """Select archival identification or AES-256 security for the new file."""

    changed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setupUi(self)
        self.marker.addItem("Keep identification from XMP", "keep")
        self.marker.addItem("Remove identification", "remove")
        for profile in PROFILES:
            self.marker.addItem("PDF/A-" + profile, profile)
        self.mode.addItems(["Unprotected", "Restrict permissions", "Require an opening password"])
        self.owner.setToolTip("Required to restrict permissions. Optional when an opening password allows all actions.")
        for field in (self.owner, self.user):
            field.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            field.textEdited.connect(self.changed)
        self.permissions = {
            mupdf.PDF_PERM_PRINT: self.print_pages,
            mupdf.PDF_PERM_PRINT_HQ: self.print_hq,
            mupdf.PDF_PERM_COPY: self.copy_content,
            mupdf.PDF_PERM_ACCESSIBILITY: self.accessible,
            mupdf.PDF_PERM_MODIFY: self.modify,
            mupdf.PDF_PERM_ANNOTATE: self.annotate,
            mupdf.PDF_PERM_FORM: self.fill_forms,
            mupdf.PDF_PERM_ASSEMBLE: self.assemble,
        }
        for box in self.permissions.values():
            box.toggled.connect(self.changed)
            box.clicked.connect(self._permissions_edited)
        self.marker.currentIndexChanged.connect(self.changed)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._previous_marker = 0
        self._custom_permissions = False
        self.reset()

    def reset(self) -> None:
        """Clear all previous passwords and restore ordinary output defaults."""
        self.mode.setCurrentIndex(0)
        self.marker.setCurrentIndex(0)
        self._previous_marker = 0
        self.owner.clear()
        self.user.clear()
        self._custom_permissions = False
        self._mode_changed()

    def _permissions_edited(self) -> None:
        self._custom_permissions = True

    def _mode_changed(self) -> None:
        mode = self.mode.currentIndex()
        if mode and self.marker.isEnabledTo(self):
            self._previous_marker = self.marker.currentIndex()
            self.marker.setCurrentIndex(1)
        elif not mode and not self.marker.isEnabledTo(self):
            self.marker.setCurrentIndex(self._previous_marker)
        self.marker.setEnabled(not mode)
        self.owner.setEnabled(bool(mode))
        self.group.setEnabled(bool(mode))
        self.user.setEnabled(mode == 2)
        if not self._custom_permissions:
            for flag, box in self.permissions.items():
                box.setChecked(mode == 2 or flag in (mupdf.PDF_PERM_PRINT, mupdf.PDF_PERM_ACCESSIBILITY))
        self.changed.emit()

    def options(self) -> dict[str, Json]:
        """Validate requested passwords before selecting a destination."""
        mode = self.mode.currentIndex()
        if not mode:
            return {"marker": self.marker.currentData(), "protect": False}
        user = self.user.text() if mode == 2 else ""
        if mode == 2 and not user:
            raise ValueError("Enter an opening password.")
        allowed = [flag for flag, box in self.permissions.items() if box.isChecked()]
        permissions = -1 if len(allowed) == len(self.permissions) else sum(allowed)
        security = PdfProtection(self.owner.text(), user, permissions)
        return {"marker": "remove", "protect": True, "owner": security.owner_password, "user": user,
                "permissions": security.permissions}
