"""Generated-PDF splitter model, worker and real offscreen desktop regression checks."""

from contextlib import closing
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import time
from collections.abc import Callable
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import pymupdf

import test_pdf_split_pages as engine_tests
from test_pdf_split_pages import ROOT
from personal_pdf_tools.split_pages.app import SplitWindow, STATUS_WHOLE, STATUS_CUSTOM
from personal_pdf_tools.split_pages.engine import build_plan, _split_document
from personal_pdf_tools.split_pages.model import Axis, Box, PageOverride, Settings, page_boxes, move_divider
from personal_pdf_tools.split_pages.worker import Worker

ENTRY = ROOT / "tools/document-processing/pdf-page-splitter.py"


def wait_for(predicate: Callable[[], bool], timeout: float = 20) -> None:
    """Pump Qt while a real worker runs; fail with a deadline rather than hang."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for the PDF split worker.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class SplitGuiTests(unittest.TestCase):
    """Exercise output geometry and real GUI state using only generated input PDFs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="split-gui-", dir=ROOT / "tmp")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.enterContext(patch("utils.config.ConfigStore.directory", return_value=self.folder / "user-config"))
        self.source = self.folder / "sample scan.pdf"
        with pymupdf.open() as doc:
            for number in range(3):
                page = doc.new_page(width=600, height=400)
                page.insert_text((30, 60), f"Original page {number + 1}", fontsize=25)
                page.insert_text((330, 60), "Right half", fontsize=25)
                page.draw_rect(pymupdf.Rect(10, 10, 590, 390), color=(0, 0, 0))
                page.draw_line((300, 10), (300, 390), color=(.5, .5, .5))
            doc.set_toc([[1, "First spread", 1], [2, "Second spread", 2], [1, "Last spread", 3]])
            doc.save(self.source)

    @staticmethod
    def settled(window: SplitWindow) -> None:
        """Wait for the immediate timer and the single background task to finish."""
        wait_for(lambda: not window.runner.busy and not window.timer.isActive())

    def window(self) -> SplitWindow:
        """Create and authenticate a real worker-backed desktop, with deterministic cleanup."""
        window = SplitWindow(ENTRY)
        window.show()

        def cleanup() -> None:
            self.settled(window)
            window.dirty = False
            window.close()
            window.deleteLater()
            QtWidgets.QApplication.processEvents()

        self.addCleanup(cleanup)
        window.open_path(self.source)
        self.settled(window)
        self.assertEqual(window.page_count, 3)
        return window

    def test_multistrip_rotations_and_single_custom_crop_match_pixels(self) -> None:
        for rotation in (0, 90, 180, 270):
            for axis in Axis:
                with self.subTest(rotation=rotation, axis=axis), pymupdf.open() as output:
                    # Reuse the established colored image fixture, including CropBox offsets.
                    with engine_tests.PdfSplitTests.make_document(self, rotation, True) as source:
                        settings = Settings(count=4, axis=axis, order="3,1,4,2")
                        plan = build_plan(source, settings, {2: PageOverride(boxes=(Box(.1, .2, .3, .4),))})
                        expected = [source[0].get_pixmap(clip=piece.clip).samples for piece in plan[0]]
                        _split_document(source, output, plan)
                        self.assertEqual(output.page_count, 5)
                        for index, page in enumerate(list(output)[:4]):
                            self.assertEqual(page.get_pixmap().samples, expected[index])
                        image_xrefs = {output[i].get_images()[0][0] for i in range(4)}
                        self.assertEqual(len(image_xrefs), 1)
                        self.assertAlmostEqual(output[4].rect.width, 20 if axis == Axis.LEFT_RIGHT else 80)
                        self.assertAlmostEqual(output[4].rect.height, 100 if axis == Axis.LEFT_RIGHT else 25)

    def test_rules_validation_and_override_priority(self) -> None:
        settings = Settings(count=3, start=2, end=2, reverse=True)
        settings.validate(3)
        special = PageOverride(boxes=(Box(.1, .1, .9, .9),))
        overrides = {1: special, 2: PageOverride(keep=True)}
        self.assertEqual(page_boxes(settings, overrides, 1, 3), special.boxes)
        self.assertEqual(page_boxes(settings, overrides, 2, 3), (Box(0, 0, 1, 1),))
        self.assertEqual(page_boxes(settings, overrides, 3, 3), (Box(0, 0, 1, 1),))
        self.assertEqual(Settings.from_data(settings.to_data()), settings)
        self.assertEqual(PageOverride.from_data(special.to_data()), special)
        for invalid in (replace(settings, count=0), replace(settings, order="1,1,2"),
                        replace(settings, order="4,2,1"), replace(settings, start=3), replace(settings, end=4)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                invalid.validate(3)
        boxes = Settings(reverse=True).boxes()
        moved = move_divider(boxes, Axis.LEFT_RIGHT, (1, 0), .6)
        self.assertAlmostEqual(moved[0].x0, .6)
        self.assertAlmostEqual(moved[0].x1, 1.1)
        self.assertAlmostEqual(moved[1].x1 - moved[1].x0, .5)
        with self.assertRaises(ValueError):
            move_divider(boxes, Axis.LEFT_RIGHT, (1, 0), float("nan"))
        with pymupdf.open(self.source) as source, self.assertRaises(ValueError):
            build_plan(source, Settings(), {1: PageOverride(boxes=(Box(0, 0, 1.01, 1),))})

    def test_padding_centering_annotations_and_destinations_after_save(self) -> None:
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), engine_tests.PdfSplitTests.make_document(self, rotation, True) as source:
                page = source[0]
                annotation = page.add_rect_annot(pymupdf.Rect(25, 20, 95, 65))
                annotation.set_colors(stroke=(0, 0, 0), fill=(1, 0, 1))
                annotation.update()
                width, height = page.rect.width, page.rect.height
                # Both crops are smaller than equal paper; the first crosses the
                # left/top source edges, the second stays inside with centered margins.
                boxes = (Box(-10 / width, -10 / height, 30 / width, 50 / height),
                         Box(30 / width, 20 / height, 70 / width, 80 / height))
                override = PageOverride(boxes=boxes, canvas=(.5, 1))
                pixel = page.get_pixmap()
                samples = pixel.samples
                source.set_toc([[1, "Inside second crop", 1, {"kind": pymupdf.LINK_GOTO, "page": 0,
                               "to": pymupdf.Point(50, 40)}]])
                # Save explicit PDF-space XYZ to avoid PyMuPDF's rotated CropBox setter issue.
                pdf_point = engine_tests.splitter._pdf_point(page, pymupdf.Point(50, 40))
                source.xref_set_key(source.get_outline_xrefs()[0], "A/D",
                    f"[{page.xref} 0 R /XYZ {pdf_point.x} {pdf_point.y} 0]")
                source[1].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(5, 5, 25, 15),
                    "page": 0, "to": pdf_point * page.transformation_matrix})
                with pymupdf.open(stream=source.tobytes(), filetype="pdf") as reopened, pymupdf.open() as output:
                    plan = build_plan(reopened, Settings(), {1: override, 2: PageOverride(keep=True)})
                    _split_document(reopened, output, plan)
                    path = self.folder / f"padded-{rotation}.pdf"
                    output.save(path)
                with pymupdf.open(path) as result:
                    for index, piece in enumerate(plan[0]):
                        actual = result[index].get_pixmap()
                        self.assertEqual((actual.width, actual.height), (int(width / 2), int(height)))
                        expected = bytearray(b"\xff" * (actual.width * actual.height * 3))
                        for y in range(actual.height):
                            sy = int(piece.viewport.y0 + y)
                            for x in range(actual.width):
                                sx = int(piece.viewport.x0 + x)
                                point = pymupdf.Point(sx + .5, sy + .5)
                                if 0 <= sx < pixel.width and 0 <= sy < pixel.height and point in piece.clip:
                                    target = (y * actual.width + x) * 3
                                    origin = (sy * pixel.width + sx) * 3
                                    expected[target:target + 3] = samples[origin:origin + 3]
                        self.assertEqual(actual.samples, bytes(expected))
                    destination = pymupdf.Point(50, 40) - plan[0][1].viewport.tl
                    self.assertEqual(result.get_toc()[0][2], 2)
                    self.assertEqual(result.get_toc(False)[0][3]["to"], destination)
                    self.assertEqual(result[2].get_links()[0]["to"], destination)
                    self.assertEqual(result[0].get_images()[0][0], result[1].get_images()[0][0])

    def test_fully_outside_crop_is_blank_and_source_is_unchanged(self) -> None:
        with pymupdf.open(self.source) as source, pymupdf.open() as output:
            override = PageOverride(boxes=(Box(2, 2, 2.5, 3),), canvas=(.5, 1))
            plan = build_plan(source, Settings(), {1: override})
            _split_document(source, output, plan)
            image = output[0].get_pixmap()
            self.assertEqual((image.width, image.height), (300, 400))
            self.assertEqual(image.samples, b"\xff" * (300 * 400 * 3))

    def test_padded_widgets_remain_registered_and_outside_fields_are_removed(self) -> None:
        for outside in (False, True):
            with self.subTest(outside=outside), pymupdf.open() as source, pymupdf.open() as output:
                page = source.new_page(width=200, height=100)
                widget = pymupdf.Widget()
                widget.field_name = "Sample"
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
                widget.field_value = "retained"
                widget.rect = pymupdf.Rect(20, 20, 180, 60)
                page.add_widget(widget)
                boxes = ((Box(2, 2, 2.5, 3),) if outside else
                         (Box(.05, .1, .45, .9), Box(.55, .1, .95, .9)))
                plan = build_plan(source, Settings(), {1: PageOverride(boxes=boxes, canvas=(.5, 1))})
                _split_document(source, output, plan)
                data = output.tobytes()
            with pymupdf.open(stream=data, filetype="pdf") as result:
                fields = result.xref_get_key(result.pdf_catalog(), "AcroForm/Fields")[1]
                for page in result:
                    widgets = list(page.widgets())
                    self.assertEqual(len(widgets), 0 if outside else 1)
                    for widget in widgets:
                        self.assertIn(f"{widget.xref} 0 R", fields)
                        self.assertEqual(widget.field_value, "retained")

    def test_page_overrides_markers_cache_and_keyboard_navigation(self) -> None:
        window = self.window()
        self.assertEqual(len(window.findChildren(QtWidgets.QGroupBox)), 2)
        self.assertIn("600.00 × 400.00", window.page_info.text())
        self.assertEqual(len(window.viewer.crop_items), 4)
        self.assertEqual(window.viewer.crop_items[0].opacity(), .5)
        self.assertEqual([item.text(3) for item in window.navigation.page_items], ["1", "3", "5"])
        original_pixels = window._shown.pixmap.cacheKey()
        window.panel.position.setValue(320)
        window.panel.position.editingFinished.emit()
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_CUSTOM)
        self.assertAlmostEqual(window.overrides[1].boxes[0].x1, 320 / 600)
        self.assertEqual(window._shown.pixmap.cacheKey(), original_pixels)
        self.assertFalse(window.runner.busy)
        self.assertFalse(window.timer.isActive())
        window.panel.keep.setChecked(True)
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_WHOLE)
        self.assertFalse(window.viewer.crop_items)
        window.panel.keep.setChecked(False)
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_CUSTOM)
        window.go_page(2)
        self.settled(window)
        self.assertEqual(window.panel.position.value(), 300)
        window.panel.keep.setChecked(True)
        self.assertEqual(window.navigation.page_items[1].text(2), STATUS_WHOLE)
        self.assertEqual([item.text(3) for item in window.navigation.page_items], ["1", "3", "4"])
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.go_page(1)
            self.assertFalse(window.timer.isActive())
            self.assertEqual(window.panel.position.value(), 320)
            window.viewer.setFocus()
            QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_PageDown)
            self.assertEqual(window.current_page, 2)
            self.assertTrue(window.panel.keep.isChecked())
            start.assert_not_called()
            self.assertEqual(window.navigation.selected_pages(), (1,))
            window.navigation.pages.setFocus()
            QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Up)
            self.assertEqual(window.current_page, 1)
            self.assertEqual(window.navigation.selected_pages(), (0,))
            QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Right)
            self.assertEqual(window.current_page, 2)
            self.assertEqual(window.navigation.selected_pages(), (1,))
            start.assert_not_called()
        QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Down)
        self.settled(window)
        self.assertEqual(window.current_page, 3)
        self.assertEqual(window.navigation.selected_pages(), (2,))
        self.assertTrue(window.navigation.pages.hasFocus())
        QtTest.QTest.keyClick(window.navigation.pages, QtCore.Qt.Key.Key_Up)
        self.settled(window)
        window._reset_page()
        self.assertEqual(window.navigation.page_items[1].text(2), "")
        self.assertEqual(len(window.viewer.crop_items), 4)

    def test_global_rules_leave_custom_boxes_and_unchanged_edits_alone(self) -> None:
        window = self.window()
        window.panel.count.setValue(3)
        window.panel.count.editingFinished.emit()
        self.assertEqual(len(window.viewer.crop_items), 6)
        self.assertEqual(window.settings.count, 3)
        for spin in window.panel.coordinates:
            spin.editingFinished.emit()
        window.panel.position.editingFinished.emit()
        self.assertEqual(window.overrides, {})
        window.panel.coordinates[2].setValue(180)
        window.panel.coordinates[2].editingFinished.emit()
        custom = window.overrides[1]
        window.panel.count.setValue(2)
        window.panel.count.editingFinished.emit()
        self.assertEqual(window.overrides[1], custom)
        self.assertEqual(len(window.viewer.crop_items), 6)
        window.panel.start.setValue(2)
        window.panel.start.editingFinished.emit()
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_CUSTOM)
        window._reset_page()
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_WHOLE)
        window.panel.keep.setChecked(False)
        self.assertEqual(window.navigation.page_items[0].text(2), STATUS_CUSTOM)
        self.assertEqual(len(window._boxes()), 2)
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            window.panel.order.setText("1,1")
            window.panel.order.editingFinished.emit()
            warning.assert_called_once()
        self.assertEqual(window.settings.order, "")

    def test_coordinate_nudges_bounds_busy_guard_and_real_export(self) -> None:
        window = self.window()
        before = self.source.read_bytes()
        window.panel.selection.setCurrentIndex(1)
        window.panel.coordinates[2].setValue(280)
        window.panel.coordinates[2].editingFinished.emit()
        window.panel.selection.setCurrentIndex(0)
        window.panel._nudge_box(0, 10)
        self.assertAlmostEqual(window.overrides[1].boxes[0].x0 * 600, 10)
        self.assertAlmostEqual(window.overrides[1].boxes[1].x1, 1 + 10 / 600)
        window.panel.selection.setCurrentIndex(1)
        window.panel._nudge_box(1, 10)
        self.assertAlmostEqual(window.overrides[1].boxes[0].y0, 10 / 400)
        self.assertAlmostEqual(window.overrides[1].boxes[1].y0, 0)
        custom = window.overrides[1]
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            window.panel.coordinates[2].setValue(310)
            window.panel.coordinates[2].editingFinished.emit()
            warning.assert_called_once()
        self.assertEqual(window.overrides[1], custom)
        window.go_page(2)
        self.settled(window)
        window.panel.keep.setChecked(True)
        target = self.folder / "result.pdf"
        with patch("personal_pdf_tools.split_pages.app.choose_pdf_output", return_value=(target, False)), \
                patch.object(QtWidgets.QMessageBox, "information") as complete:
            window._export()
            self.assertTrue(window.runner.busy)
            window.go_page(3)
            self.assertEqual(window.current_page, 2)
            self.assertFalse(window.runner.start({"operation": "inspect"}))
            self.settled(window)
            complete.assert_called_once()
        self.assertFalse(window.dirty)
        with pymupdf.open(target) as result:
            self.assertEqual(result.page_count, 5)
            self.assertAlmostEqual(result[0].rect.width, 300)
            self.assertAlmostEqual(result[2].rect.width, 600)
            self.assertIn("Original page 2", result[2].get_text())
            self.assertEqual(result.get_toc()[1][2], 3)
            self.assertFalse(result.get_page_labels())
        self.assertEqual(self.source.read_bytes(), before)

    def test_combined_crop_selector_resize_buttons_and_wrapped_parameter_hints(self) -> None:
        window = self.window()
        panel = window.panel
        self.assertEqual([panel.selection.itemText(i) for i in range(panel.selection.count())], ["All", "1", "2"])
        self.assertEqual(panel.selected_index(), -1)
        self.assertFalse(hasattr(panel, "move_mode"))
        QtTest.QTest.mouseClick(panel.coordinate_buttons[2][0], QtCore.Qt.MouseButton.LeftButton)
        QtTest.QTest.mouseClick(panel.coordinate_buttons[3][0], QtCore.Qt.MouseButton.LeftButton)
        for box in window.overrides[1].boxes:
            self.assertAlmostEqual((box.x1 - box.x0) * 600, 290)
            self.assertAlmostEqual((box.y1 - box.y0) * 400, 390)
        panel.selection.setCurrentIndex(2)
        first = window.overrides[1].boxes[0]
        QtTest.QTest.mouseClick(panel.coordinate_buttons[2][1], QtCore.Qt.MouseButton.LeftButton)
        self.assertEqual(window.overrides[1].boxes[0], first)
        second = window.overrides[1].boxes[1]
        self.assertAlmostEqual((second.x1 - second.x0) * 600, 300)
        self.assertEqual(window.overrides[1].canvas, (.5, 1))
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            before = window.overrides[1]
            QtTest.QTest.mouseClick(panel.coordinate_buttons[2][1], QtCore.Qt.MouseButton.LeftButton)
            self.assertEqual(window.overrides[1], before)
            warning.assert_called_once()
        for editor in (panel.count, panel.axis, panel.order, panel.reverse, panel.start, panel.end,
                       panel.keep, panel.reset, panel.selection, panel.divider, panel.position, *panel.coordinates):
            self.assertTrue(editor.toolTip())
        labels = {label.text(): label for label in panel.findChildren(QtWidgets.QLabel)}
        self.assertEqual(labels["Width"].toolTip(), panel.coordinates[2].toolTip())
        label = labels["Width"]
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, QtCore.QPoint(2, 2), label.mapToGlobal(QtCore.QPoint(2, 2)))
        QtWidgets.QApplication.sendEvent(label, event)
        self.assertTrue(window.tooltips.popup.isVisible())
        self.assertLessEqual(window.tooltips.popup.width(), 250)
        self.assertGreater(window.tooltips.popup.document.firstBlock().layout().lineCount(), 1)

    def test_worker_preview_export_collision_and_count_mismatch(self) -> None:
        target = self.folder / "existing.pdf"
        target.write_bytes(b"preserve existing output")
        request = {"operation": "export", "path": str(self.source), "output": str(target),
                   "page_count": 3, "settings": Settings().to_data()}
        with closing(Worker()) as worker:
            preview = worker.run({"operation": "preview", "path": str(self.source), "page": 2})
            self.assertEqual(preview["page_width"], 600)
            self.assertTrue(preview["png"])
            with self.assertRaises((ValueError, FileExistsError)):
                worker.run(request)
            with self.assertRaisesRegex(ValueError, "page count changed"):
                worker.run({**request, "page_count": 4})
        self.assertEqual(target.read_bytes(), b"preserve existing output")


if __name__ == "__main__":
    unittest.main()
