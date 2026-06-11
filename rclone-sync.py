#!/usr/bin/env python3
"""Cross-platform rclone sync task runner driven by a YAML schema.

Usage:
    python rclone-sync.py                  # interactive
    python rclone-sync.py --help           # show help
    python rclone-sync.py --task "group/task-name"
    python rclone-sync.py --task "task-name" --sub-task "sub-name"
    python rclone-sync.py --dry-run
"""

import sys
import os
import subprocess
import copy
import dataclasses
import argparse
import re
from typing import Optional, Any, Union, Set

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from utils import *

# ================================================================
# Constants
# ================================================================

ENV_SCHEMA_FILE = "ZL_RCLONE_SYNC_SCHEMA_FILE"
ENV_CONFIG_PASSWORD = "ZL_RCLONE_CONFIG_PASSWORD"
DEFAULT_SCHEMA_FILE = "./rclone-sync-default-schema.yaml"
UNGROUPED_KEY = "ungrouped"
UNNAMED_TASK = "unnamed"
DISPLAY_WIDTH = 60

VALID_MODES       = {"sync", "copy", "move", "check", "bisync"}
VALID_PLATFORMS   = {"all", "windows", "linux", "darwin", "macos"}
VALID_ARCHS       = {"all", "386", "arm", "arm64", "amd64", "x86", "x64"}
VALID_LOG_LEVELS  = {"ERROR", "NOTICE", "INFO", "DEBUG"}

_DATA_MODES = {"sync", "copy", "move", "bisync"}
_DIRECTIONAL_MODES = {"sync", "copy", "move"}  # modes where push/pull makes sense

VALID_DIRECTIONS = {"push", "pull"}
LIST_STRING_FIELDS = {"exclude", "additional-args"}

# ================================================================
# The default schema is at: ./rclone-sync-default-schema.yaml
# This file is bundled alongside this script and is the fallback when
# neither the environment variable nor CLI argument specifies a schema.
# ================================================================


# ================================================================
# FieldDef — schema definition for one SyncTask field
# ================================================================

@dataclasses.dataclass
class FieldDef:
    """Definition of a single field in :class:`SyncTask`.

    Attributes:
        yaml_key:   Key name in YAML (e.g. ``"local-path"``).
        py_attr:    Attribute name on SyncTask (e.g. ``"local_path"``).
        default:    Default value when the key is absent.
        required:   If True, the field must be present in the YAML.
        allowed:    Set of valid values, or ``None`` for free-form.
        check_type: Expected Python type for isinstance validation,
                    or ``None`` to skip.
    """
    yaml_key:   str
    py_attr:    str
    default:    Any             = None
    required:   bool            = False
    allowed:    Optional[Set]   = None
    check_type: Optional[type]  = None

    def validate(self, value: Any, path: str = "") -> Optional[str]:
        """Validate *value* against this field.  Returns an error or ``None``."""
        if value is None:
            return None
        if self.allowed is not None and value not in self.allowed:
            return f"{path}: '{self.yaml_key}' must be one of {sorted(self.allowed)}, got '{value}'"
        if self.check_type is int and isinstance(value, bool):
            return f"{path}: '{self.yaml_key}' must be int"
        if self.check_type is not None and not isinstance(value, self.check_type):
            return f"{path}: '{self.yaml_key}' must be {self.check_type.__name__}"
        if self.yaml_key in LIST_STRING_FIELDS:
            if not isinstance(value, list):
                return f"{path}: '{self.yaml_key}' must be list"
            if not all(isinstance(item, str) for item in value):
                return f"{path}: '{self.yaml_key}' must contain only strings"
        if self.yaml_key == "transfer" and isinstance(value, int) and not (1 <= value <= 64):
            return f"{path}: 'transfer' must be in range 1..64"
        return None

    def is_non_default(self, value: Any) -> bool:
        """Return True if *value* differs from the default (used for inheritance merging)."""
        if isinstance(self.default, list):
            return bool(value)
        if value is None:
            return False
        return value != self.default


# ================================================================
# Field registry — ordered list of all SyncTask fields
# ================================================================

