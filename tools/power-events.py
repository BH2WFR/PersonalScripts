#!/usr/bin/env python3
"""View historical power and session events in a cross-platform Qt GUI.

Choose a relative or custom local-time range, query in a cancellable worker,
and toggle event checkboxes without rescanning logs. Select a row for its raw
evidence; use Export CSV or Export JSON to save visible rows in display order.
CSV uses UTF-8 without BOM and includes local timestamps with UTC offsets.
Window geometry, columns, relative range and type filters persist through
QSettings. No service is
installed and no auditing, logging or power settings are changed.

Sources:
    macOS: pmset sleep/wake history, explicit loginwindow lock notifications,
        last reboot/shutdown records (minute precision), current kern.boottime.
    Windows 10+: PowerShell Get-WinEvent; provider-qualified System events and
        Security 4800/4801. Security access and prior auditing are required.
    Linux: systemd journal kernel/logind/sleep/shutdown records. Lock history
        is limited to explicit logind session transitions; desktop support and
        journal persistence/permissions vary. Non-systemd Linux is unsupported.

Limits:
    History depends on retained accessible logs. Missing records are not proof
    of absence. Shutdown initiation is not proof of completed power-off; an
    unexpected restart is timestamped when reported, not at the earlier outage.
    Screen blanking, unlock requests and wake scheduling are not state changes.
    Source commands time out after 90 seconds. At most 50,000 normalized events
    are displayed; narrow the query when the limit is reached. No usage-duration
    inference or background recording is performed in this version.

Requirements:
    - pip: PySide6 (GUI runtime).
    - System: graphical desktop; macOS built-ins, Windows PowerShell, or Linux
      journalctl. Additional log privileges may be needed for some sources.

Usage:
    conda run --no-capture-output -n base python tools/power-events.py
    conda run -n base python tools/power-events.py --help
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable
import csv
from dataclasses import dataclass, field
import datetime as dt
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import cast
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from utils import *  # noqa: E402


UTC = dt.timezone.utc
COMMAND_TIMEOUT = 90.0
POLL_SECONDS = 0.2
MAX_EVENTS = 50_000
DEFAULT_SIZE = (1200, 800)
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S %z"
MONTHS: dict[str, int] = {
    month: index for index, month in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}
XML_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


class EventKind(StrEnum):
    """Normalized event categories; requests and background wakes stay distinct."""

    STARTUP = "Startup"
    SHUTDOWN = "Shutdown"
    SLEEP = "Sleep"
    WAKE = "Wake"
    LOCK = "Lock"
    UNLOCK = "Unlock"
    HIBERNATE = "Hibernate"
    DARK_WAKE = "Background wake"
    POWER_REQUEST = "Shutdown/restart request"
    UNEXPECTED_RESTART = "Unexpected restart"


class SourceState(StrEnum):
    """Availability of a source, separately from whether matching events exist."""

    OK = "Read"
    EMPTY = "No matches"
    LIMITED = "Limited"
    ERROR = "Unavailable"


class TimeRange(StrEnum):
    """User-selectable relative ranges, recomputed at query time."""

    DAY = "Last 24 hours"
    TODAY = "Today"
    YESTERDAY = "Yesterday"
    WEEK = "Last 7 days"
    MONTH = "Last 30 days"
    CUSTOM = "Custom"


@dataclass(frozen=True)
class PowerEvent:
    """One timestamped observation and the raw evidence behind its interpretation.

    Timestamps are timezone-aware; record_id identifies the native source record.
    Session and boot_id prevent conflating distinct users and startup cycles.
    """

    timestamp: dt.datetime
    kind: EventKind
    summary: str
    source: str
    record_id: str = ""
    session: str = ""
    boot_id: str = ""
    raw: str = ""


@dataclass(frozen=True)
class SourceStatus:
    """Source name, availability, explanation and number of recognized events."""

    source: str
    state: SourceState
    message: str
    count: int = 0


@dataclass
class QueryResult:
    """Events and source diagnostics for a half-open UTC interval [start, end)."""

    start: dt.datetime
    end: dt.datetime
    events: list[PowerEvent] = field(default_factory=list)
    statuses: list[SourceStatus] = field(default_factory=list)


def _timestamp(value: str) -> dt.datetime:
    """Parse an ISO timestamp; a missing offset means the machine's local timezone."""
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _json_records(text: str) -> Iterable[dict[str, object]]:
    """Yield JSON objects from NDJSON, ignoring command banners and non-object lines."""
    for line in text.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        record = json.loads(line)
        if isinstance(record, dict):
            yield cast(dict[str, object], record)


