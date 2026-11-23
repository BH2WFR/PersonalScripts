"""Verify native Tk resize boundaries and repeated DPI changes without sending input."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(sys.platform == "win32", "Win32 window messages")
class WindowTests(unittest.TestCase):
    def test_toolbar_mode_and_size_survive_reopening(self) -> None:
        from tools.others.screen_keyboard.state import WindowLayout
        from tools.others.screen_keyboard.windows_ui import ScreenKeyboard
        from utils import ConfigStore

        with tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)):
            keyboard = ScreenKeyboard()
            try:
                root = keyboard.window
                root.update()
                button = keyboard.buttons["settings"]
                self.assertTrue(button.winfo_ismapped())
                self.assertEqual(button.cget("text"), "设置")
                with patch.object(keyboard.menu, "tk_popup") as popup:
                    button.event_generate("<ButtonRelease-1>", x=5, y=5)
                    popup.assert_called_once_with(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())
                self.assertFalse(keyboard.selection.get())
                keyboard.menu.invoke(1)
                self.assertEqual(keyboard.buttons["Layer"].cget("text"), "Layer")
                self.assertIs(keyboard.state.store.load()[keyboard.state.setting], True)
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
                self.assertTrue(keyboard.selection.get())
                self.assertTrue(keyboard.buttons["PrintScreen"].winfo_ismapped())
                self.assertTrue(keyboard.buttons["NumpadEnter"].winfo_ismapped())
                self.assertEqual((root.winfo_width(), root.winfo_height()),
                                 (keyboard.dpi.pixels(saved.width), keyboard.dpi.pixels(saved.height)))
                keyboard.menu.invoke(0)
                self.assertEqual(keyboard.buttons["Layer"].cget("text"), "CapsLock")
                keyboard.reset_size()
            finally:
                keyboard.close()
            self.assertIs(keyboard.state.store.load()[keyboard.state.setting], False)
            self.assertEqual(WindowLayout.from_config(keyboard.state.store.load()["windows_window"]), WindowLayout())

    def test_layout_and_dpi(self) -> None:
        from tools.others.screen_keyboard.layout import DEFAULT_SIZE
        from tools.others.screen_keyboard.windows_ui import ScreenKeyboard
        from tools.others.screen_keyboard.window import U
        from utils import ConfigStore

        with tempfile.TemporaryDirectory() as scratch, patch.object(ConfigStore, "directory", return_value=Path(scratch)):
            keyboard = ScreenKeyboard()
            root = keyboard.window
            hwnd = keyboard.native.hwnd
            U.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            U.PostMessageW.restype = wintypes.BOOL
            U.SendMessageW.argtypes = U.PostMessageW.argtypes
            U.SendMessageW.restype = wintypes.LPARAM
            failures = []

            def post(message: int, wp: int = 0, lp: int = 0) -> None:
                # Dispatch through Tcl's event loop as Windows does during a drag.
                self.assertTrue(U.PostMessageW(hwnd, message, wp, lp))
                root.update()

            def finish() -> None:
                try:
                    self.assertFalse(keyboard.native.is_resizing)
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
                    root.geometry("900x350")
                    root.update_idletasks()
                    self.assertTrue(keyboard.native.is_resizing)
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
