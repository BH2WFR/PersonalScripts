"""Send one physical US keystroke or UTF-16 character per Win32 input batch."""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from functools import cache
import os
from typing import TYPE_CHECKING

from utils import Keyboard
from utils.windows_input import InputPacket as _Input, WindowsInput, keyboard_packet as _packet
from .strokes import ascii_key

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


_KEYUP = 0x0002
_UNICODE = 0x0004
_SCANCODE = 0x0008
_VK_CAPITAL = 0x14


def show_panel(widget: QWidget) -> None:
    """Show the panel while keeping the typing recipient focused."""
    from utils.qt_widgets import show_nonactivating_tool

    show_nonactivating_tool(widget)


@cache
def _scan(name: str) -> int:
    code = Keyboard.windows_scan_code(name)
    if code is None:
        raise ValueError(f"Missing Windows scan code for {name!r}.")
    return code.code


def _packets(char: str, caps_lock: bool) -> list[_Input]:
    if not char.isascii():
        data = char.encode("utf-16-le")
        units = (C.c_uint16 * (len(data) // 2)).from_buffer_copy(data)
        return [_packet(unit, flags) for unit in units for flags in (_UNICODE, _UNICODE | _KEYUP)]
    name, shifted = ascii_key(char)
    if char.isalpha() and caps_lock:
        shifted = not shifted
    scan = _scan(name)
    pair = [_packet(scan, _SCANCODE), _packet(scan, _SCANCODE | _KEYUP)]
    if shifted:
        shift = _scan("left_shift")
        return [_packet(shift, _SCANCODE), *pair, _packet(shift, _SCANCODE | _KEYUP)]
    return pair


class WindowsSender(WindowsInput):
    """Type into the foreground HWND and restore it after explicit editing."""

    def __init__(self) -> None:
        super().__init__()
        api = self.api
        api.GetForegroundWindow.argtypes = []
        api.GetForegroundWindow.restype = W.HWND
        api.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        api.GetWindowThreadProcessId.restype = W.DWORD
        api.SetForegroundWindow.argtypes = [W.HWND]
        api.SetForegroundWindow.restype = W.BOOL
        api.GetKeyState.argtypes = api.GetAsyncKeyState.argtypes = [C.c_int]
        api.GetKeyState.restype = api.GetAsyncKeyState.restype = C.c_short

    def target(self) -> int:
        """Return the external foreground HWND, or zero during desktop transitions."""
        hwnd = self.api.GetForegroundWindow()
        pid = W.DWORD()
        if not hwnd or not self.api.GetWindowThreadProcessId(hwnd, C.byref(pid)) or pid.value == os.getpid():
            return 0
        return hwnd

    def restore(self, target: int) -> None:
        """Give the previously focused window the opportunity to regain focus."""
        if target:
            self.api.SetForegroundWindow(target)

    def check_ready(self) -> None:
        """Reject held modifiers that could turn typed characters into shortcuts."""
        if any(self.api.GetAsyncKeyState(vk) < 0 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            raise RuntimeError("Release Shift, Ctrl, Alt and the Windows key before typing.")

    def send(self, char: str) -> None:
        """Post a complete character; release outstanding keys after a partial batch."""
        self.send_packets(_packets(char, bool(self.api.GetKeyState(_VK_CAPITAL) & 1)))