_FIELDS: list[FieldDef] = [
    # identifier
    FieldDef("name",              "name",               default="",          required=True),
    FieldDef("inherit",           "inherit_profile",    default=""),
    # mode & behaviour
    FieldDef("mode",              "mode",               default="sync",      allowed=VALID_MODES),
    FieldDef("progress",          "progress",           default=True,        check_type=bool),
    FieldDef("transfer",          "transfer",           default=4,           check_type=int),
    FieldDef("links",             "links",              default=False,       check_type=bool),
    FieldDef("copy-links",        "copy_links",         default=False,       check_type=bool),
    FieldDef("follow-link",       "copy_links",         default=False,       check_type=bool),
    FieldDef("delete-excluded",   "delete_excluded",    default=False,       check_type=bool),
    FieldDef("allow-push",        "allow_push",         default=True,        check_type=bool),
    FieldDef("allow-pull",        "allow_pull",         default=True,        check_type=bool),
    # paths
    FieldDef("local-path",        "local_path",         default=""),
    FieldDef("remote-path",       "remote_path",        default=""),
    FieldDef("backup-dir",        "backup_dir",         default=""),
    # safety
    FieldDef("max-delete",        "max_delete",         default=None,        check_type=int),
    FieldDef("check-before-sync", "check_before_sync",  default=False,       allowed={False, True, "size-only"}),
    FieldDef("stop-on-check-failure", "stop_on_check_failure", default=False, check_type=bool),
    # logging & notification
    FieldDef("log-file",          "log_file",           default=""),
    FieldDef("log-level",         "log_level",          default="",          allowed=VALID_LOG_LEVELS | {""}),
    FieldDef("notify-after-sync", "notify_after_sync",  default=False,       check_type=bool),
    # lists
    FieldDef("exclude",           "exclude",            default=[]),
    FieldDef("additional-args",   "additional_args",    default=[]),
    # filters (not rclone flags)
    FieldDef("platform",          "platform",           default="all",       allowed=VALID_PLATFORMS),
    FieldDef("arch",              "arch",               default="all",       allowed=VALID_ARCHS),
    FieldDef("computer-name",     "computer_name",      default=""),
]

# Lookups
_YAML_TO_ATTR: dict[str, str] = {fd.yaml_key: fd.py_attr for fd in _FIELDS}
_ATTR_TO_FIELD: dict[str, FieldDef] = {fd.py_attr: fd for fd in _FIELDS}
_FIELD_DEFAULTS: dict[str, Any] = {}
for fd in _FIELDS:
    if fd.yaml_key in ("exclude", "additional-args"):
        _FIELD_DEFAULTS[fd.py_attr] = []
    else:
        _FIELD_DEFAULTS[fd.py_attr] = fd.default

# Structural keys inside a raw YAML task dict that are not fields
_STRUCTURAL_KEYS = {"sub-tasks"}


# ================================================================
# SyncTask — a resolved task / sub-task configuration
# ================================================================