def _run_command(command: list[str], cancelled: threading.Event) -> tuple[str, str]:
    """Run a read-only log command with cancellation and a bounded lifetime.

    Args:
        command: Executable and literal arguments; no shell interpretation.
        cancelled: Set by the GUI to stop the child process.

    Returns:
        UTF-8 stdout and stderr (stderr may contain partial-access notices).

    Raises:
        InterruptedError: If cancelled; the child is killed and reaped.
        RuntimeError: On nonzero exit, timeout or process-launch failure.

    Side effects:
        Starts one child process; reads system logs without changing settings.
    """
    if cancelled.is_set():
        raise InterruptedError("Query cancelled.")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, text=True, encoding="utf-8", errors="replace",
        ) as process:
            deadline = time.monotonic() + COMMAND_TIMEOUT
            try:
                while True:
                    if cancelled.is_set():
                        raise InterruptedError("Query cancelled.")
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"Source query exceeded {COMMAND_TIMEOUT:.0f} seconds.")
                    try:
                        output, errors = process.communicate(timeout=POLL_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            if process.returncode:
                raise RuntimeError(errors.strip()[:2000] or f"Command exited with code {process.returncode}.")
            return output, errors
    except InterruptedError:
        raise
    except OSError as exc:
        raise RuntimeError(f"Could not read this source: {exc}") from exc


def _parse_pmset(text: str) -> list[PowerEvent]:
    """Parse actual pmset state records, excluding Wake Requests and client acknowledgements."""
    events: list[PowerEvent] = []
    pattern = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4})\s+(Sleep|Wake|DarkWake|Hibernate)\s{2,}(.+)$")
    kinds = {"Sleep": EventKind.SLEEP, "Wake": EventKind.WAKE,
             "DarkWake": EventKind.DARK_WAKE, "Hibernate": EventKind.HIBERNATE}
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        timestamp = dt.datetime.strptime(match[1], TIMESTAMP_FORMAT).astimezone(UTC)
        events.append(PowerEvent(timestamp, kinds[match[2]], match[3].strip(), "pmset", raw=line))
    return events


def _parse_mac_sessions(text: str) -> list[PowerEvent]:
    """Recognize explicit distributed lock/unlock notifications, never requests or snapshots."""
    events: list[PowerEvent] = []
    pattern = re.compile(r"sendDistributedNotification:\s+com\.apple\.screenIs(Locked|Unlocked)\b")
    for record in _json_records(text):
        message = str(record.get("eventMessage", ""))
        match = pattern.search(message)
        if match is None:
            continue
        timestamp = _timestamp(str(record.get("timestamp", "")))
        session = re.search(r"with object:\s*(\d+)", message)
        kind = EventKind.LOCK if match[1] == "Locked" else EventKind.UNLOCK
        events.append(PowerEvent(
            timestamp, kind, f"loginwindow reported screen {match[1].lower()}",
            "loginwindow", str(record.get("machTimestamp", "")),
            f"UID {session[1]}" if session else "", str(record.get("bootUUID", "")),
            json.dumps(record, ensure_ascii=False, indent=2),
        ))
    return events


def _parse_mac_last(text: str) -> list[PowerEvent]:
    """Read last -y boot/shutdown observations, retaining their minute-level precision."""
    events: list[PowerEvent] = []
    pattern = re.compile(r"^(reboot|shutdown)\s+.*?\b\w{3}\s+(\w{3})\s+(\d+)\s+(\d{4})\s+(\d\d):(\d\d)")
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None or match[2] not in MONTHS:
            continue
        timestamp = dt.datetime(int(match[4]), MONTHS[match[2]], int(match[3]), int(match[5]), int(match[6])).astimezone(UTC)
        kind = EventKind.STARTUP if match[1] == "reboot" else EventKind.SHUTDOWN
        events.append(PowerEvent(timestamp, kind, f"{kind.value} recorded (minute precision)", "last", raw=line))
    return events


def _parse_windows_xml(xml: str) -> list[PowerEvent]:
    """Map provider-qualified Windows XML events, using embedded wake time when available."""
    root = ET.fromstring(xml)
    system = root.find("e:System", XML_NS)
    if system is None:
        return []
    provider = system.find("e:Provider", XML_NS)
    created = system.find("e:TimeCreated", XML_NS)
    if provider is None or created is None:
        return []
    source = provider.get("Name", "")
    event_id = int(system.findtext("e:EventID", "0", XML_NS))
    timestamp = _timestamp(created.get("SystemTime", ""))
    data = {node.get("Name", f"param{index}"): node.text or ""
            for index, node in enumerate(root.findall("e:EventData/e:Data", XML_NS))}
    mapping: dict[tuple[str, int], tuple[EventKind, str]] = {
        ("Microsoft-Windows-Kernel-General", 12): (EventKind.STARTUP, "Operating system started"),
        ("Microsoft-Windows-Kernel-General", 13): (EventKind.SHUTDOWN, "Operating system shutdown initiated"),
        ("Microsoft-Windows-Kernel-Power", 42): (EventKind.SLEEP, "Entering low-power state"),
        ("Microsoft-Windows-Kernel-Power", 107): (EventKind.WAKE, "System resumed from sleep"),
        ("Microsoft-Windows-Kernel-Power", 41): (EventKind.UNEXPECTED_RESTART, "Previous shutdown was unclean; timestamp is the subsequent report"),
        ("Microsoft-Windows-Power-Troubleshooter", 1): (EventKind.WAKE, "System returned from low-power state"),
        ("Microsoft-Windows-Security-Auditing", 4800): (EventKind.LOCK, "Workstation locked"),
        ("Microsoft-Windows-Security-Auditing", 4801): (EventKind.UNLOCK, "Workstation unlocked"),
        ("User32", 1074): (EventKind.POWER_REQUEST, "Shutdown/restart requested (not completion)"),
        ("USER32", 1074): (EventKind.POWER_REQUEST, "Shutdown/restart requested (not completion)"),
    }
    matched = mapping.get((source, event_id))
    if matched is None:
        return []
    kind, summary = matched
    if kind == EventKind.SLEEP and data.get("TargetState") == "5":
        kind, summary = EventKind.HIBERNATE, "Entering hibernation"
    if source == "Microsoft-Windows-Power-Troubleshooter" and data.get("WakeTime"):
        timestamp = _timestamp(data["WakeTime"])
    user = data.get("TargetUserName", "")
    session = data.get("SessionId", "")
    return [PowerEvent(
        timestamp, kind, summary, f"{source} / {event_id}",
        system.findtext("e:EventRecordID", "", XML_NS),
        f"{user} (session {session})" if session else user,
        raw=xml,
    )]


