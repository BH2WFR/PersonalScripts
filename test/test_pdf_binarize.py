"""Verify real 1-bit conversion, PDF geometry, bookmarks, and protected input.

Requirements: PyMuPDF, Pillow with libtiff, numpy, tqdm.
Run: conda run -n base python -m unittest discover -s test -p test_pdf_binarize.py
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, features
import numpy as np
import pymupdf


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/document-processing/pdf-binarize.py"
SPEC = importlib.util.spec_from_file_location("pdf_binarize", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def make_source(path: Path, *, password: str | None = None, aes: bool = False) -> None:
    """Create mixed-size scanned pages, a cropped rotated page, and bookmarks."""
    with pymupdf.open() as writer:
        for size in ((144, 72), (144, 96), (72, 144)):
            with Image.new("RGB", size, "white") as image, io.BytesIO() as buffer:
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0, 35, 30), fill="black")
                draw.rectangle((36, 0, 71, 30), fill=(160, 160, 160))
                draw.rectangle((72, 0, 107, 30), fill=(210, 210, 210))
                draw.text((8, 45), "Scan test 123", fill="black")
                image.save(buffer, format="PDF", resolution=72)
                with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as reader:
                    writer.insert_pdf(reader)
        writer[1].set_cropbox(pymupdf.Rect(10, 5, 134, 91))
        writer[1].set_rotation(90)
        writer.xref_set_key(writer.page_xref(2), "UserUnit", "2")
        writer.set_metadata({"title": "Binarization test", "author": "Test suite"})
        writer.set_toc([[1, "Chapter", 1], [2, "Nested", 2], [1, "Final", 3]])
        encryption = pymupdf.PDF_ENCRYPT_NONE if password is None else (
            pymupdf.PDF_ENCRYPT_AES_256 if aes else pymupdf.PDF_ENCRYPT_RC4_128
        )
        writer.save(path, encryption=encryption, user_pw=password or "", owner_pw="test-owner")


def page_image(document: pymupdf.Document, index: int) -> Image.Image:
    """Decode the page's first embedded image independently through Pillow."""
    xref = document[index].get_images()[0][0]
    with io.BytesIO(document.extract_image(xref)["image"]) as buffer:
        with Image.open(buffer) as image:
            return image.copy()


