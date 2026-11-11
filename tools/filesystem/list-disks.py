#!/usr/bin/env python3
"""Implementation notes.

System.scan_disks owns native discovery. Preserve partial-scan warnings and
unknown values; keep hardware, partition, container and volume ID namespaces
distinct. Return a nonzero status for failed inventory.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}DISK INVENTORY{CRst}

Show disks, partitions, volumes, mount points, capacities and native IDs read-only.
Unavailable metadata remains unknown; device paths and labels are not unique IDs,
and APFS volumes can share capacity that must not be summed.

{FLYellow}Requirements:{CRst}
  Windows: PowerShell 7 Storage/CIM. Linux: lsblk. macOS: diskutil.
  OS permissions may limit metadata or topology completeness.

{FLYellow}Usage:{CRst}
  python list-disks.py [--no-color]
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


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
        if node.kind == "APFS container":
            capacity = f"container capacity: {capacity}"
        elif node.kind == "APFS volume":
            if node.shared_capacity is not None:
                capacity = f"shared container capacity: {Console.format_size(node.shared_capacity)}"
            else:
                capacity = f"reported filesystem capacity: {capacity}"
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
        if node.shared_capacity is not None and node.size is not None and node.size != node.shared_capacity:
            fields.append(("Reported filesystem capacity", Console.format_size(node.size)))
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
        print(HELP)
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
        scan = System.scan_disks()
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
