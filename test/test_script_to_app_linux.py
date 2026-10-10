"""Verify Linux desktop generation using project-local files and mocked sessions.

Bash integration runs on POSIX hosts. Desktop discovery and terminal selection
still require a Linux desktop for end-to-end verification.
Run: conda run -n base python -m unittest discover -s test -p test_script_to_app_linux.py
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("linux_script_to_app", ROOT / "tools/script-to-app.py")
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class LinuxLauncherTests(unittest.TestCase):
    """Cover XDG paths, MIME selection, desktop session guards and safe generation."""

    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="linux-app-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.target = self.root / "target.py"
        self.target.touch()
        self.runtime = app.PythonEnvironment("/selected/python", "/selected", "3.13.13", False, None)

    def test_xdg_defaults_overrides_and_relative_values(self) -> None:
        for value, expected in (("", os.path.expanduser("~/.local/share")),
                                ("relative/data", os.path.expanduser("~/.local/share")),
                                (str(self.root), str(self.root))):
            with self.subTest(value=value), patch.object(sys, "platform", "linux"), \
                    patch.dict(os.environ, {"XDG_DATA_HOME": value}):
                self.assertEqual(app._resolve_output_dir(None), os.path.join(expected, "applications/PersonalScripts"))
                self.assertEqual(app._resolve_output_dir(str(self.root)), str(self.root))

    def test_mime_validation_and_interactive_retry(self) -> None:
        for invalid in ("text/*", "text", "text/plain;image/png", "text/plain\nName=bad", "text/plain;charset=utf-8"):
            with self.subTest(value=invalid), self.assertRaises(argparse.ArgumentTypeError):
                app._validate_mime_type(invalid)
        output = io.StringIO()
        with patch("builtins.input", side_effect=["1", "", "text/*", " Text/Plain ;text/csv;text/plain;"]), \
                contextlib.redirect_stdout(output):
            self.assertEqual(app._select_linux_mime_types(None), ("text/plain", "text/csv"))
        for example in ("text/plain", "text/csv", "image/png", "application/pdf"):
            self.assertIn(example, output.getvalue())
        self.assertIn("Enter at least one MIME type", output.getvalue())
        with patch("builtins.input") as prompt:
            self.assertEqual(app._select_linux_mime_types(["text/plain", "text/plain"]), ("text/plain",))
            self.assertEqual(app._select_linux_mime_types(None, all_files=True), ())
            prompt.assert_not_called()

    def test_interactive_all_files_choice_and_return_from_mime_input(self) -> None:
        for answers in (["2"], ["1", "b", "2"]):
            output = io.StringIO()
            with self.subTest(answers=answers), patch("builtins.input", side_effect=answers), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(app._select_linux_mime_types(None), ())
            self.assertIn("Try all files (not guaranteed)", output.getvalue())

    def test_all_files_creation_omits_mime_key_and_explains_manual_selection(self) -> None:
        for cli in ([], ["--all-files"]):
            output_dir = self.root / ("interactive" if not cli else "cli")
            output = io.StringIO()
            answers = ["2", ""] if not cli else [""]
            with self.subTest(cli=cli), patch.object(sys, "platform", "linux"), \
                    patch.object(app.System, "get_linux_gui", return_value=app.LinuxGui.X11), \
                    patch.object(app.Environment, "check_commands", return_value=True), \
                    patch.object(app.Environment, "select_python_environment", return_value=(self.runtime, None)), \
                    patch.object(app, "_refresh_linux_desktop_database"), \
                    patch("builtins.input", side_effect=answers), contextlib.redirect_stdout(output):
                self.assertEqual(app.main([
                    "--target-script", str(self.target), "--app-name", "GenericTool",
                    "--output-dir", str(output_dir), *cli,
                ]), 0)
            content = (output_dir / "GenericTool.desktop").read_text(encoding="utf-8")
            self.assertNotIn("MimeType=", content)
            self.assertNotIn("application/octet-stream", content)
            self.assertIn(" %F\n", content)
            self.assertIn("not guaranteed", output.getvalue())
            self.assertIn("Other / All Applications", output.getvalue())

    def test_cli_modes_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            app._build_arg_parser().parse_args(["--all-files", "--mime-type", "text/plain"])
        self.assertEqual(result.exception.code, 2)

    def test_x11_and_wayland_create_user_entries_without_elevation(self) -> None:
        for gui in (app.LinuxGui.X11, app.LinuxGui.WAYLAND):
            data_home = self.root / gui.value
            output = io.StringIO()
            with self.subTest(gui=gui), patch.object(sys, "platform", "linux"), \
                    patch.dict(os.environ, {"XDG_DATA_HOME": str(data_home)}), \
                    patch.object(app.System, "get_linux_gui", return_value=gui), \
                    patch.object(app.Environment, "check_commands", return_value=True), \
                    patch.object(app.Environment, "select_python_environment", return_value=(self.runtime, None)), \
                    patch.object(app.System, "try_restart_elevated") as elevate, \
                    patch.object(app, "_refresh_linux_desktop_database") as refresh, \
                    patch("builtins.input", return_value=""), contextlib.redirect_stdout(output):
                self.assertEqual(app.main([
                    "--target-script", str(self.target), "--app-name", "中文 Viewer",
                    "--mime-type", "text/plain", "--mime-type", "text/csv",
                ]), 0)
            entry = data_home / "applications/PersonalScripts/中文 Viewer.desktop"
            content = entry.read_text(encoding="utf-8")
            self.assertIn("Name=中文 Viewer\n", content)
            self.assertIn("Terminal=true\n", content)
            self.assertIn("MimeType=text/plain;text/csv;\n", content)
            self.assertTrue(Path(f"{entry}.sh").is_file())
            self.assertIn(str(entry), output.getvalue())
            self.assertIn(f"{entry}.sh", output.getvalue())
            elevate.assert_not_called()
            refresh.assert_called_once_with(str(entry.parent))
            self.assertFalse((data_home / "mimeapps.list").exists())

    def test_cancel_preserves_existing_entry_and_companion(self) -> None:
        entry = self.root / "Example.desktop"
        runner = Path(f"{entry}.sh")
        entry.write_text("original entry", encoding="utf-8")
        runner.write_text("original runner", encoding="utf-8")
        with patch.object(sys, "platform", "linux"), \
                patch.object(app.System, "get_linux_gui", return_value=app.LinuxGui.X11), \
                patch.object(app.Environment, "check_commands", return_value=True), \
                patch.object(app.Environment, "select_python_environment", return_value=(self.runtime, None)), \
                patch("builtins.input", side_effect=["y", "n"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main([
                "--target-script", str(self.target), "--app-name", "Example",
                "--output-dir", str(self.root), "--mime-type", "text/plain",
            ]), 0)
        self.assertEqual(entry.read_text(encoding="utf-8"), "original entry")
        self.assertEqual(runner.read_text(encoding="utf-8"), "original runner")

    def test_orphaned_runner_also_requires_overwrite_confirmation(self) -> None:
        Path(f"{self.root}/Example.desktop.sh").touch()
        with patch.object(sys, "platform", "linux"), patch("builtins.input", return_value="") as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(app._resolve_launcher_path(str(self.root), "Example"))
        prompt.assert_called_once()

    def test_exec_and_name_use_desktop_escaping(self) -> None:
        self.assertEqual(
            app._desktop_exec_argument('/tmp/A "B" $HOME \\C %F.sh'),
            r'"/tmp/A \\"B\\" \\$HOME \\\\C %%F.sh"',
        )
        self.assertEqual(app._desktop_string("Name\nExec=bad\t\\tail"), r"Name\nExec=bad\t\\tail")

    def test_optional_cache_refresh_uses_applications_root(self) -> None:
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root), "XDG_DATA_DIRS": str(self.root / "system")}), \
                patch.object(app.Environment, "which", return_value="cache-updater"), \
                patch.object(app.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            app._refresh_linux_desktop_database(str(self.root / "applications/PersonalScripts"))
        self.assertEqual(run.call_args.args[0], ["cache-updater", str(self.root / "applications")])

    def test_cache_unavailable_or_failed_does_not_undo_creation(self) -> None:
        for updater in (None, "cache-updater"):
            output = io.StringIO()
            with self.subTest(updater=updater), \
                    patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root), "XDG_DATA_DIRS": str(self.root / "system")}), \
                    patch.object(app.Environment, "which", return_value=updater), \
                    patch.object(app.subprocess, "run", side_effect=subprocess.TimeoutExpired("cache-updater", 15)), \
                    contextlib.redirect_stdout(output):
                app._refresh_linux_desktop_database(str(self.root / "custom-output"))
            self.assertIn("outside XDG", output.getvalue())
            self.assertTrue("unavailable" in output.getvalue() or "could not be refreshed" in output.getvalue())

    def test_linux_flags_rejected_on_other_platforms(self) -> None:
        for platform in ("win32", "darwin"):
            for args in (["--mime-type", "text/plain"], ["--all-files"]):
                with self.subTest(platform=platform, args=args), patch.object(sys, "platform", platform), \
                        patch.object(app.System, "try_restart_elevated") as elevate, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as result:
                    app.main(args)
                self.assertEqual(result.exception.code, 2)
                elevate.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "Native POSIX Bash integration")
    def test_real_runner_forwards_unicode_arguments_and_preserves_failure(self) -> None:
        runtime = app.Environment.get_python_environment()
        conda = app.Environment.find_conda_executable()
        self.target.write_text(
            'import json,sys\nprint(json.dumps(sys.argv[1:], ensure_ascii=False))\nraise SystemExit(7)\n',
            encoding="utf-8",
        )
        entry = self.root / "中文 ' quoted.desktop"
        app._write_linux_launcher(str(entry), str(self.target), runtime, conda, ("text/plain",))
        arguments = ["中文 space.txt", "literal '$HOME' & percent%.csv"]
        result = subprocess.run(
            ["/bin/bash", f"{entry}.sh", *arguments], input="\n", capture_output=True,
            text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn(json.dumps(arguments, ensure_ascii=False), result.stdout)
        self.assertIn("exit code: 7", result.stdout)
        self.assertEqual(stat.S_IMODE(entry.stat().st_mode), 0o700)
        self.assertFalse(entry.read_bytes().startswith(b"\xef\xbb\xbf"))

    @unittest.skipUnless(sys.platform == "linux", "Linux GIO desktop-entry integration")
    def test_gio_launch_parses_quoted_paths_and_file_arguments(self) -> None:
        gio = app.Environment.which("gio")
        if gio is None:
            self.skipTest("Optional GIO command is not available")
        directory = self.root / '中文 space "quote" $dollar `tick` %F back\\slash'
        directory.mkdir()
        target = directory / "target.py"
        target.write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'Path(__file__).with_suffix(".json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")\n',
            encoding="utf-8",
        )
        entry = directory / "中文 应用.desktop"
        app._write_linux_launcher(
            str(entry), str(target), app.Environment.get_python_environment(),
            app.Environment.find_conda_executable(), ("text/plain",),
        )
        # Test the real desktop parser without depending on a terminal emulator.
        entry.write_text(entry.read_text(encoding="utf-8").replace("Terminal=true", "Terminal=false"), encoding="utf-8")
        paths = [directory / "file space.txt", directory / "中文 'quote' %F $HOME.txt"]
        for path in paths:
            path.touch()
        result = subprocess.run([gio, "launch", str(entry), *map(str, paths)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = target.with_suffix(".json")
        deadline = time.monotonic() + 15
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(output.exists())
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), [str(path) for path in paths])


if __name__ == "__main__":
    unittest.main()
