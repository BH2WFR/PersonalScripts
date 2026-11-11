"""System event viewer: linux implementation."""

from __future__ import annotations

from collections.abc import Callable
import datetime as dt
import json
import re
import threading
from utils import Environment
from .models import (
    COREDUMP_MESSAGE_ID,
    EventKind,
    MAX_EVENTS,
    PowerEvent,
    QueryResult,
    SSH_PROCESSES,
    SourceState,
    SourceStatus,
    UTC,
)
from . import common


ACTIVITY_IDENTIFIERS: tuple[str, ...] = (
    "systemd", "systemd-oomd", "systemd-timesyncd", "chronyd", "ntpd", "upowerd",
    "NetworkManager", "systemd-networkd", "wpa_supplicant", "sudo", "su", "login",
    "PackageKit", "packagekitd", "dnf", "apt", "unattended-upgrade", "fwupd",
)


def _linux_activity_event(record: dict[str, object], message: str) -> tuple[EventKind, str, str] | None:
    """Classify explicit native state/error messages, never arbitrary application text."""
    identifier = str(record.get("SYSLOG_IDENTIFIER", ""))
    kernel = record.get("_TRANSPORT") == "kernel"
    session = str(record.get("UNIT") or record.get("USER_UNIT") or "")
    kind: EventKind | None = None
    if kernel:
        if re.search(r"\b(?:Out of memory:|Killed process \d+|oom-kill:|invoked oom-killer)", message):
            kind = EventKind.RESOURCE
        elif re.search(r"(?:EXT[234]-fs (?:error|warning)|BTRFS (?:error|warning)|XFS .*?(?:error|corrupt)|"
                       r"Buffer I/O error|\bI/O error, dev |blk_update_request: I/O error|"
                       r"Remounting filesystem read-only|nvme .*?(?:I/O .*timeout|controller is down))", message, re.IGNORECASE):
            kind = EventKind.FILESYSTEM
        elif re.search(r"\busb [\d.-]+: (?:new .*USB device|USB disconnect|New USB device found)", message):
            kind = EventKind.DEVICE_CHANGE
        elif re.search(r"\b(?:Link is (?:Up|Down)|NIC Link is (?:Up|Down))\b", message):
            kind = EventKind.NETWORK
        elif re.search(r"\b(?:battery|ACPI: AC Adapter)\b.*\b(?:low|critical|charging|discharging|on-line|off-line)\b",
                       message, re.IGNORECASE):
            kind = EventKind.BATTERY
    elif identifier == "systemd-oomd" and re.search(r"\b(?:Killed|memory pressure|swap used)\b", message, re.IGNORECASE):
        kind = EventKind.RESOURCE
    elif identifier == "systemd":
        if re.search(r"\b(?:Time has been changed|Clock change detected)\b", message):
            kind = EventKind.TIME_CHANGE
        elif re.search(r"^(?:Failed to mount |.*\.mount: Failed|.*\.automount: Failed)", message):
            kind = EventKind.FILESYSTEM
        elif re.search(r"^(?:Started |Stopped |Failed to start |.*\.service: (?:Main process exited|Failed with result|Scheduled restart job))", message):
            kind = EventKind.SERVICE
    elif identifier in ("systemd-timesyncd", "chronyd", "ntpd") and re.search(
            r"synchroni[sz]|clock.*(?:step|adjust|change)|time.*(?:jump|change|reset)|no suitable source|timed out", message, re.IGNORECASE):
        kind = EventKind.TIME_CHANGE
    elif identifier == "upowerd" and re.search(r"battery|on-battery|charging|discharging|critical", message, re.IGNORECASE):
        kind = EventKind.BATTERY
    elif identifier == "NetworkManager" and re.search(
            r"state change: \S+ -> (?:activated|disconnected|failed)\b|Activation: (?:successful|failed)|state is now (?:CONNECTED|DISCONNECTED)", message):
        kind = EventKind.NETWORK
    elif identifier == "systemd-networkd" and re.search(r": (?:Gained carrier|Lost carrier|Link UP|Link DOWN|DHCP lease lost)\b", message):
        kind = EventKind.NETWORK
    elif identifier == "wpa_supplicant" and re.search(r"\bCTRL-EVENT-(?:CONNECTED|DISCONNECTED|ASSOC-REJECT|SSID-TEMP-DISABLED)\b", message):
        kind = EventKind.NETWORK
    elif identifier in (*SSH_PROCESSES, "sudo", "su", "login") or str(record.get("_COMM", "")) in SSH_PROCESSES:
        return common._parse_auth_failure(message)
    elif identifier in ("PackageKit", "packagekitd", "dnf", "apt", "unattended-upgrade", "fwupd") and re.search(
            r"\b(?:install|installed|installing|upgrade|upgraded|upgrading|update|updated|transaction|error|failed)\b", message, re.IGNORECASE):
        kind = EventKind.UPDATE
    return (kind, message, session) if kind is not None else None


