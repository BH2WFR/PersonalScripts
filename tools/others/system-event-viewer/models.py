"""System event viewer: models implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from enum import StrEnum


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
    APP_CRASH = "Application crash"
    APP_HANG = "Application unresponsive"
    SYSTEM_CRASH = "System crash report"
    DIAGNOSTIC = "Diagnostic report"
    DEVICE_EJECT_BLOCKED = "Device ejection blocked"
    BATTERY = "Battery / power source"
    TIME_CHANGE = "Time changes"
    AUTHENTICATION = "Authentication"
    UPDATE = "Updates"
    RESOURCE = "Resource exhaustion"
    SERVICE = "Services"
    FILESYSTEM = "Disk / filesystem"
    DEVICE_CHANGE = "Device changes"
    NETWORK = "Network connections"
    NETWORK_AUTH = "Network authentication"
    SMB = "SMB / file sharing"


COMBINED_EVENT_FILTERS: dict[EventKind, frozenset[EventKind]] = {
    EventKind.STARTUP: frozenset({EventKind.STARTUP, EventKind.SHUTDOWN}),
    EventKind.SLEEP: frozenset({EventKind.SLEEP, EventKind.WAKE, EventKind.STANDBY_ENTER, EventKind.STANDBY_EXIT}),
    EventKind.LOCK: frozenset({EventKind.LOCK, EventKind.UNLOCK}),
    EventKind.LOGON: frozenset({EventKind.LOGON, EventKind.LOGOFF}),
    EventKind.RDP_CONNECT: frozenset({EventKind.RDP_CONNECT, EventKind.RDP_RECONNECT, EventKind.RDP_DISCONNECT}),
    EventKind.SSH_CONNECT: frozenset({EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT}),
}
EVENT_FILTER_LABELS: dict[EventKind, str] = {
    EventKind.STARTUP: "Startup / Shutdown",
    EventKind.SLEEP: "Sleep / Wake",
    EventKind.LOCK: "Lock / Unlock",
    EventKind.LOGON: "Logon / Logoff",
    EventKind.RDP_CONNECT: "RDP",
    EventKind.SSH_CONNECT: "SSH",
}
EVENT_FILTER_ORDER: tuple[EventKind, ...] = (
    # Power states and power sources.
    EventKind.STARTUP, EventKind.SLEEP, EventKind.HIBERNATE, EventKind.DARK_WAKE,
    EventKind.POWER_SESSION, EventKind.POWER_REQUEST, EventKind.BATTERY,
    # Local/remote sessions, authentication and shared access.
    EventKind.LOGON, EventKind.LOCK, EventKind.RDP_CONNECT, EventKind.SSH_CONNECT,
    EventKind.AUTHENTICATION, EventKind.NETWORK_AUTH, EventKind.SMB,
    # Network/devices and system maintenance.
    EventKind.NETWORK, EventKind.DEVICE_CHANGE, EventKind.DEVICE_EJECT_BLOCKED,
    EventKind.FILESYSTEM, EventKind.SERVICE, EventKind.UPDATE, EventKind.TIME_CHANGE,
    # Failures and diagnostic reports.
    EventKind.UNEXPECTED_RESTART, EventKind.SYSTEM_CRASH, EventKind.APP_CRASH,
    EventKind.APP_HANG, EventKind.RESOURCE, EventKind.DIAGNOSTIC,
)
EVENT_FILTER_GROUPS: dict[EventKind, frozenset[EventKind]] = {
    kind: COMBINED_EVENT_FILTERS.get(kind, frozenset({kind})) for kind in EVENT_FILTER_ORDER
}


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
DIAGNOSTIC_EVENT_KINDS: frozenset[EventKind] = frozenset({
    EventKind.APP_CRASH, EventKind.APP_HANG, EventKind.SYSTEM_CRASH, EventKind.DIAGNOSTIC,
})
ACTIVITY_EVENT_KINDS: frozenset[EventKind] = frozenset({
    EventKind.BATTERY, EventKind.TIME_CHANGE, EventKind.AUTHENTICATION,
    EventKind.UPDATE, EventKind.RESOURCE, EventKind.SERVICE, EventKind.FILESYSTEM,
    EventKind.DEVICE_CHANGE, EventKind.NETWORK,
})
DEFAULT_UNCHECKED_EVENT_KINDS: frozenset[EventKind] = ACTIVITY_EVENT_KINDS | frozenset({
    EventKind.APP_CRASH, EventKind.APP_HANG, EventKind.NETWORK_AUTH, EventKind.SMB,
})
COMMON_EVENT_KINDS: frozenset[EventKind] = frozenset({
    EventKind.STARTUP, EventKind.SHUTDOWN, EventKind.SLEEP, EventKind.WAKE,
    EventKind.LOCK, EventKind.UNLOCK, EventKind.HIBERNATE,
    EventKind.SSH_CONNECT, EventKind.SSH_DISCONNECT,
}) | DIAGNOSTIC_EVENT_KINDS | ACTIVITY_EVENT_KINDS
# Collector capabilities, not a guarantee that the host retained matching records.
PLATFORM_EVENT_KINDS: dict[str, frozenset[EventKind]] = {
    "win32": frozenset(EventKind) - {EventKind.DARK_WAKE},
    "darwin": COMMON_EVENT_KINDS | {EventKind.DARK_WAKE},
    "linux": COMMON_EVENT_KINDS,
}
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
COREDUMP_MESSAGE_ID = "fc2e22bc6ee647b6b90729ab34a250b1"
MAC_REPORT_SUFFIXES = frozenset({".ips", ".crash", ".hang", ".spin", ".panic", ".diag", ".dpsub"})
MAX_REPORT_BYTES = 8 * 1024 * 1024
MAX_REPORT_TOTAL_BYTES = 64 * 1024 * 1024
MAX_REPORT_FILES = 5000


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
