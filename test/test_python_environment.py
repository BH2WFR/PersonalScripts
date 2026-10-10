"""Verify interpreter identity and generated Windows launchers with local fixtures.

Run with conda run -n base python -m unittest discover -s test -p
test_python_environment.py. Batch tests do not request elevation or write outside tmp.
"""

import contextlib
from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import Environment, PythonEnvironment, FLYellow, CRst

SPEC = importlib.util.spec_from_file_location("script_to_app_test_target", ROOT / "tools/windows/script-to-app.py")
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class ScratchCase(unittest.TestCase):
    """Provide disposable project-local fixtures."""

    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        scratch = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="python-identity-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)


class IdentityTests(ScratchCase):
    """Ignore shell activation, path keywords, and the packager's build environment."""

    def test_conda_metadata_in_custom_location_without_activation(self) -> None:
        prefix = self.root / "custom" / "science"
        (prefix / "conda-meta").mkdir(parents=True)
        with patch.object(sys, "prefix", str(prefix)), patch.object(sys, "executable", str(prefix / "python.exe")), \
                patch.object(sys, "frozen", False, create=True), patch.dict(os.environ, {}, clear=True):
            runtime = Environment.get_python_environment()
        self.assertEqual(runtime.conda_env, "science")
        self.assertEqual(runtime.prefix, str(prefix))
        self.assertEqual(runtime.executable, str(prefix / "python.exe"))

    def test_base_and_named_environment_with_conda_package(self) -> None:
        for suffix, expected in (("distribution", "base"), ("distribution/envs/science", "science")):
            prefix = self.root / suffix
            (prefix / "conda-meta").mkdir(parents=True)
            (prefix / "conda-meta/conda-26.1-0.json").write_text("{}", encoding="utf-8")
            with self.subTest(prefix=prefix), patch.object(sys, "prefix", str(prefix)), \
                    patch.object(sys, "frozen", False, create=True):
                self.assertEqual(Environment.get_conda_env(), expected)

    def test_nonconda_and_venv_ignore_active_conda(self) -> None:
        for suffix in ("ordinary-python", "miniconda/envs/not-conda", "venv"):
            prefix = self.root / suffix
            prefix.mkdir(parents=True)
            with self.subTest(prefix=prefix), patch.object(sys, "prefix", str(prefix)), \
                    patch.object(sys, "base_prefix", str(self.root / "miniconda")), \
                    patch.dict(os.environ, {"CONDA_PREFIX": "some-other-prefix", "CONDA_DEFAULT_ENV": "base"}):
                self.assertIsNone(Environment.get_conda_env())

    def test_frozen_app_is_not_conda_even_with_metadata_and_active_shell(self) -> None:
        prefix = self.root / "bundle"
        (prefix / "conda-meta").mkdir(parents=True)
        with patch.object(sys, "prefix", str(prefix)), patch.object(sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"CONDA_PREFIX": str(prefix), "CONDA_DEFAULT_ENV": "base"}):
            runtime = Environment.get_python_environment()
            self.assertTrue(runtime.frozen)
            self.assertIsNone(runtime.conda_env)
            with self.assertRaisesRegex(ValueError, "bundled application"):
                app._build_launcher_content("target.py", runtime)

    def test_display_marks_only_actual_conda(self) -> None:
        for name in (None, "science"):
            runtime = PythonEnvironment("python.exe", "prefix", "3.13.12", False, name)
            output = io.StringIO()
            with patch.object(Environment, "get_python_environment", return_value=runtime), \
                    patch.object(Environment, "find_conda", return_value=None), \
                    patch.object(Environment, "find_pwsh", return_value=None), \
                    patch.object(Environment, "find_bash", return_value=None), contextlib.redirect_stdout(output):
                Environment.print_env_info(probe_versions=False)
            self.assertEqual("Conda env:" in output.getvalue(), name is not None)
            self.assertEqual(f"3.13.12 {FLYellow}Conda{CRst}" in output.getvalue(), name is not None)

    def test_confirmation_uses_the_same_runtime_as_the_generated_file(self) -> None:
        target = self.root / "target.py"
        target.touch()
        for name in (None, "science"):
            runtime = PythonEnvironment("chosen-python.exe", "chosen-prefix", "3.13.12", False, name)
            output = io.StringIO()
            with patch.object(Environment, "get_python_environment", return_value=runtime), \
                    patch.object(Environment, "find_conda_executable", return_value="conda.exe"), \
                    patch.object(app.System, "is_elevated", return_value=True), \
                    patch.object(app, "_write_launcher") as write, \
                    patch("builtins.input", return_value=""), contextlib.redirect_stdout(output):
                self.assertEqual(app.main([
                    "--target-script", str(target), "--app-name", "Example",
                    "--output-dir", str(self.root),
                ]), 0)
            self.assertIn(runtime.executable, output.getvalue())
            self.assertIn(runtime.prefix, output.getvalue())
            self.assertEqual("Conda env" in output.getvalue(), name is not None)
            self.assertEqual(write.call_args.args[2], runtime)


