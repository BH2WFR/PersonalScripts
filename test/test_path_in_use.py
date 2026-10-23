"""Path-usage backend fixtures and privilege guards; never elevate or close handles.

Run: conda run -n base python -m unittest discover -s test -p test_path_in_use.py
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import psutil


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("path_in_use_test_target", ROOT / "tools/filesystem/path-in-use.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class PathUsageTests(unittest.TestCase):
    """Verify native formats, exact path boundaries, diagnostics, and privilege gates."""

    def test_windows_boundaries_roots_unc_and_exact_files(self) -> None:
        cases = [
            ("d:/DATA/file.txt", "D:/Data", True, True),
            ("D:/Data-old/file.txt", "D:/Data", True, False),
            ("D:/Data", "D:/Data", True, True),
            ("D:/file.txt", "D:/", True, True),
            ("E:/file.txt", "D:/", True, False),
            ("D:/Data/file.txt.bak", "D:/Data/file.txt", False, False),
            ("D:/Data/file.txt:stream", "D:/Data/file.txt", False, True),
            (r"\\?\D:\Data\file.txt", "D:/Data", True, True),
            (r"\\?\UNC\server\share\file.txt", r"\\server\share", True, True),
        ]
        for path, target, directory, expected in cases:
            with self.subTest(path=path, target=target):
                self.assertEqual(runner._path_matches(path, target, directory, True), expected)

    def test_posix_boundaries_case_deleted_and_root(self) -> None:
        self.assertTrue(runner._path_matches("/mnt/data/a (deleted)", "/mnt/data", True, False))
        self.assertTrue(runner._path_matches("/mnt/data", "/", True, False))
        self.assertTrue(runner._path_matches("/mnt/data", "/mnt/data/", True, False))
        self.assertFalse(runner._path_matches("/mnt/database/a", "/mnt/data", True, False))
        self.assertFalse(runner._path_matches("/mnt/DATA/a", "/mnt/data", True, False))
        self.assertFalse(runner._path_matches("/mnt/data/a.bak", "/mnt/data/a", False, False))
        self.assertTrue(runner._path_matches("/mnt/a (deleted)", "/mnt/a (deleted)", False, False))

    def test_windows_worker_unicode_and_truncated_records(self) -> None:
        record = {"pid": 42, "path": "D:/Data/测试 file.txt", "kind": "handle 10A"}
        raw = f"{json.dumps(record)}\n".encode()
        scan = runner._parse_windows_worker(raw)
        self.assertEqual(len(scan.references), 1)
        self.assertEqual(scan.references[0].pid, 42)
        self.assertEqual(scan.references[0].path, "D:/Data/测试 file.txt")
        self.assertTrue(scan.warnings)
        self.assertFalse(runner._parse_windows_worker(raw + b'{"complete": true}\n').warnings)
        scan = runner._parse_windows_worker(raw + b'{"pid": 43,')
        self.assertEqual(len(scan.references), 1)
        self.assertTrue(scan.warnings)

    def test_lsof_fields_cwd_mapped_deleted_unicode_and_denied(self) -> None:
        raw = (b"p42\0ceditor\0\nfcwd\0tDIR\0n/mnt/data\0\n"
               b"f3\0tREG\0n/mnt/data/\\xe6\\xb5\\x8b\\xe8\\xaf\\x95 file.txt\0\n"
               b"fmem\0tREG\0n/mnt/data/old (deleted)\0\n"
               b"p43\0cworker\0\nf4\0n/proc/43/fd/4 (readlink: Permission denied)\0\n")
        scan = runner._parse_lsof(raw)
        self.assertEqual([ref.pid for ref in scan.references], [42, 42, 42])
        self.assertEqual(scan.references[1].path, "/mnt/data/测试 file.txt")
        self.assertEqual(scan.references[2].kind, "mem")
        self.assertTrue(scan.warnings)
        with self.assertRaises(RuntimeError):
            runner._parse_lsof(b"n/path-with-no-process\0")

    def test_native_errors_and_partial_results_are_not_empty_success(self) -> None:
        partial = subprocess.CompletedProcess(["lsof"], 1, b"p42\0capp\0\nf3\0n/data/file\0\n", b"lsof: WARNING: denied")
        with patch.object(sys, "platform", "linux"), patch.object(runner, "_run_query", return_value=partial):
            scan = runner._native_scan(["lsof"], 5)
        self.assertEqual(len(scan.references), 1)
        self.assertTrue(scan.warnings)
        for result in (subprocess.CompletedProcess(["lsof"], 0, b"", b""),
                       subprocess.CompletedProcess(["lsof"], 1, b"", b"denied")):
            with patch.object(sys, "platform", "darwin"), patch.object(runner, "_run_query", return_value=result):
                self.assertTrue(runner._native_scan(["lsof"], 5).warnings)
        with patch.object(sys, "platform", "linux"), patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("lsof", 5)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                runner._run_query(["lsof"], 5)

    def test_windows_backend_has_no_tool_dependency_and_keeps_timeout_results(self) -> None:
        record = b'{"pid":42,"path":"D:/data/file","kind":"handle 10"}\n'
        partial = subprocess.CompletedProcess(["worker"], 1, record, b"Windows worker timed out")
        with patch.object(sys, "platform", "win32"), patch.object(runner.Environment, "which") as which:
            command = runner._backend_command(42)
            self.assertIn("--_windows-worker", command)
            self.assertEqual(command[-2:], ["--pid", "42"])
            which.assert_not_called()
            with patch.object(runner, "_run_windows_query", return_value=partial):
                scan = runner._native_scan(command, 5)
            self.assertEqual(scan.references[0].pid, 42)
            self.assertTrue(scan.warnings)

    def test_worker_does_not_bypass_elevation(self) -> None:
        with patch.object(sys, "argv", ["path-in-use.py", "--_windows-worker", "42"]):
            with patch.object(runner.System, "is_elevated", return_value=False), patch.object(runner, "_WindowsHandleApi") as api:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.main(), 1)
                api.assert_not_called()
                self.assertIn("administrator", output.getvalue())

    @unittest.skipUnless(sys.platform == "win32", "Requires real Windows Kernel32 APIs")
    def test_real_windows_system_table_finds_unicode_file_and_preserves_source(self) -> None:
        # Inspect only this test process, without elevation or any external tool.
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="path-in-use-", dir=scratch) as directory:
            path = Path(directory) / "🔴 测试 file.txt"
            with path.open("w+b") as source:
                source.write(b"source is still open")
                source.flush()
                references: list[str] = []
                api = runner._WindowsHandleApi()
                api.scan_process(os.getpid(), lambda reference: references.append(reference.path))
                kernel_path = api.path_to_kernel_name(str(path))
                matches = [reference for reference in references
                           if runner._path_matches(reference, kernel_path, False, True)]
                self.assertTrue(matches, "Native system handle table did not find the open fixture")
                source.seek(0)
                self.assertEqual(source.read(), b"source is still open")

    @unittest.skipUnless(sys.platform == "win32", "Requires real Windows Kernel32 APIs")
    def test_real_windows_remote_file_and_directory_without_handle_leaks(self) -> None:
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        child_code = """
import sys
with open(sys.argv[1], "w+b") as source:
    source.write(b"still usable")
    source.flush()
    print("ready", flush=True)
    sys.stdin.read(1)
    source.seek(0)
    print(source.read().decode("ascii"), flush=True)
