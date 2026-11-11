"""Exercise projects, real object exports and offscreen Qt preview orchestration.

Run with conda base: python -m unittest discover -s test -p test_pdf_binarize_gui.py.
Uses project tmp/ and generated PDFs; never opens the user's network book.
"""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import pymupdf
from PIL import Image, ImageDraw

from test_pdf_binarize import ROOT, make_source, page_image, workflow
from personal_pdf_tools.binarize.app import ADMIN_DROP_HINT, BinarizeWindow, Operation
from personal_pdf_tools.binarize.panel import SettingsPanel
from personal_pdf_tools.binarize.preview_cache import PreviewCache, PreviewFrame, PreviewState
from personal_pdf_tools.binarize.project import Config, DEFAULT_ID, Project, SKIP_ID
from personal_pdf_tools.binarize.worker import Cancelled, Worker, export_project
from personal_pdf_tools.common.jobs import JobRunner
from personal_pdf_tools.common.pdf_images import inspect_images
from personal_pdf_tools.common.preview_buffer import PreviewBuffer
from personal_pdf_tools.common.range_input import PageRangeDialog
from personal_pdf_tools.common.viewer import ViewMode

ENTRY = ROOT / "tools/document-processing/pdf-binarizer.py"


def wait_for(predicate: Callable[[], bool], timeout: float = 15) -> None:
    """Pump Qt events until a test predicate is true or the deadline expires."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for the GUI worker.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class ProjectTests(unittest.TestCase):
    """Verify portable files and shared-profile behavior against actual PDFs."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="pdf-gui-model-", dir=ROOT / "tmp")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "user-config"))
        self.source = self.folder / "source.pdf"
        make_source(self.source)
        self.project = Project.create(self.source, 3)

    def test_image_occurrences_report_codec_effective_dpi_and_position(self) -> None:
        path = self.folder / "placements.pdf"
        with Image.new("RGB", (200, 100), "white") as image, io.BytesIO() as encoded:
            image.save(encoded, format="JPEG")
            with pymupdf.open() as document:
                page = document.new_page(width=320, height=160)
                first = pymupdf.Rect(50, 60, 150, 110)
                second = pymupdf.Rect(200, 60, 300, 110)
                xref = page.insert_image(first, stream=encoded.getvalue())
                page.insert_image(second, xref=xref)
                document.save(path)
        with pymupdf.open(path) as document:
            images = inspect_images(document[0])
        self.assertEqual(len(images), 2)
        self.assertEqual([image.codec for image in images], ["JPEG", "JPEG"])
        self.assertEqual([image.position for image in images], [(50, 60, 150, 110), (200, 60, 300, 110)])
        self.assertAlmostEqual(images[0].dpi_x, 144)
        self.assertAlmostEqual(images[0].dpi_y, 144)
        self.assertAlmostEqual(images[0].bounds[0], 50 / 320)

    def test_profile_copies_are_independent_and_bulk_apply_is_atomic(self) -> None:
        project = self.project
        self.assertEqual(project.assignments, [DEFAULT_ID] * 3)
        identity = project.add_profile("Gray illustrations", DEFAULT_ID)
        project.assign(identity, "1,-1")
        values = project.profiles[identity].config.values()
        values.update({"mode": "sauvola", "regions.clean_background": True, "regions.mode": "gray4"})
        project.profiles[identity].config = Config.from_values(values)
        self.assertFalse(project.profiles[DEFAULT_ID].config.processing.regions.clean_background)
        previous = list(project.assignments)
        with self.assertRaises(ValueError):
            project.assign(identity, "1,4")
        self.assertEqual(project.assignments, previous)
        with self.assertRaises(ValueError):
            project.remove(DEFAULT_ID, identity)
        project.remove(identity, DEFAULT_ID)
        self.assertEqual(project.assignments, [DEFAULT_ID] * 3)

    def test_json_roundtrip_missing_source_and_bad_assignments(self) -> None:
        path = self.folder / "book.binarize.json"
        self.project.assign(SKIP_ID, "1,2")
        self.project.show_original = True
        self.project.auto_fit = False
        self.project.show_regions = True
        self.project.current_page = 2
        identity = self.project.add_profile("Grayscale", DEFAULT_ID)
        values = self.project.profiles[identity].config.values()
        values.update({"regions.color_text_mode": "color8", "regions.color_text_contrast": 1.7,
                       "regions.color_text_whiten": True, "regions.color_text_white_point": 228,
                       "regions.whiten": True, "regions.white_point": 220})
        self.project.profiles[identity].config = Config.from_values(values)
        self.project.assign(identity, "3")
        self.project.save(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["pdf"], "source.pdf")
        self.assertNotIn("password", raw)
        self.assertEqual(Project.load(path).to_data(), self.project.to_data())
        self.assertEqual(Project.load(path).assignments[:2], [SKIP_ID, SKIP_ID])
        self.source.rename(self.folder / "relocated.pdf")
        self.assertFalse(Project.load(path).source.exists())
        raw["page_profiles"][2] = "missing"
        with self.assertRaises(ValueError):
            Project.from_data(raw, self.folder)
        raw = self.project.to_data()
        raw["profiles"][0]["settings"]["dpi"] = True
        with self.assertRaises(ValueError):
            Project.from_data(raw, self.folder)

    def test_shared_image_different_profiles_skip_and_native_features(self) -> None:
        source = self.folder / "shared.pdf"
        with Image.new("L", (120, 80), 150) as image, io.BytesIO() as stream:
            ImageDraw.Draw(image).text((10, 30), "Read me", fill=10)
            image.save(stream, format="PNG")
            with pymupdf.open() as document:
                first = document.new_page(width=120, height=100)
                xref = first.insert_image((0, 20, 120, 100), stream=stream.getvalue())
                first.insert_text((4, 12), "Native text", fontsize=8, color=(1, 0, 0))
                for _ in range(2):
                    page = document.new_page(width=120, height=100)
                    page.insert_image((0, 20, 120, 100), xref=xref)
                    page.insert_text((4, 12), "Native text", fontsize=8, color=(1, 0, 0))
                document[0].add_text_annot((100, 5), "Keep comment")
                document[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(0, 0, 30, 15), "page": 2})
                document.set_toc([[1, "First", 1], [2, "Last", 3]])
                document.save(source)
        project = Project.create(source, 3)
        project.assign(SKIP_ID, "1")
        project.profiles[DEFAULT_ID].config = Config(72, 100)
        identity = project.add_profile("More black", DEFAULT_ID)
        project.profiles[identity].config = Config(72, 200)
        project.assign(DEFAULT_ID, "2")
        project.assign(identity, "3")
        target = self.folder / "result.pdf"
        export_project(project, target)
        with pymupdf.open(source) as original, pymupdf.open(target) as result:
            before_toc, after_toc = original.get_toc(False), result.get_toc(False)
            for row in before_toc + after_toc:
                row[3].pop("xref", None)
            self.assertEqual(after_toc, before_toc)
            self.assertEqual(result[0].get_links()[0]["page"], 2)
            self.assertEqual(next(result[0].annots()).info["content"], "Keep comment")
            for index in range(3):
                self.assertEqual(result[index].get_text(), original[index].get_text())
            self.assertEqual(page_image(result, 0).tobytes(), page_image(original, 0).tobytes())
            self.assertNotEqual(page_image(result, 1).tobytes(), page_image(result, 2).tobytes())
            self.assertEqual(result[1].get_images()[0][4], 1)
        with self.assertRaises(FileExistsError):
            export_project(project, target)

    def test_cancel_does_not_publish_and_mismatched_count_is_rejected(self) -> None:
        target = self.folder / "result.pdf"
        marker = self.folder / "cancel"
        marker.touch()
        with self.assertRaises(Cancelled):
            export_project(self.project, target, cancel=marker)
        self.assertFalse(target.exists())
        marker.unlink()
        self.project.assign(DEFAULT_ID, "1-3")
        def cancel_after_page(message: dict[str, object]) -> None:
            if message.get("done") == 1:
                marker.touch()
        with self.assertRaises(Cancelled):
            export_project(self.project, target, cancel=marker, progress=cancel_after_page)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.folder.glob(".pdf-tools-*")))
        self.project.page_count = 4
        with self.assertRaises(ValueError):
            export_project(self.project, target)
        self.assertFalse(target.exists())

    def test_pause_after_page_stop_preserves_existing_output(self) -> None:
        target = self.folder / "result.pdf"
        target.write_bytes(b"previous output")
        pause, cancel = self.folder / "pause", self.folder / "cancel"
        states: list[bool] = []

        def control(message: dict[str, object]) -> None:
            if message.get("done") == 1:
                pause.touch()
            if message.get("paused") is True:
                states.append(True)
                cancel.touch()

        with self.assertRaises(Cancelled):
            export_project(self.project, target, progress=control, pause=pause, cancel=cancel, overwrite=True)
        self.assertEqual(states, [True])
        self.assertEqual(target.read_bytes(), b"previous output")
        self.assertFalse(list(self.folder.glob(".pdf-tools-*")))

    def test_pause_before_save_resumes_and_completes(self) -> None:
        target, pause = self.folder / "result.pdf", self.folder / "pause"
        states: list[bool] = []

        def control(message: dict[str, object]) -> None:
            if message.get("stage") == "Writing PDF":
                pause.touch()
            if "paused" in message:
                states.append(bool(message["paused"]))
                if message["paused"]:
                    self.assertFalse(target.exists())
                    pause.unlink()

        export_project(self.project, target, progress=control, pause=pause)
        self.assertEqual(states, [True, False])
        with pymupdf.open(target) as result:
            self.assertEqual(result.page_count, 3)

    def test_preview_is_repeatable_and_matches_full_export(self) -> None:
        project = self.project
        project.profiles[DEFAULT_ID].config = Config(72, 180)
        project.current_page = 2
        worker = Worker()
        self.addCleanup(worker.close)
        request = {"operation": "preview", "project": project.to_data()}
        result = worker.run(request, lambda message: None)
        original = self.source.read_bytes()
        project.show_original = True
        other = worker.run({"operation": "preview", "project": project.to_data()}, lambda message: None)
        self.assertNotEqual(result["png"], other["png"])
        self.assertEqual(worker.run(request, lambda message: None), result)
        self.assertEqual(self.source.read_bytes(), original)
        project.show_original = False
        target = self.folder / "result.pdf"
        export_project(project, target)
        with pymupdf.open(target) as document:
            import base64
            with Image.open(io.BytesIO(base64.b64decode(result["png"]))) as shown:
                self.assertEqual(document[2].get_pixmap(dpi=300).samples, shown.convert("RGB").tobytes())

    def test_dpi_policy_roundtrip_and_safe_overwrite(self) -> None:
        self.assertEqual(Config.from_values({}).processing.dpi_policy.value, "cap")
        config = Config.from_values({"dpi_policy": "target"})
        self.assertEqual(Config.from_values(config.values()), config)
        target = self.folder / "existing.pdf"
        target.write_bytes(b"retain old output")
        with patch("personal_pdf_tools.binarize.worker._publish", side_effect=OSError("Failed publish")):
            with self.assertRaises(OSError):
                export_project(self.project, target, overwrite=True)
        self.assertEqual(target.read_bytes(), b"retain old output")
        export_project(self.project, target, overwrite=True)
        with pymupdf.open(target) as result:
            self.assertEqual(result.page_count, 3)
        with self.assertRaises(FileExistsError):
            export_project(self.project, self.source, overwrite=True)


