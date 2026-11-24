"""Verify shared wheel protection and keyboard/popup behavior with offscreen Qt."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from utils.qt_widgets import (
    NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls,
    configure_qt_application, with_cjk_fallbacks,
)


class QtWidgetTests(unittest.TestCase):
    """Wheel scrolling must not silently change focused settings."""

    @classmethod
    def setUpClass(cls) -> None:
        existing = QtWidgets.QApplication.instance()
        cls.application = existing if isinstance(existing, QtWidgets.QApplication) else QtWidgets.QApplication([])
        cls.application.setStyle("Fusion")

    def wheel(self, widget: QtWidgets.QWidget) -> QtGui.QWheelEvent:
        """Send one scroll step to a widget and return its acceptance state."""
        point = widget.rect().center()
        event = QtGui.QWheelEvent(QtCore.QPointF(point), QtCore.QPointF(widget.mapToGlobal(point)),
                                 QtCore.QPoint(), QtCore.QPoint(0, -120), QtCore.Qt.MouseButton.NoButton,
                                 QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(widget, event)
        return event

    def test_cjk_fallback_order_and_font_attributes(self) -> None:
        original = QtGui.QFont("Editor", 13)
        original.setBold(True)
        original.setItalic(True)
        original.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        installed = ["Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP", "Noto Sans CJK KR", "Sarasa Mono K"]
        self.enterContext(patch.object(QtGui.QFontDatabase, "families", return_value=installed))
        self.addCleanup(QtCore.QLocale.setDefault, QtCore.QLocale())
        for locale, order in (("en_SG", ("SC", "TC", "JP", "KR")), ("zh_TW", ("TC", "SC", "JP", "KR")),
                              ("zh_HK", ("TC", "SC", "JP", "KR")), ("ja_JP", ("JP", "SC", "TC", "KR")),
                              ("ko_KR", ("KR", "SC", "TC", "JP"))):
            with self.subTest(locale=locale):
                QtCore.QLocale.setDefault(QtCore.QLocale(locale))
                font = with_cjk_fallbacks(original)
                self.assertEqual(font.families(), ["Editor", "Sarasa Mono K", *(f"Noto Sans CJK {r}" for r in order)])
                self.assertEqual(original.families(), ["Editor"])
                self.assertTrue(font.bold() and font.italic())
                self.assertEqual(font.styleHint(), original.styleHint())
                self.assertEqual(font.pointSize(), original.pointSize())
                self.assertEqual(with_cjk_fallbacks(font), font)

    def test_application_fallback_reaches_new_dialog_and_editor(self) -> None:
        self.addCleanup(self.application.setFont, self.application.font())
        self.enterContext(patch.object(QtGui.QFontDatabase, "families", return_value=["Noto Sans CJK KR"]))
        configure_qt_application(self.application)
        expected = self.application.font().families()
        self.assertIn("Noto Sans CJK KR", expected)
        configure_qt_application(self.application)
        dialog = QtWidgets.QDialog()
        self.addCleanup(dialog.deleteLater)
        editor = QtWidgets.QPlainTextEdit(dialog)
        self.assertEqual(dialog.font().families(), expected)
        self.assertEqual(editor.document().defaultFont().families(), expected)

    def test_cocoa_includes_installed_rare_script_fonts_after_ui_fonts(self) -> None:
        installed = ["Fixture Alpha", "LastResort", "Fixture Beta", "PingFang SC"]
        self.enterContext(patch.object(sys, "platform", "darwin"))
        self.enterContext(patch.object(QtGui.QGuiApplication, "platformName", return_value="cocoa"))
        self.enterContext(patch.object(QtGui.QFontDatabase, "families", return_value=installed))
        self.enterContext(patch.object(QtGui.QTextLayout, "glyphRuns", return_value=[]))
        font = with_cjk_fallbacks(QtGui.QFont("Editor"))
        self.assertEqual(font.families(), ["Editor", "PingFang SC", "Fixture Alpha", "Fixture Beta"])
        self.assertEqual(with_cjk_fallbacks(font), font)

    def test_no_installed_candidates_preserves_system_fallback(self) -> None:
        font = self.application.font()
        with patch.object(QtGui.QFontDatabase, "families", return_value=[]):
            self.assertEqual(with_cjk_fallbacks(font), font)

    def test_custom_font_allows_merging_and_preserves_other_flags(self) -> None:
        font = QtGui.QFont("Editor")
        strategy = QtGui.QFont.StyleStrategy
        font.setStyleStrategy(strategy.PreferAntialias | strategy.NoFontMerging)
        with patch.object(QtGui.QFontDatabase, "families", return_value=[]):
            self.assertEqual(with_cjk_fallbacks(font).styleStrategy(), strategy.PreferAntialias)
        self.assertTrue(font.styleStrategy() & strategy.NoFontMerging)

    def test_layout_renders_rare_scripts_with_installed_coverage(self) -> None:
        if self.application.platformName() == "offscreen":
            self.skipTest("Requires the native platform font database")
        base = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        font = with_cjk_fallbacks(base)
        families = QtGui.QFontDatabase.families()
        for text in ("𓀀", "𗀀"):
            with self.subTest(character=text):
                if not any(QtGui.QRawFont.fromFont(QtGui.QFont(f)).supportsCharacter(ord(text)) for f in families):
                    self.skipTest(f"No installed font covers U+{ord(text):X}")
                glyphs = [index for run in self._glyph_runs(text, font) for index in run.glyphIndexes()]
                self.assertTrue(glyphs)
                self.assertNotIn(0, glyphs)

    def test_latin_and_emoji_keep_system_faces(self) -> None:
        if self.application.platformName() == "offscreen":
            self.skipTest("Requires the native platform font database")
        base = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
        font = with_cjk_fallbacks(base)
        for text in ("ABC", "😀"):
            with self.subTest(text=text):
                native = self._glyph_runs(text, base)
                if native and all(index for run in native for index in run.glyphIndexes()):
                    self.assertEqual([run.rawFont().familyName() for run in self._glyph_runs(text, font)],
                                     [run.rawFont().familyName() for run in native])

    @staticmethod
    def _glyph_runs(text: str, font: QtGui.QFont) -> list[QtGui.QGlyphRun]:
        layout = QtGui.QTextLayout(text, font)
        layout.beginLayout()
        layout.createLine().setLineWidth(1000)
        layout.endLayout()
        return layout.glyphRuns()

    def test_shared_controls_ignore_focused_wheels_but_keep_keyboard_steps(self) -> None:
        for kind in (NoWheelSpinBox, NoWheelDoubleSpinBox):
            spin = kind()
            self.addCleanup(spin.deleteLater)
            spin.setValue(10)
            spin.show()
            spin.setFocus()
            self.assertFalse(self.wheel(spin).isAccepted())
            self.assertEqual(spin.value(), 10)
            QtTest.QTest.keyClick(spin, QtCore.Qt.Key.Key_Up)
            self.assertEqual(spin.value(), 11)
        combo = NoWheelComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItems(["One", "Two", "Three"])
        combo.show()
        combo.setFocus()
        self.assertFalse(self.wheel(combo).isAccepted())
        self.assertEqual(combo.currentIndex(), 0)
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key.Key_Down)
        self.assertEqual(combo.currentIndex(), 1)

    def test_guard_covers_native_dialogs_and_leaves_popup_scroll_available(self) -> None:
        install_no_wheel_controls(self.application)
        child_count = len(self.application.children())
        install_no_wheel_controls(self.application)
        self.assertEqual(len(self.application.children()), child_count)
        dialog = QtWidgets.QInputDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.setInputMode(QtWidgets.QInputDialog.InputMode.IntInput)
        dialog.setIntValue(10)
        dialog.show()
        self.application.processEvents()
        spin = dialog.findChild(QtWidgets.QSpinBox)
        assert spin is not None
        spin.setFocus()
        self.assertFalse(self.wheel(spin).isAccepted())
        self.assertFalse(self.wheel(spin.lineEdit()).isAccepted())
        self.assertEqual(dialog.intValue(), 10)
        QtTest.QTest.keyClick(spin, QtCore.Qt.Key.Key_Up)
        self.assertEqual(dialog.intValue(), 11)
        combo = NoWheelComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItems([str(index) for index in range(100)])
        combo.setMaxVisibleItems(5)
        combo.show()
        combo.showPopup()
        self.application.processEvents()
        view = combo.view()
        before = view.verticalScrollBar().value()
        self.wheel(view.viewport())
        self.assertGreater(view.verticalScrollBar().value(), before)
        combo.hidePopup()


if __name__ == "__main__":
    unittest.main()
