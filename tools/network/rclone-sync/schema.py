"""YAML validation, task configuration, inheritance, and machine matching.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Optional, Any, Union, Set, TextIO, cast
from . import endpoints as endpoint_ops
from . import models


@dataclasses.dataclass
class FieldDef:
    """Definition of a single field in :class:`SyncTask`.

    Attributes:
        yaml_key:   Key name in YAML (e.g. ``"preferred-mode"``).
        py_attr:    Attribute name on SyncTask (e.g. ``"preferred_mode"``).
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
                if item not in {action.value for action in models.SyncAction}:
                    return f"{path}: unknown action '{item}' in 'allow-actions'"
            return None

        # Fields that accept str or list[str] (OR semantics)
        if self.yaml_key in models.STRING_OR_LIST_FIELDS:
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
        if self.yaml_key in models.LIST_STRING_FIELDS:
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


_FIELDS: list[FieldDef] = [
    # identifier
    FieldDef("name",              "name",               default="",          required=True),
    FieldDef("inherit",           "inherit_profile",    default=""),
    # mode & behaviour
    FieldDef("preferred-mode",    "preferred_mode",     default="",          allowed=models.VALID_MODES | {""}, check_type=str),
    FieldDef("path-type",         "path_type",          default=models.PathType.DIRECTORY, allowed=set(models.PathType), check_type=str),
    FieldDef("allow-actions",     "allow_actions",      default=None),
    FieldDef("progress",          "progress",           default=True,        check_type=bool),
    FieldDef("transfer",          "transfer",           default=4,           check_type=int),
    FieldDef("links",             "links",              default=False,       check_type=bool),
    FieldDef("copy-links",        "copy_links",         default=False,       check_type=bool),
    FieldDef("follow-link",       "copy_links",         default=False,       check_type=bool),
    FieldDef("delete-excluded",   "delete_excluded",    default=False,       check_type=bool),
    # paths
    FieldDef("remote-path-type",  "remote_path_type",   default="auto",      allowed=models.VALID_REMOTE_PATH_TYPES),
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
    FieldDef("log-level",         "log_level",          default="",          allowed=models.VALID_LOG_LEVELS | {""}),
    FieldDef("notify-after-sync", "notify_after_sync",  default=False,       check_type=bool),
    # lists
    FieldDef("exclude",                "exclude",                default=[]),
    FieldDef("additional-args",        "additional_args",        default=[]),
    FieldDef("alternative-remote-host","alternative_remote_hosts",default=[]),
    # filters (not rclone flags)
    FieldDef("platform",          "platform",           default="",          allowed=models.VALID_PLATFORMS),
    FieldDef("arch",              "arch",               default="",          allowed=models.VALID_ARCHS),
    FieldDef("computer-name",     "computer_name",      default=""),
]


_YAML_TO_ATTR: dict[str, str] = {fd.yaml_key: fd.py_attr for fd in _FIELDS}


_ATTR_TO_FIELD: dict[str, FieldDef] = {fd.py_attr: fd for fd in _FIELDS}


_FIELD_DEFAULTS: dict[str, Any] = {}


for fd in _FIELDS:
    if fd.yaml_key in ("exclude", "additional-args", "alternative-remote-host"):
        _FIELD_DEFAULTS[fd.py_attr] = []
    else:
        _FIELD_DEFAULTS[fd.py_attr] = fd.default


_STRUCTURAL_KEYS = {"sub-tasks", "paths"}


def _parse_local_volumes(value: object) -> dict[str, models.LocalVolume]:
    """Validate literal volume selectors without querying disks or expanding text."""
    if not isinstance(value, dict):
        raise ValueError("local-volumes must be a mapping of aliases to selectors")
    volumes: dict[str, models.LocalVolume] = {}
    for alias, definition in value.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError("local-volumes aliases must be nonempty strings")
        if not isinstance(definition, dict) or set(definition) - {"label", "filesystem"}:
            raise ValueError(f"local-volumes.{alias}: expected label and optional filesystem only")
        label, filesystem = definition.get("label"), definition.get("filesystem", "")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"local-volumes.{alias}.label must be a nonempty string")
        if not isinstance(filesystem, str) or ("filesystem" in definition and not filesystem.strip()):
            raise ValueError(f"local-volumes.{alias}.filesystem must be a nonempty string when supplied")
        volumes[alias] = models.LocalVolume(label, filesystem)
    return volumes


