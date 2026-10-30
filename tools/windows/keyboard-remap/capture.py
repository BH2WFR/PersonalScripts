"""Visible, window-scoped single-key capture; never installs a global hook.

Requires PySide6. Native Windows messages supply physical scan words, not Qt's
logical key enum or translated text. Only use for legitimate testing, hotkeys
and authorized automation; no background recording or credential collection.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys

from PySide6 import QtCore, QtGui, QtWidgets
from utils import *

from .catalog import key_label

_KEY_DOWN = frozenset({0x0100, 0x0104})
_KEY_UP = frozenset({0x0101, 0x0105})
_VK_PAUSE = 0x13
_VK_NUMLOCK = 0x90
_IME_VKS = frozenset({0x15, 0x19})
_LANGUAGE_SCANS = frozenset({0x71, 0x72, 0xF1, 0xF2})
_EXTENDED = 1 << 24
_PREVIOUS_DOWN = 1 << 30
_SCAN_SHIFT = 16
_BYTE_MASK = 0xFF
_CAPTURE_TIMEOUT_MS = 20000


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", wintypes.UINT),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                ("lPrivate", wintypes.DWORD)]


@dataclass(frozen=True)
class CapturedKey:
    """One captured scan word and VK; contains no typed text or event history."""

    code: int
    vk: int


def decode_message(message: int, vk: int, lparam: int) -> CapturedKey | None:
    """Decode focused-window keyboard messages without invoking any native API.

    Args:
        message: WM_KEYDOWN/UP or WM_SYSKEYDOWN/UP; other messages are ignored.
        vk: Native virtual-key value.
        lparam: Native key-message flags, including scan byte and E0 bit.

    Returns:
        One physical word, or None for repeats, ordinary releases or zero scans.
        Korean release-only language keys are accepted without stripping bit 7.

    Raises:
        ValueError: Pause cannot be represented reliably from these message flags.
    """
    if message not in _KEY_DOWN | _KEY_UP:
        return None
    if vk == _VK_PAUSE:
        raise ValueError("Pause uses a special sequence and cannot be captured as a reliable registry word.")
    code = (lparam >> _SCAN_SHIFT) & _BYTE_MASK
    if message in _KEY_UP and not (vk in _IME_VKS and code in _LANGUAGE_SCANS):
        return None
    if message in _KEY_DOWN and lparam & _PREVIOUS_DOWN:
        return None
    if code == 0:
        return None
    prefix = ScanCodePrefix.E0 if lparam & _EXTENDED else ScanCodePrefix.NONE
    # Legacy window messages tag Num Lock as extended; its physical make word
    # is 0045, unlike the Pause sequence. Do not apply this to other keys.
    if vk == _VK_NUMLOCK and code == 0x45:
        prefix = ScanCodePrefix.NONE
    return CapturedKey(WindowsScanCode(code, prefix).value, vk)


class CaptureDialog(QtWidgets.QDialog):
    """Capture one key while this dialog is active, then require a mouse confirmation.

    Args:
        parent: Owning key-selection dialog.

    Capture ends on success, timeout or dialog closure. System shortcuts are not
    globally suppressed, and keys already remapped may report their destination.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.result_key: CapturedKey | None = None
        self.listening = False
        self.setWindowTitle("Capture a key")
        self.setMinimumWidth(590)
        layout = QtWidgets.QVBoxLayout(self)
        explanation = QtWidgets.QLabel(
            "Keep this window focused and press ONE key, including a modifier.\n"
            "Capture stops after one key or 20 seconds. Use the mouse to confirm/cancel.\n\n"
            "Already remapped keys may report their destination. Select the original\n"
            "key from the list instead. Disabled keys, Fn and system-reserved keys\n"
            "may not reach this window. System shortcuts are not blocked."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(80)
        layout.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        self.retry_button = QtWidgets.QPushButton("Listen again")
        self.use_button = QtWidgets.QPushButton("Use this key")
        cancel = QtWidgets.QPushButton("Cancel")
        for button in (self.retry_button, self.use_button, cancel):
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
            row.addWidget(button)
        layout.addLayout(row)
        self.retry_button.clicked.connect(self.begin)
        self.use_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.finished.connect(self._stop)
        self.begin()

    def begin(self) -> None:
        """Clear the previous candidate and start a bounded visible capture session."""
        self.result_key = None
        self.listening = True
        self.use_button.setEnabled(False)
        self.status.setText("Listening in this window... press a key.")
        self.timer.start(_CAPTURE_TIMEOUT_MS)
        self.setFocus()

    def _stop(self) -> None:
        self.listening = False
        self.timer.stop()

    def _timeout(self) -> None:
        self._stop()
        self.status.setText("Capture timed out. Click Listen again to retry, or select from the list.")

    def receive(self, message: int, vk: int, lparam: int) -> bool:
        """Handle one native message; return whether it belongs to this capture UI.

        Args:
            message: Windows message ID.
            vk: Native virtual key.
            lparam: Native message flags.

        Returns:
            True for keyboard messages while listening, even unsupported keys.
            This only consumes this window's message, never system-wide input.
        """
        if not self.listening or message not in _KEY_DOWN | _KEY_UP:
            return False
        try:
            key = decode_message(message, vk, lparam)
        except ValueError as exc:
            self.status.setText(str(exc))
            return True
        if key is not None:
            self._stop()
            self.result_key = key
            self.status.setText(f"Captured: {key_label(key.code)}\nVirtual key: 0x{key.vk:02X}\n"
                                "Release the key, then click Use this key.")
            self.use_button.setEnabled(True)
        return True

    def nativeEvent(self, eventType: QtCore.QByteArray | bytes | bytearray | memoryview,
                    message: int) -> tuple[bool, int]:
        """Consume only this active capture window's native keyboard messages."""
        if sys.platform == "win32" and self.listening and self.isActiveWindow():
            msg = _MSG.from_address(int(message))
            if self.receive(int(msg.message), int(msg.wParam), int(msg.lParam)):
                return True, 0
        return False, 0

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Prevent Enter/Escape from confirming or closing the capture by accident."""
        event.accept()

    def accept(self) -> None:
        """Accept only after a key has actually been captured."""
        if self.result_key is not None:
            super().accept()
