#!/usr/bin/env python3
"""Cross-platform SMART disk info viewer using smartmontools."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from utils import *  # noqa: E402


# ============ smartctl check ============
if not Utils.check_commands(CmdCheck("smartctl", hints={
    "windows": f"{FGray}scoop install smartmontools{CRst}",
    "macos": f"{FGray}brew install smartmontools{CRst}",
    "linux": f"{FGray}sudo apt install smartmontools{CRst}",
})):
    sys.exit(1)

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}SMART DISK INFO{CRst}
===============

Usage:
  python {script_name}                list SMART-capable disks and view details
  python {script_name} --help         show this help

{FLYellow}Description:{CRst}
  Cross-platform SMART disk health viewer using smartmontools.
  Lists all SMART-capable physical disks and displays detailed
  SMART attributes for the selected disk.

{FLYellow}Requirements:{CRst}
  Windows (scoop):  {FGray}scoop install smartmontools{CRst}
  Linux (apt):      {FGray}sudo apt install smartmontools{CRst}
  macOS (brew):     {FGray}brew install smartmontools{CRst}
""")
    sys.exit(0)


# ============ helpers ============
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _parse_scan_line(line: str) -> tuple[str, str] | None:
    """Parse a smartctl --scan line like '/dev/disk0 -d sat # /dev/disk0'.
    Returns (device_path, device_type) or None."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Split on ' -d ' to get device and type
    parts = line.split(" -d ", 1)
    if len(parts) < 2:
        return None
    dev_path = parts[0].strip()
    rest = parts[1]
    # Type is everything before ' #' or end of string
    dev_type = rest.split(" #", 1)[0].strip() if " #" in rest else rest.strip()
    return dev_path, dev_type


def _get_device_info(dev_path: str, dev_type: str) -> dict:
    """Run smartctl -i on a device and return parsed info."""
    info = {"dev": dev_path, "type": dev_type,
            "model": "", "serial": "", "capacity": "", "firmware": ""}
    r = _run(["smartctl", "-i", dev_path, "-d", dev_type])
    if r.returncode != 0:
        return info
    for line in r.stdout.splitlines():
        line = line.strip()
        if "Model Family:" in line:
            info["model"] = line.split(":", 1)[1].strip()
        elif "Device Model:" in line:
            if not info["model"]:
                info["model"] = line.split(":", 1)[1].strip()
        elif "Model Number:" in line:
            if not info["model"]:
                info["model"] = line.split(":", 1)[1].strip()
        elif "Serial Number:" in line:
            info["serial"] = line.split(":", 1)[1].strip()
        elif "User Capacity:" in line:
            raw = line.split(":", 1)[1].strip()
            # e.g. "1,000,204,886,016 bytes [1.00 TB]"
            bracket = raw.rfind("[")
            if bracket != -1:
                info["capacity"] = raw[bracket:].strip("[]")
            else:
                info["capacity"] = raw.split(",")[0] if "," in raw else raw
        elif "Firmware Version:" in line:
            info["firmware"] = line.split(":", 1)[1].strip()
        elif "Revision:" in line and not info["firmware"]:
            info["firmware"] = line.split(":", 1)[1].strip()
    return info


# ============ main ============
def main():
    print(f"{FLYellow}============ SMART DISK INFO ============={CRst}\n")

    # Scan for SMART devices
    r = _run(["smartctl", "--scan"])
    if r.returncode != 0 or not r.stdout.strip():
        print(f"{FLRed}  No SMART-capable devices found.{CRst}\n")
        sys.exit(1)

    devices: list[dict] = []
    for line in r.stdout.splitlines():
        parsed = _parse_scan_line(line)
        if parsed is None:
            continue
        dev_path, dev_type = parsed
        info = _get_device_info(dev_path, dev_type)
        devices.append(info)

    if not devices:
        print(f"{FLRed}  No SMART-capable devices found.{CRst}\n")
        sys.exit(1)

    # List and select device
    print(f"{FLYellow}  SMART-capable devices:{CRst}\n")
    options = []
    for idx, d in enumerate(devices):
        parts = [f"{FLGreen}{d['dev']}{CRst}"]
        if d["model"]:
            parts.append(f"{FLCyan}{d['model']}{CRst}")
        if d["capacity"]:
            parts.append(f"({d['capacity']})")
        if d["serial"]:
            parts.append(f"{FGray}S/N: {d['serial']}{CRst}")
        if d["firmware"]:
            parts.append(f"{FGray}FW: {d['firmware']}{CRst}")
        options.append(MenuOption([str(idx)], "  ".join(parts), value=idx))
    print()

    idx = Menu.select(options, prompt="Select disk number", separator=False)
    if idx is None:
        sys.exit(0)

    selected = devices[idx]
    print(f"\n{FLCyan}{'─' * 60}{CRst}")
    print(f"{FLYellow}  SMART info for {FLGreen}{selected['dev']}{CRst}"
          f"{FLYellow} ({selected['model']}){CRst}")
    print(f"{FLCyan}{'─' * 60}{CRst}\n")

    # Run smartctl -a and print directly
    result = subprocess.run(
        ["smartctl", "-a", selected["dev"], "-d", selected["type"]],
        capture_output=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
