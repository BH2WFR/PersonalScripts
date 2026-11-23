"""Regression coverage for lexical path round trips, Unicode and editor chaining."""

from pathlib import Path
from string import ascii_letters, digits
import os
import plistlib
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/others"))

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QPlainTextEdit, QTabWidget
from text_processor.window import TextProcessor
from utils import ConfigStore, path_text as paths, text_transforms as text


class PathTests(unittest.TestCase):
    def test_file_url_round_trips(self) -> None:
        for original in (r"C:\中文\a #%?.txt", "\\\\server\\share\\a b", "../a b",
                         "folder/file", "./file", "/tmp/file", r"C:file", "//localhost/share/file"):
            with self.subTest(original=original):
                uri = paths.add_file_prefix(original)
                self.assertTrue(uri.startswith("file://"))
                self.assertEqual(paths.add_file_prefix(uri), uri)
                self.assertEqual(paths.remove_file_prefix(uri), paths.forward_path(original))
        self.assertEqual(paths.add_file_prefix(r"\\nas\docs\a b"), "file://nas/docs/a%20b")
        self.assertEqual(paths.remove_file_prefix("FILE://localhost/C:/a%20b"), "C:/a b")
        self.assertEqual(paths.remove_file_prefix(r"file://C:\text"), r"C:\text")

    def test_separators_and_msys_drive_boundaries(self) -> None:
        for sep in paths.SEPARATORS.values():
            for other in paths.SEPARATORS.values():
                with self.subTest(source=sep, target=other):
                    self.assertEqual(paths.convert_separators(sep * 2 + "s" + sep + "f", sep, other),
                                     other * 2 + "s" + other + "f")
            self.assertEqual(paths.from_msys("/c/a/b", sep), "C:" + sep + "a" + sep + "b")
        self.assertEqual(paths.to_msys(r"D:\\a\\b"), "/d/a/b")
        self.assertEqual(paths.to_msys("file://server/share/a"), "//server/share/a")
        self.assertEqual(paths.from_msys("/c", "\\"), "C:\\")
        self.assertEqual(paths.from_msys("/usr/bin", "/"), "/usr/bin")
        self.assertEqual(paths.to_msys("C:file"), "C:file")

    def test_quotes(self) -> None:
        self.assertEqual(paths.remove_quotes("  '\"C:/Jim's\"' "), "C:/Jim's")
        self.assertEqual(paths.remove_quotes(" 'abc\"  "), " 'abc\"  ")
        self.assertEqual(paths.remove_quotes(' " abc " '), " abc ")
        self.assertEqual(paths.add_quotes(" 'abc' ", "'"), " 'abc' ")
        self.assertEqual(paths.transform_quoted_path(' "C:/a" ', paths.to_msys), ' "/c/a" ')

    def test_variable_boundaries_and_syntax(self) -> None:
        env = {"USERPROFILE": r"C:\Users\Me", "APPDATA": r"C:\Users\Me\AppData\Roaming"}
        for style, expected in (("cmd", r"%APPDATA%\a"), ("PowerShell", r"$env:APPDATA\a"),
                                ("Bash", "$APPDATA/a")):
            short = paths.shorten_environment("c:/users/Me/AppData/Roaming/a", style, env)
            self.assertEqual(short, expected)
            self.assertEqual(paths.expand_environment(short, env), env["APPDATA"] + "\\a")
        self.assertEqual(paths.shorten_environment("C:/Users/MeToo", "cmd", env), "C:/Users/MeToo")
        self.assertEqual(paths.expand_environment("$UNKNOWN/a", env), "$UNKNOWN/a")

    def test_home_round_trips(self) -> None:
        home = r"C:\Users\Me"
        absolute = home + r"\my docs\a"
        for value in ("~/my docs/a", "%USERPROFILE%/my docs/a", "$env:USERPROFILE/my docs/a",
                      "$HOME/my docs/a", absolute, "file:///C:/Users/Me/my%20docs/a"):
            self.assertEqual(paths.home_path(value, "Absolute", home=home), absolute)
            self.assertEqual(paths.home_path(value, "~", home=home), "~/my docs/a")
            self.assertEqual(paths.home_path(value, "cmd", home=home), r"%USERPROFILE%\my docs\a")
        self.assertEqual(paths.home_path(home, "PowerShell", home=home), "$env:USERPROFILE")
        self.assertEqual(paths.home_path("~/x", "Bash", home="/home/me"), "$HOME/x")
        self.assertEqual(paths.home_path("$HOME/x", "Absolute", home="/home/me"), "/home/me/x")
        self.assertEqual(paths.home_path(r"C:\Users\Me2", "~", home=home), r"C:\Users\Me2")
        self.assertEqual(paths.home_path("~", "Absolute"), str(Path.home()))