@dataclasses.dataclass
class SyncTask:
    """A fully-resolved rclone sync task (or sub-task) configuration.

    All fields mirror the YAML schema keys (hyphens mapped to underscores).
    Use :meth:`from_dict` to build from raw YAML, :meth:`from_inheritance_chain`
    to layer ``default → profile → task → sub-task``, and :meth:`to_command`
    to produce the rclone command line.
    """
    name:              str = ""
    inherit_profile:   str = ""
    mode:              str = "sync"
    progress:          bool = True
    transfer:          int = 4
    links:             bool = False
    copy_links:        bool = False
    delete_excluded:   bool = False
    allow_push:        bool = True
    allow_pull:        bool = True
    local_path:        str = ""
    remote_path:       str = ""
    backup_dir:        str = ""
    max_delete:        Optional[int] = None
    check_before_sync: Union[bool, str] = False
    stop_on_check_failure: bool = False
    log_file:          str = ""
    log_level:         str = ""
    notify_after_sync: bool = False
    exclude:           list = dataclasses.field(default_factory=list)
    additional_args:   list = dataclasses.field(default_factory=list)
    platform:          str = "all"
    arch:              str = "all"
    computer_name:     str = ""
    sub_tasks:         list['SyncTask'] = dataclasses.field(default_factory=list)
    explicit_fields:   set[str] = dataclasses.field(default_factory=set, repr=False)

    # ---- factory methods ----

    @classmethod
    def from_dict(cls, data: dict) -> 'SyncTask':
        """Build a SyncTask from a raw YAML dict.

        Only keys listed in the field registry are consumed.  Missing keys
        get the default defined in :class:`FieldDef`.  ``sub-tasks`` is
        recursed into.
        """
        kwargs: dict[str, Any] = dict(_FIELD_DEFAULTS)
        explicit_fields: set[str] = set()
        for yk, val in data.items():
            if yk in _STRUCTURAL_KEYS:
                continue
            attr = _YAML_TO_ATTR.get(yk)
            if attr is not None and val is not None:
                kwargs[attr] = val
                explicit_fields.add(attr)

        instance = cls(**kwargs)
        instance.explicit_fields = explicit_fields

        # recurse into sub-tasks
        raw_subs = data.get("sub-tasks")
        if isinstance(raw_subs, list):
            instance.sub_tasks = [cls.from_dict(st) for st in raw_subs]

        return instance

    @classmethod
    def from_inheritance_chain(cls, settings: dict, task_dict: dict) -> 'SyncTask':
        """Resolve full inheritance: ``default → named profile → task dict``.

        *settings* is the raw YAML ``settings`` block (dict of profile
        name → field dict).  *task_dict* is one raw task entry.
        """
        result = cls()

        # 1. global default
        defaults = settings.get("default")
        if isinstance(defaults, dict):
            result = result.merge(cls.from_dict(defaults))

        # 2. named profile (inherit)
        inh = task_dict.get("inherit")
        profile = settings.get(inh) if inh else None
        if isinstance(profile, dict):
            result = result.merge(cls.from_dict(profile))

        # 3. task itself (preserve sub-tasks for later filtering)
        task_only = {k: v for k, v in task_dict.items() if k != "sub-tasks"}
        return result.merge(cls.from_dict(task_only))

    # ---- inheritance merge ----

    def merge(self, override: 'SyncTask') -> 'SyncTask':
        """Return a new SyncTask with non-default fields from *override* layered on top."""
        result = copy.deepcopy(self)
        for fd in _FIELDS:
            if fd.py_attr in override.explicit_fields:
                ov = getattr(override, fd.py_attr)
                setattr(result, fd.py_attr, copy.deepcopy(ov))
                result.explicit_fields.add(fd.py_attr)
        # sub-tasks are always taken from the override when present
        if override.sub_tasks:
            result.sub_tasks = copy.deepcopy(override.sub_tasks)
        return result

    # ---- validation ----

    def validate(self, path: str = "", is_subtask: bool = False) -> list[str]:
        """Validate this task against the field definitions. Returns error list."""
        errors: list[str] = []
        for fd in _FIELDS:
            val = getattr(self, fd.py_attr)
            err = fd.validate(val, path)
            if err:
                errors.append(err)

        # required fields
        if self.name == "":
            errors.append(f"{path}: 'name' is required")
        if self.links and self.copy_links:
            errors.append(f"{path}: 'links' and 'copy-links' cannot both be true")
        if not self.allow_push and not self.allow_pull:
            errors.append(f"{path}: at least one of 'allow-push' or 'allow-pull' must be true")

        if not is_subtask:
            for j, st in enumerate(self.sub_tasks or []):
                st_path = f"{path}.sub-tasks[{j}]"
                errors.extend(st.validate(st_path, is_subtask=True))

        return errors

    # ---- platform / arch / computer-name matching ----

    def matches_machine(self, platform: str, arch: str, hostname: str) -> bool:
        """Return True if this task's filters match the given machine identity."""
        p = self.platform.lower()
        if p == "macos":
            p = "darwin"
        if p != "all" and p != platform:
            return False
        a = self.arch.lower()
        if a != "all" and a != arch:
            return False
        cn = self.computer_name.strip()
        if cn and cn.lower() != hostname.lower():
            return False
        return True

    def display_filters(self) -> str:
        """Return a colour-formatted filter summary, or empty string."""
        parts: list[str] = []
        p = self.platform.lower()
        if p == "macos":
            p = "darwin"
        if p != "all":
            parts.append(f"os: {p}")
        a = self.arch.lower()
        if a != "all":
            parts.append(f"arch: {a}")
        cn = self.computer_name.strip()
        if cn:
            parts.append(f"computer-name: {cn}")
        return f"  {FGray}[{', '.join(parts)}]{CRst}" if parts else ""

    # ---- path resolution ----

    def resolve_paths(self, schema_dir: str, script_dir: str) -> None:
        """Resolve ``${VAR}`` / ``{{schema_dir}}`` / ``{{script_dir}}`` /
        ``{{current_dir}}`` in all path-type fields in-place."""
        for attr in ("local_path", "remote_path", "backup_dir", "log_file"):
            val = getattr(self, attr)
            if val:
                setattr(self, attr, Utils.resolve_path_vars(val, schema_dir=schema_dir, script_dir=script_dir))

    def find_unresolved_path_vars(self) -> list[str]:
        """Return path fields that still contain unresolved variable syntax."""
        errors: list[str] = []
        patterns = (
            re.compile(r"\$\{[^}]+\}"),
            re.compile(r"\$ENV:[A-Za-z_][A-Za-z0-9_]*"),
            re.compile(r"%[A-Za-z_][A-Za-z0-9_]*%"),
            re.compile(r"\{\{(?:schema_dir|script_dir|current_dir)\}\}"),
        )
        for attr in ("local_path", "remote_path", "backup_dir", "log_file"):
            val = getattr(self, attr)
            if not val:
                continue
            if any(p.search(val) for p in patterns):
                errors.append(f"{attr.replace('_', '-')}: unresolved variable in '{val}'")
        return errors

    # ---- rclone command building ----

    def source_dest(self, direction: str = "push") -> tuple[str, str]:
        """Return source/destination paths after applying the requested direction."""
        src, dst = self.local_path, self.remote_path
        if direction == "pull" and self.mode in _DIRECTIONAL_MODES:
            src, dst = dst, src
        return src, dst

    def _append_filter_flags(self, cmd: list[str]) -> None:
        """Append flags shared by sync/copy/move/check."""
        for pat in self.exclude:
            cmd.extend(["--exclude", pat])
        if self.links:
            cmd.append("--links")
        if self.copy_links:
            cmd.append("--copy-links")

    def _append_log_flags(self, cmd: list[str]) -> None:
        """Append rclone logging flags."""
        if self.log_file:
            cmd.extend(["--log-file", self.log_file])
        if self.log_level:
            cmd.extend(["--log-level", self.log_level])

    def to_command(self, rclone_exe: str, dry_run: bool = False, direction: str = "push") -> list[str]:
        """Build the rclone command line list for this task.

        *direction*: ``"push"`` (local→remote) or ``"pull"`` (remote→local).
        Only affects sync/copy/move modes.
        """
        src, dst = self.source_dest(direction)
        cmd = [rclone_exe, self.mode, src, dst]
        is_data = self.mode in _DATA_MODES

        if is_data and self.progress:
            cmd.append("-P")
        if is_data and self.transfer != 4:
            cmd.extend(["--transfers", str(self.transfer)])
        self._append_filter_flags(cmd)
        if is_data and self.backup_dir:
            cmd.extend(["--backup-dir", self.backup_dir])
        if is_data and self.max_delete is not None:
            cmd.extend(["--max-delete", str(self.max_delete)])
        if is_data and self.delete_excluded:
            cmd.append("--delete-excluded")
        self._append_log_flags(cmd)
        cmd.extend(self.additional_args)
        if dry_run:
            cmd.append("--dry-run")
        return cmd

    # ---- rclone check command ----

    def to_check_command(self, rclone_exe: str, direction: str = "push") -> list[str]:
        """Build an ``rclone check`` command (pre-sync validation)."""
        src, dst = self.local_path, self.remote_path
        if direction == "pull":
            src, dst = dst, src
        cmd = [rclone_exe, "check", src, dst]
        self._append_filter_flags(cmd)
        if self.check_before_sync == "size-only":
            cmd.append("--size-only")
        self._append_log_flags(cmd)
        return cmd


