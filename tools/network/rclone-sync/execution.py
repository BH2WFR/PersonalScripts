"""Ordered batch execution, retry boundaries, and post-transfer actions.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import sys
import os
import subprocess
from . import endpoints as endpoint_ops
from . import models
from . import rclone as backend
from . import schema as schema_ops
from . import ui as terminal
from utils import *


def _notify(title: str, body: str) -> None:
    System.notify(title, body)


def _run_task_command(
    task: schema_ops.SyncTask, cmd: list[str], rclone_exe: str, direction: str,
) -> subprocess.CompletedProcess[str]:
    """Validate volume identity and file endpoints immediately before a command.

    Args:
        task: Resolved task, including its selected runtime mode.
        cmd: Transfer/check command, optionally containing --dry-run.
        rclone_exe: Executable for endpoint metadata checks.
        direction: Selected push/pull direction.

    Returns:
        Rclone's result, or exit code 1 without execution if validation fails.

    Raises:
        backend.OperationCancelled: The user cancels validation or execution.
        OSError: Rclone cannot be started for validation or transfer.

    Side effects:
        Prints validation failures; otherwise runs the supplied command.
    """
    try:
        endpoint_ops._validate_volume_endpoints(task, direction)
        backend._validate_file_endpoints(task, rclone_exe, direction)
    except ValueError as exc:
        print(f"{FLRed}{exc}{CRst}")
        return subprocess.CompletedProcess(cmd, 1)
    return backend._run_interruptible(cmd)


def _run_path_batch(
    tasks: list[schema_ops.SyncTask], commands: list[list[str]], rclone_exe: str, direction: str,
    start: int = 0, precheck: bool = True, dry_run: bool = False,
) -> tuple[int, int]:
    """Run ordered pairs, stopping at the first failed command or pre-check.

    Args:
        tasks: Materialized tasks with shared action and comparison settings.
        commands: Corresponding commands; successful real bisync initialization
            loses its --resync flag in this list for subsequent re-runs.
        rclone_exe: Executable used for file guards and optional pre-checks.
        direction: Selected push/pull direction.
        start: Zero-based first pair to execute; earlier successful pairs are skipped.
        precheck: Run configured pre-checks and existing link repair on initial runs.
            Re-runs skip these, but always retain file endpoint guards.
        dry_run: Append --dry-run, without changing commands or repairing links.

    Returns:
        Exit code and first unfinished index (len(tasks) if fully successful).

    Raises:
        OperationCancelled: User cancellation; remaining pairs are not started.

    Side effects:
        Prints numbered progress and executes rclone sequentially; successful
        earlier transfers are not rolled back when a later pair fails.
    """
    for index in range(start, len(tasks)):
        task, command = tasks[index], commands[index]
        print(f"\n{FLCyan}[{index + 1}/{len(tasks)}]{CRst} {FLYellow}{task.name}{CRst}")
        try:
            if precheck and not dry_run and task.mode in models._DIRECTIONAL_MODES and task.check_before_sync:
                endpoint_ops._validate_volume_endpoints(task, direction)
                print(f"{FLCyan}Running pre-sync check...{CRst}")
                check_cmd = backend.to_check_command(task, rclone_exe, direction=direction)
                terminal._print_cmd(check_cmd, f"[{index + 1}/{len(tasks)}] Pre-sync")
                result = backend._run_interruptible(check_cmd)
                if result.returncode != 0:
                    print(f"{FLYellow}  -> Pre-sync check reported differences or an error.{CRst}")
                    if task.stop_on_check_failure:
                        print(f"{FLRed}  -> Stopped because stop-on-check-failure is enabled.{CRst}")
                        return result.returncode, index
                terminal._print_cmd(command, f"[{index + 1}/{len(tasks)}]")
            run_command = [*command, "--dry-run"] if dry_run else command
            result = _run_task_command(task, run_command, rclone_exe, direction)
        except (OSError, ValueError) as exc:
            print(f"{FLRed}Could not execute pair [{index + 1}/{len(tasks)}]: {exc}{CRst}")
            return 1, index
        if result.returncode != 0:
            print(f"{FLRed}Pair [{index + 1}/{len(tasks)}] failed; remaining pairs were not started.{CRst}")
            return result.returncode, index
        if not dry_run:
            # Initialization belongs to each pair, including pairs completed on retry.
            commands[index] = [arg for arg in command if arg != "--resync"]
            _, destination = backend.source_dest(task, direction)
            if precheck and task.mode in models._DIRECTIONAL_MODES and task.links and os.path.exists(destination):
                try:
                    endpoint_ops._validate_volume_endpoints(task, direction)
                except ValueError as exc:
                    print(f"{FLRed}{exc}{CRst}")
                    return 1, index
                _fix_windows_symlinkd(destination)
    return 0, len(tasks)


def _fix_windows_symlinkd(local_path: str) -> None:
    """After rclone sync with ``--links`` on Windows, convert file-type symlinks
    that point to directories into proper directory-symlinks (symlinkd).

    Uses the same detection logic as ``windows/link-fix-symlinkd.py``.
    """
    if sys.platform != "win32":
        return
    if not os.path.isdir(local_path):
        return
    count = 0
    for root, dirs, files in os.walk(local_path):
        for name in dirs + files:
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    continue
                target = os.readlink(full)
                # Resolve the symlink; if it points to a directory, convert to symlinkd
                resolved = full
                try:
                    resolved = os.path.realpath(full)
                except OSError:
                    pass
                if not os.path.isdir(resolved):
                    continue
                os.unlink(full)
                os.symlink(target, full, target_is_directory=True)
                count += 1
            except OSError:
                pass
    if count:
        print(f"{FLYellow}  -> Fixed {count} broken symlinkd entries{CRst}")
