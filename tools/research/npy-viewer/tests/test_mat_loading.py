"""MAT/NumPy format boundaries, numeric fidelity and shared coordinate modes.

Requirements: viewer data dependencies, scipy and h5py. Usage: unittest discovery.
Fixtures are written under the Git-ignored tmp/npy-viewer-tests directory.
"""

from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import sys
import shutil
import unittest
from unittest.mock import patch

import h5py
import numpy as np
from numpy.typing import NDArray
import scipy.io
from scipy.sparse import csc_matrix
from fixture_store import fixture_directory

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
mat_loader = importlib.import_module("personal_npy_viewer.mat_loader")


class MatLoadingTests(unittest.TestCase):
    """Only supported variables load; file source precision and axes survive."""

    def setUp(self) -> None:
        """Keep generated fixtures in an ignored directory for each test."""
        self.folder = fixture_directory(f"unit-files/mat/{self._testMethodName}")
        self._fixture_number = 0

    def _hdf(self, arrays: dict[str, NDArray[np.generic]], name: str = "modern.mat") -> Path:
        self._fixture_number += 1
        label = Path(name)
        path = self.folder / f"{label.stem}-{self._fixture_number:02d}{label.suffix}"
        with h5py.File(path, "w", userblock_size=512) as archive:
            archive.create_group("#refs#")
            for key, values in arrays.items():
                kind = values.dtype.kind
                if kind in "fc":
                    matlab_class = "single" if values.real.dtype.itemsize == 4 else "double"
                else:
                    matlab_class = "logical" if kind == "b" else values.dtype.name
                stored = values.T
                if kind == "c":
                    stored = np.empty(values.T.shape, dtype=[("real", values.real.dtype), ("imag", values.real.dtype)])
                    stored["real"], stored["imag"] = values.real.T, values.imag.T
                elif kind == "b":
                    stored = values.T.astype(np.uint8)
                dataset = archive.create_dataset(key, data=stored, compression="gzip")
                dataset.attrs["MATLAB_class"] = np.bytes_(matlab_class)
        with path.open("r+b") as stream:
            stream.write(b"MATLAB 7.3 MAT-file, Platform: viewer test, HDF5 schema 1.00 .".ljust(116, b" "))
            stream.write(bytes(8) + b"\x00\x02IM")
        return path

    def test_legacy_and_v73_numeric_precision(self) -> None:
        """Keep all basic dtypes, non-square axes, NaNs and complex components."""
        arrays: dict[str, NDArray[np.generic]] = {
            "real": np.array([[1.25, np.nan, np.inf], [-2.5, -np.inf, 0]], dtype=np.float64),
            "single": np.arange(15, dtype=np.float32).reshape(3, 5) / 7,
            "large": np.array([[2**64 - 1, 2**53 + 1], [0, 2**63]], dtype=np.uint64),
            "signed": np.array([[-2**63, 2**63 - 1]], dtype=np.int64),
            "flags": np.array([[True, False, True], [False, True, False]]),
            "complex_single": np.array([[1 + 2j, -3 + 4j, 5 - 6j]], dtype=np.complex64),
            "complex_double": np.array([[3 + 4j], [-2 - 5j]], dtype=np.complex128),
        }
        for dtype in (np.int8, np.uint8, np.int16, np.uint16, np.int32, np.uint32):
            arrays[np.dtype(dtype).name] = np.arange(6, dtype=dtype).reshape(2, 3)
        modern = self._hdf(arrays, "arrays-测试.MAT")
        legacy = self.folder / "legacy.mat"
        scipy.io.savemat(legacy, arrays, do_compression=True)
        for path in (legacy, modern):
            for key, source in arrays.items():
                with self.subTest(format=path.name, variable=key):
                    loaded = model.load_document(path, key)
                    self.assertEqual(loaded.array.dtype, source.dtype)
                    np.testing.assert_array_equal(loaded.array, source)
                    self.assertEqual(set(loaded.keys), set(arrays))

    def test_v4_and_matlab_generated_v73_fixture(self) -> None:
        """Read both MAT v4 and an independent MATLAB-produced v7.3 fixture."""
        source = np.arange(15).reshape(3, 5) * (1 + 2j)
        path = self.folder / "version4.mat"
        scipy.io.savemat(path, {"matrix": source}, format="4")
        np.testing.assert_array_equal(model.load_document(path).array, source)
        fixture = Path(scipy.io.__file__).parent / "matlab/tests/data/testhdf5_7.4_GLNX86.mat"
        if not fixture.is_file():
            self.skipTest("This SciPy distribution does not include the MATLAB v7.3 fixture.")
        archived = self.folder / fixture.name
        shutil.copyfile(fixture, archived)
        loaded = model.load_document(archived)
        np.testing.assert_allclose(loaded.array, np.pi / 4 * np.arange(9).reshape(1, 9))
        self.assertEqual(loaded.key, "testdouble")

    def test_vector_xy_and_point_cloud_modes_match_numpy(self) -> None:
        """MAT row/column XY/XYZ use exactly the same coordinate interpretation."""
        for length in (1, 9):
            for shape in ((1, length), (length, 1)):
                source = np.arange(length).reshape(shape)
                doc = model.load_document(self._hdf({"vector": source}))
                self.assertEqual(doc.array.shape, shape)
                selection = model.default_selection(doc)
                self.assertEqual(selection.mode, model.ViewMode.SIGNAL)
                frame = model.prepare_frame(doc, selection, model.Limits(), 0)
                np.testing.assert_array_equal(frame.scalar, source.ravel())
        for mode, columns in ((model.ViewMode.XY, 2), (model.ViewMode.POINTS, 3)):
            source = np.arange(7 * columns).reshape(7, columns)
            for array in (source, source.T):
                doc = model.load_document(self._hdf({"coordinates": array}))
                selected = model.default_selection(doc, mode)
                frame = model.prepare_frame(doc, selected, model.Limits(), 0)
                if mode == model.ViewMode.XY:
                    np.testing.assert_array_equal(frame.x_values, source[:, 0])
                    np.testing.assert_array_equal(frame.scalar, source[:, 1])
                    swapped = model.prepare_frame(doc, replace(selected, coordinate_order=(1, 0)), model.Limits(), 0)
                    np.testing.assert_array_equal(swapped.x_values, source[:, 1])
                else:
                    np.testing.assert_array_equal(frame.point_coordinates, source)

    def test_legacy_unsupported_variables_and_selected_only_loading(self) -> None:
        """Unsupported top-level variables report names/types and never hide valid arrays."""
        path = self.folder / "mixed.mat"
        scipy.io.savemat(path, {
            "text": "message", "cell": np.array([["text", 2]], dtype=object),
            "structure": {"field": 3}, "sparse": csc_matrix(np.eye(3)),
            "cube": np.ones((2, 3, 4)), "empty": np.empty((0, 3)),
            "signal": np.arange(7).reshape(1, 7),
        })
        with patch.object(mat_loader, "loadmat", wraps=mat_loader.loadmat) as reader:
            doc = model.load_document(path)
            self.assertEqual(doc.key, "signal")
            self.assertEqual(reader.call_args.kwargs["variable_names"], ["signal"])
        for key, reason in (("text", "char"), ("cell", "cell"), ("structure", "struct"),
                            ("sparse", "sparse"), ("cube", "3D"), ("empty", "empty"), ("missing", "does not exist")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason) as error:
                model.load_document(path, key)
            self.assertIn(str(path), str(error.exception))
            self.assertIn(key, str(error.exception))

    def test_v73_rejects_containers_empty_nd_and_invalid_storage(self) -> None:
        """HDF5 references, metadata and compound types must not masquerade as matrices."""
        path = self._hdf({"signal": np.arange(5).reshape(1, 5), "cube": np.ones((2, 3, 4))})
        with h5py.File(path, "a") as archive:
            cell = archive.create_dataset("cell", (1, 2), dtype=h5py.ref_dtype)
            cell.attrs["MATLAB_class"] = np.bytes_("cell")
            struct = archive.create_group("structure")
            struct.attrs["MATLAB_class"] = np.bytes_("struct")
            sparse = archive.create_group("sparse")
            sparse.attrs["MATLAB_sparse"] = 5
            empty = archive.create_dataset("empty", data=np.array([0, 3], dtype=np.uint64))
            empty.attrs["MATLAB_class"] = np.bytes_("double")
            empty.attrs["MATLAB_empty"] = np.uint8(1)
            wrong = archive.create_dataset("wrong", data=np.ones((2, 3), dtype=np.int8))
            wrong.attrs["MATLAB_class"] = np.bytes_("double")
            archive.create_dataset("generic_hdf", data=np.ones((2, 3)))
            structured = archive.create_dataset("structured", data=np.zeros((2, 3), dtype=[("x", "f8"), ("y", "f8")]))
            structured.attrs["MATLAB_class"] = np.bytes_("double")
        self.assertEqual(model.load_document(path).key, "signal")
        for key, reason in (("cell", "cell"), ("structure", "struct"), ("sparse", "sparse"),
                            ("empty", "empty"), ("cube", "3D"), ("wrong", "does not match"),
                            ("generic_hdf", "MATLAB_class"), ("structured", "structured")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                model.load_document(path, key)

    def test_no_supported_variables_and_numpy_boundaries(self) -> None:
        """NPY/NPZ and MAT reject nonnumeric, empty and higher-rank file arrays."""
        path = self._hdf({"cube": np.ones((2, 3, 4))})
        with self.assertRaisesRegex(ValueError, "no supported.*1D/2D"):
            model.load_document(path)
        rejected = (np.array(5), np.empty((0, 3)), np.ones((2, 3, 4)), np.array(["text"]),
                    np.array([{"x": 1}], dtype=object), np.zeros(2, dtype=[("x", "f8")]))
        for index, array in enumerate(rejected):
            npy = self.folder / f"invalid-{index}.npy"
            np.save(npy, array)
            with self.subTest(dtype=array.dtype, shape=array.shape), self.assertRaises(ValueError) as error:
                model.load_document(npy)
            self.assertIn(str(npy), str(error.exception))
        archive = self.folder / "mixed.npz"
        np.savez(archive, cube=np.ones((2, 3, 4)), vector=np.arange(5))
        self.assertEqual(model.load_document(archive).key, "vector")
        with self.assertRaisesRegex(ValueError, "3D"):
            model.load_document(archive, "cube")

    def test_corrupt_missing_and_invalid_text_errors(self) -> None:
        """Every load failure carries its file path and a nonempty explanation."""
        bad: dict[str, bytes] = {
            "broken.mat": b"not a MAT file", "broken.npy": b"not numpy", "broken.npz": b"not ZIP",
            "ragged.csv": b"1,2\n3\n", "nonnumeric.txt": b"not a matrix\nnot numbers\n",
            "encoding.csv": b"\xff\xfe\x00\x00", "quoted.csv": b'"1,2\n',
        }
        for name, content in bad.items():
            path = self.folder / name
            path.write_bytes(content)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Cannot open file") as error:
                model.load_document(path)
            self.assertIn(str(path), str(error.exception))
        with self.assertRaisesRegex(ValueError, "does not exist"):
            model.load_document(self.folder / "missing.mat")
        with self.assertRaisesRegex(ValueError, "directory"):
            model.load_document(self.folder)


if __name__ == "__main__":
    unittest.main()
