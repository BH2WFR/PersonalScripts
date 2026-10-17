"""Regression coverage for PyMuPDF bookmarks, page tags, decryption and output.

Run: conda run -n base python -m unittest discover -s test -p test_pdf_tools.py
Requires PyMuPDF; fixtures and temporary output stay under the repository tmp.
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import subprocess
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from xml.dom import minidom

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XML = '<metadata>retained XML</metadata>'
sys.path.insert(0, str(ROOT))
from utils import *  # noqa: E402


def load_script(name: str) -> ModuleType:
    """Load a document tool by filename for exercising its real entry point."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools/document-processing" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bookmarks = load_script("pdf-bookmarks-add")
decrypt = load_script("pdf-decrypt")
tags = load_script("pdf-page-tag")
compress = load_script("pdf-compress")


class PdfToolsTests(unittest.TestCase):
    """Verify saved documents rather than only mocked library calls."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="pdf-tools-", dir=ROOT / "tmp")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / "source.pdf"
        self.output = self.folder / "output.pdf"
        self.make_source()

    def make_source(self, password: str | None = None, xml_metadata: str = DEFAULT_XML) -> None:
        """Create a document with outlines, links, fields, metadata and an attachment."""
        with pymupdf.open() as document:
            for _ in range(4):
                document.new_page(width=144, height=144)
            document[0].insert_text((20, 30), "Retained text")
            document[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 40, 70, 60),
                                     "page": 3, "to": pymupdf.Point(0, 0)})
            widget = pymupdf.Widget()
            widget.field_name = "sample"
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(10, 70, 90, 90)
            widget.field_value = "retained value"
            document[0].add_widget(widget)
            document.set_metadata({"title": "Original title"})
            document.set_page_labels([{"startpage": 0, "prefix": "Old-", "style": "D", "firstpagenum": 5}])
            info = int(document.xref_get_key(-1, "Info")[1].split()[0])
            document.xref_set_key(info, "CustomField", pymupdf.get_pdf_str("custom value"))
            document.set_xml_metadata(xml_metadata)
            document.embfile_add("sample.txt", b"attachment content")
            document.set_toc([[1, "Original", 1], [2, "Nested", 2], [1, "Website", -1]])
            xrefs = document.get_outline_xrefs()
            document.xref_set_key(xrefs[0], "C", "[1 0 0]")
            document.xref_set_key(xrefs[0], "F", "3")
            document.xref_set_key(xrefs[0], "A", "null")
            document.xref_set_key(xrefs[0], "Dest", f"[{document.page_xref(0)} 0 R /FitH 72]")
            document.xref_set_key(xrefs[2], "A", "<< /S /URI /URI (https://example.com/) >>")
            # Keep a named destination as a document-level object, not only a TOC entry.
            document.xref_set_key(document.pdf_catalog(), "Dests",
                                  f"<< /chapter [{document.page_xref(3)} 0 R /Fit] >>")
            encryption = pymupdf.PDF_ENCRYPT_NONE if password is None else pymupdf.PDF_ENCRYPT_AES_256
            document.save(self.source, encryption=encryption, owner_pw="owner", user_pw=password or "",
                          permissions=pymupdf.PDF_PERM_PRINT)

    def assert_structure(self, result: pymupdf.Document, xml_metadata: str = DEFAULT_XML) -> None:
        """Check document objects that a page-only reconstruction would discard."""
        self.assertFalse(result.needs_pass)
        self.assertEqual(result.xref_get_key(-1, "Encrypt"), ("null", "null"))
        for permission in (pymupdf.PDF_PERM_MODIFY, pymupdf.PDF_PERM_COPY, pymupdf.PDF_PERM_ANNOTATE,
                           pymupdf.PDF_PERM_FORM, pymupdf.PDF_PERM_ASSEMBLE):
            self.assertTrue(result.permissions & permission)
        self.assertEqual(result.page_count, 4)
        self.assertIn("Retained text", result[0].get_text())
        self.assertEqual(result.metadata["title"], "Original title")
        info = int(result.xref_get_key(-1, "Info")[1].split()[0])
        self.assertEqual(result.xref_get_key(info, "CustomField"), ("string", "custom value"))
        self.assertEqual(result.get_xml_metadata(), xml_metadata)
        self.assertEqual(result.embfile_get("sample.txt"), b"attachment content")
        self.assertEqual(result[0].get_links()[0]["page"], 3)
        self.assertEqual(next(result[0].widgets()).field_value, "retained value")
        self.assertEqual(result.resolve_names()["chapter"]["page"], 3)

    def run_decrypt(self, passwords: list[str]) -> int:
        """Run the actual decrypt CLI with only interactive inputs substituted."""
        with (
            patch.object(sys, "argv", [str(decrypt.__file__), str(self.source), "-o", str(self.output)]),
            patch.object(Input, "resolve_output_path", return_value=str(self.output)),
            patch.object(Input, "input_password", side_effect=passwords),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return decrypt.main()

    def test_decrypt_aes_retry_preserves_structure(self) -> None:
        self.make_source("secret")
        original = self.source.read_bytes()
        self.assertEqual(self.run_decrypt(["wrong", "secret"]), 0)
        with pymupdf.open(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assert_structure(result)
            self.assertEqual(result.get_toc()[0], [1, "Original", 1])
        self.assertEqual(self.source.read_bytes(), original)

    def test_decrypt_permission_only_needs_no_password_prompt(self) -> None:
        self.make_source("")
        self.assertEqual(self.run_decrypt([]), 0)
        with pymupdf.open(self.output) as result:
            self.assert_structure(result)

    def test_decrypt_plain_pdf_warns_and_exits_without_output_prompt(self) -> None:
        original = self.source.read_bytes()
        for answer in ("x", ""):
            messages = io.StringIO()
            with (
                self.subTest(answer=answer),
                patch.object(sys, "argv", [str(decrypt.__file__), str(self.source), "-o", str(self.output)]),
                patch.object(Input, "resolve_output_path") as output,
                patch.object(Input, "input_password") as password,
                patch("builtins.input", return_value=answer),
                contextlib.redirect_stdout(messages),
            ):
                self.assertEqual(decrypt.main(), 0)
            output.assert_not_called()
            password.assert_not_called()
            self.assertIn(f"{FLYellow}WARNING: No encryption, permission restrictions, or PDF/A identification", messages.getvalue())
            self.assertIn("Open another PDF", messages.getvalue())
            self.assertIn("Exit", messages.getvalue())
            self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), original)

    def test_decrypt_plain_pdf_can_reopen_protected_input(self) -> None:
        first = self.source
        first_bytes = first.read_bytes()
        self.source = self.folder / "protected.pdf"
        self.make_source("secret")
        protected_bytes = self.source.read_bytes()
        with (
            patch.object(sys, "argv", [str(decrypt.__file__), str(first)]),
            patch.object(Input, "resolve_input_path", return_value=str(self.source)) as input_path,
            patch.object(Input, "resolve_output_path", return_value=str(self.output)) as output,
            patch.object(Input, "input_password", return_value="secret") as password,
            patch("builtins.input", return_value="r"),
            patch.object(Pdf, "open_document", wraps=Pdf.open_document) as open_document,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(decrypt.main(), 0)
        input_path.assert_called_once()
        password.assert_called_once()
        output.assert_called_once()
        self.assertEqual(Path(output.call_args.args[0]), self.source.with_name("protected_decrypted.pdf"))
        self.assertEqual([call.args[0] for call in open_document.call_args_list], [str(first), str(self.source)])
        with pymupdf.open(self.output) as result:
            self.assert_structure(result)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(self.source.read_bytes(), protected_bytes)

    def test_decrypt_pdfa_only_reports_plain_info_and_writes_ordinary_pdf(self) -> None:
        self.make_source(xml_metadata='<metadata xmlns:a="http://www.aiim.org/pdfa/ns/id/" a:part="2" a:conformance="B"/>')
        original = self.source.read_bytes()
        messages = io.StringIO()
        with (
            patch.object(sys, "argv", [str(decrypt.__file__), str(self.source)]),
            patch.object(Input, "resolve_output_path", return_value=str(self.output)) as output,
            patch.object(Input, "input_password") as password,
            patch.object(Menu, "select") as menu,
            contextlib.redirect_stdout(messages),
        ):
            self.assertEqual(decrypt.main(), 0)
        password.assert_not_called()
        menu.assert_not_called()
        output.assert_called_once()
        notice = next(line for line in messages.getvalue().splitlines() if "only PDF/A" in line)
        self.assertNotIn("\x1b[", notice)
        self.assertNotIn("WARNING", messages.getvalue())
        with pymupdf.open(self.output) as result:
            self.assertFalse(Pdf.has_pdfa_identification(result))
            self.assert_structure(result, result.get_xml_metadata())
        self.assertEqual(self.source.read_bytes(), original)

    def test_pdfa_detection_ignores_namespace_declarations_and_ordinary_text(self) -> None:
        xml = '<metadata xmlns:a="http://www.aiim.org/pdfa/ns/id/">Keep PDF/A text.</metadata>'
        self.make_source(xml_metadata=xml)
        with Pdf.open_document(self.source) as (document, _):
            self.assertFalse(Pdf.has_pdfa_identification(document))
            self.assertEqual(document.get_xml_metadata(), xml)

    def test_cancel_password_writes_nothing(self) -> None:
        self.make_source("secret")
        self.assertEqual(self.run_decrypt([""]), 1)
        self.assertFalse(self.output.exists())

    def test_shared_open_retries_reuses_password_and_closes_readers(self) -> None:
        self.make_source("secret")
        original = self.source.read_bytes()
        with patch.object(Input, "input_password", side_effect=["wrong", "secret"]) as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            with Pdf.open_document(self.source) as (document, password):
                self.assertEqual(password, "secret")
                self.assertEqual(document.page_count, 4)
                self.assertEqual(Pdf.unlock(document), "")
                with Pdf.open_document(self.source, password=password, interactive=False) as (reader, accepted):
                    self.assertEqual(accepted, password)
                    self.assertEqual(reader.page_count, 4)
                self.assertTrue(reader.is_closed)
            self.assertEqual(prompt.call_count, 2)
        self.assertTrue(document.is_closed)
        self.assertEqual(self.source.read_bytes(), original)

    def test_shared_open_closes_after_password_cancellation_or_failure(self) -> None:
        self.make_source("secret")
        for interactive, password, error in ((True, None, ValueError), (False, "wrong", ValueError),
                                             (False, None, ValueError), (True, None, KeyboardInterrupt)):
            document = pymupdf.open(self.source)
            with (
                self.subTest(interactive=interactive, password=password, error=error),
                patch.object(pymupdf, "open", return_value=document),
                patch.object(Input, "input_password", side_effect=KeyboardInterrupt if error is KeyboardInterrupt else None,
                             return_value="") as prompt,
                self.assertRaises(error),
            ):
                with Pdf.open_document(self.source, password=password, interactive=interactive):
                    self.fail("Authentication must fail before the document is yielded.")
            self.assertTrue(document.is_closed)
            if not interactive:
                prompt.assert_not_called()

    def test_shared_open_closes_after_processing_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "processing failed"):
            with Pdf.open_document(self.source) as (document, _):
                raise RuntimeError("processing failed")
        self.assertTrue(document.is_closed)

    def test_compress_stages_decrypted_input_and_unprotected_output(self) -> None:
        self.make_source("secret")
        original = self.source.read_bytes()

        def fake_ghostscript(cmd: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
            self.assertTrue(check)
            self.assertFalse(any("secret" in argument or "Password" in argument for argument in cmd))
            output = next(argument.removeprefix("-sOutputFile=") for argument in cmd if argument.startswith("-sOutputFile="))
            with pymupdf.open(cmd[-1]) as prepared:
                self.assert_structure(prepared)
                # Even if an external writer adds owner restrictions, final save removes them.
                prepared.save(output, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner",
                              user_pw="", permissions=pymupdf.PDF_PERM_PRINT)
            return subprocess.CompletedProcess(cmd, 0)

        with Pdf.open_document(self.source, password="secret", interactive=False) as (document, _), \
                patch.object(compress.subprocess, "run", side_effect=fake_ghostscript), \
                contextlib.redirect_stdout(io.StringIO()):
            compress._compress_document(document, self.source, self.output, "gs", compress._build_ebook_cmd)
        with pymupdf.open(self.output) as result:
            self.assert_structure(result)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["output.pdf", "source.pdf"])

    def test_compress_failure_and_interruption_remove_staged_files(self) -> None:
        for error in (subprocess.CalledProcessError(1, ["gs"]), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), Pdf.open_document(self.source) as (document, _), \
                    patch.object(compress.subprocess, "run", side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(error)):
                compress._compress_document(document, self.source, self.output, "gs", compress._build_ebook_cmd)
            self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_compress_rejects_existing_output_before_starting_process(self) -> None:
        self.output.write_bytes(b"existing")
        with Pdf.open_document(self.source) as (document, _), patch.object(compress.subprocess, "run") as run:
            for output in (self.source, self.output):
                with self.subTest(output=output), self.assertRaises(FileExistsError):
                    compress._compress_document(document, self.source, output, "gs", compress._build_ebook_cmd)
        run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_compress_password_cancel_does_not_request_output_or_run_ghostscript(self) -> None:
        self.make_source("secret")
        with patch.object(sys, "argv", [str(compress.__file__)]), \
                patch.object(Input, "resolve_input_path", return_value=str(self.source)), \
                patch.object(Input, "resolve_output_path") as output, \
                patch.object(Input, "input_password", return_value=""), \
                patch.object(compress.subprocess, "run") as run, \
                patch.object(Environment, "check_commands", return_value=True), \
                patch.object(compress, "CmdCheck", return_value=CmdCheck("gs")) as check, \
                contextlib.redirect_stdout(io.StringIO()):
            check.return_value.path = "gs"
            self.assertEqual(compress.main(), 1)
        output.assert_not_called()
        run.assert_not_called()

    def test_decrypt_removes_pdfa_without_changing_content_or_other_metadata(self) -> None:
        namespace = "http://www.aiim.org/pdfa/ns/id/"
        cases = (
            (namespace, '', '<a:part>1</a:part><a:conformance>B</a:conformance>', None),
            (namespace, 'a:part="2" a:conformance="U"', '', "secret"),
            (namespace, 'a:part="3"', '<a:conformance>A</a:conformance>', ""),
            (namespace, '', f'<part xmlns="{namespace}">4</part><a:rev>2020</a:rev>', None),
            (namespace.rstrip("/"), 'a:part="1" a:conformance="B"', '', None),
        )
        for index, (uri, attributes, elements, password) in enumerate(cases):
            with self.subTest(index=index):
                xml = f'''<?xpacket begin="" id="sample"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about="" xmlns:a="{uri}"
        xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:custom="urn:custom"
        custom:kind="custom:Book" {attributes}>
      {elements}
      <dc:title><rdf:Alt><rdf:li xml:lang="x-default">标题 &amp; title</rdf:li></rdf:Alt></dc:title>
      <custom:note>Keep PDF/A in ordinary text.</custom:note>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta><?xpacket end="w"?>'''
                self.make_source(password, xml)
                original = self.source.read_bytes()
                self.output = self.folder / f"ordinary-{index}.pdf"
                with pymupdf.open(self.source) as source:
                    if password:
                        source.authenticate(password)
                    self.assertTrue(Pdf.has_pdfa_identification(source))
                    self.assertEqual(source.get_xml_metadata(), xml)
                    pixels = [page.get_pixmap().samples for page in source]
                    labels = Pdf.read_page_labels(source)
                    toc = source.get_toc()
                self.assertEqual(self.run_decrypt([password] if password else []), 0)
                with pymupdf.open(self.output) as result:
                    self.assertFalse(result.is_encrypted)
                    cleaned = result.get_xml_metadata()
                    self.assertFalse(Pdf.has_pdfa_identification(result))
                    self.assert_structure(result, cleaned)
                    self.assertEqual(result.get_toc(), toc)
                    self.assertEqual(Pdf.read_page_labels(result), labels)
                    self.assertEqual([page.get_pixmap().samples for page in result], pixels)
                    with minidom.parseString(cleaned) as metadata:
                        self.assertFalse(metadata.getElementsByTagNameNS(uri, "*"))
                        for element in metadata.getElementsByTagName("*"):
                            self.assertFalse(any(attr.namespaceURI == uri for attr in element.attributes.values()))
                        item = metadata.getElementsByTagName("rdf:li")[0]
                        self.assertEqual(item.getAttribute("xml:lang"), "x-default")
                        assert item.firstChild is not None
                        self.assertEqual(item.firstChild.nodeValue, "标题 & title")
                        description = metadata.getElementsByTagName("rdf:Description")[0]
                        self.assertEqual(description.getAttribute("custom:kind"), "custom:Book")
                        self.assertEqual(description.getAttribute("xmlns:custom"), "urn:custom")
                        self.assertIn("Keep PDF/A in ordinary text.", cleaned)
                self.assertEqual(self.source.read_bytes(), original)

    def test_save_without_xmp_does_not_add_metadata(self) -> None:
        with pymupdf.open() as document:
            document.new_page()
            Pdf.save_new(document, self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(result.get_xml_metadata(), "")

    def test_malformed_pdfa_xmp_fails_without_partial_output(self) -> None:
        self.make_source(xml_metadata='<broken xmlns:a="http://www.aiim.org/pdfa/ns/id/">')
        original = self.source.read_bytes()
        self.assertEqual(self.run_decrypt([]), 1)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), original)

    def test_existing_output_and_input_are_protected(self) -> None:
        self.make_source("")
        self.output.write_bytes(b"existing content")
        self.assertEqual(self.run_decrypt([]), 1)
        self.assertEqual(self.output.read_bytes(), b"existing content")
        self.output = self.source
        original = self.source.read_bytes()
        self.assertEqual(self.run_decrypt([]), 1)
        self.assertEqual(self.source.read_bytes(), original)

    def test_save_failure_or_interrupt_removes_only_new_output(self) -> None:
        for failure in (OSError("write failed"), KeyboardInterrupt()):
            with pymupdf.open(self.source) as document:
                with patch.object(document, "save", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        Pdf.save_new(document, self.output)
            self.assertFalse(self.output.exists())
            self.assertTrue(self.source.exists())

    def write_bookmarks(self, append: bool) -> None:
        """Exercise bookmark insertion with missing levels and invalid page targets."""
        mapping = bookmarks._PageMapping(2, bookmarks._BookPagesPerPdf.SINGLE, bookmarks._FirstPdfPageCount.ONE)
        entries = [
            {"page": -1, "level": 3, "title": "前言"},
            {"page": 1, "level": 1, "title": "Chapter"},
            {"page": 2, "level": 2, "title": "Child"},
            {"page": 99, "level": 1, "title": "Out of range"},
        ]
        mode = bookmarks._BookmarkWriteMode.APPEND if append else bookmarks._BookmarkWriteMode.REPLACE
        with pymupdf.open(self.source) as document, contextlib.redirect_stdout(io.StringIO()):
            bookmarks._write_bookmarks(document, entries, mapping, 1, mode)
            Pdf.save_new(document, self.output)

    def test_append_keeps_original_destinations_styles_and_collapse(self) -> None:
        self.write_bookmarks(append=True)
        with pymupdf.open(self.output) as result:
            self.assert_structure(result)
            toc = result.get_toc()
            self.assertEqual(toc[:3], [[1, "Original", 1], [2, "Nested", 2], [1, "Website", -1]])
            xref = result.get_outline_xrefs()[0]
            self.assertIn("/FitH 72", result.xref_get_key(xref, "Dest")[1])
            self.assertEqual(result.xref_get_key(xref, "F"), ("int", "3"))
            self.assertEqual(result.xref_get_key(xref, "Count"), ("int", "-1"))
            self.assertEqual(result.get_toc(False)[2][3]["uri"], "https://example.com/")
            self.assertEqual(toc[3:], [[1, "Cover", 1], [1, "Table of Contents", 1],
                                       [1, "前言", 1], [1, "Chapter", 2], [2, "Child", 3]])

    def test_replace_preserves_document_and_builds_only_new_outline(self) -> None:
        self.write_bookmarks(append=False)
        with pymupdf.open(self.output) as result:
            self.assert_structure(result)
            self.assertEqual(result.get_toc(), [[1, "Cover", 1], [1, "Table of Contents", 1],
                                                [1, "前言", 1], [1, "Chapter", 2], [2, "Child", 3]])

    def test_bookmark_cli_authenticates_and_saves(self) -> None:
        self.make_source("secret")
        mapping = bookmarks._PageMapping(3, bookmarks._BookPagesPerPdf.SINGLE, bookmarks._FirstPdfPageCount.ONE)
        original = self.source.read_bytes()
        for mode in ("a", "r"):
            for answer in ("", "y", "n"):
                self.output = self.folder / f"labels-{mode}-{answer or 'default'}.pdf"
                replies = [mode, answer] + ([""] if answer != "n" else [])
                with (
                    self.subTest(mode=mode, answer=answer),
                    patch.object(sys, "argv", [str(bookmarks.__file__), str(self.source), "-o", str(self.output)]),
                    patch.object(Input, "resolve_output_path", return_value=str(self.output)),
                    patch.object(Input, "input_password", return_value="secret"),
                    patch.object(bookmarks, "_select_page_mapping", return_value=mapping),
                    patch.object(bookmarks, "_select_toc_pdf_page", return_value=2),
                    patch.object(bookmarks, "_read_bookmark_pages", return_value=[{"page": 2, "level": 1, "title": "New"}]),
                    patch("builtins.input", side_effect=replies),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(bookmarks.main(), 0)
                with pymupdf.open(self.output) as result:
                    self.assertFalse(result.is_encrypted)
                    self.assertEqual(result.get_toc()[-1], [1, "New", 4])
                    expected = ["Old-5", "Old-6", "Old-7", "Old-8"] if answer == "n" else ["Old-5", "C1", "1", "2"]
                    self.assertEqual([page.get_label() for page in result], expected)
        self.assertEqual(self.source.read_bytes(), original)

    def run_tag_editor(self, replies: list[str], outputs: list[Path]) -> int:
        """Run the real menu with scripted input and repository-local output paths."""
        with (
            patch.object(sys, "argv", [str(tags.__file__), str(self.source)]),
            patch.object(Input, "resolve_output_path", side_effect=[str(path) for path in outputs]),
            patch("builtins.input", side_effect=replies),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return tags.main()

    def test_tag_editor_repeated_edits_and_saves_preserve_pdf(self) -> None:
        self.make_source("secret")
        original = self.source.read_bytes()
        second = self.folder / "second.pdf"
        with pymupdf.open(self.source) as source:
            source.authenticate("secret")
            before_toc = source.get_toc(False)
            for entry in before_toc:
                entry[3].pop("xref", None)
            before_pixels = [page.get_pixmap().samples for page in source]
        replies = [
            "a", "2", "3", "10", "A-",
            "a", "3", "3", "7", "B",
            "s",
            "p", "1,2-3,-1",
            "a", "-1", "", "", "C",
            "w",
        ]
        with patch.object(Input, "input_password", return_value="secret"):
            self.assertEqual(self.run_tag_editor(replies, [self.output, second]), 0)
        for path, expected in ((self.output, ["Old-5", "A-10", "B7", "Old-8"]),
                               (second, ["", "", "", "C1"])):
            with pymupdf.open(path) as result:
                self.assertFalse(result.is_encrypted)
                self.assertEqual(Pdf.read_page_labels(result), expected)
                self.assert_structure(result)
                after_toc = result.get_toc(False)
                for entry in after_toc:
                    entry[3].pop("xref", None)
                self.assertEqual(after_toc, before_toc)
                root = result.get_outline_xrefs()[0]
                self.assertIn("/FitH 72", result.xref_get_key(root, "Dest")[1])
                self.assertEqual(result.xref_get_key(root, "Count"), ("int", "-1"))
                self.assertEqual([page.get_pixmap().samples for page in result], before_pixels)
        self.assertEqual(self.source.read_bytes(), original)

    def test_tag_editor_exit_discards_only_pending_changes(self) -> None:
        original = self.source.read_bytes()
        self.assertEqual(self.run_tag_editor(["c", "q"], []), 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.run_tag_editor(["a", "1", "", "", "C", "s", "c", "q"], [self.output]), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["C1", "C2", "C3", "C4"])
        self.assertEqual(self.source.read_bytes(), original)

    def test_tag_editor_clear_all_then_add_signed_sequence(self) -> None:
        self.assertEqual(self.run_tag_editor(["c", "w"], [self.output]), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["", "", "", ""])
        second = self.folder / "signed.pdf"
        self.assertEqual(self.run_tag_editor(["c", "a", "2", "", "-1", "", "w"], [second]), 0)
        with pymupdf.open(second) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["", "-1", "0", "1"])

    def test_tag_editor_validates_ranges_and_required_start(self) -> None:
        replies = [
            "a", "", "0", "99", "3", "2", "-1", "", "",
            "p", "0", "99", "1,-1",
            "p", "",
            "w",
        ]
        self.assertEqual(self.run_tag_editor(replies, [self.output]), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["", "Old-6", "1", ""])

    def test_tag_editor_save_failure_keeps_edits_for_retry(self) -> None:
        real_save = Pdf.save_new
        fail_next = True

        def fail_once(document: pymupdf.Document, output_path: str | Path, *, compact: bool = True) -> None:
            nonlocal fail_next
            if fail_next:
                fail_next = False
                raise OSError("Simulated write failure")
            real_save(document, output_path, compact=compact)

        with patch.object(Pdf, "save_new", side_effect=fail_once):
            self.assertEqual(self.run_tag_editor(["c", "w", "w"], [self.output, self.output]), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["", "", "", ""])

    def test_tag_editor_existing_output_is_protected_and_retryable(self) -> None:
        self.output.write_bytes(b"existing content")
        second = self.folder / "retry.pdf"
        original = self.source.read_bytes()
        self.assertEqual(self.run_tag_editor(["c", "w", "w", "w"],
                                             [self.source, self.output, second]), 0)
        self.assertEqual(self.output.read_bytes(), b"existing content")
        self.assertEqual(self.source.read_bytes(), original)
        with pymupdf.open(second) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["", "", "", ""])

    def test_label_helpers_preserve_literal_text_and_validate_length(self) -> None:
        labels = ["", "A-(1)", r"目录\\2", "-1"]
        with pymupdf.open(self.source) as document:
            before = Pdf.read_page_labels(document)
            with self.assertRaises(ValueError):
                Pdf.write_page_labels(document, ["too short"])
            self.assertEqual(Pdf.read_page_labels(document), before)
            Pdf.write_page_labels(document, labels)
            Pdf.save_new(document, self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), labels)

    def test_tag_editor_keeps_unselected_physical_numbers_without_rules(self) -> None:
        unlabelled = self.folder / "unlabelled.pdf"
        with pymupdf.open(self.source) as document:
            document.set_page_labels([])
            Pdf.save_new(document, unlabelled)
        self.source = unlabelled
        self.assertEqual(self.run_tag_editor(["p", "2-3", "w"], [self.output]), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["1", "", "", "4"])

    def test_label_reader_handles_number_tree_styles_and_indirect_rules(self) -> None:
        with pymupdf.open(self.source) as document:
            roman = document.get_new_xref()
            document.update_object(roman, "<< /S /r /St 9 >>")
            child = document.get_new_xref()
            document.update_object(child, f"<< /Nums [0 {roman} 0 R 2 << /S /A /St 27 /P (A-) >>] >>")
            document.xref_set_key(document.pdf_catalog(), "PageLabels", f"<< /Kids [{child} 0 R] >>")
            self.assertEqual(Pdf.read_page_labels(document), ["ix", "x", "A-AA", "A-BB"])
            labels = Pdf.read_page_labels(document)
            labels[1] = ""
            Pdf.write_page_labels(document, labels)
            Pdf.save_new(document, self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["ix", "", "A-AA", "A-BB"])

    def test_reset_labels_preserves_front_matter(self) -> None:
        mapping = bookmarks._PageMapping(4, bookmarks._BookPagesPerPdf.SINGLE, bookmarks._FirstPdfPageCount.ONE)
        with pymupdf.open(self.source) as document:
            before_toc = document.get_toc()
            bookmarks._reset_page_labels(document, mapping, 2, 2)
            Pdf.save_new(document, self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(Pdf.read_page_labels(result), ["Old-5", "C1", "Old-7", "1"])
            self.assertEqual(result.get_toc(), before_toc)
            self.assert_structure(result)

    def test_multi_page_labels_match_book_mapping(self) -> None:
        for count, first_count, expected in (
            (2, 1, ["Old-5", "C1", "1", "2-3"]),
            (2, 2, ["Old-5", "C1", "1-2", "3-4"]),
            (4, 2, ["Old-5", "C1", "1-2", "3-6"]),
            (4, 4, ["Old-5", "C1", "1-4", "5-8"]),
        ):
            mapping = bookmarks._PageMapping(3, bookmarks._BookPagesPerPdf(count), bookmarks._FirstPdfPageCount(first_count))
            with self.subTest(count=count, first_count=first_count), pymupdf.open(self.source) as document:
                bookmarks._reset_page_labels(document, mapping, 2, 2)
                self.assertEqual([page.get_label() for page in document], expected)
                for index in range(4):
                    for book_page in mapping.book_pages(index):
                        self.assertEqual(mapping.pdf_index(book_page), index)

    def test_preserve_unlabelled_front_matter_and_reject_invalid_anchor(self) -> None:
        mapping = bookmarks._PageMapping(4, bookmarks._BookPagesPerPdf.SINGLE, bookmarks._FirstPdfPageCount.ONE)
        with pymupdf.open(self.source) as document:
            document.set_page_labels([])
            bookmarks._reset_page_labels(document, mapping, 2, 2)
            self.assertEqual([page.get_label() for page in document], ["1", "C1", "3", "1"])
            original = document.get_page_labels()
            invalid = bookmarks._PageMapping(9, bookmarks._BookPagesPerPdf.SINGLE, bookmarks._FirstPdfPageCount.ONE)
            with self.assertRaises(ValueError):
                bookmarks._reset_page_labels(document, invalid, 2, 3)
            self.assertEqual(document.get_page_labels(), original)

    def test_page_layout_mapping_and_empty_input(self) -> None:
        for count in (1, 2, 4):
            layout = bookmarks._BookPagesPerPdf(count)
            mapping = bookmarks._PageMapping(3, layout, bookmarks._FirstPdfPageCount.ONE)
            self.assertEqual(mapping.pdf_index(1), 2)
            self.assertEqual(mapping.pdf_index(2), 3)
            self.assertEqual(mapping.pdf_index(-1), 1 if count == 1 else 2)
            for value in ("", "null", "[]", '""'):
                self.assertEqual(bookmarks._parse_bookmark_page(value, mapping), [])

    def test_first_book_page_prompt_default_and_validation(self) -> None:
        for replies, expected in ((["1", "17", "20"], 20), (["1", "17", ""], 1),
                                  (["1", "17", "0", "20"], 20)):
            output = io.StringIO()
            with self.subTest(replies=replies), patch("builtins.input", side_effect=replies) as prompt:
                with contextlib.redirect_stdout(output):
                    mapping = bookmarks._select_page_mapping()
            self.assertEqual(mapping.page_offset, 17)
            self.assertEqual(mapping.first_book_page, expected)
            self.assertEqual(mapping.pdf_index(expected), 16)
            self.assertIn(f"{expected}", output.getvalue())
            self.assertIn("PDF page containing the first book page", prompt.call_args_list[1].args[0])
            self.assertIn("page number of the first book page", prompt.call_args_list[2].args[0])

    def test_pdf_page_17_matches_book_page_20_in_bookmarks_and_labels(self) -> None:
        mapping = bookmarks._PageMapping(17, bookmarks._BookPagesPerPdf.SINGLE,
                                         bookmarks._FirstPdfPageCount.ONE, first_book_page=20)
        with pymupdf.open() as document, contextlib.redirect_stdout(io.StringIO()):
            for _ in range(22):
                document.new_page()
            entries = [{"page": page, "level": 1, "title": f"Book {page}"} for page in (19, 20, 21)]
            bookmarks._write_bookmarks(document, entries, mapping, 1, bookmarks._BookmarkWriteMode.REPLACE)
            bookmarks._reset_page_labels(document, mapping, 1, 16)
            Pdf.save_new(document, self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(result.get_toc()[-3:], [[1, "Book 19", 16], [1, "Book 20", 17], [1, "Book 21", 18]])
            self.assertEqual(Pdf.read_page_labels(result)[15:], ["C16", "20", "21", "22", "23", "24", "25"])

    def test_custom_first_book_page_multi_up_labels_and_inverse_mapping(self) -> None:
        for count, first_count, expected in (
            (2, 1, ["20", "21-22"]), (2, 2, ["20-21", "22-23"]),
            (4, 1, ["20", "21-24"]), (4, 2, ["20-21", "22-25"]),
            (4, 3, ["20-22", "23-26"]), (4, 4, ["20-23", "24-27"]),
        ):
            mapping = bookmarks._PageMapping(3, bookmarks._BookPagesPerPdf(count),
                                             bookmarks._FirstPdfPageCount(first_count), first_book_page=20)
            with self.subTest(count=count, first_count=first_count), pymupdf.open(self.source) as document:
                bookmarks._reset_page_labels(document, mapping, 2, 2)
                self.assertEqual(Pdf.read_page_labels(document), ["Old-5", "C1", *expected])
                for index in range(-20, 10):
                    for book_page in mapping.book_pages(index):
                        self.assertNotEqual(book_page, 0)
                        self.assertEqual(mapping.pdf_index(book_page), index)


if __name__ == "__main__":
    unittest.main()
