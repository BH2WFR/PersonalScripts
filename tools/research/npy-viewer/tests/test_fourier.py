"""Numerical Fourier regression checks; manual test matrices stay untouched.

Requirements: existing viewer dependencies. Usage: unittest discovery.
All numerical inputs are small, in-memory scientific signals and grids.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np
from scipy.signal.windows import hann

from test_data_model import model

fourier = importlib.import_module("personal_npy_viewer.fourier")
coordinates = importlib.import_module("personal_npy_viewer.coordinates")
exporting = importlib.import_module("personal_npy_viewer.exporting")
workspace = importlib.import_module("personal_npy_viewer.workspace")
derivatives = importlib.import_module("personal_npy_viewer.derivatives")


class FourierTests(unittest.TestCase):
    """Check normalization, coordinate meaning, missing values and reversibility."""

    def transform(self, values: model.Array, options: fourier.TransformOptions | None = None,
                  crop: model.Crop = model.Crop(), limits: model.Limits = model.Limits()) -> model.Document:
        document = model.Document(Path("source.npy"), values)
        return fourier.run_transform(document, model.default_selection(document), crop, limits,
                                     options or fourier.TransformOptions(), "Source").document

    def inverse(self, document: model.Document, options: fourier.TransformOptions | None = None) -> model.Document:
        return fourier.run_transform(document, model.default_selection(document), model.Crop(), model.Limits(),
                                     options or fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE), "Spectrum").document

    def test_complex_roundtrip_all_normalizations_and_parities(self) -> None:
        for shape in ((7,), (8,), (5, 8), (6, 7)):
            values = np.arange(np.prod(shape)).reshape(shape) + 1j * np.cos(np.arange(np.prod(shape)).reshape(shape))
            for norm in fourier.TransformNorm:
                with self.subTest(shape=shape, norm=norm):
                    spectrum = self.transform(values, fourier.TransformOptions(norm=norm))
                    np.testing.assert_allclose(self.inverse(spectrum).array, values, atol=1e-12)
                    self.assertTrue(np.iscomplexobj(spectrum.array))

    def test_known_frequency_bins(self) -> None:
        count, interval = 80, 0.01
        values = np.exp(2j * np.pi * 12.5 * np.arange(count) * interval)
        result = self.transform(values, fourier.TransformOptions(spacing=(interval,), units=("s",)))
        frequencies = result.axes[0].values(0, count)
        self.assertAlmostEqual(frequencies[np.argmax(np.abs(result.array))], 12.5)
        self.assertEqual(result.axes[0].unit, "Hz")
        self.assertTrue(result.axes[0].frequency)
        self.assertAlmostEqual(abs(result.array).max(), count)

    def test_2d_partial_axis_and_padding(self) -> None:
        values = np.arange(35.).reshape(5, 7)
        options = fourier.TransformOptions(axes=(1,), spacing=(2., 0.25), output_shape=(5, 12))
        spectrum = self.transform(values, options)
        expected = np.fft.fftshift(np.fft.fft(values, n=12, axis=1), axes=(1,))
        np.testing.assert_allclose(spectrum.array, expected, atol=1e-12)
        self.assertFalse(spectrum.axes[0].frequency)
        self.assertTrue(spectrum.axes[1].frequency)
        inverse = self.inverse(spectrum, fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE, trim_padding=True))
        np.testing.assert_allclose(inverse.array, values, atol=1e-12)
        self.assertEqual(inverse.axes[0].spacing, 2)
        self.assertEqual(inverse.axes[1].spacing, 0.25)

    def test_crop_origin_and_slice_coordinates(self) -> None:
        values = np.arange(80.).reshape(8, 10)
        crop = model.Crop(2, 7, 3, 6)
        options = fourier.TransformOptions(range=fourier.TransformRange.CROP, spacing=(2., 0.5), units=("mm", "mm"))
        result = self.transform(values, options, crop)
        restored = self.inverse(result)
        np.testing.assert_allclose(restored.array, values[3:7, 2:8], atol=1e-12)
        self.assertEqual((restored.axes[0].origin, restored.axes[1].origin), (6., 1.))
        row = self.transform(values, fourier.TransformOptions(range=fourier.TransformRange.SLICE, row=True, index=4), crop)
        np.testing.assert_allclose(self.inverse(row).array, values[4, 2:8], atol=1e-12)
        self.assertEqual(self.inverse(row).axes[0].origin, 2)
        self.assertIn("Row 4", row.transform.description)

    def test_complex_magnitude_view_does_not_discard_phase(self) -> None:
        values = np.array([1+3j, 4-2j, -2+5j, 8+1j])
        document = model.Document(Path("complex.npy"), values.copy())
        selection = replace(model.default_selection(document), component=model.Component.MAGNITUDE)
        for component in (False, True):
            result = fourier.run_transform(document, selection, model.Crop(), model.Limits(),
                                           fourier.TransformOptions(display_component=component), "Complex")
            expected = np.abs(values) if component else values
            np.testing.assert_allclose(self.inverse(result.document).array, expected, atol=1e-12)
        np.testing.assert_array_equal(document.array, values)

    def test_external_inverse_orders(self) -> None:
        values = np.arange(9.) + 1j
        spectrum = np.fft.fft(values)
        for centered in (False, True):
            source = np.fft.fftshift(spectrum) if centered else spectrum
            result = self.transform(source, fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE,
                                      input_centered=centered, spacing=(2.,), units=("Hz",)))
            np.testing.assert_allclose(result.array, values, atol=1e-12)
            self.assertEqual(result.axes[0].unit, "s")
            self.assertAlmostEqual(result.axes[0].spacing, 1 / 18)

    def test_xy_sort_actual_coordinates(self) -> None:
        xy = np.array([[3., 8.], [1., 2.], [2., 5.], [0., 1.]])
        document = model.Document(Path("xy.csv"), xy)
        selection = model.default_selection(document, model.ViewMode.XY)
        result = fourier.run_transform(document, selection, model.Crop(), model.Limits(), fourier.TransformOptions(), "XY")
        np.testing.assert_allclose(self.inverse(result.document).array, [1, 2, 5, 8], atol=1e-12)
        np.testing.assert_array_equal(document.array, xy)
        for x in ([0, 1, 1, 2], [0, 1, 2, 4], [0, np.nan, 2, 3]):
            bad = replace(document, array=np.column_stack((x, xy[:, 1])))
            with self.assertRaises(ValueError):
                fourier.run_transform(bad, selection, model.Crop(), model.Limits(), fourier.TransformOptions(), "XY")

    def test_missing_samples_are_explicit(self) -> None:
        values = np.array([1., np.nan, 3., np.inf])
        with self.assertRaisesRegex(ValueError, "NaN/Inf"):
            self.transform(values)
        result = self.transform(values, fourier.TransformOptions(fill_zero=True))
        np.testing.assert_allclose(self.inverse(result).array, [1, 0, 3, 0], atol=1e-12)
        self.assertIn("zero-filled 2", result.transform.description)

    def test_window_mean_and_bounds_are_opt_in(self) -> None:
        values = np.arange(8.)
        limits = model.Limits(2, 5, model.FilterMode.CLAMP)
        np.testing.assert_allclose(self.inverse(self.transform(values, limits=limits)).array, values, atol=1e-12)
        options = fourier.TransformOptions(window=fourier.TransformWindow.HANN, subtract_mean=True, apply_bounds=True)
        expected = np.clip(values, 2, 5)
        expected = (expected - expected.mean()) * hann(8, sym=False)
        np.testing.assert_allclose(self.inverse(self.transform(values, options, limits=limits)).array, expected, atol=1e-12)
        with self.assertRaisesRegex(ValueError, "real display"):
            self.transform(values + 1j, options, limits=limits)

    def test_sampling_validation_precision_and_source_independence(self) -> None:
        for options in (fourier.TransformOptions(spacing=(0.,)), fourier.TransformOptions(output_shape=(3,)),
                        fourier.TransformOptions(axes=(1,)), fourier.TransformOptions(spacing=(np.inf,))):
            with self.assertRaises(ValueError):
                self.transform(np.arange(5.), options)
        source = np.arange(5., dtype=np.float32)
        result = self.transform(source, fourier.TransformOptions(single_precision=True))
        self.assertEqual(result.array.dtype, np.complex64)
        self.assertFalse(np.shares_memory(result.array, source))
        source[:] = 0
        np.testing.assert_allclose(self.inverse(result).array, np.arange(5), atol=1e-6)
        with self.assertRaisesRegex(ValueError, "round large integer"):
            self.transform(np.array([2**63 + 1], dtype=np.uint64))

    def test_frequency_frame_slice_export_and_derivative(self) -> None:
        grid_y = coordinates.AxisCoordinates(-2, 0.5, "Hz", True)
        grid_x = coordinates.AxisCoordinates(-3, 0.25, "Hz", True)
        x = grid_x.values(0, 10)
        values = np.tile((x**2).astype(np.complex128), (8, 1))
        document = model.Document(Path("spectrum.npy"), values, axes=(grid_y, grid_x))
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(), 4, model.Crop(2, 8, 1, 6))
        self.assertEqual(workspace.coordinate_bounds(frame), ((-2.5, -1.), (-1.5, 1.)))
        self.assertAlmostEqual(frame.surface.points[:, 0].min(), -2.5)
        layer = workspace.RenderLayer(1, "Spectrum", frame, "red", 1)
        series = workspace.profile_series(layer, True, -0.5)
        self.assertEqual(series.index, 3)
        np.testing.assert_allclose(series.source_x, x[2:9])
        derivative = derivatives.differentiate(series.values, series.valid, x_values=series.source_x)
        np.testing.assert_allclose(derivative.values[1:-1], 2 * x[3:8], atol=1e-12)
        snapshot = exporting.prepare_export(document, selection, frame, exporting.ExportOptions(
            target=exporting.ExportTarget.SLICE, row=True, index=3, layout=exporting.ExportLayout.XY_COLUMNS))
        np.testing.assert_allclose(snapshot.values[:, 0], x[2:9])
        cloud = exporting.prepare_export(document, selection, frame, exporting.ExportOptions(layout=exporting.ExportLayout.XYZ_COLUMNS))
        np.testing.assert_allclose(cloud.values[0], [-2.5, -1.5, 6.25])

    def test_db_floor_and_zero_spectrum(self) -> None:
        document = model.Document(Path("spectrum.npy"), np.array([1, 0.1, 0, np.nan], dtype=np.complex128))
        selection = replace(model.default_selection(document), component=model.Component.MAGNITUDE_DB, db_floor=-80)
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        np.testing.assert_allclose(frame.scalar, [0, -20, -80, np.nan], equal_nan=True)
        zero = model.prepare_frame(replace(document, array=np.zeros(4, dtype=np.complex128)), selection, model.Limits(), 0)
        np.testing.assert_array_equal(zero.scalar, [-80] * 4)

    def test_paired_inverse_rejects_cropped_frequency_axis(self) -> None:
        spectrum = self.transform(np.arange(12.))
        with self.assertRaisesRegex(ValueError, "complete frequency"):
            fourier.run_transform(spectrum, model.default_selection(spectrum), model.Crop(1, 10), model.Limits(),
                                   fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE,
                                     range=fourier.TransformRange.CROP), "Spectrum")


if __name__ == "__main__":
    unittest.main()
