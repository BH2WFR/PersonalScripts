"""Regression checks for schema loading, paths, actions, and profile inheritance.

Uses unittest and the runner's existing PyYAML dependency. No rclone subprocess
or real synchronization is started. Run with conda run -n base python -m unittest
discover -s test -p test_rclone_sync.py.
"""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rclone_sync_test_target", ROOT / "tools/network/rclone-sync.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class SchemaLoadingTests(unittest.TestCase):
    """Check duplicate-key locations without weakening SafeLoader or YAML merges."""

    def test_duplicate_keys_report_both_definition_locations(self) -> None:
        cases = (
            ("tasks: {}\ntasks: {}\n", 1, 2),
            ("settings:\n  base: {}\n  base: {}\n", 2, 3),
            ("tasks:\n  test: []\n  test: []\n", 2, 3),
            ("tasks:\n  test:\n  - name: demo\n    allow-actions: [push]\n    'allow-actions': all\n", 4, 5),
            ("task:\n  sub-tasks:\n  - name: all\n    local-path: first\n    local-path: second\n", 4, 5),
            ("task: {name: first, name: second}\n", 1, 1),
            ("task:\n  <<: {name: first}\n  <<: {name: second}\n", 2, 3),
            ("true: first\nyes: second\n", 1, 2),
        )
        for source, first_line, repeated_line in cases:
            with self.subTest(source=source):
                stream = io.StringIO(source)
                stream.name = "schema.yaml"
                with self.assertRaises(yaml.constructor.ConstructorError) as caught:
                    runner._load_schema(stream)
                error = caught.exception
                self.assertEqual(error.context_mark.line + 1, first_line)
                self.assertEqual(error.problem_mark.line + 1, repeated_line)
                self.assertIn("duplicate YAML key", str(error))
                self.assertIn("schema.yaml", str(error))

    def test_aliases_and_merge_overrides_keep_yaml_precedence(self) -> None:
        source = """base: &base {name: base, transfer: 4}
override: &override {<<: *base, transfer: 8}
task: {<<: [*override, *base], name: task}
alias: *override
other: {name: other}
"""
        loaded = runner._load_schema(io.StringIO(source))
        self.assertEqual(loaded, yaml.safe_load(source))
        self.assertEqual(loaded["task"], {"name": "task", "transfer": 8})

    def test_duplicate_keys_inside_merge_sources_are_also_rejected(self) -> None:
        for source in (
            "task: {<<: {transfer: 4, transfer: 8}}",
            "task: {<<: [{transfer: 4}, {name: first, name: second}]}",
        ):
            with self.subTest(source=source), self.assertRaisesRegex(yaml.YAMLError, "duplicate YAML key"):
                runner._load_schema(io.StringIO(source))

    def test_empty_unsafe_and_malformed_documents(self) -> None:
        self.assertIsNone(runner._load_schema(io.StringIO("")))
        for source in ("name: [", "!!python/object:builtins.object {}", "? [a, b]\n: value"):
            with self.subTest(source=source), self.assertRaises(yaml.YAMLError):
                runner._load_schema(io.StringIO(source))
        # The strict loader must not change other tools' PyYAML behavior.
        self.assertEqual(yaml.safe_load("value: 1\nvalue: 2"), {"value": 2})


class PathExpansionTests(unittest.TestCase):
    """Check strict one-pass expansion while preserving rclone path syntax."""

    def test_all_variable_spellings_expand_in_every_path_field(self) -> None:
        for reference in ("$ROOT", "${ROOT}", "%ROOT%", "$ENV:ROOT", "${ENV:ROOT}"):
            for field in ("local_path", "remote_path", "backup_dir", "log_file"):
                with self.subTest(reference=reference, field=field), patch.dict(os.environ, {"ROOT": "data root"}, clear=True):
                    task = runner.SyncTask(**{field: f"{reference}/files"})
                    task.resolve_paths("schema", "script")
                    self.assertEqual(getattr(task, field), "data root/files")

    def test_undefined_references_report_the_field_without_partial_updates(self) -> None:
        for reference in ("$MISSING", "${MISSING}", "%MISSING%", "$ENV:MISSING", "${ENV:MISSING}", "{{typo}}"):
            with self.subTest(reference=reference), patch.dict(os.environ, {"ROOT": "data"}, clear=True):
                task = runner.SyncTask(local_path="$ROOT/source", remote_path=f"backup:{reference}/files")
                with self.assertRaisesRegex(ValueError, "remote-path: (Undefined environment variable|Unknown placeholder)"):
                    task.resolve_paths("schema", "script")
                self.assertEqual(task.local_path, "$ROOT/source")
                self.assertEqual(task.remote_path, f"backup:{reference}/files")

    def test_inserted_values_are_not_expanded_or_rejected_as_variables(self) -> None:
        literal = "${MISSING}/$ENV:MISSING/%MISSING%/{{unknown}}"
        with patch.dict(os.environ, {"ROOT": literal}, clear=True):
            task = runner.SyncTask(local_path="$ROOT/files", log_file="{{schema_dir}}/run.log")
            task.resolve_paths(literal, "script")
        self.assertEqual(task.local_path, f"{literal}/files")
        self.assertEqual(task.log_file, f"{literal}/run.log")

    def test_placeholders_home_unc_and_remote_roots_keep_their_meaning(self) -> None:
        task = runner.SyncTask(local_path="{{schema_dir}}/data", remote_path="backup:{{script_dir}}/data",
                               backup_dir="{{current_dir}}/old", log_file="~/run.log")
        with patch.object(runner.os, "getcwd", return_value="cwd"):
            task.resolve_paths("schema", "script")
        self.assertEqual(task.local_path, "schema/data")
        self.assertEqual(task.remote_path, "backup:script/data")
        self.assertEqual(task.backup_dir, "cwd/old")
        self.assertEqual(task.log_file, os.path.expanduser("~/run.log"))
        for path in (r"\\server\share\files", "//server/share/files", "C:/files", "relative/files",
                     "backup:~/files", ":local:/data", "/data/100% ready", "backup:"):
            with self.subTest(path=path):
                task = runner.SyncTask(remote_path=path)
                task.resolve_paths("schema", "script")
                self.assertEqual(task.remote_path, path)

    def test_windows_variable_lookup_is_case_insensitive(self) -> None:
        with patch.object(runner.os, "name", "nt"), patch.dict(os.environ, {"ROOT": "data"}, clear=True):
            task = runner.SyncTask(local_path="$root/files")
            task.resolve_paths("schema", "script")
        self.assertEqual(task.local_path, "data/files")


