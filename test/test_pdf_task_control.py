"""Exercise shared task controls, real GUI workers and cancelled staged saves.

Uses generated PDFs and offscreen Qt only. Run with the project's conda Python:
    python -m unittest discover -s test -p test_pdf_task_control.py
"""

import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtTest, QtWidgets
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *

TOOLS = ROOT / "tools/document-processing"
runpy.run_path(str(TOOLS / "pdf-binarizer.py"))["load_app"]("common.task_control")
from personal_pdf_tools.common.jobs import JobRunner
from personal_pdf_tools.common.task_control import Cancelled, TaskControl
from personal_pdf_tools.bookmarks.app import BookmarksWindow
from personal_pdf_tools.font_replace.app import FontReplaceWindow
from personal_pdf_tools.font_replace.model import ReplacementRule
from personal_pdf_tools.font_replace.worker import Worker as FontWorker
from personal_pdf_tools.split_pages.app import SplitWindow


def wait_for(predicate: Callable[[], bool], timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for task control state.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class TaskControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="task-control-")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "user-config"))
        self.source = self.folder / "source.pdf"
        with pymupdf.open() as document:
            for number in range(3):
                page = document.new_page(width=300, height=300)
                page.insert_text((20, 30), f"Page {number + 1}")
            document.save(self.source)

    @staticmethod
    def idle(window: QtWidgets.QMainWindow) -> bool:
        timer = getattr(window, "timer", None)
        return not window.runner.busy and (timer is None or not timer.isActive())

    def close_window(self, window: QtWidgets.QMainWindow) -> None:
        window.runner.stop()
        wait_for(lambda: self.idle(window))
        window.dirty = False
        window.close()
        window.deleteLater()
        self.application.processEvents()

    def test_gui_export_pause_stop_resume_and_reuse(self) -> None:
        """All migrated windows use the same controls and keep edits after Stop."""
        for window_class, entry in ((SplitWindow, "pdf-page-splitter.py"),
                                    (FontReplaceWindow, "pdf-font-replacer.py"),
                                    (BookmarksWindow, "pdf-bookmark-editor.py")):
            with self.subTest(tool=entry), patch.object(QtWidgets.QMessageBox, "information"):
                window = window_class(TOOLS / entry)
                self.addCleanup(self.close_window, window)
                window.show()
                window.open_path(self.source)
                wait_for(lambda: self.idle(window))
                controls = window.task_buttons
                self.assertTrue(controls.isVisible())
                self.assertFalse(window.left.isAncestorOf(controls))
                self.assertGreaterEqual(controls.mapTo(window, QtCore.QPoint()).y(),
                                        window.viewer.mapTo(window, window.viewer.rect().bottomLeft()).y())
                self.assertFalse(controls.pause_button.isEnabled())
                self.assertFalse(controls.stop_button.isEnabled())
                self.assertFalse(controls.pause_button.icon().isNull())
                self.assertFalse(controls.stop_button.icon().isNull())
                pause_icon = controls.pause_button.icon().cacheKey()
                if isinstance(window, FontReplaceWindow):
                    window.rules = [ReplacementRule(color_only=True, color="#123456")]
                output = self.folder / f"{entry}.pdf"
                output.write_bytes(b"existing output")
                results: list[dict] = []
                window.runner.completed.connect(results.append)
                for stop in (True, False):
                    # A fresh worker cannot finish before the pause marker is written.
                    window.runner.shutdown()
                    with patch(f"{window.__module__}.choose_pdf_output", return_value=(output, True)):
                        window._export()
                    controls = window.task_buttons
                    controls.pause_button.click()
                    marker = window.runner.pause_marker
                    wait_for(lambda: window.runner.paused)
                    self.assertFalse(window._cursor_busy)
                    self.assertTrue(window.runner.busy)
                    self.assertFalse(window.export_button.isEnabled())
                    self.assertEqual(controls.pause_button.text(), "Resume")
                    self.assertNotEqual(controls.pause_button.icon().cacheKey(), pause_icon)
                    self.assertTrue(window.progress_bar.isVisible())
                    self.assertEqual(output.read_bytes(), b"existing output")
                    (controls.stop_button if stop else controls.pause_button).click()
                    wait_for(lambda: self.idle(window))
                    self.assertFalse(marker.exists())
                    self.assertFalse(window._cursor_busy)
                    self.assertTrue(window.export_button.isEnabled())
                    self.assertTrue(controls.isVisible())
                    self.assertFalse(controls.pause_button.isEnabled())
                    self.assertFalse(controls.stop_button.isEnabled())
                    self.assertEqual(controls.pause_button.icon().cacheKey(), pause_icon)
                    self.assertEqual(results[-1]["kind"], "cancelled" if stop else "exported")
                    if stop:
                        self.assertEqual(output.read_bytes(), b"existing output")
                with Pdf.open_document(output, interactive=False) as (document, _):
                    self.assertGreaterEqual(document.page_count, 3)

    def test_cancel_during_save_never_publishes_stage(self) -> None:
        cancel = self.folder / "stop"
        control = TaskControl(cancel)
        save = Pdf.save_new

        def finish_then_cancel(*args: object, **kwargs: object) -> None:
            save(*args, **kwargs)
            cancel.touch()

        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                cancel.unlink(missing_ok=True)
                output = self.folder / f"cancelled-{overwrite}.pdf"
                if overwrite:
                    output.write_bytes(b"keep")
                with Pdf.open_document(self.source, interactive=False) as (document, _):
                    with patch.object(Pdf, "save_new", side_effect=finish_then_cancel), self.assertRaises(Cancelled):
                        control.save(document, output, self.source, overwrite=overwrite)
                self.assertEqual(output.read_bytes() if output.exists() else None, b"keep" if overwrite else None)
                self.assertEqual(list(self.folder.glob(".pdf-tools-*")), [])

    def test_font_scan_can_stop_and_restart(self) -> None:
        runner = JobRunner(TOOLS / "pdf-font-replacer.py")
        results: list[dict] = []
        runner.completed.connect(results.append)
        try:
            runner.start({"operation": "scan", "path": str(self.source), "pages": "all"})
            runner.toggle_pause()
            wait_for(lambda: runner.paused)
            runner.stop()
            wait_for(lambda: not runner.busy)
            self.assertEqual(results[-1]["kind"], "cancelled")
            runner.start({"operation": "scan", "path": str(self.source), "pages": "all"})
            wait_for(lambda: not runner.busy)
            self.assertEqual(results[-1]["names"], ["Helvetica"])
        finally:
            runner.stop()
            wait_for(lambda: not runner.busy)
            runner.shutdown()

    def test_invalid_request_does_not_allocate_controls(self) -> None:
        runner = JobRunner(TOOLS / "pdf-page-splitter.py")
        with self.assertRaises(ValueError):
            runner.start({"operation": "export", "invalid": float("nan")})
        self.assertFalse(runner.busy)
        self.assertIsNone(runner.pause_marker)
        self.assertIsNone(runner._controls)

    def test_cancelled_catalog_does_not_cache_partial_results(self) -> None:
        cancel = self.folder / "stop"
        paths = [self.folder / "one.ttf", self.folder / "two.ttf"]

        def stop_after_file(message: dict) -> None:
            if message.get("done") == 1:
                cancel.touch()

        worker = FontWorker(stop_after_file)
        try:
            with patch.object(Font, "system_font_paths", return_value=paths), \
                    patch.object(Font, "read_catalog", return_value=[]) as read:
                with self.assertRaises(Cancelled):
                    worker.run({"operation": "catalog", "cancel": str(cancel)})
                self.assertIsNone(worker.catalog)
                self.assertEqual(read.call_count, 1)
                cancel.unlink()
                worker.progress = None
                reply = worker.run({"operation": "catalog"})
                self.assertEqual(reply["kind"], "fonts")
                self.assertEqual(read.call_count, 3)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
