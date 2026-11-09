"""PySide6/Fusion editor for explicit, backed-up Windows registry key remapping.

Launch ../keyboard-remap.py. Constructing widgets reads via the supplied backend
but never writes. Dragging reorders the draft; the hex view shows exact pending
bytes. Key capture is limited to a visible focused dialog.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import datetime

from PySide6 import QtCore, QtGui, QtWidgets
from utils.qt_widgets import NoWheelComboBox
from utils import *

from . import USAGE_NOTICE
from .capture import CaptureDialog
from .catalog import choices, key_label, parse_key
from .models import Mapping, Snapshot, MAX_BYTES, encode_map, hex_view, parse_backup, validate_mappings
from .registry import RegistryBackend, apply_snapshot, save_backup

RestartEditor = Callable[[Snapshot, Snapshot], None]


class MappingTable(QtWidgets.QTableWidget):
    """Request whole-row moves within this table without Qt moving cell data.

    The owning window updates the authoritative draft through move_requested.
    External drops and copy operations are rejected; cancellation changes nothing.
    """

    move_requested = QtCore.Signal(int, int)
    MIME_TYPE = "application/x-personal-keyboard-remap-row"
    INSERTION_COLOR = "#2878d0"

    def __init__(self) -> None:
        super().__init__(0, 3)
        self._drag_row: int | None = None
        self._insertion: int | None = None
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(False)  # Paint a full-width insertion line.
        self.setDragDropOverwriteMode(False)
        self.setToolTip("Drag a row above or below another row to change the stored order.")

    def startDrag(self, supportedActions: QtCore.Qt.DropAction) -> None:
        """Start a move-only drag; the drop handler alone requests draft changes."""
        if not self.dragEnabled() or self.currentRow() < 0:
            return
        self._drag_row = self.currentRow()
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(self.MIME_TYPE, b"row")
        drag.setMimeData(mime)
        try:
            drag.exec(QtCore.Qt.DropAction.MoveAction)
        finally:
            self._drag_row = None
            self._insertion = None
            self.viewport().update()
            drag.deleteLater()

    def _accepts(self, event: QtGui.QDropEvent) -> bool:
        return (self.dragEnabled() and event.source() is self and self._drag_row is not None
                and event.mimeData().hasFormat(self.MIME_TYPE)
                and bool(event.possibleActions() & QtCore.Qt.DropAction.MoveAction))

    def _slot_at(self, point: QtCore.QPoint) -> int:
        row = self.rowAt(point.y())
        if row < 0:
            return 0 if point.y() < 0 else self.rowCount()
        return row + int(point.y() >= self.rowViewportPosition(row) + self.rowHeight(row) / 2)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept only a move originating from this table's active drag."""
        self.dragMoveEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        """Update the insertion marker without changing any mappings."""
        if self._accepts(event):
            self._insertion = self._slot_at(event.position().toPoint())
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            self._insertion = None
            event.ignore()
        self.viewport().update()

    def dragLeaveEvent(self, event: QtGui.QDragLeaveEvent) -> None:
        """Hide the insertion marker when the pointer leaves the table."""
        self._insertion = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        """Emit one source-row/insertion-slot request; never overwrite cells."""
        if self._accepts(event) and self._drag_row is not None:
            self.move_requested.emit(self._drag_row, self._slot_at(event.position().toPoint()))
            event.setDropAction(QtCore.Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()
        self._insertion = None
        self.viewport().update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Draw the table and a high-contrast, full-width insertion marker."""
        super().paintEvent(event)
        if self._insertion is None:
            return
        slot = self._insertion
        y = (self.rowViewportPosition(slot) if slot < self.rowCount() else
             self.rowViewportPosition(slot - 1) + self.rowHeight(slot - 1) if slot else 0)
        painter = QtGui.QPainter(self.viewport())
        painter.setPen(QtGui.QPen(QtGui.QColor(self.INSERTION_COLOR), 2))
        painter.drawLine(0, max(1, y), self.viewport().width(), max(1, y))
        painter.end()


class KeyPicker(QtWidgets.QWidget):
    """Editable scan-code dropdown with an independent visible capture action.

    Args:
        allow_disable: Include a target-only Disable option (scan word zero).
        parent: Owning mapping dialog.
    """

    def __init__(self, allow_disable: bool, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.allow_disable = allow_disable
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = NoWheelComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.combo.setMinimumWidth(420)
        self.combo.setMaxVisibleItems(18)
        if allow_disable:
            self.combo.addItem(key_label(0), 0)
        for item in choices():
            self.combo.addItem(item.label, item.code)
        completer = self.combo.completer()
        if completer is not None:
            completer.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.combo.setCurrentIndex(-1)
        edit = self.combo.lineEdit()
        if edit is not None:
            edit.setPlaceholderText("Search key name / scan code, or enter 0xE01D")
        layout.addWidget(self.combo)
        capture = QtWidgets.QPushButton("Capture key...")
        capture.clicked.connect(self._capture)
        layout.addWidget(capture)

    def code(self) -> int:
        """Return the selected/input word, rejecting blank and disabled source keys.

        Raises:
            ValueError: Input is unrecognized or source zero was requested.
        """
        index = self.combo.currentIndex()
        if index >= 0 and self.combo.currentText() == self.combo.itemText(index):
            value = int(self.combo.itemData(index))
        else:
            value = parse_key(self.combo.currentText())
        if value == 0 and not self.allow_disable:
            raise ValueError("A source key cannot be 0x0000 (Disable).")
        return value

    def set_code(self, code: int) -> None:
        """Select a code, retaining unknown words as explicit custom entries."""
        index = self.combo.findData(code)
        if index < 0:
            self.combo.addItem(key_label(code), code)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)

    def _capture(self) -> None:
        dialog = CaptureDialog(self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.result_key is not None:
            self.set_code(dialog.result_key.code)


class MappingDialog(QtWidgets.QDialog):
    """Choose a source and destination via dropdown, raw scan word or capture."""

    def __init__(self, row: Mapping | None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.mapping: Mapping | None = None
        self.setWindowTitle("Edit mapping" if row is not None else "Add mapping")
        self.resize(930, 280)
        layout = QtWidgets.QVBoxLayout(self)
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("FROM - original physical key"), 0, 0)
        grid.addWidget(QtWidgets.QLabel("TO - replacement key"), 0, 1)
        self.source = KeyPicker(False)
        self.target = KeyPicker(True)
        grid.addWidget(self.source, 1, 0)
        grid.addWidget(self.target, 1, 1)
        layout.addLayout(grid)
        notice = QtWidgets.QLabel(
            "Scan codes, not characters or shortcuts. US labels describe base positions; "
            "ISO/JIS/Korean aliases may share codes.\n"
            "Unknown words are preserved but are not guaranteed to work. Capture cannot recover "
            "a key that Windows has already disabled or remapped."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if row is not None:
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


class RemapWindow(QtWidgets.QMainWindow):
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
        self.setWindowTitle("Keyboard Remap")
        self.resize(1120, 660)
        self.setMinimumSize(860, 480)

        # ── header and mapping table ──────────────────────
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QtWidgets.QLabel("Keyboard Remap")
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)
        info = QtWidgets.QLabel("Windows registry mappings - all users and keyboards - restart required after writing")
        layout.addWidget(info)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = MappingTable()
        self.table.setHorizontalHeaderLabels(["Original key / scan code", "Replacement key / scan code", "Draft status"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._edit)
        self.table.move_requested.connect(self._move_row)
        layout.addWidget(self.table, 1)

        # ── exact pending binary preview ─────────────────
        self.hex_toggle = QtWidgets.QToolButton()
        self.hex_toggle.setText("Final hexadecimal view (draft)")
        self.hex_toggle.setCheckable(True)
        self.hex_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.hex_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)
        layout.addWidget(self.hex_toggle)
        self.hex_panel = QtWidgets.QWidget()
        hex_layout = QtWidgets.QVBoxLayout(self.hex_panel)
        hex_layout.setContentsMargins(0, 0, 0, 0)
        self.hex_text = QtWidgets.QPlainTextEdit()
        self.hex_text.setReadOnly(True)
        self.hex_text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        self.hex_text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.hex_text.setMinimumHeight(100)
        self.hex_text.setMaximumHeight(180)
        hex_layout.addWidget(self.hex_text)
        hex_actions = QtWidgets.QHBoxLayout()
        self.copy_hex_button = self._button("Copy hex bytes", self._copy_hex, hex_actions)
        hex_actions.addStretch()
        hex_layout.addLayout(hex_actions)
        layout.addWidget(self.hex_panel)
        self.hex_panel.setVisible(False)
        self.hex_toggle.toggled.connect(self._toggle_hex)

        # ── draft controls and explicit storage actions ──
        actions = QtWidgets.QHBoxLayout()
        self.add_button = self._button("Add...", self._add, actions)
        self.edit_button = self._button("Edit...", self._edit, actions)
        self.remove_button = self._button("Remove", self._remove, actions)
        self.clear_button = self._button("Clear all mappings", self._clear, actions)
        actions.addStretch()
        layout.addLayout(actions)
        storage = QtWidgets.QHBoxLayout()
        self._button("Reload registry", self._reload_clicked, storage)
        self.backup_button = self._button("Back up saved state...", self._backup, storage)
        self.restore_button = self._button("Load backup into draft...", self._restore, storage)
        storage.addStretch()
        self.preview_button = self._button("Review changes...", self._preview, storage)
        self.apply_button = self._button("Write to registry...", self._apply, storage)
        layout.addLayout(storage)
        notice = QtWidgets.QLabel(USAGE_NOTICE)
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #737b86; font-size: 11px;")
        layout.addWidget(notice)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.reload()
        if handoff is not None and self.baseline is not None:
            expected, desired = handoff
            self.baseline = expected
            self.set_draft(desired)
            self.status.setText("Administrator draft loaded. Review it and click Write to registry again. "
                                "External changes will be checked before writing.")

    def _button(self, text: str, handler: Callable[[], None],
                layout: QtWidgets.QHBoxLayout) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(handler)
        layout.addWidget(button)
        return button

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
        self.setWindowTitle(f"Keyboard Remap{' *' if self.dirty else ''}")

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

    def _review(self, confirm: bool) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Review registry changes")
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning if confirm else QtWidgets.QMessageBox.Icon.Information)
        box.setText("Changes affect all users and keyboards, including the sign-in screen.\n"
                    "Check that you can still type your password. Restart Windows after saving.\n"
                    "Unknown, special and language scan codes may not be remappable on your hardware.")
        box.setDetailedText(self.changes())
        box.setInformativeText("Expand Show Details to review every change. A new backup is required before writing.")
        if confirm:
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        else:
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        return box.exec() == QtWidgets.QMessageBox.StandardButton.Yes

    def _preview(self) -> None:
        self._review(False)

    def _apply(self) -> None:
        if self.read_only or self.baseline is None or not self.dirty or not self._review(True):
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
        path = self._backup_path()
        if path is None:
            return
        try:
            changed = apply_snapshot(self.backend, self.baseline, self.draft, path)
        except (OSError, ValueError, RuntimeError) as exc:
            QtWidgets.QMessageBox.critical(self, "Write failed", f"{exc}\n\nIf a backup was created, keep it:\n{path}")
            return
        self.baseline = self.draft
        self.restart_required |= changed
        self.set_draft(self.draft)
        QtWidgets.QMessageBox.information(self, "Saved", f"Registry value verified. Restart Windows to apply.\nBackup: {path}")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Ask before discarding a draft; closing never applies changes."""
        if self._discard_allowed():
            event.accept()
        else:
            event.ignore()
