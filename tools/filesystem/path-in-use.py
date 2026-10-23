#!/usr/bin/env python3
"""Find processes using a file or directory on Windows, Linux, and macOS.

Directories include themselves and all reported descendant paths. Drive roots
and mount points are ordinary directories; there is no volume/device query.
On Windows, a bare drive letter such as D: means its root, D:/.
Scan open references once, rather than walking every file on a disk. Output
includes PID, process executable path, referenced path, and reference type.
Optional PID and case-insensitive process-name filters are combined with AND.

Windows uses ctypes to enumerate the system handle table, resolves NT object
names, and also checks mapped files/modules. Algorithm reference:
https://github.com/microsoft/PowerToys/tree/main/src/modules/FileLocksmith/FileLocksmithLibInterop
No PowerToys/Sysinternals installation is needed. The NT system-information
interfaces are internal Windows APIs and can change with Windows releases.
Linux/macOS use lsof's NUL-delimited output (including cwd, executable and
mapped files).
psutil supplies executable paths and supplements Windows with executable/cwd
references. Windows compares target and handle names in the same NT namespace
so junctions, symlinks, and drive aliases do not cause DOS-path mismatches.
Matching is by reported path, not file identity: alternate hard links, mount aliases and
links inside the directory are not exhaustively followed. The input path's
symlinks are resolved. Deleted paths reported by lsof remain searchable under
an existing parent directory. A reference does not prove a delete/unmount lock.

Actual scans require administrator/root privileges. All platforms use the
project's elevation helper; Linux/macOS restart through sudo in the current
terminal, preserving the Python interpreter and arguments. sudo may prompt
for a password. Already elevated processes continue without restarting.
Help never elevates. Protected processes and concurrent changes can hide data;
an empty result means no references were found, not proof a path is unused.
Exit 0: query completed; 1: failed/incomplete query or unavailable metadata;
2: invalid arguments. No inspected processes are terminated or their handles
closed. Only our temporary duplicate/process handles are released.
Windows queries run in a private worker, which is stopped on timeout while
preserving completed records. A stuck handle/map query is skipped by restarting
only our worker; diagnostics are summarized. The worker's internal CLI is not
a public API. --verbose expands incomplete-query diagnostics.

Requirements:
    Python 3.13+, project utils, psutil (pip install psutil).
    Windows 10+: built-in Kernel32/Ntdll APIs via standard-library ctypes.
    Linux/macOS: lsof on PATH (Linux: install with your package manager;
        macOS: /usr/sbin/lsof); sudo for elevation when not already root.
    Administrator/root privileges for scans; elevation is requested automatically.

Usage:
    python path-in-use.py
    python path-in-use.py "D:/Data" --process editor
    python path-in-use.py /mnt/data --pid 1234 --timeout 120
    /path/to/conda/bin/python path-in-use.py /path/to/file
"""

import argparse
from collections.abc import Callable
import ctypes
from dataclasses import dataclass, field
import json
import math
import ntpath
import os
from pathlib import Path
import posixpath
import queue
import re
import subprocess
import sys
import threading
import time
from typing import cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


DEFAULT_TIMEOUT = 60.0
SUPPORTED_PLATFORMS: tuple[str, ...] = ("win32", "linux", "darwin")
SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
OBJECT_NAME_INFORMATION = 1
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_BUFFER_TOO_SMALL = 0xC0000023
STATUS_BUFFER_OVERFLOW = 0x80000005
INITIAL_QUERY_BYTES = 65536
MAX_QUERY_BYTES = 256 * 1024 * 1024
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_SAME_ACCESS = 0x00000002
FILE_TYPE_DISK = 1
OPEN_EXISTING = 3
FILE_SHARE_ALL = 7
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
ERROR_INVALID_HANDLE = 6
ERROR_NOT_ALL_ASSIGNED = 1300
TOKEN_ADJUST_PRIVILEGES = 0x20
TOKEN_QUERY = 0x08
SE_PRIVILEGE_ENABLED = 0x02
HANDLE_STALL_SECONDS = 2.0
DELETED_SUFFIX = " (deleted)"
LSOF_ESCAPES = re.compile(rb"\\x([0-9a-fA-F]{2})|\\([bfrnt])|\^([@A-Z\[\]\\^_?])")
CONTROL_ESCAPES: dict[int, str] = {ord(char): f"\\x{ord(char):02x}" for char in map(chr, range(32))}
CONTROL_ESCAPES[127] = "\\x7f"


@dataclass(frozen=True)
class Reference:
    """One native process reference.

    Attributes:
        pid: Nonnegative operating-system process identifier.
        name: Process name reported by the backend.
        path: Referenced path; may include lsof's deleted-file suffix.
        kind: Native descriptor/handle or supplemental reference description.
    """

    pid: int
    name: str
    path: str
    kind: str


