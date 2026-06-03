#!/usr/bin/env python3
"""Cross-platform charger and instantaneous power reader.

Supported platforms:
  - macOS: ioreg AppleSmartBattery
  - Windows: PowerShell CIM/WMI battery classes
  - Linux: /sys/class/power_supply when available
"""

from __future__ import annotations
import json
import os
import plistlib
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from utils import *  # noqa: E402,F403


def print_help() -> None:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
{FLYellow}POWER CURRENT{CRst}
=============

Usage:
  python {script_name}             live update until any key is pressed
  python {script_name} --once      print once and exit
  python {script_name} -v          live update with detailed source fields
  python {script_name} --verbose   live update with detailed source fields
  python {script_name} -i 0.5      set live refresh interval in seconds
  python {script_name} --help      show this help

{FLYellow}Description:{CRst}
  Cross-platform power reader for showing:
    - charger connection state
    - charger rated/negotiated wattage when available
    - adapter input power when available
    - system load power when available
    - battery charge/discharge power when available
    - battery percentage and charging state

{FLYellow}Platform data sources:{CRst}
  macOS   : ioreg -r -c AppleSmartBattery -a
  Windows : Get-CimInstance BatteryStatus / Win32_Battery / Win32_PowerSupply
  Linux   : /sys/class/power_supply

{FLYellow}Notes:{CRst}
  Charger rated wattage is not exposed on all platforms/devices.
  Linux support depends on what the kernel driver exports under power_supply.
