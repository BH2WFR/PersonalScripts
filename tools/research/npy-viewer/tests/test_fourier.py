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
special = importlib.import_module("personal_npy_viewer.fourier_values")
conversion = importlib.import_module("personal_npy_viewer.data_conversion")
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

    def test_full_slices_preserve_entire_axis_despite_current_crop(self) -> None:
        """Full slices use source indices, including rows/columns outside crop."""
        values = np.arange(80.).reshape(8, 10)
        original = values.copy()
        crop = model.Crop(2, 7, 3, 6)
        limits = model.Limits(24, 45, model.FilterMode.CLAMP)
        for row, index in ((True, 0), (False, 9)):
            with self.subTest(row=row):
                options = fourier.TransformOptions(range=fourier.TransformRange.FULL_SLICE, row=row, index=index)
                spectrum = self.transform(values, options, crop, limits)
                expected = values[index, :] if row else values[:, index]
                np.testing.assert_allclose(spectrum.array, np.fft.fftshift(np.fft.fft(expected)), atol=1e-12)
                restored = self.inverse(spectrum)
                np.testing.assert_allclose(restored.array, expected, atol=1e-12)
                self.assertEqual(restored.axes[0].origin, 0)
                self.assertIn("Slice:", spectrum.transform.description)
                self.assertIn("Full input", spectrum.transform.description)
        np.testing.assert_array_equal(values, original)

    def test_cropped_matrix_and_slices_apply_value_bounds_without_resampling(self) -> None:
        """FFT defaults to boundary values in both viewer modes, retaining the grid."""
        values = np.arange(80.).reshape(8, 10)
        original = values.copy()
        crop = model.Crop(2, 7, 3, 6)
        for scope, row, index, source in (
            (fourier.TransformRange.CROP, True, 0, values[3:7, 2:8]),
            (fourier.TransformRange.SLICE, True, 4, values[4, 2:8]),
            (fourier.TransformRange.SLICE, False, 3, values[3:7, 3]),
        ):
            for mode in (model.FilterMode.CLAMP, model.FilterMode.HIDE):
                with self.subTest(scope=scope, row=row, mode=mode):
                    limits = model.Limits(43, 45, mode)
                    options = fourier.TransformOptions(range=scope, row=row, index=index, apply_bounds=True)
                    expected = np.clip(source, 43, 45)
                    spectrum = self.transform(values, options, crop, limits)
                    np.testing.assert_allclose(spectrum.array, np.fft.fftshift(np.fft.fftn(expected)), atol=1e-12)
                    np.testing.assert_allclose(self.inverse(spectrum).array, expected, atol=1e-12)
                    self.assertEqual(spectrum.array.shape, source.shape)
                    self.assertIn("value bounds", spectrum.transform.description)
        np.testing.assert_array_equal(values, original)

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

    def test_missing_samples_default_to_zero_and_record_counts(self) -> None:
        values = np.array([1., np.nan, 3., np.inf])
        result = self.transform(values)
        np.testing.assert_allclose(self.inverse(result).array, [1, 0, 3, 0], atol=1e-12)
        self.assertIn("NaN: 1 -> 0", result.transform.description)
        self.assertIn("+Inf: 1 -> 0", result.transform.description)

    def test_window_mean_and_bounds_are_opt_in(self) -> None:
        values = np.arange(8.)
        limits = model.Limits(2, 5, model.FilterMode.CLAMP)
        np.testing.assert_allclose(self.inverse(self.transform(values, limits=limits)).array, values, atol=1e-12)
        options = fourier.TransformOptions(window=fourier.TransformWindow.HANN, subtract_mean=True, apply_bounds=True)
        expected = np.clip(values, 2, 5)
        expected = (expected - expected.mean()) * hann(8, sym=False)
        np.testing.assert_allclose(self.inverse(self.transform(values, options, limits=limits)).array, expected, atol=1e-12)
        complex_values = values + 1j
        expected_complex = (complex_values - complex_values.mean()) * hann(8, sym=False)
        np.testing.assert_allclose(self.inverse(self.transform(complex_values, options, limits=limits)).array,
                                   expected_complex, atol=1e-12)

    def test_independent_special_values_and_pre_replacement_extrema(self) -> None:
        source = np.array([-1., .5, 2., 3.5, 5., np.nan, np.inf, -np.inf])
        original = source.copy()
        method = special.ValueReplacement
        policy = special.FourierValuePolicy(nan=method.MAXIMUM, positive=method.MINIMUM)
        for mode in model.FilterMode:
            options = fourier.TransformOptions(apply_bounds=True, value_policy=policy)
            spectrum = self.transform(source, options, limits=model.Limits(0, 4, mode))
            expected = [0, .5, 2, 3.5, 4, 3.5, .5, 0]
            np.testing.assert_allclose(self.inverse(spectrum).array, expected, atol=1e-12)
            self.assertIn("outside bounds: 2 -> Clamp to bounds", spectrum.transform.description)
        for replacement, value in ((method.ZERO, 0), (method.MINIMUM, .5), (method.MAXIMUM, 3.5)):
            options = fourier.TransformOptions(apply_bounds=True, value_policy=replace(policy, clipped=replacement))
            spectrum = self.transform(source, options, limits=model.Limits(0, 4))
            np.testing.assert_allclose(self.inverse(spectrum).array,
                                       [value, .5, 2, 3.5, value, 3.5, .5, 0], atol=1e-12)
        np.testing.assert_array_equal(source, original)

    def test_extrema_require_valid_samples_only_when_replacements_needed(self) -> None:
        method = special.ValueReplacement
        policy = special.FourierValuePolicy(nan=method.MAXIMUM, clipped=method.MINIMUM)
        with self.assertRaisesRegex(ValueError, "No finite, in-bound"):
            self.transform(np.array([np.nan, np.inf]), fourier.TransformOptions(value_policy=policy))
        with self.assertRaisesRegex(ValueError, "No finite, in-bound"):
            self.transform(np.array([9., 10.]), fourier.TransformOptions(apply_bounds=True, value_policy=policy),
                           limits=model.Limits(0, 1))
        np.testing.assert_allclose(self.inverse(self.transform(np.array([np.nan, np.inf, -np.inf]))).array, 0)
        np.testing.assert_allclose(self.inverse(self.transform(np.array([9., 10.]),
                                   fourier.TransformOptions(value_policy=policy))).array, [9, 10])
        clamped = self.transform(np.array([9., 10.]), fourier.TransformOptions(apply_bounds=True), limits=model.Limits(0, 1))
        np.testing.assert_allclose(self.inverse(clamped).array, 1)

    def test_full_complex_replaces_whole_invalid_sample_and_ignores_z(self) -> None:
        source = np.array([complex(1, 2), complex(np.nan, 3), complex(4, np.inf),
                           complex(-np.inf, 5), 0j, complex(6, -7)])
        original = source.copy()
        options = fourier.TransformOptions(apply_bounds=True, value_policy=special.FourierValuePolicy(
            nan=special.ValueReplacement.MAXIMUM, positive=special.ValueReplacement.MINIMUM))
        spectrum = self.transform(source, options, limits=model.Limits(0, 1))
        expected = np.array([1+2j, 0j, 0j, 0j, 0j, 6-7j])
        np.testing.assert_allclose(self.inverse(spectrum).array, expected, atol=1e-12)
        self.assertIn("invalid complex samples: 3 -> 0+0j", spectrum.transform.description)
        self.assertNotIn("value bounds:", spectrum.transform.description)
        np.testing.assert_array_equal(source, original)

    def test_channel_extrema_are_selected_component_and_slice_local(self) -> None:
        source = np.array([[1+10j, 2+30j, complex(np.nan, 20), 4+40j],
                           [50+100j, 60+200j, 70+300j, 80+400j]])
        document = model.Document(Path("complex.npy"), source)
        for component in (model.Component.REAL, model.Component.IMAGINARY, model.Component.MAGNITUDE):
            selection = replace(model.default_selection(document), component=component)
            options = fourier.TransformOptions(range=fourier.TransformRange.FULL_SLICE, index=0,
                display_component=True, value_policy=special.FourierValuePolicy(nan=special.ValueReplacement.MAXIMUM))
            result = fourier.run_transform(document, selection, model.Crop(), model.Limits(), options, "Channel")
            expected = (source[0].real.copy() if component == model.Component.REAL else source[0].imag.copy()
                        if component == model.Component.IMAGINARY else np.abs(source[0]))
            expected[np.isnan(expected)] = np.max(expected[np.isfinite(expected)])
            np.testing.assert_allclose(self.inverse(result.document).array, expected, atol=1e-12)

    def test_phase_ignores_bounds_and_zero_fills_invalid_source_angles(self) -> None:
        source = np.array([1j, -1j, 0j, complex(np.inf, 1), complex(1, np.inf), complex(np.nan, 1)])
        document = model.Document(Path("phase.npy"), source)
        selection = replace(model.default_selection(document), component=model.Component.PHASE)
        options = fourier.TransformOptions(display_component=True, apply_bounds=True,
            value_policy=special.FourierValuePolicy(nan=special.ValueReplacement.MAXIMUM))
        result = fourier.run_transform(document, selection, model.Crop(), model.Limits(0, .1), options, "Phase")
        np.testing.assert_allclose(self.inverse(result.document).array, [np.pi/2, -np.pi/2, 0, 0, 0, 0], atol=1e-12)
        self.assertIn("NaN: 3 -> 0", result.document.transform.description)
        frame = model.prepare_frame(document, selection, model.Limits(5, -5), 0, model.Crop(0, 4))
        np.testing.assert_allclose(frame.display_scalar[:3], [np.pi/2, -np.pi/2, 0])
        self.assertEqual(frame.value_limits, model.Limits())
        self.assertFalse(np.any(frame.clip_kind))
        np.testing.assert_array_equal(frame.valid, [True, True, True, False, False])

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
        selection = model.default_selection(document)
        options = conversion.ConversionOptions(full_complex=True, db_floor=-80)
        result = conversion.run_conversion(document, selection, model.Crop(), model.Limits(), options, "Spectrum")
        np.testing.assert_allclose(result.document.array, [0, -20, -80, np.nan], equal_nan=True)
        zero = conversion.run_conversion(replace(document, array=np.zeros(4, dtype=np.complex128)), selection,
                                         model.Crop(), model.Limits(), options, "Zero spectrum")
        np.testing.assert_array_equal(zero.document.array, [-80] * 4)

    def test_paired_inverse_rejects_cropped_frequency_axis(self) -> None:
        spectrum = self.transform(np.arange(12.))
        with self.assertRaisesRegex(ValueError, "complete frequency"):
            fourier.run_transform(spectrum, model.default_selection(spectrum), model.Crop(1, 10), model.Limits(),
                                   fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE,
                                     range=fourier.TransformRange.CROP), "Spectrum")

    def test_inverse_requires_full_complex_input(self) -> None:
        options = fourier.TransformOptions(direction=fourier.TransformDirection.INVERSE, input_centered=False)
        for values in (np.arange(8.), np.ones((4, 5), dtype=np.int16)):
            with self.subTest(shape=values.shape), self.assertRaisesRegex(ValueError, "full complex input"):
                self.transform(values, options)
        spectrum = np.fft.fft(np.arange(8.) + 2j)
        for bad in (replace(options, display_component=True), replace(options, apply_bounds=True),
                    replace(options, range=fourier.TransformRange.CROP)):
            with self.subTest(options=bad), self.assertRaises(ValueError):
                self.transform(spectrum, bad)
        # Complex dtype remains eligible even when every imaginary part is zero.
        zeros = np.zeros(8, dtype=np.complex128)
        result = self.transform(zeros, options)
        np.testing.assert_array_equal(result.array, zeros)
        self.assertTrue(result.is_complex)


if __name__ == "__main__":
    unittest.main()
