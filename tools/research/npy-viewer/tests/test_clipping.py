"""Scientific-data and geometry tests for highlighted value clamping.

Requirements: numpy, opencv-python. Usage: unittest discovery in this directory.
"""

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np
from fixture_store import preserve_array, preserve_document

PACKAGE = Path(__file__).resolve().parents[1]
if "personal_npy_viewer" not in sys.modules:
    spec = importlib.util.spec_from_file_location("personal_npy_viewer", PACKAGE / "__init__.py",
                                                submodule_search_locations=[str(PACKAGE)])
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
model = importlib.import_module("personal_npy_viewer.data_model")
clipping = importlib.import_module("personal_npy_viewer.clipping")


class ClippingTests(unittest.TestCase):
    """Clamps affect display buffers, with strict endpoint and gap semantics."""

    def test_bounds_keep_source_values_and_nonfinite_gaps(self) -> None:
        """Clamp both sides without replacing NaN/Inf or altering the source."""
        source = np.array([-10, -2, 0, 2, 10, np.nan, np.inf, -np.inf])
        document = preserve_document(model.Document(Path("signal.npy"), source), "unit-inputs/test_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(-2, 2, model.FilterMode.CLAMP), 0)
        np.testing.assert_array_equal(frame.scalar, source)
        np.testing.assert_array_equal(frame.display_scalar[:5], [-2, -2, 0, 2, 2])
        np.testing.assert_array_equal(frame.clip_kind, [-1, 0, 0, 0, 1, 0, 0, 0])
        np.testing.assert_array_equal(frame.valid, [True] * 5 + [False] * 3)
        self.assertEqual(frame.limits, (-2, 2))

    def test_fractional_bounds_and_exact_integer_source(self) -> None:
        """Fractional bounds do not truncate to integers or round raw uint64 values."""
        source = np.array([0, 1, 2, 3, 2**64 - 1], dtype=np.uint64)
        document = preserve_document(model.Document(Path("integer.npy"), source), "unit-inputs/test_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(0.5, 2.5, model.FilterMode.CLAMP), 0)
        np.testing.assert_array_equal(frame.display_scalar, [0.5, 1, 2, 2.5, 2.5])
        self.assertEqual(model.format_sample(frame.scalar, 4), str(2**64 - 1))

    def test_curve_interpolates_crossings_and_caps(self) -> None:
        """A segment crossing both bounds gets two exact horizontal cap intervals."""
        result = clipping.clip_curve(preserve_array(np.array([-4.0, 4.0]), "values", "unit-inputs/test_clipping"), preserve_array(np.ones(2, dtype=np.bool_), "valid", "unit-inputs/test_clipping"),
                                      model.Limits(-2, 2, model.FilterMode.CLAMP), 10)
        np.testing.assert_allclose(result.x, [10, 10.25, 10.75, 11])
        np.testing.assert_allclose(result.y, [-2, -2, 2, 2])
        np.testing.assert_allclose(result.cap_x, [10, 10.25, np.nan, 10.75, 11, np.nan])
        np.testing.assert_allclose(result.cap_y, [-2, -2, np.nan, 2, 2, np.nan])

    def test_caps_never_bridge_missing_samples(self) -> None:
        """Clipped samples adjacent to a hole remain disconnected."""
        result = clipping.clip_curve(preserve_array(np.array([5.0, np.nan, 5.0]), "values", "unit-inputs/test_clipping"),
                                      preserve_array(np.array([True, False, True]), "valid", "unit-inputs/test_clipping"),
                                      model.Limits(None, 1, model.FilterMode.CLAMP))
        np.testing.assert_allclose(result.y, [1, np.nan, 1])
        self.assertEqual(result.cap_x.size, 0)

    def test_equal_bounds_and_large_crossing(self) -> None:
        """Degenerate intervals and extreme finite values produce finite geometry."""
        result = clipping.clip_curve(preserve_array(np.array([-1e308, 1e308]), "values", "unit-inputs/test_clipping"), preserve_array(np.ones(2, dtype=np.bool_), "valid", "unit-inputs/test_clipping"),
                                      model.Limits(0, 0, model.FilterMode.CLAMP))
        np.testing.assert_allclose(result.x, [0, 0.5, 0.5, 1])
        np.testing.assert_array_equal(result.y, np.zeros(4))

    def test_crop_outline_and_hide_compatibility(self) -> None:
        """2D outlines follow the cropped region; hide mode retains former gaps."""
        source = np.zeros((12, 12))
        source[3:9, 3:9] = 10
        document = preserve_document(model.Document(Path("matrix.npy"), source), "unit-inputs/test_clipping")
        selection = model.default_selection(document)
        frame = model.prepare_frame(document, selection, model.Limits(None, 2, model.FilterMode.CLAMP),
                                    0, model.Crop(2, 9, 2, 9))
        self.assertEqual(frame.clip_outline.shape, (8, 8))
        self.assertTrue(frame.clip_outline[1, 1])
        self.assertFalse(frame.clip_outline[4, 4])
        self.assertEqual(frame.display_scalar[4, 4], 2)
        hidden = model.prepare_frame(document, selection, model.Limits(None, 2), 0)
        self.assertFalse(hidden.valid[4, 4])
        self.assertFalse(hidden.clip_kind.any())
        self.assertIsNone(hidden.clip_outline)

    def test_nonfinite_bounds_rejected(self) -> None:
        """Reject unusable bounds before constructing rendering buffers."""
        document = preserve_document(model.Document(Path("signal.npy"), np.arange(3)), "unit-inputs/test_clipping")
        for lower, upper in ((np.nan, None), (None, np.inf), (-np.inf, 2)):
            with self.assertRaises(ValueError):
                model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(lower, upper, model.FilterMode.CLAMP), 0)


if __name__ == "__main__":
    unittest.main()
