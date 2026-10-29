"""Windows low-level hooks, input sending and window metadata.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
import threading
import ctypes.wintypes
from .models import WindowInfo, EventSink, Hook
_OS = sys.platform


_WH_KEYBOARD_LL = 13
_WH_MOUSE_LL = 14
_WM_KEYDOWN, _WM_KEYUP = 0x0100, 0x0101
_WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x0104, 0x0105
_WM_LBUTTONDOWN, _WM_LBUTTONUP = 0x0201, 0x0202
_WM_RBUTTONDOWN, _WM_RBUTTONUP = 0x0204, 0x0205
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208
_WM_XBUTTONDOWN, _WM_XBUTTONUP = 0x020B, 0x020C
_WM_MOUSEMOVE = 0x0200
_WM_MOUSEWHEEL, _WM_MOUSEHWHEEL = 0x020A, 0x020E

_BYTE_MASK = 0xFF
_SCAN_SHIFT = 8
_FLAGS_SHIFT = 16


def _pack_keyboard(vk: int, scan_code: int, flags: int) -> int:
    """Pack hook fields into a 32-bit-safe message word without losing sides."""
    return (vk & _BYTE_MASK) | ((scan_code & _BYTE_MASK) << _SCAN_SHIFT) | ((flags & _BYTE_MASK) << _FLAGS_SHIFT)


def _dispatch_keyboard(sink: EventSink, packed: int, message: int) -> None:
    """Decode a posted key message and dispatch the original scan code/flags."""
    if message not in (_WM_KEYDOWN, _WM_SYSKEYDOWN, _WM_KEYUP, _WM_SYSKEYUP):
        return
    vk = packed & _BYTE_MASK
    flags = (packed >> _FLAGS_SHIFT) & _BYTE_MASK
    scan = WindowsScanCode.from_hook((packed >> _SCAN_SHIFT) & _BYTE_MASK, flags)
    sink._emit_key(
        Keyboard.windows_key_name(vk, scan), message in (_WM_KEYDOWN, _WM_SYSKEYDOWN), vk,
        scan_code=scan, raw_flags=flags,
    )

def create_hook(sink: EventSink) -> Hook | None:
    """Low-level Windows hooks.  Returns object with .start() / .stop()."""
    if _OS != "win32":
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # ---- ctypes types --------------------------------------------------------
    ULONG_PTR = ctypes.c_size_t

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
            ("wParam", ULONG_PTR), ("lParam", ctypes.c_ssize_t),
            ("time", ctypes.c_uint), ("pt", POINT),
            ("lPrivate", ctypes.c_uint32),
        ]

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", ctypes.c_uint32), ("scanCode", ctypes.c_uint32),
            ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", POINT), ("mouseData", ctypes.c_uint32),
            ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
            ("dwExtraInfo", ULONG_PTR),
        ]

    # ---- function prototypes -------------------------------------------------
    HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, ULONG_PTR, ctypes.c_ssize_t,
    )
    _SetWindowsHookExW = user32.SetWindowsHookExW
    _SetWindowsHookExW.argtypes = [
        ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32,
    ]
    _SetWindowsHookExW.restype = ctypes.c_void_p

    _UnhookWindowsHookEx = user32.UnhookWindowsHookEx
    _UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    _UnhookWindowsHookEx.restype = ctypes.c_bool

    _CallNextHookEx = user32.CallNextHookEx
    _CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ULONG_PTR, ctypes.c_ssize_t,
    ]
    _CallNextHookEx.restype = ctypes.c_ssize_t

    _GetMessageW = user32.GetMessageW
    _GetMessageW.argtypes = [
        ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ]
    _GetMessageW.restype = ctypes.c_int

    _PostThreadMessageW = user32.PostThreadMessageW
    _PostThreadMessageW.argtypes = [
        ctypes.c_uint32, ctypes.c_uint, ULONG_PTR, ctypes.c_ssize_t,
    ]
    _PostThreadMessageW.restype = ctypes.c_bool

    _GetCurrentThreadId = kernel32.GetCurrentThreadId
    _GetCurrentThreadId.argtypes = []
    _GetCurrentThreadId.restype = ctypes.c_uint32

    _WM_STOP = 0x0401
    _WM_PROCESS = 0x0410

    # Packing helpers — coordinates get 32 bits each in wParam;
    # lParam gets message id (low 16) + auxiliary data (upper 48).
    def _pack_mouse(x: int, y: int, msg_id: int, aux: int = 0) -> tuple:
        """Pack mouse event into (wParam, lParam) for PostThreadMessageW."""
        wx = ctypes.c_ulonglong(ctypes.c_uint32(x).value).value
        wy = ctypes.c_ulonglong(ctypes.c_uint32(y).value).value
        wp = (wx << 32) | wy
        lp = (msg_id & 0xFFFF) | ((aux & 0xFFFFFFFFFFFF) << 16)
        return (wp, lp)

    def _unpack_mouse(wParam, lParam) -> tuple:
        """Unpack mouse event → (x, y, msg_id, aux)."""
        msg_id = lParam & 0xFFFF
        aux = (lParam >> 16) & 0xFFFFFFFFFFFF
        wx = (wParam >> 32) & 0xFFFFFFFF
        wy = wParam & 0xFFFFFFFF
        x = ctypes.c_int32(wx).value
        y = ctypes.c_int32(wy).value
        return (x, y, msg_id, aux)

    class WinHook:
        def __init__(self):
            self._kbd_hook = None
            self._mou_hook = None
            self._thread_id = None
            self._ready = threading.Event()
            self.running = False

        # ---- hook callbacks --------------------------------------------------

        def _kbd_proc(self, code, wParam, lParam):
            if code >= 0:
                ks = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if wParam == _WM_KEYDOWN and ks.vkCode == 0x43:  # VK_C
                    if ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000:
                        _PostThreadMessageW(self._thread_id, _WM_STOP, 0, 0)
                packed = _pack_keyboard(ks.vkCode, ks.scanCode, ks.flags)
                _PostThreadMessageW(self._thread_id, _WM_PROCESS, packed, wParam)
            return _CallNextHookEx(None, code, wParam, lParam)

        def _mou_proc(self, code, wParam, lParam):
            if code >= 0:
                ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                x, y = int(ms.pt.x), int(ms.pt.y)
                msg = wParam

                if msg in (_WM_MOUSEWHEEL, _WM_MOUSEHWHEEL):
                    delta = ctypes.c_short(ms.mouseData >> 16).value
                    wp, lp = _pack_mouse(x, y, msg, delta)
                elif msg in (_WM_XBUTTONDOWN, _WM_XBUTTONUP):
                    xbtn = ms.mouseData >> 16
                    wp, lp = _pack_mouse(x, y, msg, xbtn)
                else:
                    wp, lp = _pack_mouse(x, y, msg)
                _PostThreadMessageW(self._thread_id, _WM_PROCESS, wp, lp)
            return _CallNextHookEx(None, code, wParam, lParam)

        # ---- message processing ----------------------------------------------

        def _process_kbd(self, packed: int, msg_id: int) -> None:
            _dispatch_keyboard(sink, packed, msg_id)

        def _process_mou(self, x: int, y: int, msg_id: int, aux: int):
            if msg_id in (_WM_LBUTTONDOWN,):
                sink._emit_mouse(x, y, "left", True)
            elif msg_id in (_WM_LBUTTONUP,):
                sink._emit_mouse(x, y, "left", False)
            elif msg_id in (_WM_RBUTTONDOWN,):
                sink._emit_mouse(x, y, "right", True)
            elif msg_id in (_WM_RBUTTONUP,):
                sink._emit_mouse(x, y, "right", False)
            elif msg_id in (_WM_MBUTTONDOWN,):
                sink._emit_mouse(x, y, "middle", True)
            elif msg_id in (_WM_MBUTTONUP,):
                sink._emit_mouse(x, y, "middle", False)
            elif msg_id in (_WM_XBUTTONDOWN,):
                name = "back" if aux == 1 else "forward" if aux == 2 else f"xbutton{aux}"
                sink._emit_mouse(x, y, name, True)
            elif msg_id in (_WM_XBUTTONUP,):
                name = "back" if aux == 1 else "forward" if aux == 2 else f"xbutton{aux}"
                sink._emit_mouse(x, y, name, False)
            elif msg_id == _WM_MOUSEWHEEL:
                delta = ctypes.c_short(aux & 0xFFFF).value // 120
                sink._emit_scroll(0, delta)
            elif msg_id == _WM_MOUSEHWHEEL:
                delta = ctypes.c_short(aux & 0xFFFF).value // 120
                sink._emit_scroll(delta, 0)

        def _process_message(self, wParam, lParam):
            msg_id = lParam & 0xFFFF
            # Keyboard: lParam = message id; wParam = VK, scan code and flags.
            if msg_id in (_WM_KEYDOWN, _WM_SYSKEYDOWN, _WM_KEYUP, _WM_SYSKEYUP):
                self._process_kbd(int(wParam), msg_id)
            else:
                x, y, msg_id, aux = _unpack_mouse(wParam, lParam)
                self._process_mou(x, y, msg_id, aux)

        # ---- message loop ----------------------------------------------------

        def start(self) -> None:
            self._thread_id = _GetCurrentThreadId()
            kbd_cb = HOOKPROC(self._kbd_proc)
            mou_cb = HOOKPROC(self._mou_proc)
            self._kbd_hook = _SetWindowsHookExW(_WH_KEYBOARD_LL, kbd_cb, None, 0)
            self._mou_hook = _SetWindowsHookExW(_WH_MOUSE_LL, mou_cb, None, 0)
            if self._kbd_hook is None or self._mou_hook is None:
                self._ready.set()
                raise OSError("Failed to install Windows hooks")
            self._kbd_cb = kbd_cb
            self._mou_cb = mou_cb
            self._ready.set()

            self.running = True
            msg = MSG()
            while self.running:
                result = _GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if result > 0:
                    if msg.message == _WM_STOP:
                        break
                    elif msg.message == _WM_PROCESS:
                        self._process_message(msg.wParam, msg.lParam)

        def stop(self) -> None:
            self.running = False
            if self._thread_id is not None:
                _PostThreadMessageW(self._thread_id, _WM_STOP, 0, 0)
                time.sleep(0.02)
            if self._kbd_hook is not None:
                _UnhookWindowsHookEx(self._kbd_hook)
                self._kbd_hook = None
            if self._mou_hook is not None:
                _UnhookWindowsHookEx(self._mou_hook)
                self._mou_hook = None

    return WinHook()

class _WinController:
    """Send keyboard / mouse events via SendInput API."""

    def __init__(self):
        self._u32 = ctypes.windll.user32

    # ctypes structures for SendInput (instantiated via name to avoid
    # forward-reference hassles inside a class body)
    def _make_kbd_input(self):
        class K(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("dwExtraInfo", ctypes.c_void_p),
            ]
        return K

    def _make_mouse_input(self):
        class M(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_void_p),
            ]
        return M

    def _make_input(self, KI, MI):
        class I(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_uint32), ("ki", KI), ("mi", MI),
            ]
        return I

    _K = None  # cached structure classes
    _M = None
    _I = None

    def _kbd_input(self):
        if self._K is None:
            self._K = self._make_kbd_input()
        return self._K()

    def _mouse_input(self):
        if self._M is None:
            self._M = self._make_mouse_input()
        return self._M()

    def _input(self):
        if self._I is None:
            self._I = self._make_input(self._make_kbd_input(), self._make_mouse_input())
        return self._I()

    _INPUT_KEYBOARD = 1
    _INPUT_MOUSE = 0
    _KEYEVENTF_KEYUP = 0x0002

    def _send_kbd(self, vk: int, flags: int = 0):
        inp = self._input()
        inp.type = self._INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.dwFlags = flags
        self._u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def press(self, name: str) -> None:
        vk = (Keyboard.windows_virtual_key(name) or 0)
        if vk:
            self._send_kbd(vk, 0)

    def release(self, name: str) -> None:
        vk = (Keyboard.windows_virtual_key(name) or 0)
        if vk:
            self._send_kbd(vk, self._KEYEVENTF_KEYUP)

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        self._u32.SetCursorPos(x, y)

    def _send_mouse(self, flags: int, data: int = 0):
        inp = self._input()
        inp.type = self._INPUT_MOUSE
        inp.mi.mouseData = data
        inp.mi.dwFlags = flags
        self._u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    _INPUT_MOUSE = 0
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040
    _MOUSEEVENTF_XDOWN = 0x0080
    _MOUSEEVENTF_XUP = 0x0100
    _MOUSEEVENTF_WHEEL = 0x0800
    _MOUSEEVENTF_HWHEEL = 0x1000

    _BTN_DOWN = {
        "left": _MOUSEEVENTF_LEFTDOWN,
        "right": _MOUSEEVENTF_RIGHTDOWN,
        "middle": _MOUSEEVENTF_MIDDLEDOWN,
        "back": _MOUSEEVENTF_XDOWN,
        "forward": _MOUSEEVENTF_XDOWN,
    }
    _BTN_UP = {
        "left": _MOUSEEVENTF_LEFTUP,
        "right": _MOUSEEVENTF_RIGHTUP,
        "middle": _MOUSEEVENTF_MIDDLEUP,
        "back": _MOUSEEVENTF_XUP,
        "forward": _MOUSEEVENTF_XUP,
    }
    _BTN_XDATA = {"back": 1, "forward": 2}

    def mouse_down(self, button: str = "left") -> None:
        flags = self._BTN_DOWN.get(button, self._MOUSEEVENTF_LEFTDOWN)
        xdata = self._BTN_XDATA.get(button, 0)
        self._send_mouse(flags, xdata << 16)

    def mouse_up(self, button: str = "left") -> None:
        flags = self._BTN_UP.get(button, self._MOUSEEVENTF_LEFTUP)
        xdata = self._BTN_XDATA.get(button, 0)
        self._send_mouse(flags, xdata << 16)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        if dy:
            self._send_mouse(self._MOUSEEVENTF_WHEEL, dy * 120)
        if dx:
            self._send_mouse(self._MOUSEEVENTF_HWHEEL, dx * 120)

    def set_modifier(self, name: str, on: bool) -> None:
        self.press(name) if on else self.release(name)

def _get_foreground_window_win() -> WindowInfo:
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    hwnd = u32.GetForegroundWindow()

    # window title
    title_buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(hwnd, title_buf, 256)
    title = title_buf.value or ""

    # PID
    pid = ctypes.c_uint32()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    # process name
    proc_name = ""
    try:
        handle = k32.OpenProcess(0x0400 | 0x0010, False, pid)
        if handle:
            exe_buf = ctypes.create_unicode_buffer(260)
            sz = ctypes.c_uint32(260)
            if k32.QueryFullProcessImageNameW(handle, 0, exe_buf, ctypes.byref(sz)):
                proc_name = exe_buf.value.rsplit("\\", 1)[-1]
            k32.CloseHandle(handle)
    except Exception:
        pass

    # window class
    cls_buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, cls_buf, 256)
    wnd_class = cls_buf.value or ""

    return WindowInfo(
        pid=pid.value, process_name=proc_name, title=title,
        window_class=wnd_class, bundle_id="",
    )
