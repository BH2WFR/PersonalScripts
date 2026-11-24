"""Validate native DPI notifications on our own windows without changing displays."""

import ctypes
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import System, TkDpi


@unittest.skipUnless(sys.platform == "win32", "Windows per-monitor DPI messages")
class WindowsDpiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        System.enable_dpi_awareness()

    def setUp(self) -> None:
        import tkinter as tk
        from ctypes import wintypes as wt

        self.root = tk.Tk()
        self.root.withdraw()
        self.errors: list[BaseException] = []
        self.root.report_callback_exception = lambda kind, exc, trace: self.errors.append(exc)
        self.dpi = TkDpi(self.root)
        self.root.geometry(f"{self.dpi.pixels(1100)}x{self.dpi.pixels(720)}")
        self.editor = tk.Text(self.root, font=self.dpi.font(points=11), height=5, padx=4)
        self.editor.pack(fill="both", expand=True)
        self.editor.insert("1.0", "A😀中\n" * 50)
        self.dpi.track_spacing()
        self.dpi.start(lambda scale: self.root.minsize(self.dpi.pixels(800), self.dpi.pixels(500)))
        self.addCleanup(self.root.destroy)
        self.root.update()
        self.user32 = ctypes.WinDLL("user32")
        self.user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        self.user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        self.user32.GetWindowRect.restype = wt.BOOL

    def notify(self, dpi: int) -> None:
        from ctypes import wintypes as wt

        # A real WM_DPICHANGED carries the recommended outer-window rectangle.
        rect = wt.RECT(30, 40, 30 + round(1100 * dpi / 96), 40 + round(720 * dpi / 96))
        self.user32.SendMessageW(self.dpi._hwnd, 0x02E0, dpi | (dpi << 16), ctypes.addressof(rect))
        self.root.update()
        actual = wt.RECT()
        self.assertTrue(self.user32.GetWindowRect(self.dpi._hwnd, ctypes.byref(actual)))
        self.assertEqual((actual.left, actual.top, actual.right, actual.bottom),
                         (rect.left, rect.top, rect.right, rect.bottom))
        self.assertEqual(self.errors, [])

    def test_startup_reads_actual_window_dpi(self) -> None:
        dpi = self.dpi._user32.GetDpiForWindow(self.dpi._hwnd)
        self.assertEqual(self.dpi.scale, dpi / 96)
        self.assertEqual(self.dpi.font().cget("size"), -round(12 * dpi / 96))

    def test_native_roundtrip_resizes_fonts_and_spacing_without_data_loss(self) -> None:
        text = self.editor.get("1.0", "end-1c")
        self.editor.tag_add("sel", "1.0", "1.1")
        editor_font = self.editor.cget("font")
        original_size = self.root.tk.call("font", "configure", "TkDefaultFont", "-size")
        for dpi in (96, 144, 192, 96, 192, 144):
            with self.subTest(dpi=dpi):
                self.notify(dpi)
                self.assertEqual(self.dpi.scale, dpi / 96)
                self.assertEqual(self.root.tk.call("font", "configure", editor_font, "-size"), -round(15 * dpi / 96))
                self.assertEqual(self.root.minsize(), (round(800 * dpi / 96), round(500 * dpi / 96)))
                self.assertEqual(int(self.editor.cget("padx")), round(4 * dpi / 96))
                self.assertEqual(self.editor.get("1.0", "end-1c"), text)
                self.assertEqual(tuple(map(str, self.editor.tag_ranges("sel"))), ("1.0", "1.1"))
                self.assertEqual(self.root.tk.call("font", "configure", "TkDefaultFont", "-size"), original_size)

    def test_window_fonts_are_independent_and_hooks_release(self) -> None:
        import tkinter as tk

        other = tk.Toplevel(self.root)
        other.withdraw()
        controller = TkDpi(other)
        original = controller.font().cget("size")
        controller.start(lambda scale: None)
        self.notify(192)
        self.assertEqual(controller.font().cget("size"), original)
        hook = controller._hook
        other.destroy()
        self.assertIsNotNone(hook)
        assert hook is not None
        self.assertFalse(hook.attached)
        controller.close()


if __name__ == "__main__":
    unittest.main()
