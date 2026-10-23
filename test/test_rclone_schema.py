"""Focused rclone regression tests: schema.

Run: conda run -n base python -m unittest discover -s test -p "test_rclone*.py".
All sync/network subprocesses are mocked.
"""

import io
import unittest
import yaml
from _rclone_test_support import models, schema_ops


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
                    schema_ops._load_schema(stream)
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
        loaded = schema_ops._load_schema(io.StringIO(source))
        self.assertEqual(loaded, yaml.safe_load(source))
        self.assertEqual(loaded["task"], {"name": "task", "transfer": 8})

    def test_duplicate_keys_inside_merge_sources_are_also_rejected(self) -> None:
        for source in (
            "task: {<<: {transfer: 4, transfer: 8}}",
            "task: {<<: [{transfer: 4}, {name: first, name: second}]}",
        ):
            with self.subTest(source=source), self.assertRaisesRegex(yaml.YAMLError, "duplicate YAML key"):
                schema_ops._load_schema(io.StringIO(source))

    def test_empty_unsafe_and_malformed_documents(self) -> None:
        self.assertIsNone(schema_ops._load_schema(io.StringIO("")))
        for source in ("name: [", "!!python/object:builtins.object {}", "? [a, b]\n: value"):
            with self.subTest(source=source), self.assertRaises(yaml.YAMLError):
                schema_ops._load_schema(io.StringIO(source))
        # The strict loader must not change other tools' PyYAML behavior.
        self.assertEqual(yaml.safe_load("value: 1\nvalue: 2"), {"value": 2})


class InheritanceTests(unittest.TestCase):
    """Check reference chains and precedence through actual schema resolution."""

    def test_cycles_are_rejected_when_loading_unused_profiles(self) -> None:
        for settings, chain in (
            ({"a": {"inherit": ["a"]}}, "a -> a"),
            ({"a": {"inherit": ["b"]}, "b": {"inherit": ["a"]}}, "a -> b -> a"),
            ({"default": {"inherit": ["a"]}, "a": {"inherit": ["default"]}}, "default -> a -> default"),
        ):
            with self.subTest(chain=chain):
                errors = schema_ops._validate_schema({"settings": settings, "tasks": {}})
                self.assertTrue(any(chain in error for error in errors), errors)
                with self.assertRaisesRegex(ValueError, chain):
                    schema_ops._resolve_profile_chain(settings, next(iter(settings)))

    def test_shared_parent_is_reapplied_and_excludes_stay_unique(self) -> None:
        settings = {
            "base": {"transfer": 8, "exclude": ["*.tmp"]},
            "left": {"inherit": ["base"], "transfer": 24, "exclude": ["*.bak"]},
            "right": {"inherit": ["base"], "exclude": ["*.tmp", "*.log"]},
        }
        task = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["left", "right"]})
        self.assertEqual(task.transfer, 8)
        self.assertEqual(task.exclude, ["*.tmp", "*.bak", "*.log"])
        self.assertEqual(schema_ops._validate_schema({"settings": settings, "tasks": {}}), [])

    def test_repeated_profile_and_explicit_fields_keep_list_precedence(self) -> None:
        settings = {"a": {"preferred-mode": "copy"}, "b": {"preferred-mode": "move"}}
        task = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test", "inherit": ["a", "b", "a"]})
        self.assertEqual(task.preferred_mode, "copy")
        sub = schema_ops.SyncTask.from_dict({"name": "sub", "inherit": ["a", "b"], "preferred-mode": "sync"})
        self.assertEqual(sub.resolve_profiles(settings).preferred_mode, "sync")

    def test_default_inheritance_and_depth_limit(self) -> None:
        settings = {"default": {"inherit": ["base"]}, "base": {"preferred-mode": "move"}}
        task = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "test"})
        self.assertEqual(task.preferred_mode, "move")
        deep = {f"p{i}": {"inherit": [f"p{i + 1}"]} for i in range(models.MAX_INHERIT_DEPTH + 2)}
        deep[f"p{models.MAX_INHERIT_DEPTH + 2}"] = {}
        with self.assertRaisesRegex(ValueError, "depth exceeded"):
            schema_ops._resolve_profile_chain(deep, "p0")

    def test_bad_references_and_types_at_each_level(self) -> None:
        for inherit in (["missing"], [5], {"profile": "base"}):
            for scope in ("profile", "task", "subtask"):
                with self.subTest(inherit=inherit, scope=scope):
                    profile: dict[str, object] = {}
                    sub: dict[str, object] = {"name": "sub", "paths": [{"path1": "local", "path2": "remote"}]}
                    task: dict[str, object] = {"name": "task", "sub-tasks": [sub]}
                    target = {"profile": profile, "task": task, "subtask": sub}[scope]
                    target["inherit"] = inherit
                    self.assertTrue(schema_ops._validate_schema({"settings": {"base": profile}, "tasks": {"test": [task]}}))



if __name__ == "__main__":
    unittest.main()
