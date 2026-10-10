"""Test macOS bundle generation without requiring Finder or invoking osacompile.

Run with conda run -n base python -m unittest discover -s test -p
test_script_to_app_macos.py. All fixtures stay in the project's tmp directory.
"""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import Environment, PythonEnvironment

SPEC = importlib.util.spec_from_file_location("mac_script_to_app", ROOT / "tools/macos/script-to-app.py")
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class MacAppTests(unittest.TestCase):
    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="mac-app-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.runtime = PythonEnvironment("/opt/custom/bin/python", "/opt/custom", "3.13.12", False, None)

    def test_conda_discovery_finds_unactivated_posix_installation(self) -> None:
        prefix = self.root / "distribution"
        executable = prefix / "bin/conda"
        executable.parent.mkdir(parents=True)
        executable.touch()
        with patch.object(sys, "platform", "darwin"), \
                patch.object(Environment, "find_conda", return_value=None), \
                patch.object(os, "access", return_value=True), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Environment.find_conda_executable(prefix=str(prefix / "envs/science")), str(executable))

    def test_shared_menu_accepts_conda_python_in_bin(self) -> None:
        prefix = self.root / "science"
        runtime = PythonEnvironment(str(prefix / "bin/python"), str(prefix), "3.13.12", False, "science")
        with patch.object(sys, "platform", "darwin"), \
                patch.object(Environment, "get_python_environment", return_value=runtime), \
                patch.object(Environment, "find_conda_executable", return_value="/opt/base/bin/conda"), \
                patch.object(Environment, "resolve_runtime", return_value=("/opt/base/bin/conda", "conda 26")), \
                patch.object(Environment, "resolve_conda_python", return_value=runtime.executable), \
                patch("builtins.input", side_effect=["2", "1", "science"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(Environment.select_python_environment(), (runtime, "/opt/base/bin/conda"))

    def test_compilation_records_selected_runtime_and_keeps_apple_event_handlers(self) -> None:
        captured: list[str] = []
        bundle = self.root / "Example.app"
        target = str(self.root / "script with 'quotes'.py")
        source_path = self.root / "source.applescript"
        source_fd = os.open(source_path, os.O_WRONLY | os.O_CREAT)

        def compile_mock(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            self.assertEqual(command[:3], ["osacompile", "-o", str(bundle)])
            captured.append(Path(command[3]).read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with patch.object(tempfile, "mkstemp", return_value=(source_fd, str(source_path))), \
                patch.object(subprocess, "run", side_effect=compile_mock):
            app._create_app_bundle(str(bundle), target, self.runtime, None)
        runner = (bundle / "Contents/Resources/python-launcher.sh").read_text(encoding="utf-8")
        self.assertIn(self.runtime.executable, runner)
        self.assertIn('"$@"', runner)
        self.assertIn("Delete this .app", runner)
        self.assertIn("on open theFiles", captured[0])
        self.assertIn("on run argv", captured[0])
        self.assertIn("python-launcher.sh", captured[0])
        self.assertIn("POSIX path of (path to me)", captured[0])
        self.assertNotIn(str(bundle), captured[0])
        self.assertIn("trap 'rm -f", captured[0])

    def test_unicode_names_have_valid_distinct_ids_and_preserved_display_names(self) -> None:
        names = ("矩阵 查看器.app", "信号 查看器.app", "Viewer_1.app", "my.app.viewer.app")
        identifiers = [app._build_bundle_id(name) for name in names]
        self.assertEqual(len(set(identifiers)), len(names))
        self.assertEqual(app._build_bundle_id("Café.app"), app._build_bundle_id("Cafe\u0301.app"))
        contents = self.root / "Contents"
        contents.mkdir()
        plist_path = contents / "Info.plist"
        for name, identifier in zip(names, identifiers):
            self.assertRegex(identifier, r"\A[A-Za-z0-9.-]+\Z")
            self.assertEqual(app._build_bundle_id(name), identifier)
            with plist_path.open("wb") as stream:
                plistlib.dump({"CFBundleExecutable": "applet"}, stream)
            app._write_info_plist(str(contents), name, identifier)
            with plist_path.open("rb") as stream:
                info = plistlib.load(stream)
            self.assertEqual(info["CFBundleDisplayName"], name.removesuffix(".app"))
            self.assertEqual(info["CFBundleIdentifier"], identifier)
            self.assertEqual(info["CFBundleExecutable"], "applet")

    def test_confirmation_and_menu_exit_preserve_existing_app(self) -> None:
        applications = self.root / "Applications/PersonalScripts"
        existing = applications / "Example.app"
        existing.mkdir(parents=True)
        marker = existing / "keep.txt"
        marker.write_text("existing", encoding="utf-8")
        target = self.root / "target.py"
        target.touch()
        for selection, inputs in ((None, ["y"]), ((self.runtime, None), ["y", "n"])):
            output = io.StringIO()
            with patch.object(sys, "platform", "darwin"), \
                    patch.object(app.os.path, "expanduser", side_effect=lambda path: str(applications) if path.startswith("~/Applications/") else path), \
                    patch.object(Environment, "select_python_environment", return_value=selection), \
                    patch.object(app, "_create_app_bundle") as create, \
                    patch("builtins.input", side_effect=inputs), contextlib.redirect_stdout(output):
                self.assertEqual(app.main(["--target-script", str(target), "--app-name", "Example"]), 0)
                create.assert_not_called()
            self.assertEqual(marker.read_text(encoding="utf-8"), "existing")
            if selection is not None:
                self.assertIn(self.runtime.version, output.getvalue())
                self.assertIn(self.runtime.executable, output.getvalue())

    def test_shell_syntax_and_missing_target_error(self) -> None:
        bash = Environment.find_bash()
        if bash is None:
            self.skipTest("Bash unavailable for generated shell validation")
        runner = self.root / "launcher.sh"
        for conda_name in (None, "science"):
            runtime = PythonEnvironment("/opt/custom/bin/python", "/opt/custom", "3.13.12", False, conda_name)
            content = app._build_shell_launcher("/nonexistent/script ' with spaces.py", runtime, "/opt/base/bin/conda" if conda_name else None)
            runner.write_text(content, encoding="utf-8", newline="\n")
            result = subprocess.run([bash, "-n", runner.as_posix()], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([bash, runner.as_posix()], input="\n", capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("Target script is missing", result.stdout)
            self.assertIn("Delete this .app", result.stdout)
            if conda_name:
                self.assertIn("--prefix /opt/custom", content)


if __name__ == "__main__":
    unittest.main()
