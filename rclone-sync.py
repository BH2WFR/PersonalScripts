#!/usr/bin/env python3
"""Cross-platform rclone sync task runner driven by a YAML schema.

Defines reusable sync tasks in YAML, filters sub-tasks by the current machine,
shows source/destination modification times, and runs rclone with interactive
confirmation.  During rclone checks and transfers, Ctrl+C cancels the current
operation and returns to the task menu instead of exiting the whole script.

Requirements:
    - pip: PyYAML
    - system: rclone

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
import json
import re
import datetime
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
MAX_INHERIT_DEPTH = 10  # max recursion depth for profile inheritance chains

VALID_MODES       = {"sync", "copy", "move", "check", "bisync"}
VALID_PLATFORMS   = {"darwin", "linux", "win32", "macos", "windows"}
VALID_ARCHS       = {"386", "arm", "arm64", "amd64", "x86", "x64"}
VALID_LOG_LEVELS  = {"ERROR", "NOTICE", "INFO", "DEBUG"}
VALID_REMOTE_PATH_TYPES = {"auto", "rclone", "local"}

_DATA_MODES = {"sync", "copy", "move", "bisync"}
_DIRECTIONAL_MODES = {"sync", "copy", "move"}  # modes where push/pull makes sense

VALID_DIRECTIONS = {"push", "pull"}
LIST_STRING_FIELDS = {"exclude", "additional-args", "alternative-remote-host"}
STRING_OR_LIST_FIELDS = {"platform", "arch", "computer-name"}

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
        if self.check_type is int and isinstance(value, bool):
            return f"{path}: '{self.yaml_key}' must be int"
        if self.check_type is not None and not isinstance(value, self.check_type):
            return f"{path}: '{self.yaml_key}' must be {self.check_type.__name__}"

        # Fields that accept str or list[str] (OR semantics)
        if self.yaml_key in STRING_OR_LIST_FIELDS:
            if isinstance(value, list):
                if not all(isinstance(item, str) for item in value):
                    return f"{path}: '{self.yaml_key}' must contain only strings"
                if self.allowed is not None:
                    for item in value:
                        if item not in self.allowed:
                            return f"{path}: '{self.yaml_key}' list item '{item}' must be one of {sorted(self.allowed)}"
            elif isinstance(value, str):
                if self.allowed is not None and value != "" and value not in self.allowed:
                    return f"{path}: '{self.yaml_key}' must be one of {sorted(self.allowed)}, got '{value}'"
            else:
                return f"{path}: '{self.yaml_key}' must be string or list of strings"
            return None

        # Fields that are always lists of strings
        if self.yaml_key in LIST_STRING_FIELDS:
            if not isinstance(value, list):
                return f"{path}: '{self.yaml_key}' must be list"
            if not all(isinstance(item, str) for item in value):
                return f"{path}: '{self.yaml_key}' must contain only strings"
            return None

        # Scalar fields with allowed-value check
        if self.allowed is not None and value not in self.allowed:
            return f"{path}: '{self.yaml_key}' must be one of {sorted(self.allowed)}, got '{value}'"

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
    FieldDef("remote-path-type",  "remote_path_type",   default="auto",      allowed=VALID_REMOTE_PATH_TYPES),
    FieldDef("backup-dir",        "backup_dir",         default=""),
    # case sensitivity
    FieldDef("ignore-case",       "ignore_case",        default=False,       check_type=bool),
    FieldDef("ignore-case-sync",  "ignore_case_sync",   default=False,       check_type=bool),
    # comparison strategy
    FieldDef("checksum",          "checksum",           default=False,       check_type=bool),
    FieldDef("size-only",         "size_only",          default=False,       check_type=bool),
    FieldDef("update",            "update",             default=False,       check_type=bool),
    # transfer behaviour
    FieldDef("bwlimit",           "bwlimit",            default="",          check_type=str),
    FieldDef("ignore-errors",     "ignore_errors",      default=False,       check_type=bool),
    FieldDef("retries",           "retries",            default=3,           check_type=int),
    FieldDef("s3-no-check-bucket","s3_no_check_bucket", default=False,       check_type=bool),
    # safety
    FieldDef("max-delete",        "max_delete",         default=None,        check_type=int),
    FieldDef("check-before-sync", "check_before_sync",  default=False,       allowed={False, True, "size-only"}),
    FieldDef("stop-on-check-failure", "stop_on_check_failure", default=False, check_type=bool),
    # logging & notification
    FieldDef("log-file",          "log_file",           default=""),
    FieldDef("log-level",         "log_level",          default="",          allowed=VALID_LOG_LEVELS | {""}),
    FieldDef("notify-after-sync", "notify_after_sync",  default=False,       check_type=bool),
    # lists
    FieldDef("exclude",                "exclude",                default=[]),
    FieldDef("additional-args",        "additional_args",        default=[]),
    FieldDef("alternative-remote-host","alternative_remote_hosts",default=[]),
    # filters (not rclone flags)
    FieldDef("platform",          "platform",           default="",          allowed=VALID_PLATFORMS),
    FieldDef("arch",              "arch",               default="",          allowed=VALID_ARCHS),
    FieldDef("computer-name",     "computer_name",      default=""),
]

# Lookups
_YAML_TO_ATTR: dict[str, str] = {fd.yaml_key: fd.py_attr for fd in _FIELDS}
_ATTR_TO_FIELD: dict[str, FieldDef] = {fd.py_attr: fd for fd in _FIELDS}
_FIELD_DEFAULTS: dict[str, Any] = {}
for fd in _FIELDS:
    if fd.yaml_key in ("exclude", "additional-args", "alternative-remote-host"):
        _FIELD_DEFAULTS[fd.py_attr] = []
    else:
        _FIELD_DEFAULTS[fd.py_attr] = fd.default

# Structural keys inside a raw YAML task dict that are not fields
_STRUCTURAL_KEYS = {"sub-tasks"}


def _normalize_inherit(value) -> list[str]:
    """Normalize an inherit value (str or list) to a list of profile names."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v]
    if isinstance(value, str) and value:
        return [value]
    return []