# ================================================================
# YAML schema validation (raw dict level)
# ================================================================

def _validate_field_in_dict(key: str, value: Any, path: str) -> Optional[str]:
    """Validate a single key-value pair from a raw YAML dict against the field registry."""
    fd = _ATTR_TO_FIELD.get(_YAML_TO_ATTR.get(key, ""))
    if fd is None:
        return f"{path}: unknown field '{key}'"
    return fd.validate(value, path)


def _validate_raw_task(task: dict, path: str, known_profiles: set) -> list[str]:
    """Validate one raw task dict (no inheritance applied yet). Returns error list."""
    errors: list[str] = []
    if not isinstance(task, dict):
        return [f"{path}: must be a dict"]
    if "name" not in task:
        errors.append(f"{path}: missing 'name'")

    for key, value in task.items():
        if key in _STRUCTURAL_KEYS:
            continue
        if key == "inherit":
            if isinstance(value, str):
                if value not in known_profiles:
                    errors.append(f"{path}: inherit='{value}' not found in settings")
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and v not in known_profiles:
                        errors.append(f"{path}: inherit='{v}' not found in settings")
            continue
        err = _validate_field_in_dict(key, value, path)
        if err:
            errors.append(err)

    # sub-tasks
    subs = task.get("sub-tasks")
    if subs is not None:
        if not isinstance(subs, list):
            errors.append(f"{path}: 'sub-tasks' must be a list")
        else:
            for j, st in enumerate(subs):
                st_path = f"{path}.sub-tasks[{j}]"
                if not isinstance(st, dict):
                    errors.append(f"{st_path}: must be a dict")
                    continue
                if "name" not in st:
                    errors.append(f"{st_path}: missing 'name'")
                for k, v in st.items():
                    err = _validate_field_in_dict(k, v, st_path)
                    if err:
                        errors.append(err)
    return errors


