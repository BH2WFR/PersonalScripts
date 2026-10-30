"""Keyboard remapper tests using an in-memory registry and offscreen Qt widgets.

Requirements: project runtime and PySide6. No native registry writes, elevation,
global hooks or synthetic system input. Run with unittest discover -s test -p
"test_keyboard_remap.py" using the project Conda interpreter.
"""

from __future__ import annotations

import importlib
import importlib.util
import contextlib
import ctypes
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import ModuleType
from typing import ClassVar
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from utils import *


def load_repo_module(name: str, path: str) -> ModuleType:
    """Load a repository module without invoking its main workflow."""
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


entry = load_repo_module("keyboard_remap_test_entry", "tools/windows/keyboard-remap.py")
app = entry.load_app()
models = importlib.import_module(f"{entry.PACKAGE_NAME}.models")
registry = importlib.import_module(f"{entry.PACKAGE_NAME}.registry")
catalog = importlib.import_module(f"{entry.PACKAGE_NAME}.catalog")
capture = importlib.import_module(f"{entry.PACKAGE_NAME}.capture")
ui = importlib.import_module(f"{entry.PACKAGE_NAME}.ui")


class MapModelTests(unittest.TestCase):
    """Binary format, validation and backups are independent of Windows."""

    def test_destination_first_round_trip_and_unknown_words(self) -> None:
        rows = (models.Mapping(0x003A, 0x0076), models.Mapping(0xE038, 0x006E),
                models.Mapping(0xABCD, 0), models.Mapping(0xE11D, 0x9876))
        data = models.encode_map(rows)
        self.assertEqual(data[:16], bytes.fromhex("00000000000000000500000076003A00"))
        self.assertEqual(models.decode_map(data), rows)
        self.assertEqual(models.encode_map(models.decode_map(data)), data)

    def test_count_is_a_dword_not_a_byte(self) -> None:
        rows = tuple(models.Mapping(code, 0) for code in range(1, 301))
        data = models.encode_map(rows)
        self.assertEqual(struct.unpack_from("<I", data, 8)[0], 301)
        self.assertEqual(models.decode_map(data), rows)

    def test_hex_view_is_exact_and_distinguishes_absence(self) -> None:
        for rows in ((), (models.Mapping(0xE038, 0x76), models.Mapping(0xABCD, 0))):
            data = models.encode_map(rows)
            lines = models.hex_view(models.Snapshot(data)).splitlines()
            self.assertIn(f"{len(data)} bytes", lines[0])
            self.assertEqual(bytes.fromhex(" ".join(line[10:] for line in lines[2:])), data)
            self.assertEqual([line[:8] for line in lines[2:]],
                             [f"{offset:08X}" for offset in range(0, len(data), 16)])
        self.assertIn("will be deleted", models.hex_view(models.Snapshot(None)))
        self.assertIn("16 bytes", models.hex_view(models.Snapshot(models.encode_map(()))))

    def test_absent_and_present_empty_are_distinct_and_round_trip(self) -> None:
        absent = models.Snapshot(None)
        empty = models.Snapshot(models.encode_map(()))
        self.assertNotEqual(absent, empty)
        for state in (absent, empty, models.Snapshot(models.encode_map((models.Mapping(0xABCD, 0),)))):
            self.assertEqual(models.parse_backup(models.backup_text(state)), state)

    def test_invalid_binary_is_rejected_without_repair(self) -> None:
        valid = models.encode_map((models.Mapping(1, 2),))
        for data in (b"", valid[:-1], valid + bytes(4), b"x" + valid[1:],
                     valid[:-4] + b"xxxx", valid[:8] + bytes(4) + valid[12:],
                     models.HEADER + struct.pack("<IHH", 2, 1, 0) + models.TERMINATOR):
            with self.subTest(data=data), self.assertRaises(ValueError):
                models.Snapshot(data)
        with self.assertRaises(ValueError):
            models.encode_map((models.Mapping(1, 2), models.Mapping(1, 3)))
        for source, target in ((0, 1), (-1, 0), (True, 2), (1, 65536)):
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                models.Mapping(source, target)

    def test_backup_rejects_foreign_path_bad_schema_and_hex(self) -> None:
        text = models.backup_text(models.Snapshot(None))
        for bad in ("[]", "null", text.replace("Scancode Map", "Other Value"),
                    text.replace("null", "123"), text.replace("null", '"xyz"')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                models.parse_backup(bad)

    def test_handoff_only_carries_validated_snapshots(self) -> None:
        pair = (models.Snapshot(None), models.Snapshot(models.encode_map((models.Mapping(1, 2),))))
        self.assertEqual(app.decode_handoff(app.encode_handoff(*pair)), pair)
        for payload in ("!", "W10=", "bnVsbA=="):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                app.decode_handoff(payload)

    def test_catalog_uses_shared_scan_table_and_keeps_alias_collisions(self) -> None:
        items = catalog.choices()
        self.assertTrue(all(f"0x{item.code:04X}" in item.label for item in items))
        self.assertGreater(sum(item.code == 0x76 for item in items), 1)
        for text, code in (("f24", 0x76), ("f1", 0x3B), ("0xF1", 0xF1),
                           ("henkan", 0x79), ("0xE01D", 0xE01D), ("0xABCD", 0xABCD)):
            self.assertEqual(catalog.parse_key(text), code)
        for item in items:
            self.assertEqual(catalog.parse_key(item.label), item.code)
        self.assertIn("0xABCD", catalog.key_label(0xABCD))
        self.assertIn("Disable", catalog.key_label(0))
        with self.assertRaises(ValueError):
            catalog.parse_key("garbage")


class RegistrySafetyTests(unittest.TestCase):
    """All mutations target a mock; backup files stay in the project scratch area."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="keyboard-remap-", dir=ROOT / "tmp")
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "backup.json"
        self.before = models.Snapshot(None)
        self.after = models.Snapshot(models.encode_map((models.Mapping(1, 2),)))
        self.backend = Mock()

    def test_success_orders_backup_before_write_and_verifies(self) -> None:
        self.backend.read.side_effect = [self.before, self.before, self.after]

        def write(snapshot: object) -> None:
            self.assertEqual(snapshot, self.after)
            self.assertEqual(models.parse_backup(self.path.read_text(encoding="utf-8")), self.before)

        self.backend.write.side_effect = write
        self.assertTrue(registry.apply_snapshot(self.backend, self.before, self.after, self.path))
        self.backend.write.assert_called_once_with(self.after)

    def test_external_change_before_or_during_backup_never_writes(self) -> None:
        for states in ([self.after], [self.before, self.after]):
            with self.subTest(states=states):
                self.backend.reset_mock()
                self.backend.read.side_effect = states
                path = self.path.with_name(f"backup-{len(states)}.json")
                with self.assertRaises(RuntimeError):
                    registry.apply_snapshot(self.backend, self.before, self.after, path)
                self.backend.write.assert_not_called()

    def test_existing_backup_and_backup_failure_prevent_writes(self) -> None:
        self.backend.read.return_value = self.before
        registry.save_backup(self.path, self.before)
        with self.assertRaises(FileExistsError):
            registry.apply_snapshot(self.backend, self.before, self.after, self.path)
        with patch.object(registry, "save_backup", side_effect=PermissionError("test")):
            with self.assertRaises(PermissionError):
                registry.apply_snapshot(self.backend, self.before, self.after, self.path)
        self.backend.write.assert_not_called()

    def test_noop_has_no_backup_or_write(self) -> None:
        self.backend.read.return_value = self.before
        self.assertFalse(registry.apply_snapshot(self.backend, self.before, self.before, self.path))
        self.assertFalse(self.path.exists())
        self.backend.write.assert_not_called()

    def test_readback_failure_keeps_backup_and_does_not_auto_rollback(self) -> None:
        self.backend.read.side_effect = [self.before, self.before, self.before]
        with self.assertRaises(RuntimeError):
            registry.apply_snapshot(self.backend, self.before, self.after, self.path)
        self.assertTrue(self.path.exists())
        self.backend.write.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Native winreg wrapper")
    def test_native_backend_is_scoped_to_one_value(self) -> None:
        import winreg
        with patch.object(winreg, "OpenKey") as opened, patch.object(winreg, "SetValueEx") as set_value, \
                patch.object(winreg, "DeleteValue") as delete_value:
            key = opened.return_value.__enter__.return_value
            native = registry.WindowsRegistry()
            native.write(self.after)
            set_value.assert_called_once_with(key, models.VALUE_NAME, 0, winreg.REG_BINARY, self.after.data)
            native.write(self.before)
            delete_value.assert_called_once_with(key, models.VALUE_NAME)
            self.assertTrue(all(call.args[1] == models.REGISTRY_PATH for call in opened.call_args_list))


class CaptureTests(unittest.TestCase):
    """Pure native-message decoding; no key listener is started by these tests."""

    def test_extended_sides_and_keypad_enter(self) -> None:
        for scan, vk, extended, expected in ((0x1C, 0x0D, False, 0x1C),
                                            (0x1C, 0x0D, True, 0xE01C),
                                            (0x1D, 0x11, True, 0xE01D),
                                            (0x38, 0x12, True, 0xE038),
                                            (0x45, 0x90, True, 0x45)):
            with self.subTest(expected=expected):
                result = capture.decode_message(0x0100, vk, (scan << 16) | (int(extended) << 24))
                self.assertEqual(result.code, expected)

    def test_ime_release_only_and_unrepresentable_pause(self) -> None:
        self.assertEqual(capture.decode_message(0x0101, 0x15, 0xF2 << 16).code, 0xF2)
        self.assertIsNone(capture.decode_message(0x0101, 0x41, 0x1E << 16))
        self.assertIsNone(capture.decode_message(0x0100, 0x41, (0x1E << 16) | (1 << 30)))
        self.assertIsNone(capture.decode_message(0x0100, 0x41, 0))
        with self.assertRaises(ValueError):
            capture.decode_message(0x0100, 0x13, 0x45 << 16)


class GuiTests(unittest.TestCase):
    """Offscreen widget interactions using mock storage and privilege APIs."""

    qt: ClassVar[QtWidgets.QApplication]

    @classmethod
    def setUpClass(cls) -> None:
        existing = QtWidgets.QApplication.instance()
        application = existing if existing is not None else QtWidgets.QApplication([])
        assert isinstance(application, QtWidgets.QApplication)
        cls.qt = application
        cls.qt.setStyle("Fusion")

    def setUp(self) -> None:
        self.before = models.Snapshot(models.encode_map((models.Mapping(0x3A, 0x76),)))
        self.backend = Mock()
        self.backend.read.return_value = self.before
        self.restart = Mock()
        self.window = ui.RemapWindow(self.backend, self.restart)
        self.addCleanup(self.window.deleteLater)

    def test_loading_and_editing_never_write(self) -> None:
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertIn("0x003A", self.window.table.item(0, 0).text())
        self.assertFalse(self.window.dirty)
        self.window.set_draft(models.Snapshot(None))
        self.assertTrue(self.window.dirty)
        self.assertIn("REMOVE", self.window.changes())
        self.backend.write.assert_not_called()
        self.restart.assert_not_called()

    def test_reordering_keeps_rows_bytes_selection_and_preview_in_sync(self) -> None:
        rows = (models.Mapping(0xABCD, 0), models.Mapping(0x3A, 0x76), models.Mapping(0xE038, 0x6E))
        self.backend.read.return_value = models.Snapshot(models.encode_map(rows))
        self.window.reload()
        self.window._move_row(0, 3)
        expected = (rows[1], rows[2], rows[0])
        self.assertEqual(self.window.rows, expected)
        self.assertEqual(self.window.draft.data, models.encode_map(expected))
        self.assertEqual(self.window.table.currentRow(), 2)
        self.assertTrue(self.window.dirty)
        self.assertIn("stored order", self.window.changes())
        self.assertEqual(self.window.hex_text.toPlainText(), models.hex_view(self.window.draft))
        self.window._move_row(2, 0)
        self.assertEqual(self.window.rows, rows)
        self.assertFalse(self.window.dirty)
        for source, insertion in ((1, 1), (1, 2), (-1, 0), (3, 0), (0, 4)):
            self.window._move_row(source, insertion)
            self.assertEqual(self.window.rows, rows)
        self.backend.write.assert_not_called()
        self.restart.assert_not_called()

    def test_drag_events_move_whole_rows_and_reject_foreign_drops(self) -> None:
        rows = (models.Mapping(1, 2), models.Mapping(3, 4), models.Mapping(5, 6))
        self.window._replace_rows(rows)
        table = self.window.table
        table.resize(800, 200)
        table.selectRow(0)
        mime = QtCore.QMimeData()
        mime.setData(table.MIME_TYPE, b"row")
        bottom = QtCore.QPointF(10, table.rowViewportPosition(2) + table.rowHeight(2) - 1)
        event = QtGui.QDropEvent(bottom, QtCore.Qt.DropAction.MoveAction, mime,
                                QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        table._drag_row = 0
        table.dropEvent(event)  # Qt reports no source for this synthetic external drop.
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.window.rows, rows)
        move = QtGui.QDragMoveEvent(bottom.toPoint(), QtCore.Qt.DropAction.MoveAction, mime,
                                   QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        with patch.object(move, "source", return_value=table):
            table.dragMoveEvent(move)
        self.assertTrue(move.isAccepted())
        self.assertEqual(table._insertion, 3)
        with patch.object(event, "source", return_value=table):
            table.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.window.rows, (rows[1], rows[2], rows[0]))
        self.assertIsNone(table._insertion)
        self.assertEqual(table.rowCount(), 3)
        for index, row in enumerate(self.window.rows):
            self.assertEqual(table.item(index, 0).text(), catalog.key_label(row.source))
            self.assertEqual(table.item(index, 1).text(), catalog.key_label(row.target))
        table._drag_row = None
        before = self.window.draft
        with patch.object(QtGui.QDrag, "exec", return_value=QtCore.Qt.DropAction.IgnoreAction):
            table.startDrag(QtCore.Qt.DropAction.MoveAction)
        self.assertIsNone(table._drag_row)
        self.assertEqual(self.window.draft, before)
        self.backend.write.assert_not_called()

    def test_hex_panel_updates_copy_and_absent_value(self) -> None:
        self.assertTrue(self.window.hex_text.isReadOnly())
        self.assertTrue(self.window.hex_panel.isHidden())
        self.window.hex_toggle.setChecked(True)
        self.assertFalse(self.window.hex_panel.isHidden())
        self.window.hex_toggle.setChecked(False)
        self.assertTrue(self.window.hex_panel.isHidden())
        clipboard = Mock()
        with patch.object(QtWidgets.QApplication, "clipboard", return_value=clipboard):
            self.window.copy_hex_button.click()
            clipboard.setText.assert_called_once_with(self.before.data.hex(" ").upper())
            clipboard.reset_mock()
            self.window.set_draft(models.Snapshot(None))
            self.assertIn("will be deleted", self.window.hex_text.toPlainText())
            self.assertFalse(self.window.copy_hex_button.isEnabled())
            self.window._copy_hex()
            clipboard.setText.assert_not_called()
        self.window.set_draft(models.Snapshot(models.encode_map(())))
        self.assertIn("16 bytes", self.window.hex_text.toPlainText())
        self.assertTrue(self.window.copy_hex_button.isEnabled())
        self.backend.write.assert_not_called()

    def test_mouse_drag_enters_move_only_workflow(self) -> None:
        rows = (models.Mapping(1, 2), models.Mapping(3, 4), models.Mapping(5, 6))
        self.window._replace_rows(rows)
        self.window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.show()
        self.qt.processEvents()
        table = self.window.table
        start = table.visualItemRect(table.item(0, 0)).center()
        end = table.visualItemRect(table.item(2, 0)).bottomLeft() + QtCore.QPoint(10, 0)

        def drop(action: QtCore.Qt.DropAction) -> QtCore.Qt.DropAction:
            self.assertEqual(action, QtCore.Qt.DropAction.MoveAction)
            self.assertEqual(table._drag_row, 0)
            mime = QtCore.QMimeData()
            mime.setData(table.MIME_TYPE, b"row")
            event = QtGui.QDropEvent(QtCore.QPointF(end), action, mime,
                                    QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
            with patch.object(event, "source", return_value=table):
                table.dropEvent(event)
            return action

        with patch.object(QtGui.QDrag, "exec", side_effect=drop) as execute:
            QtTest.QTest.mousePress(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
            QtTest.QTest.mouseMove(table.viewport(), start + QtCore.QPoint(2, 0))
            QtTest.QTest.mouseMove(table.viewport(), end)
            QtTest.QTest.mouseRelease(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=end)
            execute.assert_called_once()
        self.assertEqual(self.window.rows, (rows[1], rows[2], rows[0]))
        self.assertIsNone(table._drag_row)
        self.backend.write.assert_not_called()

    def test_insertion_marker_is_visible(self) -> None:
        self.window._replace_rows((models.Mapping(1, 2), models.Mapping(3, 4)))
        table = self.window.table
        table._insertion = 1
        picture = table.viewport().grab().toImage()
        y = table.rowViewportPosition(1)
        self.assertEqual(picture.pixelColor(5, y).name(), table.INSERTION_COLOR)

    def test_readonly_reorder_is_draft_only_and_invalid_state_blocks_it(self) -> None:
        self.window.read_only = True
        rows = (models.Mapping(1, 2), models.Mapping(3, 4))
        self.window._replace_rows(rows)
        self.window._move_row(0, 2)
        self.assertEqual(self.window.rows, rows[::-1])
        self.assertFalse(self.window.apply_button.isEnabled())
        self.backend.read.side_effect = ValueError("invalid map")
        self.window.reload()
        self.window._move_row(0, 2)
        self.assertEqual(self.window.rows, rows[::-1])
        self.assertFalse(self.window.table.dragEnabled())
        self.assertFalse(self.window.copy_hex_button.isEnabled())
        self.assertIn("unavailable", self.window.hex_text.toPlainText())
        self.backend.write.assert_not_called()

    def test_unknown_mapping_can_be_edited_without_loss(self) -> None:
        picker = ui.KeyPicker(False)
        self.addCleanup(picker.deleteLater)
        picker.set_code(0xABCD)
        self.assertEqual(picker.code(), 0xABCD)
        picker.combo.setEditText("0xE038")
        self.assertEqual(picker.code(), 0xE038)
        picker.combo.setEditText("0x0000")
        with self.assertRaises(ValueError):
            picker.code()
        destination = ui.KeyPicker(True)
        self.addCleanup(destination.deleteLater)
        destination.set_code(0)
        self.assertEqual(destination.code(), 0)

    def test_capture_stops_on_success_cancel_and_timeout(self) -> None:
        dialog = capture.CaptureDialog()
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.listening)
        self.assertTrue(dialog.receive(0x0100, 0x41, 0x1E << 16))
        self.assertEqual(dialog.result_key.code, 0x1E)
        self.assertFalse(dialog.listening)
        self.assertFalse(dialog.receive(0x0100, 0x42, 0x30 << 16))
        dialog.begin()
        dialog._timeout()
        self.assertFalse(dialog.listening)
        dialog.begin()
        dialog.reject()
        self.assertFalse(dialog.listening)
        self.assertFalse(dialog.timer.isActive())

    @unittest.skipUnless(sys.platform == "win32", "Native Windows message structure")
    def test_native_capture_event_is_scoped_to_active_dialog(self) -> None:
        dialog = capture.CaptureDialog()
        self.addCleanup(dialog.deleteLater)
        msg = capture._MSG()
        msg.message = 0x0100
        msg.wParam = 0x11
        msg.lParam = (0x1D << 16) | (1 << 24)
        with patch.object(dialog, "isActiveWindow", return_value=False):
            self.assertEqual(dialog.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg)), (False, 0))
        self.assertIsNone(dialog.result_key)
        with patch.object(dialog, "isActiveWindow", return_value=True):
            self.assertEqual(dialog.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg)), (True, 0))
        self.assertEqual(dialog.result_key.code, 0xE01D)
        self.assertFalse(dialog.listening)

    def test_invalid_registry_blocks_write_and_elevation(self) -> None:
        self.backend.read.side_effect = ValueError("Malformed map")
        self.window.reload()
        self.assertFalse(self.window.apply_button.isEnabled())
        self.assertFalse(self.window.add_button.isEnabled())
        self.window._apply()
        self.backend.write.assert_not_called()
        self.restart.assert_not_called()

    def test_cancel_review_or_backup_dialog_never_writes(self) -> None:
        self.window.set_draft(models.Snapshot(None))
        with patch.object(self.window, "_review", return_value=False):
            self.window._apply()
        with patch.object(self.window, "_review", return_value=True), \
                patch.object(System, "is_elevated", return_value=True), \
                patch.object(self.window, "_backup_path", return_value=None):
            self.window._apply()
        self.backend.write.assert_not_called()
        self.restart.assert_not_called()

    def test_nonadmin_handoff_is_a_draft_not_an_apply(self) -> None:
        desired = models.Snapshot(None)
        self.window.set_draft(desired)
        with patch.object(self.window, "_review", return_value=True), \
                patch.object(System, "is_elevated", return_value=False), \
                patch.object(QtWidgets.QMessageBox, "information"):
            self.window._apply()
        self.restart.assert_called_once_with(self.before, desired)
        self.backend.write.assert_not_called()
        self.assertTrue(self.window.dirty)

    def test_confirmed_admin_apply_updates_saved_state(self) -> None:
        desired = models.Snapshot(None)
        self.window.set_draft(desired)
        with tempfile.TemporaryDirectory(prefix="keyboard-remap-apply-", dir=ROOT / "tmp") as directory:
            path = Path(directory) / "before.json"
            self.backend.read.side_effect = [self.before, self.before, desired]
            with patch.object(self.window, "_review", return_value=True), \
                    patch.object(System, "is_elevated", return_value=True), \
                    patch.object(self.window, "_backup_path", return_value=path), \
                    patch.object(QtWidgets.QMessageBox, "information"):
                self.window._apply()
            self.assertEqual(models.parse_backup(path.read_text(encoding="utf-8")), self.before)
        self.backend.write.assert_called_once_with(desired)
        self.assertFalse(self.window.dirty)
        self.assertTrue(self.window.restart_required)

    def test_duplicate_sources_cannot_replace_draft(self) -> None:
        with self.assertRaises(ValueError):
            self.window._replace_rows((models.Mapping(1, 2), models.Mapping(1, 3)))
        self.assertEqual(self.window.draft, self.before)
        self.backend.write.assert_not_called()

    def test_read_only_mode_blocks_apply_even_for_admin(self) -> None:
        window = ui.RemapWindow(self.backend, self.restart, read_only=True)
        self.addCleanup(window.deleteLater)
        window.set_draft(models.Snapshot(None))
        with patch.object(System, "is_elevated", return_value=True):
            window._apply()
        self.assertFalse(window.apply_button.isEnabled())
        self.backend.write.assert_not_called()
        self.restart.assert_not_called()

    def test_restore_loads_into_draft_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="keyboard-remap-restore-", dir=ROOT / "tmp") as directory:
            path = Path(directory) / "backup.json"
            registry.save_backup(path, models.Snapshot(None))
            with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(path), "")):
                self.window._restore()
        self.assertIsNone(self.window.draft.data)
        self.assertTrue(self.window.dirty)
        self.backend.write.assert_not_called()


class IntegrationTests(unittest.TestCase):
    """Launcher discovery, help and compiler alias staging do not invoke live I/O."""

    def test_help_never_loads_gui_or_registry(self) -> None:
        with patch.object(entry, "load_app") as loader, patch.object(sys, "argv", ["keyboard-remap.py", "--help"]):
            with self.assertRaises(SystemExit) as result, contextlib.redirect_stdout(io.StringIO()):
                entry.main()
        self.assertEqual(result.exception.code, 0)
        loader.assert_not_called()

    def test_only_entry_is_discovered_and_compiler_stages_package(self) -> None:
        launcher = load_repo_module("remap_test_launcher", "run-script.py")
        compiler = load_repo_module("remap_test_compiler", "compile-script.py")
        config = launcher._load_launcher_config(str(ROOT))
        self.assertTrue(launcher._is_ignored(config.ignore_spec, "windows/keyboard-remap/ui.py"))
        with patch.object(compiler.sys, "platform", "win32"):
            found = [path.replace("\\", "/") for path in compiler.find_py_scripts(str(ROOT / "tools"))]
        self.assertIn("windows/keyboard-remap.py", found)
        self.assertFalse(any(path.startswith("windows/keyboard-remap/") for path in found))
        with tempfile.TemporaryDirectory(prefix="keyboard-remap-build-", dir=ROOT / "tmp") as directory:
            for builder in ("nuitka", "pyinstaller"):
                def inspect(command: list[str], *, check: bool, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
                    stage = Path(env["PYTHONPATH"].split(os.pathsep)[0]) / entry.PACKAGE_NAME
                    for name in ("app", "models", "registry", "capture", "catalog", "ui"):
                        self.assertTrue((stage / f"{name}.py").is_file())
                    self.assertTrue(any(entry.PACKAGE_NAME in option for option in command))
                    return subprocess.CompletedProcess(command, 0)

                with patch.object(compiler.subprocess, "run", side_effect=inspect):
                    compiler._run_compiler(["compiler", entry.__file__], entry.__file__, directory, builder)

    def test_elevation_bootstrap_uses_draft_only_arguments(self) -> None:
        before, after = models.Snapshot(None), models.Snapshot(models.encode_map((models.Mapping(1, 2),)))
        with patch.object(app.subprocess, "Popen") as spawn:
            app.open_elevated_editor(before, after)
        command = spawn.call_args.args[0]
        self.assertEqual(command[-2], "--admin-draft")
        self.assertEqual(app.decode_handoff(command[-1]), (before, after))
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 0x08000000)
        app._BOOTSTRAPS.clear()

    def test_embedded_startup_uses_fusion_and_read_only_window(self) -> None:
        application = QtWidgets.QApplication.instance()
        assert isinstance(application, QtWidgets.QApplication)
        backend = Mock()
        backend.read.return_value = models.Snapshot(None)
        with patch.object(registry, "WindowsRegistry", return_value=backend):
            self.assertEqual(app.run(read_only=True), 0)
        self.assertEqual(application.style().objectName(), "fusion")
        window = application.property("keyboardRemapWindow")
        self.assertTrue(window.read_only)
        self.assertFalse(window.apply_button.isEnabled())
        backend.write.assert_not_called()
        window.close()
        window.deleteLater()


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