class InheritanceTests(unittest.TestCase):
    """Check reference chains and precedence through actual schema resolution."""

    def test_cycles_are_rejected_when_loading_unused_profiles(self) -> None:
        for settings, chain in (
            ({"a": {"inherit": ["a"]}}, "a -> a"),
            ({"a": {"inherit": ["b"]}, "b": {"inherit": ["a"]}}, "a -> b -> a"),
            ({"default": {"inherit": ["a"]}, "a": {"inherit": ["default"]}}, "default -> a -> default"),
        ):
            with self.subTest(chain=chain):
                errors = runner._validate_schema({"settings": settings, "tasks": {}})
                self.assertTrue(any(chain in error for error in errors), errors)
                with self.assertRaisesRegex(ValueError, chain):
                    runner._resolve_profile_chain(settings, next(iter(settings)))

    def test_shared_parent_is_reapplied_and_excludes_stay_unique(self) -> None:
        settings = {
            "base": {"transfer": 8, "exclude": ["*.tmp"]},
            "left": {"inherit": ["base"], "transfer": 24, "exclude": ["*.bak"]},
            "right": {"inherit": ["base"], "exclude": ["*.tmp", "*.log"]},
        }
        task = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["left", "right"]})
        self.assertEqual(task.transfer, 8)
        self.assertEqual(task.exclude, ["*.tmp", "*.bak", "*.log"])
        self.assertEqual(runner._validate_schema({"settings": settings, "tasks": {}}), [])

    def test_repeated_profile_and_explicit_fields_keep_list_precedence(self) -> None:
        settings = {"a": {"preferred-mode": "copy"}, "b": {"preferred-mode": "move"}}
        task = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["a", "b", "a"]})
        self.assertEqual(task.preferred_mode, "copy")
        sub = runner.SyncTask.from_dict({"name": "sub", "inherit": ["a", "b"], "preferred-mode": "sync"})
        self.assertEqual(sub.resolve_profiles(settings).preferred_mode, "sync")

    def test_default_inheritance_and_depth_limit(self) -> None:
        settings = {"default": {"inherit": ["base"]}, "base": {"preferred-mode": "move"}}
        task = runner.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertEqual(task.preferred_mode, "move")
        deep = {f"p{i}": {"inherit": [f"p{i + 1}"]} for i in range(runner.MAX_INHERIT_DEPTH + 2)}
        deep[f"p{runner.MAX_INHERIT_DEPTH + 2}"] = {}
        with self.assertRaisesRegex(ValueError, "depth exceeded"):
            runner._resolve_profile_chain(deep, "p0")

    def test_bad_references_and_types_at_each_level(self) -> None:
        for inherit in (["missing"], [5], {"profile": "base"}):
            for scope in ("profile", "task", "subtask"):
                with self.subTest(inherit=inherit, scope=scope):
                    profile: dict[str, object] = {}
                    sub: dict[str, object] = {"name": "sub"}
                    task: dict[str, object] = {"name": "task", "sub-tasks": [sub]}
                    target = {"profile": profile, "task": task, "subtask": sub}[scope]
                    target["inherit"] = inherit
                    self.assertTrue(runner._validate_schema({"settings": {"base": profile}, "tasks": {"test": [task]}}))