def _linux_diagnostic_event(record: dict[str, object], message: str) -> tuple[EventKind, str, str] | None:
    """Recognize coredump/watchdog evidence and keep other system errors diagnostic."""
    identifier = str(record.get("SYSLOG_IDENTIFIER", ""))
    kernel = record.get("_TRANSPORT") == "kernel"
    if record.get("MESSAGE_ID") == COREDUMP_MESSAGE_ID:
        name = record.get("COREDUMP_EXE") or record.get("COREDUMP_COMM") or "process"
        pid = record.get("COREDUMP_PID", "")
        signal = record.get("COREDUMP_SIGNAL_NAME") or record.get("COREDUMP_SIGNAL", "unknown")
        return EventKind.APP_CRASH, f"Core dump reported: {name}; signal {signal}; {message}", f"PID {pid}" if pid else ""
    if identifier == "systemd" and re.search(r"(?:^|: )Watchdog timeout \(limit ", message):
        return EventKind.APP_HANG, f"Service watchdog timeout: {message}", str(record.get("UNIT") or record.get("USER_UNIT") or "")
    if kernel and "Kernel panic - not syncing:" in message:
        return EventKind.SYSTEM_CRASH, message, ""
    if (kernel or identifier in ("systemd", "systemd-oomd", "systemd-journald")) and str(record.get("PRIORITY")) in ("0", "1", "2", "3"):
        return EventKind.DIAGNOSTIC, message, str(record.get("UNIT") or record.get("USER_UNIT") or "")
    return None



def _parse_linux_journal(text: str) -> list[PowerEvent]:
    """Parse conservative kernel/systemd transitions; arbitrary desktop lock text is excluded."""
    events: list[PowerEvent] = []
    for record in common._json_records(text):
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
            matched = common._parse_ssh_message(message)
            if matched:
                kind, summary, session = matched
                pid = str(record.get("_PID", ""))
                if pid:
                    session = "; ".join(part for part in (session, f"PID {pid}") if part)
        elif unit in ("systemd-suspend.service", "systemd-hibernate.service", "systemd-suspend-then-hibernate.service", "systemd-hybrid-sleep.service"):
            if "System returned from sleep operation" in message or message == "System resumed.":
                kind = EventKind.WAKE
        if kind is None:
            diagnostic = _linux_activity_event(record, message) or _linux_diagnostic_event(record, message)
            if diagnostic is None:
                continue
            kind, summary, session = diagnostic
        timestamp = dt.datetime.fromtimestamp(int(str(record["__REALTIME_TIMESTAMP"])) / 1_000_000, UTC)
        events.append(PowerEvent(
            timestamp, kind, summary, f"journal / {identifier or unit or 'kernel'}",
            str(record.get("__CURSOR", "")), session, str(record.get("_BOOT_ID", "")),
            json.dumps(record, ensure_ascii=False, indent=2),
        ))
    return events



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
    common._collect_source(result, "systemd journal", command, _parse_linux_journal, cancelled)
    progress("Reading device, network, service and maintenance history...")
    activity = [executable, "--no-pager", "--output=json", "--reverse", f"--lines={MAX_EVENTS + 1}",
                "--since", f"@{int(result.start.timestamp())}", "--until", f"@{int(result.end.timestamp())}",
                "_TRANSPORT=kernel"]
    for identifier in ACTIVITY_IDENTIFIERS:
        activity.extend(["+", f"SYSLOG_IDENTIFIER={identifier}"])
    common._collect_source(result, "System activity", activity, _parse_linux_journal, cancelled, record_limit=MAX_EVENTS)
    progress("Reading coredumps, service watchdogs and system diagnostics...")
    diagnostics = [executable, "--no-pager", "--output=json", "--reverse", f"--lines={MAX_EVENTS + 1}",
                   "--since", f"@{int(result.start.timestamp())}", "--until", f"@{int(result.end.timestamp())}",
                   f"MESSAGE_ID={COREDUMP_MESSAGE_ID}"]
    for selector in ("_TRANSPORT=kernel", "SYSLOG_IDENTIFIER=systemd", "SYSLOG_IDENTIFIER=systemd-oomd",
                     "SYSLOG_IDENTIFIER=systemd-journald"):
        diagnostics.extend(["+", selector, "PRIORITY=0", "PRIORITY=1", "PRIORITY=2", "PRIORITY=3"])
    common._collect_source(result, "Journal diagnostics", diagnostics, _parse_linux_journal, cancelled, record_limit=MAX_EVENTS)
    result.statuses.append(SourceStatus("Coverage", SourceState.LIMITED,
        "History depends on journal retention, persistence and access. Lock/unlock is recognized only "
        "when logind explicitly records the session transition; desktop-only lock signals are not collected. "
        "Missing shutdown records do not prove a crash. SSH reads sshd journal records only; "
        "file-only authentication logs are not collected. Unnamed SSH closes have unknown authentication. "
        "RDP and general desktop logon/logoff history are only collected on Windows. "
        "Diagnostics include coredump journal reports and kernel/systemd errors. Hang detection covers "
        "service watchdog timeouts only, not every unresponsive desktop app. Kernel panics may never reach "
        "persistent logs; binary core dumps and pstore are not read. "
        "Activity includes retained UPower/battery, time-sync, PAM/SSH failures, package-manager, OOM, "
        "service, filesystem, USB and network-manager messages. Package log files and live device monitoring "
        "are not read. Message formats and available services vary by distribution."))