"""
        with tempfile.TemporaryDirectory(prefix="path-in-use-", dir=scratch) as directory:
            path = Path(directory) / "跨进程 file.txt"
            with subprocess.Popen([sys.executable, "-c", child_code, str(path)], cwd=directory,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW) as child:
                try:
                    assert child.stdout is not None
                    self.assertEqual(child.stdout.readline().strip(), b"ready")
                    api = runner._WindowsHandleApi()
                    before = psutil.Process().num_handles()
                    references: list[str] = []
                    for _ in range(3):
                        api.scan_process(child.pid, lambda reference: references.append(reference.path))
                    self.assertEqual(psutil.Process().num_handles(), before)
                    kernel_path = api.path_to_kernel_name(str(path))
                    kernel_directory = api.path_to_kernel_name(directory)
                    self.assertTrue(any(runner._path_matches(reference, kernel_path, False, True)
                                        for reference in references))
                    self.assertTrue(any(runner._path_matches(reference, kernel_directory, False, True)
                                        for reference in references))
                    output, errors = child.communicate(b"x", timeout=5)
                    self.assertEqual(child.returncode, 0, errors)
                    self.assertIn(b"still usable", output)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=5)

    def test_kernel_path_matching_aliases_and_directory_boundaries(self) -> None:
        target = r"\Device\HarddiskVolume8\Downloads"
        self.assertEqual(runner._windows_match_path(f"{target}\\🔴 file.pdf", target,
                                                    "D:/Downloads", True), "D:/Downloads\\🔴 file.pdf")
        self.assertIsNone(runner._windows_match_path(f"{target}-old\\file.pdf", target,
                                                     "D:/Downloads", True))
        self.assertEqual(runner._windows_match_path(target, target, "D:/Downloads", True), "D:/Downloads")

    @unittest.skipUnless(sys.platform == "win32", "Requires Windows mapped-file APIs")
    def test_worker_finds_mapping_after_file_and_section_handles_close(self) -> None:
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        child_code = """
import ctypes, sys
k = ctypes.WinDLL('kernel32', use_last_error=True)
p, d = ctypes.c_void_p, ctypes.c_uint32
k.CreateFileW.argtypes = [ctypes.c_wchar_p, d, d, p, d, d, p]
k.CreateFileW.restype = p
k.CreateFileMappingW.argtypes = [p, p, d, d, d, ctypes.c_wchar_p]
k.CreateFileMappingW.restype = p
k.MapViewOfFile.argtypes = [p, d, d, d, ctypes.c_size_t]
k.MapViewOfFile.restype = p
k.CloseHandle.argtypes = [p]
k.UnmapViewOfFile.argtypes = [p]
source = k.CreateFileW(sys.argv[1], 0x80000000, 7, None, 3, 0, None)
section = k.CreateFileMappingW(source, None, 2, 0, 0, None)
view = k.MapViewOfFile(section, 4, 0, 0, 0)
if not view:
    raise ctypes.WinError(ctypes.get_last_error())
