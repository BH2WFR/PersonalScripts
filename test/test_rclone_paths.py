"""Focused rclone regression tests: paths.

Run: conda run -n base python -m unittest discover -s test -p "test_rclone*.py".
All sync/network subprocesses are mocked.
"""

import contextlib
import copy
import io
import os
from pathlib import Path
import subprocess
import shlex
import unittest
import tempfile
from typing import Protocol, cast
from unittest.mock import patch
from _rclone_test_support import ROOT, backend, endpoint_ops, execution, models, schema_ops, terminal, utility


class PathExpansionTests(unittest.TestCase):
    """Check strict one-pass expansion while preserving rclone path syntax."""

    def test_all_variable_spellings_expand_in_every_path_field(self) -> None:
        for reference in ("$ROOT", "${ROOT}", "%ROOT%", "$ENV:ROOT", "${ENV:ROOT}"):
            for field in ("local_path", "remote_path", "backup_dir", "log_file"):
                with self.subTest(reference=reference, field=field), patch.dict(os.environ, {"ROOT": "data root"}, clear=True):
                    task = schema_ops.SyncTask(**{field: f"{reference}/files"})
                    endpoint_ops.resolve_paths(task, 'schema', 'script')
                    self.assertEqual(getattr(task, field), "data root/files")

    def test_undefined_references_report_the_field_without_partial_updates(self) -> None:
        for reference in ("$MISSING", "${MISSING}", "%MISSING%", "$ENV:MISSING", "${ENV:MISSING}", "{{typo}}"):
            with self.subTest(reference=reference), patch.dict(os.environ, {"ROOT": "data"}, clear=True):
                task = schema_ops.SyncTask(local_path="$ROOT/source", remote_path=f"backup:{reference}/files")
                with self.assertRaisesRegex(ValueError, "remote-path: (Undefined environment variable|Unknown placeholder)"):
                    endpoint_ops.resolve_paths(task, 'schema', 'script')
                self.assertEqual(task.local_path, "$ROOT/source")
                self.assertEqual(task.remote_path, f"backup:{reference}/files")

    def test_inserted_values_are_not_expanded_or_rejected_as_variables(self) -> None:
        literal = "${MISSING}/$ENV:MISSING/%MISSING%/{{unknown}}"
        with patch.dict(os.environ, {"ROOT": literal}, clear=True):
            task = schema_ops.SyncTask(local_path="$ROOT/files", log_file="{{schema_dir}}/run.log")
            endpoint_ops.resolve_paths(task, literal, 'script')
        self.assertEqual(task.local_path, f"{literal}/files")
        self.assertEqual(task.log_file, f"{literal}/run.log")

    def test_placeholders_home_unc_and_remote_roots_keep_their_meaning(self) -> None:
        task = schema_ops.SyncTask(local_path="{{schema_dir}}/data", remote_path="backup:{{script_dir}}/data",
                               backup_dir="{{current_dir}}/old", log_file="~/run.log")
        with patch.object(os, "getcwd", return_value="cwd"):
            endpoint_ops.resolve_paths(task, 'schema', 'script')
        self.assertEqual(task.local_path, "schema/data")
        self.assertEqual(task.remote_path, "backup:script/data")
        self.assertEqual(task.backup_dir, "cwd/old")
        self.assertEqual(task.log_file, os.path.expanduser("~/run.log"))
        for path in (r"\\server\share\files", "//server/share/files", "C:/files", "relative/files",
                     "backup:~/files", ":local:/data", "/data/100% ready", "backup:"):
            with self.subTest(path=path):
                task = schema_ops.SyncTask(remote_path=path)
                endpoint_ops.resolve_paths(task, 'schema', 'script')
                self.assertEqual(task.remote_path, path)

    def test_windows_variable_lookup_is_case_insensitive(self) -> None:
        with patch.object(os, "name", "nt"), patch.dict(os.environ, {"ROOT": "data"}, clear=True):
            task = schema_ops.SyncTask(local_path="$root/files")
            endpoint_ops.resolve_paths(task, 'schema', 'script')
        self.assertEqual(task.local_path, "data/files")


