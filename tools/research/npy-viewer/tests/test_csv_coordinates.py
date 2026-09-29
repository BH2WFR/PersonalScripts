"""CSV, coordinate interpretation and nonuniform-derivative regressions.

Requirements: numpy and viewer data dependencies. Usage: unittest discovery.
"""

from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

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
derivatives = importlib.import_module("personal_npy_viewer.derivatives")


class CSVCoordinateTests(unittest.TestCase):
    """Data order, coordinate units and raw precision survive every interpretation."""

    def setUp(self) -> None:
        """Create CSV fixtures only in the ignored project scratch directory."""
        folder = tempfile.TemporaryDirectory(prefix="viewer-csv-", dir=ROOT / "tmp")
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def _csv(self, content: str) -> Path:
        path = self.folder / "data.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_csv_headers_bom_empty_cells_and_delimiters(self) -> None:
        """Quoted UTF-8 headings and empty cells retain their table positions."""
        for delimiter in (",", ";", "\t"):
            with self.subTest(delimiter=repr(delimiter)):
                text = f'\ufeff"time"{delimiter}"value"\n\n0{delimiter}2\n1{delimiter}\n2{delimiter}4\n'
                doc = model.load_document(self._csv(text))
                self.assertEqual(doc.csv_headers, ("time", "value"))
                np.testing.assert_array_equal(doc.array, [[0, 2], [1, np.nan], [2, 4]])
                self.assertEqual(model.default_selection(doc).mode, model.ViewMode.MATRIX)

    def test_csv_integer_precision_and_invalid_records(self) -> None:
        """Large integer cells remain exact; malformed records never disappear."""
        doc = model.load_document(self._csv("18446744073709551615,9007199254740993\n0,1\n"))
        self.assertEqual(doc.array.dtype, np.uint64)
        self.assertEqual(str(doc.array[0, 0]), "18446744073709551615")
        self.assertEqual(str(doc.array[0, 1]), "9007199254740993")
        for text in ("1,2\n3\n", "1,2\n3,error\n", "x,y\n", "", "18446744073709551616\n",
                     "9007199254740993,0.5\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                model.load_document(self._csv(text))

    def test_xy_rows_columns_swapping_and_crop(self) -> None:
        """Coordinate layout is explicit and cropping preserves original X units."""
        source = np.array([[10, 2], [12, 4], [20, 8], [21, 16]], dtype=np.int64)
        for array in (source, source.T):
            doc = model.Document(Path("measurements.csv"), array)
            selection = model.default_selection(doc, model.ViewMode.XY)
            frame = model.prepare_frame(doc, selection, model.Limits(3, 10, model.FilterMode.CLAMP), 512,
                                        model.Crop(1, 3))
            np.testing.assert_array_equal(frame.x_values, [12, 20, 21])
            np.testing.assert_array_equal(frame.raw, source[1:])
            np.testing.assert_array_equal(frame.scalar, [4, 8, 16])
            np.testing.assert_array_equal(frame.display_scalar, [4, 8, 10])
            swapped = model.prepare_frame(doc, replace(selection, coordinate_order=(1, 0)), model.Limits(), 512)
            np.testing.assert_array_equal(swapped.x_values, source[:, 1])
            np.testing.assert_array_equal(swapped.scalar, source[:, 0])

    def test_point_cloud_uses_xyz_not_matrix_indices(self) -> None:
        """Point limits affect only geometry; filtering checks all coordinates."""
        source = np.array([[10, 30, 2], [20, 60, 4], [30, 90, 8], [np.nan, 100, 1], [50, 150, 16]])
        for array in (source, source.T):
            doc = model.Document(Path("cloud.npy"), array)
            selection = model.default_selection(doc, model.ViewMode.POINTS)
            frame = model.prepare_frame(doc, selection, model.Limits(), 512, max_points=2)
            np.testing.assert_array_equal(frame.surface.points, source[[0, 4]])
            np.testing.assert_array_equal(frame.surface.rows, [0, 4])
            self.assertEqual(frame.surface.faces.size, 0)
            np.testing.assert_array_equal(frame.point_coordinates, source)
            hidden = model.prepare_frame(doc, selection, model.Limits(3, 10), 512)
            np.testing.assert_array_equal(hidden.surface.points, source[[1, 2]])
            cropped = model.prepare_frame(doc, selection, model.Limits(), 512, model.Crop(1, 2))
            np.testing.assert_array_equal(cropped.surface.points, source[1:3])
            np.testing.assert_array_equal(cropped.surface.rows, [1, 2])

    def test_ambiguous_square_and_invalid_coordinate_orders(self) -> None:
        """3x3 data supports either layout; repeated assignments are rejected."""
        doc = model.Document(Path("square.npy"), np.arange(9).reshape(3, 3))
        selection = model.default_selection(doc, model.ViewMode.POINTS)
        rows = replace(selection, coordinate_axis=0, x_axis=1, coordinate_order=(2, 0, 1))
        frame = model.prepare_frame(doc, rows, model.Limits(), 512)
        np.testing.assert_array_equal(frame.point_coordinates, doc.array.T[:, (2, 0, 1)])
        with self.assertRaises(ValueError):
            model.prepare_frame(doc, replace(selection, coordinate_order=(0, 0, 2)), model.Limits(), 512)

    def test_raw_complex_and_large_integer_data_survive_filtering(self) -> None:
        """Raw cells retain complex values while plots use the requested component."""
        data = np.array([[1 + 2j, 3 + 4j], [5 + 6j, 7 + 8j]])
        doc = model.Document(Path("complex.npy"), data)
        selection = replace(model.default_selection(doc), component=model.Component.MAGNITUDE)
        frame = model.prepare_frame(doc, selection, model.Limits(0, 2, model.FilterMode.CLAMP), 512)
        np.testing.assert_array_equal(frame.raw, data)
        self.assertTrue(np.shares_memory(frame.raw, data))
        np.testing.assert_array_equal(frame.display_scalar, np.full((2, 2), 2))

    def test_nonuniform_and_descending_derivatives(self) -> None:
        """Quadratic interior slopes are exact with unequal or decreasing spacing."""
        for x in (np.array([0., 1., 3., 6.]), np.array([6., 3., 1., 0.])):
            result = derivatives.differentiate(x ** 2, np.ones(4, dtype=bool), x_values=x)
            np.testing.assert_allclose(result.values[1:-1], 2 * x[1:-1])
            self.assertTrue(np.all(result.valid))
        large_x = np.array([2 ** 63, 2 ** 63 + 1, 2 ** 63 + 3], dtype=np.uint64)
        result = derivatives.differentiate(np.array([0., 1., 9.]), np.ones(3, dtype=bool), x_values=large_x)
        self.assertAlmostEqual(result.values[1], 2)

    def test_unordered_xy_derivatives_follow_x_not_record_order(self) -> None:
        """Shuffled coordinates retain dy/dx and source-index correspondence."""
        x = np.array([6., 0., 3., 1., 10.])
        values = x ** 2
        result = derivatives.differentiate(values, np.ones(5, dtype=bool), x_values=x)
        np.testing.assert_allclose(result.values, [12, 1, 6, 2, 16])
        self.assertTrue(result.valid.all())
        np.testing.assert_array_equal(x, [6, 0, 3, 1, 10])
        np.testing.assert_array_equal(values, x ** 2)

    def test_nonadjacent_repeated_x_are_gaps_for_every_stencil(self) -> None:
        """Duplicate Y choices cannot affect any neighboring derivative."""
        x = np.array([0., 1., 2., 3., 4., 5., 6., 7., 8., 9., 4.])
        for repeated_y in (16., 1000.):
            values = x ** 2
            values[-1] = repeated_y
            result = derivatives.differentiate(values, np.ones(11, dtype=bool), x_values=x)
            np.testing.assert_array_equal(result.undefined_indices, [3, 4, 5, 10])
            np.testing.assert_allclose(result.values[result.valid], [1, 2, 4, 12, 14, 16, 17])
            self.assertTrue(np.all(np.isnan(result.values[~result.valid])))
            order = np.array([10, 8, 2, 1, 4, 9, 0, 7, 5, 3, 6])
            shuffled = derivatives.differentiate(values[order], np.ones(11, dtype=bool), x_values=x[order])
            np.testing.assert_allclose(shuffled.values, result.values[order], equal_nan=True)

    def test_repeated_and_nonfinite_x_do_not_invent_derivatives(self) -> None:
        """Short duplicate groups and invalid coordinates stay undefined."""
        for x in (np.array([0., 1., 1., 3.]), np.array([1., 1., 1.])):
            result = derivatives.differentiate(np.arange(float(len(x))), np.ones(len(x), dtype=bool), x_values=x)
            self.assertFalse(result.valid.any())
            self.assertTrue(np.isnan(result.values).all())
        x = np.array([0., np.nan, 1., np.inf, 2., -np.inf, 3.])
        result = derivatives.differentiate(np.arange(7.), np.ones(7, dtype=bool), x_values=x)
        self.assertFalse(result.valid[~np.isfinite(x)].any())
        self.assertTrue(np.isnan(result.values[~np.isfinite(x)]).all())
        self.assertTrue(np.all(np.isfinite(x[result.undefined_indices])))

    def test_xy_jump_threshold_uses_neighbors_sorted_by_x(self) -> None:
        """File order cannot change the detected jump or marker locations."""
        x = np.array([4., 0., 3., 1., 2., 5.])
        values = x + np.where(x >= 3, 10, 0)
        result = derivatives.differentiate(values, np.ones(6, dtype=bool), 5, x_values=x)
        self.assertEqual(result.jump_count, 1)
        np.testing.assert_array_equal(result.undefined_indices, [2, 4])
        np.testing.assert_allclose(result.values[result.valid], 1)


if __name__ == "__main__":
    unittest.main()
