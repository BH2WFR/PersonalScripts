"""Verify shared PDF dialog histories without opening native dialogs."""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *

runpy.run_path(str(ROOT / "tools/document-processing/pdf-binarizer.py"))["load_app"]("common.preferences")
from personal_pdf_tools.common.preferences import PDF_CONFIG, choose_open_file, choose_save_file, dialog_directory, remember_directory


class PreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def test_shared_histories_cancel_and_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="pdf-preferences-") as temporary:
            folder = Path(temporary)
            with patch.object(ConfigStore, "directory", return_value=folder / "config"):
                first, second = QtWidgets.QWidget(), QtWidgets.QWidget()
                try:
                    source = folder / "book.pdf"
                    with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(source), "")):
                        self.assertEqual(choose_open_file(first, "Open", "PDF"), str(source))
                    self.assertEqual(dialog_directory(second, "open-pdf"), str(folder))
                    with ConfigStore._locked_path(ConfigStore(PDF_CONFIG).path), patch.object(QtWidgets.QToolTip, "showText") as tooltip:
                        self.assertFalse(remember_directory(second, "open-pdf", folder / "other.pdf"))
                        self.assertEqual(dialog_directory(second, "open-pdf", folder), str(folder))
                        self.assertTrue(tooltip.called)
                    original = ConfigStore(PDF_CONFIG).path.read_bytes()
                    with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=("", "")) as dialog:
                        self.assertEqual(choose_open_file(second, "Open", "PDF"), "")
                        self.assertEqual(dialog.call_args.args[2], str(folder))
                    self.assertEqual(ConfigStore(PDF_CONFIG).path.read_bytes(), original)
                    target = folder / "export"
                    target.mkdir()
                    with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target / "out.pdf"), "")):
                        choose_save_file(first, "Save", source, "PDF", kind="save-pdf")
                    self.assertEqual(dialog_directory(second, "save-pdf"), str(target))
                    self.assertEqual(dialog_directory(second, "open-pdf"), str(folder))
                    target.rmdir()
                    self.assertEqual(dialog_directory(second, "save-pdf", folder), str(folder))
                finally:
                    first.close()
                    second.close()


if __name__ == "__main__":
    unittest.main()