def _parse_linux_journal(text: str) -> list[PowerEvent]:
    """Parse conservative kernel/systemd transitions; arbitrary desktop lock text is excluded."""
    events: list[PowerEvent] = []
    for record in _json_records(text):
        raw_message = record.get("MESSAGE", "")
        if not isinstance(raw_message, str):
            continue
        message = raw_message.strip()
        identifier = str(record.get("SYSLOG_IDENTIFIER", ""))
        unit = str(record.get("_SYSTEMD_UNIT", ""))
        kernel = record.get("_TRANSPORT") == "kernel"
        kind: EventKind | None = None
        summary = message
        session = ""
        if kernel:
            if message.startswith("Linux version "):
                kind, summary = EventKind.STARTUP, "Kernel startup recorded"
            elif re.search(r"\bPM: suspend entry\b", message):
                kind = EventKind.SLEEP
            elif re.search(r"\bPM: suspend exit\b", message):
                kind = EventKind.WAKE
            elif re.search(r"\bPM: hibernation: hibernation entry\b", message):
                kind = EventKind.HIBERNATE
            elif re.search(r"\bPM: hibernation: hibernation exit\b", message):
                kind = EventKind.WAKE
        elif identifier == "systemd-shutdown":
            if message in ("Powering off.", "Rebooting.", "Halting system."):
                kind, summary = EventKind.SHUTDOWN, f"Final shutdown stage: {message}"
        elif identifier == "systemd-logind" or unit == "systemd-logind.service":
            match = re.fullmatch(r"Session (\S+) (locked|unlocked)\.?", message, re.IGNORECASE)
            if match:
                kind = EventKind.LOCK if match[2].lower() == "locked" else EventKind.UNLOCK
                session = match[1]
        elif unit in ("systemd-suspend.service", "systemd-hibernate.service", "systemd-suspend-then-hibernate.service", "systemd-hybrid-sleep.service"):
            if "System returned from sleep operation" in message or message == "System resumed.":
                kind = EventKind.WAKE
        if kind is None:
            continue
        timestamp = dt.datetime.fromtimestamp(int(str(record["__REALTIME_TIMESTAMP"])) / 1_000_000, UTC)
        events.append(PowerEvent(
            timestamp, kind, summary, f"journal / {identifier or unit or 'kernel'}",
            str(record.get("__CURSOR", "")), session, str(record.get("_BOOT_ID", "")),
            json.dumps(record, ensure_ascii=False, indent=2),
        ))
    return events


def _collect_source(
    result: QueryResult, source: str, command: list[str],
    parser: Callable[[str], list[PowerEvent]], cancelled: threading.Event,
) -> None:
    """Append one source's bounded-range events or an availability diagnostic; cancellation propagates."""
    try:
        text, errors = _run_command(command, cancelled)
        events = [event for event in parser(text) if result.start <= event.timestamp < result.end]
        result.events.extend(events)
        state = SourceState.LIMITED if errors.strip() else SourceState.OK if events else SourceState.EMPTY
        message = errors.strip()[:2000] or "Accessible retained records queried; completeness is not guaranteed."
        result.statuses.append(SourceStatus(source, state, message, len(events)))
    except (RuntimeError, ValueError, KeyError, ET.ParseError) as exc:
        result.statuses.append(SourceStatus(source, SourceState.ERROR, str(exc)))


def _collect_macos(result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None]) -> None:
    """Collect independent macOS power, screen-session and startup sources."""
    progress("Reading sleep and wake history...")
    _collect_source(result, "Power history", ["/usr/bin/pmset", "-g", "log"], _parse_pmset, cancelled)
    progress("Reading lock and unlock notifications...")
    predicate = 'process == "loginwindow" AND eventMessage CONTAINS "sendDistributedNotification: com.apple.screenIs"'
    _collect_source(result, "Screen sessions", [
        "/usr/bin/log", "show", "--style", "ndjson", "--info",
        "--start", result.start.strftime("%Y-%m-%d %H:%M:%S+0000"),
        "--end", result.end.strftime("%Y-%m-%d %H:%M:%S+0000"), "--predicate", predicate,
    ], _parse_mac_sessions, cancelled)
    progress("Reading startup and shutdown history...")
    _collect_source(result, "Boot history", ["/usr/bin/last", "-y", "reboot", "shutdown"], _parse_mac_last, cancelled)
    try:
        text, _ = _run_command(["/usr/sbin/sysctl", "-n", "kern.boottime"], cancelled)
        match = re.search(r"sec\s*=\s*(\d+)", text)
        if match is None:
            raise ValueError("Current startup timestamp is unavailable.")
        timestamp = dt.datetime.fromtimestamp(int(match[1]), UTC)
        if result.start <= timestamp < result.end:
            result.events = [event for event in result.events if not (
                event.kind == EventKind.STARTUP and event.source == "last"
                and 0 <= (timestamp - event.timestamp).total_seconds() < 60
            )]
            result.events.append(PowerEvent(timestamp, EventKind.STARTUP, "Current kernel startup time", "kern.boottime", raw=text.strip()))
        result.statuses.append(SourceStatus("Current startup", SourceState.OK, "Current boot only; older startup records come from last."))
    except (RuntimeError, ValueError) as exc:
        result.statuses.append(SourceStatus("Current startup", SourceState.ERROR, str(exc)))
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "Lock/unlock uses explicit loginwindow notifications; macOS versions and log retention vary. "
        "Older boot records have minute precision. Background wakes do not imply user activity."))


