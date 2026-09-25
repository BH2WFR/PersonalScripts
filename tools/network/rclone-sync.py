#!/usr/bin/env python3
"""Cross-platform rclone sync task runner driven by a YAML schema.

Defines reusable sync tasks in YAML, filters sub-tasks by the current machine,
shows source/destination modification times, and offers push/pull sync, copy,
move, bisync, and check actions for directories. File tasks offer only
push-copy-file/pull-copy-file (copyto) and push-move-file/pull-move-file (moveto).
The inherited path-type defaults to directory; allow-actions defaults to all
supported actions, or accepts an exact allowlist replaced during inheritance.
An explicit null or scalar all clears inherited action restrictions; all is not
an action name and cannot appear in a list. Optional YAML
preferred-mode puts matching actions first in yellow; otherwise directory push/pull or
file copy actions are highlighted in the standard order. Comparison
choices depend on the selected action. Empty operation/confirmation input retries;
menus end with Q to return or quit. Task labels retain the group/task prefix;
sub-task menus show this parent label, and later prompts append /sub-task.
Alternative hosts show that full name in yellow. Operation paths use
blue for local and green for remote.
Final confirmation groups warnings, then shows
the command and task summary before prompting with the action name in cyan.
Move actions warn that source files will be deleted. Circular profile inheritance
is rejected with its reference chain. During rclone checks and transfers, Ctrl+C
cancels the current operation and returns to the task menu instead of exiting
the whole script.
File endpoints are checked before every transfer; no file check or bisync is
provided. File tasks require full filenames on both sides, not parent directories.
The inherited do-not-check-modified-time flag defaults to false; true skips
the advisory time comparison without changing transfer comparisons or file guards.
Missing endpoints show first-upload/download guidance, distinct from read errors.
Directory time notices are advisory and do not guarantee individual file age.
Optional max-delete-count limits sync deletions by count (-1 means unlimited);
max-delete-percent independently limits bisync deletions by percentage (0..100).
Re-runs reuse the selected command without repeating menus or advisory checks.
Duplicate YAML keys are rejected with both definition locations. Task paths use
strict, single-pass environment/placeholder expansion; undefined references stop
the selected task before any path checks or transfers.
The adjacent rclone-sync-schema-sample.yaml is detailed documentation for agents
and users, never a default runtime configuration. Select a personal schema through
--schema-file, ZL_RCLONE_SYNC_SCHEMA_FILE, or the interactive path prompt; --task
requires one of the first two sources.

Requirements:
    - pip: PyYAML
    - system: rclone

Usage:
    python rclone-sync.py                  # interactive
    python rclone-sync.py --help           # show help
    python rclone-sync.py --task "group/task-name"
    python rclone-sync.py --task "task-name" --sub-task "sub-name"
    python rclone-sync.py --task "group/task-name" --push --comparison checksum
    python rclone-sync.py --task "group/task-name" --action pull-copy
    python rclone-sync.py --task "group/file-task" --action pull-copy-file
    python rclone-sync.py --task "group/task-name" --action bisync --resync
    python rclone-sync.py --dry-run
"""

import sys
import os
import subprocess
import copy
import dataclasses
import argparse
import enum
import json
import re
import datetime
import stat
from typing import Optional, Any, Union, Set, TextIO

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
from utils import *

# ================================================================
# Constants
# ================================================================

ENV_SCHEMA_FILE = "ZL_RCLONE_SYNC_SCHEMA_FILE"
ENV_CONFIG_PASSWORD = "ZL_RCLONE_CONFIG_PASSWORD"
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
FILE_STAT_TIMEOUT = 15
RCLONE_NOT_FOUND_CODES: set[int] = {3, 4}  # directory not found / file not found
METADATA_FILTER_FLAGS: set[str] = {
    "--exclude", "--exclude-from", "--exclude-if-present", "--include", "--include-from",
    "--filter", "-f", "--filter-from", "--files-from", "--files-from-raw", "--files-from0",
    "--hash-filter", "--max-age", "--min-age", "--max-size", "--min-size", "--max-depth",
    "--metadata-exclude", "--metadata-exclude-from", "--metadata-include",
    "--metadata-include-from", "--metadata-filter", "--metadata-filter-from",
}


class PathType(enum.StrEnum):
    """Kind of both task endpoints; independent of local versus rclone storage."""

    DIRECTORY = "directory"
    FILE = "file"


class PathState(enum.StrEnum):
    """Result of inspecting an endpoint, independent of timestamp availability."""

    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


@dataclasses.dataclass(frozen=True)
class PathInfo:
    """Endpoint metadata used for advisory display and file safety checks.

    Attributes:
        state: Confirmed existence, confirmed absence, or a failed inspection.
        path_type: File/directory when known; absent for an unreadable/missing path.
        mtime: A timezone-aware timestamp, or None when omitted/unavailable.
        detail: Non-secret diagnostic text for a failed inspection.
    """

    state: PathState
    path_type: Optional[PathType] = None
    mtime: Optional[datetime.datetime] = None
    detail: str = ""


class SyncAction(enum.StrEnum):
    """User-facing operation, mapping to a command and optional direction."""

    PUSH = "push"
    PULL = "pull"
    PUSH_COPY = "push-copy"
    PULL_COPY = "pull-copy"
    PUSH_MOVE = "push-move"
    PULL_MOVE = "pull-move"
    BISYNC = "bisync"
    CHECK = "check"
    PUSH_COPY_FILE = "push-copy-file"
    PULL_COPY_FILE = "pull-copy-file"
    PUSH_MOVE_FILE = "push-move-file"
    PULL_MOVE_FILE = "pull-move-file"


ACTION_COMMANDS: dict[SyncAction, tuple[str, Optional[str]]] = {
    SyncAction.PUSH: ("sync", "push"),
    SyncAction.PULL: ("sync", "pull"),
    SyncAction.PUSH_COPY: ("copy", "push"),
    SyncAction.PULL_COPY: ("copy", "pull"),
    SyncAction.PUSH_MOVE: ("move", "push"),
    SyncAction.PULL_MOVE: ("move", "pull"),
    SyncAction.BISYNC: ("bisync", None),
    SyncAction.CHECK: ("check", None),
    SyncAction.PUSH_COPY_FILE: ("copy", "push"),
    SyncAction.PULL_COPY_FILE: ("copy", "pull"),
    SyncAction.PUSH_MOVE_FILE: ("move", "push"),
    SyncAction.PULL_MOVE_FILE: ("move", "pull"),
}
FILE_ACTIONS: tuple[SyncAction, ...] = (
    SyncAction.PUSH_COPY_FILE, SyncAction.PULL_COPY_FILE,
    SyncAction.PUSH_MOVE_FILE, SyncAction.PULL_MOVE_FILE,
)
PATH_ACTIONS: dict[PathType, tuple[SyncAction, ...]] = {
    PathType.FILE: FILE_ACTIONS,
    PathType.DIRECTORY: tuple(action for action in SyncAction if action not in FILE_ACTIONS),
}


class ComparisonMode(enum.StrEnum):
    """Runtime file-comparison strategy for data transfers.

    Attributes:
        SIZE_AND_TIME: Compare using rclone's normal size and modification-time rules.
        SIZE_ONLY: Compare using file size only.
        FORCE: Transfer every source file by enabling ``--ignore-times``.
        CHECKSUM: Compare using size and an available checksum.
    """

    SIZE_AND_TIME = "size_and_time"
    SIZE_ONLY = "size_only"
    FORCE = "force"
    CHECKSUM = "checksum"


COMPARISON_MENU_KEYS: dict[ComparisonMode, str] = {
    ComparisonMode.SIZE_AND_TIME: "0",
    ComparisonMode.SIZE_ONLY: "1",
    ComparisonMode.FORCE: "2",
    ComparisonMode.CHECKSUM: "3",
}
MODE_COMPARISONS: dict[str, tuple[ComparisonMode, ...]] = {
    "sync": tuple(ComparisonMode),
    "copy": tuple(ComparisonMode),
    "move": tuple(ComparisonMode),
    "bisync": (
        ComparisonMode.SIZE_AND_TIME, ComparisonMode.SIZE_ONLY, ComparisonMode.CHECKSUM,
    ),
    "check": (ComparisonMode.SIZE_ONLY, ComparisonMode.CHECKSUM),
}
BISYNC_COMPARE_VALUES: dict[ComparisonMode, str] = {
    ComparisonMode.SIZE_AND_TIME: "size,modtime",
    ComparisonMode.SIZE_ONLY: "size",
    ComparisonMode.CHECKSUM: "size,checksum",
}