def _validate_schema(schema: dict) -> list[str]:
    """Validate the complete YAML schema. Returns list of error strings."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["Schema must be a dict with optional 'settings' and required 'tasks'"]

    # --- settings ---
    known_profiles: set[str] = set()
    if "settings" in schema:
        s = schema["settings"]
        if not isinstance(s, dict):
            errors.append("'settings' must be a dict")
        else:
            known_profiles = set(s.keys())
            for pname, pfields in s.items():
                sp = f"settings.{pname}"
                if not isinstance(pfields, dict):
                    errors.append(f"{sp}: must be a dict")
                    continue
                for key, value in pfields.items():
                    err = _validate_field_in_dict(key, value, sp)
                    if err:
                        errors.append(err)

    # --- tasks ---
    if "tasks" not in schema:
        errors.append("Schema must contain 'tasks' section")
        return errors

    tasks = schema["tasks"]
    if not isinstance(tasks, dict):
        return ["'tasks' must be a dict (group_name → task list)"]

    for gname, tlist in tasks.items():
        gp = f"tasks.{gname}"
        if not isinstance(tlist, list):
            errors.append(f"{gp}: must be a list")
            continue
        for i, task in enumerate(tlist):
            errors.extend(_validate_raw_task(task, f"{gp}[{i}]", known_profiles))

    return errors


# ================================================================
# Utilities (rclone detection, display, notification, symlinkd fix)
# ================================================================

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


def _print_cmd(cmd: list[str]) -> None:
    display = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    print(f"\n{FLYellow}Rclone command:{CRst}")
    print(f"  {FGray}{display}{CRst}")


def _notify(title: str, body: str) -> None:
    Utils.notify(title, body)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI args. Help is printed by the custom help path before this runs."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--schema-file")
    parser.add_argument("--rclone-config-file")
    parser.add_argument("--rclone-config-password")
    parser.add_argument("--task")
    parser.add_argument("--sub-task")
    parser.add_argument("--direction", choices=sorted(VALID_DIRECTIONS))
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    ns = parser.parse_args(argv)

    if ns.push and ns.pull:
        parser.error("--push and --pull cannot be used together")
    if ns.push:
        ns.direction = "push"
    if ns.pull:
        ns.direction = "pull"
    return ns


def _fix_windows_symlinkd(local_path: str) -> None:
    """After rclone sync with ``--links`` on Windows, convert file-type symlinks
    that point to directories into proper directory-symlinks (symlinkd).

    Uses the same detection logic as ``windows/link-fix-symlinkd.py``.
    """
    if Utils.get_platform() != "windows":
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


# ================================================================
# Help
# ================================================================

def _print_help() -> None:
    """Print usage help and exit (works without any dependencies)."""
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}RCLONE SYNC RUNNER{CRst}
==================

{FLYellow}Description:{CRst}
  Interactive rclone task runner driven by a YAML schema.
  Lists tasks from the schema, lets you pick one by number,
  auto-filters sub-tasks by platform/arch/computer-name, then
  builds and runs the rclone command.

{FLYellow}Usage:{CRst}
  python {script_name}                        interactive mode
  python {script_name} --task <name>          run task directly
  python {script_name} --task <n> --sub-task <s>
  python {script_name} --task <n> --push      auto-sync (no interaction)
  python {script_name} --dry-run              print command only

{FLYellow}Options:{CRst}
  --schema-file <path>         YAML schema file path (default: ./rclone-sync-default-schema.yaml)
  --rclone-config-file <path>  rclone config file path
  --rclone-config-password <>  encrypted config password ({FLRed}deprecated{CRst}, use env var)
  --task <group/task-name>     skip task selection
  --sub-task <name>            sub-task filter (requires --task)
  --direction <push|pull>      sync direction: push (local -> remote) or pull (remote -> local)
  --push                       shorthand for --direction push
  --pull                       shorthand for --direction pull
  --dry-run                    print command, do not execute
  --verbose                    print additional diagnostics

{FLYellow}Auto-sync:{CRst}
  When --task and --direction are both specified, the script runs without
  any interactive prompts (provided other requirements are met).

{FLYellow}Environment variables:{CRst}
  {FLCyan}{ENV_SCHEMA_FILE}{CRst}    path to YAML schema file (default: ./rclone-sync-default-schema.yaml)
  {FLCyan}{ENV_CONFIG_PASSWORD}{CRst}  password for encrypted rclone config

{FLYellow}Path variables{CRst} (in YAML: local-path, remote-path, backup-dir, log-file):
  {FGray}${{ENV_VAR}}{CRst}          environment variable (also %VAR% on Windows)
  {FGray}$ENV:VAR{CRst} / {FGray}${{ENV:VAR}}{CRst}  PowerShell-style environment variable
  {FGray}{{{{schema_dir}}}}{CRst}       directory containing the YAML file
  {FGray}{{{{script_dir}}}}{CRst}       directory containing rclone-sync.py
  {FGray}{{{{current_dir}}}}{CRst}      current working directory

{FLYellow}Modes:{CRst}
  {FLCyan}sync{CRst}     make destination match source (one-way)
  {FLCyan}copy{CRst}     copy source to destination
  {FLCyan}move{CRst}     move source to destination ({FLRed}deletes source!{CRst})
  {FLCyan}check{CRst}    compare source vs destination (read-only)
  {FLCyan}bisync{CRst}   bidirectional sync between two paths

{FLYellow}Requirements:{CRst}
  rclone, PyYAML.  pip install pyyaml
""")


# ================================================================
# Main
# ================================================================

