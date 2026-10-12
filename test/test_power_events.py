"""Exercise power-event parsing, cancellation, exports and GUI filtering.

Requirements: standard library; PySide6 for GUI tests (offscreen).
Usage: conda run -n base python -m unittest discover -s test -p test_power_events.py
Fixtures and settings are isolated inside the repository's tmp directory.
"""

from __future__ import annotations

import base64
import csv
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
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


def setUpModule() -> None:
    """Create the gitignored fixture parent required on fresh repository checkouts."""
    (ROOT / "tmp").mkdir(exist_ok=True)


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

    def test_windows_modern_standby_entry_keeps_session_identifiers(self) -> None:
        """Entry is its own category and does not invent sleep or DRIPS evidence."""
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Kernel-Power", 506,
            '<Data Name="Reason">16777224</Data><Data Name="BootId">7</Data>'
            '<Data Name="ScenarioInstanceId">13</Data><Data Name="ScenarioInstanceIdV2">11</Data>',
        ))[0]
        self.assertEqual(event.kind, app.EventKind.STANDBY_ENTER)
        self.assertEqual(event.boot_id, "7")
        self.assertIn("ScenarioInstanceId=13", event.session)
        self.assertIn("ScenarioInstanceIdV2=11", event.session)
        self.assertIn("Reason=16777224", event.summary)
        self.assertNotIn("Sleep duration", event.summary)
        self.assertNotIn("DRIPS", event.summary)

    def test_windows_modern_standby_exit_preserves_metrics_and_reason(self) -> None:
        """Keep OS-rendered reasons, explicit zero residency and internal-exit evidence."""
        message = "The system is exiting Modern Standby\r\n\r\nReason: Power Button."
        for in_progress in ("true", "false"):
            with self.subTest(in_progress=in_progress):
                xml = _windows_xml(
                    "Microsoft-Windows-Kernel-Power", 507,
                    '<Data Name="SleepEntered">true</Data><Data Name="Reason">1</Data>'
                    '<Data Name="SleepDurationInUs">123456789</Data>'
                    '<Data Name="ScreenOffDurationInUs">1500000</Data>'
                    '<Data Name="DripsResidencyInUs">0</Data><Data Name="HwDripsResidencyInUs">0</Data>'
                    f'<Data Name="IsCsSessionInProgressOnExit">{in_progress}</Data>',
                )
                event = app._parse_windows_xml(xml, message)[0]
                self.assertEqual(event.kind, app.EventKind.STANDBY_EXIT)
                self.assertEqual(event.timestamp, STAMP)
                for evidence in ("Power Button", "SleepEntered=true", "Sleep duration=123.457 s",
                                 "Screen-off duration=1.500 s", "Software DRIPS=0.000 s",
                                 "Hardware DRIPS=0.000 s", f"IsCsSessionInProgressOnExit={in_progress}"):
                    self.assertIn(evidence, event.summary)
                self.assertIn(xml, event.raw)
                self.assertIn(message, event.raw)

    def test_windows_power_session_transition_is_not_a_wake(self) -> None:
        """A session reason or transition must not become an extra sleep/wake count."""
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Kernel-Power", 566,
            '<Data Name="BootId">7</Data><Data Name="Reason">11</Data>'
            '<Data Name="PreviousSessionId">12</Data><Data Name="NextSessionId">13</Data>'
            '<Data Name="PreviousSessionType">2</Data><Data Name="NextSessionType">0</Data>'
            '<Data Name="PreviousSessionDurationInUs">5000000</Data>',
        ), "The system session has transitioned. Reason FullWake")[0]
        self.assertEqual(event.kind, app.EventKind.POWER_SESSION)
        self.assertEqual(event.session, "12 -> 13")
        self.assertEqual(event.boot_id, "7")
        self.assertIn("PreviousSessionType=2", event.summary)
        self.assertIn("NextSessionType=0", event.summary)
        self.assertIn("Previous session duration=5.000 s", event.summary)

    def test_windows_modern_standby_tolerates_missing_or_unknown_fields(self) -> None:
        """Old event versions, unknown reasons and unfamiliar durations remain inspectable."""
        for event_id in (506, 507, 566):
            with self.subTest(event_id=event_id):
                self.assertEqual(app._parse_windows_xml(_windows_xml("Other-Provider", event_id)), [])
                event = app._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-Power", event_id))[0]
                self.assertNotIn("DRIPS=0", event.summary)
                self.assertNotIn("SleepEntered", event.summary)
        event = app._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Kernel-Power", 507,
            '<Data Name="Reason">999999</Data><Data Name="SleepDurationInUs">unknown</Data>',
        ))[0]
        self.assertIn("Reason=999999", event.summary)
        self.assertIn("Sleep duration=unknown us", event.summary)

    def test_windows_collector_requests_and_parses_modern_standby(self) -> None:
        """Exercise the query boundary so parser support cannot mask missing event IDs."""
        records = [{"kind": "event", "xml": _windows_xml("Microsoft-Windows-Kernel-Power", event_id),
                    "message": "OS-rendered description" if event_id == 507 else None}
                   for event_id in (506, 507, 566)]
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(app.Environment, "find_pwsh", return_value="pwsh"), patch.object(
            app, "_run_command", return_value=("\n".join(json.dumps(record) for record in records), ""),
        ) as command:
            app._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        # UTC clock values here caused an eight-hour shift on a UTC+08 Windows host.
        self.assertIn(f"[DateTimeOffset]::Parse('{result.start.isoformat()}').LocalDateTime", script)
        self.assertIn(f"[DateTimeOffset]::Parse('{result.end.isoformat()}').LocalDateTime", script)
        kernel_filter = next(line for line in script.splitlines() if "ProviderName='Microsoft-Windows-Kernel-Power'" in line)
        self.assertTrue({506, 507, 566}.issubset({int(value) for value in re.findall(r"\b\d+\b", kernel_filter)}))
        self.assertEqual([event.kind for event in result.events],
                         [app.EventKind.STANDBY_ENTER, app.EventKind.STANDBY_EXIT, app.EventKind.POWER_SESSION])
        self.assertIn("OS-rendered description", result.events[1].raw)
        self.assertNotIn("Rendered message", result.events[0].raw)

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
                    # Export through the actual buttons, retaining only visible rows.
                    csv_path = Path(directory) / "visible.csv"
                    with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(csv_path.with_suffix("")), "CSV (*.csv)")) as dialog:
                        window.export_button.click()
                    self.assertEqual(dialog.call_args.args[2], "power-events.csv")
                    with csv_path.open(encoding="utf-8", newline="") as stream:
                        rows = list(csv.DictReader(stream))
                    self.assertEqual([row["event"] for row in rows], ["Wake"])
                    self.assertEqual(rows[0]["summary"], "wake")
                    json_path = Path(directory) / "visible.json"
                    with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(json_path), "JSON (*.json)")):
                        window.export_json_button.click()
                    self.assertEqual(len(json.loads(json_path.read_text(encoding="utf-8"))["events"]), 1)
                    # Declining replacement must preserve the destination.
                    csv_path.write_text("existing content", encoding="utf-8")
                    with patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(csv_path.with_suffix("")), "CSV (*.csv)")), patch.object(
                        QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.StandardButton.No,
                    ):
                        window.export_button.click()
                    self.assertEqual(csv_path.read_text(encoding="utf-8"), "existing content")
                    window._select_types(False)
                    self.assertEqual(window.proxy.rowCount(), 0)
                    self.assertFalse(window.export_button.isEnabled())
                    self.assertFalse(window.export_json_button.isEnabled())
                    # Legacy filters must not hide newly supported Modern Standby records.
                    window.settings.setValue("types", [app.EventKind.LOCK.value, app.EventKind.WAKE.value])
                    window.settings.remove("knownTypes")
                    window._restore_settings()
                    modern_events = [app._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-Power", event_id))[0]
                                     for event_id in (506, 507, 566)]
                    window._loaded(app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), modern_events))
                    self.assertEqual(window.proxy.rowCount(), 3)
                    self.assertFalse(window.checkboxes[app.EventKind.STARTUP].isChecked())
                    window.checkboxes[app.EventKind.POWER_SESSION].setChecked(False)
                    self.assertEqual(window.proxy.rowCount(), 2)
                    self.assertEqual(query.call_count, 1)
                    window.close()
                    application.processEvents()
                    window._restore_settings()
                    self.assertFalse(window.checkboxes[app.EventKind.POWER_SESSION].isChecked())
                    self.assertTrue(window.checkboxes[app.EventKind.STANDBY_EXIT].isChecked())
            finally:
                QtCore.QSettings.setDefaultFormat(original)


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
