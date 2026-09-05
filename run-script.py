#!/usr/bin/env python3
"""Discover and run PersonalScripts tools from configured directories.

The primary script directory, optional additional-directory environment
variable, display highlighting, supported script types, and Gitignore-style
exclusions are defined in ``launcher-config.yaml``. Exclusions can depend on
the operating system, normalized processor architecture, and Linux GUI
availability. Existing configured dependency directories are prepended to
``PATH`` for launched tools. Bare script names are matched recursively;
multiple eligible matches are presented as a numbered selection before the
original arguments are passed through. An optional
``launcher-config.patch.yaml`` overrides personal settings only when present.
Normal startup displays resolved environment paths without starting external
tools for version discovery; ``--env-info`` enables those slower probes.
Python targets use the Conda environment selected by a leading ``--env=NAME``,
then ``ZL_CONDA_ENV``, and finally ``base``. The launcher itself remains in its
bootstrap environment.

Requirements:
    - pip: pathspec, PyYAML

Usage:
    python run-script.py                  # interactive: list & select
    python run-script.py --list           # list scripts and exit
    python run-script.py --env-info        # interactive with tool versions
    python run-script.py --env=test tool   # run tool with Conda env "test"
    python run-script.py <script-name> [args...]  # run by path or basename
"""

import sys
import os
import json
import platform
import re
import subprocess
import importlib.util
from dataclasses import dataclass
from typing import Optional, Protocol

from utils import *

CONFIG_FILE_NAME = "launcher-config.yaml"
PATCH_CONFIG_FILE_NAME = "launcher-config.patch.yaml"
ENV_INFO_FLAG = "--env-info"
CONDA_ENV_FLAG_PREFIX = "--env="
CONDA_ENV_VARIABLE = "ZL_CONDA_ENV"
DEFAULT_CONDA_ENV = "base"
CONDA_INFO_TIMEOUT_SECONDS = 15
SCRIPT_TYPE_KEYS = ("python", "bash", "powershell")
ARCHITECTURE_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x86": "x86",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
    "arm64": "arm64",
    "aarch64": "arm64",
    "armv7": "armv7",
    "armv7l": "armv7",
}


# ============ Helpers ============

def _get_project_dir() -> str:
    """Return the project directory in source and compiled modes."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _detect_platform() -> tuple[bool, bool, bool]:
    """Return (is_windows, is_macos, is_linux)."""
    name = sys.platform
    if name == "darwin":
        return False, True, False
    if name == "linux":
        return False, False, True
    if name in ("win32", "cygwin", "msys"):
        return True, False, False
    return False, False, False


class IgnoreSpec(Protocol):
    """Structural type implemented by ``pathspec.PathSpec``."""

    def match_file(self, file: str) -> bool:
        """Return whether a normalized relative path is ignored."""
        ...


@dataclass(frozen=True)
class _ScriptTypeConfig:
    """One configured script type and its default display color."""

    extension: str
    color: str


@dataclass(frozen=True)
class _HighlightRule:
    """One compiled display-highlight rule."""

    pattern: re.Pattern[str]
    color: str


@dataclass(frozen=True)
class _LauncherConfig:
    """Validated launcher configuration loaded from YAML."""

    script_root: str
    test_enabled: bool
    test_root: Optional[str]
    test_path_prefix: Optional[str]
    additional_path_env: str
    requirements_file: str
    extra_env_paths: tuple[str, ...]
    excluded_paths: frozenset[str]
    script_types: dict[str, _ScriptTypeConfig]
    default_folder_color: str
    test_header_color: str
    additional_header_color: str
    script_name_rules: tuple[_HighlightRule, ...]
    folder_name_rules: tuple[_HighlightRule, ...]
    ignore_spec: IgnoreSpec

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        """Return configured extensions in script-type order."""
        return tuple(self.script_types[key].extension for key in SCRIPT_TYPE_KEYS)


@dataclass(frozen=True)
class _LauncherInvocation:
    """Leading launcher options separated from the script selector."""

    arguments: tuple[str, ...]
    probe_environment_versions: bool
    conda_env_name: Optional[str]


def _platform_key() -> Optional[str]:
    """Return the current platform key used by the launcher configuration."""
    is_win, is_mac, is_linux = _detect_platform()
    if is_win:
        return "windows"
    if is_mac:
        return "macos"
    if is_linux:
        return "linux"
    return None


def _architecture_key() -> str:
    """Return a stable configuration key for the current processor architecture."""
    machine = platform.machine().strip().lower().replace("-", "_")
    return ARCHITECTURE_ALIASES.get(machine, machine)


def _linux_has_gui() -> bool:
    """Return whether this Linux process can access an X11 or Wayland display."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _read_pattern_list(value: object, yaml_key: str) -> list[str]:
    """Validate and return one list of Gitignore-style patterns.

    Args:
        value: Parsed YAML value to validate.
        yaml_key: Human-readable YAML key used in error messages.

    Returns:
        The validated list of pattern strings.

    Raises:
        ValueError: If the value is not a list containing only strings.
    """
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"'{yaml_key}' must be a list of strings")
    return [item for item in value if isinstance(item, str)]


def _read_mapping(value: object, yaml_key: str) -> dict[str, object]:
    """Validate and return a string-keyed YAML mapping."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"'{yaml_key}' must be a mapping")
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _read_required_string(
    mapping: dict[str, object],
    key: str,
    yaml_key: str,
) -> str:
    """Read one required, non-empty string from a YAML mapping."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{yaml_key}.{key}' must be a non-empty string")
    return value.strip()


def _resolve_project_path(project_dir: str, configured_path: str) -> str:
    """Resolve one configured path relative to the project directory."""
    expanded_path = os.path.expanduser(os.path.expandvars(configured_path))
    if not os.path.isabs(expanded_path):
        expanded_path = os.path.join(project_dir, expanded_path)
    return os.path.abspath(expanded_path)


