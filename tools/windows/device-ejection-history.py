#!/usr/bin/env python3
"""Implementation notes.

Read provider-qualified System/Kernel-PnP event 225 and named XML fields.
Keep recorded NT paths rather than resolving through current PIDs. Filters
combine with AND; device matching uses instance IDs. Preserve partial-query
status and locale-independent parsing.
"""

import argparse
from collections.abc import Generator
from contextlib import closing
import ctypes
import ntpath
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402
from utils.windows_events import (  # noqa: E402
    DEVICE_EJECTION_PROVIDER as PROVIDER,
    DEVICE_EJECTION_EVENT_ID as EVENT_ID,
    DeviceEjectionEvent as EjectEvent,
    parse_device_ejection_event as _parse_event,
)

HELP = f"""{FLYellow}DEVICE EJECTION HISTORY{CRst}

Find historical events identifying processes that blocked device removal.
Includes non-USB devices; recorded PIDs may have been reused. No matches do not
prove safe removal. Devices and logs are not modified.

{FLYellow}Requirements:{CRst}
  Windows 10+, administrator privileges; built-in event-log APIs.

{FLYellow}Usage:{CRst}
  python device-ejection-history.py [--minutes 60] [--limit 50]
      [--pid PID] [--process NAME] [--device INSTANCE_ID]
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


DEFAULT_MINUTES = 60
DEFAULT_LIMIT = 50
EVT_QUERY_CHANNEL_PATH = 0x1
EVT_QUERY_REVERSE_DIRECTION = 0x200
EVT_RENDER_EVENT_XML = 1
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_NO_MORE_ITEMS = 259
NEXT_TIMEOUT_MS = 5000
CONTROL_ESCAPES: dict[int, str] = {value: f"\\x{value:02x}" for value in range(32)}
CONTROL_ESCAPES[127] = "\\x7f"


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
    parser = Console.argument_parser(HELP)
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
    Console.print_banner("DEVICE EJECTION HISTORY")
    return _show_events(args.minutes, args.limit, args.pid, args.process, args.device)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