k.CloseHandle(source)
k.CloseHandle(section)
print('ready', flush=True)
sys.stdin.read(1)
k.UnmapViewOfFile(view)
"""
        with tempfile.TemporaryDirectory(prefix="path-in-use-", dir=scratch) as directory:
            path = Path(directory) / "🔴 映射-only.pdf"
            path.write_bytes(b"mapped contents" * 100)
            with subprocess.Popen([sys.executable, "-c", child_code, str(path)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=subprocess.CREATE_NO_WINDOW) as child:
                try:
                    assert child.stdout is not None
                    self.assertEqual(child.stdout.readline().strip(), b"ready")
                    with patch.object(runner.System, "is_elevated", return_value=True):
                        with contextlib.redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(runner._windows_worker(os.getpid(), child.pid, str(path)), 0)
                    scan = runner._parse_windows_worker(output.getvalue().encode())
                    self.assertTrue(any(ref.pid == child.pid and ref.kind == "mapped file/module"
                                        for ref in scan.references))
                    self.assertFalse(any(ref.kind.startswith("handle") for ref in scan.references))
                    child.communicate(b"x", timeout=5)
                    self.assertEqual(child.returncode, 0)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate(timeout=5)

    @unittest.skipUnless(sys.platform == "win32", "Requires Windows process creation")
    def test_watchdog_skips_stalled_query_and_resumes(self) -> None:
        code = """
import json, sys, time
if '--_skip' not in sys.argv:
    print(json.dumps({'checking': [42, 123]}), flush=True)
    time.sleep(30)
else:
    print(json.dumps({'pid': 99, 'path': 'D:/data/file', 'kind': 'handle 12'}), flush=True)
    print(json.dumps({'complete': True}), flush=True)
