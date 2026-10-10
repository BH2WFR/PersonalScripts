"""Check independent slice buffers and physical/aligned coordinate semantics.

Requirements: viewer dependencies. Usage: unittest discovery.
All inputs stay in memory; no manual test matrices are created.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np

from test_data_model import model

snapshot = importlib.import_module("personal_npy_viewer.slice_snapshot")
coordinates = importlib.import_module("personal_npy_viewer.coordinates")


class SliceSnapshotTests(unittest.TestCase):
    """Snapshots retain sampling and original values independently of their source."""

    def test_rows_columns_crop_alignment_and_frequency_units(self) -> None:
        values = np.arange(48, dtype=np.uint64).reshape(6, 8) + 2**60
        grids = (coordinates.AxisCoordinates(-3, .5, "mm"),
                 coordinates.AxisCoordinates(-4, .25, "Hz", True))
        document = model.Document(Path("source.npy"), values, axes=grids)
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(),
                                    2, model.Crop(2, 6, 1, 4))
        alignment = coordinates.AxisMap(3, 10)
        for row, index, trace, start, axis in ((True, 2, frame.scalar[1, :], 2, 1),
                                               (False, 3, frame.scalar[:, 1], 1, 0)):
            result = snapshot.freeze_slice(document, frame, trace, row=row, index=index,
                                           name="source / Value", alignment=alignment)
            np.testing.assert_array_equal(result.array, trace)
            self.assertEqual(result.array.dtype, values.dtype)
            self.assertFalse(np.shares_memory(result.array, values))
            np.testing.assert_allclose(result.axes[0].values(0, len(trace)),
                                       alignment.array(grids[axis].values(start, len(trace))))
            self.assertEqual(result.axes[0].unit, grids[axis].unit)
            self.assertEqual(result.axes[0].frequency, grids[axis].frequency)
            self.assertIn("No file was saved", result.import_provenance)

    def test_bounds_and_nonfinite_are_retained_independently(self) -> None:
        values = np.array([[0., 3, 8, np.nan, np.inf], [4, 5, 6, 7, 8]])
        document = model.Document(Path("source.npy"), values)
        limits = model.Limits(1, 6, model.FilterMode.CLAMP)
        frame = model.prepare_frame(document, model.default_selection(document), limits, 2)
        result = snapshot.freeze_slice(document, frame, frame.scalar[0], row=True, index=0, name="Row 0")
        restored = model.prepare_frame(result, model.default_selection(result), limits, 0)
        np.testing.assert_array_equal(restored.scalar, frame.scalar[0])
        np.testing.assert_array_equal(restored.display_scalar, frame.display_scalar[0])
        np.testing.assert_array_equal(restored.valid, frame.valid[0])
        np.testing.assert_array_equal(restored.clip_kind, frame.clip_kind[0])
        values[:] = 99
        np.testing.assert_array_equal(result.array, [0, 3, 8, np.nan, np.inf])

    def test_complex_source_freezes_displayed_scalar_channel(self) -> None:
        values = np.arange(20.).reshape(4, 5) * (1 + 2j)
        document = model.Document(Path("source.npy"), values)
        selection = replace(model.default_selection(document), component=model.Component.MAGNITUDE)
        frame = model.prepare_frame(document, selection, model.Limits(), 2)
        result = snapshot.freeze_slice(document, frame, frame.scalar[2], row=True, index=2, name="Magnitude")
        self.assertFalse(result.is_complex)
        np.testing.assert_allclose(result.array, np.abs(values[2]))
        self.assertIsNone(result.transform)
        self.assertIsNone(result.laplace)

    def test_complex_rows_and_columns_preserve_both_parts_without_bounds(self) -> None:
        values = (np.arange(48).reshape(6, 8) * (1 + 2j)).astype(np.complex64)
        values[2, 3] = complex(np.inf, -7)
        document = model.Document(Path("source.npy"), values)
        selection = replace(model.default_selection(document), component=model.Component.IMAGINARY)
        frame = model.prepare_frame(document, selection, model.Limits(20, 30, model.FilterMode.CLAMP),
                                    2, model.Crop(2, 6, 1, 4))
        for row, index, trace, expected in ((True, 2, frame.scalar[1], values[2, 2:7]),
                                            (False, 3, frame.scalar[:, 1], values[1:5, 3])):
            with self.subTest(row=row):
                result = snapshot.freeze_slice(document, frame, trace, row=row, index=index,
                                               name="Complex", preserve_complex=True)
                self.assertTrue(result.is_complex)
                self.assertEqual(result.array.dtype, np.complex64)
                self.assertEqual(result.array.ndim, 1)
                np.testing.assert_array_equal(result.array, expected)
                self.assertFalse(np.shares_memory(result.array, values))
                self.assertIn("ignored for complex data", result.import_provenance)
                self.assertIsNone(result.transform)
                self.assertIsNone(result.laplace)

    def test_complex_copy_requires_raw_data_and_keeps_zero_imaginary_dtype(self) -> None:
        document = model.Document(Path("source.npy"), np.arange(20).reshape(4, 5).astype(np.complex128))
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 2)
        result = snapshot.freeze_slice(document, frame, frame.scalar[0], row=True, index=0,
                                       name="Complex", preserve_complex=True)
        self.assertTrue(result.is_complex)
        np.testing.assert_array_equal(result.array, document.array[0])
        with self.assertRaisesRegex(ValueError, "complex values"):
            snapshot.freeze_slice(document, replace(frame, raw=None), frame.scalar[0], row=True,
                                   index=0, name="Missing", preserve_complex=True)

    def test_rejects_stale_or_invalid_slice_coordinates(self) -> None:
        document = model.Document(Path("source.npy"), np.arange(20.).reshape(4, 5))
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 2, model.Crop(1, 4, 1, 3))
        for index, trace, mapping in ((0, frame.scalar[0], coordinates.AxisMap()),
                                      (1, frame.scalar[0, :2], coordinates.AxisMap()),
                                      (1, frame.scalar[0], coordinates.AxisMap(0, 0))):
            with self.assertRaises(ValueError):
                snapshot.freeze_slice(document, frame, trace, row=True, index=index, name="bad", alignment=mapping)


if __name__ == "__main__":
    unittest.main()
