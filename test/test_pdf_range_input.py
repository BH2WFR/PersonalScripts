"""Offscreen parity controls and page-dialog tests; no user PDF is opened.

Requirements: PySide6 and the repository's utils package.
Run: conda run -n base python -m unittest discover -s test -p test_pdf_range_input.py
"""

import os
from pathlib import Path
import runpy
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / "tools/document-processing/pdf-font-replace.py"))["load_app"]("common.range_input")
from utils import *
from personal_pdf_tools.common.range_input import PageRangeDialog, RangeInput
from personal_pdf_tools.font_replace.panel import RulePanel


class RangeInputTests(unittest.TestCase):
    """Verify editing, radio exclusivity and shared parser interoperability."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        self.field = QtWidgets.QLineEdit("1,2-5")
        self.control = RangeInput(self.field)
        self.addCleanup(self.control.deleteLater)

    def test_default_all_and_buttons_preserve_input_range(self) -> None:
        self.assertTrue(self.control.buttons[None].isChecked())
        self.control.buttons[RangeParity.ODD].click()
        self.assertEqual(self.field.text(), "1,2-5|odd")
        self.assertEqual(Input.parse_index_ranges(self.field.text(), item_count=5), (0, 2, 4))
        self.control.buttons[RangeParity.EVEN].click()
        self.assertEqual(self.field.text(), "1,2-5|even")
        self.assertEqual(sum(button.isChecked() for button in self.control.buttons.values()), 1)
        self.control.buttons[None].click()
        self.assertEqual(self.field.text(), "1,2-5")

    def test_typed_and_restored_suffixes_update_buttons_without_rewriting(self) -> None:
        changes: list[str] = []
        self.field.textChanged.connect(changes.append)
        for text, parity in (("all | ODD ", RangeParity.ODD), ("none|even", RangeParity.EVEN), ("2,4", None)):
            with self.subTest(text=text):
                self.field.setText(text)
                self.assertTrue(self.control.buttons[parity].isChecked())
                self.assertEqual(self.field.text(), text)
        self.assertEqual(len(changes), 3)

    def test_empty_range_uses_all_when_filter_is_selected(self) -> None:
        self.field.clear()
        self.control.buttons[RangeParity.EVEN].click()
        self.assertEqual(self.field.text(), "all|even")
        self.control.buttons[None].click()
        self.assertEqual(self.field.text(), "all")

    def test_invalid_text_remains_for_parser_validation(self) -> None:
        self.field.setText("1|odd|even")
        self.assertEqual(self.field.text(), "1|odd|even")
        with self.assertRaises(ValueError):
            Input.parse_index_ranges(self.field.text(), item_count=5)

    def test_rule_panel_controls_keep_apply_and_ignore_independent(self) -> None:
        panel = RulePanel()
        self.addCleanup(panel.deleteLater)
        panel.pages.setText("1-5")
        panel.pages_range.buttons[RangeParity.ODD].click()
        panel.ignored.setText("3-5")
        panel.ignored_range.buttons[RangeParity.EVEN].click()
        rule = panel.read_rule()
        self.assertEqual(rule.pages, "1-5|odd")
        self.assertEqual(rule.ignored, "3-5|even")
        self.assertTrue(panel.pages_range.buttons[RangeParity.ODD].isChecked())

    def test_dialog_selection_can_be_accepted_or_cancelled(self) -> None:
        dialog = PageRangeDialog(None, "Pages", "Select physical pages", text="all|even")
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.range_input.buttons[RangeParity.EVEN].isChecked())
        dialog.range_input.buttons[RangeParity.ODD].click()
        QtCore.QTimer.singleShot(0, dialog.accept)
        self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.field.text(), "all|odd")
        QtCore.QTimer.singleShot(0, dialog.reject)
        self.assertEqual(dialog.exec(), QtWidgets.QDialog.DialogCode.Rejected)


if __name__ == "__main__":
    unittest.main()
