"""Win32 focus, z-order and interactive-resize behaviour of the floating keyboard."""

import ctypes as C
from ctypes import wintypes as W
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from queue import SimpleQueue
from threading import Thread
import tkinter as tk
import mmap

from utils._win_subclass import WindowSubclass
from .state import LeftKeyMode

U = C.WinDLL("user32", use_last_error=True)


class MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class ToolInfo(C.Structure):
    _fields_ = [("size", W.UINT), ("flags", W.UINT), ("owner", W.HWND), ("tool", C.c_size_t),
                ("rect", W.RECT), ("instance", W.HINSTANCE), ("text", W.LPWSTR),
                ("param", W.LPARAM), ("reserved", C.c_void_p)]


GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
TTS_ALWAYSTIP = 0x01
TTF_IDISHWND = 0x01
TTF_SUBCLASS = 0x10
TTM_ADDTOOLW = 0x0400 + 50
WM_MOUSEACTIVATE = 0x0021
WM_SIZING = 0x0214
WM_EXITSIZEMOVE = 0x0232
MA_NOACTIVATE = 3
GA_ROOT = 2
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
MONITOR_DEFAULTTONEAREST = 2
PER_MONITOR_AWARE_V2 = -4
CURSOR_GAP = 12
REOPEN_EVENT = r"Local\PersonalScripts.ScreenKeyboard.Show"

K = C.WinDLL("kernel32", use_last_error=True)
K.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]
K.CreateEventW.restype = W.HANDLE
K.SetEvent.argtypes = K.CloseHandle.argtypes = [W.HANDLE]
K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
K.WaitForSingleObject.restype = W.DWORD


@contextmanager
def reopen_signal(force_layer: LeftKeyMode | None = None) -> Iterator[Callable[[], LeftKeyMode | None] | None]:
    """Share the latest launch mode before waking the keyboard, including during startup."""
    with mmap.mmap(-1, 1, tagname=REOPEN_EVENT + ".Mode") as payload:
        with _reopen_event(payload, force_layer) as requested:
            yield requested


@contextmanager
def _reopen_event(payload: mmap.mmap, force_layer: LeftKeyMode | None) -> Iterator[Callable[[], LeftKeyMode | None] | None]:
    modes = tuple(LeftKeyMode)
    C.set_last_error(0)
    event = K.CreateEventW(None, False, False, REOPEN_EVENT)
    error = C.get_last_error()
    if not event:
        raise C.WinError(error)
    try:
        if error == 183:  # ERROR_ALREADY_EXISTS
            payload[0] = modes.index(force_layer or LeftKeyMode.NATIVE)
            if not K.SetEvent(event):
                raise C.WinError(C.get_last_error())
            yield None
        else:
            def requested() -> LeftKeyMode | None:
                result = K.WaitForSingleObject(event, 0)
                if result == 0xFFFFFFFF:  # WAIT_FAILED
                    raise C.WinError(C.get_last_error())
                return modes[payload[0]] if result == 0 else None

            yield requested
    finally:
        K.CloseHandle(event)