def _resolve_profile_chain(settings: dict, profile_name: str, visited: set[str], depth: int = 0) -> 'SyncTask':
    """Recursively resolve a named profile, following its own ``inherit``.

    Returns a SyncTask with the profile's fields (and any profiles it
    inherits) resolved.  *visited* prevents infinite recursion on cycles.
    *depth* guards against excessive nesting.
    """
    if depth > MAX_INHERIT_DEPTH:
        raise ValueError(
            f"Profile inheritance depth exceeded (>{MAX_INHERIT_DEPTH}) at '{profile_name}' — "
            f"check for circular or overly deep inherit chains in your YAML."
        )
    if profile_name in visited:
        return SyncTask()
    visited.add(profile_name)

    profile = settings.get(profile_name)
    if not isinstance(profile, dict):
        return SyncTask()

    # 1. Resolve profiles that THIS profile inherits (base layer)
    inh = profile.get("inherit")
    base = SyncTask()
    if isinstance(inh, list):
        for name in inh:
            if isinstance(name, str):
                base = base.merge(_resolve_profile_chain(settings, name, visited, depth + 1))
    elif isinstance(inh, str) and inh:
        base = base.merge(_resolve_profile_chain(settings, inh, visited, depth + 1))

    # 2. Merge this profile's own fields on top
    return base.merge(SyncTask.from_dict(profile))


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
    ignore_case:       bool = False
    ignore_case_sync:  bool = False
    checksum:          bool = False
    size_only:         bool = False
    update:            bool = False
    bwlimit:           str = ""
    ignore_errors:     bool = False
    retries:           int = 3
    s3_no_check_bucket: bool = False
    delete_excluded:   bool = False
    allow_push:        bool = True
    allow_pull:        bool = True
    local_path:        str = ""
    remote_path:       str = ""
    remote_path_type:  str = "auto"
    backup_dir:        str = ""
    max_delete:        Optional[int] = None
    check_before_sync: Union[bool, str] = False
    stop_on_check_failure: bool = False
    log_file:          str = ""
    log_level:         str = ""
    notify_after_sync: bool = False
    exclude:                 list = dataclasses.field(default_factory=list)
    additional_args:         list = dataclasses.field(default_factory=list)
    alternative_remote_hosts: list = dataclasses.field(default_factory=list)
    platform:                Union[str, list] = ""
    arch:                    Union[str, list] = ""
    computer_name:           Union[str, list] = ""
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

        # 2. named profile(s) (inherit) — resolved recursively
        inh = task_dict.get("inherit")
        if isinstance(inh, list):
            visited: set[str] = set()
            for profile_name in inh:
                if isinstance(profile_name, str):
                    result = result.merge(_resolve_profile_chain(settings, profile_name, visited))
        elif isinstance(inh, str) and inh:
            result = result.merge(_resolve_profile_chain(settings, inh, set()))

        # 3. task itself (preserve sub-tasks for later filtering)
        task_only = {k: v for k, v in task_dict.items() if k != "sub-tasks"}
        return result.merge(cls.from_dict(task_only))

    # ---- inheritance merge ----

    def resolve_profiles(self, settings: dict) -> 'SyncTask':
        """Apply named profiles from ``inherit_profile`` on top of this task.

        Does NOT apply ``default`` — only profiles named in this task's
        ``inherit`` field.  Profiles are resolved recursively (a profile
        that itself has ``inherit`` will pull in its parents first).
        """
        profiles = _normalize_inherit(self.inherit_profile)
        if not profiles:
            return self
        result = copy.deepcopy(self)
        visited: set[str] = set()
        for name in profiles:
            result = result.merge(_resolve_profile_chain(settings, name, visited))
        return result

    def merge(self, override: 'SyncTask') -> 'SyncTask':
        """Return a new SyncTask with non-default fields from *override* layered on top."""
        result = copy.deepcopy(self)
        for fd in _FIELDS:
            if fd.py_attr in override.explicit_fields:
                ov = getattr(override, fd.py_attr)
                if fd.py_attr in ("exclude", "alternative_remote_hosts") and isinstance(ov, list):
                    # Append with dedup (preserve base order, then new items)
                    base_list: list = getattr(result, fd.py_attr)
                    seen = set(base_list)
                    merged = list(base_list)
                    for item in ov:
                        if item not in seen:
                            merged.append(item)
                            seen.add(item)
                    setattr(result, fd.py_attr, merged)
                elif fd.py_attr == "inherit_profile" and ov:
                    # Append with dedup — sub-task inherit adds to task inherit
                    base_list = _normalize_inherit(getattr(result, fd.py_attr))
                    ov_list = _normalize_inherit(ov)
                    seen = set(base_list)
                    merged = list(base_list)
                    for item in ov_list:
                        if item not in seen:
                            merged.append(item)
                            seen.add(item)
                    setattr(result, fd.py_attr, merged)
                else:
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

    def _filter_matches(self, value, current: str, case_sensitive: bool = False) -> bool:
        """Check *value* (str, list[str], or empty) against *current*.

        Empty/None means "match any".  List items are OR'd (any match).
        """
        if not value:
            return True
        if isinstance(value, list):
            if case_sensitive:
                return current in value
            return any(current.lower() == v.lower() for v in value)
        # str
        if case_sensitive:
            return current == value
        return current.lower() == value.lower()

    @staticmethod
    def _normalize_platform(p):
        """Normalize platform aliases: 'macos' → 'darwin', 'windows' → 'win32'."""
        if isinstance(p, str):
            pl = p.lower()
            if pl == "macos": return "darwin"
            if pl == "windows": return "win32"
        elif isinstance(p, list):
            result = []
            for v in p:
                vl = v.lower()
                if vl == "macos": result.append("darwin")
                elif vl == "windows": result.append("win32")
                else: result.append(v)
            return result
        return p

    def matches_machine(self, platform: str, arch: str, hostname: str) -> bool:
        """Return True if this task's filters match the given machine identity."""
        if not self._filter_matches(self._normalize_platform(self.platform), platform):
            return False
        if not self._filter_matches(self.arch, arch):
            return False
        if not self._filter_matches(self.computer_name.strip() if isinstance(self.computer_name, str) else self.computer_name, hostname):
            return False
        return True

    def display_filters(self) -> str:
        """Return a colour-formatted filter summary, or empty string."""
        parts: list[str] = []
        p = self._normalize_platform(self.platform)
        if p:
            parts.append(f"os: {', '.join(p) if isinstance(p, list) else p}")
        a = self.arch
        if a:
            parts.append(f"arch: {', '.join(a) if isinstance(a, list) else a}")
        cn = self.computer_name.strip() if isinstance(self.computer_name, str) else self.computer_name
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
        if self.ignore_case:
            cmd.append("--ignore-case")
        if self.ignore_case_sync:
            cmd.append("--ignore-case-sync")

    def _append_log_flags(self, cmd: list[str]) -> None:
        """Append rclone logging flags."""
        if self.log_file:
            cmd.extend(["--log-file", self.log_file])
        if self.log_level:
            cmd.extend(["--log-level", self.log_level])

    def _append_comparison_and_transfer_flags(self, cmd: list[str], is_data: bool) -> None:
        """Append flags shared by sync/copy/move/check: comparison, bwlimit, retries, etc."""
        if is_data:
            if self.checksum:
                cmd.append("--checksum")
            if self.size_only:
                cmd.append("--size-only")
            if self.update:
                cmd.append("--update")
            if self.bwlimit:
                cmd.extend(["--bwlimit", self.bwlimit])
            if self.ignore_errors:
                cmd.append("--ignore-errors")
        if is_data or self.mode == "check":
            if self.retries != 3:
                cmd.extend(["--retries", str(self.retries)])

    def _append_backend_flags(self, cmd: list[str]) -> None:
        """Append backend-specific flags supported by the YAML schema."""
        if self.s3_no_check_bucket:
            cmd.append("--s3-no-check-bucket")

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
        self._append_comparison_and_transfer_flags(cmd, is_data)
        if is_data and self.backup_dir:
            cmd.extend(["--backup-dir", self.backup_dir])
        if is_data and self.max_delete is not None:
            cmd.extend(["--max-delete", str(self.max_delete)])
        if is_data and self.delete_excluded:
            cmd.append("--delete-excluded")
        self._append_backend_flags(cmd)
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
        self._append_comparison_and_transfer_flags(cmd, False)
        self._append_backend_flags(cmd)
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


