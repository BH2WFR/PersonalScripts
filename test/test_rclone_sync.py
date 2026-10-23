"""Focused rclone regression tests: sync.

Run: conda run -n base python -m unittest discover -s test -p "test_rclone*.py".
All sync/network subprocesses are mocked.
"""

import contextlib
import datetime
import io
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch
import yaml
from _rclone_test_support import app, backend, endpoint_ops, execution, models, schema_ops, terminal, utility


class WorkflowTests(unittest.TestCase):
    """Verify confirmation and execution without launching real subprocesses."""

    def setUp(self) -> None:
        """Isolate environment, filesystem probes, and external execution."""

        def locate(command: object) -> bool:
            setattr(command, "path", "rclone")
            return True

        self.output = io.StringIO()
        self.enterContext(patch.dict(os.environ, {models.ENV_SCHEMA_FILE: "schema.yaml"}, clear=True))
        self.enterContext(patch.object(utility.Environment, "check_commands", side_effect=locate))
        self.enterContext(patch.object(backend, "_detect_encrypted_config", return_value=False))
        self.enterContext(patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "rclone test", "")))
        self.enterContext(patch.object(os.path, "isfile", return_value=True))
        self.enterContext(patch.object(os.path, "exists", return_value=True))
        self.enterContext(patch.object(backend, "_get_local_path_info", return_value=models.PathInfo(models.PathState.PRESENT, models.PathType.FILE)))
        self.run: MagicMock = self.enterContext(patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0)))
        self.repair: MagicMock = self.enterContext(patch.object(execution, "_fix_windows_symlinkd"))
        self.enterContext(contextlib.redirect_stdout(self.output))

    def test_custom_webdav_prompt_precedes_preview_and_cli_skips_it(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [
            {"path1": "local-one", "path2": "dav:one", "enable-custom-webdav-host": True},
            {"path1": "local-two", "path2": "dav:two"},
        ]}]}]}}
        for cli in (False, True):
            with self.subTest(cli=cli):
                self.output.seek(0)
                self.output.truncate(0)
                argv = ["runner", "--action", "push-copy", "--comparison", "size_only", "--dry-run"]
                if cli:
                    argv.extend(["--task", "test/demo"])
                answers = [] if cli else ["0", "Y", "https://example.com/dav/"]
                with patch.object(sys, "argv", argv), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"), patch("builtins.input", side_effect=answers) as prompt, patch.object(terminal, "_print_commands") as preview:
                    self.assertEqual(app.main(), 0, self.output.getvalue())
                self.assertEqual(prompt.call_count, len(answers))
                expected = "dav:one" if cli else "dav,url='https://example.com/dav/':one"
                self.assertIn(expected, preview.call_args.args[0][0])
                self.assertIn("dav:two", preview.call_args.args[0][1])
        self.run.assert_not_called()

    def test_config_menu_actions_use_selected_config_and_exit_runner(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [
            {"name": "all", "paths": [{"path1": "local", "path2": "remote:data"}]},
        ]}]}}
        config_file = os.path.abspath("rclone config.conf")
        observed_config: list[str | None] = []

        def detect_encryption(executable: str) -> bool:
            observed_config.append(os.environ.get("RCLONE_CONFIG"))
            return False

        with (
            patch.object(sys, "argv", ["runner", "--rclone-config-file", config_file]),
            patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))),
            patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"),
            patch.object(backend, "_detect_encrypted_config", side_effect=detect_encryption),
            patch.object(backend, "_get_config_file", return_value=config_file) as query,
            patch.object(utility.System, "open_with_default_app") as open_file,
        ):
            for choice in ("p", "O"):
                with self.subTest(choice=choice), patch("builtins.input", side_effect=[choice]) as prompt:
                    self.assertEqual(app.main(), 0, self.output.getvalue())
                    self.assertEqual(prompt.call_count, 1)
        self.assertEqual(observed_config, [config_file, config_file])
        self.assertEqual(query.call_count, 2)
        open_file.assert_called_once_with(config_file)
        output = self.output.getvalue()
        expected_menu = (
            f"\n\n  {utility.FGray}[{utility.CRst}P{utility.FGray}]{utility.CRst}: {utility.FLCyan}Show rclone config file path{utility.CRst}\n"
            f"  {utility.FGray}[{utility.CRst}O{utility.FGray}]{utility.CRst}: {utility.FLCyan}Open rclone config file{utility.CRst}\n"
            f"  {utility.FGray}[{utility.CRst}C{utility.FGray}]{utility.CRst}: {utility.FLCyan}Encrypt/Decrypt rclone config file{utility.CRst}\n"
            f"  {utility.FGray}[{utility.CRst}Q{utility.FGray}]{utility.CRst}: {utility.FGray}Quit{utility.CRst}"
        )
        self.assertIn(expected_menu, output)
        self.assertEqual(output.count(f"{utility.FLGreen}{config_file}{utility.CRst}"), 2)
        self.run.assert_not_called()

    def test_native_config_menu_always_exits_runner_without_selecting_a_task(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [
            {"name": "all", "paths": [{"path1": "local", "path2": "remote:data"}]},
        ]}]}}
        outcomes = (
            (subprocess.CompletedProcess([], 0), 0),
            (subprocess.CompletedProcess([], 7), 7),
            (backend.OperationCancelled(), 0),
            (OSError("Cannot launch"), 1),
        )
        for outcome, expected in outcomes:
            with self.subTest(outcome=outcome):
                self.run.reset_mock()
                self.run.side_effect = [outcome]
                with (
                    patch.object(sys, "argv", ["runner", "--rclone-config-file", "selected.conf"]),
                    patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))),
                    patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"),
                    patch("builtins.input", side_effect=["C"]) as prompt,
                    patch.object(terminal, "_select_action") as select,
                ):
                    self.assertEqual(app.main(), expected, self.output.getvalue())
                self.run.assert_called_once_with(["rclone", "config"])
                self.assertEqual(os.environ["RCLONE_CONFIG"], "selected.conf")
                self.assertEqual(prompt.call_count, 1)
                select.assert_not_called()
        self.repair.assert_not_called()
        self.assertEqual(self.output.getvalue().count("Restart this script before running sync tasks."), len(outcomes))

    def test_old_endpoint_list_rejects_entire_batch_before_execution(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [
            {"path1": "local", "path2": "remote:first"}, ["old-local", "remote:second"],
        ]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))):
            self.assertEqual(app.main(), 1)
        self.assertIn("paths[1]", self.output.getvalue())
        self.assertIn("endpoint lists are no longer supported", self.output.getvalue())
        self.run.assert_not_called()

    def test_empty_schema_or_task_lists_warn_and_exit_without_task_input(self) -> None:
        sources = ("", "# No tasks yet\n", "{}\n", "settings: {}\n", "tasks:\n",
                   "tasks: {}\n", "tasks:\n  test: []\n  ungrouped: []\n")
        for source in sources:
            for cli in (False, True):
                with self.subTest(source=source, cli=cli):
                    self.output.seek(0)
                    self.output.truncate(0)
                    argv = ["runner", "--task", "test/demo"] if cli else ["runner"]
                    with patch.object(sys, "argv", argv), patch("builtins.open", mock_open(read_data=source)), patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"), patch("builtins.input") as prompt:
                        self.assertEqual(app.main(), 1 if cli else 0, self.output.getvalue())
                    self.assertIn(f"{utility.FLYellow}WARNING: No tasks found in schema. Exiting.{utility.CRst}", self.output.getvalue())
                    prompt.assert_not_called()
        self.run.assert_not_called()

    def test_malformed_schemas_still_fail_instead_of_becoming_no_task_warnings(self) -> None:
        for source in ("tasks: []\n", "tasks: wrong\n", "tasks:\n  test: null\n", "[]\n",
                       "settings: wrong\n", "settings:\n  default:\n    inherit: [missing]\n"):
            with self.subTest(source=source):
                self.output.seek(0)
                self.output.truncate(0)
                with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=source)), patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"), patch("builtins.input") as prompt:
                    self.assertEqual(app.main(), 1)
                self.assertIn("Schema validation failed:", self.output.getvalue())
                self.assertNotIn("No tasks found", self.output.getvalue())
                prompt.assert_not_called()
        self.run.assert_not_called()

    def test_all_unmatched_tasks_are_gray_then_warn_and_exit_without_a_menu_prompt(self) -> None:
        schema = {"tasks": {"test": [{"name": "other-device", "sub-tasks": [
            {"name": "all", "computer-name": "another-device", "paths": [{"path1": "$UNDEFINED", "path2": "remote"}]},
        ]}]}}
        with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"), patch.object(utility.System, "get_computer_name", return_value="this-device"), patch("builtins.input") as prompt:
            self.assertEqual(app.main(), 0)
        output = self.output.getvalue()
        gray_label = f"{utility.FGray}     test/other-device{utility.CRst}"
        self.assertIn(gray_label, output)
        self.assertIn(f"{utility.FLYellow}WARNING: No tasks have sub-tasks matching this machine. Exiting.{utility.CRst}", output)
        self.assertLess(output.index(gray_label), output.index("WARNING:"))
        self.assertNotIn("Select task", output)
        self.assertNotIn("Path expansion failed", output)
        prompt.assert_not_called()
        self.run.assert_not_called()

    def test_unmatched_task_is_gray_and_has_no_selection_number_for_every_filter_scope(self) -> None:
        for field, value in (("platform", "linux"), ("arch", "arm64"), ("computer-name", "another-device"), ("linux-gui-required", True)):
            for scope in ("task", "subtask", "task-profile", "subtask-profile"):
                with self.subTest(field=field, scope=scope):
                    self.output.seek(0)
                    self.output.truncate(0)
                    sub: dict[str, object] = {"name": "all", "paths": [{"path1": "$UNDEFINED", "path2": "remote"}]}
                    inactive: dict[str, object] = {"name": "inactive", "sub-tasks": [sub]}
                    profile: dict[str, object] = {}
                    if scope.endswith("profile"):
                        target = inactive if scope == "task-profile" else sub
                        target["inherit"] = ["other"]
                        profile[field] = value
                    else:
                        (inactive if scope == "task" else sub)[field] = value
                    schema = {"settings": {"other": profile}, "tasks": {"test": [inactive,
                        {"name": "available", "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}]},
                    ]}}
                    with (
                        patch.object(sys, "argv", ["runner"]),
                        patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))),
                        patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"),
                        patch.object(sys, "platform", "linux" if field == "linux-gui-required" else "win32"),
                        patch.object(utility.System, "get_linux_gui", return_value=utility.LinuxGui.NO_GUI),
                        patch.object(utility.System, "get_arch", return_value="amd64"),
                        patch.object(utility.System, "get_computer_name", return_value="this-device"),
                        patch("builtins.input", side_effect=["1", "q"]) as prompt,
                    ):
                        self.assertEqual(app.main(), 0, self.output.getvalue())
                    output = self.output.getvalue()
                    self.assertIn(f"{utility.FGray}     test/inactive{utility.CRst}", output)
                    self.assertIn(f"{utility.FGray}[{utility.CRst}0{utility.FGray}]{utility.CRst}: {utility.FLYellow}test{utility.CRst}/{utility.FLCyan}available{utility.CRst}", output)
                    self.assertIn("Invalid number: 1", output)
                    self.assertNotIn("No tasks have", output)
                    self.assertEqual(prompt.call_count, 2)
        self.run.assert_not_called()

    def test_cli_linux_gui_filter_uses_utils_and_applies_before_path_resolution(self) -> None:
        for platform in ("linux", "win32", "darwin"):
            for gui in utility.LinuxGui:
                for required in (True, False):
                    with self.subTest(platform=platform, gui=gui, required=required):
                        matches = platform != "linux" or not required or gui is not utility.LinuxGui.NO_GUI
                        schema = {"tasks": {"test": [{"name": "demo", "linux-gui-required": required, "sub-tasks": [
                            {"name": "all", "do-not-check-modified-time": True, "paths": [
                                {"path1": "local" if matches else "$UNDEFINED", "path2": "target"},
                            ]},
                        ]}]}}
                        with (
                            patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-copy", "--comparison", "size_only", "--dry-run"]),
                            patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))),
                            patch.object(sys, "platform", platform),
                            patch.object(utility.System, "get_linux_gui", return_value=gui) as detect,
                            patch.object(endpoint_ops, "resolve_paths", wraps=endpoint_ops.resolve_paths) as resolve,
                            patch("builtins.input") as prompt,
                        ):
                            self.assertEqual(app.main(), 0 if matches else 1, self.output.getvalue())
                        self.assertEqual(detect.call_count, int(platform == "linux"))
                        self.assertEqual(resolve.call_count, int(matches))
                        prompt.assert_not_called()
        self.run.assert_not_called()

    def test_cli_unmatched_task_warns_and_returns_nonzero_without_prompting(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [
            {"name": "all", "computer-name": "another-device", "paths": [{"path1": "local", "path2": "remote"}]},
        ]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(utility.System, "get_computer_name", return_value="this-device"), patch("builtins.input") as prompt:
            self.assertEqual(app.main(), 1)
        self.assertIn(f"{utility.FLYellow}WARNING: Task 'test/demo' has no sub-tasks matching this machine. Exiting.{utility.CRst}", self.output.getvalue())
        prompt.assert_not_called()
        self.run.assert_not_called()

    def test_batch_executes_every_action_in_yaml_order_with_one_comparison(self) -> None:
        for action, (mode, direction) in models.ACTION_COMMANDS.items():
            with self.subTest(action=action):
                self.run.reset_mock()
                self.output.seek(0)
                self.output.truncate(0)
                schema = {"tasks": {"test": [{"name": "demo", "do-not-check-modified-time": True,
                          "path-type": "file" if action in models.FILE_ACTIONS else "directory",
                          "sub-tasks": [{"name": "all", "paths": [{"path1": "local-one", "path2": "remote-one"}, {"path1": "local-two", "path2": "remote-two"}]}]}]}}
                with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", action.value, "--comparison", "checksum"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints") as validate:
                    self.assertEqual(app.main(), 0, self.output.getvalue())
                command_mode = f"{mode}to" if action in models.FILE_ACTIONS else mode
                expected_pairs = [["remote-one", "local-one"], ["remote-two", "local-two"]] if direction == "pull" else [["local-one", "remote-one"], ["local-two", "remote-two"]]
                self.assertEqual([call.args[0][:4] for call in self.run.call_args_list], [["rclone", command_mode, *pair] for pair in expected_pairs])
                self.assertEqual(validate.call_count, 2)
                output = self.output.getvalue()
                self.assertLess(output.index("[1/2] Rclone command:"), output.index("[2/2] Rclone command:"))
                self.assertLess(output.index("[2/2] Rclone command:"), output.index("Running..."))

    def test_batch_print_only_does_not_probe_or_execute_any_pair(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [
            {"path1": "local-one", "path2": "remote-one"}, {"path1": "local-two", "path2": "remote-two"},
        ]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "pull", "--dry-run"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_display_path_mtimes") as times, patch.object(backend, "_validate_file_endpoints") as guard:
            self.assertEqual(app.main(), 0)
        output = self.output.getvalue()
        self.assertIn("sync remote-one local-one", output)
        self.assertIn("sync remote-two local-two", output)
        self.assertEqual(output.count("--dry-run"), 2)
        self.run.assert_not_called()
        times.assert_not_called()
        guard.assert_not_called()

    def test_invalid_later_path_prevents_execution_of_earlier_pairs(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [
            {"path1": "valid", "path2": "remote"}, {"path1": "$MISSING/local", "path2": "other"},
        ]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))):
            self.assertEqual(app.main(), 1)
        self.assertIn("paths[1].path1", self.output.getvalue())
        self.run.assert_not_called()

    def test_batch_move_retry_starts_at_failure_without_reselection_or_confirmation(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [
            {"path1": "a", "path2": "remote:a"}, {"path1": "b", "path2": "remote:b"}, {"path1": "c", "path2": "remote:c"},
        ]}]}]}}
        self.run.side_effect = [subprocess.CompletedProcess([], code) for code in (0, 9, 0, 0)]
        with patch.object(sys, "argv", ["runner", "--task", "test/demo"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch("builtins.input", side_effect=["y", "r", "q"]) as prompt, patch.object(terminal, "_select_action", return_value=models.SyncAction.PUSH_MOVE) as action, patch.object(terminal, "_select_comparison_mode", return_value=models.ComparisonMode.SIZE_AND_TIME) as comparison, patch.object(terminal, "_display_path_mtimes", return_value=[]) as times:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        self.assertEqual([call.args[0][2] for call in self.run.call_args_list], ["a", "b", "b", "c"])
        self.assertEqual(times.call_count, 3)
        action.assert_called_once()
        comparison.assert_called_once()
        self.assertEqual(sum("Execute" in call.args[0] for call in prompt.call_args_list), 1)
        self.assertIn("retry from [2/3]", prompt.call_args_list[1].args[0])
        self.assertIn("re-run all", prompt.call_args_list[2].args[0])

    def test_file_guard_failure_stops_remaining_pairs(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "path-type": "file", "do-not-check-modified-time": True,
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}, {"path1": "c.ini", "path2": "d.ini"}, {"path1": "e.ini", "path2": "f.ini"}]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints", side_effect=[None, ValueError("missing source")]) as guard:
            self.assertEqual(app.main(), 1)
        self.assertEqual(guard.call_count, 2)
        self.run.assert_called_once()
        self.assertIn("Pair [2/3] failed", self.output.getvalue())

    def test_successful_batch_reruns_all_and_dry_run_does_not_change_the_real_commands(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "do-not-check-modified-time": True,
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "a", "path2": "b"}, {"path1": "c", "path2": "d"}]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch("builtins.input", side_effect=["d", "y", "r", "q"]) as prompt, patch.object(terminal, "_select_action", return_value=models.SyncAction.PUSH_COPY), patch.object(terminal, "_select_comparison_mode", return_value=models.ComparisonMode.SIZE_AND_TIME):
            self.assertEqual(app.main(), 0)
        calls = self.run.call_args_list
        self.assertEqual([call.args[0][2] for call in calls], ["a", "c", "a", "c", "a", "c"])
        self.assertEqual(["--dry-run" in call.args[0] for call in calls], [True, True, False, False, False, False])
        self.assertEqual(sum("Execute" in call.args[0] for call in prompt.call_args_list), 2)
        self.assertIn("re-run all", prompt.call_args_list[2].args[0])

    def test_cli_batch_cancellation_exits_130_without_starting_later_pairs(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "do-not-check-modified-time": True,
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "a", "path2": "b"}, {"path1": "c", "path2": "d"}, {"path1": "e", "path2": "f"}]}]}]}}
        self.run.side_effect = [subprocess.CompletedProcess([], 0), backend.OperationCancelled()]
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))):
            self.assertEqual(app.main(), 130)
        self.assertEqual(self.run.call_count, 2)

    def test_batch_warnings_are_grouped_before_all_numbered_commands(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "a", "path2": "b"}, {"path1": "c", "path2": "d"}]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push-move"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_display_path_mtimes", side_effect=[["WARNING: first pair"], ["WARNING: second pair"]]):
            self.assertEqual(app.main(), 0)
        output = self.output.getvalue()
        positions = [i for i, line in enumerate(output.splitlines()) if "WARNING:" in line]
        self.assertEqual(positions, list(range(positions[0], positions[0] + 3)))
        self.assertLess(output.index("will delete"), output.index("[1/2] Rclone command:"))
        self.assertLess(output.index("[2/2] Rclone command:"), output.index("Task:"))

    def test_file_filter_warning_precedes_command_in_command_only_mode(self) -> None:
        schema = {"settings": {"default": {"exclude": ["*.bak"]}}, "tasks": {"test": [
            {"name": "config", "path-type": "file", "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}],
             "additional-args": ["--include", "*.ini", "--s3-no-check-bucket"]},
        ]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/config", "--action", "push-copy-file", "--dry-run"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))):
            self.assertEqual(app.main(), 0)
        output = self.output.getvalue()
        self.assertIn("ignoring file-selection filters: --exclude, --include", output)
        self.assertLess(output.index("WARNING:"), output.index("Rclone command:"))
        command = output.split("Rclone command:")[1]
        self.assertNotIn("--exclude", command)
        self.assertNotIn("--include", command)
        self.assertIn("--s3-no-check-bucket", command)
        self.run.assert_not_called()

    def test_file_move_groups_filter_warning_with_move_warning(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file", "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}], "exclude": ["*.bak"], "do-not-check-modified-time": True}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/config", "--action", "pull-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints"):
            self.assertEqual(app.main(), 0)
        output = self.output.getvalue()
        lines = [i for i, line in enumerate(output.splitlines()) if "WARNING:" in line]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1], lines[0] + 1)
        self.assertLess(output.index("will delete"), output.index("Rclone command:"))
        self.assertNotIn("--exclude", self.run.call_args.args[0])
        self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "moveto", "b.ini", "a.ini"])

    def test_cli_requires_an_explicit_schema_instead_of_loading_the_sample(self) -> None:
        os.environ.pop(models.ENV_SCHEMA_FILE)
        with patch.object(sys, "argv", ["runner", "--task", "test/demo"]), patch("builtins.open") as open_file:
            self.assertEqual(app.main(), 1)
        self.assertIn("With --task, specify --schema-file", self.output.getvalue())
        self.assertIn("sample is documentation only", self.output.getvalue())
        open_file.assert_not_called()
        self.run.assert_not_called()

    def test_interactive_startup_has_no_bundled_schema_suggestion(self) -> None:
        os.environ.pop(models.ENV_SCHEMA_FILE)
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote:"}]}]}]}}
        with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(utility.Input, "resolve_input_path", return_value="personal.yaml") as prompt, patch("builtins.input", return_value="q"):
            self.assertEqual(app.main(), 0)
        self.assertEqual(prompt.call_args.args[0], "")
        self.run.assert_not_called()

    def test_cli_schema_takes_precedence_over_the_environment(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote:"}]}]}]}}
        with patch.object(sys, "argv", ["runner", "--schema-file", "chosen.yaml", "--task", "test/demo"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))) as open_file, patch("builtins.input", return_value="q"):
            self.assertEqual(app.main(), 0)
        self.assertTrue(all(call.args[0] == os.path.abspath("chosen.yaml") for call in open_file.call_args_list))
        self.run.assert_not_called()

    def test_duplicate_keys_stop_loading_with_both_line_numbers(self) -> None:
        source = "tasks:\n  test:\n  - name: demo\n    local-path: first\n    local-path: second\n"
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push"]), patch("builtins.open", mock_open(read_data=source)):
            self.assertEqual(app.main(), 1)
        output = self.output.getvalue()
        self.assertIn("duplicate YAML key 'local-path'", output)
        self.assertIn("line 4, column 5", output)
        self.assertIn("line 5, column 5", output)
        self.run.assert_not_called()

    def test_undefined_path_stops_before_host_or_operation_selection(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "$MISSING/files", "path2": "remote:"}]}]}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "pull"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_interactive_host_swap") as hosts, patch.object(terminal, "_select_action") as select:
            self.assertEqual(app.main(), 1)
        self.assertIn("Path expansion failed for 'test/demo/all': paths[0].path1: Undefined environment variable: MISSING", self.output.getvalue())
        hosts.assert_not_called()
        select.assert_not_called()
        self.run.assert_not_called()

    def test_path_error_returns_to_menu_without_reloading_schema_or_password(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "$MISSING/files", "path2": "remote:"}]}]}]}}
        with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml") as schema_path, patch.object(schema_ops, "_load_schema", wraps=schema_ops._load_schema) as load, patch.object(backend, "_verify_config_password", return_value=True) as verify, patch.dict(os.environ, {models.ENV_CONFIG_PASSWORD: "test-password"}), patch("builtins.input", side_effect=["0", "q"]):
            self.assertEqual(app.main(), 0)
        schema_path.assert_called_once()
        load.assert_called_once()
        verify.assert_called_once()
        self.run.assert_not_called()

    def test_substituted_variable_syntax_remains_literal_in_final_command(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": [{"path1": "$ROOT/files", "path2": "remote"}]}],
                                     "do-not-check-modified-time": True}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.dict(os.environ, {"ROOT": "${LITERAL}"}):
            self.assertEqual(app.main(), 0)
        self.assertEqual(self.run.call_args.args[0][2], "${LITERAL}/files")

    def test_check_never_prechecks_or_repairs_links(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "preferred-mode": "move", "links": True,
                  "check-before-sync": True, "allow-actions": ["check"],
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}]}]}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/demo", "--action", "check"]))
            stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
            self.assertEqual(app.main(), 0, self.output.getvalue())
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "check", "local", "remote"])
        self.repair.assert_not_called()

    def test_single_subtask_file_resolves_cli_direction_and_checks_before_execution(self) -> None:
        schema = {"tasks": {"appdata": [{"name": "config", "path-type": "file",
                  "allow-actions": ["pull-copy-file"], "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}]}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "appdata/config", "--pull"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints") as validate:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        validate.assert_called_once()
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "copyto", "b.ini", "a.ini"])
        self.assertIn("appdata/config", self.output.getvalue())
        self.assertNotIn("appdata/config/config", self.output.getvalue())

    def test_file_validation_failure_never_executes_in_auto_mode(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file",
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}]}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints", side_effect=ValueError("source is a directory")):
            self.assertEqual(app.main(), 1, self.output.getvalue())
        self.run.assert_not_called()
        self.assertIn("source is a directory", self.output.getvalue())

    def test_file_cli_print_only_does_not_probe_endpoints(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file",
                  "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}]}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "pull-copy-file", "--dry-run"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_validate_file_endpoints") as validate:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        validate.assert_not_called()
        self.run.assert_not_called()
        self.assertIn("copyto b.ini a.ini", self.output.getvalue())

    def test_time_display_can_be_disabled_without_disabling_file_safety_or_move_warning(self) -> None:
        schema = {"settings": {"default": {"do-not-check-modified-time": True}}, "tasks": {"test": [
            {"name": "config", "path-type": "file", "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}]},
        ]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_display_path_mtimes") as display, patch.object(backend, "_validate_file_endpoints") as validate:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        display.assert_not_called()
        validate.assert_called_once()
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][1], "moveto")
        self.assertNotIn("--ignore-times", self.run.call_args.args[0])
        self.assertIn("time check skipped by configuration", self.output.getvalue())
        self.assertIn("will delete local source files", self.output.getvalue())

    def test_false_subtask_flag_reenables_an_inherited_disabled_time_check(self) -> None:
        schema = {"settings": {"default": {"do-not-check-modified-time": True}}, "tasks": {"test": [
            {"name": "config", "sub-tasks": [
                {"name": "all", "paths": [{"path1": "local", "path2": "remote"}], "do-not-check-modified-time": False},
            ]},
        ]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_display_path_mtimes", return_value=[]) as display:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        display.assert_called_once()
        self.assertNotIn("time check skipped", self.output.getvalue())

    def test_disabling_time_display_does_not_disable_directory_precheck(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}],
                  "do-not-check-modified-time": True, "check-before-sync": True}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(terminal, "_display_path_mtimes") as display:
            self.assertEqual(app.main(), 0, self.output.getvalue())
        display.assert_not_called()
        self.assertEqual([call.args[0][1] for call in self.run.call_args_list], ["check", "copy"])

    def test_first_upload_to_missing_file_still_executes_but_missing_source_does_not(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file", "sub-tasks": [{"name": "all", "paths": [{"path1": "a.ini", "path2": "b.ini"}]}]}]}}
        present = models.PathInfo(models.PathState.PRESENT, models.PathType.FILE)
        missing = models.PathInfo(models.PathState.MISSING)
        for source_missing, observations, code in (
            (False, [present, missing, present, missing], 0),
            (True, [missing, present, missing], 1),
        ):
            with self.subTest(source_missing=source_missing):
                self.run.reset_mock()
                self.output.seek(0)
                self.output.truncate(0)
                with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(backend, "_get_local_path_info", side_effect=observations), patch.object(os.path, "islink", return_value=False):
                    self.assertEqual(app.main(), code, self.output.getvalue())
                if source_missing:
                    self.run.assert_not_called()
                    self.assertIn("local source is missing", self.output.getvalue())
                    self.assertNotIn("First upload:", self.output.getvalue())
                else:
                    self.run.assert_called_once()
                    self.assertIn("First upload:", self.output.getvalue())
                    self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "copyto", "a.ini", "b.ini"])

    def test_q_from_each_menu_never_executes_and_preserves_task_context(self) -> None:
        cases = (
            ("task", False, ["Q"]),
            ("subtask", False, ["0", "Q", "Q"]),
            ("host", False, ["0", "Q", "Q"]),
            ("operation", False, ["0", "Q", "Q"]),
            ("comparison", False, ["0", "pull", "Q", "Q"]),
            ("subtask", True, ["Q"]),
            ("comparison", True, ["pull", "Q"]),
        )
        for menu, cli_task, answers in cases:
            with self.subTest(menu=menu, cli_task=cli_task), contextlib.ExitStack() as stack:
                self.output.seek(0)
                self.output.truncate(0)
                subtasks = [
                    {"name": "all", "paths": [{"path1": "local", "path2": "primary:/files"}]},
                ]
                task: dict[str, object] = {"name": "demo", "sub-tasks": subtasks}
                if menu == "subtask":
                    subtasks.append({"name": "second", "paths": [{"path1": "local", "path2": "primary:/files"}]})
                if menu == "host":
                    task["alternative-remote-host"] = ["backup"]
                schema = {"tasks": {"test": [task]}}
                argv = ["rclone-sync.py", "--task", "test/demo"] if cli_task else ["rclone-sync.py"]
                stack.enter_context(patch.object(sys, "argv", argv))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch.object(utility.Input, "resolve_input_path", return_value="schema.yaml"))
                prompt: MagicMock = stack.enter_context(patch("builtins.input", side_effect=answers))
                self.assertEqual(app.main(), 0, self.output.getvalue())
                self.assertEqual(prompt.call_count, len(answers))
                output = self.output.getvalue()
                if menu == "host":
                    self.assertIn(f"{utility.FLYellow}test/demo/all{utility.CRst}:", output)
                elif menu == "subtask":
                    self.assertIn(f"Multiple sub-tasks of task {utility.FLYellow}test/demo{utility.CRst}", output)
                    self.assertTrue(any("Select sub-task for test/demo" in call.args[0] for call in prompt.call_args_list))
                    self.assertNotIn("test/demo/all", output)
                elif menu in ("operation", "comparison"):
                    self.assertIn(f"Task:{utility.CRst} {utility.FLCyan}test/demo/all{utility.CRst}", output)
                if not cli_task:
                    self.assertIn("Select task", prompt.call_args.args[0])
        self.run.assert_not_called()
        self.repair.assert_not_called()

    def test_task_labels_keep_group_prefix_and_handle_ungrouped_tasks(self) -> None:
        for group in ("appdata", "developer", models.UNGROUPED_KEY):
            with self.subTest(group=group), contextlib.ExitStack() as stack:
                self.output.seek(0)
                self.output.truncate(0)
                label = "demo" if group == models.UNGROUPED_KEY else f"{group}/demo"
                schema = {"tasks": {group: [{"name": "demo", "sub-tasks": [
                    {"name": "all", "paths": [{"path1": "local", "path2": "remote"}]},
                ]}]}}
                stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", label, "--verbose"]))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch("builtins.input", side_effect=["check", "", "q"]))
                self.assertEqual(app.main(), 0, self.output.getvalue())
                output = self.output.getvalue()
                self.assertIn(f"Selected: {label}{utility.CRst}", output)
                self.assertEqual(output.count(f"Task:{utility.CRst} {utility.FLCyan}{label}/all{utility.CRst}"), 2)
                self.assertIn(f"{utility.FLCyan}{label}/all{utility.CRst}", output.split("Rclone command:")[1])
                self.assertNotIn("None/demo", output)
                self.assertNotIn(f"{models.UNGROUPED_KEY}/demo", output)
        self.run.assert_not_called()

    def test_confirmation_names_action_and_adds_directional_move_warning(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [
            {"name": "all", "paths": [{"path1": "local", "path2": "remote"}]},
        ]}]}}
        older = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        newer = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
        for action, (mode, direction) in models.ACTION_COMMANDS.items():
            with self.subTest(action=action), contextlib.ExitStack() as stack:
                self.output.seek(0)
                self.output.truncate(0)
                self.run.reset_mock()
                answers = iter(["", "   ", "invalid", "d", "q"])
                schema["tasks"]["test"][0]["path-type"] = "file" if action in models.FILE_ACTIONS else "directory"

                def confirm(prompt: str) -> str:
                    print(prompt)
                    return next(answers)

                stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/demo"]))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch.object(terminal, "_select_action", return_value=action))
                stack.enter_context(patch.object(terminal, "_select_comparison_mode", return_value=models.ComparisonMode.CHECKSUM))
                stack.enter_context(patch.object(backend, "_validate_file_endpoints"))
                timestamps = [newer, older] if direction == "pull" else [older, newer]
                stack.enter_context(patch.object(backend, "_get_local_path_info", side_effect=[
                    models.PathInfo(models.PathState.PRESENT, mtime=timestamp) for timestamp in timestamps
                ]))
                prompt: MagicMock = stack.enter_context(patch("builtins.input", side_effect=confirm))
                self.assertEqual(app.main(), 0, self.output.getvalue())

                self.assertEqual(prompt.call_count, 5)
                self.assertTrue(all(call == prompt.call_args_list[0] for call in prompt.call_args_list))
                self.assertIn(
                    f"Execute{utility.CRst} {utility.FLCyan}{action.value}{utility.CRst}{utility.FLYellow}?",
                    prompt.call_args.args[0],
                )
                output = self.output.getvalue()
                is_file = action in models.FILE_ACTIONS
                self.assertEqual(output.count("WARNING:"), 5 * (int(direction is not None and is_file) + int(mode == "move")))
                self.assertEqual(output.count("NOTE: Directory timestamps"), 5 * int(direction is not None and not is_file))
                if direction is not None and not is_file:
                    self.assertIn("not guaranteed by directory times", output)
                    self.assertNotIn("would overwrite newer", output)
                screens = output.split("Rclone command:")[1:]
                self.assertEqual(len(screens), 5)
                for screen in screens:
                    self.assertIn(f"Task:{utility.CRst} {utility.FLCyan}test/demo/all{utility.CRst}", screen)
                    self.assertLess(screen.index("Task:"), screen.index("Execute"))
                    self.assertLess(screen.index("action:"), screen.index("Execute"))
                    self.assertLess(screen.index("comparison:"), screen.index("Execute"))
                self.assertEqual(output.count("Enter y, n, d, or q."), 1)
                if mode == "move":
                    source = "local" if direction == "push" else "remote"
                    self.assertIn(f"will delete {source} source files", output)
                    self.assertIn("after successful transfer or an identical destination match!", output)
                    time_note = "would overwrite newer" if is_file else "NOTE: Directory timestamps"
                    self.assertLess(output.index(time_note), output.index("will delete"))
                    warning_lines = [i for i, line in enumerate(output.splitlines()) if "WARNING:" in line or "NOTE: Directory timestamps" in line]
                    for i in range(0, len(warning_lines), 2):
                        self.assertEqual(warning_lines[i + 1], warning_lines[i] + 1)
                else:
                    self.assertNotIn("will delete", output)
                self.run.assert_called_once()
                self.assertIn("--dry-run", self.run.call_args.args[0])
        self.repair.assert_not_called()



if __name__ == "__main__":
    unittest.main()