# ================================================================
# Schema reference: <script-dir>/rclone-sync-schema-sample.yaml
# This agent-facing documentation is not a runtime configuration or fallback.
# The actual schema is selected by CLI, environment variable, or user input.
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

        if self.yaml_key == "inherit":
            try:
                _normalize_inherit(value)
            except ValueError as exc:
                return f"{path}: {exc}"
            return None

        if self.yaml_key == "preferred-mode" and isinstance(value, str) and not value.strip():
            return None

        if self.yaml_key == "allow-actions":
            if value == "all":
                return None
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                return f"{path}: 'allow-actions' must be null, 'all', or a list of action names"
            for item in value:
                if item == "all":
                    return f"{path}: use 'allow-actions: all', not 'all' inside a list"
                if item not in {action.value for action in SyncAction}:
                    return f"{path}: unknown action '{item}' in 'allow-actions'"
            return None

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
        if self.yaml_key == "max-delete-count" and isinstance(value, int) and value < -1:
            return f"{path}: 'max-delete-count' must be -1 (unlimited) or a non-negative integer"
        if self.yaml_key == "max-delete-percent" and isinstance(value, int) and not (0 <= value <= 100):
            return f"{path}: 'max-delete-percent' must be in range 0..100"
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
    FieldDef("preferred-mode",    "preferred_mode",     default="",          allowed=VALID_MODES | {""}, check_type=str),
    FieldDef("path-type",         "path_type",          default=PathType.DIRECTORY, allowed=set(PathType), check_type=str),
    FieldDef("allow-actions",     "allow_actions",      default=None),
    FieldDef("progress",          "progress",           default=True,        check_type=bool),
    FieldDef("transfer",          "transfer",           default=4,           check_type=int),
    FieldDef("links",             "links",              default=False,       check_type=bool),
    FieldDef("copy-links",        "copy_links",         default=False,       check_type=bool),
    FieldDef("follow-link",       "copy_links",         default=False,       check_type=bool),
    FieldDef("delete-excluded",   "delete_excluded",    default=False,       check_type=bool),
    # paths
    FieldDef("local-path",        "local_path",         default=""),
    FieldDef("remote-path",       "remote_path",        default=""),
    FieldDef("remote-path-type",  "remote_path_type",   default="auto",      allowed=VALID_REMOTE_PATH_TYPES),
    FieldDef("backup-dir",        "backup_dir",         default=""),
    # case sensitivity
    FieldDef("ignore-case",       "ignore_case",        default=False,       check_type=bool),
    FieldDef("ignore-case-sync",  "ignore_case_sync",   default=False,       check_type=bool),
    # comparison strategy
    FieldDef("ignore-times",      "ignore_times",       default=False,       check_type=bool),
    FieldDef("checksum",          "checksum",           default=False,       check_type=bool),
    FieldDef("size-only",         "size_only",          default=False,       check_type=bool),
    FieldDef("update",            "update",             default=False,       check_type=bool),
    # transfer behaviour
    FieldDef("bwlimit",           "bwlimit",            default="",          check_type=str),
    FieldDef("ignore-errors",     "ignore_errors",      default=False,       check_type=bool),
    FieldDef("retries",           "retries",            default=3,           check_type=int),
    FieldDef("s3-no-check-bucket","s3_no_check_bucket", default=False,       check_type=bool),
    # safety
    FieldDef("do-not-check-modified-time", "do_not_check_modified_time", default=False, check_type=bool),
    FieldDef("max-delete-count",  "max_delete_count",   default=None,        check_type=int),
    FieldDef("max-delete-percent","max_delete_percent", default=None,       check_type=int),
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


def _normalize_inherit(value: object) -> list[str]:
    """Normalize an inherit value (str or list) to a list of profile names."""
    if isinstance(value, list):
        if not all(isinstance(v, str) and v for v in value):
            raise ValueError("'inherit' must contain only non-empty profile names")
        return list(value)
    if isinstance(value, str):
        return [value] if value else []
    if value is None:
        return []
    raise ValueError("'inherit' must be a profile name or a list of profile names")