def _print_cmd(cmd: list[str]) -> None:
    display = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    print(f"  {FLYellow}Rclone command:{CRst}")
    print(f"{FGray}{display}{CRst}")


def _notify(title: str, body: str) -> None:
    Utils.notify(title, body)


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


def _get_local_mtime(path: str) -> Optional["datetime.datetime"]:
    """Return the modification time of a local file or directory as a
    timezone-aware UTC datetime, or ``None`` if the path does not exist.
    """
    try:
        ts = os.path.getmtime(path)
    except OSError:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)


def _get_remote_latest_mtime(
    rclone_exe: str, remote_path: str, timeout: int = 15
) -> Optional["datetime.datetime"]:
    """Return the latest modification time of items immediately inside
    *remote_path* via ``rclone lsjson --max-depth 1``, or ``None`` on failure.

    The path should already be a valid rclone remote reference
    (e.g. ``myremote:path/to/dir``).
    """
    try:
        proc = _run_interruptible(
            [rclone_exe, "lsjson", "--max-depth", "1", remote_path],
            capture_output=True, text=True, timeout=timeout,
        )
    except OperationCancelled:
        raise
    except (subprocess.TimeoutExpired, OSError):
        return None

    if proc.returncode != 0:
        return None

    if proc.stdout is None:
        return None

    try:
        items = json.loads(proc.stdout)
    except (TypeError, json.JSONDecodeError):
        return None

    if not items:
        return None

    # Each item has an ISO-8601 "ModTime" field, e.g. "2025-07-04T12:30:45+08:00"
    latest: Optional["datetime.datetime"] = None
    for item in items:
        raw = item.get("ModTime")
        if not raw:
            continue
        try:
            # fromisoformat handles the rclone ISO-8601 output directly
            mt = datetime.datetime.fromisoformat(raw)
        except ValueError:
            continue
        if latest is None or mt > latest:
            latest = mt

    return latest


