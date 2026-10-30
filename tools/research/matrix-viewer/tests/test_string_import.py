"""String source fidelity, safe format boundaries and raw-only preparation.

Requirements: viewer dependencies, scipy and h5py. Usage: unittest discovery.
Fixtures stay in the ignored automated-test directory.
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


class StringImportTests(TestCase):
    """Strings never pass through numeric conversion, filtering or plotting."""

    def setUp(self) -> None:
        self.folder = fixture_directory(f"unit-files/strings/{self._testMethodName}")

    def test_npy_npz_strings_preserve_values_and_shape(self) -> None:
        """Unicode and byte arrays, including number-like text, remain strings."""
        for index, values in enumerate((np.array(["alpha", "中文", "", "🙂"]),
                                        np.array([["3.14", "NaN"], ["+Inf", "two"]]),
                                        np.array([b"hello", b"\xff", "图像".encode("utf-8")]))):
            for suffix in ("npy", "npz"):
                path = self.folder / f"strings-{index}.{suffix}"
                if suffix == "npy":
                    np.save(path, values)
                else:
                    np.savez(path, words=values, numeric=np.arange(8))
                key = "words" if suffix == "npz" else None
                inspected = catalog.inspect_source(path)
                self.assertFalse(inspected.members[0].error)
                loaded = workspace.load_file(path, choices=(catalog.ImportChoice(key),))
                doc = loaded.documents[0]
                self.assertTrue(doc.is_text)
                self.assertEqual(doc.array.dtype, values.dtype)
                selection = model.default_selection(doc, model.ViewMode.POINTS)
                self.assertEqual(selection.mode, model.ViewMode.RAW)
                frame = model.prepare_frame(doc, selection, model.Limits(10, 20), 0)
                np.testing.assert_array_equal(frame.raw, values)
                self.assertIs(frame.raw, doc.array)
                self.assertEqual(frame.scalar.size, 0)
                self.assertIsNone(frame.surface)
                with self.assertRaisesRegex(ValueError, "Raw data"):
                    _ = doc.numeric_array
                with self.assertRaisesRegex(ValueError, "Raw data"):
                    _ = frame.numeric_raw
                with self.assertRaisesRegex(ValueError, "Raw data"):
                    model._extract_raw(doc, selection, model.Crop())

    def test_mat_character_matrices(self) -> None:
        """Legacy and v7.3 character matrices use the same raw-only mode."""
        legacy = self.folder / "words-v5.mat"
        savemat(legacy, {"words": np.array(["hello", "world"])})
        modern = self.folder / "words-v73.mat"
        values = np.array([list("你好A"), list("世界B")])
        codes = np.array([[ord(char) for char in row] for row in values], dtype=np.uint16)
        with h5py.File(modern, "w", userblock_size=512) as archive:
            node = archive.create_dataset("words", data=codes.T)
            node.attrs["MATLAB_class"] = np.bytes_("char")
        for path, expected in ((legacy, np.array([list("hello"), list("world")])), (modern, values)):
            self.assertFalse(catalog.inspect_source(path).members[0].error)
            doc = model.load_document(path, "words")
            self.assertTrue(doc.is_text)
            np.testing.assert_array_equal(doc.array, expected)
            self.assertEqual(model.default_selection(doc).mode, model.ViewMode.RAW)

    def test_reject_pickle_structured_and_rank3_text(self) -> None:
        """No object deserialization, string splitting or scalar coercion."""
        rejected = (np.array(["object text"], dtype=object), np.full((2, 3, 4), "text"),
                    np.array("scalar"), np.array([], dtype="U1"), np.zeros(2, dtype=[("name", "U3")]))
        for index, values in enumerate(rejected):
            path = self.folder / f"invalid-{index}.npy"
            np.save(path, values)
            with self.subTest(index=index), self.assertRaises(ValueError):
                model.load_document(path, allow_3d=True)
            with self.assertRaises(ValueError):
                catalog.inspect_source(path)