class ActionTests(unittest.TestCase):
    """Check runtime overrides, menu ordering, permissions, and comparisons."""

    def test_mode_orders_matching_actions_first(self) -> None:
        prefixes = {
            "sync": ["push", "pull"], "copy": ["push-copy", "pull-copy"],
            "move": ["push-move", "pull-move"], "bisync": ["bisync"], "check": ["check"],
        }
        for mode, expected in prefixes.items():
            with self.subTest(mode=mode):
                actions = runner._available_actions(runner.SyncTask(preferred_mode=mode))
                self.assertEqual([action.value for action in actions[:len(expected)]], expected)
                self.assertEqual(len(actions), 8)

    def test_missing_or_empty_mode_highlights_push_pull_in_standard_order(self) -> None:
        for raw in ("name: test", "name: test\npreferred-mode:", 'name: test\npreferred-mode: ""',
                    'name: test\npreferred-mode: "   "'):
            with self.subTest(raw=raw):
                config = yaml.safe_load(raw)
                self.assertEqual(runner._validate_schema({"tasks": {"test": [config]}}), [])
                task = runner.SyncTask.from_dict(config)
                self.assertEqual(task.preferred_mode, "")
                self.assertEqual(task.mode, "")
                with patch.object(runner.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
                    runner._select_action(task, None, None)
                options = select.call_args.args[0]
                self.assertEqual([option.value for option in options[:-1]], list(runner.PATH_ACTIONS[runner.PathType.DIRECTORY]))
                self.assertEqual(options[-1].keys, ["Q"])
                for option in options[:-1]:
                    expected = runner.FLYellow if option.value in (runner.SyncAction.PUSH, runner.SyncAction.PULL) else runner.FLCyan
                    self.assertEqual(option.desc_color, expected)
                    self.assertNotIn("removes source files", option.description)

    def test_only_preferred_mode_is_yellow(self) -> None:
        for mode in ("sync", "copy", "move", "bisync", "check"):
            with self.subTest(mode=mode):
                task = runner.SyncTask.from_dict({"name": "test", "preferred-mode": mode})
                with patch.object(runner.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
                    runner._select_action(task, None, None)
                options = select.call_args.args[0]
                self.assertEqual(options[0].desc_color, runner.FLYellow)
                for option in options[:-1]:
                    expected = runner.FLYellow if runner.ACTION_COMMANDS[option.value][0] == mode else runner.FLCyan
                    self.assertEqual(option.desc_color, expected)

    def test_empty_mode_clears_inherited_preference(self) -> None:
        settings = {"default": {"preferred-mode": "move"}, "copies": {"preferred-mode": "copy"}}
        inherited = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["copies"]})
        self.assertEqual(inherited.preferred_mode, "copy")
        self.assertEqual(runner._available_actions(inherited)[0], runner.SyncAction.PUSH_COPY)
        for empty in (None, "", "   "):
            with self.subTest(empty=empty):
                cleared = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["copies"], "preferred-mode": empty})
                self.assertEqual(cleared.preferred_mode, "")
                self.assertEqual(runner._available_actions(cleared), list(runner.PATH_ACTIONS[runner.PathType.DIRECTORY]))
                sub = runner.SyncTask.from_dict({"name": "sub", "preferred-mode": empty})
                self.assertEqual(inherited.merge(sub.resolve_profiles(settings)).preferred_mode, "")

    def test_unset_mode_preserves_direction_only_cli_sync(self) -> None:
        task = runner.SyncTask(local_path="local", remote_path="remote:")
        self.assertEqual(runner._select_action(task, None, "pull"), runner.SyncAction.PULL)
        self.assertEqual(task.to_command("rclone", direction="pull")[:4], ["rclone", "sync", "remote:", "local"])
        self.assertEqual(task.mode, "")

    def test_allowlist_hides_every_action_not_explicitly_granted(self) -> None:
        for expected, forbidden in (
            (["push", "push-copy", "push-move", "check"], runner.SyncAction.PULL),
            (["pull", "pull-copy", "pull-move", "check"], runner.SyncAction.PUSH),
        ):
            with self.subTest(expected=expected):
                config = {"name": "test", "allow-actions": expected}
                self.assertEqual(runner._validate_schema({"tasks": {"test": [config]}}), [])
                task = runner.SyncTask.from_dict(config)
                self.assertEqual([action.value for action in runner._available_actions(task)], expected)
                for action in (forbidden, runner.SyncAction.BISYNC):
                    with self.assertRaises(ValueError):
                        runner._select_action(task, action, None)
                    with self.assertRaises(ValueError):
                        runner._task_for_action(task, action)
                allowed = runner.SyncTask.from_dict({"name": "test"})
                self.assertEqual(runner._available_actions(allowed), list(runner.PATH_ACTIONS[runner.PathType.DIRECTORY]))

    def test_allowlists_replace_instead_of_appending_and_empty_disables_all(self) -> None:
        settings = {"oneway": {"allow-actions": ["pull-copy", "check"], "exclude": ["*.tmp"]}}
        task = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["oneway"]})
        self.assertNotIn(runner.SyncAction.PUSH_COPY, runner._available_actions(task))
        sub = runner.SyncTask.from_dict({"name": "sub", "allow-actions": ["push-copy"], "exclude": ["*.tmp", "*.bak"]})
        merged = task.merge(sub)
        self.assertEqual(runner._available_actions(merged), [runner.SyncAction.PUSH_COPY])
        self.assertEqual(merged.exclude, ["*.tmp", "*.bak"])
        empty = task.merge(runner.SyncTask.from_dict({"name": "sub", "allow-actions": []}))
        self.assertEqual(runner._available_actions(empty), [])
        self.assertEqual(runner._available_actions(task.merge(runner.SyncTask(name="sub"))), runner._available_actions(task))
        with self.assertRaises(ValueError):
            empty.to_command("rclone")

    def test_menu_does_not_select_first_action_on_enter(self) -> None:
        task = runner.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote")
        with patch.object(runner.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(runner._select_action(task, None, None))
        self.assertNotIn("default_key", select.call_args.kwargs)
        self.assertTrue(select.call_args.kwargs["required"])
        self.assertEqual(select.call_args.args[0][0].value, runner.SyncAction.PUSH_MOVE)
        for option in select.call_args.args[0][:-1]:
            self.assertIn(f"{runner.FLBlue}local{runner.CRst}", option.description)
            self.assertIn(f"{runner.FLGreen}remote{runner.CRst}", option.description)

    def test_all_clears_inherited_restrictions_for_each_path_type(self) -> None:
        settings = {"default": {"allow-actions": ["check"]}, "unrestricted": {"allow-actions": "all"}}
        parent = runner.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertEqual(runner._available_actions(parent), [runner.SyncAction.CHECK])
        for path_type in runner.PathType:
            with self.subTest(path_type=path_type):
                raw = {"name": "sub", "path-type": path_type.value, "allow-actions": "all"}
                task = parent.merge(runner.SyncTask.from_dict(raw).resolve_profiles(settings))
                self.assertEqual(task.validate(), [])
                self.assertEqual(runner._available_actions(task), list(runner.PATH_ACTIONS[path_type]))
                restored = runner.SyncTask.from_inheritance_chain(settings, {
                    "name": "test", "path-type": path_type.value, "inherit": ["unrestricted"],
                })
                self.assertEqual(runner._available_actions(restored), runner._available_actions(task))

    def test_null_and_all_clear_restrictions_but_omission_inherits(self) -> None:
        for raw_value in ("null", "~", "", "all", '"all"'):
            for scope in ("profile", "task", "subtask"):
                with self.subTest(raw_value=raw_value, scope=scope):
                    fields = yaml.safe_load(f"allow-actions: {raw_value}")
                    settings = {"default": {"allow-actions": ["check"]}, "override": {}}
                    raw = {"name": "demo", "inherit": ["override"]}
                    sub = {"name": "sub"}
                    {"profile": settings["override"], "task": raw, "subtask": sub}[scope].update(fields)
                    for path_type in runner.PathType:
                        raw["path-type"] = path_type.value
                        self.assertEqual(runner._validate_schema({"settings": settings, "tasks": {"test": [{**raw, "sub-tasks": [sub]}]}}), [])
                        parent = runner.SyncTask.from_inheritance_chain(settings, raw)
                        result = parent.merge(runner.SyncTask.from_dict(sub))
                        self.assertIsNone(result.allow_actions)
                        self.assertEqual(runner._available_actions(result), list(runner.PATH_ACTIONS[path_type]))
        restricted = runner.SyncTask.from_dict({"allow-actions": ["check"]})
        self.assertEqual(restricted.merge(runner.SyncTask.from_dict({})).allow_actions, [runner.SyncAction.CHECK])

    def test_preferred_mode_keeps_cli_direction_and_does_not_replace_action(self) -> None:
        for path_type in runner.PathType:
            for preferred in ("copy", "move"):
                with self.subTest(path_type=path_type, preferred=preferred):
                    task = runner.SyncTask.from_dict({
                        "name": "test", "preferred-mode": preferred, "path-type": path_type.value,
                        "local-path": "local", "remote-path": "remote:",
                    })
                    action = runner._select_action(task, None, "pull")
                    self.assertEqual(runner.ACTION_COMMANDS[action], (preferred, "pull"))
                    expected = f"{preferred}to" if path_type == runner.PathType.FILE else preferred
                    self.assertEqual(task.to_command("rclone", direction="pull")[:4], ["rclone", expected, "remote:", "local"])
                    override = runner.SyncAction.PUSH_COPY_FILE if path_type == runner.PathType.FILE else runner.SyncAction.PUSH
                    selected = runner._task_for_action(task, override)
                    self.assertEqual(selected.preferred_mode, preferred)
                    self.assertEqual(selected.mode, runner.ACTION_COMMANDS[override][0])
                    self.assertEqual(task.mode, "")

    def test_deletion_limits_use_the_selected_action_and_inherit_independently(self) -> None:
        settings = {"default": {"max-delete-count": 7, "max-delete-percent": 20}}
        parent = runner.SyncTask.from_inheritance_chain(settings, {"name": "test", "preferred-mode": "bisync"})
        task = parent.merge(runner.SyncTask.from_dict({"name": "sub", "max-delete-count": 12}))
        self.assertEqual((task.max_delete_count, task.max_delete_percent), (12, 20))
        for action in runner.PATH_ACTIONS[runner.PathType.DIRECTORY]:
            with self.subTest(action=action):
                selected = runner._task_for_action(task, action)
                mode, direction = runner.ACTION_COMMANDS[action]
                command = selected.to_command("rclone", direction=direction or "push")
                if mode in {"sync", "bisync"}:
                    limit = command[command.index("--max-delete") + 1]
                    self.assertEqual(limit, "12" if mode == "sync" else "20")
                else:
                    self.assertNotIn("--max-delete", command)
        for field, mode in (("max_delete_count", "bisync"), ("max_delete_percent", "sync")):
            with self.subTest(field=field, mode=mode):
                self.assertNotIn("--max-delete", runner.SyncTask(mode=mode, **{field: 5}).to_command("rclone"))

    def test_deletion_limit_validation_and_removed_yaml_names(self) -> None:
        for fields in (
            {"max-delete-count": -2}, {"max-delete-count": True}, {"max-delete-count": "5"},
            {"max-delete-percent": -1}, {"max-delete-percent": 101}, {"max-delete-percent": 0.5},
            {"max-delete-percent": False}, {"mode": "copy"}, {"max-delete": 50},
        ):
            with self.subTest(fields=fields):
                self.assertTrue(runner._validate_schema({"tasks": {"test": [{"name": "task", **fields}]}}))
        for count, percent in ((-1, 100), (0, 0), (12, 50)):
            fields = {"name": "task", "max-delete-count": count, "max-delete-percent": percent}
            self.assertEqual(runner._validate_schema({"tasks": {"test": [fields]}}), [])
        self.assertNotIn("--max-delete", runner.SyncTask().to_command("rclone"))

    def test_operation_menu_retries_empty_input_and_q_goes_back(self) -> None:
        task = runner.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote")
        for key, expected in (("q", None), ("pull", runner.SyncAction.PULL)):
            with self.subTest(key=key), patch("builtins.input", side_effect=["", "   ", key]) as prompt:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(runner._select_action(task, None, None), expected)
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
                task = runner.SyncTask(name="test/demo/all", remote_path="primary:/files", alternative_remote_hosts=["backup"])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(runner._interactive_host_swap(task, False), accepted)
                self.assertEqual(task.remote_path, expected_path)
                self.assertIn(f"remote-path{runner.CRst} {runner.FLYellow}test/demo/all{runner.CRst}:", output.getvalue())
                self.assertIn(f"[{runner.CRst}Q{runner.FGray}]", output.getvalue())

    def test_host_selection_skips_auto_local_and_missing_alternatives(self) -> None:
        for path, alternatives, auto in (
            ("primary:/files", ["backup"], True),
            ("local", ["backup"], False),
            ("primary:/files", [], False),
        ):
            with self.subTest(path=path, auto=auto), patch("builtins.input") as prompt:
                task = runner.SyncTask(remote_path=path, alternative_remote_hosts=alternatives)
                self.assertTrue(runner._interactive_host_swap(task, auto))
                self.assertEqual(task.remote_path, path)
                prompt.assert_not_called()

    def test_comparison_menu_q_cancels_but_enter_keeps_default(self) -> None:
        for mode in runner.VALID_MODES:
            for key in ("Q", ""):
                with self.subTest(mode=mode, key=key), patch("builtins.input", return_value=key):
                    task = runner.SyncTask(mode=mode)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        selected = runner._select_comparison_mode(task, None, True)
                    expected = runner.ComparisonMode.CHECKSUM if mode == "check" else runner.ComparisonMode.SIZE_AND_TIME
                    self.assertEqual(selected, None if key == "Q" else expected)
                    self.assertIn("Back to task menu", output.getvalue().splitlines()[-1])

    def test_actions_override_yaml_mode_and_reverse_pull_paths(self) -> None:
        original = runner.SyncTask(name="test", preferred_mode="move", local_path="local", remote_path="remote:")
        for name, mode, source, destination in (
            ("push", "sync", "local", "remote:"), ("pull", "sync", "remote:", "local"),
            ("push-copy", "copy", "local", "remote:"), ("pull-copy", "copy", "remote:", "local"),
            ("push-move", "move", "local", "remote:"), ("pull-move", "move", "remote:", "local"),
            ("bisync", "bisync", "local", "remote:"), ("check", "check", "local", "remote:"),
        ):
            with self.subTest(action=name):
                action = runner.SyncAction(name)
                task = runner._task_for_action(original, action)
                _, direction = runner.ACTION_COMMANDS[action]
                cmd = task.to_command("rclone", direction=direction or "push", comparison=runner.ComparisonMode.SIZE_ONLY)
                self.assertEqual(cmd[:4], ["rclone", mode, source, destination])
                self.assertEqual(original.preferred_mode, "move")
                self.assertEqual(original.mode, "")

    def test_permissions_include_check_and_do_not_expand_direction_wildcards(self) -> None:
        task = runner.SyncTask.from_dict({"name": "test", "allow-actions": ["pull", "pull-copy", "pull-move", "check"]})
        self.assertEqual([action.value for action in runner._available_actions(task)], ["pull", "pull-copy", "pull-move", "check"])
        with self.assertRaises(ValueError):
            runner._task_for_action(task, runner.SyncAction.PUSH_MOVE)
        task.allow_actions = [runner.SyncAction.CHECK]
        self.assertEqual(task.validate(), [])
        self.assertEqual(runner._available_actions(task), [runner.SyncAction.CHECK])
        task.allow_actions = [runner.SyncAction.PUSH]
        self.assertEqual(runner._available_actions(task), [runner.SyncAction.PUSH])
        with self.assertRaises(ValueError):
            runner._select_action(task, runner.SyncAction.CHECK, None)

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
                task = runner.SyncTask(mode=mode, progress=False, ignore_times=True, size_only=True, checksum=True,
                                       additional_args=["-I=true", "-c", "--size-only=false", "--compare", "size"])
                self.assertEqual(task.to_command("rclone", comparison=runner.ComparisonMode(comparison))[4:], expected)
        for mode, comparison in (("check", "force"), ("check", "size_and_time"), ("bisync", "force")):
            with self.subTest(mode=mode, comparison=comparison), self.assertRaises(ValueError):
                runner.SyncTask(mode=mode).to_command("rclone", comparison=runner.ComparisonMode(comparison))

    def test_mode_specific_arguments_and_one_way_precheck(self) -> None:
        task = runner.SyncTask(mode="copy", delete_excluded=True, max_delete_count=5,
                               additional_args=["--workdir", "state", "--resync", "--max-delete=1", "--delete-excluded", "--transfers=8"])
        cmd = task.to_command("rclone", comparison=runner.ComparisonMode.SIZE_ONLY)
        self.assertNotIn("--delete-excluded", cmd)
        self.assertNotIn("--resync", cmd)
        self.assertNotIn("state", cmd)
        self.assertNotIn("--max-delete=1", cmd)
        self.assertIn("--transfers=8", cmd)
        self.assertIn("--one-way", task.to_check_command("rclone"))
        bisync = runner.SyncTask(mode="bisync")
        self.assertNotIn("--resync", bisync.to_command("rclone", comparison=runner.ComparisonMode.SIZE_ONLY))
        self.assertIn("--resync", bisync.to_command("rclone", comparison=runner.ComparisonMode.SIZE_ONLY, resync=True))

    def test_cli_conflicts_and_configured_comparison_default(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in (["--action", "push-copy", "--pull"], ["--push", "--direction", "pull"],
                         ["--action", "check", "--resync"], ["--comparison", "default"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as raised:
                    runner._parse_args(argv)
                self.assertEqual(raised.exception.code, 2)
        task = runner.SyncTask(size_only=True)
        with patch.object(runner.Menu, "select", return_value=runner.ComparisonMode.SIZE_AND_TIME) as select, contextlib.redirect_stdout(io.StringIO()):
            selected = runner._select_comparison_mode(task, None, True)
        self.assertEqual(select.call_args.kwargs["default_key"], "1")
        self.assertEqual(selected, runner.ComparisonMode.SIZE_AND_TIME)
        self.assertNotIn("--size-only", task.to_command("rclone", comparison=selected))


class FileTaskTests(unittest.TestCase):
    """Verify exact-file actions and fail-closed metadata guards without rclone."""

    def test_file_type_inherits_and_can_be_overridden(self) -> None:
        settings = {
            "file": {"path-type": "file", "allow-actions": ["push-copy-file"]},
            "restore": {"allow-actions": ["pull-copy-file"]},
        }
        task = runner.SyncTask.from_inheritance_chain(settings, {"name": "config", "inherit": ["file", "restore"]})
        self.assertEqual(task.path_type, runner.PathType.FILE)
        self.assertEqual(runner._available_actions(task), [runner.SyncAction.PULL_COPY_FILE])
        sub = runner.SyncTask.from_dict({"name": "dir", "path-type": "directory", "allow-actions": ["check"]})
        self.assertEqual(runner._available_actions(task.merge(sub)), [runner.SyncAction.CHECK])

    def test_schema_reference_uses_the_current_fields_and_validates(self) -> None:
        with (ROOT / "tools/network/rclone-sync-schema-sample.yaml").open(encoding="utf-8") as stream:
            schema = runner._load_schema(stream)
        self.assertEqual(runner._validate_schema(schema), [])

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
                    sub: dict[str, object] = {"name": "all"}
                    task: dict[str, object] = {"name": "config", "inherit": ["profile"], "sub-tasks": [sub]}
                    {"task": task, "profile": profile, "subtask": sub}[scope].update(fields)
                    self.assertTrue(runner._validate_schema({"settings": {"profile": profile}, "tasks": {"test": [task]}}))

    def test_file_capabilities_intersect_permissions_and_cli_uses_file_names(self) -> None:
        task = runner.SyncTask(path_type=runner.PathType.FILE, local_path="a.ini", remote_path="backup:b.ini")
        self.assertEqual(runner._available_actions(task), list(runner.FILE_ACTIONS))
        self.assertEqual(runner._select_action(task, None, "pull"), runner.SyncAction.PULL_COPY_FILE)
        self.assertEqual(task.to_command("rclone", direction="pull")[:4], ["rclone", "copyto", "backup:b.ini", "a.ini"])
        for action in runner.PATH_ACTIONS[runner.PathType.DIRECTORY]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                runner._select_action(task, action, None)
        task.allow_actions = [runner.SyncAction.PUSH, runner.SyncAction.PULL_COPY_FILE]
        self.assertEqual(runner._available_actions(task), [runner.SyncAction.PULL_COPY_FILE])
        with self.assertRaises(ValueError):
            task.to_command("rclone", direction="push")
        for action in runner.FILE_ACTIONS:
            self.assertEqual(runner._parse_args(["--action", action.value]).action, action.value)

    def test_file_commands_reverse_exact_paths_and_support_all_comparisons(self) -> None:
        original = runner.SyncTask(path_type=runner.PathType.FILE, local_path="local/a.ini", remote_path="backup:dir/b.ini")
        for action in runner.FILE_ACTIONS:
            mode, direction = runner.ACTION_COMMANDS[action]
            task = runner._task_for_action(original, action)
            for comparison in runner.ComparisonMode:
                with self.subTest(action=action, comparison=comparison):
                    cmd = task.to_command("rclone", direction=direction, comparison=comparison, dry_run=True)
                    paths = ["local/a.ini", "backup:dir/b.ini"]
                    if direction == "pull":
                        paths.reverse()
                    self.assertEqual(cmd[:4], ["rclone", f"{mode}to", *paths])
                    self.assertIn("--dry-run", cmd)
                    expected = {"force": "--ignore-times", "checksum": "--checksum", "size_only": "--size-only"}.get(comparison.value)
                    for flag in ("--ignore-times", "--checksum", "--size-only"):
                        self.assertEqual(flag in cmd, flag == expected)
        self.assertEqual(original.mode, "")

    def test_file_check_precheck_and_invalid_preferences_fail(self) -> None:
        for fields in ({"check-before-sync": True}, {"preferred-mode": "check"}, {"preferred-mode": "sync"}, {"preferred-mode": "bisync"}):
            with self.subTest(fields=fields):
                schema = {"settings": {"default": {"path-type": "file"}}, "tasks": {"test": [
                    {"name": "config", "sub-tasks": [{"name": "all", **fields}]},
                ]}}
                self.assertTrue(runner._validate_schema(schema))
        task = runner.SyncTask(path_type=runner.PathType.FILE)
        with self.assertRaises(ValueError):
            task.to_check_command("rclone")
        for mode in ("sync", "check", "bisync"):
            task.mode = mode
            with self.assertRaises(ValueError):
                task.to_command("rclone")

    def test_file_menu_highlights_copy_and_has_no_check(self) -> None:
        task = runner.SyncTask(name="appdata/config", path_type=runner.PathType.FILE)
        with patch.object(runner.Menu, "select", return_value=None) as select, contextlib.redirect_stdout(io.StringIO()):
            runner._select_action(task, None, None)
        options = select.call_args.args[0]
        self.assertEqual([option.value for option in options[:-1]], list(runner.FILE_ACTIONS))
        self.assertEqual([option.desc_color for option in options[:-1]], [runner.FLYellow] * 2 + [runner.FLCyan] * 2)
        self.assertEqual(options[-1].keys, ["Q"])
        self.assertTrue(select.call_args.kwargs["required"])
        self.assertNotIn("default_key", select.call_args.kwargs)

    def test_local_file_guard_rejects_directories_missing_sources_and_links(self) -> None:
        task = runner.SyncTask(path_type=runner.PathType.FILE, mode="copy", local_path="a.ini", remote_path="b.ini")
        regular = os.stat_result((runner.stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        directory = os.stat_result((runner.stat.S_IFDIR, 0, 0, 0, 0, 0, 0, 0, 0, 0))
        for metadata, accepted in (
            ([regular, regular], True), ([regular, FileNotFoundError()], True),
            ([directory], False), ([FileNotFoundError()], False),
            ([regular, directory], False), ([regular, PermissionError()], False),
        ):
            with self.subTest(accepted=accepted), patch.object(runner.os, "stat", side_effect=metadata), patch.object(runner.os.path, "islink", return_value=False):
                if accepted:
                    runner._validate_file_endpoints(task, "rclone", "push")
                else:
                    with self.assertRaises(ValueError):
                        runner._validate_file_endpoints(task, "rclone", "push")
        with patch.object(runner.os.path, "islink", return_value=True):
            with self.assertRaises(ValueError):
                runner._validate_file_endpoints(task, "rclone", "push")

    def test_remote_guard_handles_missing_objects_without_hiding_real_directories(self) -> None:
        task = runner.SyncTask(path_type=runner.PathType.FILE, mode="copy", local_path="a.ini", remote_path="backup:dir/a.ini")
        regular = os.stat_result((runner.stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
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
                stack.enter_context(patch.object(runner.os, "stat", return_value=regular))
                stack.enter_context(patch.object(runner.os.path, "islink", return_value=False))
                probe = stack.enter_context(patch.object(runner, "_run_interruptible", side_effect=[
                    subprocess.CompletedProcess([], code, output, "") for code, output in responses
                ]))
                if accepted:
                    runner._validate_file_endpoints(task, "rclone", "push")
                else:
                    with self.assertRaises(ValueError):
                        runner._validate_file_endpoints(task, "rclone", "push")
                self.assertIn("--stat", probe.call_args_list[0].args[0])
        with patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], 4, "", "")):
            with self.assertRaises(ValueError):
                runner._validate_file_endpoints(task, "rclone", "pull")

    def test_metadata_probes_ignore_filters_but_keep_config_flags(self) -> None:
        args = ["--config", "custom.conf", "--exclude", "*", "--include=*.ini", "--files-only", "--max-depth", "9"]
        self.assertEqual(runner._mode_specific_args(args, "stat"), ["--config", "custom.conf"])

    def test_remote_root_is_never_treated_as_a_missing_filename(self) -> None:
        regular = os.stat_result((runner.stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        for path in ("backup:", "backup:/", "backup:.", "backup:dir/.."):
            with self.subTest(path=path), patch.object(runner.os, "stat", return_value=regular), patch.object(runner.os.path, "islink", return_value=False), patch.object(runner, "_run_interruptible") as execute:
                task = runner.SyncTask(path_type=runner.PathType.FILE, mode="copy", local_path="a.ini", remote_path=path)
                with self.assertRaises(ValueError):
                    runner._validate_file_endpoints(task, "rclone", "push")
                execute.assert_not_called()

    def test_unc_endpoints_are_local_and_remote_file_mtimes_use_stat(self) -> None:
        regular = os.stat_result((runner.stat.S_IFREG, 0, 0, 0, 0, 0, 1, 0, 0, 0))
        task = runner.SyncTask(path_type=runner.PathType.FILE, mode="copy", local_path="a.ini", remote_path=r"\\server\share\b.ini")
        with patch.object(runner.os, "stat", return_value=regular), patch.object(runner.os.path, "islink", return_value=False), patch.object(runner, "_run_interruptible") as execute:
            runner._validate_file_endpoints(task, "rclone", "pull")
            execute.assert_not_called()
        result = subprocess.CompletedProcess([], 0, '{"IsDir": false, "ModTime": "2026-01-01T00:00:00Z"}', "")
        with patch.object(runner, "_run_interruptible", return_value=result) as execute:
            task.remote_path = "backup:b.ini"
            info = runner._get_remote_path_info(task, "rclone")
        self.assertEqual(info.mtime, runner.datetime.datetime(2026, 1, 1, tzinfo=runner.datetime.timezone.utc))
        self.assertEqual(execute.call_args.args[0], ["rclone", "lsjson", "backup:b.ini", "--stat"])

    def test_each_execution_is_guarded_and_failure_never_transfers(self) -> None:
        task = runner.SyncTask(path_type=runner.PathType.FILE)
        with patch.object(runner, "_validate_file_endpoints", side_effect=[None, ValueError("source changed to directory")]) as validate, patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0)) as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner._run_task_command(task, ["rclone", "copyto"], "rclone", "push").returncode, 0)
            self.assertEqual(runner._run_task_command(task, ["rclone", "copyto", "--dry-run"], "rclone", "push").returncode, 1)
        self.assertEqual(validate.call_count, 2)
        execute.assert_called_once()


class ModifiedTimeTests(unittest.TestCase):
    """Distinguish first sync, unreadable metadata, and optional time display."""

    def test_flag_defaults_false_inherits_and_does_not_change_commands(self) -> None:
        self.assertFalse(runner.SyncTask().do_not_check_modified_time)
        settings = {"default": {"do-not-check-modified-time": True}}
        parent = runner.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertTrue(parent.do_not_check_modified_time)
        child = parent.merge(runner.SyncTask.from_dict({"name": "sub", "do-not-check-modified-time": False}))
        self.assertFalse(child.do_not_check_modified_time)
        for comparison in runner.ComparisonMode:
            self.assertEqual(parent.to_command("rclone", comparison=comparison), child.to_command("rclone", comparison=comparison))
        for value in (0, "true", [], {}):
            with self.subTest(value=value):
                self.assertTrue(runner._validate_schema({"tasks": {"test": [{"name": "test", "do-not-check-modified-time": value}]}}))

    def test_local_absence_and_access_errors_have_different_states(self) -> None:
        for error, state in ((FileNotFoundError(), runner.PathState.MISSING), (PermissionError(), runner.PathState.UNKNOWN), (NotADirectoryError(), runner.PathState.UNKNOWN)):
            with self.subTest(error=type(error).__name__), patch.object(runner.os, "stat", side_effect=error):
                info = runner._get_local_path_info("local")
                self.assertEqual(info.state, state)
                self.assertIsNone(info.mtime)

    def test_remote_failures_are_not_assumed_to_be_first_sync(self) -> None:
        task = runner.SyncTask(path_type=runner.PathType.FILE, remote_path="backup:a.ini")
        for code, output, state in (
            (4, "", runner.PathState.MISSING), (3, "", runner.PathState.MISSING),
            (1, "", runner.PathState.UNKNOWN), (0, "invalid", runner.PathState.UNKNOWN),
            (0, "{}", runner.PathState.UNKNOWN),
            (0, '{"IsDir": false, "ModTime": 42}', runner.PathState.PRESENT),
            (0, '{"IsDir": false, "ModTime": "2026-01-01T00:00:00"}', runner.PathState.PRESENT),
        ):
            with self.subTest(code=code, output=output), patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], code, output, "private error detail")):
                info = runner._get_remote_path_info(task, "rclone")
                self.assertEqual(info.state, state)
                self.assertNotIn("private error detail", info.detail)
                self.assertIsNone(info.mtime)
        for error in (OSError(), subprocess.TimeoutExpired("rclone", 1)):
            with self.subTest(error=type(error).__name__), patch.object(runner, "_run_interruptible", side_effect=error):
                self.assertEqual(runner._get_remote_path_info(task, "rclone").state, runner.PathState.UNKNOWN)

    def test_empty_directories_are_not_confused_with_missing_prefixes(self) -> None:
        task = runner.SyncTask(remote_path="backup:parent/empty")
        for parent_output, code, state in (
            ('[{"Name": "empty", "IsDir": true}]', 0, runner.PathState.PRESENT),
            ("[]", 0, runner.PathState.MISSING),
            ("", 1, runner.PathState.UNKNOWN),
        ):
            responses = [
                subprocess.CompletedProcess([], 0, "[]", ""),
                subprocess.CompletedProcess([], 0, '{"IsDir": true}', ""),
                subprocess.CompletedProcess([], code, parent_output, ""),
            ]
            with self.subTest(state=state), patch.object(runner, "_run_interruptible", side_effect=responses):
                info = runner._get_remote_path_info(task, "rclone")
                self.assertEqual(info.state, state)
                self.assertIsNone(info.mtime)

    def test_directory_mtime_still_uses_latest_immediate_child(self) -> None:
        output = '[{"IsDir": false, "ModTime": "2026-01-01T00:00:00Z"}, {"IsDir": true, "ModTime": "2026-01-02T00:00:00Z"}]'
        with patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0, output, "")) as execute:
            info = runner._get_remote_path_info(runner.SyncTask(remote_path="backup:dir"), "rclone")
        self.assertEqual(info.mtime, runner.datetime.datetime(2026, 1, 2, tzinfo=runner.datetime.timezone.utc))
        execute.assert_called_once()
        self.assertIn("--max-depth", execute.call_args.args[0])

    def test_first_sync_display_depends_on_direction_and_confirmed_existence(self) -> None:
        present = runner.PathInfo(runner.PathState.PRESENT, runner.PathType.FILE)
        missing = runner.PathInfo(runner.PathState.MISSING)
        unknown = runner.PathInfo(runner.PathState.UNKNOWN, detail="access denied")
        task = runner.SyncTask(local_path="local", remote_path="remote", path_type=runner.PathType.FILE)
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
            with self.subTest(direction=direction, expected=expected), patch.object(runner, "_get_local_path_info", side_effect=[local, remote]), contextlib.redirect_stdout(io.StringIO()) as output:
                warnings = runner._display_path_mtimes(task, "rclone", direction)
                text = f"{output.getvalue()}\n{' '.join(warnings)}"
                self.assertIn(expected, text)
                self.assertEqual("First upload:" in text or "First download:" in text, first_transfer)
                self.assertNotIn("would overwrite newer", text)

    def test_file_type_guard_requests_no_modtime_and_cancellation_propagates(self) -> None:
        task = runner.SyncTask(local_path="local", remote_path="backup:a.ini", path_type=runner.PathType.FILE)
        present = runner.PathInfo(runner.PathState.PRESENT, runner.PathType.FILE)
        with patch.object(runner, "_get_local_path_info", return_value=present), patch.object(runner.os.path, "islink", return_value=False), patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0, '{"IsDir": false}', "")) as execute:
            runner._validate_file_endpoints(task, "rclone", "push")
        self.assertIn("--no-modtime", execute.call_args.args[0])
        with patch.object(runner, "_run_interruptible", side_effect=runner.OperationCancelled):
            with self.assertRaises(runner.OperationCancelled):
                runner._get_remote_path_info(task, "rclone")


