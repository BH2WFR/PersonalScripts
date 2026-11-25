"""Read a Windows console's live code pages in a short-lived detached process."""

import ctypes
import os
import subprocess
import sys
from typing import NamedTuple


class ConsoleInfo(NamedTuple):
    attached: bool | None
    input_page: str
    output_page: str


def probe(pid: int) -> int:
    """Attach only this worker to the target console and report its two code pages."""
    if not 0 < pid < 0xffffffff:
        return 1
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel.AttachConsole(ctypes.c_uint32(pid)):
        return ctypes.get_last_error() or 1
    try:
        input_page = kernel.GetConsoleCP()
        output_page = kernel.GetConsoleOutputCP()
    finally:
        kernel.FreeConsole()
    os.write(1, f"{input_page} {output_page}".encode("ascii"))
    return 0


def _page_label(page: int) -> str:
    if not page:
        return "Unavailable"
    return "65001 (UTF-8)" if page == 65001 else str(page)


def console_info(pid: int) -> ConsoleInfo:
    """Read console attachment and code pages without detaching the inspector's console."""
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        args = [sys.executable, "--_console-pages", str(pid)]
    else:
        args = [sys.executable, "-I", "-S", __file__, str(pid)]
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, creationflags=subprocess.DETACHED_PROCESS, timeout=2)
        if result.returncode == 6:  # ERROR_INVALID_HANDLE: target has no console
            return ConsoleInfo(False, "No console", "No console")
        if result.returncode == 0:
            input_page, output_page = map(int, result.stdout.split())
            return ConsoleInfo(True, _page_label(input_page), _page_label(output_page))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return ConsoleInfo(None, "Unavailable", "Unavailable")


if __name__ == "__main__":
    sys.exit(probe(int(sys.argv[1])))
