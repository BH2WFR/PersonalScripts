"""Verify overlay coordinates, source fidelity and archive expansion.

Requirements: viewer dependencies. Usage: unittest discovery; generated files
belong to the ignored automated fixture directory, not manual test-matrixes.
"""

from dataclasses import replace
import importlib
from pathlib import Path
import unittest

import numpy as np
from scipy.io import savemat

from fixture_store import fixture_directory
from test_data_model import model

workspace = importlib.import_module("personal_matrix_viewer.workspace")


class WorkspaceTests(unittest.TestCase):
    """Check physical coordinates independently of GUI widgets and renderers."""

    def test_alignment_uses_actual_ranges(self) -> None:
        """Translations retain spacing; stretching maps both range endpoints."""
        align = workspace.align_axis
        modes = workspace.Alignment
        for mode, expected in ((modes.ORIGINAL, (20, 60)), (modes.START, (5, 45)),
                               (modes.END, (-25, 15)), (modes.CENTER, (-10, 30)),
                               (modes.STRETCH, (5, 15))):
            with self.subTest(mode=mode):
                mapping = align((20, 60), (5, 15), mode)
                self.assertAlmostEqual(mapping.forward(20), expected[0])
                self.assertAlmostEqual(mapping.forward(60), expected[1])
                self.assertAlmostEqual(mapping.inverse(mapping.forward(31)), 31)

    def test_singleton_stretch_is_invertible(self) -> None:
        """One sample stays at the center rather than losing inverse coordinates."""
        mapping = workspace.align_axis((7, 7), (0, 10), workspace.Alignment.STRETCH)
        self.assertEqual(mapping.forward(7), 5)
        self.assertEqual(mapping.inverse(5), 7)
        mapping = workspace.align_axis((0, 10), (7, 7), workspace.Alignment.STRETCH)
        self.assertEqual(mapping.forward(5), 7)
        self.assertEqual(mapping.scale, 1)

    def test_indexed_and_xy_are_same_family(self) -> None:
        self.assertEqual(workspace.family(model.ViewMode.SIGNAL), workspace.family(model.ViewMode.XY))
        self.assertNotEqual(workspace.family(model.ViewMode.SIGNAL), workspace.family(model.ViewMode.MATRIX))
        self.assertNotEqual(workspace.family(model.ViewMode.MATRIX), workspace.family(model.ViewMode.POINTS))

    def test_height_bounds_use_crop_and_bounds_without_color_padding(self) -> None:
        source = np.array([[np.nan, -50, 3, 100], [np.inf, -20, 8, 200]])
        document = model.Document(Path("matrix.npy"), source)
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(0, 10, model.FilterMode.CLAMP), 2,
                                    model.Crop(1, 2, 0, 1))
        self.assertEqual(workspace.height_bounds(frame, 3), (0, 24))
        hidden = model.prepare_frame(document, selection, model.Limits(0, 10), 2)
        self.assertEqual(workspace.height_bounds(hidden, 3), (9, 24))
        empty = model.prepare_frame(document, selection, model.Limits(500, 600), 2)
        self.assertEqual(workspace.height_bounds(empty, 3), (0, 0))
        constant = model.Document(Path("constant.npy"), np.full((4, 5), 7, dtype=np.int16))
        frame = model.prepare_frame(constant, model.default_selection(constant), model.Limits(), 2)
        self.assertNotEqual(frame.limits, (7, 7))
        self.assertEqual(workspace.height_bounds(frame, 2), (14, 14))

    def test_z_alignment_follows_height_without_changing_slice_data(self) -> None:
        document = model.Document(Path("matrix.npy"), np.arange(20.).reshape(4, 5))
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 2)
        layer = workspace.RenderLayer(1, "matrix", frame, "red", 0.5, height=3)
        mapping = workspace.align_axis(workspace.height_bounds(frame, 3), (10, 20), workspace.Alignment.STRETCH)
        aligned = replace(layer, z=mapping)
        self.assertAlmostEqual(aligned.z_mapping.forward(0), 10)
        self.assertAlmostEqual(aligned.z_mapping.forward(19), 20)
        self.assertNotEqual(layer.signature, aligned.signature)
        original, moved = workspace.profile_series(layer, True, 2), workspace.profile_series(aligned, True, 2)
        self.assertEqual(original.key, moved.key)
        np.testing.assert_array_equal(moved.shown, document.array[2])
        np.testing.assert_array_equal(moved.values, original.values)

    def test_point_height_bounds_ignore_invalid_coordinates(self) -> None:
        document = model.Document(Path("points.npy"), np.array([[1., 2, -100], [np.nan, 2, 500],
                                                               [3, 4, 100], [5, 6, 50]]))
        frame = model.prepare_frame(document, model.default_selection(document, model.ViewMode.POINTS),
                                    model.Limits(-20, 30, model.FilterMode.CLAMP), 2)
        self.assertEqual(workspace.height_bounds(frame, 2), (-40, 60))

    def test_overlay_auto_height_includes_unbounded_nonreference(self) -> None:
        entries = []
        for uid, (low, high) in enumerate(((-5000, 5000), (-13_000_000, 13_000_000)), 1):
            document = model.Document(Path(f"channel-{uid}.npy"), np.linspace(low, high, 20).reshape(4, 5))
            selection = model.default_selection(document)
            frame = model.prepare_frame(document, selection, model.Limits(), 2)
            entries.append(workspace.MatrixEntry(uid, document, selection, "red", frame=frame))
        scale = workspace.overlay_auto_height(entries, entries[0])
        self.assertAlmostEqual(scale * 26_000_000, 1.5)
        self.assertEqual(scale, workspace.overlay_auto_height(entries, entries[1]))
        entries[1].align_z = workspace.Alignment.STRETCH
        self.assertAlmostEqual(workspace.overlay_auto_height(entries, entries[0]) * 10_000, 1.5)
        entries[1].settings["auto_height"] = False
        self.assertAlmostEqual(workspace.overlay_auto_height(entries, entries[0]) * 10_000, 1.5)

    def test_aligned_slice_keeps_source_values_and_indices(self) -> None:
        source = np.arange(20.).reshape(4, 5)
        document = model.Document(Path("matrix.npy"), source)
        frame = model.prepare_frame(document, model.default_selection(document), model.Limits(), 2, model.Crop(1, 4, 1, 3))
        layer = workspace.RenderLayer(1, "matrix.npy", frame, "#ff0000", 0.5,
                                      workspace.AxisMap(2, 10), workspace.AxisMap(3, 20))
        row = workspace.profile_series(layer, True, 25.8)
        self.assertIsNotNone(row)
        self.assertEqual(row.index, 2)
        np.testing.assert_array_equal(row.values, source[2, 1:5])
        np.testing.assert_array_equal(row.source_x, [1, 2, 3, 4])
        np.testing.assert_array_equal(row.mapping.array(row.source_x), [12, 14, 16, 18])
        column = workspace.profile_series(layer, False, 16)
        self.assertEqual(column.index, 3)
        np.testing.assert_array_equal(column.values, source[1:4, 3])
        self.assertIsNone(workspace.profile_series(layer, True, -100))
        self.assertTrue(np.shares_memory(row.values, source))

    def test_xy_coordinates_and_cache_ignore_alignment(self) -> None:
        source = np.array([[30., 9], [10, 1], [20, 4], [20, 5]])
        document = model.Document(Path("xy.csv"), source)
        frame = model.prepare_frame(document, model.default_selection(document, model.ViewMode.XY), model.Limits(), 0)
        self.assertEqual(workspace.coordinate_bounds(frame), ((10, 30), (0, 0)))
        layer = workspace.RenderLayer(1, "xy.csv", frame, "#ff0000", 0.5)
        original = workspace.profile_series(layer)
        moved = workspace.profile_series(replace(layer, x=workspace.AxisMap(3, -10), color="#00ff00"))
        self.assertEqual(original.key, moved.key)
        np.testing.assert_array_equal(moved.source_x, source[:, 0])
        np.testing.assert_array_equal(moved.values, source[:, 1])

    def test_npz_and_mat_expand_with_errors(self) -> None:
        folder = fixture_directory("unit-files/workspace")
        archive = folder / "bundle.npz"
        np.savez(archive, unsupported=np.zeros((2, 3, 4)), signal=np.arange(8), matrix=np.eye(4))
        loaded = workspace.load_file(archive)
        self.assertEqual([doc.key for doc in loaded.documents], ["signal", "matrix"])
        self.assertEqual(len(loaded.errors), 1)
        self.assertIn("unsupported", loaded.errors[0])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            workspace.load_file(archive, "unsupported")
        selected = workspace.load_file(archive, "matrix")
        self.assertEqual(selected.documents[0].key, "matrix")
        mat = folder / "bundle.mat"
        savemat(mat, {"curve": np.arange(5), "surface": np.eye(3)})
        loaded = workspace.load_file(mat)
        self.assertEqual({doc.key for doc in loaded.documents}, {"curve", "surface"})


if __name__ == "__main__":
    unittest.main()
