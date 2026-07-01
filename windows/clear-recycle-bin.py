#!/usr/bin/env python3
"""Clear Windows Recycle Bin on all drives, with forceful fallback for stuck items.

Use case:
    OneDrive "always keep on device" folders may not be fully removed by the
    normal shell API.  This tool first empties via ``SHEmptyRecycleBinW`` and
    then walks ``$Recycle.Bin`` directly for any drives that still have content.
"""

import os
import sys
import ctypes
import stat as _stat
import string
import shutil
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402

# ============ platform guard ============
if sys.platform != "win32":
    Utils.print_error_and_exit(
        f"This script only runs on Windows.  Current platform: {sys.platform}"
    )

# ============ constants ============
SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI  = 0x00000002
SHERB_NOSOUND       = 0x00000004

_DRIVE_FIXED     = 3
_DRIVE_REMOVABLE = 2

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_INVALID_FILE_ATTRIBUTES      = 0xFFFFFFFF

_kernel32 = ctypes.windll.kernel32
_shell32  = ctypes.windll.shell32

_shell32.SHEmptyRecycleBinW.argtypes = [
    ctypes.c_void_p,
    ctypes.c_wchar_p,
    ctypes.c_uint,
]
_shell32.SHEmptyRecycleBinW.restype = ctypes.c_long


# ============ helpers ============
def _get_drive_type(drive_root: str) -> int:
    return _kernel32.GetDriveTypeW(drive_root + "\\")


def get_available_drives() -> list[str]:
    """Fixed / removable drive letters that actually exist (e.g. ``['C:', 'D:']``)."""
    drives: list[str] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:"
        if not os.path.exists(root + "\\"):
            continue
        if _get_drive_type(root) in (_DRIVE_FIXED, _DRIVE_REMOVABLE):
            drives.append(root)
    return drives


def _is_reparse_point(path: str) -> bool:
    """True when *path* is a junction, symlink, or other reparse point.

    Uses the Win32 ``GetFileAttributesW`` API (the canonical check on Windows)
    with ``os.path.islink()`` as a fallback.
    """
    try:
        attrs = _kernel32.GetFileAttributesW(path)
        if attrs != _INVALID_FILE_ATTRIBUTES:
            return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        pass
    # Fallback: os.path.islink() covers symlinks and symlinkd on Windows.
    return os.path.islink(path)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _count_tree_without_following_reparse(path: str) -> tuple[int, int, int]:
    """Count files/folders under *path* without descending into reparse dirs."""
    files = folders = total = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                full = entry.path
                try:
                    if entry.is_dir(follow_symlinks=False):
                        folders += 1
                        if not _is_reparse_point(full):
                            sub_files, sub_folders, sub_total = (
                                _count_tree_without_following_reparse(full)
                            )
                            files += sub_files
                            folders += sub_folders
                            total += sub_total
                    else:
                        total += os.lstat(full).st_size
                        files += 1
                except OSError:
                    pass
    except PermissionError:
        pass
    return (files, folders, total)


# ============ scan ============
def _count_recycle_bin(drive: str) -> tuple[int, int, int]:
    """Return ``(files, folders, total_bytes)`` for *drive*'s recycle bin.

    Returns ``(-1, -1, -1)`` when the recycle bin directory cannot be accessed
    (e.g. permission denied).

    Uses ``os.lstat`` to avoid following symlinks when computing file sizes.
    """
    recycle = os.path.join(drive + "\\", "$Recycle.Bin")
    if not os.path.isdir(recycle):
        return (0, 0, 0)

    files = folders = total = 0
    try:
        items = os.listdir(recycle)
    except PermissionError:
        return (-1, -1, -1)

    for name in items:
        full = os.path.join(recycle, name)
        if not os.path.isdir(full):
            continue
        if not name.upper().startswith("S-1-"):
            continue  # skip desktop.ini or other non-SID entries
        sub_files, sub_folders, sub_total = _count_tree_without_following_reparse(full)
        files += sub_files
        folders += sub_folders
        total += sub_total

    return (files, folders, total)


