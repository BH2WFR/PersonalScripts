"""Literal/template endpoint resolution and mounted-volume identity guards.

Internal module; launch ../rclone-sync.py. Requirements: Python 3.13+, project
utils, and PyYAML for schema loading; rclone/native disk tools only when invoked.
"""

from __future__ import annotations

import os
import copy
import dataclasses
import re
import ntpath
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit
from typing import Optional, TYPE_CHECKING

from . import models
from utils import *

if TYPE_CHECKING:
    from . import schema as schema_ops


def _validate_volume_relative(path: str) -> None:
    """Reject absolute, traversal, and platform-ambiguous volume suffixes."""
    if path.startswith("/") or ntpath.splitdrive(path)[0] or "\\" in path or ".." in path.split("/"):
        raise ValueError("volume path must be relative, use '/', and contain no '..', drive, or UNC prefix")
    if "\x00" in path:
        raise ValueError("volume path cannot contain a NUL character")
    if os.name == "nt" and any(":" in part or part.endswith((" ", ".")) for part in path.split("/") if part not in {"", "."}):
        raise ValueError("volume path cannot use Windows alternate streams or trailing spaces/dots")


def _volume_candidates() -> list[tuple[DiskInfo, bool]]:
    """Read a complete native inventory, retaining read-only ancestry and unique devices."""
    try:
        scan = System.scan_disks()
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"Cannot discover local volumes: {exc}") from exc
    if scan.warnings:
        raise ValueError(f"Local volume discovery is incomplete: {'; '.join(scan.warnings)}")
    candidates: dict[str, tuple[DiskInfo, bool]] = {}

    def visit(node: DiskInfo, inherited_readonly: bool = False) -> None:
        readonly = inherited_readonly or any(
            node.details.get(key, "").casefold() in {"true", "yes", "1"}
            for key in ("Read-only", "Read-only media", "Read-only volume", "Offline")
        )
        if node.label and node.filesystem:
            key = os.path.normcase(node.device)
            if key in candidates:
                previous, previous_readonly = candidates[key]
                if (previous.label, previous.filesystem, previous.identifiers) != (node.label, node.filesystem, node.identifiers):
                    raise ValueError(f"Inconsistent volume metadata for {node.device}")
                previous.mounts = list(dict.fromkeys([*previous.mounts, *node.mounts]))
                candidates[key] = (previous, previous_readonly or readonly)
            else:
                candidates[key] = (copy.deepcopy(node), readonly)
        for child in node.children:
            visit(child, readonly)

    for root in scan.devices:
        visit(root)
    return list(candidates.values())


def _select_volume(
    alias: str, selector: models.LocalVolume, candidates: list[tuple[DiskInfo, bool]],
) -> tuple[DiskInfo, bool, str]:
    """Require one matching volume and one usable mounted filesystem root."""
    matches = [(node, readonly) for node, readonly in candidates
               if node.label == selector.label and
               (not selector.filesystem or node.filesystem.casefold() == selector.filesystem.casefold())]
    if len(matches) != 1:
        devices = ", ".join(node.device for node, _ in matches) or "none"
        raise ValueError(f"Volume '{alias}': expected exactly one match, found {len(matches)} ({devices})")
    node, readonly = matches[0]
    roots = list(dict.fromkeys(os.path.normcase(os.path.abspath(mount)) for mount in node.mounts if os.path.isabs(mount)))
    if len(roots) != 1:
        raise ValueError(f"Volume '{alias}': expected one mount point, found {len(roots)}; mount the volume or resolve ambiguous mounts")
    root = roots[0]
    if not os.path.isdir(root) or not os.path.ismount(root):
        raise ValueError(f"Volume '{alias}': mount point is unavailable or is no longer a filesystem root: {root}")
    return node, readonly, os.path.realpath(root)


def _volume_path(root: str, relative: str) -> str:
    """Resolve a literal suffix inside a mounted volume, rejecting links and nested mounts that escape it."""
    _validate_volume_relative(relative)
    try:
        destination = str(Path(root).joinpath(*relative.split("/")).resolve())
        if os.path.commonpath((root, destination)) != root:
            raise ValueError("resolved path escapes the selected volume")
        ancestor = Path(destination)
        while not ancestor.exists():
            if ancestor.parent == ancestor:
                raise ValueError("no accessible parent for volume path")
            ancestor = ancestor.parent
        if ancestor.stat().st_dev != os.stat(root).st_dev:
            raise ValueError("path enters a different filesystem inside the selected volume")
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot verify volume path: {exc}") from exc
    return destination


