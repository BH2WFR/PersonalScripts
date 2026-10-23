"""Check package loading, launcher discovery, and mocked compiler staging.

No synchronization or compiler is started. Temporary fixtures stay below tmp/.
"""

import contextlib
import importlib.util
import inspect
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import typing
import unittest
from unittest.mock import Mock, patch

from _rclone_test_support import (
    ROOT, runner, app, backend, endpoint_ops, execution, models, schema_ops,
    terminal, utility,
)


def _load_entry(name: str, filename: str) -> ModuleType:
    """Import a repository entry without executing its main function."""
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compiler = _load_entry("rclone_compiler_test_target", "compile-script.py")
launcher = _load_entry("rclone_launcher_test_target", "run-script.py")


class PackageIntegrationTests(unittest.TestCase):
    """Verify boundaries affected by moving a standalone script into a package."""

    def setUp(self) -> None:
        (ROOT / "tmp").mkdir(exist_ok=True)
        scratch = tempfile.TemporaryDirectory(prefix="rclone-integration-", dir=ROOT / "tmp")
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def test_source_help_from_another_working_directory(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/network/rclone-sync.py"), "--help"],
            cwd=self.scratch, capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--schema-file", result.stdout)
        self.assertIn("--task", result.stdout)

    def test_help_does_not_query_disks_or_start_processes(self) -> None:
        with (
            patch.object(sys, "argv", ["rclone-sync.py", "--help"]),
            patch.object(utility.System, "scan_disks") as scan,
            patch.object(subprocess, "run") as run,
            patch.object(subprocess, "Popen") as popen,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(runner.main(), 0)
        scan.assert_not_called()
        run.assert_not_called()
        popen.assert_not_called()

    def test_entry_preserves_source_and_executable_script_directories(self) -> None:
        executable = self.scratch / "rclone-sync.exe"
        for frozen, expected in ((False, runner.SCRIPT_DIR), (True, executable.parent)):
            with (
                self.subTest(frozen=frozen),
                patch.object(runner, "IS_FROZEN", frozen),
                patch.object(sys, "executable", str(executable)),
                patch.object(app, "main", return_value=17) as main,
            ):
                self.assertEqual(runner.main(), 17)
                main.assert_called_once_with(str(expected))

    def test_repeated_loading_preserves_module_and_model_identity(self) -> None:
        self.assertIs(runner.load_app(), app)
        self.assertIs(runner.load_app().models.PathPairConfig, models.PathPairConfig)

    def test_module_annotations_resolve_after_split(self) -> None:
        for module in (models, schema_ops, endpoint_ops, backend, terminal, execution, app):
            namespace = {**vars(module), "schema_ops": schema_ops}
            for name, value in vars(module).items():
                if (inspect.isfunction(value) or inspect.isclass(value)) and value.__module__ == module.__name__:
                    with self.subTest(module=module.__name__, member=name):
                        typing.get_type_hints(value, globalns=namespace)

    def test_discovery_lists_only_the_public_entry(self) -> None:
        # Use the checked-in config alone, excluding machine-local patch files.
        shutil.copy2(ROOT / "launcher-config.yaml", self.scratch / "launcher-config.yaml")
        config = launcher._load_launcher_config(str(self.scratch))
        with (
            patch.object(utility.Environment, "find_bash", return_value=None),
            patch.object(utility.Environment, "find_pwsh", return_value=None),
        ):
            discovered = launcher.find_scripts(str(ROOT / "tools"), config)
        normalized = [path.replace("\\", "/") for path in discovered]
        self.assertIn("network/rclone-sync.py", normalized)
        self.assertFalse(any(path.startswith("network/rclone-sync/") for path in normalized))
        compiled = [path.replace("\\", "/") for path in compiler.find_py_scripts(str(ROOT / "tools"))]
        self.assertIn("network/rclone-sync.py", compiled)
        self.assertFalse(any(path.startswith("network/rclone-sync/") for path in compiled))

    def test_compiler_stages_importable_package_and_cleans_up(self) -> None:
        entry = str(ROOT / "tools/network/rclone-sync.py")
        for tool in ("nuitka", "pyinstaller"):
            for fail in (False, True):
                with self.subTest(tool=tool, fail=fail):
                    stages: list[Path] = []

                    def compile_stub(
                        command: list[str], *, check: bool, env: dict[str, str],
                    ) -> subprocess.CompletedProcess[bytes]:
                        stage = Path(env["PYTHONPATH"].split(os.pathsep)[0])
                        stages.append(stage)
                        self.assertEqual(stage.parent, self.scratch)
                        package = stage / "personal_rclone_sync"
                        self.assertTrue((package / "__init__.py").is_file())
                        self.assertTrue((package / "app.py").is_file())
                        self.assertFalse((package / "README.md").exists())
                        self.assertEqual(command[-1], entry)
                        self.assertFalse(check)
                        self.assertTrue(env["PYTHONPATH"].endswith(f"{os.pathsep}original-import-path"))
                        if tool == "nuitka":
                            self.assertIn("--include-package=personal_rclone_sync", command)
                        else:
                            self.assertEqual(command[-5:-1], ["--paths", str(stage), "--collect-submodules", "personal_rclone_sync"])
                        if fail:
                            raise OSError("Compiler could not start")
                        return subprocess.CompletedProcess(command, 0)

                    command = [sys.executable, "-m", tool, entry]
                    original = list(command)
                    with (
                        patch.dict(os.environ, {"PYTHONPATH": "original-import-path"}),
                        patch.object(compiler.subprocess, "run", side_effect=compile_stub),
                    ):
                        if fail:
                            with self.assertRaises(OSError):
                                compiler._run_compiler(command, entry, str(self.scratch), tool)
                        else:
                            result = compiler._run_compiler(command, entry, str(self.scratch), tool)
                            self.assertEqual(result.returncode, 0)
                        self.assertEqual(os.environ["PYTHONPATH"], "original-import-path")
                    self.assertEqual(command, original)
                    self.assertEqual(len(stages), 1)
                    self.assertFalse(stages[0].exists())

    def test_other_scripts_keep_the_original_compiler_invocation(self) -> None:
        entry = str(self.scratch / "other.py")
        command = [sys.executable, "-m", "nuitka", entry]
        with patch.object(compiler.subprocess, "run", return_value=Mock(returncode=0)) as run:
            result = compiler._run_compiler(command, entry, str(self.scratch), "nuitka")
        self.assertEqual(result.returncode, 0)
        run.assert_called_once_with(command, check=False)


if __name__ == "__main__":
    unittest.main()
