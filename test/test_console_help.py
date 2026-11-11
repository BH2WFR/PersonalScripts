"""Verify authored help preserves argparse validation and output semantics."""

import contextlib
import io
import unittest

from utils import Console


class AuthoredHelpTests(unittest.TestCase):
    def test_help_exits_before_required_argument_validation(self) -> None:
        parser = Console.argument_parser("Example\n\nRequirements:\n  Runtime.\n\nUsage:\n  tool PATH\n")
        parser.add_argument("path")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue(), parser.format_help())
        self.assertNotIn("options:", output.getvalue())

    def test_argument_validation_and_error_usage_remain_available(self) -> None:
        parser = Console.argument_parser("Short help.")
        parser.add_argument("--count", type=int, required=True)
        self.assertEqual(parser.parse_args(["--count", "3"]).count, 3)
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--count", "invalid"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("usage:", error.getvalue())
        self.assertIn("--count", error.getvalue())

    def test_explicit_output_stream_preserves_layout_and_percent_signs(self) -> None:
        parser = Console.argument_parser("100% complete\n  Indented detail.\n\n")
        output = io.StringIO()
        parser.print_help(file=output)
        self.assertEqual(output.getvalue(), "100% complete\n  Indented detail.\n")

    def test_subparsers_retain_native_construction_and_help(self) -> None:
        parser = Console.argument_parser("Parent help.")
        commands = parser.add_subparsers(dest="command", required=True)
        child = commands.add_parser("inspect", description="Inspect an item.")
        child.add_argument("path")
        parsed = parser.parse_args(["inspect", "sample"])
        self.assertEqual((parsed.command, parsed.path), ("inspect", "sample"))
        self.assertIn("Inspect an item.", child.format_help())


if __name__ == "__main__":
    unittest.main()
