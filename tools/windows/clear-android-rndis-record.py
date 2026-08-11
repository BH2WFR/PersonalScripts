#!/usr/bin/env python3
"""Remove stale Android USB tethering (RNDIS) network records.

Windows stores network connection names and network adapter instances in
separate registry locations. Android USB tethering usually appears as a USB
Remote NDIS device. This script lists all registered network connections,
marks records that look like RNDIS by inspecting adapter metadata, then deletes
the selected records after confirmation.

Requirements:
    - Windows only (winreg)
    - Administrator privileges (HKLM write access)
    - No third-party packages required

Usage:
    python windows/clear-android-rndis-record.py
    python windows/clear-android-rndis-record.py --force
    python windows/clear-android-rndis-record.py --match "Ethernet 2"
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Pattern

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

if sys.platform != "win32":
    Utils.print_error_and_exit(
        f"This script only runs on Windows. Current platform: {sys.platform}"
    )

import winreg  # noqa: E402


NETWORK_CLASS_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"
NETWORK_CONNECTIONS_KEY = (
    rf"SYSTEM\CurrentControlSet\Control\Network\{NETWORK_CLASS_GUID}"
)
NETWORK_ADAPTER_CLASS_KEY = (
    rf"SYSTEM\CurrentControlSet\Control\Class\{NETWORK_CLASS_GUID}"
)

GUID_RE = re.compile(
    r"^\{?[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}?$"
)
RNDIS_RE = re.compile(
    r"remote\s+ndis|rndis|usb\\class_e0&subclass_01&prot_03",
    re.IGNORECASE,
)


@dataclass
class NetworkRecord:
    """Network connection plus its matching network-adapter registry metadata.

    Args:
        guid: Network interface GUID.
        name: Connection display name stored under the Network control key.
        pnp_instance_id: PnP instance ID from the Connection key, when present.
        media_subtype: Raw media subtype value from the Connection key.
        adapter_key_name: Adapter class subkey name, such as ``"0016"``.
        driver_desc: Adapter driver description from the class key.
        device_desc: Adapter device description from the class key.
        matching_device_id: Matching device ID from the class key.
        service: Adapter service name from the class key.
        hardware_ids: Hardware IDs from the class key.
        is_rndis: True when adapter metadata identifies Remote NDIS.
        is_extra_match: True when ``--match`` matches this record.
    """

    guid: str
    name: str
    pnp_instance_id: str
    media_subtype: object
    adapter_key_name: str | None
    driver_desc: str
    device_desc: str
    matching_device_id: str
    service: str
    hardware_ids: tuple[str, ...]
    is_rndis: bool
    is_extra_match: bool

    @property
    def should_delete(self) -> bool:
        """Return True when this record is selected for deletion."""
        return self.is_rndis or self.is_extra_match

    def display_name(self) -> str:
        """Return a human-readable label. Prefers Name, falls back to GUID."""
        return self.name or f"<{self.guid}>"

    @property
    def reason(self) -> str:
        """Return a compact user-facing reason for this record's selection."""
        reasons: list[str] = []
        if self.is_rndis:
            reasons.append("RNDIS")
        if self.is_extra_match:
            reasons.append("--match")
        return "+".join(reasons) if reasons else "-"


def _query_value(key: winreg.HKEYType, name: str, default: object = "") -> object:
    """Read one registry value, returning *default* when it is missing.

    Args:
        key: Open registry key handle.
        name: Value name to read.
        default: Fallback value returned when the value cannot be read.

    Returns:
        The registry value, or *default*.

    Raises:
        No deliberate exceptions. Missing values are treated as defaults.
    """
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def _enum_subkeys(root: int, path: str) -> list[str]:
    """Enumerate direct subkey names under *path*.

    Args:
        root: Registry root handle.
        path: Registry path relative to *root*.

    Returns:
        Direct child subkey names.

    Raises:
        OSError: If *path* cannot be opened.
    """
    names: list[str] = []
    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(root, path, 0, access) as key:
        index = 0
        while True:
            try:
                names.append(winreg.EnumKey(key, index))
                index += 1
            except OSError:
                break
    return names