# ============ Phase 1 – normal empty via shell API ============
def _empty_recycle_bin_api(drive: Optional[str] = None) -> int:
    """Call ``SHEmptyRecycleBinW``; return the HRESULT (0 = S_OK)."""
    root = ctypes.c_wchar_p(drive + "\\") if drive else None
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    return _shell32.SHEmptyRecycleBinW(None, root, flags)


# ============ Phase 2 – forceful cleanup ============
def _force_delete(path: str) -> bool:
    """Delete a file or directory tree **without** following reparse points.

    - Junctions, symlinks, and other reparse points are deleted **in-place**
      (the link itself, never the target).
    - Read-only items are made writable before retrying.
    """
    try:
        if _is_reparse_point(path):
            # Delete the link / junction itself — NEVER follow to the target.
            try:
                os.rmdir(path)
            except OSError:
                os.unlink(path)
            return True

        if os.path.isdir(path):
            def _on_error(_func, p, _exc_info):
                try:
                    os.chmod(p, _stat.S_IWRITE)
                    _func(p)
                except Exception:
                    pass
            shutil.rmtree(path, onerror=_on_error)
        else:
            try:
                os.unlink(path)
            except PermissionError:
                os.chmod(path, _stat.S_IWRITE)
                os.unlink(path)
        return True
    except OSError:
        return False


def _forceful_clear_contents(path: str) -> tuple[int, int, int, int]:
    """Delete all contents under *path* without descending into reparse dirs."""
    f_ok = f_fail = d_ok = d_fail = 0

    try:
        with os.scandir(path) as entries:
            children = list(entries)
    except PermissionError:
        return (0, 0, 0, 1)
    except OSError:
        return (0, 0, 0, 0)

    for entry in children:
        full = entry.path
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False

        if is_dir:
            if not _is_reparse_point(full):
                sub_counts = _forceful_clear_contents(full)
                f_ok += sub_counts[0]
                f_fail += sub_counts[1]
                d_ok += sub_counts[2]
                d_fail += sub_counts[3]

            if _force_delete(full):
                d_ok += 1
            else:
                d_fail += 1
        else:
            if _force_delete(full):
                f_ok += 1
            else:
                f_fail += 1

    return (f_ok, f_fail, d_ok, d_fail)


def _forceful_clear(drive: str) -> tuple[int, int, int, int]:
    """Directly delete contents under ``$Recycle.Bin`` on *drive*.

    Walks each SID-named folder bottom-up so that children are
    removed before their parents.  SID folders themselves are kept.

    Returns ``(files_ok, files_fail, dirs_ok, dirs_fail)``.
    """
    recycle = os.path.join(drive + "\\", "$Recycle.Bin")
    if not os.path.isdir(recycle):
        return (0, 0, 0, 0)

    f_ok = f_fail = d_ok = d_fail = 0

    try:
        entries = os.listdir(recycle)
    except PermissionError:
        return (0, 0, 0, 1)

    for name in entries:
        sid_dir = os.path.join(recycle, name)
        if not os.path.isdir(sid_dir):
            continue
        if not name.upper().startswith("S-1-"):
            continue

        sub_counts = _forceful_clear_contents(sid_dir)
        f_ok += sub_counts[0]
        f_fail += sub_counts[1]
        d_ok += sub_counts[2]
        d_fail += sub_counts[3]

    return (f_ok, f_fail, d_ok, d_fail)


# ============ main ============
def main() -> int:
    # ── CLI flags ──────────────────────────────────────────────
    force_run = "--force-run" in sys.argv
    sys.argv = [a for a in sys.argv if a != "--force-run"]

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
{FLYellow}CLEAR RECYCLE BIN{CRst}
================

Usage:
  python {script_name}              interactive mode
  python {script_name} --force-run  skip all prompts, auto-confirm
  python {script_name} --help       show this help

{FLYellow}Description:{CRst}
  Empty Recycle Bin across all fixed / removable drives on Windows.

  Phase 1 – normal empty via the shell API (SHEmptyRecycleBinW).
            After this pass the script re-scans each drive so you can
            see whether items were partially removed or remain untouched.

  Phase 2 – for any drive that still has leftover content (e.g. stuck
            OneDrive folders), forcefully deletes items directly from
            $Recycle.Bin.  Junctions and symlinks inside the recycle
            bin are deleted in-place — the link target is never followed.

