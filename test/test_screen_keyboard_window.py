"""Verify keyboard controls and native window layout without sending input."""

import ctypes
from ctypes import wintypes
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/input-and-text"))


def _relaunch_keyboard(event_name: str) -> None:
    from screen_keyboard import window, windows_ui
    from screen_keyboard.state import LeftKeyMode

    with (patch.object(window, "REOPEN_EVENT", event_name),
          patch.object(windows_ui, "ScreenKeyboard", side_effect=AssertionError("Created a duplicate keyboard"))):
        raise SystemExit(windows_ui.run(LeftKeyMode.F24))


@unittest.skipUnless(sys.platform == "win32", "Win32 window messages")
class WindowTests(unittest.TestCase):
    def test_duplicate_process_moves_existing_window(self) -> None:
        from screen_keyboard import window
        from screen_keyboard.windows_ui import ScreenKeyboard
        from utils import ConfigStore

        event_name = rf"Local\PersonalScripts.ScreenKeyboard.Test.{uuid.uuid4().hex}"
        with (tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)),
              patch.object(window, "REOPEN_EVENT", event_name), window.reopen_signal() as requested):
            self.assertIsNotNone(requested)
            keyboard = ScreenKeyboard(requested)
            try:
                keyboard.toggle_numpad()
                api, hwnd = window.U, keyboard.native.hwnd
                self.assertTrue(api.GetWindowLongW(hwnd, window.GWL_EXSTYLE) & window.WS_EX_TOPMOST)
                rect = wintypes.RECT()
                api.GetWindowRect(hwnd, ctypes.byref(rect))
                width, height = rect.right - rect.left, rect.bottom - rect.top
                monitor = api.MonitorFromRect(ctypes.byref(rect), window.MONITOR_DEFAULTTONEAREST)
                info = window.MonitorInfo(size=ctypes.sizeof(window.MonitorInfo))
                self.assertTrue(api.GetMonitorInfoW(monitor, ctypes.byref(info)))
                work = info.work
                keyboard.native.move(work.left, work.top)
                # Reopening must also raise a keyboard that another window covered.
                self.assertTrue(api.SetWindowPos(hwnd, wintypes.HWND(-2), 0, 0, 0, 0,
                                                 window.SWP_NOMOVE | window.SWP_NOSIZE | window.SWP_NOACTIVATE))
                self.assertFalse(api.GetWindowLongW(hwnd, window.GWL_EXSTYLE) & window.WS_EX_TOPMOST)

                def pointer_at_corner(pointer):
                    ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT))[0] = wintypes.POINT(work.right - 1, work.bottom - 1)
                    return True

                process = multiprocessing.get_context("spawn").Process(target=_relaunch_keyboard, args=(event_name,))
                process.start()
                try:
                    process.join(10)
                    self.assertEqual(process.exitcode, 0)
                finally:
                    if process.is_alive():
                        process.terminate()
                        process.join()
                foreground = api.GetForegroundWindow()
                with patch.object(api, "GetCursorPos", side_effect=pointer_at_corner):
                    keyboard.window.after(550, keyboard.window.quit)
                    keyboard.window.mainloop()
                api.GetWindowRect(hwnd, ctypes.byref(rect))
                self.assertEqual((rect.right, rect.bottom), (work.right, work.bottom))
                self.assertEqual((rect.right - rect.left, rect.bottom - rect.top), (width, height))
                self.assertEqual(api.GetForegroundWindow(), foreground)
                self.assertTrue(api.GetWindowLongW(hwnd, window.GWL_EXSTYLE) & window.WS_EX_TOPMOST)
                self.assertTrue(keyboard.numpad)
                self.assertEqual(keyboard.state.output.mode.value, "F24")
                self.assertNotIn(keyboard.state.setting, keyboard.state.store.load())
                from screen_keyboard import windows_ui

                with patch.object(windows_ui.messagebox, "showwarning") as dialog:
                    self.assertEqual(windows_ui.run(warning="Unsupported argument"), 0)
                    dialog.assert_called_once_with(windows_ui.WINDOW_TITLE, "Unsupported argument")
                keyboard.window.after(550, keyboard.window.quit)
                keyboard.window.mainloop()
                self.assertIsNone(keyboard.state.force_layer)
                self.assertEqual(keyboard.state.output.mode.value, "native")
            finally:
                keyboard.close()
        with patch.object(window, "REOPEN_EVENT", event_name), window.reopen_signal() as requested:
            self.assertIsNotNone(requested)

    def test_second_layer_click_restores_both_alt_widgets(self) -> None:
        from screen_keyboard.windows_ui import ScreenKeyboard
        from utils import ConfigStore

        with (tempfile.TemporaryDirectory() as scratch,
              patch.object(ConfigStore, "directory", return_value=Path(scratch)),
              patch("screen_keyboard.windows_ui.WindowsOutput") as backend):
            output = backend.return_value
            output.mac = False
            output.target.return_value = 1
            output.locks.return_value = {"CapsLock": False, "NumLock": True, "ScrollLock": False}
            keyboard = ScreenKeyboard()
            try:
                keyboard.window.update()
                keyboard.menu.invoke(1)
                layer, left, right = (keyboard.buttons[key] for key in ("Layer", "LAlt", "RAlt"))
                normal_colors = [button.cget("background") for button in (left, right)]
                left.event_generate("<ButtonPress-1>")
                left.event_generate("<ButtonRelease-1>")
                layer_idle = layer.cget("background")
                layer.event_generate("<ButtonPress-1>")
                self.assertEqual(left.cget("text"), "L3/4")
                self.assertEqual(right.cget("text"), "L3/4")
                self.assertEqual(left.cget("background"), layer.cget("background"))
                self.assertEqual(right.cget("background"), layer_idle)
                layer.event_generate("<ButtonRelease-1>")
                self.assertEqual([button.cget("text") for button in (left, right)], ["L3/4", "L3/4"])
                self.assertEqual(right.cget("background"), layer_idle)
                layer.event_generate("<ButtonPress-1>")
                self.assertEqual([button.cget("text") for button in (left, right)], ["Alt", "Alt"])
                layer.event_generate("<ButtonRelease-1>")
                self.assertEqual([button.cget("background") for button in (left, right)], normal_colors)
            finally:
                keyboard.close()

    def test_toolbar_mode_and_size_survive_reopening(self) -> None:
        from screen_keyboard.layout import TOOLBAR, TOOLBAR_TIPS
        from screen_keyboard.state import WindowLayout
        from screen_keyboard.window import GWL_EXSTYLE, ToolInfo, U, WS_EX_NOACTIVATE
        from screen_keyboard.windows_ui import ScreenKeyboard
        from utils import ConfigStore

        with tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)):
            keyboard = ScreenKeyboard()
            try:
                root = keyboard.window
                root.update()
                button = keyboard.buttons["settings"]
                self.assertTrue(button.winfo_ismapped())
                self.assertEqual(button.cget("text"), "Prefs")
                self.assertEqual(keyboard.buttons["reset"].cget("text"), "Release")
                self.assertEqual(keyboard.buttons["redraw"].cget("text"), dict(TOOLBAR)["redraw"])
                tooltip = keyboard.native.tooltip
                self.assertTrue(U.GetWindowLongW(tooltip, GWL_EXSTYLE) & WS_EX_NOACTIVATE)
                self.assertEqual(U.SendMessageW(tooltip, 0x0400 + 13, 0, 0), len(TOOLBAR))  # TTM_GETTOOLCOUNT
                for name, _ in TOOLBAR:
                    buffer = ctypes.create_unicode_buffer(512)
                    info = ToolInfo(size=ToolInfo.reserved.offset, owner=keyboard.content.winfo_id(),
                                    tool=keyboard.buttons[name].winfo_id(), text=ctypes.cast(buffer, wintypes.LPWSTR))
                    U.SendMessageW(tooltip, 0x0400 + 56, len(buffer), ctypes.addressof(info))  # TTM_GETTEXTW
                    self.assertEqual(buffer.value, TOOLBAR_TIPS[name])
                for strip in (keyboard.header, keyboard.status, keyboard.footer, *keyboard.dividers.values()):
                    pos = keyboard.native.position()
                    strip.event_generate("<ButtonPress-1>", x=2, y=2)
                    strip.event_generate("<B1-Motion>", x=9, y=6)
                    strip.event_generate("<ButtonRelease-1>", x=2, y=2)
                    self.assertEqual(keyboard.native.position(), (pos[0] + 7, pos[1] + 4))
                with patch.object(keyboard.menu, "tk_popup") as popup:
                    button.event_generate("<ButtonRelease-1>", x=5, y=5)
                    popup.assert_called_once_with(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
                self.assertEqual(keyboard.selection.get(), "native")
                for index, name in enumerate(("CapsLock", "F1", "F24"), start=1):
                    self.assertEqual(keyboard.menu.entrycget(index, "label"), f"Left key: Layer ({name})")
                    keyboard.menu.invoke(index)
                    self.assertEqual(keyboard.selection.get(), name)
                self.assertEqual(keyboard.buttons["Layer"].cget("text"), "Layer")
                self.assertEqual(keyboard.state.store.load()[keyboard.state.setting], "F24")
                self.assertEqual(keyboard.menu.type(4), "separator")
                self.assertEqual(keyboard.menu.entrycget(5, "label"), "Remember window size")
                self.assertFalse(keyboard.remember_size.get())
                keyboard.menu.invoke(5)
                self.assertTrue(keyboard.remember_size.get())
                keyboard.toggle_extended()
                keyboard.toggle_numpad()
                keyboard.resize(658, 252, logical=True)
                keyboard.finish_resize()
                saved = WindowLayout(658, 252, True, True)
                self.assertEqual(keyboard.state.window_layout, saved)
            finally:
                keyboard.close()

            keyboard = ScreenKeyboard()
            try:
                root = keyboard.window
                root.update()
                self.assertEqual(keyboard.selection.get(), "F24")
                self.assertTrue(keyboard.remember_size.get())
                self.assertTrue(keyboard.buttons["PrintScreen"].winfo_ismapped())
                self.assertTrue(keyboard.buttons["NumpadEnter"].winfo_ismapped())
                self.assertEqual((root.winfo_width(), root.winfo_height()),
                                 (keyboard.dpi.pixels(saved.width), keyboard.dpi.pixels(saved.height)))
                keyboard.menu.invoke(0)
                self.assertEqual(keyboard.buttons["Layer"].cget("text"), "CapsLock")
                keyboard.menu.invoke(5)
                self.assertFalse(keyboard.remember_size.get())
                self.assertEqual(keyboard.current_layout(), saved)
            finally:
                keyboard.close()
            self.assertEqual(keyboard.state.store.load()[keyboard.state.setting], "native")
            keyboard = ScreenKeyboard()
            try:
                self.assertFalse(keyboard.remember_size.get())
                self.assertEqual(keyboard.current_layout(), WindowLayout())
            finally:
                keyboard.close()

    def test_layout_and_dpi(self) -> None:
        from screen_keyboard.layout import DEFAULT_SIZE
        from screen_keyboard.windows_ui import ScreenKeyboard
        from screen_keyboard.window import U
        from utils import ConfigStore

        with tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)):
            keyboard = ScreenKeyboard()
            root = keyboard.window
            hwnd = keyboard.native.hwnd
            U.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            U.PostMessageW.restype = wintypes.BOOL
            U.SendMessageW.argtypes = U.PostMessageW.argtypes
            U.SendMessageW.restype = wintypes.LPARAM
            U.IsWindowVisible.argtypes = [wintypes.HWND]
            U.IsWindowVisible.restype = wintypes.BOOL
            failures = []

            def post(message: int, wp: int = 0, lp: int = 0) -> None:
                # Dispatch through Tcl's event loop as Windows does during a drag.
                self.assertTrue(U.PostMessageW(hwnd, message, wp, lp))
                root.update()

            def finish() -> None:
                try:
                    self.assertFalse(keyboard.native.is_resizing)
                    self.assertTrue(U.IsWindowVisible(keyboard.content.winfo_id()))
                    self.assertEqual(keyboard.signature[:2], (root.winfo_width(), root.winfo_height()))
                    keyboard.toggle_extended()
                    keyboard.toggle_numpad()
                    self.assertTrue(keyboard.buttons["NumpadEnter"].winfo_ismapped())
                    self.assertTrue(keyboard.buttons["PrintScreen"].winfo_ismapped())
                    original_dpi = round(keyboard.dpi.scale * 96)
                    rect = wintypes.RECT()
                    U.GetWindowRect(hwnd, ctypes.byref(rect))
                    for dpi in (144, 192, 96, 144, original_dpi):
                        # WM_DPICHANGED carries a borrowed RECT and requires synchronous delivery.
                        U.SendMessageW(hwnd, 0x02E0, dpi | dpi << 16, ctypes.addressof(rect))
                        root.update_idletasks()
                        self.assertEqual(keyboard.dpi.scale, dpi / 96)
                        self.assertEqual(int(root.tk.splitlist(keyboard.status.cget("font"))[1]), -round(8 * dpi / 72))
                    keyboard.reset_size()
                    root.update()
                    self.assertEqual((root.winfo_width(), root.winfo_height()), tuple(keyboard.dpi.pixels(n) for n in DEFAULT_SIZE))
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    keyboard.close()

            def start() -> None:
                try:
                    original = keyboard.signature
                    post(0x0231)
                    self.assertTrue(U.IsWindowVisible(keyboard.content.winfo_id()))
                    rect = wintypes.RECT()
                    U.GetWindowRect(hwnd, ctypes.byref(rect))
                    U.SendMessageW(hwnd, 0x0214, 8, ctypes.addressof(rect))
                    root.geometry("900x350")
                    root.update_idletasks()
                    self.assertTrue(keyboard.native.is_resizing)
                    self.assertFalse(U.IsWindowVisible(keyboard.content.winfo_id()))
                    self.assertEqual(keyboard.signature, original)
                    post(0x0232)
                    root.after(200, finish)
                except BaseException as exc:
                    failures.append(exc)
                    keyboard.close()

            root.after(50, start)
            root.mainloop()
            if failures:
                raise failures[0]


