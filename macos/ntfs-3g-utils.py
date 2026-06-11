#!/usr/bin/env python3
"""NTFS-3G mount/unmount utility for macOS."""

import os
import sys
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402


# ============ system checks ============
if sys.platform != "darwin":
    print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
    sys.exit(1)

if not Utils.check_commands(CmdCheck("ntfs-3g", hints={
    "macos": f"{FGray}brew install ntfs-3g{CRst}",
})):
    sys.exit(1)

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}NTFS-3G UTILS{CRst}
==============

Usage:
  python {script_name}                interactive NTFS mount manager
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  macOS NTFS disk manager for mounting NTFS partitions with
  read-write support via ntfs-3g (macFUSE).

  Menu options:
    [N] Mount by ntfs-3g    — mount NTFS partition with read-write support
    [S] Mount by system     — mount with macOS built-in read-only driver
    [E] Eject disk          — safely eject the entire disk

{FLYellow}Requirements:{CRst}
  macOS only.
  macOS (brew):     {FGray}brew install ntfs-3g macfuse{CRst}
""")
    sys.exit(0)


# ============ helpers ============
def _run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True)
    return subprocess.run(cmd)


def _get_ntfs_partitions() -> list[dict]:
    """Return list of NTFS partitions with their current mount status."""
    import re

    result = _run(["diskutil", "list"])
    if result.returncode != 0:
        return []

    # Parse diskutil list output for NTFS partitions.
    # Partition lines look like:
    #    1:               Windows_NTFS DC1                     1.0 TB     disk7s1
    #    2:       Microsoft Basic Data DATA                    500 GB     disk4s2
    ntfs_disk_ids: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        m = re.search(r'(disk\d+s\d+)\s*$', stripped)
        if not m:
            continue
        lower = stripped.lower()
        if "windows_ntfs" in lower or "microsoft basic data" in lower:
            ntfs_disk_ids.append(m.group(1))

    partitions: list[dict] = []
    for disk_id in ntfs_disk_ids:
        info = _run(["diskutil", "info", disk_id])
        if info.returncode != 0:
            continue
        info_text = info.stdout

        # Extract volume name, mount point, size
        vol_name = ""
        mount_point = ""
        disk_size = ""
        for iline in info_text.splitlines():
            if "Volume Name:" in iline:
                vol_name = iline.split(":", 1)[1].strip()
            if "Mount Point:" in iline:
                mp = iline.split(":", 1)[1].strip()
                if mp:
                    mount_point = mp
            if "Disk Size:" in iline:
                raw = iline.split(":", 1)[1].strip()
                # Take only the human-readable part before the parentheses
                disk_size = raw.split(" (")[0] if " (" in raw else raw

        # Check mount(8) output for mount type — diskutil may not see non-system mounts.
        mount_result = _run(["mount"])
        mount_type = ""
        mount_point_from_mount = ""
        for mline in mount_result.stdout.splitlines():
            if disk_id in mline:
                # Extract mount point: /dev/disk7s1 on /Volumes/NTFS (fstype, ...)
                parts = mline.split(" on ", 1)
                if len(parts) > 1:
                    mp_and_type = parts[1]
                    mount_point_from_mount = mp_and_type.split(" (", 1)[0].strip()
                    # Extract fstype from parentheses
                    type_part = mp_and_type.split("(", 1)[1] if "(" in mp_and_type else ""
                    mount_type = type_part.split(",")[0].strip() if type_part else ""
                break

        is_ntfs3g = mount_type in ("ntfs-3g", "macfuse")
        if mount_point_from_mount:
            mount_point = mount_point_from_mount

        partitions.append({
            "disk": disk_id,
            "name": vol_name,
            "size": disk_size,
            "mount_point": mount_point,
            "mount_type": mount_type,
            "is_mounted": bool(mount_point),
            "is_ntfs3g": is_ntfs3g,
        })

    return partitions


def _get_disk_display_name(p: dict) -> str:
    """Human-readable display name for a partition."""
    name = p["name"] or p["disk"]
    dev_path = f"/dev/{p['disk']}"
    return f"{FLGreen}{name}{CRst} ({FGray}{dev_path}{CRst}, {FLYellow}{p['size']}{CRst})"


def _mount_status_label(p: dict) -> str:
    """Return colored mount status label like [NTFS-3G], [SYSTEM], [ext4], or unmounted."""
    if p["is_ntfs3g"]:
        return f"{FLGreen}[NTFS-3G]{CRst}"
    if p["is_mounted"]:
        t = p.get("mount_type", "")
        if t == "ntfs":
            return f"{FLCyan}[SYSTEM]{CRst}"
        # Other third-party mount — show the actual fstype
        return f"{FLRed}[{t}]{CRst}" if t else f"{FLCyan}[SYSTEM]{CRst}"
    return f"{FGray}unmounted{CRst}"


def _resolve_mount_dir(base: str) -> str:
    """If base is a mount point, append _2, _3... until finding an unused name.
    Returns the resolved directory path (may not exist yet)."""
    if not os.path.ismount(base):
        return base
    idx = 2
    while True:
        candidate = f"{base}_{idx}"
        if not os.path.ismount(candidate):
            return candidate
        idx += 1


def _ensure_dir(path: str) -> bool:
    if os.path.isdir(path):
        return True
    try:
        _run(["sudo", "mkdir", "-p", path], capture=False)
        print(f"{FGray}  Created directory: {path}{CRst}")
        return True
    except Exception as e:
        print(f"{FLRed}  Failed to create directory: {e}{CRst}")
        return False


# ============ mount (ntfs-3g) ============
def _remount_by_ntfs_3g(partitions: list[dict]) -> bool:
    if not partitions:
        print(f"{FGray}  No NTFS partitions found.{CRst}")
        return False

    # Filter: hide ntfs-3g and other third-party mounts; only show unmounted + system-mounted
    available = [p for p in partitions if not p["is_ntfs3g"]
                 and p.get("mount_type", "") in ("", "ntfs")]
    if not available:
        print(f"{FGray}  No NTFS partitions available for mounting.{CRst}")
        return False

    print(f"\n{FLYellow}  Available NTFS partitions:{CRst}\n")
    for idx, p in enumerate(available):
        status = _mount_status_label(p)
        print(f"    {FLYellow}[{idx}]{CRst} {_get_disk_display_name(p)}  {status}")

    # Select disk
    try:
        choice = input(f"\n{FLYellow}  Select disk number or full path (Enter to cancel): {CRst}").strip()
        if not choice:
            return False
    except EOFError:
        print()
        return False

    selected = None
    if choice.startswith("/dev/"):
        selected = next((p for p in available if f"/dev/{p['disk']}" == choice), None)
        if selected is None:
            print(f"{FLRed}  Invalid or unavailable disk: {choice}{CRst}\n")
            return False
    elif choice.startswith("disk"):
        selected = next((p for p in available if p["disk"] == choice), None)
        if selected is None:
            print(f"{FLRed}  Invalid or unavailable disk: {choice}{CRst}\n")
            return False
    else:
        try:
            idx = int(choice)
            if idx < 0 or idx >= len(available):
                print(f"{FLRed}  Invalid selection.{CRst}\n")
                return False
            selected = available[idx]
        except ValueError:
            print(f"{FLRed}  Invalid input. Enter a number, diskXsY, or /dev/diskXsY path.{CRst}\n")
            return False

    # Choose mount directory (interactive loop until resolved)
    default_dir = "/Volumes/NTFS"
    mount_dir = ""
    while True:
        try:
            dir_choice = input(
                f"{FLYellow}  Mount directory [{default_dir}]: {CRst}"
            ).strip()
        except EOFError:
            print()
            return False

        mount_dir = dir_choice or default_dir
        mount_dir = os.path.abspath(mount_dir)

        if os.path.ismount(mount_dir):
            # Already a mount point — find next available _N and ask user
            alt = _resolve_mount_dir(mount_dir)
            print(f"{FLYellow}  Path already mounted: {mount_dir}{CRst}")
            try:
                use_alt = input(
                    f"{FLYellow}  Use {FLGreen}{alt}{CRst}{FLYellow} instead? (Y/n/Enter new path): {CRst}"
                ).strip().lower()
            except EOFError:
                print()
                return False
            if use_alt in ("y", "yes", ""):
                mount_dir = alt
                break
            elif use_alt in ("n", "no"):
                return False
            # else: loop to let user enter a new path
            continue

        if os.path.isdir(mount_dir):
            # Directory exists but is not a mount point — confirm use
            try:
                use = input(
                    f"{FLYellow}  Directory exists (empty): {FGray}{mount_dir}{CRst}{FLYellow}. Use it? (Y/n): {CRst}"
                ).strip().lower()
            except EOFError:
                print()
                return False
            if use in ("y", "yes", ""):
                break
            elif use in ("n", "no"):
                return False
            continue

        if os.path.exists(mount_dir):
            print(f"{FLRed}  Path exists but is not a directory: {mount_dir}{CRst}")
            continue

        # Path does not exist — ask to create
        try:
            create = input(
                f"{FLYellow}  Directory does not exist. Create {FGray}{mount_dir}{CRst}{FLYellow}? (Y/n): {CRst}"
            ).strip().lower()
        except EOFError:
            print()
            return False
        if create in ("y", "yes", ""):
            break
        elif create in ("n", "no"):
            return False

    # Create directory if needed
    if not os.path.isdir(mount_dir):
        if not _ensure_dir(mount_dir):
            return False

    # Confirmation before mounting
    print(f"\n{FLYellow}  Summary:{CRst}")
    print(f"    Disk:      {FLGreen}{selected['name'] or selected['disk']}{CRst} ({FGray}/dev/{selected['disk']}{CRst})")
    print(f"    Mount to:  {FLGreen}{mount_dir}{CRst}")
    if selected["is_mounted"]:
        print(f"    {FLCyan}Will unmount from macOS default first.{CRst}")
    try:
        confirm = input(f"\n{FLYellow}  Proceed with mount? (Y/n): {CRst}").strip().lower()
    except EOFError:
        print()
        return False
    if confirm not in ("y", "yes", ""):
        print(f"{FGray}  Canceled.{CRst}\n")
        return False

    # If mounted by macOS, unmount first
    if selected["is_mounted"]:
        print(f"{FLYellow}  Unmounting from macOS default mount...{CRst}")
        r = _run(["sudo", "diskutil", "unmount", selected["disk"]], capture=False)
        if r.returncode != 0:
            print(f"{FLRed}  Failed to unmount.{CRst}\n")
            return False

    # Mount
    dev_path = f"/dev/{selected['disk']}"
    print(f"{FLYellow}  Mounting {dev_path} -> {mount_dir} via ntfs-3g...{CRst}")
    r = _run(["sudo", "ntfs-3g", dev_path, mount_dir,
              "-o", "volname=NTFS", "-o", "local", "-o", "allow_other",
              "-o", "auto_xattr"], capture=False)
    if r.returncode == 0:
        print(f"{FLGreen}  -> Mounted {selected['disk']} at {mount_dir}{CRst}\n")
        return True
    else:
        print(f"{FLRed}  -> ntfs-3g mount failed.{CRst}\n")
        return False


# ============ mount (system) ============
def _remount_by_system(partitions: list[dict]) -> bool:
    """Mount via macOS default driver: unmounts ntfs-3g first if needed,
    then mounts with the built-in read-only driver."""
    if not partitions:
        print(f"{FGray}  No NTFS partitions found.{CRst}")
        return False

    # Exclude already system-mounted: no need to "switch to default"
    available = [p for p in partitions if not (p["is_mounted"] and not p["is_ntfs3g"])]
    if not available:
        print(f"{FGray}  All NTFS partitions are already mounted via macOS default.{CRst}")
        return False

    print(f"\n{FLYellow}  NTFS partitions:{CRst}\n")
    for idx, p in enumerate(available):
        status = _mount_status_label(p)
        mp = f"  {FGray}-> {p['mount_point']}{CRst}" if p["mount_point"] else ""
        print(f"    {FLYellow}[{idx}]{CRst} {_get_disk_display_name(p)}  {status}{mp}")

    try:
        choice = input(f"\n{FLYellow}  Select disk (Enter to cancel): {CRst}").strip()
        if not choice:
            return False
    except EOFError:
        print()
        return False

    selected = None
    if choice.startswith("/dev/"):
        selected = next((p for p in available if f"/dev/{p['disk']}" == choice), None)
    elif choice.startswith("disk"):
        selected = next((p for p in available if p["disk"] == choice), None)
    else:
        try:
            idx = int(choice)
            if 0 <= idx < len(available):
                selected = available[idx]
        except ValueError:
            pass

    if selected is None:
        print(f"{FLRed}  Invalid disk: {choice}{CRst}\n")
        return False

    # Already mounted via macOS default — should not happen due to filter
    if selected["is_mounted"] and not selected["is_ntfs3g"]:
        print(f"{FLGreen}  Already mounted via macOS default at {selected['mount_point']}.{CRst}\n")
        return False

    # Unmount from ntfs-3g first if needed
    if selected["is_ntfs3g"]:
        print(f"{FLYellow}  Unmounting ntfs-3g from {selected['mount_point']}...{CRst}")
        r = _run(["sudo", "umount", selected["mount_point"]], capture=False)
        if r.returncode != 0:
            print(f"{FLRed}  -> Unmount failed.{CRst}\n")
            return False

    # Mount with macOS default driver
    print(f"{FLYellow}  Mounting with macOS default driver...{CRst}")
    r = _run(["sudo", "diskutil", "mount", selected["disk"]], capture=False)
    if r.returncode == 0:
        print(f"{FLGreen}  -> Done. {selected['disk']} now mounted read-only via macOS.{CRst}\n")
        return True
    else:
        print(f"{FLRed}  -> Mount failed.{CRst}\n")
        return False


# ============ eject ============
def do_eject(partitions: list[dict]) -> bool:
    """Eject an NTFS partition (unmount and remove the entire disk)."""
    if not partitions:
        print(f"{FGray}  No NTFS partitions found.{CRst}")
        return False

    print(f"\n{FLYellow}  NTFS partitions:{CRst}\n")
    for idx, p in enumerate(partitions):
        status = _mount_status_label(p)
        mp = f"  {FGray}-> {p['mount_point']}{CRst}" if p["mount_point"] else ""
        print(f"    {FLYellow}[{idx}]{CRst} {_get_disk_display_name(p)}  {status}{mp}")

    try:
        choice = input(f"\n{FLYellow}  Select disk to eject (Enter to cancel): {CRst}").strip()
        if not choice:
            return False
    except EOFError:
        print()
        return False

    selected = None
    if choice.startswith("/dev/"):
        selected = next((p for p in partitions if f"/dev/{p['disk']}" == choice), None)
    elif choice.startswith("disk"):
        selected = next((p for p in partitions if p["disk"] == choice), None)
    else:
        try:
            idx = int(choice)
            if 0 <= idx < len(partitions):
                selected = partitions[idx]
        except ValueError:
            pass

    if selected is None:
        print(f"{FLRed}  Invalid disk: {choice}{CRst}\n")
        return False

    try:
        confirm = input(
            f"{FLRed}  Eject {selected['disk']}? This removes the entire disk. (y/N): {CRst}"
        ).strip().lower()
    except EOFError:
        print(f"{FGray}  Canceled.{CRst}\n")
        return False
    if confirm not in ("y", "yes"):
        print(f"{FGray}  Canceled.{CRst}\n")
        return False

    print(f"{FLYellow}  Ejecting {selected['disk']}...{CRst}")
    r = _run(["sudo", "diskutil", "eject", selected["disk"]], capture=False)
    if r.returncode == 0:
        print(f"{FLGreen}  -> Ejected.{CRst}\n")
        return True
    else:
        print(f"{FLRed}  -> Eject failed.{CRst}\n")
        return False


# ============ main ============
_MAIN_OPTIONS = [
    MenuOption(["N"], f"Mount by {FLYellow}ntfs-3g{CRst} (read-write)"),
    MenuOption(["S"], f"Mount by {FLCyan}system{CRst} (read-only)"),
    MenuOption(["E"], "Eject disk"),
    MenuOption(["Q"], "Quit"),
]


def _print_partitions(partitions: list[dict]):
    """Print NTFS partition list with mount status."""
    if not partitions:
        print(f"  {FGray}(no NTFS partitions found){CRst}")
        return
    print()
    for idx, p in enumerate(partitions):
        status = _mount_status_label(p)
        mp = f"  {FGray}-> {p['mount_point']}{CRst}" if p["mount_point"] else ""
        print(f"  {FLYellow}[{FLCyan}{idx}{FLYellow}]{CRst} {_get_disk_display_name(p)}  {status}{mp}")
    print()


def main():
    Utils.print_banner("NTFS-3G UTILS")

    while True:
        partitions = _get_ntfs_partitions()

        print(f"{FLCyan}{'─' * 44}{CRst}")
        _print_partitions(partitions)

        choice = Menu.select(_MAIN_OPTIONS, prompt="Choice")
        if choice is None:
            Utils.print_exit_message("Bye.")
            break

        if choice == "N":
            if _remount_by_ntfs_3g(partitions) is False:
                _pause()
        elif choice == "S":
            if _remount_by_system(partitions) is False:
                _pause()
        elif choice == "E":
            if do_eject(partitions) is False:
                _pause()
            else:
                Utils.print_exit_message("Bye.")
                break
        elif choice == "Q":
            Utils.print_exit_message("Bye.")
            break


def _pause():
    try:
        input(f"{FGray}  Press Enter to continue...{CRst}")
    except EOFError:
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
