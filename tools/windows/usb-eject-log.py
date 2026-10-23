#!/usr/bin/env python3
"""Show Windows event logs identifying processes that blocked device ejection.

Reads System / Microsoft-Windows-Kernel-PnP / event 225 through the built-in
Windows Event Log API. Displays local time (with UTC offset), recorded PID,
executable path, device instance and affected devices, newest first. Fields
come from named XML event data, independent of Windows display language.
These historical records also cover non-USB devices; they do not prove that
the same process still holds the device. PIDs may have been reused. Executable
paths are preserved as recorded, including NT device paths. No current-process
lookup, drive-letter mapping, device ejection or log modification is performed.

Defaults: last 60 minutes, at most 50 matching records. Optional --pid,
--process and --device filters combine with AND; text filters are literal,
case-insensitive substrings. --device searches device IDs, not drive letters.
No matches is a successful query, not proof that a device is safe to remove.
Exit codes: 0 completed (possibly limited), 1 failed/partial, 2 invalid arguments.

Requirements:
    Windows 10+, Python 3.13+, project utils; administrator privileges.
    Standard-library ctypes / built-in Wevtapi.dll; no extra packages or tools.

Usage:
    python usb-eject-log.py
    python usb-eject-log.py --minutes 1440 --limit 100
    python usb-eject-log.py --device 'VID_1234' --process explorer
"""

import argparse
from collections.abc import Generator
from contextlib import closing
import ctypes
from dataclasses import dataclass
import datetime as dt
import ntpath
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


PROVIDER = "Microsoft-Windows-Kernel-PnP"
EVENT_ID = 225
DEFAULT_MINUTES = 60
DEFAULT_LIMIT = 50
EVT_QUERY_CHANNEL_PATH = 0x1
EVT_QUERY_REVERSE_DIRECTION = 0x200
EVT_RENDER_EVENT_XML = 1
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
NEXT_TIMEOUT_MS = 5000
XML_NS: dict[str, str] = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
CONTROL_ESCAPES: dict[int, str] = {value: f"\\x{value:02x}" for value in range(32)}
CONTROL_ESCAPES[127] = "\\x7f"


@dataclass(frozen=True)
class EjectEvent:
    """Historical removal veto; paths and IDs are retained as Windows recorded them.

    Attributes:
        time: Timezone-aware event timestamp.
        record_id: System log record identifier.
        pid: Recorded blocking PID, never the event publisher's PID.
        executable: Recorded ProcessName, possibly an NT device path.
        device: DeviceInstance identifying the removal target.
        affected_devices: Optional VetoingDevices field from newer event versions.
    """

    time: dt.datetime
    record_id: str
    pid: int
    executable: str
    device: str
    affected_devices: str = ""


def _parse_event(xml: str) -> EjectEvent:
    """Decode one event 225, raising ValueError/ParseError for invalid records."""
    root = ET.fromstring(xml)
    provider = root.find("e:System/e:Provider", XML_NS)
    created = root.find("e:System/e:TimeCreated", XML_NS)
    if (provider is None or provider.get("Name") != PROVIDER
            or root.findtext("e:System/e:EventID", "", XML_NS) != str(EVENT_ID)):
        raise ValueError("Unexpected provider or event ID")
    if created is None:
        raise ValueError("Missing event timestamp")
    timestamp = dt.datetime.fromisoformat(created.get("SystemTime", ""))
    if timestamp.tzinfo is None:
        raise ValueError("Event timestamp has no timezone")
    data = {node.get("Name", ""): node.text or ""
            for node in root.findall("e:EventData/e:Data", XML_NS)}
    for required in ("ProcessId", "ProcessName", "DeviceInstance"):
        if not data.get(required):
            raise ValueError(f"Missing event field: {required}")
    pid = int(data["ProcessId"])
    if pid < 0:
        raise ValueError("Invalid recorded PID")
    return EjectEvent(timestamp, root.findtext("e:System/e:EventRecordID", "", XML_NS),
                      pid, data["ProcessName"], data["DeviceInstance"], data.get("VetoingDevices", ""))


