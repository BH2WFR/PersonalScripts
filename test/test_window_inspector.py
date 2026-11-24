"""Regression checks for the two cue banners, identity selection and action safety."""

import os
import importlib.util
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/others"))
from window_inspector.model import CONTROLS_HINT, INITIAL_HINT, LOADED_HINT, PropertyGroup, Snapshot, Window, find_window


class StartupTests(unittest.TestCase):
    def test_elevation_preserves_foreground_only_on_windows(self) -> None:
        import window_inspector
        from utils import System

        entry = str(ROOT / "tools/others/window-inspector.py")
        main = runpy.run_path(entry)["main"]
        original = Window(42, 123, "Original", "")
        backend = Mock()
        backend.foreground.return_value = original
        view = Mock()
        view.run.return_value = 0
        with (patch.dict(sys.modules, {"window_inspector.view": view}),
              patch.object(System, "enable_dpi_awareness"),
              patch.object(System, "restart_elevated") as elevate):
            with (patch.object(sys, "platform", "win32"),
                  patch.object(window_inspector, "windows", backend, create=True)):
                elevate.side_effect = SystemExit(0)
                with patch.object(sys, "argv", [entry, "--top"]), self.assertRaises(SystemExit):
                    main()
                view.run.assert_not_called()
                elevate.assert_called_once_with(entry=entry, args=["--startup-window", "42", "123", "--top"])
                elevate.side_effect = None
                with patch.object(sys, "argv", [entry, *elevate.call_args.kwargs["args"]]):
                    self.assertEqual(main(), 0)
                backend.foreground.assert_called_once_with()
                view.run.assert_called_once_with(backend, original, top=True)
            elevate.reset_mock()
            with (patch.object(sys, "platform", "darwin"), patch.object(sys, "argv", [entry]),
                  patch.object(window_inspector, "macos", backend, create=True)):
                self.assertEqual(main(), 0)
                view.run.assert_called_with(backend, original, top=False)
                elevate.assert_not_called()


class InspectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from utils.qt_widgets import configure_qt_application

        cls.app = QApplication.instance() or QApplication([])
        configure_qt_application(cls.app)

    def setUp(self) -> None:
        from window_inspector.view import Inspector

        self.first = Window(12, os.getpid(), "同名弹窗", "Popup")
        self.second = Window(34, os.getpid(), "同名弹窗", "Popup")
        self.backend = Mock()
        self.backend.windows.return_value = [self.first, self.second]
        self.backend.snapshot.side_effect = lambda w: Snapshot(w, [
            (PropertyGroup.WINDOW, "Window ID", str(w.id)),
            (PropertyGroup.PROCESS, "Process ID", str(w.pid)),
        ])
        self.backend.checked.side_effect = lambda w: w
        self.ui = Inspector(self.backend)
        self.addCleanup(self.ui.close)

    def complete_job(self) -> None:
        if self.ui.job is not None:
            self.ui.job.result(timeout=3)
            self.ui._finish_job()

    def test_inspector_starts_on_top_only_when_requested(self) -> None:
        from PySide6.QtCore import Qt
        from window_inspector.view import Inspector

        flag = Qt.WindowType.WindowStaysOnTopHint
        self.assertFalse(self.ui.windowFlags() & flag)
        self.assertFalse(self.ui.pin.isChecked())
        pinned = Inspector(self.backend, top=True)
        self.addCleanup(pinned.close)
        self.assertTrue(pinned.windowFlags() & flag)
        self.assertTrue(pinned.pin.isChecked())

    def test_list_prompt_and_selection(self) -> None:
        from PySide6.QtCore import Qt

        combo = self.ui.selector
        self.assertEqual(self.ui.editor.placeholderText(), INITIAL_HINT)
        self.assertEqual(combo.currentIndex(), -1)
        self.assertEqual(combo.count(), 1)
        self.ui.load(self.first)
        self.ui.load(self.second)
        self.assertEqual(combo.count(), 2)
        self.assertEqual(self.ui.controls.topLevelItem(0).text(0), CONTROLS_HINT)
        self.ui.refresh_list()
        self.complete_job()
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.itemText(0), LOADED_HINT)
        self.assertEqual(self.ui.editor.placeholderText(), LOADED_HINT)
        self.assertFalse(combo.model().index(0, 0).flags() & (Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled))
        self.assertEqual(self.ui.target, self.second)
        self.assertEqual(combo.currentIndex(), 2)
        self.ui._selected(0)
        self.assertEqual(self.ui.target, self.second)
        self.ui._selected(1)
        self.assertEqual(self.ui.target, self.first)

    def test_edit_invalidates_target_and_selectors_match_exactly(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        self.ui.load(self.first)
        self.ui.editor.selectAll()
        self.ui.editor.insert("ID:0x22")
        self.assertIsNone(self.ui.target)
        self.assertTrue(all(not widget.isEnabled() for widget in self.ui.target_controls))
        QTest.keyClick(self.ui.editor, Qt.Key.Key_Return)
        self.complete_job()
        self.assertEqual(self.ui.target, self.second)
        self.assertIsNone(find_window([self.first, self.second], "2"))
        self.assertEqual(find_window([self.first, self.second], f"PID:{os.getpid()}"), self.first)

    def test_process_action_rechecks_after_confirmation(self) -> None:
        self.ui.load(self.first)
        with patch.object(self.ui, "_confirm", return_value=True), patch.object(self.ui, "_start_job") as job:
            self.backend.checked.side_effect = [self.first, RuntimeError("窗口已关闭")]
            self.ui.guard(lambda: self.ui._end(False))
            job.assert_not_called()
        self.assertIsNone(self.ui.target)
        self.assertIn("窗口已关闭", self.ui.status.text())

    def test_property_groups_expand_copy_and_refresh(self) -> None:
        self.ui.load(self.first)
        tree = self.ui.info
        groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        self.assertTrue(all(group.childCount() and group.isExpanded() for group in groups))
        self.assertEqual([group.text(0) for group in groups[:2]], ["Window", "Process"])
        self.assertNotIn("Application bundle", [group.text(0) for group in groups])
        process = groups[1]
        names = [process.child(i).text(0) for i in range(process.childCount())]
        self.assertIn("Process ID", names)
        self.assertIn("Parent PID", names)
        with patch.object(self.ui, "_copy") as copy:
            tree.itemDoubleClicked.emit(groups[0], 0)
            copy.assert_not_called()
            tree.itemDoubleClicked.emit(groups[0].child(0), 1)
            copy.assert_called_once_with(str(self.first.id))
        process.setExpanded(False)
        self.ui.refresh()
        self.assertTrue(tree.topLevelItem(0).isExpanded())
        self.assertFalse(tree.topLevelItem(1).isExpanded())
        self.ui.load(self.second)
        self.assertTrue(tree.topLevelItem(1).isExpanded())

    def test_property_value_column_fills_space_and_scrolls_for_long_text(self) -> None:
        from PySide6.QtWidgets import QSplitter, QTreeWidgetItem

        self.ui.show()
        tree = self.ui.info
        item = QTreeWidgetItem(tree, ["Title", "Short"])
        splitter = tree.parentWidget()
        assert isinstance(splitter, QSplitter)
        for widths in ([400, 400], [600, 200]):
            splitter.setSizes(widths)
            self.app.processEvents()
            self.assertEqual(tree.columnWidth(1), tree.viewport().width() - tree.columnWidth(0))
        tree.setColumnWidth(0, tree.columnWidth(0) + 25)
        self.app.processEvents()
        self.assertEqual(tree.header().length(), tree.viewport().width())
        long_value = "Window title " * 60
        item.setText(1, long_value)
        self.app.processEvents()
        self.assertGreaterEqual(tree.columnWidth(1), tree.fontMetrics().horizontalAdvance(long_value))
        self.assertGreater(tree.horizontalScrollBar().maximum(), 0)
        item.setText(1, "Short")
        self.app.processEvents()
        self.assertEqual(tree.header().length(), tree.viewport().width())
        self.assertEqual(tree.horizontalScrollBar().maximum(), 0)

    def test_toolbar_actions_and_permanent_copy_hint(self) -> None:
        from PySide6.QtWidgets import QLabel, QPushButton, QToolBar

        self.ui.load(self.first)
        self.ui.show()
        self.app.processEvents()
        bars = {bar.windowTitle(): bar for bar in self.ui.findChildren(QToolBar)}
        self.assertEqual(set(bars), {"Process", "Window"})
        self.assertTrue(all(button.toolTip() for button in self.ui.findChildren(QPushButton)))
        for bar in bars.values():
            for action in bar.actions():
                if action.text():
                    self.assertNotEqual(action.toolTip(), action.text())
                    self.assertTrue(action.toolTip())
        center = next(action for action in bars["Window"].actions() if action.text() == "Center")
        center.trigger()
        self.backend.act.assert_called_once_with(self.first, "Center", 0)
        hint = next(label for label in self.ui.findChildren(QLabel) if label.text().startswith("Double-click"))
        self.ui.controls.itemDoubleClicked.emit(self.ui.controls.topLevelItem(0), 0)
        self.ui._clear()
        self.assertFalse(center.isEnabled())
        self.assertTrue(hint.isVisible())
        self.assertIn("Release", self.ui.finder.toolTip())

    @unittest.skipUnless(sys.platform == "win32", "Windows window opacity")
    def test_opacity_dialog_edits_the_selected_window(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QSpinBox, QToolBar

        snapshot = Snapshot(self.first, [], opacity=73)
        self.backend.snapshot.side_effect = None
        self.backend.snapshot.return_value = snapshot
        self.backend.act.side_effect = lambda w, action, value: setattr(snapshot, "opacity", value)
        self.ui.load(self.first)
        self.ui.show()
        bar = next(bar for bar in self.ui.findChildren(QToolBar) if bar.windowTitle() == "Window")
        actions = bar.actions()
        index = next(i for i, action in enumerate(actions) if action.text() == "Always on Top")
        opacity = actions[index + 1]
        self.assertEqual(opacity.text(), "Opacity")

        def open_editor() -> tuple[QDialog, QSpinBox, QDialogButtonBox]:
            opacity.trigger()
            dialog = self.app.activeModalWidget()
            assert isinstance(dialog, QDialog)
            spin, box = dialog.findChild(QSpinBox), dialog.findChild(QDialogButtonBox)
            assert spin is not None and box is not None
            return dialog, spin, box

        dialog, spin, box = open_editor()
        self.assertEqual((spin.minimum(), spin.maximum(), spin.value()), (30, 100, 73))
        QTest.keyClicks(spin, "42")
        self.backend.act.assert_not_called()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.backend.act.assert_not_called()

        dialog, spin, box = open_editor()
        QTest.keyClicks(spin, "42")
        box.button(QDialogButtonBox.StandardButton.Ok).click()
        self.backend.act.assert_called_once_with(self.first, "Opacity", 42)

        self.backend.act.reset_mock()
        dialog, spin, box = open_editor()
        self.assertEqual(spin.value(), 42)
        box.button(QDialogButtonBox.StandardButton.Reset).click()
        self.backend.act.assert_called_once_with(self.first, "Opacity", 100)

        snapshot.opacity = 15
        self.backend.act.reset_mock()
        dialog, spin, box = open_editor()
        self.assertEqual(spin.value(), 30)
        self.backend.act.assert_not_called()
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.backend.act.assert_called_once_with(self.first, "Opacity", 30)
        self.ui._clear()
        self.assertFalse(opacity.isEnabled())

    @unittest.skipUnless(sys.platform == "win32", "Windows scheduling classes")
    def test_priority_selection_applies_once(self) -> None:
        from window_inspector.view import PRIORITIES

        self.ui.load(self.first)
        assert self.ui.process is not None
        with patch.object(self.ui.process, "nice", return_value=PRIORITIES["Normal"]) as nice:
            self.ui.refresh()
            self.assertFalse(any(call.args for call in nice.call_args_list))
            index = self.ui.priority.findText("BelowNormal")
            self.ui.priority.setCurrentIndex(index)
            self.ui.priority.activated.emit(index)
            self.assertEqual([call.args for call in nice.call_args_list if call.args], [(PRIORITIES["BelowNormal"],)])

    def test_nice_editor_commits_after_typing(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QSpinBox
        from window_inspector.model import ProcessInfo
        from window_inspector.view import Inspector

        details = ProcessInfo("Example", "", "", 0, [])
        with (patch("window_inspector.view.IS_WINDOWS", False),
              patch("window_inspector.view.process_info", return_value=details)):
            ui = Inspector(self.backend)
            self.addCleanup(ui.close)
            ui.load(self.first)
            assert ui.process is not None
            assert isinstance(ui.priority, QSpinBox)
            with patch.object(ui.process, "nice", side_effect=lambda value: setattr(details, "priority", value)) as nice:
                ui.refresh()
                ui.priority.selectAll()
                QTest.keyClicks(ui.priority, "12")
                nice.assert_not_called()
                QTest.keyClick(ui.priority, Qt.Key.Key_Return)
                nice.assert_called_once_with(12)

    @unittest.skipUnless(sys.platform == "win32", "Windows layered windows")
    def test_native_opacity_floor(self) -> None:
        from window_inspector import windows

        with patch.object(windows, "U") as native, patch.object(windows, "_layer", return_value=(0, 255, 0)):
            with self.assertRaises(ValueError):
                windows._set_layer(123, 29)
            native.GetWindowLongW.assert_not_called()
            native.GetWindowLongW.return_value = 0
            windows._set_layer(123, 30)
            self.assertEqual(native.SetLayeredWindowAttributes.call_args.args[2], 77)

    @unittest.skipUnless(sys.platform == "win32", "Windows child controls")
    def test_enable_and_show_controls(self) -> None:
        from window_inspector import windows

        target = Window(99, os.getpid(), "", "")
        with (patch.object(windows, "checked", return_value=target),
              patch.object(windows, "_handles", return_value=[10, 11, 12, 13]),
              patch.object(windows, "U") as native):
            native.IsWindowEnabled.side_effect = [False, True, False, True]
            total, enabled = windows.enable_controls(target)
        self.assertEqual((total, enabled), (4, 2))
        self.assertEqual(native.EnableWindow.call_count, 2)
        with (patch.object(windows, "checked", return_value=target),
              patch.object(windows, "_handles", return_value=[10, 11, 12, 13]),
              patch.object(windows, "U") as native):
            native.IsWindowVisible.side_effect = [True, False, False, True]
            total, shown = windows.show_controls(target)
        self.assertEqual((total, shown), (4, 2))
        self.assertEqual(native.ShowWindowAsync.call_count, 2)

    @unittest.skipUnless(sys.platform == "win32", "Windows menu bar")
    def test_enable_menu(self) -> None:
        from window_inspector import windows

        target = Window(99, os.getpid(), "", "")
        with (patch.object(windows, "checked", return_value=target),
              patch.object(windows, "U") as native):
            native.GetMenu.return_value = 0
            self.assertEqual(windows.enable_menu(target), (0, 0))
            native.GetMenu.return_value = 0x7000
            native.GetMenuItemCount.return_value = 2
            native.GetSubMenu.return_value = 0
            with (patch.object(windows, "_menu_item_state",
                               side_effect=[windows.MFS_DISABLED, windows.MFS_ENABLED]),
                  patch.object(windows, "_set_menu_item_state", return_value=True) as set_state):
                self.assertEqual(windows.enable_menu(target), (2, 1))
            self.assertEqual(set_state.call_count, 1)


class MacDiscoveryTests(unittest.TestCase):
    def test_frontmost_popup_without_accessibility_and_covered_inspector(self) -> None:
        from types import SimpleNamespace

        quartz = Mock()
        for key in ("Bounds", "Number", "OwnerPID", "Name", "OwnerName", "Layer", "Alpha"):
            setattr(quartz, f"kCGWindow{key}", key)
        quartz.kCGWindowListOptionOnScreenOnly = 1
        quartz.kCGWindowListExcludeDesktopElements = 16
        quartz.CGEventGetLocation.return_value = SimpleNamespace(x=-90, y=21)
        bounds = dict(X=-100, Y=20, Width=200, Height=120)
        popup = dict(Bounds=bounds, Number=8, OwnerPID=432, Name="", OwnerName="Fixture", Layer=4)
        main = dict(popup, Number=9, Name="Main", Layer=0)
        overlay = dict(popup, Bounds=dict(bounds, Height=4), OwnerPID=os.getpid())
        quartz.CGWindowListCopyWindowInfo.return_value = [overlay, popup, main]
        appkit, ax = Mock(), Mock()
        appkit.NSWorkspace.sharedWorkspace.return_value.frontmostApplication.return_value.processIdentifier.return_value = 432
        ax.AXIsProcessTrusted.return_value = False
        spec = importlib.util.spec_from_file_location("window_inspector._test_macos", ROOT / "tools/others/window_inspector/macos.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"Quartz": quartz, "AppKit": appkit, "ApplicationServices": ax, "objc": Mock()}):
            spec.loader.exec_module(module)
        expected = Window(8, 432, "", "Fixture")
        with patch.dict(sys.modules, {"AppKit": appkit}):
            self.assertEqual(module.foreground(), expected)
        self.assertEqual(module.at_pointer(), expected)
        self.assertEqual(module.windows(False), [expected, Window(9, 432, "Main", "Fixture")])
        quartz.CGWindowListCopyWindowInfo.return_value = [popup]
        app = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value
        app.bundleIdentifier.return_value = "com.example.fixture"
        app.bundleURL.return_value.path.return_value = "/Applications/Fixture.app"
        rows = module.snapshot(expected).rows
        self.assertIn((PropertyGroup.GEOMETRY, "Position (points)", "-100, 20"), rows)
        self.assertIn((PropertyGroup.BUNDLE, "Bundle ID", "com.example.fixture"), rows)
        quartz.CGWindowListCopyWindowInfo.return_value = [dict(main, OwnerPID=os.getpid()), popup]
        self.assertIsNone(module.at_pointer())


if __name__ == "__main__":
    unittest.main()