def _parse_endpoint(value: object, location: str) -> models.Endpoint:
    """Read a template string or a strict {path, optional volume} literal object."""
    if isinstance(value, str) and value.strip():
        return value
    if not isinstance(value, dict) or set(value) not in ({"path"}, {"path", "volume"}):
        raise ValueError(f"{location}: expected a nonempty string, {{path: ...}}, or {{volume: ..., path: ...}}")
    literal, volume = value.get("path"), value.get("volume")
    if not isinstance(literal, str) or not literal.strip():
        raise ValueError(f"{location}.path must be a nonempty string")
    if "volume" in value:
        if not isinstance(volume, str) or not volume.strip():
            raise ValueError(f"{location}.volume must be a nonempty alias")
        try:
            endpoint_ops._validate_volume_relative(literal)
        except ValueError as exc:
            raise ValueError(f"{location}: {exc}") from exc
    return models.LiteralEndpoint(literal, cast(str | None, volume))


def _parse_path_pairs(
    value: object, path: str = "task",
) -> list[models.PathPairConfig]:
    """Validate a nonempty list of path1/path2 objects.

    Args:
        value: Raw YAML list; objects may enable one per-pair address prompt.
        path: Schema location used in errors.

    Returns:
        Ordered path configurations, each containing both endpoints and its prompt.

    Raises:
        ValueError: The list, object fields, or an endpoint is invalid.
    """
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}: 'paths' must be a non-empty list of path1/path2 objects")
    pairs: list[models.PathPairConfig] = []
    for index, pair in enumerate(value):
        location = f"{path}.paths[{index}]"
        backend: models.CustomHost | None = None
        if not isinstance(pair, dict):
            raise ValueError(f"{location}: expected {{path1: ..., path2: ...}}; endpoint lists are no longer supported")
        if not {"path1", "path2"} <= set(pair) or set(pair) - {"path1", "path2", *models._CUSTOM_HOST_FIELDS}:
            raise ValueError(f"{location}: expected path1, path2, and optional custom-host switches only")
        for key, kind in models._CUSTOM_HOST_FIELDS.items():
            enabled = pair.get(key, False)
            if not isinstance(enabled, bool):
                raise ValueError(f"{location}.{key} must be bool")
            if enabled:
                if backend is not None:
                    raise ValueError(f"{location}: only one custom-host switch may be true")
                backend = kind
        endpoints = (_parse_endpoint(pair["path1"], f"{location}.path1"),
                     _parse_endpoint(pair["path2"], f"{location}.path2"))
        pairs.append(models.PathPairConfig(endpoints[0], endpoints[1], backend))
    return pairs


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
    if len(chain) > models.MAX_INHERIT_DEPTH:
        raise ValueError(
            f"Profile inheritance depth exceeded (>{models.MAX_INHERIT_DEPTH}): "
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


@dataclasses.dataclass
class SyncTask:
    """A fully-resolved rclone sync task (or sub-task) configuration.

    Configuration fields mirror YAML keys (hyphens mapped to underscores).
    Paths are declared only on sub-tasks; local_path/remote_path are internal
    endpoints populated by path_tasks() for one command at a time.
    Use from_dict() to build from YAML and from_inheritance_chain() to layer
    default → profile → task → sub-task. endpoints.resolve_paths() creates
    separate runtime pairs; rclone.to_command() builds a materialized command.
    """
    name:              str = ""
    inherit_profile:   Union[str, list[str]] = ""
    preferred_mode:    str = ""
    mode:              str = ""  # Selected runtime command; not a YAML field.
    path_type:         models.PathType = models.PathType.DIRECTORY
    allow_actions:     Optional[list[models.SyncAction]] = None
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
    local_path:        str = ""  # Runtime endpoint of one materialized path pair.
    remote_path:       str = ""  # Runtime endpoint; never read as a YAML field.
    paths: list[models.PathPairConfig] = dataclasses.field(default_factory=list)
    resolved_paths: list[models.ResolvedPathPair] = dataclasses.field(default_factory=list, repr=False)
    volume_bindings: tuple[models.VolumeBinding | None, models.VolumeBinding | None] = (None, None)
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
        get the default defined in :class:`FieldDef`. ``sub-tasks`` is
        recursed into; ``paths`` is parsed as ordered endpoint pairs.
        Legacy local-path/remote-path keys raise ValueError.
        """
        kwargs: dict[str, Any] = dict(_FIELD_DEFAULTS)
        explicit_fields: set[str] = set()
        if "local-path" in data or "remote-path" in data:
            raise ValueError("Legacy local-path/remote-path keys are not supported; use sub-task paths: [{path1: local, path2: remote}]")
        if "paths" in data:
            kwargs["paths"] = _parse_path_pairs(data["paths"])
            explicit_fields.add("paths")
        for yk, val in data.items():
            if yk in _STRUCTURAL_KEYS:
                continue
            attr = _YAML_TO_ATTR.get(yk)
            if yk in {"path-type", "allow-actions"}:
                error = _validate_field_in_dict(yk, val, "task")
                if error:
                    raise ValueError(error)
                if yk == "path-type":
                    val = models.PathType(val)
                else:
                    val = None if val is None or val == "all" else [models.SyncAction(item) for item in val]
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
        if "paths" in override.explicit_fields:
            result.paths = list(override.paths)
            result.resolved_paths = []
            result.volume_bindings = (None, None)
            result.explicit_fields.add("paths")
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
        if self.path_type == models.PathType.FILE:
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

    def _filter_matches(self, value: str | list[str], current: str, case_sensitive: bool = False) -> bool:
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
    def _normalize_platform(p: str | list[str]) -> str | list[str]:
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
    if key in {"local-path", "remote-path"}:
        return f"{path}: legacy '{key}' is not supported; use sub-task paths: [{{path1: local, path2: remote}}]"
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


def _validate_raw_task(
    task: dict, path: str, known_profiles: set, known_volumes: set[str] | None = None,
) -> list[str]:
    """Validate one raw task dict (no inheritance applied yet). Returns error list."""
    errors: list[str] = []
    if not isinstance(task, dict):
        return [f"{path}: must be a dict"]
    if "name" not in task:
        errors.append(f"{path}: missing 'name'")

    for key, value in task.items():
        if key == "sub-tasks":
            continue
        err = _validate_field_in_dict(key, value, path, known_profiles)
        if err:
            errors.append(err)

    # sub-tasks
    subs = task.get("sub-tasks")
    if not subs:
        errors.append(f"{path}: 'sub-tasks' must be a non-empty list; put paths inside each sub-task")
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
                try:
                    pairs = _parse_path_pairs(st.get("paths"), st_path)
                    for pair in pairs:
                        for endpoint in pair.endpoints:
                            if isinstance(endpoint, models.LiteralEndpoint) and endpoint.volume is not None and endpoint.volume not in (known_volumes or set()):
                                errors.append(f"{st_path}: unknown local volume alias '{endpoint.volume}'")
                except ValueError as exc:
                    errors.append(str(exc))
                for k, v in st.items():
                    if k == "paths":
                        continue
                    err = _validate_field_in_dict(k, v, st_path, known_profiles)
                    if err:
                        errors.append(err)
    return errors


def _validate_schema(schema: dict) -> list[str]:
    """Validate the complete YAML schema. Returns list of error strings."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["Schema must be a dict with optional 'settings' and 'tasks' sections"]

    unknown = set(schema) - {"settings", "tasks", "local-volumes"}
    if unknown:
        errors.append(f"Unknown top-level schema fields: {', '.join(sorted(str(key) for key in unknown))}")
    volumes: dict[str, models.LocalVolume] = {}
    try:
        volumes = _parse_local_volumes(schema.get("local-volumes", {}))
    except ValueError as exc:
        errors.append(str(exc))

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
    tasks = schema.get("tasks")
    if tasks is None:
        return errors

    if not isinstance(tasks, dict):
        return ["'tasks' must be a dict (group_name → task list)"]

    for gname, tlist in tasks.items():
        gp = f"tasks.{gname}"
        if not isinstance(tlist, list):
            errors.append(f"{gp}: must be a list")
            continue
        for i, task in enumerate(tlist):
            errors.extend(_validate_raw_task(task, f"{gp}[{i}]", known_profiles, set(volumes)))

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
