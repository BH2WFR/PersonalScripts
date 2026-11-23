"""Win32 focus, z-order and interactive-resize behaviour of the floating keyboard."""

import ctypes as C
from ctypes import wintypes as W
from collections.abc import Callable
from queue import SimpleQueue
from threading import Thread
import tkinter as tk

from utils._win_subclass import WindowSubclass

U = C.WinDLL("user32", use_last_error=True)


class MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WM_MOUSEACTIVATE = 0x0021
WM_ENTERSIZEMOVE = 0x0231
WM_EXITSIZEMOVE = 0x0232
MA_NOACTIVATE = 3
GA_ROOT = 2
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOP = 0
HWND_TOPMOST = -1
MONITOR_DEFAULTTONEAREST = 2
PER_MONITOR_AWARE_V2 = -4
CURSOR_GAP = 12


U.GetAncestor.argtypes = [W.HWND, W.UINT]
U.GetAncestor.restype = W.HWND
U.GetForegroundWindow.restype = W.HWND
U.ShowWindow.argtypes = [W.HWND, C.c_int]
U.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT]
U.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
U.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
U.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
U.MonitorFromPoint.argtypes = [W.POINT, W.DWORD]
U.MonitorFromPoint.restype = W.HANDLE
U.GetMonitorInfoW.argtypes = [W.HANDLE, C.POINTER(MonitorInfo)]
U.SetThreadDpiAwarenessContext.argtypes = [W.HANDLE]
U.SetThreadDpiAwarenessContext.restype = W.HANDLE


U.GetWindowLongW.argtypes = [W.HWND, C.c_int]
U.GetWindowLongW.restype = W.LONG
U.SetWindowLongW.argtypes = [W.HWND, C.c_int, W.LONG]
U.SetWindowLongW.restype = W.LONG
U.MonitorFromRect.argtypes = [C.POINTER(W.RECT), W.DWORD]
U.MonitorFromRect.restype = W.HANDLE
U.RedrawWindow.argtypes = [W.HWND, C.POINTER(W.RECT), W.HANDLE, W.UINT]


class NonactivatingWindow:
    def __init__(self, root: tk.Tk, on_resize_end: Callable[[], None]) -> None:
        self.root = root
        self.on_resize_end = on_resize_end
        self.is_resizing = False
        self.commands: SimpleQueue[Callable[[], None] | None] = SimpleQueue()
        # Tk 首次映射会主动 SetActiveWindow；先在禁用状态完成映射。
        root.attributes("-disabled", True)
        root.deiconify()
        root.update_idletasks()
        root.withdraw()
        root.attributes("-disabled", False)
        self.hwnd = U.GetAncestor(root.winfo_id(), GA_ROOT)
        style = U.GetWindowLongW(self.hwnd, GWL_STYLE)
        U.SetWindowLongW(self.hwnd, GWL_STYLE, style & ~WS_MINIMIZEBOX)
        style = U.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        U.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                           style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        self.hook = WindowSubclass(self.hwnd, self.window_message, root.report_callback_exception)
        self.closed = False
        Thread(target=self.dispatch, daemon=True).start()

    def window_message(self, hwnd: int, message: int, wp: int, lp: int) -> int | None:
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if message == WM_ENTERSIZEMOVE:
            self.is_resizing = True
        elif message == WM_EXITSIZEMOVE:
            self.commands.put(self.finish_resize)
        elif message == 0x02E0 and lp:  # Clamp TkDpi's suggested outer rectangle to the work area.
            rect = C.cast(lp, C.POINTER(W.RECT)).contents
            monitor = U.MonitorFromRect(C.byref(rect), MONITOR_DEFAULTTONEAREST)
            info = MonitorInfo(size=C.sizeof(MonitorInfo))
            if U.GetMonitorInfoW(monitor, C.byref(info)):
                work = info.work
                w = min(rect.right - rect.left, work.right - work.left)
                h = min(rect.bottom - rect.top, work.bottom - work.top)
                rect.left = max(work.left, min(rect.left, work.right - w))
                rect.top = max(work.top, min(rect.top, work.bottom - h))
                rect.right, rect.bottom = rect.left + w, rect.top + h
        return None

    def dispatch(self) -> None:
        # A native sizing loop can call the WndProc while Tcl is busy.
        while (command := self.commands.get()) is not None and not self.closed:
            try:
                self.root.after(0, command)
            except RuntimeError:
                if not self.closed:
                    raise

    def finish_resize(self) -> None:
        if not self.closed:
            self.is_resizing = False
            self.on_resize_end()

    def close(self) -> None:
        self.closed = True
        self.commands.put(None)
        self.hook.close()

    def redraw(self) -> None:
        U.RedrawWindow(self.hwnd, None, None, 0x185)  # invalidate, erase, children, update now

    def fit_client(self, width: int, height: int) -> None:
        """Account for the actual monitor's nonclient borders after Tk sets geometry."""
        client, frame = W.RECT(), W.RECT()
        if not U.GetClientRect(self.hwnd, C.byref(client)):
            raise C.WinError(C.get_last_error())
        if (width, height) != (client.right, client.bottom):
            if not U.GetWindowRect(self.hwnd, C.byref(frame)):
                raise C.WinError(C.get_last_error())
            if not U.SetWindowPos(self.hwnd, None, 0, 0, frame.right - frame.left + width - client.right,
                                  frame.bottom - frame.top + height - client.bottom,
                                  SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE):
                raise C.WinError(C.get_last_error())

    def show(self) -> None:
        self.root.update_idletasks()
        self.place_near_cursor()
        U.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        # 显示和定位后再提升 Z 序，盖过已存在的置顶窗口，保留输入目标焦点。
        U.SetWindowPos(self.hwnd, W.HWND(HWND_TOP), 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)

    def place_near_cursor(self) -> None:
        # 在同一 DPI 上下文中读取鼠标、外框及工作区，兼容副屏负坐标和混合缩放。
        previous = U.SetThreadDpiAwarenessContext(W.HANDLE(PER_MONITOR_AWARE_V2))
        try:
            point, rect = W.POINT(), W.RECT()
            U.GetCursorPos(C.byref(point))
            U.GetWindowRect(self.hwnd, C.byref(rect))
            monitor = U.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
            info = MonitorInfo(size=C.sizeof(MonitorInfo))
            if not U.GetMonitorInfoW(monitor, C.byref(info)):
                raise C.WinError(C.get_last_error())
            work = info.work
            width = min(rect.right - rect.left, work.right - work.left)
            height = min(rect.bottom - rect.top, work.bottom - work.top)
            x, y = point.x + CURSOR_GAP, point.y + CURSOR_GAP
            if x + width > work.right:
                x = point.x - width - CURSOR_GAP
            if y + height > work.bottom:
                y = point.y - height - CURSOR_GAP
            x = max(work.left, min(x, work.right - width))
            y = max(work.top, min(y, work.bottom - height))
            U.SetWindowPos(self.hwnd, W.HWND(HWND_TOPMOST), x, y, width, height, SWP_NOACTIVATE)
        finally:
            U.SetThreadDpiAwarenessContext(previous)
