"""Regression coverage for normalized RGB parsing without optional packages.

Run: conda run -n base python -m unittest discover -s test -p test_input_color.py
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402


class InputColorTests(unittest.TestCase):
    """Validate accepted RGB notations, channel scales and invalid input."""

    def test_equivalent_rgb_notations(self) -> None:
        for text in ("255, 0, 0", "#FF0000", " #f00 ", "rgb(255,0,0)",
                     "RGB(255 0 0)", "rgb(100%, 0%, 0%)", "rgb(100% 0 0%)",
                     "rgb(2.55e2 0 0)"):
            with self.subTest(text=text):
                self.assertEqual(Input.parse_color(text), (1, 0, 0))

    def test_channel_scale_precision_and_bounds(self) -> None:
        cases = {"0,0,0": (0, 0, 0), "#fff": (1, 1, 1),
                 "#123456": (18 / 255, 52 / 255, 86 / 255),
                 "#abc": (170 / 255, 187 / 255, 204 / 255),
                 "1,0,0": (1 / 255, 0, 0), "127.5, 0, 255": (.5, 0, 1),
                 "rgb(50% 25% 0%)": (.5, .25, 0), "rgb(.5 0 0)": (.5 / 255, 0, 0)}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(Input.parse_color(text), expected)

    def test_invalid_or_unsupported_colors(self) -> None:
        for text in ("", " ", "red", "#ggg", "#ff", "#ffff", "#ff000000", "#ff 0000",
                     "255 0 0", "255,0", "255,0,0,1", "255,,0", "255,0,0,", "(255,0,0)",
                     "-1,0,0", "256,0,0", "nan,0,0", "inf,0,0", "1e999,0,0",
                     "rgb(101% 0% 0%)", "rgb(100%,0,0)", "100%,0%,0%",
                     "rgb(255,0 0)", "rgb(255 0 0 / .5)", "rgba(255,0,0,1)",
                     "rgb (255,0,0)", "hsl(0,100%,50%)", "rgb(none 0 0)"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Input.parse_color(text)


if __name__ == "__main__":
    unittest.main()
