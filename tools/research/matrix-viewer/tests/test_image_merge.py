"""Verify selected-channel composition, image metadata and lossless PNG pixels.

Requirements: existing viewer dependencies. In-memory inputs only; no manual
test-matrix files are generated or changed.
"""

from dataclasses import replace
import importlib
from io import BytesIO
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from test_data_model import model

merge = importlib.import_module("personal_matrix_viewer.image_merge")
exporting = importlib.import_module("personal_matrix_viewer.exporting")
components = importlib.import_module("personal_matrix_viewer.complex_merge")


def candidate(values: np.ndarray, label: str = "source") -> components.MergeInput:
    """Create a full scalar 2D interpretation without loading a file."""
    document = model.Document(Path(f"{label}.npy"), values)
    return components.MergeInput(document, model.default_selection(document, model.ViewMode.MATRIX), label)


class ImageMergeTests(unittest.TestCase):
    """Verify ownership, mapping order, alpha layout and input validation."""

    def test_gains_and_png_round_trip(self) -> None:
        values = np.arange(20, dtype=np.uint8).reshape(4, 5) * 10
        before = values.copy()
        prepared = merge.prepare_images((candidate(values),))
        channels = (merge.ImageChannel(0, gain=2), merge.ImageChannel(0, gain=.5),
                    merge.ImageChannel(-1, constant=25), merge.ImageChannel(-1, constant=255, gain=.5))
        result = merge.generate_image(prepared, merge.ImageMergeMode.RGBA, channels, "Merged")
        source = result.document.image_source
        self.assertIsNotNone(source)
        pixels = source.pixels
        np.testing.assert_array_equal(pixels[..., 0], np.minimum(values.astype(float) * 2, 255))
        np.testing.assert_array_equal(pixels[..., 1], np.rint(values.astype(float) * .5))
        self.assertTrue(np.all(pixels[..., 2] == 25))
        self.assertTrue(np.all(pixels[..., 3] == 128))
        self.assertFalse(np.shares_memory(pixels, values))
        np.testing.assert_array_equal(values, before)
        data = exporting.serialize_array(pixels, exporting.ExportFormat.PNG)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.mode, "RGBA")
            np.testing.assert_array_equal(np.asarray(image), pixels)
        self.assertEqual(result.document.key, model.ImageMember.RGBA_COLOR)
        self.assertIn(model.ImageMember.RGBA_GRAY, result.document.keys)

    def test_monochrome_alpha_and_rgb_layouts(self) -> None:
        prepared = merge.prepare_images((candidate(np.full((4, 5), 77, dtype=np.uint8)),))
        for mode in (merge.ImageMergeMode.MA, merge.ImageMergeMode.RGB):
            specs = tuple(merge.ImageChannel(0) for _ in mode.channels)
            result = merge.generate_image(prepared, mode, specs, "")
            pixels = result.document.image_source.pixels
            with Image.open(BytesIO(exporting.serialize_array(pixels, exporting.ExportFormat.PNG))) as image:
                self.assertEqual(image.mode, "LA" if mode == merge.ImageMergeMode.MA else "RGB")
                np.testing.assert_array_equal(np.asarray(image), pixels)
            if mode == merge.ImageMergeMode.MA:
                self.assertNotIn(model.ImageMember.RGB_COLOR, result.document.keys)
            else:
                self.assertNotIn(model.ImageMember.RGBA_COLOR, result.document.keys)

    def test_mapping_nonfinite_and_complex_component(self) -> None:
        values = np.array([[0, .5, 1], [np.nan, -np.inf, np.inf]])
        prepared = merge.prepare_images((candidate(values),))
        unit = merge.ImageChannel(0, gain=.5, mapping=merge.ImageMapping.UNIT)
        pixels = merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, (unit,) * 3)
        np.testing.assert_array_equal(pixels[..., 0], [[0, 64, 128], [0, 0, 255]])
        complex_input = candidate(np.full((4, 5), 3 + 4j))
        complex_input = replace(complex_input, selection=replace(complex_input.selection, component=model.Component.IMAGINARY))
        prepared = merge.prepare_images((complex_input,))
        np.testing.assert_array_equal(prepared.values[0], np.full((4, 5), 4))
        self.assertEqual(prepared.ranges, ((4, 4),))

    def test_invalid_shapes_modes_and_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "identical dimensions"):
            merge.prepare_images((candidate(np.zeros((4, 5))), candidate(np.zeros((5, 4)))))
        prepared = merge.prepare_images((candidate(np.zeros((4, 5))),))
        for spec in (merge.ImageChannel(0, gain=-1), merge.ImageChannel(0, mapping=merge.ImageMapping.MANUAL, lower=5, upper=2)):
            with self.assertRaises(ValueError):
                merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, (spec,) * 3)
        with self.assertRaisesRegex(ValueError, "Use PNG"):
            exporting.serialize_array(np.zeros((4, 5, 4), dtype=np.uint8), exporting.ExportFormat.BMP)

    def test_shared_auto_uses_assigned_sources_and_matches_preview(self) -> None:
        values = np.arange(20, dtype=float).reshape(4, 5)
        prepared = merge.prepare_images(tuple(candidate(data) for data in
            (values, values + 100, values + 200, values + 10000)))
        channels = tuple(merge.ImageChannel(index, mapping=merge.ImageMapping.AUTO_SHARED) for index in range(3))
        for channel in channels:
            self.assertEqual(merge.channel_limits(prepared, channel, channels), (0, 219))
        pixels = merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, channels)
        np.testing.assert_array_equal(pixels[..., 1], np.rint((values + 100) / 219 * 255))
        np.testing.assert_array_equal(pixels, merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, channels, preview=True))
        own = tuple(replace(channel, mapping=merge.ImageMapping.AUTO) for channel in channels)
        own_pixels = merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, own)
        np.testing.assert_array_equal(own_pixels[..., 0], own_pixels[..., 2])
        # Alpha participates only when assigned, not when it is an opaque constant.
        rgba = channels + (merge.ImageChannel(3),)
        self.assertEqual(merge.channel_limits(prepared, channels[0], rgba), (0, 10019))
        rgba = channels + (merge.ImageChannel(-1, constant=255),)
        self.assertEqual(merge.channel_limits(prepared, channels[0], rgba), (0, 219))
        result = merge.generate_image(prepared, merge.ImageMergeMode.RGB, channels, "shared")
        np.testing.assert_array_equal(result.document.image_source.pixels, pixels)
        self.assertIn("range=(0.0, 219.0)", result.document.conversion_provenance)

    def test_shared_auto_excludes_sources_without_finite_values(self) -> None:
        prepared = merge.prepare_images((candidate(np.full((4, 5), 20.0)),
                                         candidate(np.full((4, 5), np.nan))))
        channels = (merge.ImageChannel(0, mapping=merge.ImageMapping.AUTO_SHARED),
                    merge.ImageChannel(1, mapping=merge.ImageMapping.AUTO_SHARED),
                    merge.ImageChannel(-1))
        self.assertIsNone(prepared.ranges[1])
        self.assertEqual(merge.channel_limits(prepared, channels[0], channels), (20, 20))
        self.assertFalse(merge.merge_pixels(prepared, merge.ImageMergeMode.RGB, channels).any())
        self.assertEqual(merge.channel_limits(prepared, channels[1], (channels[1],)), (0, 0))


if __name__ == "__main__":
    unittest.main()
