"""Verify export layouts, independent processing and lossless file round trips.

Requirements: viewer dependencies. Usage: unittest discovery. All data files
are written under the Git-ignored tmp/matrix-viewer-tests directory.
"""

from dataclasses import replace
from io import BytesIO
import importlib
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
from scipy.io import loadmat

from fixture_store import fixture_directory, preserve_document
from test_array_export import model

exports = importlib.import_module("personal_matrix_viewer.exporting")


class ExportFormatTests(unittest.TestCase):
    """Check saved values against independent expectations and original sources."""

    def setUp(self) -> None:
        """Keep generated inputs/outputs in the project's ignored fixture tree."""
        self.folder = fixture_directory(f"unit-files/export-formats/{self._testMethodName}")
        self.source = np.arange(20, dtype=np.int16).reshape(4, 5)
        self.doc = preserve_document(model.Document(Path("source.npy"), self.source), "unit-inputs/test_export_formats")
        self.selection = model.default_selection(self.doc)
        self.frame = model.prepare_frame(self.doc, self.selection,
                                        model.Limits(7, 12, model.FilterMode.CLAMP), 2, model.Crop(1, 3, 1, 2))

    def test_independent_xy_and_z_processing(self) -> None:
        """All four combinations preserve the requested shape and numeric values."""
        for crop in (False, True):
            for bounds in (False, True):
                options = exports.ExportOptions(crop_xy=crop, bound_values=bounds)
                snapshot = exports.prepare_export(self.doc, self.selection, self.frame, options)
                expected = self.source[1:3, 1:4] if crop else self.source
                if bounds:
                    expected = np.clip(expected, 7, 12)
                np.testing.assert_array_equal(snapshot.values, expected)
                self.assertEqual(snapshot.values.dtype, np.int16)
                (self.folder / f"{snapshot.stem}.npy").write_bytes(exports.serialize_array(snapshot.values, exports.ExportFormat.NPY))

    def test_matrix_cloud_uses_absolute_indices_and_omits_gaps(self) -> None:
        """Cropped XYZ records refer to original coordinates, independent of mesh sampling."""
        frame = model.prepare_frame(self.doc, self.selection, model.Limits(7, 12), 2, model.Crop(1, 3, 1, 2))
        options = exports.ExportOptions(layout=exports.ExportLayout.XYZ_COLUMNS)
        result = exports.prepare_export(self.doc, self.selection, frame, options)
        np.testing.assert_array_equal(result.values, [[2, 1, 7], [3, 1, 8], [1, 2, 11], [2, 2, 12]])
        transposed = exports.prepare_export(self.doc, self.selection, frame,
                                            replace(options, layout=exports.ExportLayout.XYZ_ROWS))
        np.testing.assert_array_equal(transposed.values, result.values.T)

    def test_signal_and_slice_xy_coordinates(self) -> None:
        """Signal and column slices keep the correct absolute source index axis."""
        doc = preserve_document(model.Document(Path("signal.npy"), np.arange(8, dtype=np.float32)), "unit-inputs/test_export_formats")
        selection = model.default_selection(doc)
        frame = model.prepare_frame(doc, selection, model.Limits(), 2, model.Crop(3, 6))
        options = exports.ExportOptions(layout=exports.ExportLayout.XY_ROWS)
        result = exports.prepare_export(doc, selection, frame, options)
        np.testing.assert_array_equal(result.values, [[3, 4, 5, 6], [3, 4, 5, 6]])
        result = exports.prepare_export(self.doc, self.selection, self.frame,
                                        exports.ExportOptions(target=exports.ExportTarget.SLICE,
                                                              layout=exports.ExportLayout.XY_COLUMNS,
                                                              row=False, index=2, bound_values=False))
        np.testing.assert_array_equal(result.values, [[1, 7], [2, 12]])

    def test_xy_keeps_unsorted_duplicate_x_and_swapped_coordinates(self) -> None:
        """Export retains record order and physical X, even for repeated X values."""
        doc = preserve_document(model.Document(Path("xy.csv"), np.array([[5, 2], [1, 2], [4, 0]])), "unit-inputs/test_export_formats")
        selection = replace(model.default_selection(doc, model.ViewMode.XY), coordinate_order=(1, 0))
        frame = model.prepare_frame(doc, selection, model.Limits(), 2)
        result = exports.prepare_export(doc, selection, frame, exports.ExportOptions(layout=exports.ExportLayout.XY_ROWS))
        np.testing.assert_array_equal(result.values, [[2, 2, 0], [5, 1, 4]])

    def test_original_complex_and_split_text_roundtrip(self) -> None:
        """Original data ignores view settings; both text components remain exact."""
        source = np.array([[1 + 2j, -3 - 4j], [5 + 6j, 7 - 8j]], dtype=np.complex128)
        doc = preserve_document(model.Document(Path("complex.npy"), source, key="wave"), "unit-inputs/test_export_formats")
        selection = replace(model.default_selection(doc), component=model.Component.MAGNITUDE)
        frame = model.prepare_frame(doc, selection, model.Limits(2, 3), 2, model.Crop(1, 1, 0, 1))
        result = exports.prepare_export(doc, selection, frame, exports.ExportOptions(target=exports.ExportTarget.ORIGINAL))
        np.testing.assert_array_equal(result.values, source)
        self.assertIn("wave_original", result.stem)
        for format_ in (exports.ExportFormat.CSV, exports.ExportFormat.TXT):
            paths = exports.output_paths(self.folder / f"complex.{format_.value}", result.values, format_)
            self.assertEqual([path.stem for path in paths], ["complex_real", "complex_imag"])
            for path, values in zip(paths, (result.values.real, result.values.imag), strict=True):
                path.write_bytes(exports.serialize_array(values, format_))
            recovered = model.load_document(paths[0]).array + 1j * model.load_document(paths[1]).array
            np.testing.assert_array_equal(recovered, source)
        with self.assertRaisesRegex(ValueError, "split complex"):
            exports.serialize_array(source, exports.ExportFormat.CSV)

    def test_complex_crop_and_slice_retain_both_components(self) -> None:
        """Complex crop-only exports preserve imaginary data regardless of display mode."""
        doc = preserve_document(model.Document(Path("complex.npy"), self.source + 1j * self.source), "unit-inputs/test_export_formats")
        selection = replace(model.default_selection(doc), component=model.Component.PHASE)
        frame = model.prepare_frame(doc, selection, model.Limits(1, 2), 2, model.Crop(1, 3, 1, 2))
        options = exports.ExportOptions(bound_values=False, preserve_complex=True)
        snapshot = exports.prepare_export(doc, selection, frame, options)
        np.testing.assert_array_equal(snapshot.values, doc.array[1:3, 1:4])
        snapshot = exports.prepare_export(doc, selection, frame, replace(options, target=exports.ExportTarget.SLICE, index=2))
        np.testing.assert_array_equal(snapshot.values, doc.array[2, 1:4])
        with self.assertRaisesRegex(ValueError, "ordered Z"):
            exports.prepare_export(doc, selection, frame, replace(options, bound_values=True))

    def test_binary_roundtrip_real_complex_logical_and_vectors(self) -> None:
        """NPY keeps exact dtype/shape; MAT preserves values and stores column vectors."""
        samples = (self.source, self.source.astype(np.complex64) * (1 + 2j), self.source > 10,
                   np.array([1.0, 1.0000000000000002, -2.5]), np.array([2**63 + 1], dtype=np.uint64))
        for index, source in enumerate(samples):
            for format_ in (exports.ExportFormat.NPY, exports.ExportFormat.MAT):
                path = self.folder / f"sample-{index}.{format_.value}"
                path.write_bytes(exports.serialize_array(source, format_))
                recovered = model.load_document(path).array
                expected = source[:, None] if source.ndim == 1 and format_ == exports.ExportFormat.MAT else source
                np.testing.assert_array_equal(recovered, expected)
                self.assertEqual(recovered.dtype, source.dtype)
                if format_ == exports.ExportFormat.MAT:
                    self.assertIn("matrix", loadmat(path))

    def test_text_precision_and_uint64_are_not_plot_rounded(self) -> None:
        """Text round trips retain float samples and integers above float64 precision."""
        samples = (np.array([2**63 + 1, 2**64 - 1], dtype=np.uint64),
                   np.array([1.2345678901234567, np.nextafter(1.0, 2.0), np.nan, np.inf]),
                   np.array([1.2345678, 1.0000001], dtype=np.float32))
        for index, source in enumerate(samples):
            for format_ in (exports.ExportFormat.CSV, exports.ExportFormat.TXT):
                path = self.folder / f"precision-{index}.{format_.value}"
                path.write_bytes(exports.serialize_array(source, format_))
                recovered = model.load_document(path).array.ravel().astype(source.dtype)
                np.testing.assert_array_equal(recovered, source)

    def test_invalid_and_empty_cloud_exports(self) -> None:
        """Reject incompatible layouts and exports containing no finite points."""
        with self.assertRaisesRegex(ValueError, "one-dimensional"):
            exports.prepare_export(self.doc, self.selection, self.frame,
                                   exports.ExportOptions(layout=exports.ExportLayout.XY_COLUMNS))
        frame = model.prepare_frame(self.doc, self.selection, model.Limits(99, 100), 2)
        with self.assertRaisesRegex(ValueError, "No finite points"):
            exports.prepare_export(self.doc, self.selection, frame,
                                   exports.ExportOptions(layout=exports.ExportLayout.XYZ_ROWS))
        with self.assertRaisesRegex(ValueError, "1D/2D"):
            exports.serialize_array(np.zeros((2, 3, 4)), exports.ExportFormat.TXT)

    def test_uint64_coordinates_do_not_lose_bits(self) -> None:
        """Nonnegative source indices can share an exact uint64 table with large Z."""
        doc = preserve_document(model.Document(Path("large.npy"), np.full((2, 2), 2**63 + 1, dtype=np.uint64)), "unit-inputs/test_export_formats")
        selection = model.default_selection(doc)
        frame = model.prepare_frame(doc, selection, model.Limits(), 2)
        result = exports.prepare_export(doc, selection, frame, exports.ExportOptions(layout=exports.ExportLayout.XYZ_COLUMNS))
        self.assertEqual(result.values.dtype, np.uint64)
        np.testing.assert_array_equal(result.values[:, 2], doc.array.ravel())

    def test_point_view_exports_all_records_without_display_sampling(self) -> None:
        """Point-view caps affect only Z; physical coordinates remain unchanged."""
        source = np.array([[10, 20, -1], [11, 21, 2], [12, 22, 9], [13, 23, 4]], dtype=np.int32)
        doc = preserve_document(model.Document(Path("points.npy"), source), "unit-inputs/test_export_formats")
        selection = model.default_selection(doc, model.ViewMode.POINTS)
        frame = model.prepare_frame(doc, selection, model.Limits(0, 5, model.FilterMode.CLAMP), 2, max_points=1)
        result = exports.prepare_export(doc, selection, frame, exports.ExportOptions(layout=exports.ExportLayout.XYZ_ROWS))
        np.testing.assert_array_equal(result.values, [[10, 11, 12, 13], [20, 21, 22, 23], [0, 2, 5, 4]])

    def test_snapshot_never_shares_mutable_source_storage(self) -> None:
        """No later mutation of source data changes an already prepared export."""
        options = exports.ExportOptions(target=exports.ExportTarget.SLICE, index=1, bound_values=False)
        snapshot = exports.prepare_export(self.doc, self.selection, self.frame, options)
        expected = self.source[1, 1:4].copy()
        self.assertFalse(np.shares_memory(snapshot.values, self.source))
        self.source.fill(-100)
        np.testing.assert_array_equal(snapshot.values, expected)

    def test_grayscale_image_roundtrip_and_orientation(self) -> None:
        """Both codecs preserve one cell per pixel and finite min/max scaling."""
        source = np.array([[-10., 0., 10.], [np.nan, np.inf, -np.inf]])
        expected = np.array([[0, 128, 255], [0, 0, 0]], dtype=np.uint8)
        for format_ in (exports.ExportFormat.PNG, exports.ExportFormat.BMP):
            payload = exports.serialize_array(source, format_)
            (self.folder / f"normalized.{format_.value}").write_bytes(payload)
            with Image.open(BytesIO(payload)) as image:
                self.assertEqual(image.mode, "L")
                self.assertEqual(image.size, (3, 2))
                np.testing.assert_array_equal(np.asarray(image), expected)
        self.assertTrue(np.isnan(source[1, 0]))
        self.assertEqual(source[0, 0], -10)

    def test_grayscale_extremes_constants_and_rejections(self) -> None:
        """Extreme floats and nearby uint64 values do not overflow or collapse."""
        maximum = np.finfo(np.float64).max
        samples = (
            (np.array([[-maximum, 0, maximum]]), [[0, 128, 255]]),
            (np.array([[2**64 - 3, 2**64 - 2, 2**64 - 1]], dtype=np.uint64), [[0, 128, 255]]),
            (np.array([[-2**63, 0, 2**63 - 1]], dtype=np.int64), [[0, 128, 255]]),
            (np.full((2, 3), 255), np.zeros((2, 3), dtype=np.uint8)),
            (np.array([[False, True]]), [[0, 255]]),
        )
        for source, expected in samples:
            with np.errstate(all="raise"):
                np.testing.assert_array_equal(exports.normalized_grayscale(source), expected)
        for source in (np.array([1, 2]), np.ones((2, 2), dtype=complex),
                       np.zeros((2, 2, 3)), np.empty((0, 2)), np.full((2, 2), np.nan)):
            with self.assertRaises(ValueError):
                exports.serialize_array(source, exports.ExportFormat.PNG)

    def test_image_matrix_keeps_all_channels_and_channel_export_is_scalar(self) -> None:
        """RGBA original/result exports retain channels even with R active."""
        source = np.arange(80, dtype=np.uint8).reshape(4, 5, 4)
        path = self.folder / "rgba.png"
        Image.fromarray(source).save(path)
        document = model.load_document(path, "R")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(25, 45, model.FilterMode.CLAMP),
                                    2, model.Crop(1, 3, 1, 2))
        options = exports.ExportOptions(preserve_channels=True)
        result = exports.prepare_export(document, selection, frame, options)
        np.testing.assert_array_equal(result.values, np.clip(source[1:3, 1:4], 25, 45))
        self.assertIn("all-channels", result.stem)
        original = exports.prepare_export(document, selection, frame,
                                          replace(options, target=exports.ExportTarget.ORIGINAL))
        np.testing.assert_array_equal(original.values, source)
        channel = exports.prepare_export(document, selection, frame, replace(options, preserve_channels=False))
        np.testing.assert_array_equal(channel.values, np.clip(source[1:3, 1:4, 0], 25, 45))
        assert document.image_source is not None
        self.assertFalse(np.shares_memory(result.values, document.image_source.pixels))

    def test_whole_numeric_channels_follow_sample_axis(self) -> None:
        """Whole-source signal cropping keeps all channels in their original axes."""
        document = model.Document(Path("channels.npy"), self.source)
        selection = model.default_selection(document, model.ViewMode.SIGNAL, channel_axis=1)
        frame = model.prepare_frame(document, selection, model.Limits(), 2, model.Crop(1, 2))
        snapshot = exports.prepare_export(document, selection, frame,
                                          exports.ExportOptions(preserve_channels=True, bound_values=False))
        np.testing.assert_array_equal(snapshot.values, self.source[1:3, :])


if __name__ == "__main__":
    unittest.main()
