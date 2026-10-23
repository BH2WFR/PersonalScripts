#!/usr/bin/env python3
"""Print connected disks, partitions, volumes, mount points, and native IDs.

Windows uses PowerShell 7 Storage/CIM, Linux uses util-linux lsblk, and macOS
uses diskutil. Includes internal/external and OS-visible virtual devices, plus
unmounted partitions. APFS containers retain physical-store references because
their space is shared. Disk/partition/volume IDs are explicitly distinguished;
device names and labels are not unique persistent identifiers.

Run once, print a tree, and exit. Select ID text directly in your terminal.
There is no clipboard operation, interactive menu, or JSON output. Queries are
read-only, never mount/unlock disks, and never request elevation. Optional query
failures retain partial results with warnings; a failed inventory exits with 1.
Each native query times out after 60 seconds. Hardware can change during a scan.

Requirements:
    Python standard library and project utils; no additional Python packages.
    Windows: PowerShell 7 (pwsh) and Windows Storage/CIM providers.
    Linux: lsblk (util-linux). macOS: built-in diskutil.
    Restricted permissions can hide some metadata; unknown values are not IDs.

Usage:
    python list-disks.py
    python list-disks.py --no-color
    python list-disks.py --help
"""

from dataclasses import dataclass, field
import json
import os
import plistlib
import shutil
import subprocess
import sys
from typing import cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


QUERY_TIMEOUT = 60
LINUX_COLUMNS = "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS,MODEL,SERIAL,TRAN,RM,RO,PTTYPE,FSAVAIL"


@dataclass
class DiskInfo:
    """One disk, partition, filesystem, or virtual block device.

    Attributes:
        device: OS device path or name (not a persistent identity).
        kind: Native device type, such as disk, part, lvm, or APFS container.
        size: Capacity in bytes, or None when unavailable; zero is valid.
        free: Filesystem free/available bytes, or None; not disk unallocated space.
        label: Filesystem label, if reported.
        filesystem: Native filesystem type, if known.
        mounts: Drive roots and directory mount points; excludes volume GUIDs.
        identifiers: Named identifiers, keeping disk, partition, and volume IDs distinct.
        details: Platform-specific descriptive fields, including topology references.
        children: Dependent devices. Shared devices may appear under multiple parents.
    """

    device: str
    kind: str
    size: int | None = None
    free: int | None = None
    label: str = ""
    filesystem: str = ""
    mounts: list[str] = field(default_factory=list)
    identifiers: dict[str, str] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    children: list["DiskInfo"] = field(default_factory=list)


@dataclass
class DiskScan:
    """Read-only inventory with explicit partial-result diagnostics.

    Attributes:
        devices: Root devices, including virtual devices exposed by the OS.
        warnings: Failed optional queries or incomplete topology explanations.
    """

    devices: list[DiskInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _record(value: object) -> dict[str, object]:
    """Validate a native JSON/plist mapping at the parser boundary."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a device information object")
    return cast(dict[str, object], value)


def _records(value: object) -> list[dict[str, object]]:
    """Accept native empty arrays, singleton objects, or arrays of objects."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [_record(value)]
    if not isinstance(value, list):
        raise ValueError("Expected a device information array")
    return [_record(item) for item in cast(list[object], value)]


def _text(value: object) -> str:
    """Normalize optional native scalar text without turning null into an ID."""
    return str(value).strip() if value is not None else ""


def _size(value: object) -> int | None:
    """Read nonnegative native byte counts, preserving unknown and zero."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)):
        try:
            number = int(value)
            return number if number >= 0 else None
        except ValueError:
            pass
    return None


def _strings(value: object) -> list[str]:
    """Normalize singleton/array text fields and remove absent entries."""
    values = cast(list[object], value) if isinstance(value, list) else [value]
    return list(dict.fromkeys(text for item in values if (text := _text(item))))


def _fields(data: dict[str, object], mapping: dict[str, str]) -> dict[str, str]:
    """Pick named scalar fields without inventing missing values."""
    return {label: value for key, label in mapping.items() if (value := _text(data.get(key)))}


def _run(command: list[str]) -> bytes:
    """Run a bounded read-only query; failures include the native diagnostic."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(command, capture_output=True, timeout=QUERY_TIMEOUT, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Cannot query {command[0]}: {exc}") from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{command[0]} failed ({result.returncode}): {error}")
    return result.stdout


