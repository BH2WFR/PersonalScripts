"""Focused rclone regression tests: commands.

Run: conda run -n base python -m unittest discover -s test -p "test_rclone*.py".
All sync/network subprocesses are mocked.
"""

import contextlib
import datetime
import io
import os
import subprocess
import stat
import unittest
from unittest.mock import patch
import yaml
from _rclone_test_support import ROOT, backend, endpoint_ops, execution, models, schema_ops, terminal, utility


class ConfigFileTests(unittest.TestCase):
    """Check path-only queries and failures without reading or opening real files."""

    def test_path_query_uses_rclone_and_rejects_failed_or_malformed_output(self) -> None:
        path = str(ROOT / "tmp" / "rclone config.conf")
        with patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess(
            [], 0, f"Configuration file is stored at:\n{path}\n", "",
        )) as run:
            self.assertEqual(backend._get_config_file("rclone"), path)
        run.assert_called_once_with(
            ["rclone", "config", "file", "--ask-password=false"],
            capture_output=True, timeout=10,
        )
        for code, output in ((1, path), (0, ""), (0, "Unexpected output")):
            with self.subTest(code=code, output=output), patch.object(
                backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], code, output, ""),
            ), self.assertRaises(ValueError):
                backend._get_config_file("rclone")

    def test_open_missing_file_and_query_failures_return_without_opening(self) -> None:
        path = str(ROOT / "tmp" / "missing config.conf")
        failures = [OSError("unavailable"), ValueError("bad output"),
                    subprocess.TimeoutExpired(["rclone"], 10), backend.OperationCancelled()]
        with patch.object(utility.System, "open_with_default_app") as open_file:
            with patch.object(backend, "_get_config_file", return_value=path), patch.object(os.path, "isfile", return_value=False), contextlib.redirect_stdout(io.StringIO()) as output:
                terminal._config_file_action("rclone", open_file=True)
                self.assertIn("does not exist", output.getvalue())
            for failure in failures:
                with self.subTest(failure=type(failure).__name__), patch.object(backend, "_get_config_file", side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
                    terminal._config_file_action("rclone", open_file=True)
            open_file.assert_not_called()


class ActionTests(unittest.TestCase):
    """Check runtime overrides, menu ordering, permissions, and comparisons."""

    def test_mode_orders_matching_actions_first(self) -> None:
        prefixes = {
            "sync": ["push", "pull"], "copy": ["push-copy", "pull-copy"],
            "move": ["push-move", "pull-move"], "bisync": ["bisync"], "check": ["check"],
        }
        for mode, expected in prefixes.items():
            with self.subTest(mode=mode):
                actions = backend._available_actions(schema_ops.SyncTask(preferred_mode=mode))
                self.assertEqual([action.value for action in actions[:len(expected)]], expected)
                self.assertEqual(len(actions), 8)

    def test_missing_or_empty_mode_highlights_push_pull_in_standard_order(self) -> None:
        for raw in ("name: test", "name: test\npreferred-mode:", 'name: test\npreferred-mode: ""',
                    'name: test\npreferred-mode: "   "'):
            with self.subTest(raw=raw):
                config = yaml.safe_load(raw)
                config["sub-tasks"] = [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}]
                self.assertEqual(schema_ops._validate_schema({"tasks": {"test": [config]}}), [])
                task = schema_ops.SyncTask.from_dict(config)
                self.assertEqual(task.preferred_mode, "")
                self.assertEqual(task.mode, "")
                with patch.object(utility.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
                    terminal._select_action(task, None, None)
                options = select.call_args.args[0]
                self.assertEqual([option.value for option in options[:-1]], list(models.PATH_ACTIONS[models.PathType.DIRECTORY]))
                self.assertEqual(options[-1].keys, ["Q"])
                for option in options[:-1]:
                    expected = utility.FLYellow if option.value in (models.SyncAction.PUSH, models.SyncAction.PULL) else utility.FLCyan
                    self.assertEqual(option.desc_color, expected)
                    self.assertNotIn("removes source files", option.description)

    def test_only_preferred_mode_is_yellow(self) -> None:
        for mode in ("sync", "copy", "move", "bisync", "check"):
            with self.subTest(mode=mode):
                task = schema_ops.SyncTask.from_dict({"name": "test", "preferred-mode": mode})
                with patch.object(utility.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
                    terminal._select_action(task, None, None)
                options = select.call_args.args[0]
                self.assertEqual(options[0].desc_color, utility.FLYellow)
                for option in options[:-1]:
                    expected = utility.FLYellow if models.ACTION_COMMANDS[option.value][0] == mode else utility.FLCyan
                    self.assertEqual(option.desc_color, expected)

    def test_empty_mode_clears_inherited_preference(self) -> None:
        settings = {"default": {"preferred-mode": "move"}, "copies": {"preferred-mode": "copy"}}
        inherited = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["copies"]})
        self.assertEqual(inherited.preferred_mode, "copy")
        self.assertEqual(backend._available_actions(inherited)[0], models.SyncAction.PUSH_COPY)
        for empty in (None, "", "   "):
            with self.subTest(empty=empty):
                cleared = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["copies"], "preferred-mode": empty})
                self.assertEqual(cleared.preferred_mode, "")
                self.assertEqual(backend._available_actions(cleared), list(models.PATH_ACTIONS[models.PathType.DIRECTORY]))
                sub = schema_ops.SyncTask.from_dict({"name": "sub", "preferred-mode": empty})
                self.assertEqual(inherited.merge(sub.resolve_profiles(settings)).preferred_mode, "")

    def test_unset_mode_preserves_direction_only_cli_sync(self) -> None:
        task = schema_ops.SyncTask(local_path="local", remote_path="remote:")
        self.assertEqual(terminal._select_action(task, None, "pull"), models.SyncAction.PULL)
        self.assertEqual(backend.to_command(task, 'rclone', direction='pull')[:4], ["rclone", "sync", "remote:", "local"])
        self.assertEqual(task.mode, "")

    def test_allowlist_hides_every_action_not_explicitly_granted(self) -> None:
        for expected, forbidden in (
            (["push", "push-copy", "push-move", "check"], models.SyncAction.PULL),
            (["pull", "pull-copy", "pull-move", "check"], models.SyncAction.PUSH),
        ):
            with self.subTest(expected=expected):
                config = {"name": "test", "allow-actions": expected,
                          "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}]}
                self.assertEqual(schema_ops._validate_schema({"tasks": {"test": [config]}}), [])
                task = schema_ops.SyncTask.from_dict(config)
                self.assertEqual([action.value for action in backend._available_actions(task)], expected)
                for action in (forbidden, models.SyncAction.BISYNC):
                    with self.assertRaises(ValueError):
                        terminal._select_action(task, action, None)
                    with self.assertRaises(ValueError):
                        backend._task_for_action(task, action)
                allowed = schema_ops.SyncTask.from_dict({"name": "test"})
                self.assertEqual(backend._available_actions(allowed), list(models.PATH_ACTIONS[models.PathType.DIRECTORY]))

    def test_allowlists_replace_instead_of_appending_and_empty_disables_all(self) -> None:
        settings = {"oneway": {"allow-actions": ["pull-copy", "check"], "exclude": ["*.tmp"]}}
        task = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["oneway"]})
        self.assertNotIn(models.SyncAction.PUSH_COPY, backend._available_actions(task))
        sub = schema_ops.SyncTask.from_dict({"name": "sub", "allow-actions": ["push-copy"], "exclude": ["*.tmp", "*.bak"]})
        merged = task.merge(sub)
        self.assertEqual(backend._available_actions(merged), [models.SyncAction.PUSH_COPY])
        self.assertEqual(merged.exclude, ["*.tmp", "*.bak"])
        empty = task.merge(schema_ops.SyncTask.from_dict({"name": "sub", "allow-actions": []}))
        self.assertEqual(backend._available_actions(empty), [])
        self.assertEqual(backend._available_actions(task.merge(schema_ops.SyncTask(name="sub"))), backend._available_actions(task))
        with self.assertRaises(ValueError):
            backend.to_command(empty, 'rclone')

    def test_menu_does_not_select_first_action_on_enter(self) -> None:
        task = schema_ops.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote")
        with patch.object(utility.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(terminal._select_action(task, None, None))
        self.assertNotIn("default_key", select.call_args.kwargs)
        self.assertTrue(select.call_args.kwargs["required"])
        self.assertEqual(select.call_args.args[0][0].value, models.SyncAction.PUSH_MOVE)
        for option in select.call_args.args[0][:-1]:
            self.assertIn(f"{utility.FLBlue}local{utility.CRst}", option.description)
            self.assertIn(f"{utility.FLGreen}remote{utility.CRst}", option.description)

    def test_all_clears_inherited_restrictions_for_each_path_type(self) -> None:
        settings = {"default": {"allow-actions": ["check"]}, "unrestricted": {"allow-actions": "all"}}
        parent = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertEqual(backend._available_actions(parent), [models.SyncAction.CHECK])
        for path_type in models.PathType:
            with self.subTest(path_type=path_type):
                raw = {"name": "sub", "path-type": path_type.value, "allow-actions": "all"}
                task = parent.merge(schema_ops.SyncTask.from_dict(raw).resolve_profiles(settings))
                self.assertEqual(task.validate(), [])
                self.assertEqual(backend._available_actions(task), list(models.PATH_ACTIONS[path_type]))
                restored = schema_ops.SyncTask.from_inheritance_chain(settings, {
                    "name": "test", "path-type": path_type.value, "inherit": ["unrestricted"],
                })
                self.assertEqual(backend._available_actions(restored), backend._available_actions(task))

    def test_null_and_all_clear_restrictions_but_omission_inherits(self) -> None:
        for raw_value in ("null", "~", "", "all", '"all"'):
            for scope in ("profile", "task", "subtask"):
                with self.subTest(raw_value=raw_value, scope=scope):
                    fields = yaml.safe_load(f"allow-actions: {raw_value}")
                    settings = {"default": {"allow-actions": ["check"]}, "override": {}}
                    raw = {"name": "demo", "inherit": ["override"]}
                    sub = {"name": "sub", "paths": [{"path1": "local", "path2": "remote"}]}
                    {"profile": settings["override"], "task": raw, "subtask": sub}[scope].update(fields)
                    for path_type in models.PathType:
                        raw["path-type"] = path_type.value
                        self.assertEqual(schema_ops._validate_schema({"settings": settings, "tasks": {"test": [{**raw, "sub-tasks": [sub]}]}}), [])
                        parent = schema_ops.SyncTask.from_inheritance_chain(settings, raw)
                        result = parent.merge(schema_ops.SyncTask.from_dict(sub))
                        self.assertIsNone(result.allow_actions)
                        self.assertEqual(backend._available_actions(result), list(models.PATH_ACTIONS[path_type]))
        restricted = schema_ops.SyncTask.from_dict({"allow-actions": ["check"]})
        self.assertEqual(restricted.merge(schema_ops.SyncTask.from_dict({})).allow_actions, [models.SyncAction.CHECK])

    def test_preferred_mode_keeps_cli_direction_and_does_not_replace_action(self) -> None:
        for path_type in models.PathType:
            for preferred in ("copy", "move"):
                with self.subTest(path_type=path_type, preferred=preferred):
                    task = endpoint_ops.path_tasks(schema_ops.SyncTask.from_dict({'name': 'test', 'preferred-mode': preferred, 'path-type': path_type.value, 'paths': [{'path1': 'local', 'path2': 'remote:'}]}))[0]
                    action = terminal._select_action(task, None, "pull")
                    self.assertEqual(models.ACTION_COMMANDS[action], (preferred, "pull"))
                    expected = f"{preferred}to" if path_type == models.PathType.FILE else preferred
                    self.assertEqual(backend.to_command(task, 'rclone', direction='pull')[:4], ["rclone", expected, "remote:", "local"])
                    override = models.SyncAction.PUSH_COPY_FILE if path_type == models.PathType.FILE else models.SyncAction.PUSH
                    selected = backend._task_for_action(task, override)
                    self.assertEqual(selected.preferred_mode, preferred)
                    self.assertEqual(selected.mode, models.ACTION_COMMANDS[override][0])
                    self.assertEqual(task.mode, "")

    def test_deletion_limits_use_the_selected_action_and_inherit_independently(self) -> None:
        settings = {"default": {"max-delete-count": 7, "max-delete-percent": 20}}
        parent = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "preferred-mode": "bisync"})
        task = parent.merge(schema_ops.SyncTask.from_dict({"name": "sub", "max-delete-count": 12}))
        self.assertEqual((task.max_delete_count, task.max_delete_percent), (12, 20))
        for action in models.PATH_ACTIONS[models.PathType.DIRECTORY]:
            with self.subTest(action=action):
                selected = backend._task_for_action(task, action)
                mode, direction = models.ACTION_COMMANDS[action]
                command = backend.to_command(selected, 'rclone', direction=direction or 'push')
                if mode in {"sync", "bisync"}:
                    limit = command[command.index("--max-delete") + 1]
                    self.assertEqual(limit, "12" if mode == "sync" else "20")
                else:
                    self.assertNotIn("--max-delete", command)
        for field, mode in (("max_delete_count", "bisync"), ("max_delete_percent", "sync")):
            with self.subTest(field=field, mode=mode):
                self.assertNotIn("--max-delete", backend.to_command(schema_ops.SyncTask(mode=mode, **{field: 5}), 'rclone'))

    def test_deletion_limit_validation_and_removed_yaml_names(self) -> None:
        for fields in (
            {"max-delete-count": -2}, {"max-delete-count": True}, {"max-delete-count": "5"},
            {"max-delete-percent": -1}, {"max-delete-percent": 101}, {"max-delete-percent": 0.5},
            {"max-delete-percent": False}, {"mode": "copy"}, {"max-delete": 50},
        ):
            with self.subTest(fields=fields):
                self.assertTrue(schema_ops._validate_schema({"tasks": {"test": [{"name": "task", **fields}]}}))
        for count, percent in ((-1, 100), (0, 0), (12, 50)):
            fields = {"name": "task", "max-delete-count": count, "max-delete-percent": percent,
                      "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}]}
            self.assertEqual(schema_ops._validate_schema({"tasks": {"test": [fields]}}), [])
        self.assertNotIn("--max-delete", backend.to_command(schema_ops.SyncTask(), 'rclone'))

    def test_operation_menu_retries_empty_input_and_q_goes_back(self) -> None:
        task = schema_ops.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote")
        for key, expected in (("q", None), ("pull", models.SyncAction.PULL)):
            with self.subTest(key=key), patch("builtins.input", side_effect=["", "   ", key]) as prompt:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(terminal._select_action(task, None, None), expected)
                self.assertEqual(prompt.call_count, 3)
                self.assertTrue(all(call == prompt.call_args_list[0] for call in prompt.call_args_list))
                self.assertEqual(output.getvalue().count("Back to task menu"), 3)
                self.assertNotIn("removes source files", output.getvalue())

    def test_host_menu_shows_full_task_name_and_q_cancels(self) -> None:
        for answers, accepted, expected_path in (
            (["q"], False, "primary:/files"),
            (["Q"], False, "primary:/files"),
            (["invalid", "Q"], False, "primary:/files"),
            ([""], True, "primary:/files"),
            (["1"], True, "backup:/files"),
        ):
            with self.subTest(answers=answers), patch("builtins.input", side_effect=answers):
                task = schema_ops.SyncTask(name="test/demo/all", remote_path="primary:/files", alternative_remote_hosts=["backup"])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(terminal._interactive_host_swap(task, False), accepted)
                self.assertEqual(task.remote_path, expected_path)
                self.assertIn(f"remote-path{utility.CRst} {utility.FLYellow}test/demo/all{utility.CRst}:", output.getvalue())
                self.assertIn(f"[{utility.CRst}Q{utility.FGray}]", output.getvalue())

    def test_host_selection_skips_auto_local_and_missing_alternatives(self) -> None:
        for path, alternatives, auto in (
            ("primary:/files", ["backup"], True),
            ("local", ["backup"], False),
            ("primary:/files", [], False),
        ):
            with self.subTest(path=path, auto=auto), patch("builtins.input") as prompt:
                task = schema_ops.SyncTask(remote_path=path, alternative_remote_hosts=alternatives)
                self.assertTrue(terminal._interactive_host_swap(task, auto))
                self.assertEqual(task.remote_path, path)
                prompt.assert_not_called()

    def test_comparison_menu_q_cancels_but_enter_keeps_default(self) -> None:
        for mode in models.VALID_MODES:
            for key in ("Q", ""):
                with self.subTest(mode=mode, key=key), patch("builtins.input", return_value=key):
                    task = schema_ops.SyncTask(mode=mode)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        selected = terminal._select_comparison_mode(task, None, True)
                    expected = models.ComparisonMode.CHECKSUM if mode == "check" else models.ComparisonMode.SIZE_AND_TIME
                    self.assertEqual(selected, None if key == "Q" else expected)
                    self.assertIn("Back to task menu", output.getvalue().splitlines()[-1])

    def test_actions_override_yaml_mode_and_reverse_pull_paths(self) -> None:
        original = schema_ops.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote:")
        for name, mode, source, destination in (
            ("push", "sync", "local", "remote:"), ("pull", "sync", "remote:", "local"),
            ("push-copy", "copy", "local", "remote:"), ("pull-copy", "copy", "remote:", "local"),
            ("push-move", "move", "local", "remote:"), ("pull-move", "move", "remote:", "local"),
            ("bisync", "bisync", "local", "remote:"), ("check", "check", "local", "remote:"),
        ):
            with self.subTest(action=name):
                action = models.SyncAction(name)
                task = backend._task_for_action(original, action)
                _, direction = models.ACTION_COMMANDS[action]
                cmd = backend.to_command(task, 'rclone', direction=direction or 'push', comparison=models.ComparisonMode.SIZE_ONLY)
                self.assertEqual(cmd[:4], ["rclone", mode, source, destination])
                self.assertEqual(original.preferred_mode, "move")
                self.assertEqual(original.mode, "")

    def test_permissions_include_check_and_do_not_expand_direction_wildcards(self) -> None:
        task = schema_ops.SyncTask.from_dict({"name": "test", "allow-actions": ["pull", "pull-copy", "pull-move", "check"]})
        self.assertEqual([action.value for action in backend._available_actions(task)], ["pull", "pull-copy", "pull-move", "check"])
        with self.assertRaises(ValueError):
            backend._task_for_action(task, models.SyncAction.PUSH_MOVE)
        task.allow_actions = [models.SyncAction.CHECK]
        self.assertEqual(task.validate(), [])
        self.assertEqual(backend._available_actions(task), [models.SyncAction.CHECK])
        task.allow_actions = [models.SyncAction.PUSH]
        self.assertEqual(backend._available_actions(task), [models.SyncAction.PUSH])
        with self.assertRaises(ValueError):
            terminal._select_action(task, models.SyncAction.CHECK, None)

    def test_explicit_comparison_removes_conflicting_configured_flags(self) -> None:
        for mode, comparison, expected in (
            ("copy", "size_and_time", []), ("move", "force", ["--ignore-times"]),
            ("sync", "size_only", ["--size-only"]), ("copy", "checksum", ["--checksum"]),
            ("check", "checksum", []), ("check", "size_only", ["--size-only"]),
            ("bisync", "size_and_time", ["--compare", "size,modtime"]),
            ("bisync", "size_only", ["--compare", "size"]),
            ("bisync", "checksum", ["--compare", "size,checksum"]),
        ):
            with self.subTest(mode=mode, comparison=comparison):
                task = schema_ops.SyncTask(mode=mode, progress=False, ignore_times=True, size_only=True, checksum=True,
                                       additional_args=["-I=true", "-c", "--size-only=false", "--compare", "size"])
                self.assertEqual(backend.to_command(task, 'rclone', comparison=models.ComparisonMode(comparison))[4:], expected)
        for mode, comparison in (("check", "force"), ("check", "size_and_time"), ("bisync", "force")):
            with self.subTest(mode=mode, comparison=comparison), self.assertRaises(ValueError):
                backend.to_command(schema_ops.SyncTask(mode=mode), 'rclone', comparison=models.ComparisonMode(comparison))

    def test_mode_specific_arguments_and_one_way_precheck(self) -> None:
        task = schema_ops.SyncTask(mode="copy", delete_excluded=True, max_delete_count=5,
                               additional_args=["--workdir", "state", "--resync", "--max-delete=1", "--delete-excluded", "--transfers=8"])
        cmd = backend.to_command(task, 'rclone', comparison=models.ComparisonMode.SIZE_ONLY)
        self.assertNotIn("--delete-excluded", cmd)
        self.assertNotIn("--resync", cmd)
        self.assertNotIn("state", cmd)
        self.assertNotIn("--max-delete=1", cmd)
        self.assertIn("--transfers=8", cmd)
        self.assertIn("--one-way", backend.to_check_command(task, 'rclone'))
        bisync = schema_ops.SyncTask(mode="bisync")
        self.assertNotIn("--resync", backend.to_command(bisync, 'rclone', comparison=models.ComparisonMode.SIZE_ONLY))
        self.assertIn("--resync", backend.to_command(bisync, 'rclone', comparison=models.ComparisonMode.SIZE_ONLY, resync=True))

    def test_cli_conflicts_and_configured_comparison_default(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (["--action", "push-copy", "--pull"], ["--push", "--direction", "pull"],
                         ["--action", "check", "--resync"], ["--comparison", "default"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                    terminal._parse_args(argv)
                self.assertEqual(raised.exception.code, 2)
        task = schema_ops.SyncTask(size_only=True)
        with patch.object(utility.Menu, "select", return_value=models.ComparisonMode.SIZE_AND_TIME) as select, contextlib.redirect_stdout(io.StringIO()):
            selected = terminal._select_comparison_mode(task, None, True)
        self.assertEqual(select.call_args.kwargs["default_key"], "1")
        self.assertEqual(selected, models.ComparisonMode.SIZE_AND_TIME)
        self.assertNotIn("--size-only", backend.to_command(task, 'rclone', comparison=selected))


class FileTaskTests(unittest.TestCase):
    """Verify exact-file actions and fail-closed metadata guards without rclone."""

    def test_file_type_inherits_and_can_be_overridden(self) -> None:
        settings = {
            "file": {"path-type": "file", "allow-actions": ["push-copy-file"]},
            "restore": {"allow-actions": ["pull-copy-file"]},
        }
        task = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "config", "inherit": ["file", "restore"]})
        self.assertEqual(task.path_type, models.PathType.FILE)
        self.assertEqual(backend._available_actions(task), [models.SyncAction.PULL_COPY_FILE])
        sub = schema_ops.SyncTask.from_dict({"name": "dir", "path-type": "directory", "allow-actions": ["check"]})
        self.assertEqual(backend._available_actions(task.merge(sub)), [models.SyncAction.CHECK])

    def test_schema_reference_uses_the_current_fields_and_validates(self) -> None:
        with (ROOT / "tools/network/rclone-sync-schema-sample.yaml").open(encoding="utf-8") as stream:
            schema = schema_ops._load_schema(stream)
        self.assertEqual(schema_ops._validate_schema(schema), [])

    def test_invalid_values_and_old_permission_fields_are_rejected(self) -> None:
        cases = [
            {"path-type": value} for value in (None, "directiry", "dir", "symlink", True, [])
        ] + [
            {"allow-actions": value} for value in ("None", "push", True, 1, {}, [None], [True], ["all"],
                                                  ["push", "all"], ["check-file"], ["push-copyto"])
        ] + [
            {key: True} for key in ("allow-push", "allow-pull", "push-only", "pull-only", "is-file-not-directory")
        ]
        for fields in cases:
            for scope in ("task", "profile", "subtask"):
                with self.subTest(fields=fields, scope=scope):
                    profile: dict[str, object] = {}
                    sub: dict[str, object] = {"name": "all", "paths": [{"path1": "local", "path2": "remote"}]}
                    task: dict[str, object] = {"name": "config", "inherit": ["profile"], "sub-tasks": [sub]}
                    {"task": task, "profile": profile, "subtask": sub}[scope].update(fields)
                    self.assertTrue(schema_ops._validate_schema({"settings": {"profile": profile}, "tasks": {"test": [task]}}))

    def test_file_capabilities_intersect_permissions_and_cli_uses_file_names(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, local_path="a.ini", remote_path="backup:b.ini")
        self.assertEqual(backend._available_actions(task), list(models.FILE_ACTIONS))
        self.assertEqual(terminal._select_action(task, None, "pull"), models.SyncAction.PULL_COPY_FILE)
        self.assertEqual(backend.to_command(task, 'rclone', direction='pull')[:4], ["rclone", "copyto", "backup:b.ini", "a.ini"])
        for action in models.PATH_ACTIONS[models.PathType.DIRECTORY]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                terminal._select_action(task, action, None)
        task.allow_actions = [models.SyncAction.PUSH, models.SyncAction.PULL_COPY_FILE]
        self.assertEqual(backend._available_actions(task), [models.SyncAction.PULL_COPY_FILE])
        with self.assertRaises(ValueError):
            backend.to_command(task, 'rclone', direction='push')
        for action in models.FILE_ACTIONS:
            self.assertEqual(terminal._parse_args(["--action", action.value]).action, action.value)

    def test_file_commands_reverse_exact_paths_and_support_all_comparisons(self) -> None:
        original = schema_ops.SyncTask(path_type=models.PathType.FILE, local_path="local/a.ini", remote_path="backup:dir/b.ini")
        for action in models.FILE_ACTIONS:
            mode, direction = models.ACTION_COMMANDS[action]
            task = backend._task_for_action(original, action)
            for comparison in models.ComparisonMode:
                with self.subTest(action=action, comparison=comparison):
                    cmd = backend.to_command(task, 'rclone', direction=direction, comparison=comparison, dry_run=True)
                    paths = ["local/a.ini", "backup:dir/b.ini"]
                    if direction == "pull":
                        paths.reverse()
                    self.assertEqual(cmd[:4], ["rclone", f"{mode}to", *paths])
                    self.assertIn("--dry-run", cmd)
                    expected = {"force": "--ignore-times", "checksum": "--checksum", "size_only": "--size-only"}.get(comparison.value)
                    for flag in ("--ignore-times", "--checksum", "--size-only"):
                        self.assertEqual(flag in cmd, flag == expected)
        self.assertEqual(original.mode, "")

    def test_file_commands_ignore_inherited_excludes_without_mutating_configuration(self) -> None:
        settings = {"default": {"exclude": ["*.bak", ".DS_Store"], "ignore-case": True,
                                "transfer": 24, "s3-no-check-bucket": True, "copy-links": True}}
        parent = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "config"})
        file_task = endpoint_ops.path_tasks(parent.merge(schema_ops.SyncTask.from_dict({'name': 'file', 'path-type': 'file', 'paths': [{'path1': 'a.ini', 'path2': 'remote:b.ini'}]})))[0]
        for action in models.FILE_ACTIONS:
            task = backend._task_for_action(file_task, action)
            _, direction = models.ACTION_COMMANDS[action]
            for comparison in models.ComparisonMode:
                with self.subTest(action=action, comparison=comparison):
                    cmd = backend.to_command(task, 'rclone', direction=direction, comparison=comparison)
                    self.assertNotIn("--exclude", cmd)
                    self.assertNotIn("--ignore-case", cmd)
                    self.assertIn("--copy-links", cmd)
                    self.assertIn("--s3-no-check-bucket", cmd)
                    self.assertEqual(cmd[cmd.index("--transfers") + 1], "24")
                    self.assertEqual(backend.ignored_file_filter_flags(task), ["--exclude", "--ignore-case"])
        self.assertEqual(file_task.exclude, ["*.bak", ".DS_Store"])
        self.assertEqual(parent.exclude, file_task.exclude)
        self.assertEqual(backend.ignored_file_filter_flags(parent), [])
        for action in models.PATH_ACTIONS[models.PathType.DIRECTORY]:
            task = backend._task_for_action(parent, action)
            _, direction = models.ACTION_COMMANDS[action]
            cmd = backend.to_command(task, 'rclone', direction=direction or 'push')
            self.assertEqual(cmd.count("--exclude"), 2)
            self.assertIn("--ignore-case", cmd)
        self.assertIn("--exclude", backend.to_check_command(parent, 'rclone'))

    def test_file_extra_filters_and_their_values_are_ignored(self) -> None:
        for flag in sorted(models.METADATA_FILTER_FLAGS | {"--filters-file"}):
            for args in ([flag, "pattern"], [f"{flag}=pattern"]):
                for mode in ("copy", "move"):
                    with self.subTest(flag=flag, args=args, mode=mode):
                        extras = ["--config", "test.conf", *args, "--s3-no-check-bucket", "--bwlimit=1M"]
                        task = schema_ops.SyncTask(path_type=models.PathType.FILE, mode=mode, additional_args=extras)
                        cmd = backend.to_command(task, 'rclone')
                        self.assertEqual(cmd[-4:], ["--config", "test.conf", "--s3-no-check-bucket", "--bwlimit=1M"])
                        self.assertNotIn("pattern", cmd)
                        self.assertNotIn(f"{flag}=pattern", cmd)
                        self.assertEqual(backend.ignored_file_filter_flags(task), [flag])
                        self.assertEqual(task.additional_args, extras)

    def test_file_short_filters_booleans_and_warnings_are_deduplicated(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, exclude=["*.bak"], ignore_case=True,
                               additional_args=["--exclude=*.bak", "-f-*.tmp", "-f", "+ *.ini",
                                                "--ignore-case=false", "--dirs-only", "--files-only=true",
                                                "--ignore-case-sync", "--checksum", "--backup-dir", "old"])
        cmd = backend.to_command(task, 'rclone')
        self.assertEqual(cmd[-4:], ["--ignore-case-sync", "--checksum", "--backup-dir", "old"])
        self.assertEqual(backend.ignored_file_filter_flags(task), ["--exclude", "--ignore-case", "-f", "--dirs-only", "--files-only"])
        self.assertNotIn("+ *.ini", cmd)
        directory_args = ["--include", "*.ini", "-f-*.bak", "--max-size=1M"]
        self.assertEqual(backend._mode_specific_args(directory_args, "copy"), directory_args)
        self.assertEqual(backend._mode_specific_args(["--filters-file", "filters.txt"], "stat"), [])

    def test_file_check_precheck_and_invalid_preferences_fail(self) -> None:
        for fields in ({"check-before-sync": True}, {"preferred-mode": "check"}, {"preferred-mode": "sync"}, {"preferred-mode": "bisync"}):
            with self.subTest(fields=fields):
                schema = {"settings": {"default": {"path-type": "file"}}, "tasks": {"test": [
                    {"name": "config", "sub-tasks": [{"name": "all", "paths": [{"path1": "local", "path2": "remote"}], **fields}]},
                ]}}
                self.assertTrue(schema_ops._validate_schema(schema))
        task = schema_ops.SyncTask(path_type=models.PathType.FILE)
        with self.assertRaises(ValueError):
            backend.to_check_command(task, 'rclone')
        for mode in ("sync", "check", "bisync"):
            task.mode = mode
            with self.assertRaises(ValueError):
                backend.to_command(task, 'rclone')

    def test_file_menu_highlights_copy_and_has_no_check(self) -> None:
        task = schema_ops.SyncTask(name="appdata/config", path_type=models.PathType.FILE)
        with patch.object(utility.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
            terminal._select_action(task, None, None)
        options = select.call_args.args[0]
        self.assertEqual([option.value for option in options[:-1]], list(models.FILE_ACTIONS))
        self.assertEqual([option.desc_color for option in options[:-1]], [utility.FLYellow] * 2 + [utility.FLCyan] * 2)
        self.assertEqual(options[-1].keys, ["Q"])
        self.assertTrue(select.call_args.kwargs["required"])
        self.assertNotIn("default_key", select.call_args.kwargs)

    def test_local_file_guard_rejects_directories_missing_sources_and_links(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, mode="copy", local_path="a.ini", remote_path="b.ini")
        regular = os.stat_result((stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        directory = os.stat_result((stat.S_IFDIR, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        for metadata, accepted in (
            ([regular, regular], True), ([regular, FileNotFoundError()], True),
            ([directory], False), ([FileNotFoundError()], False),
            ([regular, directory], False), ([regular, PermissionError()], False),
        ):
            with self.subTest(accepted=accepted), patch.object(os, "stat", side_effect=metadata), patch.object(os.path, "islink", return_value=False):
                if accepted:
                    backend._validate_file_endpoints(task, "rclone", "push")
                else:
                    with self.assertRaises(ValueError):
                        backend._validate_file_endpoints(task, "rclone", "push")
        with patch.object(os.path, "islink", return_value=True):
            with self.assertRaises(ValueError):
                backend._validate_file_endpoints(task, "rclone", "push")

    def test_remote_guard_handles_missing_objects_without_hiding_real_directories(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, mode="copy", local_path="a.ini", remote_path="backup:dir/a.ini")
        regular = os.stat_result((stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        for responses, accepted in (
            ([(0, '{"IsDir": false}')], True),
            ([(4, "")], True),
            ([(3, "")], True),
            ([(1, "")], False),
            ([(0, "invalid")], False),
            ([(0, "{}")], False),
            ([(0, '{"IsDir": true}'), (0, "[]")], True),
            ([(0, '{"IsDir": true}'), (0, '[{"Name": "a.ini", "IsDir": true}]')], False),
            ([(0, '{"IsDir": true}'), (0, '[{"Name": "A.INI", "IsDir": true}]')], False),
            ([(0, '{"IsDir": true}'), (1, "")], False),
        ):
            with self.subTest(responses=responses), contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(os, "stat", return_value=regular))
                stack.enter_context(patch.object(os.path, "islink", return_value=False))
                probe = stack.enter_context(patch.object(backend, "_run_interruptible", side_effect=[
                    subprocess.CompletedProcess([], code, output, "") for code, output in responses
                ]))
                if accepted:
                    backend._validate_file_endpoints(task, "rclone", "push")
                else:
                    with self.assertRaises(ValueError):
                        backend._validate_file_endpoints(task, "rclone", "push")
                self.assertIn("--stat", probe.call_args_list[0].args[0])
        with patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 4, "", "")):
            with self.assertRaises(ValueError):
                backend._validate_file_endpoints(task, "rclone", "pull")

    def test_metadata_probes_ignore_filters_but_keep_config_flags(self) -> None:
        args = ["--config", "custom.conf", "--exclude", "*", "--include=*.ini", "--files-only", "--max-depth", "9"]
        self.assertEqual(backend._mode_specific_args(args, "stat"), ["--config", "custom.conf"])

    def test_remote_root_is_never_treated_as_a_missing_filename(self) -> None:
        regular = os.stat_result((stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        for path in ("backup:", "backup:/", "backup:.", "backup:dir/.."):
            with self.subTest(path=path), patch.object(os, "stat", return_value=regular), patch.object(os.path, "islink", return_value=False), patch.object(backend, "_run_interruptible") as execute:
                task = schema_ops.SyncTask(path_type=models.PathType.FILE, mode="copy", local_path="a.ini", remote_path=path)
                with self.assertRaises(ValueError):
                    backend._validate_file_endpoints(task, "rclone", "push")
                execute.assert_not_called()

    def test_unc_endpoints_are_local_and_remote_file_mtimes_use_stat(self) -> None:
        regular = os.stat_result((stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, mode="copy", local_path="a.ini", remote_path=r"\\server\share\b.ini")
        with patch.object(os, "stat", return_value=regular), patch.object(os.path, "islink", return_value=False), patch.object(backend, "_run_interruptible") as execute:
            backend._validate_file_endpoints(task, "rclone", "pull")
            execute.assert_not_called()
        result = subprocess.CompletedProcess([], 0, '{"IsDir": false, "ModTime": "2026-01-01T00:00:00Z"}', "")
        with patch.object(backend, "_run_interruptible", return_value=result) as execute:
            task.remote_path = "backup:b.ini"
            info = backend._get_remote_path_info(task, "rclone")
        self.assertEqual(info.mtime, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
        self.assertEqual(execute.call_args.args[0], ["rclone", "lsjson", "backup:b.ini", "--stat"])

    def test_each_execution_is_guarded_and_failure_never_transfers(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE)
        with patch.object(backend, "_validate_file_endpoints", side_effect=[None, ValueError("source changed to directory")]) as validate, patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0)) as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execution._run_task_command(task, ["rclone", "copyto"], "rclone", "push").returncode, 0)
            self.assertEqual(execution._run_task_command(task, ["rclone", "copyto", "--dry-run"], "rclone", "push").returncode, 1)
        self.assertEqual(validate.call_count, 2)
        execute.assert_called_once()


class ModifiedTimeTests(unittest.TestCase):
    """Distinguish first sync, unreadable metadata, and optional time display."""

    def test_flag_defaults_false_inherits_and_does_not_change_commands(self) -> None:
        self.assertFalse(schema_ops.SyncTask().do_not_check_modified_time)
        settings = {"default": {"do-not-check-modified-time": True}}
        parent = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertTrue(parent.do_not_check_modified_time)
        child = parent.merge(schema_ops.SyncTask.from_dict({"name": "sub", "do-not-check-modified-time": False}))
        self.assertFalse(child.do_not_check_modified_time)
        for comparison in models.ComparisonMode:
            self.assertEqual(backend.to_command(parent, 'rclone', comparison=comparison), backend.to_command(child, 'rclone', comparison=comparison))
        for value in (0, "true", [], {}):
            with self.subTest(value=value):
                self.assertTrue(schema_ops._validate_schema({"tasks": {"test": [{"name": "test", "do-not-check-modified-time": value}]}}))

    def test_local_absence_and_access_errors_have_different_states(self) -> None:
        for error, state in ((FileNotFoundError(), models.PathState.MISSING), (PermissionError(), models.PathState.UNKNOWN), (NotADirectoryError(), models.PathState.UNKNOWN)):
            with self.subTest(error=type(error).__name__), patch.object(os, "stat", side_effect=error):
                info = backend._get_local_path_info("local")
                self.assertEqual(info.state, state)
                self.assertIsNone(info.mtime)

    def test_remote_failures_are_not_assumed_to_be_first_sync(self) -> None:
        task = schema_ops.SyncTask(path_type=models.PathType.FILE, remote_path="backup:a.ini")
        for code, output, state in (
            (4, "", models.PathState.MISSING), (3, "", models.PathState.MISSING),
            (1, "", models.PathState.UNKNOWN), (0, "invalid", models.PathState.UNKNOWN),
            (0, "{}", models.PathState.UNKNOWN),
            (0, '{"IsDir": false, "ModTime": 42}', models.PathState.PRESENT),
            (0, '{"IsDir": false, "ModTime": "2026-01-01T00:00:00"}', models.PathState.PRESENT),
        ):
            with self.subTest(code=code, output=output), patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], code, output, "private error detail")):
                info = backend._get_remote_path_info(task, "rclone")
                self.assertEqual(info.state, state)
                self.assertNotIn("private error detail", info.detail)
                self.assertIsNone(info.mtime)
        for error in (OSError(), subprocess.TimeoutExpired("rclone", 1)):
            with self.subTest(error=type(error).__name__), patch.object(backend, "_run_interruptible", side_effect=error):
                self.assertEqual(backend._get_remote_path_info(task, "rclone").state, models.PathState.UNKNOWN)

    def test_empty_directories_are_not_confused_with_missing_prefixes(self) -> None:
        task = schema_ops.SyncTask(remote_path="backup:parent/empty")
        for parent_output, code, state in (
            ('[{"Name": "empty", "IsDir": true}]', 0, models.PathState.PRESENT),
            ("[]", 0, models.PathState.MISSING),
            ("", 1, models.PathState.UNKNOWN),
        ):
            responses = [
                subprocess.CompletedProcess([], 0, "[]", ""),
                subprocess.CompletedProcess([], 0, '{"IsDir": true}', ""),
                subprocess.CompletedProcess([], code, parent_output, ""),
            ]
            with self.subTest(state=state), patch.object(backend, "_run_interruptible", side_effect=responses):
                info = backend._get_remote_path_info(task, "rclone")
                self.assertEqual(info.state, state)
                self.assertIsNone(info.mtime)

    def test_directory_mtime_still_uses_latest_immediate_child(self) -> None:
        output = '[{"IsDir": false, "ModTime": "2026-01-01T00:00:00Z"}, {"IsDir": true, "ModTime": "2026-01-02T00:00:00Z"}]'
        with patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0, output, "")) as execute:
            info = backend._get_remote_path_info(schema_ops.SyncTask(remote_path="backup:dir"), "rclone")
        self.assertEqual(info.mtime, datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc))
        execute.assert_called_once()
        self.assertIn("--max-depth", execute.call_args.args[0])

    def test_first_sync_display_depends_on_direction_and_confirmed_existence(self) -> None:
        present = models.PathInfo(models.PathState.PRESENT, models.PathType.FILE)
        missing = models.PathInfo(models.PathState.MISSING)
        unknown = models.PathInfo(models.PathState.UNKNOWN, detail="access denied")
        task = schema_ops.SyncTask(local_path="local", remote_path="remote", path_type=models.PathType.FILE)
        for local, remote, direction, expected, first_transfer in (
            (present, missing, "push", "First upload:", True),
            (missing, present, "pull", "First download:", True),
            (missing, present, "push", "local source is missing", False),
            (present, missing, "pull", "remote source is missing", False),
            (missing, missing, "push", "Both paths are missing", False),
            (unknown, missing, "push", "Cannot determine first-sync direction", False),
            (missing, present, "", "initialize it with a one-way pull", False),
            (present, unknown, "push", "access denied", False),
            (present, present, "push", "exists; modification time unavailable", False),
        ):
            with self.subTest(direction=direction, expected=expected), patch.object(backend, "_get_local_path_info", side_effect=[local, remote]), contextlib.redirect_stdout(io.StringIO()) as output:
                warnings = terminal._display_path_mtimes(task, "rclone", direction)
                text = f"{output.getvalue()}\n{' '.join(warnings)}"
                self.assertIn(expected, text)
                self.assertEqual("First upload:" in text or "First download:" in text, first_transfer)
                self.assertNotIn("would overwrite newer", text)

    def test_file_type_guard_requests_no_modtime_and_cancellation_propagates(self) -> None:
        task = schema_ops.SyncTask(local_path="local", remote_path="backup:a.ini", path_type=models.PathType.FILE)
        present = models.PathInfo(models.PathState.PRESENT, models.PathType.FILE)
        with patch.object(backend, "_get_local_path_info", return_value=present), patch.object(os.path, "islink", return_value=False), patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0, '{"IsDir": false}', "")) as execute:
            backend._validate_file_endpoints(task, "rclone", "push")
        self.assertIn("--no-modtime", execute.call_args.args[0])
        with patch.object(backend, "_run_interruptible", side_effect=backend.OperationCancelled):
            with self.assertRaises(backend.OperationCancelled):
                backend._get_remote_path_info(task, "rclone")



if __name__ == "__main__":
    unittest.main()
