"""Application workflow connecting schema, endpoint, UI, and execution modules.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import sys
import os
import subprocess
import re
from pathlib import Path
from typing import Optional
from . import endpoints as endpoint_ops
from . import execution
from . import models
from . import rclone as backend
from . import schema as schema_ops
from . import ui as terminal
from utils import *


def main(script_dir: str | None = None) -> int:
    """Run task selection, resolution, confirmation, and ordered execution.

    Args:
        script_dir: Original entry directory for the script_dir placeholder.
            Defaults to this package's parent when called by internal tests.

    Returns:
        Process exit status: zero on success/cancelled menus, nonzero on errors,
        or 130 when a CLI-selected transfer is interrupted.

    Side effects:
        Reads YAML, prompts in interactive mode, and executes only selected tasks.
        The --help branch performs no discovery or rclone subprocess calls.
    """
    Console.print_banner("RCLONE SYNC RUNNER")

    # ---- help (works without any dependencies) ----
    if "--help" in sys.argv or "-h" in sys.argv:
        terminal._print_help()
        return 0

    try:
        import yaml as yaml_mod
    except ImportError:
        Console.print_error_and_exit("PyYAML is not installed. Run: pip install pyyaml")
        raise  # unreachable — satisfies the type checker

    script_dir = script_dir or str(Path(__file__).resolve().parent.parent)

    # ---- parse CLI args ----
    try:
        parsed = terminal._parse_args(sys.argv[1:])
    except SystemExit as e:
        return int(e.code or 0)

    cli_schema_file: Optional[str] = parsed.schema_file
    cli_config_file: Optional[str] = parsed.rclone_config_file
    cli_config_password: Optional[str] = parsed.rclone_config_password
    cli_task: Optional[str] = parsed.task
    cli_sub_task: Optional[str] = parsed.sub_task
    cli_dry_run = parsed.dry_run
    cli_verbose = parsed.verbose
    cli_direction: Optional[str] = parsed.direction
    cli_action = models.SyncAction(parsed.action) if parsed.action is not None else None
    cli_resync: bool = parsed.resync
    cli_comparison: Optional[models.ComparisonMode] = (
        models.ComparisonMode(parsed.comparison)
        if parsed.comparison is not None
        else None
    )
    cli_auto = cli_task is not None

    # ================================================================
    # Step 1: Check rclone & configure password
    # ================================================================
    _rclone = CmdCheck("rclone", hints={
        "windows": f"{FGray}scoop install rclone{CRst}",
        "macos":   f"{FGray}brew install rclone{CRst}",
        "linux":   f"{FGray}sudo apt install rclone{CRst}",
    })
    if not Environment.check_commands(_rclone):
        return 1
    assert _rclone.path is not None
    rclone_exe: str = _rclone.path

    # Print rclone location and version
    ver_process = subprocess.run([rclone_exe, "version"], capture_output=True, text=True, timeout=10)
    ver_first_line = ver_process.stdout.strip().split("\n")[0] if ver_process.stdout else ""
    if ver_first_line:
        print(f"{FGray}rclone:{CRst} {rclone_exe} {FGray}({ver_first_line}){CRst}")

    print("")

    if cli_config_file:
        os.environ["RCLONE_CONFIG"] = cli_config_file
    config_password: Optional[str] = None
    if cli_config_password:
        os.environ["RCLONE_CONFIG_PASS"] = cli_config_password
        if not backend._verify_config_password(rclone_exe):
            Console.print_error_and_exit("rclone config password is incorrect (from --rclone-config-password)")
        config_password = cli_config_password
    elif models.ENV_CONFIG_PASSWORD in os.environ:
        config_password = os.environ[models.ENV_CONFIG_PASSWORD]
        os.environ["RCLONE_CONFIG_PASS"] = config_password
        if not backend._verify_config_password(rclone_exe):
            Console.print_error_and_exit(f"rclone config password is incorrect (from {models.ENV_CONFIG_PASSWORD})")
    elif backend._detect_encrypted_config(rclone_exe):
        print(f"{FLYellow}  rclone config is encrypted.{CRst}")
        while True:
            config_password = Input.input_password("Enter rclone config password")
            if not config_password:
                Console.print_exit_message("Bye.")
                return 0
            os.environ["RCLONE_CONFIG_PASS"] = config_password
            if backend._verify_config_password(rclone_exe):
                break
            os.environ.pop("RCLONE_CONFIG_PASS", None)
            print(f"{FLRed}  Incorrect password.{CRst}")

    if config_password:
        os.environ["RCLONE_CONFIG_PASS"] = config_password

    # ================================================================
    # Step 2: Resolve YAML schema file path
    # ================================================================
    default_schema = cli_schema_file or os.environ.get(models.ENV_SCHEMA_FILE, "")

    if cli_auto:
        if not default_schema:
            print(f"{FLRed}With --task, specify --schema-file or set {models.ENV_SCHEMA_FILE}. "
                  f"The bundled sample is documentation only.{CRst}")
            return 1
        schema_file = default_schema
    else:
        if models.ENV_SCHEMA_FILE not in os.environ:
            print(f"{FGray}Tip: set {FLCyan}{models.ENV_SCHEMA_FILE}{FGray} to your default YAML schema path.{CRst}")
        try:
            schema_file = Input.resolve_input_path(
                default_schema,
                prompt="Path to YAML schema file",
                path_type="file",
            )
        except EOFError:
            print()
            Console.print_exit_message("Bye.")
            return 0

    schema_file = os.path.abspath(os.path.expanduser(schema_file))
    schema_dir = os.path.dirname(schema_file)

    if cli_verbose:
        print(f"{FGray}Schema file: {schema_file}{CRst}")

    if not os.path.isfile(schema_file):
        print(f"{FLRed}Schema file not found: {FGray}{schema_file}{CRst}")
        return 1

    # ================================================================
    # Step 3: Load & validate YAML
    # ================================================================
    try:
        with open(schema_file, "r", encoding="utf-8") as fh:
            schema = schema_ops._load_schema(fh)
    except (OSError, UnicodeError, yaml_mod.YAMLError) as e:
        print(f"{FLRed}Failed to read YAML schema:{CRst} {FGray}{schema_file}{CRst}\n{FGray}{e}{CRst}")
        return 1

    if schema is None:
        schema = {}

    errors = schema_ops._validate_schema(schema)
    if errors:
        print(f"{FLRed}Schema validation failed:{CRst} {FGray}{schema_file}{CRst}")
        for err in errors:
            print(f"  {FLRed}- {err}{CRst}")
        return 1

    settings = schema.get("settings", {}) if isinstance(schema, dict) else {}
    if not isinstance(settings, dict):
        settings = {}

    tasks_section = schema.get("tasks") or {}
    if not isinstance(tasks_section, dict):
        print(f"{FLRed}'tasks' must be a dict (group_name → task list):{CRst} {FGray}{schema_file}{CRst}")
        return 1

    # ================================================================
    # Build flat task list in schema order, including the ungrouped section.
    # ================================================================
    all_entries: list[tuple[Optional[str], dict]] = []

    for group_name, tlist in tasks_section.items():
        if not isinstance(tlist, list):
            continue
        for t in tlist:
            if not isinstance(t, dict):
                continue
            all_entries.append((None if group_name == models.UNGROUPED_KEY else group_name, t))

    if not all_entries:
        print(f"{FLYellow}WARNING: No tasks found in schema. Exiting.{CRst}")
        return 1 if cli_auto else 0

    # ---- Scan YAML for name: line numbers (for duplicate-name error reporting) ----
    with open(schema_file, "r", encoding="utf-8") as fh:
        yaml_text = fh.read()

    # Ordered list of (group, task_name) and (group, task_name, sub_name) from parsed schema
    _task_name_order: list[tuple[Optional[str], str]] = []
    _subtask_name_order: list[tuple[Optional[str], str, str]] = []
    for g, t in all_entries:
        _task_name_order.append((g, t.get("name", "")))
        for st in (t.get("sub-tasks") or []):
            if isinstance(st, dict):
                _subtask_name_order.append((g, t.get("name", ""), st.get("name", "")))

    # Scan the raw YAML for all "  - name: ..." lines
    _name_matches = list(re.finditer(r'^\s*-\s+name:\s*(.+)$', yaml_text, re.MULTILINE))
    _name_entries: list[tuple[int, str]] = []
    for m in _name_matches:
        lineno = yaml_text[:m.start()].count('\n') + 1
        val = m.group(1).strip().strip('"').strip("'")
        _name_entries.append((lineno, val))

    # First len(_task_name_order) entries are task names
    _task_name_to_lines: dict[str, list[tuple[Optional[str], int]]] = {}
    for (g, tn), (lineno, _) in zip(_task_name_order, _name_entries[:len(_task_name_order)]):
        _task_name_to_lines.setdefault(tn, []).append((g, lineno))

    # Remaining are sub-task names
    _subtask_name_to_lines: dict[tuple[Optional[str], str, str], list[int]] = {}
    for (g, tn, sn), (lineno, _) in zip(_subtask_name_order, _name_entries[len(_task_name_order):]):
        key = (g, tn, sn)
        if key not in _subtask_name_to_lines:
            _subtask_name_to_lines[key] = []
        _subtask_name_to_lines[key].append(lineno)

    platform_cur = sys.platform
    arch_cur = System.get_arch()
    computer_cur = System.get_computer_name()

    # Pre-compute matching sub-tasks for every task (reused in Steps 4-5).
    # Task-level ``platform`` / ``arch`` / ``computer-name`` are merged
    # into each sub-task for matching, and both task-level and sub-task-level
    # ``inherit`` profiles are resolved so that machine constraints inside
    # profiles also participate.  The stored SyncTask is the original sub-task
    # — the full merge happens at execution time.
    _matching_subs_cache: dict[int, list[schema_ops.SyncTask]] = {}
    _matching_entries: set[int] = set()
    for i, (group_name, t) in enumerate(all_entries):
        raw_subs = t.get("sub-tasks") or []
        if raw_subs:
            task_name = t.get("name", models.UNNAMED_TASK)
            task_label = f"{group_name}/{task_name}" if group_name else task_name
            parent_dict = {k: v for k, v in t.items() if k != "sub-tasks"}
            try:
                parent = schema_ops.SyncTask.from_inheritance_chain(settings, parent_dict)
            except ValueError as e:
                print(f"{FLRed}Inheritance error in task '{task_label}': {e}{CRst}")
                return 1
            matching: list[schema_ops.SyncTask] = []
            for st in raw_subs:
                sub = schema_ops.SyncTask.from_dict(st)
                try:
                    sub_prof = sub.resolve_profiles(settings)
                except ValueError as e:
                    print(f"{FLRed}Inheritance error in sub-task '{task_label}/{st.get('name', '')}': {e}{CRst}")
                    return 1
                if parent.merge(sub_prof).matches_machine(platform_cur, arch_cur, computer_cur):
                    matching.append(sub)
            _matching_subs_cache[i] = matching
            if matching:
                _matching_entries.add(i)
        else:
            _matching_subs_cache[i] = []
            parent = schema_ops.SyncTask.from_inheritance_chain(settings, t)
            if parent.matches_machine(platform_cur, arch_cur, computer_cur):
                _matching_entries.add(i)

    while True:
        # ================================================================
        # Step 4: Select task
        # ================================================================
        selected_task_dict: Optional[dict] = None
        selected_entry_idx: int = -1

        if cli_auto:
            assert cli_task is not None
            target_group, target_name = (None, cli_task)
            if "/" in cli_task:
                parts = cli_task.split("/", 1)
                target_group, target_name = parts[0], parts[1]

            # Reject --task when the name is duplicated
            dup_entries = _task_name_to_lines.get(target_name, [])
            if len(dup_entries) > 1:
                print(f"{FLRed}Duplicate task name '{target_name}':{CRst}")
                for g, lineno in dup_entries:
                    label = f"{g}/{target_name}" if g else target_name
                    print(f"  {FGray}line {lineno}:{CRst} {FLCyan}{label}{CRst}")
                return 1

            for i, (group_name, t) in enumerate(all_entries):
                if t.get("name") == target_name:
                    if target_group is None or group_name == target_group:
                        selected_task_dict = t
                        selected_entry_idx = i
                        break

            if selected_task_dict is None:
                matches = [f"{g}/{t.get('name')}" for g, t in all_entries if t.get("name") == target_name]
                if matches:
                    print(f"{FLRed}Task '{cli_task}' not found. Did you mean:{CRst}")
                    for m in matches:
                        print(f"  {FGray}{m}{CRst}")
                else:
                    print(f"{FLRed}Task '{cli_task}' not found.{CRst}")
                return 1
            if selected_entry_idx not in _matching_entries:
                print(f"{FLYellow}WARNING: Task '{cli_task}' has no sub-tasks matching this machine. Exiting.{CRst}")
                return 1
        else:
            Console.print_separator(width=models.DISPLAY_WIDTH, color_ansi_esc=None, indent=2)
            print(f"  Available tasks from `{FGray}{schema_file}{CRst}`:\n")

            # Build mapping: display index -> all_entries index (only matching tasks)
            selectable_map: dict[int, int] = {}
            selectable_set: set[int] = set()
            display_total = 0
            for i in range(len(all_entries)):
                if i in _matching_entries:
                    selectable_map[display_total] = i
                    selectable_set.add(i)
                    display_total += 1

            max_digits = len(str(max(display_total - 1, 0)))

            # Display all tasks — matching get numbers, non-matching shown in gray
            d_idx = 0   # display index (only for matching tasks)
            prev_group: Optional[str] = None
            for all_idx, (group_name, t) in enumerate(all_entries):
                tname = t.get("name", models.UNNAMED_TASK)
                is_match = all_idx in selectable_set

                # Blank line between groups
                if all_idx > 0 and group_name != prev_group:
                    print()

                if is_match:
                    if group_name is None:
                        print(f"  {FGray}[{CRst}{d_idx:>{max_digits}}{FGray}]{CRst}: {FLCyan}{tname}{CRst}")
                    else:
                        print(f"  {FGray}[{CRst}{d_idx:>{max_digits}}{FGray}]{CRst}: {FLYellow}{group_name}{CRst}/{FLCyan}{tname}{CRst}")
                    d_idx += 1
                else:
                    if group_name is None:
                        print(f"  {FGray}{' ' * (max_digits + 4)}{tname}{CRst}")
                    else:
                        print(f"  {FGray}{' ' * (max_digits + 4)}{group_name}/{tname}{CRst}")

                prev_group = group_name

            if not selectable_map:
                print(f"\n  {FLYellow}WARNING: No tasks have sub-tasks matching this machine. Exiting.{CRst}")
                return 0

            print()
            print(f"  {FGray}[{CRst}{'P':>{max_digits}}{FGray}]{CRst}: {FLCyan}Show rclone config file path{CRst}")
            print(f"  {FGray}[{CRst}{'O':>{max_digits}}{FGray}]{CRst}: {FLCyan}Open rclone config file{CRst}")
            print(f"  {FGray}[{CRst}{'C':>{max_digits}}{FGray}]{CRst}: {FLCyan}Encrypt/Decrypt rclone config file{CRst}")
            print(f"  {FGray}[{CRst}{'Q':>{max_digits}}{FGray}]{CRst}: {FGray}Quit{CRst}")
            Console.print_separator(width=models.DISPLAY_WIDTH, color_ansi_esc=None, indent=2)

            # Warn about duplicate task names
            _dup_task_names = {tn: entries for tn, entries in _task_name_to_lines.items() if len(entries) > 1}
            if _dup_task_names:
                print(f"\n  {FLYellow}Warning: duplicate task names:{CRst}")
                for tn, entries in _dup_task_names.items():
                    for g, lineno in entries:
                        label = f"{g}/{tn}" if g else tn
                        print(f"    {FGray}line {lineno}:{CRst} {FLCyan}{label}{CRst}")

            print(f"\n  Enter {FLGreen}number{CRst} to select, {FLCyan}P/O/C{CRst} for rclone config, {FLCyan}E{CRst} to open YAML, or {FLCyan}Q/Enter{CRst} to exit")

            while True:
                try:
                    choice = input(f"\n{FLYellow}Select task{CRst} {FGray}[# / P / O / C / E / Q=quit]{CRst}: ").strip()
                except EOFError:
                    print()
                    Console.print_exit_message("Bye.")
                    return 0
                if not choice or choice.lower() == "q":
                    Console.print_exit_message("Bye.")
                    return 0
                if choice.lower() == "e":
                    System.open_with_default_app(schema_file)
                    continue
                if choice.lower() in {"p", "o"}:
                    terminal._config_file_action(rclone_exe, open_file=choice.lower() == "o")
                    Console.print_exit_message("Bye.")
                    return 0
                if choice.lower() == "c":
                    print(f"\n{FLYellow}Opening the native rclone config menu.{CRst}")
                    print(f"{FGray}Choose 's) Set configuration password' to encrypt, change the password, or decrypt.{CRst}")
                    try:
                        # Inherit the terminal for rclone's own menus/password input.
                        return backend._run_interruptible([rclone_exe, "config"]).returncode
                    except backend.OperationCancelled:
                        return 0
                    except OSError as exc:
                        print(f"{FLRed}Could not start rclone config: {exc}{CRst}")
                        return 1
                    finally:
                        Console.print_exit_message("Restart this script before running sync tasks.")
                if choice.isdigit():
                    sel_idx = int(choice)
                    if sel_idx in selectable_map:
                        selected_entry_idx = selectable_map[sel_idx]
                        _, selected_task_dict = all_entries[selected_entry_idx]
                        break
                    print(f"{FLRed}Invalid number: {sel_idx}{CRst}")
                    continue
                print(f"{FLRed}Enter a number, P/O/C for rclone config, E to open YAML, or Q/Enter to exit.{CRst}")

        assert selected_task_dict is not None
        _task_group = all_entries[selected_entry_idx][0]
        _task_name = selected_task_dict.get("name", models.UNNAMED_TASK)
        _task_label = f"{_task_group}/{_task_name}" if _task_group else _task_name

        # ---- Resolve task with inheritance ----
        try:
            merged_task = schema_ops.SyncTask.from_inheritance_chain(settings, selected_task_dict)
        except ValueError as e:
            print(f"{FLRed}Inheritance error in task '{_task_label}': {e}{CRst}")
            return 1

        if cli_verbose:
            print(f"{FGray}Selected: {_task_label}{CRst}")

        # ================================================================
        # Step 5: Sub-task selection (reuses pre-computed matching list)
        # ================================================================
        matching_subs = _matching_subs_cache[selected_entry_idx]
        selected_subtask: Optional[schema_ops.SyncTask] = None
        subtask_go_back = False

        # Check for duplicate sub-task names within this task (warn interactive, reject --sub-task)
        raw_subs = selected_task_dict.get("sub-tasks") or []
        sub_name_counts: dict[str, int] = {}
        for st in raw_subs:
            if isinstance(st, dict):
                sn = st.get("name", "")
                sub_name_counts[sn] = sub_name_counts.get(sn, 0) + 1
        _dup_sub_names = {sn: cnt for sn, cnt in sub_name_counts.items() if cnt > 1}

        if cli_sub_task:
            if cli_sub_task in _dup_sub_names:
                task_group = all_entries[selected_entry_idx][0]
                task_name = selected_task_dict.get("name", "")
                task_label = f"{task_group}/{task_name}" if task_group else task_name
                print(f"{FLRed}Duplicate sub-task name '{FLYellow}{cli_sub_task}{FLRed}' in task '{FLYellow}{task_label}{FLRed}':{CRst}")
                key = (task_group, task_name, cli_sub_task)
                for lineno in _subtask_name_to_lines.get(key, []):
                    print(f"  {FGray}line {lineno}{CRst}")
                return 1

            if not matching_subs:
                print(f"{FLRed}Task {FLYellow}{_task_label}{FLRed} has no sub-tasks matching this machine.{CRst}")
                return 1
            found = next((st for st in matching_subs if st.name == cli_sub_task), None)
            if found is None:
                names = [st.name for st in matching_subs]
                print(f"{FLRed}Sub-task '{cli_sub_task}' not found in task {FLYellow}{_task_label}{FLRed}. Matching: {', '.join(names)}{CRst}")
                return 1
            selected_subtask = found
        elif matching_subs:
            # Warn about duplicate sub-task names
            if _dup_sub_names:
                print(f"\n  {FLYellow}Warning: duplicate sub-task names in {_task_label}:{CRst}")
                for sn in _dup_sub_names:
                    key = (_task_group, _task_name, sn)
                    for lineno in _subtask_name_to_lines.get(key, []):
                        print(f"    {FGray}line {lineno}:{CRst} {FLCyan}{sn}{CRst}")

            if len(matching_subs) == 1:
                selected_subtask = matching_subs[0]
            else:
                print(f"\nMultiple sub-tasks of task {FLYellow}{_task_label}{CRst} match this machine:")
                for idx, sub in enumerate(matching_subs):
                    print(f"  {FGray}[{CRst}{idx}{FGray}]{CRst}: {FLGreen}{sub.name}{CRst}{terminal.display_filters(sub)}")
                back_label = "Quit" if cli_auto else "Back to task menu"
                print(f"  {FGray}[{CRst}Q{FGray}]{CRst}: {FGray}{back_label}{CRst}")

                while True:
                    try:
                        choice = input(
                            f"\n{FLYellow}Select sub-task for {_task_label}{CRst} "
                            f"{FGray}[# / Q or Enter={back_label.lower()}]{CRst}: "
                        ).strip()
                    except EOFError:
                        print()
                        return 0
                    if not choice or choice.lower() == "q":
                        subtask_go_back = True
                        break
                    if choice.isdigit():
                        idx = int(choice)
                        if 0 <= idx < len(matching_subs):
                            selected_subtask = matching_subs[idx]
                            break
                        print(f"{FLRed}Invalid number: {idx}{CRst}")
                        continue
                    print(f"{FLRed}Enter a number, or Q/Enter to {back_label.lower()}.{CRst}")

            if subtask_go_back:
                if cli_auto:
                    return 0
                continue  # back to task selection

        # ---- Merge sub-task into final task, resolve paths ----
        if selected_subtask:
            # Re-validate sub-task matches this machine at execution time
            if not selected_subtask.matches_machine(platform_cur, arch_cur, computer_cur):
                print(f"{FLRed}Selected sub-task '{_task_label}/{selected_subtask.name}' does not match this machine.{CRst}")
                return 1
            # Resolve sub-task's own inherit profiles on top of the sub-task
            # before merging onto the already-resolved task.
            try:
                sub_resolved = selected_subtask.resolve_profiles(settings)
            except ValueError as e:
                print(f"{FLRed}Inheritance error in sub-task '{_task_label}/{selected_subtask.name}': {e}{CRst}")
                return 1
            final_task = merged_task.merge(sub_resolved)
            final_task.name = f"{_task_label}/{selected_subtask.name}"
        else:
            print(f"{FLRed}No matching sub-tasks for this machine — task requires a compatible sub-task.{CRst}")
            return 1

        final_errors = final_task.validate("selected task")
        if final_errors:
            print(f"{FLRed}Resolved task validation failed:{CRst}")
            for err in final_errors:
                print(f"  {FLRed}- {err}{CRst}")
            return 1

        try:
            endpoint_ops.resolve_paths(final_task, schema_dir, script_dir, schema_ops._parse_local_volumes(schema.get('local-volumes', {})))
        except ValueError as exc:
            print(f"{FLRed}Path expansion failed for '{final_task.name}': {exc}{CRst}")
            if cli_auto:
                return 1
            continue  # keep the schema and password, return to task selection

        # ---- Alternative remote host selection ----
        if not terminal._interactive_batch_hosts(final_task, cli_auto):
            continue  # back to task selection without using the current host
        if not terminal._interactive_custom_hosts(final_task, cli_auto):
            continue

        # ================================================================
        # Step 6: Select action before the optional pre-sync check
        # ================================================================

        # Determine direction before pre-sync check so the check uses the same direction
        # ---- Interactive operation selection (includes direction) ----
        try:
            action = terminal._select_action(final_task, cli_action, cli_direction)
            if action is None:
                if cli_auto:
                    return 0
                continue  # back to task selection
            final_task = backend._task_for_action(final_task, action)
            if cli_resync and action is not models.SyncAction.BISYNC:
                raise ValueError("--resync requires the bisync action")
        except ValueError as exc:
            print(f"{FLRed}{exc}{CRst}")
            if cli_auto:
                return 1
            continue
        _, action_direction = models.ACTION_COMMANDS[action]
        directional = action_direction is not None
        direction = action_direction or "push"

        # Auto-execute with --task and --action (or the legacy --direction). When --task
        # is supplied from the CLI, there is no task list to return to.
        auto_execute = cli_task is not None and (cli_action is not None or cli_direction is not None)
        comparison = terminal._select_comparison_mode(
            final_task, cli_comparison, interactive=not auto_execute,
        )
        if comparison is None:
            if cli_auto:
                return 1 if auto_execute or cli_comparison is not None else 0
            continue

        pair_tasks = endpoint_ops.path_tasks(final_task)

        cancel_hint = (
            "Press Ctrl+C to cancel and exit with code 130."
            if cli_auto else
            "Press Ctrl+C to cancel and return to the task menu."
        )

        # ================================================================
        # Step 7: Confirm & execute
        # ================================================================
        print("────────────")
        task_summary = (
            f"  {FLYellow}Task:{CRst} {FLCyan}{final_task.name}{CRst}  "
            f"{FLYellow}action:{CRst} {FLCyan}{action.value}{CRst}"
        )
        if comparison is not None:
            task_summary += (
                f"  {FLYellow}comparison:{CRst} "
                f"{FLCyan}{comparison.value}{CRst}"
            )
        commands = [
            backend.to_command(pair, rclone_exe, dry_run=cli_dry_run, direction=direction, comparison=comparison, resync=cli_resync)
            for pair in pair_tasks
        ]
        ignored_filters = backend.ignored_file_filter_flags(final_task)
        filter_warning = (
            f"  {FLYellow}WARNING: File task uses exact paths; ignoring file-selection "
            f"filters: {', '.join(ignored_filters)}.{CRst}"
            if ignored_filters else ""
        )
        if cli_dry_run:
            if filter_warning:
                print(filter_warning)
            terminal._print_commands(commands)
            print(task_summary)
            print(f"\n{FGray}(dry-run - command only, no changes made){CRst}")
            return 0

        # Show path modification times for user awareness.
        # Only show directional danger warnings for sync/copy/move (not bisync/check).
        warnings: list[str] = []
        if final_task.do_not_check_modified_time:
            print(f"{FGray}Path modification time check skipped by configuration.{CRst}")
        else:
            print(f"\n{FLCyan}Checking path modification times...{CRst} {FGray}{cancel_hint}{CRst}")
            try:
                for index, pair in enumerate(pair_tasks, 1):
                    print(f"{FLCyan}[{index}/{len(pair_tasks)}]{CRst} {FLYellow}{pair.name}{CRst}")
                    pair_warnings = terminal._display_path_mtimes(pair, rclone_exe, direction if directional else "")
                    warnings.extend(
                        f"[{index}/{len(pair_tasks)}] {warning}" if len(pair_tasks) > 1 else warning
                        for warning in pair_warnings
                    )
            except backend.OperationCancelled:
                if cli_auto:
                    return 130
                continue

        if filter_warning:
            warnings.append(filter_warning)
        if final_task.mode == "move":
            source_side = "local" if direction == "push" else "remote"
            warnings.append(
                f"  {FLYellow}  ⚠ WARNING:{CRst} {FLCyan}{action.value}{CRst} "
                f"{FLRed}will delete {source_side} source files after successful transfer "
                f"or an identical destination match!{CRst}"
            )
        if final_task.mode == "bisync":
            print(f"{FGray}Bisync keeps local as Path1 and remote as Path2; state is stored in rclone's work directory.{CRst}")
            if cli_resync:
                warnings.append(f"  {FLYellow}  ⚠ WARNING: Rebuilding bisync state (--resync); rclone's default conflict preference is Path1 (local).{CRst}")
            else:
                print(f"{FGray}First use or comparison changes may require an explicit --resync run.{CRst}")
        go_back = False
        while True:
            for warning in warnings:
                print(warning)
            terminal._print_commands(commands)
            print(task_summary)
            if auto_execute:
                break  # skip confirmation, execute directly
            try:
                choice = input(
                    f"\n{FLYellow}Execute{CRst} {FLCyan}{action.value}{CRst}{FLYellow}?{CRst} "
                    f"{FGray}[{FLGreen}y{FGray}=yes / {FLCyan}n{FGray}=back / {FLCyan}d{FGray}=dry-run / {FLCyan}Q{FGray}=quit]{CRst}: "
                ).strip().lower()
            except EOFError:
                print()
                Console.print_exit_message("Bye.")
                return 0

            if not choice:
                continue
            if choice == "y":
                break
            elif choice == "n":
                go_back = True
                break
            elif choice == "d":
                print(f"\n{FLCyan}Running dry-run...{CRst} {FGray}{cancel_hint}{CRst}\n")
                try:
                    dry_code, _ = execution._run_path_batch(
                        pair_tasks, commands, rclone_exe, direction, precheck=False, dry_run=True,
                    )
                except backend.OperationCancelled:
                    if cli_auto:
                        return 130
                    go_back = True
                    break
                if dry_code == 0:
                    print(f"\n{FGray}(dry-run complete — no changes){CRst}")
                else:
                    print(f"\n{FLRed}Dry-run failed with exit code {dry_code}.{CRst}")
                continue
            elif choice == "q":
                Console.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter y, n, d, or q.{CRst}")

        if go_back:
            continue  # back to outermost task selection loop

        # ---- Execute ----
        print(f"\n{FLYellow}Running...{CRst} {FGray}{cancel_hint}{CRst}\n")
        try:
            exit_code, next_pair = execution._run_path_batch(pair_tasks, commands, rclone_exe, direction)
        except backend.OperationCancelled:
            if cli_auto:
                return 130
            continue

        if exit_code == 0:
            print(f"\n{FLGreen}Operation '{action.value}' completed successfully.{CRst}")
        else:
            print(f"\n{FLRed}Operation '{action.value}' failed with exit code {exit_code}.{CRst}")

        if final_task.notify_after_sync:
            status = "completed" if exit_code == 0 else f"failed (code {exit_code})"
            execution._notify(f"rclone-sync: {final_task.name}", f"{action.value} {status}")

        if auto_execute:
            return exit_code

        # ================================================================
        # Step 8: Post-execution menu
        # ================================================================
        while True:
            rerun_label = f"retry from [{next_pair + 1}/{len(pair_tasks)}]" if next_pair < len(pair_tasks) else "re-run all"
            try:
                choice = input(
                    f"\n{FLYellow}What next?{CRst} {FGray}[{FLGreen}m{FGray}/{FLGreen}Enter{FGray}=back to menu / {FLCyan}r{FGray}={rerun_label} / {FLCyan}Q{FGray}=quit]{CRst}: "
                ).strip().lower()
            except EOFError:
                print()
                Console.print_exit_message("Bye.")
                return 0

            if not choice or choice == "m":
                break  # back to task selection menu
            elif choice == "r":
                print(f"\n{FLYellow}Re-running...{CRst} {FGray}{cancel_hint}{CRst}\n")
                try:
                    start = next_pair if next_pair < len(pair_tasks) else 0
                    exit_code, next_pair = execution._run_path_batch(
                        pair_tasks, commands, rclone_exe, direction, start=start, precheck=False,
                    )
                except backend.OperationCancelled:
                    if cli_auto:
                        return 130
                    break
                if exit_code == 0:
                    print(f"\n{FLGreen}Operation '{action.value}' completed successfully.{CRst}")
                else:
                    print(f"\n{FLRed}Operation '{action.value}' failed with exit code {exit_code}.{CRst}")
            elif choice == "q":
                Console.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter m/Enter, r, or q.{CRst}")
