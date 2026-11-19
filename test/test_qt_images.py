"""Pixel ownership and atomic PNG output for shared Qt image operations."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from PySide6.QtGui import QImage

from utils.qt_images import qimage_from_pillow, save_png


class QtImageTests(unittest.TestCase):
    def test_png_keeps_alpha_and_survives_failed_replacement(self) -> None:
        with Image.new("RGBA", (3, 2), (25, 50, 75, 128)) as source:
            image = qimage_from_pillow(source)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "preview.png"
            save_png(image, path)
            saved = path.read_bytes()
            self.assertEqual(QImage(str(path)).pixelColor(2, 1).getRgb(), (25, 50, 75, 128))
            with self.assertRaises(OSError):
                save_png(QImage(), path)
            self.assertEqual(path.read_bytes(), saved)
