"""Check complex reconstruction, source identity and binary/text round trips.

Requirements: existing viewer dependencies. Usage: unittest discovery.
Generated files stay in the ignored fixture store, outside manual samples.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np
from PIL import Image

from fixture_store import fixture_directory
from test_data_model import model

merge = importlib.import_module("personal_matrix_viewer.complex_merge")
exporting = importlib.import_module("personal_matrix_viewer.exporting")
coordinates = importlib.import_module("personal_matrix_viewer.coordinates")


class ComplexMergeTests(unittest.TestCase):
    """Verify independent Cartesian parts and the phase-unit convention."""

    def test_cartesian_owned_matrix_and_exports(self) -> None:
        a = model.Document(Path("real.npy"), np.arange(20, dtype=np.float64).reshape(4, 5))
        b = model.Document(Path("imag.npy"), -a.array - 0.5)
        left = merge.MergeInput(a, model.default_selection(a), "Real source")
        right = merge.MergeInput(b, model.default_selection(b), "Imag source")
        result = merge.run_merge(left, right, merge.MergeMode.CARTESIAN, name="Reconstructed")
        self.assertTrue(result.document.is_complex)
        self.assertFalse(a.is_complex)
        self.assertEqual(result.name, "Reconstructed")
        expected = a.array + 1j * b.array
        np.testing.assert_array_equal(result.document.array, expected)
        self.assertFalse(np.shares_memory(result.document.array, a.array))
        self.assertIn("Imag source", result.document.complex_provenance)
        folder = fixture_directory("unit-files/complex-merge")
        for format_ in (exporting.ExportFormat.NPY, exporting.ExportFormat.MAT):
            path = folder / f"reconstructed.{format_.value}"
            path.write_bytes(exporting.serialize_array(result.document.array, format_))
            loaded = model.load_document(path)
            self.assertTrue(loaded.is_complex)
            np.testing.assert_array_equal(loaded.array, expected)
        for format_ in (exporting.ExportFormat.CSV, exporting.ExportFormat.TXT):
            paths = exporting.output_paths(folder / f"pair.{format_.value}", result.document.array, format_)
            self.assertEqual(len(paths), 2)
            for path, values in zip(paths, (expected.real, expected.imag), strict=True):
                path.write_bytes(exporting.serialize_array(values, format_))
            sources = [model.load_document(path) for path in paths]
            merged = merge.run_merge(*(merge.MergeInput(doc, model.default_selection(doc), doc.path.name) for doc in sources),
                                     merge.MergeMode.CARTESIAN)
            np.testing.assert_array_equal(merged.document.array, expected)

    def test_complex_channels_and_polar_units(self) -> None:
        source = np.array([1 + 2j, -3 + 4j, -2 - 5j, 4 - 3j, 0j])
        doc = model.Document(Path("wave.npy"), source)
        selection = model.default_selection(doc)
        real = merge.MergeInput(doc, replace(selection, component=model.Component.REAL), "Real")
        imag = merge.MergeInput(doc, replace(selection, component=model.Component.IMAGINARY), "Imaginary")
        np.testing.assert_array_equal(merge.run_merge(real, imag, merge.MergeMode.CARTESIAN).document.array, source)
        magnitude = merge.MergeInput(doc, replace(selection, component=model.Component.MAGNITUDE), "Magnitude")
        for unit in (merge.PhaseUnit.RADIANS, merge.PhaseUnit.DEGREES):
            if unit == merge.PhaseUnit.RADIANS:
                phase = merge.MergeInput(doc, replace(selection, component=model.Component.PHASE), "Phase (rad)")
            else:
                degrees = model.Document(Path("phase_degrees.npy"), np.angle(source, deg=True))
                phase = merge.MergeInput(degrees, model.default_selection(degrees), "Converted phase degrees")
            result = merge.run_merge(magnitude, phase, merge.MergeMode.POLAR, unit)
            np.testing.assert_allclose(result.document.array, source, atol=1e-14)
        np.testing.assert_array_equal(doc.array, source)

    def test_zero_imaginary_is_still_complex(self) -> None:
        doc = model.Document(Path("real.npy"), np.arange(4.0))
        zero = replace(doc, array=np.zeros(4))
        result = merge.run_merge(merge.MergeInput(doc, model.default_selection(doc), "Value"),
                                 merge.MergeInput(zero, model.default_selection(zero), "Zero"), merge.MergeMode.CARTESIAN)
        self.assertTrue(result.document.is_complex)
        self.assertTrue(np.all(result.document.array.imag == 0))

    def test_cartesian_nonfinite_parts_are_independent(self) -> None:
        a = model.Document(Path("a.npy"), np.array([1., np.inf, np.nan, -2]))
        b = replace(a, array=np.array([np.inf, 3., 7, np.nan]))
        result = merge.run_merge(merge.MergeInput(a, model.default_selection(a), "A"),
                                 merge.MergeInput(b, model.default_selection(b), "B"), merge.MergeMode.CARTESIAN)
        np.testing.assert_array_equal(result.document.array.real, a.array)
        np.testing.assert_array_equal(result.document.array.imag, b.array)

    def test_invalid_shapes_grid_magnitude_and_precision(self) -> None:
        doc = model.Document(Path("a.npy"), np.arange(4.0))
        source = merge.MergeInput(doc, model.default_selection(doc), "A")
        wrong_shape = replace(doc, array=np.ones((4, 1)))
        with self.assertRaisesRegex(ValueError, "shapes must match"):
            merge.run_merge(source, merge.MergeInput(wrong_shape, model.default_selection(wrong_shape, model.ViewMode.MATRIX), "B"), merge.MergeMode.CARTESIAN)
        with self.assertRaisesRegex(ValueError, "coordinates do not match"):
            merge.run_merge(source, replace(source, document=replace(doc, axes=(coordinates.AxisCoordinates(spacing=2),))), merge.MergeMode.CARTESIAN)
        with self.assertRaisesRegex(ValueError, "negative"):
            merge.run_merge(replace(source, document=replace(doc, array=-doc.array)), source, merge.MergeMode.POLAR)
        with self.assertRaisesRegex(ValueError, "precision"):
            merge.run_merge(replace(source, document=replace(doc, array=np.full(4, 2**63 + 1, dtype=np.uint64))), source, merge.MergeMode.CARTESIAN)

    def test_xy_reorders_matching_uniform_coordinates(self) -> None:
        a = model.Document(Path("a.csv"), np.array([[2., 30], [0, 10], [1, 20]]))
        b = model.Document(Path("b.csv"), np.array([[1., -2], [2, -3], [0, -1]]))
        result = merge.run_merge(merge.MergeInput(a, model.default_selection(a, model.ViewMode.XY), "A"),
                                 merge.MergeInput(b, model.default_selection(b, model.ViewMode.XY), "B"), merge.MergeMode.CARTESIAN)
        np.testing.assert_array_equal(result.document.array, [10 - 1j, 20 - 2j, 30 - 3j])
        self.assertEqual(result.document.axes[0], coordinates.AxisCoordinates())

    def test_lazy_image_channel_selection(self) -> None:
        folder = fixture_directory("unit-files/complex-merge")
        pixels = np.zeros((4, 5, 3), dtype=np.uint8)
        pixels[..., 0] = 20
        pixels[..., 1] = 60
        path = folder / "channels.png"
        Image.fromarray(pixels).save(path)
        doc = model.load_document(path)
        selection = model.default_selection(doc)
        result = merge.run_merge(merge.MergeInput(doc, selection, "R", model.ImageMember.RED),
                                 merge.MergeInput(doc, selection, "G", model.ImageMember.GREEN), merge.MergeMode.CARTESIAN)
        np.testing.assert_array_equal(result.document.array, np.full((4, 5), 20 + 60j))


if __name__ == "__main__":
    unittest.main()
