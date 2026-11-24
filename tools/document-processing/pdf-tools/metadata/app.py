"""Qt editor for document properties, the XMP packet and export settings."""

from pathlib import Path
from typing import cast

from pymupdf import mupdf
from PySide6 import QtCore, QtGui, QtWidgets
from utils import *
from utils.qt_widgets import NoWheelComboBox, configure_qt_application, with_cjk_fallbacks
from ..common.file_actions import choose_pdf_output
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.preferences import choose_open_file, remember_directory
from ..common.protocol import Json
from ..common.task_buttons import TaskButtons
from .engine import Property
from .titles import TitleDialog
from .xmp import FIELDS, PROFILES, Packet


class Properties(QtWidgets.QWidget):
    """Edit the Info dictionary. Keep original row identity across key renames."""

    changed = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        self.fields: dict[str, QtWidgets.QLineEdit] = {}
        for name in FIELDS:
            field = QtWidgets.QLineEdit()
            field.setMaxLength(2**31 - 1)
            field.textEdited.connect(self.changed)
            self.fields[name] = field
            if name == "Title":
                title_row = QtWidgets.QHBoxLayout()
                title_row.addWidget(field)
                self.edit_titles = QtWidgets.QPushButton("Multilingual…")
                title_row.addWidget(self.edit_titles)
                form.addRow(name, title_row)
            else:
                form.addRow(name, field)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(QtWidgets.QLabel("Additional document properties"))
        buttons.addStretch()
        self.add = QtWidgets.QPushButton("Add property")
        self.remove = QtWidgets.QPushButton("Remove")
        buttons.addWidget(self.add)
        buttons.addWidget(self.remove)
        layout.addLayout(buttons)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Property", "Format", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self.changed)
        self.add.clicked.connect(self._add)
        self.remove.clicked.connect(self._remove)
        layout.addWidget(self.table)

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


