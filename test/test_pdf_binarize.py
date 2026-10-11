"""Verify real 1-bit conversion, PDF geometry, bookmarks, and protected input.

Requirements: PyMuPDF, Pillow with libtiff, pypdf; cryptography for AES tests.
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
import pymupdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import Destination, Fit, FloatObject, NameObject, NumberObject, RectangleObject


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/document-processing/pdf-binarize.py"
SPEC = importlib.util.spec_from_file_location("pdf_binarize", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


def make_source(path: Path, *, password: str | None = None, aes: bool = False) -> None:
    """Create mixed-size scanned pages, a cropped rotated page, and bookmarks."""
    with PdfWriter() as writer:
        for size in ((144, 72), (144, 96), (72, 144)):
            with Image.new("RGB", size, "white") as image, io.BytesIO() as buffer:
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0, 35, 30), fill="black")
                draw.rectangle((36, 0, 71, 30), fill=(160, 160, 160))
                draw.rectangle((72, 0, 107, 30), fill=(210, 210, 210))
                draw.text((8, 45), "Scan test 123", fill="black")
                image.save(buffer, format="PDF", resolution=72)
                buffer.seek(0)
                reader = PdfReader(buffer)
                writer.add_page(reader.pages[0])
        writer.pages[1].cropbox = RectangleObject((10, 5, 134, 91))
        writer.pages[1].rotate(90)
        writer.pages[2][NameObject("/UserUnit")] = FloatObject(2)
        writer.add_metadata({"/Title": "Binarization test", "/Author": "Test suite"})
        parent = writer.add_outline_item("Chapter", 0)
        writer.add_outline_item("Nested", 1, parent=parent)
        writer.add_outline_item("Final", 2)
        if password is not None:
            writer.encrypt(password, owner_password="test-owner", algorithm="AES-256" if aes else "RC4-128")
        writer.write(path)


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
        with PdfReader(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result.pages), 3)
            self.assertEqual(result.metadata.title, "Binarization test")
            expected_sizes = ((144, 72), (86, 124), (144, 288))
            for page, size in zip(result.pages, expected_sizes):
                self.assertAlmostEqual(float(page.mediabox.width), size[0])
                self.assertAlmostEqual(float(page.mediabox.height), size[1])
                self.assertEqual(len(page.images), 1)
                image_obj = next(iter(page["/Resources"]["/XObject"].values())).get_object()
                self.assertEqual(image_obj["/BitsPerComponent"], 1)
                self.assertEqual(image_obj["/ColorSpace"], "/DeviceGray")
                self.assertIn("/CCITTFaxDecode", image_obj["/Filter"])
                self.assertEqual(set(page.images[0].image.convert("L").getdata()), {0, 255})
            pixels = result.pages[0].images[0].image.convert("L")
            self.assertEqual(pixels.size, (288, 144))
            self.assertEqual([pixels.getpixel((x, 20)) for x in (20, 100, 180, 260)], [0, 0, 255, 255])
            outline = result.outline
            self.assertEqual(outline[0].title, "Chapter")
            self.assertEqual(outline[1][0].title, "Nested")
            self.assertEqual(result.get_destination_page_number(outline[1][0]), 1)
            self.assertEqual(result.get_destination_page_number(outline[2]), 2)
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_threshold_changes_gray_region_without_dithering(self) -> None:
        self.convert(threshold=128)
        with PdfReader(self.output) as result:
            image = result.pages[0].images[0].image.convert("L")
            self.assertEqual(image.getpixel((50, 10)), 255)

    def test_permission_only_encryption_needs_no_password(self) -> None:
        make_source(self.source, password="")
        with patch.object(app.Input, "input_password") as prompt:
            self.convert()
            prompt.assert_not_called()
        with PdfReader(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result.pages), 3)
            self.assertEqual(result.outline[0].title, "Chapter")
        self.assert_no_temporary_files()

    def test_password_retry_and_aes(self) -> None:
        if importlib.util.find_spec("cryptography") is None:
            self.skipTest("cryptography required for AES")
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

    def test_cli_and_interactive_defaults(self) -> None:
        with (
            patch.object(sys, "argv", [str(SCRIPT), str(self.source), "-o", str(self.output)]),
            patch.object(app.Input, "input_number", side_effect=[300, 180]),
            patch.object(app, "_binarize_pdf") as convert,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            # The result summary expects the file created by the converter.
            self.output.write_bytes(b"test output")
            self.assertEqual(app.main(), 0)
            self.assertEqual(convert.call_args.args[2:], (300, 180, app.DEFAULT_WORKERS, None))
        for flag in ("--dpi", "--threshold", "--workers"):
            with patch.object(sys, "argv", [str(SCRIPT), flag, "0"]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                    app.main()
                self.assertEqual(exc.exception.code, 2)

    def test_missing_bookmark_title_retains_hierarchy(self) -> None:
        heading = Destination("removed", NumberObject(0), Fit.fit())
        heading.pop(NameObject("/Title"))
        child = Destination("Child", NumberObject(1), Fit.fit())
        with PdfReader(self.source) as reader, PdfWriter() as writer:
            writer.append(reader, import_outline=False)
            app._copy_bookmarks(reader, writer, [heading, [child]])
            writer.write(self.output)
        with PdfReader(self.output) as result:
            self.assertEqual(result.outline[0].title, app.UNTITLED_BOOKMARK)
            self.assertEqual(result.outline[1][0].title, "Child")

    def test_parallel_and_serial_outputs_match(self) -> None:
        self.convert(workers=1)
        serial_path = self.output
        self.output = self.folder / "parallel.pdf"
        self.convert(workers=3)
        with PdfReader(serial_path) as serial, PdfReader(self.output) as parallel:
            self.assertEqual(len(serial.pages), len(parallel.pages))
            for before, after in zip(serial.pages, parallel.pages):
                self.assertEqual(before.mediabox, after.mediabox)
                self.assertEqual(before.images[0].image.tobytes(), after.images[0].image.tobytes())
            self.assertEqual(parallel.outline[0].title, "Chapter")
            self.assertEqual(parallel.get_destination_page_number(parallel.outline[1][0]), 1)

    def test_parallel_completion_order_does_not_change_page_order(self) -> None:
        second_finished = threading.Event()
        completed: list[int] = []
        lock = threading.Lock()

        def render(document: pymupdf.Document, index: int, dpi: int) -> Image.Image:
            self.assertEqual(threading.current_thread(), threading.main_thread())
            return Image.new("L", (1, 1), index + 1)

        def encode(image: Image.Image, dpi: int, threshold: int) -> bytes:
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

        def write(writer: PdfWriter, destination: Path) -> None:
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

        def slow_write(path: Path) -> None:
            path.write_bytes(b"partially written PDF")
            time.sleep(0.06)
            raise OSError("write failed")

        with PdfWriter() as writer:
            with (
                patch.object(writer, "write", side_effect=slow_write),
                patch.object(app, "PROGRESS_INTERVAL_SECONDS", 0.01),
                contextlib.redirect_stdout(output),
                self.assertRaisesRegex(OSError, "write failed"),
            ):
                app._write_pdf_with_progress(writer, self.folder / "incomplete.pdf")
        self.assertIn("elapsed", output.getvalue())
        self.assertIn("written...", output.getvalue())
        self.assertNotIn("Final PDF written in", output.getvalue())
        self.assertFalse(any(thread.name == "pdf-write-progress" for thread in threading.enumerate()))

    def test_finalization_stages_are_reported(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            app._binarize_pdf(self.source, self.output, 72, 180, 2)
        for message in ("Copying document metadata and bookmarks", "Writing final PDF",
                        "Output copy:", "100%", "Cleaning up temporary files"):
            self.assertIn(message, output.getvalue())

    def test_skipped_pages_keep_original_content_and_order(self) -> None:
        self.convert(skip_pages="1,-1")
        with PdfReader(self.source) as source, PdfReader(self.output) as result:
            self.assertEqual(len(result.pages), 3)
            for index in (0, 2):
                self.assertEqual(result.pages[index].images[0].image.tobytes(), source.pages[index].images[0].image.tobytes())
                self.assertEqual(result.pages[index].get_contents().get_data(), source.pages[index].get_contents().get_data())
                self.assertEqual(result.pages[index].cropbox, source.pages[index].cropbox)
                self.assertEqual(result.pages[index].rotation, source.pages[index].rotation)
                self.assertEqual(result.pages[index].user_unit, source.pages[index].user_unit)
            self.assertEqual(result.pages[1].images[0].image.mode, "1")
            self.assertAlmostEqual(float(result.pages[1].mediabox.width), 86)
            self.assertAlmostEqual(float(result.pages[1].mediabox.height), 124)
            self.assertEqual(result.get_destination_page_number(result.outline[1][0]), 1)

    def test_noncontiguous_rendered_pages_map_back_correctly(self) -> None:
        self.convert(skip_pages="2")
        with PdfReader(self.source) as source, PdfReader(self.output) as result:
            self.assertEqual(result.pages[0].images[0].image.mode, "1")
            self.assertEqual(result.pages[2].images[0].image.mode, "1")
            self.assertEqual(result.pages[1].images[0].image.tobytes(), source.pages[1].images[0].image.tobytes())
            self.assertEqual(result.pages[1].rotation, 90)
            self.assertEqual(result.pages[1].cropbox, source.pages[1].cropbox)
            self.assertAlmostEqual(float(result.pages[2].mediabox.width), 144)
            self.assertAlmostEqual(float(result.pages[2].mediabox.height), 288)

    def test_real_thousand_page_document_skipping_first_two_pages(self) -> None:
        with PdfWriter() as writer:
            for _ in range(1045):
                writer.add_blank_page(width=8, height=8)
            writer.write(self.source)
        with patch.object(app, "_render_page", wraps=app._render_page) as render:
            self.convert(dpi=36, skip_pages="1,2")
        self.assertEqual(render.call_count, 1043)
        self.assertEqual([call.args[1] for call in render.call_args_list], list(range(2, 1045)))
        with PdfReader(self.output) as result:
            self.assertEqual(len(result.pages), 1045)
            self.assertEqual(len(result.pages[0].images), 0)
            self.assertEqual(len(result.pages[1].images), 0)
            self.assertTrue(all(page.images[0].image.mode == "1" for page in result.pages[2:]))
        self.assert_no_temporary_files()

    def test_only_selected_pages_are_rendered_in_order(self) -> None:
        with patch.object(app, "_render_page", wraps=app._render_page) as render:
            self.convert(skip_pages="2")
        self.assertEqual(render.call_count, 2)
        self.assertEqual([call.args[1] for call in render.call_args_list], [0, 2])
        with PdfReader(self.source) as source, PdfReader(self.output) as result:
            self.assertEqual(len(result.pages), 3)
            self.assertEqual(result.pages[0].images[0].image.size, (144, 72))
            self.assertEqual(result.pages[2].images[0].image.size, (144, 288))
            self.assertEqual(result.pages[1].images[0].data, source.pages[1].images[0].data)
            self.assertEqual(result.get_destination_page_number(result.outline[1][0]), 1)
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
            patch.object(app.pymupdf, "open") as render,
            patch.object(app, "_encode_page") as encode,
            patch.object(app.features, "check", return_value=False),
        ):
            self.convert(skip_pages="1-3")
        render.assert_not_called()
        encode.assert_not_called()
        with PdfReader(self.output) as result:
            self.assertFalse(result.is_encrypted)
            self.assertEqual(len(result.pages), 3)
            self.assertEqual(result.pages[0].images[0].image.mode, "RGB")
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
        with PdfReader(self.output) as result:
            self.assertTrue(all(page.images[0].image.mode == "1" for page in result.pages))

    def test_cli_skip_selection_is_passed_to_converter(self) -> None:
        self.output.write_bytes(b"test output")
        for selection in ("1-2,-1", "-1,-2", ""):
            with (
                self.subTest(selection=selection),
                patch.object(sys, "argv", [str(SCRIPT), str(self.source), "-o", str(self.output),
                                            "--dpi=72", "--threshold=180", f"--skip-pages={selection}"]),
                patch.object(app, "_binarize_pdf") as convert,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(app.main(), 0)
                self.assertEqual(convert.call_args.args[-1], selection)


if __name__ == "__main__":
    unittest.main()