def _resolve_profile_chain(
    settings: dict[str, Any],
    profile_name: str,
    chain: tuple[str, ...] = (),
) -> 'SyncTask':
    """Recursively resolve a named profile, following its own ``inherit``.

    Returns a SyncTask with the profile's fields (and any profiles it
    inherits) resolved. Only names on the current *chain* count as a cycle;
    shared ancestors are reapplied in list order. Raises ValueError for a
    cycle, a missing profile, or nesting beyond MAX_INHERIT_DEPTH.
    """
    reference_chain = (*chain, profile_name)
    if profile_name in chain:
        raise ValueError(f"Circular profile inheritance: {' -> '.join(reference_chain)}")
    if len(chain) > MAX_INHERIT_DEPTH:
        raise ValueError(
            f"Profile inheritance depth exceeded (>{MAX_INHERIT_DEPTH}): "
            f"{' -> '.join(reference_chain)}; "
            f"check for circular or overly deep inherit chains in your YAML."
        )

    profile = settings.get(profile_name)
    if not isinstance(profile, dict):
        raise ValueError(f"Missing or invalid profile in chain: {' -> '.join(reference_chain)}")

    # 1. Resolve profiles that THIS profile inherits (base layer)
    base = SyncTask()
    for name in _normalize_inherit(profile.get("inherit")):
        base = base.merge(_resolve_profile_chain(settings, name, reference_chain))

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
    inherit_profile:   Union[str, list[str]] = ""
    preferred_mode:    str = ""
    mode:              str = ""  # Selected runtime command; not a YAML field.
    path_type:         PathType = PathType.DIRECTORY
    allow_actions:     Optional[list[SyncAction]] = None
    progress:          bool = True
    transfer:          int = 4
    links:             bool = False
    copy_links:        bool = False
    ignore_case:       bool = False
    ignore_case_sync:  bool = False
    ignore_times:      bool = False
    checksum:          bool = False
    size_only:         bool = False
    update:            bool = False
    bwlimit:           str = ""
    ignore_errors:     bool = False
    retries:           int = 3
    s3_no_check_bucket: bool = False
    delete_excluded:   bool = False
    local_path:        str = ""
    remote_path:       str = ""
    remote_path_type:  str = "auto"
    backup_dir:        str = ""
    do_not_check_modified_time: bool = False
    max_delete_count:  Optional[int] = None
    max_delete_percent: Optional[int] = None
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
            if yk in {"path-type", "allow-actions"}:
                error = _validate_field_in_dict(yk, val, "task")
                if error:
                    raise ValueError(error)
                if yk == "path-type":
                    val = PathType(val)
                else:
                    val = None if val is None or val == "all" else [SyncAction(item) for item in val]
            if yk == "preferred-mode" and (val is None or isinstance(val, str) and not val.strip()):
                # An explicit empty mode clears an inherited menu preference.
                val = ""
            if attr is not None and (val is not None or yk == "allow-actions"):
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
            result = result.merge(_resolve_profile_chain(settings, "default"))

        # 2. named profile(s) (inherit) — resolved recursively
        for profile_name in _normalize_inherit(task_dict.get("inherit")):
            result = result.merge(_resolve_profile_chain(settings, profile_name))

        # 3. task itself (preserve sub-tasks for later filtering)
        task_only = {k: v for k, v in task_dict.items() if k != "sub-tasks"}
        return result.merge(cls.from_dict(task_only))

    # ---- inheritance merge ----

    def resolve_profiles(self, settings: dict) -> 'SyncTask':
        """Resolve named profiles, then apply this task's explicit fields.

        Does NOT apply ``default`` — only profiles named in this task's
        ``inherit`` field.  Profiles are resolved recursively (a profile
        that itself has ``inherit`` will pull in its parents first).
        """
        profiles = _normalize_inherit(self.inherit_profile)
        if not profiles:
            return self
        result = SyncTask()
        for name in profiles:
            result = result.merge(_resolve_profile_chain(settings, name))
        return result.merge(self)

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
        if self.path_type == PathType.FILE:
            if self.preferred_mode not in {"", "copy", "move"}:
                errors.append(f"{path}: file tasks only support a copy/move menu preference")
            if self.mode not in {"", "copy", "move"}:
                errors.append(f"{path}: file tasks only support copy/move commands")
            if self.check_before_sync:
                errors.append(f"{path}: 'check-before-sync' is not supported for file tasks")

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
        """Expand all task paths once, applying changes only if every path is valid.

        Args:
            schema_dir: Directory containing the selected YAML schema.
            script_dir: Directory containing this script.

        Raises:
            ValueError: A referenced environment variable or placeholder is
                undefined. The message identifies the YAML field.

        Side effects:
            Updates path fields in-place after successful validation. Supports
            $VAR, ${VAR}, %VAR%, $ENV:VAR, ${ENV:VAR}, and the schema_dir,
            script_dir, current_dir placeholders. Substituted values stay literal;
            leading ~ is expanded, but remote/UNC and relative paths stay intact.
        """
        placeholders = {
            "schema_dir": schema_dir, "script_dir": script_dir,
            "current_dir": os.getcwd(),
        }
        resolved: dict[str, str] = {}
        for attr in ("local_path", "remote_path", "backup_dir", "log_file"):
            val = getattr(self, attr)
            if val:
                try:
                    resolved[attr] = os.path.expanduser(Paths.expand_template(val, os.environ, placeholders))
                except ValueError as exc:
                    raise ValueError(f"{attr.replace('_', '-')}: {exc}") from exc
        for attr, val in resolved.items():
            setattr(self, attr, val)

    # ---- rclone command building ----

    def source_dest(self, direction: str = "push") -> tuple[str, str]:
        """Return source/destination paths after applying the requested direction."""
        src, dst = self.local_path, self.remote_path
        if direction == "pull" and (self.mode or self.preferred_mode or "sync") in _DIRECTIONAL_MODES:
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

    def _append_comparison_and_transfer_flags(
        self,
        cmd: list[str],
        is_data: bool,
        comparison: Optional[ComparisonMode] = None,
    ) -> None:
        """Append comparison, bandwidth, retry, and related transfer flags."""
        if self.mode == "check":
            if comparison is ComparisonMode.SIZE_ONLY or (comparison is None and self.size_only):
                cmd.append("--size-only")
        elif self.mode == "bisync" and comparison is not None:
            cmd.extend(["--compare", BISYNC_COMPARE_VALUES[comparison]])
        elif is_data:
            if comparison is None:
                if self.ignore_times:
                    cmd.append("--ignore-times")
                if self.checksum:
                    cmd.append("--checksum")
            elif comparison is ComparisonMode.FORCE:
                cmd.append("--ignore-times")
            elif comparison is ComparisonMode.CHECKSUM:
                cmd.append("--checksum")
            elif comparison is ComparisonMode.SIZE_ONLY:
                cmd.append("--size-only")
            if comparison is None and self.size_only:
                cmd.append("--size-only")
        if is_data:
            if (
                self.mode in _DIRECTIONAL_MODES
                and comparison in (None, ComparisonMode.SIZE_AND_TIME) and self.update
            ):
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

    def to_command(
        self,
        rclone_exe: str,
        dry_run: bool = False,
        direction: str = "push",
        comparison: Optional[ComparisonMode] = None,
        resync: bool = False,
    ) -> list[str]:
        """Build the rclone command line list for this task.

        *direction*: ``"push"`` (local→remote) or ``"pull"`` (remote→local).
        *comparison*: runtime comparison strategy; overrides configured
        ``--ignore-times``, ``--checksum``, and ``--size-only`` flags for this
        invocation. Check supports size_only/checksum; bisync excludes force.
        *resync*: explicitly initialize/rebuild bisync state for this run.
        Raises ValueError for a comparison or resync incompatible with mode.
        An unset runtime mode uses preferred-mode, or sync for directories and
        copy for files when no preference is set. File tasks
        map copy/move to copyto/moveto. Permissions also apply to this API.
        """
        if not self.mode:
            default_mode = self.preferred_mode or ("copy" if self.path_type == PathType.FILE else "sync")
            return dataclasses.replace(self, mode=default_mode).to_command(
                rclone_exe, dry_run=dry_run, direction=direction,
                comparison=comparison, resync=resync,
            )
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"Unknown direction '{direction}'")
        selected = next((
            action for action in _available_actions(self)
            if ACTION_COMMANDS[action] == (
                self.mode, direction if self.mode in _DIRECTIONAL_MODES else None,
            )
        ), None)
        if selected is None:
            raise ValueError(f"Task does not allow mode '{self.mode}' with direction '{direction}'")
        if self.path_type == PathType.FILE and self.check_before_sync:
            raise ValueError("'check-before-sync' is not supported for file tasks")
        if comparison is not None and comparison not in MODE_COMPARISONS[self.mode]:
            raise ValueError(f"Comparison '{comparison.value}' is not supported by '{self.mode}'")
        if resync and self.mode != "bisync":
            raise ValueError("--resync requires the bisync action")
        src, dst = self.source_dest(direction)
        command_mode = f"{self.mode}to" if self.path_type == PathType.FILE else self.mode
        cmd = [rclone_exe, command_mode, src, dst]
        is_data = self.mode in _DATA_MODES

        if is_data and self.progress:
            cmd.append("-P")
        if is_data and self.transfer != 4:
            cmd.extend(["--transfers", str(self.transfer)])
        self._append_filter_flags(cmd)
        self._append_comparison_and_transfer_flags(cmd, is_data, comparison)
        if self.mode in _DIRECTIONAL_MODES and self.backup_dir:
            cmd.extend(["--backup-dir", self.backup_dir])
        if self.mode == "sync" and self.max_delete_count is not None:
            cmd.extend(["--max-delete", str(self.max_delete_count)])
        if self.mode == "bisync" and self.max_delete_percent is not None:
            cmd.extend(["--max-delete", str(self.max_delete_percent)])
        if self.mode == "sync" and self.delete_excluded:
            cmd.append("--delete-excluded")
        self._append_backend_flags(cmd)
        self._append_log_flags(cmd)
        additional_args = (
            self.additional_args
            if comparison is None
            else _without_comparison_args(self.additional_args)
        )
        cmd.extend(_mode_specific_args(additional_args, self.mode))
        if resync:
            cmd.append("--resync")
        if dry_run:
            cmd.append("--dry-run")
        return cmd

    # ---- rclone check command ----

    def to_check_command(self, rclone_exe: str, direction: str = "push") -> list[str]:
        """Build an ``rclone check`` command (pre-sync validation)."""
        if self.path_type == PathType.FILE:
            raise ValueError("File tasks do not support check")
        src, dst = self.local_path, self.remote_path
        if direction == "pull":
            src, dst = dst, src
        cmd = [rclone_exe, "check", src, dst]
        self._append_filter_flags(cmd)
        if self.check_before_sync == "size-only":
            cmd.append("--size-only")
        if self.mode in {"copy", "move"}:
            cmd.append("--one-way")
        self._append_comparison_and_transfer_flags(cmd, False)
        self._append_backend_flags(cmd)
        self._append_log_flags(cmd)
        return cmd


def _comparison_arg_mode(arg: str) -> Optional[ComparisonMode]:
    """Return the comparison mode represented by one rclone argument."""
    stripped = arg.strip().partition("=")[0]
    if stripped in {"-I", "--ignore-times"}:
        return ComparisonMode.FORCE
    if stripped in {"-c", "--checksum"}:
        return ComparisonMode.CHECKSUM
    if stripped == "--size-only":
        return ComparisonMode.SIZE_ONLY
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