@unittest.skipUnless(sys.platform == "win32", "Windows batch integration")
class BatchTests(ScratchCase):
    """Execute generated CMD files, including real Conda and isolated venv Python."""

    def setUp(self) -> None:
        super().setUp()
        self.runtime = Environment.get_python_environment()
        self.conda = Environment.find_conda_executable()
        self.target = self.root / "target script.py"
        self.target.write_text(
            "import json,sys\nprint(json.dumps(sys.argv[1:], ensure_ascii=True))\n",
            encoding="utf-8",
        )

    def run_launcher(self, runtime: PythonEnvironment, target: Path | None = None) -> subprocess.CompletedProcess[str]:
        launcher = self.root / "launch test.cmd"
        app._write_launcher(str(launcher), str(target or self.target), runtime, self.conda)
        data = launcher.read_bytes()
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        # Execute the batch language with its required interpreter, not PowerShell.
        command = subprocess.list2cmdline([os.environ.get("COMSPEC", "cmd.exe")])
        return subprocess.run(
            f'{command} /d /s /c ""{launcher}" "opened file.txt""',
            input="\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )

    def test_current_runtime_forwards_arguments(self) -> None:
        result = self.run_launcher(self.runtime)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(json.dumps(["opened file.txt"]), result.stdout)

    def test_missing_script_and_wrong_environment_explain_regeneration(self) -> None:
        for runtime, target, message in (
            (self.runtime, self.root / "missing.py", "Target script is missing"),
            (replace(self.runtime, executable=str(self.root / "missing.exe")), self.target, "recorded Python environment"),
            (replace(self.runtime, prefix=str(self.root / "wrong-prefix")), self.target, "recorded Python environment"),
        ):
            with self.subTest(message=message):
                result = self.run_launcher(runtime, target)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(message, result.stdout)
                self.assertIn("Delete this .cmd file and regenerate", result.stdout)

    def test_target_error_keeps_exit_code_and_is_not_an_environment_error(self) -> None:
        self.target.write_text("raise SystemExit(7)\n", encoding="utf-8")
        result = self.run_launcher(self.runtime)
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn("Script execution failed with exit code: 7", result.stdout)
        self.assertNotIn("Delete this .cmd", result.stdout)

    def test_nonconda_venv_with_inherited_conda_activation(self) -> None:
        prefix = self.root / "plain-venv"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(prefix)], check=True, capture_output=True)
        runtime = PythonEnvironment(str(prefix / "Scripts/python.exe"), str(prefix), sys.version.split()[0], False, None)
        with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "unrelated", "CONDA_PREFIX": "unrelated"}):
            probe = subprocess.run(
                [runtime.executable, "-c", "from utils import Environment; print(Environment.get_conda_env())"],
                cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(probe.stdout.strip(), "None")
            result = self.run_launcher(runtime)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(json.dumps(["opened file.txt"]), result.stdout)


if __name__ == "__main__":
    unittest.main()