def _collect_windows(result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None]) -> None:
    """Read provider-qualified event XML through PowerShell, retaining access errors per source."""
    executable = Environment.find_pwsh()
    if executable is None:
        result.statuses.append(SourceStatus("Windows Event Log", SourceState.ERROR, "PowerShell was not found."))
        return
    progress("Reading Windows System and Security event logs...")
    script = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$start = [DateTimeOffset]::Parse('__START__').UtcDateTime
$end = [DateTimeOffset]::Parse('__END__').UtcDateTime
$sources = @(
    @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=@(12,13)},
    @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(41,42,107)},
    @{LogName='System'; ProviderName='Microsoft-Windows-Power-Troubleshooter'; Id=@(1)},
    @{LogName='System'; ProviderName='User32'; Id=@(1074)},
    @{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4800,4801)}
)
foreach ($filter in $sources) {
    $label = "$($filter.LogName) / $($filter.ProviderName)"
    $filter.StartTime = $start
    $filter.EndTime = $end
    $count = 0
    try {
        Get-WinEvent -FilterHashtable $filter -MaxEvents 50001 -ErrorAction Stop | ForEach-Object {
            @{kind='event'; xml=$_.ToXml()} | ConvertTo-Json -Compress
            $count++
        }
        @{kind='status'; source=$label; state='Read'; count=$count; message='Accessible retained records queried.'} | ConvertTo-Json -Compress
    } catch {
        $state = if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {'No matches'} else {'Unavailable'}
        @{kind='status'; source=$label; state=$state; count=$count; message=$_.Exception.Message} | ConvertTo-Json -Compress
    }
}
""".replace("__START__", result.start.isoformat()).replace("__END__", result.end.isoformat())
    try:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        text, _ = _run_command([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], cancelled)
        for record in _json_records(text):
            if record.get("kind") == "event":
                result.events.extend(_parse_windows_xml(str(record["xml"])))
            elif record.get("kind") == "status":
                count = int(str(record.get("count", 0)))
                result.statuses.append(SourceStatus(str(record["source"]), SourceState(str(record["state"])), str(record["message"]), count))
                if count > MAX_EVENTS:
                    result.statuses.append(SourceStatus("Result limit", SourceState.LIMITED, "A source reached the event limit; narrow the time range."))
    except (RuntimeError, ValueError, KeyError, ET.ParseError) as exc:
        result.statuses.append(SourceStatus("Windows Event Log", SourceState.ERROR, str(exc)))
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "Lock/unlock requires prior Other Logon/Logoff auditing and Security log access. "
        "Modern Standby coverage varies. Unclean shutdown reports are timestamped at the later report."))


def _collect_linux(result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None]) -> None:
    """Read systemd journal power records; report unsupported and limited histories explicitly."""
    executable = Environment.which("journalctl")
    if executable is None:
        result.statuses.append(SourceStatus("systemd journal", SourceState.ERROR, "journalctl was not found; this version requires systemd journal."))
        return
    progress("Reading kernel and systemd power history...")
    command = [executable, "--no-pager", "--output=json", "--since", f"@{int(result.start.timestamp())}",
               "--until", f"@{int(result.end.timestamp())}",
               "_TRANSPORT=kernel", "+", "_SYSTEMD_UNIT=systemd-logind.service", "+",
               "_SYSTEMD_UNIT=systemd-suspend.service", "+", "_SYSTEMD_UNIT=systemd-hibernate.service", "+",
               "_SYSTEMD_UNIT=systemd-suspend-then-hibernate.service", "+", "_SYSTEMD_UNIT=systemd-hybrid-sleep.service", "+",
               "SYSLOG_IDENTIFIER=systemd-shutdown"]
    _collect_source(result, "systemd journal", command, _parse_linux_journal, cancelled)
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "History depends on journal retention, persistence and access. Lock/unlock is recognized only "
        "when logind explicitly records the session transition; desktop-only lock signals are not collected. "
        "Missing shutdown records do not prove a crash."))


def query_events(
    start: dt.datetime, end: dt.datetime, cancelled: threading.Event,
    progress: Callable[[str], None] = lambda _message: None,
) -> QueryResult:
    """Read local power history without changing settings or escalating privileges.

    Args:
        start: Inclusive timezone-aware start timestamp.
        end: Exclusive timezone-aware end timestamp, after start.
        cancelled: Cancellation flag shared with the GUI worker.
        progress: Optional callback receiving short English progress messages.

    Returns:
        Sorted events and per-source diagnostics, including partial failures.

    Raises:
        ValueError: For naive or reversed timestamps.
        InterruptedError: When the user cancels the query.

    Side effects:
        Runs native read-only log commands. No files or system settings are changed.
    """
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Choose an end time after the start time, with a timezone.")
    result = QueryResult(start.astimezone(UTC), end.astimezone(UTC))
    collectors = {"darwin": _collect_macos, "win32": _collect_windows, "linux": _collect_linux}
    collector = collectors.get(sys.platform)
    if collector is None:
        result.statuses.append(SourceStatus("Platform", SourceState.ERROR, f"Unsupported platform: {sys.platform}"))
    else:
        collector(result, cancelled, progress)
    if cancelled.is_set():
        raise InterruptedError("Query cancelled.")
    unique: dict[tuple[dt.datetime, EventKind, str, str, str], PowerEvent] = {}
    for event in result.events:
        if result.start <= event.timestamp < result.end:
            unique[(event.timestamp, event.kind, event.source, event.record_id, event.session)] = event
    result.events = sorted(unique.values(), key=lambda event: event.timestamp, reverse=True)
    if len(result.events) > MAX_EVENTS:
        result.events = result.events[:MAX_EVENTS]
        result.statuses.append(SourceStatus("Result limit", SourceState.LIMITED, f"Showing newest {MAX_EVENTS:,} events; narrow the time range."))
    return result


def export_events(path: Path, events: Iterable[PowerEvent], result: QueryResult) -> None:
    """Write visible events to UTF-8 CSV or JSON, with timezone-aware timestamps.

    Args:
        path: User-selected .csv or .json destination; an existing file is overwritten.
        events: Visible events in their current display order.
        result: Query bounds and source availability metadata for JSON export.

    Raises:
        ValueError: For unsupported extensions.
        OSError: If the destination cannot be written.

    Side effects:
        Writes only the selected export file. JSON includes original evidence.
    """
    rows = [{"time": event.timestamp.astimezone().isoformat(), "event": event.kind.value,
             "summary": event.summary, "source": event.source, "session": event.session,
             "boot_id": event.boot_id, "record_id": event.record_id, "raw": event.raw} for event in events]
    if path.suffix.lower() == ".json":
        payload = {"start": result.start.isoformat(), "end_exclusive": result.end.isoformat(),
                   "sources": [{"source": status.source, "state": status.state.value,
                                "message": status.message, "count": status.count} for status in result.statuses],
                   "events": rows}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif path.suffix.lower() == ".csv":
        columns = ["time", "event", "summary", "source", "session", "boot_id", "record_id"]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                # Keep copied log strings from becoming spreadsheet formulas.
                writer.writerow({key: f"'{value}" if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                                 for key, value in row.items()})
    else:
        raise ValueError("Choose a .csv or .json export file.")


def _launch_gui() -> int:
    """Load the Qt GUI after CLI help/dependency checks and run its event loop."""
    from PySide6 import QtCore, QtGui, QtWidgets

    class QueryWorker(QtCore.QThread):
        """Run log collection off the GUI thread and deliver results via Qt signals."""

        completed = QtCore.Signal(object)
        failed = QtCore.Signal(str)
        progress = QtCore.Signal(str)

        def __init__(self, start: dt.datetime, end: dt.datetime, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.start_time, self.end_time = start, end
            self.cancelled = threading.Event()

        def run(self) -> None:
            """Emit a complete result or failure; exceptions never escape the worker thread."""
            try:
                result = query_events(self.start_time, self.end_time, self.cancelled, self.progress.emit)
                self.completed.emit(result)
            except Exception as exc:
                self.failed.emit(str(exc))

    class EventsModel(QtCore.QAbstractTableModel):
        """Read-only event model; formatting does not allocate a widget for each cell."""

        HEADERS = ("Time (local)", "Event", "Details", "Source", "User / session")

        def __init__(self, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.events: list[PowerEvent] = []

        def rowCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
            """Return the number of top-level events; this table has no child rows."""
            return 0 if parent.isValid() else len(self.events)

        def columnCount(self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = QtCore.QModelIndex()) -> int:
            """Return the fixed number of event columns."""
            return len(self.HEADERS)

        def data(self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> object:
            """Return rendered cells, raw tooltips or stable sort values for an event."""
            if not index.isValid() or not 0 <= index.row() < len(self.events):
                return None
            event = self.events[index.row()]
            if role == QtCore.Qt.ItemDataRole.UserRole:
                return event.timestamp.timestamp() if index.column() == 0 else self.data(index)
            if role == QtCore.Qt.ItemDataRole.ToolTipRole:
                return event.summary
            if role != QtCore.Qt.ItemDataRole.DisplayRole:
                return None
            return (event.timestamp.astimezone().strftime(TIMESTAMP_FORMAT), event.kind.value,
                    event.summary, event.source, event.session)[index.column()]

        def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> object:
            """Return English horizontal labels or row numbers."""
            if role != QtCore.Qt.ItemDataRole.DisplayRole:
                return None
            return self.HEADERS[section] if orientation == QtCore.Qt.Orientation.Horizontal else section + 1

        def replace(self, events: list[PowerEvent]) -> None:
            """Replace the current query atomically and notify attached views."""
            self.beginResetModel()
            self.events = events
            self.endResetModel()

    class EventFilter(QtCore.QSortFilterProxyModel):
        """Filter cached events by checkbox selection without querying the OS again."""

        def __init__(self, model: EventsModel, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.events_model = model
            self.allowed: set[EventKind] = set(EventKind)
            self.setSourceModel(model)
            self.setSortRole(QtCore.Qt.ItemDataRole.UserRole)

        def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
            """Include a row when its event type is enabled."""
            return self.events_model.events[source_row].kind in self.allowed

    class PowerEventsWindow(QtWidgets.QMainWindow):
        """Power history browser with cancellable queries, local filters and evidence detail."""

        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Power Events")
            self.resize(*DEFAULT_SIZE)
            self.settings = QtCore.QSettings(
                QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                "PersonalScripts", "PowerEvents",
            )
            self.worker: QueryWorker | None = None
            self.result: QueryResult | None = None
            self.closing = False
            self.checkboxes: dict[EventKind, QtWidgets.QCheckBox] = {}
            self._build_ui()
            self._restore_settings()
            self._apply_range()
            QtCore.QTimer.singleShot(0, self._query)

        def _build_ui(self) -> None:
            """Build native Qt controls and connect query/filter/export actions."""
            central = QtWidgets.QWidget(self)
            layout = QtWidgets.QVBoxLayout(central)
            layout.setContentsMargins(16, 14, 16, 12)
            layout.setSpacing(10)
            self.setCentralWidget(central)

            # ── time range and query controls ───────────
            bar = QtWidgets.QHBoxLayout()
            self.range_box = QtWidgets.QComboBox()
            self.range_box.addItems([value.value for value in TimeRange])
            self.range_box.currentIndexChanged.connect(self._apply_range)
            self.start_edit = QtWidgets.QDateTimeEdit()
            self.end_edit = QtWidgets.QDateTimeEdit()
            for editor in (self.start_edit, self.end_edit):
                editor.setCalendarPopup(True)
                editor.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
                editor.setMinimumWidth(180)
            self.query_button = QtWidgets.QPushButton("Query / Refresh")
            self.query_button.clicked.connect(self._query)
            self.cancel_button = QtWidgets.QPushButton("Cancel")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self._cancel)
            for widget in (QtWidgets.QLabel("Range"), self.range_box, QtWidgets.QLabel("From"),
                           self.start_edit, QtWidgets.QLabel("Until"), self.end_edit,
                           self.query_button, self.cancel_button):
                bar.addWidget(widget)
            layout.addLayout(bar)
            note = QtWidgets.QLabel("Local time. Start is inclusive; end is exclusive. Type filters apply instantly to loaded events.")
            note.setWordWrap(True)
            layout.addWidget(note)

            # ── event visibility controls ───────────────
            group = QtWidgets.QGroupBox("Show events")
            filters = QtWidgets.QGridLayout(group)
            for index, kind in enumerate(EventKind):
                checkbox = QtWidgets.QCheckBox(kind.value)
                checkbox.setChecked(kind != EventKind.DARK_WAKE)
                checkbox.toggled.connect(self._filter)
                self.checkboxes[kind] = checkbox
                filters.addWidget(checkbox, index // 6, index % 6)
            select_all = QtWidgets.QPushButton("All")
            select_none = QtWidgets.QPushButton("None")
            select_all.clicked.connect(lambda: self._select_types(True))
            select_none.clicked.connect(lambda: self._select_types(False))
            filters.addWidget(select_all, 1, 4)
            filters.addWidget(select_none, 1, 5)
            layout.addWidget(group)

            # ── event table and evidence tabs ───────────
            self.model = EventsModel(self)
            self.proxy = EventFilter(self.model, self)
            self.table = QtWidgets.QTableView()
            self.table.setModel(self.proxy)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
            self.table.setAlternatingRowColors(True)
            self.table.setWordWrap(False)
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(0, QtCore.Qt.SortOrder.DescendingOrder)
            self.table.verticalHeader().hide()
            for index, width in enumerate((220, 155, 380, 220, 160)):
                self.table.setColumnWidth(index, width)
            self.table.selectionModel().selectionChanged.connect(self._show_detail)
            self.detail = QtWidgets.QPlainTextEdit()
            self.detail.setReadOnly(True)
            self.detail.setPlaceholderText("Select an event to inspect its original evidence.")
            self.sources = QtWidgets.QPlainTextEdit()
            self.sources.setReadOnly(True)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self.detail, "Event details")
            tabs.addTab(self.sources, "Sources and coverage")
            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(tabs)
            splitter.setSizes([470, 170])
            layout.addWidget(splitter, 1)
            self.summary = QtWidgets.QLabel("Ready")
            self.summary.setWordWrap(True)
            self.export_button = QtWidgets.QPushButton("Export CSV...")
            self.export_button.setEnabled(False)
            self.export_button.clicked.connect(lambda: self._export(".csv"))
            self.export_json_button = QtWidgets.QPushButton("Export JSON...")
            self.export_json_button.setEnabled(False)
            self.export_json_button.clicked.connect(lambda: self._export(".json"))
            footer = QtWidgets.QHBoxLayout()
            footer.addWidget(self.summary, 1)
            footer.addWidget(self.export_button)
            footer.addWidget(self.export_json_button)
            layout.addLayout(footer)
            self.statusBar().showMessage("Ready")

        def _restore_settings(self) -> None:
            """Restore presentation preferences; relative date ranges are not stored as fixed dates."""
            geometry = self.settings.value("geometry")
            if isinstance(geometry, QtCore.QByteArray):
                self.restoreGeometry(geometry)
            header = self.settings.value("columns")
            if isinstance(header, QtCore.QByteArray):
                self.table.horizontalHeader().restoreState(header)
            value = str(self.settings.value("range", TimeRange.DAY.value))
            index = self.range_box.findText(value)
            self.range_box.setCurrentIndex(max(0, index))
            selected = self.settings.value("types")
            if isinstance(selected, list):
                for kind, checkbox in self.checkboxes.items():
                    checkbox.setChecked(kind.value in selected)
            if value == TimeRange.CUSTOM.value:
                for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                    saved = str(self.settings.value(key, ""))
                    parsed = QtCore.QDateTime.fromString(saved, QtCore.Qt.DateFormat.ISODate)
                    if parsed.isValid():
                        editor.setDateTime(parsed)
            self._filter()

        def _apply_range(self) -> None:
            """Update date controls for relative ranges; retain custom selections."""
            selected = TimeRange(self.range_box.currentText())
            custom = selected == TimeRange.CUSTOM
            self.start_edit.setEnabled(custom)
            self.end_edit.setEnabled(custom)
            now = QtCore.QDateTime.currentDateTime()
            if custom:
                if self.start_edit.date().year() < 2001:
                    self.start_edit.setDateTime(now.addDays(-1))
                    self.end_edit.setDateTime(now)
                return
            end = now
            if selected == TimeRange.TODAY:
                start = QtCore.QDateTime(now.date(), QtCore.QTime(0, 0))
            elif selected == TimeRange.YESTERDAY:
                end = QtCore.QDateTime(now.date(), QtCore.QTime(0, 0))
                start = end.addDays(-1)
            elif selected == TimeRange.DAY:
                start = now.addSecs(-24 * 60 * 60)
            else:
                start = now.addDays(-7 if selected == TimeRange.WEEK else -30)
            self.start_edit.setDateTime(start)
            self.end_edit.setDateTime(end)

        def _query(self) -> None:
            """Start a new worker; reject reversed ranges and overlapping queries."""
            if self.worker is not None:
                return
            self._apply_range()
            start = dt.datetime.fromtimestamp(self.start_edit.dateTime().toSecsSinceEpoch(), UTC)
            end = dt.datetime.fromtimestamp(self.end_edit.dateTime().toSecsSinceEpoch(), UTC)
            if start >= end:
                QtWidgets.QMessageBox.warning(self, "Invalid range", "Choose an end time after the start time.")
                return
            self.worker = QueryWorker(start, end, self)
            self.worker.completed.connect(self._loaded)
            self.worker.failed.connect(self._failed)
            self.worker.progress.connect(self.statusBar().showMessage)
            self.worker.finished.connect(self._finished)
            self.query_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.export_button.setEnabled(False)
            self.export_json_button.setEnabled(False)
            self.summary.setText("Querying... Previous results remain visible until the query completes.")
            self.worker.start()

        def _cancel(self) -> None:
            """Request cancellation without blocking the GUI thread."""
            if self.worker is not None:
                self.worker.cancelled.set()
                self.cancel_button.setEnabled(False)
                self.statusBar().showMessage("Cancelling...")

        def _loaded(self, result: object) -> None:
            """Install a completed result and display all source errors alongside successful sources."""
            if not isinstance(result, QueryResult):
                return
            self.result = result
            self.detail.clear()
            self.model.replace(result.events)
            self.sources.setPlainText("\n\n".join(
                f"{status.source}: {status.state.value} ({status.count} matching events)\n{status.message}"
                for status in result.statuses
            ))
            self._filter()
            errors = sum(status.state == SourceState.ERROR for status in result.statuses)
            self.statusBar().showMessage(f"Query complete. {errors} unavailable source(s). See Sources and coverage.")

        def _failed(self, message: str) -> None:
            """Keep previous results on cancellation or unexpected errors and surface the cause."""
            self._filter()
            self.statusBar().showMessage(message)
            if message != "Query cancelled.":
                QtWidgets.QMessageBox.warning(self, "Query failed", message)

        def _finished(self) -> None:
            """Release the finished worker; close only after cancellation has reaped its child."""
            worker, self.worker = self.worker, None
            if worker is not None:
                worker.deleteLater()
            self.query_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(self.proxy.rowCount() > 0)
            if self.closing:
                self.close()

        def _select_types(self, checked: bool) -> None:
            """Toggle all event types with one final proxy refresh."""
            for checkbox in self.checkboxes.values():
                blocker = QtCore.QSignalBlocker(checkbox)
                checkbox.setChecked(checked)
                del blocker
            self._filter()

        def _filter(self) -> None:
            """Apply checkbox states to cached events and update the result count."""
            if not hasattr(self, "proxy"):
                return
            self.proxy.allowed = {kind for kind, checkbox in self.checkboxes.items() if checkbox.isChecked()}
            self.proxy.invalidate()
            self.detail.clear()
            self.export_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            if self.result is None:
                self.summary.setText("No query results yet.")
                return
            start = self.result.start.astimezone().strftime(TIMESTAMP_FORMAT)
            end = self.result.end.astimezone().strftime(TIMESTAMP_FORMAT)
            self.summary.setText(f"{self.proxy.rowCount():,} shown / {len(self.model.events):,} loaded  |  {start} to {end}")

        def _show_detail(self) -> None:
            """Show the selected row's metadata and original evidence without interpreting it as HTML."""
            index = self.table.currentIndex()
            if not index.isValid():
                self.detail.clear()
                return
            event = self.model.events[self.proxy.mapToSource(index).row()]
            self.detail.setPlainText(
                f"Time: {event.timestamp.astimezone().isoformat()}\nEvent: {event.kind.value}\n"
                f"Source: {event.source}\nSession: {event.session or 'Not recorded'}\n"
                f"Boot ID: {event.boot_id or 'Not recorded'}\nRecord ID: {event.record_id or 'Not recorded'}\n"
                f"\n{event.summary}\n\nOriginal evidence:\n{event.raw}"
            )

        def _export(self, suffix: str) -> None:
            """Save visible rows in display order using the requested .csv or .json format."""
            if self.result is None:
                return
            format_name = suffix[1:].upper()
            filename, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, f"Export visible events as {format_name}", f"power-events{suffix}",
                f"{format_name} (*{suffix})",
            )
            if not filename:
                return
            path = Path(filename)
            if not path.suffix:
                path = path.with_suffix(suffix)
                if path.exists() and QtWidgets.QMessageBox.question(self, "Replace file?", f"Replace {path.name}?") != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            if path.suffix.lower() != suffix:
                QtWidgets.QMessageBox.warning(self, "Invalid extension", f"Choose a {suffix} export file.")
                return
            events = [self.model.events[self.proxy.mapToSource(self.proxy.index(row, 0)).row()]
                      for row in range(self.proxy.rowCount())]
            try:
                export_events(path, events, self.result)
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.warning(self, "Export failed", str(exc))
                return
            self.statusBar().showMessage(f"Exported {len(events):,} visible events to {path}")

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:
            """Cancel active collection before closing, then persist presentation preferences."""
            if self.worker is not None:
                self.closing = True
                self._cancel()
                event.ignore()
                return
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("columns", self.table.horizontalHeader().saveState())
            self.settings.setValue("range", self.range_box.currentText())
            self.settings.setValue("types", [kind.value for kind, checkbox in self.checkboxes.items() if checkbox.isChecked()])
            for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                self.settings.setValue(key, editor.dateTime().toString(QtCore.Qt.DateFormat.ISODate))
            super().closeEvent(event)

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A non-GUI Qt application is already running.")
    window = PowerEventsWindow()
    window.show()
    # Keep a reference when embedded in another Qt session (also used by GUI tests).
    application.setProperty("powerEventsWindow", window)
    return application.exec() if owns_application else 0