""")


def first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
    return None


def first_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes", "1", "online", "charging"):
                return True
            if lowered in ("false", "no", "0", "offline", "discharging"):
                return False
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def format_watts(value: float | None) -> str:
    if value is None:
        return f"{FGray}N/A{CRst}"
    if abs(value) >= 10:
        return f"{value:.1f} W"
    return f"{value:.2f} W"


def format_mv(value: float | None) -> str:
    return f"{FGray}N/A{CRst}" if value is None else f"{value / 1000:.2f} V"


def format_ma(value: float | None) -> str:
    return f"{FGray}N/A{CRst}" if value is None else f"{value / 1000:.2f} A"


def format_percent(value: float | None) -> str:
    return f"{FGray}N/A{CRst}" if value is None else f"{value:.0f}%"


def format_wh(value: float | None) -> str:
    return f"{FGray}N/A{CRst}" if value is None else f"{value / 1000.0:.2f} Wh"


def power_record(
    *,
    platform_name: str,
    connected: bool | None = None,
    charging: bool | None = None,
    discharging: bool | None = None,
    charger_power_w: float | None = None,
    adapter_input_w: float | None = None,
    system_load_w: float | None = None,
    battery_power_w: float | None = None,
    battery_percent: float | None = None,
    battery_design_capacity_mwh: float | None = None,
    battery_full_charge_capacity_mwh: float | None = None,
    details: list[tuple[str, Any]] | None = None,
    sources: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "platform": platform_name,
        "connected": connected,
        "charging": charging,
        "discharging": discharging,
        "charger_power_w": charger_power_w,
        "adapter_input_w": adapter_input_w,
        "system_load_w": system_load_w,
        "battery_power_w": battery_power_w,
        "battery_percent": battery_percent,
        "battery_design_capacity_mwh": battery_design_capacity_mwh,
        "battery_full_charge_capacity_mwh": battery_full_charge_capacity_mwh,
        "details": details or [],
        "sources": sources or [],
    }


# ============ macOS ============
def macos_run_ioreg(class_name: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["ioreg", "-r", "-c", class_name, "-a"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    data = plistlib.loads(proc.stdout)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def macos_collect() -> dict[str, Any]:
    batteries = macos_run_ioreg("AppleSmartBattery")
    if not batteries:
        raise RuntimeError("No AppleSmartBattery entry found.")

    battery = batteries[0]
    adapter = battery.get("AdapterDetails")
    if not isinstance(adapter, dict):
        adapter = {}
    telemetry = battery.get("PowerTelemetryData")
    if not isinstance(telemetry, dict):
        telemetry = {}
    battery_data = battery.get("BatteryData")
    if not isinstance(battery_data, dict):
        battery_data = {}

    charger_w = first_number(adapter.get("Watts"))
    adapter_input_w = first_number(telemetry.get("SystemPowerIn"))
    adapter_input_w = adapter_input_w / 1000.0 if adapter_input_w is not None else first_number(battery_data.get("AdapterPower"))
    system_load_w = first_number(telemetry.get("SystemLoad"))
    system_load_w = system_load_w / 1000.0 if system_load_w is not None else first_number(battery_data.get("SystemPower"))
    battery_power = first_number(telemetry.get("BatteryPower"))
    battery_power_w = abs(battery_power) / 1000.0 if battery_power not in (None, 0) else None
    if battery_power_w is None:
        battery_power_w = abs(first_number(battery_data.get("SystemPower")) or 0) or None

    voltage_mv = first_number(battery.get("AppleRawBatteryVoltage"), battery.get("Voltage"))
    current_ma = first_number(battery.get("InstantAmperage"), battery.get("Amperage"))
    if battery_power_w is None and voltage_mv is not None and current_ma is not None:
        battery_power_w = abs(voltage_mv * current_ma / 1_000_000.0)

    connected = bool(battery.get("ExternalConnected") or battery.get("AppleRawExternalConnected") or adapter)
    charging = bool(battery.get("IsCharging"))

    return power_record(
        platform_name="macOS",
        connected=connected,
        charging=charging,
        discharging=(not connected),
        charger_power_w=charger_w,
        adapter_input_w=adapter_input_w,
        system_load_w=abs(system_load_w) if system_load_w is not None else None,
        battery_power_w=battery_power_w,
        battery_percent=first_number(battery.get("CurrentCapacity")),
        battery_design_capacity_mwh=first_number(battery.get("DesignCapacity")),
        battery_full_charge_capacity_mwh=first_number(
            battery.get("AppleRawMaxCapacity"),
            battery.get("MaxCapacity"),
        ),
        details=[
            ("Adapter name", adapter.get("Name", "N/A")),
            ("Adapter maker", adapter.get("Manufacturer", "N/A")),
            ("Adapter voltage", format_mv(first_number(adapter.get("AdapterVoltage")))),
            ("Adapter current", format_ma(first_number(adapter.get("Current")))),
            ("System voltage in", format_mv(first_number(telemetry.get("SystemVoltageIn")))),
            ("System current in", format_ma(first_number(telemetry.get("SystemCurrentIn")))),
            ("Battery voltage", format_mv(voltage_mv)),
            ("Battery current", format_ma(current_ma)),
        ],
        sources=[
            ("Charger power", "AdapterDetails.Watts"),
            ("Adapter input", "PowerTelemetryData.SystemPowerIn / BatteryData.AdapterPower"),
            ("System load", "PowerTelemetryData.SystemLoad / BatteryData.SystemPower"),
            ("Battery power", "PowerTelemetryData.BatteryPower / BatteryData.SystemPower / Voltage*Current"),
        ],
    )


# ============ Windows ============
def powershell_path() -> str:
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("PowerShell not found.")


def ps_json(script: str) -> Any:
    result = subprocess.run(
        [
            powershell_path(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"PowerShell exit code {result.returncode}")
    text = result.stdout.strip()
    return json.loads(text) if text else None


def ps_available_class(class_name: str, namespace: str = "root/cimv2") -> bool:
    script = (
        f"if (Get-CimClass -Namespace '{namespace}' -ClassName '{class_name}' "
        "{ -ErrorAction SilentlyContinue }) { 'true' } else { 'false' }"
    )
    result = subprocess.run(
        [
            powershell_path(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def windows_collect() -> dict[str, Any]:
    has_power_supply_class = ps_available_class("Win32_PowerSupply")
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$batteryStatus = Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus |
    Select-Object PowerOnline,Charging,Discharging,Voltage,Rate,ChargeRate,DischargeRate,RemainingCapacity,FullChargedCapacity
$batteryFull = Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity |
    Select-Object FullChargedCapacity
$win32Battery = Get-CimInstance -ClassName Win32_Battery |
    Select-Object EstimatedChargeRemaining,BatteryStatus,Status,DesignCapacity,FullChargeCapacity
$powerSupply = $null
if (Get-CimClass -ClassName Win32_PowerSupply -ErrorAction SilentlyContinue) {
  $powerSupply = Get-CimInstance -ClassName Win32_PowerSupply |
      Select-Object Name,DeviceID,Status,TotalOutputPower,MaxOutputPower
}
[pscustomobject]@{
  BatteryStatus = $batteryStatus
  BatteryFull = $batteryFull
  Win32Battery = $win32Battery
  PowerSupply = $powerSupply
} | ConvertTo-Json -Depth 6 -Compress
"""
    data = ps_json(script)
    if not isinstance(data, dict):
        raise RuntimeError("No Windows power data returned.")

    statuses = [x for x in as_list(data.get("BatteryStatus")) if isinstance(x, dict)]
    batteries = [x for x in as_list(data.get("Win32Battery")) if isinstance(x, dict)]
    supplies = [x for x in as_list(data.get("PowerSupply")) if isinstance(x, dict)]
    full_caps = [x for x in as_list(data.get("BatteryFull")) if isinstance(x, dict)]

    status = statuses[0] if statuses else {}
    win_battery = batteries[0] if batteries else {}
    full_cap = full_caps[0] if full_caps else {}
    connected = first_bool(status.get("PowerOnline"))
    charging = first_bool(status.get("Charging"))
    discharging = first_bool(status.get("Discharging"))

    charger_w = None
    supply_name = "N/A"
    for item in supplies:
        value = first_number(item.get("TotalOutputPower"), item.get("MaxOutputPower"))
        if value is not None and value > 0:
            charger_w = value
            supply_name = str(item.get("Name") or item.get("DeviceID") or "PowerSupply")
            break
    if not has_power_supply_class:
        supply_name = "Class unavailable"

    discharge = first_number(status.get("DischargeRate"))
    charge = first_number(status.get("ChargeRate"))
    rate = first_number(status.get("Rate"))
    battery_power_w = None
    if discharge is not None and discharge > 0:
        battery_power_w = discharge / 1000.0
    elif charge is not None and charge > 0:
        battery_power_w = charge / 1000.0
    elif rate is not None and rate != 0:
        battery_power_w = abs(rate) / 1000.0
    elif discharge == 0 or charge == 0 or rate == 0:
        battery_power_w = 0.0

    percent = first_number(win_battery.get("EstimatedChargeRemaining"))
    remaining = first_number(status.get("RemainingCapacity"))
    full = first_number(status.get("FullChargedCapacity"), full_cap.get("FullChargedCapacity"))
    if percent is None and remaining is not None and full:
        percent = remaining / full * 100

    return power_record(
        platform_name="Windows",
        connected=connected,
        charging=charging,
        discharging=discharging,
        charger_power_w=charger_w,
        battery_power_w=battery_power_w,
        battery_percent=percent,
        battery_design_capacity_mwh=first_number(win_battery.get("DesignCapacity")),
        battery_full_charge_capacity_mwh=full,
        details=[
            ("Power supply", supply_name),
            ("Battery voltage", format_mv(first_number(status.get("Voltage")))),
            ("Remaining cap", f"{remaining if remaining is not None else 'N/A'} mWh"),
            ("Full charged cap", f"{full if full is not None else 'N/A'} mWh"),
            ("Win32 status", win_battery.get("Status", "N/A")),
            ("Win32 batt code", win_battery.get("BatteryStatus", "N/A")),
        ],
        sources=[
            ("Charger power", "Win32_PowerSupply.TotalOutputPower/MaxOutputPower"),
            ("Battery power", "BatteryStatus.DischargeRate/ChargeRate/Rate"),
        ],
    )


