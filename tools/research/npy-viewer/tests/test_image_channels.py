"""Image channel, file-depth and fusion regressions using real encoded files.

Requirements: numpy, opencv-python and Pillow. Usage: unittest discovery here.
"""

import importlib
import importlib.util
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[2]
if "personal_npy_viewer" not in sys.modules:
    spec = importlib.util.spec_from_file_location("personal_npy_viewer", PACKAGE / "__init__.py",
                                                submodule_search_locations=[str(PACKAGE)])
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
model = importlib.import_module("personal_npy_viewer.data_model")


class ImageChannelTests(unittest.TestCase):
    """File metadata and derived previews never alter source channels."""

    def setUp(self) -> None:
        """Allocate fixtures in the repository's ignored scratch directory."""
        scratch = (ROOT / "tmp").resolve()
        self.directory = tempfile.TemporaryDirectory(prefix="viewer-image-test-", dir=scratch)
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.assertTrue(self.folder.is_relative_to(scratch))
        self.console = io.StringIO()
        self.enterContext(redirect_stdout(self.console))

    def _save(self, name: str, pixels: NDArray[np.uint8] | NDArray[np.uint16]) -> Path:
        path = self.folder / name
        if pixels.ndim == 3:
            order = [2, 1, 0, 3] if pixels.shape[-1] == 4 else [2, 1, 0]
            pixels = pixels[..., order]
        success, encoded = cv2.imencode(path.suffix, pixels)
        self.assertTrue(success)
        encoded.tofile(path)
        return path

    def test_rgb_and_rgba_channels_preserve_values_and_dtype(self) -> None:
        """8/16-bit RGB(A) source members are 2D views in named RGB(A) order."""
        for dtype in (np.uint8, np.uint16):
            for channels in (3, 4):
                with self.subTest(dtype=dtype, channels=channels):
                    maximum = np.iinfo(dtype).max
                    source = np.arange(3 * 4 * channels).reshape(3, 4, channels).astype(dtype)
                    source[0, 0, 0] = maximum
                    path = self._save(f"color-{channels}-{maximum}.png", source)
                    doc = model.load_document(path)
                    self.assertEqual(doc.key, model.ImageMember.RGB_GRAY)
                    self.assertIn("RGB color", doc.keys)
                    self.assertIn("RGBA color", doc.keys)
                    self.assertEqual(doc.image_source.metadata.depth, f"{source.dtype.itemsize * 8}-bit per channel")
                    for index, name in enumerate(("R", "G", "B", "A")[:channels]):
                        selected = model.select_image_member(doc, name)
                        self.assertEqual(selected.array.dtype, dtype)
                        self.assertEqual(selected.array.ndim, 2)
                        self.assertTrue(np.shares_memory(selected.array, doc.image_source.pixels))
                        frame = model.prepare_frame(selected, model.default_selection(selected), model.Limits(), 0)
                        np.testing.assert_array_equal(frame.scalar, source[..., index])
                        self.assertFalse(frame.composite)
                    np.testing.assert_array_equal(doc.image_source.pixels, source)

    def test_grayscale_fusions_keep_distinct_alpha_semantics(self) -> None:
        """RGB ignores alpha; RGBA grayscale composites against black."""
        source = np.array([[[65535, 0, 0, 0], [0, 65535, 0, 32768], [0, 0, 65535, 65535]]], dtype=np.uint16)
        doc = model.load_document(self._save("alpha16.png", source))
        luminance = source[..., :3].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])
        gray = model.select_image_member(doc, model.ImageMember.RGB_GRAY)
        weighted = model.select_image_member(doc, model.ImageMember.RGBA_GRAY)
        np.testing.assert_allclose(gray.array, luminance)
        np.testing.assert_allclose(weighted.array, luminance * source[..., 3] / 65535)
        np.testing.assert_allclose(doc.array, luminance)
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(), 0)
        self.assertFalse(frame.composite)
        np.testing.assert_allclose(frame.scalar, luminance)
        np.testing.assert_allclose(frame.image, luminance)
        np.testing.assert_array_equal(doc.image_source.pixels, source)

    def test_rgb_without_alpha_uses_opaque_fusion(self) -> None:
        """No synthetic alpha channel is advertised, and missing alpha means one."""
        source = np.array([[[20, 30, 40], [255, 128, 0]]], dtype=np.uint8)
        doc = model.load_document(self._save("rgb.png", source))
        self.assertNotIn("A", doc.keys)
        gray = model.select_image_member(doc, model.ImageMember.RGB_GRAY)
        weighted = model.select_image_member(doc, model.ImageMember.RGBA_GRAY)
        np.testing.assert_array_equal(gray.array, weighted.array)
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(), 0)
        self.assertFalse(frame.composite)
        np.testing.assert_array_equal(frame.scalar, gray.array)
        with self.assertRaises(KeyError):
            model.select_image_member(doc, "A")

    def test_monochrome_16bit_and_1bit_metadata(self) -> None:
        """Original 1-bit PNGs are distinguished from their expanded uint8 buffers."""
        source = np.array([[0, 1000, 65535]], dtype=np.uint16)
        doc = model.load_document(self._save("gray16.png", source))
        self.assertEqual(doc.keys, ("Monochrome", "Monochrome color"))
        self.assertEqual(doc.image_source.metadata.depth, "16-bit per channel")
        np.testing.assert_array_equal(doc.array, source)
        binary = self.folder / "binary.png"
        Image.fromarray(np.array([[True, False, True]])).save(binary)
        doc = model.load_document(binary)
        self.assertEqual(doc.image_source.metadata.depth, "1-bit per channel")
        self.assertEqual(doc.array.dtype, np.uint8)
        self.assertEqual(doc.keys, ("Monochrome", "Monochrome color"))
        selection = model.default_selection(doc, model.ViewMode.SIGNAL)
        self.assertIsNone(selection.channel_axis)

    def test_monochrome_alpha_members(self) -> None:
        """Gray+alpha PNGs expose only their two actual source channels."""
        values = np.array([[[25, 0], [180, 128], [255, 255]]], dtype=np.uint8)
        path = self.folder / "gray-alpha.png"
        Image.fromarray(values).save(path)
        doc = model.load_document(path)
        self.assertEqual(doc.image_source.metadata.mode, "LA")
        self.assertEqual(doc.image_source.channels, (model.ImageMember.MONO, model.ImageMember.ALPHA))
        self.assertEqual(doc.keys, ("Monochrome", "A", model.ImageMember.RGBA_GRAY.value,
                                    "RGBA color", "Monochrome color"))
        gray = model.select_image_member(doc, "Monochrome")
        np.testing.assert_array_equal(gray.array, values[..., 0])
        weighted = model.select_image_member(doc, model.ImageMember.RGBA_GRAY)
        np.testing.assert_allclose(weighted.array, values[..., 0].astype(float) * values[..., 1] / 255)
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(), 0)
        self.assertEqual(doc.key, model.ImageMember.MONO)
        np.testing.assert_array_equal(frame.scalar, values[..., 0])
        color = model.select_image_member(doc, model.ImageMember.RGBA_COLOR)
        frame = model.prepare_frame(color, model.default_selection(color), model.Limits(), 0)
        self.assertTrue(frame.composite)
        np.testing.assert_array_equal(frame.image[..., :3], np.repeat(values[..., :1], 3, axis=-1))
        np.testing.assert_array_equal(frame.image[..., 3], values[..., 1])

    def test_palette_indices_and_tiff_sample_depth(self) -> None:
        """Indexed PNG depth is not misreported as RGB depth; TIFF keeps 16 bits."""
        palette = Image.new("P", (3, 2))
        palette.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
        palette.putdata([0, 1, 2, 3, 2, 1])
        path = self.folder / "palette.png"
        palette.save(path, bits=2)
        doc = model.load_document(path)
        self.assertEqual(doc.image_source.metadata.depth, "2-bit palette indices")
        self.assertEqual(doc.image_source.metadata.mode, "P")
        self.assertEqual(doc.image_source.channels, (model.ImageMember.RED, model.ImageMember.GREEN, model.ImageMember.BLUE))
        values = np.array([[[65535, 32768, 12345], [0, 1, 2]]], dtype=np.uint16)
        tiff = model.load_document(self._save("color16.tiff", values))
        self.assertEqual(tiff.image_source.metadata.depth, "16-bit per channel")
        np.testing.assert_array_equal(tiff.image_source.pixels, values)

    def test_initial_member_cropping_and_cached_switch(self) -> None:
        """Member switches need no file I/O and keep full-resolution crop indices."""
        source = np.arange(5 * 7 * 4, dtype=np.uint16).reshape(5, 7, 4)
        path = self._save("cropped.png", source)
        doc = model.load_document(path, "G")
        path.unlink()
        alpha = model.select_image_member(doc, "A")
        frame = model.prepare_frame(alpha, model.default_selection(alpha), model.Limits(), 0, model.Crop(2, 4, 1, 3))
        np.testing.assert_array_equal(frame.scalar, source[1:4, 2:5, 3])
        self.assertEqual((frame.x_start, frame.y_start), (2, 1))
        self.assertIs(alpha.image_source, doc.image_source)

    def test_color_members_share_height_but_differ_in_alpha(self) -> None:
        """RGB is opaque; RGBA preserves opacity, while heights remain luminance."""
        source = np.array([[[65535, 0, 0, 0], [0, 65535, 0, 32768]],
                           [[0, 0, 65535, 65535], [65535, 65535, 65535, 10000]]], dtype=np.uint16)
        doc = model.load_document(self._save("render16.png", source))
        gray = source[..., :3].astype(float) @ np.asarray(model.LUMINANCE_WEIGHTS)
        for member in (model.ImageMember.RGB_COLOR, model.ImageMember.RGBA_COLOR):
            selected = model.select_image_member(doc, member)
            frame = model.prepare_frame(selected, model.default_selection(selected), model.Limits(), 0)
            self.assertTrue(frame.composite)
            np.testing.assert_allclose(frame.scalar, gray)
            np.testing.assert_array_equal(frame.image[..., :3], (source[..., :3] / 65535 * 255).astype(np.uint8))
            expected_alpha = 255 if member == model.ImageMember.RGB_COLOR else (source[..., 3] / 65535 * 255).astype(np.uint8)
            np.testing.assert_array_equal(frame.image[..., 3], expected_alpha)
            mesh = frame.surface
            np.testing.assert_array_equal(mesh.colors, frame.image[mesh.rows, mesh.columns])
        np.testing.assert_array_equal(doc.image_source.pixels, source)

    def test_color_crop_and_grayscale_replication(self) -> None:
        """Cropping preserves color-to-vertex alignment; grayscale expands equally."""
        source = np.arange(8 * 9, dtype=np.uint16).reshape(8, 9) * 500
        doc = model.load_document(self._save("gray-color.png", source), model.ImageMember.MONO_COLOR)
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(), 3, model.Crop(2, 7, 3, 6))
        mesh = frame.surface
        expected_gray = (source[mesh.rows, mesh.columns] / 65535 * 255).astype(np.uint8)
        for channel in range(3):
            np.testing.assert_array_equal(mesh.colors[:, channel], expected_gray)
        np.testing.assert_array_equal(mesh.colors[:, 3], 255)
        np.testing.assert_allclose(frame.scalar, source[3:7, 2:8])

    def test_debug_output_reports_source_and_selected_matrix(self) -> None:
        """Console diagnostics include format, depth, layout, dtype and selected key."""
        source = np.array([[[5000, 6000, 7000, 32768]]], dtype=np.uint16)
        model.load_document(self._save("debug.png", source), "A")
        text = self.console.getvalue()
        for expected in ("[Image] Opening:", "Format: PNG", "file depth: 16-bit per channel",
                         "Decoded: RGBA", "dtype: uint16", "Selected: A", "loaded in"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