"""
        with patch.object(runner, "HANDLE_STALL_SECONDS", 0.1):
            result = runner._run_windows_query([sys.executable, "-u", "-c", code], 5)
        self.assertEqual(result.returncode, 0)
        scan = runner._parse_windows_worker(result.stdout)
        self.assertEqual(scan.references[0].pid, 99)
        self.assertTrue(any("skipped stalled" in note for note in scan.warnings))

    def test_incomplete_results_summarize_diagnostics(self) -> None:
        scan = runner.Scan(warnings=[f"Unavailable process {pid}; PIDs: {pid}." for pid in range(20)])
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(runner._print_results(scan, "/data", True, None, None), 1)
        self.assertIn("scan incomplete", output.getvalue())
        self.assertNotIn("No matching references found", output.getvalue())
        self.assertLessEqual(len(error.getvalue().splitlines()), 4)

    def test_executable_path_grouping_filters_and_missing_metadata(self) -> None:
        scan = runner.Scan([
            runner.Reference(42, "editor", "/data/file", "3"),
            runner.Reference(42, "editor", "/data/file", "4"),
            runner.Reference(43, "worker", "/database/file", "3"),
        ])
        process = Mock()
        process.name.return_value = "Editor"
        process.exe.return_value = "/opt/editor/bin/editor"
        with patch.object(sys, "platform", "linux"), patch.object(psutil, "Process", return_value=process):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner._print_results(scan, "/data", True, 42, "EDIT"), 0)
        self.assertIn(f"{runner.FLGreen}PID:{runner.CRst} 42", output.getvalue())
        self.assertIn("/opt/editor/bin/editor", output.getvalue())
        self.assertEqual(output.getvalue().count(f"In use:{runner.CRst} /data/file"), 1)
        self.assertNotIn(f"PID:{runner.CRst} 43", output.getvalue())
        with patch.object(sys, "platform", "linux"), patch.object(psutil, "Process", side_effect=psutil.AccessDenied(42)):
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner._print_results(scan, "/data", True, None, None), 1)
        self.assertIn(f"{runner.FLGreen}PID:{runner.CRst} 42", output.getvalue())
        self.assertIn(f"{runner.FLGreen}Executable:{runner.CRst} <unavailable>", output.getvalue())

    def test_help_and_invalid_arguments_never_elevate(self) -> None:
        for arguments, status in ((["--help"], 0), (["--timeout", "nan"], 2), (["--pid", "0"], 2)):
            with patch.object(sys, "argv", ["path-in-use.py", *arguments]), patch.object(runner, "_require_elevation") as elevate:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        runner.main()
                self.assertEqual(caught.exception.code, status)
                elevate.assert_not_called()

    def test_failed_elevation_never_queries_or_prompts(self) -> None:
        with patch.object(sys, "argv", ["path-in-use.py"]), patch.object(runner, "_require_elevation", return_value=False):
            with patch.object(runner, "_native_scan") as scan, patch.object(runner.Input, "resolve_input_path") as prompt:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 1)
                scan.assert_not_called()
                prompt.assert_not_called()
        with patch.object(sys, "platform", "linux"), patch.object(runner.System, "is_elevated", return_value=False):
            with patch.object(runner.System, "restart_elevated") as restart, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(runner._require_elevation())
                restart.assert_not_called()
            self.assertIn("sudo", output.getvalue())
        with patch.object(sys, "platform", "win32"), patch.object(runner.System, "is_elevated", return_value=False):
            with patch.object(runner.System, "restart_elevated") as restart, contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(runner._require_elevation())
                restart.assert_called_once()

    def test_main_uses_real_path_and_propagates_scan_failure(self) -> None:
        with patch.object(sys, "argv", ["path-in-use.py", str(ROOT)]), patch.object(runner, "_require_elevation", return_value=True):
            with patch.object(runner, "_backend_command", return_value=["backend"]), patch.object(runner, "_native_scan", side_effect=RuntimeError("backend failed")):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(runner.main(), 1)
                self.assertIn("backend failed", error.getvalue())


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        runner.Console.print_keyboard_interrupt_message_and_exit()
