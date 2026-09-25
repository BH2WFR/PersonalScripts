"""Characterize launcher behavior while moving shared logic into utils.

Run with conda run -n base python -m unittest discover -s test -p
test_launcher_utils.py. Fixtures are isolated under the ignored project tmp
directory; no real Conda environment is created or modified.
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
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("launcher_utils_test_target", ROOT / "run-script.py")
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = launcher
SPEC.loader.exec_module(launcher)


class ScratchCase(unittest.TestCase):
    """Provide an isolated project directory with deterministic launcher config."""

    def setUp(self) -> None:
        """Create only test fixtures within the repository scratch directory."""
        (ROOT / "tmp").mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="launcher-utils-", dir=ROOT / "tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "tools").mkdir()
        (self.root / "deps").mkdir()
        config: dict[str, object] = {
            "launcher": {
                "script-root": "tools", "test": {"enabled": False, "test-root": "test"},
                "additional-path-env": "LAUNCHER_TEST_PATHS", "requirements-file": "requirements.txt",
                "excluded-paths": [],
                "script-types": {name: {"extension": extension, "color": "CRst"} for name, extension in (
                    ("python", ".py"), ("bash", ".sh"), ("powershell", ".ps1"))},
            },
            "display": {"default-folder-color": "CRst", "test-header-color": "CRst", "additional-header-color": "CRst"},
            "script-name-highlight-pattern": {}, "folder-name-highlight-pattern": {},
            "ignore-list": {"all-platforms": [], "platform-specific": {}},
            "extra-env-paths": {"all-platforms": ["deps", "missing-dep", "./deps"]},
        }
        (self.root / "launcher-config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


class PathTests(ScratchCase):
    """Retain the launcher's permissive expansion and lexical path behavior."""

    def test_native_expansion_preserves_undefined_variables_and_literal_placeholders(self) -> None:
        with patch.dict(os.environ, {"LAUNCHER_TEST_ROOT": str(self.root), "LAUNCHER_TEST_HOME": "~"}):
            for text in ("./tools/../deps", "${LAUNCHER_TEST_ROOT}/deps", "${LAUNCHER_UNDEFINED}/x", "{{schema_dir}}/x", "${LAUNCHER_TEST_HOME}/x"):
                with self.subTest(text=text):
                    expanded = os.path.expanduser(os.path.expandvars(text))
                    expected = os.path.abspath(os.path.join(self.root, expanded))
                    self.assertEqual(launcher.Paths.resolve_path(text, self.root), expected)

    def test_preexpanded_input_stays_literal_and_symlink_resolution_is_opt_in(self) -> None:
        with patch.dict(os.environ, {"LAUNCHER_TEST_LITERAL": "expanded"}):
            expected = str(self.root / "${LAUNCHER_TEST_LITERAL}")
            self.assertEqual(launcher.Paths.resolve_path("${LAUNCHER_TEST_LITERAL}", self.root, expand_environment=False), expected)
        with patch.object(Path, "resolve", return_value=Path("/resolved")) as resolve:
            launcher.Paths.resolve_path("dir/../file", self.root)
            resolve.assert_not_called()
            self.assertEqual(launcher.Paths.resolve_path("dir/../file", self.root, resolve_symlinks=True), str(Path("/resolved")))
            resolve.assert_called_once()

    def test_directories_deduplicate_and_report_missing_once(self) -> None:
        file_path = self.root / "plain-file"
        file_path.touch()
        missing: list[str] = []
        result = launcher.Paths.resolve_directories(
            ["deps", "./deps", "missing", "./missing", "plain-file", "tools"],
            self.root, on_missing=missing.append,
        )
        self.assertEqual(result, (str(self.root / "deps"), str(self.root / "tools")))
        self.assertEqual(missing, [str(self.root / "missing"), str(file_path)])

    def test_config_and_additional_directories_use_shared_resolution(self) -> None:
        config = launcher._load_launcher_config(str(self.root))
        self.assertEqual(config.script_root, str(self.root / "tools"))
        self.assertEqual(config.test_root, str(self.root / "test"))
        self.assertEqual(config.requirements_file, str(self.root / "requirements.txt"))
        self.assertEqual(config.extra_env_paths, (str(self.root / "deps"),))
        raw = os.pathsep.join([" deps ", "", "./deps", "missing", "./missing", "tools"])
        stderr = io.StringIO()
        with patch.dict(os.environ, {"LAUNCHER_TEST_PATHS": raw}), contextlib.redirect_stderr(stderr):
            paths = launcher._resolve_additional_directories(str(self.root), config)
        self.assertEqual(paths, [str(self.root / "deps"), str(self.root / "tools")])
        self.assertEqual(stderr.getvalue().count("Ignoring missing additional directory:"), 1)

    def test_prepend_path_preserves_duplicates_order_and_empty_path_behavior(self) -> None:
        for original in (None, "", "old-path"):
            with self.subTest(original=original), patch.dict(os.environ, clear=True):
                if original is not None:
                    os.environ["PATH"] = original
                launcher.Environment.prepend_path(())
                self.assertEqual(os.environ.get("PATH"), original)
                launcher.Environment.prepend_path(("first", "first", "second"))
                expected = os.pathsep.join(["first", "first", "second", *([original] if original else [])])
                self.assertEqual(os.environ["PATH"], expected)