# ============ Linux ============
def read_sysfs(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def read_sysfs_number(device: Path, *names: str) -> float | None:
    for name in names:
        value = first_number(read_sysfs(device / name))
        if value is not None:
            return value
    return None


def linux_collect() -> dict[str, Any]:
    base = Path("/sys/class/power_supply")
    if not base.is_dir():
        raise RuntimeError("/sys/class/power_supply is not available.")

    devices = [p for p in base.iterdir() if p.is_dir()]
    batteries = [p for p in devices if (read_sysfs(p / "type") or "").lower() == "battery"]
    supplies = [p for p in devices if (read_sysfs(p / "type") or "").lower() in {"mains", "usb", "usb_c", "usb_pd"}]
    if not batteries and not supplies:
        raise RuntimeError("No battery or AC adapter found under /sys/class/power_supply.")

    battery = batteries[0] if batteries else None
    connected = None
    for supply in supplies:
        online = first_number(read_sysfs(supply / "online"))
        if online is not None:
            connected = bool(online)
            if connected:
                break

    charger_power_w = None
    adapter_input_w = None
    supply_name = "N/A"
    for supply in supplies:
        supply_name = supply.name
        power_uw = read_sysfs_number(supply, "power_now", "input_power_now")
        voltage_uv = read_sysfs_number(supply, "voltage_now", "input_voltage_now")
        current_ua = read_sysfs_number(supply, "current_now", "input_current_now")
        if power_uw is not None:
            adapter_input_w = abs(power_uw) / 1_000_000.0
        elif voltage_uv is not None and current_ua is not None:
            adapter_input_w = abs(voltage_uv * current_ua / 1_000_000_000_000.0)
        charger_power_uw = read_sysfs_number(supply, "power_max", "input_power_limit")
        if charger_power_uw is not None:
            charger_power_w = abs(charger_power_uw) / 1_000_000.0
        if adapter_input_w is not None or charger_power_w is not None:
            break

    percent = None
    charging = None
    discharging = None
    battery_power_w = None
    battery_name = "N/A"
    voltage_uv = None
    current_ua = None
    if battery:
        battery_name = battery.name
        status = (read_sysfs(battery / "status") or "").lower()
        charging = status == "charging"
        discharging = status == "discharging"
        percent = read_sysfs_number(battery, "capacity")
        power_uw = read_sysfs_number(battery, "power_now")
        voltage_uv = read_sysfs_number(battery, "voltage_now")
        current_ua = read_sysfs_number(battery, "current_now")
        if power_uw is not None:
            battery_power_w = abs(power_uw) / 1_000_000.0
        elif voltage_uv is not None and current_ua is not None:
            battery_power_w = abs(voltage_uv * current_ua / 1_000_000_000_000.0)

    return power_record(
        platform_name="Linux",
        connected=connected,
        charging=charging,
        discharging=discharging,
        charger_power_w=charger_power_w,
        adapter_input_w=adapter_input_w,
        system_load_w=battery_power_w,
        battery_power_w=battery_power_w,
        battery_percent=percent,
        battery_design_capacity_mwh=read_sysfs_number(
            battery, "energy_full_design", "charge_full_design"
        ) if battery else None,
        battery_full_charge_capacity_mwh=read_sysfs_number(
            battery, "energy_full", "charge_full"
        ) if battery else None,
        details=[
            ("Power supply", supply_name),
            ("Battery device", battery_name),
            ("Battery voltage", "N/A" if voltage_uv is None else f"{voltage_uv / 1_000_000.0:.2f} V"),
            ("Battery current", "N/A" if current_ua is None else f"{current_ua / 1_000_000.0:.2f} A"),
        ],
        sources=[
            ("Charger power", "power_supply power_max/input_power_limit"),
            ("Adapter input", "power_supply power_now or voltage_now*current_now"),
            ("Battery power", "BAT power_now or voltage_now*current_now"),
        ],
    )


def collect_power() -> dict[str, Any]:
    if sys.platform == "darwin":
        return macos_collect()
    if sys.platform == "win32":
        return windows_collect()
    if sys.platform.startswith("linux"):
        return linux_collect()
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def yes_no_text(value: bool | None, yes_color: str = FLGreen) -> str:
    if value is None:
        return f"{FGray}N/A{CRst}"
    return f"{yes_color}yes{CRst}" if value else f"{FGray}no{CRst}"


def build_report(verbose: bool) -> tuple[int, str]:
    try:
        record = collect_power()
    except Exception as exc:
        return 1, f"{FLRed}ERROR: {exc}{CRst}"

    adapter_input_w = record.get("adapter_input_w")
    system_load_w = record.get("system_load_w")
    battery_power_w = record.get("battery_power_w")
    design_capacity_mwh = record.get("battery_design_capacity_mwh")
    full_charge_capacity_mwh = record.get("battery_full_charge_capacity_mwh")

    separator = f"{FLCyan}{'-' * 48}{CRst}"
    lines = [
        f"{FLYellow}=========== POWER CURRENT - {record['platform']} ==========={CRst}",
        separator,
        f"  Charger connected : {yes_no_text(record.get('connected'))}",
        f"  Charger power     : {FLGreen}{format_watts(record.get('charger_power_w'))}{CRst}" if record.get("charger_power_w") is not None else f"  Charger power     : {format_watts(None)}",
        f"  Adapter input     : {FLMagenta}{format_watts(adapter_input_w)}{CRst}" if adapter_input_w is not None else f"  Adapter input     : {format_watts(None)}",
        f"  System load       : {FLMagenta}{format_watts(system_load_w)}{CRst}" if system_load_w is not None else f"  System load       : {format_watts(None)}",
        f"  Battery power     : {FLMagenta}{format_watts(battery_power_w)}{CRst}" if battery_power_w is not None else f"  Battery power     : {format_watts(None)}",
        f"  Battery           : {FLCyan}{format_percent(record.get('battery_percent'))}{CRst}" if record.get("battery_percent") is not None else f"  Battery           : {format_percent(None)}",
        f"  Charging          : {yes_no_text(record.get('charging'))}",
        f"  Discharging       : {yes_no_text(record.get('discharging'), FLYellow)}",
    ]
    if design_capacity_mwh is not None or full_charge_capacity_mwh is not None:
        lines.extend([
            f"  Design capacity   : {format_wh(design_capacity_mwh)}",
            f"  Full charge cap   : {format_wh(full_charge_capacity_mwh)}",
        ])

    if verbose:
        lines.extend(["", f"{FLYellow}Details{CRst}", separator])
        for key, value in record.get("details", []):
            lines.append(f"  {key:<17}: {FLCyan}{value}{CRst}")
        if record.get("sources"):
            lines.extend(["", f"{FLYellow}Sources{CRst}", separator])
            for key, value in record.get("sources", []):
                lines.append(f"  {key:<17}: {FGray}{value}{CRst}")

    return 0, "\n".join(lines)


def print_report(verbose: bool) -> int:
    code, report = build_report(verbose)
    print(report)
    return code


def key_pressed_posix() -> bool:
    return bool(select.select([sys.stdin], [], [], 0)[0])


def live_report(verbose: bool, interval: float) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return print_report(verbose)

    previous_lines = 0
    exit_code = 0
    old_settings = None
    use_msvcrt = False
    msvcrt = None

    if sys.platform == "win32":
        try:
            import msvcrt as imported_msvcrt
            msvcrt = imported_msvcrt
            use_msvcrt = True
        except ImportError:
            pass
    else:
        import termios
        import tty
        old_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            code, report = build_report(verbose)
            exit_code = code
            output = f"{report}\n\n{FGray}Press any key to exit. Refresh interval: {interval:g}s{CRst}"
            if previous_lines:
                print(f"{Cursor.prev_line(previous_lines)}{CEraseDisplayToEnd}", end="")
            print(output)
            previous_lines = output.count("\n") + 1
            sys.stdout.flush()

            start = time.monotonic()
            while time.monotonic() - start < interval:
                if use_msvcrt and msvcrt and msvcrt.kbhit():
                    msvcrt.getch()
                    print()
                    return exit_code
                if not use_msvcrt and key_pressed_posix():
                    sys.stdin.read(1)
                    print()
                    return exit_code
                time.sleep(0.05)
    except KeyboardInterrupt:
        print()
        return exit_code
    finally:
        if os.name != "nt" and old_settings is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)


