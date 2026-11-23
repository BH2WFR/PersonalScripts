"""Native Windows UAC launch and process-handle lifetime."""

import ctypes
from ctypes import wintypes as w
import os
import subprocess
import sys


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("fMask", w.ULONG), ("hwnd", w.HWND),
        ("lpVerb", w.LPCWSTR), ("lpFile", w.LPCWSTR), ("lpParameters", w.LPCWSTR),
        ("lpDirectory", w.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", w.HINSTANCE),
        ("lpIDList", w.LPVOID), ("lpClass", w.LPCWSTR), ("hkeyClass", w.HKEY),
        ("dwHotKey", w.DWORD), ("hIcon", w.HANDLE), ("hProcess", w.HANDLE),
    ]


def has_console() -> bool:
    """Return whether the caller is attached to a Windows console, including a PTY."""
    pid = w.DWORD()
    return bool(ctypes.windll.kernel32.GetConsoleProcessList(ctypes.byref(pid), 1))


def is_gui_executable(path: str) -> bool:
    """Recognize a GUI interpreter or frozen GUI from its PE subsystem."""
    get_type = ctypes.windll.shell32.SHGetFileInfoW
    get_type.argtypes = [w.LPCWSTR, w.DWORD, w.LPVOID, w.UINT, w.UINT]
    get_type.restype = ctypes.c_size_t
    image = get_type(path, 0, None, 0, 0x2000)  # SHGFI_EXETYPE
    return (image & 0xFFFF) == 0x4550 and (image >> 16) != 0


def run_as_admin(command: list[str], *, hidden: bool) -> int:
    """Show the native fallback warning, request UAC and wait for the process.

    Raises OSError on cancellation or a Win32 failure. The caller stays alive
    while the helper attaches to its console.
    """
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = w.BOOL
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = os.getcwd()
    info.nShow = 0 if hidden else 1  # SW_HIDE for the bridge, SW_SHOWNORMAL for a GUI.
    warning = (
        "Windows will request administrator privileges using ShellExecuteExW "
        "(the extended version of ShellExecuteW).\n\n"
        "We recommend installing gsudo for future runs:\nscoop install gsudo"
    )
    message_box = ctypes.windll.user32.MessageBoxW
    message_box.argtypes = [w.HWND, w.LPCWSTR, w.LPCWSTR, w.UINT]
    if not message_box(None, warning, "Elevation fallback", 0x30):  # MB_OK | MB_ICONWARNING
        print(warning, file=sys.stderr, flush=True)
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:  # INFINITE / WAIT_OBJECT_0
            raise ctypes.WinError(ctypes.get_last_error())
        status = w.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return status.value
    finally:
        kernel.CloseHandle(info.hProcess)
