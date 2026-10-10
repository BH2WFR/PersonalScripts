"""Check heterogeneous workspace archives without writing manual test matrices.

Requirements: viewer dependencies. Usage: unittest discovery.
Arrays and round-trip archives remain in memory.
"""

from dataclasses import replace
from io import BytesIO
import importlib
from pathlib import Path
import unittest

import numpy as np
from openpyxl import load_workbook
from scipy.io import loadmat

from test_data_model import model

bundle = importlib.import_module("personal_npy_viewer.bundle_export")
exports = importlib.import_module("personal_npy_viewer.exporting")
workspace_export = importlib.import_module("personal_npy_viewer.workspace_export")
metadata = importlib.import_module("personal_npy_viewer.image_metadata")


class BundleExportTests(unittest.TestCase):
    """Archives retain independent arrays, native image channels and complex parts."""

    def test_npz_shapes_dtypes_complex_and_safe_unique_names(self) -> None:
        arrays = (np.array([2**64 - 1, 2**63 + 3], dtype=np.uint64),
                  np.arange(20, dtype=np.float32).reshape(4, 5),
                  np.array([1 + 2j, 3 - 4j], dtype=np.complex64),
                  np.array([[np.nan, np.inf, -np.inf]]), np.array([True, False]))
        labels = ("file", "allow_pickle", "../same/name", "same name", "中文")
        sources = tuple((name, model.Document(Path("source.npy"), array)) for name, array in zip(labels, arrays, strict=True))
        snapshots = bundle.prepare_bundle(sources)
        for item, array in zip(snapshots, arrays, strict=True):
            self.assertFalse(np.shares_memory(item.values, array))
        payload = bundle.serialize_bundle(snapshots, exports.ExportFormat.NPZ)
        names = bundle.npz_member_names(snapshots)
        self.assertEqual(len(set(names)), len(arrays))
        self.assertTrue(all("/" not in name and "\\" not in name for name in names))
        with np.load(BytesIO(payload), allow_pickle=False) as archive:
            self.assertEqual(archive.files, list(names))
            for name, array in zip(names, arrays, strict=True):
                self.assertEqual(archive[name].dtype, array.dtype)
                self.assertEqual(archive[name].shape, array.shape)
                np.testing.assert_array_equal(archive[name], array)

    def test_mat_stores_separate_complex_variables_and_column_vectors(self) -> None:
        sources = (("A-B", model.Document(Path("a.npy"), np.arange(12).reshape(3, 4))),
                   ("A B", model.Document(Path("b.npy"), np.array([1 + 2j, 3 - 4j]))))
        snapshots = bundle.prepare_bundle(sources)
        names = workspace_export.mat_variable_names(snapshots)
        archive = loadmat(BytesIO(bundle.serialize_bundle(snapshots, exports.ExportFormat.MAT)))
        self.assertNotEqual(names[0], names[1])
        np.testing.assert_array_equal(archive[names[0]], sources[0][1].array)
        np.testing.assert_array_equal(archive[names[1]], sources[1][1].array[:, None])
        self.assertTrue(np.iscomplexobj(archive[names[1]]))

    def test_excel_sheets_split_complex_and_preserve_large_integer_text(self) -> None:
        sources = (("signal", model.Document(Path("a.npy"), np.array([1 + 2j, 3 - 4j]))),
                   ("counter", model.Document(Path("b.npy"), np.array([2**64 - 1], dtype=np.uint64))),
                   ("gaps", model.Document(Path("c.npy"), np.array([[np.nan, np.inf, -np.inf]]))))
        workbook = load_workbook(BytesIO(bundle.serialize_bundle(bundle.prepare_bundle(sources), exports.ExportFormat.XLSX)))
        try:
            self.assertEqual(workbook.sheetnames, ["signal_real", "signal_imag", "counter", "gaps"])
            self.assertEqual(list(workbook["signal_real"].values), [(1,), (3,)])
            self.assertEqual(list(workbook["signal_imag"].values), [(2,), (-4,)])
            self.assertEqual(workbook["counter"]["A1"].value, str(2**64 - 1))
            self.assertEqual(list(workbook["gaps"].values), [("nan", "inf", "-inf")])
        finally:
            workbook.close()

    def test_images_use_native_pixels_not_displayed_grayscale_or_alpha_weighting(self) -> None:
        for channels in ((model.ImageMember.RED, model.ImageMember.GREEN, model.ImageMember.BLUE, model.ImageMember.ALPHA),
                         (model.ImageMember.MONO, model.ImageMember.ALPHA), (model.ImageMember.MONO,)):
            pixels = np.arange(4 * 5 * len(channels), dtype=np.uint16).reshape(4, 5, len(channels))
            if len(channels) == 1:
                pixels = pixels[..., 0]
            image = model.ImageSource(pixels, channels, metadata.ImageMetadata("PNG", "RGBA", "16-bit", False))
            doc = model.Document(Path("image.png"), np.zeros((4, 5)), is_image=True, image_source=image)
            snapshots = bundle.prepare_bundle((("Photo", doc),))
            self.assertEqual(len(snapshots), len(channels))
            for index, snapshot in enumerate(snapshots):
                expected = pixels if pixels.ndim == 2 else pixels[..., index]
                np.testing.assert_array_equal(snapshot.values, expected)
                self.assertEqual(snapshot.values.dtype, pixels.dtype)

    def test_empty_unsupported_and_snapshot_independence(self) -> None:
        with self.assertRaisesRegex(ValueError, "No matrices"):
            bundle.prepare_bundle(())
        doc = model.Document(Path("matrix.npy"), np.arange(12).reshape(3, 4))
        snapshot = bundle.prepare_bundle((("Matrix", doc),))
        doc.array[:] = 99
        np.testing.assert_array_equal(snapshot[0].values, np.arange(12).reshape(3, 4))
        with self.assertRaisesRegex(ValueError, "single array"):
            bundle.serialize_bundle(snapshot, exports.ExportFormat.NPY)
        with self.assertRaisesRegex(ValueError, "1D/2D"):
            bundle.prepare_bundle((("Bad", replace(doc, array=np.zeros((2, 3, 4)))),))


if __name__ == "__main__":
    unittest.main()