def parse_args() -> tuple[bool, bool, float, int]:
    verbose = False
    once = False
    interval = 1.0
    args = sys.argv[1:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg in ("-h", "--help"):
            print_help()
            return False, False, interval, 0
        if arg in ("-v", "--verbose"):
            verbose = True
        elif arg == "--once":
            once = True
        elif arg in ("-i", "--interval"):
            idx += 1
            if idx >= len(args):
                print(f"{FLRed}ERROR: {arg} requires a value.{CRst}")
                return verbose, once, interval, 2
            try:
                interval = float(args[idx])
            except ValueError:
                print(f"{FLRed}ERROR: invalid interval: {args[idx]}{CRst}")
                return verbose, once, interval, 2
            if interval <= 0:
                print(f"{FLRed}ERROR: interval must be greater than 0.{CRst}")
                return verbose, once, interval, 2
        else:
            print(f"{FLRed}ERROR: Unknown option: {arg}{CRst}")
            print(f"{FGray}Use --help for usage.{CRst}\n")
            return verbose, once, interval, 2
        idx += 1
    return verbose, once, interval, -1


def main() -> int:
    verbose, once, interval, parse_code = parse_args()
    if parse_code >= 0:
        return parse_code
    if once:
        return print_report(verbose)
    return live_report(verbose, interval)


if __name__ == "__main__":
    sys.exit(main())