class PathBatchTests(unittest.TestCase):
    """Validate the paths-only schema and ordered per-pair execution contracts."""

    def schema(self, paths: object) -> dict[str, object]:
        """Build a minimal schema with the supplied raw paths value."""
        return {"tasks": {"test": [{"name": "demo", "sub-tasks": [{"name": "all", "paths": paths}]}]}}

    def test_paths_require_objects_with_two_nonempty_endpoints(self) -> None:
        self.assertEqual(schema_ops._validate_schema(self.schema([
            {"path1": "local", "path2": "remote"}, {"path1": "other", "path2": "nas:other"},
        ])), [])
        for value in (None, [], "local", {}, [None], [[]], [["a"]], [["a", "b", "c"]],
                      [["", "b"]], [["a", "  "]], [[True, "b"]], [["a", 1]],
                      [{"local": "a", "remote": "b"}], [["a", "b"], ["c", None]],
                      [{"path1": "", "path2": "b"}], [{"path1": "a", "path2": "  "}],
                      [{"path1": True, "path2": "b"}], [{"path1": "a", "path2": 1}]):
            with self.subTest(value=value):
                errors = schema_ops._validate_schema(self.schema(value))
                self.assertTrue(errors)
                self.assertIn("sub-tasks[0]", errors[0])
                with self.assertRaises(ValueError):
                    schema_ops.SyncTask.from_dict({"paths": value})

    def test_paths_are_required_on_subtasks_only_and_legacy_keys_are_rejected(self) -> None:
        for field in ("local-path", "remote-path", "paths"):
            for scope in ("task", "profile", "subtask"):
                if field == "paths" and scope == "subtask":
                    continue
                with self.subTest(field=field, scope=scope):
                    profile: dict[str, object] = {}
                    sub: dict[str, object] = {"name": "all", "paths": [{"path1": "a", "path2": "b"}]}
                    task: dict[str, object] = {"name": "demo", "sub-tasks": [sub]}
                    target = {"task": task, "profile": profile, "subtask": sub}[scope]
                    target[field] = [{"path1": "a", "path2": "b"}] if field == "paths" else "old-path"
                    errors = schema_ops._validate_schema({"settings": {"default": profile}, "tasks": {"test": [task]}})
                    self.assertTrue(any(field in error for error in errors))
        for task in ({"name": "demo"}, {"name": "demo", "sub-tasks": []},
                     {"name": "demo", "sub-tasks": [{"name": "all"}]}):
            self.assertTrue(schema_ops._validate_schema({"tasks": {"test": [task]}}))
        with self.assertRaisesRegex(ValueError, "Legacy"):
            schema_ops.SyncTask.from_dict({"local-path": "a", "remote-path": "b"})

    def test_path_materialization_preserves_shared_options_without_merging_alternatives(self) -> None:
        settings = {"default": {"exclude": ["*.tmp"]}, "bulk": {"transfer": 24, "exclude": ["*.tmp", "*.bak"]}}
        parent = schema_ops.SyncTask.from_inheritance_chain(settings, {"name": "demo", "inherit": ["bulk"]})
        batch = parent.merge(schema_ops.SyncTask.from_dict({"name": "all", "paths": [{"path1": "a", "path2": "b"}, {"path1": "c", "path2": "d"}]}))
        batch = backend._task_for_action(batch, models.SyncAction.PULL_COPY)
        pairs = endpoint_ops.path_tasks(batch)
        self.assertEqual([backend.to_command(p, 'rclone', direction='pull')[:4] for p in pairs],
                         [["rclone", "copy", "b", "a"], ["rclone", "copy", "d", "c"]])
        for pair in pairs:
            self.assertEqual(pair.exclude, ["*.tmp", "*.bak"])
            self.assertEqual(pair.transfer, 24)
        pairs[0].exclude.append("unique")
        self.assertNotIn("unique", pairs[1].exclude)
        self.assertNotIn("unique", batch.exclude)
        replacement = batch.merge(schema_ops.SyncTask.from_dict({"paths": [{"path1": "x", "path2": "y"}]}))
        self.assertEqual([pair.endpoints for pair in replacement.paths], [("x", "y")])
        with self.assertRaisesRegex(ValueError, "Materialize"):
            backend.to_command(batch, 'rclone')

    def test_path_expansion_is_atomic_across_all_pairs_and_runs_once(self) -> None:
        raw = [{"path1": "$ROOT/a", "path2": "nas:backup"}, {"path1": "local", "path2": "$MISSING/b"}]
        task = schema_ops.SyncTask.from_dict({"paths": raw, "backup-dir": "$ROOT/old"})
        with patch.dict(os.environ, {"ROOT": "${LITERAL}"}, clear=True):
            with self.assertRaisesRegex(ValueError, r"paths\[1\]\.path2"):
                endpoint_ops.resolve_paths(task, 'schema', 'script')
            self.assertEqual([pair.endpoints for pair in task.paths], [(pair["path1"], pair["path2"]) for pair in raw])
            self.assertEqual(task.resolved_paths, [])
            self.assertEqual(task.backup_dir, "$ROOT/old")
            os.environ["MISSING"] = "destination"
            endpoint_ops.resolve_paths(task, 'schema', 'script')
        self.assertEqual([pair.endpoints for pair in task.resolved_paths], [("${LITERAL}/a", "nas:backup"), ("local", "destination/b")])
        self.assertEqual(endpoint_ops.path_tasks(task)[0].local_path, "${LITERAL}/a")
        empty = schema_ops.SyncTask.from_dict({"paths": [{"path1": "$EMPTY", "path2": "remote"}]})
        with patch.dict(os.environ, {"EMPTY": ""}), self.assertRaisesRegex(ValueError, "expanded path is empty"):
            endpoint_ops.resolve_paths(empty, 'schema', 'script')

    def test_host_selection_reuses_only_matching_prefix_and_cancels_atomically(self) -> None:
        task = schema_ops.SyncTask(name="test/demo/all", alternative_remote_hosts=["backup"], paths=[
            models.PathPairConfig("a", "primary:/a"), models.PathPairConfig("b", "primary:/b"),
            models.PathPairConfig("c", "other:/c"), models.PathPairConfig("d", r"\\server\share"),
        ])
        with patch("builtins.input", side_effect=["1", "0"]) as prompt, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(terminal._interactive_batch_hosts(task, False))
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual([pair.endpoints for pair in task.resolved_paths], [("a", "backup:/a"), ("b", "backup:/b"), ("c", "other:/c"), ("d", r"\\server\share")])
        before = list(task.resolved_paths)
        with patch("builtins.input", side_effect=["1", "q"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(terminal._interactive_batch_hosts(task, False))
        self.assertEqual(task.resolved_paths, before)

    def test_retry_skips_successful_pairs_and_drops_each_successful_resync_flag(self) -> None:
        batch = schema_ops.SyncTask(name="test/demo/all", mode="bisync", paths=[models.PathPairConfig("a", "b"), models.PathPairConfig("c", "d"), models.PathPairConfig("e", "f")])
        pairs = endpoint_ops.path_tasks(batch)
        commands = [backend.to_command(pair, 'rclone', resync=True) for pair in pairs]
        results = [subprocess.CompletedProcess([], code) for code in (0, 7, 0, 0)]
        with patch.object(execution, "_run_task_command", side_effect=results) as run, contextlib.redirect_stdout(io.StringIO()):
            code, start = execution._run_path_batch(pairs, commands, "rclone", "push")
            self.assertEqual((code, start), (7, 1))
            self.assertNotIn("--resync", commands[0])
            self.assertIn("--resync", commands[1])
            self.assertEqual(execution._run_path_batch(pairs, commands, "rclone", "push", start=start, precheck=False), (0, 3))
        self.assertEqual([call.args[0].local_path for call in run.call_args_list], ["a", "c", "c", "e"])
        self.assertTrue(all("--resync" not in cmd for cmd in commands))

    def test_prechecks_run_per_pair_and_failure_stops_before_transfer(self) -> None:
        batch = schema_ops.SyncTask(mode="copy", paths=[models.PathPairConfig("a", "b"), models.PathPairConfig("c", "d")],
                                check_before_sync=True, stop_on_check_failure=True)
        pairs = endpoint_ops.path_tasks(batch)
        commands = [backend.to_command(pair, 'rclone') for pair in pairs]
        with patch.object(backend, "_run_interruptible", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 8)]) as check, patch.object(execution, "_run_task_command", return_value=subprocess.CompletedProcess([], 0)) as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execution._run_path_batch(pairs, commands, "rclone", "push"), (8, 1))
            self.assertEqual([call.args[0][2:4] for call in check.call_args_list], [["a", "b"], ["c", "d"]])
            run.assert_called_once()
            self.assertEqual(execution._run_path_batch(pairs, commands, "rclone", "push", start=1, precheck=False), (0, 2))
            self.assertEqual(check.call_count, 2)

    def test_dry_run_does_not_consume_resync_state_or_repair_links(self) -> None:
        batch = schema_ops.SyncTask(mode="bisync", links=True, paths=[models.PathPairConfig("a", "b"), models.PathPairConfig("c", "d")])
        pairs = endpoint_ops.path_tasks(batch)
        commands = [backend.to_command(pair, 'rclone', resync=True) for pair in pairs]
        with patch.object(execution, "_run_task_command", return_value=subprocess.CompletedProcess([], 0)) as run, patch.object(execution, "_fix_windows_symlinkd") as repair, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execution._run_path_batch(pairs, commands, "rclone", "push", dry_run=True), (0, 2))
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all("--dry-run" in call.args[1] for call in run.call_args_list))
        self.assertTrue(all("--resync" in cmd and "--dry-run" not in cmd for cmd in commands))
        repair.assert_not_called()

    def test_cancel_and_process_launch_failure_never_start_remaining_pairs(self) -> None:
        batch = schema_ops.SyncTask(mode="copy", paths=[models.PathPairConfig("a", "b"), models.PathPairConfig("c", "d"), models.PathPairConfig("e", "f")])
        pairs = endpoint_ops.path_tasks(batch)
        for failure in (backend.OperationCancelled(), OSError("launch failed")):
            with self.subTest(failure=type(failure).__name__), patch.object(execution, "_run_task_command", side_effect=[subprocess.CompletedProcess([], 0), failure]) as run, contextlib.redirect_stdout(io.StringIO()):
                commands = [backend.to_command(pair, 'rclone') for pair in pairs]
                if isinstance(failure, backend.OperationCancelled):
                    with self.assertRaises(backend.OperationCancelled):
                        execution._run_path_batch(pairs, commands, "rclone", "push")
                else:
                    self.assertEqual(execution._run_path_batch(pairs, commands, "rclone", "push"), (1, 1))
                self.assertEqual(run.call_count, 2)


