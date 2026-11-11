#!/usr/bin/env python3
"""Implementation notes.

Choose a relative or custom local-time range, query in a cancellable worker,
and toggle event checkboxes without rescanning logs. Select a row for its raw
evidence; use Export CSV or Export JSON to save visible rows in display order.
CSV uses UTF-8 without BOM and includes local timestamps with UTC offsets.
Window geometry, columns, relative range and type filters persist through
QSettings; retain its existing organization/application identity when renaming.
No service is
installed and no auditing, logging or power settings are changed.

Sources:
    macOS: pmset sleep/wake history, explicit loginwindow lock notifications,
        last reboot/shutdown records (minute precision), current kern.boottime.
    Windows 10+: PowerShell Get-WinEvent; provider-qualified System, Security,
        TerminalServices-LocalSessionManager and OpenSSH records. Includes
        Modern Standby entry/exit (506/507) and auxiliary power-session
        transitions (566), with reported reasons,
        sleep/DRIPS durations and session identifiers when available.
        Security access and prior auditing are required for lock/unlock and
        interactive logon/logoff. RDP connections require explicit remote
        address or RDP station evidence; console switches are not RDP.
    Linux: systemd journal kernel/logind/sleep/shutdown records. Lock history
        is limited to explicit logind session transitions; desktop support and
        journal persistence/permissions vary. Non-systemd Linux is unsupported.
    SSH: local OpenSSH server logs (Windows Event Log, Linux journal or macOS
        unified log). Accepted authentication is a connection; transport closes
        without a user are marked authentication unknown. Pre-auth closes and
        failed attempts are excluded. File-only logs and outgoing clients are
        not collected. Separate native observations are retained, not merged.

Limits:
    History depends on retained accessible logs. Missing records are not proof
    of absence. Shutdown initiation is not proof of completed power-off; an
    unexpected restart is timestamped when reported, not at the earlier outage.
    Screen blanking, unlock requests and wake scheduling are not state changes.
    Modern Standby entry/exit is separate from traditional sleep/wake: entry
    alone does not establish low-power residency, and exit may be internal.
    These records do not by themselves establish a Wake-on-LAN wake source.
    Source commands time out after 90 seconds. At most 50,000 normalized events
    are displayed; narrow the query when the limit is reached. No usage-duration
    inference or background recording is performed in this version.
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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

HELP = f"""{FLYellow}POWER EVENT VIEWER{CRst}

Inspect and export power, lock/unlock and incoming SSH history, plus Windows
interactive logon/logoff and RDP connections. Includes Windows Modern Standby.
History depends on retained logs; power transitions alone do not prove Wake-on-LAN.

{FLYellow}Requirements:{CRst}
  PySide6; Windows PowerShell, macOS log/pmset/last/sysctl, or Linux journalctl.
  Security log access and prior auditing for Windows lock/logon history.
  OpenSSH server logs for SSH; file-only logs are not read. Linux locks are limited.

{FLYellow}Usage:{CRst}
  python power-event-viewer.py
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


UTC = dt.timezone.utc
COMMAND_TIMEOUT = 90.0
POLL_SECONDS = 0.2
MAX_EVENTS = 50_000
DEFAULT_SIZE = (1200, 800)
GUI_STYLE = "Fusion"
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
    STANDBY_ENTER = "Modern standby entry"
    STANDBY_EXIT = "Modern standby exit"
    POWER_SESSION = "Power session transition"
    LOGON = "Logon"
    LOGOFF = "Logoff"
    RDP_CONNECT = "RDP connection"
    RDP_RECONNECT = "RDP reconnection"
    RDP_DISCONNECT = "RDP disconnection"
    SSH_CONNECT = "SSH connection"
    SSH_DISCONNECT = "SSH disconnection"