{FLYellow}Requirements:{CRst}
  Windows only.  Administrator privileges are strongly recommended; the
  script will offer to elevate if not already running elevated.
""")
        return 0

    Utils.print_banner("CLEAR RECYCLE BIN")

    # ── admin check ────────────────────────────────────────────
    if not Utils.is_elevated():
        print(
            f"{FLYellow}This operation may require administrator privileges.{CRst}\n"
        )
        if force_run:
            Utils.restart_elevated()
        else:
            choice = Menu.select(
                [
                    MenuOption(["Y"], "Elevate and continue"),
                    MenuOption(["N"], "Continue without elevation"),
                    MenuOption(["Q"], "Quit"),
                ],
                prompt="Choice",
                default_key="Y",
            )
            if choice == "Q" or choice is None:
                Utils.print_exit_message_and_exit("Cancelled.")
            if choice == "Y":
                Utils.restart_elevated()

    # ── scan ──────────────────────────────────────────────────
    drives = get_available_drives()
    if not drives:
        Utils.print_error_and_exit("No fixed or removable drives found.")

    print(
        f"\n{FLCyan}Scanning recycle bin on {FLYellow}{len(drives)}{FLCyan}"
        f" drive(s) ...{CRst}\n"
    )

    scan: dict[str, tuple[int, int, int]] = {}
    total_files = total_folders = total_size = 0
    inaccessible = 0

    for drive in drives:
        files, folders, size = _count_recycle_bin(drive)
        scan[drive] = (files, folders, size)

        if files < 0:
            print(f"  {FLYellow}{drive}{CRst}  {FLRed}access denied{CRst}")
            inaccessible += 1
        else:
            total_files += files
            total_folders += folders
            total_size += size
            if files or folders:
                detail = (
                    f"{FLCyan}{files}{CRst} files  "
                    f"{FLCyan}{folders}{CRst} folders  "
                    f"{FLCyan}{_format_size(size)}{CRst}"
                )
                print(f"  {FLYellow}{drive}{CRst}  {detail}")
            else:
                print(f"  {FLYellow}{drive}{CRst}  {FGray}empty{CRst}")

    print(
        f"\n  {FLYellow}Total:{CRst}  "
        f"{FLCyan}{total_files}{CRst} files  "
        f"{FLCyan}{total_folders}{CRst} folders  "
        f"{FLCyan}{_format_size(total_size)}{CRst}"
    )

    if total_files == 0 and total_folders == 0:
        if inaccessible:
            print(
                f"\n{FLYellow}No readable recycle-bin contents found, but "
                f"{inaccessible} drive(s) could not be checked.{CRst}"
            )
            return 1
        else:
            print(f"\n{FLGreen}Recycle Bin is already empty on all drives.{CRst}")
            return 0

    # ── confirm ───────────────────────────────────────────────
    if not force_run:
        print()
        choice = Menu.select(
            [
                MenuOption(["Y"], "Empty Recycle Bin on all drives"),
                MenuOption(["N"], "Cancel"),
            ],
            prompt="Proceed",
            default_key="N",
        )
        if choice != "Y":
            Utils.print_exit_message_and_exit("Cancelled.")

    # ── Phase 1 ───────────────────────────────────────────────
    print(f"\n{FLYellow}Phase 1: Normal empty {FGray}(SHEmptyRecycleBinW){CRst}\n")

    phase1_results: dict[str, int] = {}  # drive → HRESULT

    for drive in drives:
        files, folders, _size = scan[drive]
        if files < 0:
            continue  # skip drives that were inaccessible during scan
        if files == 0 and folders == 0:
            continue  # skip drives that showed nothing
        hr = _empty_recycle_bin_api(drive)
        phase1_results[drive] = hr
        if hr == 0:  # S_OK
            print(f"  {FLYellow}{drive}{CRst}  {FLGreen}OK{CRst}")
        else:
            print(f"  {FLYellow}{drive}{CRst}  {FLRed}FAILED  {FGray}(HRESULT 0x{hr & 0xFFFFFFFF:08X}){CRst}")

    # Re-scan to see what actually remains
    print(f"\n{FLCyan}Re-scanning after Phase 1 ...{CRst}\n")

    remaining_drives: list[str] = [
        drive for drive, (files, _folders, _size) in scan.items() if files < 0
    ]
    remaining_total_files = remaining_total_folders = remaining_total_size = 0

    for drive in drives:
        if drive not in phase1_results:
            continue
        files, folders, size = _count_recycle_bin(drive)
        prev_files, prev_folders, _ = scan[drive]

        if files < 0:
            print(f"  {FLYellow}{drive}{CRst}  {FLRed}access denied (cannot verify){CRst}")
            # Treat as failed — we don't know if anything remains.
            remaining_drives.append(drive)
            continue

        delta_files   = prev_files - files
        delta_folders = prev_folders - folders

        if files == 0 and folders == 0:
            status = f"{FLGreen}completely clean{CRst}"
        elif delta_files == 0 and delta_folders == 0:
            status = f"{FLRed}unchanged{CRst}  ({FLCyan}{files}{CRst} files, {FLCyan}{folders}{CRst} folders remain)"
            remaining_drives.append(drive)
            remaining_total_files   += files
            remaining_total_folders += folders
            remaining_total_size    += size
        else:
            status = (
                f"{FLYellow}partial{CRst}  "
                f"{FLGreen}-{delta_files}{CRst} / {FLRed}{files}{CRst} files,  "
                f"{FLGreen}-{delta_folders}{CRst} / {FLRed}{folders}{CRst} folders"
            )
            remaining_drives.append(drive)
            remaining_total_files   += files
            remaining_total_folders += folders
            remaining_total_size    += size

        print(f"  {FLYellow}{drive}{CRst}  {status}")

    if not remaining_drives:
        print(f"\n{FLGreen}All drives cleaned successfully.{CRst}")
        return 0

    print(
        f"\n  {FLYellow}Remaining:{CRst}  "
        f"{FLCyan}{remaining_total_files}{CRst} files  "
        f"{FLCyan}{remaining_total_folders}{CRst} folders  "
        f"{FLCyan}{_format_size(remaining_total_size)}{CRst}"
    )

    # ── Phase 2 confirm ───────────────────────────────────────
    print(
        f"\n{FLCyan}Forceful cleanup will directly delete items from $Recycle.Bin."
        f"\nReparse points (junctions / symlinks) are deleted in-place — "
        f"the link target is never followed.{CRst}"
    )

    if not force_run:
        choice = Menu.select(
            [
                MenuOption(["Y"], "Proceed with forceful cleanup"),
                MenuOption(["N"], "Skip and exit"),
            ],
            prompt="Proceed",
            default_key="N",
        )
        if choice != "Y":
            Utils.print_exit_message_and_exit("Skipped forceful cleanup.")
    else:
        print(f"\n{FLYellow}--force-run: automatically proceeding with Phase 2.{CRst}")

    # ── Phase 2 ───────────────────────────────────────────────
    print(f"\n{FLYellow}Phase 2: Forceful cleanup {FGray}(direct $Recycle.Bin walk){CRst}\n")

    f_total_ok = f_total_fail = d_total_ok = d_total_fail = 0

    for drive in remaining_drives:
        f_ok, f_fail, d_ok, d_fail = _forceful_clear(drive)
        f_total_ok   += f_ok
        f_total_fail += f_fail
        d_total_ok   += d_ok
        d_total_fail += d_fail

        parts: list[str] = []
        if f_ok or d_ok:
            parts.append(f"{FLGreen}{f_ok + d_ok} deleted{CRst}")
        if f_fail or d_fail:
            parts.append(f"{FLRed}{f_fail + d_fail} failed{CRst}")
        detail = ", ".join(parts) if parts else f"{FGray}nothing to delete{CRst}"
        print(f"  {FLYellow}{drive}{CRst}  {detail}")

    print(
        f"\n{FLGreen}Done.{CRst}  "
        f"Forcefully deleted {FLCyan}{f_total_ok + d_total_ok}{CRst} item(s); "
        f"{FLRed}{f_total_fail + d_total_fail}{CRst} remaining failure(s)."
    )

    return 0 if f_total_fail + d_total_fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
