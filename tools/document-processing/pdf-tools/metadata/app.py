"""Qt editor for document properties, the XMP packet and export settings."""

from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from utils import *
from utils.qt_styles import set_button_style
from utils.qt_widgets import configure_qt_application, monospace_ui_font
from ..common.file_actions import choose_pdf_output
from ..common.file_drop import FileDropFilter
from ..common.jobs import JobRunner
from ..common.preferences import choose_open_file, remember_directory
from ..common.protocol import Json
from ..common.task_buttons import TaskButtons
from .engine import Property
from .titles import TitleDialog
from .xmp import FIELDS, Packet
from .ui_mainwindow import Ui_MetadataWindow


class MetadataWindow(QtWidgets.QWidget, Ui_MetadataWindow):
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
        self.setupUi(self)
        self.open_button.clicked.connect(self._choose)
        self.info.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.properties.edit_titles.clicked.connect(self._edit_titles)
        self.xml.setFont(monospace_ui_font())
        self.xml.setPlaceholderText("Enter an XMP packet in RDF/XML.")
        self.tabs.setTabToolTip(1, "Edit any XMP property, including translations, arrays and custom namespaces. "
                               "Changed common fields and output identification are applied after these edits.")
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        task_buttons = TaskButtons(self.runner, self, with_progress=True)
        self.task_slot.addWidget(task_buttons)
        self.setTabOrder(task_buttons.stop_button, self.save)
        set_button_style(self.save, "blue")
        self.save.clicked.connect(self._save)
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
