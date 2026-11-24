"""Verify screen mask painting, per-block appearance, and persisted defaults."""

import io
import os
import runpy
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu, QPushButton, QSpinBox

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "others"))
from screen_mask.app import Mask, Session
from utils import ConfigStore, System
from utils.qt_widgets import configure_qt_application


class LinuxEntryTests(unittest.TestCase):
    def test_linux_launch_requires_a_desktop(self) -> None:
        entry = str(ROOT / "tools/others/screen-mask.py")
        main = runpy.run_path(entry)["main"]
        for display in ({}, {"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}):
            with (self.subTest(display=display), patch.object(sys, "platform", "linux"),
                  patch.object(sys, "argv", [entry]), patch.dict(os.environ, display, clear=True),
                  patch("screen_mask.app.run", return_value=0) as launch, redirect_stderr(io.StringIO())):
                self.assertEqual(main(), 0 if display else 1)
                self.assertEqual(launch.call_count, int(bool(display)))

    def test_cli_selects_one_mode(self) -> None:
        entry = str(ROOT / "tools/others/screen-mask.py")
        main = runpy.run_path(entry)["main"]
        for args, hollow in (([], False), (["--solid"], False), (["--hollow"], True)):
            with (self.subTest(args=args), patch.object(sys, "argv", [entry, *args]),
                  patch.object(System, "is_headless", return_value=False),
                  patch("screen_mask.app.run", return_value=0) as launch):
                self.assertEqual(main(), 0)
                launch.assert_called_once_with(hollow=hollow)
        with (patch.object(sys, "argv", [entry, "--solid", "--hollow"]),
              redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error):
            main()
        self.assertEqual(error.exception.code, 2)


class ScreenMaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if sys.platform == "linux" and System.is_headless():
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        existing = QApplication.instance()
        cls.app = existing if isinstance(existing, QApplication) else QApplication([])
        configure_qt_application(cls.app)

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        directory_patch = patch.object(ConfigStore, "directory", return_value=Path(directory.name))
        directory_patch.start()
        self.addCleanup(directory_patch.stop)
        self.session = Session(self.app, ConfigStore("screen-mask.yaml"))
        self.addCleanup(self.session.close_all)

    @staticmethod
    def use_menu(block: Mask, interact: Callable[[QMenu], None]) -> None:
        """Run a real popup and propagate callback failures after its nested event loop."""
        errors: list[Exception] = []

        def run_callback() -> None:
            menu = block.findChildren(QMenu)[-1]
            try:
                interact(menu)
            except Exception as exc:
                errors.append(exc)
            finally:
                menu.close()

        QTimer.singleShot(0, run_callback)
        pos = QPoint(10, 10)
        block.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, block.mapToGlobal(pos)))
        if errors:
            raise errors[0]

    def choose(self, block: Mask, label: str) -> None:
        """Select the corresponding action in the block's real context menu."""
        def select(menu: QMenu) -> None:
            action = next((action for action in menu.actions() if action.text().startswith(label)), None)
            assert action is not None
            menu.setActiveAction(action)
            QTest.keyClick(menu, Qt.Key.Key_Return)

        self.use_menu(block, select)

    def test_colors_round_trip_without_recoloring_other_blocks(self) -> None:
        self.session.add_block()
        first, = self.session.blocks
        before = first.grab().toImage()
        self.assertEqual(before.pixelColor(0, 0), QColor("blue"))
        self.assertEqual(before.pixelColor(before.width() // 2, before.height() // 2), QColor("black"))
        self.choose(first, "Add solid block")
        other, = self.session.blocks - {first}
        for label, value in (("Border", "#123456"), ("Background", "#789abc")):
            with patch.object(QColorDialog, "getColor", return_value=QColor(value)):
                self.choose(first, label)
        self.assertEqual(other.colors["background_color"], QColor("black"))
        self.assertEqual(other.colors["border_color"], QColor("blue"))
        self.assertEqual(self.session.store.load(), {"border_color": "#123456", "background_color": "#789abc"})
        reloaded = Session(self.app, self.session.store)
        self.addCleanup(reloaded.close_all)
        reloaded.add_block()
        restored, = reloaded.blocks
        self.assertEqual(restored.colors, first.colors)

    def test_opacity_resize_edges_and_close_actions(self) -> None:
        self.session.add_block()
        first, = self.session.blocks
        self.assertTrue(first.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(first.edges_at(QPoint(0, 0)), Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
        self.assertEqual(first.edges_at(first.rect().center()), Qt.Edge(0))
        def edit_opacity(menu: QMenu) -> None:
            spin = next(spin for spin in menu.findChildren(QSpinBox) if spin.accessibleName() == "Opacity")
            self.assertEqual((spin.minimum(), spin.maximum()), (31, 100))
            spin.setValue(31)
            image = first.grab().toImage()
            for x in (0, image.width() // 2):
                self.assertEqual(image.pixelColor(x, image.height() // 2).alpha(), round(255 * 0.31))
            reset, = menu.findChildren(QPushButton)
            QTest.mouseClick(reset, Qt.MouseButton.LeftButton)
            self.assertEqual((spin.value(), first.opacity_percent), (100, 100))
            self.assertTrue(menu.isVisible())
            QTest.keyClick(spin, Qt.Key.Key_Down)
            self.assertEqual(first.opacity_percent, 99)

        self.use_menu(first, edit_opacity)
        self.choose(first, "Add solid block")
        other, = self.session.blocks - {first}
        self.assertEqual(other.opacity_percent, 100)
        self.choose(other, "Close this block")
        self.assertEqual(self.session.blocks, {first})
        self.choose(first, "Add solid block")
        self.choose(first, "Close all and quit")
        self.assertFalse(self.session.blocks)

    def test_border_width_painting_and_persistence(self) -> None:
        self.session.add_block()
        first, = self.session.blocks
        self.session.add_block()
        other, = self.session.blocks - {first}

        def edit_width(menu: QMenu) -> None:
            width = next(spin for spin in menu.findChildren(QSpinBox) if spin.accessibleName() == "Border width")
            self.assertEqual(width.value(), 2)
            width.setValue(0)
            self.assertEqual(first.grab().toImage().pixelColor(0, 0), QColor("black"))
            width.setValue(7)
            image = first.grab().toImage()
            y = image.height() // 2
            scale = image.devicePixelRatio()
            self.assertEqual(image.pixelColor(round(5 * scale), y), QColor("blue"))
            self.assertEqual(image.pixelColor(round(9 * scale), y), QColor("black"))

        self.use_menu(first, edit_width)
        self.assertEqual(self.session.store.load(), {"border_width": 7})
        self.assertEqual(other.border_width, 2)
        self.session.add_block()
        new, = self.session.blocks - {other, first}
        self.assertEqual(new.border_width, 7)
        reloaded = Session(self.app, self.session.store)
        self.assertEqual(reloaded.widths["border_width"], 7)

    def test_hollow_frame_tracks_size_and_width_and_restores_solid(self) -> None:
        self.session.add_block()
        block, = self.session.blocks
        window = block.windowHandle()
        assert window is not None
        block._set_border_width(0)
        self.choose(block, "Hollow frame")
        center = block.rect().center()
        self.assertFalse(window.mask().contains(center))
        self.assertTrue(window.mask().contains(QPoint(center.x(), 0)))
        self.assertEqual(block.edges_at(QPoint(center.x(), 0)), Qt.Edge(0))
        self.assertEqual(block.edges_at(QPoint(0, 0)), Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
        self.assertEqual(block.border_width, 5)
        block._set_border_width(12)
        old_width = block.width()
        block.resize(old_width + 70, 90)
        self.app.processEvents()
        self.assertFalse(window.mask().contains(QPoint(old_width - 1, 40)))
        self.assertTrue(window.mask().contains(QPoint(block.width() - 1, 40)))
        block.resize(block.minimumSize())
        block._set_border_width(32)
        self.assertFalse(window.mask().contains(block.rect().center()))
        image = block.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 0)
        self.assertEqual(image.pixelColor(0, 0), QColor("blue"))
        self.choose(block, "Add solid block")
        other, = self.session.blocks - {block}
        self.assertFalse(other.hollow)
        self.choose(block, "Hollow frame")
        self.assertTrue(window.mask().isEmpty())
        self.assertEqual(block.border_width, 0)
        block.resize(420, 78)
        image = block.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2), QColor("black"))

    def test_menu_creates_hollow_and_saves_its_own_width(self) -> None:
        self.session.store.update({"border_width": 9})
        session = Session(self.app, self.session.store)
        self.addCleanup(session.close_all)
        session.add_block()
        solid, = session.blocks
        self.choose(solid, "Add hollow frame")
        frame, = session.blocks - {solid}
        self.assertTrue(frame.hollow)
        self.assertEqual((solid.border_width, frame.border_width), (9, 5))
        handle = frame.windowHandle()
        assert handle is not None
        self.assertFalse(handle.mask().contains(frame.rect().center()))
        self.assertTrue(handle.mask().contains(QPoint(frame.width() // 2, 4)))
        self.assertFalse(handle.mask().contains(QPoint(frame.width() // 2, 5)))

        def widen(menu: QMenu) -> None:
            width = next(spin for spin in menu.findChildren(QSpinBox) if spin.accessibleName() == "Border width")
            width.setValue(11)

        self.use_menu(frame, widen)
        self.assertEqual(self.session.store.load(), {"border_width": 9, "hollow_border_width": 11})
        self.choose(frame, "Hollow frame")
        self.assertEqual(frame.border_width, 9)
        self.choose(frame, "Hollow frame")
        self.assertEqual(frame.border_width, 11)
        reloaded = Session(self.app, self.session.store)
        self.addCleanup(reloaded.close_all)
        reloaded.add_block(hollow=True)
        restored, = reloaded.blocks
        self.assertEqual(restored.border_width, 11)

    @unittest.skipUnless(sys.platform == "win32", "Windows activation style")
    def test_frame_uses_native_nonactivation_on_windows(self) -> None:
        if self.app.platformName() != "windows":
            self.skipTest("requires a native Windows window")
        import ctypes
        from ctypes import wintypes

        self.session.add_block()
        block, = self.session.blocks
        self.choose(block, "Hollow frame")
        style = ctypes.windll.user32.GetWindowLongW(wintypes.HWND(int(block.winId())), -20)
        self.assertTrue(style & 0x08000000)  # WS_EX_NOACTIVATE

    def test_drag_fallback_moves_and_resizes_in_logical_coordinates(self) -> None:
        self.session.add_block()
        block, = self.session.blocks
        start = block.geometry()
        left = Qt.MouseButton.LeftButton
        no_button = Qt.MouseButton.NoButton
        modifiers = Qt.KeyboardModifier.NoModifier

        def drag(pos: QPoint, delta: QPoint) -> None:
            local = QPointF(pos)
            origin = QPointF(block.mapToGlobal(pos))
            with patch.object(block, "windowHandle", return_value=None):
                block.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, local, origin,
                                                  left, left, modifiers))
            block.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, local + delta, origin + delta,
                                             no_button, left, modifiers))
            block.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, local, origin + delta,
                                                left, no_button, modifiers))

        drag(block.rect().center(), QPoint(-30, 14))
        self.assertEqual(block.geometry(), start.translated(-30, 14))
        moved = block.geometry()
        drag(block.rect().bottomRight(), QPoint(35, 10))
        self.assertEqual(block.geometry(), moved.adjusted(0, 0, 35, 10))
        corner = block.geometry().bottomRight()
        drag(QPoint(), QPoint(1000, 1000))
        self.assertEqual(block.size(), block.minimumSize())
        self.assertEqual(block.geometry().bottomRight(), corner)