class OutputOptions(QtWidgets.QWidget):
    """Select archival identification or AES-256 security for the new file."""

    changed = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QFormLayout(self)
        self.marker = NoWheelComboBox()
        self.marker.addItem("Keep identification from XMP", "keep")
        self.marker.addItem("Remove identification", "remove")
        for profile in PROFILES:
            self.marker.addItem("PDF/A-" + profile, profile)
        layout.addRow("PDF/A identification", self.marker)
        note = QtWidgets.QLabel("Writing identification alone does not establish PDF/A conformance.")
        note.setWordWrap(True)
        layout.addRow(note)
        self.mode = NoWheelComboBox()
        self.mode.addItems(["Unprotected", "Restrict permissions", "Require an opening password"])
        layout.addRow("Output security", self.mode)
        self.owner = QtWidgets.QLineEdit()
        self.owner.setToolTip("Required to restrict permissions. Optional when an opening password allows all actions.")
        self.user = QtWidgets.QLineEdit()
        for label, field in (("Owner password", self.owner), ("Opening password", self.user)):
            field.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
            field.textEdited.connect(self.changed)
            layout.addRow(label, field)
        group = QtWidgets.QGroupBox("Allowed actions")
        grid = QtWidgets.QGridLayout(group)
        self.permissions: dict[int, QtWidgets.QCheckBox] = {}
        for i, (name, flag) in enumerate((
            ("Print", mupdf.PDF_PERM_PRINT), ("High-quality printing", mupdf.PDF_PERM_PRINT_HQ),
            ("Copy text and images", mupdf.PDF_PERM_COPY), ("Accessibility", mupdf.PDF_PERM_ACCESSIBILITY),
            ("Modify content", mupdf.PDF_PERM_MODIFY), ("Add annotations", mupdf.PDF_PERM_ANNOTATE),
            ("Fill forms", mupdf.PDF_PERM_FORM), ("Assemble pages", mupdf.PDF_PERM_ASSEMBLE),
        )):
            box = QtWidgets.QCheckBox(name)
            box.toggled.connect(self.changed)
            box.clicked.connect(self._permissions_edited)
            self.permissions[flag] = box
            grid.addWidget(box, i // 2, i % 2)
        self.group = group
        layout.addRow(group)
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


class MetadataWindow(QtWidgets.QWidget):
    """Keep a draft in memory and publish only complete, separately named exports."""

    def __init__(self, entry: Path) -> None:
        super().__init__()
        self.runner = JobRunner(entry, self)
        self.source: Path | None = None
        self.pending: Path | None = None
        self.password = self.pending_password = ""
        self.identity: Json = None
        self.initial: dict[str, str] = {}
        self._dialog_title: str | None = None
        self._keep_plain_title = False
        self.dirty = False
        self.setWindowTitle("PDF Metadata Editor")
        self.resize(760, 600)
        layout = QtWidgets.QVBoxLayout(self)
        self.open_button = QtWidgets.QPushButton("Open PDF…")
        self.open_button.clicked.connect(self._choose)
        self.info = QtWidgets.QLabel("Open a PDF to edit its document properties.")
        self.info.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.info.setWordWrap(True)
        layout.addWidget(self.open_button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.info)
        self.tabs = QtWidgets.QTabWidget()
        self.properties = Properties()
        self.properties.edit_titles.clicked.connect(self._edit_titles)
        self.xml = QtWidgets.QPlainTextEdit()
        fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        self.xml.setFont(with_cjk_fallbacks(fixed_font))
        self.xml.setPlaceholderText("Enter an XMP packet in RDF/XML.")
        self.options = OutputOptions()
        self.tabs.addTab(self.properties, "Document properties")
        self.tabs.addTab(self.xml, "XMP (XML)")
        self.tabs.addTab(self.options, "Output settings")
        self.tabs.setTabToolTip(1, "Edit any XMP property, including translations, arrays and custom namespaces. "
                               "Changed common fields and output identification are applied after these edits.")
        layout.addWidget(self.tabs)
        self.status = QtWidgets.QLabel()
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch()
        footer.addWidget(TaskButtons(self.runner, self, with_progress=True))
        self.save = QtWidgets.QPushButton("Save as…")
        self.save.clicked.connect(self._save)
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.runner.busyChanged.connect(self._enable)
        self.runner.completed.connect(self._reply)
        self.runner.controlStatus.connect(self.status.setText)
        self.runner.progress.connect(lambda message: self.status.setText(str(message.get("stage", ""))))
        self.properties.changed.connect(self._edited)
        self.options.changed.connect(self._edited)
        self.xml.textChanged.connect(self._edited)
        self.drop_filter = FileDropFilter(self, self.open_path, lambda: not self.runner.busy, suffixes=(".pdf",))
        self._enable()

    def _enable(self) -> None:
        self.open_button.setEnabled(not self.runner.busy)
        self.tabs.setEnabled(self.source is not None and not self.runner.busy)
        self.save.setEnabled(self.tabs.isEnabled())

    def _edited(self) -> None:
        self.dirty = True

    def _edit_titles(self) -> None:
        field = self.properties.fields["Title"]
        plain = field.text()
        try:
            packet = Packet(self.xml.toPlainText().strip())
            titles = packet.titles()
            has_property = packet.has_title()
            # Bring a pending ordinary-title edit into the dialog. Seed a first
            # multilingual title from Info, unless the user explicitly removed it.
            baseline = self._dialog_title
            if baseline is None:
                link = plain != self.initial.get("Title", "") or not has_property
            else:
                link = plain != baseline and has_property
            if link:
                if plain:
                    titles["x-default"] = plain
                else:
                    titles.pop("x-default", None)
            dialog = TitleDialog(titles, self, has_property=has_property)
            result = dialog.exec()
            dialog.deleteLater()
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return
            if dialog.titles == titles and not dialog.removed_all:
                return
            if has_property or dialog.titles:
                packet.set_titles(dialog.titles)
                xml = packet.dom.toxml()
                Packet(xml)  # Reject invalid XML characters before changing the draft.
                cursor = self.xml.textCursor()
                cursor.select(QtGui.QTextCursor.SelectionType.Document)
                cursor.insertText(xml)
            default = dialog.titles.get("x-default", "")
            if dialog.removed_all:
                self._keep_plain_title = True
                if default:
                    field.setText(default)
            elif default != titles.get("x-default", ""):
                field.setText(default)
            self._dialog_title = field.text()
            self._edited()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Multilingual titles", str(exc))

    def _discard(self) -> bool:
        yes = QtWidgets.QMessageBox.StandardButton.Yes
        no = QtWidgets.QMessageBox.StandardButton.No
        return not self.dirty or QtWidgets.QMessageBox.question(
            self, "Unsaved changes", "Discard the edits made since the last export?", yes | no, no) == yes

    def _choose(self) -> None:
        selected = choose_open_file(self, "Open PDF", "PDF (*.pdf)")
        if selected:
            self.open_path(Path(selected))

    def open_path(self, path: Path) -> None:
        """Inspect a candidate without discarding the current draft on failure or cancellation."""
        if self.runner.busy or not self._discard():
            return
        self.pending = path.absolute()
        self.pending_password = ""
        self._inspect(False)

    def _inspect(self, unlock: bool) -> None:
        self.status.setText("Opening PDF…")
        self.runner.start({"operation": "inspect", "path": str(self.pending), "password": self.pending_password,
                           "unlock": unlock})

    def _reply(self, reply: dict[str, Json]) -> None:
        kind = reply["kind"]
        if kind == "unlock":
            if QtWidgets.QMessageBox.question(self, "Protected PDF", "Unlock this PDF for editing? "
                    "The output security can be set separately.") == QtWidgets.QMessageBox.StandardButton.Yes:
                self._inspect(True)
                return
        elif kind == "password":
            prompt = "Incorrect password. Try again:" if self.pending_password else "PDF opening password:"
            key, ok = QtWidgets.QInputDialog.getText(self, "Unlock PDF", prompt, QtWidgets.QLineEdit.EchoMode.Password)
            if ok and key:
                self.pending_password = key
                self._inspect(True)
                return
        elif kind == "opened":
            assert self.pending is not None
            self.source = self.pending
            self.password = self.pending_password
            self.identity = reply["identity"]
            self.initial = cast(dict[str, str], reply["common"])
            self._dialog_title = None
            self._keep_plain_title = False
            for name, field in self.properties.fields.items():
                field.setText(self.initial[name])
            self.properties.table.setRowCount(0)
            for row in cast(list[Property], reply["rows"]):
                if row["key"] not in FIELDS or row["raw"]:
                    self.properties.append(row)
            self.xml.setPlainText(str(reply["xml"]))
            self.xml.document().setModified(False)
            self.options.reset()
            self.tabs.setCurrentIndex(0)
            self.dirty = False
            remember_directory(self, "open-pdf", self.source)
            size = Console.format_size(cast(int, reply["size"]))
            security = "Protected input (unlocked)" if reply["protected"] else "Unprotected input"
            self.info.setText(f"{self.source.name}\n{reply['format']}  ·  Pages: {reply['pages']}  ·  {size}"
                              f"  ·  {security}  ·  PDF/A identification: {reply['marker']}")
            self.info.setToolTip(str(self.source))
            self._enable()
        elif kind == "exported":
            self.dirty = False
            self.status.setText(f"Saved to {reply['path']}")
            return
        elif kind == "error":
            QtWidgets.QMessageBox.warning(self, "PDF metadata editor", str(reply["message"]))
        self.pending = None
        self.pending_password = ""
        self.status.setText(str(reply.get("message", "")))

    def _save(self) -> None:
        if self.source is None:
            return
        try:
            options = self.options.options()
            extras = self.properties.rows()
            keys = [row["key"] for row in extras]
            if len(keys) != len(set(keys)) or any(not key for key in keys):
                raise ValueError("Each property needs a distinct, nonempty name.")
            if any(row["key"] in FIELDS and not (row["raw"] and row["key"] == row["original"]) for row in extras):
                raise ValueError("Use the common field above the table for this property.")
            default = self.source.with_name(f"{self.source.stem}_metadata.pdf")
            output = choose_pdf_output(self, self.source, default)
            if output is None:
                return
            changes = {key: field.text() for key, field in self.properties.fields.items()
                       if field.text() != self.initial[key]}
            sync_title = True
            if self._dialog_title is not None:
                plain = self.properties.fields["Title"].text()
                if self._keep_plain_title and plain and not any(row["key"] == "Title" for row in extras):
                    changes["Title"] = plain
                sync_title = plain != self._dialog_title and Packet(self.xml.toPlainText().strip()).has_title()
            self.status.setText("Exporting PDF…")
            self.runner.start({**options, "operation": "export", "path": str(self.source), "password": self.password,
                               "identity": self.identity, "extras": cast(Json, extras), "common": cast(Json, changes),
                               "sync_xmp_title": sync_title,
                               "xml": self.xml.toPlainText() if self.xml.document().isModified() else None,
                               "output": str(output[0]), "overwrite": output[1]})
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Cannot export", str(exc))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.runner.busy:
            self.status.setText("Wait for the current operation or stop the export before closing.")
            event.ignore()
        elif self._discard():
            self.runner.shutdown()
            event.accept()
        else:
            event.ignore()


def main(entry: Path, source: Path | None) -> int:
    """Start the Fusion GUI and optionally inspect a command-line PDF."""
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert isinstance(application, QtWidgets.QApplication)
    configure_qt_application(application)
    window = MetadataWindow(entry)
    window.show()
    if source is not None:
        window.open_path(source)
    return application.exec()
