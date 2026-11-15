"""Model downloads, checksum failures, cancellation, isolation and Unicode anchors."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import pymupdf
from test_pdf_ocr import ROOT, Settings, Result, Token, TextLayer, Worker
from personal_pdf_tools.ocr import models
from personal_pdf_tools.common.task_control import Cancelled, TaskControl


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="ocr-model-test-", dir=ROOT / "tmp")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.enterContext(patch.object(models, "cache_directory", return_value=self.folder))
        self.content = b"ONNX fixture" * 10000
        self.model = models.Model("fixture", "Fixture", "test", "https://example.invalid/fixture.onnx",
                                  hashlib.sha256(self.content).hexdigest())

    @contextmanager
    def response(self, body: bytes, status: int = 200):
        with patch.object(models.httpx, "stream", return_value=httpx.Response(status, content=body,
                request=httpx.Request("GET", self.model.url))) as stream:
            # Response itself is not a context manager in httpx.
            @contextmanager
            def opened(*args, **kwargs):
                yield httpx.Response(status, content=body, request=httpx.Request("GET", self.model.url))
            stream.side_effect = opened
            yield

    def test_download_verify_delete_and_existing_file_survives_failure(self) -> None:
        path = models.model_path(self.model)
        path.write_bytes(b"old model")
        for body, status, error in ((b"wrong hash", 200, ValueError), (b"error", 503, httpx.HTTPStatusError)):
            with self.response(body, status), self.assertRaises(error):
                models.download(self.model, TaskControl())
            self.assertEqual(path.read_bytes(), b"old model")
            self.assertEqual(list(self.folder.iterdir()), [path])
        progress = []
        with self.response(self.content):
            models.download(self.model, TaskControl(progress=progress.append))
        self.assertEqual(models.verify(self.model, TaskControl()).read_bytes(), self.content)
        self.assertTrue(progress)
        models.delete(self.model)
        self.assertFalse(path.exists())

    def test_cancel_during_download_cleans_stage_preserves_old_model(self) -> None:
        path = models.model_path(self.model)
        path.write_bytes(b"old")
        cancel = self.folder / "cancel"
        control = TaskControl(cancel=cancel, progress=lambda message: cancel.touch())
        with self.response(self.content), self.assertRaises(Cancelled):
            models.download(self.model, control)
        self.assertEqual(path.read_bytes(), b"old")
        self.assertFalse(list(self.folder.glob(".download-*")))

    def test_registry_bundled_protection_and_invalid_paths(self) -> None:
        registry = models.catalog()
        self.assertTrue(set(models.EXTENSIONS).issubset(registry))
        for key in ("detector", "cjk", "classifier"):
            models.verify(registry[key], TaskControl())
            with self.assertRaises(ValueError):
                models.delete(registry[key])
            with self.assertRaises(ValueError):
                models.download(registry[key], TaskControl())
        bad = models.Model("bad", "Bad", "", "https://example.invalid/..%2Fbad.onnx", "0" * 64)
        with self.assertRaises(ValueError):
            models.model_path(bad)
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            models.delete(self.model)

    def test_worker_model_operations_need_no_pdf_and_release_models(self) -> None:
        with patch.object(models, "catalog", return_value={"fixture": self.model}), WorkerContext() as worker:
            reply = worker.run({"operation": "model-list"})
            self.assertEqual(reply["kind"], "models")
            self.assertEqual(reply["rows"][0]["status"], "Not installed")
            worker.recognizer = object()
            with self.response(self.content):
                reply = worker.run({"operation": "model-download", "model": "fixture"})
            self.assertIsNone(worker.recognizer)
            self.assertEqual(reply["rows"][0]["size"], len(self.content))
            worker.run({"operation": "model-verify", "model": "fixture"})
            worker.run({"operation": "model-delete", "model": "fixture"})
            self.assertFalse(models.model_path(self.model).exists())

    def test_settings_migration_and_missing_model_never_downloads(self) -> None:
        from personal_pdf_tools.ocr.backend import Recognizer
        self.assertEqual(Settings.from_data({"language": "mixed"}).languages,
                         ("chinese", "english", "japanese", "korean"))
        self.assertEqual(Settings(languages=("thai",)).recognition_models(), ("thai",))
        self.assertEqual(Settings(languages=("english", "greek")).recognition_models(), ("cjk", "greek"))
        with patch("rapidocr.RapidOCR") as backend, self.assertRaisesRegex(FileNotFoundError, "Manage models"):
            Recognizer(Settings(languages=("thai",)))
        backend.assert_not_called()

    def test_extended_scripts_keep_unicode_and_invisible_highlight_anchors(self) -> None:
        words = ("مرحبا", "हिंदी", "ไทย", "தமிழ்", "తెలుగు", "Русский", "Ελληνικά")
        tokens = tuple(Token(text, ((.1, .08 + i * .12), (.8, .08 + i * .12),
                                    (.8, .14 + i * .12), (.1, .14 + i * .12)), .9)
                       for i, text in enumerate(words))
        result = Result("\n".join(words), tokens)
        with pymupdf.open() as doc:
            page = doc.new_page(width=400, height=700)
            before = page.get_pixmap().samples
            layer = TextLayer([result])
            layer.write(page, result)
            self.assertEqual(page.get_pixmap().samples, before)
            with pymupdf.open(stream=doc.tobytes(), filetype="pdf") as reopened:
                extracted = reopened[0].get_text()
                for text in words:
                    # MuPDF applies bidi ordering to extracted Arabic; every Unicode
                    # scalar must survive even when visual/logical order differs.
                    self.assertTrue(all(char in extracted for char in text), (text, extracted))
                for text in words[1:]:
                    self.assertTrue(reopened[0].search_for(text), (text, extracted))
                boxes = reopened[0].get_text("words")
                self.assertGreaterEqual(len(boxes), len(words))
                for box in boxes:
                    self.assertTrue(reopened[0].add_highlight_annot(pymupdf.Rect(box[:4])))


@contextmanager
def WorkerContext():
    worker = Worker()
    try:
        yield worker
    finally:
        worker.close()
