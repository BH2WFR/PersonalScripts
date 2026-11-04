"""Generated-font tests for font GUI rules, worker isolation and preview refresh.

Run with conda Python: -m unittest discover -s test -p test_pdf_font_replace*.py.
No user PDF or installed font catalog is needed; Qt uses the offscreen platform.
"""

from contextlib import closing
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import time
from typing import Callable
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtTest, QtWidgets
import pymupdf

from test_pdf_font_replace import ROOT, make_font
from utils import *
from personal_pdf_tools.font_replace.app import FontReplaceWindow
from personal_pdf_tools.font_replace.model import ReplacementRule
from personal_pdf_tools.font_replace.engine import _Embedding, _font_name, _page_font_aliases
from personal_pdf_tools.font_replace.worker import Worker, _font_details
from personal_pdf_tools.common.protocol import Json

ENTRY = ROOT / "tools/document-processing/pdf-font-replace.py"


def wait_for(predicate: Callable[[], bool], timeout: float = 20) -> None:
    """Pump Qt until background work finishes, failing instead of hanging a test."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for font replacement worker.")
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(10)


class FontGuiTests(unittest.TestCase):
    """Use the same generated fixture through direct worker and real QProcess UI."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="font-gui-", dir=ROOT / "tmp")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.font = self.folder / "fixture.ttf"
        make_font(self.font)
        self.face = Font.read_faces(self.font)[0]
        self.rule = ReplacementRule(names=("Helvetica",), faces={FontStyle.REGULAR: self.face})
        self.source = self.folder / "source.pdf"
        with pymupdf.open() as doc:
            for text in ("First page", "Second page"):
                page = doc.new_page(width=300, height=300)
                page.insert_text((30, 60), text, fontsize=14)
                page.insert_text((30, 100), "Keep Times", fontname="tiro", fontsize=10)
            doc.set_toc([[1, "Opening", 1], [2, "Second", 2]])
            doc[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(30, 40, 90, 60), "uri": "https://example.com"})
            doc[0].add_text_annot((200, 200), "Keep")
            Pdf.write_page_labels(doc, ["i", "1"])
            doc.save(self.source)

    def request(self, operation: str, **values: Json) -> dict[str, Json]:
        """Construct a serial worker request for the generated PDF."""
        return {"operation": operation, "path": str(self.source), "rules": [self.rule.to_data()], **values}

    def window(self) -> FontReplaceWindow:
        """Open an actual worker-backed window and register deterministic cleanup."""
        window = FontReplaceWindow(ENTRY)
        window.show()

        def cleanup() -> None:
            wait_for(lambda: not window.runner.busy)
            window.dirty = False
            window.close()
            window.deleteLater()
            QtWidgets.QApplication.processEvents()

        self.addCleanup(cleanup)
        window.open_path(self.source)
        self.settled(window)
        self.assertEqual(window.page_count, 2)
        return window

    @staticmethod
    def settled(window: FontReplaceWindow) -> None:
        """Wait through the debounce interval and serial render completion."""
        wait_for(lambda: not window.runner.busy and not window.timer.isActive())

    def test_rule_roundtrip_and_invalid_filters(self) -> None:
        rule = replace(self.rule, sizes="12-16", ignored="-1", source_colors="#000; rgb(255,0,0)", color="#123")
        restored = ReplacementRule.from_data(rule.to_data())
        self.assertEqual(restored, rule)
        compiled = restored.compile(2)
        self.assertEqual(compiled.ignored, (1,))
        self.assertEqual(compiled.source_colors, frozenset((0, 0xFF0000)))
        for values in ({"sizes": "0-12"}, {"ignored": "3"}, {"source_colors": "red"}, {"color": "#bad-color"}, {"faces": {}}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                replace(rule, **values).compile(2)

    def test_worker_preview_isolated_and_ignored_pages_remapped(self) -> None:
        before = self.source.read_bytes()
        with closing(Worker()) as worker:
            raw = worker.run(self.request("preview", page=1, raw=True))
            processed = worker.run(self.request("preview", page=1, revision=2))
            self.assertNotEqual(raw["png"], processed["png"])
            self.assertEqual(processed["count"], len("First page"))
            raw_again = worker.run(self.request("preview", page=1, raw=True))
            self.assertEqual(raw["png"], raw_again["png"])
            ignored = replace(self.rule, ignored="2")
            result = worker.run(self.request("preview", page=2, rules=[ignored.to_data()]))
            original = worker.run(self.request("preview", page=2, raw=True))
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["png"], original["png"])
        self.assertEqual(self.source.read_bytes(), before)

    def test_export_retains_structure_and_source_and_reports_progress(self) -> None:
        output = self.folder / "out.pdf"
        messages: list[dict[str, Json]] = []
        before = self.source.read_bytes()
        with closing(Worker(messages.append)) as worker:
            worker.run(self.request("preview", page=1))
            result = worker.run(self.request("export", output=str(output)))
            self.assertEqual(result["count"], len("First pageSecond page"))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(messages[-1]["done"], 2)
        with Pdf.open_document(output, interactive=False) as (doc, _):
            self.assertEqual(doc.get_toc(), [[1, "Opening", 1], [2, "Second", 2]])
            self.assertEqual(Pdf.read_page_labels(doc), ["i", "1"])
            self.assertEqual(doc[0].get_links()[0]["uri"], "https://example.com")
            self.assertEqual(len(list(doc[0].annots())), 1)
            self.assertIn("Fixture-Regular", {span["font"] for span in doc[1].get_texttrace()})
            self.assertIn("Times-Roman", {span["font"] for span in doc[1].get_texttrace()})

    def test_export_failure_preserves_existing_output(self) -> None:
        output = self.folder / "keep.pdf"
        output.write_bytes(b"existing")
        bad = replace(self.rule, faces={FontStyle.BOLD: replace(self.face, style=FontStyle.BOLD)})
        with closing(Worker()) as worker, self.assertRaisesRegex(ValueError, "Missing target REGULAR"):
            worker.run(self.request("export", output=str(output), overwrite=True, rules=[bad.to_data()]))
        self.assertEqual(output.read_bytes(), b"existing")

    def test_scan_and_font_file_discovery(self) -> None:
        with closing(Worker()) as worker:
            result = worker.run(self.request("scan", pages="1,-1"))
            self.assertEqual(result["names"], ["Helvetica", "Times-Roman"])
            self.assertEqual(result["colors"], [0])
            self.assertIn("Type1; embedded: no; 14 pt", result["details"]["Helvetica"])
            self.assertIn("Scanned physical pages: 1-2", result["details"]["Helvetica"])
            self.assertIn("#000000", result["details"]["Helvetica"])
            faces = worker.run({"operation": "font_file", "font_path": str(self.font)})
            self.assertEqual(faces["kind"], "fonts")

    def test_target_results_select_family_and_expose_localized_names(self) -> None:
        window = self.window()
        panel = window.panel
        self.assertIn("load", panel.target_status.text().lower())
        panel.add_faces([self.face])
        panel.search.setText("测试字体")
        self.assertEqual(panel.target.count(), 1)
        item = panel.target.item(0)
        self.assertIn("Fixture-Regular", item.text())
        self.assertIn("测试字体", item.text())
        self.assertIn(str(self.font), item.toolTip())
        panel.target.setCurrentItem(item)
        self.assertEqual(panel.read_rule().faces[FontStyle.REGULAR], self.face)
        self.assertEqual(panel.selected_target.text(), "Selected: Fixture")
        panel.search.setText("not-a-font")
        self.assertEqual(panel.target.count(), 0)
        self.assertIn("No matching fonts", panel.target_status.text())
        self.assertEqual(panel.read_rule().faces[FontStyle.REGULAR], self.face)

    def test_source_details_preserve_exact_rule_font_name(self) -> None:
        window = self.window()
        window.panel.scan_current.click()
        self.settled(window)
        item = window.panel.sources.topLevelItem(0)
        self.assertEqual([item.text(column) for column in range(4)], ["Helvetica", "Type1", "no", "14"])
        self.assertTrue(item.font(0).bold())
        self.assertFalse(item.font(1).bold())
        self.assertIn("encoding:", item.toolTip(0))
        window.panel.sources.setCurrentItem(item)
        self.assertEqual(window.panel.names.text(), "Helvetica")
        self.assertNotIn("embedded:", window.panel.read_rule().names[0])
        window.panel.sources.topLevelItem(1).setSelected(True)
        self.assertEqual(set(window.panel.read_rule().names), {"Helvetica", "Times-Roman"})

    def test_embedded_source_metadata_does_not_change_pdf(self) -> None:
        source = self.folder / "embedded.pdf"
        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_font(fontname="Fixture", fontfile=str(self.font))
            page.insert_text((30, 60), "ABC", fontname="Fixture", fontsize=17)
            document.save(source)
        before = source.read_bytes()
        with closing(Worker()) as worker:
            result = worker.run({"operation": "scan", "path": str(source), "pages": "all"})
            self.assertIn("embedded: yes; 17 pt", result["details"]["Fixture-Regular"])
            self.assertIn("Identity-H", result["details"]["Fixture-Regular"])
        self.assertEqual(source.read_bytes(), before)

    def test_source_names_decode_utf8_without_guessing_legacy_codepages(self) -> None:
        for name in ("宋体", "微软雅黑-Bold", "仿宋_GB2312", "맑은 고딕-Bold", "나눔명조", "Müller", "Français", "Helvetica"):
            with self.subTest(name=name):
                self.assertEqual(_font_name(name), name)
                self.assertEqual(_font_name(f"ABCDEF+{name.encode('utf-8').decode('latin1')}"), name)
        legacy = "宋体".encode("gbk")
        self.assertEqual(_font_name(legacy.decode("utf-8", errors="surrogateescape")), legacy.decode("latin1"))
        self.assertEqual(_font_name(legacy.decode("latin1")), legacy.decode("latin1"))

    def test_multilingual_font_scan_selection_and_replacement(self) -> None:
        for family, legacy_encoding in (("测试字体", "gbk"), ("맑은 고딕", "cp949")):
            with self.subTest(family=family):
                canonical = f"{family}-Regular"
                source = self.folder / f"{family}.pdf"
                with pymupdf.open() as document:
                    page = document.new_page()
                    xref = page.insert_font(fontname="Localized", fontfile=str(self.font))
                    # PyMuPDF's font inserter ASCII-sanitizes names, so construct
                    # Unicode PDF names explicitly, as real producers do.
                    escaped = "".join(f"#{byte:02X}" for byte in canonical.encode("utf-8"))
                    pdf_name = f"/{escaped}"
                    document.xref_set_key(xref, "BaseFont", pdf_name)
                    descendant = int(document.xref_get_key(xref, "DescendantFonts")[1].strip("[]").split()[0])
                    document.xref_set_key(descendant, "BaseFont", pdf_name)
                    document.xref_set_key(descendant, "FontDescriptor/FontName", pdf_name)
                    page.insert_text((30, 60), "ABC", fontname="Localized", fontsize=17)
                    document.save(source)
                    legacy = canonical.encode(legacy_encoding)
                    with patch("pymupdf.mupdf.ll_fz_font_name", return_value=legacy.decode("utf-8", errors="surrogateescape")):
                        self.assertEqual(_page_font_aliases(page), {legacy.decode("latin1"): canonical})
                with closing(Worker()) as worker:
                    request: dict[str, Json] = {"operation": "scan", "path": str(source), "pages": "all"}
                    scan = worker.run(request)
                    self.assertEqual(scan["names"], [canonical])
                    self.assertIn("embedded: yes; 17 pt", scan["details"][canonical])
                    self.assertIn(f"PDF name: {canonical}", scan["details"][canonical])
                    for name in (canonical, canonical.encode("utf-8").decode("latin1")):
                        for color_only in (False, True):
                            rule = replace(self.rule, names=(name,), color_only=color_only, color="#F00")
                            result = worker.run({**request, "operation": "preview", "page": 1, "rules": [rule.to_data()]})
                            self.assertGreater(result["recolored_runs"] if color_only else result["count"], 0)

    def test_source_metadata_resolves_direct_and_indirect_descendants(self) -> None:
        for direct_child in (False, True):
            for indirect_array in (False, True):
                for direct_descriptor in (False, True):
                    with self.subTest(child=direct_child, array=indirect_array, descriptor=direct_descriptor), pymupdf.open() as document:
                        page = document.new_page()
                        xref = page.insert_font(fontname="Fixture", fontfile=str(self.font))
                        page.insert_text((30, 60), "ABC", fontname="Fixture", fontsize=17)
                        descendant = int(document.xref_get_key(xref, "DescendantFonts")[1].strip("[]").split()[0])
                        if direct_descriptor:
                            descriptor = Pdf.read_dictionary(document, descendant, "FontDescriptor")
                            document.xref_set_key(descendant, "FontDescriptor", descriptor)
                        child = document.xref_object(descendant) if direct_child else f"{descendant} 0 R"
                        array = f"[{child}]"
                        value = f"{Pdf.new_object(document, array)} 0 R" if indirect_array else array
                        document.xref_set_key(xref, "DescendantFonts", value)
                        before = [document.xref_object(number) for number in range(1, document.xref_length())]
                        details, colors = _font_details(document, [0], ["Fixture-Regular"])
                        self.assertIn("embedded: yes; 17 pt", details["Fixture-Regular"])
                        self.assertEqual(colors, [0])
                        self.assertEqual(before, [document.xref_object(number) for number in range(1, document.xref_length())])

    def test_gui_rule_update_raw_cache_and_clear_refresh(self) -> None:
        window = self.window()
        original = window.viewer._original.toImage()
        window.panel.load_rule(self.rule)
        window._commit_rule(True)
        self.settled(window)
        first = window.viewer._original.toImage()
        self.assertNotEqual(first, original)
        self.assertEqual(window.rule_list.topLevelItemCount(), 1)
        window.panel.color.setText("#F00")
        window._commit_rule(False)
        self.settled(window)
        red = window.viewer._original.toImage()
        self.assertNotEqual(red, first)
        window.raw.setChecked(True)
        self.settled(window)
        self.assertEqual(window.viewer._original.toImage(), original)
        with patch.object(window.runner, "start", wraps=window.runner.start) as start:
            window.raw.setChecked(False)
            self.assertEqual(start.call_count, 0)
            self.assertEqual(window.viewer._original.toImage(), red)
        window._clear_rules()
        self.settled(window)
        self.assertEqual(window.viewer._original.toImage(), original)

    def test_gui_readonly_navigation_shortcuts_and_debounce(self) -> None:
        window = self.window()
        self.assertEqual(window.navigation.count(), 2)
        item = window.navigation.bookmarks.topLevelItem(0)
        self.assertFalse(item.flags() & QtCore.Qt.ItemFlag.ItemIsEditable)
        window.raw.setChecked(True)
        self.settled(window)
        window.viewer.setFocus()
        QtTest.QTest.keyClick(window.viewer, QtCore.Qt.Key.Key_PageDown)
        self.settled(window)
        self.assertEqual(window.current_page, 2)
        self.assertTrue(window.raw.isChecked())
        window.panel.load_rule(self.rule)
        window._commit_rule(True)
        self.settled(window)
        window.raw.setChecked(False)
        self.settled(window)
        window.go_page(1)
        self.assertTrue(window.timer.isActive())
        self.assertFalse(window.runner.busy)
        window.go_page(2)
        self.assertFalse(window.timer.isActive())
        self.assertFalse(window.runner.busy)

    def test_gui_order_delete_and_draft_validation(self) -> None:
        window = self.window()
        window.panel.load_rule(self.rule)
        window._commit_rule(True)
        self.settled(window)
        window.panel.color.setText("#F00")
        window._commit_rule(True)
        self.settled(window)
        window._move_rule(-1)
        self.settled(window)
        self.assertEqual(window.rules[0].color, "#F00")
        window.panel.sizes.setText("invalid")
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            window._commit_rule(False)
        warning.assert_called_once()
        self.assertEqual(window.rules[0].sizes, "")
        window._delete_rules()
        self.settled(window)
        self.assertEqual(len(window.rules), 1)
        self.assertEqual(window.rules[0].color, "")

    def test_gui_font_file_and_export_then_close_reopen(self) -> None:
        window = self.window()
        window._start({"operation": "font_file", "font_path": str(self.font)})
        self.settled(window)
        self.assertEqual(window.panel.read_rule().faces[FontStyle.REGULAR].path, self.font)
        window.panel.names.setText("Helvetica")
        window._commit_rule(True)
        self.settled(window)
        output = self.folder / "gui-output.pdf"
        with patch("personal_pdf_tools.font_replace.app.choose_pdf_output", return_value=(output, False)), \
                patch.object(QtWidgets.QMessageBox, "information") as information:
            window._export()
            self.settled(window)
        information.assert_called_once()
        self.assertTrue(output.is_file())
        self.assertFalse(window.dirty)
        window._close_pdf()
        self.assertIsNone(window.source)
        self.assertEqual(window.cache.size, 0)
        window.open_path(self.source)
        self.settled(window)
        self.assertEqual(window.page_count, 2)
        self.assertFalse(window.rules)

    def test_worker_no_matches_and_source_overwrite_are_safe(self) -> None:
        before = self.source.read_bytes()
        output = self.folder / "empty.pdf"
        unmatched = replace(self.rule, names=("NotInDocument",))
        with closing(Worker()) as worker:
            response = worker.run(self.request("export", output=str(output), rules=[unmatched.to_data()]))
            self.assertEqual(response["kind"], "no_matches")
            self.assertFalse(output.exists())
            with self.assertRaises((ValueError, FileExistsError)):
                worker.run(self.request("export", output=str(self.source), overwrite=True))
        self.assertEqual(self.source.read_bytes(), before)

    def test_application_pages_use_shared_parser_and_exclusions(self) -> None:
        with patch.object(Input, "parse_index_ranges", wraps=Input.parse_index_ranges) as parser:
            compiled = replace(self.rule, pages="1,3-4,-1", ignored="3").compile(5)
        self.assertEqual(compiled.ignored, (1, 2))
        parser.assert_any_call("1,3-4,-1", item_count=5)
        self.assertEqual(replace(self.rule, pages="ALL").compile(3).ignored, ())
        self.assertEqual(replace(self.rule, pages="none").compile(3).ignored, (0, 1, 2))
        for pages in ("0", "3", "bad", "2-1"):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                replace(self.rule, pages=pages).compile(2)

    def test_color_only_filters_pages_colors_and_preserves_fonts(self) -> None:
        rule = ReplacementRule(pages="2", source_colors="#000", color="#F00", color_only=True)
        output = self.folder / "recolored.pdf"
        with closing(Worker()) as worker, patch(
                "personal_pdf_tools.font_replace.engine._embed", side_effect=AssertionError("Must not embed")), patch(
                "personal_pdf_tools.font_replace.engine._source_font", side_effect=AssertionError("Must not decode Unicode")):
            skipped = worker.run(self.request("preview", page=1, rules=[rule.to_data()]))
            raw = worker.run(self.request("preview", page=1, raw=True))
            self.assertEqual(skipped["png"], raw["png"])
            changed = worker.run(self.request("preview", page=2, rules=[rule.to_data()]))
            self.assertEqual(changed["recolored_runs"], 2)
            result = worker.run(self.request("export", output=str(output), rules=[rule.to_data()]))
            self.assertEqual(result["kind"], "exported")
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["recolored_runs"], 2)
        with Pdf.open_document(self.source, interactive=False) as (before, _), \
                Pdf.open_document(output, interactive=False) as (after, _):
            self.assertEqual(before[0].get_texttrace(), after[0].get_texttrace())
            for original, converted in zip(before[1].get_texttrace(), after[1].get_texttrace()):
                self.assertEqual(converted["color"], (1, 0, 0))
                for key in ("font", "chars", "size", "dir", "opacity", "type"):
                    self.assertEqual(original[key], converted[key])
        with closing(Worker()) as worker:
            unmatched = replace(rule, source_colors="#00F")
            response = worker.run(self.request("export", output=str(self.folder / "none.pdf"), rules=[unmatched.to_data()]))
            self.assertEqual(response["kind"], "no_matches")

    def test_gui_color_only_mode_scope_and_subset_default(self) -> None:
        window = self.window()
        panel = window.panel
        self.assertEqual(panel.pages.text(), "all")
        self.assertEqual(panel.read_rule().embedding, _Embedding.SUBSET)
        original = window.viewer._original.toImage()
        panel.color_only.setChecked(True)
        self.assertFalse(panel.font_controls.isEnabled())
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            window._commit_rule(True)
        warning.assert_called_once()
        panel.color.setText("#F00")
        panel.source_colors.setText("#000")
        panel.pages.setText("2")
        window._commit_rule(True)
        self.settled(window)
        self.assertEqual(window.viewer._original.toImage(), original)
        self.assertEqual(window.rules[0].pages, "2")
        self.assertTrue(window.rules[0].color_only)
        window.go_page(2)
        self.settled(window)
        self.assertIn("2 text runs recolored", window.status.text())
        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            panel.pages.setText("3")
            window._commit_rule(False)
        warning.assert_called_once()
        self.assertEqual(window.rules[0].pages, "2")


if __name__ == "__main__":
    unittest.main()