class WorkflowTests(unittest.TestCase):
    """Verify confirmation and execution without launching real subprocesses."""

    def setUp(self) -> None:
        """Isolate environment, filesystem probes, and external execution."""

        def locate(command: object) -> bool:
            setattr(command, "path", "rclone")
            return True

        self.output = io.StringIO()
        self.enterContext(patch.dict(os.environ, {runner.ENV_SCHEMA_FILE: "schema.yaml"}, clear=True))
        self.enterContext(patch.object(runner.Environment, "check_commands", side_effect=locate))
        self.enterContext(patch.object(runner, "_detect_encrypted_config", return_value=False))
        self.enterContext(patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "rclone test", "")))
        self.enterContext(patch.object(runner.os.path, "isfile", return_value=True))
        self.enterContext(patch.object(runner.os.path, "exists", return_value=True))
        self.enterContext(patch.object(runner, "_get_local_path_info", return_value=runner.PathInfo(runner.PathState.PRESENT, runner.PathType.FILE)))
        self.run: MagicMock = self.enterContext(patch.object(runner, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0)))
        self.repair: MagicMock = self.enterContext(patch.object(runner, "_fix_windows_symlinkd"))
        self.enterContext(contextlib.redirect_stdout(self.output))

    def test_cli_requires_an_explicit_schema_instead_of_loading_the_sample(self) -> None:
        os.environ.pop(runner.ENV_SCHEMA_FILE)
        with patch.object(sys, "argv", ["runner", "--task", "test/demo"]), patch("builtins.open") as open_file:
            self.assertEqual(runner.main(), 1)
        self.assertIn("With --task, specify --schema-file", self.output.getvalue())
        self.assertIn("sample is documentation only", self.output.getvalue())
        open_file.assert_not_called()
        self.run.assert_not_called()

    def test_interactive_startup_has_no_bundled_schema_suggestion(self) -> None:
        os.environ.pop(runner.ENV_SCHEMA_FILE)
        schema = {"tasks": {"test": [{"name": "demo", "local-path": "local", "remote-path": "remote:"}]}}
        with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner.Input, "resolve_input_path", return_value="personal.yaml") as prompt, patch("builtins.input", return_value="q"):
            self.assertEqual(runner.main(), 0)
        self.assertEqual(prompt.call_args.args[0], "")
        self.run.assert_not_called()

    def test_cli_schema_takes_precedence_over_the_environment(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "local-path": "local", "remote-path": "remote:"}]}}
        with patch.object(sys, "argv", ["runner", "--schema-file", "chosen.yaml", "--task", "test/demo"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))) as open_file, patch("builtins.input", return_value="q"):
            self.assertEqual(runner.main(), 0)
        self.assertTrue(all(call.args[0] == os.path.abspath("chosen.yaml") for call in open_file.call_args_list))
        self.run.assert_not_called()

    def test_duplicate_keys_stop_loading_with_both_line_numbers(self) -> None:
        source = "tasks:\n  test:\n  - name: demo\n    local-path: first\n    local-path: second\n"
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push"]), patch("builtins.open", mock_open(read_data=source)):
            self.assertEqual(runner.main(), 1)
        output = self.output.getvalue()
        self.assertIn("duplicate YAML key 'local-path'", output)
        self.assertIn("line 4, column 5", output)
        self.assertIn("line 5, column 5", output)
        self.run.assert_not_called()

    def test_undefined_path_stops_before_host_or_operation_selection(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "local-path": "$MISSING/files", "remote-path": "remote:"}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "pull"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_interactive_host_swap") as hosts, patch.object(runner, "_select_action") as select:
            self.assertEqual(runner.main(), 1)
        self.assertIn("Path expansion failed for 'test/demo': local-path: Undefined environment variable: MISSING", self.output.getvalue())
        hosts.assert_not_called()
        select.assert_not_called()
        self.run.assert_not_called()

    def test_path_error_returns_to_menu_without_reloading_schema_or_password(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "local-path": "$MISSING/files", "remote-path": "remote:"}]}}
        with patch.object(sys, "argv", ["runner"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner.Input, "resolve_input_path", return_value="schema.yaml") as schema_path, patch.object(runner, "_load_schema", wraps=runner._load_schema) as load, patch.object(runner, "_verify_config_password", return_value=True) as verify, patch.dict(os.environ, {runner.ENV_CONFIG_PASSWORD: "test-password"}), patch("builtins.input", side_effect=["0", "q"]):
            self.assertEqual(runner.main(), 0)
        schema_path.assert_called_once()
        load.assert_called_once()
        verify.assert_called_once()
        self.run.assert_not_called()

    def test_substituted_variable_syntax_remains_literal_in_final_command(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "local-path": "$ROOT/files", "remote-path": "remote",
                                     "do-not-check-modified-time": True}]}}
        with patch.object(sys, "argv", ["runner", "--task", "test/demo", "--action", "push"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.dict(os.environ, {"ROOT": "${LITERAL}"}):
            self.assertEqual(runner.main(), 0)
        self.assertEqual(self.run.call_args.args[0][2], "${LITERAL}/files")

    def test_check_never_prechecks_or_repairs_links(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "preferred-mode": "move", "links": True,
                  "check-before-sync": True, "allow-actions": ["check"],
                  "sub-tasks": [{"name": "all", "local-path": "local", "remote-path": "remote"}]}]}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/demo", "--action", "check"]))
            stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "check", "local", "remote"])
        self.repair.assert_not_called()

    def test_standalone_file_task_resolves_cli_direction_and_checks_before_execution(self) -> None:
        schema = {"tasks": {"appdata": [{"name": "config", "path-type": "file",
                  "allow-actions": ["pull-copy-file"], "local-path": "a.ini", "remote-path": "b.ini"}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "appdata/config", "--pull"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_validate_file_endpoints") as validate:
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        validate.assert_called_once()
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][:4], ["rclone", "copyto", "b.ini", "a.ini"])
        self.assertIn("appdata/config", self.output.getvalue())
        self.assertNotIn("appdata/config/config", self.output.getvalue())

    def test_file_validation_failure_never_executes_in_auto_mode(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file",
                  "local-path": "a.ini", "remote-path": "b.ini"}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_validate_file_endpoints", side_effect=ValueError("source is a directory")):
            self.assertEqual(runner.main(), 1, self.output.getvalue())
        self.run.assert_not_called()
        self.assertIn("source is a directory", self.output.getvalue())

    def test_file_cli_print_only_does_not_probe_endpoints(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file",
                  "local-path": "a.ini", "remote-path": "b.ini"}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "pull-copy-file", "--dry-run"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_validate_file_endpoints") as validate:
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        validate.assert_not_called()
        self.run.assert_not_called()
        self.assertIn("copyto b.ini a.ini", self.output.getvalue())

    def test_time_display_can_be_disabled_without_disabling_file_safety_or_move_warning(self) -> None:
        schema = {"settings": {"default": {"do-not-check-modified-time": True}}, "tasks": {"test": [
            {"name": "config", "path-type": "file", "local-path": "a.ini", "remote-path": "b.ini"},
        ]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-move-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_display_path_mtimes") as display, patch.object(runner, "_validate_file_endpoints") as validate:
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        display.assert_not_called()
        validate.assert_called_once()
        self.run.assert_called_once()
        self.assertEqual(self.run.call_args.args[0][1], "moveto")
        self.assertNotIn("--ignore-times", self.run.call_args.args[0])
        self.assertIn("time check skipped by configuration", self.output.getvalue())
        self.assertIn("will delete local source files", self.output.getvalue())

    def test_false_subtask_flag_reenables_an_inherited_disabled_time_check(self) -> None:
        schema = {"settings": {"default": {"do-not-check-modified-time": True}}, "tasks": {"test": [
            {"name": "config", "local-path": "local", "remote-path": "remote", "sub-tasks": [
                {"name": "all", "do-not-check-modified-time": False},
            ]},
        ]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_display_path_mtimes", return_value=[]) as display:
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        display.assert_called_once()
        self.assertNotIn("time check skipped", self.output.getvalue())

    def test_disabling_time_display_does_not_disable_directory_precheck(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "local-path": "local", "remote-path": "remote",
                  "do-not-check-modified-time": True, "check-before-sync": True}]}}
        with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_display_path_mtimes") as display:
            self.assertEqual(runner.main(), 0, self.output.getvalue())
        display.assert_not_called()
        self.assertEqual([call.args[0][1] for call in self.run.call_args_list], ["check", "copy"])

    def test_first_upload_to_missing_file_still_executes_but_missing_source_does_not(self) -> None:
        schema = {"tasks": {"test": [{"name": "config", "path-type": "file", "local-path": "a.ini", "remote-path": "b.ini"}]}}
        present = runner.PathInfo(runner.PathState.PRESENT, runner.PathType.FILE)
        missing = runner.PathInfo(runner.PathState.MISSING)
        for source_missing, observations, code in (
            (False, [present, missing, present, missing], 0),
            (True, [missing, present, missing], 1),
        ):
            with self.subTest(source_missing=source_missing):
                self.run.reset_mock()
                self.output.seek(0)
                self.output.truncate(0)
                with patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/config", "--action", "push-copy-file"]), patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))), patch.object(runner, "_get_local_path_info", side_effect=observations), patch.object(runner.os.path, "islink", return_value=False):
                    self.assertEqual(runner.main(), code, self.output.getvalue())
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
                    {"name": "all", "local-path": "local", "remote-path": "primary:/files"},
                ]
                task: dict[str, object] = {"name": "demo", "sub-tasks": subtasks}
                if menu == "subtask":
                    subtasks.append({"name": "second", "local-path": "local", "remote-path": "primary:/files"})
                if menu == "host":
                    task["alternative-remote-host"] = ["backup"]
                schema = {"tasks": {"test": [task]}}
                argv = ["rclone-sync.py", "--task", "test/demo"] if cli_task else ["rclone-sync.py"]
                stack.enter_context(patch.object(sys, "argv", argv))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch.object(runner.Input, "resolve_input_path", return_value="schema.yaml"))
                prompt: MagicMock = stack.enter_context(patch("builtins.input", side_effect=answers))
                self.assertEqual(runner.main(), 0, self.output.getvalue())
                self.assertEqual(prompt.call_count, len(answers))
                output = self.output.getvalue()
                if menu == "host":
                    self.assertIn(f"{runner.FLYellow}test/demo/all{runner.CRst}:", output)
                elif menu == "subtask":
                    self.assertIn(f"Multiple sub-tasks of task {runner.FLYellow}test/demo{runner.CRst}", output)
                    self.assertTrue(any("Select sub-task for test/demo" in call.args[0] for call in prompt.call_args_list))
                    self.assertNotIn("test/demo/all", output)
                elif menu in ("operation", "comparison"):
                    self.assertIn(f"Task:{runner.CRst} {runner.FLCyan}test/demo/all{runner.CRst}", output)
                if not cli_task:
                    self.assertIn("Select task", prompt.call_args.args[0])
        self.run.assert_not_called()
        self.repair.assert_not_called()

    def test_task_labels_keep_group_prefix_and_handle_ungrouped_tasks(self) -> None:
        for group in ("appdata", "developer", runner.UNGROUPED_KEY):
            with self.subTest(group=group), contextlib.ExitStack() as stack:
                self.output.seek(0)
                self.output.truncate(0)
                label = "demo" if group == runner.UNGROUPED_KEY else f"{group}/demo"
                schema = {"tasks": {group: [{"name": "demo", "sub-tasks": [
                    {"name": "all", "local-path": "local", "remote-path": "remote"},
                ]}]}}
                stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", label, "--verbose"]))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch("builtins.input", side_effect=["check", "", "q"]))
                self.assertEqual(runner.main(), 0, self.output.getvalue())
                output = self.output.getvalue()
                self.assertIn(f"Selected: {label}{runner.CRst}", output)
                self.assertEqual(output.count(f"Task:{runner.CRst} {runner.FLCyan}{label}/all{runner.CRst}"), 2)
                self.assertIn(f"{runner.FLCyan}{label}/all{runner.CRst}", output.split("Rclone command:")[1])
                self.assertNotIn("None/demo", output)
                self.assertNotIn(f"{runner.UNGROUPED_KEY}/demo", output)
        self.run.assert_not_called()

    def test_confirmation_names_action_and_adds_directional_move_warning(self) -> None:
        schema = {"tasks": {"test": [{"name": "demo", "sub-tasks": [
            {"name": "all", "local-path": "local", "remote-path": "remote"},
        ]}]}}
        older = runner.datetime.datetime(2026, 1, 1, tzinfo=runner.datetime.timezone.utc)
        newer = runner.datetime.datetime(2026, 1, 2, tzinfo=runner.datetime.timezone.utc)
        for action, (mode, direction) in runner.ACTION_COMMANDS.items():
            with self.subTest(action=action), contextlib.ExitStack() as stack:
                self.output.seek(0)
                self.output.truncate(0)
                self.run.reset_mock()
                answers = iter(["", "   ", "invalid", "d", "q"])
                schema["tasks"]["test"][0]["path-type"] = "file" if action in runner.FILE_ACTIONS else "directory"

                def confirm(prompt: str) -> str:
                    print(prompt)
                    return next(answers)

                stack.enter_context(patch.object(sys, "argv", ["rclone-sync.py", "--task", "test/demo"]))
                stack.enter_context(patch("builtins.open", mock_open(read_data=yaml.safe_dump(schema))))
                stack.enter_context(patch.object(runner, "_select_action", return_value=action))
                stack.enter_context(patch.object(runner, "_select_comparison_mode", return_value=runner.ComparisonMode.CHECKSUM))
                stack.enter_context(patch.object(runner, "_validate_file_endpoints"))
                timestamps = [newer, older] if direction == "pull" else [older, newer]
                stack.enter_context(patch.object(runner, "_get_local_path_info", side_effect=[
                    runner.PathInfo(runner.PathState.PRESENT, mtime=timestamp) for timestamp in timestamps
                ]))
                prompt: MagicMock = stack.enter_context(patch("builtins.input", side_effect=confirm))
                self.assertEqual(runner.main(), 0, self.output.getvalue())

                self.assertEqual(prompt.call_count, 5)
                self.assertTrue(all(call == prompt.call_args_list[0] for call in prompt.call_args_list))
                self.assertIn(
                    f"Execute{runner.CRst} {runner.FLCyan}{action.value}{runner.CRst}{runner.FLYellow}?",
                    prompt.call_args.args[0],
                )
                output = self.output.getvalue()
                is_file = action in runner.FILE_ACTIONS
                self.assertEqual(output.count("WARNING:"), 5 * (int(direction is not None and is_file) + int(mode == "move")))
                self.assertEqual(output.count("NOTE: Directory timestamps"), 5 * int(direction is not None and not is_file))
                if direction is not None and not is_file:
                    self.assertIn("not guaranteed by directory times", output)
                    self.assertNotIn("would overwrite newer", output)
                screens = output.split("Rclone command:")[1:]
                self.assertEqual(len(screens), 5)
                for screen in screens:
                    self.assertIn(f"Task:{runner.CRst} {runner.FLCyan}test/demo/all{runner.CRst}", screen)
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
