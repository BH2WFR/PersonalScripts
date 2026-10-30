"""Check explicit 3D channel splitting, axis fidelity and strict default loaders.

Requirements: viewer dependencies. Run via unittest discovery; generated files
stay under ignored tmp through fixture_store, never in manual test-matrixes.
"""

import importlib
from unittest import TestCase

import h5py
import numpy as np
from scipy.io import savemat

from fixture_store import fixture_directory
from test_data_model import model

catalog = importlib.import_module("personal_matrix_viewer.import_catalog")
workspace = importlib.import_module("personal_matrix_viewer.workspace")


class Rank3ImportTests(TestCase):
    """Only explicit splits admit rank 3; output order, shape and values survive."""

    def setUp(self) -> None:
        self.folder = fixture_directory(f"unit-files/rank3/{self._testMethodName}")

    def test_all_axes_and_numeric_formats(self) -> None:
        """NPY, NPZ and both MAT formats preserve channel ordering and dtype."""
        values = np.arange(120, dtype=np.float64).reshape(4, 5, 6)
        paths = [self.folder / name for name in ("channels.npy", "channels.npz", "legacy.mat", "modern.mat")]
        np.save(paths[0], values)
        np.savez(paths[1], channels=values, ordinary=values[0])
        savemat(paths[2], {"channels": values})
        with h5py.File(paths[3], "w", userblock_size=512) as archive:
            node = archive.create_dataset("channels", data=values.transpose())
            node.attrs["MATLAB_class"] = np.bytes_("double")
        for path in paths:
            key = None if path.suffix == ".npy" else "channels"
            metadata = catalog.inspect_source(path)
            member = next(item for item in metadata.members if item.key == key)
            self.assertEqual(member.shape, values.shape)
            self.assertFalse(member.error)
            with self.assertRaises(ValueError):
                model.load_document(path, key)
            for axis in catalog.SplitAxis:
                with self.subTest(path=path.name, axis=axis):
                    loaded = workspace.load_file(path, choices=(catalog.ImportChoice(key, split_axis=axis),))
                    self.assertEqual(len(loaded.documents), values.shape[axis])
                    for index, doc in enumerate(loaded.documents):
                        np.testing.assert_array_equal(doc.array, np.take(values, index, axis=axis))
                        self.assertEqual(doc.array.dtype, values.dtype)
                        self.assertEqual(doc.array.ndim, 2)
                        assert doc.key is not None
                        self.assertIn(f"axis {axis.value}, channel {index}", doc.key)
                        self.assertEqual(model.default_selection(doc).mode, model.ViewMode.MATRIX)

    def test_complex_and_mixed_archive(self) -> None:
        """Other members remain independent, including complex and invalid data."""
        path = self.folder / "mixed.npz"
        values = np.arange(120, dtype=np.float32).reshape(4, 5, 6).astype(np.complex64)
        values.imag = -values.real
        np.savez(path, complex_channels=values, signal=np.arange(9), rank4=np.zeros((2, 2, 2, 2)),
                 objects=np.array([[[object()]]], dtype=object), empty=np.zeros((2, 0, 3)))
        members = {item.key: item for item in catalog.inspect_source(path).members}
        self.assertFalse(members["complex_channels"].error)
        for key in ("rank4", "objects", "empty"):
            self.assertTrue(members[key].error)
        loaded = workspace.load_file(path, choices=(catalog.ImportChoice("signal"),
                    catalog.ImportChoice("complex_channels", split_axis=catalog.SplitAxis.THIRD)))
        self.assertEqual(len(loaded.documents), 7)
        self.assertEqual(loaded.documents[0].key, "signal")
        for index, doc in enumerate(loaded.documents[1:]):
            self.assertTrue(doc.is_complex)
            np.testing.assert_array_equal(doc.array, values[..., index])
        with self.assertRaises(ValueError):
            workspace.load_file(path, choices=(catalog.ImportChoice("complex_channels"),))
        with self.assertRaises(ValueError):
            workspace.load_file(path, choices=(catalog.ImportChoice("signal", split_axis=catalog.SplitAxis.THIRD),))
