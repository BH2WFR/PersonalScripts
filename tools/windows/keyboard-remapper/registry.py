"""Read/write only HKLM Keyboard Layout\\Scancode Map with backup and conflict checks.

Standard-library Windows registry access is lazy. Importing this module never
reads or writes the registry. Tests can provide a completely in-memory backend.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Protocol

from .models import REGISTRY_PATH, VALUE_NAME, Snapshot, backup_text


class RegistryBackend(Protocol):
    """Narrow storage boundary for the single Scancode Map value."""

    def read(self) -> Snapshot:
        """Read and validate the saved value without mutation."""
        ...

    def write(self, snapshot: Snapshot) -> None:
        """Replace/delete only the saved value; caller owns authorization."""
        ...


class WindowsRegistry:
    """Native backend; writes require the calling process to be elevated."""

    def read(self) -> Snapshot:
        """Read HKLM; reject malformed or non-binary values rather than dropping data.

        Returns:
            Exact validated state, including absence.

        Raises:
            OSError: Windows access fails or this platform is unsupported.
            ValueError: The value type or binary structure is invalid.
        """
        if sys.platform != "win32":
            raise OSError("Registry keyboard remapping requires Windows 10 or later.")
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH, 0, winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return Snapshot(None)
        if kind != winreg.REG_BINARY or not isinstance(value, bytes):
            raise ValueError("Scancode Map is not REG_BINARY; no changes are allowed.")
        return Snapshot(value)

    def write(self, snapshot: Snapshot) -> None:
        """Set or delete Scancode Map, never its parent key or other values.

        Args:
            snapshot: Validated replacement; None data means remove this value.

        Raises:
            OSError: Access denied, unsupported platform or another native error.

        Side effects:
            Changes machine-wide mappings after a Windows restart.
        """
        if sys.platform != "win32":
            raise OSError("Registry keyboard remapping requires Windows.")
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if snapshot.data is None:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_BINARY, snapshot.data)


def save_backup(path: Path, snapshot: Snapshot) -> None:
    """Create a new durable JSON backup without overwriting any existing file.

    Args:
        path: User-selected new output file; its parent must exist.
        snapshot: Exact validated registry state.

    Raises:
        OSError: Creation, write or flush fails. A failed partial file may remain.
    """
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(backup_text(snapshot))
        stream.flush()
        os.fsync(stream.fileno())


def apply_snapshot(backend: RegistryBackend, expected: Snapshot, desired: Snapshot,
                   backup_path: Path) -> bool:
    """Backup and apply a previously confirmed change with optimistic conflict checks.

    Args:
        backend: Native or in-memory storage boundary.
        expected: State originally loaded by the editor.
        desired: State explicitly approved by the user.
        backup_path: New file for the original value; existing files are rejected.

    Returns:
        True after verified write; False for an unchanged value (no backup needed).

    Raises:
        RuntimeError: The registry changed externally, or readback differs.
        OSError: Backup or native operation failed; the backup remains recoverable.

    Side effects:
        Creates the backup before writing. Windows offers no atomic compare-and-
        swap here: a small race remains between the last check and write. Never
        auto-roll back on verification failure, which could clobber another writer.
    """
    if backend.read() != expected:
        raise RuntimeError("Registry changed outside this window. Reload before writing.")
    if desired == expected:
        return False
    save_backup(backup_path, expected)
    if backend.read() != expected:
        raise RuntimeError("Registry changed during backup. Nothing was written; reload first.")
    backend.write(desired)
    if backend.read() != desired:
        raise RuntimeError(f"Registry readback differs. Inspect it before retrying. Backup: {backup_path}")
    return True
