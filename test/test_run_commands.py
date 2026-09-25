"""Behavioral tests for run-commands; no installation or external account access.

Run: conda run -n base python -m unittest discover -s test -p test_run_commands.py
Fixtures live in the repository's ignored tmp directory. Subprocess integration
checks use the current managed Python and optional installed shells only.
"""

import importlib.util
from collections.abc import Mapping
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/run-commands.py"
SPEC = importlib.util.spec_from_file_location("run_commands_test_target", RUNNER)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def schema(task: Mapping[str, object], settings: Mapping[str, object] | None = None) -> dict[str, object]:
    """Build a minimal real schema with a stable examples/test task identifier."""
    return {"settings": settings or {}, "tasks": {"examples": [{"name": "test", **task}]}}


def code_run(code: str = "pass") -> dict[str, object]:
    """Build an inline-code payload using the managed test interpreter."""
    return {"type": "code", "runtime": "python-current", "code": code}


class SchemaTests(unittest.TestCase):
    """Exercise inheritance, filters, input overwrite, and strict validation."""

    def test_diamond_and_repeated_profiles_apply_once_across_parent_child(self) -> None:
        settings = {
            "base": {"environment": {"LEVEL": "base"}},
            "left": {"inherit": ["base"], "environment": {"LEVEL": "left"}},
            "right": {"inherit": ["base"]},
        }
        config = schema({"inherit": ["left", "right", "left"],
                         "environment": {"LEVEL": "parent"},
                         "sub-tasks": [{"name": "child", "inherit": ["base"], "run": code_run()}]}, settings)
        self.assertEqual(runner._parse_schema(config)[0].config["environment"]["LEVEL"], "parent")

    def test_unused_cycles_unknown_references_and_long_chains_fail(self) -> None:
        for settings, expected in (
            ({"a": {"inherit": ["b"]}, "b": {"inherit": ["a"]}}, "a -> b -> a"),
            ({"a": {"inherit": ["missing"]}}, "Unknown profile"),
            ({"default": {"inherit": "default"}}, "default -> default"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, expected):
                runner._parse_schema(schema({"run": code_run()}, settings))
        deep = {f"p{i}": {"inherit": [f"p{i + 1}"]} for i in range(70)}
        deep["p70"] = {}
        with self.assertRaisesRegex(ValueError, "depth"):
            runner._parse_schema(schema({"run": code_run()}, deep))

    def test_context_survives_atomic_run_replacement_and_inputs_overwrite(self) -> None:
        config = schema({
            "inherit": ["profile"], "environment": {"A": "parent"},
            "interactive-inputs": {"VALUE": "Parent prompt"},
            "run": {"type": "exec", "executable": "git", "environment": {"B": "parent-run"}},
            "sub-tasks": [{"name": "child", "environment": {"A": "child"},
                           "interactive-inputs": {"VALUE": "Child prompt"},
                           "run": {**code_run(), "environment": {"A": "child-run"},
                                   "interactive-inputs": {"VALUE": "Final prompt"}}}],
        }, {"profile": {"environment": {"A": "profile"}, "interactive-inputs": {"VALUE": "Profile prompt"}}})
        task = runner._parse_schema(config)[0]
        self.assertEqual(task.config["environment"], {"A": "child-run", "B": "parent-run"})
        self.assertNotIn("executable", task.config["run"])
        with patch("builtins.input", return_value="  raw ${UNKNOWN}  ") as prompt:
            self.assertEqual(runner._input_values(task, [], interactive=True), {"VALUE": "  raw ${UNKNOWN}  "})
            prompt.assert_called_once()
            self.assertIn("Final prompt", prompt.call_args.args[0])
        self.assertEqual(runner._input_values(task, ["VALUE=first", "VALUE=last"], interactive=False), {"VALUE": "last"})

    def test_invalid_fields_types_and_execution_combinations_fail(self) -> None:
        bad_tasks = [
            {"run": {**code_run(), "shell": "conda-python"}},
            {"run": {**code_run(), "abort-on-error": True}},
            {"run": {**code_run(), "environment": []}},
            {"run": {"type": "exec", "executable": "git", "args": "--version"}},
            {"run": {"type": "script", "script-path": "demo.py"}},
            {"run": {"type": "code", "runtime": "python", "code": "pass"}},
            {"run": {"type": "shell", "runtime": "node", "command": "hello"}},
            {"run": {"type": "code", "runtime": "conda-python", "code": "pass",
                     "conda-environment": "base", "conda-prefix": "."}},
            {"environment": {"NUMBER": 12}, "run": code_run()},
            {"run": code_run(), "sub-tasks": []},
            {"run": code_run(), "platform": "windwos"},
            {"run": code_run(), "default-shell-binding": [{"runtime": "pwsh-7", "platform": "windwos"}]},
        ]
        for task in bad_tasks:
            with self.subTest(task=task), self.assertRaises(ValueError):
                runner._parse_schema(schema(task))

    def test_duplicate_task_and_subtask_identifiers_fail(self) -> None:
        config = schema({"run": code_run()})
        groups = cast(dict[str, list[dict[str, object]]], config["tasks"])
        groups["examples"].append({"name": "test", "run": code_run()})
        with self.assertRaisesRegex(ValueError, "Duplicate task"):
            runner._parse_schema(config)
        with self.assertRaisesRegex(ValueError, "Duplicate sub-task"):
            runner._parse_schema(schema({"sub-tasks": [{"name": "same", "run": code_run()}, {"name": "same", "run": code_run()}]}))

    def test_machine_filter_and_last_binding_then_explicit_runtime(self) -> None:
        task = runner._parse_schema(schema({
            "platform": ["windows", "macos"], "arch": "x64", "computer-name": ["EXAMPLE"],
            "default-shell-binding": [{"platform": "windows", "runtime": "powershell-5.1"},
                                      {"computer-name": "example", "runtime": "pwsh-7"}],
            "run": {"type": "shell", "command": "echo hello"},
        }))[0]
        with patch.object(runner.sys, "platform", "win32"), patch.object(runner.System, "get_arch", return_value="amd64"), patch.object(runner.System, "get_computer_name", return_value="example"):
            self.assertTrue(runner._matches(task.config))
            self.assertEqual(runner._runtime(task), runner.RuntimeKind.PWSH)
            task.config["run"]["runtime"] = "cmd"
            self.assertEqual(runner._runtime(task), runner.RuntimeKind.CMD)
            task.config["platform"] = "linux"
            self.assertFalse(runner._matches(task.config))


class EnvironmentTests(unittest.TestCase):
    """Check literal substitution, dependency order, and cycle diagnostics."""

    def test_forward_references_parent_path_and_literal_inputs(self) -> None:
        before = dict(os.environ)
        result = runner.Paths.resolve_environment(
            {"PATH": "original"}, {"RESULT": "${NEXT}", "NEXT": "${VALUE}", "PATH": "extra{{pathsep}}${PATH}"},
            {"VALUE": "  ${UNDEFINED}; 'quoted'  "}, {"pathsep": os.pathsep},
        )
        self.assertEqual(result["RESULT"], "  ${UNDEFINED}; 'quoted'  ")
        self.assertEqual(result["PATH"], f"extra{os.pathsep}original")
        self.assertEqual(dict(os.environ), before)

    def test_cycles_and_undefined_variables_fail(self) -> None:
        for values in ({"A": "${B}", "B": "${A}"}, {"A": "${MISSING}"}, {"A": "${A}"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                runner.Paths.resolve_environment({}, values, {}, {})

    def test_template_expansion_is_one_pass(self) -> None:
        self.assertEqual(runner.Paths.expand_template("${A}/{{current_dir}}/%B%", {"A": "${LITERAL}", "B": "end"}, {"current_dir": "{{literal}}"}), "${LITERAL}/{{literal}}/end")

    @unittest.skipUnless(os.name == "nt", "Windows case-insensitive environment")
    def test_windows_case_variants_overwrite_and_find_install_roots(self) -> None:
        result = runner.Paths.resolve_environment({"Path": "original"}, {"path": "prefix;${PATH}"}, {}, {})
        self.assertEqual(result["PATH"], "prefix;original")
        with patch.object(runner.shutil, "which", return_value=None), patch.object(Path, "is_file", return_value=True):
            paths = runner.Environment.runtime_candidates(runner.RuntimeKind.PWSH, {"PROGRAMFILES": "X:/Apps", "PATH": ""})
            self.assertIn(os.path.abspath("X:/Apps/PowerShell/7/pwsh.exe"), paths)

    @unittest.skipUnless(os.name == "nt", "PowerShell version selection")
    def test_pwsh_never_accepts_powershell_five_and_explicit_path_never_falls_back(self) -> None:
        result = subprocess.CompletedProcess([], 0, "5.1.19041\n", "")
        with patch.object(runner.subprocess, "run", return_value=result), patch.object(runner.Environment, "runtime_candidates") as candidates:
            with self.assertRaisesRegex(ValueError, "version check failed"):
                runner.Environment.resolve_runtime(runner.RuntimeKind.PWSH, executable=sys.executable)
            candidates.assert_not_called()


class ExecutionTests(unittest.TestCase):
    """Exercise the real CLI and harmless child processes with isolated fixtures."""

    def setUp(self) -> None:
        """Create an isolated directory in the ignored project scratch area."""
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="run-commands-test-", dir=ROOT / "tmp")
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        self.config = self.work / "configuration" / "config.yaml"
        self.config.parent.mkdir()

    def invoke(self, config: dict[str, object], *args: str) -> subprocess.CompletedProcess[str]:
        """Run a fixture config through the real CLI, capturing UTF-8 output."""
        self.config.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
        return subprocess.run([sys.executable, str(RUNNER), "--schema-file", str(self.config), *args],
                              cwd=self.work, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=30,
                              env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})

    def test_interactive_schema_uses_environment_default_and_can_be_changed(self) -> None:
        self.config.write_text(yaml.safe_dump(schema({"run": code_run()})), encoding="utf-8")
        alternative = self.work / "alternative.yaml"
        alternative.write_text(yaml.safe_dump(schema({"name": "alternative", "run": code_run()})), encoding="utf-8")
        for answer, expected in (("", "examples/test"), (str(alternative), "examples/alternative")):
            with self.subTest(answer=answer), patch.dict(os.environ, {runner.SCHEMA_ENV: str(self.config)}), \
                    patch.object(runner.sys, "argv", [str(RUNNER), "--list"]), \
                    patch.object(runner.Console, "has_interactive_input", return_value=True), \
                    patch("builtins.input", return_value=answer) as prompt, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(runner.main(), 0)
                prompt.assert_called_once()
                self.assertIn(str(self.config), prompt.call_args.args[0])
                self.assertIn(expected, output.getvalue())

    def test_interactive_schema_cli_overrides_default_and_no_default_requires_input(self) -> None:
        self.config.write_text(yaml.safe_dump(schema({"run": code_run()})), encoding="utf-8")
        with patch.dict(os.environ, {runner.SCHEMA_ENV: "missing.yaml"}), patch("builtins.input", return_value="") as prompt:
            path = runner._select_schema_path(str(self.config), interactive=True, invocation_dir=self.work)
            self.assertEqual(path, self.config)
            self.assertIn(str(self.config), prompt.call_args.args[0])
        with patch.dict(os.environ, {runner.SCHEMA_ENV: ""}), patch("builtins.input", return_value=str(self.config)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner._select_schema_path(None, interactive=True, invocation_dir=self.work), self.config)

    def test_direct_schema_requires_configuration_and_never_uses_sample(self) -> None:
        with patch.dict(os.environ, {runner.SCHEMA_ENV: ""}), patch.object(runner.Input, "resolve_input_path") as prompt:
            with self.assertRaisesRegex(ValueError, "No configuration path"):
                runner._select_schema_path(None, interactive=False, invocation_dir=self.work)
            self.assertEqual(runner._select_schema_path("./custom.yaml", interactive=False, invocation_dir=self.work), self.work / "custom.yaml")
            prompt.assert_not_called()
        with patch.dict(os.environ, {runner.SCHEMA_ENV: str(self.config)}):
            self.assertEqual(runner._select_schema_path(None, interactive=False, invocation_dir=self.work), self.config)

    def test_task_mode_skips_path_prompt_and_interactive_eof_cancels(self) -> None:
        self.config.write_text(yaml.safe_dump(schema({"run": code_run()})), encoding="utf-8")
        with patch.dict(os.environ, {runner.SCHEMA_ENV: str(self.config)}), \
                patch.object(runner.sys, "argv", [str(RUNNER), "--task", "examples/test", "--dry-run"]), \
                patch.object(runner.Console, "has_interactive_input", return_value=True), \
                patch("builtins.input", side_effect=AssertionError("unexpected prompt")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(), 0)
        with patch.object(runner.sys, "argv", [str(RUNNER)]), \
                patch.object(runner.Console, "has_interactive_input", return_value=True), \
                patch("builtins.input", side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(), 0)

    def test_default_cwd_is_literal_not_a_template(self) -> None:
        literal_cwd = self.work / "${UNDEFINED_CWD_VARIABLE}"
        literal_cwd.mkdir()
        task = runner._parse_schema(schema({"run": {"type": "exec", "executable": sys.executable}}))[0]
        with patch.dict(os.environ, {}, clear=True):
            plan = runner._build_plan(task, self.config, literal_cwd, {})
        self.assertEqual(plan.cwd, literal_cwd)

    def test_relative_path_lookup_uses_task_directory(self) -> None:
        project = self.work / "project"
        bin_dir = project / "bin"
        bin_dir.mkdir(parents=True)
        executable = bin_dir / ("preset-demo.exe" if os.name == "nt" else "preset-demo")
        executable.write_bytes(b"fixture, never executed")
        executable.chmod(0o755)
        if os.name == "nt":
            (bin_dir / "preset-demo").write_text("POSIX shim, not a Windows executable", encoding="utf-8")
        task = runner._parse_schema(schema({"cwd": str(project), "environment": {"PATH": "bin"},
                                           "run": {"type": "exec", "executable": "preset-demo"}}))[0]
        plan = runner._build_plan(task, self.config, self.work, {})
        self.assertEqual([os.path.normcase(item) for item in plan.argv], [os.path.normcase(str(executable))])

    def test_runtime_lookup_and_version_probe_use_task_directory(self) -> None:
        project = self.work / "project"
        bin_dir = project / "bin"
        bin_dir.mkdir(parents=True)
        executable = bin_dir / ("node.exe" if os.name == "nt" else "node")
        executable.write_bytes(b"fixture, never executed")
        executable.chmod(0o755)
        task = runner._parse_schema(schema({"cwd": str(project), "environment": {"PATH": "bin"},
                                           "run": {"type": "code", "runtime": "node", "code": "void 0"}}))[0]
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "v26.0.0\n", "")) as probe:
            plan = runner._build_plan(task, self.config, self.work, {})
            self.assertEqual(os.path.normcase(plan.argv[0]), os.path.normcase(str(executable)))
            self.assertEqual(probe.call_args.kwargs["cwd"], str(project))

    def test_interpreter_symlink_is_preserved(self) -> None:
        interpreter = self.work / ("linked-python.exe" if os.name == "nt" else "linked-python")
        try:
            interpreter.symlink_to(sys.executable)
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        task = runner._parse_schema(schema({"run": {"type": "code", "runtime": "python",
                                           "runtime-executable": str(interpreter), "code": "pass"}}))[0]
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Python 3.13.9\n", "")) as probe:
            plan = runner._build_plan(task, self.config, self.work, {})
            self.assertEqual(plan.argv[0], str(interpreter))
            self.assertEqual(probe.call_args.args[0][0], str(interpreter))

    def test_code_inputs_exit_status_and_literal_source(self) -> None:
        target = self.work / "result.json"
        code = "import json, os, pathlib, sys\npathlib.Path('result.json').write_text(json.dumps([os.environ['A'], os.environ['B'], '${LITERAL}', sys.argv[1:]]), encoding='utf-8')\nsys.exit(7)"
        config = schema({"environment": {"A": "static", "B": "${A}"}, "interactive-inputs": {"A": "Value:"},
                         "run": {**code_run(code), "args": ["a b", 'a"b', "中文", "", "tail\\", "&|%!"]}})
        result = self.invoke(config, "--task", "examples/test", "--input", "A=ignored", "--input", "A=${RAW}; 'x'", "--yes")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), ["${RAW}; 'x'", "${RAW}; 'x'", "${LITERAL}", ["a b", 'a"b', "中文", "", "tail\\", "&|%!"]])

    def test_dry_run_and_validate_do_not_execute_task(self) -> None:
        config = schema({"run": code_run("from pathlib import Path\nPath('marker').touch()")})
        result = self.invoke(config, "--task", "examples/test", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.work / "marker").exists())
        groups = cast(dict[str, list[dict[str, object]]], config["tasks"])
        groups["examples"][0]["run"] = {"type": "exec", "executable": "definitely-missing-command"}
        self.assertEqual(self.invoke(config, "--validate").returncode, 0)

    def test_relative_script_uses_task_cwd_not_config_directory(self) -> None:
        project = self.work / "project space"
        project.mkdir()
        (project / "script.py").write_text("from pathlib import Path\nPath('marker').write_text('ok', encoding='utf-8')\n", encoding="utf-8")
        config = schema({"cwd": "project space", "run": {"type": "script", "runtime": "python-current", "script-path": "./script.py"}})
        result = self.invoke(config, "--task", "examples/test", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((project / "marker").read_text(encoding="utf-8"), "ok")

    def test_exec_preserves_arguments(self) -> None:
        config = schema({"run": {"type": "exec", "executable": sys.executable, "args": ["-c", "import sys; assert sys.argv[1:] == ['a b', '中文', '', 'a\\\"b']", "a b", "中文", "", 'a"b']}})
        result = self.invoke(config, "--task", "examples/test", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_conda_multiline_code_preserves_arguments_and_input(self) -> None:
        try:
            runner.Environment.resolve_runtime(runner.RuntimeKind.CONDA)
        except ValueError as exc:
            self.skipTest(str(exc))
        config = schema({
            "interactive-inputs": {"VALUE": "Value:"},
            "run": {"type": "code", "runtime": "conda-python", "conda-environment": "base",
                    "code": "import os, json, pathlib, sys\npathlib.Path('result.json').write_text(json.dumps([sys.argv[1:], os.environ['VALUE']]), encoding='utf-8')",
                    "args": ["a b", 'a"b', "中文", "", "line\nbreak", "100% & echo nope"]},
        })
        result = self.invoke(config, "--task", "examples/test", "--input", "VALUE=${LITERAL}", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.work / "result.json").read_text(encoding="utf-8")),
                         [["a b", 'a"b', "中文", "", "line\nbreak", "100% & echo nope"], "${LITERAL}"])

    def test_noninteractive_missing_input_confirmation_and_ambiguous_child_fail(self) -> None:
        config = schema({"run": code_run(), "interactive-inputs": {"VALUE": "Value:"}})
        self.assertIn("--input VALUE=VALUE", self.invoke(config, "--task", "examples/test", "--yes").stderr)
        self.assertIn("requires --yes", self.invoke(schema({"run": code_run()}), "--task", "examples/test").stderr)
        children = [{"name": name, "run": code_run()} for name in ("one", "two")]
        self.assertIn("--sub-task", self.invoke(schema({"sub-tasks": children}), "--task", "examples/test", "--yes").stderr)

    def test_shell_blocks_share_variables_and_working_directory(self) -> None:
        runtime = "pwsh-7" if os.name == "nt" else "bash"
        try:
            runner.Environment.resolve_runtime(runner.RuntimeKind(runtime))
        except ValueError as exc:
            self.skipTest(str(exc))
        command = ["$value = 'shared'", "New-Item -ItemType Directory nested | Out-Null", "Set-Location nested", "[IO.File]::WriteAllText((Join-Path (Get-Location) 'result'), $value)"] if os.name == "nt" else ["value=shared", "mkdir nested", "cd nested", "printf '%s' \"$value\" > result"]
        result = self.invoke(schema({"run": {"type": "shell", "runtime": runtime, "command": command}}), "--task", "examples/test", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "nested/result").read_text(encoding="utf-8"), "shared")

    @unittest.skipUnless(os.name == "nt", "Windows CMD session")
    def test_cmd_list_runs_in_one_session(self) -> None:
        config = schema({"run": {"type": "shell", "runtime": "cmd", "command": ["set VALUE=shared", "echo %VALUE%>result", "exit /b 9"]}})
        result = self.invoke(config, "--task", "examples/test", "--yes")
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual((self.work / "result").read_text(encoding="utf-8").strip(), "shared")

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell 5.1 and Git Bash")
    def test_other_windows_shells_keep_session_and_return_exit_status(self) -> None:
        commands = {
            "powershell-5.1": ["$value = 'shared'", "[IO.File]::WriteAllText((Join-Path (Get-Location) 'result'), $value)", "exit 6"],
            "git-bash": ["value=shared", "printf '%s' \"$value\" > result", "exit 6"],
        }
        for runtime, command in commands.items():
            with self.subTest(runtime=runtime):
                try:
                    runner.Environment.resolve_runtime(runner.RuntimeKind(runtime))
                except ValueError as exc:
                    self.skipTest(str(exc))
                result = self.invoke(schema({"run": {"type": "shell", "runtime": runtime, "command": command}}), "--task", "examples/test", "--yes")
                self.assertEqual(result.returncode, 6, result.stderr)
                self.assertEqual((self.work / "result").read_text(encoding="utf-8"), "shared")


if __name__ == "__main__":
    unittest.main()
