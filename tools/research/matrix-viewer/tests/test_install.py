"""Check safe incremental release updates; no manual matrix samples are used.

Requirements: Python 3.13+ and project utils (standard library only).
Usage: unittest discovery with -p test_install.py. All fixtures live under tmp/.
"""

import ctypes
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[2] / "_matrix_viewer_install.py"
SPEC = importlib.util.spec_from_file_location("matrix_viewer_install", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
installer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    """Deployment must preserve unchanged DLLs and files outside its inventory."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=installer.PROJECT_DIR / "tmp", prefix="viewer-install-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "stage"
        self.destination = self.root / "release"
        internal = self.source / "_internal"
        internal.mkdir(parents=True)
        (self.source / installer.EXECUTABLE).write_bytes(b"application v1")
        (internal / "library.dll").write_bytes(b"library v1")
        (internal / "build-manifest.json").write_text(
            json.dumps({"application": "MatrixViewer", "layout": "onedir"}), encoding="utf-8",
        )

    def test_unchanged_files_keep_exact_timestamps(self) -> None:
        first = installer.install_release(self.source, self.destination)
        self.assertEqual(first.updated, 3)
        before: dict[Path, int] = {}
        for path in self.destination.rglob("*"):
            if path.is_file():
                os.utime(path, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
                before[path] = path.stat().st_mtime_ns
        second = installer.install_release(self.source, self.destination)
        self.assertEqual((second.updated, second.unchanged, second.removed), (0, 3, 0))
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in before})

    def test_source_update_preserves_dependency_and_user_files(self) -> None:
        installer.install_release(self.source, self.destination)
        library = self.destination / "_internal/library.dll"
        previous_time = library.stat().st_mtime_ns
        custom = self.destination / "notes.txt"
        custom.write_text("Keep my notes.", encoding="utf-8")
        untracked = self.destination / "_internal/user-file.txt"
        untracked.write_text("Keep this too.", encoding="utf-8")
        (self.source / installer.EXECUTABLE).write_bytes(b"application v2")
        result = installer.install_release(self.source, self.destination)
        self.assertEqual((result.updated, result.unchanged), (1, 2))
        self.assertEqual(library.stat().st_mtime_ns, previous_time)
        self.assertEqual((self.destination / installer.EXECUTABLE).read_bytes(), b"application v2")
        self.assertEqual(custom.read_text(encoding="utf-8"), "Keep my notes.")
        self.assertTrue(untracked.is_file())

    def test_same_size_and_timestamp_changed_library_is_replaced(self) -> None:
        installer.install_release(self.source, self.destination)
        library = self.source / "_internal/library.dll"
        timestamp = library.stat().st_mtime_ns
        library.write_bytes(b"library v2")
        os.utime(library, ns=(timestamp, timestamp))
        result = installer.install_release(self.source, self.destination)
        self.assertEqual(result.updated, 1)
        self.assertEqual((self.destination / "_internal/library.dll").read_bytes(), b"library v2")

    def test_removed_dependencies_are_pruned(self) -> None:
        installer.install_release(self.source, self.destination)
        (self.source / "_internal/library.dll").unlink()
        result = installer.install_release(self.source, self.destination)
        self.assertEqual(result.removed, 1)
        self.assertFalse((self.destination / "_internal/library.dll").exists())

    def test_adopts_previous_pyinstaller_release(self) -> None:
        installer.install_release(self.source, self.destination)
        (self.destination / installer.INSTALL_RECORD).unlink()
        library = self.destination / "_internal/library.dll"
        timestamp = library.stat().st_mtime_ns
        result = installer.install_release(self.source, self.destination)
        self.assertEqual(result.updated, 0)
        self.assertEqual(library.stat().st_mtime_ns, timestamp)

    def test_rejects_unrelated_nonempty_destination(self) -> None:
        self.destination.mkdir()
        note = self.destination / "important.txt"
        note.write_bytes(b"do not delete")
        with self.assertRaises(ValueError):
            installer.install_release(self.source, self.destination)
        self.assertEqual(note.read_bytes(), b"do not delete")
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    def test_invalid_inventory_cannot_escape_destination(self) -> None:
        installer.install_release(self.source, self.destination)
        outside = self.root / "outside.txt"
        outside.write_bytes(b"keep")
        (self.destination / installer.INSTALL_RECORD).write_text(json.dumps({
            "application": "MatrixViewer", "version": 1, "files": {"../outside.txt": "bad"},
        }), encoding="utf-8")
        with self.assertRaises(ValueError):
            installer.install_release(self.source, self.destination)
        self.assertEqual(outside.read_bytes(), b"keep")

    def test_incomplete_build_does_not_change_release(self) -> None:
        installer.install_release(self.source, self.destination)
        exe = self.destination / installer.EXECUTABLE
        before = exe.stat().st_mtime_ns
        (self.source / installer.EXECUTABLE).unlink()
        with self.assertRaises(ValueError):
            installer.install_release(self.source, self.destination)
        self.assertEqual(exe.stat().st_mtime_ns, before)

    def test_rejects_overlapping_build_and_install(self) -> None:
        with self.assertRaises(ValueError):
            installer.install_release(self.source, self.source)
        self.assertTrue((self.source / installer.EXECUTABLE).is_file())

    def test_failed_build_leaves_existing_release_intact(self) -> None:
        installer.install_release(self.source, self.destination)
        before = {path: path.read_bytes() for path in self.destination.rglob("*") if path.is_file()}
        build = self.root / "build"
        with (patch.multiple(installer, BUILD_DIR=build, STAGE_DIR=build / "stage", SETTINGS_FILE=build / "settings.json"),
              patch.object(installer.Environment, "find_conda_executable", return_value="conda.exe"),
              patch.object(installer.subprocess, "run", return_value=SimpleNamespace(returncode=7)),
              patch.object(sys, "argv", [str(SCRIPT), "--output", str(self.destination), "--environment", "matrix-viewer-build"]),
              redirect_stdout(StringIO())):
            self.assertEqual(installer.main(), 1)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_prompt_reuses_destination_and_builds_only_in_stage(self) -> None:
        build = self.root / "build"
        build.mkdir()
        settings = build / "settings.json"
        settings.write_text(json.dumps({"application": "MatrixViewer", "output": str(self.destination),
                                        "environment": "matrix-viewer-build"}), encoding="utf-8")
        with (patch.multiple(installer, BUILD_DIR=build, STAGE_DIR=build / "stage", SETTINGS_FILE=settings),
              patch.object(installer.Environment, "find_conda_executable", return_value="conda.exe"),
              patch.object(installer.Input, "prompt", side_effect=[str(self.destination), "matrix-viewer-build"]) as prompt,
              patch.object(installer.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run,
              patch.object(installer, "install_release", return_value=installer.InstallResult(1, 2, 0)) as install,
              patch.object(sys, "argv", [str(SCRIPT)]), redirect_stdout(StringIO())):
            self.assertEqual(installer.main(), 0)
        self.assertEqual(prompt.call_args_list[0].kwargs["default"], str(self.destination))
        self.assertEqual(prompt.call_args_list[1].kwargs["default"], "matrix-viewer-build")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-n") + 1], "matrix-viewer-build")
        self.assertIn("-I", command)
        self.assertEqual(run.call_args.kwargs["env"]["PYTHONNOUSERSITE"], "1")
        self.assertNotIn("--clean", command)
        self.assertEqual(command[command.index("--distpath") + 1], str(build / "stage"))
        install.assert_called_once_with(build / "stage" / "MatrixViewer", self.destination)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["environment"], "matrix-viewer-build")

    def test_base_build_allows_user_site_without_inheriting_pythonpath(self) -> None:
        build = self.root / "build"
        settings = build / "settings.json"
        with (patch.multiple(installer, BUILD_DIR=build, STAGE_DIR=build / "stage", SETTINGS_FILE=settings),
              patch.object(installer.Environment, "find_conda_executable", return_value="conda.exe"),
              patch.object(installer.Input, "prompt") as prompt,
              patch.dict(os.environ, {"PYTHONNOUSERSITE": "1", "PYTHONPATH": "unwanted", "PYTHONHOME": "unwanted"}),
              patch.object(installer.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run,
              patch.object(installer, "install_release", return_value=installer.InstallResult(0, 3, 0)),
              patch.object(sys, "argv", [str(SCRIPT), "--output", str(self.destination), "--environment", "base"]),
              redirect_stdout(StringIO())):
            self.assertEqual(installer.main(), 0)
        prompt.assert_not_called()
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-n") + 1], "base")
        self.assertIn("-P", command)
        self.assertNotIn("-I", command)
        for name in ("PYTHONNOUSERSITE", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(name, run.call_args.kwargs["env"])
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["environment"], "base")

    def test_initial_environment_prompt_defaults_to_base(self) -> None:
        build = self.root / "build"
        with (patch.multiple(installer, BUILD_DIR=build, STAGE_DIR=build / "stage", SETTINGS_FILE=build / "settings.json"),
              patch.object(installer.Environment, "find_conda_executable", return_value="conda.exe"),
              patch.object(installer.Input, "prompt", return_value="base") as prompt,
              patch.object(installer.subprocess, "run", return_value=SimpleNamespace(returncode=7)),
              patch.object(sys, "argv", [str(SCRIPT), "--output", str(self.destination)]), redirect_stdout(StringIO())):
            self.assertEqual(installer.main(), 1)
        self.assertEqual(prompt.call_args.kwargs["default"], "base")

    @unittest.skipUnless(sys.platform == "win32", "Windows sharing/lock semantics")
    def test_locked_executable_prevents_all_release_changes(self) -> None:
        installer.install_release(self.source, self.destination)
        (self.source / "_internal/library.dll").write_bytes(b"library v2")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                      ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.CreateFileW(str(self.destination / installer.EXECUTABLE), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(PermissionError):
                installer.install_release(self.source, self.destination)
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual((self.destination / "_internal/library.dll").read_bytes(), b"library v1")


if __name__ == "__main__":
    unittest.main()
