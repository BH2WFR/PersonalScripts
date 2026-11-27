"""PySide6/Fusion editor for confirmed Windows registry key remapping.

Launch ../keyboard-remapper.py. Constructing widgets reads via the supplied backend
but never writes. Dragging reorders the draft; the hex view shows exact pending
bytes. Key capture is limited to a visible focused dialog.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import datetime

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_styles import set_text_style
from utils.qt_widgets import monospace_ui_font
from utils import *

from .catalog import key_label
from .models import Mapping, Snapshot, MAX_BYTES, encode_map, hex_view, parse_backup, validate_mappings
from .registry import RegistryBackend, apply_snapshot, save_backup
from .ui_mainwindow import Ui_RemapWindow
from .ui_mapping import Ui_MappingDialog
from .widgets import KeyPicker as KeyPicker, MappingTable as MappingTable

RestartEditor = Callable[[Snapshot, Snapshot], None]


class MappingDialog(QtWidgets.QDialog, Ui_MappingDialog):
    """Choose a source and destination via dropdown, raw scan word or capture."""

    def __init__(self, row: Mapping | None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.mapping: Mapping | None = None
        self.setupUi(self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        if row is not None:
            self.setWindowTitle("Edit mapping")
            self.source.set_code(row.source)
            self.target.set_code(row.target)

    def accept(self) -> None:
        """Validate input before committing the mapping to the parent draft."""
        try:
            row = Mapping(self.source.code(), self.target.code())
            if row.source == row.target:
                raise ValueError("Source and target are identical; remove the mapping instead.")
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid mapping", str(exc))
            return
        self.mapping = row
        super().accept()


class RemapWindow(QtWidgets.QMainWindow, Ui_RemapWindow):
    """Edit a saved snapshot without writing until the user confirms Apply.

    Args:
        backend: Only registry access boundary; tests supply an in-memory store.
        restart_editor: Open an elevated editor with expected and desired states.
        handoff: Optional validated draft passed from a non-elevated editor.
        read_only: Disable writes and elevation, even when already an administrator.
    """

    def __init__(self, backend: RegistryBackend, restart_editor: RestartEditor,
                 handoff: tuple[Snapshot, Snapshot] | None = None, *, read_only: bool = False) -> None:
        super().__init__()
        self.backend = backend
        self.restart_editor = restart_editor
        self.read_only = read_only
        self.baseline: Snapshot | None = None
        self.draft = Snapshot(None)
        self.rows: tuple[Mapping, ...] = ()
        self.restart_required = False
        self.setupUi(self)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._edit)
        self.table.move_requested.connect(self._move_row)
        self.hex_text.setFont(monospace_ui_font())
        self.hex_panel.hide()
        self.hex_toggle.toggled.connect(self._toggle_hex)
        self.copy_hex_button.clicked.connect(self._copy_hex)
        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.remove_button.clicked.connect(self._remove)
        self.clear_button.clicked.connect(self._clear)
        self.reload_button.clicked.connect(self._reload_clicked)
        self.backup_button.clicked.connect(self._backup)
        self.restore_button.clicked.connect(self._restore)
        self.preview_button.clicked.connect(self._preview)
        self.apply_button.clicked.connect(self._apply)
        set_text_style(self.notice, "gray")
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.reload()
        if handoff is not None and self.baseline is not None:
            expected, desired = handoff
            self.baseline = expected
            self.set_draft(desired)
            self.status.setText("Administrator draft loaded. Review it and click Write to registry again. "
                                "External changes will be checked before writing.")

    @property
    def dirty(self) -> bool:
        """Whether the draft differs byte-for-byte from the loaded saved state."""
        return self.baseline is not None and self.draft != self.baseline

    def _update_actions(self) -> None:
        editable = self.baseline is not None
        self.table.setDragEnabled(editable and len(self.rows) > 1)
        self.copy_hex_button.setEnabled(editable and self.draft.data is not None)
        selected = self.table.currentRow() >= 0
        self.add_button.setEnabled(editable)
        self.edit_button.setEnabled(editable and selected)
        self.remove_button.setEnabled(editable and selected)
        self.clear_button.setEnabled(editable and self.draft.data is not None)
        self.backup_button.setEnabled(editable)
        self.restore_button.setEnabled(editable)
        self.preview_button.setEnabled(editable)
        self.apply_button.setEnabled(editable and self.dirty and not self.read_only)

    def set_draft(self, snapshot: Snapshot) -> None:
        """Replace the in-memory draft and repaint, without accessing the registry."""
        self.draft = snapshot
        self.rows = snapshot.rows
        self.hex_text.setPlainText(hex_view(snapshot))
        self.table.setRowCount(len(self.rows))
        old = {row.source: row.target for row in self.baseline.rows} if self.baseline else {}
        for index, row in enumerate(self.rows):
            state = "Saved" if old.get(row.source) == row.target else ("Changed" if row.source in old else "Added")
            for column, text in enumerate((key_label(row.source), key_label(row.target), state)):
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
        self.status.setText(f"{len(self.rows)} mappings | {'Unsaved changes' if self.dirty else 'Saved state loaded'} | "
                            f"{'Administrator' if System.is_elevated() else 'Standard user; elevation only when writing'}"
                            f"{' | READ-ONLY MODE: writing disabled' if self.read_only else ''}"
                            f"{' | Restart Windows to activate saved changes' if self.restart_required else ''}")
        self._update_actions()
        self.setWindowTitle(f"Keyboard Remapper{' *' if self.dirty else ''}")

    def reload(self) -> None:
        """Read and validate current saved state; block editing on any read error."""
        try:
            snapshot = self.backend.read()
        except (OSError, ValueError) as exc:
            self.baseline = None
            self.hex_text.setPlainText("Registry state unavailable. No valid final bytes to preview.")
            self.status.setText(f"Cannot load registry: {exc} No registry changes are allowed.")
            self._update_actions()
            return
        self.baseline = snapshot
        self.set_draft(snapshot)

    def _discard_allowed(self) -> bool:
        return not self.dirty or QtWidgets.QMessageBox.question(
            self, "Discard draft?", "Discard unsaved changes?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No) == QtWidgets.QMessageBox.StandardButton.Yes

    def _reload_clicked(self) -> None:
        if self._discard_allowed():
            self.reload()

    def _replace_rows(self, rows: tuple[Mapping, ...]) -> None:
        validate_mappings(rows)
        self.set_draft(Snapshot(encode_map(rows) if rows else None))

    def _move_row(self, source: int, insertion: int) -> None:
        """Move one draft row to a pre-removal slot, preserving row identity."""
        if self.baseline is None or not 0 <= source < len(self.rows) or not 0 <= insertion <= len(self.rows):
            return
        destination = insertion - int(insertion > source)
        if destination == source:
            return
        rows = list(self.rows)
        rows.insert(destination, rows.pop(source))
        self._replace_rows(tuple(rows))
        self.table.selectRow(destination)
        item = self.table.item(destination, 0)
        if item is not None:
            self.table.scrollToItem(item)

    def _toggle_hex(self, expanded: bool) -> None:
        self.hex_panel.setVisible(expanded)
        self.hex_toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow)

    def _copy_hex(self) -> None:
        """Copy exact pending bytes, without offsets or labels, on explicit click."""
        if self.baseline is not None and self.draft.data is not None:
            QtWidgets.QApplication.clipboard().setText(self.draft.data.hex(" ").upper())

    def _add(self) -> None:
        dialog = MappingDialog(None, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.mapping is not None:
            try:
                self._replace_rows((*self.rows, dialog.mapping))
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Cannot add mapping", str(exc))

    def _edit(self) -> None:
        index = self.table.currentRow()
        if self.baseline is None or index < 0:
            return
        dialog = MappingDialog(self.rows[index], self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.mapping is not None:
            try:
                self._replace_rows((*self.rows[:index], dialog.mapping, *self.rows[index + 1:]))
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Cannot edit mapping", str(exc))

    def _remove(self) -> None:
        index = self.table.currentRow()
        if index >= 0:
            self._replace_rows((*self.rows[:index], *self.rows[index + 1:]))

    def _clear(self) -> None:
        if QtWidgets.QMessageBox.question(
            self, "Clear draft?", "Remove all mappings from the draft? Nothing is written until Apply.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No) == QtWidgets.QMessageBox.StandardButton.Yes:
            self.set_draft(Snapshot(None))

    def _backup_path(self) -> Path | None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        name, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save a NEW backup file (existing files will not be overwritten)",
            f"keyboard-map-{stamp}.json", "Keyboard map backup (*.json)")
        return Path(name) if name else None

    def _backup(self) -> None:
        path = self._backup_path()
        if path is None:
            return
        try:
            save_backup(path, self.backend.read())
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, "Backup failed", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Backup saved", f"Saved current registry state, not the draft:\n{path}")

    def _restore(self) -> None:
        if not self._discard_allowed():
            return
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load a keyboard map backup", "", "Keyboard map backup (*.json)")
        if not name:
            return
        try:
            with Path(name).open("r", encoding="utf-8") as stream:
                snapshot = parse_backup(stream.read(MAX_BYTES * 3 + 1))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, "Invalid backup", str(exc))
            return
        self.set_draft(snapshot)
        self.status.setText("Backup loaded into the draft only. Review changes and explicitly write to restore it.")

    def changes(self) -> str:
        """Return a reviewable diff against the original loaded state, with scan words."""
        if self.baseline is None:
            return "Registry state unavailable."
        old = {row.source: row.target for row in self.baseline.rows}
        new = {row.source: row.target for row in self.rows}
        lines: list[str] = []
        for source in sorted(old.keys() | new.keys()):
            if source not in new:
                lines.append(f"REMOVE: {key_label(source)} -> {key_label(old[source])}")
            elif source not in old:
                lines.append(f"ADD: {key_label(source)} -> {key_label(new[source])}")
            elif old[source] != new[source]:
                lines.append(f"CHANGE: {key_label(source)}\n  {key_label(old[source])} -> {key_label(new[source])}")
        if not lines:
            lines.append("Only stored order / value presence differs." if self.dirty else "No changes.")
        if self.draft.data is None:
            lines.append("The Scancode Map value will be removed; the parent key remains untouched.")
        return "\n".join(lines)

    def _review(self, confirm: bool) -> bool | None:
        """Return the backup choice on Save, or None for cancellation/preview."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Review registry changes")
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning if confirm else QtWidgets.QMessageBox.Icon.Information)
        box.setText("Changes affect all users and keyboards, including the sign-in screen.\n"
                    "Check that you can still type your password. Restart Windows after saving.\n"
                    "Unknown, special and language scan codes may not be remappable on your hardware.")
        box.setDetailedText(self.changes())
        box.setInformativeText("Expand Show Details to review every change.")
        backup = QtWidgets.QCheckBox("Back up the current registry state before saving")
        backup.setChecked(True)
        if confirm:
            box.setCheckBox(backup)
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        else:
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        if box.exec() == QtWidgets.QMessageBox.StandardButton.Save:
            return backup.isChecked()
        return None

    def _preview(self) -> None:
        self._review(False)

    def _apply(self) -> None:
        if self.read_only or self.baseline is None or not self.dirty:
            return
        backup_requested = self._review(True)
        if backup_requested is None:
            return
        if not System.is_elevated():
            try:
                self.restart_editor(self.baseline, self.draft)
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.critical(self, "Cannot open administrator editor", str(exc))
                return
            QtWidgets.QMessageBox.information(
                self, "Administrator editor requested",
                "Approve the elevation prompt, then review and click Write to registry in the new window.\n"
                "Nothing has been written by this window. If elevation is cancelled, your draft remains here.\n"
                "After saving there, reload this window to see the result.")
            return
        path = self._backup_path() if backup_requested else None
        if backup_requested and path is None:
            return
        try:
            changed = apply_snapshot(self.backend, self.baseline, self.draft, path)
        except (OSError, ValueError, RuntimeError) as exc:
            backup_note = f"\n\nIf a backup was created, keep it:\n{path}" if path is not None else ""
            QtWidgets.QMessageBox.critical(self, "Write failed", f"{exc}{backup_note}")
            return
        self.baseline = self.draft
        self.restart_required |= changed
        self.set_draft(self.draft)
        backup_note = f"\nBackup: {path}" if path is not None else ""
        QtWidgets.QMessageBox.information(self, "Saved", f"Registry value verified. Restart Windows to apply.{backup_note}")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Ask before discarding a draft; closing never applies changes."""
        if self._discard_allowed():
            event.accept()
        else:
            event.ignore()