def _resolve_existing_directories(
    project_dir: str,
    configured_paths: list[str],
) -> tuple[str, ...]:
    """Resolve, silently discard missing directories, and deduplicate paths."""
    directories: dict[str, str] = {}
    for configured_path in configured_paths:
        directory = _resolve_project_path(project_dir, configured_path)
        if os.path.isdir(directory):
            directories.setdefault(os.path.normcase(directory), directory)
    return tuple(directories.values())


def _prepend_env_paths(paths: tuple[str, ...]) -> None:
    """Prepend directories to this process's PATH without changing its parent."""
    if paths:
        current_path = os.environ.get("PATH")
        path_entries = (*paths, current_path) if current_path else paths
        os.environ["PATH"] = os.pathsep.join(path_entries)


def _resolve_config_color(color_name: str, yaml_key: str) -> str:
    """Resolve one configured color name with contextual validation errors."""
    try:
        return Console.resolve_ansi_color(color_name)
    except ValueError as exc:
        raise ValueError(f"'{yaml_key}' contains unknown color '{color_name}'") from exc


def _compile_highlight_rules(value: object, yaml_key: str) -> tuple[_HighlightRule, ...]:
    """Compile color-grouped regular expressions from launcher YAML."""
    groups = _read_mapping(value, yaml_key)
    rules: list[_HighlightRule] = []
    for color_name, pattern_value in groups.items():
        color = _resolve_config_color(color_name, yaml_key)
        for pattern_text in _read_pattern_list(pattern_value, f"{yaml_key}.{color_name}"):
            try:
                pattern = re.compile(pattern_text)
            except re.error as exc:
                raise ValueError(
                    f"'{yaml_key}.{color_name}' contains invalid regex "
                    f"'{pattern_text}': {exc}"
                ) from exc
            rules.append(_HighlightRule(pattern=pattern, color=color))
    return tuple(rules)


def _deep_merge_mappings(
    base: dict[str, object],
    override: dict[str, object],
) -> dict[str, object]:
    """Recursively merge YAML mappings, replacing lists and scalar values."""
    merged: dict[str, object] = dict(base)
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge_mappings(
                _read_mapping(base_value, key),
                _read_mapping(override_value, key),
            )
        else:
            merged[key] = override_value
    return merged


