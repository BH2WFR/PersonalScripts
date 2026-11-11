"""System event viewer: macos implementation."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import cast
from .models import (
    ACTIVITY_EVENT_KINDS,
    COMMAND_TIMEOUT,
    DIAGNOSTIC_EVENT_KINDS,
    EventKind,
    MAC_REPORT_SUFFIXES,
    MAX_REPORT_BYTES,
    MAX_REPORT_FILES,
    MAX_REPORT_TOTAL_BYTES,
    MAX_EVENTS,
    MONTHS,
    PLATFORM_EVENT_KINDS,
    PowerEvent,
    QueryResult,
    SSH_PROCESSES,
    SourceState,
    SourceStatus,
    TIMESTAMP_FORMAT,
    UTC,
)
from . import common
from .macos_activity import activity_predicate, parse_activity


ACTIVITY_QUERY_WORKERS = 4
ACTIVITY_QUERY_MIN_SPAN = dt.timedelta(hours=6)


def _parse_pmset(text: str) -> list[PowerEvent]:
    """Parse actual pmset state records, excluding Wake Requests and client acknowledgements."""
    events: list[PowerEvent] = []
    pattern = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4})\s+(Sleep|Wake|DarkWake)\s{2,}(.+)$")
    kinds = {"Sleep": EventKind.SLEEP, "Wake": EventKind.WAKE,
             "DarkWake": EventKind.DARK_WAKE}
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
    for record in common._json_records(text):
        message = str(record.get("eventMessage", ""))
        match = pattern.search(message)
        if match is None:
            continue
        timestamp = common._timestamp(str(record.get("timestamp", "")))
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



def _parse_mac_ssh(text: str) -> list[PowerEvent]:
    """Read incoming SSH evidence from unified-log server processes only."""
    events: list[PowerEvent] = []
    for record in common._json_records(text):
        process = str(record.get("processImagePath") or record.get("process") or "").rsplit("/", 1)[-1]
        if process not in SSH_PROCESSES:
            continue
        message = str(record.get("eventMessage", ""))
        matched = common._parse_ssh_message(message) or common._parse_auth_failure(message)
        if matched is None:
            continue
        kind, summary, user = matched
        pid = str(record.get("processID", ""))
        session = "; ".join(part for part in (user, f"PID {pid}" if pid else "") if part)
        events.append(PowerEvent(
            common._timestamp(str(record["timestamp"])), kind, summary, f"unified log / {process}",
            str(record.get("machTimestamp", "")), session, str(record.get("bootUUID", "")),
            json.dumps(record, ensure_ascii=False, indent=2),
        ))
    return events



def _parse_mac_report(text: str, path: Path, modified: dt.datetime) -> PowerEvent:
    """Read modern two-object IPS and legacy text reports; unknown formats stay diagnostic.

    A missing/invalid incident timestamp uses explicitly labelled file modification
    time. Spin samples and resource reports do not by themselves establish a hang.
    """
    header: dict[str, object] = {}
    body: dict[str, object] = {}
    if path.suffix.lower() == ".ips":
        decoder = json.JSONDecoder()
        payload = text.lstrip()
        value, end = decoder.raw_decode(payload)
        if not isinstance(value, dict):
            raise ValueError("IPS metadata must be an object.")
        header = cast(dict[str, object], value)
        remaining = payload[end:].strip()
        if remaining:
            value = json.loads(remaining)
            if not isinstance(value, dict):
                raise ValueError("IPS report data must be an object.")
            body = cast(dict[str, object], value)
        else:
            body = header
    fields = {match[1].strip(): match[2].strip() for match in
              re.finditer(r"^([\w /]+):[ \t]*(.+)$", text, re.MULTILINE)}
    kind = EventKind.DIAGNOSTIC
    suffix = path.suffix.lower()
    if body.get("panicString") or suffix == ".panic":
        kind = EventKind.SYSTEM_CRASH
    elif suffix == ".hang" or str(body.get("event") or fields.get("Event", "")).casefold() in ("hang", "unresponsive"):
        kind = EventKind.APP_HANG
    elif (suffix == ".crash" or str(header.get("bug_type")) == "309") and not body.get("isNonFatal"):
        kind = EventKind.APP_CRASH
    name = str(body.get("procName") or header.get("app_name") or header.get("name")
               or fields.get("Process") or fields.get("Command") or path.name)
    summary = f"{kind.value}: {name}"
    stamp = body.get("captureTime") or header.get("timestamp") or fields.get("Date/Time") or fields.get("Date")
    timestamp = modified
    try:
        if not isinstance(stamp, str) or not stamp.strip():
            raise ValueError("Missing report timestamp")
        timestamp = common._timestamp(re.sub(r"\s+([+-]\d{4})$", r"\1", stamp.strip()))
    except ValueError:
        summary += "; file modification time (incident time unavailable)"
    for label, value in (("Exception", body.get("exception") or fields.get("Exception Type")),
                         ("Termination", body.get("termination") or fields.get("Termination Reason")),
                         ("Event", body.get("event") or fields.get("Event")),
                         ("Bug type", header.get("bug_type"))):
        if value:
            summary += f"; {label}={json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value}"
    pid = body.get("pid")
    return PowerEvent(timestamp, kind, summary, f"DiagnosticReports / {suffix}", str(path),
                      f"PID {pid}" if pid is not None else "", raw=f"Report: {path}\n\n{text}")



def _collect_mac_reports(result: QueryResult, cancelled: threading.Event, directories: tuple[Path, ...]) -> None:
    """Read bounded, local diagnostic report files without following links or unpacking dumps."""
    deadline = time.monotonic() + COMMAND_TIMEOUT
    total_bytes = 0
    scanned = 0
    for directory in directories:
        for folder in (directory, directory / "Retired"):
            source = str(folder)
            count = 0
            problems: list[str] = []
            skipped = 0
            try:
                if cancelled.is_set():
                    raise InterruptedError("Query cancelled.")
                if folder.is_symlink():
                    result.statuses.append(SourceStatus(source, SourceState.LIMITED, "Linked report directories are not followed."))
                    continue
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if cancelled.is_set():
                            raise InterruptedError("Query cancelled.")
                        if time.monotonic() >= deadline or scanned >= MAX_REPORT_FILES or total_bytes >= MAX_REPORT_TOTAL_BYTES:
                            result.statuses.append(SourceStatus(source, SourceState.LIMITED,
                                "Diagnostic report scan limit reached; some reports were not read.", count))
                            return
                        path = Path(entry.path)
                        if path.suffix.lower() not in MAC_REPORT_SUFFIXES or not entry.is_file(follow_symlinks=False):
                            continue
                        scanned += 1
                        try:
                            stat = entry.stat(follow_symlinks=False)
                            if stat.st_size > MAX_REPORT_BYTES:
                                raise ValueError("Report exceeds the 8 MiB per-file limit.")
                            if total_bytes + stat.st_size > MAX_REPORT_TOTAL_BYTES:
                                result.statuses.append(SourceStatus(source, SourceState.LIMITED,
                                    "Diagnostic report byte limit reached; some reports were not read.", count))
                                return
                            with path.open("rb") as stream:
                                raw = stream.read(MAX_REPORT_BYTES + 1)
                            total_bytes += len(raw)
                            if len(raw) > MAX_REPORT_BYTES:
                                raise ValueError("Report exceeds the 8 MiB per-file limit.")
                            text = raw.decode("utf-8-sig")
                            if "\x00" in text:
                                raise ValueError("Binary diagnostic reports are not supported.")
                            event = _parse_mac_report(text, path, dt.datetime.fromtimestamp(stat.st_mtime, UTC))
                            if result.start <= event.timestamp < result.end:
                                result.events.append(event)
                                count += 1
                        except (OSError, ValueError) as exc:
                            skipped += 1
                            if len(problems) < 3:
                                problems.append(f"{path.name}: {exc}")
                state = SourceState.LIMITED if skipped else SourceState.OK if count else SourceState.EMPTY
                detail = f"Skipped {skipped} report(s). {'; '.join(problems)}" if skipped else "Retained text/IPS reports queried."
                result.statuses.append(SourceStatus(source, state, detail, count))
            except FileNotFoundError:
                result.statuses.append(SourceStatus(source, SourceState.EMPTY, "Report directory does not exist."))
            except OSError as exc:
                # InterruptedError is an OSError subclass; cancellation must escape.
                if isinstance(exc, InterruptedError):
                    raise
                result.statuses.append(SourceStatus(source, SourceState.ERROR, str(exc), count))



def _collect_current_boot(result: QueryResult, cancelled: threading.Event) -> None:
    """Read precise current boot time and replace its minute-resolution last record."""
    try:
        text, _ = common._run_command(["/usr/sbin/sysctl", "-n", "kern.boottime"], cancelled)
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


def _collect_mac_activity(
    result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None],
    selected_kinds: frozenset[EventKind],
) -> None:
    """Read long activity ranges in up to four independent, cancellable time slices.

    Each slice retains its own source limits and status, so a failed or truncated
    period cannot hide readable periods. Half-open filtering removes records at
    the next slice's boundary even if log show includes its end timestamp.
    """
    duration = result.end - result.start
    workers = max(1, min(ACTIVITY_QUERY_WORKERS, duration // ACTIVITY_QUERY_MIN_SPAN))
    predicate = activity_predicate(selected_kinds)
    # Whole-second internal boundaries match log show's command-line precision.
    seconds = int(duration.total_seconds())
    boundaries = [result.start] + [
        (result.start + dt.timedelta(seconds=seconds * index // workers)).replace(microsecond=0)
        for index in range(1, workers)
    ] + [result.end]

    def collect_slice(index: int) -> QueryResult:
        """Keep each subprocess's events and availability diagnostics isolated."""
        part = QueryResult(boundaries[index], boundaries[index + 1])
        source = "System activity"
        if workers > 1:
            source += f" [{part.start:%Y-%m-%d %H:%M:%S} / {part.end:%Y-%m-%d %H:%M:%S} UTC)"
        common._collect_source(part, source, [
            "/usr/bin/log", "show", "--style", "ndjson", "--info",
            "--start", part.start.strftime("%Y-%m-%d %H:%M:%S+0000"),
            "--end", part.end.strftime("%Y-%m-%d %H:%M:%S+0000"), "--predicate", predicate,
        ], parse_activity, cancelled, record_limit=MAX_EVENTS, stream_ndjson=True)
        return part

    progress("Reading system activity and maintenance history...")
    if workers == 1:
        parts = [collect_slice(0)]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="macos-log") as pool:
            futures = [pool.submit(collect_slice, index) for index in range(workers)]
            try:
                for completed, future in enumerate(as_completed(futures), 1):
                    future.result()
                    if cancelled.is_set():
                        raise InterruptedError("Query cancelled.")
                    progress(f"Reading system activity: {completed}/{workers} time ranges complete...")
                parts = [future.result() for future in futures]
            except BaseException:
                cancelled.set()
                raise
    for part in parts:
        result.events.extend(part.events)
        result.statuses.extend(part.statuses)


