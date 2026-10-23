"""Native inventory fixtures; no real disk access or clipboard operations.

Run: conda run -n base python -m unittest discover -s test -p test_list_disks.py
"""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("list_disks_test_target", ROOT / "tools/filesystem/list-disks.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
inventory = sys.modules["utils.system"]


class InventoryTests(unittest.TestCase):
    """Exercise topology and missing metadata across native output formats."""

    def test_linux_nested_unmounted_and_multiple_mounts(self) -> None:
        raw = {"blockdevices": [{"name": "sda", "path": "/dev/sda", "type": "disk", "size": 4096,
            "serial": "DISK-123", "children": [
                {"path": "/dev/sda1", "type": "part", "size": 2048, "uuid": "FS-123",
                 "partuuid": "PART-123", "label": "测试盘", "fsavail": 0,
                 "mountpoints": ["/mnt/with space", "/srv/bind", None]},
                {"path": "/dev/sda2", "type": "part", "mountpoints": [None], "uuid": "FS-123"}]}]}
        with patch.object(inventory, "_disk_run", return_value=json.dumps(raw).encode()):
            scan = inventory._disk_scan_linux()
        disk = scan.devices[0]
        self.assertEqual(disk.identifiers, {"Hardware serial": "DISK-123"})
        self.assertEqual(len(disk.children), 2)  # Cloned UUIDs must not merge devices.
        part = disk.children[0]
        self.assertEqual(part.mounts, ["/mnt/with space", "/srv/bind"])
        self.assertEqual(part.free, 0)
        self.assertEqual(part.identifiers["Partition UUID"], "PART-123")
        self.assertEqual(disk.children[1].mounts, [])
        self.assertIsNone(disk.children[1].size)

    def test_linux_old_mountpoint_fallback(self) -> None:
        replies = [RuntimeError("lsblk: unknown column: MOUNTPOINTS"),
                   b'{"blockdevices":[{"name":"sda1","mountpoint":"/mnt/backup"}]}']
        with patch.object(inventory, "_disk_run", side_effect=replies) as run:
            scan = inventory._disk_scan_linux()
        self.assertEqual(scan.devices[0].mounts, ["/mnt/backup"])
        self.assertIn("MOUNTPOINT,", run.call_args.args[0][-1])
        self.assertTrue(scan.warnings)

    def test_windows_volume_ids_and_folder_mount(self) -> None:
        node = inventory._disk_windows_node({"device": "Disk 2 / Partition 1", "kind": "partition",
            "identifiers": {"Partition GUID": "partition-guid"}, "children": [{
                "device": "volume-guid-path", "kind": "volume", "size": "2048", "free": 0,
                "mounts": ["C:\\Mounts\\Backup\\"], "label": "BACKUP", "filesystem": "NTFS",
                "identifiers": {"Volume GUID path": "volume-guid-path", "Volume serial": "0000-0000", "Unknown": None}}]})
        volume = node.children[0]
        self.assertEqual(volume.mounts, ["C:\\Mounts\\Backup\\"])
        self.assertEqual(volume.identifiers["Volume serial"], "0000-0000")
        self.assertNotIn("Unknown", volume.identifiers)
        self.assertEqual(volume.free, 0)
        self.assertEqual(volume.size, 2048)

    def test_macos_apfs_and_partial_query(self) -> None:
        listing = {"AllDisksAndPartitions": [
            {"DeviceIdentifier": "disk0", "Partitions": [{"DeviceIdentifier": "disk0s2", "Content": "Apple_APFS"}]},
            {"DeviceIdentifier": "disk3", "APFSVolumes": [{"DeviceIdentifier": "disk3s1", "VolumeName": "Data"}]}]}
        apfs = {"Containers": [{"ContainerReference": "disk3", "APFSContainerUUID": "container-uuid",
            "PhysicalStores": [{"DeviceIdentifier": "disk0s2"}],
            "Volumes": [{"DeviceIdentifier": "disk3s1", "APFSVolumeUUID": "volume-uuid"}]}]}
        def query(command: list[str]) -> bytes:
            if command[1:] == ["list", "-plist"]:
                return plistlib.dumps(listing)
            if command[1] == "apfs":
                return plistlib.dumps(apfs)
            if command[-1] == "disk3s1":
                raise RuntimeError("Device disappeared")
            return plistlib.dumps({"DeviceIdentifier": command[-1], "TotalSize": 4096})
        with patch.object(inventory, "_disk_run", side_effect=query):
            scan = inventory._disk_scan_macos()
        container = scan.devices[1]
        self.assertEqual(container.kind, "APFS container")
        self.assertEqual(container.details["Physical stores"], "disk0s2")
        self.assertEqual(container.identifiers["APFS container UUID"], "container-uuid")
        self.assertEqual(container.children[0].identifiers["Volume UUID"], "volume-uuid")
        self.assertEqual(container.children[0].label, "Data")
        self.assertTrue(scan.warnings)

    def test_display_full_ids_and_terminal_control_escaping(self) -> None:
        identity = "12345678-1234-1234-1234-123456789012"
        node = runner.DiskInfo("/dev/sda", "disk", label="Bad\x1b[2J\nLabel", identifiers={"UUID": identity})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runner._print_tree([node], color=False)
        self.assertIn(identity, output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn("\\u001b", output.getvalue())

    def test_macos_ids_and_shared_capacity_keep_their_actual_scope(self) -> None:
        listing = {"AllDisksAndPartitions": [
            {"DeviceIdentifier": "disk0", "Partitions": [{"DeviceIdentifier": "disk0s2", "Content": "Apple_APFS"}]},
            {"DeviceIdentifier": "disk3", "APFSVolumes": [
                {"DeviceIdentifier": "disk3s1"}, {"DeviceIdentifier": "disk3s2"}]}]}
        info = {
            "disk0": {"TotalSize": 8192},
            "disk0s2": {"DiskUUID": "physical-partition-id", "TotalSize": 4096},
            "disk3": {"DiskUUID": "CONTAINER-ID", "TotalSize": 4096},
            "disk3s1": {"DiskUUID": "VOLUME-ID", "VolumeUUID": "volume-id", "TotalSize": 4096},
            "disk3s2": {"DiskUUID": "OTHER-VOLUME-ID", "TotalSize": 1024},
        }
        apfs = {"Containers": [{"ContainerReference": "disk3", "APFSContainerUUID": "container-id",
            "CapacityCeiling": 4096, "PhysicalStores": [{"DeviceIdentifier": "disk0s2"}],
            "Volumes": [{"DeviceIdentifier": "disk3s1", "APFSVolumeUUID": "volume-id"},
                        {"DeviceIdentifier": "disk3s2", "APFSVolumeUUID": "other-volume-id"}]}]}
        def query(command: list[str]) -> bytes:
            if command[1:] == ["list", "-plist"]:
                return plistlib.dumps(listing)
            if command[1] == "apfs":
                return plistlib.dumps(apfs)
            return plistlib.dumps(info[command[-1]])
        with patch.object(inventory, "_disk_run", side_effect=query):
            scan = inventory._disk_scan_macos()
        self.assertEqual(scan.devices[0].children[0].identifiers, {"Partition UUID": "physical-partition-id"})
        container = scan.devices[1]
        self.assertEqual(container.identifiers, {"APFS container UUID": "container-id"})
        self.assertEqual(container.children[0].identifiers, {"Volume UUID": "volume-id"})
        self.assertEqual(container.children[1].identifiers, {"Volume UUID": "other-volume-id"})
        self.assertEqual(container.children[1].shared_capacity, 4096)
        self.assertEqual(container.children[1].size, 1024)  # Do not overwrite a volume's own reported capacity.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner._print_tree([container], color=False)
        self.assertIn("shared container capacity: 4.0 KB", output.getvalue())
        self.assertIn("Reported filesystem capacity: 1.0 KB", output.getvalue())
        self.assertNotIn("Partition UUID", output.getvalue())

    def test_macos_apfs_failure_does_not_guess_shared_capacity_or_id(self) -> None:
        listing = {"AllDisksAndPartitions": [{"DeviceIdentifier": "disk3", "APFSVolumes": [
            {"DeviceIdentifier": "disk3s1", "Size": 2048, "VolumeUUID": "volume-id", "DiskUUID": "different-id"}]}]}
        def query(command: list[str]) -> bytes:
            if command[1:] == ["list", "-plist"]:
                return plistlib.dumps(listing)
            if command[1] == "apfs":
                raise RuntimeError("APFS query unavailable")
            return plistlib.dumps({"FilesystemType": "apfs"})
        with patch.object(inventory, "_disk_run", side_effect=query):
            scan = inventory._disk_scan_macos()
        volume = scan.devices[0].children[0]
        self.assertEqual(volume.identifiers, {"Volume UUID": "volume-id", "Disk UUID (diskutil)": "different-id"})
        self.assertIsNone(volume.shared_capacity)
        self.assertTrue(scan.warnings)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner._print_tree([volume], color=False)
        self.assertIn("reported filesystem capacity: 2.0 KB", output.getvalue())
        self.assertNotIn("shared container capacity", output.getvalue())

    def test_help_does_not_scan_and_scan_failure_exits_nonzero(self) -> None:
        with patch.object(sys, "argv", ["list-disks.py", "--help"]), patch.object(runner.System, "scan_disks") as scan:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 0)
            scan.assert_not_called()
        with patch.object(sys, "argv", ["list-disks.py"]), patch.object(runner.System, "scan_disks", side_effect=RuntimeError("denied")):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(runner.main(), 1)
            self.assertIn("denied", error.getvalue())

    def test_default_prints_once_without_prompting(self) -> None:
        scan = runner.DiskScan([runner.DiskInfo("/dev/example", "disk", size=4096)])
        with patch.object(sys, "argv", ["list-disks.py"]), patch.object(runner.System, "scan_disks", return_value=scan):
            with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.main(), 0)
        self.assertIn("/dev/example [disk]", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())


if __name__ == "__main__":
    unittest.main()
