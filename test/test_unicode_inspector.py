"""Exercise the standalone Qt inspector with generated text and mocked clipboard I/O."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import os
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("unicode_inspector_test_entry", ROOT / "tools/input-and-text/unicode-inspector.py")
assert SPEC is not None and SPEC.loader is not None
entry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entry
SPEC.loader.exec_module(entry)


class EntryTests(unittest.TestCase):
    def test_help_does_not_require_qt(self) -> None:
        for flag in ("--help", "-h"):
            with patch.dict(sys.modules, {"PySide6": None}), patch.object(sys, "argv", ["unicode-inspector.py", flag]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
                    entry.main()
                self.assertEqual(result.exception.code, 0)
                self.assertIn("Requirements:", output.getvalue())

    def test_clipboard_and_text_conflict_before_window_creation(self) -> None:
        with patch.object(sys, "argv", ["unicode-inspector.py", "--clip", "text"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                entry.main()
        self.assertEqual(result.exception.code, 2)


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from utils.qt_widgets import configure_qt_application

        existing = QApplication.instance()
        cls.app = existing if isinstance(existing, QApplication) else QApplication([])
        configure_qt_application(cls.app)
        sys.path.insert(0, str(entry.SCRIPT_DIR))
        cls.addClassCleanup(sys.path.remove, str(entry.SCRIPT_DIR))

    def setUp(self) -> None:
        from unicode_inspector.window import UnicodeInspector

        self.window = UnicodeInspector("")
        self.addCleanup(self.window.close)

    def test_layout_fonts_and_columns(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        from utils import UnicodeText

        fonts = {button.text(): button.font() for button in self.window.findChildren(QPushButton)}
        self.assertEqual(set(fonts), {"Clear", "Paste", "Analyze", "Copy Original", "Copy Full Report", "Copy Selected Rows"})
        self.assertEqual({label for label, font in fonts.items() if font.bold()}, {"Paste", "Analyze"})
        font = self.window.original.font()
        self.assertEqual(font.pointSizeF(), self.app.font().pointSizeF())
        self.assertEqual(self.window.original.document().defaultFont().pointSizeF(), font.pointSizeF())
        self.assertEqual(font.families(), self.app.font().families())
        self.assertEqual(self.window.original.document().defaultFont().families(), font.families())
        self.assertEqual(self.window.table.font().families(), font.families())
        model = self.window.model
        self.assertEqual(tuple(model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())),
                         UnicodeText.COLUMNS)

    def test_source_survives_edit_selection_copy_and_undo(self) -> None:
        from PySide6.QtCore import QMimeData
        from unicode_inspector.editor import mime_text

        text = " \x00\r\n中😀e\u0301\t\u00a0\u2028\u2029\r\ufdd0\ufdd1\ud800\ufffd "
        self.window.set_text(text)
        self.assertEqual(self.window.model.report.text, text)
        self.assertEqual(self.window.statistics["Characters"].text(), str(len(text)))
        self.assertEqual(self.window.model.rowCount(), len(text))
        self.assertEqual(self.window.statistics["UTF-8 bytes"].text(), "Invalid")
        editor = self.window.original
        editor.selectAll()
        self.assertEqual(mime_text(editor.createMimeDataFromSelection()), text)
        pasted = QMimeData()
        pasted.setText(" \r\n\u2029字\u00a0")
        editor.insertFromMimeData(pasted)
        self.assertEqual(editor.original_text(), pasted.text())
        self.assertIn("Analyze to update", self.window.status.text())
        editor.undo()
        self.assertEqual(editor.original_text(), text)
        editor.redo()
        self.assertEqual(editor.original_text(), pasted.text())

    def test_paste_button_and_nontext_clipboard(self) -> None:
        from PySide6.QtCore import QMimeData

        data = QMimeData()
        with patch("unicode_inspector.window.QApplication.clipboard") as clipboard:
            clipboard.return_value.mimeData.return_value = data
            data.setText(" \t\r\n ")
            self.window.paste()
            self.assertEqual(self.window.model.report.text, " \t\r\n ")
            data.clear()
            self.window.paste()
            self.assertIn("no readable text", self.window.status.text())
            self.assertEqual(self.window.original.original_text(), " \t\r\n ")

    def test_copy_and_reanalysis(self) -> None:
        from PySide6.QtCore import QItemSelectionModel, Qt
        from PySide6.QtTest import QTest
        from unicode_inspector.editor import mime_text
        from utils import UnicodeText

        self.window.set_text("A\n😀")
        model = self.window.model
        selection = self.window.table.selectionModel()
        for row in (2, 1):
            selection.select(model.index(row, 0), QItemSelectionModel.SelectionFlag.Select |
                             QItemSelectionModel.SelectionFlag.Rows)
        with patch("unicode_inspector.window.QApplication.clipboard") as clipboard:
            def copied() -> str | None:
                return mime_text(clipboard.return_value.setMimeData.call_args.args[0])

            QTest.keyClick(self.window.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(copied(), "\n".join("\t".join(row.columns()) for row in model.report.characters[1:]))
            self.window.original.insert_source("中" * 2500)
            self.window.copy_original()
            self.assertEqual(copied(), "A\n😀" + "中" * 2500)
            self.window.copy_report()
            self.assertEqual(copied(), UnicodeText.format_report(model.report))
            self.assertEqual(model.rowCount(), 2503)
        self.window.set_text("")
        self.assertEqual(model.rowCount(), 0)
        self.assertTrue(all(value.text() == "0" for value in self.window.statistics.values()))


if __name__ == "__main__":
    unittest.main()
