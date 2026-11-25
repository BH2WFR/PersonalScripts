"""Regression checks for the two cue banners, identity selection and action safety."""

import os
import importlib.util
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

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


@unittest.skipUnless(sys.platform == "win32", "Windows regional settings")
class RegionalSettingsTests(unittest.TestCase):
    def test_console_pages_follow_runtime_changes(self) -> None:
        import subprocess
        import psutil
        from window_inspector.model import process_info

        program = """
import ctypes
import sys
kernel = ctypes.windll.kernel32
for line in sys.stdin:
    input_page, output_page = map(int, line.split())
    assert kernel.SetConsoleCP(input_page) and kernel.SetConsoleOutputCP(output_page)
    print("ready", flush=True)
"""
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        with subprocess.Popen([sys.executable, "-c", program], creationflags=subprocess.CREATE_NEW_CONSOLE,
                              startupinfo=startup, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
            assert child.stdin and child.stdout
            try:
                for settings, expected in [("437 65001", ("437", "65001 (UTF-8)")),
                                           ("65001 65001", ("65001 (UTF-8)", "65001 (UTF-8)"))]:
                    child.stdin.write(settings + "\n")
                    child.stdin.flush()
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    rows = process_info(psutil.Process(child.pid)).rows
                    self.assertIn((PropertyGroup.WINDOW, "Has console", "Yes"), rows)
                    self.assertIn((PropertyGroup.REGIONAL, "Console input code page", expected[0]), rows)
                    self.assertIn((PropertyGroup.REGIONAL, "Console output code page", expected[1]), rows)
            finally:
                child.stdin.close()

        with subprocess.Popen([sys.executable, "-c", "input()"], creationflags=subprocess.DETACHED_PROCESS,
                              stdin=subprocess.PIPE) as detached:
            try:
                rows = process_info(psutil.Process(detached.pid)).rows
                self.assertIn((PropertyGroup.WINDOW, "Has console", "No"), rows)
                self.assertIn((PropertyGroup.REGIONAL, "Console input code page", "No console"), rows)
            finally:
                detached.communicate(b"\n", timeout=10)

    def test_reads_only_selected_locale_variables_from_target(self) -> None:
        import subprocess
        import psutil
        from window_inspector.model import process_info

        env = dict(os.environ, TZ="JST-9", LC_CTYPE="ja_JP.UTF-8", UNRELATED_TEST_VALUE="do not display")
        with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                              stdin=subprocess.PIPE, env=env) as child:
            try:
                rows = process_info(psutil.Process(child.pid)).rows
            finally:
                child.communicate(input=b"", timeout=10)
        regional = {name: value for group, name, value in rows if group == PropertyGroup.REGIONAL}
        self.assertEqual(regional["Process environment: TZ"], "JST-9")
        self.assertEqual(regional["Process environment: LC_CTYPE"], "ja_JP.UTF-8")
        self.assertNotIn("do not display", regional.values())
        self.assertIn("User profile region", regional)
        self.assertIn("System ANSI code page", regional)
        self.assertIn("System time zone", regional)

    def test_embedded_manifest_and_unavailable_environment(self) -> None:
        import ctypes
        import psutil
        from window_inspector import windows
        from window_inspector.console_pages import ConsoleInfo

        manifest = b'''<assembly xmlns="urn:schemas-microsoft-com:asm.v1">
          <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
          <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
          </windowsSettings></application></assembly>'''
        buffer = ctypes.create_string_buffer(manifest)
        target = Mock()
        target.environ.side_effect = psutil.AccessDenied(42)
        with (patch.object(windows, "KERNEL") as kernel,
              patch.object(windows, "console_info", return_value=ConsoleInfo(None, "Unavailable", "Unavailable"))):
            kernel.SizeofResource.return_value = len(manifest)
            kernel.LockResource.return_value = ctypes.addressof(buffer)
            rows = windows._regional_rows(target, "example.exe", None)
            kernel.FreeLibrary.assert_called_once()
        self.assertIn((PropertyGroup.WINDOW, "Has console", "Unavailable"), rows)
        self.assertIn((PropertyGroup.REGIONAL, "Embedded manifest code page", "UTF-8"), rows)
        self.assertIn((PropertyGroup.REGIONAL, "User profile locale", "Unavailable"), rows)
        self.assertIn((PropertyGroup.REGIONAL, "Process locale environment", "Unavailable"), rows)


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

    @unittest.skipUnless(sys.platform == "darwin", "macOS preview window level")
    def test_preview_changes_pin_without_hiding_inspector(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QSignalSpy

        self.ui.show()
        handle = self.ui.windowHandle()
        assert handle is not None
        visibility = QSignalSpy(handle.visibleChanged)
        flag = Qt.WindowType.WindowStaysOnTopHint
        self.ui.pin.setChecked(True)
        self.ui._pin(False)
        self.assertFalse(handle.flags() & flag)
        self.assertTrue(self.ui.pin.isChecked())
        with patch("window_inspector.macos.activate_inspector"):
            self.ui._finish_preview()
        self.assertTrue(handle.flags() & flag)
        self.assertTrue(handle.isVisible())
        self.assertEqual(visibility.count(), 0)

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

    @unittest.skipUnless(sys.platform == "darwin", "macOS inspector details")
    def test_arguments_paths_and_copy_preserve_selected_data(self) -> None:
        from window_inspector.model import ProcessInfo
        from PySide6.QtWidgets import QTreeWidgetItem

        snapshot = Snapshot(self.first, [], paths={"App Bundle": "/Fixture.app", "Document": "/fixture file"})
        self.backend.snapshot.side_effect = None
        self.backend.snapshot.return_value = snapshot
        details = ProcessInfo("Fixture", "/fixture", "fixture 'two words'", None, [], ["fixture", "two words"])
        with patch("window_inspector.view.process_info", return_value=details):
            self.ui.load(self.first)
            self.ui.paths.setCurrentText("Document")
            self.ui.refresh()
        self.assertEqual(self.ui.fields["Path"].text(), "/fixture file")
        self.assertEqual(self.ui.arguments.topLevelItem(1).text(1), "two words")
        control = QTreeWidgetItem(["1", "AXButton", "", "Example"])
        self.ui.controls.addTopLevelItem(control)
        with patch.object(self.ui, "_copy") as copy:
            self.ui.controls.itemDoubleClicked.emit(control, 1)
            copy.assert_called_once_with("AXButton")
            self.ui._copy_all()
            output = copy.call_args.args[0]
            self.assertIn("1\ttwo words", output)
            self.assertIn("1\tAXButton\t\tExample", output)
            self.assertNotIn(CONTROLS_HINT, output)

    def test_windows_arguments_fill_panel_and_grow_for_long_values(self) -> None:
        from window_inspector.model import ProcessInfo
        from window_inspector.view import Inspector

        details = ProcessInfo("Fixture", "", "", None, [], ["fixture.exe", "two words", ""])
        with (patch("window_inspector.view.IS_MACOS", False),
              patch("window_inspector.view.IS_WINDOWS", True),
              patch("window_inspector.view.process_info", return_value=details)):
            ui = Inspector(self.backend)
            self.addCleanup(ui.close)
            ui.load(self.first)
            ui.tabs.setCurrentWidget(ui.arguments)
            ui.show()
            self.app.processEvents()
            table = ui.arguments
            self.assertEqual(ui.tabs.tabText(ui.tabs.currentIndex()), "Arguments")
            self.assertEqual([table.topLevelItem(i).text(1) for i in range(table.topLevelItemCount())], details.arguments)
            self.assertEqual(table.header().length(), table.viewport().width())
            long_arg = "long path with spaces " * 45
            details.arguments.append(long_arg)
            ui.refresh()
            self.app.processEvents()
            self.assertGreaterEqual(table.columnWidth(1), table.fontMetrics().horizontalAdvance(long_arg))
            self.assertGreater(table.horizontalScrollBar().maximum(), 0)
            details.arguments.clear()
            ui.load(self.second)
            self.app.processEvents()
            self.assertEqual(table.topLevelItemCount(), 0)
            self.assertEqual(table.header().length(), table.viewport().width())

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
        if sys.platform in ("darwin", "win32"):
            self.assertEqual(groups[-1].text(0), "Regional settings")
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
        self.assertEqual(self.backend.act.call_args_list, [call(self.first, "Activate"), call(self.first, "Center")])
        hint = next(label for label in self.ui.findChildren(QLabel) if label.text().startswith("Double-click"))
        self.ui.controls.itemDoubleClicked.emit(self.ui.controls.topLevelItem(0), 0)
        self.ui._clear()
        self.assertFalse(center.isEnabled())
        self.assertTrue(hint.isVisible())
        self.assertIn("Release", self.ui.finder.toolTip())

    def test_geometry_actions_preview_then_restore_focus(self) -> None:
        from PySide6.QtTest import QTest
        from window_inspector.view import PREVIEW_MS

        self.ui.load(self.first)
        events = Mock()
        events.attach_mock(self.backend.act, "act")
        with (patch("window_inspector.view.IS_MACOS", False),
              patch("window_inspector.view.show_cursor_tooltip") as tooltip,
              patch.object(self.ui.outline, "show", events.show),
              patch.object(self.ui.outline, "hide", events.hide),
              patch.object(self.ui, "_restore_focus", events.restore)):
            for action in ("Activate", "Center", "Reset Size"):
                with self.subTest(action=action):
                    events.reset_mock()
                    tooltip.reset_mock()
                    self.ui._window_action(action)
                    self.assertEqual(self.ui.return_focus.interval(), PREVIEW_MS)
                    QTest.qWait(200)
                    actions = [call.act(self.first, "Activate")]
                    if action != "Activate":
                        actions.append(call.act(self.first, action))
                    self.assertEqual(events.mock_calls, [*actions, call.show(self.first)])
                    tooltip.assert_called_once()
                    self.assertEqual(tooltip.call_args.args, ("Focus returns to Window Inspector in 3 seconds.",))
                    self.assertTrue(0 < tooltip.call_args.kwargs["duration_ms"] <= PREVIEW_MS)
                    if action == "Activate":
                        QTest.qWait(2000)
                        self.assertEqual([c.args[0] for c in tooltip.call_args_list], [
                            "Focus returns to Window Inspector in 3 seconds.",
                            "Focus returns to Window Inspector in 2 seconds.",
                            "Focus returns to Window Inspector in 1 second."])
                    self.ui.return_focus.start(1)
                    QTest.qWait(50)
                    self.assertEqual(events.mock_calls[-2:], [call.hide(), call.restore()])
            tooltip.reset_mock()
            self.ui._window_action("Highlight")
            tooltip.assert_not_called()

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
    def test_disabling_click_through_returns_focus_after_success(self) -> None:
        self.ui.load(self.first)
        toggle = self.ui.toggles["Click-through"]
        with patch.object(self.ui, "_restore_focus") as restore:
            toggle.trigger()
            self.backend.act.assert_called_with(self.first, "Click-through", 1)
            restore.assert_not_called()
            toggle.trigger()
            self.backend.act.assert_called_with(self.first, "Click-through", 0)
            restore.assert_called_once_with()

    @unittest.skipUnless(sys.platform == "win32", "Windows window frames")
    def test_maximized_outline_stays_inside_the_window_and_work_area(self) -> None:
        from ctypes.wintypes import RECT
        from window_inspector import windows

        frame = (-1932, -12, 1936, 1084)
        with (patch.object(windows, "checked", return_value=self.first),
              patch.object(windows, "U") as native, patch.object(windows, "DWM"),
              patch.object(windows, "_rect", return_value=frame),
              patch.object(windows, "_scale", return_value=1.5),
              patch.object(windows, "_work_area", return_value=RECT(-1920, 0, 0, 1080))):
            native.IsHungAppWindow.return_value = native.IsIconic.return_value = False
            native.IsZoomed.return_value = True
            self.assertEqual(windows.frame(self.first), ((-1920, 0, 1920, 1072), 6))
            native.IsZoomed.return_value = False
            self.assertEqual(windows.frame(self.first), (frame, 6))

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
    @unittest.skipUnless(sys.platform == "darwin", "macOS process properties")
    def test_terminal_and_locale_visibility_are_independent(self) -> None:
        import psutil
        from window_inspector.model import process_info

        process = psutil.Process()
        with (patch.object(process, "terminal", return_value=None) as terminal,
              patch.object(process, "environ", return_value={}) as environment):
            rows = process_info(process).rows
            self.assertIn((PropertyGroup.PROCESS, "Controlling terminal", "None"), rows)
            self.assertIn((PropertyGroup.REGIONAL, "Process locale environment", "Unavailable"), rows)
            terminal.side_effect = psutil.AccessDenied(process.pid)
            environment.return_value = {"LANG": "C", "tz": "ignore", "OTHER": "ignore"}
            rows = process_info(process).rows
            self.assertIn((PropertyGroup.PROCESS, "Controlling terminal", "Unavailable"), rows)
            self.assertEqual([r for r in rows if r[0] == PropertyGroup.REGIONAL],
                             [(PropertyGroup.REGIONAL, "Process environment: LANG", "C")])

    @unittest.skipUnless(sys.platform == "darwin", "macOS Accessibility")
    def test_picker_keeps_exact_ax_window_without_windowserver_record(self) -> None:
        from types import SimpleNamespace
        from window_inspector import macos as mac

        element, window = object(), object()
        app = Mock()
        app.localizedName.return_value = "Fixture"
        app.processIdentifier.return_value = 432
        attrs = {"AXWindow": window, "AXRole": "AXButton", "AXTitle": "Same title"}
        with (patch.object(mac.CG, "CGEventGetLocation", return_value=SimpleNamespace(x=-45, y=120)),
              patch.object(mac.AX, "AXIsProcessTrusted", return_value=True),
              patch.object(mac.AX, "AXUIElementCopyElementAtPosition", return_value=(0, element)) as hit,
              patch.object(mac.AX, "AXUIElementGetPid", return_value=(0, 432)),
              patch.object(mac.A, "NSRunningApplication") as apps,
              patch.object(mac, "_attribute", side_effect=lambda obj, key, default=None: attrs.get(key, default)),
              patch.object(mac, "_window_id", return_value=0),
              patch.object(mac, "_records", side_effect=AssertionError("AX hit must precede Dock overlay"))):
            apps.runningApplicationWithProcessIdentifier_.return_value = app
            picked = mac.at_pointer()
            assert picked is not None
            self.assertEqual(hit.call_args.args[1:], (-45, 120, None))
            self.assertIs(picked.ax_window, window)
            self.assertEqual((picked.title, picked.pid), ("Same title", 432))
            self.assertNotEqual(picked.id, 0)
            attrs["AXRole"] = "AXWindow"
            self.assertIs(mac.checked(picked), picked)
            attrs["AXRole"] = None
            with self.assertRaisesRegex(RuntimeError, "closed"):
                mac.checked(picked)

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
        bundle = appkit.NSBundle.bundleWithPath_.return_value
        bundle.localizations.return_value = ["en", "zh-Hans"]
        bundle.developmentLocalization.return_value = "en"
        rows = module.snapshot(expected).rows
        self.assertIn((PropertyGroup.GEOMETRY, "Position (points)", "-100, 20"), rows)
        self.assertIn((PropertyGroup.BUNDLE, "Bundle ID", "com.example.fixture"), rows)
        self.assertIn((PropertyGroup.BUNDLE, "Available localizations", "en, zh-Hans"), rows)
        self.assertIn((PropertyGroup.BUNDLE, "Development language", "en"), rows)
        quartz.CGWindowListCopyWindowInfo.return_value = [dict(main, OwnerPID=os.getpid()), popup]
        self.assertIsNone(module.at_pointer())
        quartz.CGWindowListCopyWindowInfo.return_value = [dict(main, OwnerName="Dock", Layer=20), popup]
        self.assertEqual(module.at_pointer(), expected)


if __name__ == "__main__":
    unittest.main()
