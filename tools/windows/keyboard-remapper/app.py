"""Application startup and draft-only elevation handoff for keyboard-remapper.

Requires PySide6 for the GUI. No registry writes occur during startup, handoff,
elevation or shutdown. The elevated editor still requires a separate confirmation.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from utils import *

from .models import Snapshot, backup_text, parse_backup

if TYPE_CHECKING:
    from .ui import RemapWindow

ADMIN_DRAFT_FLAG = "--admin-draft"
_MAX_PAYLOAD_CHARS = 28000
_CREATE_NO_WINDOW = 0x08000000
_BOOTSTRAPS: list[subprocess.Popen[bytes]] = []
_WINDOWS: list[RemapWindow] = []


def _release_window(window: RemapWindow) -> None:
    """Release the Python wrapper after Qt destroys a closed editor."""
    if window in _WINDOWS:
        _WINDOWS.remove(window)


def encode_handoff(expected: Snapshot, desired: Snapshot) -> str:
    """Encode two validated snapshots for an elevated editor, not an automatic write.

    Args:
        expected: Registry state originally read by the current window.
        desired: Uncommitted draft to display in the administrator window.

    Returns:
        ASCII base64 payload safe to pass as one process argument.

    Raises:
        ValueError: Payload is too large for a Windows command line.
    """
    text = json.dumps([backup_text(expected), backup_text(desired)])
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if len(payload) > _MAX_PAYLOAD_CHARS:
        raise ValueError("Draft is too large for elevation handoff. Start the editor as Administrator first.")
    return payload


def decode_handoff(payload: str) -> tuple[Snapshot, Snapshot]:
    """Validate an internal draft payload before requesting elevation.

    Args:
        payload: Base64 data produced by encode_handoff.

    Returns:
        Expected and desired snapshots, both schema/structure validated.

    Raises:
        ValueError: Size, encoding, shape or either backup document is invalid.
    """
    if len(payload) > _MAX_PAYLOAD_CHARS:
        raise ValueError("Elevation handoff exceeds the size limit.")
    obj: object = json.loads(base64.b64decode(payload, validate=True).decode("utf-8"))
    if not isinstance(obj, list) or len(obj) != 2 or not all(isinstance(item, str) for item in obj):
        raise ValueError("Invalid elevation draft payload.")
    return parse_backup(obj[0]), parse_backup(obj[1])


def open_elevated_editor(expected: Snapshot, desired: Snapshot) -> None:
    """Launch a bootstrap which uses System.restart_elevated before opening a GUI.

    Args:
        expected: Original saved state for later conflict checking.
        desired: Draft; it will never be applied automatically by the bootstrap.

    Raises:
        OSError: The subprocess cannot be launched.
        ValueError: Payload or command exceeds the Windows command-line limit.

    Side effects:
        Starts a hidden-console child and requests elevation. The parent retains
        its draft; no completion or successful write is inferred from child exit.
    """
    payload = encode_handoff(expected, desired)
    frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    entry = Path(__file__).resolve().parent.parent / "keyboard-remapper.py"
    command = [sys.executable, *([] if frozen else [str(entry)]), ADMIN_DRAFT_FLAG, payload]
    if len(subprocess.list2cmdline(command)) >= 30000:
        raise ValueError("Elevation command is too long. Start the editor as Administrator first.")
    _BOOTSTRAPS[:] = [process for process in _BOOTSTRAPS if process.poll() is None]
    _BOOTSTRAPS.append(subprocess.Popen(command, creationflags=_CREATE_NO_WINDOW))


def run(handoff: tuple[Snapshot, Snapshot] | None = None, *, read_only: bool = False) -> int:
    """Open the Fusion GUI; callers must enforce the Windows platform guard.

    Args:
        handoff: Optional draft from a standard-user editor, never auto-applied.
        read_only: Disable registry writes and elevation in this window.

    Returns:
        Qt exit status, or zero when embedded in an existing QApplication.

    Raises:
        RuntimeError: A non-GUI Qt application already exists.
        ImportError: PySide6 is unavailable.

    Side effects:
        Reads the saved map and opens a window. User actions alone write/export.
    """
    from PySide6 import QtCore, QtWidgets
    from utils.qt_widgets import install_no_wheel_controls
    from .registry import WindowsRegistry
    from .ui import RemapWindow

    existing = QtWidgets.QApplication.instance()
    owns_application = existing is None
    application = existing if existing is not None else QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A non-GUI Qt application already exists.")
    application.setStyle("Fusion")
    install_no_wheel_controls(application)
    window = RemapWindow(WindowsRegistry(), open_elevated_editor, handoff, read_only=read_only)
    # A Qt dynamic property stores a QObject pointer, not a strong Python
    # subclass reference. Retain the wrapper when embedded run() returns early.
    _WINDOWS.append(window)
    window.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda: _release_window(window))
    application.setProperty("keyboardRemapWindow", window)
    window.show()
    return application.exec() if owns_application else 0
