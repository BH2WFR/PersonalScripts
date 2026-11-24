"""Regression checks for physical chords, UTF-16 events and nonactivating controls."""

import ctypes
import importlib
import os
from pathlib import Path
import string
import subprocess
import sys
from textwrap import dedent
import unittest
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/input-and-text"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit
from auto_typer.panel import TypingPanel
from auto_typer.strokes import ascii_key
from utils import Keyboard


class KeyEventTests(unittest.TestCase):
    def test_every_printable_ascii_has_a_physical_key_on_both_platforms(self) -> None:
        for char in string.printable[:-2]:  # Exclude VT and FF; CR normalizes to LF.
            name, shifted = ascii_key(char.replace("\r", "\n"))
            with self.subTest(char=char):
                self.assertIsNotNone(Keyboard.windows_scan_code(name))
                self.assertIsNotNone(Keyboard.macos_virtual_key(name))
                self.assertEqual(shifted, char in string.ascii_uppercase + '~!@#$%^&*()_+{}|:"<>?')

    @unittest.skipUnless(sys.platform == "win32", "Windows INPUT ABI")
    def test_windows_native_packets(self) -> None:
        from auto_typer.windows import _Input, _packets

        self.assertEqual(ctypes.sizeof(_Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

        def events(char: str, caps: bool = False) -> list[tuple[int, int]]:
            return [(p.data.keyboard.scan, p.data.keyboard.flags) for p in _packets(char, caps)]

        self.assertEqual(events("!"), [(42, 8), (2, 8), (2, 10), (42, 10)])
        self.assertEqual(events("A", True), [(30, 8), (30, 10)])
        self.assertEqual(events("a", True), events("A"))
        self.assertEqual(events("\n"), [(28, 8), (28, 10)])
        self.assertEqual(events("中"), [(0x4E2D, 4), (0x4E2D, 6)])
        self.assertEqual(events("😀"), [(0xD83D, 4), (0xD83D, 6), (0xDE00, 4), (0xDE00, 6)])

    def test_quartz_shift_and_unicode_length(self) -> None:
        quartz = Mock(kCGEventFlagMaskShift=1 << 17, kCGSessionEventTap=1)
        appkit = Mock(NSPanel=object)
        event = quartz.CGEventCreateKeyboardEvent.return_value
        with patch.dict(sys.modules, {"Quartz": quartz, "AppKit": appkit, "objc": Mock()}):
            mac = importlib.import_module("auto_typer.macos")
            with patch.object(mac, "Q", quartz):
                sender = mac.MacSender()
                sender.send("A")
                self.assertEqual(quartz.CGEventCreateKeyboardEvent.call_args_list, [
                    call(None, 56, True), call(None, 0, True),
                    call(None, 0, False), call(None, 56, False),
                ])
                quartz.CGEventKeyboardSetUnicodeString.assert_not_called()
                sender.send("😀")
                self.assertEqual(quartz.CGEventKeyboardSetUnicodeString.call_args_list,
                                 [call(event, 2, "😀"), call(event, 2, "😀")])


@unittest.skipUnless(sys.platform == "darwin", "macOS native close button")
class MacPanelTests(unittest.TestCase):
    def test_title_bar_close_exits_process(self) -> None:
        # Exercise the Cocoa button in its own process with a running Qt event loop.
        script = dedent("""
            import sys
            from unittest.mock import patch
            sys.path.insert(0, "tools/input-and-text")
            from auto_typer import macos
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            show_panel = macos.show_panel
            def show_and_close(widget):
                panel, host = show_panel(widget)
                button = panel.standardWindowButton_(macos.A.NSWindowCloseButton)
                QTimer.singleShot(0, lambda: button.performClick_(None))
                return panel, host

            with patch.object(macos, "show_panel", show_and_close), patch.object(QApplication, "clipboard") as clipboard:
                clipboard.return_value.text.return_value = ""
                sys.exit(macos.run_macos())
        """)
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=10,
                       env={**os.environ, "QT_QPA_PLATFORM": "cocoa"})


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.sender = Mock()
        self.sender.target.return_value = 42
        self.clipboard = Mock()
        self.clipboard.text.return_value = "A\r\n\t中😀\r"
        self.enterContext(patch.object(QApplication, "clipboard", return_value=self.clipboard))
        self.panel = TypingPanel(self.sender)
        self.addCleanup(self.panel.deleteLater)
        self.addCleanup(self.panel.timer.stop)

    def test_clipboard_multiline_and_restart(self) -> None:
        text = "A\n\t中😀\n"
        self.assertEqual(self.panel.text, text)
        self.panel.start.click()
        for _ in text:
            self.panel._type_next()
        self.assertEqual("".join(c.args[0] for c in self.sender.send.call_args_list), text)
        self.assertFalse(self.panel.timer.isActive())
        self.clipboard.text.return_value = "again"
        self.panel.paste.click()
        self.panel.start.click()
        self.panel._type_next()
        self.panel.stop.click()
        self.assertFalse(self.panel.timer.isActive())
        self.assertEqual(self.panel.sent, 1)
        self.assertTrue(self.panel.edit.isEnabled())

    def test_refuses_invalid_input_and_stops_before_changed_target(self) -> None:
        self.panel._set_text("ok\x00")
        self.panel.start.click()
        self.assertIn("U+0000", self.panel.status.text())
        self.assertFalse(self.panel.timer.isActive())
        self.panel.paste.click()
        self.panel.start.click()
        self.sender.target.return_value = 99
        self.panel._type_next()
        self.sender.send.assert_not_called()
        self.assertFalse(self.panel.timer.isActive())

    def test_ascii_only_clipboard_import(self) -> None:
        self.assertFalse(self.panel.ascii_only.isChecked())
        self.panel.ascii_only.click()
        self.assertEqual(self.panel.text, "A\n\t\n")
        self.assertEqual(self.panel.preview.toPlainText(), self.panel.text)
        self.panel.paste.click()
        self.assertEqual(self.panel.preview.toPlainText(), "A\n\t\n")
        self.panel.start.click()
        self.assertFalse(self.panel.ascii_only.isEnabled())
        for _ in self.panel.text:
            self.panel._type_next()
        self.assertEqual(self.sender.send.call_args_list, [call(char) for char in "A\n\t\n"])
        self.clipboard.text.return_value = "é中😀"
        self.panel.paste.click()
        self.assertFalse(self.panel.start.isEnabled())
        self.panel.ascii_only.click()
        self.panel.paste.click()
        self.assertEqual(self.panel.text, "é中😀")
        self.panel.ascii_only.click()
        self.assertEqual(self.panel.text, "")
        self.assertFalse(self.panel.start.isEnabled())

    def test_sender_error_stops_typing(self) -> None:
        self.panel.start.click()
        self.sender.send.side_effect = OSError("Target unavailable")
        self.panel._type_next()
        self.assertTrue(self.panel.start.isEnabled())
        self.assertFalse(self.panel.timer.isActive())
        self.assertIn("Target unavailable", self.panel.status.text())

    def test_edit_accept_and_cancel(self) -> None:
        def change(accept: bool) -> None:
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, QDialog)
            editor = dialog.findChild(QPlainTextEdit)
            assert editor is not None
            editor.selectAll()
            editor.insertPlainText("two\nlines\u00a0" if accept else "discard")
            if accept:
                dialog.accept()
            else:
                dialog.reject()

        for checked, accept, expected in (
            (False, True, "two\nlines\u00a0"),
            (True, False, "two\nlines"),
            (True, True, "two\nlines"),
        ):
            self.panel.ascii_only.setChecked(checked)
            QTimer.singleShot(0, lambda accepted=accept: change(accepted))
            self.panel.edit.click()
            self.assertEqual(self.panel.text, expected)
        self.sender.restore.assert_called_with(42)
