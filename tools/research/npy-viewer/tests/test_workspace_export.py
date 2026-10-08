"""Check visible exports, coordinate fidelity and matrix/channel identities.

Requirements: existing viewer dependencies. Usage: unittest discovery.
Tests use in-memory arrays and MAT bytes, never the manual test-matrixes folder.
"""

from dataclasses import replace
from io import BytesIO
import importlib
from pathlib import Path
import unittest

import numpy as np
from scipy.io import loadmat

from test_data_model import model

workspace = importlib.import_module("personal_npy_viewer.workspace")
exporting = importlib.import_module("personal_npy_viewer.exporting")
visible = importlib.import_module("personal_npy_viewer.workspace_export")


class WorkspaceExportTests(unittest.TestCase):
    """Assert numeric meaning, independent of Qt layouts or save dialogs."""

    def test_signal_crop_clamp_and_alignment(self) -> None:
        document = model.Document(Path("wave.npy"), np.array([0., 2, 9, np.nan, 5]))
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(1, 4, model.FilterMode.CLAMP), 0, model.Crop(1, 4))
        entry = workspace.MatrixEntry(1, document, selection, "red", name="Wave B")
        layer = workspace.RenderLayer(1, entry.label, frame, "red", 1, workspace.AxisMap(2, 10))
        snapshot = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.RESULT)
        np.testing.assert_allclose(snapshot.values, [[12, 2], [14, 4], [16, np.nan], [18, 4]], equal_nan=True)
        self.assertEqual(snapshot.stem, "Wave_B_Value_result_aligned")
        np.testing.assert_allclose(document.array, [0, 2, 9, np.nan, 5], equal_nan=True)
        self.assertFalse(np.shares_memory(snapshot.values, document.array))

    def test_unsorted_xy_keeps_records_and_duplicate_x(self) -> None:
        document = model.Document(Path("pairs.csv"), np.array([[9., 2], [3, 5], [3, 6]]))
        selection = model.default_selection(document, model.ViewMode.XY)
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        entry = workspace.MatrixEntry(1, document, selection, "red")
        layer = workspace.RenderLayer(1, entry.label, frame, "red", 1, workspace.AxisMap(0.5, -1))
        snapshot = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.RESULT)
        np.testing.assert_array_equal(snapshot.values, [[3.5, 2], [0.5, 5], [0.5, 6]])

    def test_matrix_xyz_and_aligned_column_slice(self) -> None:
        source = np.arange(20., dtype=np.float64).reshape(4, 5)
        document = model.Document(Path("surface.npy"), source)
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(7, 18), 2, model.Crop(1, 3, 1, 3))
        entry = workspace.MatrixEntry(1, document, selection, "red")
        layer = workspace.RenderLayer(1, entry.label, frame, "red", 1,
                                      workspace.AxisMap(2, 10), workspace.AxisMap(3, -5), height=100)
        result = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.RESULT)
        expected = [[2*x+10, 3*y-5, source[y, x]] for y in range(1, 4) for x in range(1, 4) if source[y, x] >= 7]
        np.testing.assert_array_equal(result.values, expected)
        column = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.SLICE, row=False, position=14)
        np.testing.assert_array_equal(column.values, [[-2, 7], [1, 12], [4, 17]])
        self.assertIn("column-2", column.stem)
        self.assertIsNone(visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.SLICE, position=100))

    def test_exact_uint64_and_lossy_coordinate_promotion(self) -> None:
        source = np.array([2**64 - 1, 2**64 - 2], dtype=np.uint64)
        document = model.Document(Path("large.npy"), source)
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        entry = workspace.MatrixEntry(1, document, selection, "red")
        layer = workspace.RenderLayer(1, entry.label, frame, "red", 1)
        snapshot = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.RESULT)
        self.assertEqual(snapshot.values.dtype, np.uint64)
        np.testing.assert_array_equal(snapshot.values[:, 1], source)
        with self.assertRaisesRegex(ValueError, "precision"):
            visible.prepare_displayed_export(entry, replace(layer, x=workspace.AxisMap(0.5, 0)), exporting.ExportTarget.RESULT)

    def test_mat_variables_disambiguate_names(self) -> None:
        first = exporting.ExportSnapshot(np.arange(8).reshape(4, 2), "same-name")
        second = exporting.ExportSnapshot(np.arange(9).reshape(3, 3), "same name")
        third = exporting.ExportSnapshot(np.arange(6).reshape(3, 2), "123中文")
        snapshots = (first, second, third)
        names = visible.mat_variable_names(snapshots)
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(name[0].isalpha() and name.isascii() and len(name) <= 63 for name in names))
        decoded = loadmat(BytesIO(visible.serialize_displayed_mat(snapshots)))
        for name, snapshot in zip(names, snapshots, strict=True):
            np.testing.assert_array_equal(decoded[name], snapshot.values)
        self.assertEqual(visible.safe_stem("../A:B / C"), "A_B_C")
        self.assertEqual(visible.safe_stem("CON"), "matrix_CON")

    def test_rename_and_complex_channel_choices(self) -> None:
        document = model.Document(Path("package.npz"), np.array([1+2j, 2+4j]), key="wave")
        selection = replace(model.default_selection(document), component=model.Component.PHASE_DEG)
        entry = workspace.MatrixEntry(1, document, selection, "red", name="Phase sample")
        self.assertEqual(entry.label, "Phase sample")
        self.assertEqual(entry.source_label, "package.npz :: wave")
        choices = workspace.channel_choices(entry)
        self.assertEqual(len(choices), len(model.Component))
        self.assertEqual(workspace.active_channel(entry).label, "Phase (deg)")
        self.assertEqual(visible.default_stem(entry, exporting.ExportTarget.RESULT, preserve_complex=True),
                         "Phase_sample_complex_result")
        frame = model.prepare_frame(document, selection, model.Limits(), 0)
        layer = workspace.RenderLayer(1, entry.label, frame, "red", 1)
        snapshot = visible.prepare_displayed_export(entry, layer, exporting.ExportTarget.RESULT)
        np.testing.assert_allclose(snapshot.values[:, 1], np.angle(document.array, deg=True))


if __name__ == "__main__":
    unittest.main()
