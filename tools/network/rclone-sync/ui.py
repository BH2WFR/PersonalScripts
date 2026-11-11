"""Implementation notes.

Private presentation module for personal_rclone_sync. Entry help belongs to
../rclone-sync.py; keep task parsing, prompts and previews here.
"""

from __future__ import annotations

import sys
import os
import argparse
import re
import shlex
import dataclasses
import subprocess
from typing import Optional
from . import endpoints as endpoint_ops
from . import models
from . import rclone as backend
from . import schema as schema_ops
from utils import *


def display_filters(task: schema_ops.SyncTask) -> str:
    """Format the configured machine filters without printing.

    Args:
        task: Task whose platform, architecture, computer, and GUI filters are shown.

    Returns:
        Colored summary, or an empty string if no filters are configured.
    """
    parts: list[str] = []
    p = task._normalize_platform(task.platform)
    if p:
        parts.append(f"os: {', '.join(p) if isinstance(p, list) else p}")
    a = task.arch
    if a:
        parts.append(f"arch: {', '.join(a) if isinstance(a, list) else a}")
    cn = task.computer_name.strip() if isinstance(task.computer_name, str) else task.computer_name
    if cn:
        parts.append(f"computer-name: {cn}")
    if task.linux_gui_required:
        parts.append("linux-gui-required: true")
    return f"  {FGray}[{', '.join(parts)}]{CRst}" if parts else ""


def _config_file_action(rclone_exe: str, *, open_file: bool = False) -> None:
    """Show the effective rclone config path and optionally open an existing file.

    Args:
        rclone_exe: Executable used to query the active configuration path.
        open_file: Open with the system default application when True.

    Side effects:
        Prints the path or an error, queries rclone, and optionally opens the
        file. Does not print configuration contents or create missing files.
        Query cancellation and failures return to the caller, which exits.
    """
    try:
        config_file = backend._get_config_file(rclone_exe)
        print(f"\n{FLYellow}Rclone configuration file:{CRst} {FLGreen}{config_file}{CRst}")
        if open_file:
            if not os.path.isfile(config_file):
                print(f"{FLYellow}Configuration file does not exist or is not a regular file.{CRst}")
                return
            System.open_with_default_app(config_file)
    except backend.OperationCancelled:
        return
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"{FLRed}Could not access the rclone configuration file: {exc}{CRst}")


def _print_cmd(cmd: list[str], label: str = "") -> None:
    """Print a command quoted for PowerShell on Windows or a POSIX shell elsewhere."""
    if os.name == "nt":
        quoted: list[str] = []
        for arg in cmd:
            if re.fullmatch(r"[A-Za-z0-9_./:\\-]+", arg):
                quoted.append(arg)
            else:
                escaped = arg.replace("'", "''")
                quoted.append(f"'{escaped}'")
        display = " ".join(quoted)
    else:
        display = shlex.join(cmd)
    prefix = f"{label} " if label else ""
    print(f"  {FLYellow}{prefix}Rclone command:{CRst}")
    print(f"{FGray}{display}{CRst}")


def _print_commands(commands: list[list[str]]) -> None:
    """Print every full command in execution order with a one-based batch index."""
    for index, command in enumerate(commands, 1):
        _print_cmd(command, f"[{index}/{len(commands)}]")


