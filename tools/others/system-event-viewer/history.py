"""System event viewer: history implementation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import csv
import datetime as dt
import json
from pathlib import Path
import sys
import threading
from .models import (
    EventKind,
    MAX_EVENTS,
    PowerEvent,
    QueryResult,
    SourceState,
    SourceStatus,
    UTC,
)
from . import windows, macos, linux


def query_events(
    start: dt.datetime, end: dt.datetime, cancelled: threading.Event,
    progress: Callable[[str], None] = lambda _message: None,
) -> QueryResult:
    """Read local event and diagnostic history without changing settings or escalating privileges.

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
        Runs native read-only log commands and reads macOS report files.
        No files or system settings are changed.
    """
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Choose an end time after the start time, with a timezone.")
    result = QueryResult(start.astimezone(UTC), end.astimezone(UTC))
    collectors = {"darwin": macos._collect_macos, "win32": windows._collect_windows, "linux": linux._collect_linux}
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

