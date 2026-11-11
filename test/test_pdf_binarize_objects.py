"""Verify mixed PDF objects, shared resources and scan output without page flattening."""
import contextlib
from dataclasses import replace
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
import pymupdf

from test_pdf_binarize import ROOT, engine_settings, objects, raster, workflow
from test_rclone_integration import compiler, launcher, utility


def image_bytes(alpha: bool = False) -> bytes:
    """Create a color scan fragment with black ink and optional transparent corners."""
    with Image.new("RGBA" if alpha else "RGB", (80, 60), (0, 0, 0, 0) if alpha else "white") as image:
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 65, 45), fill=(160, 100, 100, 255) if alpha else (160, 100, 100))
        draw.text((15, 20), "SCAN", fill="black")
        with io.BytesIO() as stream:
            image.save(stream, format="PNG")
            return stream.getvalue()


class ObjectPipelineTests(unittest.TestCase):
    """Exercise persisted output, not only object dictionaries before save."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="object-pdf-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source, self.target = self.folder / "source.pdf", self.folder / "result.pdf"

    def convert(self, vectors: bool = False, skip: str = "", workers: int = 2) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            workflow._binarize_pdf(self.source, self.target, 144, 180, workers, skip,
                                  processing=engine_settings._Processing(vectors=vectors))

    def make_mixed(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=240, height=240)
            image = page.insert_image((10, 90, 170, 210), stream=image_bytes())
            page.draw_rect((10, 10, 60, 45), fill=(1, 0, 0), color=(0, .5, 0))
            page.draw_rect((70, 10, 120, 45), fill=(1, 1, 1), color=(1, 1, 1))
            page.insert_text((15, 65), "Native red text", color=(1, 0, 0))
            page.insert_text((15, 120), "Hidden OCR", render_mode=3)
            page.add_text_annot((180, 60), "Retain comment")
            widget = pymupdf.Widget()
            widget.field_name, widget.field_value = "kept", "value"
            widget.field_type, widget.rect = pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.Rect(15, 215, 100, 235)
            page.add_widget(widget)
            second = document.new_page(width=240, height=240)
            second.insert_image((10, 90, 170, 210), xref=image)
            document[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 30, 30),
                                     "page": 1, "to": pymupdf.Point(11, 25), "zoom": 1.5})
            document[1].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(10, 10, 30, 30),
                                     "uri": "https://example.com"})
            document.set_toc([[1, "Exact destination", 1, {"kind": 1, "page": 0,
                                "to": pymupdf.Point(23, 57), "zoom": 1.7}]])
            document.save(self.source)

    def test_native_objects_bookmark_coordinates_and_shared_skipped_image(self) -> None:
        self.make_mixed()
        original_bytes = self.source.read_bytes()
        self.convert(vectors=True, skip="2")
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            self.assertEqual(before[0].get_text(), after[0].get_text())
            for old, new in zip(before[0].get_texttrace(), after[0].get_texttrace()):
                for key in ("chars", "color", "type", "size", "font", "bbox"):
                    self.assertEqual(old[key], new[key])
            self.assertEqual(after[0].get_links()[0]["page"], 1)
            self.assertEqual(after[1].get_links()[0]["uri"], "https://example.com")
            self.assertEqual(next(after[0].annots()).info["content"], "Retain comment")
            self.assertEqual(next(after[0].widgets()).field_value, "value")
            for key in ("to", "zoom", "page", "kind"):
                self.assertEqual(before.get_toc(False)[0][3][key], after.get_toc(False)[0][3][key])
            self.assertEqual(before[1].get_pixmap().samples, after[1].get_pixmap().samples)
            self.assertEqual(after[1].get_images()[0][4], 8)
            self.assertEqual(after[0].get_images()[0][4], 1)
            pix = after[0].get_pixmap()
            self.assertEqual(pix.pixel(25, 25), (0, 0, 0))
            self.assertEqual(pix.pixel(90, 25), (255, 255, 255))
        self.assertEqual(self.source.read_bytes(), original_bytes)

    def test_dpi_policy_caps_each_axis_and_optionally_upsamples(self) -> None:
        for policy, placement, expected in (
            ("cap", (160, 120), (80, 60)),
            ("target", (160, 120), (320, 240)),
            ("cap", (20, 15), (40, 30)),
            ("target", (20, 15), (40, 30)),
            ("cap", (20, 120), (40, 60)),
        ):
            with self.subTest(policy=policy, placement=placement), pymupdf.open() as document:
                width, height = placement
                page = document.new_page(width=200, height=200)
                xref = page.insert_image((0, 0, width, height), stream=image_bytes(), keep_proportion=False)
                processing = replace(engine_settings._Processing(), dpi_policy=engine_settings._DpiPolicy(policy))
                engine = objects._Engine(document, 144, 180, processing, 1)
                try:
                    engine.page_rect = page.rect
                    target = engine._image(xref, pymupdf.Matrix(width, 0, 0, height, 0, 0))
                    engine._finish()
                    document.xref_set_key(page.xref, "Resources", f"<< /XObject << /Result {target} 0 R >> >>")
                    page.set_contents(objects._object(document, data=b"/Result Do"))
                    self.assertEqual(page.get_images()[0][2:4], expected)
                finally:
                    engine.close()

    def test_vector_default_preserves_colors_and_text_only_pages_have_no_image(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=100, height=100)
            page.draw_rect((10, 10, 40, 40), fill=(1, 0, 0))
            page.insert_text((10, 65), "Text")
            document.save(self.source)
        with patch.object(objects, "_render_image") as render:
            self.convert()
        render.assert_not_called()
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            self.assertEqual(before[0].read_contents(), after[0].read_contents())
            self.assertEqual(before[0].get_pixmap().samples, after[0].get_pixmap().samples)
            self.assertEqual(after[0].get_images(), [])

    def test_nested_forms_shared_with_skipped_page_keep_placement_and_text(self) -> None:
        with pymupdf.open() as tile, pymupdf.open() as document:
            page = tile.new_page(width=100, height=100)
            page.insert_image((10, 10, 90, 70), stream=image_bytes())
            page.insert_text((10, 90), "FORM", color=(0, 0, 1))
            page.draw_line((1, 1), (99, 1), color=(1, 0, 0), width=2)
            for _ in range(2):
                page = document.new_page(width=200, height=200)
                page.show_pdf_page(pymupdf.Rect(20, 30, 180, 190), tile, 0, rotate=90)
            document.save(self.source)
        self.convert(vectors=True, skip="2")
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            self.assertEqual(before[1].get_pixmap().samples, after[1].get_pixmap().samples)
            self.assertEqual(before[0].get_text("words"), after[0].get_text("words"))
            self.assertEqual(after[0].get_images()[0][4], 1)
            self.assertEqual(before[0].get_image_info()[0]["bbox"], after[0].get_image_info()[0]["bbox"])

    def test_clip_path_survives_color_override_and_text_inherits_original_red(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=100, height=100)
            page.insert_font(fontname="helv")
            page.set_contents(objects._object(document, data=(
                b"1 0 0 rg 10 10 30 30 re W f BT /helv 10 Tf 12 20 Td (RED) Tj ET "
                b"0 0 1 rg 0 0 100 100 re f")))
            document.save(self.source)
        self.convert(vectors=True)
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            self.assertEqual(after[0].get_texttrace()[0]["color"], before[0].get_texttrace()[0]["color"])
            pix = after[0].get_pixmap()
            self.assertEqual(pix.pixel(5, 5), (255, 255, 255))
            self.assertEqual(pix.pixel(20, 80), (0, 0, 0))

    def test_transparent_image_preserves_underlying_vector(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=80, height=60)
            page.draw_rect(page.rect, color=None, fill=(0, 0, 1))
            page.insert_image(page.rect, stream=image_bytes(alpha=True))
            document.save(self.source)
        self.convert()
        with pymupdf.open(self.target) as document:
            pix = document[0].get_pixmap()
            self.assertEqual(pix.pixel(3, 3), (0, 0, 255))
            self.assertEqual(pix.pixel(30, 35), (0, 0, 0))

    def test_inline_image_is_processed_and_native_text_is_unchanged(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=100, height=100)
            page.insert_font(fontname="helv")
            page.set_contents(objects._object(document, data=(
                b"q 80 0 0 40 10 20 cm BI /W 2 /H 1 /BPC 8 /CS /G ID "
                b"\x80\xff EI Q BT /helv 10 Tf 10 80 Td (INLINE) Tj ET")))
            document.save(self.source)
        self.convert()
        with pymupdf.open(self.target) as document:
            self.assertIn("INLINE", document[0].get_text())
            self.assertEqual(document[0].get_images()[0][4], 1)
            pix = document[0].get_pixmap()
            self.assertEqual(pix.pixel(20, 60), (0, 0, 0))
            self.assertEqual(pix.pixel(80, 60), (255, 255, 255))

    def test_single_full_page_scan_matches_previous_render_then_threshold(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=160, height=120)
            page.insert_image(page.rect, stream=image_bytes())
            document.save(self.source)
        with contextlib.redirect_stdout(io.StringIO()):
            workflow._binarize_pdf(self.source, self.target, 144, 180, 2, "", processing=
                engine_settings._Processing(dpi_policy=engine_settings._DpiPolicy.TARGET))
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            pix = before[0].get_pixmap(dpi=144, colorspace=pymupdf.csGRAY, alpha=False)
            expected = bytes(0 if value < 180 else 255 for value in pix.samples)
            image = pymupdf.Pixmap(after, after[0].get_images()[0][0])
            self.assertEqual(image.samples, expected)

    def test_bounded_workers_release_buffers_on_cancellation(self) -> None:
        self.make_mixed()
        with pymupdf.open(self.source) as document:
            document[1].insert_image((175, 100, 230, 155), stream=image_bytes())
            unique = self.folder / "multiple.pdf"
            document.save(unique)
        self.source = unique
        images: list[Image.Image] = []
        original = objects._render_image

        def fail_after_first(document: pymupdf.Document, xref: int, width: float, height: float,
                             dpi: int, color: bool) -> tuple[Image.Image, Image.Image | None]:
            self.assertIs(threading.current_thread(), threading.main_thread())
            if images:
                raise KeyboardInterrupt()
            result = original(document, xref, width, height, dpi, color)
            images.append(result[0])
            return result

        with patch.object(objects, "_render_image", side_effect=fail_after_first), self.assertRaises(KeyboardInterrupt):
            self.convert()
        self.assertFalse(self.target.exists())
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.assertFalse(any(thread.name.startswith("pdf-encode") for thread in threading.enumerate()))

    def test_gradient_and_pattern_are_binary_without_flattening_page_text(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=100, height=100)
            page.insert_font(fontname="helv")
            function = objects._object(document,
                "<< /FunctionType 2 /Domain [0 1] /C0 [1 0 0] /C1 [0.5 0.5 0.5] /N 1 >>")
            shading = objects._object(document, f"<< /ShadingType 2 /ColorSpace /DeviceRGB "
                f"/Coords [0 0 100 0] /Function {function} 0 R /Extend [true true] >>")
            pattern = objects._object(document,
                "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 10 10] "
                "/XStep 10 /YStep 10 /Resources <<>> >>", b"1 0 0 rg 0 0 5 10 re f 1 g 5 0 5 10 re f")
            resource = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
            document.xref_set_key(resource, "Shading", f"<< /S {shading} 0 R >>")
            document.xref_set_key(resource, "Pattern", f"<< /P {pattern} 0 R >>")
            page.set_contents(objects._object(document, data=(
                b"q 0 50 100 50 re W n /S sh Q "
                b"/Pattern cs /P scn 0 0 100 40 re f "
                b"0 0 1 rg BT /helv 10 Tf 10 45 Td (Native) Tj ET")))
            document.save(self.source)
        self.convert(vectors=True)
        with pymupdf.open(self.target) as document:
            self.assertIn("Native", document[0].get_text())
            pix = document[0].get_pixmap()
            self.assertEqual(pix.pixel(20, 20), (0, 0, 0))
            self.assertEqual(pix.pixel(2, 80), (0, 0, 0))
            self.assertEqual(pix.pixel(7, 80), (255, 255, 255))
            self.assertEqual(pix.pixel(90, 55), (255, 255, 255))

    def test_shared_processed_image_reuses_one_encoded_resource(self) -> None:
        self.make_mixed()
        with patch.object(objects, "_render_image", wraps=objects._render_image) as render:
            self.convert()
        self.assertEqual(render.call_count, 1)
        with pymupdf.open(self.target) as document:
            self.assertEqual(document[0].get_images()[0][0], document[1].get_images()[0][0])

    def test_pattern_images_are_processed_even_with_vector_colors_disabled(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=80, height=60)
            image = page.insert_image(page.rect, stream=image_bytes())
            pattern = objects._object(document,
                f"<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 80 60] "
                f"/XStep 80 /YStep 60 /Resources << /XObject << /I {image} 0 R >> >> >>",
                b"q 80 0 0 60 0 0 cm /I Do Q")
            document.xref_set_key(page.xref, "Resources", f"<< /Pattern << /P {pattern} 0 R >> >>")
            page.set_contents(objects._object(document, data=b"/Pattern cs /P scn 0 0 80 60 re f"))
            document.save(self.source)
        self.convert(vectors=False)
        with pymupdf.open(self.target) as document:
            self.assertEqual(document[0].get_pixmap().pixel(30, 35), (0, 0, 0))

    def test_escaped_image_resource_names_and_skipped_copy(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=80, height=60)
            image = page.insert_image(page.rect, stream=image_bytes())
            document.new_page(width=80, height=60)
            resource = objects._object(document, f"<< /XObject << /Image#2FName {image} 0 R >> >>")
            stream = objects._object(document, data=b"q 80 0 0 60 0 0 cm /Image#2FName Do Q")
            for page in document:
                document.xref_set_key(page.xref, "Resources", f"{resource} 0 R")
                page.set_contents(stream)
            document.save(self.source)
        self.convert(skip="2")
        with pymupdf.open(self.source) as before, pymupdf.open(self.target) as after:
            self.assertEqual(before[1].get_pixmap().samples, after[1].get_pixmap().samples)
            self.assertEqual(after[0].get_images()[0][4], 1)

    def test_translucent_crop_composes_once_over_colored_background(self) -> None:
        with pymupdf.open() as document:
            page = document.new_page(width=80, height=60)
            page.draw_rect(page.rect, fill=(0, 0, 1), color=None)
            page.insert_image(page.rect, stream=image_bytes())
            resource = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
            document.xref_set_key(resource, "ExtGState", "<< /Half << /ca 0.5 >> >>")
            stream = page.get_contents()[-1]
            document.update_stream(stream, b"q /Half gs " + document.xref_stream(stream) + b" Q")
            before = page.get_pixmap().samples
            settings = engine_settings._Processing(regions=engine_settings.regions._Settings(enabled=True))
            with contextlib.closing(objects._Engine(document, 72, 180, settings, 1)) as engine:
                engine.page(0, (engine_settings.regions._Region((0, 0, 1, 1), codec=engine_settings.regions._Codec.FLATE),))
            after = document.reload_page(page).get_pixmap().samples
            self.assertLessEqual(np.abs(np.frombuffer(before, dtype=np.uint8).astype(int) -
                                       np.frombuffer(after, dtype=np.uint8).astype(int)).max(), 1)

    def test_entry_discovery_and_compiler_package_staging(self) -> None:
        shutil.copy2(ROOT / "launcher-config.yaml", self.folder / "launcher-config.yaml")
        config = launcher._load_launcher_config(str(self.folder))
        with patch.object(utility.Environment, "find_bash", return_value=None), patch.object(
                utility.Environment, "find_pwsh", return_value=None):
            discovered = launcher.find_scripts(str(ROOT / "tools"), config)
        for listing in (discovered, compiler.find_py_scripts(str(ROOT / "tools"))):
            paths = [path.replace("\\", "/") for path in listing]
            self.assertIn("document-processing/pdf-binarizer.py", paths)
            self.assertNotIn("document-processing/pdf-binarize-old.py", paths)
            self.assertIn("document-processing/pdf-bookmark-editor.py", paths)
            self.assertIn("document-processing/pdf-font-replacer.py", paths)
            self.assertIn("document-processing/pdf-page-splitter.py", paths)
            self.assertNotIn("document-processing/pdf-page-tag.py", paths)
            self.assertFalse(any(path.startswith("document-processing/pdf-tools/") for path in paths))
        stages: list[Path] = []

        def staged(command: list[str], *, check: bool, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
            stage = Path(env["PYTHONPATH"].split(os.pathsep)[0])
            stages.append(stage)
            self.assertTrue((stage / "personal_pdf_tools/binarize/objects.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/binarize/regions.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/common/navigation.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/bookmarks/app.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/bookmarks/worker.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/font_replace/app.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/font_replace/engine.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/split_pages/app.py").is_file())
            self.assertTrue((stage / "personal_pdf_tools/split_pages/engine.py").is_file())
            self.assertTrue(any("personal_pdf_tools" in part for part in command))
            return subprocess.CompletedProcess(command, 0)

        for filename in ("pdf-binarizer.py", "pdf-bookmark-editor.py", "pdf-font-replacer.py", "pdf-page-splitter.py"):
            entry = str(ROOT / "tools/document-processing" / filename)
            for tool in ("nuitka", "pyinstaller"):
                with patch.object(compiler.subprocess, "run", side_effect=staged):
                    result = compiler._run_compiler(["compiler", entry], entry, str(self.folder), tool)
                    self.assertEqual(result.returncode, 0)
        self.assertTrue(all(not path.exists() for path in stages))


if __name__ == "__main__":
    unittest.main()
