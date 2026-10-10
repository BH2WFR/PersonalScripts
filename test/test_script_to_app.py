"""Verify the merged launcher workflow without elevation or file associations.

Run: conda run -n base python -m unittest discover -s test -p test_script_to_app.py
All generated files are isolated under the repository's ignored tmp directory.
"""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("merged_script_to_app", ROOT / "tools/script-to-app.py")
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class LauncherWorkflowTests(unittest.TestCase):
    """Keep platform routing, cancellation, help and output paths consistent."""

    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="merged-app-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.target = self.root / "target.py"
        self.target.touch()
        self.runtime = app.PythonEnvironment("selected-python", "selected-prefix", "3.13.13", False, None)

    def arguments(self) -> list[str]:
        """Return explicit CLI inputs pointing into this test's scratch directory."""
        return ["--target-script", str(self.target), "--app-name", "Example",
                "--output-dir", str(self.root / "launchers")]

    def test_default_and_custom_destinations_on_both_platforms(self) -> None:
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    patch.dict(os.environ, {"ProgramFiles": str(self.root / "Program Files")}):
                expected = (str(self.root / "Program Files/PersonalScripts") if platform == "win32"
                            else os.path.expanduser("~/Applications/PersonalScripts"))
                self.assertEqual(app._resolve_output_dir(None), expected)
                self.assertEqual(app._resolve_output_dir(str(self.root)), str(self.root))

    def test_help_never_requests_elevation_or_runtime_selection(self) -> None:
        for platform in ("win32", "darwin", "linux"):
            output = io.StringIO()
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    patch.object(app.System, "try_restart_elevated") as elevate, \
                    patch.object(app.Environment, "select_python_environment") as select, \
                    contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
                app.main(["--help"])
            self.assertEqual(result.exception.code, 0)
            elevate.assert_not_called()
            select.assert_not_called()
            self.assertIn("--output-dir", output.getvalue())

    def test_headless_linux_rejects_creation_before_prompting(self) -> None:
        with patch.object(sys, "platform", "linux"), \
                patch.object(app.System, "get_linux_gui", return_value=app.LinuxGui.NO_GUI), \
                patch.object(app.Environment, "select_python_environment") as select, \
                patch("builtins.input") as prompt, contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as result:
            app.main(self.arguments())
        self.assertNotEqual(result.exception.code, 0)
        select.assert_not_called()
        prompt.assert_not_called()
        self.assertFalse((self.root / "launchers").exists())

    def test_windows_elevation_failure_uses_writable_destination(self) -> None:
        original_argv = sys.argv
        replayed: list[str] = []

        def fail_elevation() -> bool:
            """Capture the replay arguments without requesting administrator access."""
            replayed.extend(sys.argv)
            return False

        output = io.StringIO()
        with patch.object(sys, "platform", "win32"), \
                patch.object(app.System, "is_elevated", return_value=False), \
                patch.object(app.System, "try_restart_elevated", side_effect=fail_elevation), \
                patch.object(app.Environment, "select_python_environment", return_value=(self.runtime, None)), \
                patch.object(app, "_create_app_bundle") as bundle, \
                patch("builtins.input", return_value=""), contextlib.redirect_stdout(output):
            self.assertEqual(app.main(self.arguments()), 0)
        self.assertIs(sys.argv, original_argv)
        self.assertEqual(replayed, [str(ROOT / "tools/script-to-app.py"), *self.arguments()])
        bundle.assert_not_called()
        launcher = self.root / "launchers/Example.cmd"
        data = launcher.read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertIn(b'"%ZL_APP_TARGET%" %*', data)
        self.assertIn(str(launcher), output.getvalue())
        self.assertIn("Created:", output.getvalue())

    def test_macos_uses_bundle_backend_without_elevation(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "platform", "darwin"), \
                patch.object(app.System, "try_restart_elevated") as elevate, \
                patch.object(app.Environment, "select_python_environment", return_value=(self.runtime, None)), \
                patch.object(app, "_create_app_bundle") as bundle, \
                patch.object(app, "_write_info_plist") as plist, \
                patch.object(app, "_write_launcher") as cmd, \
                patch.object(app.subprocess, "run"), \
                patch("builtins.input", return_value=""), contextlib.redirect_stdout(output):
            self.assertEqual(app.main(self.arguments()), 0)
        launcher = str(self.root / "launchers/Example.app")
        bundle.assert_called_once_with(launcher, str(self.target), self.runtime, None)
        self.assertEqual(plist.call_args.args[:2], (os.path.join(launcher, "Contents"), "Example.app"))
        cmd.assert_not_called()
        elevate.assert_not_called()
        self.assertIn(launcher, output.getvalue())
        self.assertIn("Created:", output.getvalue())

    def test_cancelling_runtime_selection_creates_nothing(self) -> None:
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    patch.object(app.System, "is_elevated", return_value=True), \
                    patch.object(app.Environment, "select_python_environment", return_value=None), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.main(self.arguments()), 0)
            self.assertFalse((self.root / "launchers").exists())

    def test_names_cannot_escape_output_directory(self) -> None:
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                app._resolve_launcher_path(str(self.root), "../outside")


if __name__ == "__main__":
    unittest.main()
