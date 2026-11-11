"""Exercise Windows IME commits without changing the user's IME or clipboard."""

import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils.tk_input import TkTextInput


@unittest.skipUnless(sys.platform == "win32", "Windows IME compatibility")
class ImeInputTests(unittest.TestCase):
    def setUp(self) -> None:
        import tkinter as tk
        from tkinter.scrolledtext import ScrolledText
        from ctypes import wintypes as wt

        self.root = tk.Tk()
        self.root.withdraw()
        self.text = ScrolledText(self.root, undo=True)
        self.text.pack()
        self.text.winfo_id()  # Realize the hidden test widget before queuing events.
        self.guard = TkTextInput(self.text)
        self.addCleanup(self.root.destroy)
        self.addCleanup(self.guard.close)
        if not self.guard._attached:
            self.skipTest("Native Tk 9 input is used")
        self.root.update()
        self.user32 = ctypes.WinDLL("user32")
        self.user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self.user32.SendMessageW.restype = ctypes.c_ssize_t

    def commit(self, text: str) -> None:
        raw = text.encode("utf-16-le")

        def read(context: int, flag: int, buffer: ctypes.Array[ctypes.c_char] | None, size: int) -> int:
            if buffer is not None:
                ctypes.memmove(buffer, raw, len(raw))
            return len(raw)

        with (patch.object(self.text, "focus_get", return_value=self.text),
              patch.object(self.guard._imm, "ImmGetContext", return_value=1),
              patch.object(self.guard._imm, "ImmReleaseContext", return_value=1) as release,
              patch.object(self.guard._imm, "ImmGetCompositionStringW", side_effect=read)):
            self.user32.SendMessageW(self.guard._hwnd, 0x010F, 0, 0x0800)
            release.assert_called_once_with(self.guard._hwnd, 1)
        self.root.update()

    def test_ime_commit_preserves_entire_unicode_string(self) -> None:
        value = "前😀后𠀀👩\u200d💻\U0010ffff尾"
        self.commit(value)
        self.assertEqual(self.text.get("1.0", "end-1c"), value)

    def test_selection_replacement_and_undo(self) -> None:
        self.text.insert("1.0", "old")
        self.text.edit_separator()
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "1.1")
        self.commit("😀")
        self.assertEqual(self.text.get("1.0", "end-1c"), "😀")
        self.text.edit_undo()
        self.assertEqual(self.text.get("1.0", "end-1c"), "old")

    def test_other_focus_and_unfinished_composition_are_not_intercepted(self) -> None:
        with (patch.object(self.guard, "_read_composition") as read,
              patch.object(self.text, "focus_get", return_value=None)):
            self.user32.SendMessageW(self.guard._hwnd, 0x010F, 0, 0x0800)
            read.assert_not_called()
        with (patch.object(self.guard, "_read_composition") as read,
              patch.object(self.text, "focus_get", return_value=self.text)):
            self.user32.SendMessageW(self.guard._hwnd, 0x010F, 0, 0x0008)
            read.assert_not_called()

    def test_bmp_commit_keeps_native_handler(self) -> None:
        with (patch.object(self.text, "focus_get", return_value=self.text),
              patch.object(self.guard, "_read_composition", return_value="中文abc"),
              patch.object(self.text, "event_generate") as event):
            self.user32.SendMessageW(self.guard._hwnd, 0x010F, 0, 0x0800)
            event.assert_not_called()

    def test_destroy_text_removes_callback_before_toplevel(self) -> None:
        self.text.destroy()
        self.assertFalse(self.guard._attached)
        self.guard.close()


class PlatformTests(unittest.TestCase):
    def test_other_platforms_do_not_touch_widget_or_load_native_libraries(self) -> None:
        for platform in ("darwin", "linux"):
            with patch("utils.tk_input.sys.platform", platform):
                guard = TkTextInput(None)  # type: ignore[arg-type]
                guard.close()
                self.assertFalse(guard._attached)


if __name__ == "__main__":
    unittest.main()
