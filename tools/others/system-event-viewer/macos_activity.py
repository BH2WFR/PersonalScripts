"""Conservative unified-log activity rules with matching native query predicates.

macOS message formats are not stable APIs. Rules require both a known system
process and explicit text; retain the original observation without inferring a
physical transition, successful update or authentication from a request alone.
"""

from dataclasses import dataclass
import json
import re

from . import common
from .models import EventKind, PowerEvent


@dataclass(frozen=True)
class ActivityRule:
    """A source-qualified message pattern and inexpensive native query keywords."""

    kind: EventKind
    processes: tuple[str, ...]
    keywords: tuple[str, ...]
    pattern: str


ACTIVITY_RULES: tuple[ActivityRule, ...] = (
    ActivityRule(EventKind.BATTERY, ("powerd",), ("battery", "AC power", "power source"),
                 r"(?:battery.*\b(?:low|critical|charging|discharging|level|percent)\b|"
                 r"\b(?:using|switched to) (?:AC|battery) power|power source.*(?:change|AC|battery))"),
    ActivityRule(EventKind.TIME_CHANGE, ("timed", "timed-helper", "systemsetup"),
                 ("clock", "time", "synchron"), r"(?:clock.*(?:step|adjust|change|set)|"
                 r"time.*(?:jump|change|adjust|synchron|set)|synchron.*(?:fail|success))"),
    ActivityRule(EventKind.AUTHENTICATION, ("opendirectoryd", "authd", "loginwindow", "sudo", "su"),
                 ("auth", "password", "locked"), r"(?:authentication (?:failed|failure)|"
                 r"failed to authenticate|invalid password|account.*locked|pam_\w+\([^)]*:auth\): authentication failure)"),
    ActivityRule(EventKind.UPDATE, ("softwareupdated", "softwareupdate", "installd", "osinstallersetupd"),
                 ("install", "update", "upgrade", "rollback"),
                 r"\b(?:install(?:ation|ing|ed)?|updat(?:e|ed|ing)|upgrad(?:e|ed|ing)|rollback)\b"),
    ActivityRule(EventKind.RESOURCE, ("kernel", "memorystatus", "memorypressure"),
                 ("memorystatus", "jetsam", "out of memory", "memory pressure", "swap"),
                 r"(?:memorystatus.*(?:kill|pressure|limit)|jetsam.*(?:kill|limit)|out of memory|"
                 r"memory pressure.*(?:critical|warn)|swap.*(?:full|exhaust|fail))"),
    ActivityRule(EventKind.SERVICE, ("launchd",), ("exited", "spawn", "service", "throttl"),
                 r"(?:service exited|exited (?:with|due to)|spawn.*(?:fail|error)|service.*(?:fail|crash)|throttling respawn)"),
    ActivityRule(EventKind.FILESYSTEM, ("kernel", "fsck_apfs", "fsck_hfs", "diskarbitrationd"),
                 ("I/O", "corrupt", "space", "filesystem", "mount", "apfs", "hfs"),
                 r"(?:I/O error|no space left|filesystem.*(?:error|corrupt)|"
                 r"(?:apfs|hfs).*?(?:error|corrupt)|(?:mount|unmount).*fail|volume.*(?:corrupt|could not be verified))"),
    ActivityRule(EventKind.DEVICE_CHANGE, ("kernel", "diskarbitrationd", "bluetoothd"),
                 ("USB", "disk", "device"), r"(?:USB.*(?:disconnect|attach|detach|enumerat)|"
                 r"disk.*(?:appeared|disappeared)|device.*(?:connected|disconnected|attached|detached))"),
    ActivityRule(EventKind.NETWORK, ("airportd", "wifid", "configd", "nesessionmanager", "pppd"),
                 ("link", "connect", "associat", "disconnect", "terminated"),
                 r"(?:link (?:up|down)|\b(?:disconnected|associated|disassociated)\b|"
                 r"connection (?:established|failed|terminated)|status changed.*(?:connected|disconnected))"),
)


def activity_predicate() -> str:
    """Filter at the log source using static process names and message keywords."""
    clauses = []
    for rule in ACTIVITY_RULES:
        processes = " OR ".join(f'process == "{process}"' for process in rule.processes)
        words = " OR ".join(f'eventMessage CONTAINS[c] "{word}"' for word in rule.keywords)
        clauses.append(f"(({processes}) AND ({words}))")
    return " OR ".join(clauses)


def parse_activity(text: str) -> list[PowerEvent]:
    """Decode source-qualified activity records; invalid timestamps raise ValueError."""
    events: list[PowerEvent] = []
    for record in common._json_records(text):
        process = str(record.get("processImagePath") or record.get("process") or "").rsplit("/", 1)[-1]
        message = str(record.get("eventMessage", ""))
        for rule in ACTIVITY_RULES:
            if process not in rule.processes or not re.search(rule.pattern, message, re.IGNORECASE):
                continue
            # The collector reports malformed records as an unavailable source.
            timestamp = common._timestamp(str(record.get("timestamp", "")))
            pid = str(record.get("processID", ""))
            events.append(PowerEvent(
                timestamp, rule.kind, message, f"unified log / {process}",
                str(record.get("machTimestamp", "")), f"PID {pid}" if pid else "",
                str(record.get("bootUUID", "")), json.dumps(record, ensure_ascii=False, indent=2),
            ))
            break
    return events
