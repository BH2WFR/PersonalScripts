"""System event viewer: windows implementation."""

from __future__ import annotations

import base64
from collections.abc import Callable
import threading
import xml.etree.ElementTree as ET
from utils import Environment
from .models import (
    EventKind,
    INTERACTIVE_LOGON_TYPES,
    MAX_EVENTS,
    MICROSECONDS_PER_SECOND,
    MODERN_EVENT_KINDS,
    PowerEvent,
    QueryResult,
    RDP_PROVIDER,
    SECURITY_PROVIDER,
    SSH_PROCESSES,
    SourceState,
    SourceStatus,
    WINDOWS_DURATION_FIELDS,
    WINDOWS_MODERN_EVENTS,
    XML_NS,
)
from . import common
from .windows_activity import activity_filters, parse_activity
from .windows_smb import parse_smb_event
from utils.windows_events import (
    DEVICE_EJECTION_PROVIDER, DEVICE_EJECTION_EVENT_ID, parse_device_ejection_event,
)


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



def _windows_diagnostic_event(source: str, event_id: int, data: dict[str, str], message: str) -> tuple[EventKind, str, str] | None:
    """Separate failure observations from WER summaries and hardware/performance diagnostics."""
    categories = {
        ("Application Error", 1000): (EventKind.APP_CRASH, "Application crash recorded"),
        ("Application Hang", 1002): (EventKind.APP_HANG, "Application stopped responding"),
        ("Windows Error Reporting", 1001): (EventKind.DIAGNOSTIC, "Windows Error Reporting report"),
        ("Microsoft-Windows-WER-SystemErrorReporting", 1001):
            (EventKind.SYSTEM_CRASH, "Bugcheck reported after restart (report time)"),
    }
    matched = categories.get((source, event_id))
    if source in ("Microsoft-Windows-WHEA-Logger", "Microsoft-Windows-Diagnostics-Performance"):
        matched = EventKind.DIAGNOSTIC, f"{source.removeprefix('Microsoft-Windows-')} diagnostic"
    if matched is None:
        return None
    kind, summary = matched
    fields = dict(data)
    if source in ("Application Error", "Application Hang"):
        # Older event versions use positional EventData instead of named fields.
        fields.setdefault("AppName", data.get("param0", ""))
    for key in ("AppName", "ModuleName", "ExceptionCode", "EventName", "P1", "ReportId",
                "BootTime", "ShutdownTime", "BootIsDegradation", "ShutdownIsDegradation"):
        if fields.get(key):
            summary += f"; {key}={fields[key]}"
    if source == "Microsoft-Windows-WER-SystemErrorReporting":
        for key, label in (("param1", "Bugcheck"), ("param2", "Dump"), ("param3", "Report")):
            if data.get(key):
                summary += f"; {label}={data[key]}"
    if message:
        summary += f"; {' '.join(message.split())}"
    process = fields.get("ProcessId", "")
    return kind, summary, f"PID {process}" if process else ""



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
    timestamp = common._timestamp(created.get("SystemTime", ""))
    data = {node.get("Name", f"param{index}"): node.text or ""
            for index, node in enumerate(root.findall("e:EventData/e:Data", XML_NS))}
    # TerminalServices uses UserData/EventXML in its own XML namespace.
    user_data = root.find("e:UserData", XML_NS)
    if user_data is not None:
        data.update({node.tag.rsplit("}", 1)[-1]: node.text or ""
                     for node in user_data.iter() if len(node) == 0})
    session_event = _windows_session_event(source, event_id, data)
    if session_event is None:
        session_event = parse_smb_event(source, event_id, data, system.findtext("e:Keywords", "", XML_NS), message)
    if source == DEVICE_EJECTION_PROVIDER and event_id == DEVICE_EJECTION_EVENT_ID:
        ejection = parse_device_ejection_event(xml)
        summary = f"{ejection.executable} (PID {ejection.pid}) blocked removal of {ejection.device}"
        if ejection.affected_devices:
            summary += f"; Vetoing devices: {ejection.affected_devices}"
        session_event = (EventKind.DEVICE_EJECT_BLOCKED, summary, f"PID {ejection.pid}")
    if session_event is None:
        session_event = _windows_diagnostic_event(source, event_id, data, message)
    if session_event is None:
        session_event = parse_activity(source, event_id, data, message)
    if source == "OpenSSH":
        process = data.get("process", "").lower().removesuffix(".exe")
        if process not in SSH_PROCESSES:
            return []
        session_event = common._parse_ssh_message(data.get("payload") or message)
        if session_event is None:
            session_event = common._parse_auth_failure(data.get("payload") or message)
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
        timestamp = common._timestamp(data["WakeTime"])
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