WINDOWS_MODERN_EVENTS: dict[int, tuple[EventKind, str]] = {
    506: (EventKind.STANDBY_ENTER, "Entering Modern Standby"),
    507: (EventKind.STANDBY_EXIT, "Exiting Modern Standby"),
    566: (EventKind.POWER_SESSION, "Power session state changed"),
}
MODERN_EVENT_KINDS: frozenset[EventKind] = frozenset(kind for kind, _ in WINDOWS_MODERN_EVENTS.values())
LOGIN_EVENT_KINDS: frozenset[EventKind] = frozenset({
    EventKind.LOGON, EventKind.LOGOFF, EventKind.RDP_CONNECT, EventKind.RDP_RECONNECT,
    EventKind.RDP_DISCONNECT, EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT,
})
SECURITY_PROVIDER = "Microsoft-Windows-Security-Auditing"
RDP_PROVIDER = "Microsoft-Windows-TerminalServices-LocalSessionManager"
SSH_PROCESSES: frozenset[str] = frozenset({"sshd", "sshd-session", "sshd-auth"})
INTERACTIVE_LOGON_TYPES: dict[str, str] = {
    "2": "Interactive", "10": "Remote interactive (RDP)",
    "11": "Cached interactive", "12": "Cached remote interactive",
}
WINDOWS_DURATION_FIELDS: tuple[tuple[str, str], ...] = (
    ("DurationInUs", "Session duration"),
    ("ScreenOffDurationInUs", "Screen-off duration"),
    ("SleepDurationInUs", "Sleep duration"),
    ("DripsResidencyInUs", "Software DRIPS"),
    ("HwDripsResidencyInUs", "Hardware DRIPS"),
    ("PreviousSessionDurationInUs", "Previous session duration"),
)
MICROSECONDS_PER_SECOND = 1_000_000
FILTER_COLUMNS = 6


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
    XML is retained separately for structured viewing; raw keeps complete evidence.
    """

    timestamp: dt.datetime
    kind: EventKind
    summary: str
    source: str
    record_id: str = ""
    session: str = ""
    boot_id: str = ""
    raw: str = ""
    xml: str = ""


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


def _parse_ssh_message(message: str) -> tuple[EventKind, str, str] | None:
    """Interpret trusted sshd messages; authentication attempts are not connections.

    The caller must verify the server process/provider. A transport-only close
    has no implied authenticated user. Addresses and ports identify endpoints,
    not a synthetic session ID, and records are never paired across queries.
    """
    message = re.sub(r"^sshd(?:-session|-auth)?(?:\[\d+\])?:\s*", "", message.strip())
    if "[preauth]" in message or re.search(r"\b(?:invalid|authenticating) user\b", message):
        return None
    accepted = re.match(r"^Accepted (\S+) for (.+?) from (\S+) port (\d+)\b", message)
    if accepted:
        method, user, address, port = accepted.groups()
        return (EventKind.SSH_CONNECT, f"SSH authentication accepted ({method}); client {address} port {port}", user)
    closed = re.match(
        r"^(?:Disconnected from|Connection (?:closed|reset) by|Received disconnect from) "
        r"(?:user (.+?) )?(\S+) port (\d+)\b", message,
    )
    if closed:
        user, address, port = closed.groups()
        summary = f"SSH transport disconnected; client {address} port {port}"
        if not user:
            summary += "; authentication unknown in this record"
        return EventKind.SSH_DISCONNECT, summary, user or ""
    return None


def _parse_mac_ssh(text: str) -> list[PowerEvent]:
    """Read incoming SSH evidence from unified-log server processes only."""
    events: list[PowerEvent] = []
    for record in _json_records(text):
        process = str(record.get("processImagePath") or record.get("process") or "").rsplit("/", 1)[-1]
        if process not in SSH_PROCESSES:
            continue
        matched = _parse_ssh_message(str(record.get("eventMessage", "")))
        if matched is None:
            continue
        kind, summary, user = matched
        pid = str(record.get("processID", ""))
        session = "; ".join(part for part in (user, f"PID {pid}" if pid else "") if part)
        events.append(PowerEvent(
            _timestamp(str(record["timestamp"])), kind, summary, f"unified log / {process}",
            str(record.get("machTimestamp", "")), session, str(record.get("bootUUID", "")),
            json.dumps(record, ensure_ascii=False, indent=2),
        ))
    return events


def _windows_session_event(source: str, event_id: int, data: dict[str, str]) -> tuple[EventKind, str, str] | None:
    """Map audited interactive and Terminal Services observations without guessing RDP."""
    user = data.get("TargetUserName") or data.get("AccountName") or data.get("User", "")
    domain = data.get("TargetDomainName") or data.get("AccountDomain", "")
    if domain and domain != "-" and user:
        user = f"{domain}\\{user}"
    session_id = data.get("SessionId") or data.get("SessionID", "")
    session = f"{user} (session {session_id})" if session_id else user
    logon_id = data.get("TargetLogonId") or data.get("LogonID", "")
    if logon_id:
        session = "; ".join(part for part in (session, f"logon {logon_id}") if part)
    kind: EventKind
    summary: str
    if source == SECURITY_PROVIDER:
        if event_id in (4800, 4801):
            kind = EventKind.LOCK if event_id == 4800 else EventKind.UNLOCK
            summary = "Workstation locked" if event_id == 4800 else "Workstation unlocked"
        elif event_id in (4624, 4634):
            logon_type = data.get("LogonType", "")
            if logon_type not in INTERACTIVE_LOGON_TYPES:
                return None
            # Windows desktop helpers create interactive logons too; they are not people.
            if data.get("TargetUserSid", "").startswith(("S-1-5-90-", "S-1-5-96-")):
                return None
            kind = EventKind.LOGON if event_id == 4624 else EventKind.LOGOFF
            summary = f"{INTERACTIVE_LOGON_TYPES[logon_type]} {kind.value.lower()} (type {logon_type})"
        elif event_id in (4778, 4779):
            station = data.get("SessionName", "")
            if not station.lower().startswith("rdp-tcp"):
                return None
            kind = EventKind.RDP_RECONNECT if event_id == 4778 else EventKind.RDP_DISCONNECT
            summary = f"{kind.value}; station {station}"
        else:
            return None
        address = data.get("ClientAddress") or data.get("IpAddress", "")
    elif source == RDP_PROVIDER:
        address = data.get("Address", "")
        remote = address.casefold() not in ("", "-", "local", "unknown", "0.0.0.0", "::")
        if event_id == 21:
            kind = EventKind.RDP_CONNECT if remote else EventKind.LOGON
            summary = "RDP session logon succeeded" if remote else "Terminal Services session logon (RDP not established by this record)"
        elif event_id == 23:
            # This record has no address; do not infer its transport from another session.
            kind, summary = EventKind.LOGOFF, "Terminal Services session logoff succeeded"
        elif event_id in (24, 25) and remote:
            kind = EventKind.RDP_DISCONNECT if event_id == 24 else EventKind.RDP_RECONNECT
            summary = kind.value
        else:
            return None
    else:
        return None
    if address and address != "-":
        summary += f"; client {address}"
    if data.get("ClientName") and data["ClientName"] != "-":
        summary += f"; client name {data['ClientName']}"
    return kind, summary, session


def _parse_windows_xml(xml: str, message: str = "") -> list[PowerEvent]:
    """Map provider-qualified Windows power and login records, preserving their evidence.

    Args:
        xml: Native event XML with provider, timestamp and optional event data.
        message: Optional OS-rendered description, including localized reasons.

    Returns:
        One observation for a supported provider/event pair, otherwise no rows.
        Missing optional metrics stay absent; unknown reason codes stay numeric.
        Power-Troubleshooter uses its embedded wake time when available.

    Raises:
        ET.ParseError: If XML is malformed.
        ValueError: If the event ID or required timestamp is malformed.
    """
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
    # TerminalServices uses UserData/EventXML in its own XML namespace.
    user_data = root.find("e:UserData", XML_NS)
    if user_data is not None:
        data.update({node.tag.rsplit("}", 1)[-1]: node.text or ""
                     for node in user_data.iter() if len(node) == 0})
    session_event = _windows_session_event(source, event_id, data)
    if source == "OpenSSH":
        process = data.get("process", "").lower().removesuffix(".exe")
        if process not in SSH_PROCESSES:
            return []
        session_event = _parse_ssh_message(data.get("payload") or message)
        if session_event is None:
            return []
    mapping: dict[tuple[str, int], tuple[EventKind, str]] = {
        ("Microsoft-Windows-Kernel-General", 12): (EventKind.STARTUP, "Operating system started"),
        ("Microsoft-Windows-Kernel-General", 13): (EventKind.SHUTDOWN, "Operating system shutdown initiated"),
        ("Microsoft-Windows-Kernel-Power", 42): (EventKind.SLEEP, "Entering low-power state"),
        ("Microsoft-Windows-Kernel-Power", 107): (EventKind.WAKE, "System resumed from sleep"),
        ("Microsoft-Windows-Kernel-Power", 41): (EventKind.UNEXPECTED_RESTART, "Previous shutdown was unclean; timestamp is the subsequent report"),
        ("Microsoft-Windows-Power-Troubleshooter", 1): (EventKind.WAKE, "System returned from low-power state"),
        ("User32", 1074): (EventKind.POWER_REQUEST, "Shutdown/restart requested (not completion)"),
        ("USER32", 1074): (EventKind.POWER_REQUEST, "Shutdown/restart requested (not completion)"),
    }
    mapping.update({("Microsoft-Windows-Kernel-Power", event_id): value
                    for event_id, value in WINDOWS_MODERN_EVENTS.items()})
    matched = mapping.get((source, event_id))
    if matched is None and session_event is None:
        return []
    if session_event is not None:
        kind, summary, session = session_event
    else:
        assert matched is not None
        kind, summary = matched
        session = ""
    if kind == EventKind.SLEEP and data.get("TargetState") == "5":
        kind, summary = EventKind.HIBERNATE, "Entering hibernation"
    if source == "Microsoft-Windows-Power-Troubleshooter" and data.get("WakeTime"):
        timestamp = _timestamp(data["WakeTime"])
    if source == "OpenSSH":
        execution = system.find("e:Execution", XML_NS)
        pid = execution.get("ProcessID", "") if execution is not None else ""
        if pid:
            session = "; ".join(part for part in (session, f"PID {pid}") if part)
    # ── Modern Standby evidence ────────────────────
    if kind in MODERN_EVENT_KINDS:
        details = [" ".join(message.split()) or summary]
        for key in ("Reason", "MonitorReason", "SleepEntered", "IsCsSessionInProgressOnExit",
                    "PreviousSessionType", "NextSessionType"):
            if data.get(key):
                details.append(f"{key}={data[key]}")
        for key, label in WINDOWS_DURATION_FIELDS:
            value = data.get(key, "")
            if value:
                # Preserve unfamiliar values rather than discarding the entire event.
                duration = f"{int(value) / MICROSECONDS_PER_SECOND:,.3f} s" if value.isdecimal() else f"{value} us"
                details.append(f"{label}={duration}")
        summary = "; ".join(details)
        if kind == EventKind.POWER_SESSION:
            session = f"{data.get('PreviousSessionId', '?')} -> {data.get('NextSessionId', '?')}"
        else:
            session = "; ".join(f"{key}={data[key]}" for key in ("ScenarioInstanceId", "ScenarioInstanceIdV2") if data.get(key))
    return [PowerEvent(
        timestamp, kind, summary, f"{source} / {event_id}",
        system.findtext("e:EventRecordID", "", XML_NS),
        session, boot_id=data.get("BootId", ""),
        raw=f"Rendered message:\n{message}\n\nXML:\n{xml}" if message else xml,
        xml=xml,
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
        elif identifier in SSH_PROCESSES or str(record.get("_COMM", "")) in SSH_PROCESSES:
            matched = _parse_ssh_message(message)
            if matched:
                kind, summary, session = matched
                pid = str(record.get("_PID", ""))
                if pid:
                    session = "; ".join(part for part in (session, f"PID {pid}") if part)
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
    progress("Reading incoming SSH history...")
    ssh_predicate = " OR ".join(f'process == "{process}"' for process in sorted(SSH_PROCESSES))
    _collect_source(result, "OpenSSH server", [
        "/usr/bin/log", "show", "--style", "ndjson", "--info",
        "--start", result.start.strftime("%Y-%m-%d %H:%M:%S+0000"),
        "--end", result.end.strftime("%Y-%m-%d %H:%M:%S+0000"), "--predicate", ssh_predicate,
    ], _parse_mac_ssh, cancelled)
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
        "Older boot records have minute precision. Background wakes do not imply user activity. "
        "SSH requires retained sshd unified logs; private/redacted fields may prevent recognition. "
        "RDP and general desktop logon/logoff history are only collected on Windows."))


def _collect_windows(result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None]) -> None:
    """Read provider-qualified event XML through PowerShell, retaining access errors per source."""
    executable = Environment.find_pwsh()
    if executable is None:
        result.statuses.append(SourceStatus("Windows Event Log", SourceState.ERROR, "PowerShell was not found."))
        return
    progress("Reading Windows power, logon, RDP and OpenSSH event logs...")
    script = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
# Get-WinEvent's hashtable filter interprets clock values as local even with Kind=Utc.
# Normalize to local wall time here; Python still applies the exact half-open UTC bounds.
$start = [DateTimeOffset]::Parse('__START__').LocalDateTime
$end = [DateTimeOffset]::Parse('__END__').LocalDateTime
$sources = @(
    @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=@(12,13)},
    @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(41,42,107,506,507,566)},
    @{LogName='System'; ProviderName='Microsoft-Windows-Power-Troubleshooter'; Id=@(1)},
    @{LogName='System'; ProviderName='User32'; Id=@(1074)},
    @{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4800,4801,4778,4779)},
    @{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4624,4634)},
    @{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'; ProviderName='Microsoft-Windows-TerminalServices-LocalSessionManager'; Id=@(21,23,24,25)},
    @{LogName='OpenSSH/Operational'; ProviderName='OpenSSH'},
    @{LogName='OpenSSH/Admin'; ProviderName='OpenSSH'}
)
foreach ($filter in $sources) {
    $label = "$($filter.LogName) / $($filter.ProviderName)"
    if ($filter.Id) { $label += " / IDs $($filter.Id -join ',')" }
    $filter.StartTime = $start
    $filter.EndTime = $end
    $count = 0
    try {
        $query = @{FilterHashtable=$filter; MaxEvents=50001; ErrorAction='Stop'}
        if ($filter.Id -contains 4624) {
            # Filter before the limit: network/service logons otherwise crowd out people.
            $utcStart = $start.ToUniversalTime().ToString('o')
            $utcEnd = $end.ToUniversalTime().ToString('o')
            $xpath = "*[System[Provider[@Name='Microsoft-Windows-Security-Auditing'] and (EventID=4624 or EventID=4634) and TimeCreated[@SystemTime >= '$utcStart' and @SystemTime < '$utcEnd']] and EventData[__LOGON_TYPES__]]"
            $query = @{LogName='Security'; FilterXPath=$xpath; MaxEvents=50001; ErrorAction='Stop'}
        }
        Get-WinEvent @query | ForEach-Object {
            $description = ''
            # Missing provider message resources must not prevent reading the XML evidence.
            try { $description = $_.FormatDescription() } catch { }
            @{kind='event'; xml=$_.ToXml(); message=$description} | ConvertTo-Json -Compress
            $count++
        }
        @{kind='status'; source=$label; state='Read'; count=$count; message='Accessible retained records queried.'} | ConvertTo-Json -Compress
    } catch {
        $state = if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') {'No matches'} else {'Unavailable'}
        @{kind='status'; source=$label; state=$state; count=$count; message=$_.Exception.Message} | ConvertTo-Json -Compress
    }
}
""".replace("__START__", result.start.isoformat()).replace("__END__", result.end.isoformat()).replace(
        "__LOGON_TYPES__", " or ".join(f"Data[@Name='LogonType']='{value}'" for value in INTERACTIVE_LOGON_TYPES),
    )
    try:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        text, _ = _run_command([executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], cancelled)
        for record in _json_records(text):
            if record.get("kind") == "event":
                result.events.extend(_parse_windows_xml(str(record["xml"]), str(record.get("message") or "")))
            elif record.get("kind") == "status":
                count = int(str(record.get("count", 0)))
                result.statuses.append(SourceStatus(str(record["source"]), SourceState(str(record["state"])), str(record["message"]), count))
                if count > MAX_EVENTS:
                    result.statuses.append(SourceStatus("Result limit", SourceState.LIMITED, "A source reached the event limit; narrow the time range."))
    except (RuntimeError, ValueError, KeyError, ET.ParseError) as exc:
        result.statuses.append(SourceStatus("Windows Event Log", SourceState.ERROR, str(exc)))
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "Lock/unlock requires prior Other Logon/Logoff auditing and Security log access. "
        "Interactive logon/logoff requires Logon/Logoff auditing (types 2/10/11/12 only); "
        "network, service and batch logons are excluded. RDP also uses TerminalServices operational logs. "
        "SSH reads local OpenSSH server Operational/Admin channels, not file-only or outgoing client logs. "
        "SSH authentication success is separate from a transport close; unnamed closes have unknown authentication. "
        "Multiple sources can report the same session; rows are observations, not unique login counts. "
        "Modern Standby 506/507 and auxiliary session transitions 566 are included. "
        "Entry alone does not prove low-power residency; exit can be internal and is not proof of Wake-on-LAN. "
        "Reported sleep/DRIPS durations are shown when present; missing metrics are not zero. "
        "Unclean shutdown reports are timestamped at the later report."))


