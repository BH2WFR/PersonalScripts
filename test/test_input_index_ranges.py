"""Verify reusable range parsing and interactive selection without external tools.

Run: conda run -n base python -m unittest discover -s test -p test_input_index_ranges.py
"""

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402


class MergeIntegerRangesTests(unittest.TestCase):
    """Verify reusable selection compaction for arbitrary integer iterables."""

    def test_empty_singleton_and_contiguous_values(self) -> None:
        self.assertEqual(Input.merge_integer_ranges([]), ())
        self.assertEqual(Input.merge_integer_ranges([7]), ((7, 7),))
        self.assertEqual(Input.merge_integer_ranges(range(3, 1046)), ((3, 1045),))

    def test_unsorted_duplicates_are_normalized_without_mutation(self) -> None:
        values = [5, 2, 1, 2, 3, 8, 7]
        original = values.copy()
        self.assertEqual(Input.merge_integer_ranges(values), ((1, 3), (5, 5), (7, 8)))
        self.assertEqual(values, original)

    def test_signed_values_and_single_pass_generator(self) -> None:
        values = (number for number in (2, -3, -1, 0, -2, 5))
        self.assertEqual(Input.merge_integer_ranges(values), ((-3, 0), (2, 2), (5, 5)))
        self.assertEqual(tuple(values), ())

    def test_compacted_ranges_preserve_the_integer_selection(self) -> None:
        values = (5, -2, 0, -1, 5, 8, 7, 6, 20)
        spans = Input.merge_integer_ranges(values)
        text = Input.format_integer_ranges(spans)
        self.assertEqual(Input.parse_integer_ranges(text), tuple(sorted(set(values))))


class FormatIntegerRangesTests(unittest.TestCase):
    """Verify range formatting composes with parsing and preserves sequences."""

    def test_compact_format_and_empty_input(self) -> None:
        self.assertEqual(Input.format_integer_ranges(((1, 3), (5, 5))), "1-3,5")
        self.assertEqual(Input.format_integer_ranges(()), "")

    def test_signed_descending_and_duplicate_ranges_round_trip(self) -> None:
        spans = ((-3, -1), (2, -1), (0, 0), (5, 5), (5, 5))
        values = (span for span in spans)
        text = Input.format_integer_ranges(values)
        self.assertEqual(text, "-3--1,2--1,0,5,5")
        self.assertEqual(Input.parse_integer_ranges(text), (-3, -2, -1, 2, 1, 0, -1, 0, 5, 5))
        self.assertEqual(tuple(values), ())


