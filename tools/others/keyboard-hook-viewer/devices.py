"""Read-only platform input-device enumeration.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
from typing import Any
from .models import InputDevice
_OS = sys.platform


def _enumerate_devices_macos() -> list[InputDevice]:
    try:
        r = subprocess.run(
            ["hidutil", "list", "--ndjson"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        raw_devices = [
            json.loads(line) for line in r.stdout.splitlines() if line.strip()
        ]
    except Exception:
        return []

    result: list[InputDevice] = []
    for raw in raw_devices:
        # A service and its backing device are normally both present.  The
        # device record is the one IOHIDElementGetDevice identifies later.
        if raw.get("type") != "device":
            continue
        usage_page = int(raw.get("PrimaryUsagePage", 0))
        usage = int(raw.get("PrimaryUsage", 0))
        if usage_page == 0x01 and usage == 0x06:
            kind = "KBD"
        elif usage_page == 0x01 and usage == 0x02:
            kind = "MOU"
        else:
            continue
        result.append(InputDevice(
            idx=0,
            name=raw.get("Product", "") or raw.get("Transport", "") or "Unknown",
            kind=kind,
            vendor_id=str(raw.get("VendorID", "")),
            product_id=str(raw.get("ProductID", "")),
            serial=str(raw.get("SerialNumber", "")),
            path=str(raw.get("IORegistryEntryID", "")),
        ))
    return result

def _enumerate_devices_windows() -> list[InputDevice]:
    result: list[InputDevice] = []

    def _run_ps(query: str) -> list[dict[str, Any]]:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", query],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return []
            data = json.loads(r.stdout)
            return [data] if isinstance(data, dict) else data
        except Exception:
            return []

    for kb in _run_ps(
        "Get-CimInstance -ClassName Win32_Keyboard | "
        "Select-Object Name, PNPDeviceID | ConvertTo-Json"
    ):
        result.append(InputDevice(
            idx=0,
            name=str(kb.get("Name", "Unknown Keyboard")),
            kind="KBD", vendor_id="", product_id="", serial="",
            path=str(kb.get("PNPDeviceID", "")),
        ))
    for mou in _run_ps(
        "Get-CimInstance -ClassName Win32_PointingDevice | "
        "Select-Object Name, PNPDeviceID | ConvertTo-Json"
    ):
        result.append(InputDevice(
            idx=0,
            name=str(mou.get("Name", "Unknown Mouse")),
            kind="MOU", vendor_id="", product_id="", serial="",
            path=str(mou.get("PNPDeviceID", "")),
        ))
    return result

def enumerate_devices() -> list[InputDevice]:
    if _OS == "darwin":
        devices = _enumerate_devices_macos()
    elif _OS == "win32":
        devices = _enumerate_devices_windows()
    else:
        devices = []
    for i, d in enumerate(devices):
        d.idx = i
    return devices