def _collect_linux(result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None]) -> None:
    """Read systemd journal power records; report unsupported and limited histories explicitly."""
    executable = Environment.which("journalctl")
    if executable is None:
        result.statuses.append(SourceStatus("systemd journal", SourceState.ERROR, "journalctl was not found; this version requires systemd journal."))
        return
    progress("Reading kernel, systemd and incoming SSH history...")
    command = [executable, "--no-pager", "--output=json", "--since", f"@{int(result.start.timestamp())}",
               "--until", f"@{int(result.end.timestamp())}",
               "_TRANSPORT=kernel", "+", "_SYSTEMD_UNIT=systemd-logind.service", "+",
               "_SYSTEMD_UNIT=systemd-suspend.service", "+", "_SYSTEMD_UNIT=systemd-hibernate.service", "+",
               "_SYSTEMD_UNIT=systemd-suspend-then-hibernate.service", "+", "_SYSTEMD_UNIT=systemd-hybrid-sleep.service", "+",
               "SYSLOG_IDENTIFIER=systemd-shutdown"]
    for process in sorted(SSH_PROCESSES):
        command.extend(["+", f"SYSLOG_IDENTIFIER={process}", "+", f"_COMM={process}"])
    _collect_source(result, "systemd journal", command, _parse_linux_journal, cancelled)
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "History depends on journal retention, persistence and access. Lock/unlock is recognized only "
        "when logind explicitly records the session transition; desktop-only lock signals are not collected. "
        "Missing shutdown records do not prove a crash. SSH reads sshd journal records only; "
        "file-only authentication logs are not collected. Unnamed SSH closes have unknown authentication. "
        "RDP and general desktop logon/logoff history are only collected on Windows."))