def _linux_node(data: dict[str, object]) -> DiskInfo:
    """Preserve lsblk dependency trees, including unmounted and stacked devices."""
    node = DiskInfo(
        device=_text(data.get("path")) or f"/dev/{_text(data.get('name'))}",
        kind=_text(data.get("type")), size=_size(data.get("size")),
        free=_size(data.get("fsavail")), label=_text(data.get("label")),
        filesystem=_text(data.get("fstype")),
        mounts=_strings(data.get("mountpoints", data.get("mountpoint"))),
        identifiers=_fields(data, {"serial": "Hardware serial", "uuid": "Filesystem UUID", "partuuid": "Partition UUID"}),
        details=_fields(data, {"model": "Model", "tran": "Transport", "pttype": "Partition table"}),
        children=[_linux_node(child) for child in _records(data.get("children"))],
    )
    for key, label in (("rm", "Removable media"), ("ro", "Read-only")):
        if data.get(key) is not None:
            node.details[label] = "yes" if data[key] in (True, 1, "1") else "no"
    return node


def _scan_linux() -> DiskScan:
    """Query lsblk, with the older single-mountpoint column as a fallback."""
    command = ["lsblk", "--json", "--bytes", "--tree", "--output", LINUX_COLUMNS]
    warnings: list[str] = []
    try:
        raw = _run(command)
    except RuntimeError as exc:
        if "unknown column" not in str(exc).lower() or "MOUNTPOINTS" not in str(exc):
            raise
        command[-1] = LINUX_COLUMNS.replace("MOUNTPOINTS", "MOUNTPOINT")
        raw = _run(command)
        warnings.append("This lsblk version exposes only one mount point per filesystem.")
    data = _record(json.loads(raw))
    if "blockdevices" not in data:
        raise ValueError("lsblk response has no blockdevices array")
    return DiskScan([_linux_node(node) for node in _records(data["blockdevices"])], warnings)