class CondaTests(ScratchCase):
    """Preserve environment selection, JSON discovery, errors, and the fast path."""

    def test_current_environment_needs_no_conda_or_version_probe(self) -> None:
        with patch.object(launcher.Environment, "get_conda_env", return_value="base"), \
                patch.object(launcher.Environment, "find_conda") as find, \
                patch.object(subprocess, "run") as run:
            self.assertEqual(launcher.Environment.resolve_conda_python("base"), os.path.abspath(sys.executable))
            find.assert_not_called()
            run.assert_not_called()

    def test_discovery_honors_custom_env_dirs_and_base_root(self) -> None:
        base = self.root / "conda-base"
        selected = self.root / "custom-env-dir" / "research"
        for directory in (base, selected):
            (directory / "conda-meta").mkdir(parents=True)
            executable = directory / ("python.exe" if sys.platform in ("win32", "cygwin", "msys") else "bin/python")
            executable.parent.mkdir(exist_ok=True)
            executable.touch()
        response = subprocess.CompletedProcess([], 0, json.dumps({"root_prefix": str(base), "envs": [str(base), str(selected)]}), "")
        with patch.object(launcher.Environment, "get_conda_env", return_value=None), \
                patch.object(launcher.Environment, "find_conda", return_value="conda-test"), \
                patch.object(subprocess, "run", return_value=response) as run:
            for name, directory in (("base", base), ("research", selected)):
                with self.subTest(name=name):
                    expected = directory / ("python.exe" if sys.platform in ("win32", "cygwin", "msys") else "bin/python")
                    self.assertEqual(launcher.Environment.resolve_conda_python(name), str(expected))
            self.assertEqual(run.call_args.args[0], ["conda-test", "info", "--envs", "--json"])
            self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_missing_conda_and_query_failure_errors_are_preserved(self) -> None:
        with patch.object(launcher.Environment, "get_conda_env", return_value=None), \
                patch.object(launcher.Environment, "find_conda", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "conda is not in PATH"):
                launcher.Environment.resolve_conda_python("research")
        cases = [
            (subprocess.CompletedProcess([], 3, "", "query failed\nmore detail"), "query failed more detail"),
            (subprocess.CompletedProcess([], 2, "", ""), "conda exited with code 2"),
            (subprocess.CompletedProcess([], 0, "invalid-json", ""), "invalid environment data"),
            (subprocess.CompletedProcess([], 0, "[]", ""), "invalid environment data"),
            (subprocess.CompletedProcess([], 0, "{}", ""), "incomplete environment data"),
        ]
        for response, message in cases:
            with self.subTest(message=message), patch.object(launcher.Environment, "get_conda_env", return_value=None), \
                    patch.object(launcher.Environment, "find_conda", return_value="conda-test"), \
                    patch.object(subprocess, "run", return_value=response), self.assertRaisesRegex(RuntimeError, message):
                launcher.Environment.resolve_conda_python("research")

    def test_missing_ambiguous_invalid_and_pythonless_environment_fail(self) -> None:
        first = self.root / "a/research"
        second = self.root / "b/research"
        for envs, has_meta, message in (([], False, "does not exist"), ([str(first), str(second)], False, "Multiple Conda"),
                                        ([str(first)], False, "is invalid"), ([str(first)], True, "no Python executable")):
            if has_meta:
                (first / "conda-meta").mkdir(parents=True)
            response = subprocess.CompletedProcess([], 0, json.dumps({"root_prefix": str(self.root), "envs": envs}), "")
            with self.subTest(message=message), patch.object(launcher.Environment, "get_conda_env", return_value=None), \
                    patch.object(launcher.Environment, "find_conda", return_value="conda-test"), \
                    patch.object(subprocess, "run", return_value=response), self.assertRaisesRegex(RuntimeError, message):
                launcher.Environment.resolve_conda_python("research")