class GuiTests(unittest.TestCase):
    """Exercise real Qt events and one actual subprocess opening/rendering path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="pdf-gui-ui-", dir=ROOT / "tmp")
        notice = patch.object(QtWidgets.QMessageBox, "information")
        self.notice = notice.start()
        self.addCleanup(notice.stop)
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "user-config"))
        self.source = self.folder / "source.pdf"
        make_source(self.source)
        self.window = BinarizeWindow(ENTRY)
        self.window.project = Project.create(self.source, 3)
        self.window.page_number.setRange(1, 3)
        self.window.labels = ["1", "2", "3"]
        self.window.navigation.load(self.window.labels, [(1, "First", 1), (2, "Last", 3)])
        self.window._load_profiles()
        self.window._load_current_page()
        self.window.show()
        self.application.processEvents()
        self.addCleanup(self.close_window)

    def close_window(self) -> None:
        self.window.preview_timer.stop()
        if self.window.runner.busy:
            wait_for(lambda: not self.window.runner.busy)
        self.window.dirty = False
        self.window.close()
        self.application.processEvents()

    def test_profile_input_dialog_ranges_and_label_tooltips(self) -> None:
        window = self.window
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("1", True)) as prompt:
            window._add_profile()
        self.assertEqual(prompt.call_args.kwargs["text"], "1")
        identity = window.project.assignments[0]
        with patch.object(PageRangeDialog, "get_text", return_value=("all|odd", True)):
            window._apply_profile_pages(identity)
        self.assertEqual(window.project.assignments, [identity, DEFAULT_ID, identity])
        item = window.profile_list.topLevelItem(2)
        self.assertEqual(item.text(1), "1,3")
        original = list(window.project.assignments)
        with patch.object(PageRangeDialog, "get_text", return_value=("2,99|odd", True)), patch.object(window, "_error") as error:
            window._apply_profile_pages(identity)
        error.assert_called_once()
        self.assertEqual(window.project.assignments, original)
        window.preview_timer.stop()
        with patch.object(QtWidgets.QMenu, "exec"):
            point = window.profile_list.visualItemRect(window.profile_list.topLevelItem(1)).center()
            QtTest.QTest.mouseClick(window.profile_list.viewport(), QtCore.Qt.MouseButton.RightButton, pos=point)
        self.assertEqual(window.project.assignments, original)
        for key in ("dpi", "dpi_policy", "threshold", "k"):
            self.assertTrue(window.settings.labels[key].toolTip())
        self.assertGreaterEqual(len(window.settings.findChildren(QtWidgets.QGroupBox)), 8)

    def test_colored_text_controls_follow_detection_and_whitening_switches(self) -> None:
        panel = self.window.settings
        panel.set_config(Config.from_values({"regions.enabled": True, "regions.color_text_mode": "color4",
                                             "regions.color_text_whiten": True}))
        self.assertTrue(panel.editors["regions.color_text_contrast"].isEnabled())
        self.assertTrue(panel.editors["regions.color_text_white_point"].isEnabled())
        panel.set_config(Config.from_values({"regions.enabled": True}))
        self.assertFalse(panel.editors["regions.color_text_contrast"].isEnabled())
        self.assertFalse(panel.editors["regions.color_text_white_point"].isEnabled())
        self.assertTrue(panel.editors["regions.color_text_whiten"].isEnabled())
        panel.set_config(Config())
        self.assertFalse(panel.editors["regions.color_text_mode"].isEnabled())
        self.assertFalse(panel.editors["regions.color_text_whiten"].isEnabled())

    def test_image_whitening_controls_commit_and_support_shaded_panels(self) -> None:
        panel = self.window.settings
        panel.set_config(Config.from_values({"regions.enabled": True}))
        self.assertTrue(panel.editors["regions.whiten"].isEnabled())
        self.assertFalse(panel.editors["regions.white_point"].isEnabled())
        panel.editors["regions.whiten"].setChecked(True)
        self.assertTrue(panel.config.processing.regions.whiten)
        self.assertTrue(panel.editors["regions.white_point"].isEnabled())
        self.assertFalse(panel.config.processing.regions.color_text_whiten)
        panel.set_config(Config.from_values({"mode": "sauvola", "regions.clean_background": True,
                                            "regions.whiten": True}))
        self.assertTrue(panel.editors["regions.white_point"].isEnabled())
        panel.set_config(Config())
        self.assertFalse(panel.editors["regions.whiten"].isEnabled())

    def test_apply_all_pages_and_hide_default_profile_ranges(self) -> None:
        window = self.window
        default_item = window.profile_list.topLevelItem(0)
        self.assertEqual(default_item.text(1), "")
        self.assertIn("3 page(s)", default_item.toolTip(1))
        identity = window.project.add_profile("Special", DEFAULT_ID)
        window._load_profiles()
        window._load_current_page()
        with patch.object(PageRangeDialog, "get_text", return_value=("ALL", True)) as dialog:
            window._apply_profile_pages(identity)
        self.assertIn("all", dialog.call_args.args[2])
        self.assertEqual(window.project.assignments, [identity] * 3)
        self.assertEqual(window.profile_list.topLevelItem(0).text(1), "")
        self.assertEqual(window.profile_list.topLevelItem(2).text(1), "1-3")
        with patch.object(PageRangeDialog, "get_text", return_value=("none", True)), \
                patch.object(window, "_error") as error:
            window._apply_profile_pages(DEFAULT_ID)
        error.assert_called_once()
        self.assertEqual(window.project.assignments, [identity] * 3)

    def test_close_pdf_releases_handles_resets_and_can_reopen(self) -> None:
        window = self.window
        window.open_path(self.source)
        wait_for(lambda: not window.runner.busy and window._displayed_page is not None)
        window.dirty = False
        window._close_pdf()
        self.application.processEvents()
        self.assertTrue(window.isVisible())
        self.assertIsNone(window.project)
        self.assertEqual(window.profile_list.topLevelItemCount(), 0)
        self.assertFalse(window.close_pdf_button.isEnabled())
        moved = self.folder / "moved.pdf"
        self.source.rename(moved)
        window.open_path(moved)
        wait_for(lambda: not window.runner.busy and window._displayed_page is not None)
        self.assertEqual(window.project.source, moved)

    def test_output_dialog_numbers_defaults_and_requires_explicit_overwrite(self) -> None:
        from personal_pdf_tools.common.file_actions import choose_pdf_output
        target = self.folder / "output.pdf"
        target.write_bytes(b"Existing")
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")) as dialog:
            self.assertIsNone(choose_pdf_output(self.window, self.source, target))
        self.assertEqual(Path(dialog.call_args.args[2]).name, "output_1.pdf")
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(target), "PDF")), \
                patch.object(QtWidgets.QMessageBox, "exec", return_value=0):
            self.assertIsNone(choose_pdf_output(self.window, self.source, target))
            with patch.object(QtWidgets.QMessageBox, "clickedButton",
                              new=lambda message: next(button for button in message.buttons() if button.text() == "Overwrite")):
                self.assertEqual(choose_pdf_output(self.window, self.source, target), (target, True))
        self.assertEqual(target.read_bytes(), b"Existing")
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(self.source), "PDF")), \
                patch.object(QtWidgets.QMessageBox, "warning") as warning:
            self.assertIsNone(choose_pdf_output(self.window, self.source, target))
        warning.assert_called_once()

    def test_navigation_coalesces_and_busy_blocks_all_submissions(self) -> None:
        with patch.object(self.window.runner, "start", return_value=True) as start:
            self.window.go_page(1)
            QtTest.QTest.qWait(100)
            self.window.go_page(2)
            QtTest.QTest.qWait(200)
            self.assertEqual(start.call_count, 0)
            QtTest.QTest.qWait(150)
            self.assertEqual(start.call_count, 1)
            self.assertEqual(start.call_args.args[0]["project"]["view"]["page"], 3)
        self.window.runner.busy = True
        self.window._busy_changed(True)
        self.window.go_page(0)
        self.assertEqual(self.window.project.current_page, 2)
        self.assertFalse(self.window.navigation.isEnabled())
        self.assertFalse(self.window.runner.start({"operation": "inspect"}))
        self.assertIsNotNone(QtWidgets.QApplication.overrideCursor())
        self.window.runner.busy = False
        self.window._busy_changed(False)
        self.assertIsNone(QtWidgets.QApplication.overrideCursor())

    def test_profile_selection_assignment_navigation_and_original_warning(self) -> None:
        self.window.project.assign(SKIP_ID, "1,2")
        self.window._load_current_page()
        self.window.original.setChecked(True)
        self.window.preview_timer.stop()
        default_item = self.window.profile_list.topLevelItem(0)
        self.window.profile_list.setCurrentItem(default_item)
        self.window.preview_timer.stop()
        self.assertEqual(self.window.project.assignments[0], DEFAULT_ID)
        self.assertIn("#b06b00", self.window.original.styleSheet())
        before = list(self.window.project.assignments)
        self.window.go_page(1)
        self.window.preview_timer.stop()
        self.assertEqual(self.window.project.assignments, before)
        self.assertTrue(self.window.original.isChecked())
        self.assertEqual(self.window.profile_list.currentItem().data(0, QtCore.Qt.ItemDataRole.UserRole), SKIP_ID)
        self.assertFalse(self.window.settings.widget(0).isEnabled())
        self.window.go_page(2)
        self.window.preview_timer.stop()
        self.assertIn("#b06b00", self.window.original.styleSheet())

    def test_numeric_settings_wait_for_commit_and_sliders_wait_for_release(self) -> None:
        panel = self.window.settings
        self.window.project.assign(DEFAULT_ID, "1")
        self.window._load_current_page()
        spy = QtTest.QSignalSpy(panel.configChanged)
        spin = panel.editors["threshold"]
        spin.setValue(151)
        self.assertEqual(spy.count(), 0)
        spin.editingFinished.emit()
        self.window.preview_timer.stop()
        self.assertEqual(spy.count(), 1)
        slider = panel.sliders["threshold"]
        slider.setValue(160)
        self.assertEqual(spy.count(), 1)
        slider.sliderReleased.emit()
        self.window.preview_timer.stop()
        self.assertEqual(spy.count(), 2)

    def test_real_worker_open_preview_and_repeated_profile_render(self) -> None:
        self.window.project = None
        self.window.open_path(self.source)
        wait_for(lambda: self.window.project is not None and self.window._displayed_page == 0 and not self.window.runner.busy)
        self.assertEqual(self.window.project.assignments, [DEFAULT_ID] * 3)
        self.window.go_page(2)
        wait_for(lambda: self.window._displayed_page == 2 and not self.window.runner.busy)
        self.assertIn("Processed page 3", self.window.status.text())
        self.window.original.setChecked(True)
        wait_for(lambda: "Original page 3" in self.window.status.text() and not self.window.runner.busy)
        self.assertTrue(self.window.original.isChecked())
        output = self.folder / "gui-export.pdf"
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
            self.window._export(False)
        self.assertFalse(self.window.next_button.isEnabled())
        wait_for(lambda: not self.window.runner.busy)
        self.assertTrue(output.is_file())
        self.assertIn("Before:", self.notice.call_args.args[2])
        self.assertIn("After:", self.notice.call_args.args[2])
        with pymupdf.open(output) as result:
            self.assertEqual([page.get_images()[0][4] for page in result], [1, 1, 1])

    def test_real_worker_pause_resume_stop_and_edit_again(self) -> None:
        window = self.window
        window.preview_timer.stop()
        window._preview_requested = False
        for stop in (False, True):
            output = self.folder / f"pause-{stop}.pdf"
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
                window._export(False)
            # Request pause before pumping events / allowing the worker to start.
            window.pause_button.click()
            pause, cancel = window.runner.pause_marker, window.runner.cancel_marker
            self.assertTrue(pause.exists())
            wait_for(lambda: window.runner.paused)
            self.assertTrue(window.runner.busy)
            self.assertFalse(window._cursor_busy)
            self.assertEqual(window.pause_button.text(), "Resume")
            self.assertTrue(window.cancel_button.isEnabled())
            self.assertFalse(window.settings.isEnabled())
            value = window.progress_bar.value()
            QtTest.QTest.qWait(180)
            self.assertEqual(window.progress_bar.value(), value)
            self.assertFalse(output.exists())
            if stop:
                window.cancel_button.click()
            else:
                window.pause_button.click()
            wait_for(lambda: not window.runner.busy)
            self.assertFalse(pause.exists())
            self.assertFalse(cancel.exists())
            self.assertFalse(window.runner.paused)
            self.assertFalse(window._cursor_busy)
            self.assertTrue(window.settings.isEnabled())
            self.assertTrue(window.export_button.isEnabled())
            self.assertTrue(window.pause_button.isVisible())
            self.assertFalse(window.pause_button.isEnabled())
            self.assertEqual(output.exists(), not stop)
            if stop:
                self.assertIn("cancelled", window.status.text())
                window.settings.editors["threshold"].setValue(160)
                window.settings.editors["threshold"].editingFinished.emit()
                self.assertEqual(window.project.profiles[DEFAULT_ID].config.threshold, 160)
                window.preview_timer.stop()
                window._preview_requested = False
        # Same persistent worker and project remain usable after Stop.
        output = self.folder / "after-stop.pdf"
        with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(output), "")):
            window._export(False)
        wait_for(lambda: not window.runner.busy)
        self.assertTrue(output.is_file())

    def test_cancelled_save_dialog_preserves_pending_preview_without_rendering_inside(self) -> None:
        self.window.project.assign(DEFAULT_ID, "1")
        self.window._load_current_page()

        def cancel_dialog(*args: object, **kwargs: object) -> tuple[str, str]:
            self.assertFalse(self.window.preview_timer.isActive())
            QtTest.QTest.qWait(30)
            self.assertFalse(self.window.runner.busy)
            return "", ""

        for action in (lambda: self.window._save_project(True), lambda: self.window._export(False)):
            self.window._schedule_preview(0)
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName", side_effect=cancel_dialog):
                self.window._invoke(action)
            self.assertTrue(self.window.preview_timer.isActive())
            self.assertTrue(self.window._preview_requested)
            self.window.preview_timer.stop()

    def test_project_relocation_restores_profiles_and_marks_new_path_unsaved(self) -> None:
        project = Project.create(self.folder / "missing.pdf", 3)
        identity = project.add_profile("Special", DEFAULT_ID)
        project.profiles[identity].config = Config(72, 210)
        project.assign(identity, "3")
        project.current_page = 2
        project.show_original = True
        path = self.folder / "relocated.json"
        project.save(path)
        with patch.object(QtWidgets.QFileDialog, "getOpenFileName", return_value=(str(self.source), "")):
            self.window.open_path(path)
        wait_for(lambda: self.window.project_path == path and self.window._displayed_page == 2 and not self.window.runner.busy)
        self.assertEqual(self.window.project.source, self.source)
        self.assertEqual(self.window.project.assignments[2], identity)
        self.assertEqual(self.window.settings.config.threshold, 210)
        self.assertTrue(self.window.original.isChecked())
        self.assertTrue(self.window.dirty)

    def test_page_count_mismatch_does_not_adopt_project(self) -> None:
        project = Project.create(self.source, 4)
        path = self.folder / "wrong-count.json"
        project.save(path)
        before = self.window.project
        with patch.object(QtWidgets.QMessageBox, "exec", return_value=0) as dialog:
            self.window.open_path(path)
            wait_for(lambda: not self.window.runner.busy)
        dialog.assert_called_once()
        self.assertIs(self.window.project, before)

    def test_corrupt_project_does_not_replace_active_session(self) -> None:
        invalid = self.folder / "invalid.json"
        invalid.write_text('{"version": 999}', encoding="utf-8")
        before = self.window.project
        with patch.object(QtWidgets.QMessageBox, "critical") as error:
            self.window.open_path(invalid)
        error.assert_called_once()
        self.assertIs(self.window.project, before)

    def test_pdf_drop_on_preview_opens_through_the_window(self) -> None:
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(self.source))])
        entered = QtGui.QDragEnterEvent(QtCore.QPoint(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                        QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        dropped = QtGui.QDropEvent(QtCore.QPointF(20, 20), QtCore.Qt.DropAction.CopyAction, mime,
                                   QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        with patch.object(self.window.file_drops, "open_path") as opened:
            QtWidgets.QApplication.sendEvent(self.window.viewer.viewport(), entered)
            self.assertTrue(entered.isAccepted())
            QtWidgets.QApplication.sendEvent(self.window.viewer.viewport(), dropped)
        opened.assert_called_once_with(self.source)

    def test_unc_file_drop_through_native_window_routing(self) -> None:
        # External desktop drags first reach QWindow, then a child or its parent.
        source = Path("//example.invalid/share/Chinese 书籍/file with spaces.pdf")
        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(str(source))])
        point = self.window.viewer.viewport().mapTo(self.window, QtCore.QPoint(20, 20))
        with patch.object(self.window.file_drops, "open_path") as opened:
            for event in (QtGui.QDragEnterEvent(point, QtCore.Qt.DropAction.CopyAction, mime,
                             QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier),
                          QtGui.QDragMoveEvent(point, QtCore.Qt.DropAction.CopyAction, mime,
                             QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier),
                          QtGui.QDropEvent(QtCore.QPointF(point), QtCore.Qt.DropAction.CopyAction, mime,
                             QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)):
                QtWidgets.QApplication.sendEvent(self.window.windowHandle(), event)
                self.assertTrue(event.isAccepted())
        opened.assert_called_once_with(source)

    def test_compact_layout_and_page_jump_on_enter_or_focus_loss(self) -> None:
        window = self.window
        self.assertTrue(window.left.isAncestorOf(window.open_pdf_button))
        self.assertEqual(window.previous_button.text(), "")
        self.assertEqual(window.next_button.text(), "")
        self.assertLessEqual(window.next_button.width(), 30)
        self.assertEqual(window.page_number.width(), 48)
        self.assertEqual(window.page_total.text(), "/ 3")
        self.assertEqual(sum(action.isSeparator() for action in window.view_toolbar.actions()), 2)
        self.assertGreater(window.profile_list.height(), 80)
        toolbar_bottom = window.view_toolbar.mapTo(window, window.view_toolbar.rect().bottomLeft()).y()
        self.assertLessEqual(window.viewer.mapTo(window, QtCore.QPoint()).y(), toolbar_bottom + 8)
        self.assertTrue(window.progress_bar.isHidden())
        self.assertTrue(window.cancel_button.isVisible())
        self.assertFalse(window.cancel_button.isEnabled())
        self.assertFalse(window.left.isAncestorOf(window.task_buttons))
        self.assertFalse(window.pause_button.icon().isNull())
        self.assertFalse(window.cancel_button.icon().isNull())
        window.page_number.setFocus()
        self.application.processEvents()
        QtTest.QTest.keyClick(window.page_number, QtCore.Qt.Key.Key_A, QtCore.Qt.KeyboardModifier.ControlModifier)
        QtTest.QTest.keyClicks(window.page_number, "3")
        self.assertEqual(window.project.current_page, 0)
        QtTest.QTest.keyClick(window.page_number, QtCore.Qt.Key.Key_Return)
        self.assertEqual(window.project.current_page, 2)
        window.preview_timer.stop()

        QtTest.QTest.keyClick(window.page_number, QtCore.Qt.Key.Key_A, QtCore.Qt.KeyboardModifier.ControlModifier)
        QtTest.QTest.keyClicks(window.page_number, "1")
        window.original.setFocus()
        self.application.processEvents()
        self.assertEqual(window.project.current_page, 0)
        window.preview_timer.stop()

    def test_actual_profile_original_refresh_and_stale_editor_flag(self) -> None:
        window = self.window
        window.project.assign(SKIP_ID, "1")
        window._load_current_page()
        window._schedule_preview(0)
        wait_for(lambda: window._displayed_page == 0 and not window.runner.busy)
        original = window.viewer._original.toImage()
        window.profile_list.setCurrentItem(window.profile_list.topLevelItem(0))
        wait_for(lambda: "Processed page 1" in window.status.text() and not window.runner.busy)
        processed = window.viewer._original.toImage()
        self.assertNotEqual(processed, original)
        window.settings.editing = True  # Former text editor has already lost focus.
        window.viewer.setFocus()
        window.original.setChecked(True)
        wait_for(lambda: "Original page 1" in window.status.text() and not window.runner.busy)
        self.assertEqual(window.viewer._original.toImage(), original)
        window.original.setChecked(False)
        wait_for(lambda: "Processed page 1" in window.status.text() and not window.runner.busy)
        self.assertEqual(window.viewer._original.toImage(), processed)
        window.profile_list.setCurrentItem(window.profile_list.topLevelItem(1))
        wait_for(lambda: "no-processing" in window.status.text() and not window.runner.busy)
        self.assertEqual(window.viewer._original.toImage(), original)

    def test_viewer_zoom_auto_fit_and_focus_scoped_navigation(self) -> None:
        window = self.window
        pixmap = QtGui.QPixmap(900, 1200)
        pixmap.fill(QtCore.Qt.GlobalColor.white)
        window.viewer.set_pixmap(pixmap, ("book", 0))
        window.zoom.setValue(37.5)
        window.zoom.editingFinished.emit()
        self.assertAlmostEqual(window.viewer.transform().m11(), .375)
        self.assertEqual(window.zoom.suffix(), " %")
        window.viewer.set_pixmap(pixmap, ("book", 1))
        self.assertEqual(window.viewer.mode, ViewMode.PAGE)
        window.auto_fit.setChecked(False)
        window.viewer.set_zoom(75)
        window.viewer.set_pixmap(pixmap, ("book", 2))
        self.assertAlmostEqual(window.viewer.transform().m11(), .75)
        window.viewer.setFocus()
        QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_PageDown)
        self.assertEqual(window.project.current_page, 1)
        window.preview_timer.stop()
        QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_Right)
        self.assertEqual(window.project.current_page, 2)
        window.preview_timer.stop()
        self.assertEqual(window.navigation.selected_pages(), (2,))
        window.navigation.pages.setFocus()
        QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Up)
        self.assertEqual(window.project.current_page, 1)
        self.assertEqual(window.navigation.selected_pages(), (1,))
        window.preview_timer.stop()
        QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Right)
        self.assertEqual(window.project.current_page, 2)
        self.assertEqual(window.navigation.selected_pages(), (2,))
        window.preview_timer.stop()
        window.region_path.setFocus()
        QtTest.QTest.keyClick(window.region_path, QtCore.Qt.Key.Key_Left)
        self.assertEqual(window.project.current_page, 2)
        window.navigation.pages.setFocus()
        QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Left)
        wait_for(lambda: not window.runner.busy and not window.preview_timer.isActive())
        self.assertEqual(window.project.current_page, 1)
        self.assertEqual(window.navigation.selected_pages(), (1,))
        self.assertTrue(window.navigation.pages.hasFocus())
        with patch.object(window.runner, "busy", True):
            QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Right)
            self.assertEqual(window.project.current_page, 1)
            self.assertEqual(window.navigation.selected_pages(), (1,))

    def test_image_tab_tracks_view_and_profile_and_blue_outline_can_be_cleared(self) -> None:
        window = self.window
        window.navigation.setCurrentIndex(2)
        window._schedule_preview(0)
        wait_for(lambda: window._displayed_page == 0 and not window.runner.busy)
        tree = window.navigation.images
        self.assertGreater(tree.topLevelItemCount(), 0)
        self.assertIn("144.0 × 72.0 pt", window.navigation.page_size_label.text())
        self.assertIn("72 DPI", window.navigation.scan_dpi_label.text())
        self.assertIn("300 DPI", window.navigation.preview_dpi_label.text())
        processed_codec = tree.topLevelItem(0).text(1)
        processed_dpi = float(tree.topLevelItem(0).text(2))
        item = tree.topLevelItem(0)
        point = QtCore.QPoint(15, tree.visualItemRect(item).center().y())
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNotNone(window.viewer._image_highlight)
        self.assertEqual(window.viewer._image_highlight.pen().color(), QtGui.QColor("#1677ff"))
        bounds = window.preview_cache.get(PreviewState.from_project(window.project)).images[0].bounds
        self.assertAlmostEqual(window.viewer._image_highlight.rect().x(),
                               bounds[0] * window.viewer._bounds.width(), delta=1)
        window.viewer.set_regions([(.1, .2, .3, .4)])
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNone(window.viewer._image_highlight)
        self.assertEqual(len(window.viewer._region_items), 1)
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNotNone(window.viewer._image_highlight)
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                pos=QtCore.QPoint(15, tree.viewport().height() - 5))
        self.assertIsNone(window.viewer._image_highlight)
        QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)
        self.assertIsNotNone(window.viewer._image_highlight)
        QtTest.QTest.keyClick(tree, QtCore.Qt.Key.Key_Escape)
        self.assertIsNone(window.viewer._image_highlight)
        window.original.setChecked(True)
        wait_for(lambda: not window._preview_requested and not window.runner.busy)
        self.assertEqual(tree.topLevelItem(0).text(1), "JPEG")
        self.assertIn("144.0 × 72.0 pt", window.navigation.page_size_label.text())
        self.assertIn("72 DPI", window.navigation.scan_dpi_label.text())
        self.assertIsNone(window.viewer._image_highlight)
        window.original.setChecked(False)
        self.assertEqual(tree.topLevelItem(0).text(1), processed_codec)
        identity = window.project.add_profile("Double resolution", DEFAULT_ID)
        window.project.profiles[identity].config = Config.from_values({"dpi": 72, "upscale": 2})
        window.project.assign(identity, "1")
        window._load_current_page()
        window._schedule_preview(0)
        self.assertEqual(tree.topLevelItemCount(), 0)
        self.assertEqual(window.navigation.page_size_label.text(), "Page: —")
        wait_for(lambda: not window._preview_requested and not window.runner.busy
                 and tree.topLevelItemCount() > 0)
        self.assertGreater(float(tree.topLevelItem(0).text(2)), processed_dpi)
        self.assertIn("144 DPI", window.navigation.scan_dpi_label.text())
        self.assertIn("300 DPI", window.navigation.preview_dpi_label.text())
        window.go_page(1)
        self.assertEqual(window.navigation.page_size_label.text(), "Page: —")
        wait_for(lambda: window._displayed_page == 1 and not window.runner.busy)
        self.assertNotIn("144.0 × 72.0 pt", window.navigation.page_size_label.text())
        self.assertIn("DPI", window.navigation.preview_dpi_label.text())

    def test_original_transport_reuses_document_and_red_boxes_are_overlay_only(self) -> None:
        window = self.window
        window.project.assign(DEFAULT_ID, "1")
        window.project.show_regions = True
        region_path = self.folder / "regions.json"
        region_path.write_text(json.dumps({"version": 1, "sha256": workflow.regions._identity(self.source),
            "page_count": 3, "pages": {"1": [{"rect": [.25, .1, .75, .7], "mode": "keep"}]}}), encoding="utf-8")
        window.project.output.region_input = region_path
        window._load_current_page()
        window._schedule_preview(0)
        wait_for(lambda: window._displayed_page == 0 and not window.runner.busy)
        pixels = window.viewer._original.toImage()
        self.assertEqual(len(window.viewer._region_items), 1)
        rect = window.viewer._region_items[0].rect()
        self.assertAlmostEqual(rect.x(), window.viewer._bounds.width() * .25, delta=2)
        window.show_regions.setChecked(False)
        self.assertFalse(window.viewer._region_items)
        self.assertEqual(window.viewer._original.toImage(), pixels)
        self.assertFalse(window.runner.busy)
        window.go_page(1)
        wait_for(lambda: window._displayed_page == 1 and not window.runner.busy)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(0)
            window.show_regions.setChecked(True)
            self.assertEqual(window._displayed_page, 0)
            self.assertEqual(len(window.viewer._region_items), 1)
            self.assertEqual(window.viewer._original.toImage(), pixels)
            start.assert_not_called()
        window.show_regions.setChecked(False)
        worker = Worker()
        buffer = PreviewBuffer()
        try:
            project = window.project
            project.show_original = True
            request = {"operation": "preview", "project": project.to_data(), "pixel_buffer": buffer.name}
            with patch("personal_pdf_tools.binarize.worker.Pdf.open_document", wraps=workflow.Pdf.open_document) as opened:
                first = worker.run(request, lambda message: None)
                copied = buffer.read(first["width"], first["height"]).toImage()
                project.current_page = 1
                worker.run({**request, "project": project.to_data()}, lambda message: None)
                self.assertEqual(opened.call_count, 1)
                self.assertEqual(copied.size(), pixels.size())
                self.assertNotIn("png", first)
        finally:
            worker.close()
            buffer.close()

    def test_unloaded_file_actions_remain_enabled_and_elevation_is_explained(self) -> None:
        self.window.project = None
        self.window._refresh_enabled()
        self.assertTrue(self.window.open_pdf_button.isEnabled())
        self.assertTrue(self.window.open_project_button.isEnabled())
        self.assertFalse(self.window.save_project_button.isEnabled())
        self.assertFalse(self.window.profile_list.isEnabled())
        self.window._elevated = True
        self.window._title()
        self.assertIn("[Administrator]", self.window.windowTitle())
        self.assertIn("Open PDF", ADMIN_DROP_HINT)

    def test_cache_page_turn_is_synchronous_and_new_settings_replace_previous_result(self) -> None:
        window = self.window
        window.project.profiles[DEFAULT_ID].config = Config(72, 90)
        window._load_current_page()
        window._schedule_preview(0)
        wait_for(lambda: window._displayed_page == 0 and not window.runner.busy)
        before = window.viewer._original.toImage()
        old_state = PreviewState.from_project(window.project)
        window.go_page(1)
        wait_for(lambda: window._displayed_page == 1 and not window.runner.busy)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(0)
            self.assertEqual(window._displayed_page, 0)  # No event-loop turn or timer wait.
            self.assertFalse(window.preview_timer.isActive())
            self.assertFalse(window._preview_requested)
            self.assertFalse(window.runner.busy)
            self.assertIsNone(QtWidgets.QApplication.overrideCursor())
            self.assertEqual(window.viewer._original.toImage(), before)
            start.assert_not_called()
            # Cancels an uncached page's pending timer when returning to a hit.
            window.go_page(2)
            self.assertTrue(window.preview_timer.isActive())
            window.go_page(0)
            self.assertFalse(window.preview_timer.isActive())
            start.assert_not_called()

        window._settings_changed(Config(72, 220))
        wait_for(lambda: not window._preview_requested and not window.runner.busy)
        after = window.viewer._original.toImage()
        self.assertNotEqual(after, before)
        self.assertIsNone(window.preview_cache.get(old_state))
        self.assertEqual(window.preview_cache.get(PreviewState.from_project(window.project)).pixmap.toImage(), after)
        # Page 2 still carries the old shared-profile settings; it must be rebuilt.
        window.go_page(1)
        self.assertTrue(window.preview_timer.isActive())
        self.assertEqual(window._displayed_page, 0)
        wait_for(lambda: window._displayed_page == 1 and not window.runner.busy)
        window.go_page(0)
        self.assertEqual(window._displayed_page, 0)
        self.assertEqual(window.viewer._original.toImage(), after)

    def test_original_turns_skip_delay_and_processed_original_caches_stay_separate(self) -> None:
        window = self.window
        window._schedule_preview(0)
        wait_for(lambda: window._displayed_page == 0 and not window.runner.busy)
        processed = window.viewer._original.toImage()
        window.original.setChecked(True)
        wait_for(lambda: not window._preview_requested and not window.runner.busy)
        original = window.viewer._original.toImage()
        self.assertNotEqual(original, processed)
        window.go_page(1)
        self.assertEqual(window.preview_timer.interval(), 0)
        wait_for(lambda: window._displayed_page == 1 and not window.runner.busy)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(0)
            self.assertEqual(window.viewer._original.toImage(), original)
            window.original.setChecked(False)
            self.assertEqual(window.viewer._original.toImage(), processed)
            window.original.setChecked(True)
            window._settings_changed(Config(72, 120))
            self.assertEqual(window.viewer._original.toImage(), original)
            self.assertIn("#b06b00", window.original.styleSheet())
            start.assert_not_called()
        window.original.setChecked(False)
        self.assertTrue(window.preview_timer.isActive())
        wait_for(lambda: not window._preview_requested and not window.runner.busy)

    def test_ctrl_shift_selection_applies_profile_even_when_already_current(self) -> None:
        window = self.window
        window.project.assign(SKIP_ID, "3")
        window._load_current_page()
        tree = window.navigation.pages
        window.navigation.select_page(0)
        def click_page(index: int, modifier: QtCore.Qt.KeyboardModifier) -> None:
            point = tree.visualItemRect(window.navigation.page_items[index]).center()
            QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.MouseButton.LeftButton, modifier, point)
        with patch.object(window.runner, "start", return_value=True) as start:
            click_page(2, QtCore.Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(window.navigation.selected_pages(), (0, 2))
            self.assertFalse(window.preview_timer.isActive())
            item = window.profile_list.topLevelItem(0)
            QtTest.QTest.mouseClick(window.profile_list.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                   pos=window.profile_list.visualItemRect(item).center())
            window.preview_timer.stop()
            self.assertEqual(window.project.assignments, [DEFAULT_ID] * 3)
            self.assertEqual(window.navigation.selected_pages(), (0, 2))
            window._preview_requested = False
            window.navigation.select_page(0)
            click_page(2, QtCore.Qt.KeyboardModifier.ShiftModifier)
            self.assertEqual(window.navigation.selected_pages(), (0, 1, 2))
            self.assertFalse(window.preview_timer.isActive())
            window.profile_list.setCurrentItem(window.profile_list.topLevelItem(1))
            window.preview_timer.stop()
            self.assertEqual(window.project.assignments, [SKIP_ID] * 3)
            self.assertFalse(window.settings.widget(0).isEnabled())
            self.assertEqual(window.navigation.selected_pages(), (0, 1, 2))
            start.assert_not_called()
        window.go_page(1)
        window.preview_timer.stop()
        self.assertEqual(window.navigation.selected_pages(), (1,))

    def test_preview_cache_bounds_replacement_and_region_matching(self) -> None:
        pixmap = QtGui.QPixmap(10, 10)
        pixmap.fill(QtCore.Qt.GlobalColor.white)
        state = PreviewState.from_project(self.window.project)
        first = PreviewFrame(state, pixmap, ((.1, .2, .3, .4),), True)
        cache = PreviewCache(max_bytes=first.size * 3, max_pages=2)
        cache.put(first)
        cache.put(replace(first, state=replace(state, page=1)))
        self.assertIs(cache.get(state), first)  # Refresh page 1's recency.
        cache.put(replace(first, state=replace(state, page=2)))
        self.assertIsNone(cache.get(replace(state, page=1)))
        new_state = replace(state, config=Config(72, 120))
        updated = replace(first, state=new_state)
        cache.put(updated)
        self.assertIsNone(cache.get(state))
        self.assertIs(cache.get(new_state), updated)
        self.assertEqual(cache.size, first.size * 2)
        original_state = replace(state, original=True)
        cache.put(replace(first, state=original_state))
        self.assertIsNotNone(cache.get(replace(original_state, config=Config(72, 120))))
        self.assertIsNone(cache.get(replace(original_state, config=Config(72, 120), show_regions=True)))
        self.assertIsNotNone(cache.get(replace(original_state, show_regions=True)))
        self.assertIsNone(cache.get(replace(state, region_input=self.folder / "different.json")))
        cache.max_bytes = first.size * 2
        cache.put(replace(first, state=replace(state, page=2, original=True)))
        self.assertLessEqual(cache.size, cache.max_bytes)
        self.assertIsNone(cache.get(new_state))
        cache.clear()
        self.assertEqual(cache.size, 0)

    def test_opening_another_document_clears_cached_pages(self) -> None:
        window = self.window
        window.go_page(2)
        wait_for(lambda: window._displayed_page == 2 and not window.runner.busy)
        state = PreviewState.from_project(window.project)
        self.assertIsNotNone(window.preview_cache.get(state))
        another = self.folder / "another.pdf"
        make_source(another)
        window.open_path(another)
        wait_for(lambda: window.project.source == another and window._displayed_page == 0 and not window.runner.busy)
        self.assertIsNone(window.preview_cache.get(state))


if __name__ == "__main__":
    unittest.main()