class TextTests(unittest.TestCase):
    def test_alphabets_and_irreversible_case(self) -> None:
        original = ascii_letters + digits
        for style in text.LETTER_STYLES:
            styled = text.style_letters(original, style)
            plain = text.plain_letters(styled)
            with self.subTest(style=style):
                self.assertEqual(plain.lower(), original.lower())
                if style not in {"Squared", "Negative squared", "Negative circled", "Superscript"}:
                    self.assertEqual(plain, original)
        self.assertEqual(text.plain_letters("🅰ⓩℬ𝐮𝟛❽全！㎏"), "AzBu38全！㎏")
        self.assertEqual(text.plain_letters("🅰️ ☀️"), "A ☀️")
        for style in text.LETTER_STYLES:
            with self.subTest(target=style):
                self.assertEqual(text.style_letters("𝟙②３Ⓐℬ🅲𝒶𝔟ｃ！中", style),
                                 text.style_letters("123ABCabc！中", style))

    def test_width_and_spaces(self) -> None:
        narrow = "A 1! ｶﾞﾊﾟ"
        self.assertEqual(text.to_fullwidth(narrow), "Ａ　１！　ガパ")
        self.assertEqual(text.to_halfwidth(text.to_fullwidth(narrow)), narrow)
        self.assertEqual(text.normalize_spaces("a\xa0\u2007\u202f\u3000b\t\n"), "a    b\t\n")
        self.assertEqual(text.expand_ligatures("ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ"), "ff fi fl ffi ffl st st")

    def test_case_with_accents_apostrophes_and_cyrillic(self) -> None:
        self.assertEqual(text.title_words("e\u0301COLE déjà ПРИВЕТ don't ǳUNGLE"),
                         "E\u0301cole Déjà Привет Don't ǲungle")

    def test_pdf_and_lines(self) -> None:
        self.assertEqual(text.clean_pdf("oﬃce\xa0text\u200e\r\nwraps.\x02\n中\n文。\nNext"),
                         "office text wraps.\n中文。\nNext")
        self.assertEqual(text.clean_pdf("hy\u00ad\nphen hy-\nphen"), "hyphen hy-phen")
        self.assertEqual(text.clean_pdf("par\x02\nagraph"), "paragraph")
        self.assertEqual(text.map_lines(" a\r\n\r\n b \n", str.strip), "a\r\n\r\nb\n")
        self.assertEqual(text.remove_blank_lines("\r\n a\r\n \t\r\nb\n  "), " a\r\nb\n")
        self.assertEqual(text.expand_tabs("中\tX\t", 4), "中  X   ")

    def test_hostname(self) -> None:
        self.assertEqual(text.url_hostname("https://user:pass@sub.example.com:443/path"), "sub.example.com")
        self.assertEqual(text.url_hostname("https://[2001:db8::1]:8080/"), "2001:db8::1")
        self.assertEqual(text.url_hostname("例子.测试/a"), "例子.测试")
        self.assertEqual(text.url_hostname("https://[invalid"), "https://[invalid")


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.object(ConfigStore, "directory", return_value=directory))
        self.window = TextProcessor()
        self.addCleanup(self.window.close)

    def test_settings_persist_across_windows_and_merge_independent_changes(self) -> None:
        store = ConfigStore("text-processor.yaml")
        self.assertFalse(store.path.exists())
        self.assertTrue(self.window.chain.isChecked())
        self.assertEqual(self.window.variable_syntax.currentText(), "cmd" if sys.platform == "win32" else "Bash")
        other = TextProcessor()
        self.addCleanup(other.close)
        self.window.chain.click()
        other.variable_syntax.setCurrentText("PowerShell")
        self.assertEqual(store.load(), {"use_result_for_next_operation": False, "variable_syntax": "PowerShell"})
        self.window.close()
        other.close()
        reopened = TextProcessor()
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.chain.isChecked())
        self.assertEqual(reopened.variable_syntax.currentText(), "PowerShell")

    def click(self, label: str) -> None:
        button = next(b for b in self.window.findChildren(QPushButton) if (b.accessibleName() or b.text()) == label)
        button.click()

    def select(self, label: str) -> None:
        box = next(c for c in self.window.findChildren(QComboBox) if c.findText(label) >= 0)
        box.setCurrentText(label)

    def test_spaced_letters_and_home_actions(self) -> None:
        self.window.source.setPlainText("t h i s  i s   a")
        self.select("Join spaced letters")
        self.click("Apply")
        self.assertEqual(self.window.result.toPlainText(), "this is a")
        self.click("Clear all")
        self.window.source.setPlainText("~/folder")
        self.click("To absolute")
        self.assertEqual(self.window.result.toPlainText(), str(Path.home() / "folder"))
        self.select("Bash")
        self.click("To home variable")
        self.assertEqual(self.window.result.toPlainText(), "$HOME/folder")
        self.click("To ~")
        self.assertEqual(self.window.result.toPlainText(), "~/folder")

    def test_clipboard_chaining_wrap_and_clearing(self) -> None:
        original = ' "file:///C:/a%20b" \n' + r"\\nas\share"
        QApplication.clipboard().setText(original)
        self.click("Paste from Clipboard")
        self.click("Quick clean paths")
        self.assertEqual(self.window.result.toPlainText(), "C:/a b\n//nas/share")
        self.assertTrue(self.window.chain.isChecked())
        self.click("Indent")
        self.assertEqual(self.window.result.toPlainText(), "    C:/a b\n    //nas/share")
        self.window.chain.setChecked(False)
        self.click("Indent")
        expected = "\n".join("    " + line for line in original.split("\n"))
        self.assertEqual(self.window.result.toPlainText(), expected)
        self.assertEqual(self.window.source.toPlainText(), original)
        wrap = next(c for c in self.window.findChildren(QCheckBox) if c.text() == "Word wrap")
        self.assertTrue(wrap.isChecked())
        wrap.click()
        self.assertEqual(self.window.result.lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap)
        self.assertTrue(self.window.result.isReadOnly())
        self.click("Clear result")
        self.assertEqual(self.window.result.toPlainText(), "")
        self.assertEqual(self.window.source.toPlainText(), original)
        self.window.chain.setChecked(True)
        self.click("Quick clean paths")
        self.assertEqual(self.window.result.toPlainText(), "C:/a b\n//nas/share")
        self.click("Clear all")
        self.assertEqual(self.window.source.toPlainText(), "")
        self.assertEqual(self.window.result.toPlainText(), "")

    @patch("utils.qt_clipboard.sys", platform="win32")
    def test_get_paths_displays_clipboard_source_and_processed_paths(self, _platform: Mock) -> None:
        clipboard = QApplication.clipboard()
        mime = QMimeData()
        mime.setUrls([QUrl("file:///C:/a%20b/report%2520.txt"), QUrl("file://nas/share/资料"),
                      QUrl("file://localhost/D:/folder"), QUrl("file://localhost/share/doc")])
        mime.setText("Explorer display names")
        clipboard.setMimeData(mime)
        self.window.source.setPlainText("original")
        self.window.result.setPlainText("previous result")
        self.click("Get paths from clipboard")
        self.assertEqual(self.window.result.toPlainText(), "\n".join(
            [r"C:\a b\report%20.txt", r"\\nas\share\资料", r"D:\folder", r"\\localhost\share\doc"]))
        self.assertEqual(clipboard.text(), "Explorer display names")
        self.assertEqual(self.window.source.toPlainText(), "Explorer display names")
        self.assertEqual(len(clipboard.mimeData().urls()), 4)
        clipboard.setText('"C:\\a b.txt"\r\n"file://nas/share/x%20y"')
        self.click("Get paths from clipboard")
        expected = "C:\\a b.txt\n\\\\nas\\share\\x y"
        self.assertEqual(self.window.result.toPlainText(), expected)
        original = '"C:\\a b.txt"\n"file://nas/share/x%20y"'
        self.assertEqual(self.window.source.toPlainText(), original)
        for content in ("unrelated", "", "https://example.com/"):
            clipboard.setText(content)
            self.click("Get paths from clipboard")
            self.assertEqual(self.window.result.toPlainText(), expected)
            self.assertFalse(self.window.clipboard_notice.isHidden())
            self.assertEqual(self.window.source.toPlainText(), content)

    @patch("utils.qt_clipboard.sys", platform="darwin")
    def test_finder_prefers_native_list_then_item_plists_then_file_urls(self, _platform: Mock) -> None:
        native = Mock()
        board = native.NSPasteboard.generalPasteboard.return_value
        board.types.return_value = ["NSFilenamesPboardType"]
        values = ["/Users/甲/file%20 ", r"/Users/甲/a\b"]
        board.propertyListForType_.return_value = values
        mime = QMimeData()
        mime.setUrls([QUrl("file:///Users/a/other%20folder")])
        QApplication.clipboard().setMimeData(mime)
        with patch.dict(sys.modules, {"AppKit": native}):
            self.click("Get paths from clipboard")
            self.assertEqual(self.window.result.toPlainText(), "\n".join(values))
            self.assertEqual(self.window.source.toPlainText(), "\n".join(values))
            board.propertyListForType_.return_value = None
            first, second = Mock(), Mock()
            for item in (first, second):
                item.types.return_value = ["NSFilenamesPboardType"]
            first.dataForType_.return_value = plistlib.dumps(values[:1], fmt=plistlib.FMT_BINARY)
            second.dataForType_.return_value = b"invalid"
            second.stringForType_.return_value = plistlib.dumps(values[1:]).decode()
            board.pasteboardItems.return_value = [first, second]
            self.click("Get paths from clipboard")
            self.assertEqual(self.window.result.toPlainText(), "\n".join(values))
            board.pasteboardItems.return_value = []
            self.click("Get paths from clipboard")
            self.assertEqual(self.window.result.toPlainText(), "/Users/a/other folder")
            self.assertEqual(self.window.source.toPlainText(), "file:///Users/a/other%20folder")

    def test_dedicated_tabs_actions_and_reset_from_current_input(self) -> None:
        tabs = self.window.findChild(QTabWidget)
        assert tabs is not None
        pages = {tabs.tabText(i): tabs.widget(i) for i in range(tabs.count())}

        def press(page: str, label: str) -> None:
            tabs.setCurrentWidget(pages[page])
            next(b for b in tabs.currentWidget().findChildren(QPushButton) if b.text() == label).click()

        self.window.source.setPlainText("hello\xa0world\ncontinues.")
        press("Text", "Clean copied PDF text")
        self.assertEqual(self.window.result.toPlainText(), "hello world continues.")
        self.window.source.setPlainText("edited\xa0input")
        self.click("Reset")
        self.assertEqual(self.window.result.document().toRawText(), "edited\xa0input")
        styles = pages["Letter Style"].findChild(QComboBox)
        assert styles is not None
        self.assertEqual(styles.currentData(), "Normal")
        self.assertEqual(styles.count(), len(text.LETTER_STYLES))
        for i, style in enumerate(text.LETTER_STYLES):
            self.assertEqual(styles.itemData(i), style)
            self.assertEqual(styles.itemText(i).split(), [*style.split(), text.style_letters("123ABCabc", style)])
        styles.setCurrentIndex(styles.findData("Bold"))
        press("Letter Style", "Style letters and digits")
        self.assertIn("𝐞", self.window.result.toPlainText())
        styles.setCurrentIndex(styles.findData("Circled"))
        press("Letter Style", "Style letters and digits")
        self.assertIn("ⓔ", self.window.result.toPlainText())
        styles.setCurrentIndex(0)
        press("Letter Style", "Style letters and digits")
        self.assertEqual(self.window.result.document().toRawText(), "edited\xa0input")
        press("Letter Style", "Restore plain letters and digits")
        self.assertEqual(self.window.result.document().toRawText(), "edited\xa0input")
        self.window.chain.setChecked(False)
        self.window.source.setPlainText("https://a.example/path\nhttps://b.example/x")
        press("URL", "Extract URL hostnames")
        self.assertEqual(self.window.result.toPlainText(), "a.example\nb.example")
        self.click("Apply result to input")
        self.assertEqual(self.window.source.toPlainText(), "a.example\nb.example")
        self.assertEqual(self.window.result.toPlainText(), "a.example\nb.example")
        self.window.source.clear()
        self.click("Reset")
        self.assertEqual(self.window.result.toPlainText(), "")

    def test_regex_chains_and_keeps_failed_edit(self) -> None:
        self.window.source.setPlainText("one\xa0TWO")
        self.click("Indent")
        dialog = self.window.regex
        dialog.match_case.setChecked(False)
        dialog.pattern.setText(r"(?P<first>ONE)\xa0(TWO)")
        dialog.replacement.setText(r"\2 \g<first>")
        dialog._replace()
        self.assertEqual(self.window.result.toPlainText(), "    TWO one")
        dialog.replacement.setText(r"\g<absent>")
        dialog._replace()
        self.assertTrue(dialog.error.text())
        self.assertEqual(self.window.result.toPlainText(), "    TWO one")
        self.assertEqual(self.window.source.document().toRawText(), "one\xa0TWO")