@dataclass
class Scan:
    """Collected references and diagnostics from a single non-atomic scan.

    Attributes:
        references: Native references, before filtering and deduplication.
        warnings: Reasons the scan or executable metadata is incomplete.
    """

    references: list[Reference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _positive_pid(value: str) -> int:
    """Parse a positive process identifier for argparse."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("PID must be positive")
    return number


def _timeout(value: str) -> float:
    """Reject nonpositive, NaN, and infinite subprocess timeouts."""
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("Timeout must be a finite positive number")
    return seconds


def _parser() -> argparse.ArgumentParser:
    """Build help without requiring psutil, querying processes, or elevating."""
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}{'PATH IN USE':^60}{CRst}\n\n"
        "Description:\n  Find processes referencing a file or directory (recursively).\n"
        "  Print PID, process name, full executable path, and referenced paths.\n"
        "  Drive roots and mount points are treated as directories (D: means D:/).",
        epilog=f"{FGray}Requirements:\n"
        "  psutil (pip install psutil); Windows 10+: built-in APIs, no external tool.\n"
        "  Linux/macOS: lsof on PATH; sudo for elevation when not already root.\n"
        "  Scans automatically request administrator/root privileges.\n"
        "  Linux/macOS restart in the current terminal; sudo may prompt for a password.\n\n"
        "Examples:\n  python path-in-use.py D:/Data --process editor\n"
        "  /path/to/conda/bin/python path-in-use.py /mnt/data --pid 1234\n\n"
        "Notes:\n  No disk/volume-specific scanning. Uses reported paths, not file identity.\n"
        "  Windows checks file handles and mapped files/modules using NT names.\n"
        "  Alternate hard links and restricted processes may still be missed.\n"
        "  A reference does not prove a lock; no matches do not prove availability.\n"
        "  Exit: 0 completed, 1 failed/incomplete, 2 invalid arguments.\n"
        "  Queries are read-only. Target processes/handles are never terminated/closed.\n"
        f"  Windows skips stalled queries after {HANDLE_STALL_SECONDS:g}s; --timeout caps the scan.{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", help="File or directory; prompt if omitted")
    parser.add_argument("--pid", type=_positive_pid, help="Only include this PID")
    parser.add_argument("--process", help="Case-insensitive substring of the process name")
    parser.add_argument("--timeout", type=_timeout, default=DEFAULT_TIMEOUT,
                        help=f"Native query timeout in seconds (default: {DEFAULT_TIMEOUT:g})")
    parser.add_argument("--verbose", action="store_true", help="Show all incomplete-query diagnostics")
    parser.add_argument("--_windows-worker", type=_positive_pid, help=argparse.SUPPRESS)
    parser.add_argument("--_skip", action="append", default=[], help=argparse.SUPPRESS)
    return parser


def _require_elevation() -> bool:
    """Request elevation through the shared helper on every supported platform."""
    if not System.is_elevated():
        System.restart_elevated()
    if not System.is_elevated():
        print(f"{FLRed}Elevation failed; no scan was started.{CRst}")
        return False
    return True


def _run_windows_query(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    """Restart only our worker after a stalled query, skipping its PID/handle pair."""
    if sys.platform != "win32":
        raise OSError("The Windows query worker is unavailable on this platform")
    deadline = time.monotonic() + timeout
    output: list[bytes] = []
    skipped: set[tuple[int, int]] = set()
    while time.monotonic() < deadline:
        arguments = [*command]
        for pid, handle in sorted(skipped):
            arguments.extend(["--_skip", f"{pid}:{handle}"])
        events: queue.Queue[bytes | None] = queue.Queue()
        with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW) as worker:
            assert worker.stdout is not None

            def read_lines() -> None:
                """Drain this worker's pipe without blocking the watchdog."""
                assert worker.stdout is not None
                try:
                    for line in worker.stdout:
                        events.put(line)
                finally:
                    events.put(None)

            reader = threading.Thread(target=read_lines, daemon=True)
            reader.start()
            current: tuple[int, int] | None = None
            last_progress = time.monotonic()
            restart = False
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        line = events.get(timeout=min(HANDLE_STALL_SECONDS, remaining))
                    except queue.Empty:
                        if current is not None and time.monotonic() - last_progress >= HANDLE_STALL_SECONDS:
                            skipped.add(current)
                            pid, handle = current
                            detail = "mapped files/modules" if handle == -1 else f"handle {handle:X}"
                            warning = f"PID {pid}: skipped stalled {detail} query after {HANDLE_STALL_SECONDS:g}s."
                            output.append(f"{json.dumps({'warning': warning})}\n".encode())
                            restart = True
                            break
                        continue
                    if line is None:
                        code = worker.wait(timeout=max(0.1, deadline - time.monotonic()))
                        return subprocess.CompletedProcess(command, code, b"".join(output), b"")
                    try:
                        record = json.loads(line)
                        progress = record.get("checking") if isinstance(record, dict) else None
                        if isinstance(progress, list) and len(progress) == 2 and all(type(v) is int for v in progress):
                            current = (progress[0], progress[1])
                            last_progress = time.monotonic()
                            continue
                    except (ValueError, UnicodeError):
                        pass  # Preserve diagnostics; the parser will mark invalid records.
                    output.append(line)
            finally:
                if worker.poll() is None:
                    worker.kill()
                worker.wait()
                reader.join(timeout=1)
            if not restart:
                break
    message = f"Windows scan timed out after {timeout:g}s; completed matches were retained."
    return subprocess.CompletedProcess(command, 1, b"".join(output), message.encode())


def _run_query(command: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    """Run a bounded native query without a shell; hide the Windows worker window."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        if sys.platform == "win32":
            return _run_windows_query(command, timeout)
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout, env=environment, check=False)
    except subprocess.TimeoutExpired as exc:
        if sys.platform == "win32":
            message = f"Windows worker timed out after {timeout:g}s; completed records were retained."
            return subprocess.CompletedProcess(command, 1, exc.stdout or b"", message.encode("utf-8"))
        raise RuntimeError(
            f"Query timed out after {timeout:g}s; no complete result is available. "
            "Increase --timeout if needed."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot start {command[0]}: {exc}") from exc


class _SystemHandleEntry(ctypes.Structure):
    """Pointer-sized SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX (PowerToys/NtdllBase.h)."""

    _fields_ = [
        ("object", ctypes.c_void_p), ("pid", ctypes.c_size_t),
        ("handle", ctypes.c_size_t), ("access", ctypes.c_uint32),
        ("backtrace", ctypes.c_uint16), ("type_index", ctypes.c_uint16),
        ("attributes", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
    ]


class _UnicodeString(ctypes.Structure):
    """NT counted UTF-16 string; lengths are bytes, not Python characters."""

    _fields_ = [("length", ctypes.c_uint16), ("maximum", ctypes.c_uint16),
                ("buffer", ctypes.c_void_p)]


class _TokenPrivileges(ctypes.Structure):
    """One TOKEN_PRIVILEGES entry containing the SeDebugPrivilege LUID."""

    _fields_ = [("count", ctypes.c_uint32), ("low", ctypes.c_uint32),
                ("high", ctypes.c_int32), ("attributes", ctypes.c_uint32)]


class _WindowsHandleApi:
    """Enumerate file handles once and compare NT names, following File Locksmith.

    Only the querying process receives duplicate handles or token adjustments.
    No target handles are closed and no target threads are terminated.
    """

    # Keep Windows-only bindings and methods out of POSIX static analysis.
    if sys.platform == "win32":
        def __init__(self) -> None:
            """Bind Win32/NT signatures; raise OSError outside Windows."""
            if sys.platform != "win32":
                raise OSError("Windows handle APIs are unavailable on this platform")
            self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.ntdll = ctypes.WinDLL("ntdll")
            self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            handle, dword = ctypes.c_void_p, ctypes.c_uint32
            self.kernel.OpenProcess.argtypes = [dword, ctypes.c_int, dword]
            self.kernel.OpenProcess.restype = handle
            self.kernel.GetCurrentProcess.argtypes = []
            self.kernel.GetCurrentProcess.restype = handle
            self.kernel.CloseHandle.argtypes = [handle]
            self.kernel.CloseHandle.restype = ctypes.c_int
            self.kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, dword, dword, handle, dword, dword, handle]
            self.kernel.CreateFileW.restype = handle
            self.kernel.DuplicateHandle.argtypes = [handle, handle, handle, ctypes.POINTER(handle),
                                                   dword, ctypes.c_int, dword]
            self.kernel.DuplicateHandle.restype = ctypes.c_int
            self.kernel.GetFileType.argtypes = [handle]
            self.kernel.GetFileType.restype = dword
            self.ntdll.NtQuerySystemInformation.argtypes = [dword, handle, dword, ctypes.POINTER(dword)]
            self.ntdll.NtQuerySystemInformation.restype = ctypes.c_int32
            self.ntdll.NtQueryObject.argtypes = [handle, dword, handle, dword, ctypes.POINTER(dword)]
            self.ntdll.NtQueryObject.restype = ctypes.c_int32
            self.advapi.OpenProcessToken.argtypes = [handle, dword, ctypes.POINTER(handle)]
            self.advapi.OpenProcessToken.restype = ctypes.c_int
            self.advapi.LookupPrivilegeValueW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, handle]
            self.advapi.LookupPrivilegeValueW.restype = ctypes.c_int
            self.advapi.AdjustTokenPrivileges.argtypes = [handle, ctypes.c_int, handle, dword, handle, handle]
            self.advapi.AdjustTokenPrivileges.restype = ctypes.c_int
            self.current: int = self.kernel.GetCurrentProcess()

        def enable_debug_privilege(self) -> bool:
            """Enable SeDebugPrivilege on our token, if assigned; always close the token.

            Returns:
                True if enabled, False if not assigned or otherwise unavailable.
            Side effects:
                Adjusts only this worker's token for the duration of its lifetime.
            """
            token = ctypes.c_void_p()
            if not self.advapi.OpenProcessToken(self.current, TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                               ctypes.byref(token)):
                return False
            try:
                privilege = _TokenPrivileges(count=1, attributes=SE_PRIVILEGE_ENABLED)
                luid = ctypes.byref(privilege, _TokenPrivileges.low.offset)
                if not self.advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", luid):
                    return False
                ctypes.set_last_error(0)
                success = self.advapi.AdjustTokenPrivileges(token, False, ctypes.byref(privilege), 0, None, None)
                return bool(success) and ctypes.get_last_error() != ERROR_NOT_ALL_ASSIGNED
            finally:
                self.kernel.CloseHandle(token)

        def _open_path(self, path: str) -> int:
            """Open metadata only, sharing read/write/delete and supporting directories."""
            handle: int | None = self.kernel.CreateFileW(path, 0, FILE_SHARE_ALL, None, OPEN_EXISTING,
                                                         FILE_FLAG_BACKUP_SEMANTICS, None)
            if handle is None or handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            return handle

        def _kernel_name(self, handle: int | ctypes.c_void_p) -> str:
            """Query an NT name with a growable buffer and decode counted UTF-16 bytes."""
            size = INITIAL_QUERY_BYTES
            while size <= MAX_QUERY_BYTES:
                buffer = ctypes.create_string_buffer(size)
                required = ctypes.c_uint32()
                status = self.ntdll.NtQueryObject(handle, OBJECT_NAME_INFORMATION, buffer, size,
                                                 ctypes.byref(required)) & 0xFFFFFFFF
                if status in (STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_TOO_SMALL, STATUS_BUFFER_OVERFLOW):
                    size = max(size * 2, required.value)
                    continue
                if status:
                    raise OSError(f"NtQueryObject failed: NTSTATUS 0x{status:08X}")
                name = _UnicodeString.from_buffer(buffer)
                if not name.buffer or not name.length:
                    return ""
                start = ctypes.addressof(buffer)
                if name.length % 2 or not (start <= name.buffer <= start + size - name.length):
                    raise OSError("NtQueryObject returned an invalid Unicode string")
                return ctypes.string_at(name.buffer, name.length).decode("utf-16-le", errors="surrogatepass")
            raise OSError("NT object name exceeded the query buffer limit")

        def path_to_kernel_name(self, path: str) -> str:
            """Resolve a file/directory to an NT name and immediately close our handle.

            Args:
                path: Existing absolute Windows file/directory path.
            Returns:
                Kernel object name, including its device prefix.
            Raises:
                OSError: Opening or querying the path fails.
            """
            handle = self._open_path(path)
            try:
                return self._kernel_name(handle)
            finally:
                self.kernel.CloseHandle(handle)

        def handles(self) -> list[_SystemHandleEntry]:
            """Snapshot all file-type handles using one system table, without PSS.

            Returns:
                Owned copies of file-handle records; non-file object types are excluded.
            Raises:
                OSError: The NT query fails or its returned layout is invalid.
            Side effects:
                Temporarily opens the Python/application executable to identify the
                kernel's file type index.
            """
            probe = self._open_path(sys.executable)
            try:
                size = INITIAL_QUERY_BYTES
                while size <= MAX_QUERY_BYTES:
                    buffer = ctypes.create_string_buffer(size)
                    required = ctypes.c_uint32()
                    status = self.ntdll.NtQuerySystemInformation(SYSTEM_EXTENDED_HANDLE_INFORMATION,
                        buffer, size, ctypes.byref(required)) & 0xFFFFFFFF
                    if status == STATUS_INFO_LENGTH_MISMATCH:
                        size = max(size * 2, required.value)
                        continue
                    if status:
                        raise OSError(f"System handle enumeration failed: NTSTATUS 0x{status:08X}")
                    header_size = ctypes.sizeof(ctypes.c_size_t) * 2
                    count = ctypes.c_size_t.from_buffer(buffer).value
                    entry_size = ctypes.sizeof(_SystemHandleEntry)
                    if header_size + count * entry_size > size:
                        raise OSError("Invalid NT system handle table length")
                    entries = (_SystemHandleEntry * count).from_buffer(buffer, header_size)
                    file_type = next((entry.type_index for entry in entries
                                      if entry.pid == os.getpid() and entry.handle == probe), None)
                    if file_type is None:
                        raise OSError("Could not identify the file object type in the system handle table")
                    return [_SystemHandleEntry.from_buffer_copy(entry) for entry in entries
                            if entry.type_index == file_type]
                raise OSError("System handle table exceeded the query buffer limit")
            finally:
                self.kernel.CloseHandle(probe)

        def _file_path(self, process: int, source: int) -> str | None:
            """Query a known file-type handle's NT name, closing only our local copy."""
            duplicate = ctypes.c_void_p()
            if not self.kernel.DuplicateHandle(process, source, self.current, ctypes.byref(duplicate),
                                               0, False, DUPLICATE_SAME_ACCESS):
                if ctypes.get_last_error() == ERROR_INVALID_HANDLE:
                    return None  # A normal close/reuse race after taking the table snapshot.
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if self.kernel.GetFileType(duplicate) != FILE_TYPE_DISK:
                    return None
                return self._kernel_name(duplicate)
            finally:
                self.kernel.CloseHandle(duplicate)

        def scan_process(self, pid: int, emit: Callable[[Reference], None],
                         entries: list[_SystemHandleEntry] | None = None,
                         checking: Callable[[int, int], None] | None = None) -> int:
            """Emit NT names for one PID using only PROCESS_DUP_HANDLE access.

            Args:
                pid: Positive process identifier.
                emit: Receives resolved file/directory NT references.
                entries: Pre-filtered system-table entries, or None to take a snapshot.
                checking: Optional progress callback before each potentially blocking query.
            Returns:
                Number of unsuccessful handle queries.
            Raises:
                OSError: Opening the process or enumerating handles fails.
            Side effects:
                Creates and closes local process/duplicate handles; invokes callbacks.
            """
            if entries is None:
                entries = [entry for entry in self.handles() if entry.pid == pid]
            process: int | None = self.kernel.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            failed = 0
            try:
                for entry in entries:
                    if checking:
                        checking(pid, entry.handle)
                    try:
                        path = self._file_path(process, entry.handle)
                    except OSError:
                        failed += 1
                        continue
                    if path:
                        emit(Reference(pid, "<unavailable>", path, f"handle {entry.handle:X}"))
                return failed
            finally:
                self.kernel.CloseHandle(process)
    else:
        def __init__(self) -> None:
            """Reject accidental native-backend use on Linux/macOS."""
            raise OSError("Windows handle APIs are unavailable on this platform")


def _windows_match_path(path: str, kernel_target: str, target: str, directory: bool) -> str | None:
    """Compare NT names with path boundaries and translate only matched paths for display."""
    if not _path_matches(path, kernel_target, directory, True):
        return None
    base = kernel_target.rstrip("\\")
    suffix = path[len(base):]
    return f"{target.rstrip(chr(92)).rstrip('/')}{suffix}"


def _windows_worker(parent_pid: int, pid_filter: int | None, target: str | None,
                    skipped: set[tuple[int, int]] | None = None) -> int:
    """Query NT handles and mappings, streaming progress and matching records."""
    if sys.platform != "win32" or not System.is_elevated():
        print(json.dumps({"warning": "The Windows worker requires administrator privileges."}), flush=True)
        return 1
    try:
        import psutil

        if not target:
            raise ValueError("The Windows worker requires a target path")
        api = _WindowsHandleApi()
        if not api.enable_debug_privilege():
            print(json.dumps({"warning": "SeDebugPrivilege is unavailable; protected processes may be skipped."}), flush=True)
        kernel_target = api.path_to_kernel_name(target)
        directory = os.path.isdir(target)
        skipped = skipped or set()
        excluded = {0, os.getpid(), parent_pid}
        groups: dict[int, list[_SystemHandleEntry]] = {}
        for entry in api.handles():
            if entry.pid in excluded or (pid_filter is not None and entry.pid != pid_filter):
                continue
            if (entry.pid, entry.handle) not in skipped:
                groups.setdefault(entry.pid, []).append(entry)

        def checking(pid: int, handle: int) -> None:
            """Publish the in-flight query before entering a potentially blocking API."""
            print(json.dumps({"checking": [pid, handle]}), flush=True)

        def emit(reference: Reference) -> None:
            """Filter in kernel namespace and stream only matching paths."""
            path = _windows_match_path(reference.path, kernel_target, target, directory)
            if path is not None:
                print(json.dumps({"pid": reference.pid, "path": path, "kind": reference.kind}), flush=True)

        inaccessible: list[int] = []
        failed_handles = 0
        for pid, entries in groups.items():
            try:
                failed_handles += api.scan_process(pid, emit, entries, checking)
            except OSError:
                if psutil.pid_exists(pid):
                    inaccessible.append(pid)
        if inaccessible:
            print(json.dumps({"warning": f"Handle access denied/unavailable for {len(inaccessible)} processes; "
                                         f"PIDs: {', '.join(map(str, inaccessible))}."}), flush=True)
        if failed_handles:
            print(json.dumps({"warning": f"{failed_handles} file handles could not be queried (access/race/driver)."}), flush=True)

        # Include mapped data and images even after their ordinary file handles close.
        unresolved: list[int] = []
        names: dict[str, str] = {}
        pids = [pid_filter] if pid_filter is not None else psutil.pids()
        for pid in pids:
            if pid in excluded or (pid, -1) in skipped:
                continue
            checking(pid, -1)
            try:
                for mapping in psutil.Process(pid).memory_maps():
                    path = mapping.path
                    if not directory and ntpath.basename(path).casefold() != ntpath.basename(target).casefold():
                        continue
                    if path not in names:
                        try:
                            names[path] = api.path_to_kernel_name(path)
                        except OSError:
                            names[path] = ""
                    if names[path]:
                        emit(Reference(pid, "<unavailable>", names[path], "mapped file/module"))
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError):
                unresolved.append(pid)
        if unresolved:
            print(json.dumps({"warning": f"Mapped-file access unavailable for {len(unresolved)} processes; "
                                         f"PIDs: {', '.join(map(str, unresolved))}."}), flush=True)
        print(json.dumps({"complete": True}), flush=True)
        return 0
    except (OSError, AttributeError, ImportError, ValueError) as exc:
        print(json.dumps({"warning": f"Windows query failed: {exc}"}), flush=True)
        return 1


def _parse_windows_worker(raw: bytes) -> Scan:
    """Decode complete worker records; flag crashes, truncation, and partial scans."""
    scan = Scan()
    complete = False
    for line in raw.splitlines():
        try:
            value: object = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            record = cast(dict[str, object], value)
            if "checking" in record:
                continue
            if record.get("complete") is True:
                complete = True
            elif isinstance(record.get("warning"), str):
                scan.warnings.append(str(record["warning"]))
            else:
                pid, path, kind = record.get("pid"), record.get("path"), record.get("kind")
                if type(pid) is not int or not isinstance(path, str) or not isinstance(kind, str):
                    raise ValueError("Invalid reference record")
                scan.references.append(Reference(pid, "<unavailable>", path, kind))
        except (ValueError, UnicodeError):
            scan.warnings.append("An incomplete or invalid Windows worker record was discarded.")
    if not complete:
        scan.warnings.append("Windows handle scan did not complete; results are partial.")
    return scan


def _decode_lsof(value: bytes) -> str:
    """Decode lsof's printable escapes under LC_ALL=C, including UTF-8 bytes."""
    controls: dict[bytes, bytes] = {b"b": b"\b", b"f": b"\f", b"r": b"\r", b"n": b"\n", b"t": b"\t"}

    def replace(match: re.Match[bytes]) -> bytes:
        """Translate one lsof hexadecimal, C-style, or caret escape."""
        if match[1] is not None:
            return bytes([int(match[1], 16)])
        if match[2] is not None:
            return controls[match[2]]
        return bytes([127 if match[3] == b"?" else match[3][0] & 31])

    return os.fsdecode(LSOF_ESCAPES.sub(replace, value))


def _parse_lsof(raw: bytes) -> Scan:
    """Parse NUL fields and record boundaries, retaining cwd/text/deleted paths."""
    scan = Scan()
    pid: int | None = None
    name = ""
    descriptor = ""
    for token in raw.split(b"\0"):
        token = token.lstrip(b"\n")  # lsof adds NL after each process/file set.
        if not token:
            continue
        code, value = token[:1], token[1:]
        if code == b"p":
            if not value.isdigit():
                raise RuntimeError("Invalid PID in lsof output")
            pid, name, descriptor = int(value), "", ""
        elif code == b"c":
            name = _decode_lsof(value)
        elif code == b"f":
            descriptor = value.decode("ascii", errors="replace")
        elif code == b"n":
            path = _decode_lsof(value)
            if pid is None or not descriptor:
                raise RuntimeError("lsof returned a path without a process/file descriptor")
            if "(readlink:" in path or "(stat:" in path:
                scan.warnings.append(f"PID {pid}: {path}")
            elif path.startswith("/"):
                scan.references.append(Reference(pid, name, path, descriptor))
            elif "denied" in path.casefold() or "error" in path.casefold():
                scan.warnings.append(f"PID {pid}: {path}")
        elif code not in (b"t",):
            scan.warnings.append(f"Unexpected lsof field: {os.fsdecode(token)}")
    if raw.strip() and pid is None:
        raise RuntimeError("lsof returned no process records")
    return scan


def _backend_command(pid_filter: int | None = None) -> list[str]:
    """Resolve the required native tool before prompting for a path."""
    if sys.platform == "win32":
        command = [sys.executable]
        if not getattr(sys, "frozen", False) and "__compiled__" not in globals():
            command.append(os.path.abspath(__file__))
        command.extend(["--_windows-worker", str(os.getpid())])
        if pid_filter is not None:
            command.extend(["--pid", str(pid_filter)])
        return command
    executable = Environment.which("lsof")
    if executable is None:
        raise RuntimeError("lsof is required on PATH. Install it with your system package manager.")
    return [executable, "-n", "-P", "-F0pcftn"]


def _native_scan(command: list[str], timeout: float) -> Scan:
    """Collect native references, preserving diagnostics and partial output."""
    result = _run_query(command, timeout)
    if sys.platform == "win32":
        scan = _parse_windows_worker(result.stdout)
        if result.returncode:
            scan.warnings.append(f"Windows worker exited with status {result.returncode}.")
    else:
        if result.returncode not in (0, 1):
            raise RuntimeError(f"lsof failed ({result.returncode}): {os.fsdecode(result.stderr).strip()}")
        scan = _parse_lsof(result.stdout)
        if result.returncode:
            scan.warnings.append("lsof exited with status 1; the process inventory may be incomplete.")
        if not result.stdout.strip():
            scan.warnings.append("lsof returned no process inventory; completeness could not be verified.")
    if result.stderr.strip():
        scan.warnings.append(os.fsdecode(result.stderr).strip())
    return scan


def _path_matches(path: str, target: str, directory: bool, windows: bool) -> bool:
    """Match path components, drive roots, file streams, and deleted references."""
    path_module = ntpath if windows else posixpath
    if windows and path.startswith("\\\\?\\UNC\\"):
        path = f"\\\\{path[8:]}"
    elif windows and path.startswith("\\\\?\\"):
        path = path[4:]
    candidate = path_module.normcase(path_module.normpath(path))
    base = path_module.normcase(path_module.normpath(target))
    if candidate == base:
        return True
    if windows and not directory and candidate.startswith(f"{base}:"):
        return True  # Alternate data streams reference the same Windows file.
    if not windows and candidate.endswith(DELETED_SUFFIX):
        if candidate.removesuffix(DELETED_SUFFIX) == base:
            return True
    prefix = base if base.endswith(path_module.sep) else f"{base}{path_module.sep}"
    return directory and candidate.startswith(prefix)


def _windows_process_references(scan: Scan, pid_filter: int | None) -> None:
    """Supplement handle queries with executable/cwd paths; report denied reads."""
    import psutil as ps

    denied = 0
    for process in ps.process_iter():
        if pid_filter is not None and process.pid != pid_filter:
            continue
        if process.pid == os.getpid() or process.pid == 0:
            continue
        try:
            name = process.name()
        except ps.NoSuchProcess:
            continue
        except ps.AccessDenied:
            name = "<unavailable>"
        for kind, getter in (("executable", process.exe), ("cwd", process.cwd)):
            try:
                path = getter()
            except ps.NoSuchProcess:
                break
            except (ps.AccessDenied, OSError):
                denied += 1
                continue
            if path:
                scan.references.append(Reference(process.pid, name, path, kind))
    if denied:
        scan.warnings.append(f"Could not read {denied} executable/cwd fields from protected processes.")


def _print_results(scan: Scan, target: str, directory: bool, pid_filter: int | None,
                   name_filter: str | None, verbose: bool = False) -> int:
    """Filter, group, enrich, and print references without truncating paths."""
    import psutil as ps

    # ── path and process selection ──────────────────────────
    groups: dict[int, list[Reference]] = {}
    for reference in scan.references:
        if reference.pid == os.getpid():
            continue
        if pid_filter is not None and reference.pid != pid_filter:
            continue
        if _path_matches(reference.path, target, directory, sys.platform == "win32"):
            groups.setdefault(reference.pid, []).append(reference)

    # ── executable metadata and grouped output ──────────────
    matched = 0
    for pid, references in sorted(groups.items()):
        name = references[0].name
        executable = "<unavailable>"
        try:
            process = ps.Process(pid)
            name = process.name() or name
            executable = process.exe() or "<unavailable>"
        except (ps.NoSuchProcess, ps.AccessDenied, OSError) as exc:
            scan.warnings.append(f"PID {pid}: executable metadata unavailable ({exc})")
        if name_filter and name_filter.casefold() not in name.casefold():
            continue
        if executable == "<unavailable>":
            scan.warnings.append(f"PID {pid}: full executable path is unavailable.")
        matched += 1
        print(f"\n{FLYellow}PROCESS {matched}{CRst}:")
        print(f"  {FLGreen}PID:{CRst} {FLYellow}{pid}{CRst}    {FLGreen}Process:{CRst} {FLYellow}{name.translate(CONTROL_ESCAPES)}{CRst}")
        print(f"  {FLGreen}Executable:{CRst} {FGray}{executable.translate(CONTROL_ESCAPES)}{CRst}")
        paths: dict[str, set[str]] = {}
        for reference in references:
            paths.setdefault(reference.path, set()).add(reference.kind)
        for path, kinds in sorted(paths.items()):
            print(f"  {FLGreen}In use:{CRst} {FGray}{path.translate(CONTROL_ESCAPES)}{CRst} "
                  f"{FLGreen}[{' / '.join(sorted(kinds))}]{CRst}")

    # ── completion and incomplete-result diagnostics ────────
    status = " (scan incomplete)" if scan.warnings else ""
    print(f"\n{FLCyan}Matched processes{CRst}: {FLYellow}{matched}{CRst}{FGray}{status}{CRst}")
    print("")
    
    warnings = list(dict.fromkeys(scan.warnings))
    shown = warnings if verbose else warnings[:3]
    for warning in shown:
        detail = warning if verbose else warning.split("; PIDs:", 1)[0]
        print(f"{FLYellow}Warning{CRst}: {detail.translate(CONTROL_ESCAPES)}{CRst}", file=sys.stderr)
    if warnings and not verbose:
        print(f"{FLYellow}Use --verbose for all {len(warnings)} diagnostics and PID details.{CRst}", file=sys.stderr)
    if not matched:
        print("The scan is incomplete; path availability could not be determined." if scan.warnings else
              "No matching references found in this scan. This does not prove the path is unused.")
    return 1 if scan.warnings else 0


def main() -> int:
    """Run the interactive/CLI path query with mandatory elevated privileges.

    Returns:
        0 for a completed query; 1 for failures or known incomplete results.

    Raises:
        SystemExit: Help/argument parsing, interactive exit, or elevated restart.
        KeyboardInterrupt: Propagates to the standard module-level handler.

    Side effects:
        May request administrator/root elevation; prompts when no path is supplied, invokes
        native read-only queries, and writes results/diagnostics to the terminal.
    """
    args = _parser().parse_args()
    if args._windows_worker is not None:
        skipped = {tuple(map(int, item.split(":"))) for item in args._skip}
        if any(len(item) != 2 for item in skipped):
            raise ValueError("Invalid internal query skip record")
        return _windows_worker(args._windows_worker, args.pid, args.path,
                               {(item[0], item[1]) for item in skipped})
    if not _require_elevation():
        return 1
    Console.print_banner("PATH IN USE")
    if sys.platform not in SUPPORTED_PLATFORMS:
        print(f"{FLRed}Unsupported platform: {sys.platform}{CRst}")
        return 1

    # ── dependencies and input ──────────────────────────────
    try:
        import psutil
    except ImportError:
        print(f"{FLRed}Missing dependency: psutil. Install with: pip install psutil{CRst}")
        return 1
    try:
        command = _backend_command(args.pid)
        path: str | None = args.path
        if path is None:
            if not Console.has_interactive_input():
                raise ValueError("A file/directory path is required when stdin is not interactive")
            path = Input.resolve_input_path("", prompt="File or directory to inspect", path_type="any")
        if sys.platform == "win32" and re.fullmatch(r"[A-Za-z]:", path):
            path = f"{path}/"
        target = Paths.resolve_path(path, os.getcwd(), resolve_symlinks=True)
        target_path = Path(target)
        if not target_path.exists():
            raise ValueError(f"Path does not exist: {target}")
        directory = target_path.is_dir()
        if not directory and not target_path.is_file():
            raise ValueError("Only files and directories are supported; pass a mount point for a disk")

        # ── query and report ────────────────────────────────────
        print(f"{FLCyan}Scanning: {target.translate(CONTROL_ESCAPES)}{CRst}")
        if sys.platform == "win32":
            command.append(target)
        scan = _native_scan(command, args.timeout)
        if sys.platform == "win32":
            _windows_process_references(scan, args.pid)
        return _print_results(scan, target, directory, args.pid, args.process, args.verbose)
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"{FLRed}Error: {str(exc).translate(CONTROL_ESCAPES)}{CRst}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
