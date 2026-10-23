"""Shared value types and constants for the private rclone runner.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import dataclasses
import enum
import datetime
from typing import Optional


ENV_SCHEMA_FILE = "ZL_RCLONE_SYNC_SCHEMA_FILE"


ENV_CONFIG_PASSWORD = "ZL_RCLONE_CONFIG_PASSWORD"


UNGROUPED_KEY = "ungrouped"


UNNAMED_TASK = "unnamed"


DISPLAY_WIDTH = 60


MAX_INHERIT_DEPTH = 10


VALID_MODES       = {"sync", "copy", "move", "check", "bisync"}


VALID_PLATFORMS   = {"darwin", "linux", "win32", "macos", "windows"}


VALID_ARCHS       = {"386", "arm", "arm64", "amd64", "x86", "x64"}


VALID_LOG_LEVELS  = {"ERROR", "NOTICE", "INFO", "DEBUG"}


VALID_REMOTE_PATH_TYPES = {"auto", "rclone", "local"}


_DATA_MODES = {"sync", "copy", "move", "bisync"}


_DIRECTIONAL_MODES = {"sync", "copy", "move"}


VALID_DIRECTIONS = {"push", "pull"}


LIST_STRING_FIELDS = {"exclude", "additional-args", "alternative-remote-host"}


STRING_OR_LIST_FIELDS = {"platform", "arch", "computer-name"}


FILE_STAT_TIMEOUT = 15


RCLONE_NOT_FOUND_CODES: set[int] = {3, 4}


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


@dataclasses.dataclass(frozen=True)
class LiteralEndpoint:
    """Literal endpoint path, optionally relative to a named local volume.

    Attributes:
        path: Unexpanded endpoint text; volume paths use forward slashes.
        volume: Alias in local-volumes, or None for an ordinary literal endpoint.
    """

    path: str
    volume: str | None = None


@dataclasses.dataclass(frozen=True)
class LocalVolume:
    """Literal volume selector: exact label and optional case-insensitive filesystem."""

    label: str
    filesystem: str = ""


@dataclasses.dataclass(frozen=True)
class VolumeBinding:
    """Identity captured when resolving a volume-backed endpoint.

    Attributes:
        alias: Configuration alias used in diagnostics.
        selector: Original label/filesystem constraints, rechecked on each run.
        relative: Literal path inside the filesystem.
        root: Canonical mount root chosen before command confirmation.
        device: OS device identity, retained to detect removal or replacement.
        identifiers: Native IDs captured at selection time.
        stat_device: Filesystem identity returned by stat for the mount root.
    """

    alias: str
    selector: LocalVolume
    relative: str
    root: str
    device: str
    identifiers: tuple[tuple[str, str], ...]
    stat_device: int


Endpoint = str | LiteralEndpoint


class CustomHost(enum.StrEnum):
    """Backend whose path2 address may be overridden in an interactive run."""

    SFTP = "sftp"
    WEBDAV = "webdav"


@dataclasses.dataclass(frozen=True)
class PathPairConfig:
    """One YAML path object before template expansion or device discovery.

    Attributes:
        path1: Local/source endpoint in the configured push direction.
        path2: Second endpoint, possibly an rclone remote or local volume.
        custom_host: Optional interactive address prompt, attached to this pair.
    """

    path1: Endpoint
    path2: Endpoint
    custom_host: CustomHost | None = None

    @property
    def endpoints(self) -> tuple[Endpoint, Endpoint]:
        """Return the two configured endpoints in YAML order."""
        return self.path1, self.path2


@dataclasses.dataclass(frozen=True)
class ResolvedPathPair:
    """Resolved runtime endpoints with the identities required for safe retries.

    Attributes:
        path1: Resolved first endpoint; no further template expansion is allowed.
        path2: Resolved second endpoint, including any temporary remote override.
        custom_host: Prompt requested by the corresponding configuration object.
        bindings: Optional volume identity for each endpoint, in the same order.
    """

    path1: str
    path2: str
    custom_host: CustomHost | None = None
    bindings: tuple[VolumeBinding | None, VolumeBinding | None] = (None, None)

    @property
    def endpoints(self) -> tuple[str, str]:
        """Return the two execution endpoints in push order."""
        return self.path1, self.path2


_CUSTOM_HOST_FIELDS: dict[str, CustomHost] = {
    "enable-custom-sftp-host": CustomHost.SFTP,
    "enable-custom-webdav-host": CustomHost.WEBDAV,
}
