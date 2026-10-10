"""Check shape, numeric fidelity and value-bound semantics of NPY exports.

Requirements: numpy and viewer data dependencies. Usage: unittest discovery.
"""

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
from fixture_store import preserve_document

PACKAGE = Path(__file__).resolve().parents[1]
if "personal_matrix_viewer" not in sys.modules:
    spec = importlib.util.spec_from_file_location("personal_matrix_viewer", PACKAGE / "__init__.py",
                                                submodule_search_locations=[str(PACKAGE)])
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
model = importlib.import_module("personal_matrix_viewer.data_model")


class ArrayExportTests(unittest.TestCase):
    """Export numerical arrays rather than normalized or sampled display buffers."""

    def test_cropped_matrix_keeps_full_resolution_and_dtype(self) -> None:
        """A low-resolution 3D preview never changes exported matrix dimensions."""
        source = np.arange(48, dtype=np.int16).reshape(6, 8)
        doc = preserve_document(model.Document(Path("data.npy"), source), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(0, 1, model.FilterMode.CLAMP),
                                    2, model.Crop(2, 6, 1, 4))
        saved = model.export_array(frame, model.ExportMode.CROP)
        np.testing.assert_array_equal(saved, source[1:5, 2:7])
        self.assertEqual(saved.dtype, np.int16)
        self.assertFalse(np.shares_memory(saved, source))

    def test_integral_caps_preserve_integer_dtype(self) -> None:
        """Lower/upper caps change only offending entries, keeping a 2D shape."""
        source = np.array([[-9, 1, 4], [10, -2, 8]], dtype=np.int16)
        doc = preserve_document(model.Document(Path("data.npy"), source), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(-2, 6, model.FilterMode.CLAMP), 512)
        saved = model.export_array(frame)
        np.testing.assert_array_equal(saved, [[-2, 1, 4], [6, -2, 6]])
        self.assertEqual(saved.dtype, np.int16)
        np.testing.assert_array_equal(source, [[-9, 1, 4], [10, -2, 8]])

    def test_fractional_caps_promote_signal_without_flattening(self) -> None:
        """Fractional boundaries are not truncated to the input integer dtype."""
        doc = preserve_document(model.Document(Path("signal.npy"), np.array([-3, 0, 5], dtype=np.int16)), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(-0.5, 2.5, model.FilterMode.CLAMP), 512)
        saved = model.export_array(frame)
        self.assertEqual(saved.shape, (3,))
        np.testing.assert_array_equal(saved, [-0.5, 0, 2.5])
        self.assertEqual(saved.dtype, np.float64)

    def test_hidden_samples_become_nan_without_removing_cells(self) -> None:
        """Gaps keep their original row/column positions in an exported matrix."""
        doc = preserve_document(model.Document(Path("data.npy"), np.arange(6, dtype=np.uint16).reshape(2, 3)), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(1, 4), 512)
        saved = model.export_array(frame)
        np.testing.assert_array_equal(saved, [[np.nan, 1, 2], [3, 4, np.nan]])
        self.assertEqual(saved.shape, (2, 3))
        self.assertEqual(saved.dtype, np.float64)

    def test_large_unclipped_integers_never_round_silently(self) -> None:
        """Export avoids the float-only render buffer and rejects lossy promotion."""
        source = np.array([2 ** 63 + 1, 2 ** 63 + 3, 0], dtype=np.uint64)
        doc = preserve_document(model.Document(Path("precise.npy"), source), "unit-inputs/test_array_export")
        selection = model.default_selection(doc)
        frame = model.prepare_frame(doc, selection, model.Limits(2, None, model.FilterMode.CLAMP), 512)
        saved = model.export_array(frame)
        np.testing.assert_array_equal(saved, np.array([2 ** 63 + 1, 2 ** 63 + 3, 2], dtype=np.uint64))
        self.assertEqual(saved.dtype, np.uint64)
        for limits in (model.Limits(0.5, None, model.FilterMode.CLAMP), model.Limits(1, None)):
            frame = model.prepare_frame(doc, selection, limits, 512)
            with self.assertRaisesRegex(ValueError, "integer precision"):
                model.export_array(frame)
            np.testing.assert_array_equal(model.export_array(frame, model.ExportMode.CROP), source)

    def test_nonfinite_gaps_and_float_dtype(self) -> None:
        """Processed nonfinite positions become NaN; crop-only keeps source values."""
        source = np.array([np.nan, -np.inf, np.inf, -3, 7], dtype=np.float32)
        doc = preserve_document(model.Document(Path("signal.npy"), source), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc), model.Limits(-1, 5, model.FilterMode.CLAMP), 512)
        saved = model.export_array(frame)
        np.testing.assert_array_equal(saved, [np.nan, np.nan, np.nan, -1, 5])
        self.assertEqual(saved.dtype, np.float32)
        np.testing.assert_array_equal(model.export_array(frame, model.ExportMode.CROP), source)

    def test_xy_exports_keep_actual_x_coordinates(self) -> None:
        """Only the Y column is processed; actual X coordinates are not discarded."""
        doc = preserve_document(model.Document(Path("xy.csv"), np.array([[10, -1], [11, 2], [12, 7]], dtype=np.int64)), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc, model.ViewMode.XY),
                                    model.Limits(0, 3, model.FilterMode.CLAMP), 512)
        np.testing.assert_array_equal(model.export_array(frame), [[10, 0], [11, 2], [12, 3]])
        np.testing.assert_array_equal(model.export_array(frame, model.ExportMode.CROP), doc.array)

    def test_point_clouds_require_switching_to_matrix_mode(self) -> None:
        """The array-export action cannot silently turn a cloud into a Z-only list."""
        doc = preserve_document(model.Document(Path("cloud.npy"), np.arange(12).reshape(4, 3)), "unit-inputs/test_array_export")
        frame = model.prepare_frame(doc, model.default_selection(doc, model.ViewMode.POINTS), model.Limits(), 512)
        with self.assertRaises(ValueError):
            model.export_array(frame)


if __name__ == "__main__":
    unittest.main()
