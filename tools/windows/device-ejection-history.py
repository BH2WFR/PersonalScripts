#!/usr/bin/env python3
"""Implementation notes.

Read Kernel-PnP process and device vetoes from their respective channels.
Keep recorded NT paths rather than resolving through current PIDs. Filters
combine with AND; device matching includes veto names. Preserve partial-query
status and locale-independent parsing.
"""

import argparse
from collections.abc import Generator
from contextlib import closing
import ctypes
import heapq
import ntpath
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402
from utils.windows_events import (  # noqa: E402
    DEVICE_EJECTION_PROVIDER as PROVIDER,
    DEVICE_EJECTION_EVENT_ID as EVENT_ID,
    DEVICE_REMOVAL_VETO_CHANNEL,
    DEVICE_REMOVAL_VETO_EVENT_ID,
    DeviceEjectionEvent as EjectEvent,
    DeviceRemovalVetoEvent,
    parse_device_ejection_event as _parse_event,
    parse_device_removal_veto_event,
)

HELP = f"""{FLYellow}DEVICE EJECTION HISTORY{CRst}

Show why Windows blocked device removal. Kernel-PnP event 225 identifies the
recorded process; event 1000 reports the veto type and source. Historical PIDs
may have been reused.

{FLYellow}Requirements:{CRst}
  Windows 10+, administrator privileges; built-in event-log APIs.

{FLYellow}Usage:{CRst}
  python device-ejection-history.py [--minutes 60] [--limit 50]
      [--pid PID] [--process NAME] [--device INSTANCE_ID]
  Process filters apply to event 225. --device also matches the veto source.
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    Console.print_help_and_exit(HELP)


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


def _event_xml(minutes: int, channel: str, event_id: int) -> Generator[str, None, None]:
    """Yield provider-qualified XML newest first, closing native handles on exit.

    Args:
        minutes: Positive lookback window in minutes.
        channel: Local event log name.
        event_id: Kernel-PnP event ID in that channel.
    Yields:
        One complete Unicode event XML document at a time.
    Raises:
        OSError: Windows cannot query, enumerate or render the selected log.
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
    query = (f"*[System[Provider[@Name='{PROVIDER}'] and EventID={event_id} "
             f"and TimeCreated[timediff(@SystemTime) <= {minutes * 60000}]]]")
    result = api.EvtQuery(None, channel, query, EVT_QUERY_CHANNEL_PATH | EVT_QUERY_REVERSE_DIRECTION)
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
    parser.add_argument("--device", help="Case-insensitive substring of a device ID or veto source")
    return parser


def _print_event(event: EjectEvent | DeviceRemovalVetoEvent, index: int) -> None:
    """Display recorded fields for the event's channel and schema."""
    source = (f"System / {EVENT_ID}" if isinstance(event, EjectEvent)
              else f"{DEVICE_REMOVAL_VETO_CHANNEL} / {DEVICE_REMOVAL_VETO_EVENT_ID}")
    print(f"\n{FLYellow}--- Log {index} ---{CRst}")
    print(f"{FLGreen}Time:{CRst} {event.time.astimezone().isoformat(sep=' ', timespec='seconds')}"
          f"    {FLGreen}Record:{CRst} {event.record_id.translate(CONTROL_ESCAPES)}")
    print(f"  {FLGreen}Source:{CRst} {source}")
    print(f"  {FLGreen}Device:{CRst} {FGray}{event.device.translate(CONTROL_ESCAPES)}{CRst}")
    if isinstance(event, EjectEvent):
        print(f"{FLGreen}PID:{CRst} {FLYellow}{event.pid}{CRst}    {FLGreen}Process:{CRst} "
              f"{FLYellow}{ntpath.basename(event.executable).translate(CONTROL_ESCAPES)}{CRst}")
        print(f"  {FLGreen}Executable:{CRst} {FGray}{event.executable.translate(CONTROL_ESCAPES)}{CRst}")
        if event.affected_devices:
            print(f"  {FLGreen}Affected devices:{CRst} {FGray}{event.affected_devices.translate(CONTROL_ESCAPES)}{CRst}")
    else:
        print(f"  {FLGreen}Veto type:{CRst} {event.veto_type_description}")
        print(f"  {FLGreen}Vetoed by:{CRst} {event.veto_name.translate(CONTROL_ESCAPES) or '(not recorded)'}")


def _show_events(minutes: int, limit: int, pid: int | None,
                 process: str | None, device: str | None) -> int:
    """Read, filter and print historical records; return 1 on failed/partial reads."""
    matched = 0
    invalid = 0
    failed = False
    limited = False
    process_filter = (process or "").casefold()
    device_filter = (device or "").casefold()
    print(f"Reading Kernel-PnP removal vetoes from the last {minutes} minutes (newest first).")
    print("Historical records: PIDs may have been reused; paths are shown as recorded.")

    def read_matches(channel: str, event_id: int) -> Generator[EjectEvent | DeviceRemovalVetoEvent]:
        """Stream matches and retain failures independently for each channel."""
        nonlocal failed, invalid
        try:
            with closing(_event_xml(minutes, channel, event_id)) as records:
                for xml in records:
                    try:
                        if event_id == EVENT_ID:
                            event = _parse_event(xml)
                            if pid is not None and event.pid != pid:
                                continue
                            if process_filter and process_filter not in event.executable.casefold():
                                continue
                            other_device = event.affected_devices
                        else:
                            event = parse_device_removal_veto_event(xml)
                            other_device = event.veto_name
                    except (ValueError, ET.ParseError):
                        invalid += 1
                        continue
                    if device_filter and not any(device_filter in value.casefold()
                                                 for value in (event.device, other_device)):
                        continue
                    yield event
        except OSError as exc:
            failed = True
            print(f"{FLRed}Log query failed ({channel}): {str(exc).translate(CONTROL_ESCAPES)}{CRst}", file=sys.stderr)

    with (
        closing(read_matches("System", EVENT_ID)) as system,
        closing(read_matches(DEVICE_REMOVAL_VETO_CHANNEL, DEVICE_REMOVAL_VETO_EVENT_ID)) as vetoes,
    ):
        events = system if pid is not None or process_filter else heapq.merge(
            system, vetoes, key=lambda event: event.time, reverse=True)
        for event in events:
            if matched >= limit:
                limited = True
                break
            matched += 1
            _print_event(event, matched)

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
        May request UAC elevation; reads Kernel-PnP logs and prints recorded metadata.
    """
    Console.initialize_ansi_output()
    args = _parser().parse_args()
    if sys.platform != "win32":
        print(f"{FLRed}This script requires Windows 10+. Current platform: {sys.platform}{CRst}")
        return 1
    System.restart_elevated()
    Console.print_banner("DEVICE EJECTION HISTORY")
    return _show_events(args.minutes, args.limit, args.pid, args.process, args.device)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
