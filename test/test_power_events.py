"""Exercise power-event parsing, cancellation, exports and GUI filtering.

Requirements: standard library; PySide6 for GUI tests (offscreen).
Usage: conda run -n base python -m unittest discover -s test -p test_power_events.py
Fixtures and settings are isolated inside the repository's tmp directory.
"""

from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *  # noqa: E402

SPEC = importlib.util.spec_from_file_location("power_events", ROOT / "tools/power-events.py")
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)
STAMP = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)


def _windows_xml(provider: str, event_id: int, data: str = "") -> str:
    """Create a provider-qualified Windows event fixture with an explicit UTC timestamp."""
    return f'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="{provider}"/><EventID>{event_id}</EventID>
<TimeCreated SystemTime="2026-10-10T12:00:00.0000000Z"/><EventRecordID>123</EventRecordID></System>
<EventData>{data}</EventData></Event>'''


class ParserTests(unittest.TestCase):
    """Test interpretations that otherwise cause misleading power histories."""

    def test_pmset_excludes_requests_and_preserves_dark_wake(self) -> None:
        """Only actual event columns match; a scheduled wake is not a wake."""
        text = "\n".join((
            "2026-10-10 20:00:00 +0800 Sleep               \tEntering Sleep state due to 'Idle Sleep'",
            "2026-10-10 20:00:01 +0800 Wake Requests       \tprocess=request wakeAt=later",
            "2026-10-10 20:00:02 +0800 Kernel Client Acks  \tDelays to Wake notifications",
            "2026-10-10 20:01:00 +0800 DarkWake            \tDarkWake from Deep Idle",
            "2026-10-10 20:02:00 +0800 Wake                \tWake from Deep Idle",
        ))
        events = app._parse_pmset(text)
        self.assertEqual([event.kind for event in events], [app.EventKind.SLEEP, app.EventKind.DARK_WAKE, app.EventKind.WAKE])
        self.assertEqual(events[0].timestamp, STAMP)

    def test_mac_unlock_request_and_locked_snapshot_are_not_transitions(self) -> None:
        """State snapshots and failed/started authentication must not become lock events."""
        messages = (
            "start an unlock with active user as the reason",
            "SleepWakeCallback screenIsLocked=1",
            "sendDistributedNotification: com.apple.screenIsLocked, with object:501",
            "sendDistributedNotification: com.apple.screenIsUnlocked, with object:501",
        )
        text = "\n".join(json.dumps({"timestamp": "2026-10-10 20:00:00.123456+0800", "eventMessage": message}) for message in messages)
        events = app._parse_mac_sessions(text)
        self.assertEqual([event.kind for event in events], [app.EventKind.LOCK, app.EventKind.UNLOCK])
        self.assertEqual(events[0].session, "UID 501")

    def test_mac_boot_history_retains_minute_precision(self) -> None:
        """Parse the explicit year rather than assuming every record belongs to this year."""
        events = app._parse_mac_last("reboot time  Sun Oct  4 2026 21:40\nshutdown time  Sun Oct  4 2026 21:31")
        self.assertEqual(len(events), 2)
        self.assertIn("minute precision", events[0].summary)
        self.assertEqual(events[0].timestamp.astimezone().year, 2026)

    def test_windows_ids_require_the_correct_provider(self) -> None:
        """An unrelated provider's event 12 is not a system startup."""
        self.assertEqual(app._parse_windows_xml(_windows_xml("Other-Provider", 12)), [])
        event = app._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-General", 12))[0]
        self.assertEqual(event.kind, app.EventKind.STARTUP)
        self.assertEqual(event.timestamp, STAMP)

    def test_windows_wake_uses_embedded_time_not_later_log_time(self) -> None:
        """Power-Troubleshooter can write its record after the actual wake."""
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Power-Troubleshooter", 1,
            '<Data Name="WakeTime">2026-10-10T11:59:00Z</Data>',
        ))[0]
        self.assertEqual(event.timestamp, STAMP - dt.timedelta(minutes=1))
        self.assertIn("12:00:00", event.raw)

    def test_windows_hibernation_and_security_session(self) -> None:
        """Preserve hibernation semantics and the user/session identifying a lock."""
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Kernel-Power", 42, '<Data Name="TargetState">5</Data>',
        ))[0]
        self.assertEqual(event.kind, app.EventKind.HIBERNATE)
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Security-Auditing", 4800,
            '<Data Name="TargetUserName">demo</Data><Data Name="SessionId">3</Data>',
        ))[0]
        self.assertEqual(event.session, "demo (session 3)")

    def test_linux_only_accepts_relevant_source_transitions(self) -> None:
        """Kernel sleep, desktop chatter and logind lock records remain distinct."""
        records = [
            {"MESSAGE": "PM: suspend entry (s2idle)", "_TRANSPORT": "kernel"},
            {"MESSAGE": "PM: suspend exit", "_TRANSPORT": "kernel"},
            {"MESSAGE": "Screen unlocked requested", "SYSLOG_IDENTIFIER": "gnome-shell"},
            {"MESSAGE": "Session 2 locked.", "SYSLOG_IDENTIFIER": "systemd-logind"},
            {"MESSAGE": "Session 2 unlocked.", "SYSLOG_IDENTIFIER": "systemd-logind"},
        ]
        for record in records:
            record["__REALTIME_TIMESTAMP"] = str(int(STAMP.timestamp() * 1_000_000))
            record["_BOOT_ID"] = "boot-fixture"
        events = app._parse_linux_journal("\n".join(json.dumps(record) for record in records))
        self.assertEqual([event.kind for event in events], [app.EventKind.SLEEP, app.EventKind.WAKE, app.EventKind.LOCK, app.EventKind.UNLOCK])
        self.assertTrue(all(event.boot_id == "boot-fixture" for event in events))

    def test_unavailable_source_is_not_an_empty_success(self) -> None:
        """Permission failure leaves a source diagnostic rather than an empty success."""
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(app, "_run_command", side_effect=RuntimeError("Access denied")):
            app._collect_source(result, "Security", ["fixture"], lambda _text: [], threading.Event())
        self.assertEqual(result.statuses[0].state, app.SourceState.ERROR)

    def test_query_uses_half_open_range_and_deduplicates_exact_records(self) -> None:
        """End-boundary records are excluded while the start boundary is retained."""
        def collect(result: app.QueryResult, cancelled: threading.Event, progress: object) -> None:
            first = app.PowerEvent(STAMP, app.EventKind.WAKE, "wake", "fixture", "1")
            result.events.extend([first, first, app.PowerEvent(STAMP + dt.timedelta(hours=1), app.EventKind.LOCK, "lock", "fixture", "2")])

        with patch.object(sys, "platform", "darwin"), patch.object(app, "_collect_macos", side_effect=collect):
            result = app.query_events(STAMP, STAMP + dt.timedelta(hours=1), threading.Event())
        self.assertEqual(len(result.events), 1)

    def test_cancellation_reaps_a_running_child(self) -> None:
        """Cancellation stops a waiting native-source process promptly."""
        cancelled = threading.Event()
        timer = threading.Timer(0.15, cancelled.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InterruptedError):
                app._run_command([sys.executable, "-c", "import time; time.sleep(10)"], cancelled)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 3)

    def test_exports_preserve_evidence_and_escape_csv_formulas(self) -> None:
        """JSON keeps source coverage/raw evidence; CSV neutralizes formula-like log fields."""
        event = app.PowerEvent(STAMP, app.EventKind.LOCK, "=danger", "fixture", raw="raw\nrecord")
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), [event])
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="power-events-export-") as directory:
            path = Path(directory) / "events.json"
            app.export_events(path, [event], result)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["events"][0]["raw"], "raw\nrecord")
            path = path.with_suffix(".csv")
            app.export_events(path, [event], result)
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["summary"], "'=danger")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    """Exercise actual Qt controls with fixture history and isolated settings."""

    def test_gui_filters_without_requery_and_shows_original_evidence(self) -> None:
        """Load history asynchronously, filter checkboxes, select details and close cleanly."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtWidgets

        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        events = [app.PowerEvent(STAMP, app.EventKind.LOCK, "locked", "fixture", raw="lock evidence"),
                  app.PowerEvent(STAMP + dt.timedelta(seconds=1), app.EventKind.WAKE, "wake", "fixture", raw="wake evidence")]
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), events)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="power-events-gui-") as directory:
            original = QtCore.QSettings.defaultFormat()
            QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
            QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, directory)
            try:
                with patch.object(app, "query_events", return_value=result) as query:
                    self.assertEqual(app._launch_gui(), 0)
                    window = application.property("powerEventsWindow")
                    deadline = time.monotonic() + 5
                    while window.result is None or window.worker is not None:
                        application.processEvents()
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertEqual(window.proxy.rowCount(), 2)
                    window.checkboxes[app.EventKind.LOCK].setChecked(False)
                    application.processEvents()
                    self.assertEqual(window.proxy.rowCount(), 1)
                    self.assertEqual(query.call_count, 1)
                    window.table.selectRow(0)
                    application.processEvents()
                    self.assertIn("wake evidence", window.detail.toPlainText())
                    window._select_types(False)
                    self.assertEqual(window.proxy.rowCount(), 0)
                    window.close()
                    application.processEvents()
            finally:
                QtCore.QSettings.setDefaultFormat(original)


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
