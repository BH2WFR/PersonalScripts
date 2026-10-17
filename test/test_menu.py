"""Single- and multiple-selection menu regressions using simulated terminal input.

Run: conda run -n base python -m unittest discover -s test -p test_menu.py
"""

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402


class MenuTests(unittest.TestCase):
    """Check return contracts, aliases, defaults and invalid-entry handling."""

    def setUp(self) -> None:
        self.options = [MenuOption(["1", "A"], "First", "first"),
                        MenuOption(["2", "B"], "Second", "second"),
                        MenuOption(["3", "C"], "Third", "third")]

    def test_multiple_keys_and_aliases_preserve_input_order(self) -> None:
        with patch("builtins.input", return_value=" 2, a,1,3,B "), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True), ["second", "first", "third"])

    def test_multi_returns_list_for_single_selection_and_empty_input(self) -> None:
        with patch("builtins.input", side_effect=["1", ""]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True), ["first"])
            self.assertEqual(Menu.select(self.options, allow_multiple=True), [])

    def test_multiple_defaults_use_same_parsing_and_deduplication(self) -> None:
        with patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True, default_key="b,1,2", required=True),
                             ["second", "first"])

    def test_invalid_multiple_default_fails_before_prompting(self) -> None:
        with patch("builtins.input", side_effect=AssertionError("Unexpected prompt")):
            with self.assertRaises(ValueError):
                Menu.select(self.options, allow_multiple=True, default_key="1,missing")

    def test_invalid_or_empty_item_retries_the_whole_entry(self) -> None:
        with patch("builtins.input", side_effect=["1,no", "1,,2", ",1", "1,", "3,2"]) as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True), ["third", "second"])
        self.assertEqual(prompt.call_count, 5)

    def test_required_multiple_selection_retries_blank_input(self) -> None:
        with patch("builtins.input", side_effect=["", "1,3"]) as prompt, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True, required=True), ["first", "third"])
        self.assertEqual(prompt.call_count, 2)

    def test_custom_tokens_are_returned_without_range_expansion(self) -> None:
        with patch("builtins.input", return_value="1,4-6,custom,4-6,Custom"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options, allow_multiple=True, accept_custom_string=True),
                             ["first", "4-6", "custom", "Custom"])

    def test_deduplication_uses_options_not_unhashable_values(self) -> None:
        first: list[int] = [1]
        second: list[int] = [1]
        options = [MenuOption(["1", "A"], "First", first), MenuOption(["2"], "Second", second)]
        with patch("builtins.input", return_value="1,a,2"), contextlib.redirect_stdout(io.StringIO()):
            result = Menu.select(options, allow_multiple=True)
        self.assertEqual(result, [[1], [1]])
        self.assertIs(result[0], first)
        self.assertIs(result[1], second)

    def test_single_mode_contract_is_unchanged(self) -> None:
        with patch("builtins.input", side_effect=["a", "", "", "1,2"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options), "first")
            self.assertIsNone(Menu.select(self.options))
            self.assertEqual(Menu.select(self.options, default_key="2"), "second")
            self.assertEqual(Menu.select(self.options, accept_custom_string=True), "1,2")

    def test_single_mode_rejects_multiple_keys(self) -> None:
        with patch("builtins.input", side_effect=["1,2", "3"]) as prompt, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(self.options), "third")
        self.assertEqual(prompt.call_count, 2)

    def test_exact_comma_key_takes_precedence(self) -> None:
        options = [*self.options, MenuOption(["1,2"], "Combined", "combined")]
        with patch("builtins.input", return_value="1,2"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Menu.select(options, allow_multiple=True), ["combined"])

    def test_interrupt_and_eof_keep_existing_exit_behavior(self) -> None:
        with patch("builtins.input", side_effect=KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                Menu.select(self.options, allow_multiple=True)
        with patch("builtins.input", side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exit_result:
                Menu.select(self.options, allow_multiple=True)
        self.assertEqual(exit_result.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