@unittest.skipUnless(sys.platform == "darwin", "Cocoa panel")
class CocoaWindowTests(unittest.TestCase):
    def test_globe_tap_delivers_delayed_f18_to_the_same_app(self) -> None:
        from screen_keyboard import macos
        from screen_keyboard.mac_ui import A, F, PanelController, create_panel
        from screen_keyboard.state import LeftKeyMode
        from utils import ConfigStore

        with (patch.object(ConfigStore, "load", return_value={}),
              patch.object(macos, "frontmost_target", return_value=123) as frontmost,
              patch.object(macos, "switch_input_source") as switch,
              patch.object(macos, "post") as post):
            A.NSApplication.sharedApplication()
            panel = create_panel()
            self.addCleanup(panel.close)
            controller = PanelController.alloc().init()
            controller.setup(panel, LeftKeyMode.CAPS)
            globe = controller.buttons["language"]
            switch.side_effect = [("English", 123), ("Chinese", 123), ("English", 123)]
            for old_source in (None, "English"):
                post.reset_mock()
                globe.performClick_(None)
                switch.assert_called_with(old_source)
                post.assert_not_called()
                F.NSRunLoop.mainRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.15))
                self.assertEqual(post.call_args_list, [call(79, True, 0), call(79, False, 0)])

            post.reset_mock()
            globe.performClick_(None)
            frontmost.return_value = 456
            F.NSRunLoop.mainRunLoop().runUntilDate_(F.NSDate.dateWithTimeIntervalSinceNow_(.15))
            post.assert_not_called()

    def test_panel_blocks_zoom_and_edge_fill(self) -> None:
        from screen_keyboard.mac_ui import A, F, PanelController, create_panel

        A.NSApplication.sharedApplication()
        panel = create_panel()
        self.addCleanup(panel.close)
        controller = PanelController.alloc().init()
        panel.setDelegate_(controller)
        self.addCleanup(panel.setDelegate_, None)
        before = panel.frame()
        zoom = panel.standardWindowButton_(A.NSWindowZoomButton)
        self.assertFalse(zoom.isEnabled())
        self.assertTrue(panel.collectionBehavior() & A.NSWindowCollectionBehaviorFullScreenDisallowsTiling)
        zoom.performClick_(None)
        panel.performZoom_(None)
        self.assertEqual(panel.frame(), before)

        available = A.NSScreen.mainScreen().visibleFrame().size
        resize = controller.windowWillResize_toSize_
        self.assertEqual(resize(panel, available), before.size)
        with (patch.object(panel, "inLiveResize", return_value=True),
              patch.object(panel, "screen", return_value=A.NSScreen.mainScreen())):
            self.assertEqual(resize(panel, F.NSMakeSize(550, 250)), (550, 250))
            self.assertEqual(resize(panel, F.NSMakeSize(available.width, 250)), (before.size.width, 250))
            self.assertEqual(resize(panel, F.NSMakeSize(550, available.height)), (550, before.size.height))

    def test_globe_and_live_resize(self) -> None:
        from screen_keyboard.layout import TOOLBAR_TIPS
        from screen_keyboard.mac_ui import A, PanelController, create_panel
        from utils import ConfigStore

        with tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)):
            A.NSApplication.sharedApplication()
            panel = create_panel()
            try:
                controller = PanelController.alloc().init()
                controller.setup(panel)
                panel.setDelegate_(controller)
                controller.toggle_numpad()
                self.assertFalse(controller.buttons["NumpadEnter"].isHidden())
                controller.toggle_numpad()
                for name, tip in TOOLBAR_TIPS.items():
                    self.assertEqual(controller.buttons[name].toolTip(), tip)
                globe = controller.buttons["language"]
                self.assertIsNotNone(globe.image())
                controller.windowWillStartLiveResize_(None)
                self.assertTrue(all(view.isHidden() for view in panel.contentView().subviews()))
                controller.windowDidEndLiveResize_(None)
                controller.redraw()
                self.assertFalse(globe.isHidden() or controller.header.isHidden() or controller.footer.isHidden())
                self.assertEqual(globe.imagePosition(), A.NSImageOnly)
                self.assertEqual(globe.attributedTitle().string(), "")
                self.assertTrue(controller.buttons["NumpadEnter"].isHidden())
            finally:
                panel.close()