@unittest.skipUnless(features.check("libtiff"), "Pillow libtiff required")
class PdfBinarizeTests(unittest.TestCase):
    """Exercise actual rendering and encoding, plus failure and menu boundaries."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="binary-pdf-", dir=ROOT / "tmp")
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.source = self.folder / "source.pdf"
        self.output = self.folder / "output.pdf"
        make_source(self.source)

    def convert(
        self, *, threshold: int = 180, dpi: int = 72, workers: int = 2, skip_pages: str | None = "",
    ) -> None:
        """Convert the fixture using real in-memory rendering and encoding."""
        with contextlib.redirect_stdout(io.StringIO()):
            app._binarize_pdf(self.source, self.output, dpi, threshold, workers, skip_pages)

    def assert_no_temporary_files(self) -> None:
        """Ensure the temporary output directory has been removed."""
        self.assertEqual(list(self.folder.glob(".pdf-binary-*")), [])

    def test_real_conversion_bit_depth_pixels_geometry_bookmarks_metadata(self) -> None:
        original = self.source.read_bytes()
        self.convert(dpi=144)
        with pymupdf.open(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result), 3)
            self.assertEqual(result.metadata["title"], "Binarization test")
            expected_sizes = ((144, 72), (86, 124), (144, 288))
            for page, size in zip(result, expected_sizes):
                self.assertAlmostEqual(float(page.mediabox.width), size[0])
                self.assertAlmostEqual(float(page.mediabox.height), size[1])
                self.assertEqual(len(page.get_images()), 1)
                image_xref = page.get_images()[0][0]
                self.assertEqual(result.xref_get_key(image_xref, "BitsPerComponent"), ("int", "1"))
                self.assertEqual(result.xref_get_key(image_xref, "ColorSpace"), ("name", "/DeviceGray"))
                self.assertIn("/CCITTFaxDecode", result.xref_get_key(image_xref, "Filter")[1])
                self.assertEqual(set(page_image(result, page.number).convert("L").tobytes()), {0, 255})
            pixels = page_image(result, 0).convert("L")
            self.assertEqual(pixels.size, (288, 144))
            self.assertEqual([pixels.getpixel((x, 20)) for x in (20, 100, 180, 260)], [0, 0, 255, 255])
            self.assertEqual(result.get_toc(), [[1, "Chapter", 1], [2, "Nested", 2], [1, "Final", 3]])
            for xref in result.get_outline_xrefs():
                self.assertIn("/Fit", result.xref_get_key(xref, "Dest")[1])
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_threshold_changes_gray_region_without_dithering(self) -> None:
        self.convert(threshold=128)
        with pymupdf.open(self.output) as result:
            image = page_image(result, 0).convert("L")
            self.assertEqual(image.getpixel((50, 10)), 255)

    def test_permission_only_encryption_needs_no_password(self) -> None:
        make_source(self.source, password="")
        with patch.object(app.Input, "input_password") as prompt:
            self.convert()
            prompt.assert_not_called()
        with pymupdf.open(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result), 3)
            self.assertEqual(result.get_toc()[0][1], "Chapter")
        self.assert_no_temporary_files()

    def test_password_retry_and_aes(self) -> None:
        make_source(self.source, password="test-open", aes=True)
        with patch.object(app.Input, "input_password", side_effect=["wrong", "test-open"]) as prompt:
            self.convert()
            self.assertEqual(prompt.call_count, 2)
        self.assert_no_temporary_files()

    def test_cancel_password_leaves_no_output(self) -> None:
        make_source(self.source, password="test-open")
        with patch.object(app.Input, "input_password", return_value=""):
            with self.assertRaisesRegex(ValueError, "cancelled"):
                self.convert()
        self.assertFalse(self.output.exists())
        self.assert_no_temporary_files()

    def test_render_failure_or_interrupt_cleans_up(self) -> None:
        make_source(self.source, password="test-open")
        for error in (RuntimeError("render failed"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                with patch.object(app.Input, "input_password", return_value="test-open"):
                    with patch.object(app, "_render_page", side_effect=error):
                        with self.assertRaises(type(error)):
                            self.convert()
                self.assertFalse(self.output.exists())
                self.assert_no_temporary_files()

    def test_existing_output_and_source_cannot_be_overwritten(self) -> None:
        self.output.write_bytes(b"existing content")
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(self.output.read_bytes(), b"existing content")
        self.output = self.source
        original = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(self.source.read_bytes(), original)

    def test_invalid_settings_and_missing_codec_do_not_render(self) -> None:
        with patch.object(app, "_render_page") as render:
            for dpi, threshold in ((0, 180), (1201, 180), (300, 0), (300, 256)):
                with self.subTest(dpi=dpi, threshold=threshold), self.assertRaises(ValueError):
                    self.convert(dpi=dpi, threshold=threshold)
            with patch.object(app.features, "check", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "libtiff"):
                    self.convert()
            render.assert_not_called()

    def test_interactive_defaults(self) -> None:
        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", return_value=str(self.output)),
            patch("builtins.input", return_value=""),
            patch.object(app, "_binarize_pdf") as convert,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.output.write_bytes(b"test output")
            self.assertEqual(app.main(), 0)
            self.assertEqual(convert.call_args.args[2:], (300, 180, app.DEFAULT_WORKERS, None))
            self.assertFalse(convert.call_args.kwargs["processing"].sharpen)

    def test_missing_bookmark_title_retains_hierarchy(self) -> None:
        with pymupdf.open(self.source) as document:
            document.xref_set_key(document.get_outline_xrefs()[0], "Title", "null")
            app._reset_bookmark_positions(document)
            document.save(self.output)
        with pymupdf.open(self.output) as result:
            self.assertEqual(result.get_toc()[0][1], app.UNTITLED_BOOKMARK)
            self.assertEqual(result.get_toc()[1], [2, "Nested", 2])

    def test_parallel_and_serial_outputs_match(self) -> None:
        self.convert(workers=1)
        serial_path = self.output
        self.output = self.folder / "parallel.pdf"
        self.convert(workers=3)
        with pymupdf.open(serial_path) as serial, pymupdf.open(self.output) as parallel:
            self.assertEqual(len(serial), len(parallel))
            for index, (before, after) in enumerate(zip(serial, parallel)):
                self.assertEqual(before.mediabox, after.mediabox)
                self.assertEqual(page_image(serial, index).tobytes(), page_image(parallel, index).tobytes())
            self.assertEqual(parallel.get_toc()[0][1], "Chapter")
            self.assertEqual(parallel.get_toc()[1], [2, "Nested", 2])

    def test_parallel_completion_order_does_not_change_page_order(self) -> None:
        second_finished = threading.Event()
        completed: list[int] = []
        lock = threading.Lock()

        def render(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
            self.assertEqual(threading.current_thread(), threading.main_thread())
            return Image.new("L", (1, 1), index + 1)

        def encode(image: Image.Image, dpi: int, threshold: int,
                   processing: app._Processing = app.DEFAULT_PROCESSING) -> bytes:
            number = int(image.tobytes()[0])
            if number == 1:
                self.assertTrue(second_finished.wait(timeout=2))
            with lock:
                completed.append(number)
            if number == 2:
                second_finished.set()
            image.close()
            return str(number).encode("ascii")

        with patch.object(app, "_render_page", side_effect=render), patch.object(app, "_encode_page", side_effect=encode):
            result = list(app._encoded_pages(self.source, list(range(12)), 72, 180, 2))
        self.assertEqual(completed[0], 2)
        self.assertEqual(result, [str(number).encode("ascii") for number in range(1, 13)])

    def test_encoder_failure_cleans_up_after_workers_stop(self) -> None:
        with patch.object(app, "_encode_page", side_effect=OSError("encoder failed")):
            with self.assertRaisesRegex(OSError, "encoder failed"):
                self.convert(workers=2)
        self.assertFalse(self.output.exists())
        self.assert_no_temporary_files()
        self.assertFalse(any(thread.name.startswith("pdf-encode") for thread in threading.enumerate()))

    def test_pipeline_limits_render_ahead_and_releases_images_on_close(self) -> None:
        real_render = app._render_page
        images: list[Image.Image] = []
        documents: list[pymupdf.Document] = []

        def render(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
            self.assertEqual(threading.current_thread(), threading.main_thread())
            image = real_render(document, index, dpi)
            images.append(image)
            documents.append(document)
            return image

        with patch.object(app, "_render_page", side_effect=render):
            pages = app._encoded_pages(self.source, [0, 1, 2], 72, 180, 2)
            try:
                self.assertTrue(next(pages).startswith(b"%PDF"))
                self.assertEqual(len(images), 2)
            finally:
                pages.close()
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))
        self.assertTrue(all(document.is_closed for document in documents))
        self.assertFalse(any(thread.name.startswith("pdf-encode") for thread in threading.enumerate()))

    def test_no_page_images_or_decrypted_pdf_are_written(self) -> None:
        real_render = app._render_page
        real_write = app._write_pdf_with_progress

        def render(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
            self.assertEqual(threading.current_thread(), threading.main_thread())
            folders = list(self.folder.glob(".pdf-binary-*"))
            self.assertEqual(len(folders), 1)
            self.assertEqual(list(folders[0].iterdir()), [])
            return real_render(document, index, dpi)

        def write(writer: pymupdf.Document, destination: Path) -> None:
            self.assertEqual(list(destination.parent.iterdir()), [])
            real_write(writer, destination)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

        for number, password in enumerate((None, "test-open")):
            with self.subTest(encrypted=password is not None):
                make_source(self.source, password=password)
                self.output = self.folder / f"output-{number}.pdf"
                with (
                    patch.object(app.Input, "input_password", return_value=password or ""),
                    patch.object(app, "_render_page", side_effect=render) as rendered,
                    patch.object(app, "_write_pdf_with_progress", side_effect=write),
                ):
                    self.convert()
                self.assertEqual(rendered.call_count, 3)
                self.assert_no_temporary_files()

    def test_write_progress_reports_activity_and_stops_on_failure(self) -> None:
        output = io.StringIO()

        def slow_write(document: pymupdf.Document, path: Path) -> None:
            path.write_bytes(b"partially written PDF")
            time.sleep(0.06)
            raise OSError("write failed")

        with pymupdf.open() as writer:
            with (
                patch.object(app.Pdf, "save_new", side_effect=slow_write),
                patch.object(app, "PROGRESS_INTERVAL_SECONDS", 0.01),
                contextlib.redirect_stdout(output),
                self.assertRaisesRegex(OSError, "write failed"),
            ):
                app._write_pdf_with_progress(writer, self.folder / "incomplete.pdf")
        self.assertIn("elapsed", output.getvalue())
        self.assertIn("written", output.getvalue())
        self.assertNotIn("100%", output.getvalue())
        self.assertNotIn("Final PDF written in", output.getvalue())
        self.assertFalse(any(thread.name == "pdf-write-progress" for thread in threading.enumerate()))

    def test_finalization_stages_are_reported(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            app._binarize_pdf(self.source, self.output, 72, 180, 2)
        for message in ("Processing pages", "Copying document metadata and bookmarks", "Writing final PDF",
                        "Copying output:", "100%", "Cleaning up temporary files"):
            self.assertIn(message, output.getvalue())

    def test_skipped_pages_keep_original_content_and_order(self) -> None:
        self.convert(skip_pages="1,-1")
        with pymupdf.open(self.source) as source, pymupdf.open(self.output) as result:
            self.assertEqual(len(result), 3)
            for index in (0, 2):
                self.assertEqual(page_image(result, index).tobytes(), page_image(source, index).tobytes())
                self.assertEqual(result[index].read_contents(), source[index].read_contents())
                self.assertEqual(result[index].cropbox, source[index].cropbox)
                self.assertEqual(result[index].rotation, source[index].rotation)
                self.assertEqual(result[index].rect, source[index].rect)
            self.assertEqual(result[1].get_images()[0][4], 1)
            self.assertAlmostEqual(result[1].mediabox.width, 86)
            self.assertAlmostEqual(result[1].mediabox.height, 124)
            self.assertEqual(result.get_toc()[1], [2, "Nested", 2])

    def test_noncontiguous_rendered_pages_map_back_correctly(self) -> None:
        self.convert(skip_pages="2")
        with pymupdf.open(self.source) as source, pymupdf.open(self.output) as result:
            self.assertEqual(result[0].get_images()[0][4], 1)
            self.assertEqual(result[2].get_images()[0][4], 1)
            self.assertEqual(page_image(result, 1).tobytes(), page_image(source, 1).tobytes())
            self.assertEqual(result[1].rotation, 90)
            self.assertEqual(result[1].cropbox, source[1].cropbox)
            self.assertAlmostEqual(result[2].mediabox.width, 144)
            self.assertAlmostEqual(result[2].mediabox.height, 288)

    def test_real_thousand_page_document_skipping_first_two_pages(self) -> None:
        with pymupdf.open() as writer:
            for _ in range(1045):
                writer.new_page(width=8, height=8)
            writer.save(self.source)
        with patch.object(app, "_render_page", wraps=app._render_page) as render:
            self.convert(dpi=36, skip_pages="1,2")
        self.assertEqual(render.call_count, 1043)
        self.assertEqual([call.args[1] for call in render.call_args_list], list(range(2, 1045)))
        with pymupdf.open(self.output) as result:
            self.assertEqual(len(result), 1045)
            self.assertEqual(len(result[0].get_images()), 0)
            self.assertEqual(len(result[1].get_images()), 0)
            self.assertTrue(all(result[index].get_images()[0][4] == 1 for index in range(2, len(result))))
        self.assert_no_temporary_files()

    def test_only_selected_pages_are_rendered_in_order(self) -> None:
        with patch.object(app, "_render_page", wraps=app._render_page) as render:
            self.convert(skip_pages="2")
        self.assertEqual(render.call_count, 2)
        self.assertEqual([call.args[1] for call in render.call_args_list], [0, 2])
        with pymupdf.open(self.source) as source, pymupdf.open(self.output) as result:
            self.assertEqual(len(result), 3)
            self.assertEqual(page_image(result, 0).size, (144, 72))
            self.assertEqual(page_image(result, 2).size, (144, 288))
            self.assertEqual(page_image(result, 1).tobytes(), page_image(source, 1).tobytes())
            self.assertEqual(result.get_toc()[1], [2, "Nested", 2])
        self.assert_no_temporary_files()

    def test_later_render_failure_closes_earlier_images(self) -> None:
        original = self.source.read_bytes()
        real_render = app._render_page
        calls = 0
        images: list[Image.Image] = []

        def fail_second_page(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("render failed")
            image = real_render(document, index, dpi)
            images.append(image)
            return image

        with (
            patch.object(app, "_render_page", side_effect=fail_second_page),
            self.assertRaisesRegex(RuntimeError, "render failed"),
        ):
            self.convert(skip_pages="2")
        self.assertEqual(calls, 2)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(self.output.exists())
        self.assert_no_temporary_files()
        for image in images:
            with self.assertRaises(ValueError):
                image.getpixel((0, 0))

    def test_all_skipped_does_not_render_or_encode(self) -> None:
        make_source(self.source, password="")
        with (
            patch.object(app, "_render_page") as render,
            patch.object(app, "_encode_page") as encode,
            patch.object(app.features, "check", return_value=False),
        ):
            self.convert(skip_pages="1-3")
        render.assert_not_called()
        encode.assert_not_called()
        with pymupdf.open(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result), 3)
            self.assertEqual(page_image(result, 0).mode, "RGB")
        self.assert_no_temporary_files()

    def test_bad_skip_selection_fails_before_rendering(self) -> None:
        with patch.object(app, "_render_page") as render:
            for selection in ("0", "4", "-4", "1-4", "bad"):
                with self.subTest(selection=selection), self.assertRaises(ValueError):
                    self.convert(skip_pages=selection)
        render.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assert_no_temporary_files()

    def test_skip_prompt_retries_and_blank_means_none(self) -> None:
        with patch("builtins.input", side_effect=["4", ""]) as prompt:
            self.convert(skip_pages=None)
        self.assertEqual(prompt.call_count, 2)
        with pymupdf.open(self.output) as result:
            self.assertTrue(all(page.get_images()[0][4] == 1 for page in result))

    def test_interactive_skip_selection_preserves_original_pages(self) -> None:
        for number, selection in enumerate(("1-2,-1", "-1,-2", "")):
            target = self.folder / f"interactive-skip-{number}.pdf"
            with (
                self.subTest(selection=selection),
                patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
                patch.object(app.Input, "resolve_output_path", return_value=str(target)),
                patch.object(app, "_configure", return_value=(72, 180, app.DEFAULT_PROCESSING)),
                patch("builtins.input", side_effect=["f", selection]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(app.main(), 0)
            skipped = app.Input.parse_index_ranges(selection, item_count=3)
            with pymupdf.open(target) as result:
                for index in range(3):
                    self.assertEqual(result[index].get_images()[0][4], 8 if index in skipped else 1)

    def test_skipped_links_forms_custom_metadata_and_rendered_pixels(self) -> None:
        enriched = self.folder / "enriched.pdf"
        with pymupdf.open(self.source) as document:
            for index, target in ((0, 2), (2, 0)):
                document[index].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(0, 0, 20, 20),
                                             "page": target, "to": pymupdf.Point(0, 0)})
            for index in (0, 1):
                widget = pymupdf.Widget()
                widget.field_name = f"field-{index}"
                widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
                widget.field_value = "value"
                widget.rect = pymupdf.Rect(10, 10, 40, 20)
                document[index].add_widget(widget)
            info = int(document.xref_get_key(-1, "Info")[1].split()[0])
            document.xref_set_key(info, "CustomField", "(retained)")
            document.set_xml_metadata("<metadata>retained</metadata>")
            document.save(enriched)
        self.source = enriched
        self.convert(skip_pages="1,3", dpi=144)
        with pymupdf.open(self.source) as original, pymupdf.open(self.output) as result:
            self.assertEqual(result[0].get_links()[0]["page"], 2)
            self.assertEqual(result[2].get_links()[0]["page"], 0)
            self.assertEqual(next(result[0].widgets()).field_value, "value")
            self.assertEqual(list(result[1].widgets()), [])
            self.assertEqual(result.is_form_pdf, 1)
            info = int(result.xref_get_key(-1, "Info")[1].split()[0])
            self.assertEqual(result.xref_get_key(info, "CustomField"), ("string", "retained"))
            self.assertEqual(result.get_xml_metadata(), "<metadata>retained</metadata>")
            before = original[1].get_pixmap(dpi=144, colorspace=pymupdf.csGRAY, alpha=False)
            after = result[1].get_pixmap(dpi=144, colorspace=pymupdf.csGRAY, alpha=False)
            self.assertEqual((after.width, after.height), (before.width, before.height))
            self.assertEqual(after.samples, bytes(0 if value < 180 else 255 for value in before.samples))

    def test_converted_pages_remove_original_text_and_image_resources(self) -> None:
        with pymupdf.open(self.source) as document:
            document[0].insert_text((10, 65), "Searchable source text")
            self.source = self.folder / "searchable.pdf"
            document.save(self.source)
        with pymupdf.open(self.source) as document:
            self.assertIn("Searchable source text", document[0].get_text())
        self.convert()
        with pymupdf.open(self.output) as result:
            for page in result:
                self.assertEqual(page.get_text(), "")
            image_depths = [result.xref_get_key(xref, "BitsPerComponent")[1]
                            for xref in range(1, result.xref_length())
                            if result.xref_get_key(xref, "Subtype") == ("name", "/Image")]
            self.assertEqual(image_depths, ["1", "1", "1"])

    def test_sauvola_matches_local_statistics_across_strip_boundaries(self) -> None:
        pixels = np.random.default_rng(42).integers(0, 256, (19, 23), dtype=np.uint8)
        expected = np.empty(pixels.shape, dtype=np.uint8)
        padded = np.pad(pixels.astype(np.float64), 2, mode="reflect")
        # Independent direct-neighborhood calculation, including image edges.
        for row in range(19):
            for col in range(23):
                neighborhood = padded[row:row + 5, col:col + 5]
                cutoff = neighborhood.mean() * (1 + 0.2 * (neighborhood.std() / 128 - 1))
                expected[row, col] = 255 if pixels[row, col] > cutoff else 0
        with Image.fromarray(pixels) as gray:
            for strip_rows in (1, 3, 256):
                with self.subTest(strip_rows=strip_rows), patch.object(app, "SAUVOLA_STRIP_ROWS", strip_rows):
                    with app._sauvola(gray, 5, 0.2) as result:
                        self.assertEqual(result.mode, "1")
                        self.assertEqual(result.convert("L").tobytes(), expected.tobytes())
        for color in (0, 255):
            with Image.new("L", (1, 1), color) as gray, app._sauvola(gray, 31, 0.2) as result:
                self.assertEqual(result.getpixel((0, 0)), color)

    def test_sharpening_is_off_by_default_and_can_retain_a_faint_stroke(self) -> None:
        with Image.new("L", (21, 21), 255) as gray:
            ImageDraw.Draw(gray).line((10, 2, 10, 18), fill=190)
            with app._threshold_image(gray, 180, app.DEFAULT_PROCESSING) as result:
                self.assertEqual(set(result.convert("L").tobytes()), {255})
            with app._threshold_image(gray, 180, app._Processing(sharpen=True)) as result:
                self.assertEqual(result.getpixel((10, 10)), 0)
                self.assertEqual(result.getpixel((0, 0)), 255)
            self.assertEqual(gray.getpixel((10, 10)), 190)

    def test_preview_matches_full_conversion_and_renders_only_one_page(self) -> None:
        original = self.source.read_bytes()
        for mode in app._BinarizeMode:
            for sharpen, upscale in ((False, 1), (True, 1), (False, 2), (True, 2)):
                processing = app._Processing(mode=mode, sharpen=sharpen, upscale=upscale,
                                             levels=upscale > 1, black_point=110, white_point=250)
                full = self.folder / f"full-{mode}-{sharpen}-{upscale}.pdf"
                with contextlib.redirect_stdout(io.StringIO()):
                    app._binarize_pdf(self.source, full, 144, 180, 2, processing=processing)
                for page_number, index in ((2, 1), (-1, 2)):
                    preview = self.folder / f"preview-{mode}-{sharpen}-{upscale}-{index}.pdf"
                    with (
                        self.subTest(mode=mode, sharpen=sharpen, upscale=upscale, page=page_number),
                        patch.object(app, "_render_page", wraps=app._render_page) as render,
                        contextlib.redirect_stdout(io.StringIO()),
                    ):
                        app._preview_pdf(self.source, preview, page_number, 144, 180, processing)
                    self.assertEqual(render.call_count, 1)
                    self.assertEqual(render.call_args.args[1], index)
                    with pymupdf.open(preview) as result, pymupdf.open(full) as complete:
                        self.assertEqual(len(result), 1)
                        self.assertEqual(result.get_toc(), [])
                        self.assertEqual(result[0].rect, complete[index].rect)
                        self.assertEqual(result[0].get_images()[0][4], 1)
                        self.assertEqual(page_image(result, 0).size, (
                            int(result[0].rect.width * 2 * upscale), int(result[0].rect.height * 2 * upscale),
                        ))
                        self.assertEqual(page_image(result, 0).tobytes(), page_image(complete, index).tobytes())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_preview_password_failure_and_existing_output_protection(self) -> None:
        make_source(self.source, password="secret", aes=True)
        original = self.source.read_bytes()
        with patch.object(app.Input, "input_password", return_value="secret"), contextlib.redirect_stdout(io.StringIO()):
            app._preview_pdf(self.source, self.output, -1, 72, 180)
            for output in (self.source, self.output):
                with self.assertRaises(FileExistsError):
                    app._preview_pdf(self.source, output, 1, 72, 180)
            with patch.object(app, "_render_page") as render:
                for page in (0, 4, -4):
                    with self.assertRaises(ValueError):
                        app._preview_pdf(self.source, self.folder / "invalid.pdf", page, 72, 180)
                render.assert_not_called()
            with patch.object(app, "_encode_page", side_effect=RuntimeError("test failure")):
                with self.assertRaises(RuntimeError):
                    app._preview_pdf(self.source, self.folder / "failed.pdf", 1, 72, 180)
        self.assertFalse((self.folder / "invalid.pdf").exists())
        self.assertFalse((self.folder / "failed.pdf").exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_interactive_preview_reconfigure_preview_then_convert(self) -> None:
        preview_one = self.folder / "fixed-preview.pdf"
        preview_two = self.folder / "sauvola-preview.pdf"
        replies = [
            "", "72", "", "", "", "",  # fixed, 72 DPI, threshold 180, levels off, 1x, sharpening off
            "p", "2",
            "s", "s", "", "30", "31", "", "y", "110", "100", "250", "2", "y", "0.7", "50",
            "p", "2", "f", "1,-1",
        ]
        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", side_effect=[str(preview_one), str(preview_two), str(self.output)]),
            patch.object(app.System, "open_with_default_app") as viewer,
            patch("builtins.input", side_effect=replies),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(app.main(), 0)
            self.assertEqual(viewer.call_count, 2)
        with pymupdf.open(preview_two) as preview, pymupdf.open(self.output) as complete:
            self.assertEqual(page_image(preview, 0).tobytes(), page_image(complete, 1).tobytes())
            self.assertEqual(complete[0].get_images()[0][4], 8)
            self.assertEqual(complete[2].get_images()[0][4], 8)
        with pymupdf.open(preview_one) as result:
            self.assertEqual(len(result), 1)

    def test_interactive_preview_can_disable_viewer_and_quit(self) -> None:
        processing = app._Processing(mode=app._BinarizeMode.SAUVOLA, sharpen=True,
                                     levels=True, black_point=110, white_point=250, upscale=2)
        with (
            patch.object(app.Input, "resolve_input_path", return_value=str(self.source)),
            patch.object(app.Input, "resolve_output_path", return_value=str(self.output)),
            patch.object(app, "_configure", return_value=(72, 180, processing)),
            patch.object(app.System, "open_with_default_app") as viewer,
            patch("builtins.input", side_effect=["o", "1", "n", "n", "n", "n", "p", "-1", "q"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(app.main(), 0)
            viewer.assert_not_called()
        with pymupdf.open(self.output) as result:
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].get_images()[0][4], 1)
            self.assertEqual(result[0].rect, pymupdf.Rect(0, 0, 144, 288))
            self.assertEqual(page_image(result, 0).size, (288, 576))

    def test_invalid_processing_is_rejected_before_rendering(self) -> None:
        invalid = [
            app._Processing(window=30), app._Processing(window=1),
            app._Processing(k=float("nan")), app._Processing(k=0),
            app._Processing(sharpen_radius=0), app._Processing(sharpen_percent=0),
            app._Processing(black_point=-1), app._Processing(black_point=255),
            app._Processing(white_point=0), app._Processing(white_point=256),
            app._Processing(upscale=0), app._Processing(upscale=5),
        ]
        with patch.object(app, "_render_page") as render:
            for processing in invalid:
                with self.subTest(processing=processing), self.assertRaises(ValueError):
                    app._preview_pdf(self.source, self.output, 1, 72, 180, processing)
            render.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_sauvola_serial_parallel_results_match(self) -> None:
        processing = app._Processing(mode=app._BinarizeMode.SAUVOLA, sharpen=True,
                                     levels=True, black_point=110, white_point=250, upscale=2)
        second = self.folder / "parallel.pdf"
        with contextlib.redirect_stdout(io.StringIO()):
            app._binarize_pdf(self.source, self.output, 72, 180, 1, processing=processing)
            app._binarize_pdf(self.source, second, 72, 180, 3, processing=processing)
        with pymupdf.open(self.output) as serial, pymupdf.open(second) as parallel:
            for index in range(3):
                self.assertEqual(page_image(serial, index).tobytes(), page_image(parallel, index).tobytes())

    def test_levels_mapping_identity_disabled_and_source_preservation(self) -> None:
        with Image.frombytes("L", (256, 1), bytes(range(256))) as gray:
            original = gray.tobytes()
            for mode in app._BinarizeMode:
                with app._threshold_image(gray, 128, app._Processing(mode=mode)) as baseline:
                    for processing in (
                        app._Processing(mode=mode, levels=True),
                        app._Processing(mode=mode, levels=False, black_point=110, white_point=250),
                    ):
                        with app._threshold_image(gray, 128, processing) as result:
                            self.assertEqual(result.tobytes(), baseline.tobytes())
            # Linear 110..250 levels cross fixed threshold 128 at source value 180.
            with app._threshold_image(gray, 128, app._Processing(
                levels=True, black_point=110, white_point=250,
            )) as result:
                self.assertEqual(result.convert("L").tobytes(), bytes([0] * 180 + [255] * 76))
            self.assertEqual(gray.tobytes(), original)

    def test_upscale_keeps_encoded_pdf_size_and_scales_image(self) -> None:
        for scale in (1, 2, 3, 4):
            with self.subTest(scale=scale):
                encoded = app._encode_page(Image.new("L", (144, 72), 255), 72, 180,
                                           app._Processing(upscale=scale))
                with pymupdf.open(stream=encoded, filetype="pdf") as result:
                    self.assertEqual(result[0].rect, pymupdf.Rect(0, 0, 144, 72))
                    self.assertEqual(page_image(result, 0).size, (144 * scale, 72 * scale))

    def test_configure_retains_new_settings_on_enter(self) -> None:
        settings = app._Processing(mode=app._BinarizeMode.SAUVOLA, levels=True,
                                   black_point=110, white_point=250, upscale=2,
                                   sharpen=True, sharpen_radius=0.7, sharpen_percent=50)
        with patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app._configure(144, 180, settings), (144, 180, settings))

    def test_equal_or_reversed_levels_fail_before_rendering(self) -> None:
        with patch.object(app, "_render_page") as render:
            for black, white in ((110, 110), (250, 110)):
                with self.subTest(black=black, white=white), self.assertRaises(ValueError):
                    app._preview_pdf(self.source, self.output, 1, 72, 180,
                                     app._Processing(levels=True, black_point=black, white_point=white))
            render.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