def main() -> int:
    """Launch the GUI or print help, returning nonzero for missing requirements.

    Reads sys.argv, prints English diagnostics and opens a GUI. The GUI reads
    system logs, saves display preferences and writes only user-requested exports.
    Ctrl+C propagates to the module-level handler.
    """
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        Console.print_banner("POWER EVENTS")
        print(f"""{FGray}Usage:
  python power-events.py
  python power-events.py --help

Description:
  GUI history viewer for startup, shutdown, sleep, wake, lock and unlock.
  Choose a local date/time range; check event types to show or hide loaded rows.
  Supports cancellation, raw evidence and saved display preferences.
  Export CSV / Export JSON saves visible rows in their current display order.
  CSV uses UTF-8 without BOM and local timestamps with UTC offsets.
  Queries the last 24 hours initially. No monitoring service is installed.
  Availability depends on retained logs and permissions; missing events are not
  proof of absence. Linux lock history and Windows Modern Standby are limited.

Options:
  --help, -h   Show this help without opening the GUI or reading logs.

Requirements:
  Python package: PySide6.
  macOS: built-in pmset, log, last and sysctl.
  Windows 10+: PowerShell; Security log access/auditing for lock events.
  Linux desktop: systemd journalctl; access to system logs.
{CRst}""")
        return 0
    if sys.argv[1:]:
        print(f"{FLRed}Unknown arguments: {sys.argv[1:]!r}. Use --help.{CRst}", file=sys.stderr)
        return 1
    if sys.platform not in ("darwin", "win32", "linux"):
        print(f"{FLRed}Unsupported platform: {sys.platform}{CRst}", file=sys.stderr)
        return 1
    if System.is_headless():
        print(f"{FLRed}This version requires a graphical desktop.{CRst}", file=sys.stderr)
        return 1
    try:
        return _launch_gui()
    except ImportError as exc:
        print(f"{FLRed}GUI dependency unavailable: {exc}. Install PySide6 in this Python environment.{CRst}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