def _windows_source_filters(selected_kinds: frozenset[EventKind] | None) -> str:
    """Select native sources before reading, retaining all shared-source dependencies."""
    sources: tuple[tuple[frozenset[EventKind], str], ...] = (
        (frozenset({EventKind.STARTUP, EventKind.SHUTDOWN}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-Kernel-General'; Id=@(12,13)}"),
        (frozenset({EventKind.UNEXPECTED_RESTART, EventKind.SLEEP, EventKind.HIBERNATE, EventKind.WAKE,
                    EventKind.STANDBY_ENTER, EventKind.STANDBY_EXIT, EventKind.POWER_SESSION}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=@(41,42,107,506,507,566)}"),
        (frozenset({EventKind.WAKE}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-Power-Troubleshooter'; Id=@(1)}"),
        (frozenset({EventKind.POWER_REQUEST}),
         "@{LogName='System'; ProviderName='User32'; Id=@(1074)}"),
        (frozenset({EventKind.DEVICE_EJECT_BLOCKED}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-Kernel-PnP'; Id=@(225)}"),
        (frozenset({EventKind.LOCK, EventKind.UNLOCK, EventKind.RDP_RECONNECT, EventKind.RDP_DISCONNECT}),
         "@{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4800,4801,4778,4779)}"),
        (frozenset({EventKind.LOGON, EventKind.LOGOFF}),
         "@{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4624,4634)}"),
        (frozenset({EventKind.NETWORK_AUTH}),
         "@{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(4624)}"),
        (frozenset({EventKind.SMB}),
         "@{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(5140)}"),
        (frozenset({EventKind.SMB}),
         "@{LogName='Security'; ProviderName='Microsoft-Windows-Security-Auditing'; Id=@(5145)}"),
        (frozenset({EventKind.SMB}),
         "@{LogName='Microsoft-Windows-SMBServer/Security'; ProviderName='Microsoft-Windows-SMBServer'; Id=@(551)}"),
        (frozenset({EventKind.LOGON, EventKind.LOGOFF, EventKind.RDP_CONNECT, EventKind.RDP_RECONNECT, EventKind.RDP_DISCONNECT}),
         "@{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational'; ProviderName='Microsoft-Windows-TerminalServices-LocalSessionManager'; Id=@(21,23,24,25)}"),
        (frozenset({EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT, EventKind.AUTHENTICATION}),
         "@{LogName='OpenSSH/Operational'; ProviderName='OpenSSH'}"),
        (frozenset({EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT, EventKind.AUTHENTICATION}),
         "@{LogName='OpenSSH/Admin'; ProviderName='OpenSSH'}"),
        (frozenset({EventKind.APP_CRASH}),
         "@{LogName='Application'; ProviderName='Application Error'; Id=@(1000)}"),
        (frozenset({EventKind.APP_HANG}),
         "@{LogName='Application'; ProviderName='Application Hang'; Id=@(1002)}"),
        (frozenset({EventKind.DIAGNOSTIC}),
         "@{LogName='Application'; ProviderName='Windows Error Reporting'; Id=@(1001)}"),
        (frozenset({EventKind.SYSTEM_CRASH}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=@(1001)}"),
        (frozenset({EventKind.DIAGNOSTIC}),
         "@{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'}"),
        (frozenset({EventKind.DIAGNOSTIC}),
         "@{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; ProviderName='Microsoft-Windows-Diagnostics-Performance'; Level=@(1,2,3)}"),
    )
    filters = [activity_filters(selected_kinds)]
    filters.extend(f"    {selector}" for kinds, selector in sources
                   if selected_kinds is None or kinds & selected_kinds)
    return ",\n".join(part for part in filters if part)


def _collect_windows(
    result: QueryResult, cancelled: threading.Event, progress: Callable[[str], None],
    *, selected_kinds: frozenset[EventKind] | None = None,
) -> None:
    """Read selected sources through EventLogReader; preserve messages and per-source errors."""
    filters = _windows_source_filters(selected_kinds)
    if not filters:
        return
    executable = Environment.find_pwsh()
    if executable is None:
        result.statuses.append(SourceStatus("Windows Event Log", SourceState.ERROR, "PowerShell was not found."))
        return
    progress("Reading Windows system, login, diagnostic and device event logs...")
    script = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
# XPath uses explicit UTC bounds, avoiding local-clock and DST ambiguity.
$utcStart = [DateTimeOffset]::Parse('__START__').UtcDateTime.ToString('o')
$utcEnd = [DateTimeOffset]::Parse('__END__').UtcDateTime.ToString('o')
$sources = @(
__SOURCES__
)
foreach ($filter in $sources) {
    $label = "$($filter.LogName) / $($filter.ProviderName)"
    if ($filter.Id) { $label += " / IDs $($filter.Id -join ',')" }
    $count = 0
    $reader = $null
    try {
        $conditions = @("Provider[@Name='$($filter.ProviderName)']", "TimeCreated[@SystemTime >= '$utcStart' and @SystemTime < '$utcEnd']")
        if ($filter.Id) { $conditions += '(' + (($filter.Id | ForEach-Object { "EventID=$_" }) -join ' or ') + ')' }
        if ($filter.Level) { $conditions += '(' + (($filter.Level | ForEach-Object { "Level=$_" }) -join ' or ') + ')' }
        $xpath = '*[System[' + ($conditions -join ' and ') + ']]'
        if ($filter.Id -contains 4624) {
            # Separate limits prevent network authentication crowding out desktop sessions.
            if ($filter.Id.Count -eq 1) {
                $eventIds = 'EventID=4624'
                $types = "Data[@Name='LogonType']='3'"
                $label += ' / Network (type 3)'
            } else {
                $eventIds = 'EventID=4624 or EventID=4634'
                $types = "__LOGON_TYPES__"
                $label += ' / Interactive'
            }
            $xpath = "*[System[Provider[@Name='Microsoft-Windows-Security-Auditing'] and ($eventIds) and TimeCreated[@SystemTime >= '$utcStart' and @SystemTime < '$utcEnd']] and EventData[$types]]"
        }
        $query = [System.Diagnostics.Eventing.Reader.EventLogQuery]::new(
            $filter.LogName, [System.Diagnostics.Eventing.Reader.PathType]::LogName, $xpath)
        $query.ReverseDirection = $true
        $reader = [System.Diagnostics.Eventing.Reader.EventLogReader]::new($query)
        while ($count -lt __LIMIT__ -and ($record = $reader.ReadEvent())) {
            try {
                $description = ''
                # Missing message resources must not hide the original XML evidence.
                try { $description = $record.FormatDescription() } catch { }
                ConvertTo-Json -InputObject @{kind='event'; xml=$record.ToXml(); message=$description} -Compress
                $count++
            } finally {
                $record.Dispose()
            }
        }
        $state = if ($count) {'Read'} else {'No matches'}
        @{kind='status'; source=$label; state=$state; count=$count; message='Accessible retained records queried.'} | ConvertTo-Json -Compress
    } catch {
        $state = 'Unavailable'
        @{kind='status'; source=$label; state=$state; count=$count; message=$_.Exception.Message} | ConvertTo-Json -Compress
    } finally {
        if ($null -ne $reader) { $reader.Dispose() }
    }
}
""".replace("__SOURCES__", filters).replace("__LIMIT__", str(MAX_EVENTS + 1)).replace("__START__", result.start.isoformat()).replace("__END__", result.end.isoformat()).replace(
        "__LOGON_TYPES__", " or ".join(f"Data[@Name='LogonType']='{value}'" for value in INTERACTIVE_LOGON_TYPES),
    )
    try:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        text, _ = common._run_command([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], cancelled)
        for record in common._json_records(text):
            if record.get("kind") == "event":
                try:
                    result.events.extend(_parse_windows_xml(str(record["xml"]), str(record.get("message") or "")))
                except (ValueError, KeyError, ET.ParseError) as exc:
                    result.statuses.append(SourceStatus("Windows event record", SourceState.LIMITED,
                                                        f"Skipped an invalid event: {exc}"))
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
        "type 3 authentication is shown separately and does not by itself identify SMB. "
        "Successful service and batch logons are excluded. RDP also uses TerminalServices operational logs. "
        "SSH reads local OpenSSH server Operational/Admin channels, not file-only or outgoing client logs. "
        "SSH authentication success is separate from a transport close; unnamed closes have unknown authentication. "
        "Multiple sources can report the same session; rows are observations, not unique login counts. "
        "Modern Standby 506/507 and auxiliary session transitions 566 are included. "
        "Entry alone does not prove low-power residency; exit can be internal and is not proof of Wake-on-LAN. "
        "Reported sleep/DRIPS durations are shown when present; missing metrics are not zero. "
        "Unclean shutdown and bugcheck reports are timestamped at the later report. "
        "Application Error/Hang records are separate from WER summaries; WHEA and performance diagnostics "
        "do not by themselves prove a crash. Performance diagnostics include critical/error/warning levels. "
        "Memory dumps and WER archive files are not read. "
        "Kernel-PnP 225 identifies blocked ejections of USB and other PnP devices. "
        "Process paths and PIDs are historical; no current PID lookup is performed. "
        "Missing ejection records do not prove safe removal. "
        "Optional activity categories include battery/power-source reports, clock changes/synchronization, "
        "failed logons/account lockouts, Windows Update, resource exhaustion, Service Control Manager, "
        "disk/NTFS, Kernel-PnP configuration and NetworkProfile/WLAN connections. "
        "Device configuration/start/deletion records do not establish every physical insertion/removal. "
        "Authentication audit failures can include network logons; required auditing must already be enabled. "
        "Healthy volume reports and requested updates retain their native meaning; they are not assumed failures. "
        "Battery and resource history is event-based, not continuous usage monitoring. "
        "SMB/file sharing reads SMBServer Security 551 and Security 5140/5145. "
        "5140 requires prior File Share auditing; 5145 requires Detailed File Share auditing and may be noisy. "
        "5145 failures describe share-level denials, not NTFS denials; successful checks do not prove file access completed. "
        "Empty results do not establish whether auditing is enabled; this viewer never enables it. "
        "Audit changes cannot recover past accesses. SMB logs describe incoming access to this host, not outgoing clients."))

