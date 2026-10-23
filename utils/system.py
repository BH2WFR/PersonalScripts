"""Operating-system integration, privilege, and permission helpers."""

import base64
import ctypes
import importlib
import json
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from enum import StrEnum
from dataclasses import dataclass, field
from typing import cast

from .ansi import *


class LinuxGui(StrEnum):
    """Linux display environments recognized by the launcher."""

    NO_GUI = "no-gui"
    X11 = "x11"
    WAYLAND = "wayland"


_DISK_QUERY_TIMEOUT = 60
_DISK_LINUX_COLUMNS = "NAME,PATH,TYPE,SIZE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS,MODEL,SERIAL,TRAN,RM,RO,PTTYPE,FSAVAIL"


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
        shared_capacity: APFS parent container capacity in bytes, when confirmed.
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
    shared_capacity: int | None = None


@dataclass
class DiskScan:
    """Read-only inventory with explicit partial-result diagnostics.

    Attributes:
        devices: Root devices, including virtual devices exposed by the OS.
        warnings: Failed optional queries or incomplete topology explanations.
    """

    devices: list[DiskInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _disk_record(value: object) -> dict[str, object]:
    """Validate a native JSON/plist mapping at the parser boundary."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected a device information object")
    return cast(dict[str, object], value)


def _disk_records(value: object) -> list[dict[str, object]]:
    """Accept native empty arrays, singleton objects, or arrays of objects."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [_disk_record(value)]
    if not isinstance(value, list):
        raise ValueError("Expected a device information array")
    return [_disk_record(item) for item in cast(list[object], value)]


def _disk_text(value: object) -> str:
    """Normalize optional native scalar text without turning null into an ID."""
    return str(value).strip() if value is not None else ""


def _disk_size(value: object) -> int | None:
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


def _disk_strings(value: object) -> list[str]:
    """Normalize singleton/array text fields and remove absent entries."""
    values = cast(list[object], value) if isinstance(value, list) else [value]
    return list(dict.fromkeys(text for item in values if (text := _disk_text(item))))


def _disk_fields(data: dict[str, object], mapping: dict[str, str]) -> dict[str, str]:
    """Pick named scalar fields without inventing missing values."""
    return {label: value for key, label in mapping.items() if (value := _disk_text(data.get(key)))}


def _disk_run(command: list[str]) -> bytes:
    """Run a bounded read-only query; failures include the native diagnostic."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        result = subprocess.run(command, capture_output=True, timeout=_DISK_QUERY_TIMEOUT, env=environment)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Cannot query {command[0]}: {exc}") from exc
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{command[0]} failed ({result.returncode}): {error}")
    return result.stdout


def _disk_linux_node(data: dict[str, object]) -> DiskInfo:
    """Preserve lsblk dependency trees, including unmounted and stacked devices."""
    node = DiskInfo(
        device=_disk_text(data.get("path")) or f"/dev/{_disk_text(data.get('name'))}",
        kind=_disk_text(data.get("type")), size=_disk_size(data.get("size")),
        free=_disk_size(data.get("fsavail")), label=_disk_text(data.get("label")),
        filesystem=_disk_text(data.get("fstype")),
        mounts=_disk_strings(data.get("mountpoints", data.get("mountpoint"))),
        identifiers=_disk_fields(data, {"serial": "Hardware serial", "uuid": "Filesystem UUID", "partuuid": "Partition UUID"}),
        details=_disk_fields(data, {"model": "Model", "tran": "Transport", "pttype": "Partition table"}),
        children=[_disk_linux_node(child) for child in _disk_records(data.get("children"))],
    )
    for key, label in (("rm", "Removable media"), ("ro", "Read-only")):
        if data.get(key) is not None:
            node.details[label] = "yes" if data[key] in (True, 1, "1") else "no"
    return node


def _disk_scan_linux() -> DiskScan:
    """Query lsblk, with the older single-mountpoint column as a fallback."""
    command = ["lsblk", "--json", "--bytes", "--tree", "--output", _DISK_LINUX_COLUMNS]
    warnings: list[str] = []
    try:
        raw = _disk_run(command)
    except RuntimeError as exc:
        if "unknown column" not in str(exc).lower() or "MOUNTPOINTS" not in str(exc):
            raise
        command[-1] = _DISK_LINUX_COLUMNS.replace("MOUNTPOINTS", "MOUNTPOINT")
        raw = _disk_run(command)
        warnings.append("This lsblk version exposes only one mount point per filesystem.")
    data = _disk_record(json.loads(raw))
    if "blockdevices" not in data:
        raise ValueError("lsblk response has no blockdevices array")
    return DiskScan([_disk_linux_node(node) for node in _disk_records(data["blockdevices"])], warnings)


# Emit explicit properties rather than serializing provider-dependent CIM objects.
# GUID access paths are identities, not evidence of a drive/directory mount.
_DISK_WINDOWS_QUERY = r"""
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


def _disk_windows_node(data: dict[str, object]) -> DiskInfo:
    """Read the explicit Windows helper contract and omit empty optional IDs."""
    return DiskInfo(
        device=_disk_text(data.get("device")), kind=_disk_text(data.get("kind")),
        size=_disk_size(data.get("size")), free=_disk_size(data.get("free")),
        label=_disk_text(data.get("label")), filesystem=_disk_text(data.get("filesystem")),
        mounts=_disk_strings(data.get("mounts")),
        identifiers={k: v for k, raw in sorted(_disk_record(data.get("identifiers", {})).items()) if (v := _disk_text(raw))},
        details={k: v for k, raw in sorted(_disk_record(data.get("details", {})).items()) if (v := _disk_text(raw))},
        children=[_disk_windows_node(child) for child in _disk_records(data.get("children"))],
    )


def _disk_scan_windows() -> DiskScan:
    """Collect Windows Storage topology and supplemental CIM identity fields."""
    executable = shutil.which("pwsh")
    if not executable:
        raise RuntimeError("PowerShell 7 (pwsh) is required for Windows disk discovery.")
    raw = _disk_run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", _DISK_WINDOWS_QUERY])
    data = _disk_record(json.loads(raw.decode("utf-8-sig")))
    if "devices" not in data:
        raise ValueError("PowerShell response has no devices array")
    return DiskScan([_disk_windows_node(node) for node in _disk_records(data["devices"])], _disk_strings(data.get("warnings")))


def _disk_scan_macos() -> DiskScan:
    """Read diskutil topology, enriching every device with its info property list."""
    listing = _disk_record(plistlib.loads(_disk_run(["diskutil", "list", "-plist"])))
    if "AllDisksAndPartitions" not in listing:
        raise ValueError("diskutil response has no AllDisksAndPartitions array")
    result = DiskScan()
    nodes: dict[str, DiskInfo] = {}

    def read_node(entry: dict[str, object], kind: str) -> DiskInfo:
        """Keep list metadata when a device disappears during its info query."""
        identifier = _disk_text(entry.get("DeviceIdentifier"))
        if not identifier:
            raise ValueError("diskutil returned a device without an identifier")
        data = dict(entry)
        try:
            data.update(_disk_record(plistlib.loads(_disk_run(["diskutil", "info", "-plist", identifier]))))
        except (RuntimeError, ValueError, plistlib.InvalidFileException) as exc:
            result.warnings.append(f"{identifier}: details unavailable: {exc}")
        if kind == "disk" and _disk_text(data.get("APFSContainerReference")) == identifier:
            kind = "APFS container"
        identifiers = _disk_fields(data, {"VolumeUUID": "Volume UUID"})
        native_uuid = _disk_text(data.get("DiskUUID"))
        if native_uuid:
            if kind == "partition":
                identifiers["Partition UUID"] = native_uuid
            elif kind == "APFS container":
                identifiers["APFS container UUID"] = native_uuid
            elif native_uuid.casefold() != identifiers.get("Volume UUID", "").casefold():
                # Preserve an otherwise unclassified native ID without calling
                # it a physical partition or assuming it is a volume UUID.
                identifiers["Disk UUID (diskutil)"] = native_uuid
        node = DiskInfo(
            device=_disk_text(data.get("DeviceNode")) or f"/dev/{identifier}", kind=kind,
            size=_disk_size(data.get("TotalSize", data.get("Size"))),
            free=_disk_size(data.get("VolumeFreeSpace")), label=_disk_text(data.get("VolumeName")),
            filesystem=_disk_text(data.get("FilesystemType")), mounts=_disk_strings(data.get("MountPoint")),
            identifiers=identifiers,
            details=_disk_fields(data, {
                "MediaName": "Media name", "BusProtocol": "Transport", "Content": "Content",
                "Internal": "Internal", "RemovableMedia": "Removable media", "VirtualOrPhysical": "Device class",
                "ReadOnlyMedia": "Read-only media", "ReadOnlyVolume": "Read-only volume",
                "Mounted": "Mounted", "APFSContainerReference": "APFS container",
            }),
        )
        nodes[identifier] = node
        for key, child_kind in (("Partitions", "partition"), ("APFSVolumes", "APFS volume")):
            node.children.extend(read_node(child, child_kind) for child in _disk_records(entry.get(key)))
        return node

    result.devices = [read_node(entry, "disk") for entry in _disk_records(listing["AllDisksAndPartitions"])]
    # APFS storage is shared. Keep synthesized containers separate, with explicit
    # physical-store references instead of falsely assigning a single parent.
    if any("apfs" in f"{node.filesystem} {node.details}".lower() for node in nodes.values()):
        try:
            apfs = _disk_record(plistlib.loads(_disk_run(["diskutil", "apfs", "list", "-plist"])))
            for container in _disk_records(apfs.get("Containers")):
                reference = _disk_text(container.get("ContainerReference"))
                node = nodes.get(reference)
                if node is None:
                    node = read_node({"DeviceIdentifier": reference}, "APFS container")
                    result.devices.append(node)
                node.kind = "APFS container"
                container_uuid = _disk_text(container.get("APFSContainerUUID"))
                native_uuid = node.identifiers.get("Disk UUID (diskutil)", "")
                if native_uuid and native_uuid.casefold() == container_uuid.casefold():
                    del node.identifiers["Disk UUID (diskutil)"]
                node.identifiers.update(_disk_fields(container, {"APFSContainerUUID": "APFS container UUID"}))
                ceiling = _disk_size(container.get("CapacityCeiling"))
                if ceiling is not None:
                    node.size = ceiling
                stores = [_disk_text(store.get("DeviceIdentifier")) for store in _disk_records(container.get("PhysicalStores"))]
                node.details["Physical stores"] = ", ".join(stores)
                node.details["Capacity"] = "Shared by APFS volumes; do not sum child capacities"
                for volume in _disk_records(container.get("Volumes")):
                    identifier = _disk_text(volume.get("DeviceIdentifier"))
                    child = nodes.get(identifier)
                    if child is None:
                        child = read_node(volume, "APFS volume")
                        node.children.append(child)
                    child.identifiers.update(_disk_fields(volume, {"APFSVolumeUUID": "Volume UUID"}))
                    native_uuid = child.identifiers.get("Disk UUID (diskutil)", "")
                    if native_uuid and native_uuid.casefold() == child.identifiers.get("Volume UUID", "").casefold():
                        del child.identifiers["Disk UUID (diskutil)"]
                for child in node.children:
                    if child.kind == "APFS volume":
                        child.shared_capacity = node.size
        except (RuntimeError, ValueError, plistlib.InvalidFileException) as exc:
            result.warnings.append(f"APFS topology unavailable: {exc}")
    return result



class System:
    @staticmethod
    def scan_disks() -> DiskScan:
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
                return _disk_scan_windows()
            if sys.platform == "linux":
                return _disk_scan_linux()
            if sys.platform == "darwin":
                return _disk_scan_macos()
        except plistlib.InvalidFileException as exc:
            raise ValueError(f"Invalid diskutil property list: {exc}") from exc
        raise RuntimeError(f"Unsupported disk inventory platform: {sys.platform}")



    @staticmethod
    def get_arch() -> str:
        """Return the normalized machine architecture."""
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return "amd64"
        if machine in ("x86", "i386", "i686"):
            return "386"
        if machine in ("arm64", "aarch64"):
            return "arm64"
        if machine.startswith("arm"):
            return "arm"
        return machine

    @staticmethod
    def get_computer_name() -> str:
        """Return the computer hostname."""
        return socket.gethostname()

    @staticmethod
    def get_os_name() -> str:
        """Return a human-readable operating-system name and version."""
        if sys.platform == "darwin":
            version = platform.mac_ver()[0]
            return f"macOS {version}" if version else "macOS"
        if sys.platform == "linux":
            return f"Linux ({platform.release()})"
        if sys.platform == "win32":
            edition = platform.win32_edition()
            base = f"Windows {platform.release()} {platform.version()}"
            return f"{base} {edition}" if edition else base
        return sys.platform

    @staticmethod
    def get_linux_gui() -> LinuxGui | None:
        """Return the Linux display environment inferred from process variables.

        Returns:
            The detected Wayland, X11, or headless environment on Linux;
            ``None`` on other operating systems. Wayland takes precedence when
            both display variables are present.
        """
        if sys.platform != "linux":
            return None
        if os.environ.get("WAYLAND_DISPLAY"):
            return LinuxGui.WAYLAND
        if os.environ.get("DISPLAY"):
            return LinuxGui.X11
        return LinuxGui.NO_GUI

    @staticmethod
    def is_headless() -> bool:
        """Return True if the environment likely has no GUI/display available."""
        if sys.platform == "darwin":
            return False
        if sys.platform == "linux":
            return System.get_linux_gui() is LinuxGui.NO_GUI
        if sys.platform != "win32":
            return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
        return False

    @staticmethod
    def open_browser_safe(url: str) -> None:
        """Open *url* in the default browser, silently skip on headless systems."""
        if System.is_headless():
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    @staticmethod
    def enable_dpi_awareness() -> None:
        """Enable per-monitor DPI awareness on Windows (no-op on other platforms)."""
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        # Windows 10+ recommended: Per Monitor V2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except Exception:
            pass

        # Win8.1 fallback
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # Older systems fallback
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    @staticmethod
    def is_elevated() -> bool:
        """Check if the current process has administrator/root privileges.

        Returns True on Windows (admin) or macOS/Linux (root). Detection
        failures are treated as non-elevated.
        """
        if sys.platform == "win32":
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            try:
                return os.geteuid() == 0
            except AttributeError:
                return False

    @staticmethod
    def _restart_command() -> list[str]:
        """Return the command that re-launches the current program."""
        executable = os.path.abspath(sys.executable)
        args = sys.argv[1:]
        if getattr(sys, "frozen", False) or "__compiled__" in globals():
            return [executable, *args]
        return [executable, os.path.abspath(sys.argv[0]), *args]

    @staticmethod
    def _elevation_command(
        helper_name: str,
        helper_executable: str,
        restart_command: list[str],
    ) -> list[str]:
        """Wrap a restart command for the selected elevation helper."""
        if sys.platform == "win32" and helper_name == "gsudo":
            return System._windows_gsudo_command(
                helper_executable,
                restart_command,
            )
        return [helper_executable, *restart_command]

    @staticmethod
    def _windows_gsudo_command(
        helper_executable: str,
        restart_command: list[str],
    ) -> list[str]:
        """Build a gsudo command that preserves arbitrary Windows arguments."""
        command_data = {
            "program": restart_command[0],
            "argument_line": subprocess.list2cmdline(restart_command[1:]),
        }
        command_json = json.dumps(command_data, ensure_ascii=False)
        command_payload = base64.b64encode(
            command_json.encode("utf-8"),
        ).decode("ascii")
        bootstrap = (
            "$ProgressPreference = 'SilentlyContinue'\n"
            "$commandJson = [Text.Encoding]::UTF8.GetString("
            "[Convert]::FromBase64String('"
            f"{command_payload}'))\n"
            "$command = ConvertFrom-Json -InputObject $commandJson\n"
            "$startInfo = New-Object System.Diagnostics.ProcessStartInfo\n"
            "$startInfo.FileName = [string]$command.program\n"
            "$startInfo.Arguments = [string]$command.argument_line\n"
            "$startInfo.UseShellExecute = $false\n"
            "$process = [Diagnostics.Process]::Start($startInfo)\n"
            "$process.WaitForExit()\n"
            "exit $process.ExitCode\n"
        )
        encoded_bootstrap = base64.b64encode(
            bootstrap.encode("utf-16le"),
        ).decode("ascii")
        return [
            helper_executable,
            "--direct",
            r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-OutputFormat",
            "Text",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded_bootstrap,
        ]

    @staticmethod
    def restart_elevated() -> None:
        """Re-execute the current script with administrator/root privileges.

        **Must be called at the very beginning of the program**, before any
        output is written to stdout.  On Windows the Win32 API fallback spawns
        a fresh console window that cannot render ANSI escape sequences; any
        prior output will appear garbled or be lost.

        If already elevated, returns immediately.  Does **not** return when
        elevation succeeds — the current process is replaced via ``os.execv``
        or ``sys.exit(0)``.

        Elevation order
            **Linux / macOS** — ``sudo`` only.
            **Windows** — ``gsudo`` → ``sudo`` → Win32 ``ShellExecuteW``
            (last resort; spawns a separate Python console window with no ANSI
            support).  All in-place helpers are called via ``subprocess.run``
            instead of ``os.execv`` to avoid stdin contention.

        Once a helper starts, the parent exits with the child's status instead
        of trying another helper.
        """
        if System.is_elevated():
            return

        restart_command = System._restart_command()

        if sys.platform == "win32":
            # 1) gsudo — in-place elevation, preserves ANSI escapes.
            # 2) sudo  — same-terminal elevation fallback.
            # Use subprocess.run instead of os.execv: scoop's sudo does not
            # properly detach stdin, causing two processes to compete for input
            # and producing doubled keystrokes / cursor glitches.
            failures: list[str] = []
            for name in ("gsudo", "sudo"):
                executable = shutil.which(name)
                if executable is None:
                    failures.append(f"{name}: not found in PATH")
                    continue
                try:
                    result = subprocess.run(
                        System._elevation_command(
                            name,
                            executable,
                            restart_command,
                        ),
                        check=False,
                    )
                except OSError as exc:
                    failures.append(f"{name}: failed to start ({exc})")
                    continue
                raise SystemExit(result.returncode)

            # 3) ShellExecuteW — last resort.  Spawns a fresh console window;
            #    ANSI escape sequences are not carried over.
            sys.stdout.flush()
            print()
            params = subprocess.list2cmdline(restart_command[1:])
            try:
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", restart_command[0], params, None, 1,
                )
            except OSError as exc:
                failures.append(f"Windows UAC: failed to start ({exc})")
            else:
                if ret > 32:
                    sys.exit(0)
                failures.append(f"Windows UAC: ShellExecuteW error {ret}")

            print(f"{FLRed}Elevation failed: {'; '.join(failures)}.{CRst}")
            print(
                f"{FLYellow}Run this script from an Administrator PowerShell "
                f"window and try again.{CRst}"
            )
            sys.exit(1)
        else:
            sudo = shutil.which("sudo")
            if sudo:
                os.execv(
                    sudo,
                    System._elevation_command("sudo", sudo, restart_command),
                )
            print(f"{FLRed}Cannot elevate: sudo not found in PATH.{CRst}")
            sys.exit(1)

    @staticmethod
    def try_restart_elevated() -> bool:
        """Re-launch via a helper that waits for the child to finish.

        **Should be called as early as possible**, before significant output,
        though the in-place helpers (``gsudo`` / ``sudo``) preserve the
        terminal state and are more forgiving than the Win32 API fallback.

        Unlike :meth:`restart_elevated`, this does **not** fall back to
        ``ShellExecuteW`` spawning a new window. Missing helpers and launch
        errors fall through to the next helper. Once a helper starts, a
        non-zero child status returns ``False`` without running the program a
        second time through another helper.

        If already elevated, returns ``True`` immediately so the caller can
        simply proceed.

        Elevation order
            **Linux / macOS** — ``sudo`` only.
            **Windows** — ``gsudo`` → ``sudo`` (both in-place).

        Raises ``SystemExit(0)`` when the child exits successfully.
        Returns ``False`` if no helper could be started or the launched child
        exited with a non-zero code. The caller should continue with reduced
        privileges.
        """
        if System.is_elevated():
            return True

        helpers: list[str] = (
            ["gsudo", "sudo"] if sys.platform == "win32" else ["sudo"]
        )
        restart_command = System._restart_command()

        for name in helpers:
            executable = shutil.which(name)
            if executable is None:
                continue
            try:
                result = subprocess.run(
                    System._elevation_command(
                        name,
                        executable,
                        restart_command,
                    ),
                    check=False,
                )
            except OSError:
                continue
            if result.returncode == 0:
                raise SystemExit(0)
            return False
        return False

    @staticmethod
    def open_with_default_app(path: str) -> None:
        """Open a file or directory with the OS default application."""
        abs_path = os.path.abspath(path)
        if sys.platform == "win32":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", abs_path], check=False)
        else:
            subprocess.run(["xdg-open", abs_path], check=False)

    @staticmethod
    def notify(title: str, body: str) -> None:
        """Send a desktop notification (best-effort, silently fails)."""
        try:
            if sys.platform == "win32":
                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(title, body, duration=5, threaded=True)
                except ImportError:
                    pass
            elif sys.platform == "darwin":
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{body}" with title "{title}"',
                ], check=False, capture_output=True)
            else:
                subprocess.run(["notify-send", title, body], check=False, capture_output=True)
        except Exception:
            pass

    @staticmethod
    def check_macos_accessibility_permission(*, prompt: bool = False) -> bool:
        """Return whether this process has macOS Accessibility access.

        When prompt is true, macOS may show its native authorization prompt.
        Non-macOS platforms return True.
        """
        if sys.platform != "darwin":
            return True
        try:
            # These symbols are injected dynamically by PyObjC and are absent
            # from its static type stubs, so resolve them at runtime.
            application_services = importlib.import_module("ApplicationServices")
            is_trusted_with_options = getattr(
                application_services,
                "AXIsProcessTrustedWithOptions",
            )
            prompt_option = getattr(
                application_services,
                "kAXTrustedCheckOptionPrompt",
            )
            return bool(is_trusted_with_options({
                prompt_option: prompt,
            }))
        except (ImportError, AttributeError, OSError):
            try:
                framework = ctypes.CDLL(
                    "/System/Library/Frameworks/"
                    "ApplicationServices.framework/ApplicationServices"
                )
                framework.AXIsProcessTrusted.argtypes = []
                framework.AXIsProcessTrusted.restype = ctypes.c_bool
                return bool(framework.AXIsProcessTrusted())
            except (AttributeError, OSError):
                return False

    @staticmethod
    def check_macos_screen_recording_permission(
        *,
        request: bool = False,
    ) -> bool:
        """Return whether this process has macOS Screen Recording access.

        When request is true, macOS may show its native authorization prompt.
        Non-macOS platforms return True.
        """
        if sys.platform != "darwin":
            return True
        try:
            framework = ctypes.CDLL(
                "/System/Library/Frameworks/"
                "CoreGraphics.framework/CoreGraphics"
            )
            function_name = (
                "CGRequestScreenCaptureAccess"
                if request
                else "CGPreflightScreenCaptureAccess"
            )
            check = getattr(framework, function_name)
            check.argtypes = []
            check.restype = ctypes.c_bool
            return bool(check())
        except (AttributeError, OSError):
            return False

    @staticmethod
    def ensure_macos_permissions(
        *,
        accessibility: bool = False,
        screen_recording: bool = False,
        timeout_s: float = 60.0,
        prompt: bool = True,
    ) -> bool:
        """Ensure requested macOS TCC permissions are available.

        System prompts and settings panes still require explicit user approval.
        This method waits up to timeout_s for that approval. Non-macOS
        platforms return True.
        """
        if sys.platform != "darwin":
            return True

        accessibility_ok = (
            not accessibility
            or System.check_macos_accessibility_permission(prompt=prompt)
        )
        screen_recording_ok = (
            not screen_recording
            or System.check_macos_screen_recording_permission(request=prompt)
        )
        if accessibility_ok and screen_recording_ok:
            return True

        missing: list[str] = []
        if not accessibility_ok:
            missing.append("Accessibility (mouse/keyboard control)")
        if not screen_recording_ok:
            missing.append("Screen Recording (screenshot capture)")

        print(f"{FLYellow}============================================{CRst}")
        print(f"{FLYellow}Missing required permissions:{CRst}")
        for item in missing:
            print(f"{FLYellow}   - {item}{CRst}")
        print(f"{FLYellow}Grant them to this terminal or Python executable in:{CRst}")
        print(f"{FLCyan}System Settings -> Privacy & Security{CRst}")
        print(f"{FLYellow}Then return here; permission status will be rechecked.{CRst}")
        print(f"{FLYellow}============================================{CRst}")

        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security"],
            check=False,
            capture_output=True,
        )

        print(f"{FLCyan}Waiting for permissions... (timeout: {timeout_s}s){CRst}")
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            accessibility_ok = (
                not accessibility
                or System.check_macos_accessibility_permission()
            )
            screen_recording_ok = (
                not screen_recording
                or System.check_macos_screen_recording_permission()
            )
            if accessibility_ok and screen_recording_ok:
                print(f"{FLGreen}All permissions granted.{CRst}")
                return True
            time.sleep(1.0)

        print(f"{FLRed}Permissions not granted within timeout.{CRst}")
        return False

    @staticmethod
    def wait_for_macos_screen_capture_approval(
        capture_probe: Callable[[], object],
    ) -> bool:
        """Trigger and wait for macOS direct-screen-capture approval.

        On recent macOS versions, the first direct CoreGraphics capture can
        display a second confirmation dialog even when Screen Recording is
        already granted. There is no reliable public preflight result for that
        dialog, so the user explicitly confirms that it has been handled. The
        probe is run again before this method returns successfully.

        The caller supplies a small, non-persistent capture operation so this
        utility does not depend on a particular screenshot library.
        """
        if sys.platform != "darwin":
            return True

        print(f"{FLCyan}Checking direct screen-capture authorization...{CRst}")
        try:
            capture_probe()
        except Exception as exc:
            print(f"{FLRed}Initial screen-capture probe failed: {exc}{CRst}")
            return False

        print()
        print(f"{FLYellow}If macOS displayed a screen-capture dialog, handle it now.{CRst}")
        print(f"{FLYellow}Click Allow, or grant access in System Settings.{CRst}")
        try:
            input(
                f"{FLCyan}After the dialog is closed and access is granted, "
                f"press Enter to continue...{CRst}"
            )
        except (EOFError, OSError):
            print(f"{FLRed}Cannot wait for permission confirmation on this input.{CRst}")
            return False

        if not System.check_macos_screen_recording_permission():
            print(f"{FLRed}Screen Recording permission is still unavailable.{CRst}")
            return False

        try:
            capture_probe()
        except Exception as exc:
            print(f"{FLRed}Screen-capture verification failed: {exc}{CRst}")
            return False

        print(f"{FLGreen}Screen-capture authorization confirmed.{CRst}")
        return True
