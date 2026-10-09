"""Check pointwise arithmetic, coordinates and immutable full-resolution output.

Requirements: existing viewer dependencies. Usage: unittest discovery. Test
arrays live in memory; the manual test-matrixes directory is never modified.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np

from test_data_model import model

conversion = importlib.import_module("personal_npy_viewer.data_conversion")
coordinates = importlib.import_module("personal_npy_viewer.coordinates")
exporting = importlib.import_module("personal_npy_viewer.exporting")
fourier = importlib.import_module("personal_npy_viewer.fourier")


class DataConversionTests(unittest.TestCase):
    """Verify mathematical conventions and preservation of source identity."""

    def test_db_amplitude_and_power_are_distinct(self) -> None:
        values = np.array([-10., 0, 0.1, 1, 10, np.nan, np.inf])
        original = values.copy()
        options = conversion.ConversionOptions(reference_mode=conversion.DBReference.FIXED)
        actual, _ = conversion.convert_values(values, options)
        np.testing.assert_allclose(actual, [20, -120, -20, 0, 20, np.nan, np.nan], equal_nan=True)
        power, _ = conversion.convert_values(values, replace(options, operation=conversion.Conversion.POWER_DB))
        np.testing.assert_allclose(power, [np.nan, -120, -10, 0, 10, np.nan, np.nan], equal_nan=True)
        peak, _ = conversion.convert_values(np.array([0., 0.1, 1, 10]), replace(options, reference_mode=conversion.DBReference.PEAK))
        np.testing.assert_allclose(peak, [-120, -40, -20, 0])
        np.testing.assert_array_equal(values, original)
        self.assertFalse(np.shares_memory(actual, values))

    def test_db_floor_and_extreme_ratios(self) -> None:
        options = conversion.ConversionOptions(reference_mode=conversion.DBReference.FIXED, reference=1e300,
                                               db_floor=None)
        actual, _ = conversion.convert_values(np.array([1e-300, 1e300, 0]), options)
        np.testing.assert_allclose(actual[:2], [-12000, 0])
        self.assertTrue(np.isneginf(actual[2]))
        zeros, _ = conversion.convert_values(np.zeros(4), conversion.ConversionOptions())
        np.testing.assert_array_equal(zeros, np.full(4, -120.))
        with self.assertRaisesRegex(ValueError, "no finite"):
            conversion.convert_values(np.zeros(4), replace(options, reference=1))
        for bad in (0, -1, np.inf, np.nan):
            with self.assertRaisesRegex(ValueError, "reference"):
                conversion.convert_values(np.ones(3), replace(options, reference=bad))

    def test_angles_logs_magnitude_and_affine(self) -> None:
        angles = np.array([-180., 0, 90, 360])
        options = conversion.ConversionOptions(operation=conversion.Conversion.DEG2RAD)
        rad, _ = conversion.convert_values(angles, options)
        np.testing.assert_allclose(rad, [-np.pi, 0, np.pi / 2, 2 * np.pi])
        deg, _ = conversion.convert_values(rad, replace(options, operation=conversion.Conversion.RAD2DEG))
        np.testing.assert_allclose(deg, angles)
        for operation, expected in ((conversion.Conversion.LOG10, 1), (conversion.Conversion.LN, np.log(10))):
            result, _ = conversion.convert_values(np.array([-1., 0, 1, 10]), replace(options, operation=operation))
            np.testing.assert_allclose(result, [np.nan, np.nan, 0, expected], equal_nan=True)
        z = np.array([3 + 4j, -5 + 12j])
        result, _ = conversion.convert_values(z, replace(options, operation=conversion.Conversion.ABSOLUTE))
        np.testing.assert_array_equal(result, [5, 13])
        affine, _ = conversion.convert_values(z, replace(options, operation=conversion.Conversion.AFFINE, gain=2, offset=3))
        np.testing.assert_array_equal(affine, [9 + 8j, -7 + 24j])
        with self.assertRaisesRegex(ValueError, "real channel"):
            conversion.convert_values(z, options)
        # Converting to floating point before abs prevents signed-integer overflow.
        result, _ = conversion.convert_values(np.array([-128], dtype=np.int8), replace(options, operation=conversion.Conversion.ABSOLUTE))
        np.testing.assert_array_equal(result, [128])

    def test_crop_bounds_slice_and_physical_axes(self) -> None:
        source = np.arange(30.).reshape(5, 6) - 5
        doc = model.Document(Path("matrix.npy"), source,
                             axes=(coordinates.AxisCoordinates(20, 2, "mm"), coordinates.AxisCoordinates(-10, 0.5, "mm")))
        selection = model.default_selection(doc)
        crop = model.Crop(1, 4, 1, 3)
        limits = model.Limits(5, 10, model.FilterMode.CLAMP)
        options = conversion.ConversionOptions(operation=conversion.Conversion.AFFINE, range=fourier.TransformRange.CROP,
                                               apply_bounds=True, gain=2, offset=1)
        result = conversion.run_conversion(doc, selection, crop, limits, options, "source")
        expected = np.clip(source[1:4, 1:5], 5, 10) * 2 + 1
        np.testing.assert_array_equal(result.document.array, expected)
        self.assertEqual(tuple(axis.origin for axis in result.document.axes), (22, -9.5))
        self.assertEqual(tuple(axis.spacing for axis in result.document.axes), (2, 0.5))
        self.assertFalse(np.shares_memory(source, result.document.array))
        sliced = conversion.run_conversion(doc, selection, crop, limits,
            replace(options, range=fourier.TransformRange.SLICE, row=False, index=2), "source", "Column result")
        np.testing.assert_array_equal(sliced.document.array, expected[:, 1])
        self.assertEqual(sliced.selection.mode, model.ViewMode.SIGNAL)
        self.assertEqual(sliced.document.axes[0], result.document.axes[0])
        self.assertIn("Column 2", sliced.document.conversion_provenance)
        self.assertEqual(sliced.name, "Column result")
        full = conversion.run_conversion(doc, selection, crop, limits, replace(options, range=fourier.TransformRange.FULL, apply_bounds=False), "source")
        np.testing.assert_array_equal(full.document.array, source * 2 + 1)
        np.testing.assert_array_equal(doc.array, source)

    def test_xy_preserves_duplicates_order_and_axis_swap(self) -> None:
        source = np.array([[4., 180], [1, 90], [1, -180], [-2, 360]])
        for values in (source, source.T):
            doc = model.Document(Path("xy.csv"), values)
            selection = model.default_selection(doc, model.ViewMode.XY)
            options = conversion.ConversionOptions(operation=conversion.Conversion.DEG2RAD)
            result = conversion.run_conversion(doc, selection, model.Crop(), model.Limits(), options, "XY")
            self.assertEqual(result.selection.mode, model.ViewMode.XY)
            np.testing.assert_array_equal(result.document.array[:, 0], source[:, 0])
            np.testing.assert_allclose(result.document.array[:, 1], np.deg2rad(source[:, 1]))
            swapped = conversion.run_conversion(doc, replace(selection, coordinate_order=(1, 0)), model.Crop(), model.Limits(), options, "YX")
            np.testing.assert_array_equal(swapped.document.array[:, 0], source[:, 1])
            np.testing.assert_allclose(swapped.document.array[:, 1], np.deg2rad(source[:, 0]))

    def test_points_convert_z_only(self) -> None:
        source = np.array([[1., 2, -3], [4, 5, -6], [7, 8, 9], [2, 3, 4]])
        doc = model.Document(Path("cloud.npy"), source)
        result = conversion.run_conversion(doc, model.default_selection(doc, model.ViewMode.POINTS), model.Crop(), model.Limits(),
                                           conversion.ConversionOptions(operation=conversion.Conversion.ABSOLUTE), "cloud")
        self.assertEqual(result.selection.mode, model.ViewMode.POINTS)
        np.testing.assert_array_equal(result.document.array[:, :2], source[:, :2])
        np.testing.assert_array_equal(result.document.array[:, 2], np.abs(source[:, 2]))

    def test_complex_components_and_result_export(self) -> None:
        doc = model.Document(Path("complex.npy"), np.array([1j, 10j, 100j]))
        selection = replace(model.default_selection(doc), component=model.Component.IMAGINARY)
        options = conversion.ConversionOptions(full_complex=True)
        result = conversion.run_conversion(doc, selection, model.Crop(), model.Limits(), options, "Imaginary")
        np.testing.assert_allclose(result.document.array, [-40, -20, 0])
        self.assertFalse(result.document.is_complex)
        self.assertIsNone(result.document.transform)
        with self.assertRaisesRegex(ValueError, "complex samples"):
            conversion.run_conversion(doc, selection, model.Crop(), model.Limits(), replace(options, apply_bounds=True), "source")
        result = conversion.run_conversion(doc, selection, model.Crop(), model.Limits(),
            replace(options, operation=conversion.Conversion.AFFINE, gain=2, offset=1), "source")
        self.assertTrue(result.document.is_complex)
        frame = model.prepare_frame(result.document, result.selection, model.Limits(), 2)
        exported = exporting.prepare_export(result.document, result.selection, frame,
            exporting.ExportOptions(preserve_complex=True, bound_values=False))
        np.testing.assert_array_equal(exported.values, [1 + 2j, 1 + 20j, 1 + 200j])

    def test_image_composite_uses_grayscale(self) -> None:
        pixels = np.zeros((4, 5, 3), dtype=np.uint8)
        pixels[..., 0] = 255
        doc = model.Document(Path("rgb.png"), pixels, is_image=True)
        result = conversion.run_conversion(doc, model.default_selection(doc), model.Crop(), model.Limits(),
            conversion.ConversionOptions(operation=conversion.Conversion.AFFINE, gain=2), "RGB color")
        self.assertEqual(result.document.array.shape, (4, 5))
        self.assertFalse(result.document.is_image)
        np.testing.assert_allclose(result.document.array, np.full((4, 5), 255 * 0.2126 * 2))


if __name__ == "__main__":
    unittest.main()