def _load_launcher_config(project_dir: str) -> _LauncherConfig:
    """Load and validate all launcher settings from YAML.

    Args:
        project_dir: Directory containing the launcher configuration.

    Returns:
        Fully validated paths, script types, colors, regexes, and ignore rules.

    Raises:
        FileNotFoundError: If the launcher configuration does not exist.
        ImportError: If PyYAML or pathspec is unavailable.
        ValueError: If the YAML structure is invalid.
    """
    try:
        import yaml
        from pathspec import PathSpec
    except ImportError as exc:
        package_name = "PyYAML" if exc.name == "yaml" else "pathspec"
        raise ImportError(f"Missing Python dependency: {package_name}") from exc

    config_path = os.path.join(project_dir, CONFIG_FILE_NAME)
    try:
        with open(config_path, "r", encoding="utf-8") as stream:
            document = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {CONFIG_FILE_NAME}: {exc}") from exc

    root = _read_mapping(document, "root")

    patch_path = os.path.join(project_dir, PATCH_CONFIG_FILE_NAME)
    if os.path.isfile(patch_path):
        try:
            with open(patch_path, "r", encoding="utf-8") as stream:
                patch_document = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in {PATCH_CONFIG_FILE_NAME}: {exc}") from exc
        if patch_document is not None:
            patch_root = _read_mapping(patch_document, "patch root")
            root = _deep_merge_mappings(root, patch_root)

    launcher = _read_mapping(root.get("launcher"), "launcher")
    display = _read_mapping(root.get("display"), "display")

    script_root = _resolve_project_path(
        project_dir,
        _read_required_string(launcher, "script-root", "launcher"),
    )
    test_settings = _read_mapping(launcher.get("test"), "launcher.test")
    test_enabled_value = test_settings.get("enabled")
    if not isinstance(test_enabled_value, bool):
        raise ValueError("'launcher.test.enabled' must be a boolean")

    test_root: Optional[str] = None
    test_path_prefix: Optional[str] = None
    configured_test_root = test_settings.get("test-root")
    if test_enabled_value or configured_test_root is not None:
        if not isinstance(configured_test_root, str) or not configured_test_root.strip():
            raise ValueError("'launcher.test.test-root' must be a non-empty string")
        configured_test_root = configured_test_root.strip()
        test_root = _resolve_project_path(project_dir, configured_test_root)
        if os.path.isabs(configured_test_root):
            test_path_prefix = os.path.basename(test_root)
        else:
            test_path_prefix = _normalize_relative_path(configured_test_root).rstrip("/")

    requirements_file = _resolve_project_path(
        project_dir,
        _read_required_string(launcher, "requirements-file", "launcher"),
    )
    additional_path_env = _read_required_string(
        launcher,
        "additional-path-env",
        "launcher",
    )

    excluded_paths = frozenset(
        _normalize_relative_path(path)
        for path in _read_pattern_list(
            launcher.get("excluded-paths"),
            "launcher.excluded-paths",
        )
    )

    script_type_values = _read_mapping(
        launcher.get("script-types"),
        "launcher.script-types",
    )
    script_types: dict[str, _ScriptTypeConfig] = {}
    configured_extensions: set[str] = set()
    for script_type_key in SCRIPT_TYPE_KEYS:
        type_mapping = _read_mapping(
            script_type_values.get(script_type_key),
            f"launcher.script-types.{script_type_key}",
        )
        extension = _read_required_string(
            type_mapping,
            "extension",
            f"launcher.script-types.{script_type_key}",
        )
        if not extension.startswith(".") or "/" in extension or "\\" in extension:
            raise ValueError(
                f"'launcher.script-types.{script_type_key}.extension' "
                "must be a file extension"
            )
        if extension in configured_extensions:
            raise ValueError(f"duplicate configured script extension: {extension}")
        configured_extensions.add(extension)
        color_name = _read_required_string(
            type_mapping,
            "color",
            f"launcher.script-types.{script_type_key}",
        )
        script_types[script_type_key] = _ScriptTypeConfig(
            extension=extension,
            color=_resolve_config_color(
                color_name,
                f"launcher.script-types.{script_type_key}.color",
            ),
        )

    default_folder_color_name = _read_required_string(
        display,
        "default-folder-color",
        "display",
    )
    test_header_color_name = _read_required_string(
        display,
        "test-header-color",
        "display",
    )
    additional_header_color_name = _read_required_string(
        display,
        "additional-header-color",
        "display",
    )

    script_name_rules = _compile_highlight_rules(
        root.get("script-name-highlight-pattern"),
        "script-name-highlight-pattern",
    )
    folder_name_rules = _compile_highlight_rules(
        root.get("folder-name-highlight-pattern"),
        "folder-name-highlight-pattern",
    )

    ignore_list = _read_mapping(root.get("ignore-list"), "ignore-list")
    patterns = _read_pattern_list(
        ignore_list.get("all-platforms"),
        "ignore-list.all-platforms",
    )
    platform_rules = _read_mapping(
        ignore_list.get("platform-specific"),
        "ignore-list.platform-specific",
    )
    architecture_rules = _read_mapping(
        ignore_list.get("arch-specific", {}),
        "ignore-list.arch-specific",
    )
    no_gui_rules = _read_mapping(
        ignore_list.get("no-gui", {}),
        "ignore-list.no-gui",
    )

    platform_key = _platform_key()
    if platform_key is not None:
        patterns.extend(
            _read_pattern_list(
                platform_rules.get(platform_key),
                f"ignore-list.platform-specific.{platform_key}",
            )
        )

        architecture_key = _architecture_key()
        architecture_platform_rules = _read_mapping(
            architecture_rules.get(architecture_key, {}),
            f"ignore-list.arch-specific.{architecture_key}",
        )
        patterns.extend(
            _read_pattern_list(
                architecture_platform_rules.get(platform_key),
                f"ignore-list.arch-specific.{architecture_key}.{platform_key}",
            )
        )

        if platform_key == "linux" and not _linux_has_gui():
            patterns.extend(
                _read_pattern_list(
                    no_gui_rules.get("linux"),
                    "ignore-list.no-gui.linux",
                )
            )

    try:
        ignore_spec = PathSpec.from_lines("gitwildmatch", patterns)
    except Exception as exc:
        raise ValueError(f"invalid Gitignore pattern: {exc}") from exc

    extra_env_path_rules = _read_mapping(
        root.get("extra-env-paths", {}),
        "extra-env-paths",
    )
    configured_extra_env_paths = _read_pattern_list(
        extra_env_path_rules.get("all-platforms"),
        "extra-env-paths.all-platforms",
    )
    if platform_key is not None:
        configured_extra_env_paths.extend(
            _read_pattern_list(
                extra_env_path_rules.get(platform_key),
                f"extra-env-paths.{platform_key}",
            )
        )
    extra_env_paths = _resolve_existing_directories(
        project_dir,
        configured_extra_env_paths,
    )

    return _LauncherConfig(
        script_root=script_root,
        test_enabled=test_enabled_value,
        test_root=test_root,
        test_path_prefix=test_path_prefix,
        additional_path_env=additional_path_env,
        requirements_file=requirements_file,
        extra_env_paths=extra_env_paths,
        excluded_paths=excluded_paths,
        script_types=script_types,
        default_folder_color=_resolve_config_color(
            default_folder_color_name,
            "display.default-folder-color",
        ),
        test_header_color=_resolve_config_color(
            test_header_color_name,
            "display.test-header-color",
        ),
        additional_header_color=_resolve_config_color(
            additional_header_color_name,
            "display.additional-header-color",
        ),
        script_name_rules=script_name_rules,
        folder_name_rules=folder_name_rules,
        ignore_spec=ignore_spec,
    )


def _normalize_relative_path(path: str, is_dir: bool = False) -> str:
    """Normalize a relative path for Gitignore-style matching."""
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if is_dir and not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return normalized


def _is_ignored(ignore_spec: IgnoreSpec, relative_path: str, is_dir: bool = False) -> bool:
    """Return whether a path relative to one discovery root is ignored."""
    return ignore_spec.match_file(_normalize_relative_path(relative_path, is_dir))


def _is_valid_script(
    script_dir: str,
    script_path: str,
    config: _LauncherConfig,
) -> bool:
    """Return whether a candidate is a supported, non-ignored script."""
    rel = os.path.relpath(script_path, script_dir)
    normalized = _normalize_relative_path(rel)
    if normalized in config.excluded_paths:
        return False
    if os.path.basename(script_path).startswith("_"):
        return False
    if not script_path.endswith(config.supported_extensions):
        return False
    return not _is_ignored(config.ignore_spec, rel)


# ============ Interpreter Discovery ============

# ============ Script Discovery ============

def find_scripts(script_dir: str, config: _LauncherConfig) -> list[str]:
    """Find all runnable scripts, returning relative paths from script_dir.

    Excludes:
      - paths matched by configured Gitignore-style rules
      - .sh scripts if bash is not available
      - .ps1 scripts if pwsh is not available
      - files whose names start with an underscore

    Gitignore patterns are evaluated relative to ``script_dir``.  All
    interpreter-supported scripts are retained, including same-stem files with
    different extensions.
    """
    has_bash = Environment.find_bash() is not None
    has_pwsh = Environment.find_pwsh() is not None

    extensions: list[str] = [config.script_types["python"].extension]
    if has_bash:
        extensions.append(config.script_types["bash"].extension)
    if has_pwsh:
        extensions.append(config.script_types["powershell"].extension)

    scripts: list[str] = []

    for root, dirs, files in os.walk(script_dir):
        dirs[:] = [
            directory
            for directory in dirs
            if not _is_ignored(
                config.ignore_spec,
                os.path.relpath(os.path.join(root, directory), script_dir),
                is_dir=True,
            )
        ]

        for filename in files:
            if filename.startswith("_"):
                continue
            if any(filename.endswith(ext) for ext in extensions):
                full = os.path.join(root, filename)
                rel = os.path.relpath(full, script_dir)
                if _is_valid_script(script_dir, full, config):
                    scripts.append(rel)

    scripts.sort()
    return scripts