def _mode_specific_args(args: list[str], mode: str) -> list[str]:
    """Drop known command-specific extra flags when switching action modes.

    Value-taking flags consume their following token even when omitted.
    Unrecognized flags are left for rclone to validate.
    """
    rules: dict[str, tuple[set[str], bool]] = {
        "--delete-excluded": ({"sync"}, False),
        "--delete-before": ({"sync"}, False),
        "--delete-during": ({"sync"}, False),
        "--delete-after": ({"sync"}, False),
        "--max-delete": ({"sync", "bisync"}, True),
        "--backup-dir": (_DIRECTIONAL_MODES, True),
        "--resync": ({"bisync"}, False),
        "--resync-mode": ({"bisync"}, True),
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
        "--update": (_DIRECTIONAL_MODES, False),
        "-u": (_DIRECTIONAL_MODES, False),
    }
    result: list[str] = []
    tokens = iter(args)
    for arg in tokens:
        flag, separator, _ = arg.partition("=")
        if mode == "stat" and flag in METADATA_FILTER_FLAGS:
            if not separator:
                next(tokens, None)
            continue
        if mode == "stat" and flag in {"--dirs-only", "--files-only"}:
            continue
        rule = rules.get(flag)
        if rule is not None and mode not in rule[0]:
            if rule[1] and not separator:
                next(tokens, None)
            continue
        result.append(arg)
    return result


def _configured_comparison_modes(task: SyncTask) -> set[ComparisonMode]:
    """Return comparison modes enabled by resolved YAML fields and arguments."""
    modes: set[ComparisonMode] = set()
    if task.ignore_times:
        modes.add(ComparisonMode.FORCE)
    if task.checksum:
        modes.add(ComparisonMode.CHECKSUM)
    if task.size_only:
        modes.add(ComparisonMode.SIZE_ONLY)
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
                mode for mode, compare_value in BISYNC_COMPARE_VALUES.items()
                if attributes == set(compare_value.split(","))
            ), None)
            if selected is None:
                raise ValueError(f"Configured --compare '{value}' needs an explicit --comparison choice")
            modes = {selected}
    return modes


# ================================================================
# YAML schema validation (raw dict level)
# ================================================================

def _load_schema(stream: TextIO) -> Any:
    """Safely load a YAML document, rejecting duplicate keys before merging.

    Args:
        stream: Open UTF-8 YAML text stream; its name appears in parse errors.

    Returns:
        The raw YAML value for schema validation, or None for an empty document.

    Raises:
        yaml.YAMLError: Invalid/unsafe YAML or duplicate keys. Duplicate-key
            errors include the first and repeated definition's line and column.

    Side effects:
        Reads the stream. YAML merge-key overrides remain supported; no global
        PyYAML constructors are changed.
    """
    import yaml

    class SchemaLoader(yaml.SafeLoader):
        """Check each original mapping once, before YAML merges expand aliases."""

        def __init__(self, source: TextIO) -> None:
            super().__init__(source)
            self.checked_mappings: set[yaml.MappingNode] = set()

        def flatten_mapping(self, node: yaml.MappingNode) -> None:
            """Reject repeated explicit keys while allowing inherited overrides."""
            if node not in self.checked_mappings:
                self.checked_mappings.add(node)
                marks: dict[object, yaml.error.Mark] = {}
                for key_node, _ in node.value:
                    if key_node.tag in {"tag:yaml.org,2002:merge", "tag:yaml.org,2002:value"}:
                        key = key_node.value
                    else:
                        key = self.construct_object(key_node, deep=True)
                    try:
                        first = marks.get(key)
                        if first is not None:
                            raise yaml.constructor.ConstructorError(
                                "first key defined here", first,
                                f"duplicate YAML key {key!r}", key_node.start_mark,
                            )
                        marks[key] = key_node.start_mark
                    except TypeError as exc:
                        raise yaml.constructor.ConstructorError(
                            "while reading a mapping", node.start_mark,
                            "mapping keys must be hashable", key_node.start_mark,
                        ) from exc
            super().flatten_mapping(node)

    return yaml.load(stream, Loader=SchemaLoader)


def _validate_field_in_dict(
    key: str, value: Any, path: str, known_profiles: Optional[set[str]] = None,
) -> Optional[str]:
    """Validate a single key-value pair from a raw YAML dict against the field registry."""
    fd = _ATTR_TO_FIELD.get(_YAML_TO_ATTR.get(key, ""))
    if fd is None:
        return f"{path}: unknown field '{key}'"
    if key == "path-type" and value is None:
        return f"{path}: '{key}' cannot be null; omit the key to inherit"
    error = fd.validate(value, path)
    if error is None and key == "inherit" and known_profiles is not None:
        missing = [name for name in _normalize_inherit(value) if name not in known_profiles]
        if missing:
            return f"{path}: inherit profiles not found in settings: {', '.join(missing)}"
    return error


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
        err = _validate_field_in_dict(key, value, path, known_profiles)
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
                    err = _validate_field_in_dict(k, v, st_path, known_profiles)
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
                if not isinstance(pname, str) or not pname:
                    errors.append("Settings profile names must be non-empty strings")
                    continue
                if not isinstance(pfields, dict):
                    errors.append(f"{sp}: must be a dict")
                    continue
                for key, value in pfields.items():
                    err = _validate_field_in_dict(key, value, sp, known_profiles)
                    if err:
                        errors.append(err)
            if not errors:
                # Check unused profiles too, before any task can be executed.
                for pname in s:
                    try:
                        _resolve_profile_chain(s, pname)
                    except ValueError as exc:
                        errors.append(f"settings.{pname}: {exc}")

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

    if not errors:
        # Validate effective leaves too: a file type or pre-check may be inherited.
        settings = schema.get("settings", {})
        for gname, tlist in tasks.items():
            for task in tlist:
                label = f"tasks.{gname}/{task['name']}"
                try:
                    parent = SyncTask.from_inheritance_chain(settings, task)
                    raw_subs = task.get("sub-tasks") or []
                    if not raw_subs:
                        errors.extend(parent.validate(label))
                    for sub in raw_subs:
                        resolved = parent.merge(SyncTask.from_dict(sub).resolve_profiles(settings))
                        errors.extend(resolved.validate(f"{label}/{sub['name']}"))
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")

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
    System.notify(title, body)


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


def _get_local_path_info(path: str, read_modtime: bool = True) -> PathInfo:
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
        return PathInfo(PathState.MISSING)
    except OSError as exc:
        return PathInfo(PathState.UNKNOWN, detail=f"filesystem error: {exc.strerror or type(exc).__name__}")
    path_type = (
        PathType.FILE if stat.S_ISREG(metadata.st_mode) else
        PathType.DIRECTORY if stat.S_ISDIR(metadata.st_mode) else None
    )
    mtime = datetime.datetime.fromtimestamp(metadata.st_mtime, tz=datetime.timezone.utc) if read_modtime else None
    return PathInfo(PathState.PRESENT, path_type, mtime)


