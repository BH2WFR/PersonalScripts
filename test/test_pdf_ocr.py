"""Generated PDF checks for additive OCR, geometry, isolation and cancellation."""

from contextlib import closing
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("pdf_ocr_entry", ROOT / "tools/document-processing/pdf-ocr.py")
assert spec is not None and spec.loader is not None
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
entry.load_app("ocr.model")
from personal_pdf_tools.ocr.model import Result, Settings, Token, adjusted_result
from personal_pdf_tools.ocr.preprocessing import preprocess
from personal_pdf_tools.ocr.tiling import tiles, recognize_tiled
from personal_pdf_tools.ocr.engine import TextLayer, recognition_image, token_points
from personal_pdf_tools.ocr.worker import Worker
from personal_pdf_tools.common.task_control import Cancelled
from utils import Pdf


RESULT = Result("测试 English 日本語 한국어", (
    Token("测试 English 日本語 한국어", ((.1, .2), (.8, .2), (.8, .3), (.1, .3)), .9),))


class OcrEngineTests(unittest.TestCase):
    """Use deterministic anchors rather than relying on model accuracy in unit tests."""

    def test_settings_validation(self) -> None:
        self.assertEqual(Settings.from_data(Settings().to_data()), Settings())
        self.assertEqual(Settings().languages, ("chinese", "english"))
        self.assertEqual(Settings.from_data({"language": "cjk"}), Settings())
        self.assertEqual(Settings.from_data({"language": "mixed", "languages": ["english"]}).languages, ("english",))
        self.assertEqual(Settings(languages=("english", "korean")).recognition_models(), ("korean",))
        self.assertEqual(Settings(languages=("japanese", "korean")).recognition_models(), ("cjk", "korean"))
        for data in ({"dpi": True}, {"dpi": 0}, {"threshold": float("nan")}, {"score": 2},
                     {"language": "other"}, {"angle": 1}, {"threads": 4.5}, {"languages": []},
                     {"languages": "english"}, {"languages": ["unknown"]}, {"tile_overlap": 100},
                     {"margin_y": -50}, {"contrast": "other"}, {"tile_size": 0}):
            with self.assertRaises(ValueError):
                Settings.from_data(data)
        self.assertEqual(Result.from_data(RESULT.to_data()), RESULT)

    def test_preprocessing_preserves_geometry_input_and_disabled_behavior(self) -> None:
        image = np.zeros((100, 120, 3), dtype=np.uint8)
        image[:] = np.arange(120)[None, :, None] + 60
        original = image.copy()
        self.assertIs(preprocess(image, Settings()), image)
        for contrast in ("off", "auto", "local"):
            for denoise in ("off", "median", "bilateral"):
                result = preprocess(image, Settings(grayscale=True, contrast=contrast, denoise=denoise))
                self.assertEqual(result.shape, image.shape)
                self.assertEqual(result.dtype, np.uint8)
                self.assertTrue(np.array_equal(result[:, :, 0], result[:, :, 2]))
                self.assertTrue(np.array_equal(image, original))
        stretched = preprocess(image, Settings(grayscale=True, contrast="auto"))
        self.assertEqual((stretched.min(), stretched.max()), (0, 255))

    def test_anchor_margins_do_not_change_raw_coordinates_or_inference_key(self) -> None:
        settings = Settings(margin_x=10, margin_y=-20)
        adjusted = adjusted_result(RESULT, settings)
        self.assertEqual(settings.for_recognition(), Settings())
        self.assertEqual(RESULT.tokens[0].quad[0], (.1, .2))
        np.testing.assert_allclose(adjusted.tokens[0].quad, ((.03, .22), (.87, .22), (.87, .28), (.03, .28)))
        self.assertEqual(adjusted.text, RESULT.text)

    def test_tiled_coordinates_and_seam_deduplication(self) -> None:
        width, height = 1300, 900
        settings = Settings(tiled=True, tile_size=512, tile_overlap=20)
        windows = list(tiles(width, height, settings.tile_size, settings.tile_overlap))
        positions = [(100, 100), (460, 200), (490, 200), (850, 250), (1100, 400), (850, 700), (480, 650)]
        calls = iter(windows)

        def recognize(pixels: np.ndarray, checkpoint: object) -> Result:
            tile = next(calls)
            x0, y0, x1, y1 = tile.rect
            tokens = tuple(Token(f"word{index}", tuple(((x - x0 + dx) / (x1 - x0), (y - y0 + dy) / (y1 - y0))
                for dx, dy in ((-15, -10), (15, -10), (15, 10), (-15, 10))), .9)
                for index, (x, y) in enumerate(positions) if x0 + 15 <= x < x1 - 15 and y0 + 10 <= y < y1 - 10)
            return Result("\n".join(token.text for token in tokens), tokens, (1,) * len(tokens))

        result = recognize_tiled(np.zeros((height, width, 3), dtype=np.uint8), settings, recognize, lambda: None)
        self.assertEqual(len(result.tokens), len(positions))
        self.assertEqual({token.text for token in result.tokens}, {f"word{i}" for i in range(len(positions))})
        for token in result.tokens:
            x, y = positions[int(token.text[4:])]
            np.testing.assert_allclose(np.mean(token.quad, axis=0), (x / width, y / height))
        self.assertEqual(sum(result.line_lengths), len(result.tokens))
        self.assertIn("word1 word2", result.text)
        for index in range(len(positions)):
            self.assertEqual(result.text.count(f"word{index}"), 1)

    def test_hidden_layer_rotated_cropped_and_highlightable(self) -> None:
        layer = TextLayer([RESULT])
        self.assertLess(len(layer.buffer), 100_000)
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), pymupdf.open() as doc:
                page = doc.new_page(width=600, height=800)
                page.set_cropbox(pymupdf.Rect(40, 50, 560, 750))
                page.set_rotation(rotation)
                before = page.get_pixmap().samples
                layer.write(page, RESULT)
                data = doc.tobytes()
                with pymupdf.open(stream=data, filetype="pdf") as reopened:
                    actual = reopened[0]
                    self.assertEqual(actual.get_pixmap().samples, before)
                    self.assertIn(RESULT.text, actual.get_text())
                    points = token_points(actual, RESULT.tokens[0])
                    bounds = pymupdf.Quad(points[0], points[1], points[3], points[2]).rect
                    text_bounds = pymupdf.Rect(actual.get_text("dict")["blocks"][0]["bbox"])
                    for a, b in zip(text_bounds, bounds):
                        self.assertAlmostEqual(a, b, delta=.3)
                    quads = actual.search_for("한국어", quads=True)
                    self.assertTrue(quads)
                    actual.add_highlight_annot(quads)
                    self.assertNotEqual(actual.get_pixmap().samples, before)

    def test_existing_text_masked_without_losing_image_text(self) -> None:
        with pymupdf.open() as doc:
            page = doc.new_page(width=200, height=200)
            page.insert_text((20, 40), "Native text", fontsize=16)
            page.draw_rect((20, 90, 100, 120), fill=(0, 0, 0), color=None)
            for rotation in (0, 90, 180, 270):
                page.set_rotation(rotation)
                image = recognition_image(page, Settings(dpi=72))
                rect = pymupdf.Rect(20, 90, 100, 120) * page.rotation_matrix
                mask = image.copy()
                mask[int(rect.y0)-1:int(rect.y1)+1, int(rect.x0)-1:int(rect.x1)+1] = 255
                self.assertTrue(np.all(mask == 255))
                self.assertLess(image.min(), 10)

    def test_worker_reuse_ignored_preservation_and_settings_invalidation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            folder = Path(temporary)
            source, output = folder / "source.pdf", folder / "output.pdf"
            with pymupdf.open() as doc:
                for index in range(3):
                    page = doc.new_page(width=300, height=400)
                    page.insert_text((30, 35), f"Keep {index}")
                doc[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(20, 20, 50, 50), "uri": "https://example.com"})
                doc[0].add_text_annot((150, 150), "Keep annotation")
                doc.set_toc([[1, "One", 1], [1, "Three", 3]])
                Pdf.write_page_labels(doc, ["i", "ii", "1"])
                Pdf.save_new(doc, source)
            with patch("personal_pdf_tools.ocr.worker.Recognizer") as backend, closing(Worker()) as worker:
                backend.return_value.recognize.return_value = RESULT
                request = {"path": str(source), "settings": Settings().to_data()}
                worker.run({**request, "operation": "scan", "page": 1})
                worker.run({**request, "operation": "export", "ignored": "2", "output": str(output)})
                self.assertEqual(backend.return_value.recognize.call_count, 2)
                worker.run({**request, "operation": "scan", "page": 1,
                            "settings": Settings(margin_x=10).to_data()})
                self.assertEqual(backend.return_value.recognize.call_count, 2)
                with Pdf.open_document(source, interactive=False) as (original, _), Pdf.open_document(output, interactive=False) as (result, _):
                    self.assertEqual(result.get_toc(), original.get_toc())
                    self.assertEqual(Pdf.read_page_labels(result), ["i", "ii", "1"])
                    self.assertEqual(result[0].get_links()[0]["uri"], "https://example.com")
                    self.assertEqual(next(result[0].annots()).info["content"], "Keep annotation")
                    self.assertEqual(result[1].get_text(), original[1].get_text())
                    for index in range(3):
                        self.assertEqual(result[index].get_pixmap().samples, original[index].get_pixmap().samples)
                    self.assertIn(RESULT.text, result[2].get_text())
                with self.assertRaises(FileExistsError):
                    worker.run({**request, "operation": "export", "output": str(source), "overwrite": True})
                worker.run({**request, "operation": "scan", "settings": Settings(score=.2).to_data()})
                self.assertEqual(backend.return_value.recognize.call_count, 3)

    def test_cancellation_retains_completed_pages_and_never_publishes(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
            folder = Path(temporary)
            source, output, cancel = folder / "source.pdf", folder / "output.pdf", folder / "cancel"
            with pymupdf.open() as doc:
                doc.new_page()
                doc.new_page()
                Pdf.save_new(doc, source)

            def progress(message: dict) -> None:
                if message.get("done") == 1:
                    cancel.touch()

            with patch("personal_pdf_tools.ocr.worker.Recognizer") as backend, closing(Worker(progress)) as worker:
                backend.return_value.recognize.return_value = RESULT
                with self.assertRaises(Cancelled):
                    worker.run({"operation": "export", "path": str(source), "output": str(output), "cancel": str(cancel)})
                self.assertEqual(set(worker.results), {0})
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