class _VolumeTaskFixture(Protocol):
    """Typed view of the dynamically imported runner's materialized test tasks."""

    local_path: str
    remote_path: str
    remote_path_type: str
    mode: str
    check_before_sync: bool
    volume_bindings: tuple[object | None, object | None]


class LocalVolumeEndpointTests(unittest.TestCase):
    """Resolve literal endpoints and reject unsafe volume changes before rclone runs."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="rclone-volume-", dir=ROOT / "tmp")
        self.addCleanup(self.directory.cleanup)
        self.mount = Path(self.directory.name).resolve()
        self.node = utility.DiskInfo(
            "/dev/example1", "volume", label="BACKUP", filesystem="exFAT",
            mounts=[str(self.mount)], identifiers={"Filesystem UUID": "id-1"},
        )
        self.scan = patch.object(utility.System, "scan_disks", return_value=utility.DiskScan([self.node])).start()
        self.addCleanup(patch.stopall)
        patch.object(os.path, "ismount", return_value=True).start()
        self.definitions = schema_ops._parse_local_volumes({"backup": {"label": "BACKUP", "filesystem": "exfat"}})

    def task(self, relative: str = "data", side: int = 1) -> _VolumeTaskFixture:
        """Build a directory copy task bound to a temporary fake mounted volume."""
        paths: list[object] = [str(self.mount / "source"), str(self.mount / "destination")]
        paths[side] = {"volume": "backup", "path": relative}
        batch = schema_ops.SyncTask.from_dict({"name": "demo", "paths": [{"path1": paths[0], "path2": paths[1]}]})
        batch.mode = "copy"
        endpoint_ops.resolve_paths(batch, 'schema', 'script', self.definitions)
        return cast(_VolumeTaskFixture, endpoint_ops.path_tasks(batch)[0])

    def test_literal_objects_preserve_special_characters_without_disk_queries(self) -> None:
        literal = "~/$HOME/%TEMP%/{{unknown}}/files[*]?"
        task = schema_ops.SyncTask.from_dict({"paths": [{"path1": {"path": literal}, "path2": {"path": "nas:${NOT_AN_ENV}"}}]})
        with patch.dict(os.environ, {}, clear=True):
            endpoint_ops.resolve_paths(task, 'schema', 'script')
        self.assertEqual([pair.endpoints for pair in task.resolved_paths], [(literal, "nas:${NOT_AN_ENV}")])
        self.scan.assert_not_called()

    def test_schema_validates_objects_aliases_and_selectors_without_scanning(self) -> None:
        def schema(endpoint: object, volumes: object) -> dict[str, object]:
            return {"local-volumes": volumes, "tasks": {"test": [{"name": "demo", "sub-tasks": [
                {"name": "all", "paths": [{"path1": "local", "path2": endpoint}]}]}]}}
        valid = {"backup": {"label": "BACKUP", "filesystem": "exfat"}}
        self.assertEqual(schema_ops._validate_schema(schema({"volume": "backup", "path": "."}, valid)), [])
        for endpoint in ({"volume": "unknown", "path": "x"}, {"volume": "backup"}, {"path": ""},
                         {"path": "x", "expand": True}, {"volume": None, "path": "x"}):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(schema_ops._validate_schema(schema(endpoint, valid)))
        for volumes in (None, [], {"backup": {"lable": "BACKUP"}}, {"backup": {"label": 123}},
                        {"backup": {"label": "BACKUP", "filesystem": None}}):
            with self.subTest(volumes=volumes):
                self.assertTrue(schema_ops._validate_schema(schema({"volume": "backup", "path": "x"}, volumes)))
        self.scan.assert_not_called()

    def test_volume_paths_are_literal_and_force_local_remote_classification(self) -> None:
        relative = "$HOME/%TEMP%/{{unknown}}/!data"
        task = self.task(relative)
        self.assertEqual(task.remote_path, str(self.mount.joinpath(*relative.split("/"))))
        self.assertEqual(task.remote_path_type, "local")
        self.assertEqual(getattr(task.volume_bindings[1], "alias"), "backup")
        self.assertEqual(backend.to_command(task, 'rclone')[:4], ["rclone", "copy", str(self.mount / "source"), task.remote_path])
        self.assertEqual(self.task(".").remote_path, str(self.mount))

    def test_absolute_and_traversal_paths_are_rejected_before_scanning(self) -> None:
        for relative in ("../data", "data/../other", "/absolute", "C:/data", "C:data", "//server/share", r"data\other"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                schema_ops.SyncTask.from_dict({"paths": [{"path1": "local", "path2": {"volume": "backup", "path": relative}}]})
        self.scan.assert_not_called()

    def test_missing_duplicate_unmounted_and_partial_inventory_fail_closed(self) -> None:
        duplicate = copy.deepcopy(self.node)
        duplicate.device = "/dev/other1"
        unmounted = copy.deepcopy(self.node)
        unmounted.mounts = []
        for inventory in (utility.DiskScan(), utility.DiskScan([self.node, duplicate]),
                          utility.DiskScan([unmounted]), utility.DiskScan([self.node], ["incomplete"])):
            with self.subTest(inventory=inventory):
                self.scan.return_value = inventory
                with self.assertRaises(ValueError):
                    self.task()

    def test_repeated_tree_nodes_are_one_volume_but_multiple_mounts_are_ambiguous(self) -> None:
        self.scan.return_value = utility.DiskScan([self.node, copy.deepcopy(self.node)])
        self.assertEqual(self.task().remote_path, str(self.mount / "data"))
        self.node.mounts.append(str(self.mount / "another-mount"))
        with self.assertRaisesRegex(ValueError, "mount point"):
            self.task()

    def test_swapped_removed_or_unmounted_volume_never_starts_rclone(self) -> None:
        task = self.task()
        replacement = copy.deepcopy(self.node)
        replacement.identifiers["Filesystem UUID"] = "id-2"
        for inventory in (utility.DiskScan(), utility.DiskScan([replacement])):
            self.scan.return_value = inventory
            with patch.object(backend, "_run_interruptible") as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(execution._run_task_command(task, ["rclone", "copy"], "rclone", "push").returncode, 1)
            run.assert_not_called()
        self.scan.return_value = utility.DiskScan([self.node])
        with patch.object(os.path, "ismount", return_value=False), self.assertRaises(ValueError):
            endpoint_ops._validate_volume_endpoints(task, "push")

    def test_readonly_ancestry_respects_operation_and_direction(self) -> None:
        task = self.task()
        disk = utility.DiskInfo("/dev/example", "disk", details={"Read-only": "True"}, children=[self.node])
        self.scan.return_value = utility.DiskScan([disk])
        with self.assertRaisesRegex(ValueError, "read-only"):
            endpoint_ops._validate_volume_endpoints(task, "push")
        endpoint_ops._validate_volume_endpoints(task, "pull")  # Copy source may be read-only.
        task.mode = "move"
        with self.assertRaisesRegex(ValueError, "read-only"):
            endpoint_ops._validate_volume_endpoints(task, "pull")
        task.mode = "check"
        endpoint_ops._validate_volume_endpoints(task, "push")

    def test_precheck_rechecks_before_transfer_and_retry(self) -> None:
        task = self.task()
        task.check_before_sync = True
        self.scan.side_effect = [utility.DiskScan([self.node]), utility.DiskScan()]
        with patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0)) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(execution._run_path_batch([task], [backend.to_command(task, 'rclone')], "rclone", "push"), (1, 0))
            self.assertEqual(run.call_count, 1)  # Pre-check only; disk removed before transfer.
        self.scan.side_effect = None
        self.scan.return_value = utility.DiskScan()
        with patch.object(backend, "_run_interruptible") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execution._run_path_batch([task], [backend.to_command(task, 'rclone')], "rclone", "push", precheck=False), (1, 0))
        run.assert_not_called()

    def test_realpath_escape_is_rejected(self) -> None:
        outside = str(self.mount.parent / "outside")
        with patch.object(Path, "resolve", return_value=Path(outside)):
            with self.assertRaisesRegex(ValueError, "escapes"):
                endpoint_ops._volume_path(str(self.mount), "data")


class PathObjectTests(unittest.TestCase):
    """Exercise per-pair schema switches and isolated temporary remote addresses."""

    def test_sample_schema_validates_without_disk_or_remote_access(self) -> None:
        with (ROOT / "tools/network/rclone-sync-schema-sample.yaml").open(encoding="utf-8") as stream:
            schema = schema_ops._load_schema(stream)
        with patch.object(utility.System, "scan_disks") as scan, patch.object(backend, "_run_interruptible") as run:
            self.assertEqual(schema_ops._validate_schema(schema), [])
        scan.assert_not_called()
        run.assert_not_called()

    def test_connection_string_previews_preserve_shell_quotes(self) -> None:
        remote = "dav,url='https://example.com/dav/$name/':dir"
        command = ["rclone", "copy", "local", remote]
        for platform in ("nt", "posix"):
            output = io.StringIO()
            with patch.object(os, "name", platform), contextlib.redirect_stdout(output):
                terminal._print_cmd(command)
            line = output.getvalue().splitlines()[1].removeprefix(utility.FGray).removesuffix(utility.CRst)
            if platform == "posix":
                self.assertEqual(shlex.split(line), command)
            else:
                self.assertEqual(line, "rclone copy local 'dav,url=''https://example.com/dav/$name/'':dir'")

    def test_objects_keep_literal_semantics_and_per_pair_options(self) -> None:
        task = schema_ops.SyncTask.from_dict({"paths": [
            {"path1": "$ROOT/data", "path2": {"path": "dav:$LITERAL"}, "enable-custom-webdav-host": True},
            {"path1": "other", "path2": "sftp:other"},
        ]})
        with patch.dict(os.environ, {"ROOT": "local"}, clear=True):
            endpoint_ops.resolve_paths(task, 'schema', 'script')
        self.assertEqual([pair.endpoints for pair in task.resolved_paths], [("local/data", "dav:$LITERAL"), ("other", "sftp:other")])
        self.assertEqual([pair.custom_host for pair in task.paths], [models.CustomHost.WEBDAV, None])
        self.assertEqual(task.paths[0].path1, "$ROOT/data")
        parent = schema_ops.SyncTask.from_dict({"additional-args": ["--stats", "1s"]})
        merged = parent.merge(task)
        self.assertEqual(merged.paths, task.paths)
        replaced = merged.merge(schema_ops.SyncTask.from_dict({"paths": [{"path1": "x", "path2": "y"}]}))
        self.assertEqual([pair.custom_host for pair in replaced.paths], [None])
        self.assertEqual(replaced.resolved_paths, [])
        with patch.dict(os.environ, {"ROOT": "local"}, clear=True):
            endpoint_ops.resolve_paths(merged, "schema", "script")
        self.assertEqual(endpoint_ops.path_tasks(merged)[0].additional_args, ["--stats", "1s"])

    def test_invalid_objects_and_switch_placement_fail_schema_validation(self) -> None:
        for entry in (
            {"path1": "a"}, {"path2": "b"}, {"path1": "a", "path2": "b", "path3": "c"},
            {"path1": "a", "path2": "b", "enable-custom-sftp-host": "true"},
            {"path1": "a", "path2": "b", "enable-custom-webdav-host": None},
            {"path1": "a", "path2": "b", "enable-custom-webdav-host": 1},
            {"path1": "a", "path2": "b", "enable-custom-webdav-host": True, "enable-custom-sftp-host": True},
        ):
            with self.subTest(entry=entry):
                schema = {"tasks": {"demo": [{"name": "task", "sub-tasks": [{"name": "all", "paths": [entry]}]}]}}
                self.assertTrue(schema_ops._validate_schema(schema))
                with self.assertRaises(ValueError):
                    schema_ops.SyncTask.from_dict({"paths": [entry]})
        schema = {"settings": {"default": {"enable-custom-sftp-host": True}}}
        self.assertTrue(schema_ops._validate_schema(schema))

    def test_local_destinations_cannot_enable_custom_remote_prompts(self) -> None:
        for path, storage in (("local", "auto"), ("C:/local", "auto"), ("nas:path", "local")):
            with self.subTest(path=path, storage=storage):
                task = schema_ops.SyncTask.from_dict({"remote-path-type": storage, "paths": [
                    {"path1": "source", "path2": path, "enable-custom-sftp-host": True},
                ]})
                with self.assertRaisesRegex(ValueError, "named rclone remote"):
                    endpoint_ops.resolve_paths(task, 'schema', 'script')

    def test_no_is_default_and_cli_or_disabled_switch_never_prompts(self) -> None:
        for enabled, cli, answers in ((True, False, [""]), (True, True, []), (False, False, [])):
            with self.subTest(enabled=enabled, cli=cli):
                task = schema_ops.SyncTask.from_dict({"paths": [
                    {"path1": "source", "path2": "nas:data", "enable-custom-sftp-host": enabled},
                ]})
                endpoint_ops.resolve_paths(task, 'schema', 'script')
                with patch("builtins.input", side_effect=answers) as prompt, contextlib.redirect_stdout(io.StringIO()):
                    self.assertTrue(terminal._interactive_custom_hosts(task, cli))
                self.assertEqual(prompt.call_count, len(answers))
                self.assertEqual([pair.endpoints for pair in task.resolved_paths], [("source", "nas:data")])

    def test_override_is_per_pair_after_alternative_remote_selection(self) -> None:
        task = schema_ops.SyncTask.from_dict({"alternative-remote-host": ["backup"], "paths": [
            {"path1": "source", "path2": "nas:data", "enable-custom-sftp-host": True},
            {"path1": "other", "path2": "nas:other", "enable-custom-sftp-host": True},
        ]})
        endpoint_ops.resolve_paths(task, 'schema', 'script')
        with patch("builtins.input", side_effect=["1", "Y", "192.0.2.10", ""]), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(terminal._interactive_batch_hosts(task, False))
            self.assertTrue(terminal._interactive_custom_hosts(task, False))
        self.assertEqual([pair.endpoints for pair in task.resolved_paths], [("source", "backup,host='192.0.2.10':data"), ("other", "backup:other")])
        self.assertEqual(task.paths[0].path2, "nas:data")

    def test_cancel_and_address_eof_do_not_commit_any_override(self) -> None:
        for last in ("Q", EOFError()):
            task = schema_ops.SyncTask.from_dict({"paths": [
                {"path1": "a", "path2": "nas:a", "enable-custom-sftp-host": True},
                {"path1": "b", "path2": "nas:b", "enable-custom-sftp-host": True},
            ]})
            original = list(task.paths)
            with patch("builtins.input", side_effect=["Y", "example.com", "Y", last]), contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(terminal._interactive_custom_hosts(task, False))
            self.assertEqual(task.paths, original)
            self.assertEqual(task.resolved_paths, [])

    def test_addresses_reject_credentials_and_wrong_formats(self) -> None:
        for backend, invalid in (
            (models.CustomHost.SFTP, ["", "user@example.com", "https://example.com", "example.com:22", "a,b", "a\nb"]),
            (models.CustomHost.WEBDAV, ["example.com", "ftp://example.com", "https://u:p@example.com", "https://example.com:99999", "http://example.com/?token=secret", "http://example.com/#fragment", "http://exa mple.com"]),
        ):
            for address in invalid:
                with self.subTest(backend=backend, address=address), self.assertRaises(ValueError):
                    endpoint_ops._custom_host_value(address, backend)
        self.assertEqual(endpoint_ops._custom_host_value("[2001:db8::1]", models.CustomHost.SFTP), "2001:db8::1")

    def test_quoted_webdav_url_survives_metadata_checks_pull_and_retry(self) -> None:
        url = "https://[2001:db8::1]:8443/dav/o'neil,$literal/"
        prefix = "dav,url='https://[2001:db8::1]:8443/dav/o''neil,$literal/':"
        task = schema_ops.SyncTask.from_dict({"check-before-sync": True, "paths": [
            {"path1": "local", "path2": "dav:dir/file.txt", "enable-custom-webdav-host": True},
        ]})
        endpoint_ops.resolve_paths(task, 'schema', 'script')
        with patch("builtins.input", side_effect=["Y", "bad-url", url]), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(terminal._interactive_custom_hosts(task, False))
        pair = endpoint_ops.path_tasks(task)[0]
        pair.mode = "copy"
        self.assertEqual(endpoint_ops._extract_remote_host(pair.remote_path), (prefix, "dav"))
        self.assertEqual(backend.to_command(pair, 'rclone', direction='pull')[2:4], [f"{prefix}dir/file.txt", "local"])
        with patch.object(backend, "_run_interruptible", return_value=subprocess.CompletedProcess([], 0, '[]', '')) as metadata:
            backend._find_remote_child(pair, "rclone", pair.remote_path, read_modtime=False)
        self.assertEqual(metadata.call_args.args[0][2], f"{prefix}dir")
        command = backend.to_command(pair, 'rclone')
        with patch.object(backend, "_run_interruptible", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 8), subprocess.CompletedProcess([], 0)]) as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(execution._run_path_batch([pair], [command], "rclone", "push"), (8, 0))
            self.assertEqual(execution._run_path_batch([pair], [command], "rclone", "push", precheck=False), (0, 1))
        self.assertTrue(all(f"{prefix}dir/file.txt" in call.args[0] for call in execute.call_args_list))



if __name__ == "__main__":
    unittest.main()
