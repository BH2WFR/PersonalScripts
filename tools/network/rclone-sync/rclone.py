"""Rclone commands, metadata queries, file guards, and cancellable subprocesses.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import os
import subprocess
import dataclasses
import json
import datetime
import stat
from typing import Optional, Any
from . import endpoints as endpoint_ops
from . import models
from . import schema as schema_ops
from utils import *


def source_dest(task: schema_ops.SyncTask, direction: str = "push") -> tuple[str, str]:
    """Return source/destination paths after applying the requested direction.

    Args:
        task: Materialized task with concrete local and remote endpoints.
        direction: Push by default; pull reverses directional transfer endpoints.

    Returns:
        Source and destination strings without changing the task.
    """
    src, dst = task.local_path, task.remote_path
    if direction == "pull" and (task.mode or task.preferred_mode or "sync") in models._DIRECTIONAL_MODES:
        src, dst = dst, src
    return src, dst


def _append_filter_flags(task: schema_ops.SyncTask, cmd: list[str]) -> None:
    """Append flags shared by sync/copy/move/check."""
    # copyto/moveto select one exact file and reject additional file filters.
    if task.path_type != models.PathType.FILE:
        for pat in task.exclude:
            cmd.extend(["--exclude", pat])
    if task.links:
        cmd.append("--links")
    if task.copy_links:
        cmd.append("--copy-links")
    if task.ignore_case and task.path_type != models.PathType.FILE:
        cmd.append("--ignore-case")
    if task.ignore_case_sync:
        cmd.append("--ignore-case-sync")


def ignored_file_filter_flags(task: schema_ops.SyncTask) -> list[str]:
    """Return ignored file-selection option names for the confirmation warning.

    Args:
        task: Materialized task whose configured filters are inspected.

    Returns:
        Unique flags in configuration order, or an empty list for directory
        tasks. Includes inherited YAML excludes and additional-args filters.
        Does not change task configuration or print anything.
    """
    if task.path_type != models.PathType.FILE:
        return []
    ignored: list[str] = []
    if task.exclude:
        ignored.append("--exclude")
    if task.ignore_case:
        ignored.append("--ignore-case")
    # Both exact-file commands have the same filtering restrictions.
    _mode_specific_args(task.additional_args, "copyto", ignored_filters=ignored)
    return list(dict.fromkeys(ignored))


def _append_log_flags(task: schema_ops.SyncTask, cmd: list[str]) -> None:
    """Append rclone logging flags."""
    if task.log_file:
        cmd.extend(["--log-file", task.log_file])
    if task.log_level:
        cmd.extend(["--log-level", task.log_level])


def _append_comparison_and_transfer_flags(
    task: schema_ops.SyncTask,
    cmd: list[str],
    is_data: bool,
    comparison: Optional[models.ComparisonMode] = None,
) -> None:
    """Append comparison, bandwidth, retry, and related transfer flags."""
    if task.mode == "check":
        if comparison is models.ComparisonMode.SIZE_ONLY or (comparison is None and task.size_only):
            cmd.append("--size-only")
    elif task.mode == "bisync" and comparison is not None:
        cmd.extend(["--compare", models.BISYNC_COMPARE_VALUES[comparison]])
    elif is_data:
        if comparison is None:
            if task.ignore_times:
                cmd.append("--ignore-times")
            if task.checksum:
                cmd.append("--checksum")
        elif comparison is models.ComparisonMode.FORCE:
            cmd.append("--ignore-times")
        elif comparison is models.ComparisonMode.CHECKSUM:
            cmd.append("--checksum")
        elif comparison is models.ComparisonMode.SIZE_ONLY:
            cmd.append("--size-only")
        if comparison is None and task.size_only:
            cmd.append("--size-only")
    if is_data:
        if (
            task.mode in models._DIRECTIONAL_MODES
            and comparison in (None, models.ComparisonMode.SIZE_AND_TIME) and task.update
        ):
            cmd.append("--update")
        if task.bwlimit:
            cmd.extend(["--bwlimit", task.bwlimit])
        if task.ignore_errors:
            cmd.append("--ignore-errors")
    if is_data or task.mode == "check":
        if task.retries != 3:
            cmd.extend(["--retries", str(task.retries)])


def _append_backend_flags(task: schema_ops.SyncTask, cmd: list[str]) -> None:
    """Append backend-specific flags supported by the YAML schema."""
    if task.s3_no_check_bucket:
        cmd.append("--s3-no-check-bucket")


def to_command(
    task: schema_ops.SyncTask,
    rclone_exe: str,
    dry_run: bool = False,
    direction: str = "push",
    comparison: Optional[models.ComparisonMode] = None,
    resync: bool = False,
) -> list[str]:
    """Build the rclone command line list for this task.

    An unset runtime mode uses preferred-mode, or sync for directories and
    copy for files when no preference is set. File tasks
    map copy/move to copyto/moveto. Permissions also apply to this API.
    File-selection filters are omitted for exact-file transfers; use
    ignored_file_filter_flags() to obtain the options for a user warning.

    Args:
        task: Materialized task containing one pair and shared transfer options.
        rclone_exe: Executable path or command name.
        dry_run: Append --dry-run when True; defaults to False.
        direction: Push (local to remote) by default, or pull (remote to local).
        comparison: Optional runtime strategy overriding configured comparison
            flags. Check supports size/checksum; bisync excludes force.
        resync: Explicitly initialize/rebuild bisync state; defaults to False.

    Returns:
        Argument list ready for subprocess execution. Does not start a process.

    Raises:
        ValueError: Task is an unresolved batch, action is disallowed, or the
            direction, comparison, pre-check, or resync is incompatible.
    """
    if task.paths:
        raise ValueError("Materialize sub-task paths with path_tasks() before building a single command")
    if not task.mode:
        default_mode = task.preferred_mode or ("copy" if task.path_type == models.PathType.FILE else "sync")
        return to_command(dataclasses.replace(task, mode=default_mode), rclone_exe, dry_run=dry_run, direction=direction, comparison=comparison, resync=resync)
    if direction not in models.VALID_DIRECTIONS:
        raise ValueError(f"Unknown direction '{direction}'")
    selected = next((
        action for action in _available_actions(task)
        if models.ACTION_COMMANDS[action] == (
            task.mode, direction if task.mode in models._DIRECTIONAL_MODES else None,
        )
    ), None)
    if selected is None:
        raise ValueError(f"Task does not allow mode '{task.mode}' with direction '{direction}'")
    if task.path_type == models.PathType.FILE and task.check_before_sync:
        raise ValueError("'check-before-sync' is not supported for file tasks")
    if comparison is not None and comparison not in models.MODE_COMPARISONS[task.mode]:
        raise ValueError(f"Comparison '{comparison.value}' is not supported by '{task.mode}'")
    if resync and task.mode != "bisync":
        raise ValueError("--resync requires the bisync action")
    src, dst = source_dest(task, direction)
    command_mode = f"{task.mode}to" if task.path_type == models.PathType.FILE else task.mode
    cmd = [rclone_exe, command_mode, src, dst]
    is_data = task.mode in models._DATA_MODES

    if is_data and task.progress:
        cmd.append("-P")
    if is_data and task.transfer != 4:
        cmd.extend(["--transfers", str(task.transfer)])
    _append_filter_flags(task, cmd)
    _append_comparison_and_transfer_flags(task, cmd, is_data, comparison)
    if task.mode in models._DIRECTIONAL_MODES and task.backup_dir:
        cmd.extend(["--backup-dir", task.backup_dir])
    if task.mode == "sync" and task.max_delete_count is not None:
        cmd.extend(["--max-delete", str(task.max_delete_count)])
    if task.mode == "bisync" and task.max_delete_percent is not None:
        cmd.extend(["--max-delete", str(task.max_delete_percent)])
    if task.mode == "sync" and task.delete_excluded:
        cmd.append("--delete-excluded")
    _append_backend_flags(task, cmd)
    _append_log_flags(task, cmd)
    additional_args = (
        task.additional_args
        if comparison is None
        else _without_comparison_args(task.additional_args)
    )
    cmd.extend(_mode_specific_args(additional_args, command_mode))
    if resync:
        cmd.append("--resync")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def to_check_command(task: schema_ops.SyncTask, rclone_exe: str, direction: str = "push") -> list[str]:
    """Build an rclone check command for pre-transfer validation.

    Args:
        task: Materialized directory task with pre-check options.
        rclone_exe: Executable path or command name.
        direction: Push by default, or pull to reverse the endpoints.

    Returns:
        Argument list; does not run the check or modify the task.

    Raises:
        ValueError: Task targets a single file, which does not support check.
    """
    if task.path_type == models.PathType.FILE:
        raise ValueError("File tasks do not support check")
    src, dst = task.local_path, task.remote_path
    if direction == "pull":
        src, dst = dst, src
    cmd = [rclone_exe, "check", src, dst]
    _append_filter_flags(task, cmd)
    if task.check_before_sync == "size-only":
        cmd.append("--size-only")
    if task.mode in {"copy", "move"}:
        cmd.append("--one-way")
    _append_comparison_and_transfer_flags(task, cmd, False)
    _append_backend_flags(task, cmd)
    _append_log_flags(task, cmd)
    return cmd


def _comparison_arg_mode(arg: str) -> Optional[models.ComparisonMode]:
    """Return the comparison mode represented by one rclone argument."""
    stripped = arg.strip().partition("=")[0]
    if stripped in {"-I", "--ignore-times"}:
        return models.ComparisonMode.FORCE
    if stripped in {"-c", "--checksum"}:
        return models.ComparisonMode.CHECKSUM
    if stripped == "--size-only":
        return models.ComparisonMode.SIZE_ONLY
    return None


def _comparison_arg_enabled(arg: str) -> bool:
    """Return whether a recognized boolean comparison argument is enabled."""
    _, separator, raw_value = arg.strip().partition("=")
    if not separator:
        return True
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


def _without_comparison_args(args: list[str]) -> list[str]:
    """Remove runtime-selectable comparison flags from an argument list."""
    result: list[str] = []
    tokens = iter(args)
    for arg in tokens:
        flag, separator, _ = arg.partition("=")
        if flag == "--compare":
            if not separator:
                next(tokens, None)
        elif _comparison_arg_mode(arg) is None:
            result.append(arg)
    return result


def _mode_specific_args(
    args: list[str], mode: str, *, ignored_filters: Optional[list[str]] = None,
) -> list[str]:
    """Drop known command-specific extra flags when switching action modes.

    Value-taking flags consume their following token even when omitted.
    Unrecognized flags are left for rclone to validate.
    copyto/moveto ignore file-selection filters like stat, and apply their
    copy/move rules to other options. If supplied, ignored_filters collects
    the removed filter option names for the caller's warning.
    """
    exact_file = mode in {"copyto", "moveto"}
    if exact_file:
        mode = mode[:-2]
    rules: dict[str, tuple[set[str], bool]] = {
        "--delete-excluded": ({"sync"}, False),
        "--delete-before": ({"sync"}, False),
        "--delete-during": ({"sync"}, False),
        "--delete-after": ({"sync"}, False),
        "--max-delete": ({"sync", "bisync"}, True),
        "--backup-dir": (models._DIRECTIONAL_MODES, True),
        "--resync": ({"bisync"}, False),
        "--resync-mode": ({"bisync"}, True),
        "--filters-file": ({"bisync"}, True),
        "--workdir": ({"bisync"}, True),
        "--backup-dir1": ({"bisync"}, True),
        "--backup-dir2": ({"bisync"}, True),
        "--conflict-resolve": ({"bisync"}, True),
        "--conflict-loser": ({"bisync"}, True),
        "--conflict-suffix": ({"bisync"}, True),
        "--check-sync": ({"bisync"}, True),
        "--check-access": ({"bisync"}, False),
        "--recover": ({"bisync"}, False),
        "--resilient": ({"bisync"}, False),
        "--one-way": ({"check"}, False),
        "--download": ({"check"}, False),
        "--update": (models._DIRECTIONAL_MODES, False),
        "-u": (models._DIRECTIONAL_MODES, False),
    }
    result: list[str] = []
    tokens = iter(args)
    for arg in tokens:
        flag, separator, _ = arg.partition("=")
        # Cobra accepts attached short-option values such as -f-*.bak.
        if arg.startswith("-f") and not arg.startswith("--") and len(arg) > 2:
            flag, separator = "-f", "="
        if (mode == "stat" or exact_file) and (
            flag in models.METADATA_FILTER_FLAGS or (exact_file and flag == "--filters-file")
        ):
            if exact_file and ignored_filters is not None:
                ignored_filters.append(flag)
            if not separator:
                next(tokens, None)
            continue
        if mode == "stat" and flag in {"--dirs-only", "--files-only"}:
            continue
        if exact_file and flag in {"--ignore-case", "--dirs-only", "--files-only"}:
            if ignored_filters is not None:
                ignored_filters.append(flag)
            continue
        rule = rules.get(flag)
        if rule is not None and mode not in rule[0]:
            if rule[1] and not separator:
                next(tokens, None)
            continue
        result.append(arg)
    return result


def _configured_comparison_modes(task: schema_ops.SyncTask) -> set[models.ComparisonMode]:
    """Return comparison modes enabled by resolved YAML fields and arguments."""
    modes: set[models.ComparisonMode] = set()
    if task.ignore_times:
        modes.add(models.ComparisonMode.FORCE)
    if task.checksum:
        modes.add(models.ComparisonMode.CHECKSUM)
    if task.size_only:
        modes.add(models.ComparisonMode.SIZE_ONLY)
    for arg in task.additional_args:
        mode = _comparison_arg_mode(arg)
        if mode is not None and _comparison_arg_enabled(arg):
            modes.add(mode)
    if task.mode == "bisync":
        tokens = iter(task.additional_args)
        for arg in tokens:
            flag, separator, value = arg.partition("=")
            if flag != "--compare":
                continue
            if not separator:
                value = next(tokens, "")
            attributes = {part.strip() for part in value.split(",")}
            selected = next((
                mode for mode, compare_value in models.BISYNC_COMPARE_VALUES.items()
                if attributes == set(compare_value.split(","))
            ), None)
            if selected is None:
                raise ValueError(f"Configured --compare '{value}' needs an explicit --comparison choice")
            modes = {selected}
    return modes


def _get_config_file(rclone_exe: str) -> str:
    """Ask rclone for the effective configuration path without reading its contents.

    Args:
        rclone_exe: Executable path or command name; inherits RCLONE_CONFIG.

    Returns:
        Absolute configuration path, which may not exist yet.

    Raises:
        ValueError: Rclone fails or does not report an absolute path.
        OSError: The subprocess cannot start.
        subprocess.TimeoutExpired: The query exceeds ten seconds.
        OperationCancelled: The user cancels the query.

    Side effects:
        Runs rclone config file with password prompting disabled.
    """
    result = _run_interruptible(
        [rclone_exe, "config", "file", "--ask-password=false"],
        capture_output=True, timeout=10,
    )
    lines = (result.stdout or "").strip().splitlines()
    if result.returncode != 0:
        raise ValueError(f"Could not query the rclone configuration path (exit code {result.returncode})")
    if not lines or not os.path.isabs(lines[-1]):
        raise ValueError("Rclone did not report a configuration file path")
    return lines[-1]


def _detect_encrypted_config(rclone_exe: str) -> bool:
    """Run ``rclone config`` briefly; return True if it asks for a password."""
    try:
        proc = subprocess.Popen(
            [rclone_exe, "config"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return "Enter configuration password:" in (out or "")
    except Exception:
        return False


def _verify_config_password(rclone_exe: str) -> bool:
    """Return True if the current RCLONE_CONFIG_PASS is valid.

    Runs ``rclone config show``; a wrong password produces ``Couldn't decrypt``
    or ``unable to decrypt`` on stderr, and a missing password still prompts
    ``Enter configuration password:``.
    """
    try:
        proc = subprocess.run(
            [rclone_exe, "config", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (proc.stdout + proc.stderr).lower()
        if "couldn't decrypt" in output or "unable to decrypt" in output:
            return False
        if "enter configuration password:" in output:
            return False
        return True
    except Exception:
        return False


class OperationCancelled(Exception):
    """Raised when the user cancels the current rclone operation with Ctrl+C."""


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    """Terminate a running child process, escalating to kill if needed."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_interruptible(
    cmd: list[str],
    *,
    capture_output: bool = False,
    text: bool = True,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and convert Ctrl+C into a menu-level cancellation.

    Args:
        cmd: Command and arguments to execute.
        capture_output: Capture stdout and stderr when True; otherwise inherit
            the current console streams.
        text: Decode captured streams as text when True.
        timeout: Optional maximum number of seconds to wait.

    Returns:
        Completed process object with return code and optional captured output.

    Raises:
        OperationCancelled: If the user presses Ctrl+C while the process is
            running.  The child process is terminated before raising.
        subprocess.TimeoutExpired: If *timeout* expires.
        OSError: If the process cannot be started.

    Side effects:
        Starts a child process and may print a cancellation message.
    """
    stdout = subprocess.PIPE if capture_output else None
    stderr = subprocess.PIPE if capture_output else None
    popen_kwargs: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "text": text,
    }
    if text:
        popen_kwargs["encoding"] = "utf-8"
        popen_kwargs["errors"] = "replace"
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except KeyboardInterrupt as exc:
        _terminate_process(proc)
        print(f"\n{FLYellow}Cancelled current operation.{CRst}")
        raise OperationCancelled from exc
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _get_local_path_info(path: str, read_modtime: bool = True) -> models.PathInfo:
    """Inspect local/UNC metadata without confusing absence with access errors.

    Args:
        path: Local file or directory to inspect.
        read_modtime: Include its timezone-aware UTC modification time if true.

    Returns:
        Existence, type and optional time; only FileNotFoundError means missing.

    Side effects:
        Reads filesystem metadata, following source links as os.stat normally does.
    """
    try:
        metadata = os.stat(path)
    except FileNotFoundError:
        return models.PathInfo(models.PathState.MISSING)
    except OSError as exc:
        return models.PathInfo(models.PathState.UNKNOWN, detail=f"filesystem error: {exc.strerror or type(exc).__name__}")
    path_type = (
        models.PathType.FILE if stat.S_ISREG(metadata.st_mode) else
        models.PathType.DIRECTORY if stat.S_ISDIR(metadata.st_mode) else None
    )
    mtime = datetime.datetime.fromtimestamp(metadata.st_mtime, tz=datetime.timezone.utc) if read_modtime else None
    return models.PathInfo(models.PathState.PRESENT, path_type, mtime)


def _read_remote_metadata(
    task: schema_ops.SyncTask, rclone_exe: str, path: str, *, stat_only: bool,
    read_modtime: bool = True, timeout: int = models.FILE_STAT_TIMEOUT,
) -> object:
    """Read unfiltered rclone metadata using the task's backend/config flags.

    Args:
        task: Supplies backend/config flags, but not transfer filters.
        rclone_exe: Rclone executable.
        path: Exact remote path or parent being listed.
        stat_only: Request one entry with --stat, rather than immediate children.
        read_modtime: False adds --no-modtime for existence/type-only checks.
        timeout: Maximum query duration in seconds.

    Returns:
        Parsed JSON; callers validate the expected object/list shape.

    Raises:
        FileNotFoundError: Rclone explicitly reports a missing file/directory.
        ValueError: Query failure or invalid JSON; diagnostics never include stderr.
        OperationCancelled: The user cancels the query.

    Side effects:
        Runs read-only rclone lsjson requests; never transfers file contents.
    """
    cmd = [rclone_exe, "lsjson", path, *(["--stat"] if stat_only else ["--max-depth", "1"])]
    _append_backend_flags(task, cmd)
    if task.copy_links:
        cmd.append("--copy-links")
    # Retain backend/config flags while dropping transfer-only mode options.
    cmd.extend(_mode_specific_args(_without_comparison_args(task.additional_args), "stat"))
    if not read_modtime:
        cmd.append("--no-modtime")
    try:
        proc = _run_interruptible(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("metadata query timed out") from exc
    except OSError as exc:
        raise ValueError("cannot run rclone metadata query") from exc
    if proc.returncode in models.RCLONE_NOT_FOUND_CODES:
        raise FileNotFoundError("remote path not found")
    if proc.returncode != 0:
        raise ValueError(f"rclone metadata query failed (exit {proc.returncode})")
    try:
        return json.loads(proc.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid rclone metadata JSON") from exc


def _remote_entry_info(item: object, read_modtime: bool = True) -> models.PathInfo:
    """Parse one lsjson entry; reject malformed types, tolerate unavailable times.

    Args:
        item: Decoded rclone metadata object.
        read_modtime: Whether to parse the optional ModTime field.

    Returns:
        Confirmed endpoint type and optional timezone-aware modification time.

    Raises:
        ValueError: The object does not identify a file or directory.
    """
    if not isinstance(item, dict) or not isinstance(item.get("IsDir"), bool):
        raise ValueError("invalid rclone endpoint metadata")
    mtime: Optional[datetime.datetime] = None
    # Each item has an ISO-8601 "ModTime" field, e.g. "2025-07-04T12:30:45+08:00"
    raw = item.get("ModTime")
    if read_modtime and isinstance(raw, str) and raw:
        try:
            # fromisoformat handles the rclone ISO-8601 output directly
            parsed = datetime.datetime.fromisoformat(raw)
            if parsed.tzinfo is not None:
                mtime = parsed
        except ValueError:
            pass
    return models.PathInfo(models.PathState.PRESENT, models.PathType.DIRECTORY if item["IsDir"] else models.PathType.FILE, mtime)


def _find_remote_child(
    task: schema_ops.SyncTask, rclone_exe: str, path: str, read_modtime: bool,
) -> models.PathInfo:
    """Disambiguate missing bucket objects/prefixes from existing directories.

    Args:
        task: Metadata query settings.
        rclone_exe: Rclone executable.
        path: Path whose --stat result identifies a directory.
        read_modtime: Whether the matching entry's timestamp is needed.

    Returns:
        Matching child metadata or a confirmed missing state. A remote root
        reported as a directory remains present even when its listing is empty.

    Raises:
        ValueError: Parent metadata is malformed or cannot be read.
        FileNotFoundError: The parent is missing.
        OperationCancelled: The user cancels the read-only parent listing.

    Side effects:
        May list the parent with filters removed, never changing either endpoint.
    """
    prefix = endpoint_ops._extract_remote_host(path, "rclone")[0]
    if prefix is None:
        raise ValueError("cannot identify remote prefix")
    relative = path[len(prefix):].rstrip("/")
    if not relative:
        return models.PathInfo(models.PathState.PRESENT, models.PathType.DIRECTORY)
    parent, _, filename = relative.rpartition("/")
    if filename in {".", ".."}:
        raise ValueError("cannot identify the remote child name")
    entries = _read_remote_metadata(task, rclone_exe, f"{prefix}{parent}", stat_only=False, read_modtime=read_modtime)
    if not isinstance(entries, list):
        raise ValueError("invalid remote parent listing")
    matches: list[models.PathInfo] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("Name"), str):
            raise ValueError("invalid remote parent entry")
        info = _remote_entry_info(entry, read_modtime)
        if entry["Name"].casefold() == filename.casefold():
            matches.append(info)
    if not matches:
        return models.PathInfo(models.PathState.MISSING)
    # A directory/file name collision must not bypass the file safety guard.
    return next((info for info in matches if info.path_type == models.PathType.DIRECTORY), matches[0])


def _get_remote_path_info(
    task: schema_ops.SyncTask, rclone_exe: str, read_modtime: bool = True,
) -> models.PathInfo:
    """Inspect the remote endpoint while preserving directory time semantics.

    Args:
        task: Remote path, expected path type and metadata query settings.
        rclone_exe: Rclone executable.
        read_modtime: Include timestamps; false is used by file safety checks.

    Returns:
        Existence/type and optional time. Directory times remain the latest
        immediate-child time, not the directory's own time. Empty listings alone
        never imply absence; a failed probe never implies first synchronization.

    Raises:
        OperationCancelled: The user cancels a metadata query.

    Side effects:
        Reads remote metadata; may inspect the parent for bucket-based backends.
    """
    try:
        if task.path_type == models.PathType.DIRECTORY:
            entries = _read_remote_metadata(task, rclone_exe, task.remote_path, stat_only=False, read_modtime=read_modtime)
            if not isinstance(entries, list):
                raise ValueError("invalid remote directory listing")
            if entries:
                times = [info.mtime for entry in entries if (info := _remote_entry_info(entry, read_modtime)).mtime is not None]
                return models.PathInfo(models.PathState.PRESENT, models.PathType.DIRECTORY, max(times, default=None))
        item = _read_remote_metadata(task, rclone_exe, task.remote_path, stat_only=True, read_modtime=read_modtime)
        info = _remote_entry_info(item, read_modtime)
        if info.path_type == models.PathType.DIRECTORY:
            # Bucket backends report missing objects as empty directories.
            # An unfiltered parent listing distinguishes these from real prefixes.
            info = _find_remote_child(task, rclone_exe, task.remote_path, read_modtime)
        if task.path_type == models.PathType.DIRECTORY:
            info = dataclasses.replace(info, mtime=None)
        return info
    except FileNotFoundError:
        return models.PathInfo(models.PathState.MISSING)
    except ValueError as exc:
        return models.PathInfo(models.PathState.UNKNOWN, detail=str(exc))


def _validate_file_endpoints(task: schema_ops.SyncTask, rclone_exe: str, direction: str) -> None:
    """Require exact file endpoints before copyto/moveto can run.

    Args:
        task: Resolved file task; directory tasks are not probed.
        rclone_exe: Executable used for read-only remote metadata requests.
        direction: Push reads local-path; pull reads remote-path.

    Raises:
        ValueError: A source is missing, an endpoint is a directory/link, or
            metadata cannot be verified. A missing destination is permitted.
        OperationCancelled: The user cancels a metadata request.

    Side effects:
        Reads local metadata and may run rclone lsjson --stat. Never transfers
        data, creates directories, or substitutes either endpoint's parent.
    """
    if task.path_type != models.PathType.FILE:
        return
    source, destination = source_dest(task, direction)
    if source == destination:
        raise ValueError("Source and destination must be different files")
    for attr in ("local_path", "remote_path"):
        path: str = getattr(task, attr)
        is_source = path == source
        role = "source" if is_source else "destination"
        if not path or path.endswith(("/", "\\")):
            raise ValueError(f"File {role} requires a full filename: {path}")
        storage = task.remote_path_type if attr == "remote_path" else "local"
        remote_prefix = endpoint_ops._extract_remote_host(path, storage)[0]
        if remote_prefix is None:
            if os.path.islink(path) and (not is_source or not task.copy_links):
                raise ValueError(f"File {role} is a symbolic link: {path}")
            info = _get_local_path_info(path, read_modtime=False)
        else:
            if path[len(remote_prefix):].rsplit("/", 1)[-1] in {"", ".", ".."}:
                raise ValueError(f"Remote file {role} requires a full filename: {path}")
            info = _get_remote_path_info(task, rclone_exe, read_modtime=False)
        if info.state == models.PathState.MISSING:
            if not is_source:
                continue
            raise ValueError(f"Source file does not exist: {path}. First sync requires existing source data.")
        if info.state == models.PathState.UNKNOWN:
            raise ValueError(f"Cannot inspect file {role}: {path}: {info.detail}")
        if info.path_type != models.PathType.FILE:
            raise ValueError(f"File {role} is not a regular file: {path}")


def _available_actions(task: schema_ops.SyncTask) -> list[models.SyncAction]:
    """Return allowed actions, stably placing the configured mode first."""
    actions = [
        action for action in models.PATH_ACTIONS[task.path_type]
        if task.allow_actions is None or action in task.allow_actions
    ]
    return sorted(actions, key=lambda action: models.ACTION_COMMANDS[action][0] != task.preferred_mode)


def _task_for_action(task: schema_ops.SyncTask, action: models.SyncAction) -> schema_ops.SyncTask:
    """Copy a task with its runtime command mode, enforcing write permissions.

    The original configuration is unchanged. Raises ValueError when the
    action is forbidden or a one-way backup directory would be misapplied.
    """
    if action not in _available_actions(task):
        raise ValueError(f"Task does not allow action '{action.value}'")
    mode, direction = models.ACTION_COMMANDS[action]
    if task.backup_dir and direction == "pull":
        raise ValueError("Refusing pull with backup-dir. Use a task-specific pull backup path or disable backup-dir.")
    if task.backup_dir and mode == "bisync":
        raise ValueError("Bisync requires side-specific --backup-dir1/--backup-dir2 instead of backup-dir.")
    return dataclasses.replace(task, mode=mode)
