"""Verify reusable PDF operations independently of the PDF GUI packages.

Run: conda run -n base python -m unittest discover -s test -p test_pdf_utils.py.
Requires PyMuPDF; creates in-memory PDFs only.
"""

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *


class PdfUtilityTests(unittest.TestCase):
    """Check pixel limits and retained PDF objects through the public Pdf API."""

    def test_rotated_rgb_preview_respects_pixel_budget_and_annotation_switch(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=201.3, height=301.7)
            page.draw_rect((20, 20, 180, 180), fill=(.2, .4, .6))
            page.add_text_annot((50, 50), "Annotation")
            page = document.reload_page(page)
            before = page.read_contents()
            for rotation in (0, 2.5, 45, 90, -175):
                pixmap = Pdf.render_page(page, dpi=600, rotation=rotation, max_pixels=10_000)
                self.assertLessEqual(pixmap.width * pixmap.height, 10_000)
                self.assertEqual(pixmap.n, 3)
                self.assertFalse(pixmap.alpha)
            self.assertNotEqual(Pdf.render_page(page).samples, Pdf.render_page(page, annotations=False).samples)
            self.assertEqual(page.read_contents(), before)
            for kwargs in ({"dpi": 0}, {"rotation": float("nan")}, {"max_pixels": 0}):
                with self.assertRaises(ValueError):
                    Pdf.render_page(page, **kwargs)

    def test_outline_roundtrip_keeps_actions_styles_and_validates_before_changes(self) -> None:
        with pymupdf.open() as document:
            for _ in range(3):
                document.new_page()
            root = Pdf.append_bookmark(document, "Root", 0)
            Pdf.append_bookmark(document, "Child", 1, root)
            uri = Pdf.append_bookmark(document, "Website", 0)
            document.xref_set_key(uri, "Dest", "null")
            document.xref_set_key(uri, "A", "<< /S /URI /URI (https://example.com) >>")
            document.xref_set_key(root, "C", "[1 0 0]")
            document.xref_set_key(root, "Count", "-1")
            original = Pdf.read_bookmarks(document)
            old_uri = document.xref_get_key(uri, "A")
            for invalid in ([replace(original[0], level=2)], [PdfBookmark("Bad", 4)],
                            [PdfBookmark("Missing original", 1, original_xref=99999)]):
                with self.assertRaises(ValueError):
                    Pdf.write_bookmarks(document, invalid)
                self.assertEqual(Pdf.read_bookmarks(document), original)
            Pdf.write_bookmarks(document, [replace(original[0], title="Renamed"), *original[1:]])
            rewritten = Pdf.read_bookmarks(document)
            self.assertEqual([entry.title for entry in rewritten], ["Renamed", "Child", "Website"])
            first_xref, uri_xref = rewritten[0].original_xref, rewritten[2].original_xref
            assert first_xref is not None and uri_xref is not None
            self.assertEqual(document.xref_get_key(first_xref, "C"), ("array", "[1 0 0]"))
            self.assertEqual(document.xref_get_key(first_xref, "Count"), ("int", "-1"))
            self.assertEqual(document.xref_get_key(uri_xref, "A"), old_uri)
            Pdf.write_bookmarks(document, [])
            self.assertEqual(Pdf.read_bookmarks(document), [])

    def test_label_edits_validate_whole_selection_before_mutating(self) -> None:
        labels = ["i", "ii", "1", "2"]
        for update in (Pdf.number_page_labels, Pdf.clear_page_labels):
            with self.assertRaises(ValueError):
                update(labels, [0, 99])
            self.assertEqual(labels, ["i", "ii", "1", "2"])
        Pdf.generate_page_labels(labels, 3, 20, [2, 2], toc_prefix="TOC-")
        self.assertEqual(labels, ["i", "TOC-1", "20", "21"])
        Pdf.number_page_labels(labels, [3, 2], -1, "A")
        self.assertEqual(labels[2:], ["A0", "A-1"])

    def test_numbered_outputs_and_staged_replacement(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="pdf-save-test-") as directory:
            folder = Path(directory)
            output = folder / "result.pdf"
            self.assertEqual(Paths.available_path(output), output)
            output.write_bytes(b"Existing output")
            self.assertEqual(Paths.available_path(output).name, "result_1.pdf")
            (folder / "result_1.pdf").touch()
            self.assertEqual(Paths.available_path(output).name, "result_2.pdf")
            with pymupdf.open() as document:
                document.new_page()
                with self.assertRaises(FileExistsError):
                    Pdf.save_new(document, output)
                with patch.object(pymupdf.Document, "save", side_effect=OSError("Disk write failed")):
                    with self.assertRaises(OSError):
                        Pdf.save_new(document, output, overwrite=True)
                self.assertEqual(output.read_bytes(), b"Existing output")
                self.assertFalse(list(folder.glob(".pdf-save-*")))
                Pdf.save_new(document, output, overwrite=True)
            with Pdf.open_document(output, interactive=False) as (document, _):
                self.assertEqual(document.page_count, 1)
                with self.assertRaises(ValueError):
                    Pdf.save_new(document, output, overwrite=True)


if __name__ == "__main__":
    unittest.main()
