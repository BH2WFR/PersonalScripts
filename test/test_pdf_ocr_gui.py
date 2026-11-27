"""Real worker preview/OCR checks and GUI state tests using generated scans."""

from collections.abc import Callable
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import pymupdf
from test_pdf_ocr import ROOT, RESULT
from personal_pdf_tools.ocr.app import OcrWindow
from personal_pdf_tools.common.navigation import PAGE_ROLE
from personal_pdf_tools.common.page_toolbar import PageToolbar
from utils.qt_styles import button_stylesheet
from utils import Pdf

ENTRY = ROOT / "tools/document-processing/pdf-ocr.py"


def wait_for(predicate: Callable[[], bool], timeout: float = 25) -> None:
    """Pump Qt through process I/O and debounce intervals without a fixed long sleep."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for OCR GUI.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class OcrGuiTests(unittest.TestCase):
    def test_model_manager_uses_serial_worker_and_protects_bundled_files(self) -> None:
        from personal_pdf_tools.ocr.model_dialog import ModelDialog
        window = self.window
        dialog = ModelDialog(window.runner, window._start, window)
        window.model_dialog = dialog
        try:
            dialog.show()
            dialog.refresh()
            wait_for(lambda: not window.runner.busy)
            self.assertEqual(dialog.tree.topLevelItemCount(), 13)
            self.assertFalse(dialog.download_button.isEnabled())
            self.assertFalse(dialog.delete_button.isEnabled())
            self.assertTrue(dialog.verify_button.isEnabled())
            dialog._action("verify")
            self.assertFalse(dialog.close_button.isEnabled())
            dialog.reject()
            self.assertTrue(dialog.isVisible())
            wait_for(lambda: not window.runner.busy)
            self.assertEqual(dialog.status.text(), "SHA-256 verified.")
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(3))
            self.assertTrue(dialog.download_button.isEnabled())
            self.assertIn("Korean", dialog._row()["title"])
            self.assertIn("MiB", dialog.summary.text())
            # Refresh preserves selection and does not start a network download.
            dialog.refresh()
            wait_for(lambda: not window.runner.busy)
            self.assertEqual(dialog._row()["key"], "korean")
        finally:
            wait_for(lambda: not window.runner.busy)
            window.model_dialog = None
            dialog.close()
            dialog.deleteLater()

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="ocr-gui-", dir=ROOT / "tmp")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "preferences"))
        self.source = self.folder / "source.pdf"
        with pymupdf.open() as scan, pymupdf.open() as doc:
            p = scan.new_page(width=400, height=200)
            p.insert_text((30, 90), "Highlight this text", fontsize=24)
            png = p.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            for _ in range(3):
                page = doc.new_page(width=400, height=200)
                page.insert_image(page.rect, stream=png)
            doc.set_toc([[1, "First", 1], [2, "Third", 3]])
            Pdf.save_new(doc, self.source)
        self.window = OcrWindow(ENTRY)
        self.window.show()

        def cleanup() -> None:
            wait_for(lambda: not self.window.runner.busy)
            self.window.close()
            self.window.deleteLater()
            QtWidgets.QApplication.processEvents()

        self.addCleanup(cleanup)
        self.window.open_path(self.source)
        self.settled()
        self.assertEqual(self.window.page_count, 3)

    def settled(self) -> None:
        wait_for(lambda: not self.window.runner.busy and not self.window.timer.isActive())

    def test_page_toolbar_separates_original_control_and_navigates(self) -> None:
        window = self.window
        toolbar = window.toolbar
        self.assertIsInstance(toolbar, PageToolbar)
        options = window.tool_toolbar
        self.assertIs(toolbar.parentWidget(), options.parentWidget())
        self.assertEqual(toolbar.y(), options.y())
        self.assertLess(toolbar.geometry().right(), options.x())
        self.assertFalse(toolbar.isAncestorOf(window.original))
        self.assertIs(options.widgetForAction(options.actions()[0]), window.original)
        self.assertFalse(toolbar.previous.isEnabled())
        self.assertEqual(toolbar.page_total.text(), "/ 3")
        toolbar.next.click()
        self.settled()
        self.assertEqual(window.current_page, 2)
        self.assertEqual(toolbar.page_number.value(), 2)
        self.assertTrue(toolbar.previous.isEnabled())
        self.assertEqual(window.export_button.styleSheet(), button_stylesheet("blue", window.export_button))

    def test_debounce_original_text_tab_and_cache_invalidation(self) -> None:
        window = self.window
        self.assertFalse(window.results)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(2)
            window.go_page(3)
            self.settled()
            self.assertEqual(start.call_count, 1)
            self.assertEqual(start.call_args.args[0]["operation"], "preview")
            self.assertEqual(start.call_args.args[0]["page"], 3)
        window.results[3] = RESULT
        window.original.setChecked(True)
        window.go_page(2)
        self.assertTrue(window.original.isChecked())
        self.settled()
        window.go_page(3)
        self.settled()
        window._update_text()
        self.assertTrue(window.text.isReadOnly())
        self.assertEqual(window.text.toPlainText(), RESULT.text)
        window.panel.color = QtGui.QColor("blue")
        window._appearance_changed()
        self.assertEqual(window.results[3], RESULT)
        window.panel.controls["dpi"].setValue(200)
        window._settings_changed()
        self.assertFalse(window.results)
        self.assertEqual(window.text.toPlainText(), "")

    def test_selected_page_and_bookmark_exclusions(self) -> None:
        window = self.window
        tree = window.navigation.pages
        tree.clearSelection()
        tree.topLevelItem(0).setSelected(True)
        tree.topLevelItem(2).setSelected(True)
        menu = QtWidgets.QMenu()
        point = tree.visualItemRect(tree.topLevelItem(0)).center()
        window._context_actions(menu, tree, point)
        menu.actions()[0].trigger()
        self.assertEqual(window.ignored, {0, 2})
        self.assertFalse(window.scan_button.isEnabled())
        self.assertEqual(window.navigation.page_items[1].text(2), "Not run")
        window._set_ignored([2], False)
        self.assertEqual(window.ignored, {0})
        tree = window.navigation.bookmarks
        window.navigation.setCurrentWidget(tree)
        tree.clearSelection()
        parent = tree.topLevelItem(0)
        parent.setSelected(True)
        menu = QtWidgets.QMenu()
        window._context_actions(menu, tree, tree.visualItemRect(parent).center())
        menu.actions()[1].trigger()
        self.assertFalse(window.ignored)  # Not the parent's descendant chapter range.
        self.assertEqual(window.panel.ignored_list.topLevelItemCount(), 0)

    def test_ignore_list_add_remove_and_invalid_batch(self) -> None:
        window = self.window
        window.panel.add_current.click()
        self.assertEqual(window.ignored, {0})
        with patch("personal_pdf_tools.ocr.app.PageRangeDialog.get_text", side_effect=[("999", True), ("1,3", True)]), \
             patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
            window.panel.add_pages.click()
            warning.assert_called_once()
        self.assertEqual(window.ignored, {0, 2})
        self.assertEqual(window.panel.ignored_list.topLevelItemCount(), 2)
        self.assertEqual(window.panel.ignored_list.topLevelItem(1).text(1), "Third")
        window.panel.ignored_list.topLevelItem(0).setSelected(True)
        window.panel.remove_pages.click()
        self.assertEqual(window.ignored, {2})
        window.panel.clear_pages.click()
        self.assertFalse(window.ignored)
        self.assertTrue(window.scan_button.isEnabled())

    def test_language_checkboxes_default_and_last_language_guard(self) -> None:
        panel = self.window.panel
        self.assertEqual(panel.selected_languages(), ("chinese", "english"))
        panel.language_list.item(0).setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(self.window.settings.languages, ("english",))
        panel.language_list.item(1).setCheckState(QtCore.Qt.CheckState.Unchecked)
        self.assertEqual(panel.selected_languages(), ("english",))
        panel.language_list.item(3).setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(self.window.settings.recognition_models(), ("korean",))
        panel.language_list.item(2).setCheckState(QtCore.Qt.CheckState.Checked)
        self.assertEqual(self.window.settings.recognition_models(), ("cjk", "korean"))

    def test_grouped_processing_settings_and_margin_cache(self) -> None:
        window = self.window
        panel = window.panel
        self.assertEqual([panel.tabText(i) for i in range(panel.count())], ["OCR", "Layout", "Preprocess", "Preview"])
        window.results[1] = RESULT
        panel.controls["margin_y"].setValue(10)
        window._settings_changed()
        self.assertEqual(window.results[1], RESULT)
        self.assertEqual(window.settings.margin_y, 10)
        panel.grayscale.setChecked(True)
        self.assertFalse(window.results)
        panel.tiling_group.setChecked(True)
        panel.contrast.setCurrentIndex(panel.contrast.findData("local"))
        self.assertTrue(panel.controls["contrast_clip"].isEnabled())
        self.assertTrue(window.settings.tiled)
        self.assertTrue(window.settings.grayscale)
        self.assertEqual(window.settings.contrast, "local")

    def test_real_process_recognition_and_blocked_navigation(self) -> None:
        window = self.window
        window._scan()
        self.assertTrue(window.runner.busy)
        window.go_page(2)
        self.assertEqual(window.current_page, 1)
        self.settled()
        self.assertIn("Highlight", window.results[1].text)
        self.assertIn("Highlight", window.text.toPlainText())
        self.assertFalse(window.original.isChecked())
        word_count = len(window.results[1].tokens)
        window.panel.english.setCurrentIndex(1)
        window._scan()
        self.settled()
        self.assertGreater(len(window.results[1].tokens), word_count)
        output = self.folder / "ocr.pdf"
        with patch("PySide6.QtWidgets.QMessageBox.information"):
            window._set_ignored([1, 2], True)
            window._start({"operation": "export", "output": str(output)})
            self.settled()
        with Pdf.open_document(output, interactive=False) as (doc, _):
            self.assertIn("Highlight", doc[0].get_text())
            self.assertEqual(doc[1].get_text(), "")
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())


if __name__ == "__main__":
    unittest.main()
