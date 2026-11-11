"""Exercise the standalone Tk inspector with generated text and mocked clipboard I/O."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("unicode_inspector_test_entry", ROOT / "tools/others/unicode-inspector.py")
assert SPEC is not None and SPEC.loader is not None
entry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entry
SPEC.loader.exec_module(entry)


class EntryTests(unittest.TestCase):
    def test_help_does_not_require_tk(self) -> None:
        for flag in ("--help", "-h"):
            with patch.dict(sys.modules, {"tkinter": None}), patch.object(sys, "argv", ["unicode-inspector.py", flag]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
                    entry.main()
                self.assertEqual(result.exception.code, 0)
                self.assertIn("Requirements:", output.getvalue())

    def test_clipboard_and_text_conflict_before_window_creation(self) -> None:
        with patch.object(sys, "argv", ["unicode-inspector.py", "--clip", "text"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                entry.main()
        self.assertEqual(result.exception.code, 2)


class GuiTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("Tkinter is unavailable")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"A graphical Tk display is required: {exc}")
        self.root.withdraw()
        self.window = entry.UnicodeInspector(self.root)
        self.addCleanup(self.window.close)

    def drain(self) -> None:
        deadline = time.monotonic() + 5
        while self.window._render_job is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.002)
        self.assertIsNone(self.window._render_job)
        self.root.update()

    def test_original_preserves_nul_crlf_spaces_and_non_bmp(self) -> None:
        text = " \x00\r\n中😀e\u0301\t "
        self.window.set_text(text)
        self.drain()
        self.assertEqual(self.window.report.text, text)
        self.assertEqual(self.window.original.get("1.0", "end-1c"), text)
        self.assertEqual(len(self.window.table.get_children()), len(text))
        self.assertEqual(self.window.statistics["Characters"].get(), str(len(text)))

    def test_paste_whitespace_and_unavailable_clipboard(self) -> None:
        import tkinter as tk
        with patch.object(self.root, "clipboard_get", return_value=" \t\n "):
            self.window.paste()
        self.assertEqual(self.window.report.text, " \t\n ")
        with patch.object(self.root, "clipboard_get", side_effect=tk.TclError("no text")):
            self.window.paste()
        self.assertEqual(self.window.report.text, " \t\n ")
        self.assertIn("no readable text", self.window.status.get())

    def test_copy_rows_uses_source_order_and_safe_cells(self) -> None:
        self.window.set_text("A\n😀")
        self.window.table.selection_set(("2", "1"))
        with patch.object(self.window, "_copy") as copy:
            self.window.copy_rows()
        value = copy.call_args.args[0]
        self.assertEqual(len(value.splitlines()), 2)
        self.assertTrue(value.startswith("1\t[LF]\tU+000A"))
        self.assertIn("2\t😀\tU+1F600", value)

    def test_report_and_original_copy_use_current_editor_text(self) -> None:
        self.window.set_text("old")
        self.window.original.delete("1.0", "end")
        self.window.original.insert("1.0", "\tnew\n ")
        with patch.object(self.window, "_copy") as copy:
            self.window.copy_original()
            copy.assert_called_with("\tnew\n ")
            self.window.copy_report()
            self.assertTrue(copy.call_args.args[0].startswith("Original text:\n\tnew\n \n\n"))
        self.assertEqual(self.window.report.text, "\tnew\n ")

    def test_reanalysis_cancels_stale_batch_and_clear_empties_table(self) -> None:
        self.window.set_text("x" * 2500)
        self.assertIsNotNone(self.window._render_job)
        self.window.set_text("😀\u200b")
        self.drain()
        self.assertEqual(self.window.table.get_children(), ("0", "1"))
        self.window.set_text("")
        self.assertEqual(self.window.table.get_children(), ())
        self.assertTrue(all(value.get() == "0" for value in self.window.statistics.values()))

    def test_copy_uses_tk_and_shortcuts_match_window_system(self) -> None:
        with patch.object(self.root, "clipboard_clear") as clear, patch.object(self.root, "clipboard_append") as append:
            self.window.set_text("A\nB")
            self.window.copy_original()
        clear.assert_called_once()
        append.assert_called_once_with("A\nB")
        modifier = "Command" if self.root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        self.assertTrue(self.window.table.bind(f"<{modifier}-c>"))
        self.assertTrue(self.root.bind(f"<{modifier}-Return>"))

    def test_edit_during_render_keeps_pending_analysis_notice(self) -> None:
        self.window.set_text("x" * 1200)
        self.window.original.insert("end-1c", "new")
        self.drain()
        self.assertEqual(self.window.report.text, "x" * 1200)
        self.assertIn("Analyze to update", self.window.status.get())


if __name__ == "__main__":
    unittest.main()