def _as_text(value: object) -> str:
    """Convert registry values to searchable display text.

    Args:
        value: Registry value of any simple type.

    Returns:
        String representation suitable for regex matching.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value)


def _read_adapter_metadata() -> dict[str, dict[str, object]]:
    """Read network adapter class records keyed by ``NetCfgInstanceId``.

    Returns:
        Mapping of upper-case interface GUID to adapter metadata.

    Raises:
        No deliberate exceptions. Unreadable adapter records are skipped.
    """
    adapters: dict[str, dict[str, object]] = {}
    try:
        subkeys = _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, NETWORK_ADAPTER_CLASS_KEY)
    except OSError:
        return adapters

    for subkey_name in subkeys:
        if not subkey_name.isdigit():
            continue

        path = f"{NETWORK_ADAPTER_CLASS_KEY}\\{subkey_name}"
        try:
            access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
                guid = _as_text(_query_value(key, "NetCfgInstanceId", "")).upper()
                if not GUID_RE.match(guid):
                    continue

                adapters[guid] = {
                    "AdapterKeyName": subkey_name,
                    "DriverDesc": _query_value(key, "DriverDesc", ""),
                    "DeviceDesc": _query_value(key, "DeviceDesc", ""),
                    "MatchingDeviceId": _query_value(key, "MatchingDeviceId", ""),
                    "Service": _query_value(key, "Service", ""),
                    "HardwareID": _query_value(key, "HardwareID", ()),
                }
        except OSError:
            continue

    return adapters


def _matches_any(patterns: list[Pattern[str]], values: list[str]) -> bool:
    """Return True if any regex pattern matches any supplied value.

    Args:
        patterns: Compiled regular expressions.
        values: Searchable text values.

    Returns:
        True when at least one pattern matches.
    """
    return any(pattern.search(value) for pattern in patterns for value in values)


def _is_rndis(values: list[str]) -> bool:
    """Return True when adapter metadata identifies USB Remote NDIS.

    Args:
        values: Searchable adapter and connection metadata.

    Returns:
        True when known RNDIS markers are present.
    """
    return any(RNDIS_RE.search(value) for value in values)


def _read_network_records(match_patterns: list[Pattern[str]]) -> list[NetworkRecord]:
    """Read all registered network connections and mark deletion targets.

    Args:
        match_patterns: Extra user-supplied regexes from ``--match``.

    Returns:
        Network records sorted by display name.

    Raises:
        OSError: If the Network control key cannot be opened.
    """
    adapters = _read_adapter_metadata()
    records: list[NetworkRecord] = []

    for guid in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, NETWORK_CONNECTIONS_KEY):
        if not GUID_RE.match(guid):
            continue

        conn_path = f"{NETWORK_CONNECTIONS_KEY}\\{guid}\\Connection"
        try:
            access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, conn_path, 0, access) as key:
                name = _as_text(_query_value(key, "Name", ""))
                pnp_instance_id = _as_text(_query_value(key, "PnpInstanceID", ""))
                media_subtype = _query_value(key, "MediaSubType", "")
        except OSError:
            continue

        metadata = adapters.get(guid.upper(), {})
        driver_desc = _as_text(metadata.get("DriverDesc", ""))
        device_desc = _as_text(metadata.get("DeviceDesc", ""))
        matching_device_id = _as_text(metadata.get("MatchingDeviceId", ""))
        service = _as_text(metadata.get("Service", ""))
        hardware_ids_value = metadata.get("HardwareID", ())
        hardware_ids = tuple(
            str(item) for item in hardware_ids_value
        ) if isinstance(hardware_ids_value, (list, tuple)) else ()

        searchable = [
            guid,
            name,
            pnp_instance_id,
            driver_desc,
            device_desc,
            matching_device_id,
            service,
            " ".join(hardware_ids),
        ]

        records.append(
            NetworkRecord(
                guid=guid,
                name=name,
                pnp_instance_id=pnp_instance_id,
                media_subtype=media_subtype,
                adapter_key_name=(
                    _as_text(metadata.get("AdapterKeyName", "")) or None
                ),
                driver_desc=driver_desc,
                device_desc=device_desc,
                matching_device_id=matching_device_id,
                service=service,
                hardware_ids=hardware_ids,
                is_rndis=_is_rndis(searchable),
                is_extra_match=_matches_any(match_patterns, searchable),
            )
        )

    return sorted(records, key=lambda item: (item.name.lower(), item.guid.lower()))


def _format_cell(value: str, width: int) -> str:
    """Trim a table cell to fit the requested width.

    Args:
        value: Raw cell text.
        width: Maximum display width.

    Returns:
        Text padded or trimmed to *width* characters.
    """
    clean = value.replace("\r", " ").replace("\n", " ")
    if len(clean) <= width:
        return f"{clean:<{width}}"
    return f"{clean[: max(0, width - 1)]}…"


def _print_records(records: list[NetworkRecord]) -> None:
    """Print all discovered network records with RNDIS and target markers.

    Args:
        records: Network records to display.

    Returns:
        None. Prints to stdout.
    """
    print(f"{FLCyan}Scanned {len(records)} network record(s):{CRst}\n")

    header = (
        f"{'Sel':<5}  "
        f"{'Name':<26}  {'Driver / PnP':<52}"
    )
    print(f"{FLCyan}{header}{CRst}")
    print(f"{FGray}{'-' * len(header)}{CRst}")

    for record in records:
        sel = record.reason if record.should_delete else ""
        sel_color = FLRed if record.is_rndis else FLYellow if record.should_delete else FGray
        detail = record.driver_desc or record.device_desc or record.pnp_instance_id
        name_color = FLYellow if record.is_rndis else FGray
        detail_color = FGray
        print(
            f"{sel_color}{sel:<5}{CRst}  "
            f"{name_color}{_format_cell(record.name, 26)}{CRst}  "
            f"{detail_color}{_format_cell(detail, 52)}{CRst}"
        )


def _delete_key_tree(root: int, path: str) -> None:
    """Delete a registry key tree recursively.

    Args:
        root: Registry root handle.
        path: Registry key path relative to *root*.

    Raises:
        OSError: If a key cannot be opened or deleted.
    """
    access = winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(root, path, 0, access) as key:
        while True:
            try:
                child = winreg.EnumKey(key, 0)
            except OSError:
                break
            _delete_key_tree(root, f"{path}\\{child}")

    winreg.DeleteKeyEx(root, path, winreg.KEY_WOW64_64KEY, 0)


def _delete_record(record: NetworkRecord) -> tuple[int, int]:
    """Delete the registry records associated with one network interface.

    Args:
        record: Selected network record.

    Returns:
        ``(deleted, failed)`` counts for this record.
    """
    paths = [f"{NETWORK_CONNECTIONS_KEY}\\{record.guid}"]
    if record.adapter_key_name:
        paths.append(f"{NETWORK_ADAPTER_CLASS_KEY}\\{record.adapter_key_name}")

    deleted = 0
    failed = 0

    for path in paths:
        try:
            _delete_key_tree(winreg.HKEY_LOCAL_MACHINE, path)
            deleted += 1
            print(f"  {FLGreen}Removed:{CRst} {FGray}HKLM\\{path}{CRst}")
        except FileNotFoundError:
            print(f"  {FLYellow}Missing:{CRst} {FGray}HKLM\\{path}{CRst}")
        except OSError as exc:
            failed += 1
            print(f"  {FLRed}Failed:{CRst}  {FGray}HKLM\\{path}{CRst}  {exc}")

    return deleted, failed


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Configured ``ArgumentParser``.
    """
    return argparse.ArgumentParser(
        description=(
            f"{FLYellow}CLEAR ANDROID RNDIS NETWORK RECORDS{CRst}\n\n"
            "List Windows network connection records, mark USB Remote NDIS "
            "records, and delete selected registry records after confirmation."
        ),
        epilog=(
            f"{FGray}Requirements: Windows only; Administrator privileges are "
            f"required for deletion. No third-party packages required.{CRst}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def main() -> int:
    # ── CLI flags ──────────────────────────────────────────
    parser = _build_parser()
    parser.add_argument(
        "--force",
        "--force-run",
        action="store_true",
        help="delete selected RNDIS/matched records without prompting",
    )
    parser.add_argument(
        "--match",
        action="append",
        default=[],
        metavar="REGEX",
        help="also delete records whose name, GUID, driver, or PnP ID matches REGEX",
    )
    args = parser.parse_args()

    match_patterns: list[Pattern[str]] = []
    for raw_pattern in args.match:
        try:
            match_patterns.append(re.compile(raw_pattern, re.IGNORECASE))
        except re.error as exc:
            Utils.print_error_and_exit(f"Invalid --match regex: {raw_pattern}\n  {exc}")

    Utils.print_banner("CLEAR ANDROID RNDIS NETWORK RECORDS")

    # ── elevation check ────────────────────────────────────
    if not Utils.is_elevated():
        print(
            f"{FLYellow}Administrator privileges are required to delete HKLM "
            f"network records.{CRst}\n"
        )
        if args.force:
            Utils.restart_elevated()
        choice = Menu.select(
            [
                MenuOption(["Y"], "Elevate and continue"),
                MenuOption(["N"], "Exit"),
            ],
            prompt="Choice",
            default_key="Y",
        )
        if choice != "Y":
            Utils.print_exit_message_and_exit("Cancelled.")
        Utils.restart_elevated()

    # ── scan registry ──────────────────────────────────────
    print(f"\n{FGray}Network records: HKLM\\{NETWORK_CONNECTIONS_KEY}{CRst}")
    print(f"{FGray}Adapter records: HKLM\\{NETWORK_ADAPTER_CLASS_KEY}{CRst}")
    if match_patterns:
        print(f"{FGray}Extra match:     {', '.join(args.match)}{CRst}")
    print()

    try:
        records = _read_network_records(match_patterns)
    except OSError as exc:
        Utils.print_error_and_exit(f"Cannot read network records:\n  {exc}")

    if not records:
        print(f"{FLGreen}No network records found.{CRst}")
        return 0

    _print_records(records)

    targets = [record for record in records if record.should_delete]
    print(
        f"\n{FLCyan}Total: {FLYellow}{len(records)}{FLCyan}, "
        f"Selected for deletion: {FLRed}{len(targets)}{CRst}"
    )

    if not targets:
        print(f"\n{FLGreen}No RNDIS or --match records found. Nothing to delete.{CRst}")
        return 0

    # ── confirm ────────────────────────────────────────────
    if not args.force:
        choice = Menu.select(
            [
                MenuOption(["Y"], f"Delete {len(targets)} network record(s)"),
                MenuOption(["N"], "Cancel"),
            ],
            prompt="Proceed",
            default_key="N",
        )
        if choice != "Y":
            Utils.print_exit_message_and_exit("Cancelled.")

    # ── delete ─────────────────────────────────────────────
    deleted = 0
    failed = 0
    print(f"\n{FLCyan}Deleting selected registry records...{CRst}\n")

    for record in targets:
        print(
            f"{FLYellow}{record.display_name()}{CRst} "
            f"{FGray}({record.reason}){CRst}"
        )
        record_deleted, record_failed = _delete_record(record)
        deleted += record_deleted
        failed += record_failed

    print(
        f"\n{FLGreen}Done.{CRst} "
        f"Deleted={FLCyan}{deleted}{CRst} "
        f"Failed={FLRed}{failed}{CRst}"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