def _bind_volume(
    endpoint: models.LiteralEndpoint, definitions: dict[str, models.LocalVolume], candidates: list[tuple[DiskInfo, bool]],
) -> tuple[str, models.VolumeBinding]:
    """Resolve a volume endpoint and freeze its identity for subsequent execution guards."""
    alias = endpoint.volume
    if alias is None or alias not in definitions:
        raise ValueError(f"Unknown local volume alias: {alias}")
    selector = definitions[alias]
    node, _, root = _select_volume(alias, selector, candidates)
    destination = _volume_path(root, endpoint.path)
    try:
        binding = models.VolumeBinding(alias, selector, endpoint.path, root, node.device,
                                tuple(sorted(node.identifiers.items())), os.stat(root).st_dev)
    except OSError as exc:
        raise ValueError(f"Cannot inspect volume '{alias}': {exc}") from exc
    return destination, binding


def resolve_paths(
    task: schema_ops.SyncTask, schema_dir: str, script_dir: str, local_volumes: dict[str, models.LocalVolume] | None = None,
) -> None:
    """Expand all task paths once, applying changes only if every path is valid.

    Args:
        task: Batch configuration whose runtime pairs will be replaced atomically.
        schema_dir: Directory containing the selected YAML schema.
        script_dir: Directory containing this script.
        local_volumes: Validated local-volumes selectors; required by volume objects.

    Raises:
        ValueError: A referenced environment variable or placeholder is
            undefined. The message identifies the YAML field.

    Side effects:
        Stores resolved_paths separately after successful validation. Supports
        $VAR, ${VAR}, %VAR%, $ENV:VAR, ${ENV:VAR}, and the schema_dir,
        script_dir, current_dir placeholders. Substituted values stay literal;
        leading ~ is expanded, but remote/UNC and relative paths stay intact.
        Configured path objects remain unchanged. Literal objects bypass expansion.
        Volume objects resolve mounted local
        filesystems and retain identity bindings; a failed resolution is atomic.
    """
    placeholders = {
        "schema_dir": schema_dir, "script_dir": script_dir,
        "current_dir": os.getcwd(),
    }
    resolved: dict[str, str] = {}
    pairs: list[models.ResolvedPathPair] = []
    needs_volumes = any(isinstance(value, models.LiteralEndpoint) and value.volume is not None
                        for pair in task.paths for value in pair.endpoints)
    candidates = _volume_candidates() if needs_volumes else []
    for index, pair in enumerate(task.paths):
        endpoints: list[str] = []
        pair_bindings: list[models.VolumeBinding | None] = []
        for side, value in enumerate(pair.endpoints):
            binding: models.VolumeBinding | None = None
            try:
                if isinstance(value, models.LiteralEndpoint):
                    if value.volume is not None:
                        endpoint, binding = _bind_volume(value, local_volumes or {}, candidates)
                    else:
                        endpoint = value.path
                else:
                    endpoint = os.path.expanduser(Paths.expand_template(value, os.environ, placeholders))
                endpoints.append(endpoint)
                pair_bindings.append(binding)
            except ValueError as exc:
                raise ValueError(f"paths[{index}].path{side + 1}: {exc}") from exc
            if not endpoints[-1].strip():
                raise ValueError(f"paths[{index}].path{side + 1}: expanded path is empty")
        pairs.append(models.ResolvedPathPair(
            endpoints[0], endpoints[1], pair.custom_host, (pair_bindings[0], pair_bindings[1]),
        ))
        if pair.custom_host is not None:
            if pair_bindings[1] is not None or _extract_remote_host(endpoints[1], task.remote_path_type)[0] is None:
                raise ValueError(f"paths[{index}].path2: custom-host prompts require a named rclone remote")
    for attr in ("local_path", "remote_path", "backup_dir", "log_file"):
        val = getattr(task, attr)
        if val:
            try:
                resolved[attr] = os.path.expanduser(Paths.expand_template(val, os.environ, placeholders))
            except ValueError as exc:
                raise ValueError(f"{attr.replace('_', '-')}: {exc}") from exc
    for attr, val in resolved.items():
        setattr(task, attr, val)
    task.resolved_paths = pairs


def resolved_pairs(task: schema_ops.SyncTask) -> list[models.ResolvedPathPair]:
    """Return runtime pairs, allowing unexpanded plain strings for internal callers.

    Args:
        task: A resolved batch, or an internal batch with plain string endpoints.

    Returns:
        A fresh list; the immutable pairs and their volume bindings are retained.

    Raises:
        ValueError: Literal/volume objects have not yet been resolved.

    Side effects:
        None. Does not expand strings, scan disks, or mutate the configuration.
    """
    if task.resolved_paths:
        return list(task.resolved_paths)
    result: list[models.ResolvedPathPair] = []
    for pair in task.paths:
        if not isinstance(pair.path1, str) or not isinstance(pair.path2, str):
            raise ValueError("Resolve literal/volume endpoints before materializing path pairs")
        result.append(models.ResolvedPathPair(pair.path1, pair.path2, pair.custom_host))
    return result