U.GetAncestor.argtypes = [W.HWND, W.UINT]
U.GetAncestor.restype = W.HWND
U.GetForegroundWindow.restype = W.HWND
U.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                              W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
U.CreateWindowExW.restype = W.HWND
U.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
U.SendMessageW.restype = W.LPARAM
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
    def __init__(self, root: tk.Tk, content_hwnd: int, on_resize_end: Callable[[], None]) -> None:
        self.root = root
        self.content_hwnd = content_hwnd
        self.on_resize_end = on_resize_end
        self.is_resizing = False
        self.commands: SimpleQueue[Callable[[], None] | None] = SimpleQueue()
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
        if message == WM_SIZING and not self.is_resizing:
            self.is_resizing = True
            # The native sizing loop can block Tk callbacks until mouse-up.
            U.ShowWindow(self.content_hwnd, SW_HIDE)
        elif message == WM_EXITSIZEMOVE and self.is_resizing:
            self.is_resizing = False
            U.ShowWindow(self.content_hwnd, SW_SHOWNOACTIVATE)
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
        if not self.closed and not self.is_resizing:
            self.on_resize_end()

    def close(self) -> None:
        self.closed = True
        self.commands.put(None)
        self.hook.close()

    def redraw(self) -> None:
        U.RedrawWindow(self.hwnd, None, None, 0x185)  # invalidate, erase, children, update now

    def add_tooltips(self, tips: dict[int, str]) -> None:
        """Attach native hover tips to the toolbar HWNDs without activating the keyboard."""
        C.windll.comctl32.InitCommonControls()
        self.tooltip = U.CreateWindowExW(WS_EX_TOPMOST | WS_EX_NOACTIVATE, "tooltips_class32", None,
                                         WS_POPUP | TTS_ALWAYSTIP, 0, 0, 0, 0, self.hwnd, None, None, None)
        if not self.tooltip:
            raise C.WinError(C.get_last_error())
        # Keep the Unicode strings alive until Windows destroys the owned tooltip.
        self.tools = [ToolInfo(size=ToolInfo.reserved.offset, flags=TTF_IDISHWND | TTF_SUBCLASS,
                               owner=self.content_hwnd, tool=hwnd, text=text) for hwnd, text in tips.items()]
        for info in self.tools:
            if not U.SendMessageW(self.tooltip, TTM_ADDTOOLW, 0, C.addressof(info)):
                raise RuntimeError("Could not register a keyboard toolbar tooltip.")

    def position(self) -> tuple[int, int]:
        """Return the outer frame origin in screen coordinates."""
        frame = W.RECT()
        if not U.GetWindowRect(self.hwnd, C.byref(frame)):
            raise C.WinError(C.get_last_error())
        return frame.left, frame.top

    def move(self, x: int, y: int) -> None:
        """Move the panel while preserving the foreground input target."""
        if not U.SetWindowPos(self.hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE):
            raise C.WinError(C.get_last_error())

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

    @staticmethod
    def cursor_position() -> W.POINT:
        """Read the pointer in the same physical coordinates used for placement."""
        previous = U.SetThreadDpiAwarenessContext(W.HANDLE(PER_MONITOR_AWARE_V2))
        try:
            point = W.POINT()
            if not U.GetCursorPos(C.byref(point)):
                raise C.WinError(C.get_last_error())
            return point
        finally:
            U.SetThreadDpiAwarenessContext(previous)

    def show(self, point: W.POINT) -> None:
        # Map the disabled, transparent root without deiconify() taking focus.
        # Deliver Tk's pending map/configure events before exposing the controls.
        self.root.state("normal")
        self.root.update()
        self.place_near_cursor(point)
        self.root.update_idletasks()
        self.redraw()
        self.root.attributes("-disabled", False, "-alpha", 1.0)

    def place_near_cursor(self, point: W.POINT, *, reopen: bool = False) -> None:
        # 在同一 DPI 上下文中读取鼠标、外框及工作区，兼容副屏负坐标和混合缩放。
        previous = U.SetThreadDpiAwarenessContext(W.HANDLE(PER_MONITOR_AWARE_V2))
        try:
            rect = W.RECT()
            if not U.GetWindowRect(self.hwnd, C.byref(rect)):
                raise C.WinError(C.get_last_error())
            monitor = U.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
            info = MonitorInfo(size=C.sizeof(MonitorInfo))
            if not U.GetMonitorInfoW(monitor, C.byref(info)):
                raise C.WinError(C.get_last_error())
            work = info.work
            width, height = rect.right - rect.left, rect.bottom - rect.top
            x, y = point.x, point.y
            flags = SWP_NOACTIVATE
            if reopen:
                flags |= SWP_NOSIZE | SWP_SHOWWINDOW
            else:
                width = min(width, work.right - work.left)
                height = min(height, work.bottom - work.top)
                x += CURSOR_GAP
                y += CURSOR_GAP
                if x + width > work.right:
                    x = point.x - width - CURSOR_GAP
                if y + height > work.bottom:
                    y = point.y - height - CURSOR_GAP
            x = max(work.left, min(x, work.right - width))
            y = max(work.top, min(y, work.bottom - height))
            if not U.SetWindowPos(self.hwnd, W.HWND(HWND_TOPMOST), x, y, width, height, flags):
                raise C.WinError(C.get_last_error())
        finally:
            U.SetThreadDpiAwarenessContext(previous)