class LauncherTests(ScratchCase):
    """Protect pass-through arguments, shell policy, stdin support, and exit codes."""

    def test_environment_option_precedence_and_argument_passthrough(self) -> None:
        with patch.dict(os.environ, {"ZL_CONDA_ENV": "from-variable"}):
            invocation = launcher._parse_launcher_invocation(["--env=chosen", "--env-info", "tool", "--env=target-argument", "a b"])
            self.assertEqual(launcher._default_conda_env_name(invocation.conda_env_name), "chosen")
            self.assertEqual(invocation.arguments, ("tool", "--env=target-argument", "a b"))
            self.assertTrue(invocation.probe_environment_versions)
            self.assertEqual(launcher._default_conda_env_name(None), "from-variable")
        with patch.dict(os.environ, {"ZL_CONDA_ENV": " "}):
            self.assertEqual(launcher._default_conda_env_name(None), "base")

    def test_shell_selection_flags_and_exit_codes_are_unchanged(self) -> None:
        response = subprocess.CompletedProcess([], 23)
        with patch.object(launcher.Environment, "find_bash", return_value="selected-bash"), \
                patch.object(launcher.Environment, "find_pwsh", return_value="selected-powershell"), \
                patch.object(subprocess, "run", return_value=response) as run:
            self.assertEqual(launcher.run_sh_script("script.sh", ["a b", ""]), 23)
            self.assertEqual(run.call_args.args[0], ["selected-bash", "script.sh", "a b", ""])
            self.assertEqual(launcher.run_ps1_script("script.ps1", ["a b", ""]), 23)
            self.assertEqual(run.call_args.args[0], ["selected-powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "script.ps1", "a b", ""])

    def test_main_accepts_piped_selection_and_keeps_in_process_python(self) -> None:
        (self.root / "tools/example.py").write_text("import sys\ndef main() -> int:\n    print(repr(sys.argv[1:]))\n    return 19\n", encoding="utf-8")
        stdout = io.StringIO()
        with patch.object(launcher, "_get_project_dir", return_value=str(self.root)), \
                patch.object(launcher.Environment, "resolve_conda_python", return_value=sys.executable) as resolve, \
                patch.object(launcher.Environment, "print_env_info") as info, \
                patch.object(sys, "argv", ["run-script.py"]), \
                patch.object(sys, "stdin", io.StringIO("example --env=target-argument value\n")), \
                patch.object(sys, "path", list(sys.path)), patch.dict(os.environ, {"LAUNCHER_TEST_PATHS": "", "ZL_CONDA_ENV": "base"}), \
                patch.object(subprocess, "run") as run, contextlib.redirect_stdout(stdout):
            self.assertEqual(launcher.main(), 19)
            resolve.assert_called_once_with("base")
            info.assert_called_once_with(probe_versions=False)
            run.assert_not_called()
        self.assertIn("['--env=target-argument', 'value']", stdout.getvalue())

    def test_other_python_environment_remains_a_child_process(self) -> None:
        script = str(self.root / "tools/example.py")
        executable = str(self.root / "another-python.exe")
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 29)) as run:
            self.assertEqual(launcher.run_py_script(script, ["a b", 'a"b', ""], executable), 29)
            run.assert_called_once_with([executable, os.path.abspath(script), "a b", 'a"b', ""], check=False)

    def test_default_list_has_no_subprocess_version_probes(self) -> None:
        (self.root / "tools/example.py").touch()
        with patch.object(launcher, "_get_project_dir", return_value=str(self.root)), \
                patch.object(sys, "argv", ["run-script.py", "--list"]), \
                patch.dict(os.environ, {"LAUNCHER_TEST_PATHS": ""}), \
                patch.object(subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.main(), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
