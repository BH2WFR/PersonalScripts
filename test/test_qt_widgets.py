"""Verify shared wheel protection and keyboard/popup behavior with offscreen Qt."""

import os
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from utils.gui_colors import BUTTON_COLORS, button_fills, text_hex
from utils.qt_styles import button_stylesheet, is_dark_theme, set_button_style, set_text_style, text_stylesheet
from utils.qt_widgets import (
    NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls,
    configure_qt_application, monospace_ui_font, set_bold, with_cjk_fallbacks,
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

    def test_theme_styles_follow_live_palette_and_clear(self) -> None:
        app = self.application
        self.enterContext(patch.object(QtGui.QStyleHints, "colorScheme", return_value=QtCore.Qt.ColorScheme.Unknown))
        original = app.palette()
        self.addCleanup(app.setPalette, original)
        window = QtWidgets.QWidget()
        label, action = QtWidgets.QLabel("Status", window), QtWidgets.QPushButton("Run", window)
        set_text_style(label, "red")
        set_button_style(action, "blue")
        action.resize(120, 36)
        native = QtWidgets.QPushButton(action.text(), window)
        set_bold(native)
        native.resize(action.size())
        native.setEnabled(False)
        role = QtGui.QPalette.ColorRole
        for dark in (False, True, False):
            palette = QtGui.QPalette(original)
            palette.setColor(role.Window, QtGui.QColor("#252525" if dark else "#fafafa"))
            palette.setColor(role.WindowText, QtGui.QColor("white" if dark else "black"))
            app.setPalette(palette)
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            self.assertEqual(is_dark_theme(), dark)
            self.assertEqual(label.styleSheet(), text_stylesheet("red"))
            self.assertIn(text_hex("red", dark=dark), label.styleSheet())
            for accent in BUTTON_COLORS:
                set_button_style(action, accent)
                self.assertEqual(action.styleSheet(), button_stylesheet(accent))
                normal, hover, pressed = button_fills(accent, dark=dark)
                self.assertEqual(action.grab().toImage().pixelColor(8, 18).name(), normal)
                option = QtWidgets.QStyleOptionButton()
                action.initStyleOption(option)
                option.state |= QtWidgets.QStyle.StateFlag.State_MouseOver | QtWidgets.QStyle.StateFlag.State_HasFocus
                pixmap = QtGui.QPixmap(action.size())
                painter = QtGui.QPainter(pixmap)
                action.style().drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, option, painter, action)
                painter.end()
                self.assertEqual(pixmap.toImage().pixelColor(8, 18).name(), hover)
                self.assertEqual(pixmap.toImage().pixelColor(60, 0).name(), "#a6cfff" if dark else "#071a37")
                self.assertGreater(QtGui.qGray(QtGui.QColor(hover).rgb()), QtGui.qGray(QtGui.QColor(normal).rgb()))
                option.state |= QtWidgets.QStyle.StateFlag.State_On
                painter = QtGui.QPainter(pixmap)
                action.style().drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, option, painter, action)
                painter.end()
                self.assertEqual(pixmap.toImage().pixelColor(8, 18).name(), pressed)
                self.assertEqual(pixmap.toImage().pixelColor(60, 0).name(), "#a6cfff")
                self.assertLess(QtGui.qGray(QtGui.QColor(pressed).rgb()), QtGui.qGray(QtGui.QColor(normal).rgb()))
                action.setDown(True)
                self.assertEqual(action.grab().toImage().pixelColor(8, 18).name(), pressed)
                action.setDown(False)
                action.setEnabled(False)
                self.assertEqual(action.grab().toImage(), native.grab().toImage())
                self.assertTrue(action.font().bold())
                action.setEnabled(True)
        set_text_style(label, None)
        self.assertEqual(label.styleSheet(), "")

    def test_system_scheme_precedes_window_fallback_and_follows_reparent(self) -> None:
        app = self.application
        scheme = QtCore.Qt.ColorScheme
        hint = self.enterContext(patch.object(QtGui.QStyleHints, "colorScheme", return_value=scheme.Unknown))
        white, black = QtWidgets.QWidget(), QtWidgets.QWidget()
        role = QtGui.QPalette.ColorRole
        for window, color in ((white, "white"), (black, "black")):
            palette = window.palette()
            palette.setColor(role.Window, QtGui.QColor(color))
            window.setPalette(palette)
        label = QtWidgets.QLabel("State", white)
        palette = label.palette()
        palette.setColor(role.Window, QtGui.QColor("black"))
        palette.setColor(role.Base, QtGui.QColor("black"))
        label.setPalette(palette)
        set_text_style(label, "cyan")
        self.assertFalse(is_dark_theme(label))
        for current, dark in ((scheme.Dark, True), (scheme.Light, False), (scheme.Unknown, False)):
            hint.return_value = current
            app.styleHints().colorSchemeChanged.emit(current)
            app.processEvents()
            self.assertEqual(is_dark_theme(label), dark)
            self.assertIn(text_hex("cyan", dark=dark), label.styleSheet())
            if current != scheme.Unknown:
                self.assertEqual(is_dark_theme(black), dark)
        label.setParent(black)
        app.processEvents()
        self.assertIn(text_hex("cyan", dark=True), label.styleSheet())
        black.setPalette(white.palette())
        app.processEvents()
        self.assertIn(text_hex("cyan", dark=False), label.styleSheet())

    def test_preview_switches_both_themes_without_changing_other_windows(self) -> None:
        root = Path(__file__).resolve().parent
        app = self.application
        self.enterContext(patch.object(QtGui.QStyleHints, "colorScheme", return_value=QtCore.Qt.ColorScheme.Light))
        other = QtWidgets.QWidget()
        window = runpy.run_path(str(root / "qt-style-preview.py"))["build_preview"]()
        window.show()
        self.addCleanup(window.close)
        buttons = window.findChildren(QtWidgets.QPushButton)
        switch = next(b for b in buttons if b.text() == "Switch to dark mode")
        blue = next(b for b in buttons if b.text() == "Blue" and b.isEnabled() and not b.isCheckable())
        disabled = next(b for b in buttons if b.text() == "Blue" and not b.isEnabled())
        reference = QtWidgets.QPushButton(disabled.text(), window)
        set_bold(reference)
        reference.setEnabled(False)
        field = window.findChild(QtWidgets.QLineEdit)
        field.setText("Edited")
        for dark in (True, False, True, False):
            switch.click()
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
            self.assertEqual(is_dark_theme(blue), dark)
            self.assertFalse(is_dark_theme(other))
            self.assertEqual(switch.text(), "Switch to light mode" if dark else "Switch to dark mode")
            self.assertEqual(blue.styleSheet(), button_stylesheet("blue", window))
            self.assertEqual(blue.grab().toImage().pixelColor(8, blue.height() // 2).name(),
                             button_fills("blue", dark=dark)[0])
            switch.setFocus()
            QtTest.QTest.keyClick(switch, QtCore.Qt.Key.Key_Tab)
            self.assertTrue(blue.hasFocus())
            focused = blue.grab().toImage()
            self.assertEqual(focused.pixelColor(focused.width() // 2, 0).name(), "#a6cfff" if dark else "#071a37")
            blue.setDown(True)
            pressed = blue.grab().toImage()
            self.assertEqual(pressed.pixelColor(pressed.width() // 2, 0).name(), "#a6cfff")
            blue.setDown(False)
            QtTest.QTest.keyClick(blue, QtCore.Qt.Key.Key_Tab)
            self.assertFalse(blue.hasFocus())
            unfocused = blue.grab().toImage()
            self.assertEqual(unfocused.pixelColor(unfocused.width() // 2, 0), unfocused.pixelColor(8, 8))
            reference.resize(disabled.size())
            self.assertEqual(disabled.grab().toImage(), reference.grab().toImage())
            self.assertEqual(field.text(), "Edited")
            for name in ("Default", "Bold"):
                sample = next(b for b in buttons if b.text() == name)
                self.assertEqual(sample.styleSheet(), "")
                self.assertEqual(sample.font().bold(), name == "Bold")

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

    def test_monospace_ui_uses_platform_size_and_regional_fallback(self) -> None:
        self.addCleanup(self.application.setFont, self.application.font())
        self.application.setFont(QtGui.QFont("UI", 14))
        fixed = QtGui.QFont("System Mono", 9)
        self.enterContext(patch.object(QtGui.QGuiApplication, "platformName", return_value="offscreen"))
        self.enterContext(patch.object(QtGui.QFontDatabase, "families", return_value=["Sarasa Mono SC"]))
        self.enterContext(patch.object(QtGui.QFontDatabase, "systemFont", side_effect=lambda role: QtGui.QFont(fixed)))
        for platform, points in (("darwin", 14), ("win32", 9), ("linux", 9)):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                font = monospace_ui_font()
                self.assertEqual(font.pointSizeF(), points)
                self.assertEqual(font.styleHint(), QtGui.QFont.StyleHint.Monospace)
                self.assertEqual(font.families()[:2], ["Consolas", "System Mono"])
                self.assertIn("Sarasa Mono SC", font.families())

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