def _read_remote_metadata(
    task: SyncTask, rclone_exe: str, path: str, *, stat_only: bool,
    read_modtime: bool = True, timeout: int = FILE_STAT_TIMEOUT,
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
    task._append_backend_flags(cmd)
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
    if proc.returncode in RCLONE_NOT_FOUND_CODES:
        raise FileNotFoundError("remote path not found")
    if proc.returncode != 0:
        raise ValueError(f"rclone metadata query failed (exit {proc.returncode})")
    try:
        return json.loads(proc.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid rclone metadata JSON") from exc


def _remote_entry_info(item: object, read_modtime: bool = True) -> PathInfo:
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
    return PathInfo(PathState.PRESENT, PathType.DIRECTORY if item["IsDir"] else PathType.FILE, mtime)


def _find_remote_child(
    task: SyncTask, rclone_exe: str, path: str, read_modtime: bool,
) -> PathInfo:
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
    prefix = _extract_remote_host(path, "rclone")[0]
    if prefix is None:
        raise ValueError("cannot identify remote prefix")
    relative = path[len(prefix):].rstrip("/")
    if not relative:
        return PathInfo(PathState.PRESENT, PathType.DIRECTORY)
    parent, _, filename = relative.rpartition("/")
    if filename in {".", ".."}:
        raise ValueError("cannot identify the remote child name")
    entries = _read_remote_metadata(task, rclone_exe, f"{prefix}{parent}", stat_only=False, read_modtime=read_modtime)
    if not isinstance(entries, list):
        raise ValueError("invalid remote parent listing")
    matches: list[PathInfo] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("Name"), str):
            raise ValueError("invalid remote parent entry")
        info = _remote_entry_info(entry, read_modtime)
        if entry["Name"].casefold() == filename.casefold():
            matches.append(info)
    if not matches:
        return PathInfo(PathState.MISSING)
    # A directory/file name collision must not bypass the file safety guard.
    return next((info for info in matches if info.path_type == PathType.DIRECTORY), matches[0])


def _get_remote_path_info(
    task: SyncTask, rclone_exe: str, read_modtime: bool = True,
) -> PathInfo:
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
        if task.path_type == PathType.DIRECTORY:
            entries = _read_remote_metadata(task, rclone_exe, task.remote_path, stat_only=False, read_modtime=read_modtime)
            if not isinstance(entries, list):
                raise ValueError("invalid remote directory listing")
            if entries:
                times = [info.mtime for entry in entries if (info := _remote_entry_info(entry, read_modtime)).mtime is not None]
                return PathInfo(PathState.PRESENT, PathType.DIRECTORY, max(times, default=None))
        item = _read_remote_metadata(task, rclone_exe, task.remote_path, stat_only=True, read_modtime=read_modtime)
        info = _remote_entry_info(item, read_modtime)
        if info.path_type == PathType.DIRECTORY:
            # Bucket backends report missing objects as empty directories.
            # An unfiltered parent listing distinguishes these from real prefixes.
            info = _find_remote_child(task, rclone_exe, task.remote_path, read_modtime)
        if task.path_type == PathType.DIRECTORY:
            info = dataclasses.replace(info, mtime=None)
        return info
    except FileNotFoundError:
        return PathInfo(PathState.MISSING)
    except ValueError as exc:
        return PathInfo(PathState.UNKNOWN, detail=str(exc))


def _display_path_mtimes(
    task: SyncTask,
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
    local_info = _get_local_path_info(local_path)
    remote_is_rclone = _extract_remote_host(remote_path, task.remote_path_type)[0] is not None
    if remote_is_rclone:
        remote_info = _get_remote_path_info(task, rclone_exe)
    else:
        remote_info = _get_local_path_info(remote_path)
    local_mtime, remote_mtime = local_info.mtime, remote_info.mtime

    def _fmt(info: PathInfo) -> str:
        if info.state == PathState.MISSING:
            return f"{FGray}(not found){CRst}"
        if info.state == PathState.UNKNOWN:
            return f"{FGray}(unavailable: {info.detail}){CRst}"
        if info.mtime is None:
            return f"{FGray}(exists; modification time unavailable){CRst}"
        local_dt = info.mtime.astimezone()  # local timezone
        return f"{CRst}{local_dt.strftime('%Y-%m-%d %H:%M:%S')}{CRst}"

    print()
    print(f"  {FLYellow}Path modification times:{CRst}")
    print(f"  {FLGreen}Local :{CRst}  {_fmt(local_info)}  {FGray}{local_path}{CRst}")
    print(f"  {FLCyan}Remote:{CRst}  {_fmt(remote_info)}  {FGray}{remote_path}{CRst}")
    if task.path_type == PathType.DIRECTORY:
        print(f"  {FGray}Directory times are hints only; they do not guarantee which files are newer.{CRst}")

    # Missing endpoints need first-sync guidance, not an unavailable-time warning.
    if PathState.MISSING in {local_info.state, remote_info.state}:
        if local_info.state == remote_info.state == PathState.MISSING:
            warnings.append(f"  {FLYellow}WARNING: Both paths are missing. First sync requires existing source data on one side.{CRst}")
        elif PathState.UNKNOWN in {local_info.state, remote_info.state}:
            warnings.append(f"  {FLYellow}WARNING: One path is missing and the other could not be inspected. Cannot determine first-sync direction.{CRst}")
        elif direction in VALID_DIRECTIONS:
            source_info = local_info if direction == "push" else remote_info
            source_side, target_side = ("local", "remote") if direction == "push" else ("remote", "local")
            if source_info.state == PathState.MISSING:
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
            missing_side = "local" if local_info.state == PathState.MISSING else "remote"
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
                if task.path_type == PathType.DIRECTORY:
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
                if task.path_type == PathType.DIRECTORY:
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


def _validate_file_endpoints(task: SyncTask, rclone_exe: str, direction: str) -> None:
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
    if task.path_type != PathType.FILE:
        return
    source, destination = task.source_dest(direction)
    if source == destination:
        raise ValueError("Source and destination must be different files")
    for attr in ("local_path", "remote_path"):
        path: str = getattr(task, attr)
        is_source = path == source
        role = "source" if is_source else "destination"
        if not path or path.endswith(("/", "\\")):
            raise ValueError(f"File {role} requires a full filename: {path}")
        storage = task.remote_path_type if attr == "remote_path" else "local"
        remote_prefix = _extract_remote_host(path, storage)[0]
        if remote_prefix is None:
            if os.path.islink(path) and (not is_source or not task.copy_links):
                raise ValueError(f"File {role} is a symbolic link: {path}")
            info = _get_local_path_info(path, read_modtime=False)
        else:
            if path[len(remote_prefix):].rsplit("/", 1)[-1] in {"", ".", ".."}:
                raise ValueError(f"Remote file {role} requires a full filename: {path}")
            info = _get_remote_path_info(task, rclone_exe, read_modtime=False)
        if info.state == PathState.MISSING:
            if not is_source:
                continue
            raise ValueError(f"Source file does not exist: {path}. First sync requires existing source data.")
        if info.state == PathState.UNKNOWN:
            raise ValueError(f"Cannot inspect file {role}: {path}: {info.detail}")
        if info.path_type != PathType.FILE:
            raise ValueError(f"File {role} is not a regular file: {path}")


def _run_task_command(
    task: SyncTask, cmd: list[str], rclone_exe: str, direction: str,
) -> subprocess.CompletedProcess[str]:
    """Validate file endpoints immediately before running a task command.

    Args:
        task: Resolved task, including its selected runtime mode.
        cmd: Transfer/check command, optionally containing --dry-run.
        rclone_exe: Executable for endpoint metadata checks.
        direction: Selected push/pull direction.

    Returns:
        Rclone's result, or exit code 1 without execution if validation fails.

    Raises:
        OperationCancelled: The user cancels validation or execution.
        OSError: Rclone cannot be started for execution.

    Side effects:
        Prints validation failures; otherwise runs the supplied command.
    """
    try:
        _validate_file_endpoints(task, rclone_exe, direction)
    except ValueError as exc:
        print(f"{FLRed}{exc}{CRst}")
        return subprocess.CompletedProcess(cmd, 1)
    return _run_interruptible(cmd)


def _interactive_host_swap(final_task: 'SyncTask', cli_auto: bool) -> bool:
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
    current_prefix, current_host = _extract_remote_host(
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
        alt_prefix = _host_name_to_prefix(alt, current_prefix)
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
        full = _replace_path_host(original_path, current_prefix, prefix)
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
                    setattr(final_task, path_attr, _replace_path_host(old_val, current_prefix, new_prefix))
                return True
            print(f"{FLRed}Invalid number: {idx}{CRst}")
            continue
        print(f"{FLRed}Enter a number, Q to go back, or Enter to keep current.{CRst}")


def _host_name_to_prefix(name: str, template_prefix: str) -> str:
    """Build a full path prefix from a host *name* using *template_prefix*
    to preserve the rclone remote separator."""
    return name if name.endswith(':') else name + ':'


def _available_actions(task: SyncTask) -> list[SyncAction]:
    """Return allowed actions, stably placing the configured mode first."""
    actions = [
        action for action in PATH_ACTIONS[task.path_type]
        if task.allow_actions is None or action in task.allow_actions
    ]
    return sorted(actions, key=lambda action: ACTION_COMMANDS[action][0] != task.preferred_mode)


def _select_action(
    task: SyncTask,
    cli_action: Optional[SyncAction],
    cli_direction: Optional[str],
) -> Optional[SyncAction]:
    """Resolve CLI action/direction or show the mode-prioritized action menu.

    Returns None when q is selected; empty input retries without selecting.
    Raises ValueError for disallowed actions
    or directions on nondirectional modes. CLI direction uses preferred-mode.
    """
    actions = _available_actions(task)
    selected = cli_action
    if selected is None and cli_direction is not None:
        command_mode = task.preferred_mode or ("copy" if task.path_type == PathType.FILE else "sync")
        selected = next((
            action for action in PATH_ACTIONS[task.path_type]
            if ACTION_COMMANDS[action] == (command_mode, cli_direction)
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
        highlighted = "push-copy-file/pull-copy-file" if task.path_type == PathType.FILE else "push/pull"
        print(f"  {FGray}No preferred mode; {highlighted} are highlighted in the standard order.{CRst}")
    if not actions:
        print(f"  {FLYellow}No actions are permitted for this path type.{CRst}")
    print(f"  {FGray}Enter retries; q returns to the task menu.{CRst}")
    local = f"{FLBlue}{task.local_path}{CRst}"
    remote = f"{FLGreen}{task.remote_path}{CRst}"
    options: list[MenuOption] = []
    action_width = max((len(action.value) for action in actions), default=10)
    preferred_mode = task.preferred_mode or ("copy" if task.path_type == PathType.FILE else "sync")
    for index, action in enumerate(actions):
        mode, direction = ACTION_COMMANDS[action]
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
    return selected if isinstance(selected, SyncAction) else None


def _task_for_action(task: SyncTask, action: SyncAction) -> SyncTask:
    """Copy a task with its runtime command mode, enforcing write permissions.

    The original configuration is unchanged. Raises ValueError when the
    action is forbidden or a one-way backup directory would be misapplied.
    """
    if action not in _available_actions(task):
        raise ValueError(f"Task does not allow action '{action.value}'")
    mode, direction = ACTION_COMMANDS[action]
    if task.backup_dir and direction == "pull":
        raise ValueError("Refusing pull with backup-dir. Use a task-specific pull backup path or disable backup-dir.")
    if task.backup_dir and mode == "bisync":
        raise ValueError("Bisync requires side-specific --backup-dir1/--backup-dir2 instead of backup-dir.")
    return dataclasses.replace(task, mode=mode)


def _select_comparison_mode(
    task: SyncTask,
    cli_comparison: Optional[ComparisonMode],
    interactive: bool,
) -> Optional[ComparisonMode]:
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
    allowed = MODE_COMPARISONS[task.mode or "sync"]
    if cli_comparison is not None:
        if cli_comparison not in allowed:
            print(f"{FLRed}Comparison '{cli_comparison.value}' is not supported by '{task.mode}'.{CRst}")
            return None
        return cli_comparison

    try:
        configured_modes = _configured_comparison_modes(task)
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
        default_mode: Optional[ComparisonMode] = None
    else:
        fallback = ComparisonMode.CHECKSUM if task.mode == "check" else ComparisonMode.SIZE_AND_TIME
        default_mode = next(iter(configured_modes), fallback)
        if configured_modes:
            flag = {
                ComparisonMode.SIZE_AND_TIME: "--compare size,modtime",
                ComparisonMode.SIZE_ONLY: "--size-only",
                ComparisonMode.FORCE: "--ignore-times",
                ComparisonMode.CHECKSUM: "--checksum",
            }[default_mode]
            print(
                f"\n{FLYellow}Configured comparison mode:{CRst} "
                f"{FLCyan}{default_mode.value}{CRst} {FGray}({flag}){CRst}"
            )

    if not interactive:
        return default_mode

    options = [
        MenuOption(
            [COMPARISON_MENU_KEYS[ComparisonMode.SIZE_AND_TIME]],
            "size_and_time  Compare by size and modified time",
            value=ComparisonMode.SIZE_AND_TIME,
            desc_color=FGray,
        ),
        MenuOption(
            [COMPARISON_MENU_KEYS[ComparisonMode.SIZE_ONLY]],
            "size_only      Compare by size only (--size-only)",
            value=ComparisonMode.SIZE_ONLY,
            desc_color=FGray,
        ),
        MenuOption(
            [COMPARISON_MENU_KEYS[ComparisonMode.FORCE]],
            "force          Transfer all files unconditionally (--ignore-times)",
            value=ComparisonMode.FORCE,
            desc_color=FGray,
        ),
        MenuOption(
            [COMPARISON_MENU_KEYS[ComparisonMode.CHECKSUM]],
            "checksum       Compare by size and checksum (--checksum)",
            value=ComparisonMode.CHECKSUM,
            desc_color=FGray,
        ),
    ]
    options = [option for option in options if option.value in allowed]
    if task.mode == "bisync":
        for option in options:
            description = option.description.partition(" (")[0]
            option.description = f"{description} (--compare {BISYNC_COMPARE_VALUES[option.value]})"
    if task.mode == "check":
        for option in options:
            if option.value is ComparisonMode.CHECKSUM:
                option.description = "checksum       Compare by size and checksum (rclone check)"
    options.append(MenuOption(["q"], "Back to task menu", desc_color=FGray))
    selected = Menu.select(
        options,
        prompt="Comparison mode",
        required=default_mode is None,
        default_key=(COMPARISON_MENU_KEYS[default_mode] if default_mode is not None else None),
        separator=False,
    )
    return selected if isinstance(selected, ComparisonMode) else None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI args. Help is printed by the custom help path before this runs."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--schema-file")
    parser.add_argument("--rclone-config-file")
    parser.add_argument("--rclone-config-password")
    parser.add_argument("--task")
    parser.add_argument("--sub-task")
    parser.add_argument("--direction", choices=sorted(VALID_DIRECTIONS))
    parser.add_argument("--action", choices=[action.value for action in SyncAction])
    parser.add_argument("--resync", action="store_true")
    parser.add_argument("--comparison", choices=[mode.value for mode in ComparisonMode])
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
    if ns.resync and ns.action not in (None, SyncAction.BISYNC.value):
        parser.error("--resync requires --action bisync")
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
  python {script_name} --task <n> --push --comparison checksum
  python {script_name} --task <n> --action pull-copy --comparison size_only
  python {script_name} --task <n> --action pull-copy-file --comparison checksum
  python {script_name} --task <n> --action bisync --resync
  python {script_name} --dry-run              print command only

{FLYellow}Options:{CRst}
  --schema-file <path>         actual YAML schema path (overrides the environment variable)
  --rclone-config-file <path>  rclone config file path
  --rclone-config-password <>  encrypted config password ({FLRed}deprecated{CRst}, use env var)
  --task <group/task-name>     skip task selection
  --sub-task <name>            sub-task filter (requires --task)
  --direction <push|pull>      sync direction: push (local -> remote) or pull (remote -> local)
                               uses preferred-mode (directory: sync, file: copy if unset)
                               cannot combine with --action
  --push                       shorthand for --direction push
  --pull                       shorthand for --direction pull
  --action <name>              push | pull | push-copy | pull-copy | push-move |
                               pull-move | bisync | check | push-copy-file |
                               pull-copy-file | push-move-file | pull-move-file
  --resync                     explicitly initialize/rebuild bisync state for this run
  --comparison <mode>          size_and_time | size_only | force | checksum
                               (available choices depend on the selected action)
  --dry-run                    print command, do not execute
  --verbose                    print additional diagnostics

{FLYellow}Auto-sync:{CRst}
  When --task and --action (or --direction) are specified, the script runs without
  any interactive prompts.  If --comparison is omitted, the effective task
  configuration selects the comparison mode automatically.

{FLYellow}Comparison modes:{CRst}
  Sync/copy/move offer all four choices. Bisync excludes force and uses --compare.
  Check offers size_only and checksum (the latter is rclone check's default).
  {FLCyan}size_and_time{CRst}  compare by size and modified time
  {FLCyan}size_only{CRst}      compare by size only (--size-only)
  {FLCyan}force{CRst}          transfer all files unconditionally (--ignore-times)
  {FLCyan}checksum{CRst}       compare by size and checksum (--checksum)
  Configured --ignore-times, --checksum, or --size-only flags only change the
  interactive default.  Each explicit selection has the behavior shown above.

{FLYellow}Action menu and inheritance:{CRst}
  Optional preferred-mode puts matching actions first in yellow; others are cyan.
  Missing mode highlights push/pull for directories, or the two copy-file actions
  for files, in the standard order.
  Empty/null preferred-mode clears an inherited preference.
  Menus end with Q: quit from the task menu; return from sub-task, host,
  operation, and comparison menus. With --task and no task menu, Q exits.
  Empty operation/confirmation input retries. Comparison keeps its Enter default.
  Task labels retain group/task; after selection, they include /sub-task in
  host/operation menus, confirmation, and notifications. Ungrouped tasks omit
  the group prefix. Alternative hosts show the full name in yellow. Operation paths use blue
  for local and green for remote. Execute/What next retain Q=quit.
  Final confirmation groups warnings, then shows the command and task summary
  before prompting with the action name in cyan. Move warns about deleting source files.
  allow-actions accepts null, scalar all, or an exact list of action names, also enforced by CLI.
  Omit it to inherit; if never set, all actions for the path type are available.
  Explicit null/all clears inherited restrictions. [] disables all actions.
  Lists replace inherited lists; [all] and unknown action names fail.
  Check must be allowed explicitly when an allowlist is used; it never fixes links.
  Profile inheritance is applied in list order; cycles are rejected with their
  full reference chain, including cycles in default and unused profiles.
  Duplicate YAML keys fail with the first and repeated definition's line/column.

{FLYellow}Modification time display:{CRst}
  do-not-check-modified-time: false (default; inherited by tasks/sub-tasks).
  Set true to skip advisory time queries/display. This does not change comparison
  or disable file existence/type guards. Missing destinations show first-upload/
  download information; missing sources require the opposite direction or a
  corrected source path. Read failures and empty directories are not assumed missing.
  Directory time notices are hints, not guarantees of individual file age.

{FLYellow}Deletion limits (optional):{CRst}
  max-delete-count: sync only; non-negative file count, or -1 for unlimited.
  max-delete-percent: bisync only; integer percentage from 0 to 100.
  Omit either to use rclone's default (sync: unlimited; bisync: 50 percent).
  Each applies only to its own operation; copy/move/check use neither.

{FLYellow}File tasks:{CRst}
  path-type: directory | file (inherited; default: directory).
  File tasks require full filenames on both sides and only offer copy-file and
  move-file actions, using copyto/moveto. No file check, pre-check, sync, or bisync.
  preferred-mode accepts copy/move. All four comparisons work for file transfers.
  Source must be a file; an absent destination is allowed, a directory is not.
  Endpoints are checked before each execution, dry-run, and re-run. A symbolic
  link source on local storage requires copy-links; local link destinations are refused.
  A task without sub-tasks can run directly if its machine filters match.

{FLYellow}Bisync state:{CRst}
  Local is always Path1, remote is Path2. Rclone stores state in its local cache
  (or an explicit --workdir in additional-args). Normal runs never add --resync.
  Use --action bisync --resync for initialization/rebuilding, then omit --resync.
  Changing comparison settings may require rebuilding state. Resync defaults
  to preferring Path1 on conflicts; use --resync-mode in additional-args to change it.

{FLYellow}Cancellation:{CRst}
  During rclone time checks, dry-runs, checks, and transfers, Ctrl+C cancels
  the current operation and returns to the task menu in interactive mode.
  When --task is supplied, cancellation exits with code 130 because there is
  no interactive task list to return to.
  Re-run reuses the chosen command without repeating selection, confirmation,
  time display, or pre-sync check. File endpoint guards still apply.

{FLYellow}Schema selection:{CRst}
  Interactive startup prompts for the actual configuration path, suggesting
  --schema-file or {ENV_SCHEMA_FILE} when set (CLI takes precedence).
  With neither set, a path must be entered. With --task, one of them is required.
  rclone-sync-schema-sample.yaml is detailed agent/user documentation, not a
  runtime configuration. The script never uses it as an automatic fallback.

{FLYellow}Environment variables:{CRst}
  {FLCyan}{ENV_SCHEMA_FILE}{CRst}    path to the actual YAML schema file (no bundled default)
  {FLCyan}{ENV_CONFIG_PASSWORD}{CRst}  password for encrypted rclone config

{FLYellow}Path variables{CRst} (in YAML: local-path, remote-path, backup-dir, log-file):
  {FGray}$VAR / ${{VAR}} / %VAR%{CRst}  environment variable on every platform
  {FGray}$ENV:VAR{CRst} / {FGray}${{ENV:VAR}}{CRst}  PowerShell-style environment variable
  {FGray}{{{{schema_dir}}}}{CRst}       directory containing the YAML file
  {FGray}{{{{script_dir}}}}{CRst}       directory containing rclone-sync.py
  {FGray}{{{{current_dir}}}}{CRst}      current working directory
  Expansion is single-pass; substituted values are not parsed again.
  Undefined variables/placeholders stop the selected task and identify the field.
  Leading ~ expands to the user home; remote/UNC paths and relative paths stay intact.

{FLYellow}Remote path type:{CRst}
  YAML field {FLCyan}remote-path-type{CRst}: auto | rclone | local  (default: auto).
  It controls whether {FLCyan}remote-path{CRst} should be treated as a rclone remote
  for features such as {FLCyan}alternative-remote-host{CRst} and remote mtime checks.
  Local, drive, and UNC paths use filesystem mtime in auto/local mode.

{FLYellow}Modes:{CRst}
  YAML preferred-mode prioritizes the menu; the selected action determines the command.
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
    Console.print_banner("RCLONE SYNC RUNNER")

    # ---- help (works without any dependencies) ----
    if "--help" in sys.argv or "-h" in sys.argv:
        _print_help()
        return 0

    try:
        import yaml as yaml_mod
    except ImportError:
        Console.print_error_and_exit("PyYAML is not installed. Run: pip install pyyaml")
        raise  # unreachable — satisfies the type checker

    script_dir = SCRIPT_DIR

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
    cli_action = SyncAction(parsed.action) if parsed.action is not None else None
    cli_resync: bool = parsed.resync
    cli_comparison: Optional[ComparisonMode] = (
        ComparisonMode(parsed.comparison)
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
    
    config_password: Optional[str] = None
    if cli_config_password:
        os.environ["RCLONE_CONFIG_PASS"] = cli_config_password
        if not _verify_config_password(rclone_exe):
            Console.print_error_and_exit("rclone config password is incorrect (from --rclone-config-password)")
        config_password = cli_config_password
    elif ENV_CONFIG_PASSWORD in os.environ:
        config_password = os.environ[ENV_CONFIG_PASSWORD]
        os.environ["RCLONE_CONFIG_PASS"] = config_password
        if not _verify_config_password(rclone_exe):
            Console.print_error_and_exit(f"rclone config password is incorrect (from {ENV_CONFIG_PASSWORD})")
    elif _detect_encrypted_config(rclone_exe):
        print(f"{FLYellow}  rclone config is encrypted.{CRst}")
        while True:
            config_password = Input.input_password("Enter rclone config password")
            if not config_password:
                Console.print_exit_message("Bye.")
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
    default_schema = cli_schema_file or os.environ.get(ENV_SCHEMA_FILE, "")

    if cli_auto:
        if not default_schema:
            print(f"{FLRed}With --task, specify --schema-file or set {ENV_SCHEMA_FILE}. "
                  f"The bundled sample is documentation only.{CRst}")
            return 1
        schema_file = default_schema
    else:
        if ENV_SCHEMA_FILE not in os.environ:
            print(f"{FGray}Tip: set {FLCyan}{ENV_SCHEMA_FILE}{FGray} to your default YAML schema path.{CRst}")
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
            schema = _load_schema(fh)
    except (OSError, UnicodeError, yaml_mod.YAMLError) as e:
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
    arch_cur = System.get_arch()
    computer_cur = System.get_computer_name()

    # Pre-compute matching sub-tasks for every task (reused in Steps 4-5).
    # Task-level ``platform`` / ``arch`` / ``computer-name`` are merged
    # into each sub-task for matching, and both task-level and sub-task-level
    # ``inherit`` profiles are resolved so that machine constraints inside
    # profiles also participate.  The stored SyncTask is the original sub-task
    # — the full merge happens at execution time.
    _matching_subs_cache: dict[int, list[SyncTask]] = {}
    _matching_entries: set[int] = set()
    for i, (group_name, t) in enumerate(all_entries):
        raw_subs = t.get("sub-tasks") or []
        if raw_subs:
            task_name = t.get("name", UNNAMED_TASK)
            task_label = f"{group_name}/{task_name}" if group_name else task_name
            parent_dict = {k: v for k, v in t.items() if k != "sub-tasks"}
            try:
                parent = SyncTask.from_inheritance_chain(settings, parent_dict)
            except ValueError as e:
                print(f"{FLRed}Inheritance error in task '{task_label}': {e}{CRst}")
                return 1
            matching: list[SyncTask] = []
            for st in raw_subs:
                sub = SyncTask.from_dict(st)
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
            parent = SyncTask.from_inheritance_chain(settings, t)
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
                print(f"{FLRed}Task '{cli_task}' does not match this machine or has no matching sub-tasks.{CRst}")
                return 1
        else:
            Console.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)
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

            if not selectable_map:
                print(f"  {FLRed}No tasks or sub-tasks match this machine.{CRst}")
                Console.print_exit_message("Bye.")
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

            print(f"  {FGray}[{CRst}{'Q':>{max_digits}}{FGray}]{CRst}: {FGray}Quit{CRst}")
            Console.print_separator(width=DISPLAY_WIDTH, color_ansi_esc=None, indent=2)

            # Warn about duplicate task names
            _dup_task_names = {tn: entries for tn, entries in _task_name_to_lines.items() if len(entries) > 1}
            if _dup_task_names:
                print(f"\n  {FLYellow}Warning: duplicate task names:{CRst}")
                for tn, entries in _dup_task_names.items():
                    for g, lineno in entries:
                        label = f"{g}/{tn}" if g else tn
                        print(f"    {FGray}line {lineno}:{CRst} {FLCyan}{label}{CRst}")

            print(f"\n  Enter {FLGreen}number{CRst} to select, {FLCyan}e{CRst} to open YAML, or {FLCyan}Q/Enter{CRst} to exit")

            while True:
                try:
                    choice = input(f"\n{FLYellow}Select task{CRst} {FGray}[# / Q=quit]{CRst}: ").strip()
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
                if choice.isdigit():
                    sel_idx = int(choice)
                    if sel_idx in selectable_map:
                        selected_entry_idx = selectable_map[sel_idx]
                        _, selected_task_dict = all_entries[selected_entry_idx]
                        break
                    print(f"{FLRed}Invalid number: {sel_idx}{CRst}")
                    continue
                print(f"{FLRed}Enter a number, 'e' to open YAML, or Q/Enter to exit.{CRst}")

        assert selected_task_dict is not None
        _task_group = all_entries[selected_entry_idx][0]
        _task_name = selected_task_dict.get("name", UNNAMED_TASK)
        _task_label = f"{_task_group}/{_task_name}" if _task_group else _task_name

        # ---- Resolve task with inheritance ----
        try:
            merged_task = SyncTask.from_inheritance_chain(settings, selected_task_dict)
        except ValueError as e:
            print(f"{FLRed}Inheritance error in task '{_task_label}': {e}{CRst}")
            return 1

        if cli_verbose:
            print(f"{FGray}Selected: {_task_label}{CRst}")

        # ================================================================
        # Step 5: Sub-task selection (reuses pre-computed matching list)
        # ================================================================
        matching_subs = _matching_subs_cache[selected_entry_idx]
        selected_subtask: Optional[SyncTask] = None
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
                    print(f"  {FGray}[{CRst}{idx}{FGray}]{CRst}: {FLGreen}{sub.name}{CRst}{sub.display_filters()}")
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
        elif not raw_subs:
            final_task = merged_task
            final_task.name = _task_label
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
            final_task.resolve_paths(schema_dir, script_dir)
        except ValueError as exc:
            print(f"{FLRed}Path expansion failed for '{final_task.name}': {exc}{CRst}")
            if cli_auto:
                return 1
            continue  # keep the schema and password, return to task selection

        if not final_task.local_path or not final_task.remote_path:
            print(f"{FLRed}Task is missing local-path or remote-path.{CRst}")
            return 1

        # ---- Alternative remote host selection ----
        if not _interactive_host_swap(final_task, cli_auto):
            continue  # back to task selection without using the current host

        # ================================================================
        # Step 6: Select action before the optional pre-sync check
        # ================================================================

        # Determine direction before pre-sync check so the check uses the same direction
        # ---- Interactive operation selection (includes direction) ----
        try:
            action = _select_action(final_task, cli_action, cli_direction)
            if action is None:
                if cli_auto:
                    return 0
                continue  # back to task selection
            final_task = _task_for_action(final_task, action)
            if cli_resync and action is not SyncAction.BISYNC:
                raise ValueError("--resync requires the bisync action")
        except ValueError as exc:
            print(f"{FLRed}{exc}{CRst}")
            if cli_auto:
                return 1
            continue
        _, action_direction = ACTION_COMMANDS[action]
        directional = action_direction is not None
        direction = action_direction or "push"

        # Auto-execute with --task and --action (or the legacy --direction). When --task
        # is supplied from the CLI, there is no task list to return to.
        auto_execute = cli_task is not None and (cli_action is not None or cli_direction is not None)
        comparison = _select_comparison_mode(
            final_task, cli_comparison, interactive=not auto_execute,
        )
        if comparison is None:
            if cli_auto:
                return 1 if auto_execute or cli_comparison is not None else 0
            continue

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
        cmd = final_task.to_command(
            rclone_exe,
            dry_run=cli_dry_run,
            direction=direction,
            comparison=comparison,
            resync=cli_resync,
        )
        if cli_dry_run:
            _print_cmd(cmd)
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
                warnings = _display_path_mtimes(final_task, rclone_exe, direction if directional else "")
            except OperationCancelled:
                if cli_auto:
                    return 130
                continue

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
            _print_cmd(cmd)
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
                dry_cmd = final_task.to_command(
                    rclone_exe,
                    dry_run=True,
                    direction=direction,
                    comparison=comparison,
                    resync=cli_resync,
                )
                print(f"\n{FLCyan}Running dry-run...{CRst} {FGray}{cancel_hint}{CRst}\n")
                try:
                    exec_result = _run_task_command(final_task, dry_cmd, rclone_exe, direction)
                except OperationCancelled:
                    go_back = True
                    break
                if exec_result.returncode == 0:
                    print(f"\n{FGray}(dry-run complete — no changes){CRst}")
                else:
                    print(f"\n{FLRed}Dry-run failed with exit code {exec_result.returncode}.{CRst}")
                continue
            elif choice == "q":
                Console.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter y, n, d, or q.{CRst}")

        if go_back:
            continue  # back to outermost task selection loop

        # ---- Execute ----
        if directional and final_task.check_before_sync:
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
                print(f"{FLYellow}  -> Pre-sync check reported differences or an error.{CRst}")
                if final_task.stop_on_check_failure:
                    print(f"{FLRed}  -> Stopped because stop-on-check-failure is enabled.{CRst}")
                    return result.returncode
            _print_cmd(cmd)
        print(f"\n{FLYellow}Running...{CRst} {FGray}{cancel_hint}{CRst}\n")
        try:
            exec_result = _run_task_command(final_task, cmd, rclone_exe, direction)
        except OperationCancelled:
            if cli_auto:
                return 130
            continue

        if exec_result.returncode == 0:
            print(f"\n{FLGreen}Operation '{action.value}' completed successfully.{CRst}")
        else:
            print(f"\n{FLRed}Operation '{action.value}' failed with exit code {exec_result.returncode}.{CRst}")

        _, sync_dst = final_task.source_dest(direction)
        if exec_result.returncode == 0 and directional and final_task.links and os.path.exists(sync_dst):
            _fix_windows_symlinkd(sync_dst)

        if final_task.notify_after_sync:
            status = "completed" if exec_result.returncode == 0 else f"failed (code {exec_result.returncode})"
            _notify(f"rclone-sync: {final_task.name}", f"{action.value} {status}")

        if auto_execute:
            return exec_result.returncode

        if cli_resync and exec_result.returncode == 0:
            cmd = final_task.to_command(rclone_exe, direction=direction, comparison=comparison)

        # ================================================================
        # Step 8: Post-execution menu
        # ================================================================
        while True:
            try:
                choice = input(
                    f"\n{FLYellow}What next?{CRst} {FGray}[{FLGreen}m{FGray}/{FLGreen}Enter{FGray}=back to menu / {FLCyan}r{FGray}=re-run / {FLCyan}Q{FGray}=quit]{CRst}: "
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
                    exec_result = _run_task_command(final_task, cmd, rclone_exe, direction)
                except OperationCancelled:
                    break
                if exec_result.returncode == 0:
                    print(f"\n{FLGreen}Operation '{action.value}' completed successfully.{CRst}")
                else:
                    print(f"\n{FLRed}Operation '{action.value}' failed with exit code {exec_result.returncode}.{CRst}")
            elif choice == "q":
                Console.print_exit_message("Bye.")
                return 0
            else:
                print(f"{FLRed}Enter m/Enter, r, or q.{CRst}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
