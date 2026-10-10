"""Numerical Laplace tests: direct sums, inverse contours, coordinates and errors.

Requirements: viewer numeric dependencies. Usage: unittest discover in this folder.
No fixtures are written to the curated manual test-matrixes directory.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np

from test_data_model import model

laplace = importlib.import_module("personal_npy_viewer.laplace")
fourier = importlib.import_module("personal_npy_viewer.fourier")
coordinates = importlib.import_module("personal_npy_viewer.coordinates")


class LaplaceTests(unittest.TestCase):
    """Test the finite-record convention without relying only on a round trip."""

    def forward(self, values: model.Array, options: laplace.LaplaceOptions | None = None,
                crop: model.Crop = model.Crop(), limits: model.Limits = model.Limits()) -> model.Document:
        document = model.Document(Path("signal.npy"), values)
        return laplace.run_laplace(document, model.default_selection(document), crop, limits,
            options or laplace.LaplaceOptions(sigma_count=5), "Signal").document

    def inverse(self, document: model.Document, **kwargs: object) -> model.Document:
        options = laplace.LaplaceOptions(direction=laplace.LaplaceDirection.INVERSE, **kwargs)
        return laplace.run_laplace(document, model.default_selection(document, model.ViewMode.MATRIX),
            model.Crop(), model.Limits(), options, "Plane").document

    def test_matches_direct_complex_exponential_sum(self) -> None:
        values = np.arange(7.) + 1j * np.cos(np.arange(7.))
        dt = 0.125
        plane = self.forward(values, laplace.LaplaceOptions(spacing=dt, unit="s", sigma_min=-1,
            sigma_max=2, sigma_count=4, fft_size=10))
        sigma = plane.axes[0].values(0, 4)
        omega = plane.axes[1].values(0, 10)
        t = np.arange(7) * dt
        expected = np.array([[dt * np.sum(values * np.exp(-(s + 1j * w) * t)) for w in omega] for s in sigma])
        np.testing.assert_allclose(plane.array, expected, atol=1e-13)
        self.assertEqual(plane.axes[0].label(), "σ (1/s)")
        self.assertEqual(plane.axes[1].label(), "ω (rad/s)")

    def test_real_complex_parities_padding_and_nonzero_contour(self) -> None:
        for count in (7, 8):
            for complex_ in (False, True):
                values = np.sin(np.arange(count)) + (1j * np.arange(count) if complex_ else 0)
                original = values.copy()
                for size in (count, count + 3):
                    plane = self.forward(values, laplace.LaplaceOptions(spacing=0.2, sigma_min=-1,
                        sigma_max=1, sigma_count=5, fft_size=size))
                    for row in (None, 0, 4):
                        restored = self.inverse(plane, inverse_row=row)
                        self.assertEqual(restored.array.shape, (count,))
                        self.assertTrue(np.iscomplexobj(restored.array))
                        np.testing.assert_allclose(restored.array, original, atol=1e-12)
                    np.testing.assert_array_equal(values, original)

    def test_external_centered_and_standard_spectra(self) -> None:
        values = np.array([1, 3 + 2j, -1, 4, 8j])
        plane = self.forward(values, laplace.LaplaceOptions(spacing=0.3, sigma_min=-0.5,
            sigma_max=0.5, sigma_count=3, fft_size=8))
        for centered in (True, False):
            data = plane.array if centered else np.fft.ifftshift(plane.array, axes=1)
            external = model.Document(Path("reloaded.npy"), data)
            restored = self.inverse(external, inverse_row=2, external_sigma=0.5,
                omega_spacing=plane.axes[1].spacing, output_count=5, output_origin=12.0,
                unit="s", input_centered=centered)
            np.testing.assert_allclose(restored.array, values, atol=1e-12)
            self.assertAlmostEqual(restored.axes[0].spacing, 0.3)
            self.assertEqual(restored.axes[0].origin, 12.0)

    def test_crop_origin_and_input_axis_metadata(self) -> None:
        values = np.arange(20.)
        options = laplace.LaplaceOptions(range=fourier.TransformRange.CROP, spacing=0.25, unit="s", sigma_count=5)
        plane = self.forward(values, options, model.Crop(4, 11))
        restored = self.inverse(plane)
        np.testing.assert_allclose(restored.array, values[4:12], atol=1e-12)
        self.assertEqual(restored.axes[0].origin, 1.0)
        document = model.Document(Path("physical.npy"), values, axes=(coordinates.AxisCoordinates(10, 0.25, "s"),))
        plane = laplace.run_laplace(document, model.default_selection(document), model.Crop(4, 11),
            model.Limits(), options, "Physical").document
        self.assertEqual(self.inverse(plane).axes[0].origin, 11.0)

    def test_xy_coordinates_and_rejection(self) -> None:
        x = np.arange(8.) * 0.1 + 5
        values = np.column_stack((x, x**2))[::-1]
        document = model.Document(Path("xy.npy"), values)
        selection = model.default_selection(document, model.ViewMode.XY)
        plane = laplace.run_laplace(document, selection, model.Crop(), model.Limits(),
            laplace.LaplaceOptions(sigma_count=5, unit="s"), "XY").document
        result = self.inverse(plane)
        np.testing.assert_allclose(result.array, x**2, atol=1e-12)
        self.assertAlmostEqual(result.axes[0].spacing, 0.1)
        self.assertEqual(result.axes[0].origin, 5.0)
        for bad_x in ([0, 1, 1, 3], [0, 1, 2, 4]):
            bad = model.Document(Path("bad_xy.npy"), np.column_stack((bad_x, np.arange(4.))))
            with self.assertRaises(ValueError):
                laplace.run_laplace(bad, model.default_selection(bad, model.ViewMode.XY), model.Crop(),
                    model.Limits(), laplace.LaplaceOptions(), "Bad XY")

    def test_preprocessing_is_explicit(self) -> None:
        values = np.array([0., 2., np.nan, 5.])
        with self.assertRaisesRegex(ValueError, "NaN"):
            self.forward(values)
        result = self.forward(values, laplace.LaplaceOptions(sigma_count=5, fill_zero=True,
            apply_bounds=True), limits=model.Limits(1, 3, model.FilterMode.CLAMP))
        np.testing.assert_allclose(self.inverse(result).array, [1, 2, 0, 3], atol=1e-12)
        self.assertIn("zero-filled", result.laplace.description)
        complex_ = np.array([1 + 2j, 3 + 4j])
        with self.assertRaisesRegex(ValueError, "real display"):
            self.forward(complex_, laplace.LaplaceOptions(apply_bounds=True))

    def test_single_precision_and_integer_guard(self) -> None:
        values = np.arange(12., dtype=np.float32)
        result = self.forward(values, laplace.LaplaceOptions(sigma_count=5, single_precision=True))
        self.assertEqual(result.array.dtype, np.complex64)
        np.testing.assert_allclose(self.inverse(result).array, values, atol=2e-6)
        with self.assertRaisesRegex(ValueError, "round"):
            self.forward(np.array([2**63 + 1, 2**63 + 3], dtype=np.uint64))

    def test_invalid_input_and_output_controls(self) -> None:
        values = np.arange(5.)
        for options in (laplace.LaplaceOptions(spacing=0), laplace.LaplaceOptions(sigma_min=1, sigma_max=0),
                        laplace.LaplaceOptions(sigma_count=1), laplace.LaplaceOptions(fft_size=2),
                        laplace.LaplaceOptions(sigma_min=-1e4, sigma_max=1e4),
                        laplace.LaplaceOptions(range=fourier.TransformRange.SLICE),
                        laplace.LaplaceOptions(range=fourier.TransformRange.FULL_SLICE)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.forward(values, options)
        with self.assertRaises(MemoryError):
            self.forward(values, laplace.LaplaceOptions(fft_size=100_000_000))
        with self.assertRaisesRegex(ValueError, "1D"):
            self.forward(np.ones((4, 5)))
        with self.assertRaisesRegex(ValueError, "two"):
            self.forward(np.ones(1))

    def test_inverse_invalid_or_incomplete_data(self) -> None:
        plane = self.forward(np.arange(8.))
        for kwargs in ({"inverse_row": 99}, {"range": fourier.TransformRange.CROP}, {"apply_bounds": True},
                       {"display_component": True}):
            with self.assertRaises(ValueError):
                self.inverse(plane, **kwargs)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.inverse(replace(plane, array=plane.array[:, :-1]))
        with self.assertRaisesRegex(ValueError, "complex"):
            self.inverse(replace(plane, array=plane.array.real))
        with self.assertRaisesRegex(ValueError, "omega"):
            selection = replace(model.default_selection(plane), x_axis=0, y_axis=1)
            laplace.run_laplace(plane, selection, model.Crop(), model.Limits(),
                laplace.LaplaceOptions(direction=laplace.LaplaceDirection.INVERSE), "Transposed")
        external = replace(plane, laplace=None, axes=())
        for kwargs in ({"omega_spacing": 0}, {"output_count": 100}, {"external_sigma": float("nan")}):
            with self.assertRaises(ValueError):
                self.inverse(external, **kwargs)
        corrupted = plane.array.copy()
        corrupted[2, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "NaN"):
            self.inverse(replace(plane, array=corrupted), inverse_row=2)


if __name__ == "__main__":
    unittest.main()