# ============ Script Resolution ============

def _script_name_matches(
    relative_path: str,
    query: str,
    config: _LauncherConfig,
) -> bool:
    """Return whether one discovered script matches a user query.

    A query containing a directory separator is matched against the complete
    relative path. A bare query is matched against the basename in any
    subdirectory. Omitting the extension matches every supported extension
    with the same stem.

    Args:
        relative_path: Script path relative to its discovery root.
        query: User-supplied script name, with or without a path or extension.
        config: Validated launcher settings, including supported extensions.

    Returns:
        ``True`` when the discovered script matches the query.
    """
    normalized_path = relative_path.replace("\\", "/").lstrip("/")
    normalized_query = query.replace("\\", "/").lstrip("/")
    while normalized_query.startswith("./"):
        normalized_query = normalized_query[2:]

    if not normalized_query:
        return False

    match_path = normalized_path if "/" in normalized_query else os.path.basename(normalized_path)
    has_supported_extension = normalized_query.lower().endswith(config.supported_extensions)
    if not has_supported_extension:
        match_path = os.path.splitext(match_path)[0]

    if _detect_platform()[0]:
        return match_path.casefold() == normalized_query.casefold()
    return match_path == normalized_query


def _collect_group_matches(
    group_selector: str,
    script_dir: str,
    scripts: list[str],
    query: str,
    config: _LauncherConfig,
    display_prefix: Optional[str] = None,
) -> list[tuple[str, str, str]]:
    """Collect matching scripts from one already-filtered discovery group.

    Args:
        group_selector: Launcher selector (for example ``"0"`` or ``"test"``).
        script_dir: Absolute discovery-root path.
        scripts: Eligible script paths relative to ``script_dir``.
        query: User-supplied path or basename query.
        config: Validated launcher settings.
        display_prefix: Optional path prefix used for Test labels.

    Returns:
        Tuples containing the group number, display label, and absolute path.
    """
    matches: list[tuple[str, str, str]] = []
    for relative_path in scripts:
        if not _script_name_matches(relative_path, query, config):
            continue
        normalized_path = relative_path.replace("\\", "/")
        label = (
            f"{display_prefix}/{normalized_path}"
            if display_prefix
            else f"@{group_selector}:{normalized_path}"
        )
        full_path = os.path.abspath(os.path.join(script_dir, relative_path))
        matches.append((group_selector, label, full_path))
    return matches


def _resolve_with_groups(
    name: str,
    script_dir: str,
    scripts: list[str],
    test_group: Optional[tuple[str, list[str]]],
    additional_groups: list[tuple[str, list[str]]],
    config: _LauncherConfig,
) -> Optional[str]:
    """Resolve a script query across discovery groups.

    Bare names match basenames recursively and extensionless names include all
    supported extensions. ``@N:`` restricts matching to one group. Multiple
    eligible matches are presented through ``Menu.select()``.

    Args:
        name: User-supplied script query, optionally prefixed with ``@N:``.
        script_dir: Configured primary discovery root.
        scripts: Eligible scripts from the primary discovery root.
        test_group: Optional Test discovery root and eligible scripts.
        additional_groups: Additional discovery roots and their eligible
            relative script paths.
        config: Validated launcher settings.

    Returns:
        The selected absolute script path, or ``None`` when nothing matches.

    Side effects:
        Prints and prompts with a numbered menu when multiple scripts match.
    """
    if os.path.isabs(name):
        if os.path.isfile(name) and name.lower().endswith(config.supported_extensions):
            return os.path.abspath(name)
        return None

    groups: list[tuple[str, str, list[str], Optional[str]]] = [
        ("0", script_dir, scripts, None)
    ]
    if test_group is not None and config.test_path_prefix is not None:
        groups.append(
            (
                "test",
                test_group[0],
                test_group[1],
                config.test_path_prefix,
            )
        )
    groups.extend(
        (str(group_index), directory, group_scripts, None)
        for group_index, (directory, group_scripts) in enumerate(additional_groups, start=1)
    )

    query = name
    prefix_match = re.match(r"^@([^:]+):(.+)$", name)
    if prefix_match:
        requested_group = prefix_match.group(1).casefold()
        query = prefix_match.group(2)
        groups = [group for group in groups if group[0] == requested_group]

    matches: list[tuple[str, str, str]] = []
    for group_selector, directory, group_scripts, display_prefix in groups:
        group_query = query
        normalized_query = query.replace("\\", "/").lstrip("/")
        if display_prefix and "/" in normalized_query:
            normalized_prefix = display_prefix.replace("\\", "/").strip("/")
            expected_prefix = f"{normalized_prefix}/"
            if not normalized_query.casefold().startswith(expected_prefix.casefold()):
                continue
            group_query = normalized_query[len(expected_prefix):]
        matches.extend(
            _collect_group_matches(
                group_selector,
                directory,
                group_scripts,
                group_query,
                config,
                display_prefix,
            )
        )

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0][2]

    options = [
        MenuOption(keys=[str(index)], description=label, value=path)
        for index, (_, label, path) in enumerate(matches)
    ]
    print(f"\n{FLYellow}Warning: multiple scripts match '{CRst}{name}{FLYellow}'.{CRst}")
    selected = Menu.select(
        options,
        prompt="Select script",
        default_key="0",
        separator=False,
        key_color=FGray,
        default_desc_color=CRst,
    )
    return selected if isinstance(selected, str) else None


# ============ Display ============

def _script_color(path: str, config: _LauncherConfig) -> str:
    """Return the configured default color for one script path."""
    for script_type in config.script_types.values():
        if path.endswith(script_type.extension):
            return script_type.color
    return config.script_types["python"].color


