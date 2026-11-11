"""Tk 8 Windows IME workaround; importing this module does not load Tk.

Tk 8.6.14's HandleIMEComposition stops at the first UTF-16 high surrogate.
Read completed compositions as UTF-16 before that handler runs. Only the
registered Text widget is affected; no global input hook or clipboard is used.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


class TkTextInput:
    """Preserve non-BMP IME input in a Tk Text widget on Windows with Tk 8.

    Construct on the widget's GUI thread and retain until widget destruction.
    Other platforms and Tk 9 use their native input path. Raises OSError if
    Windows cannot install the per-window callback. No extra package is needed.
    """

    _WM_IME_COMPOSITION = 0x010F
    _WM_NCDESTROY = 0x0082
    _GCS_RESULTSTR = 0x0800
    _EVENT = "<<UnicodeImeCommit>>"

    def __init__(self, widget: tk.Text) -> None:
        self.widget = widget
        self._attached = False
        if sys.platform != "win32" or not str(widget.tk.call("package", "require", "Tk")).startswith("8."):
            return

        import ctypes as ct
        from ctypes import wintypes as wt

        self._ct = ct
        self._imm = ct.WinDLL("imm32", use_last_error=True)
        self._comctl = ct.WinDLL("comctl32", use_last_error=True)
        callback_type = ct.WINFUNCTYPE(ct.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM,
                                      wt.LPARAM, ct.c_size_t, ct.c_size_t)
        self._callback = callback_type(self._window_proc)
        self._comctl.SetWindowSubclass.argtypes = [wt.HWND, callback_type, ct.c_size_t, ct.c_size_t]
        self._comctl.SetWindowSubclass.restype = wt.BOOL
        self._comctl.RemoveWindowSubclass.argtypes = [wt.HWND, callback_type, ct.c_size_t]
        self._comctl.RemoveWindowSubclass.restype = wt.BOOL
        self._comctl.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self._comctl.DefSubclassProc.restype = ct.c_ssize_t
        self._imm.ImmGetContext.argtypes = [wt.HWND]
        self._imm.ImmGetContext.restype = wt.HANDLE
        self._imm.ImmReleaseContext.argtypes = [wt.HWND, wt.HANDLE]
        self._imm.ImmReleaseContext.restype = wt.BOOL
        self._imm.ImmGetCompositionStringW.argtypes = [wt.HANDLE, wt.DWORD, ct.c_void_p, wt.DWORD]
        self._imm.ImmGetCompositionStringW.restype = wt.LONG
        # Tk routes native keyboard/IME messages through the toplevel HWND.
        self._hwnd = widget.winfo_toplevel().winfo_id()
        if not self._comctl.SetWindowSubclass(self._hwnd, self._callback, id(self), 0):
            raise OSError("Cannot enable Unicode IME input for the Tk text editor")
        self._attached = True
        # Tcl's %d substitution preserves the entire Unicode string. TextInsert
        # supplies the same selection replacement, undo and scrolling as typing.
        widget.bind(self._EVENT, "tk::TextInsert %W %d")
        widget.bind("<Destroy>", self._on_destroy, add=True)

    def _read_composition(self, hwnd: int) -> str | None:
        context = self._imm.ImmGetContext(hwnd)
        if not context:
            return None
        try:
            size = self._imm.ImmGetCompositionStringW(context, self._GCS_RESULTSTR, None, 0)
            if size <= 0 or size % 2:
                return None
            buffer = self._ct.create_string_buffer(size)
            copied = self._imm.ImmGetCompositionStringW(context, self._GCS_RESULTSTR, buffer, size)
            if copied != size:
                return None
            return buffer.raw.decode("utf-16-le")
        finally:
            self._imm.ImmReleaseContext(hwnd, context)

    def _window_proc(self, hwnd: int, message: int, wparam: int, lparam: int,
                     subclass_id: int, reference: int) -> int:
        try:
            if message == self._WM_NCDESTROY:
                self.close()
            elif (message == self._WM_IME_COMPOSITION and lparam & self._GCS_RESULTSTR
                  and self.widget.focus_get() is self.widget):
                text = self._read_composition(hwnd)
                if text is not None and any(ord(char) > 0xFFFF for char in text):
                    self.widget.event_generate(self._EVENT, data=text, when="tail")
                    return 0
        except Exception as exc:
            # Never let a Python exception escape a native callback.
            self.widget._root().report_callback_exception(type(exc), exc, exc.__traceback__)
        return self._comctl.DefSubclassProc(hwnd, message, wparam, lparam)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.widget:
            self.close()

    def close(self) -> None:
        """Remove the native callback; safe to repeat or call on other platforms."""
        if self._attached:
            self._comctl.RemoveWindowSubclass(self._hwnd, self._callback, id(self))
            self._attached = False
