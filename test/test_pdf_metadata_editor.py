"""Round-trip metadata, output security and a real worker-backed Qt export."""

import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pymupdf
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/document-processing"
sys.path[:0] = [str(TOOLS), str(ROOT)]
app = importlib.import_module("pdf-ocr").load_app("metadata.app")
from personal_pdf_tools.metadata import engine, worker, xmp
from utils.qt_styles import theme_tint
from utils import Pdf, PdfProtection

PACKET = f'''<rdf:RDF xmlns:rdf="{xmp.RDF}" xmlns:a="{xmp.PDFA}" xmlns:dc="{xmp.DC}">
<rdf:Description rdf:about="" a:part="1" a:conformance="B">
<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Original</rdf:li><rdf:li xml:lang="fr">Livre</rdf:li>
</rdf:Alt></dc:title><dc:creator><rdf:Seq><rdf:li>Ada</rdf:li><rdf:li>Li</rdf:li></rdf:Seq></dc:creator>
</rdf:Description></rdf:RDF>'''


class MetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = self.enterContext(tempfile.TemporaryDirectory(dir=ROOT / "tmp"))
        self.source = Path(folder) / "source.pdf"
        self.output = Path(folder) / "output.pdf"
        with pymupdf.open() as doc:
            doc.new_page().insert_text((30, 50), "Original page content")
            doc.set_toc([[1, "Original bookmark", 1]])
            doc.set_metadata({"producer": "Original producer"})
            obj = int(doc.xref_get_key(-1, "Info")[1].split()[0])
            doc.xref_set_key(obj, "Trapped", "/False")
            doc.xref_set_key(obj, "Custom", "[1 /Name (text)]")
            doc.set_xml_metadata(PACKET)
            doc.save(self.source)

    def test_metadata_types_xmp_languages_and_rendering(self) -> None:
        original = self.source.read_bytes()
        with Pdf.open_document(self.source) as (doc, _):
            pixels = doc[0].get_pixmap().samples
            rows = engine.read_properties(doc)
            self.assertEqual(engine.common_values(rows, PACKET)["Title"], "Original")
            extras = [row for row in rows if row["key"] not in xmp.FIELDS and row["key"] != "Trapped"]
            extras[0]["key"] = "部门 / (group)"
            extras.append(engine.Property(original="", key="Revision", value="42", raw=True))
            extras.append(engine.Property(original="", key="备注", value="文本 (\\)", raw=False))
            engine.apply_edits(doc, extras, {"Title": "新标题", "Author": "New", "Producer": ""}, None, "4f")
            Pdf.save_new(doc, self.output, preserve_pdfa=True)
        self.assertEqual(self.source.read_bytes(), original)
        with Pdf.open_document(self.output) as (doc, _):
            rows = {row["key"]: row for row in engine.read_properties(doc)}
            self.assertEqual(rows["Title"]["value"], "新标题")
            self.assertNotIn("Producer", rows)
            self.assertNotIn("Trapped", rows)
            self.assertTrue(rows["部门 / (group)"]["raw"])
            self.assertEqual(rows["Revision"]["value"], "42")
            self.assertEqual(rows["备注"]["value"], "文本 (\\)")
            xml = doc.get_xml_metadata()
            packet = xmp.Packet(xml)
            self.assertEqual((packet.read("Title"), packet.read("Author")), ("新标题", "New"))
            for text in (">Li<", ">Livre<", ">2020<", ">4<", ">F<"):
                self.assertIn(text, xml)
            self.assertNotIn('a:part="1"', xml)
            self.assertEqual(doc.get_toc(), [[1, "Original bookmark", 1]])
            self.assertEqual(doc[0].get_pixmap().samples, pixels)

    def test_unlocked_permissions_password_and_unchanged_destination(self) -> None:
        original = self.source.read_bytes()
        for password in ("", "打开"):
            with self.subTest(password_required=bool(password)):
                with Pdf.open_document(self.source) as (doc, _):
                    Pdf.save_new(doc, self.output, overwrite=True,
                                 protection=PdfProtection("owner", password, pymupdf.PDF_PERM_PRINT))
                request = {"operation": "inspect", "path": str(self.output)}
                run = lambda **kwargs: worker.run({**request, **kwargs}, lambda _: None)
                self.assertEqual(run()["kind"], "unlock")
                if password:
                    self.assertEqual(run(unlock=True, password="incorrect")["kind"], "password")
                self.assertEqual(run(unlock=True, password=password)["kind"], "opened")
                with Pdf.open_document(self.output, password=password, interactive=False) as (doc, _):
                    self.assertFalse(Pdf.has_pdfa_identification(doc))
                    self.assertFalse(doc.permissions & pymupdf.PDF_PERM_MODIFY)
                    self.assertTrue(doc.permissions & pymupdf.PDF_PERM_PRINT)
                    self.assertTrue(doc.authenticate("owner") & 4)
        previous = self.output.read_bytes()
        with Pdf.open_document(self.source) as (doc, _):
            with self.assertRaises(ValueError):
                Pdf.save_new(doc, self.output, overwrite=True, preserve_pdfa=True, protection=PdfProtection("owner"))
            with self.assertRaises(FileExistsError):
                Pdf.save_new(doc, self.output)
        self.assertEqual(self.output.read_bytes(), previous)
        self.assertEqual(self.source.read_bytes(), original)

    def test_gui_worker_export_and_repeat(self) -> None:
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        application.setStyle("Fusion")
        self.enterContext(patch.object(app, "remember_directory"))
        warnings = self.enterContext(patch.object(QtWidgets.QMessageBox, "warning"))
        window = app.MetadataWindow(TOOLS / "pdf-metadata-editor.py")
        def settle() -> None:
            deadline = time.monotonic() + 20
            while window.runner.busy and time.monotonic() < deadline:
                application.processEvents()
                QtTest.QTest.qWait(10)
            self.assertFalse(window.runner.busy)
            self.assertFalse(warnings.called, warnings.call_args)
        try:
            window.show()
            window.open_path(self.source)
            settle()
            self.assertEqual(window.properties.fields["Author"].text(), "Ada")
            self.assertIn("Pages: 1", window.info.text())
            field = window.properties.fields["Title"]
            field.selectAll()
            QtTest.QTest.keyClicks(field, "Updated")
            self.assertTrue(window.dirty)
            window.options.marker.setCurrentIndex(window.options.marker.findData("2b"))
            with patch.object(app, "choose_pdf_output", return_value=(self.output, False)):
                window._save()
                settle()
            self.assertFalse(window.dirty)
            with Pdf.open_document(self.output) as (doc, _):
                self.assertEqual(doc.metadata["title"], "Updated")
                self.assertTrue(Pdf.has_pdfa_identification(doc))
            window.options.mode.setCurrentIndex(2)
            window.options.user.setText("reader")
            with patch.object(app, "choose_pdf_output", return_value=(self.output, True)):
                window._save()
                settle()
            with Pdf.open_document(self.output, password="reader", interactive=False) as (doc, _):
                self.assertEqual(doc.metadata["title"], "Updated")
                self.assertFalse(Pdf.has_pdfa_identification(doc))
                self.assertTrue(doc.permissions & pymupdf.PDF_PERM_MODIFY)
        finally:
            window.dirty = False
            window.close()
            application.processEvents()

    def test_decrypt_export_and_invalid_raw_xmp_do_not_replace_files(self) -> None:
        with Pdf.open_document(self.source) as (doc, _):
            Pdf.save_new(doc, self.output, protection=PdfProtection("owner", "reader"))
        unlocked = self.source.with_name("unlocked.pdf")
        protected_bytes = self.output.read_bytes()
        request = {"path": str(self.output), "password": "reader", "unlock": True, "operation": "inspect"}
        opened = worker.run(request, lambda _: None)
        draft = {**request, "identity": opened["identity"], "operation": "export", "output": str(unlocked),
                 "extras": [], "common": {"Title": "edited"}, "overwrite": False, "xml": None, "marker": "remove"}
        worker.run(draft, lambda _: None)
        with Pdf.open_document(unlocked, interactive=False) as (doc, _):
            self.assertEqual(doc.metadata["title"], "edited")
            self.assertEqual(doc.xref_get_key(-1, "Encrypt")[0], "null")
        previous = unlocked.read_bytes()
        for change in ({"xml": "<broken>"}, {"identity": "stale"}, {"output": str(self.output)}):
            with self.subTest(change=change), self.assertRaises((ValueError, FileExistsError)):
                worker.run({**draft, "overwrite": True, **change}, lambda _: None)
        self.assertEqual(unlocked.read_bytes(), previous)
        self.assertEqual(self.output.read_bytes(), protected_bytes)

    def test_blank_source_custom_xmp_and_removing_all_metadata(self) -> None:
        with pymupdf.open() as doc:
            doc.new_page()
            engine.apply_edits(doc, [], {"Title": "First"}, None, "4")
            self.assertIn(">2020<", doc.get_xml_metadata())
            engine.apply_edits(doc, [], {}, PACKET, "keep")
            self.assertEqual(xmp.Packet(doc.get_xml_metadata()).read("Author"), "Ada")
            engine.apply_edits(doc, [], {"Title": ""}, "", "remove")
            Pdf.save_new(doc, self.output)
        with Pdf.open_document(self.output) as (doc, _):
            self.assertEqual(engine.read_properties(doc), [])
            self.assertEqual(doc.get_xml_metadata(), "")

    def test_multilingual_dialog_order_color_clear_and_custom_language(self) -> None:
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        parent = QtWidgets.QWidget()
        dialog = app.TitleDialog({"fr": "Livre", "x-default": "Book"}, parent, has_property=True)
        languages = dialog.languages
        role = QtCore.Qt.ItemDataRole.UserRole
        self.assertEqual([languages.item(i).data(role) for i in range(2)], ["x-default", "fr"])
        first = languages.item(0)
        self.assertTrue(first.font().bold())
        color = first.foreground().color()
        self.assertGreater(color.green(), max(color.red(), color.blue()))
        background = first.background().color()
        self.assertGreater(background.green(), max(background.red(), background.blue()))
        self.assertEqual(background, theme_tint("green"))
        style = QtWidgets.QStyleOptionViewItem()
        languages.itemDelegate().initStyleOption(style, languages.model().index(0, 0))
        self.assertEqual(style.palette.color(QtGui.QPalette.ColorRole.HighlightedText), color)
        selected = style.palette.color(QtGui.QPalette.ColorRole.Highlight)
        self.assertGreater(selected.green(), max(selected.red(), selected.blue()))
        self.assertEqual(selected, theme_tint("green", selected=True))
        self.assertFalse(languages.item(2).font().bold())
        languages.setCurrentRow(1)
        self.assertEqual(dialog.editor.toPlainText(), "Livre")
        dialog.clear_one.click()
        self.assertEqual(dialog.titles, {"x-default": "Book"})
        self.assertGreater(languages.currentRow(), 0)
        self.assertFalse(languages.currentItem().font().bold())
        self.assertIsNone(languages.currentItem().data(QtCore.Qt.ItemDataRole.BackgroundRole))
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("zh-Hant-HK", True)):
            dialog._add_language()
        dialog.editor.setPlainText("繁體標題")
        self.assertEqual(languages.currentRow(), 1)
        self.assertEqual(dialog._tag(), "zh-Hant-HK")
        self.assertTrue(languages.currentItem().font().bold())
        dialog.clear_all.click()
        self.assertEqual(dialog.titles, {})
        self.assertFalse(dialog.clear_one.isEnabled())
        self.assertFalse(dialog.clear_all.isEnabled())
        self.assertEqual(dialog.editor.toPlainText(), "")
        dialog.reject()
        parent.close()
        application.processEvents()

    def test_localized_titles_create_convert_and_remove(self) -> None:
        for xml in ("", f'<r:RDF xmlns:r="{xmp.RDF}" xmlns:d="{xmp.DC}">'
                    '<r:Description d:title="Book" d:format="application/pdf"/></r:RDF>'):
            packet = xmp.Packet(xml)
            titles = packet.titles()
            if xml:
                self.assertEqual(titles, {"x-default": "Book"})
            titles.update({"ja": "日本語", "x-default": "Book"})
            packet.set_titles(titles)
            self.assertEqual(list(packet.titles()), ["x-default", "ja"])
            packet.set_titles({"ja": "日本語"})
            self.assertEqual(packet.titles(), {"ja": "日本語"})
            packet.set_titles({})
            self.assertFalse(packet.has_title())
            if xml:
                self.assertIn('d:format="application/pdf"', packet.dom.toxml())

    def test_multilingual_title_dialog_through_export(self) -> None:
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.enterContext(patch.object(app, "remember_directory"))
        warnings = self.enterContext(patch.object(QtWidgets.QMessageBox, "warning"))
        window = app.MetadataWindow(TOOLS / "pdf-metadata-editor.py")

        def settle() -> None:
            deadline = time.monotonic() + 15
            while window.runner.busy and time.monotonic() < deadline:
                application.processEvents()
                QtTest.QTest.qWait(10)
            self.assertFalse(window.runner.busy)
            self.assertFalse(warnings.called, warnings.call_args)

        def export() -> tuple[str, xmp.Packet]:
            with patch.object(app, "choose_pdf_output", return_value=(self.output, self.output.exists())):
                window._save()
                settle()
            with Pdf.open_document(self.output) as (doc, _):
                return doc.metadata["title"], xmp.Packet(doc.get_xml_metadata())

        def edit(dialog: app.TitleDialog) -> int:
            dialog.languages.setCurrentRow(1)
            dialog.clear_one.click()
            with patch.object(QtWidgets.QInputDialog, "getText", return_value=("zh-Hans", True)):
                dialog._add_language()
            dialog.editor.setPlainText("中文标题")
            return QtWidgets.QDialog.DialogCode.Accepted

        def remove(dialog: app.TitleDialog) -> int:
            dialog.clear_all.click()
            return QtWidgets.QDialog.DialogCode.Accepted

        def cancel_removal(dialog: app.TitleDialog) -> int:
            dialog.clear_all.click()
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            window.open_path(self.source)
            settle()
            window.properties.fields["Title"].setText("Edited ordinary title")
            with patch.object(app.TitleDialog, "exec", edit):
                window.properties.edit_titles.click()
            title, packet = export()
            self.assertEqual(title, "Edited ordinary title")
            self.assertEqual(packet.titles(), {"x-default": title, "zh-Hans": "中文标题"})
            before = window.xml.toPlainText()
            with patch.object(app.TitleDialog, "exec", cancel_removal):
                window.properties.edit_titles.click()
            self.assertEqual(window.xml.toPlainText(), before)
            with patch.object(app.TitleDialog, "exec", remove):
                window.properties.edit_titles.click()
            window.options.marker.setCurrentIndex(window.options.marker.findData("2b"))
            for text in ("Edited ordinary title", "Plain title only"):
                window.properties.fields["Title"].setText(text)
                title, packet = export()
                self.assertEqual(title, text)
                self.assertFalse(packet.has_title())
                self.assertEqual(packet.read("Author"), "Ada")
        finally:
            window.dirty = False
            window.close()
            application.processEvents()


if __name__ == "__main__":
    unittest.main()
