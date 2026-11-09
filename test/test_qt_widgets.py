"""Verify shared wheel protection and keyboard/popup behavior with offscreen Qt."""

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from utils.qt_widgets import (
    NoWheelComboBox, NoWheelSpinBox, NoWheelDoubleSpinBox, install_no_wheel_controls,
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
