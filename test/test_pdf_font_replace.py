"""Font replacement regressions using generated, redistributable test fonts.

Run: conda run -n base python -m unittest discover -s test -p test_pdf_font_replace.py
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.t2CharStringPen import T2CharStringPen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *  # noqa: E402

spec = importlib.util.spec_from_file_location("pdf_font_replace", ROOT / "tools/document-processing/pdf-font-replace.py")
assert spec and spec.loader
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)


def make_font(path: Path, *, bold: bool = False, italic: bool = False, cff: bool = False,
              family: str = "Fixture") -> None:
    """Build a static font with ASCII/CJK glyphs, deliberately different advances."""
    characters = list(range(32, 127)) + [ord(char) for char in "中文字体测试"]
    cmap = {code: f"uni{code:04X}" for code in characters}
    glyph_order = [".notdef", *cmap.values()]
    builder = FontBuilder(1000, isTTF=not cff)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(cmap)
    glyphs = {}
    for name in glyph_order:
        pen = T2CharStringPen(900, None) if cff else TTGlyphPen(None)
        if name != cmap[32]:
            pen.moveTo((80, 0))
            pen.lineTo((750, 0))
            pen.lineTo((750, 700))
            pen.lineTo((80, 700))
            pen.closePath()
        glyphs[name] = pen.getCharString() if cff else pen.glyph()
    style = "BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
    if cff:
        builder.setupCFF(f"{family}-{style}", {"FullName": f"{family} {style}", "FamilyName": family, "Weight": style}, glyphs, {})
    else:
        builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (900, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": style, "uniqueFontIdentifier": f"{family}-{style}",
                            "fullName": f"{family} {style}", "psName": f"{family}-{style}"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200,
                    usWeightClass=700 if bold else 400, fsSelection=(32 if bold else 0) | (1 if italic else 0) | (64 if not bold and not italic else 0))
    builder.setupPost(italicAngle=-12 if italic else 0)
    builder.font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    builder.font["name"].setName("测试字体", 1, 3, 1, 0x804)
    builder.save(path)


class FontReplaceTests(unittest.TestCase):
    """Verify positioning, selective rewriting and direct output saving."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pdf-font-test-", dir=ROOT / "tmp")
        self.folder = Path(self.temporary.name)
        self.source = self.folder / "input.pdf"
        self.output = self.folder / "output.pdf"
        self.faces = {}
        for style in FontStyle:
            bold, italic = style.value
            path = self.folder / f"{style.name}.ttf"
            make_font(path, bold=bold, italic=italic)
            self.faces[style] = Font.read_faces(path)[0]
        with pymupdf.open() as document:
            for _ in range(2):
                page = document.new_page(width=300, height=300)
                page.insert_text((30, 50), "ABC XYZ", fontname="helv", fontsize=12)
                page.insert_text((30, 100), "Large text", fontname="helv", fontsize=18)
                page.insert_text((30, 150), "Keep Times", fontname="tiro", fontsize=12)
            document.set_toc([[1, "First", 1], [1, "Second", 2]])
            document[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(30, 30, 80, 50), "uri": "https://example.com"})
            document.set_metadata({"title": "Font replacement test", "author": "Fixture"})
            document.set_xml_metadata('<x:metadata xmlns:x="urn:fixture">Retain this</x:metadata>')
            document.embfile_add("note.txt", b"Keep the attachment")
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), 0)
            pixmap.clear_with(127)
            document[0].insert_image(pymupdf.Rect(200, 200, 220, 220), pixmap=pixmap)
            document[0].add_text_annot((250, 100), "Keep annotation")
            document.save(self.source)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def convert(self, names=None, sizes=(), ignored=(), embedding=app._Embedding.SUBSET) -> int:
        with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
            original = [[(char[0], char[2], span["size"], span["dir"], span["color"], span["opacity"], span["type"])
                         for span in page.get_texttrace() for char in span["chars"]] for page in document]
            count = app._convert(document, self.output, (app._Rule(names, sizes, tuple(ignored), self.faces, embedding),))
        if count:
            with pymupdf.open(self.output) as result:
                for page, before in zip(result, original):
                    after = [(char[0], char[2], span["size"], span["dir"], span["color"], span["opacity"], span["type"])
                             for span in page.get_texttrace() for char in span["chars"]]
                    self.assertEqual(len(before), len(after))
                    for first, second in zip(before, after):
                        self.assertEqual(first[0], second[0])
                        self.assertEqual(first[3:], second[3:])
                        for expected, actual in zip((*first[1], first[2]), (*second[1], second[2])):
                            self.assertAlmostEqual(expected, actual, delta=0.0001)
        return count

    def test_simple_fonts_sizes_ignored_pages_and_structures(self) -> None:
        source_bytes = self.source.read_bytes()
        self.assertEqual(self.convert({"Helvetica"}, ((12, 12),), (1,)), 7)
        self.assertEqual(source_bytes, self.source.read_bytes())
        with pymupdf.open(self.source) as source, pymupdf.open(self.output) as result:
            self.assertEqual(source.metadata, result.metadata)
            self.assertEqual(source.get_xml_metadata(), result.get_xml_metadata())
            self.assertEqual(source.get_toc(simple=False), result.get_toc(simple=False))
            self.assertEqual(source.get_page_labels(), result.get_page_labels())
            self.assertEqual(source.embfile_names(), result.embfile_names())
            for name in source.embfile_names():
                self.assertEqual(source.embfile_get(name), result.embfile_get(name))
            for before, after in zip(source, result):
                self.assertEqual(before.rect, after.rect)
                self.assertEqual(before.get_links(), after.get_links())
                self.assertEqual([annotation.info for annotation in before.annots()],
                                 [annotation.info for annotation in after.annots()])
                self.assertEqual([row[:8] for row in before.get_images(full=True)],
                                 [row[:8] for row in after.get_images(full=True)])
                for row in before.get_images(full=True):
                    self.assertEqual(source.xref_stream(row[0]), result.xref_stream(row[0]))
            self.assertEqual(source[1].read_contents(), result[1].read_contents())
            fonts = [(span["font"], span["size"]) for span in result[0].get_texttrace()]
            self.assertIn(("Fixture-Regular", 12), fonts)
            self.assertIn(("Helvetica", 18), fonts)
            self.assertIn(("Times-Roman", 12), fonts)

    def test_multiple_source_fonts_can_share_or_use_different_targets(self) -> None:
        path = self.folder / "alternate.ttf"
        make_font(path, family="Alternate")
        alternate = {FontStyle.REGULAR: Font.read_faces(path)[0]}
        for second_faces in (self.faces, alternate):
            with self.subTest(target=second_faces[FontStyle.REGULAR].name):
                output = self.folder / f"multiple-{second_faces[FontStyle.REGULAR].name}.pdf"
                rules = [app._Rule({"Helvetica"}, (), (), self.faces, app._Embedding.SUBSET),
                         app._Rule({"Times-Roman"}, (), (), second_faces, app._Embedding.SUBSET)]
                with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app._convert(document, output, rules), 54)
                with pymupdf.open(output) as result:
                    spans = result[0].get_texttrace()
                    self.assertEqual(spans[0]["font"], "Fixture-Regular")
                    self.assertEqual(spans[2]["font"], second_faces[FontStyle.REGULAR].name)

    def test_rules_match_original_fonts_without_cascading(self) -> None:
        path = self.folder / "alternate.ttf"
        make_font(path, family="Alternate")
        alternate = {FontStyle.REGULAR: Font.read_faces(path)[0]}
        with pymupdf.open(self.source) as document:
            page = document[0]
            page.insert_font(fontname="OriginalFixture", fontfile=self.faces[FontStyle.REGULAR].path)
            page.insert_text((30, 180), "Original", fontname="OriginalFixture", fontsize=12)
            document.save(self.folder / "with-fixture.pdf")
        rules = [app._Rule({"Helvetica"}, (), (), self.faces, app._Embedding.SUBSET),
                 app._Rule({"Fixture-Regular"}, (), (), alternate, app._Embedding.FULL)]
        with Pdf.open_document(self.folder / "with-fixture.pdf") as (document, _), \
                contextlib.redirect_stdout(io.StringIO()):
            app._convert(document, self.output, rules)
        with pymupdf.open(self.output) as result:
            spans = result[0].get_texttrace()
            self.assertEqual(spans[0]["font"], "Fixture-Regular")
            self.assertEqual(spans[1]["font"], "Fixture-Regular")
            self.assertEqual(spans[-1]["font"], "Alternate-Regular")

    def test_rule_sizes_pages_and_first_match_priority(self) -> None:
        path = self.folder / "alternate.ttf"
        make_font(path, family="Alternate")
        alternate = {FontStyle.REGULAR: Font.read_faces(path)[0]}
        rules = [app._Rule({"Helvetica"}, ((12, 12),), (1,), self.faces, app._Embedding.SUBSET,
                          color=(1, 0, 0)),
                 app._Rule({"Helvetica"}, (), (), alternate, app._Embedding.FULL, color=(0, 0, 1))]
        with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
            app._convert(document, self.output, rules)
        with pymupdf.open(self.output) as result:
            first = result[0].get_texttrace()
            second = result[1].get_texttrace()
            self.assertEqual([span["font"] for span in first],
                             ["Fixture-Regular", "Alternate-Regular", "Times-Roman"])
            self.assertEqual([span["font"] for span in second],
                             ["Alternate-Regular", "Alternate-Regular", "Times-Roman"])
            self.assertEqual([span["color"] for span in first], [(1, 0, 0), (0, 0, 1), (0, 0, 0)])
            self.assertEqual([span["color"] for span in second], [(0, 0, 1), (0, 0, 1), (0, 0, 0)])
            with pymupdf.open(self.source) as original:
                for before_page, after_page in zip(original, result):
                    before = [(char[0], char[2]) for span in before_page.get_texttrace() for char in span["chars"]]
                    after = [(char[0], char[2]) for span in after_page.get_texttrace() for char in span["chars"]]
                    self.assertEqual(before, after)

    def test_interactive_add_rule_then_start_saves_once(self) -> None:
        with patch.object(sys, "argv", [str(app.__file__), str(self.source), "-o", str(self.output)]), \
                patch.object(Menu, "select", side_effect=["P", ["1"], app._SourceColorMode.ALL, "F", app._Embedding.SUBSET, False, False, False,
                                                        "P", ["2"], app._SourceColorMode.ALL, "F", app._Embedding.FULL, True, False, True]), \
                patch.object(Input, "input_real_ranges", return_value=None), \
                patch.object(Input, "input_index_ranges", side_effect=[(0, 1), (), (0, 1), ()]), \
                patch.object(Input, "resolve_input_path", return_value=str(self.faces[FontStyle.REGULAR].path)), \
                patch.object(Pdf, "save_new", wraps=Pdf.save_new) as save, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(), 0)
        self.assertEqual(save.call_count, 1)
        with pymupdf.open(self.output) as result:
            self.assertEqual({span["font"] for page in result for span in page.get_texttrace()}, {"Fixture-Regular"})

    def test_color_restores_graphics_and_preserves_text_show_state(self) -> None:
        colors = (b"", b".4 g .7 G", b"0 .5 .7 rg .8 .2 .1 RG",
                  b"1 0 .5 0 k 0 1 .5 0 K",
                  b"/DeviceRGB cs .1 .2 .3 sc /DeviceRGB CS .7 .8 .9 SCN")
        for index, setup in enumerate(colors):
            with self.subTest(setup=setup), Pdf.open_document(self.source) as (document, _):
                content = (setup + b" q .1 g .2 G Q BT /helv 12 Tf 2 Tr 15 TL 1 0 0 1 30 250 Tm "
                           b"(A) Tj [(B) -30 (C)] TJ (D) ' 2 1 (E F) \" "
                           b"/tiro 12 Tf (Keep) Tj ET 20 20 30 30 re B")
                stream = app._object(document, "<< >>", content)
                document.xref_set_key(document[0].xref, "Contents", f"{stream} 0 R")
                before = document[0].get_texttrace()
                drawings = document[0].get_drawings()
                output = self.folder / f"colors-{index}.pdf"
                rule = app._Rule({"Helvetica"}, (), (1,), self.faces, app._Embedding.SUBSET, color=(1, 0, 0))
                with contextlib.redirect_stdout(io.StringIO()):
                    app._convert(document, output, (rule,))
                with pymupdf.open(output) as result:
                    after = result[0].get_texttrace()
                    # Color changes can split MuPDF's batches, so compare glyphs
                    # separately for fill/stroke rather than relying on span counts.
                    for render_type in (0, 1):
                        original_chars = [(span, char) for span in before if span["type"] == render_type
                                          for char in span["chars"]]
                        changed_chars = [(span, char) for span in after if span["type"] == render_type
                                         for char in span["chars"]]
                        self.assertEqual(len(original_chars), len(changed_chars))
                        for (original, first), (changed, second) in zip(original_chars, changed_chars):
                            expected = (1, 0, 0) if original["font"] == "Helvetica" else original["color"]
                            self.assertEqual(changed["color"], expected)
                            for key in ("dir", "size", "opacity", "type"):
                                self.assertEqual(original[key], changed[key])
                            self.assertEqual(first[0], second[0])
                            for a, b in zip(first[2], second[2]):
                                self.assertAlmostEqual(a, b, delta=0.0001)
                    self.assertEqual([{k: v for k, v in item.items() if k != "seqno"} for item in drawings],
                                     [{k: v for k, v in item.items() if k != "seqno"} for item in result[0].get_drawings()])
                    self.assertEqual(document[1].get_texttrace(), result[1].get_texttrace())

    def test_source_color_discovery_and_multiselection(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            page = document[0]
            page.insert_text((30, 180), "Red", color=(1, 0, 0))
            page.insert_text((30, 210), "Hidden", color=(0, 0, 1), render_mode=3)
            page.draw_rect(pymupdf.Rect(10, 10, 20, 20), color=(0, 1, 0), fill=(0, 1, 0))
            before = page.read_contents()
            xref_count = document.xref_length()
            self.assertEqual(app._pdf_colors(document, (0,)), [0, 0xFF0000])
            self.assertEqual(app._pdf_colors(document, (1,)), [0])
            with patch.object(Menu, "select", side_effect=[app._SourceColorMode.PAGES, ["1-2"]]), \
                    patch.object(Input, "input_index_ranges", return_value=(0,)), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app._select_source_colors(document), frozenset((0, 0xFF0000)))
            self.assertEqual(page.read_contents(), before)
            self.assertEqual(document.xref_length(), xref_count)

    def test_source_color_empty_pages_back_manual_and_exit(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            document.new_page()
            scenarios = [
                ([app._SourceColorMode.PAGES, app._SourceColorMode.ALL], [(2,)], [], None),
                ([app._SourceColorMode.PAGES, ["R"], app._SourceColorMode.MANUAL], [(0,)], ["#F00"], frozenset((0xFF0000,))),
                ([app._SourceColorMode.MANUAL, app._SourceColorMode.MANUAL, app._SourceColorMode.ALL], [], ["bad", ""], None),
            ]
            for menus, pages, values, expected in scenarios:
                with self.subTest(menus=menus), patch.object(Menu, "select", side_effect=menus), \
                        patch.object(Input, "input_index_ranges", side_effect=pages), \
                        patch.object(Input, "prompt", side_effect=values), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app._select_source_colors(document), expected)
            with patch.object(Menu, "select", side_effect=[app._SourceColorMode.PAGES, ["E"]]), \
                    patch.object(Input, "input_index_ranges", return_value=(0,)), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
                app._select_source_colors(document)

    def test_source_color_combines_with_font_size_pages_and_rule_priority(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            page = document[0]
            content = (b"BT /helv 12 Tf 30 250 Td 1 0 0 rg (A) Tj 0 0 1 rg (B) Tj "
                       b"1 0 0 rg /helv 18 Tf (C) Tj /tiro 12 Tf (D) Tj ET")
            stream = app._object(document, "<< >>", content)
            document.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
            before = [(char[0], char[2]) for span in page.get_texttrace() for char in span["chars"]]
            rules = (
                app._Rule({"Helvetica"}, ((12, 12),), (1,), self.faces, app._Embedding.SUBSET,
                          color=(0, 1, 0), source_colors=frozenset((0xFF0000,))),
                app._Rule({"Helvetica"}, ((12, 12),), (1,), self.faces, app._Embedding.SUBSET,
                          color=(1, 1, 0), source_colors=frozenset((0xFF0000, 0x0000FF))),
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app._convert(document, self.output, rules), 2)
        with pymupdf.open(self.output) as result:
            spans = result[0].get_texttrace()
            self.assertEqual([span["font"] for span in spans],
                             ["Fixture-Regular", "Fixture-Regular", "Helvetica", "Times-Roman"])
            self.assertEqual([span["color"] for span in spans], [(0, 1, 0), (1, 1, 0), (1, 0, 0), (1, 0, 0)])
            self.assertEqual(before, [(char[0], char[2]) for span in spans for char in span["chars"]])
            self.assertNotIn("Fixture-Regular", {span["font"] for span in result[1].get_texttrace()})

    def test_source_color_gray_cmyk_named_and_default_spaces(self) -> None:
        for index, color in enumerate((b".5 g", b"0 .5 1 0 k", b"/Original cs .2 .5 .8 scn",
                                       b"/DeviceCMYK cs", b".2 .5 .8 rg")):
            with self.subTest(color=color), Pdf.open_document(self.source) as (document, _):
                page = document[0]
                resources = app._reference(document, page.xref, "Resources")
                document.xref_set_key(resources, "ColorSpace",
                                      "<< /Original [/CalRGB << /WhitePoint [1 1 1] >>] "
                                      "/DefaultRGB [/CalRGB << /WhitePoint [1 1 1] /Gamma [2 2 2] >>] >>")
                content = color + b" BT /helv 12 Tf 30 250 Td (A) Tj 0 1 0 rg (B) Tj ET"
                stream = app._object(document, "<< >>", content)
                document.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
                original = page.get_texttrace()
                rule = app._Rule({"Helvetica"}, (), (1,), self.faces, app._Embedding.SUBSET,
                                 source_colors=frozenset((app._rgb_key(original[0]["color"]),)))
                output = self.folder / f"source-color-{index}.pdf"
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app._convert(document, output, (rule,)), 1)
                with pymupdf.open(output) as result:
                    spans = result[0].get_texttrace()
                    self.assertEqual([span["font"] for span in spans], ["Fixture-Regular", "Helvetica"])
                    self.assertEqual([span["color"] for span in spans], [span["color"] for span in original])

    def test_source_color_matches_stroke_but_not_hidden_or_fill_only_text(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            content = (b"0 1 0 rg 0 0 1 RG BT /helv 12 Tf 30 250 Td 2 Tr (A) Tj "
                       b"0 Tr (B) Tj 3 Tr (C) Tj ET")
            stream = app._object(document, "<< >>", content)
            document.xref_set_key(document[0].xref, "Contents", f"{stream} 0 R")
            rule = app._Rule({"Helvetica"}, (), (1,), self.faces, app._Embedding.SUBSET,
                             source_colors=frozenset((0x0000FF,)))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app._convert(document, self.output, (rule,)), 1)
        with pymupdf.open(self.output) as result:
            self.assertEqual([span["font"] for span in result[0].get_texttrace()],
                             ["Fixture-Regular", "Fixture-Regular", "Helvetica", "Helvetica"])

    def test_interactive_source_color_from_pages(self) -> None:
        with patch.object(sys, "argv", [str(app.__file__), str(self.source), "-o", str(self.output)]), \
                patch.object(Menu, "select", side_effect=["P", ["1"], app._SourceColorMode.PAGES, ["1"], "F",
                                                        app._Embedding.SUBSET, False, False, True]), \
                patch.object(Input, "input_real_ranges", return_value=None), \
                patch.object(Input, "input_index_ranges", side_effect=[(0, 1), (0,), (1,)]), \
                patch.object(Input, "resolve_input_path", return_value=str(self.faces[FontStyle.REGULAR].path)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(), 0)
        with pymupdf.open(self.output) as result:
            self.assertEqual(result[0].get_texttrace()[0]["font"], "Fixture-Regular")
            self.assertEqual(result[1].get_texttrace()[0]["font"], "Helvetica")

    def test_source_color_limits_required_styles_and_can_match_nothing(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            document[0].insert_text((30, 180), "Red bold", fontname="hebo", color=(1, 0, 0))
            self.assertEqual(app._required_styles(document, None, (), (), frozenset((0xFF0000,))),
                             {FontStyle.BOLD})
            rule = app._Rule(None, (), (), self.faces, app._Embedding.SUBSET,
                             source_colors=frozenset((0xFF00FF,)))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app._convert(document, self.output, (rule,)), 0)
            self.assertFalse(self.output.exists())

    def test_color_in_form_restores_inherited_named_color_space(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            page = document[0]
            resources = app._reference(document, page.xref, "Resources")
            fonts = app._dictionary(document, resources, "Font")
            document.xref_set_key(resources, "ColorSpace", "<< /Original [/CalRGB << /WhitePoint [1 1 1] >>] >>")
            form = app._object(document, f"<< /Type /XObject /Subtype /Form /BBox [0 0 300 300] "
                               f"/Resources << /Font {fonts} >> >>",
                               b"BT /helv 12 Tf 30 250 Td (A) Tj /tiro 12 Tf (B) Tj ET 20 20 30 30 re f")
            document.xref_set_key(resources, "XObject", f"<< /Fixture {form} 0 R >>")
            stream = app._object(document, "<< >>", b"/Original cs .2 .5 .8 scn /Fixture Do")
            document.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
            before = page.get_texttrace()
            drawings = page.get_drawings()
            rule = app._Rule({"Helvetica"}, (), (1,), self.faces, app._Embedding.SUBSET, color=(1, 0, 0),
                             source_colors=frozenset((app._rgb_key(before[0]["color"]),)))
            with contextlib.redirect_stdout(io.StringIO()):
                app._convert(document, self.output, (rule,))
        with pymupdf.open(self.output) as result:
            after = result[0].get_texttrace()
            self.assertEqual(after[0]["color"], (1, 0, 0))
            self.assertEqual(after[1]["color"], before[1]["color"])
            self.assertEqual(after[1]["chars"], before[1]["chars"])
            self.assertEqual([{k: v for k, v in item.items() if k != "seqno"} for item in drawings],
                             [{k: v for k, v in item.items() if k != "seqno"} for item in result[0].get_drawings()])

    def test_interactive_color_retries_invalid_input(self) -> None:
        with patch.object(sys, "argv", [str(app.__file__), str(self.source), "-o", str(self.output)]), \
                patch.object(Menu, "select", side_effect=["P", ["1"], app._SourceColorMode.ALL, "F", app._Embedding.SUBSET,
                                                        False, True, True]), \
                patch.object(Input, "prompt", side_effect=["256, 0, 0", "#FF0000"]) as prompt, \
                patch.object(Input, "input_real_ranges", return_value=None), \
                patch.object(Input, "input_index_ranges", side_effect=[(0, 1), (1,)]), \
                patch.object(Input, "resolve_input_path", return_value=str(self.faces[FontStyle.REGULAR].path)), \
                contextlib.redirect_stdout(io.StringIO()) as messages:
            self.assertEqual(app.main(), 0)
        self.assertEqual(prompt.call_count, 2)
        self.assertIn("Invalid color", messages.getvalue())
        with pymupdf.open(self.output) as result:
            self.assertEqual(result[0].get_texttrace()[0]["color"], (1, 0, 0))
            self.assertEqual(result[1].get_texttrace()[0]["color"], (0, 0, 0))

    def test_color_in_form_restores_inherited_pattern(self) -> None:
        with Pdf.open_document(self.source) as (document, _):
            page = document[0]
            resources = app._reference(document, page.xref, "Resources")
            fonts = app._dictionary(document, resources, "Font")
            pattern = app._object(document, "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
                                  "/BBox [0 0 5 5] /XStep 5 /YStep 5 /Resources << >> >>",
                                  b"0 0 1 rg 0 0 3 3 re f")
            document.xref_set_key(resources, "Pattern", f"<< /Original {pattern} 0 R >>")
            form = app._object(document, f"<< /Type /XObject /Subtype /Form /BBox [0 0 300 300] "
                               f"/Resources << /Font {fonts} >> >>",
                               b"BT /helv 12 Tf 30 250 Td (A) Tj /tiro 12 Tf (B) Tj ET 20 20 30 30 re f")
            document.xref_set_key(resources, "XObject", f"<< /Fixture {form} 0 R >>")
            stream = app._object(document, "<< >>",
                                 b"q 0 g BT /helv 12 Tf 60 200 Td (Trigger) Tj ET Q "
                                 b"/Pattern cs /Original scn /Fixture Do")
            document.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
            clip = pymupdf.Rect(10, 240, 60, 290)
            before = page.get_pixmap(clip=clip).samples
            self.assertIn(0, before)
            rule = app._Rule({"Helvetica"}, (), (1,), self.faces, app._Embedding.SUBSET, color=(1, 0, 0))
            with contextlib.redirect_stdout(io.StringIO()):
                app._convert(document, self.output, (rule,))
        with pymupdf.open(self.output) as result:
            self.assertEqual(before, result[0].get_pixmap(clip=clip).samples)

    def embedded_source(self) -> tuple[int, int]:
        """Build two pages sharing an embedded font; return font and program xrefs."""
        self.source = self.folder / "embedded-source.pdf"
        with pymupdf.open() as document:
            font_xref = 0
            for _ in range(2):
                page = document.new_page()
                font_xref = page.insert_font(fontname="Original", fontfile=self.faces[FontStyle.REGULAR].path)
                page.insert_text((30, 50), "ABC", fontname="Original", fontsize=12)
                page.insert_text((30, 80), "XYZ", fontname="Original", fontsize=18)
            child = app._reference(document, font_xref, "DescendantFonts")
            descriptor = app._reference(document, child, "FontDescriptor")
            program = app._reference(document, descriptor, "FontFile2")
            document.save(self.source)
        return font_xref, program

    def test_per_rule_original_embedding_keep_and_delete(self) -> None:
        font_xref, program = self.embedded_source()
        source_bytes = self.source.read_bytes()
        for remove in (False, True):
            with self.subTest(remove=remove):
                output = self.folder / f"cleanup-{remove}.pdf"
                rule = app._Rule({"Fixture-Regular"}, (), (), self.faces, app._Embedding.SUBSET, remove)
                with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
                    app._convert(document, output, (rule,))
                with pymupdf.open(output) as result:
                    self.assertEqual(bool(result.extract_font(font_xref)[3]), not remove)
                    self.assertEqual(result.xref_stream(program) is None, remove)
                    self.assertIn("ABC", result[0].get_text())
                    targets = [row[0] for row in result[0].get_fonts() if row[0] != font_xref]
                    self.assertTrue(any(result.extract_font(xref)[3] for xref in targets))
        self.assertEqual(self.source.read_bytes(), source_bytes)

    def test_cleanup_retains_partial_ignored_and_explicitly_kept_fonts(self) -> None:
        font_xref, _ = self.embedded_source()
        names = {"Fixture-Regular"}
        scenarios = [
            [app._Rule(names, ((12, 12),), (), self.faces, app._Embedding.SUBSET, True)],
            [app._Rule(names, (), (1,), self.faces, app._Embedding.SUBSET, True)],
            [app._Rule(names, ((12, 12),), (), self.faces, app._Embedding.SUBSET, True),
             app._Rule(names, ((18, 18),), (), self.faces, app._Embedding.SUBSET, False)],
        ]
        for index, rules in enumerate(scenarios):
            with self.subTest(scenario=index):
                output = self.folder / f"retained-{index}.pdf"
                with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
                    app._convert(document, output, rules)
                with pymupdf.open(output) as result:
                    self.assertTrue(result.extract_font(font_xref)[3])

    def test_cleanup_protects_annotation_appearance_fonts(self) -> None:
        font_xref, _ = self.embedded_source()
        with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
            annotation = document[0].add_freetext_annot(pymupdf.Rect(20, 100, 200, 140), "Annotation")
            appearance = app._reference(document, annotation.xref, "AP/N")
            document.xref_set_key(appearance, "Resources", f"<< /Font << /Original {font_xref} 0 R >> >>")
            document.update_stream(appearance, b"BT /Original 12 Tf 1 0 0 1 10 10 Tm <0024> Tj ET")
            rule = app._Rule({"Fixture-Regular"}, (), (), self.faces, app._Embedding.SUBSET, True)
            app._convert(document, self.output, (rule,))
        with pymupdf.open(self.output) as result:
            self.assertTrue(result.extract_font(font_xref)[3])
            self.assertIn(b"/Original 12 Tf", result.xref_stream(appearance))

    def test_cleanup_copies_descriptors_shared_with_another_font(self) -> None:
        font_xref, program = self.embedded_source()
        with Pdf.open_document(self.source) as (document, _), contextlib.redirect_stdout(io.StringIO()):
            other = app._object(document, document.xref_object(font_xref))
            resources = app._reference(document, document[0].xref, "Resources")
            document.xref_set_key(resources, "Font/Other", f"{other} 0 R")
            rule = app._Rule({"Fixture-Regular"}, (), (), self.faces, app._Embedding.SUBSET, True)
            app._convert(document, self.output, (rule,))
        with pymupdf.open(self.output) as result:
            self.assertFalse(result.extract_font(font_xref)[3])
            self.assertTrue(result.extract_font(other)[3])
            self.assertIsNotNone(result.xref_stream(program))

    def test_cleanup_handles_shared_forms_and_ignored_form_pages(self) -> None:
        self.embedded_source()
        forms = self.folder / "embedded-forms.pdf"
        with pymupdf.open(self.source) as original, pymupdf.open() as document:
            for _ in range(2):
                page = document.new_page()
                page.show_pdf_page(page.rect, original, 0)
            font_xref = document[0].get_fonts(full=True)[0][0]
            document.save(forms)
        for ignored in ((), (1,)):
            with self.subTest(ignored=ignored):
                output = self.folder / f"clean-forms-{len(ignored)}.pdf"
                rule = app._Rule({"Fixture-Regular"}, (), ignored, self.faces, app._Embedding.SUBSET, True)
                with Pdf.open_document(forms) as (document, _), contextlib.redirect_stdout(io.StringIO()):
                    app._convert(document, output, (rule,))
                with pymupdf.open(output) as result:
                    self.assertEqual(bool(result.extract_font(font_xref)[3]), bool(ignored))
                    self.assertTrue(all("ABC" in page.get_text() for page in result))

    def test_full_embedding(self) -> None:
        self.assertGreater(self.convert({"Helvetica"}, embedding=app._Embedding.FULL), 0)
        with pymupdf.open(self.output) as document:
            embedded = [row for row in document[0].get_fonts() if row[3] == "Fixture-Regular"]
            self.assertTrue(embedded)

    def test_identity_h_cjk_and_four_styles(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page()
            for index, fontname in enumerate(("helv", "hebo", "heit", "hebi")):
                page.insert_text((30, 50 + index * 30), "Style text", fontname=fontname, fontsize=12)
            page.insert_font(fontname="CJK", fontfile=self.faces[FontStyle.REGULAR].path)
            page.insert_text((30, 200), "中文测试", fontname="CJK", fontsize=14)
            document.save(self.folder / "styles.pdf")
        self.source = self.folder / "styles.pdf"
        self.assertEqual(self.convert(), 44)
        with pymupdf.open(self.output) as document:
            fonts = {span["font"] for span in document[0].get_texttrace()}
            self.assertEqual(fonts, {"Fixture-Regular", "Fixture-Bold", "Fixture-Italic", "Fixture-BoldItalic"})

    def test_name_keyed_cff_target(self) -> None:
        target = self.folder / "target.otf"
        make_font(target, cff=True)
        self.faces[FontStyle.REGULAR] = Font.read_faces(target)[0]
        self.assertGreater(self.convert({"Helvetica"}), 0)

    def test_form_shared_between_pages_is_cloned(self) -> None:
        with pymupdf.open(self.source) as original, pymupdf.open() as document:
            for _ in range(2):
                page = document.new_page(width=300, height=300)
                page.show_pdf_page(page.rect, original, 0)
            document.save(self.folder / "forms.pdf")
        self.source = self.folder / "forms.pdf"
        self.assertGreater(self.convert({"Helvetica"}, ignored=(1,)), 0)
        with pymupdf.open(self.output) as result:
            self.assertIn("Fixture-Regular", {span["font"] for span in result[0].get_texttrace()})
            self.assertNotIn("Fixture-Regular", {span["font"] for span in result[1].get_texttrace()})

    def test_scaled_text_uses_effective_size(self) -> None:
        with pymupdf.open(self.source) as document:
            stream = app._object(document, "<< >>", b"q BT /helv 240 Tf .05 0 0 .05 30 250 Tm (ABC) Tj ET Q")
            document.xref_set_key(document[0].xref, "Contents", f"{stream} 0 R")
            document.save(self.folder / "scaled.pdf")
        self.source = self.folder / "scaled.pdf"
        self.assertEqual(self.convert({"Helvetica"}, ((12, 12),), (1,)), 3)

    def test_horizontal_scaling_and_word_spacing_keep_origins(self) -> None:
        with pymupdf.open(self.source) as document:
            content = b"q BT /helv 12 Tf 50 Tz 3 Tw 1 Tc 1 0 0 1 30 250 Tm [(A B) -35 ( C)] TJ ET Q"
            stream = app._object(document, "<< >>", content)
            document.xref_set_key(document[0].xref, "Contents", f"{stream} 0 R")
            document.save(self.folder / "horizontal.pdf")
        self.source = self.folder / "horizontal.pdf"
        self.assertEqual(self.convert({"Helvetica"}, ((6, 6),), (1,)), 5)

    def test_encrypted_input_retries_and_output_has_no_protection(self) -> None:
        with pymupdf.open(self.source) as document:
            document.save(self.folder / "encrypted.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256,
                          owner_pw="owner", user_pw="secret", permissions=pymupdf.PDF_PERM_PRINT)
        self.source = self.folder / "encrypted.pdf"
        with patch.object(Input, "input_password", side_effect=["wrong", "secret"]) as password:
            self.assertGreater(self.convert({"Helvetica"}), 0)
            self.assertEqual(password.call_count, 2)
        with pymupdf.open(self.output) as document:
            self.assertFalse(document.is_encrypted)
            self.assertEqual(document.xref_get_key(-1, "Encrypt"), ("null", "null"))

    def test_missing_glyphs_fail_without_output(self) -> None:
        from fontTools.ttLib import TTFont
        path = self.faces[FontStyle.REGULAR].path
        with TTFont(path) as font:
            for table in font["cmap"].tables:
                table.cmap.pop(ord("A"), None)
            font.save(self.folder / "missing.ttf")
        self.faces[FontStyle.REGULAR] = Font.read_faces(self.folder / "missing.ttf")[0]
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.convert({"Helvetica"})
        self.assertFalse(self.output.exists())

    def test_missing_style_prompts_or_exits_without_substitution(self) -> None:
        regular = {FontStyle.REGULAR: self.faces[FontStyle.REGULAR]}
        with patch.object(Menu, "select", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            app._complete_styles(regular, {FontStyle.BOLD})
        with patch.object(Menu, "select", return_value=True), \
                patch.object(Input, "resolve_input_path", return_value=str(self.faces[FontStyle.BOLD].path)), \
                contextlib.redirect_stdout(io.StringIO()):
            app._complete_styles(regular, {FontStyle.BOLD})
        self.assertEqual(regular[FontStyle.BOLD].style, FontStyle.BOLD)

    def test_readonly_font_list_excludes_image_only_pages(self) -> None:
        with pymupdf.open(self.source) as document:
            page = document.new_page()
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), 0)
            pixmap.clear_with(127)
            page.insert_image(pymupdf.Rect(10, 10, 30, 30), pixmap=pixmap)
            self.assertEqual(app._pdf_fonts(document, (2,)), [])
            self.assertEqual(app._pdf_fonts(document, (0,)), ["Helvetica", "Times-Roman"])

    def test_no_matching_text_writes_nothing(self) -> None:
        self.assertEqual(self.convert({"Helvetica"}, ((30, 40),)), 0)
        self.assertFalse(self.output.exists())

    def test_conversion_saves_directly_without_reopening(self) -> None:
        with Pdf.open_document(self.source) as (document, _), \
                patch.object(Pdf, "save_new", wraps=Pdf.save_new) as save, \
                patch.object(Pdf, "open_document", side_effect=AssertionError("Output must not be reopened")), \
                patch.object(pymupdf, "open", side_effect=AssertionError("Output must not be reopened")), \
                contextlib.redirect_stdout(io.StringIO()):
            rule = app._Rule({"Helvetica"}, (), (), self.faces, app._Embedding.SUBSET)
            self.assertGreater(app._convert(document, self.output, (rule,)), 0)
            save.assert_called_once_with(document, self.output, compact=False)
        self.assertTrue(self.output.exists())
        self.assertFalse(list(self.folder.glob(".pdf-font-replace-*")))

    def test_existing_file_is_preserved(self) -> None:
        self.output.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_terminal_progress_bars_replace_per_page_messages(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as progress, \
                patch.object(progress, "isatty", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                Pdf.open_document(self.source) as (document, _):
            Font.read_catalog([self.faces[FontStyle.REGULAR].path], show_progress=True)
            rule = app._Rule({"Helvetica"}, (), (), self.faces, app._Embedding.SUBSET)
            app._convert(document, self.output, (rule,))
        self.assertIn("Reading font metadata", progress.getvalue())
        self.assertIn("Replacing fonts", progress.getvalue())
        self.assertIn("Embedding fonts", progress.getvalue())
        self.assertNotIn("Checked page", output.getvalue())

    def test_localized_alias_and_canonical_name_find_same_face(self) -> None:
        faces = list(self.faces.values())
        self.assertEqual(Font.search_faces(faces, "测试字体"), Font.search_faces(faces, "Fixture"))
        self.assertEqual(Font.search_faces(faces, "测试字体 bOlD"),
                         [self.faces[FontStyle.BOLD], self.faces[FontStyle.BOLD_ITALIC]])
        self.assertEqual(Font.search_faces(faces, "  "), faces)
        label = self.faces[FontStyle.REGULAR].label()
        self.assertIn(f"{FLCyan}Fixture-Regular{CRst}", label)
        self.assertIn(f"{CRst}Fixture Regular{CRst}", label)
        self.assertIn(f"{FGray}Fixture{CRst}", label)
        self.assertIn("测试字体", label)
        self.assertIn(f"{FLGreen}测试字体{CRst}", label)
        self.assertIn(f"{CRst} / {FLGreen}", label)

    def test_font_scan_quiets_only_legacy_timestamp_warnings(self) -> None:
        import logging
        from fontTools.ttLib import TTFont
        from fontTools.ttLib.tables._n_a_m_e import table__n_a_m_e

        path = self.folder / "legacy.ttf"
        with TTFont(self.faces[FontStyle.REGULAR].path, recalcTimestamp=False) as font:
            font["head"].created = 1
            font["head"].modified = 1
            font.save(path)
        logger = logging.getLogger("fontTools.ttLib.tables._h_e_a_d")
        original_filters = logger.filters[:]

        def family_with_warning() -> str:
            logger.warning("An unrelated font warning")
            return "Fixture"

        with self.assertLogs(logger, level="WARNING") as logs, \
                patch.object(table__n_a_m_e, "getBestFamilyName", side_effect=family_with_warning):
            self.assertTrue(Font.read_faces(path))
        self.assertEqual(len(logs.output), 1)
        self.assertIn("An unrelated font warning", logs.output[0])
        self.assertEqual(logger.filters, original_filters)
        with self.assertLogs(logger, level="WARNING") as logs, TTFont(path) as font:
            font["head"]
        self.assertTrue(any("timestamp seems very low" in message for message in logs.output))

    def test_font_collection_and_catalog_skip_unreadable_files(self) -> None:
        from fontTools.ttLib import TTCollection, TTFont

        path = self.folder / "family.ttc"
        with TTFont(self.faces[FontStyle.REGULAR].path) as regular, \
                TTFont(self.faces[FontStyle.BOLD].path) as bold:
            collection = TTCollection()
            collection.fonts = [regular, bold]
            collection.save(path)
        faces = Font.read_faces(path)
        self.assertEqual([face.index for face in faces], [0, 1])
        self.assertEqual([face.style for face in faces], [FontStyle.REGULAR, FontStyle.BOLD])
        self.assertTrue(all(face.path == path.resolve() for face in faces))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            catalog = Font.read_catalog([path, self.folder / "missing.ttf"])
        self.assertEqual(set(catalog), set(faces))
        self.assertIn("could not read 1 font file", output.getvalue())

    def test_family_styles_prefer_nearby_files_and_selected_face(self) -> None:
        from dataclasses import replace

        base = self.faces[FontStyle.REGULAR]
        nearby = self.faces[FontStyle.BOLD]
        remote = replace(nearby, path=self.folder / "elsewhere" / "bold.ttf", name="AAA")
        unrelated = replace(self.faces[FontStyle.ITALIC], family="Unrelated")
        alternative = replace(base, name="AAA")
        result = Font.family_faces(base, [remote, nearby, unrelated, alternative])
        self.assertEqual(result, {FontStyle.REGULAR: base, FontStyle.BOLD: nearby})

    def test_fontless_page_retries_then_selects_or_exits(self) -> None:
        with pymupdf.open(self.source) as document:
            document.new_page()
            for retry in (True, False):
                menus = ["P", retry, ["1"]] if retry else ["P", retry]
                with patch.object(Menu, "select", side_effect=menus), \
                        patch.object(Input, "input_index_ranges", side_effect=[(2,), (0,)]), \
                        patch.object(Input, "prompt", return_value="1"), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    if retry:
                        self.assertEqual(app._select_source_fonts(document), {"Helvetica"})
                    else:
                        with self.assertRaises(KeyboardInterrupt):
                            app._select_source_fonts(document)
                self.assertIn("no text fonts", output.getvalue())

    def test_inline_images_fail_without_publication(self) -> None:
        with self.assertRaisesRegex(ValueError, "Inline-image"):
            list(app._tokens(b"q BI /W 1 /H 1 ID xxx EI Q"))

    def test_source_font_menu_ranges_retry_exit_and_gray_actions(self) -> None:
        cases = [(["P", "1-2"], {"Helvetica", "Times-Roman"}, 1),
                 (["P", "1,2"], {"Helvetica", "Times-Roman"}, 1),
                 (["P", "1,r", "1"], {"Helvetica"}, 1),
                 (["P", "r", "2"], {"Times-Roman"}, 2),
                 (["P", "99", "1"], {"Helvetica"}, 1),
                 (["P", "e"], None, 1)]
        with pymupdf.open(self.source) as document:
            for answers, expected, page_prompts in cases:
                with self.subTest(answers=answers), \
                        patch("builtins.input", side_effect=answers), \
                        patch.object(Input, "input_index_ranges", return_value=(0,)) as pages, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    if expected is None:
                        with self.assertRaises(KeyboardInterrupt):
                            app._select_source_fonts(document)
                    else:
                        self.assertEqual(app._select_source_fonts(document), expected)
                self.assertEqual(pages.call_count, page_prompts)
                self.assertIn(f"{FGray}R{FGray}]{CRst} {FGray}Select pages/search again{CRst}", output.getvalue())
                self.assertIn(f"{FGray}E{FGray}]{CRst} {FGray}Exit{CRst}", output.getvalue())

    def test_lexer_decodes_literals_and_skips_fake_operators(self) -> None:
        tokens = list(app._tokens(b"% fake /font 9 Tf\n[(A\\(B\\)\\040C) -20 <4142>] TJ"))
        self.assertEqual(app._string_bytes(tokens[0].children[0].raw), b"A(B) C")
        self.assertEqual(app._string_bytes(tokens[0].children[2].raw), b"AB")

    def test_interactive_replacement_with_optional_path_arguments(self) -> None:
        for supplied_paths in (True, False):
            with self.subTest(supplied_paths=supplied_paths):
                output = self.folder / f"interactive-{supplied_paths}.pdf"
                arguments = [str(app.__file__)]
                target = str(self.faces[FontStyle.REGULAR].path)
                input_paths = [target] if supplied_paths else [str(self.source), target]
                if supplied_paths:
                    arguments.extend([str(self.source), "-o", str(output)])
                with patch.object(sys, "argv", arguments), \
                        patch.object(Menu, "select", side_effect=["P", ["1"], app._SourceColorMode.ALL, "F", app._Embedding.SUBSET, False, False, True]), \
                        patch.object(Input, "prompt", return_value="1"), \
                        patch.object(Input, "input_real_ranges", return_value=((12, 12),)), \
                        patch.object(Input, "input_index_ranges", side_effect=[(0, 1), (1,)]), \
                        patch.object(Input, "resolve_input_path", side_effect=input_paths) as input_path, \
                        patch.object(Input, "resolve_output_path", return_value=str(output)) as output_path, \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app.main(), 0)
                self.assertEqual(input_path.call_count, len(input_paths))
                self.assertEqual(output_path.call_count, 0 if supplied_paths else 1)
                with pymupdf.open(output) as document:
                    fonts = {(span["font"], span["size"]) for span in document[0].get_texttrace()}
                    self.assertIn(("Fixture-Regular", 12), fonts)
                    self.assertIn(("Helvetica", 18), fonts)
                    self.assertNotIn("Fixture-Regular", {span["font"] for span in document[1].get_texttrace()})


if __name__ == "__main__":
    unittest.main()