def _event_xml(minutes: int) -> Generator[str, None, None]:
    """Yield event 225 XML newest first, closing native handles on exit.

    Args:
        minutes: Positive lookback window in minutes.
    Yields:
        One complete Unicode event XML document at a time.
    Raises:
        OSError: Windows cannot query, enumerate or render the System log.
        ValueError: The lookback window is not positive.
    Side effects:
        Opens read-only local log handles; callers must close this generator
        if they stop consuming it early. Uses only the calling thread.
    """
    if minutes <= 0:
        raise ValueError("Lookback minutes must be positive")
    api = ctypes.WinDLL("wevtapi", use_last_error=True)
    handle = ctypes.c_void_p
    dword = ctypes.c_uint32
    api.EvtQuery.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_wchar_p, dword]
    api.EvtQuery.restype = handle
    api.EvtNext.argtypes = [handle, dword, ctypes.POINTER(handle), dword, dword, ctypes.POINTER(dword)]
    api.EvtNext.restype = ctypes.c_int
    api.EvtRender.argtypes = [handle, handle, dword, dword, handle,
                              ctypes.POINTER(dword), ctypes.POINTER(dword)]
    api.EvtRender.restype = ctypes.c_int
    api.EvtClose.argtypes = [handle]
    api.EvtClose.restype = ctypes.c_int

    # ── native provider/time selection ──────────────────────
    query = (f"*[System[Provider[@Name='{PROVIDER}'] and EventID={EVENT_ID} "
             f"and TimeCreated[timediff(@SystemTime) <= {minutes * 60000}]]]")
    result = api.EvtQuery(None, "System", query, EVT_QUERY_CHANNEL_PATH | EVT_QUERY_REVERSE_DIRECTION)
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        while True:
            event = handle()
            returned = dword()
            if not api.EvtNext(result, 1, ctypes.byref(event), NEXT_TIMEOUT_MS, 0, ctypes.byref(returned)):
                error = ctypes.get_last_error()
                if error == ERROR_NO_MORE_ITEMS:
                    return
                raise ctypes.WinError(error)
            try:
                # EvtRender sizes are bytes; the output is UTF-16 on Windows.
                needed = dword()
                properties = dword()
                if not api.EvtRender(None, event, EVT_RENDER_EVENT_XML, 0, None,
                                     ctypes.byref(needed), ctypes.byref(properties)):
                    error = ctypes.get_last_error()
                    if error != ERROR_INSUFFICIENT_BUFFER:
                        raise ctypes.WinError(error)
                buffer = ctypes.create_unicode_buffer((needed.value + 1) // ctypes.sizeof(ctypes.c_wchar))
                if not api.EvtRender(None, event, EVT_RENDER_EVENT_XML, ctypes.sizeof(buffer), buffer,
                                     ctypes.byref(needed), ctypes.byref(properties)):
                    raise ctypes.WinError(ctypes.get_last_error())
                xml = buffer.value
            finally:
                api.EvtClose(event)
            yield xml
    finally:
        api.EvtClose(result)


def _positive_int(value: str) -> int:
    """Validate positive integer CLI values before elevation."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return number


def _parser() -> argparse.ArgumentParser:
    """Build platform-independent help without querying logs or elevating."""
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}{'USB EJECT LOG':^60}{CRst}\n\n"
        "Description:\n  Show processes recorded as blocking device removal/ejection.\n"
        "  Reads System / Kernel-PnP / event 225, newest first, in local time.",
        epilog=f"{FGray}Requirements:\n  Windows 10+, administrator privileges, project utils.\n"
        "  Uses built-in Windows APIs; no extra packages or tools.\n\n"
        "Examples:\n  python usb-eject-log.py\n"
        "  python usb-eject-log.py --minutes 1440 --limit 100\n"
        "  python usb-eject-log.py --device VID_1234 --process explorer\n\n"
        "Notes:\n  Historical events, including non-USB devices; PIDs may have been reused.\n"
        "  Paths are shown as recorded (possibly NT paths), not resolved via current PIDs.\n"
        "  Device filters use instance IDs, not drive letters. Filters combine with AND.\n"
        "  No records does not prove safe removal. No devices or logs are modified.\n"
        f"  Exit: 0 completed, 1 failed/partial, 2 invalid arguments.{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--minutes", type=_positive_int, default=DEFAULT_MINUTES,
                        help=f"Look back this many minutes (default: {DEFAULT_MINUTES})")
    parser.add_argument("--limit", type=_positive_int, default=DEFAULT_LIMIT,
                        help=f"Maximum matching records to show (default: {DEFAULT_LIMIT})")
    parser.add_argument("--pid", type=_positive_int, help="Filter by recorded blocking PID")
    parser.add_argument("--process", help="Case-insensitive literal substring of recorded executable path")
    parser.add_argument("--device", help="Case-insensitive literal substring of device/affected-device IDs")
    return parser


def _show_events(minutes: int, limit: int, pid: int | None,
                 process: str | None, device: str | None) -> int:
    """Read, filter and print historical records; return 1 on failed/partial reads."""
    matched = 0
    invalid = 0
    failed = False
    limited = False
    print(f"Reading event {EVENT_ID} from the last {minutes} minutes (newest first).")
    print("Historical records: PIDs may have been reused; paths are shown as recorded.")
    try:
        with closing(_event_xml(minutes)) as records:
            for xml in records:
                try:
                    event = _parse_event(xml)
                except (ValueError, ET.ParseError):
                    invalid += 1
                    continue
                if pid is not None and event.pid != pid:
                    continue
                if process and process.casefold() not in event.executable.casefold():
                    continue
                if device and not any(device.casefold() in value.casefold()
                                      for value in (event.device, event.affected_devices)):
                    continue
                if matched >= limit:
                    limited = True
                    break
                matched += 1
                # ── recorded identity, without live PID enrichment ──
                print(f"\n{FLYellow}--- Log {matched} ---{CRst}")
                print(f"{FLGreen}Time:{CRst} {event.time.astimezone().isoformat(sep=' ', timespec='seconds')}"
                      f"    {FLGreen}Record:{CRst} {event.record_id.translate(CONTROL_ESCAPES)}")
                print(f"{FLGreen}PID:{CRst} {FLYellow}{event.pid}{CRst}    {FLGreen}Process:{CRst} "
                      f"{FLYellow}{ntpath.basename(event.executable).translate(CONTROL_ESCAPES)}{CRst}")
                print(f"  {FLGreen}Executable:{CRst} {FGray}{event.executable.translate(CONTROL_ESCAPES)}{CRst}")
                print(f"  {FLGreen}Device:{CRst} {FGray}{event.device.translate(CONTROL_ESCAPES)}{CRst}")
                if event.affected_devices:
                    print(f"  {FLGreen}Affected devices:{CRst} {FGray}{event.affected_devices.translate(CONTROL_ESCAPES)}{CRst}")
    except OSError as exc:
        failed = True
        print(f"{FLRed}Log query failed: {str(exc).translate(CONTROL_ESCAPES)}{CRst}", file=sys.stderr)

    # ── completion and partial-read diagnostics ──────────────
    print(f"\nDisplayed records: {matched}")
    if limited:
        print(f"{FLYellow}More matches exist. Increase --limit to display them.{CRst}")
    if invalid:
        print(f"{FLYellow}Skipped {invalid} malformed or unsupported records.{CRst}", file=sys.stderr)
    if failed or invalid:
        print(f"{FLYellow}The query is incomplete.{CRst}")
        return 1
    if not matched:
        print("No matching events in this time range. Try again after a failed eject, or increase --minutes.")
        print("This does not prove that the device is safe to remove.")
    return 0


def main() -> int:
    """Query Windows ejection-veto logs after mandatory administrator elevation.

    Returns:
        0 on success (including no matches), 1 on unsupported OS or query failure.
    Raises:
        SystemExit: Help, invalid arguments, or completion of the elevation helper.
    Side effects:
        May request UAC elevation; reads the System log and prints recorded metadata.
    """
    args = _parser().parse_args()
    if sys.platform != "win32":
        print(f"{FLRed}This script requires Windows 10+. Current platform: {sys.platform}{CRst}")
        return 1
    System.restart_elevated()
    if not System.is_elevated():
        print(f"{FLRed}Administrator privileges are required.{CRst}")
        return 1
    Console.print_banner("USB EJECT LOG")
    return _show_events(args.minutes, args.limit, args.pid, args.process, args.device)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