def _display_path_mtimes(
    local_path: str,
    remote_path: str,
    rclone_exe: str,
    direction: str,
    remote_path_type: str = "auto",
) -> None:
    """Print the modification times of the local and remote paths in a compact
    comparison block, suitable for the pre-execution confirmation screen.

    Local mtime comes from the filesystem.  Remote mtime comes from
    ``rclone lsjson`` when ``remote-path`` is classified as a rclone remote,
    otherwise it comes from the local filesystem (including UNC paths).

    When *direction* is ``"push"`` and local is older than remote, or
    *direction* is ``"pull"`` and local is newer than remote, a warning is
    shown — the sync would overwrite newer data with older data.
    """
    local_mtime = _get_local_mtime(local_path)
    remote_is_rclone = _extract_remote_host(remote_path, remote_path_type)[0] is not None
    if remote_is_rclone:
        remote_mtime = _get_remote_latest_mtime(rclone_exe, remote_path)
    else:
        remote_mtime = _get_local_mtime(remote_path)

    def _fmt(dt: Optional["datetime.datetime"]) -> str:
        if dt is None:
            return f"{FGray}(unavailable){CRst}"
        local_dt = dt.astimezone()  # local timezone
        return f"{CRst}{local_dt.strftime('%Y-%m-%d %H:%M:%S')}{CRst}"

    print()
    print(f"  {FLYellow}Path modification times:{CRst}")
    print(f"  {FLGreen}Local :{CRst}  {_fmt(local_mtime)}  {FGray}{local_path}{CRst}")
    print(f"  {FLCyan}Remote:{CRst}  {_fmt(remote_mtime)}  {FGray}{remote_path}{CRst}")

    # Show which side is more recent, plus a directional danger warning
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
            # local newer + pull = danger: would overwrite newer local with older remote
            if direction == "pull":
                print(f"  {FLYellow}  ⚠ WARNING: {FLRed}pull would overwrite newer{CRst} {FLGreen}local{CRst}"
                      f" {FLRed}data with older{CRst} {FLCyan}remote{CRst} {FLRed}data!{CRst}")
        else:
            mins = int(abs(delta_sec) // 60) if abs(delta_sec) >= 60 else 0
            if mins:
                print(f"  {FGray}  -> {FLCyan}remote{FGray} is{CRst} {mins}m {FLYellow}newer{CRst} {FGray}than {FLGreen}local{CRst}")
            else:
                print(f"  {FGray}  -> {FLCyan}remote{FGray} is{CRst} {int(abs(delta_sec))}s {FLYellow}newer{CRst} {FGray}than {FLGreen}local{CRst}")
            # remote newer + push = danger: would overwrite newer remote with older local
            if direction == "push":
                print(f"  {FLRed}  ⚠ WARNING: push would overwrite newer{CRst} {FLCyan}remote{CRst}"
                      f" {FLRed}data with older{CRst} {FLCyan}local{CRst} {FLRed}data!{CRst}")
    elif local_mtime is not None:
        print(f"  {FGray}  -> (remote time unavailable for comparison){CRst}")
    elif remote_mtime is not None:
        print(f"  {FGray}  -> (local time unavailable for comparison){CRst}")
    print()


# ---- alternative remote host helpers ----

_RCLONE_REMOTE_RE = re.compile(r"^([\w][\w.-]*):")


def _extract_remote_host(
    path: str, remote_path_type: str = "auto"
) -> tuple[Optional[str], Optional[str]]:
    """Extract a rclone remote prefix from *path*.

    Returns ``(full_prefix, host_name)`` for paths like ``remote:/dir``.
    ``remote_path_type`` may be ``"auto"``, ``"rclone"``, or ``"local"``.
    Local paths, Windows drive paths, Unix paths, and UNC paths return
    ``(None, None)`` in auto/local mode so inherited
    ``alternative-remote-host`` settings do not affect non-rclone destinations.
    """
    if remote_path_type == "local":
        return None, None
    if not path:
        return None, None
    m = _RCLONE_REMOTE_RE.match(path)
    if m is None:
        return None, None
    host = m.group(1)
    if remote_path_type == "auto" and len(host) == 1 and re.match(r"^[A-Za-z]$", host):
        return None, None
    return f"{host}:", host


def _replace_path_host(path: str, old_prefix: str, new_prefix: str) -> str:
    """Replace the host prefix in *path*."""
    if path.startswith(old_prefix):
        return new_prefix + path[len(old_prefix):]
    return path


def _interactive_host_swap(final_task: 'SyncTask', cli_auto: bool) -> None:
    """If *final_task* has ``alternative_remote_hosts``, offer the user
    a choice of which host to use in ``local_path`` / ``remote_path``.
    Modifies *final_task* in place.  Skipped silently when *cli_auto*.
    """
    if cli_auto:
        return
    alternatives = final_task.alternative_remote_hosts
    if not alternatives:
        return

    # Only remote-path participates. Local/UNC paths skip in auto/local mode.
    path_attr = "remote_path"
    current_prefix, current_host = _extract_remote_host(
        final_task.remote_path,
        final_task.remote_path_type,
    )

    if path_attr is None or current_host is None or current_prefix is None:
        return

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
        alt_prefix = _host_name_to_prefix(alt, current_prefix)
        choices.append((alt, alt_prefix))

    if len(choices) <= 1:
        return

    # Compute full path for each choice by swapping the host prefix
    original_path = getattr(final_task, path_attr)
    # [0] is dimmed if an alternative also has the same host name
    current_overlaps = current_host in seen
    print(f"\n{FLYellow}Alternative hosts available{CRst} for {FLCyan}{path_attr.replace('_', '-')}{CRst}:")
    for idx, (name, prefix) in enumerate(choices):
        mark = f"{FGray}[{CRst}{idx}{FGray}]{CRst}"
        full = _replace_path_host(original_path, current_prefix, prefix)
        if idx == 0 and current_overlaps:
            # [0] duplicates an alternative — show dimmed
            print(f"  {mark}: {FGray}{full}{CRst} {FGray}(current){CRst}")
        elif idx == 0:
            print(f"  {mark}: {FLCyan}{full}{CRst} {FGray}(current){CRst}")
        else:
            print(f"  {mark}: {FLCyan}{full}{CRst}")

    while True:
        try:
            choice = input(
                f"\n{FLYellow}Select host{CRst} {FGray}[# or Enter to keep current]{CRst}: "
            ).strip()
        except EOFError:
            print()
            return
        if not choice:
            return
        if choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(choices):
                _, new_prefix = choices[idx]
                if new_prefix != current_prefix:
                    old_val = getattr(final_task, path_attr)
                    setattr(final_task, path_attr, _replace_path_host(old_val, current_prefix, new_prefix))
                return
            print(f"{FLRed}Invalid number: {idx}{CRst}")


def _host_name_to_prefix(name: str, template_prefix: str) -> str:
    """Build a full path prefix from a host *name* using *template_prefix*
    to preserve the rclone remote separator."""
    return name if name.endswith(':') else name + ':'


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

{FLYellow}Cancellation:{CRst}
  During rclone time checks, dry-runs, checks, and transfers, Ctrl+C cancels
  the current operation and returns to the task menu in interactive mode.
  When --task is supplied, cancellation exits with code 130 because there is
  no interactive task list to return to.

{FLYellow}Environment variables:{CRst}
  {FLCyan}{ENV_SCHEMA_FILE}{CRst}    path to YAML schema file (default: ./rclone-sync-default-schema.yaml)
  {FLCyan}{ENV_CONFIG_PASSWORD}{CRst}  password for encrypted rclone config

{FLYellow}Path variables{CRst} (in YAML: local-path, remote-path, backup-dir, log-file):
  {FGray}${{ENV_VAR}}{CRst}          environment variable (also %VAR% on Windows)
  {FGray}$ENV:VAR{CRst} / {FGray}${{ENV:VAR}}{CRst}  PowerShell-style environment variable
  {FGray}{{{{schema_dir}}}}{CRst}       directory containing the YAML file
  {FGray}{{{{script_dir}}}}{CRst}       directory containing rclone-sync.py
  {FGray}{{{{current_dir}}}}{CRst}      current working directory

{FLYellow}Remote path type:{CRst}
  YAML field {FLCyan}remote-path-type{CRst}: auto | rclone | local  (default: auto).
  It controls whether {FLCyan}remote-path{CRst} should be treated as a rclone remote
  for features such as {FLCyan}alternative-remote-host{CRst} and remote mtime checks.
  Local, drive, and UNC paths use filesystem mtime in auto/local mode.

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
    # Step 1: Check rclone & configure password
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

    # Print rclone location and version
    ver_process = subprocess.run([rclone_exe, "version"], capture_output=True, text=True, timeout=10)
    ver_first_line = ver_process.stdout.strip().split("\n")[0] if ver_process.stdout else ""
    if ver_first_line:
        print(f"{FGray}rclone:{CRst} {rclone_exe} {FGray}({ver_first_line}){CRst}")
    
    print("")
    
    config_password: Optional[str] = None
    if cli_config_password:
        os.environ["RCLONE_CONFIG_PASS"] = cli_config_password
        if not _verify_config_password(rclone_exe):
            Utils.print_error_and_exit("rclone config password is incorrect (from --rclone-config-password)")
        config_password = cli_config_password
    elif ENV_CONFIG_PASSWORD in os.environ:
        config_password = os.environ[ENV_CONFIG_PASSWORD]
        os.environ["RCLONE_CONFIG_PASS"] = config_password
        if not _verify_config_password(rclone_exe):
            Utils.print_error_and_exit(f"rclone config password is incorrect (from {ENV_CONFIG_PASSWORD})")
    elif _detect_encrypted_config(rclone_exe):
        print(f"{FLYellow}  rclone config is encrypted.{CRst}")
        while True:
            config_password = Input.input_password("Enter rclone config password")
            if not config_password:
                Utils.print_exit_message("Bye.")
                return 0
            os.environ["RCLONE_CONFIG_PASS"] = config_password
            if _verify_config_password(rclone_exe):
                break
            os.environ.pop("RCLONE_CONFIG_PASS", None)
            print(f"{FLRed}  Incorrect password.{CRst}")

    if config_password:
        os.environ["RCLONE_CONFIG_PASS"] = config_password
    if cli_config_file:
        os.environ["RCLONE_CONFIG"] = cli_config_file

    # ================================================================
    # Step 2: Resolve YAML schema file path
    # ================================================================
    default_schema = DEFAULT_SCHEMA_FILE
    if ENV_SCHEMA_FILE in os.environ:
        default_schema = os.environ[ENV_SCHEMA_FILE]
    if cli_schema_file:
        default_schema = cli_schema_file

    if cli_auto:
        schema_file = default_schema
    else:
        if ENV_SCHEMA_FILE not in os.environ:
            print(f"{FGray}Tip: set {FLCyan}{ENV_SCHEMA_FILE}{FGray} to your default YAML schema path.{CRst}")
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
    # Step 3: Load & validate YAML
    # ================================================================
    try:
        with open(schema_file, "r", encoding="utf-8") as fh:
            schema = yaml_mod.safe_load(fh)
    except Exception as e:
        print(f"{FLRed}Failed to read YAML schema:{CRst} {FGray}{schema_file}{CRst}\n{FGray}{e}{CRst}")
        return 1

    if schema is None:
        print(f"{FLRed}Schema file is empty:{CRst} {FGray}{schema_file}{CRst}")
        return 1

    errors = _validate_schema(schema)
    if errors:
        print(f"{FLRed}Schema validation failed:{CRst} {FGray}{schema_file}{CRst}")
        for err in errors:
            print(f"  {FLRed}- {err}{CRst}")
        return 1

    settings = schema.get("settings", {}) if isinstance(schema, dict) else {}
    if not isinstance(settings, dict):
        settings = {}

    tasks_section = schema.get("tasks", {})
    if not isinstance(tasks_section, dict):
        print(f"{FLRed}'tasks' must be a dict (group_name → task list):{CRst} {FGray}{schema_file}{CRst}")
        return 1

    # ================================================================
    # Build flat task list: ungrouped first, then groups alphabetically
    # ================================================================
    ungrouped: list[dict] = []
    grouped: list[tuple[str, dict]] = []

    for group_name, tlist in tasks_section.items():
        if not isinstance(tlist, list):
            continue
        for t in tlist:
            if not isinstance(t, dict):
                continue
            if group_name == UNGROUPED_KEY:
                ungrouped.append(t)
            else:
                grouped.append((group_name, t))

    grouped.sort(key=lambda x: x[0].lower())

    all_entries: list[tuple[Optional[str], dict]] = []
    for t in ungrouped:
        all_entries.append((None, t))
    for group_name, t in grouped:
        all_entries.append((group_name, t))

    if not all_entries:
        print(f"{FLRed}No tasks found in schema.{CRst}")
        return 1

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
    arch_cur = Utils.get_arch()
    computer_cur = Utils.get_computer_name()

    # Pre-compute matching sub-tasks for every task (reused in Steps 4-5).
    # Task-level ``platform`` / ``arch`` / ``computer-name`` are merged
    # into each sub-task for matching, and both task-level and sub-task-level
    # ``inherit`` profiles are resolved so that machine constraints inside
    # profiles also participate.  The stored SyncTask is the original sub-task
    # — the full merge happens at execution time.
    _matching_subs_cache: dict[int, list[SyncTask]] = {}
    for i, (_, t) in enumerate(all_entries):
        raw_subs = t.get("sub-tasks") or []
        if raw_subs:
            parent_dict = {k: v for k, v in t.items() if k != "sub-tasks"}
            try:
                parent = SyncTask.from_dict(parent_dict).resolve_profiles(settings)
            except ValueError as e:
                print(f"{FLRed}Inheritance error in task '{t.get('name', UNNAMED_TASK)}': {e}{CRst}")
                return 1
            matching: list[SyncTask] = []
            for st in raw_subs:
                sub = SyncTask.from_dict(st)
                try:
                    sub_prof = sub.resolve_profiles(settings)
                except ValueError as e:
                    print(f"{FLRed}Inheritance error in sub-task '{st.get('name', '')}': {e}{CRst}")
                    return 1
                if parent.merge(sub_prof).matches_machine(platform_cur, arch_cur, computer_cur):
                    matching.append(sub)
            _matching_subs_cache[i] = matching
        else:
            _matching_subs_cache[i] = []

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
            if not _matching_subs_cache[selected_entry_idx]:
                print(f"{FLRed}Task '{cli_task}' has no sub-tasks matching this machine.{CRst}")
                return 1
        else:
            Utils.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)
            print(f"  Available tasks from `{FGray}{schema_file}{CRst}`:\n")

            # Build mapping: display index -> all_entries index (only matching tasks)
            selectable_map: dict[int, int] = {}
            selectable_set: set[int] = set()
            display_total = 0
            for i in range(len(all_entries)):
                if _matching_subs_cache[i]:
                    selectable_map[display_total] = i
                    selectable_set.add(i)
                    display_total += 1

            if not selectable_map:
                print(f"  {FLRed}No tasks have sub-tasks matching this machine.{CRst}")
                Utils.print_exit_message("Bye.")
                return 0

            max_digits = len(str(display_total - 1))

            # Display all tasks — matching get numbers, non-matching shown in gray
            d_idx = 0   # display index (only for matching tasks)
            prev_group: Optional[str] = None
            for all_idx, (group_name, t) in enumerate(all_entries):
                tname = t.get("name", UNNAMED_TASK)
                is_match = all_idx in selectable_set

                # Blank line between groups
                if group_name is not None and prev_group is not None and group_name != prev_group:
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

                if group_name is not None:
                    prev_group = group_name

            Utils.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)

            # Warn about duplicate task names
            _dup_task_names = {tn: entries for tn, entries in _task_name_to_lines.items() if len(entries) > 1}
            if _dup_task_names:
                print(f"\n  {FLYellow}Warning: duplicate task names:{CRst}")
                for tn, entries in _dup_task_names.items():
                    for g, lineno in entries:
                        label = f"{g}/{tn}" if g else tn
                        print(f"    {FGray}line {lineno}:{CRst} {FLCyan}{label}{CRst}")

            print(f"\n  Enter {FLGreen}number{CRst} to select, {FLCyan}e{CRst} to open YAML, or {FLCyan}Enter{CRst} to exit")

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
                    sel_idx = int(choice)
                    if sel_idx in selectable_map:
                        selected_entry_idx = selectable_map[sel_idx]
                        _, selected_task_dict = all_entries[selected_entry_idx]
                        break
                    print(f"{FLRed}Invalid number: {sel_idx}{CRst}")
                    continue
                print(f"{FLRed}Enter a number, 'e' to open YAML, or Enter to exit.{CRst}")

        assert selected_task_dict is not None

        # ---- Resolve task with inheritance ----
        try:
            merged_task = SyncTask.from_inheritance_chain(settings, selected_task_dict)
        except ValueError as e:
            print(f"{FLRed}Inheritance error: {e}{CRst}")
            return 1

        if cli_verbose:
            print(f"{FGray}Selected: {merged_task.name}{CRst}")

        # ================================================================
        # Step 5: Sub-task selection (reuses pre-computed matching list)
        # ================================================================
        matching_subs = _matching_subs_cache[selected_entry_idx]
        selected_subtask: Optional[SyncTask] = None

        _task_group = all_entries[selected_entry_idx][0]
        _task_name = selected_task_dict.get("name", UNNAMED_TASK)
        _task_label = f"{_task_group}/{_task_name}" if _task_group else _task_name

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
                    print(f"  {FGray}[{CRst}{idx}{FGray}]{CRst}: {FLGreen}{sub.name}{CRst}{sub.display_filters()}")

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
            # Re-validate sub-task matches this machine at execution time
            if not selected_subtask.matches_machine(platform_cur, arch_cur, computer_cur):
                print(f"{FLRed}Selected sub-task '{selected_subtask.name}' does not match this machine.{CRst}")
                return 1
            # Resolve sub-task's own inherit profiles on top of the sub-task
            # before merging onto the already-resolved task.
            try:
                sub_resolved = selected_subtask.resolve_profiles(settings)
            except ValueError as e:
                print(f"{FLRed}Inheritance error in sub-task '{selected_subtask.name}': {e}{CRst}")
                return 1
            final_task = merged_task.merge(sub_resolved)
            final_task.name = f"{merged_task.name}/{selected_subtask.name}"
        else:
            print(f"{FLRed}No matching sub-tasks for this machine — task requires a compatible sub-task.{CRst}")
            return 1

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

        # ---- Alternative remote host selection ----
        _interactive_host_swap(final_task, cli_auto)

        # ================================================================
        # Step 6: Pre-sync check (if configured)
        # ================================================================

        # Determine direction before pre-sync check so the check uses the same direction
        directional = final_task.mode in _DIRECTIONAL_MODES
        direction: str = cli_direction or "push"

        if directional and cli_direction is None:
            # ---- Interactive direction selection ----
            print()
            print(f"  {FLYellow}Task:{CRst} {FLCyan}{final_task.name}{CRst}")
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
                separator=False,
                key_color="",
            )
            if result is None:
                continue  # back to task selection
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

        # Auto-execute when both --task and --direction are given.  When --task
        # is supplied from the CLI, there is no task list to return to.
        auto_execute = cli_task is not None and cli_direction is not None
        cancel_hint = (
            "Press Ctrl+C to cancel and exit with code 130."
            if cli_auto else
            "Press Ctrl+C to cancel and return to the task menu."
        )

        if not cli_dry_run and final_task.check_before_sync and final_task.check_before_sync is not False:
            print(f"\n{FLCyan}Running pre-sync check...{CRst} {FGray}{cancel_hint}{CRst}")
            check_cmd = final_task.to_check_command(rclone_exe, direction=direction)
            _print_cmd(check_cmd)
            try:
                result = _run_interruptible(check_cmd)
            except OperationCancelled:
                if cli_auto:
                    return 130
                continue
            if result.returncode != 0:
                print(f"{FLYellow}  -> Differences detected between source and destination.{CRst}")
                if final_task.stop_on_check_failure:
                    print(f"{FLRed}  -> Stopped because stop-on-check-failure is enabled.{CRst}")
                    return result.returncode

        # ================================================================
        # Step 7: Confirm & execute
        # ================================================================
        print("────────────")
        print(f"  {FLYellow}Task:{CRst} {FLCyan}{final_task.name}{CRst}  {FLYellow}mode:{CRst} {FLCyan}{final_task.mode}{CRst}  {FLYellow}direction:{CRst} {FLCyan}{direction}{CRst}")
        cmd = final_task.to_command(rclone_exe, dry_run=cli_dry_run, direction=direction)
        _print_cmd(cmd)

        # Show path modification times for user awareness.
        # Only show directional danger warnings for sync/copy/move (not bisync/check).
        print(f"\n{FLCyan}Checking path modification times...{CRst} {FGray}{cancel_hint}{CRst}")
        try:
            _display_path_mtimes(
                final_task.local_path, final_task.remote_path, rclone_exe,
                direction if directional else "",
                final_task.remote_path_type,
            )
        except OperationCancelled:
            if cli_auto:
                return 130
            continue

        if cli_dry_run:
            print(f"\n{FGray}(dry-run - no changes made){CRst}")
            return 0
        elif auto_execute:
            pass  # skip confirmation, execute directly
        else:
            go_back = False
            while True:
                try:
                    choice = input(
                        f"\n{FLYellow}Execute?{CRst} {FGray}[{FLGreen}y{FGray}=yes / {FLCyan}n{FGray}=back / {FLCyan}d{FGray}=dry-run / {FLCyan}q{FGray}=quit]{CRst}: "
                    ).strip().lower()
                except EOFError:
                    print()
                    Utils.print_exit_message("Bye.")
                    return 0

                if choice == "y":
                    break
                elif choice == "n":
                    go_back = True
                    break
                elif choice == "d":
                    dry_cmd = final_task.to_command(rclone_exe, dry_run=True, direction=direction)
                    print(f"\n{FLCyan}Running dry-run...{CRst} {FGray}{cancel_hint}{CRst}\n")
                    try:
                        exec_result = _run_interruptible(dry_cmd)
                    except OperationCancelled:
                        go_back = True
                        break
                    if exec_result.returncode == 0:
                        print(f"\n{FGray}(dry-run complete — no changes){CRst}")
                    else:
                        print(f"\n{FLRed}Dry-run failed with exit code {exec_result.returncode}.{CRst}")
                    continue
                elif choice == "q":
                    Utils.print_exit_message("Bye.")
                    return 0
                else:
                    print(f"{FLRed}Enter y, n, d, or q.{CRst}")

            if go_back:
                continue  # back to outermost task selection loop

        # ---- Execute ----
        print(f"\n{FLYellow}Running...{CRst} {FGray}{cancel_hint}{CRst}\n")
        try:
            exec_result = _run_interruptible(cmd)
        except OperationCancelled:
            if cli_auto:
                return 130
            continue

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
                    f"\n{FLYellow}What next?{CRst} {FGray}[{FLGreen}m{FGray}/{FLGreen}Enter{FGray}=back to menu / {FLCyan}r{FGray}=re-run / {FLCyan}q{FGray}=quit]{CRst}: "
                ).strip().lower()
            except EOFError:
                print()
                Utils.print_exit_message("Bye.")
                return 0

            if not choice or choice == "m":
                break  # back to task selection menu
            elif choice == "r":
                print(f"\n{FLYellow}Re-running...{CRst} {FGray}{cancel_hint}{CRst}\n")
                try:
                    exec_result = _run_interruptible(cmd)
                except OperationCancelled:
                    break
                if exec_result.returncode == 0:
                    print(f"\n{FLGreen}Sync completed successfully.{CRst}")
                else:
                    print(f"\n{FLRed}Sync failed with exit code {exec_result.returncode}.{CRst}")
            elif choice == "q":
                Utils.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter m/Enter, r, or q.{CRst}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