def query_events(
    start: dt.datetime, end: dt.datetime, cancelled: threading.Event,
    progress: Callable[[str], None] = lambda _message: None,
) -> QueryResult:
    """Read local power and login history without changing settings or escalating privileges.

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
    from utils.qt_widgets import NoWheelComboBox, install_no_wheel_controls

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
            self.setWindowTitle("Power Event Viewer")
            self.resize(*DEFAULT_SIZE)
            self.settings = QtCore.QSettings(
                QtCore.QSettings.defaultFormat(), QtCore.QSettings.Scope.UserScope,
                "PersonalScripts", "PowerEvents",
            )
            self.worker: QueryWorker | None = None
            self.result: QueryResult | None = None
            self.status_message = ""
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
            self.range_box = NoWheelComboBox()
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
            for text, widget in (("Range", self.range_box), ("From", self.start_edit), ("Until", self.end_edit)):
                label = QtWidgets.QLabel(text)
                label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
                bar.addWidget(label)
                bar.addWidget(widget)
            bar.addSpacing(8)
            divider = QtWidgets.QFrame()
            divider.setFrameShape(QtWidgets.QFrame.Shape.VLine)
            divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            bar.addWidget(divider)
            bar.addSpacing(8)
            bar.addWidget(self.query_button)
            bar.addWidget(self.cancel_button)
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
                filters.addWidget(checkbox, index // FILTER_COLUMNS, index % FILTER_COLUMNS)
            select_all = QtWidgets.QPushButton("All")
            select_none = QtWidgets.QPushButton("None")
            select_all.clicked.connect(lambda: self._select_types(True))
            select_none.clicked.connect(lambda: self._select_types(False))
            for index, button in enumerate((select_all, select_none), start=len(EventKind)):
                filters.addWidget(button, index // FILTER_COLUMNS, index % FILTER_COLUMNS)
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
            rows = self.table.verticalHeader()
            rows.hide()
            row_height = self.table.fontMetrics().height() + 4
            rows.setMinimumSectionSize(row_height)
            rows.setDefaultSectionSize(row_height)
            rows.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
            for index, width in enumerate((155, 380, 220, 160), start=1):
                self.table.setColumnWidth(index, width)
            self.table.selectionModel().selectionChanged.connect(self._show_detail)
            self.detail = QtWidgets.QPlainTextEdit()
            self.detail.setReadOnly(True)
            self.detail.setPlaceholderText("Select an event to inspect its original evidence.")
            xml_page = QtWidgets.QWidget()
            xml_layout = QtWidgets.QVBoxLayout(xml_page)
            xml_layout.setContentsMargins(0, 0, 0, 0)
            self.xml_notice = QtWidgets.QLabel("Select an event to inspect its XML.")
            self.xml_notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.xml_notice.setWordWrap(True)
            self.xml_tree = QtWidgets.QTreeWidget()
            self.xml_tree.setHeaderLabels(["Node", "Value", "Attributes"])
            self.xml_tree.setAlternatingRowColors(True)
            self.xml_tree.setUniformRowHeights(True)
            self.xml_tree.setColumnWidth(0, 240)
            self.xml_tree.setColumnWidth(1, 280)
            self.xml_tree.hide()
            xml_layout.addWidget(self.xml_notice)
            xml_layout.addWidget(self.xml_tree, 1)
            self.sources = QtWidgets.QPlainTextEdit()
            self.sources.setReadOnly(True)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self.detail, "Event details")
            tabs.addTab(xml_page, "XML")
            tabs.addTab(self.sources, "Sources and coverage")
            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
            splitter.addWidget(self.table)
            splitter.addWidget(tabs)
            splitter.setSizes([470, 170])
            layout.addWidget(splitter, 1)
            self.summary = QtWidgets.QLabel("Ready")
            self.summary.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            self.summary.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
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

        def _restore_settings(self) -> None:
            """Restore presentation preferences; relative date ranges are not stored as fixed dates."""
            geometry = self.settings.value("geometry")
            if isinstance(geometry, QtCore.QByteArray):
                self.restoreGeometry(geometry)
            header = self.settings.value("columns")
            if isinstance(header, QtCore.QByteArray):
                self.table.horizontalHeader().restoreState(header)
            # Fit timestamps even when an older saved layout used a wider column.
            self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            value = str(self.settings.value("range", TimeRange.DAY.value))
            index = self.range_box.findText(value)
            self.range_box.setCurrentIndex(max(0, index))
            selected = self.settings.value("types")
            if isinstance(selected, list):
                # Older releases saved only checked types; new categories must remain visible.
                known = self.settings.value("knownTypes", [kind.value for kind in EventKind
                                            if kind not in MODERN_EVENT_KINDS | LOGIN_EVENT_KINDS])
                for kind, checkbox in self.checkboxes.items():
                    if isinstance(known, list) and kind.value in known:
                        checkbox.setChecked(kind.value in selected)
                    else:
                        checkbox.setChecked(kind != EventKind.DARK_WAKE)
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
            self.worker.progress.connect(self._set_status)
            self.worker.finished.connect(self._finished)
            self.query_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.export_button.setEnabled(False)
            self.export_json_button.setEnabled(False)
            self._set_status("Querying...")
            self.worker.start()

        def _cancel(self) -> None:
            """Request cancellation without blocking the GUI thread."""
            if self.worker is not None:
                self.worker.cancelled.set()
                self.cancel_button.setEnabled(False)
                self._set_status("Cancelling...")

        def _loaded(self, result: object) -> None:
            """Install a completed result and display all source errors alongside successful sources."""
            if not isinstance(result, QueryResult):
                return
            self.result = result
            self._clear_details()
            self.model.replace(result.events)
            self.sources.setPlainText("\n\n".join(
                f"{status.source}: {status.state.value} ({status.count} matching events)\n{status.message}"
                for status in result.statuses
            ))
            self.status_message = ""
            self._filter()

        def _failed(self, message: str) -> None:
            """Keep previous results on cancellation or unexpected errors and surface the cause."""
            self._filter()
            self._set_status("Cancelled" if message == "Query cancelled." else "Query failed")
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
            self._clear_details()
            self.export_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            self.export_json_button.setEnabled(self.worker is None and self.proxy.rowCount() > 0)
            self._update_summary()

        def _set_status(self, message: str) -> None:
            """Show query/export feedback in the same footer as the result count."""
            self.status_message = message
            self._update_summary()

        def _update_summary(self) -> None:
            """Keep the footer on one line; retain exact query times in its tooltip."""
            if self.result is None:
                self.summary.setText(self.status_message or "Ready")
                self.summary.setToolTip(self.summary.text())
                return
            shown, total = self.proxy.rowCount(), len(self.model.events)
            count = f"{total:,} events" if shown == total else f"{shown:,} / {total:,} events"
            start, end = self.result.start.astimezone(), self.result.end.astimezone()
            parts = [count, self.status_message or f"{start:%Y-%m-%d %H:%M} – {end:%Y-%m-%d %H:%M}"]
            errors = sum(status.state == SourceState.ERROR for status in self.result.statuses)
            if errors:
                parts.append(f"{errors} source{'s' if errors != 1 else ''} unavailable")
            self.summary.setText("  |  ".join(parts))
            self.summary.setToolTip(
                f"{shown:,} shown / {total:,} loaded\n"
                f"Local range: {start.strftime(TIMESTAMP_FORMAT)} to {end.strftime(TIMESTAMP_FORMAT)} (end exclusive)\n"
                f"{self.status_message or 'Query complete'}. See Sources and coverage for log availability."
            )

        def _clear_details(self) -> None:
            """Clear both evidence views when the selection or query changes."""
            self.detail.clear()
            self.xml_tree.clear()
            self.xml_tree.hide()
            self.xml_notice.setText("Select an event to inspect its XML.")
            self.xml_notice.show()

        def _show_xml(self, event: PowerEvent) -> None:
            """Display XML structure as plain text, preserving child order and namespaces in tooltips."""
            self.xml_tree.clear()
            self.xml_tree.hide()
            self.xml_notice.show()
            if not event.xml:
                self.xml_notice.setText("This event has no XML record. See Event details for its original evidence.")
                return
            try:
                root = ET.fromstring(event.xml)
            except ET.ParseError as exc:
                self.xml_notice.setText(f"Cannot display this XML: {exc}. See Event details for the original record.")
                return
            pending = [(root, self.xml_tree.invisibleRootItem())]
            while pending:
                element, parent = pending.pop()
                name = element.tag.rsplit("}", 1)[-1]
                if name == "Data" and element.get("Name"):
                    name = f"Data [{element.get('Name')}]"
                value = element.text or ""
                attributes = "; ".join(f"{key.rsplit('}', 1)[-1]}={json.dumps(value, ensure_ascii=False)}"
                                       for key, value in element.attrib.items())
                item = QtWidgets.QTreeWidgetItem([name, value.strip(), attributes])
                item.setToolTip(0, element.tag)
                item.setToolTip(1, value)
                item.setToolTip(2, "\n".join(f"{key}={value}" for key, value in element.attrib.items()))
                parent.addChild(item)
                pending.extend((child, item) for child in reversed(element))
            self.xml_tree.expandToDepth(1)
            self.xml_notice.hide()
            self.xml_tree.show()

        def _show_detail(self) -> None:
            """Show the selected row's metadata and original evidence without interpreting it as HTML."""
            index = self.table.currentIndex()
            if not index.isValid():
                self._clear_details()
                return
            event = self.model.events[self.proxy.mapToSource(index).row()]
            self.detail.setPlainText(
                f"Time: {event.timestamp.astimezone().isoformat()}\nEvent: {event.kind.value}\n"
                f"Source: {event.source}\nSession: {event.session or 'Not recorded'}\n"
                f"Boot ID: {event.boot_id or 'Not recorded'}\nRecord ID: {event.record_id or 'Not recorded'}\n"
                f"\n{event.summary}\n\nOriginal evidence:\n{event.raw}"
            )
            self._show_xml(event)

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
            self._set_status(f"Exported {len(events):,} events ({format_name})")
            self.summary.setToolTip(f"{self.summary.toolTip()}\nSaved to: {path}")

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
            self.settings.setValue("knownTypes", [kind.value for kind in EventKind])
            for key, editor in (("start", self.start_edit), ("end", self.end_edit)):
                self.settings.setValue(key, editor.dateTime().toString(QtCore.Qt.DateFormat.ISODate))
            super().closeEvent(event)

    application = QtWidgets.QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QtWidgets.QApplication([sys.argv[0]])
    if not isinstance(application, QtWidgets.QApplication):
        raise RuntimeError("A non-GUI Qt application is already running.")
    application.setStyle(GUI_STYLE)
    install_no_wheel_controls(application)
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
        Console.print_banner("POWER EVENT VIEWER")
        print(HELP)
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
