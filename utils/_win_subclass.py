"""Private, GUI-thread-only Windows subclass lifetime management."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from types import TracebackType


class WindowSubclass:
    """Forward unhandled messages and detach before a native window is destroyed."""

    def __init__(self, hwnd: int, handler: Callable[[int, int, int, int], int | None],
                 report_error: Callable[[type[BaseException], BaseException, TracebackType | None], None]) -> None:
        from ctypes import wintypes as wt

        self.hwnd = hwnd
        self._handler = handler
        self._report_error = report_error
        self._api = ctypes.WinDLL("comctl32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM,
                                          wt.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
        self._callback = callback_type(self._dispatch)
        self._api.SetWindowSubclass.argtypes = [wt.HWND, callback_type, ctypes.c_size_t, ctypes.c_size_t]
        self._api.SetWindowSubclass.restype = wt.BOOL
        self._api.RemoveWindowSubclass.argtypes = [wt.HWND, callback_type, ctypes.c_size_t]
        self._api.RemoveWindowSubclass.restype = wt.BOOL
        self._api.DefSubclassProc.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        self._api.DefSubclassProc.restype = ctypes.c_ssize_t
        self.attached = bool(self._api.SetWindowSubclass(hwnd, self._callback, id(self), 0))
        if not self.attached:
            raise OSError("Cannot install the window compatibility callback")

    def _dispatch(self, hwnd: int, message: int, wparam: int, lparam: int,
                  subclass_id: int, reference: int) -> int:
        try:
            if message == 0x0082:  # WM_NCDESTROY: detach before forwarding destruction.
                self.close()
            else:
                result = self._handler(hwnd, message, wparam, lparam)
                if result is not None:
                    return result
        except Exception as exc:
            self._report_error(type(exc), exc, exc.__traceback__)
        return self._api.DefSubclassProc(hwnd, message, wparam, lparam)

    def close(self) -> None:
        """Detach once while keeping the callback alive through the current call."""
        if self.attached:
            if not self._api.RemoveWindowSubclass(self.hwnd, self._callback, id(self)):
                raise OSError("Cannot remove the window compatibility callback")
            self.attached = False