def _collect_macos(
    result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None],
    *, selected_kinds: frozenset[EventKind] | None = None,
) -> None:
    """Read only sources needed by selected categories; omitted selection retains full coverage."""
    available = PLATFORM_EVENT_KINDS["darwin"]
    selected = available if selected_kinds is None else selected_kinds & available
    if not selected:
        return
    if selected & {EventKind.SLEEP, EventKind.WAKE, EventKind.DARK_WAKE}:
        progress("Reading sleep and wake history...")
        common._collect_source(result, "Power history", ["/usr/bin/pmset", "-g", "log"], _parse_pmset, cancelled)
    if selected & {EventKind.LOCK, EventKind.UNLOCK}:
        progress("Reading lock and unlock notifications...")
        predicate = 'process == "loginwindow" AND eventMessage CONTAINS "sendDistributedNotification: com.apple.screenIs"'
        common._collect_source(result, "Screen sessions", [
            "/usr/bin/log", "show", "--style", "ndjson", "--info",
            "--start", result.start.strftime("%Y-%m-%d %H:%M:%S+0000"),
            "--end", result.end.strftime("%Y-%m-%d %H:%M:%S+0000"), "--predicate", predicate,
        ], _parse_mac_sessions, cancelled, record_limit=MAX_EVENTS, stream_ndjson=True)
    if selected & {EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT, EventKind.AUTHENTICATION}:
        progress("Reading incoming SSH history...")
        ssh_predicate = " OR ".join(f'process == "{process}"' for process in sorted(SSH_PROCESSES))
        common._collect_source(result, "OpenSSH server", [
            "/usr/bin/log", "show", "--style", "ndjson", "--info",
            "--start", result.start.strftime("%Y-%m-%d %H:%M:%S+0000"),
            "--end", result.end.strftime("%Y-%m-%d %H:%M:%S+0000"), "--predicate", ssh_predicate,
        ], _parse_mac_ssh, cancelled, record_limit=MAX_EVENTS, stream_ndjson=True)
    if selected & {EventKind.STARTUP, EventKind.SHUTDOWN}:
        progress("Reading startup and shutdown history...")
        common._collect_source(result, "Boot history", ["/usr/bin/last", "-y", "reboot", "shutdown"], _parse_mac_last, cancelled)
        if EventKind.STARTUP in selected:
            _collect_current_boot(result, cancelled)
    if selected & DIAGNOSTIC_EVENT_KINDS:
        progress("Reading crash, hang and diagnostic reports...")
        _collect_mac_reports(result, cancelled, (Path.home() / "Library/Logs/DiagnosticReports",
                                               Path("/Library/Logs/DiagnosticReports")))
    if selected & ACTIVITY_EVENT_KINDS:
        _collect_mac_activity(result, cancelled, progress, selected)
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "Only sources needed by the selected event types were queried. "
        "Lock/unlock uses explicit loginwindow notifications; macOS versions and log retention vary. "
        "Older boot records have minute precision. Background wakes do not imply user activity. "
        "Separate hibernation transitions are not collected; HibernateStats alone is not a transition. "
        "SSH requires retained sshd unified logs; private/redacted fields may prevent recognition. "
        "RDP and general desktop logon/logoff history are only collected on Windows. "
        "Diagnostics cover the current user's and system DiagnosticReports (including Retired), not other users, "
        "archives or binary dumps. Spin samples alone are not hangs; missing report times use labelled file times. "
        "Report reads are limited to 8 MiB per file, 64 MiB total and 5,000 files per query. "
        "Activity uses explicit powerd, timed, authentication, installer, kernel memory/filesystem, launchd, "
        "device and network-service messages. macOS versions, privacy redaction and log levels affect recognition; "
        "these are native log observations, not a complete device, battery or connection timeline."))