def _display_path_mtimes(
    task: schema_ops.SyncTask,
    rclone_exe: str,
    direction: str,
) -> list[str]:
    """Print the modification times of the local and remote paths in a compact
    comparison block, suitable for the pre-execution confirmation screen.

    Local mtime comes from the filesystem.  Remote mtime comes from
    ``rclone lsjson`` when ``remote-path`` is classified as a rclone remote,
    otherwise it comes from the local filesystem (including UNC paths).

    When *direction* is ``"push"`` and local is older than remote, or
    *direction* is ``"pull"`` and local is newer than remote, a warning is
    returned. Directory times are only hints: they do not guarantee individual
    file age or whether an overwrite will occur. The caller prints these
    notices together with other pre-execution warnings.

    Args:
        task: Resolved endpoints and metadata query settings.
        rclone_exe: Rclone executable for remote metadata.
        direction: Push/pull, or empty for check/bisync. Missing targets receive
            first-sync guidance; missing sources are never treated as upload targets.

    Returns:
        Colored warning lines to display together before confirmation.

    Raises:
        OperationCancelled: The user cancels a metadata request.

    Side effects:
        Reads endpoint metadata and prints timestamps or first-sync information.
    """
    warnings: list[str] = []
    local_path, remote_path = task.local_path, task.remote_path
    local_info = backend._get_local_path_info(local_path)
    remote_is_rclone = endpoint_ops._extract_remote_host(remote_path, task.remote_path_type)[0] is not None
    if remote_is_rclone:
        remote_info = backend._get_remote_path_info(task, rclone_exe)
    else:
        remote_info = backend._get_local_path_info(remote_path)
    local_mtime, remote_mtime = local_info.mtime, remote_info.mtime

    def _fmt(info: models.PathInfo) -> str:
        if info.state == models.PathState.MISSING:
            return f"{FGray}(not found){CRst}"
        if info.state == models.PathState.UNKNOWN:
            return f"{FGray}(unavailable: {info.detail}){CRst}"
        if info.mtime is None:
            return f"{FGray}(exists; modification time unavailable){CRst}"
        local_dt = info.mtime.astimezone()  # local timezone
        return f"{CRst}{local_dt.strftime('%Y-%m-%d %H:%M:%S')}{CRst}"

    print()
    print(f"  {FLYellow}Path modification times:{CRst}")
    print(f"  {FLGreen}Local :{CRst}  {_fmt(local_info)}  {FGray}{local_path}{CRst}")
    print(f"  {FLCyan}Remote:{CRst}  {_fmt(remote_info)}  {FGray}{remote_path}{CRst}")
    if task.path_type == models.PathType.DIRECTORY:
        print(f"  {FGray}Directory times are hints only; they do not guarantee which files are newer.{CRst}")

    # Missing endpoints need first-sync guidance, not an unavailable-time warning.
    if models.PathState.MISSING in {local_info.state, remote_info.state}:
        if local_info.state == remote_info.state == models.PathState.MISSING:
            warnings.append(f"  {FLYellow}WARNING: Both paths are missing. First sync requires existing source data on one side.{CRst}")
        elif models.PathState.UNKNOWN in {local_info.state, remote_info.state}:
            warnings.append(f"  {FLYellow}WARNING: One path is missing and the other could not be inspected. Cannot determine first-sync direction.{CRst}")
        elif direction in models.VALID_DIRECTIONS:
            source_info = local_info if direction == "push" else remote_info
            source_side, target_side = ("local", "remote") if direction == "push" else ("remote", "local")
            if source_info.state == models.PathState.MISSING:
                opposite = "pull" if direction == "push" else "push"
                warnings.append(
                    f"  {FLYellow}WARNING: The {source_side} source is missing; {direction} has no source data. "
                    f"For first sync, choose {opposite} to initialize it from the other side, or correct the source path.{CRst}"
                )
            else:
                operation = "upload" if direction == "push" else "download"
                print(
                    f"  {FLCyan}First {operation}: the {target_side} path does not exist yet. "
                    f"The destination will be created when data is transferred.{CRst}"
                )
        else:
            missing_side = "local" if local_info.state == models.PathState.MISSING else "remote"
            initialize = "pull" if missing_side == "local" else "push"
            warnings.append(
                f"  {FLYellow}WARNING: The {missing_side} path is missing. "
                f"For first sync, initialize it with a one-way {initialize} before checking or using bisync.{CRst}"
            )
        print()
        return warnings

    # Show which side is more recent, and collect a directional danger warning
    if local_mtime is not None and remote_mtime is not None:
        delta = local_mtime - remote_mtime
        delta_sec = delta.total_seconds()
        if abs(delta_sec) < 1:
            print(f"  {FGray}  -> times match (same second){CRst}")
        elif delta_sec > 0:
            mins = int(delta_sec // 60) if abs(delta_sec) >= 60 else 0
            if mins:
                print(f"  {FGray}  -> {FLGreen}local{FGray} is{CRst} {mins}m {FLYellow}newer{CRst} {FGray}than {FLCyan}remote{CRst}")
            else:
                print(f"  {FGray}  -> {FLGreen}local{FGray} is{CRst} {int(delta_sec)}s {FLYellow}newer{CRst} {FGray}than {FLCyan}remote{CRst}")
            # local newer + pull: directory times suggest a possible overwrite.
            if direction == "pull":
                if task.path_type == models.PathType.DIRECTORY:
                    warnings.append(
                        f"  {FLYellow}NOTE: Directory timestamps suggest local data may be newer. "
                        f"Pull might replace newer files; this is not guaranteed by directory times.{CRst}"
                    )
                else:
                    warnings.append(f"  {FLYellow}  ⚠ WARNING: {FLRed}pull would overwrite newer{CRst} {FLGreen}local{CRst}"
                                    f" {FLRed}data with older{CRst} {FLCyan}remote{CRst} {FLRed}data!{CRst}")
        else:
            mins = int(abs(delta_sec) // 60) if abs(delta_sec) >= 60 else 0
            if mins:
                print(f"  {FGray}  -> {FLCyan}remote{FGray} is{CRst} {mins}m {FLYellow}newer{CRst} {FGray}than {FLGreen}local{CRst}")
            else:
                print(f"  {FGray}  -> {FLCyan}remote{FGray} is{CRst} {int(abs(delta_sec))}s {FLYellow}newer{CRst} {FGray}than {FLGreen}local{CRst}")
            # remote newer + push: directory times suggest a possible overwrite.
            if direction == "push":
                if task.path_type == models.PathType.DIRECTORY:
                    warnings.append(
                        f"  {FLYellow}NOTE: Directory timestamps suggest remote data may be newer. "
                        f"Push might replace newer files; this is not guaranteed by directory times.{CRst}"
                    )
                else:
                    warnings.append(f"  {FLRed}  ⚠ WARNING: push would overwrite newer{CRst} {FLCyan}remote{CRst}"
                                    f" {FLRed}data with older{CRst} {FLCyan}local{CRst} {FLRed}data!{CRst}")
    elif local_mtime is not None:
        print(f"  {FGray}  -> (remote time unavailable for comparison){CRst}")
    elif remote_mtime is not None:
        print(f"  {FGray}  -> (local time unavailable for comparison){CRst}")
    print()
    return warnings


def _interactive_host_swap(final_task: schema_ops.SyncTask, cli_auto: bool) -> bool:
    """If *final_task* has ``alternative_remote_hosts``, offer the user
    a choice of which host to use in ``remote_path``.
    Modifies *final_task* in place.  Skipped silently when *cli_auto*.

    Args:
        final_task: Resolved task whose remote path may be changed; its name
            includes the selected sub-task suffix for the menu heading.
        cli_auto: Skip interaction when the task was selected from the CLI.

    Returns:
        True when selected, kept, or skipped. False on Q/EOF cancellation,
        leaving the remote path unchanged.
    """
    if cli_auto:
        return True
    alternatives = final_task.alternative_remote_hosts
    if not alternatives:
        return True

    # Only remote-path participates. Local/UNC paths skip in auto/local mode.
    path_attr = "remote_path"
    current_prefix, current_host = endpoint_ops._extract_remote_host(
        final_task.remote_path,
        final_task.remote_path_type,
    )

    if path_attr is None or current_host is None or current_prefix is None:
        return True

    # Build choices: current host first, then alternatives.
    # [0] is kept even if an alternative has the same name.
    assert current_prefix is not None  # narrowed above
    choices: list[tuple[str, str]] = []  # (host_name, full_prefix)
    choices.append((current_host, current_prefix))

    seen: set[str] = set()
    for alt in alternatives:
        alt = alt.strip()
        if not alt or alt in seen:
            continue
        seen.add(alt)
        alt_prefix = endpoint_ops._host_name_to_prefix(alt, current_prefix)
        choices.append((alt, alt_prefix))

    if len(choices) <= 1:
        return True

    # Compute full path for each choice by swapping the host prefix
    original_path = getattr(final_task, path_attr)
    # [0] is dimmed if an alternative also has the same host name
    current_overlaps = current_host in seen
    print(
        f"\n{FLYellow}Alternative hosts available{CRst} for "
        f"{FLGreen}{path_attr.replace('_', '-')}{CRst} {FLYellow}{final_task.name}{CRst}:"
    )
    for idx, (name, prefix) in enumerate(choices):
        mark = f"{FGray}[{CRst}{idx}{FGray}]{CRst}"
        full = endpoint_ops._replace_path_host(original_path, current_prefix, prefix)
        if idx == 0 and current_overlaps:
            # [0] duplicates an alternative — show dimmed
            print(f"  {mark}: {FGray}{full}{CRst} {FGray}(current){CRst}")
        elif idx == 0:
            print(f"  {mark}: {FLGreen}{full}{CRst} {FGray}(current){CRst}")
        else:
            print(f"  {mark}: {FLGreen}{full}{CRst}")
    print(f"  {FGray}[{CRst}Q{FGray}]{CRst}: {FGray}Back to task menu{CRst}")

    while True:
        try:
            choice = input(
                f"\n{FLYellow}Select host{CRst} {FGray}[# / Enter=keep current / Q=back]{CRst}: "
            ).strip()
        except EOFError:
            print()
            return False
        if choice.lower() == "q":
            return False
        if not choice:
            return True
        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(choices):
                _, new_prefix = choices[idx]
                if new_prefix != current_prefix:
                    old_val = getattr(final_task, path_attr)
                    setattr(final_task, path_attr, endpoint_ops._replace_path_host(old_val, current_prefix, new_prefix))
                return True
            print(f"{FLRed}Invalid number: {idx}{CRst}")
            continue
        print(f"{FLRed}Enter a number, Q to go back, or Enter to keep current.{CRst}")


def _interactive_batch_hosts(task: schema_ops.SyncTask, cli_auto: bool) -> bool:
    """Choose alternate hosts once per original remote prefix for a path batch.

    Args:
        task: Expanded sub-task whose ordered paths may be updated.
        cli_auto: Skip host prompts for CLI-selected tasks.

    Returns:
        False on cancellation, leaving every path unchanged; otherwise True.

    Side effects:
        Shows host menus. Reuses choices only for the same original prefix;
        local/UNC endpoints remain untouched and unrelated remotes stay separate.
    """
    choices: dict[str, str] = {}
    resolved = endpoint_ops.resolved_pairs(task)
    paths: list[models.ResolvedPathPair] = []
    for index, pair in enumerate(endpoint_ops.path_tasks(task), 1):
        prefix, _ = endpoint_ops._extract_remote_host(pair.remote_path, pair.remote_path_type)
        if prefix is not None and prefix in choices:
            pair.remote_path = endpoint_ops._replace_path_host(pair.remote_path, prefix, choices[prefix])
        else:
            if len(task.paths) > 1:
                pair.name = f"{task.name} [{index}/{len(task.paths)}]"
            if not _interactive_host_swap(pair, cli_auto):
                return False
            replacement, _ = endpoint_ops._extract_remote_host(pair.remote_path, pair.remote_path_type)
            if prefix is not None and replacement is not None:
                choices[prefix] = replacement
        paths.append(dataclasses.replace(resolved[index - 1], path1=pair.local_path, path2=pair.remote_path))
    task.resolved_paths = paths
    return True


def _interactive_custom_hosts(task: schema_ops.SyncTask, cli_auto: bool) -> bool:
    """Offer per-pair path2 overrides, committing only after all prompts complete.

    Args:
        task: Resolved batch after alternative-remote selection.
        cli_auto: True skips all prompts, retaining configured addresses.

    Returns:
        True on completion, including defaults/disabled switches. False on Q or
        address-input EOF, leaving every path unchanged. Menu EOF exits through
        Menu.select; Ctrl+C propagates to the normal exit handler.

    Side effects:
        Prints default-No menus and reads literal addresses. Updates only in-memory
        path2 strings; rclone inherits credentials through named connection strings.
        Repeated paths have independent choices; no config or environment is written.
    """
    if cli_auto or not any(pair.custom_host for pair in task.paths):
        return True
    paths = endpoint_ops.resolved_pairs(task)
    for index, pair in enumerate(paths):
        host_kind = pair.custom_host
        if host_kind is None:
            continue
        remote = pair.path2
        prefix, _ = endpoint_ops._extract_remote_host(remote, task.remote_path_type)
        if prefix is None:
            raise ValueError(f"paths[{index}].path2: custom-host prompts require a named rclone remote")
        print(f"\n{FLYellow}{task.name} [{index + 1}/{len(paths)}]{CRst}")
        print(f"  {FGray}Path2:{CRst} {FLGreen}{remote}{CRst}")
        try:
            selected = Menu.select(
                [MenuOption(["N"], "No, keep configured address", False),
                 MenuOption(["Y"], "Yes, use a temporary address", True),
                 MenuOption(["Q"], "Back to task menu", None)],
                prompt=f"Use a custom {host_kind.value.upper()} address?", default_key="N",
            )
            if selected is None:
                return False
            if selected is False:
                continue
            hint = "SFTP hostname/IP (no port)" if host_kind is models.CustomHost.SFTP else "WebDAV base URL (http(s)://host:port/path/)"
            while True:
                value = Input.prompt(f"{FLYellow}{hint}{CRst} {FGray}[Enter=keep / Q=back]{CRst}: ")
                if value.lower() == "q":
                    return False
                if not value:
                    break
                try:
                    address = endpoint_ops._custom_host_value(value, host_kind)
                except ValueError as exc:
                    print(f"{FLRed}{exc}{CRst}")
                    continue
                # Rclone connection strings quote ':'/',' and double embedded quotes.
                escaped = address.replace("'", "''")
                key = "host" if host_kind is models.CustomHost.SFTP else "url"
                replacement = f"{prefix[:-1]},{key}='{escaped}':"
                paths[index] = dataclasses.replace(pair, path2=endpoint_ops._replace_path_host(remote, prefix, replacement))
                break
        except EOFError:
            print()
            return False
    task.resolved_paths = paths
    return True


def _select_action(
    task: schema_ops.SyncTask,
    cli_action: Optional[models.SyncAction],
    cli_direction: Optional[str],
) -> Optional[models.SyncAction]:
    """Resolve CLI action/direction or show the mode-prioritized action menu.

    Returns None when q is selected; empty input retries without selecting.
    Raises ValueError for disallowed actions
    or directions on nondirectional modes. CLI direction uses preferred-mode.
    """
    actions = backend._available_actions(task)
    selected = cli_action
    if selected is None and cli_direction is not None:
        command_mode = task.preferred_mode or ("copy" if task.path_type == models.PathType.FILE else "sync")
        selected = next((
            action for action in models.PATH_ACTIONS[task.path_type]
            if models.ACTION_COMMANDS[action] == (command_mode, cli_direction)
        ), None)
        if selected is None:
            raise ValueError(f"Preferred mode '{command_mode}' has no direction; use --action {command_mode}")
    if selected is not None:
        if selected not in actions:
            raise ValueError(f"Task does not allow action '{selected.value}'")
        return selected

    print(f"\n  {FLYellow}Task:{CRst} {FLCyan}{task.name}{CRst}")
    print(f"  {FGray}Path type: {task.path_type.value}{CRst}")
    if task.preferred_mode:
        print(f"  {FGray}Preferred mode '{task.preferred_mode}' is listed first in yellow.{CRst}")
    else:
        highlighted = "push-copy-file/pull-copy-file" if task.path_type == models.PathType.FILE else "push/pull"
        print(f"  {FGray}No preferred mode; {highlighted} are highlighted in the standard order.{CRst}")
    if not actions:
        print(f"  {FLYellow}No actions are permitted for this path type.{CRst}")
    print(f"  {FGray}Enter retries; q returns to the task menu.{CRst}")
    pairs = [pair.endpoints for pair in endpoint_ops.resolved_pairs(task)] or [(task.local_path, task.remote_path)]
    if len(pairs) > 1:
        for index, (local_path, remote_path) in enumerate(pairs, 1):
            print(f"  {FGray}[{index}/{len(pairs)}]{CRst} {FLBlue}{local_path}{CRst} | {FLGreen}{remote_path}{CRst}")
        local = f"{FLBlue}local ({len(pairs)} paths){CRst}"
        remote = f"{FLGreen}remote ({len(pairs)} paths){CRst}"
    else:
        local = f"{FLBlue}{pairs[0][0]}{CRst}"
        remote = f"{FLGreen}{pairs[0][1]}{CRst}"
    options: list[MenuOption] = []
    action_width = max((len(action.value) for action in actions), default=10)
    preferred_mode = task.preferred_mode or ("copy" if task.path_type == models.PathType.FILE else "sync")
    for index, action in enumerate(actions):
        mode, direction = models.ACTION_COMMANDS[action]
        source, destination = (remote, local) if direction == "pull" else (local, remote)
        arrow = "↔" if mode == "bisync" else "=" if mode == "check" else "→"
        action_color = FLYellow if mode == preferred_mode else FLCyan
        options.append(MenuOption(
            [str(index), action.value],
            f"{action.value:<{action_width}} {source} {FGray}{arrow}{CRst} {destination}",
            value=action,
            desc_color=action_color,
        ))
    options.append(MenuOption(["q"], "Back to task menu", desc_color=FGray))
    selected = Menu.select(options, prompt="Operation", required=True, separator=False, key_color="")
    return selected if isinstance(selected, models.SyncAction) else None


def _select_comparison_mode(
    task: schema_ops.SyncTask,
    cli_comparison: Optional[models.ComparisonMode],
    interactive: bool,
) -> Optional[models.ComparisonMode]:
    """Resolve the runtime comparison mode from CLI, task configuration, or input.

    Configured ``--ignore-times``, ``--checksum``, and ``--size-only`` settings
    only determine the menu's default choice.  Each explicit menu choice has
    fixed behavior.

    Args:
        task: Fully resolved task whose comparison settings are inspected.
        cli_comparison: Explicit CLI comparison mode, or ``None``.
        interactive: Whether to display the comparison selection menu.

    Returns:
        The selected comparison mode, or ``None`` when Q is selected or
        conflicting configured modes cannot be resolved non-interactively.

    Side effects:
        Prints configured-mode notices, conflict errors, and an interactive
        menu when appropriate.
    """
    allowed = models.MODE_COMPARISONS[task.mode or "sync"]
    if cli_comparison is not None:
        if cli_comparison not in allowed:
            print(f"{FLRed}Comparison '{cli_comparison.value}' is not supported by '{task.mode}'.{CRst}")
            return None
        return cli_comparison

    try:
        configured_modes = backend._configured_comparison_modes(task)
    except ValueError as exc:
        print(f"{FLRed}{exc}{CRst}")
        if not interactive:
            return None
        configured_modes = set(allowed)  # Require an explicit menu choice.
    unsupported = configured_modes.difference(allowed)
    if unsupported:
        labels = ", ".join(sorted(mode.value for mode in unsupported))
        print(f"{FLYellow}Configured comparison '{labels}' does not apply to '{task.mode}'.{CRst}")
        configured_modes.difference_update(unsupported)
    if len(configured_modes) > 1:
        configured_text = ", ".join(sorted(mode.value for mode in configured_modes))
        print(
            f"\n{FLRed}Conflicting configured comparison modes:{CRst} "
            f"{FLYellow}{configured_text}{CRst}"
        )
        if not interactive:
            print(f"{FLRed}Specify --comparison to choose one mode.{CRst}")
            return None
        default_mode: Optional[models.ComparisonMode] = None
    else:
        fallback = models.ComparisonMode.CHECKSUM if task.mode == "check" else models.ComparisonMode.SIZE_AND_TIME
        default_mode = next(iter(configured_modes), fallback)
        if configured_modes:
            flag = {
                models.ComparisonMode.SIZE_AND_TIME: "--compare size,modtime",
                models.ComparisonMode.SIZE_ONLY: "--size-only",
                models.ComparisonMode.FORCE: "--ignore-times",
                models.ComparisonMode.CHECKSUM: "--checksum",
            }[default_mode]
            print(
                f"\n{FLYellow}Configured comparison mode:{CRst} "
                f"{FLCyan}{default_mode.value}{CRst} {FGray}({flag}){CRst}"
            )

    if not interactive:
        return default_mode

    options = [
        MenuOption(
            [models.COMPARISON_MENU_KEYS[models.ComparisonMode.SIZE_AND_TIME]],
            "size_and_time  Compare by size and modified time",
            value=models.ComparisonMode.SIZE_AND_TIME,
            desc_color=FGray,
        ),
        MenuOption(
            [models.COMPARISON_MENU_KEYS[models.ComparisonMode.SIZE_ONLY]],
            "size_only      Compare by size only (--size-only)",
            value=models.ComparisonMode.SIZE_ONLY,
            desc_color=FGray,
        ),
        MenuOption(
            [models.COMPARISON_MENU_KEYS[models.ComparisonMode.FORCE]],
            "force          Transfer all files unconditionally (--ignore-times)",
            value=models.ComparisonMode.FORCE,
            desc_color=FGray,
        ),
        MenuOption(
            [models.COMPARISON_MENU_KEYS[models.ComparisonMode.CHECKSUM]],
            "checksum       Compare by size and checksum (--checksum)",
            value=models.ComparisonMode.CHECKSUM,
            desc_color=FGray,
        ),
    ]
    options = [option for option in options if option.value in allowed]
    if task.mode == "bisync":
        for option in options:
            description = option.description.partition(" (")[0]
            option.description = f"{description} (--compare {models.BISYNC_COMPARE_VALUES[option.value]})"
    if task.mode == "check":
        for option in options:
            if option.value is models.ComparisonMode.CHECKSUM:
                option.description = "checksum       Compare by size and checksum (rclone check)"
    options.append(MenuOption(["q"], "Back to task menu", desc_color=FGray))
    selected = Menu.select(
        options,
        prompt="Comparison mode",
        required=default_mode is None,
        default_key=(models.COMPARISON_MENU_KEYS[default_mode] if default_mode is not None else None),
        separator=False,
    )
    return selected if isinstance(selected, models.ComparisonMode) else None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI args. Help is printed by the custom help path before this runs."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--schema-file")
    parser.add_argument("--rclone-config-file")
    parser.add_argument("--rclone-config-password")
    parser.add_argument("--task")
    parser.add_argument("--sub-task")
    parser.add_argument("--direction", choices=sorted(models.VALID_DIRECTIONS))
    parser.add_argument("--action", choices=[action.value for action in models.SyncAction])
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--comparison", choices=[mode.value for mode in models.ComparisonMode])
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    ns = parser.parse_args(argv)

    if ns.push and ns.pull:
        parser.error("--push and --pull cannot be used together")
    if (ns.push and ns.direction == "pull") or (ns.pull and ns.direction == "push"):
        parser.error("--push/--pull conflicts with --direction")
    if ns.push:
        ns.direction = "push"
    if ns.pull:
        ns.direction = "pull"
    if ns.action is not None and ns.direction is not None:
        parser.error("Use --action or --direction/--push/--pull, not both")
    if ns.resync and ns.action not in (None, models.SyncAction.BISYNC.value):
        parser.error("--resync requires --action bisync")
    return ns
