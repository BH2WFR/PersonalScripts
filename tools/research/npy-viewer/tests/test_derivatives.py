"""Numerical regression checks for gap-aware, original-sample derivatives.

Requirements: numpy. Usage: unittest discovery in this directory.
"""

import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "personal_npy_viewer"
if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, PACKAGE / "__init__.py", submodule_search_locations=[str(PACKAGE)],
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = package
    spec.loader.exec_module(package)
derivatives = importlib.import_module(f"{PACKAGE_NAME}.derivatives")


class DerivativeTests(unittest.TestCase):
    """Verify finite differences without crossing rejected neighboring pairs."""

    def test_smooth_curve_and_outer_endpoints(self) -> None:
        """Central differences are exact for a quadratic at interior samples."""
        values = np.arange(6, dtype=np.float64) ** 2
        result = derivatives.differentiate(values, np.ones(6, dtype=np.bool_))
        np.testing.assert_allclose(result.values, [1, 2, 4, 6, 8, 9])
        self.assertEqual(len(result.undefined_indices), 0)

    def test_phase_jumps_omit_both_sides(self) -> None:
        """Radians and degree presets reject the same phase-wrap neighbors."""
        radians = np.array([2.7, 2.9, 3.1, -3.0, -2.8, -2.6])
        for scale, threshold in ((1.0, np.pi), (180 / np.pi, 180)):
            result = derivatives.differentiate(radians * scale, np.ones(6, dtype=np.bool_), threshold)
            np.testing.assert_array_equal(result.undefined_indices, [2, 3])
            np.testing.assert_allclose(result.values[[0, 1, 4, 5]], 0.2 * scale)
            self.assertTrue(np.isnan(result.values[2:4]).all())
            self.assertEqual(result.jump_count, 1)

    def test_filtered_and_nonfinite_gaps(self) -> None:
        """Boundary red markers represent visible samples adjacent to gaps."""
        values = np.array([0, 1, np.nan, 3, 4, 5, 6], dtype=np.float64)
        valid = np.array([True, True, True, True, True, False, True])
        result = derivatives.differentiate(values, valid)
        np.testing.assert_array_equal(result.undefined_indices, [1, 3, 4, 6])
        np.testing.assert_array_equal(np.flatnonzero(result.valid), [0])
        self.assertEqual(result.jump_count, 0)

    def test_large_integer_steps_keep_precision(self) -> None:
        """Unit steps above 2**53 survive, including signed/unsigned extremes."""
        for dtype, offset in ((np.uint64, 2**64 - 10), (np.int64, -(2**63)), (np.int64, 2**63 - 10)):
            values = np.array([offset + index for index in range(6)], dtype=dtype)
            for source, slope in ((values, 1), (values[::-1], -1)):
                result = derivatives.differentiate(source, np.ones(6, dtype=np.bool_))
                np.testing.assert_array_equal(result.values, np.full(6, slope))
        limits = np.array([-(2**63), 2**63 - 1], dtype=np.int64)
        result = derivatives.differentiate(limits, np.ones(2, dtype=np.bool_))
        np.testing.assert_allclose(result.values, float(2**64 - 1))

    def test_empty_singleton_and_all_invalid(self) -> None:
        """No difference is invented for empty, isolated or excluded samples."""
        for values, valid, markers in (
            ([], [], []), ([7], [True], [0]), ([7], [False], []),
            ([np.nan, np.inf], [True, True], []),
        ):
            result = derivatives.differentiate(np.array(values, dtype=np.float64), np.array(valid, dtype=np.bool_))
            self.assertFalse(result.valid.any())
            np.testing.assert_array_equal(result.undefined_indices, markers)

    def test_threshold_is_strict_and_optional(self) -> None:
        """A change equal to the threshold remains usable; gaps-only permits jumps."""
        values = np.array([0, 3, 6, 20], dtype=np.float64)
        valid = np.ones(4, dtype=np.bool_)
        result = derivatives.differentiate(values, valid, 3)
        np.testing.assert_array_equal(result.undefined_indices, [2, 3])
        self.assertEqual(result.jump_count, 1)
        self.assertTrue(derivatives.differentiate(values, valid).valid.all())

    def test_overflow_is_undefined(self) -> None:
        """Nonrepresentable differences are omitted rather than drawn as spikes."""
        values = np.array([-1e308, 1e308])
        result = derivatives.differentiate(values, np.ones(2, dtype=np.bool_))
        np.testing.assert_array_equal(result.undefined_indices, [0, 1])

    def test_invalid_shapes_and_thresholds(self) -> None:
        """Reject ambiguous inputs before performing numerical work."""
        with self.assertRaises(ValueError):
            derivatives.differentiate(np.ones((2, 2)), np.ones((2, 2), dtype=np.bool_))
        with self.assertRaises(ValueError):
            derivatives.differentiate(np.ones(2), np.ones(3, dtype=np.bool_))
        for threshold in (0, -1, np.inf, np.nan):
            with self.assertRaises(ValueError):
                derivatives.differentiate(np.ones(2), np.ones(2, dtype=np.bool_), threshold)


if __name__ == "__main__":
    unittest.main()