class InputIntegerRangesTests(unittest.TestCase):
    """Cover literal signed sequences independently of collection indexes."""

    def test_order_duplicates_and_signed_ranges(self) -> None:
        examples: dict[str, tuple[int, ...]] = {
            "": (), " \t ": (), "0": (0,), "-0,+0": (0, 0),
            "1,2": (1, 2), "1-3,4": (1, 2, 3, 4),
            "-1, -2": (-1, -2), "-3--1": (-3, -2, -1),
            "-1--3": (-1, -2, -3), "-2-2": (-2, -1, 0, 1, 2),
            "2--2": (2, 1, 0, -1, -2), "3-1,2,2": (3, 2, 1, 2, 2),
            " +1 - +3 , -2 , 3,1 ": (1, 2, 3, -2, 3, 1),
            "100000000000000000000": (100000000000000000000,),
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_integer_ranges(text), expected)

    def test_zero_restriction_includes_range_interiors(self) -> None:
        for text in ("0", "-0", "+0", "0-2", "-2-0", "-2-2", "2--2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_integer_ranges(text, allow_zero=False)
        self.assertEqual(Input.parse_integer_ranges("-3--1,2-1", allow_zero=False), (-3, -2, -1, 2, 1))
        self.assertEqual(Input.parse_integer_ranges("", allow_zero=False), ())

    def test_malformed_expressions(self) -> None:
        for text in ("1,,2", ",", "1,", "a", "1.5", "1-", "--1", "1 2", "1-2-3"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_integer_ranges(text)

    def test_blank_defaults_and_literal_zero(self) -> None:
        cases: tuple[tuple[str, str | None, tuple[int, ...] | None], ...] = (
            ("", None, None), (" \t ", "", None), ("", "  ", None),
            ("", "0", (0,)), ("0", None, (0,)),
            ("", "2--1", (2, 1, 0, -1)), ("-2", "1", (-2,)),
        )
        for text, default, expected in cases:
            with (
                self.subTest(text=text, default=default),
                patch("builtins.input", return_value=text), contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(Input.input_integer_ranges("Values", default=default), expected)

    def test_invalid_input_can_be_retried_or_left_blank(self) -> None:
        for answer, expected in (("", None), ("-2,3-1", (-2, 3, 2, 1))):
            with (
                self.subTest(answer=answer), patch("builtins.input", side_effect=["-1-1", answer]) as prompt,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(Input.input_integer_ranges("Values", allow_zero=False), expected)
                self.assertEqual(prompt.call_count, 2)

    def test_invalid_default_fails_before_prompting(self) -> None:
        with patch("builtins.input") as prompt, self.assertRaises(ValueError):
            Input.input_integer_ranges("Values", default="-1-1", allow_zero=False)
        prompt.assert_not_called()

    def test_cancellation_propagates(self) -> None:
        for error in (KeyboardInterrupt(), EOFError()):
            with (
                self.subTest(error=type(error).__name__), patch("builtins.input", side_effect=error),
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(error)),
            ):
                Input.input_integer_ranges("Values")


class InputIndexRangesTests(unittest.TestCase):
    """Cover signed endpoints, bounds, duplicate selections, and input recovery."""

    def test_supported_selections(self) -> None:
        examples: dict[str, tuple[int, ...]] = {
            "": (), " \t ": (), "1,2": (0, 1), "1-3,4": (0, 1, 2, 3),
            "2,3,4": (1, 2, 3), "-1, -2": (8, 9), "-3--1": (7, 8, 9),
            " 1 - 3 , -2 , 3,1 ": (0, 1, 2, 8),
            "2-2": (1,), "+1,+2": (0, 1), "10,-1": (9,),
            "1--1": tuple(range(10)), "-10-2": (0, 1),
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_index_ranges(text, item_count=10), expected)

    def test_invalid_selections(self) -> None:
        for text in ("0", "-0", "11", "-11", "1-11", "3-1", "-1--3",
                     "1,,2", ",", "1,", "a", "1.5", "1-", "--1", "1 2", "1-2-3"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_index_ranges(text, item_count=10)

    def test_empty_collection(self) -> None:
        self.assertEqual(Input.parse_index_ranges("", item_count=0), ())
        with self.assertRaises(ValueError):
            Input.parse_index_ranges("1", item_count=0)
        with self.assertRaises(ValueError):
            Input.parse_index_ranges("", item_count=-1)

    def test_interactive_blank_and_custom_default(self) -> None:
        for default, expected in ((None, None), ("", None), ("  ", None), ("1,-1", (0, 9))):
            with (
                self.subTest(default=default), patch("builtins.input", return_value="  "),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(Input.input_index_ranges("Skip", item_count=10, default=default), expected)

    def test_zero_based_selections(self) -> None:
        examples: dict[str, tuple[int, ...]] = {
            "0": (0,), "0-2,4": (0, 1, 2, 4), "1,2": (1, 2),
            "-1,-2": (8, 9), "-3--1": (7, 8, 9), "-10-2": (0, 1, 2),
            "0--1": tuple(range(10)), "0,-10,-0": (0,), "9,-1": (9,),
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_index_ranges(text, item_count=10, allow_zero=True), expected)
        for text in ("10", "-11", "0-10", "2-0", "-1--3"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_index_ranges(text, item_count=10, allow_zero=True)

    def test_zero_based_empty_and_single_item_collections(self) -> None:
        self.assertEqual(Input.parse_index_ranges("", item_count=0, allow_zero=True), ())
        self.assertEqual(Input.parse_index_ranges("0,-1", item_count=1, allow_zero=True), (0,))
        for text in ("0", "-1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_index_ranges(text, item_count=0, allow_zero=True)

    def test_zero_based_interactive_default_and_numbering_hint(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", return_value=""), contextlib.redirect_stdout(output):
            self.assertEqual(Input.input_index_ranges("Select", item_count=3, allow_zero=True, default="0"), (0,))
        self.assertIn("zero-based (0 = first)", output.getvalue())
        with patch("builtins.input", return_value="0"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Input.input_index_ranges("Select", item_count=3, allow_zero=True), (0,))

    def test_invalid_input_then_blank_returns_none(self) -> None:
        with patch("builtins.input", side_effect=["0", ""]), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(Input.input_index_ranges("Skip", item_count=3))

    def test_invalid_count_fails_before_prompting(self) -> None:
        with patch("builtins.input") as prompt, self.assertRaises(ValueError):
            Input.input_index_ranges("Skip", item_count=-1)
        prompt.assert_not_called()

    def test_interactive_retries_then_accepts(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", side_effect=["0", "11", "1-3, -1"]), contextlib.redirect_stdout(output):
            self.assertEqual(Input.input_index_ranges("Skip", item_count=10), (0, 1, 2, 9))
        self.assertIn("zero is invalid", output.getvalue())

    def test_invalid_default_fails_before_prompting(self) -> None:
        with patch("builtins.input") as prompt, self.assertRaises(ValueError):
            Input.input_index_ranges("Skip", item_count=10, default="11")
        prompt.assert_not_called()

    def test_cancellation_propagates(self) -> None:
        for error in (KeyboardInterrupt(), EOFError()):
            with (
                self.subTest(error=type(error).__name__), patch("builtins.input", side_effect=error),
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(error)),
            ):
                Input.input_index_ranges("Skip", item_count=10)


if __name__ == "__main__":
    unittest.main()