def path_tasks(task: schema_ops.SyncTask) -> list[schema_ops.SyncTask]:
    """Materialize ordered path pairs with shared settings and runtime endpoints.

    Args:
        task: Batch with resolved runtime pairs and shared transfer options.

    Returns:
        Independent task copies ready for per-pair command generation. Paths
        must already be expanded by resolve_paths(); no expansion is repeated.

    Raises:
        ValueError: No path pairs are configured.
    """
    if not task.paths:
        raise ValueError("Selected sub-task has no path pairs")
    materialized: list[schema_ops.SyncTask] = []
    for pair in resolved_pairs(task):
        materialized.append(dataclasses.replace(
            copy.deepcopy(task), paths=[], resolved_paths=[], local_path=pair.path1, remote_path=pair.path2,
            volume_bindings=pair.bindings,
            remote_path_type="local" if pair.bindings[1] is not None else task.remote_path_type,
        ))
    return materialized


_RCLONE_REMOTE_RE = re.compile(
    r'''^([\w][\w.-]*)(?:,[\w.]+(?:=(?:'(?:[^']|'')*'|"(?:[^"]|"")*"|[^,:'"]*))?)*:'''
)


def _extract_remote_host(
    path: str, remote_path_type: str = "auto"
) -> tuple[Optional[str], Optional[str]]:
    """Extract a rclone remote prefix from *path*.

    Returns ``(full_prefix, host_name)`` for paths like ``remote:/dir``.
    The prefix includes connection-string options, including quoted URLs.
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
    return m.group(0), host


def _replace_path_host(path: str, old_prefix: str, new_prefix: str) -> str:
    """Replace the host prefix in *path*."""
    if path.startswith(old_prefix):
        return new_prefix + path[len(old_prefix):]
    return path


def _validate_volume_endpoints(task: schema_ops.SyncTask, direction: str) -> None:
    """Recheck volume identity, containment, and write eligibility before each command.

    Args:
        task: Materialized task with identity bindings from initial resolution.
        direction: Selected push/pull direction; bisync and move write both sides.

    Raises:
        ValueError: Discovery is incomplete, a volume/mount changed, an endpoint
            escapes its volume, or a write operation would use read-only media.

    Side effects:
        Runs read-only native queries only when the task has bound volumes.
        Does not rebind cached commands to different paths after confirmation.
    """
    if not any(task.volume_bindings):
        return
    candidates = _volume_candidates()
    destination_side = 0 if direction == "pull" else 1
    for side, binding in enumerate(task.volume_bindings):
        if binding is None:
            continue
        node, readonly, root = _select_volume(binding.alias, binding.selector, candidates)
        try:
            changed = (
                root != binding.root or node.device != binding.device or
                tuple(sorted(node.identifiers.items())) != binding.identifiers or
                os.stat(root).st_dev != binding.stat_device
            )
        except OSError as exc:
            raise ValueError(f"Volume '{binding.alias}' became unavailable: {exc}") from exc
        if changed:
            raise ValueError(f"Volume '{binding.alias}' identity or mount changed; select the task again")
        current = _volume_path(root, binding.relative)
        expected = task.local_path if side == 0 else task.remote_path
        if current != expected:
            raise ValueError(f"Volume '{binding.alias}' endpoint changed; select the task again")
        writes = task.mode in {"move", "bisync"} or (task.mode != "check" and side == destination_side)
        if writes and readonly:
            raise ValueError(f"Volume '{binding.alias}' is read-only for the selected action")


def _custom_host_value(value: str, backend: models.CustomHost) -> str:
    """Validate literal address input; never expand variables or inspect credentials.

    SFTP accepts a hostname or IPv4/IPv6 address without a port. WebDAV accepts
    a full HTTP(S) base URL without userinfo, query, or fragment. Raises ValueError
    for invalid input, including whitespace/control characters.
    """
    if not value or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Address must be nonempty and contain no whitespace or control characters")
    if backend is models.CustomHost.WEBDAV:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = (
                parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment and "\\" not in value
                and (port is None or port > 0)
            )
        except ValueError as exc:
            raise ValueError("Invalid WebDAV URL or port") from exc
        if not valid:
            raise ValueError("Enter a complete http(s) base URL without credentials, query, or fragment")
        return value
    # Brackets are accepted for pasted IPv6 addresses, but rclone host omits them.
    host = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    if ":" in host:
        try:
            return str(ipaddress.IPv6Address(host))
        except ValueError as exc:
            raise ValueError("Enter a hostname or IP only; SFTP port stays in the remote configuration") from exc
    try:
        hostname = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid SFTP hostname") from exc
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in hostname.rstrip(".").split(".")
    ):
        raise ValueError("Enter an SFTP hostname or IP only, without scheme, port, or path")
    return hostname


def _host_name_to_prefix(name: str, template_prefix: str) -> str:
    """Build a full path prefix from a host *name* using *template_prefix*
    to preserve the rclone remote separator."""
    return name if name.endswith(':') else name + ':'