def _highlight_text(
    text: str,
    rules: tuple[_HighlightRule, ...],
    default_color: str,
) -> str:
    """Apply ordered non-overlapping highlight rules to one text value."""
    matches: list[tuple[int, int, str]] = []
    for rule in rules:
        for match in rule.pattern.finditer(text):
            matches.append((match.start(), match.end(), rule.color))

    if not matches:
        return f"{default_color}{text}{CRst}"

    matches.sort(key=lambda item: item[0])
    parts: list[str] = []
    last_end = 0
    for start, end, color in matches:
        if start < last_end:
            continue
        if start > last_end:
            parts.append(f"{default_color}{text[last_end:start]}{CRst}")
        parts.append(f"{color}{text[start:end]}{CRst}")
        last_end = end

    if last_end < len(text):
        parts.append(f"{default_color}{text[last_end:]}{CRst}")
    return "".join(parts)


def _highlight_subdirectory(subdirectory: str, config: _LauncherConfig) -> str:
    """Color a subdirectory and its trailing separator from configured rules."""
    normalized = subdirectory.replace("\\", "/")
    normalized = f"{normalized}/"
    return _highlight_text(
        normalized,
        config.folder_name_rules,
        config.default_folder_color,
    )


def _format_script_path(relative_path: str, config: _LauncherConfig) -> str:
    """Return one relative script path with configured ANSI highlighting."""
    normalized = relative_path.replace("\\", "/")
    subdirectory, separator, filename = normalized.rpartition("/")
    if not separator:
        filename = normalized

    highlighted_filename = _highlight_filename(filename, config)

    if subdirectory:
        return f"{_highlight_subdirectory(subdirectory, config)}{highlighted_filename}"
    return highlighted_filename


def _highlight_filename(filename: str, config: _LauncherConfig) -> str:
    """Return a filename highlighted by configured regex rules."""
    return _highlight_text(
        filename,
        config.script_name_rules,
        _script_color(filename, config),
    )


def show_scripts(
    script_dir: str,
    scripts: list[str],
    config: _LauncherConfig,
    test_group: Optional[tuple[str, list[str]]] = None,
    additional_groups: Optional[list[tuple[str, list[str]]]] = None,
) -> list[str]:
    """Print all discovery groups and return their launcher selector tokens."""
    has_test = bool(test_group and test_group[1])
    has_additional = bool(additional_groups)
    if not scripts and not has_test and not has_additional:
        print(f"No scripts found in: `{script_dir}`")
        return []

    # Build type label
    types: list[str] = []
    available_types = {
        key: any(script.endswith(script_type.extension) for script in scripts)
        for key, script_type in config.script_types.items()
    }
    if test_group:
        for key, script_type in config.script_types.items():
            available_types[key] = available_types[key] or any(
                script.endswith(script_type.extension) for script in test_group[1]
            )
    if additional_groups:
        for _, add_scripts in additional_groups:
            for key, script_type in config.script_types.items():
                available_types[key] = available_types[key] or any(
                    script.endswith(script_type.extension) for script in add_scripts
                )
    for key in SCRIPT_TYPE_KEYS:
        if available_types[key]:
            label = "PowerShell" if key == "powershell" else key
            types.append(f"{config.script_types[key].color}{label}{CRst}")
    type_str = "/".join(types) if types else "scripts"

    Console.print_separator(width=60, color_ansi_esc=None, indent=2)

    print(f"  Available {type_str} scripts in `{FGray}{script_dir}{CRst}`:")

    test_count = len(test_group[1]) if test_group else 0
    additional_count = sum(len(g[1]) for g in additional_groups) if additional_groups else 0
    total = len(scripts) + test_count + additional_count
    max_digits = len(str(total - 1)) if total > 0 else 1

    all_scripts: list[str] = []
    cnt = 0

    root_scripts = [s for s in scripts if "/" not in s.replace("\\", "/")]
    sub_scripts = [s for s in scripts if "/" in s.replace("\\", "/")]

    # ── root scripts ──
    for rel in root_scripts:
        print(f"  {FGray}[{cnt:>{max_digits}}]{CRst}: {_format_script_path(rel, config)}")
        all_scripts.append(f"@0:{rel}")
        cnt += 1

    # ── subfolder scripts (no header) ──
    for rel in sub_scripts:
        print(f"  {FGray}[{cnt:>{max_digits}}]{CRst}: {_format_script_path(rel, config)}")
        all_scripts.append(f"@0:{rel}")
        cnt += 1

    # ── configured test scripts ──
    if test_group and config.test_path_prefix:
        print()
        print(f"  {config.test_header_color}─── Test ───{CRst}")
        for rel in test_group[1]:
            normalized_rel = rel.replace("\\", "/")
            display_path = f"{config.test_path_prefix}/{normalized_rel}"
            print(
                f"  {FGray}[{cnt:>{max_digits}}]{CRst}: "
                f"{_format_script_path(display_path, config)}"
            )
            all_scripts.append(f"@test:{rel}")
            cnt += 1

    # ── additional scripts ──
    if additional_groups:
        for group_idx, (_, add_scripts) in enumerate(additional_groups):
            display_idx = group_idx + 1
            print()
            print(f"  {config.additional_header_color}─── Additional [{display_idx}] ───{CRst}")
            for rel in add_scripts:
                print(f"  {FGray}[{cnt:>{max_digits}}]{CRst}: {_format_script_path(rel, config)}")
                all_scripts.append(f"@{display_idx}:{rel}")
                cnt += 1

    Console.print_separator(width=60, color_ansi_esc=None, indent=2)

    return all_scripts


# ============ Script Execution ============

def _parse_conda_env_flag(argument: str) -> str:
    """Return and validate the environment name in one ``--env=`` option.

    Args:
        argument: Complete launcher argument beginning with ``--env=``.

    Returns:
        Non-empty Conda environment name.

    Raises:
        ValueError: If the value is empty or resembles a filesystem path.
    """
    env_name = argument.removeprefix(CONDA_ENV_FLAG_PREFIX).strip()
    if not env_name:
        raise ValueError("--env requires a non-empty environment name")
    if "/" in env_name or "\\" in env_name:
        raise ValueError("--env accepts an environment name, not a path")
    return env_name