def main() -> int:
    Utils.print_banner("RCLONE SYNC RUNNER")

    # ---- help (works without any dependencies) ----
    if "--help" in sys.argv or "-h" in sys.argv:
        _print_help()
        return 0

    Utils.print_env_info()

    try:
        import yaml as yaml_mod
    except ImportError:
        Utils.print_error_and_exit("PyYAML is not installed. Run: pip install pyyaml")
        raise  # unreachable — satisfies the type checker

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ---- parse CLI args ----
    try:
        parsed = _parse_args(sys.argv[1:])
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
    cli_auto = cli_task is not None

    # ================================================================
    # Step 1: Resolve YAML schema file path
    # ================================================================
    default_schema = DEFAULT_SCHEMA_FILE
    if ENV_SCHEMA_FILE in os.environ:
        default_schema = os.environ[ENV_SCHEMA_FILE]
    if cli_schema_file:
        default_schema = cli_schema_file

    if cli_auto:
        schema_file = default_schema
    else:
        schema_file = Input.resolve_input_path(
            default_schema,
            prompt="Path to YAML schema file",
            path_type="file",
        )

    schema_file = os.path.abspath(os.path.expanduser(schema_file))
    schema_dir = os.path.dirname(schema_file)

    if cli_verbose:
        print(f"{FGray}Schema file: {schema_file}{CRst}")

    if not os.path.isfile(schema_file):
        print(f"{FLRed}Schema file not found: {FGray}{schema_file}{CRst}")
        return 1

    # ================================================================
    # Step 2: Check rclone & configure password
    # ================================================================
    _rclone = CmdCheck("rclone", hints={
        "windows": f"{FGray}scoop install rclone{CRst}",
        "macos":   f"{FGray}brew install rclone{CRst}",
        "linux":   f"{FGray}sudo apt install rclone{CRst}",
    })
    if not Utils.check_commands(_rclone):
        return 1
    assert _rclone.path is not None
    rclone_exe: str = _rclone.path

    config_password: Optional[str] = None
    if cli_config_password:
        config_password = cli_config_password
    elif ENV_CONFIG_PASSWORD in os.environ:
        config_password = os.environ[ENV_CONFIG_PASSWORD]
    elif _detect_encrypted_config(rclone_exe):
        print(f"{FLYellow}  rclone config is encrypted.{CRst}")
        config_password = Input.input_password("Enter rclone config password")

    if config_password:
        os.environ["RCLONE_CONFIG_PASS"] = config_password
    if cli_config_file:
        os.environ["RCLONE_CONFIG"] = cli_config_file

    # ================================================================
    # Step 3: Load & validate YAML
    # ================================================================
    try:
        with open(schema_file, "r", encoding="utf-8") as fh:
            schema = yaml_mod.safe_load(fh)
    except Exception as e:
        print(f"{FLRed}Failed to read YAML schema: {e}{CRst}")
        return 1

    if schema is None:
        print(f"{FLRed}Schema file is empty.{CRst}")
        return 1

    errors = _validate_schema(schema)
    if errors:
        print(f"{FLRed}Schema validation failed:{CRst}")
        for err in errors:
            print(f"  {FLRed}- {err}{CRst}")
        return 1

    settings = schema.get("settings", {}) if isinstance(schema, dict) else {}
    if not isinstance(settings, dict):
        settings = {}

    tasks_section = schema.get("tasks", {})
    if not isinstance(tasks_section, dict):
        print(f"{FLRed}'tasks' must be a dict (group_name → task list).{CRst}")
        return 1

    # ================================================================
    # Build flat task list: ungrouped first, then groups alphabetically
    # ================================================================
    ungrouped: list[dict] = []
    grouped: list[tuple[str, dict]] = []

    for gname, tlist in tasks_section.items():
        if not isinstance(tlist, list):
            continue
        for t in tlist:
            if not isinstance(t, dict):
                continue
            if gname == UNGROUPED_KEY:
                ungrouped.append(t)
            else:
                grouped.append((gname, t))

    grouped.sort(key=lambda x: x[0].lower())

    all_entries: list[tuple[Optional[str], dict]] = []
    for t in ungrouped:
        all_entries.append((None, t))
    for gname, t in grouped:
        all_entries.append((gname, t))

    if not all_entries:
        print(f"{FLRed}No tasks found in schema.{CRst}")
        return 1

    while True:
        # ================================================================
        # Step 4: Select task
        # ================================================================
        selected_task_dict: Optional[dict] = None

        if cli_auto:
            assert cli_task is not None
            target_group, target_name = (None, cli_task)
            if "/" in cli_task:
                parts = cli_task.split("/", 1)
                target_group, target_name = parts[0], parts[1]

            for gname, t in all_entries:
                if t.get("name") == target_name:
                    if target_group is None or gname == target_group:
                        selected_task_dict = t
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
        else:
            Utils.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)
            print(f"  Available tasks from `{FGray}{schema_file}{CRst}`:\n")

            max_digits = len(str(len(all_entries) - 1)) if len(all_entries) > 0 else 1
            idx = 0

            # Ungrouped tasks first
            for t in ungrouped:
                tname = t.get("name", UNNAMED_TASK)
                print(f"  {FGray}[{idx:>{max_digits}}]{CRst}: {FLCyan}{tname}{CRst}")
                idx += 1

            # Grouped tasks with blank lines between groups
            if grouped:
                print()
                prev_group = ""
                for gname, t in grouped:
                    if prev_group and gname != prev_group:
                        print()
                    tname = t.get("name", UNNAMED_TASK)
                    print(f"  {FGray}[{idx:>{max_digits}}]{CRst}: {FLYellow}{gname}{CRst}/{FLCyan}{tname}{CRst}")
                    idx += 1
                    prev_group = gname

            Utils.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)

            print(f"\n  {FLYellow}Enter number to select{CRst}, {FLCyan}e{CRst} to open YAML, or {FLYellow}Enter{CRst} to exit")

            while True:
                try:
                    choice = input(f"\n{FLYellow}Select task{CRst} {FGray}[#]{CRst}: ").strip()
                except EOFError:
                    print()
                    Utils.print_exit_message("Bye.")
                    return 0
                if not choice:
                    Utils.print_exit_message("Bye.")
                    return 0
                if choice.lower() == "e":
                    Utils.open_with_default_app(schema_file)
                    continue
                if choice.isdigit():
                    idx = int(choice)
                    if 0 <= idx < len(all_entries):
                        _, selected_task_dict = all_entries[idx]
                        break
                    print(f"{FLRed}Invalid number: {idx}{CRst}")
                    continue
                print(f"{FLRed}Enter a number, 'e' to open YAML, or Enter to exit.{CRst}")

        assert selected_task_dict is not None

        # ---- Resolve task with inheritance ----
        merged_task = SyncTask.from_inheritance_chain(settings, selected_task_dict)

        if cli_verbose:
            print(f"{FGray}Selected: {merged_task.name}{CRst}")

        # ================================================================
        # Step 5: Sub-task selection
        # ================================================================
        # Build sub-task SyncTask instances from the raw dict
        raw_subs: list[dict] = selected_task_dict.get("sub-tasks") or []
        all_sub_tasks = [SyncTask.from_dict(st) for st in raw_subs]

        platform_cur = Utils.get_platform()
        arch_cur = Utils.get_arch()
        computer_cur = Utils.get_computer_name()

        matching_subs = [st for st in all_sub_tasks if st.matches_machine(platform_cur, arch_cur, computer_cur)]
        selected_subtask: Optional[SyncTask] = None

        if cli_sub_task:
            if not matching_subs:
                print(f"{FLRed}Task has no sub-tasks matching this machine.{CRst}")
                return 1
            found = next((st for st in matching_subs if st.name == cli_sub_task), None)
            if found is None:
                names = [st.name for st in matching_subs]
                print(f"{FLRed}Sub-task '{cli_sub_task}' not found. Matching: {', '.join(names)}{CRst}")
                return 1
            selected_subtask = found
        elif matching_subs:
            if len(matching_subs) == 1:
                selected_subtask = matching_subs[0]
                print(f"\n{FLCyan}Auto-selected sub-task:{CRst} {FLGreen}{selected_subtask.name}{CRst}{selected_subtask.display_filters()}")
            else:
                print(f"\n{FLYellow}Multiple sub-tasks match this machine:{CRst}")
                for idx, sub in enumerate(matching_subs):
                    print(f"  {FGray}[{idx}]{CRst}: {FLGreen}{sub.name}{CRst}{sub.display_filters()}")

                while True:
                    try:
                        choice = input(
                            f"\n{FLYellow}Select sub-task{CRst} {FGray}[# or Enter to go back]{CRst}: "
                        ).strip()
                    except EOFError:
                        print()
                        return 0
                    if not choice:
                        continue
                    if choice.isdigit():
                        idx = int(choice)
                        if 0 <= idx < len(matching_subs):
                            selected_subtask = matching_subs[idx]
                            break
                        print(f"{FLRed}Invalid number: {idx}{CRst}")

        # ---- Merge sub-task into final task, resolve paths ----
        if selected_subtask:
            final_task = merged_task.merge(selected_subtask)
            final_task.name = f"{merged_task.name}/{selected_subtask.name}"
        else:
            final_task = merged_task

        final_errors = final_task.validate("selected task")
        if final_errors:
            print(f"{FLRed}Resolved task validation failed:{CRst}")
            for err in final_errors:
                print(f"  {FLRed}- {err}{CRst}")
            return 1

        final_task.resolve_paths(schema_dir, script_dir)

        if not final_task.local_path or not final_task.remote_path:
            print(f"{FLRed}Task is missing local-path or remote-path.{CRst}")
            return 1

        # ================================================================
        # Step 6: Pre-sync check (if configured)
        # ================================================================

        # Determine direction before pre-sync check so the check uses the same direction
        directional = final_task.mode in _DIRECTIONAL_MODES
        direction: str = cli_direction or "push"

        if directional and cli_direction is None:
            # ---- Interactive direction selection ----
            print()
            lp, rp = final_task.local_path, final_task.remote_path
            direction_options: list[MenuOption] = []
            if final_task.allow_push:
                direction_options.append(MenuOption(["0"], f"push   {FLCyan}{lp}{CRst} {FGray}->{CRst} {FLCyan}{rp}{CRst}", value="push"))
            if final_task.allow_pull:
                key = "1" if direction_options else "0"
                direction_options.append(MenuOption([key], f"pull   {FLCyan}{rp}{CRst} {FGray}->{CRst} {FLCyan}{lp}{CRst}", value="pull"))
            if not direction_options:
                print(f"{FLRed}Task allows neither push nor pull.{CRst}")
                return 1
            result = Menu.select(
                direction_options,
                prompt="Sync direction",
                default_key=direction_options[0].keys[0],
                separator=False,
            )
            if result is None:
                Utils.print_exit_message("Bye.")
                return 0
            direction = result
        elif not directional and cli_direction:
            print(f"{FGray}  -> direction 'push/pull' ignored for mode '{final_task.mode}'{CRst}")

        if directional and direction == "push" and not final_task.allow_push:
            print(f"{FLRed}Task does not allow push direction.{CRst}")
            return 1
        if directional and direction == "pull" and not final_task.allow_pull:
            print(f"{FLRed}Task does not allow pull direction.{CRst}")
            return 1
        if directional and direction == "pull" and final_task.backup_dir:
            print(f"{FLRed}Refusing pull with backup-dir. Use a task-specific pull backup path or disable backup-dir.{CRst}")
            return 1

        unresolved_path_vars = final_task.find_unresolved_path_vars()
        if unresolved_path_vars:
            print(f"{FLRed}Task contains unresolved path variables:{CRst}")
            for err in unresolved_path_vars:
                print(f"  {FLRed}- {err}{CRst}")
            return 1

        if not cli_dry_run and final_task.check_before_sync and final_task.check_before_sync is not False:
            print(f"\n{FLCyan}Running pre-sync check...{CRst}")
            check_cmd = final_task.to_check_command(rclone_exe, direction=direction)
            _print_cmd(check_cmd)
            result = subprocess.run(check_cmd, check=False)
            if result.returncode != 0:
                print(f"{FLYellow}  -> Differences detected between source and destination.{CRst}")
                if final_task.stop_on_check_failure:
                    print(f"{FLRed}  -> Stopped because stop-on-check-failure is enabled.{CRst}")
                    return result.returncode

        # ================================================================
        # Step 7: Confirm & execute
        # ================================================================
        cmd = final_task.to_command(rclone_exe, dry_run=cli_dry_run, direction=direction)
        _print_cmd(cmd)

        # Auto-execute when both --task and --direction are given
        auto_execute = cli_task is not None and cli_direction is not None

        if cli_dry_run:
            print(f"\n{FGray}(dry-run - no changes made){CRst}")
            return 0
        elif auto_execute:
            pass  # skip confirmation, execute directly
        else:
            while True:
                try:
                    choice = input(
                        f"\n{FLYellow}Execute?{CRst} {FGray}[y=yes / n=back / d=dry-run / q=quit]{CRst}: "
                    ).strip().lower()
                except EOFError:
                    print()
                    Utils.print_exit_message("Bye.")
                    return 0

                if choice == "y":
                    break
                elif choice == "n":
                    continue
                elif choice == "d":
                    dry_cmd = final_task.to_command(rclone_exe, dry_run=True, direction=direction)
                    _print_cmd(dry_cmd)
                    print(f"\n{FGray}(dry-run - no changes made){CRst}")
                    continue
                elif choice == "q":
                    Utils.print_exit_message("Bye.")
                    return 0
                else:
                    print(f"{FLRed}Enter y, n, d, or q.{CRst}")

        # ---- Execute ----
        print(f"\n{FLYellow}Running...{CRst}\n")
        exec_result = subprocess.run(cmd, check=False)

        if exec_result.returncode == 0:
            print(f"\n{FLGreen}Sync completed successfully.{CRst}")
        else:
            print(f"\n{FLRed}Sync failed with exit code {exec_result.returncode}.{CRst}")

        _, sync_dst = final_task.source_dest(direction)
        if final_task.links and os.path.exists(sync_dst):
            _fix_windows_symlinkd(sync_dst)

        if final_task.notify_after_sync:
            status = "completed" if exec_result.returncode == 0 else f"failed (code {exec_result.returncode})"
            _notify(f"rclone-sync: {final_task.name}", f"Sync {status}")

        if auto_execute:
            return exec_result.returncode

        # ================================================================
        # Step 8: Post-execution menu
        # ================================================================
        while True:
            try:
                choice = input(
                    f"\n{FLYellow}What next?{CRst} {FGray}[r=re-run / s=select another / q=quit]{CRst}: "
                ).strip().lower()
            except EOFError:
                print()
                Utils.print_exit_message("Bye.")
                return 0

            if choice == "r":
                print(f"\n{FLYellow}Re-running...{CRst}\n")
                exec_result = subprocess.run(cmd, check=False)
                if exec_result.returncode == 0:
                    print(f"\n{FLGreen}Sync completed successfully.{CRst}")
                else:
                    print(f"\n{FLRed}Sync failed with exit code {exec_result.returncode}.{CRst}")
            elif choice == "s":
                continue
            elif choice == "q":
                Utils.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter r, s, or q.{CRst}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
