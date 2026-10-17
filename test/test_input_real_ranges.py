"""Real-interval parsing and interactive input regression coverage.

Run: conda run -n base python -m unittest discover -s test -p test_input_real_ranges.py
"""

import contextlib
import io
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402


class InputRealRangesTests(unittest.TestCase):
    """Keep continuous ranges distinct from integer sequences and item indexes."""

    def test_signed_decimal_and_reversed_endpoints(self) -> None:
        examples = {
            "": (), "  ": (), "15": ((15.0, 15.0),),
            "13.5,14.5-15": ((13.5, 13.5), (14.5, 15.0)),
            "-2.5--1,0-3,-1-1": ((-2.5, -1.0), (0.0, 3.0), (-1.0, 1.0)),
            "1--1": ((-1.0, 1.0),), "-1--2.5": ((-2.5, -1.0),),
            " +.5 - +1. , -0 ": ((0.5, 1.0), (0.0, 0.0)),
            "1e-3-2e+1,-2E-2--1e-2": ((0.001, 20.0), (-0.02, -0.01)),
            "2,1-3,2": ((2.0, 2.0), (1.0, 3.0), (2.0, 2.0)),
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_real_ranges(text), expected)

    def test_unbounded_intervals(self) -> None:
        examples = {
            "-inf-inf": ((-math.inf, math.inf),),
            "-INF--1,0-+Infinity": ((-math.inf, -1.0), (0.0, math.inf)),
            "inf--inf": ((-math.inf, math.inf),),
            "2.5-inf": ((2.5, math.inf),),
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_real_ranges(text), expected)
                with self.assertRaises(ValueError):
                    Input.parse_real_ranges(text, allow_infinity=False)

    def test_zero_policy_includes_interval_interior(self) -> None:
        for text in ("0", "-0.0", "-1-1", "1--1", "0-3", "-inf-inf"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_real_ranges(text, allow_zero=False)
        self.assertEqual(Input.parse_real_ranges("-2.5--1,1-inf", allow_zero=False),
                         ((-2.5, -1.0), (1.0, math.inf)))

    def test_invalid_expressions_and_overflow(self) -> None:
        for text in ("nan", "NaN-1", "1,,2", ",", "1,", "1-", "--1", "1 2", "1-2-3",
                     ".", "1e", "1e9999", "-1e9999-0", "inf", "-inf", "inf-inf", "-inf--inf"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_real_ranges(text)

    def test_ranges_filter_values_without_expanding(self) -> None:
        ranges = Input.parse_real_ranges("13.5,14.5-15")
        selected = [size for size in (13, 13.5, 14, 14.5, 14.75, 15, 15.5)
                    if any(low <= size <= high for low, high in ranges)]
        self.assertEqual(selected, [13.5, 14.5, 14.75, 15])
        self.assertEqual(Input.parse_integer_ranges("1--1"), (1, 0, -1))
        self.assertEqual(Input.parse_index_ranges("1--1", item_count=4), (0, 1, 2, 3))
        for text in ("1.5", "1.0", "0.0", "inf"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_index_ranges(text, item_count=4, allow_zero=True)

    def test_interactive_defaults_blank_and_zero(self) -> None:
        for text, default, expected in (
            ("", None, None), ("", "  ", None), ("", "0", ((0.0, 0.0),)),
            ("0", "1-2", ((0.0, 0.0),)), ("", "-2.5--1", ((-2.5, -1.0),)),
        ):
            with self.subTest(text=text, default=default), patch("builtins.input", return_value=text), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(Input.input_real_ranges("Sizes", default=default), expected)

    def test_interactive_retries_and_validates_defaults_before_prompting(self) -> None:
        with patch("builtins.input", side_effect=["0", "1-inf", "1.5-2.5"]) as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Input.input_real_ranges("Range", allow_zero=False, allow_infinity=False),
                             ((1.5, 2.5),))
            self.assertEqual(prompt.call_count, 3)
        with patch("builtins.input") as prompt, self.assertRaises(ValueError):
            Input.input_real_ranges("Range", default="-1-1", allow_zero=False)
        prompt.assert_not_called()

    def test_interruption_propagates(self) -> None:
        for error in (KeyboardInterrupt(), EOFError()):
            with self.subTest(error=type(error).__name__), patch("builtins.input", side_effect=error), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(error)):
                Input.input_real_ranges("Range")


if __name__ == "__main__":
    unittest.main()