def _parse_launcher_invocation(arguments: list[str]) -> _LauncherInvocation:
    """Separate leading launcher options from the target script selector.

    ``--env-info`` and ``--env=<name>`` are recognized only before the target
    script name, numeric selector, or ``--list``. Options after that selector
    remain untouched for the target script.

    Args:
        arguments: Command-line arguments excluding the launcher path.

    Returns:
        Parsed launcher settings and unconsumed selector/target arguments.

    Raises:
        ValueError: If ``--env`` is invalid or repeated.
    """
    probe_versions = False
    conda_env_name: Optional[str] = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == ENV_INFO_FLAG:
            probe_versions = True
        elif argument.startswith(CONDA_ENV_FLAG_PREFIX):
            if conda_env_name is not None:
                raise ValueError("--env may be specified only once")
            conda_env_name = _parse_conda_env_flag(argument)
        else:
            break
        index += 1
    return _LauncherInvocation(
        arguments=tuple(arguments[index:]),
        probe_environment_versions=probe_versions,
        conda_env_name=conda_env_name,
    )


def _default_conda_env_name(command_line_env: Optional[str]) -> str:
    """Apply CLI, environment-variable, and base precedence for target Python."""
    if command_line_env is not None:
        return command_line_env
    configured_env = os.environ.get(CONDA_ENV_VARIABLE, "").strip()
    return configured_env or DEFAULT_CONDA_ENV


def _conda_env_names_equal(left: str, right: str) -> bool:
    """Compare Conda environment names using platform path case semantics."""
    return os.path.normcase(left) == os.path.normcase(right)


