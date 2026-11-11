"""Verify Unicode edge cases without creating windows or touching the clipboard."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import UnicodeText


class UnicodeTextTests(unittest.TestCase):
    def test_empty_text(self) -> None:
        report = UnicodeText.inspect("")
        self.assertEqual(report.characters, ())
        self.assertEqual([value for _, value in report.statistics.items()], [0, 0, 0, 0, 0])

    def test_encoding_and_code_points_not_graphemes(self) -> None:
        report = UnicodeText.inspect("A中😀e\u0301")
        self.assertEqual(report.statistics.characters, 5)
        self.assertEqual(report.statistics.utf8_bytes, 11)
        self.assertEqual(report.statistics.utf16_bytes, 12)
        self.assertEqual(report.characters[2].columns()[2], "U+1F600")
        self.assertEqual(report.characters[2].utf8, "F0 9F 98 80")
        self.assertEqual(report.characters[2].style, "non_bmp")
        self.assertEqual(report.characters[4].display, "◌\u0301")
        self.assertEqual(report.characters[4].category, "Mn")

    def test_control_names_and_invisible_display_do_not_replace_input(self) -> None:
        text = "\x00\t\r\n \u00a0\u200b\u202e"
        report = UnicodeText.inspect(text)
        self.assertEqual(report.text, text)
        self.assertEqual(report.characters[0].name, "NULL")
        self.assertEqual(report.characters[0].style, "control")
        self.assertEqual(report.characters[1].display, "[TAB]")
        self.assertEqual(report.characters[5].display, "[NBSP]")
        self.assertEqual(report.characters[-1].display, "[RLO]")
        self.assertTrue(all("\n" not in row.display and "\t" not in row.display for row in report.characters))

    def test_crlf_and_trailing_lines(self) -> None:
        text = " a\r\nb\rc\n"
        report = UnicodeText.inspect(text)
        self.assertEqual(report.statistics.lines, 4)
        self.assertEqual(report.statistics.characters, len(text))
        self.assertEqual(report.text, text)
        self.assertEqual(UnicodeText.statistics("\n").lines, 2)

    def test_word_count_keeps_apostrophes(self) -> None:
        self.assertEqual(UnicodeText.statistics("don't l’été a_b 123 中文").words, 5)

    def test_invalid_surrogates_are_not_silently_encoded(self) -> None:
        report = UnicodeText.inspect("a\ud800\udfff")
        self.assertEqual(report.statistics.characters, 3)
        self.assertIsNone(report.statistics.utf8_bytes)
        self.assertIsNone(report.statistics.utf16_bytes)
        self.assertEqual(report.characters[1].category, "Cs")
        self.assertEqual(report.characters[1].display, "\\ud800")
        self.assertEqual(report.characters[1].utf8, "<invalid surrogate>")

    def test_noncharacters_and_private_use(self) -> None:
        report = UnicodeText.inspect("\ufdd0\U0001ffff\ue000")
        self.assertEqual([row.name for row in report.characters[:2]], ["NONCHARACTER"] * 2)
        self.assertEqual(report.characters[2].category, "Co")

    def test_report_retains_original_and_tabular_columns(self) -> None:
        report = UnicodeText.inspect("\tX\n ")
        formatted = UnicodeText.format_report(report)
        self.assertTrue(formatted.startswith("Original text:\n\tX\n \n\n"))
        self.assertIn("\t".join(UnicodeText.COLUMNS), formatted)
        self.assertIn("0\t[TAB]\tU+0009\t9\t09\tCc - Control\tHORIZONTAL TABULATION", formatted)


if __name__ == "__main__":
    unittest.main()
