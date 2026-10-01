"""Behavioral tests for matrix interpretation, source fidelity and mesh gaps.

Requirements: numpy and opencv-python.
Usage: conda run -n base python -m unittest discover -s tools/research/npy-viewer/tests
"""

from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np
from fixture_store import fixture_directory, preserve_document

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[2]
spec = importlib.util.spec_from_file_location("personal_npy_viewer", PACKAGE / "__init__.py",
                                            submodule_search_locations=[str(PACKAGE)])
assert spec is not None and spec.loader is not None
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
model = importlib.import_module("personal_npy_viewer.data_model")


class DataModelTests(unittest.TestCase):
    """Validate scientific data semantics independently of rendering backends."""

    def test_integer_fidelity_and_axis_order(self) -> None:
        """Keep integers above float precision exact in source data/readouts."""
        source = np.arange(35, dtype=np.uint64).reshape(5, 7) + 2**60
        document = preserve_document(model.Document(Path("matrix.npy"), source), "unit-inputs/test_data_model")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        np.testing.assert_array_equal(frame.scalar, source)
        self.assertEqual(model.format_value(frame.scalar[3, 4]), str(2**60 + 25))
        surface = frame.surface
        self.assertIsNotNone(surface)
        self.assertEqual(surface.points.dtype, np.float64)
        np.testing.assert_array_equal(surface.points[:, 0], surface.columns)
        np.testing.assert_array_equal(surface.points[:, 1], surface.rows)

    def test_channel_first_and_channel_last_match(self) -> None:
        """The same channel gives the same matrix under HWC and CHW layouts."""
        source = np.arange(60).reshape(4, 5, 3)
        for array, channel_axis in ((source, 2), (source.transpose(2, 0, 1), 0)):
            document = preserve_document(model.Document(Path("channels.npy"), array), "unit-inputs/test_data_model")
            selection = replace(model.default_selection(document, channel_axis=channel_axis), channel=2)
            frame = model.prepare_frame(document, selection, model.Limits(), 0)
            np.testing.assert_array_equal(frame.scalar, source[:, :, 2])

    def test_multichannel_signal_and_extra_slice(self) -> None:
        """Axis selection handles NC signals and extra indexed dimensions."""
        source = np.arange(48).reshape(2, 8, 3)
        document = preserve_document(model.Document(Path("signal.npy"), source), "unit-inputs/test_data_model")
        selection = model.Selection(model.ViewMode.SIGNAL, 1, None, 2, 1, (1, 0, 0))
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        np.testing.assert_array_equal(frame.scalar, source[1, :, 1])
        self.assertIsNone(frame.surface)

    def test_complex_component(self) -> None:
        """Every complex display component is real-valued and numerically correct."""
        document = preserve_document(model.Document(Path("complex.npy"), np.array([3 + 4j, 1j])), "unit-inputs/test_data_model")
        expected = {
            model.Component.REAL: [3, 0],
            model.Component.IMAGINARY: [4, 1],
            model.Component.MAGNITUDE: [5, 1],
            model.Component.PHASE: [np.arctan2(4, 3), np.pi / 2],
            model.Component.PHASE_DEG: [53.13010235415598, 90],
        }
        for component, values in expected.items():
            with self.subTest(component=component):
                selection = replace(model.default_selection(document), component=component)
                frame = model.prepare_frame(document, selection, model.Limits(), 0)
                self.assertFalse(np.iscomplexobj(frame.scalar))
                np.testing.assert_allclose(frame.scalar, values)

    def test_sample_formatting_requires_complete_indices(self) -> None:
        """Preserve raw float/integer formatting and reject accidental row selection."""
        integers = np.array([[2**60 + 1]], dtype=np.uint64)
        self.assertEqual(model.format_sample(integers, 0, 0), str(2**60 + 1))
        floats = np.array([0.12345678], dtype=np.float32)
        self.assertEqual(model.format_sample(floats, 0), str(floats[0]))
        self.assertEqual(model.format_sample(np.array([True]), 0), "True")
        with self.assertRaises(ValueError):
            model.format_sample(integers, 0)
        with self.assertRaises(IndexError):
            model.format_sample(integers, 2, 0)

    def test_fractional_surface_heights(self) -> None:
        """Integer grid coordinates must not cause fractional heights to truncate."""
        source = np.array([[0.25, 0.75], [1.25, 1.75]], dtype=np.float32)
        document = preserve_document(model.Document(Path("fractional.npy"), source), "unit-inputs/test_data_model")
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 0)
        self.assertEqual(frame.surface.points.dtype, np.float64)
        np.testing.assert_array_equal(frame.surface.points[:, 2], source.ravel())

    def test_filter_preserves_holes_inside_sampled_cells(self) -> None:
        """A removed interior pixel must not be covered by a coarse surface."""
        source = np.ones((7, 7))
        source[2, 2] = 100
        document = preserve_document(model.Document(Path("hole.npy"), source), "unit-inputs/test_data_model")
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(0, 2), 3)
        self.assertFalse(frame.valid[2, 2])
        self.assertTrue(np.isnan(frame.image[2, 2]))
        surface = frame.surface
        self.assertEqual(surface.faces.size // 5, 3)
        for face in surface.faces.reshape(-1, 5)[:, 1:]:
            rows, columns = surface.rows[face], surface.columns[face]
            self.assertTrue(np.all(frame.valid[rows.min():rows.max() + 1, columns.min():columns.max() + 1]))

    def test_filter_endpoints_nonfinite_and_empty_result(self) -> None:
        """Bounds are inclusive and NaN/Inf never produce visible vertices."""
        source = np.array([[0, 1, 2], [np.nan, np.inf, 3]])
        document = preserve_document(model.Document(Path("filter.npy"), source), "unit-inputs/test_data_model")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(1, 2), 0)
        np.testing.assert_array_equal(frame.valid, [[False, True, True], [False, False, False]])
        empty = model.prepare_frame(document, selection, model.Limits(10, 20), 0)
        self.assertEqual(len(empty.surface.points), 0)
        self.assertEqual(empty.limits, (0, 1))

    def test_singleton_dimensions(self) -> None:
        """One-pixel-wide matrices retain their axes and render as points."""
        for shape in ((1, 5), (5, 1), (1, 1)):
            document = preserve_document(model.Document(Path("narrow.npy"), np.ones(shape)), "unit-inputs/test_data_model")
            frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 2)
            self.assertEqual(frame.scalar.shape, shape)
            self.assertEqual(frame.surface.faces.size, 0)
            self.assertGreater(len(frame.surface.points), 0)

    def test_npy_npz_and_16bit_png(self) -> None:
        """Disk loaders preserve values, archive members and Unicode image paths."""
        folder = fixture_directory("unit-files/numpy")
        source = np.array([[0, 1024, 65535], [9, 300, 2048]], dtype=np.uint16)
        np.save(folder / "a.npy", source)
        loaded = model.load_document(folder / "a.npy")
        np.testing.assert_array_equal(loaded.array, source)
        del loaded
        np.savez(folder / "arrays.npz", signal=np.arange(6), matrix=source)
        archive = model.load_document(folder / "arrays.npz", "matrix")
        self.assertEqual(archive.keys, ("signal", "matrix"))
        np.testing.assert_array_equal(archive.array, source)
        np.savez(folder / "mixed.npz", metadata=np.array({"label": "test"}, dtype=object),
                 empty=np.empty(0), matrix=source)
        mixed = model.load_document(folder / "mixed.npz")
        self.assertEqual(mixed.key, "matrix")
        self.assertEqual(mixed.keys, ("metadata", "empty", "matrix"))
        success, encoded = cv2.imencode(".png", source)
        self.assertTrue(success)
        path = folder / "matrix-\u6d4b\u8bd5.png"
        encoded.tofile(path)
        image = model.load_document(path)
        self.assertEqual(image.array.dtype, np.uint16)
        np.testing.assert_array_equal(image.array, source)

    def test_matrix_crop_keeps_original_coordinates_and_precision(self) -> None:
        """Inclusive matrix crops retain raw uint64 values and absolute mesh indices."""
        source = np.arange(117, dtype=np.uint64).reshape(9, 13) + 2**60
        document = preserve_document(model.Document(Path("matrix.npy"), source), "unit-inputs/test_data_model")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(), 4, model.Crop(3, 9, 2, 6))
        np.testing.assert_array_equal(frame.scalar, source[2:7, 3:10])
        self.assertEqual(frame.scalar.dtype, np.uint64)
        self.assertEqual((frame.x_start, frame.y_start), (3, 2))
        surface = frame.surface
        self.assertIsNotNone(surface)
        np.testing.assert_array_equal(surface.points[:, 0], surface.columns)
        np.testing.assert_array_equal(surface.points[:, 1], surface.rows)
        self.assertEqual((surface.columns.min(), surface.columns.max()), (3, 9))
        self.assertEqual((surface.rows.min(), surface.rows.max()), (2, 6))

    def test_crop_after_axis_assignment_and_extra_slice(self) -> None:
        """Crop bounds refer to assigned X/Y axes, including transposed matrices."""
        source = np.arange(2 * 7 * 9).reshape(2, 7, 9)
        document = preserve_document(model.Document(Path("axes.npy"), source), "unit-inputs/test_data_model")
        selection = model.Selection(model.ViewMode.MATRIX, 1, 2, None, 0, (1, 0, 0))
        frame = model.prepare_frame(document, selection, model.Limits(), 0, model.Crop(1, 3, 4, 5))
        np.testing.assert_array_equal(frame.scalar, source[1, 1:4, 4:6].T)
        self.assertEqual(frame.scalar.shape, (2, 3))

    def test_crop_multichannel_signal_and_complex_component(self) -> None:
        """Signal crops select sample indices without cropping channel dimensions."""
        source = np.arange(24).reshape(8, 3) * (1 + 2j)
        document = preserve_document(model.Document(Path("signal.npy"), source), "unit-inputs/test_data_model")
        selection = replace(model.default_selection(document, model.ViewMode.SIGNAL, 1),
                            channel=2, component=model.Component.IMAGINARY)
        frame = model.prepare_frame(document, selection, model.Limits(), 0, model.Crop(2, 5))
        np.testing.assert_array_equal(frame.scalar, source[2:6, 2].imag)
        self.assertEqual(frame.x_start, 2)
        self.assertIsNone(frame.surface)

    def test_crop_rgba_and_channel_first(self) -> None:
        """RGB composition crops all channels identically under HWC and CHW layouts."""
        source = np.arange(8 * 10 * 4, dtype=np.uint16).reshape(8, 10, 4).astype(np.uint8)
        for array, axis in ((source, 2), (source.transpose(2, 0, 1), 0)):
            document = preserve_document(model.Document(Path("rgba.png"), array, is_image=True), "unit-inputs/test_data_model")
            selection = model.default_selection(document, channel_axis=axis)
            frame = model.prepare_frame(document, selection, model.Limits(), 0, model.Crop(2, 6, 3, 5))
            np.testing.assert_array_equal(frame.image, source[3:6, 2:7])
            np.testing.assert_allclose(frame.scalar, source[3:6, 2:7, :3] @ np.array([0.2126, 0.7152, 0.0722]))

    def test_crop_single_pixel_filter_restore_and_absolute_reapply(self) -> None:
        """Singleton crops work, filters remain gaps, and recropping uses the source."""
        source = np.arange(48, dtype=np.float64).reshape(6, 8)
        original = source.copy()
        document = preserve_document(model.Document(Path("matrix.npy"), source), "unit-inputs/test_data_model")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(30, None), 0, model.Crop(4, 4, 2, 2))
        self.assertEqual(frame.scalar.shape, (1, 1))
        self.assertEqual(frame.scalar[0, 0], source[2, 4])
        self.assertFalse(frame.valid.any())
        self.assertEqual(len(frame.surface.points), 0)
        second = model.prepare_frame(document, selection, model.Limits(), 0, model.Crop(1, 2, 0, 1))
        np.testing.assert_array_equal(second.scalar, source[:2, 1:3])
        full = model.prepare_frame(document, selection, model.Limits(), 0)
        np.testing.assert_array_equal(full.scalar, original)
        np.testing.assert_array_equal(document.array, original)

    def test_crop_rejects_invalid_source_bounds(self) -> None:
        """Reversed, negative or out-of-range bounds fail without silently wrapping."""
        document = preserve_document(model.Document(Path("matrix.npy"), np.zeros((4, 5))), "unit-inputs/test_data_model")
        selection = model.default_selection(document)
        for crop in (model.Crop(3, 2), model.Crop(-1, 2), model.Crop(0, 5),
                     model.Crop(0, 3, 3, 2), model.Crop(0, 3, -1, 2), model.Crop(0, 3, 0, 4)):
            with self.subTest(crop=crop), self.assertRaises(ValueError):
                model.prepare_frame(document, selection, model.Limits(), 0, crop)

    def test_rgb_and_alpha(self) -> None:
        """RGB composition retains color while scalar views use luminance."""
        source = np.array([[[255, 0, 0, 128], [0, 255, 0, 255]]], dtype=np.uint8)
        document = preserve_document(model.Document(Path("rgba.png"), source, is_image=True), "unit-inputs/test_data_model")
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 0)
        self.assertTrue(frame.composite)
        np.testing.assert_array_equal(frame.image, source)
        np.testing.assert_allclose(frame.scalar, [[54.213, 182.376]])


if __name__ == "__main__":
    unittest.main()