# Emit explicit properties rather than serializing provider-dependent CIM objects.
# GUID access paths are identities, not evidence of a drive/directory mount.
WINDOWS_QUERY = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$notes = [Collections.Generic.List[string]]::new()
$disks = @(Get-Disk | Sort-Object Number)
$parts = @()
$volumes = @()
$cimVolumes = @()
$physical = @()
try { $parts = @(Get-Partition) } catch { $notes.Add("Partition query failed: $_") }
try { $volumes = @(Get-Volume) } catch { $notes.Add("Volume query failed: $_") }
try { $cimVolumes = @(Get-CimInstance Win32_Volume) } catch { $notes.Add("Volume serial query failed: $_") }
try { $physical = @(Get-CimInstance Win32_DiskDrive) } catch { $notes.Add("Physical disk query failed: $_") }
$seen = @{}
function Read-Volume($v, $accessPaths) {
    $id = [string]$v.Path
    $seen[$id] = $true
    $cv = $cimVolumes | Where-Object { $_.DeviceID -eq $id } | Select-Object -First 1
    $ids = @{ 'Volume GUID path' = $id }
    if ($null -ne $cv -and $null -ne $cv.SerialNumber) {
        $hex = ([uint32]$cv.SerialNumber).ToString('X8')
        $ids['Volume serial'] = $hex.Insert(4, '-')
    }
    $mounts = @($accessPaths | Where-Object { $_ -and $_ -notlike '\\?\Volume{*' })
    if ([int][char]$v.DriveLetter -gt 0) { $mounts += "$($v.DriveLetter):\" }
    @{
        device = $id; kind = 'volume'; size = $v.Size; free = $v.SizeRemaining
        label = [string]$v.FileSystemLabel; filesystem = [string]$v.FileSystemType
        mounts = @($mounts | Select-Object -Unique); identifiers = $ids
        details = @{ 'Health' = [string]$v.HealthStatus; 'Drive type' = [string]$v.DriveType }
    }
}
$nodes = @(
    foreach ($d in $disks) {
        $hw = $physical | Where-Object { $_.Index -eq $d.Number } | Select-Object -First 1
        $children = @(
            foreach ($p in @($parts | Where-Object { $_.DiskNumber -eq $d.Number } | Sort-Object PartitionNumber)) {
                $letter = [string]$p.DriveLetter
                $vs = @($volumes | Where-Object {
                    ($_.Path -and $_.Path -in $p.AccessPaths) -or
                    ([int][char]$p.DriveLetter -gt 0 -and [string]$_.DriveLetter -eq $letter)
                })
                $pids = @{}
                if ($p.Guid) { $pids['Partition GUID'] = [string]$p.Guid }
                @{
                    device = "Disk $($d.Number) / Partition $($p.PartitionNumber)"
                    kind = 'partition'; size = $p.Size; identifiers = $pids
                    mounts = @($p.AccessPaths | Where-Object { $_ -and $_ -notlike '\\?\Volume{*' })
                    details = @{ 'Partition type' = [string]$p.Type; 'Offset (bytes)' = [string]$p.Offset }
                    children = @(foreach ($v in $vs) { Read-Volume $v $p.AccessPaths })
                }
            }
        )
        $ids = @{ 'Hardware serial' = [string]$d.SerialNumber; 'Disk unique ID' = [string]$d.UniqueId }
        if ($d.Guid -and $d.Guid -ne [guid]::Empty) { $ids['Disk GUID'] = [string]$d.Guid }
        if ([string]$d.PartitionStyle -eq 'MBR') { $ids['MBR signature'] = ([uint32]$d.Signature).ToString('X8') }
        @{
            device = "\\.\PHYSICALDRIVE$($d.Number)"; kind = 'disk'; size = $d.Size
            identifiers = $ids; children = $children
            details = @{
                'Model' = [string]$d.FriendlyName; 'Transport' = [string]$d.BusType
                'Partition table' = [string]$d.PartitionStyle; 'Read-only' = [string]$d.IsReadOnly
                'Offline' = [string]$d.IsOffline; 'Health' = [string]$d.HealthStatus
                'Media type' = [string]$hw.MediaType
            }
        }
    }
    foreach ($hw in $physical) {
        if ($hw.Index -notin $disks.Number) {
            $notes.Add("$($hw.DeviceID): Storage topology unavailable (for example, a dynamic disk).")
            @{
                device = [string]$hw.DeviceID; kind = 'disk'; size = $hw.Size
                identifiers = @{ 'Hardware serial' = [string]$hw.SerialNumber }
                details = @{ 'Model' = [string]$hw.Model; 'Transport' = [string]$hw.InterfaceType }
            }
        }
    }
    foreach ($v in $volumes) {
        if (-not $seen.ContainsKey([string]$v.Path)) {
            $node = Read-Volume $v @()
            $node.details['Topology'] = 'No partition association reported'
            $node
        }
    }
)
@{ devices = $nodes; warnings = @($notes) } | ConvertTo-Json -Depth 12 -Compress
"""


def _windows_node(data: dict[str, object]) -> DiskInfo:
    """Read the explicit Windows helper contract and omit empty optional IDs."""
    return DiskInfo(
        device=_text(data.get("device")), kind=_text(data.get("kind")),
        size=_size(data.get("size")), free=_size(data.get("free")),
        label=_text(data.get("label")), filesystem=_text(data.get("filesystem")),
        mounts=_strings(data.get("mounts")),
        identifiers={k: v for k, raw in sorted(_record(data.get("identifiers", {})).items()) if (v := _text(raw))},
        details={k: v for k, raw in sorted(_record(data.get("details", {})).items()) if (v := _text(raw))},
        children=[_windows_node(child) for child in _records(data.get("children"))],
    )


def _scan_windows() -> DiskScan:
    """Collect Windows Storage topology and supplemental CIM identity fields."""
    executable = shutil.which("pwsh")
    if not executable:
        raise RuntimeError("PowerShell 7 (pwsh) is required for Windows disk discovery.")
    raw = _run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_QUERY])
    data = _record(json.loads(raw.decode("utf-8-sig")))
    if "devices" not in data:
        raise ValueError("PowerShell response has no devices array")
    return DiskScan([_windows_node(node) for node in _records(data["devices"])], _strings(data.get("warnings")))


def _scan_macos() -> DiskScan:
    """Read diskutil topology, enriching every device with its info property list."""
    listing = _record(plistlib.loads(_run(["diskutil", "list", "-plist"])))
    if "AllDisksAndPartitions" not in listing:
        raise ValueError("diskutil response has no AllDisksAndPartitions array")
    result = DiskScan()
    nodes: dict[str, DiskInfo] = {}

    def read_node(entry: dict[str, object], kind: str) -> DiskInfo:
        """Keep list metadata when a device disappears during its info query."""
        identifier = _text(entry.get("DeviceIdentifier"))
        if not identifier:
            raise ValueError("diskutil returned a device without an identifier")
        data = dict(entry)
        try:
            data.update(_record(plistlib.loads(_run(["diskutil", "info", "-plist", identifier]))))
        except (RuntimeError, ValueError, plistlib.InvalidFileException) as exc:
            result.warnings.append(f"{identifier}: details unavailable: {exc}")
        node = DiskInfo(
            device=_text(data.get("DeviceNode")) or f"/dev/{identifier}", kind=kind,
            size=_size(data.get("TotalSize", data.get("Size"))),
            free=_size(data.get("VolumeFreeSpace")), label=_text(data.get("VolumeName")),
            filesystem=_text(data.get("FilesystemType")), mounts=_strings(data.get("MountPoint")),
            identifiers=_fields(data, {"VolumeUUID": "Volume UUID", "DiskUUID": "Partition UUID"}),
            details=_fields(data, {
                "MediaName": "Media name", "BusProtocol": "Transport", "Content": "Content",
                "Internal": "Internal", "RemovableMedia": "Removable media", "VirtualOrPhysical": "Device class",
                "ReadOnlyMedia": "Read-only media", "ReadOnlyVolume": "Read-only volume",
                "Mounted": "Mounted", "APFSContainerReference": "APFS container",
            }),
        )
        nodes[identifier] = node
        for key, child_kind in (("Partitions", "partition"), ("APFSVolumes", "APFS volume")):
            node.children.extend(read_node(child, child_kind) for child in _records(entry.get(key)))
        return node

    result.devices = [read_node(entry, "disk") for entry in _records(listing["AllDisksAndPartitions"])]
    # APFS storage is shared. Keep synthesized containers separate, with explicit
    # physical-store references instead of falsely assigning a single parent.
    if any("apfs" in f"{node.filesystem} {node.details}".lower() for node in nodes.values()):
        try:
            apfs = _record(plistlib.loads(_run(["diskutil", "apfs", "list", "-plist"])))
            for container in _records(apfs.get("Containers")):
                reference = _text(container.get("ContainerReference"))
                node = nodes.get(reference)
                if node is None:
                    node = read_node({"DeviceIdentifier": reference}, "APFS container")
                    result.devices.append(node)
                node.kind = "APFS container"
                node.identifiers.update(_fields(container, {"APFSContainerUUID": "APFS container UUID"}))
                stores = [_text(store.get("DeviceIdentifier")) for store in _records(container.get("PhysicalStores"))]
                node.details["Physical stores"] = ", ".join(stores)
                node.details["Capacity"] = "Shared by APFS volumes; do not sum child capacities"
                for volume in _records(container.get("Volumes")):
                    identifier = _text(volume.get("DeviceIdentifier"))
                    child = nodes.get(identifier)
                    if child is None:
                        child = read_node(volume, "APFS volume")
                        node.children.append(child)
                    child.identifiers.update(_fields(volume, {"APFSVolumeUUID": "Volume UUID"}))
        except (RuntimeError, ValueError, plistlib.InvalidFileException) as exc:
            result.warnings.append(f"APFS topology unavailable: {exc}")
    return result


class Disks:
    """Native, read-only disk inventory for terminal inspection."""

    @staticmethod
    def scan() -> DiskScan:
        """Discover connected disks, partitions, volumes, and native identifiers.

        Returns:
            Inventory including unmounted devices and warnings for partial queries.
            Unknown values remain absent. Virtual devices are retained as reported
            by the OS; shared devices can appear in multiple dependency branches.

        Raises:
            RuntimeError: Unsupported platform, missing tool, timeout, or failed scan.
            ValueError: Native output is malformed or lacks its inventory field.

        Side effects:
            Runs read-only OS commands, without elevation, mounting, or printing.
            Each subprocess has a 60-second timeout. Hardware may change during a scan.
        """
        try:
            if sys.platform == "win32":
                return _scan_windows()
            if sys.platform == "linux":
                return _scan_linux()
            if sys.platform == "darwin":
                return _scan_macos()
        except plistlib.InvalidFileException as exc:
            raise ValueError(f"Invalid diskutil property list: {exc}") from exc
        raise RuntimeError(f"Unsupported disk inventory platform: {sys.platform}")



def _display_text(value: str) -> str:
    """Escape terminal controls in device-supplied labels while retaining Unicode."""
    return "".join(
        f"\\u{ord(char):04x}" if ord(char) < 32 or 127 <= ord(char) < 160 else char
        for char in value
    )


def _print_tree(devices: list[DiskInfo], color: bool, prefix: str = "") -> None:
    """Print native topology and full identifiers without truncating long values."""
    for index, node in enumerate(devices):
        last = index == len(devices) - 1
        branch = "`-- " if last else "|-- "
        continuation = "    " if last else "|   "
        heading = f"{_display_text(node.device)} [{_display_text(node.kind)}]"
        capacity = "unknown capacity" if node.size is None else Console.format_size(node.size)
        if color:
            heading_color = FLYellow if node.kind == "disk" else FLCyan
            heading = f"{heading_color}{heading}{CRst}"
        print(f"{prefix}{branch}{heading}  ({capacity})")
        indent = f"{prefix}{continuation}"
        fields: list[tuple[str, str]] = []
        if node.label:
            fields.append(("Label", node.label))
        if node.filesystem:
            fields.append(("Filesystem", node.filesystem))
        if node.mounts:
            fields.extend(("Mount", mount) for mount in node.mounts)
        elif node.filesystem or node.kind in ("volume", "APFS volume"):
            fields.append(("Mount", "(no mount point reported)"))
        if node.free is not None:
            fields.append(("Free/available", Console.format_size(node.free)))
        fields.extend(node.details.items())
        fields.extend(node.identifiers.items())
        for name, value in fields:
            field_name = _display_text(name)
            field_value = _display_text(value)
            if color:
                field_name = f"{FGray}{field_name}{CRst}"
                if name in node.identifiers or (name == "Mount" and node.mounts):
                    field_value = f"{FLGreen}{field_value}{CRst}"
            print(f"{indent}  {field_name}: {field_value}")
        if node.children:
            _print_tree(node.children, color, indent)


def main() -> int:
    """Print help or a disk inventory and return its exit status.

    Returns:
        0 for a successful or partial inventory (including no disks), 1 for a
        failed scan, or 2 for invalid arguments.

    Side effects:
        Reads native disk information and prints the tree to stdout; diagnostics
        go to stderr. No prompts, clipboard writes, mounting, or file writes.
    """
    # ── help and arguments ──────────────────────────
    if "--help" in sys.argv or "-h" in sys.argv:
        Console.print_banner("LIST DISKS")
        print("""
Usage:
  python list-disks.py [--no-color]

Description:
  Print disks -> partitions -> volumes, mount points/drive letters, labels,
  capacities, filesystems, and full native IDs for terminal text selection.
  Includes internal/external disks, unmounted partitions, and virtual devices
  visible to the OS. Linux shows block dependencies (including LVM/RAID).
  macOS shows synthesized APFS containers with physical-store references.
  Shared filesystem capacities must not be added together.
  Reads information only; does not mount, unlock, elevate, or modify disks.
  Prints once and exits; no menu, clipboard integration, or JSON output.

Options:
  --no-color  Disable ANSI colors (also disabled when stdout is redirected).
  --help, -h  Show help without scanning.

Requirements:
  No additional Python packages beyond project utils.
  Windows: PowerShell 7 (pwsh), Storage/CIM providers.
  Linux: lsblk from util-linux. macOS: built-in diskutil.
  Some metadata may be unavailable without sufficient OS permissions.
  Dynamic disk topology may be incomplete on Windows; warnings explain gaps.
  Each native query has a 60-second timeout.

Identifiers:
  Hardware serial identifies a disk; UUID/GUID/serial fields identify the
  indicated partition, container, or volume. They are different namespaces.
  Device paths, drive letters, and labels can change or be duplicated.
  Unknown IDs are omitted; zero free space is displayed as zero.
""")
        return 0
    invalid = [arg for arg in sys.argv[1:] if arg != "--no-color"]
    if invalid:
        print(f"Unknown arguments: {' '.join(invalid)}. Use --help.", file=sys.stderr)
        return 2

    # ── inventory and display ───────────────────────
    color = sys.stdout.isatty() and "--no-color" not in sys.argv
    title = f"DISK INVENTORY - {System.get_os_name()}"
    print(f"{FLYellow}{title}{CRst}" if color else title)
    try:
        scan = Disks.scan()
    except (RuntimeError, ValueError) as exc:
        print(f"Disk scan failed: {_display_text(str(exc))}", file=sys.stderr)
        return 1
    for warning in scan.warnings:
        print(f"Warning: {_display_text(warning)}", file=sys.stderr)
    if not scan.devices:
        print("No disks reported by the operating system.")
        return 0
    _print_tree(scan.devices, color)
    print("\nIDs are printed in full for terminal selection. Missing fields were not reported by the OS.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