def _resolve_conda_python(env_name: str) -> str:
    """Resolve the Python executable belonging to a named Conda environment.

    The current interpreter is returned without starting Conda when it already
    belongs to the requested environment. Other environments are discovered
    through ``conda info --envs --json`` so custom ``envs_dirs`` are honored.

    Args:
        env_name: Exact Conda environment name, or ``base``.

    Returns:
        Absolute path to the selected environment's Python executable.

    Raises:
        RuntimeError: If Conda is unavailable, discovery fails, the environment
            does not exist or is ambiguous, or it has no Python executable.
    """
    current_env = Environment.get_conda_env()
    if current_env is not None and _conda_env_names_equal(current_env, env_name):
        return os.path.abspath(sys.executable)

    conda_executable = Environment.find_conda()
    if conda_executable is None:
        raise RuntimeError(
            f"Cannot resolve Conda environment '{env_name}': conda is not in PATH."
        )
    try:
        result = subprocess.run(
            [conda_executable, "info", "--envs", "--json"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CONDA_INFO_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"Cannot inspect Conda environments: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())
        if not detail:
            detail = f"conda exited with code {result.returncode}"
        raise RuntimeError(f"Cannot inspect Conda environments: {detail}")

    try:
        payload: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Conda returned invalid environment data.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Conda returned invalid environment data.")

    root_prefix = payload.get("root_prefix")
    env_paths = payload.get("envs")
    if not isinstance(root_prefix, str) or not isinstance(env_paths, list):
        raise RuntimeError("Conda returned incomplete environment data.")

    if _conda_env_names_equal(env_name, DEFAULT_CONDA_ENV):
        matching_prefixes = [root_prefix]
    else:
        matching_prefixes = [
            path
            for path in env_paths
            if isinstance(path, str)
            and _conda_env_names_equal(os.path.basename(os.path.normpath(path)), env_name)
        ]
    if not matching_prefixes:
        raise RuntimeError(f"Conda environment '{env_name}' does not exist.")
    if len(matching_prefixes) > 1:
        raise RuntimeError(
            f"Multiple Conda environments are named '{env_name}'; use a unique name."
        )

    env_prefix = os.path.abspath(matching_prefixes[0])
    if not os.path.isdir(os.path.join(env_prefix, "conda-meta")):
        raise RuntimeError(f"Conda environment '{env_name}' is invalid.")
    python_path = (
        os.path.join(env_prefix, "python.exe")
        if _detect_platform()[0]
        else os.path.join(env_prefix, "bin", "python")
    )
    if not os.path.isfile(python_path):
        raise RuntimeError(
            f"Conda environment '{env_name}' has no Python executable."
        )
    return python_path


def run_py_script(
    script_path: str,
    args: list[str],
    python_executable: str,
) -> int:
    """Execute a Python script with the selected Conda interpreter.

    Uses the existing in-process ``main()`` path when the selected interpreter
    is the launcher interpreter. Otherwise, starts the target script as a child
    process so only the target—not the launcher—uses the selected environment.

    Args:
        script_path: Absolute or relative path to the target Python script.
        args: Arguments passed to the target script.
        python_executable: Interpreter from the requested Conda environment.

    Returns:
        Target ``main()`` result or child-process exit code.

    Side effects:
        Imports and invokes the target in-process, or starts a child process
        when a different Conda environment was selected.
    """
    abs_path = os.path.abspath(script_path)
    selected_python = os.path.realpath(python_executable)
    launcher_python = os.path.realpath(sys.executable)
    if os.path.normcase(selected_python) != os.path.normcase(launcher_python):
        result = subprocess.run(
            [python_executable, abs_path, *args],
            check=False,
        )
        return result.returncode

    module_name = "_entry_" + abs_path \
        .replace(os.sep, "_") \
        .replace(".", "_") \
        .replace("-", "_") \
        .lstrip("_")

    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        print(f"{FLRed}Cannot load script: {abs_path}{CRst}", file=sys.stderr)
        return 1

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"{FLRed}Error loading script {abs_path}: {e}{CRst}", file=sys.stderr)
        return 1

    if not hasattr(module, "main"):
        print(f"{FLRed}Script has no main() function: {abs_path}{CRst}", file=sys.stderr)
        return 1

    try:
        return module.main()
    except SystemExit as e:
        if e.code is None:
            return 0
        if isinstance(e.code, int):
            return e.code
        return 1


def run_sh_script(script_path: str, args: list[str]) -> int:
    """Execute a .sh script via bash."""
    bash = Environment.find_bash()
    if bash is None:
        print(f"{FLRed}Cannot find bash interpreter{CRst}", file=sys.stderr)
        return 1
    result = subprocess.run([bash, script_path] + args, check=False)
    return result.returncode


def run_ps1_script(script_path: str, args: list[str]) -> int:
    """Execute a .ps1 script via PowerShell."""
    pwsh = Environment.find_pwsh()
    if pwsh is None:
        print(f"{FLRed}Cannot find PowerShell interpreter (pwsh/powershell){CRst}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path] + args,
        check=False,
    )
    return result.returncode


# ============ Main ============

def _print_help(config: _LauncherConfig) -> None:
    """Print launcher usage, configuration, and dependency information."""
    path_separator = os.pathsep
    project_dir = _get_project_dir()
    script_root = os.path.relpath(config.script_root, project_dir).replace("\\", "/")
    requirements_file = os.path.relpath(
        config.requirements_file,
        project_dir,
    ).replace("\\", "/")
    print(f"""
{FLYellow}PERSONAL SCRIPT LAUNCHER{CRst}

{FLYellow}Usage:{CRst}
  python run-script.py
  python run-script.py --list
  python run-script.py --env-info [--list | <script-name> [args...]]
  python run-script.py --env=<name> [<number> | <script-name> [args...]]
  python run-script.py <script-name> [args...]
  python run-script.py @N:<script-name> [args...]
  python run-script.py @test:<script-name> [args...]

{FLYellow}Description:{CRst}
  Lists runnable scripts from {FGray}{script_root}{CRst} and optional additional
  directories, then runs a selection by number or name. A bare name searches
  every eligible subdirectory and supported extension. Multiple matches are
  shown as a numbered selection before arguments are passed through. When the
  configured Test group is enabled, its scripts participate in the same lookup.
  Ignore rules can depend on the OS, normalized processor architecture, and
  whether Linux has an X11 or Wayland display. Existing dependency directories
  configured under extra-env-paths are prepended to PATH without warnings for
  missing directories.

{FLYellow}Options:{CRst}
  {FLCyan}--list{CRst}                   List scripts and exit.
  {FLCyan}{ENV_INFO_FLAG}{CRst}               Probe and show Conda, PowerShell, and Bash versions.
                             Must precede the script selector.
  {FLCyan}{CONDA_ENV_FLAG_PREFIX}<name>{CRst}             Run the selected Python script in this Conda environment.
                             Must precede the script selector and overrides
                             {FLCyan}{CONDA_ENV_VARIABLE}{CRst}.
  {FLCyan}--help, -h{CRst}               Show this help message and exit.

{FLYellow}Configuration:{CRst}
  {FLCyan}{CONFIG_FILE_NAME}{CRst}         Paths, script types, colors, and context-aware ignore rules.
  {FLCyan}{PATCH_CONFIG_FILE_NAME}{CRst}   Optional personal overrides; ignored when absent.
  {FLCyan}{config.additional_path_env}{CRst}  Additional directories separated by
                             {FGray}{path_separator}{CRst}. Relative paths use the project root.
  {FLCyan}{CONDA_ENV_VARIABLE}{CRst}          Default Conda environment for Python targets.
                             Empty or unset selects {FGray}{DEFAULT_CONDA_ENV}{CRst}.

{FLYellow}Requirements:{CRst}
  Python 3.13+, PyYAML, pathspec
  Install dependencies with:
    {FGray}python -m pip install -r {requirements_file}{CRst}
""")


def _resolve_additional_directories(
    project_dir: str,
    config: _LauncherConfig,
) -> list[str]:
    """Resolve and deduplicate configured additional script directories.

    Args:
        project_dir: Base directory for resolving relative entries.
        config: Validated launcher settings containing the environment name.

    Returns:
        Existing absolute directories in environment-variable order.

    Side effects:
        Prints a warning for each configured path that is not a directory.
    """
    raw_value = os.environ.get(config.additional_path_env, "").strip()
    if not raw_value:
        return []

    directories: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_value.split(os.pathsep):
        raw_path = raw_path.strip()
        if not raw_path:
            continue

        expanded_path = os.path.expanduser(os.path.expandvars(raw_path))
        if not os.path.isabs(expanded_path):
            expanded_path = os.path.join(project_dir, expanded_path)
        resolved_path = os.path.abspath(expanded_path)
        normalized_key = os.path.normcase(resolved_path)

        if normalized_key in seen:
            continue
        seen.add(normalized_key)

        if not os.path.isdir(resolved_path):
            print(
                f"{FLYellow}Ignoring missing additional directory:{CRst} "
                f"{FGray}{resolved_path}{CRst}",
                file=sys.stderr,
            )
            continue
        directories.append(resolved_path)

    return directories


def main() -> int:
    try:
        invocation = _parse_launcher_invocation(sys.argv[1:])
    except ValueError as exc:
        print(f"{FLRed}Invalid launcher option:{CRst} {exc}", file=sys.stderr)
        return 2
    launcher_args = list(invocation.arguments)
    target_conda_env = _default_conda_env_name(invocation.conda_env_name)

    project_dir = _get_project_dir()
    try:
        config = _load_launcher_config(project_dir)
    except (FileNotFoundError, ImportError, ValueError) as exc:
        print(f"{FLRed}Cannot load {CONFIG_FILE_NAME}:{CRst} {exc}", file=sys.stderr)
        return 1

    _prepend_env_paths(config.extra_env_paths)

    if launcher_args and launcher_args[0] in ("--help", "-h"):
        _print_help(config)
        return 0

    Console.print_banner("PERSONAL SCRIPT LAUNCHER")
    Environment.print_env_info(
        probe_versions=invocation.probe_environment_versions
    )
    print(
        f"  {FLCyan}Target Conda env:{CRst} "
        f"{FLYellow}{target_conda_env}{CRst}\n"
    )

    script_dir = config.script_root
    if not os.path.isdir(script_dir):
        print(f"{FLRed}Script directory not found:{CRst} {FGray}{script_dir}{CRst}", file=sys.stderr)
        return 1

    scripts = find_scripts(script_dir, config)

    # ── optional test script directory ────────────────────
    test_group: Optional[tuple[str, list[str]]] = None
    if config.test_enabled:
        assert config.test_root is not None
        if not os.path.isdir(config.test_root):
            print(
                f"{FLRed}Test script directory not found:{CRst} "
                f"{FGray}{config.test_root}{CRst}",
                file=sys.stderr,
            )
            return 1
        test_group = (config.test_root, find_scripts(config.test_root, config))

    # ── additional script directories ─────────────────────
    additional_groups: list[tuple[str, list[str]]] = []
    for directory in _resolve_additional_directories(project_dir, config):
        scripts_found = find_scripts(directory, config)
        if scripts_found:
            additional_groups.append((directory, scripts_found))

    script_name: Optional[str] = None
    remaining_args: list[str] = []

    if launcher_args:
        script_name = launcher_args[0]
        remaining_args = launcher_args[1:]

    show_list = (
        script_name is None
        or script_name == "--list"
        or script_name.isdigit()
    )

    if show_list:
        all_rel = show_scripts(
            script_dir,
            scripts,
            config,
            test_group,
            additional_groups if additional_groups else None,
        )

        if script_name == "--list":
            return 0
        if "--list" in remaining_args:
            return 0
        if not all_rel:
            return 0

        print(f"\nAll of the python scripts support argument {FLCyan}--help{CRst} for usage details.")
        print(f"Examples:")
        print(f"    {FLYellow}5{CRst}                              select by number")
        print(f"    {FLCyan}--env=test{CRst} {FLYellow}5{CRst}                   select environment + number")
        print(f"    {FLYellow}5{CRst} {FLCyan}--help{CRst}                       number + passthrough args")
        print(f"    {FLYellow}script-name{CRst} {FLCyan}arg1 arg2{CRst}          name + passthrough args")

        script_path: Optional[str] = None
        command_line_parts = (
            [script_name, *remaining_args]
            if script_name is not None and script_name.isdigit()
            else None
        )
        while True:
            noninteractive_choice = command_line_parts is not None
            if command_line_parts is not None:
                parts = command_line_parts
                command_line_parts = None
            else:
                print(f"\n{FLYellow}Enter number or script name to execute{CRst} (or {FLYellow}Enter{CRst} to exit): ", end="")
                try:
                    choice_line = input().strip()
                except EOFError:
                    print()
                    Console.print_exit_message("Bye.")
                    return 0

                if not choice_line:
                    Console.print_exit_message("Bye.")
                    return 0
                parts = choice_line.split()

            if parts[0].startswith(CONDA_ENV_FLAG_PREFIX):
                try:
                    target_conda_env = _parse_conda_env_flag(parts[0])
                except ValueError as exc:
                    print(f"{FLRed}Invalid launcher option:{CRst} {exc}", file=sys.stderr)
                    if noninteractive_choice:
                        return 2
                    continue
                parts = parts[1:]
                if not parts:
                    print(
                        f"{FLRed}Missing script number or name after --env.{CRst}",
                        file=sys.stderr,
                    )
                    if noninteractive_choice:
                        return 2
                    continue

            first_token = parts[0]
            remaining_args = parts[1:]

            if first_token.isdigit():
                idx = int(first_token)
                if idx < 0 or idx >= len(all_rel):
                    print(f"{FLRed}Invalid selection: {idx}{CRst}", file=sys.stderr)
                    if noninteractive_choice:
                        return 1
                    continue
                first_token = all_rel[idx]

            script_path = _resolve_with_groups(
                first_token,
                script_dir,
                scripts,
                test_group,
                additional_groups,
                config,
            )
            if script_path is None:
                print(f"{FLRed}Cannot find script: `{first_token}`{CRst}", file=sys.stderr)
                if noninteractive_choice:
                    return 1
                continue
            break

    else:
        # CLI arg provided (not --list)
        assert script_name is not None  # guaranteed by show_list logic
        script_path = _resolve_with_groups(
            script_name,
            script_dir,
            scripts,
            test_group,
            additional_groups,
            config,
        )
        if script_path is None:
            print(f"{FLRed}Cannot find script: `{script_name}`{CRst}", file=sys.stderr)
            return 1

    if os.path.abspath(script_path) == os.path.abspath(__file__):
        print(f"{FLRed}Refusing to run itself: `{script_path}`{CRst}", file=sys.stderr)
        return 1

    sys.argv = [script_path] + remaining_args

    print(f"{FLYellow}Resolved script path:{CRst} {FLGreen}{script_path}{CRst}")

    if script_path.endswith(config.script_types["python"].extension):
        print()
        try:
            target_python = _resolve_conda_python(target_conda_env)
        except RuntimeError as exc:
            print(f"{FLRed}Cannot select target Python:{CRst} {exc}", file=sys.stderr)
            return 1
        print(
            f"{FLCyan}Python target environment:{CRst} "
            f"{FLYellow}{target_conda_env}{CRst}"
        )
        print(f"{FGray}{target_python}{CRst}\n")
        if project_dir not in sys.path:
            sys.path.insert(0, project_dir)
        return run_py_script(script_path, remaining_args, target_python)

    if script_path.endswith(config.script_types["bash"].extension):
        print()
        return run_sh_script(script_path, remaining_args)

    if script_path.endswith(config.script_types["powershell"].extension):
        print()
        return run_ps1_script(script_path, remaining_args)

    ext = os.path.splitext(script_path)[1]
    print(f"{FLRed}Unsupported script type: `{ext}`{CRst}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
