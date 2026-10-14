"""PDF splitter regression tests using generated scans and saved output.

Run: conda run -n base python -m unittest discover -s test -p test_pdf_split_pages.py
Requires PyMuPDF and tqdm; temporary files stay under the repository tmp.
"""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from test_pdf_tools import load_script
from utils import *


splitter = load_script("pdf-split-pages")
ROOT = Path(__file__).resolve().parents[1]


class PdfSplitTests(unittest.TestCase):
    """Exercise split geometry, navigation, labels, and real CLI output."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="pdf-split-", dir=ROOT / "tmp")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def make_document(self, rotation: int = 0, cropped: bool = False) -> pymupdf.Document:
        """Build scans with four distinct quadrants and a blank second page."""
        document = pymupdf.open()
        page = document.new_page(width=200, height=120)
        colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
        samples = bytes(component for y in range(120) for x in range(200)
                        for component in colors[(2 if y >= 60 else 0) + (1 if x >= 100 else 0)])
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, 200, 120, samples, False)
        page.insert_image(page.rect, pixmap=pixmap)
        if cropped:
            page.set_cropbox(pymupdf.Rect(20, 10, 180, 110))
        page.set_rotation(rotation)
        document.new_page(width=80, height=100)
        document.set_metadata({"title": "Split scan test"})
        document.set_xml_metadata("<metadata>retained</metadata>")
        document.embfile_add("readme.txt", b"retained attachment")
        document.set_page_labels([{"startpage": 0, "prefix": "Old-", "style": "D"}])
        return document

    def test_rendered_halves_match_original_all_directions_rotations_and_crops(self) -> None:
        for rotation in (0, 90, 180, 270):
            for cropped in (False, True):
                for axis in splitter._Axis:
                    for reverse in (False, True):
                        with (
                            self.subTest(rotation=rotation, cropped=cropped, axis=axis, reverse=reverse),
                            self.make_document(rotation, cropped) as source,
                            pymupdf.open() as output,
                        ):
                            plan = splitter._build_plan(source, {1}, axis, reverse, 50)
                            expected = [source[0].get_pixmap(clip=piece.clip).samples for piece in plan[0]]
                            splitter._split_document(source, output, plan, progress=False)
                            self.assertEqual(output.page_count, 3)
                            for index, piece in enumerate(plan[0]):
                                page = output[index]
                                self.assertAlmostEqual(page.rect.width, piece.clip.width)
                                self.assertAlmostEqual(page.rect.height, piece.clip.height)
                                self.assertEqual(page.get_pixmap().samples, expected[index])
                            self.assertEqual(output[2].rect, source[1].rect)
                            self.assertEqual(output[0].get_images()[0][0], output[1].get_images()[0][0])
                            self.assertEqual(output.get_page_labels(), [])

    def test_custom_split_and_blank_pages(self) -> None:
        with self.make_document() as source, pymupdf.open() as output:
            plan = splitter._build_plan(source, set(), splitter._Axis.LEFT_RIGHT, True, 25)
            splitter._split_document(source, output, plan, progress=False)
            self.assertEqual([page.rect.width for page in output], [150, 50, 60, 20])
            self.assertEqual([page.rect.height for page in output], [120, 120, 100, 100])

    def test_bookmarks_links_labels_and_metadata_after_saving(self) -> None:
        with self.make_document() as source, pymupdf.open() as output:
            source.set_toc([
                [1, "Left", 1, {"kind": pymupdf.LINK_GOTO, "page": 0, "to": pymupdf.Point(20, 20), "bold": True}],
                [2, "Right", 1, {"kind": pymupdf.LINK_GOTO, "page": 0, "to": pymupdf.Point(160, 90)}],
                [1, "Whole-page target", 1],
                [1, "Ignored page", 2],
                [1, "Website", -1, {"kind": pymupdf.LINK_URI, "uri": "https://example.com/"}],
            ])
            xref = source.get_outline_xrefs()[2]
            source.xref_set_key(xref, "A", "null")
            source.xref_set_key(xref, "Dest", f"[{source.page_xref(0)} 0 R /Fit]")
            source[1].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 40, 30),
                                   "page": 0, "to": pymupdf.Point(160, 90)})
            source[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(90, 10, 110, 30),
                                   "uri": "https://example.com/"})
            # Reopen raw outline edits as a real input PDF, avoiding stale
            # in-memory outline caches after xref_set_key().
            with pymupdf.open(stream=source.tobytes(), filetype="pdf") as reopened:
                plan = splitter._build_plan(reopened, {1}, splitter._Axis.LEFT_RIGHT, True, 50)
                ambiguous, skipped = splitter._split_document(reopened, output, plan, progress=False)
            self.assertEqual((ambiguous, skipped), (1, 0), source.get_toc(False))
            path = self.folder / "output.pdf"
            Pdf.save_new(output, path)
        with pymupdf.open(path) as result:
            self.assertEqual([item[2] for item in result.get_toc()], [2, 1, 1, 3, -1])
            toc = result.get_toc(False)
            self.assertTrue(toc[0][3]["bold"])
            self.assertTrue(toc[0][3]["collapse"])
            self.assertEqual(toc[1][3]["to"], pymupdf.Point(60, 90))
            self.assertEqual(toc[4][3]["uri"], "https://example.com/")
            self.assertEqual(result[2].get_links()[0]["page"], 0)
            self.assertEqual(result[2].get_links()[0]["to"], pymupdf.Point(60, 90))
            for page in (result[0], result[1]):
                self.assertEqual(page.get_links()[0]["uri"], "https://example.com/")
                self.assertEqual(page.get_links()[0]["from"].width, 10)
            self.assertEqual(result.get_page_labels(), [])
            self.assertEqual(result.xref_get_key(result.pdf_catalog(), "PageLabels")[0], "null")
            self.assertEqual(result.metadata["title"], "Split scan test")
            self.assertEqual(result.get_xml_metadata(), "<metadata>retained</metadata>")
            self.assertEqual(result.embfile_get("readme.txt"), b"retained attachment")

    def test_rotated_bookmark_and_link_destinations(self) -> None:
        for rotation in (90, 180, 270):
            with self.subTest(rotation=rotation), self.make_document(rotation, True) as source, pymupdf.open() as output:
                point = pymupdf.Point(source[0].rect.width * 0.75, source[0].rect.height * 0.75)
                source.set_toc([[1, "Target", 1, {"kind": pymupdf.LINK_GOTO, "page": 0, "to": point}]])
                page = source[0]
                unrotated = point * page.derotation_matrix
                pdf_point = pymupdf.Point(unrotated.x + page.cropbox.x0,
                                          page.mediabox.y1 - page.cropbox.y0 - unrotated.y)
                xref = source.get_outline_xrefs()[0]
                source.xref_set_key(xref, "A/D", f"[{page.xref} 0 R /XYZ {pdf_point.x} {pdf_point.y} 0]")
                source[1].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 40, 30),
                                       "page": 0, "to": pdf_point * page.transformation_matrix})
                source[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(10, 10, 30, 30),
                                       "uri": "https://example.com/"})
                with pymupdf.open(stream=source.tobytes(), filetype="pdf") as reopened:
                    self.assertEqual(reopened.get_toc(False)[0][3]["to"], point)
                    link_rect = reopened[0].get_links()[0]["from"]
                    plan = splitter._build_plan(reopened, {1}, splitter._Axis.TOP_BOTTOM, False, 50)
                    splitter._split_document(reopened, output, plan, progress=False)
                path = self.folder / f"rotation-{rotation}.pdf"
                Pdf.save_new(output, path)
            with pymupdf.open(path) as result:
                target = point - plan[0][1].clip.tl
                self.assertEqual(result.get_toc()[0][2], 2)
                self.assertEqual(result.get_toc(False)[0][3]["to"], target)
                self.assertEqual(result[2].get_links()[0]["page"], 1)
                self.assertEqual(result[2].get_links()[0]["to"], target)
                for piece in plan[0]:
                    clipped = link_rect & piece.clip
                    links = result[piece.output_index].get_links()
                    if clipped.is_empty:
                        self.assertEqual(links, [])
                    else:
                        self.assertEqual(links[0]["from"], pymupdf.Rect(
                            clipped.x0 - piece.clip.x0, clipped.y0 - piece.clip.y0,
                            clipped.x1 - piece.clip.x0, clipped.y1 - piece.clip.y0,
                        ))

    def test_page_annotations_remain_visible_in_cropped_halves(self) -> None:
        with self.make_document(90, True) as source, pymupdf.open() as output:
            annot = source[0].add_rect_annot(pymupdf.Rect(30, 30, 130, 70))
            annot.set_colors(stroke=(0, 0, 0), fill=(1, 0, 1))
            annot.update()
            plan = splitter._build_plan(source, {1}, splitter._Axis.LEFT_RIGHT, False, 50)
            expected = [source[0].get_pixmap(clip=piece.clip).samples for piece in plan[0]]
            splitter._split_document(source, output, plan, progress=False)
            for index in range(2):
                self.assertEqual(output[index].get_pixmap().samples, expected[index])

    def test_cli_ignore_all_still_removes_tags_and_warns(self) -> None:
        source_path = self.folder / "source.pdf"
        output_path = self.folder / "output.pdf"
        with self.make_document() as source:
            source.save(source_path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                        owner_pw="owner", user_pw="secret")
        original = source_path.read_bytes()
        with (
            patch.object(sys, "argv", [str(splitter.__file__), str(source_path)]),
            patch.object(Input, "input_password", return_value="secret"),
            patch.object(Input, "resolve_output_path", return_value=str(output_path)),
            patch("builtins.input", side_effect=["t", "2", "", "1,-1"]),
            contextlib.redirect_stdout(io.StringIO()) as console,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(splitter.main(), 0)
            self.assertIn("ALL page tags / page labels will be removed", console.getvalue())
            self.assertIn("including on ignored pages", console.getvalue())
        with pymupdf.open(output_path) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(result.page_count, 2)
            self.assertEqual(result.get_page_labels(), [])
            self.assertEqual(result[0].rect, pymupdf.Rect(0, 0, 200, 120))
        self.assertEqual(source_path.read_bytes(), original)

    def test_plan_rejects_invalid_input_before_processing(self) -> None:
        with self.make_document() as source:
            for percent in (0, 100, -1, float("nan"), float("inf")):
                with self.subTest(percent=percent), self.assertRaises(ValueError):
                    splitter._build_plan(source, set(), splitter._Axis.LEFT_RIGHT, False, percent)
            with self.assertRaises(ValueError):
                splitter._build_plan(source, {2}, splitter._Axis.LEFT_RIGHT, False, 50)

    def test_cli_never_overwrites_input(self) -> None:
        source_path = self.folder / "source.pdf"
        with self.make_document() as document:
            document.save(source_path)
        original = source_path.read_bytes()
        with (
            patch.object(sys, "argv", [str(splitter.__file__), str(source_path)]),
            patch.object(Input, "resolve_output_path", return_value=str(source_path)),
            patch("builtins.input", side_effect=["", "", "", ""]),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(splitter.main(), 1)
        self.assertEqual(source_path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
