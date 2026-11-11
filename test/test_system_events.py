"""Exercise system-event parsing, cancellation, exports and GUI filtering.

Requirements: standard library; PySide6 for GUI tests (offscreen).
Usage: conda run -n base python -m unittest discover -s test -p test_system_events.py
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
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *  # noqa: E402
from utils.windows_events import DeviceEjectionEvent, parse_device_ejection_event

SPEC = importlib.util.spec_from_file_location("power_events", ROOT / "tools/others/system-event-viewer.py")
assert SPEC is not None and SPEC.loader is not None
entry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = entry
SPEC.loader.exec_module(entry)
entry.load_app()
from personal_system_event_viewer import models as app, common, windows, macos, linux as linux_events, history, ui
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
        events = macos._parse_pmset(text)
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
        events = macos._parse_mac_sessions(text)
        self.assertEqual([event.kind for event in events], [app.EventKind.LOCK, app.EventKind.UNLOCK])
        self.assertEqual(events[0].session, "UID 501")

    def test_mac_boot_history_retains_minute_precision(self) -> None:
        """Parse the explicit year rather than assuming every record belongs to this year."""
        events = macos._parse_mac_last("reboot time  Sun Oct  4 2026 21:40\nshutdown time  Sun Oct  4 2026 21:31")
        self.assertEqual(len(events), 2)
        self.assertIn("minute precision", events[0].summary)
        self.assertEqual(events[0].timestamp.astimezone().year, 2026)

    def test_windows_ids_require_the_correct_provider(self) -> None:
        """An unrelated provider's event 12 is not a system startup."""
        self.assertEqual(windows._parse_windows_xml(_windows_xml("Other-Provider", 12)), [])
        event = windows._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-General", 12))[0]
        self.assertEqual(event.kind, app.EventKind.STARTUP)
        self.assertEqual(event.timestamp, STAMP)

    def test_windows_wake_uses_embedded_time_not_later_log_time(self) -> None:
        """Power-Troubleshooter can write its record after the actual wake."""
        event = windows._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Power-Troubleshooter", 1,
            '<Data Name="WakeTime">2026-10-10T11:59:00Z</Data>',
        ))[0]
        self.assertEqual(event.timestamp, STAMP - dt.timedelta(minutes=1))
        self.assertIn("12:00:00", event.raw)

    def test_windows_hibernation_and_security_session(self) -> None:
        """Preserve hibernation semantics and the user/session identifying a lock."""
        event = windows._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Kernel-Power", 42, '<Data Name="TargetState">5</Data>',
        ))[0]
        self.assertEqual(event.kind, app.EventKind.HIBERNATE)
        event = windows._parse_windows_xml(_windows_xml(
            "Microsoft-Windows-Security-Auditing", 4800,
            '<Data Name="TargetUserName">demo</Data><Data Name="SessionId">3</Data>',
        ))[0]
        self.assertEqual(event.session, "demo (session 3)")

    def test_windows_modern_standby_entry_keeps_session_identifiers(self) -> None:
        """Entry is its own category and does not invent sleep or DRIPS evidence."""
        event = windows._parse_windows_xml(_windows_xml(
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
                event = windows._parse_windows_xml(xml, message)[0]
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
        event = windows._parse_windows_xml(_windows_xml(
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
                self.assertEqual(windows._parse_windows_xml(_windows_xml("Other-Provider", event_id)), [])
                event = windows._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-Power", event_id))[0]
                self.assertNotIn("DRIPS=0", event.summary)
                self.assertNotIn("SleepEntered", event.summary)
        event = windows._parse_windows_xml(_windows_xml(
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
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("\n".join(json.dumps(record) for record in records), ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        # UTC clock values here caused an eight-hour shift on a UTC+08 Windows host.
        self.assertIn(f"[DateTimeOffset]::Parse('{result.start.isoformat()}').LocalDateTime", script)
        self.assertIn(f"[DateTimeOffset]::Parse('{result.end.isoformat()}').LocalDateTime", script)
        kernel_filter = " ".join(line for line in script.splitlines() if "ProviderName='Microsoft-Windows-Kernel-Power'" in line)
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
        events = linux_events._parse_linux_journal("\n".join(json.dumps(record) for record in records))
        self.assertEqual([event.kind for event in events], [app.EventKind.SLEEP, app.EventKind.WAKE, app.EventKind.LOCK, app.EventKind.UNLOCK])
        self.assertTrue(all(event.boot_id == "boot-fixture" for event in events))

    def test_windows_interactive_logons_exclude_network_and_helper_accounts(self) -> None:
        """RDP is a type 10 session; network/service logons must not become SSH logins."""
        for event_id, kind in ((4624, app.EventKind.LOGON), (4634, app.EventKind.LOGOFF)):
            for logon_type in ("2", "10", "11", "12", "3", "4", "5", "7", "9", "13"):
                with self.subTest(event_id=event_id, logon_type=logon_type):
                    data = (f'<Data Name="LogonType">{logon_type}</Data>'
                            '<Data Name="TargetUserName">demo</Data><Data Name="TargetDomainName">EXAMPLE</Data>'
                            '<Data Name="TargetLogonId">0x123</Data><Data Name="IpAddress">192.0.2.1</Data>')
                    events = windows._parse_windows_xml(_windows_xml(app.SECURITY_PROVIDER, event_id, data))
                    if logon_type in ("2", "10", "11", "12"):
                        self.assertEqual(events[0].kind, kind)
                        self.assertIn("EXAMPLE\\demo", events[0].session)
                        self.assertIn("0x123", events[0].session)
                        self.assertIn("192.0.2.1", events[0].summary)
                    elif event_id == 4624 and logon_type == "3":
                        self.assertEqual(events[0].kind, app.EventKind.NETWORK_AUTH)
                        self.assertIn("protocol not established", events[0].summary)
                    else:
                        self.assertEqual(events, [])
        for sid in ("S-1-5-90-0-1", "S-1-5-96-0-1"):
            self.assertEqual(windows._parse_windows_xml(_windows_xml(
                app.SECURITY_PROVIDER, 4624,
                f'<Data Name="LogonType">2</Data><Data Name="TargetUserSid">{sid}</Data>',
            )), [])

    def test_windows_rdp_userdata_and_console_are_distinct(self) -> None:
        """Namespaced UserData is parsed even without localized message resources."""
        for event_id, kind in ((21, app.EventKind.RDP_CONNECT), (23, app.EventKind.LOGOFF),
                               (24, app.EventKind.RDP_DISCONNECT), (25, app.EventKind.RDP_RECONNECT)):
            with self.subTest(event_id=event_id):
                xml = _windows_xml(app.RDP_PROVIDER, event_id).replace(
                    "<EventData></EventData>",
                    '<UserData><EventXML xmlns="Event_NS"><User>EXAMPLE\\demo</User>'
                    '<SessionID>7</SessionID><Address>2001:db8::1</Address></EventXML></UserData>',
                )
                event = windows._parse_windows_xml(xml)[0]
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.session, "EXAMPLE\\demo (session 7)")
                self.assertIn("2001:db8::1", event.summary)
                self.assertEqual(event.raw, xml)
                self.assertEqual(windows._parse_windows_xml(xml.replace(app.RDP_PROVIDER, "Other")), [])
                if event_id in (24, 25):
                    self.assertEqual(windows._parse_windows_xml(xml.replace("2001:db8::1", "LOCAL")), [])
                elif event_id == 21:
                    local = windows._parse_windows_xml(xml.replace("2001:db8::1", "LOCAL"))[0]
                    self.assertEqual(local.kind, app.EventKind.LOGON)
        # Event 23 normally has no network address; never guess its transport.
        event = windows._parse_windows_xml(_windows_xml(app.RDP_PROVIDER, 23, '<Data Name="SessionID">7</Data>'))[0]
        self.assertEqual(event.kind, app.EventKind.LOGOFF)

    def test_windows_rdp_security_requires_remote_station(self) -> None:
        """Fast user switching produces the same IDs but is not an RDP connection."""
        for event_id, kind in ((4778, app.EventKind.RDP_RECONNECT), (4779, app.EventKind.RDP_DISCONNECT)):
            data = ('<Data Name="AccountName">demo</Data><Data Name="AccountDomain">EXAMPLE</Data>'
                    '<Data Name="LogonID">0x456</Data><Data Name="SessionName">RDP-Tcp#2</Data>'
                    '<Data Name="ClientAddress">192.0.2.2</Data><Data Name="ClientName">CLIENT</Data>')
            xml = _windows_xml(app.SECURITY_PROVIDER, event_id, data)
            event = windows._parse_windows_xml(xml)[0]
            self.assertEqual(event.kind, kind)
            self.assertIn("0x456", event.session)
            self.assertIn("CLIENT", event.summary)
            self.assertIn("192.0.2.2", event.summary)
            self.assertEqual(windows._parse_windows_xml(xml.replace("RDP-Tcp#2", "Console")), [])

    def test_ssh_authentication_and_disconnect_evidence(self) -> None:
        """Preserve endpoints and users without turning failed attempts into logins."""
        cases = (
            ("Accepted publickey for demo from 2001:db8::1 port 63022 ssh2: ED25519 fingerprint",
             app.EventKind.SSH_CONNECT, "demo"),
            ("sshd: Accepted keyboard-interactive/pam for EXAMPLE\\demo from 192.0.2.1 port 12345 ssh2",
             app.EventKind.SSH_CONNECT, "EXAMPLE\\demo"),
            ("Disconnected from user demo 2001:db8::1 port 63022", app.EventKind.SSH_DISCONNECT, "demo"),
            ("Connection reset by user demo 192.0.2.1 port 12345", app.EventKind.SSH_DISCONNECT, "demo"),
            ("Received disconnect from 192.0.2.1 port 12345:11: disconnected by user",
             app.EventKind.SSH_DISCONNECT, ""),
        )
        for message, kind, user in cases:
            with self.subTest(message=message):
                matched = common._parse_ssh_message(message)
                self.assertIsNotNone(matched)
                assert matched is not None
                self.assertEqual((matched[0], matched[2]), (kind, user))
                if not user:
                    self.assertIn("authentication unknown", matched[1])
        for message in (
            "Failed password for demo from 192.0.2.1 port 12345 ssh2",
            "Connection from 192.0.2.1 port 12345 on 192.0.2.2 port 22",
            "Partial publickey for demo from 192.0.2.1 port 12345 ssh2",
            "Connection closed by authenticating user demo 192.0.2.1 port 12345 [preauth]",
            "Disconnected from invalid user demo 192.0.2.1 port 12345",
            "Received disconnect from 192.0.2.1 port 12345:11: Bye [preauth]",
        ):
            with self.subTest(message=message):
                self.assertIsNone(common._parse_ssh_message(message))

    def test_ssh_platform_parsers_validate_server_source(self) -> None:
        """All platforms use server evidence, retaining raw records and process identity."""
        message = "Accepted password for demo from 192.0.2.1 port 54321 ssh2"
        data = f'<Data Name="process">sshd</Data><Data Name="payload">{escape(message)}</Data>'
        xml = _windows_xml("OpenSSH", 4, data)
        event = windows._parse_windows_xml(xml)[0]
        self.assertEqual(event.kind, app.EventKind.SSH_CONNECT)
        self.assertEqual(event.raw, xml)
        self.assertEqual(windows._parse_windows_xml(xml.replace(">sshd<", ">ssh<")), [])
        self.assertEqual(windows._parse_windows_xml(xml.replace('Name="OpenSSH"', 'Name="Other"')), [])
        linux = {"SYSLOG_IDENTIFIER": "sshd-session", "_PID": "321", "MESSAGE": message,
                 "__REALTIME_TIMESTAMP": str(int(STAMP.timestamp() * 1_000_000)), "_BOOT_ID": "boot-ssh"}
        event = linux_events._parse_linux_journal(json.dumps(linux))[0]
        self.assertEqual(event.kind, app.EventKind.SSH_CONNECT)
        self.assertEqual(event.session, "demo; PID 321")
        self.assertEqual(event.boot_id, "boot-ssh")
        linux["SYSLOG_IDENTIFIER"] = "ssh"
        self.assertEqual(linux_events._parse_linux_journal(json.dumps(linux)), [])
        mac = {"processImagePath": "/usr/sbin/sshd", "processID": 321,
               "timestamp": STAMP.isoformat(), "eventMessage": message, "bootUUID": "boot-ssh"}
        event = macos._parse_mac_ssh(json.dumps(mac))[0]
        self.assertEqual(event.kind, app.EventKind.SSH_CONNECT)
        self.assertEqual(event.session, "demo; PID 321")
        self.assertEqual(event.timestamp, STAMP)
        mac["processImagePath"] = "/usr/bin/ssh"
        self.assertEqual(macos._parse_mac_ssh(json.dumps(mac)), [])

    def test_windows_collector_includes_sessions_and_survives_denied_security(self) -> None:
        """Unavailable Security must not hide readable RDP/SSH sources."""
        records = [
            {"kind": "status", "source": "Security", "state": "Unavailable", "message": "Access denied"},
            {"kind": "event", "xml": _windows_xml(app.RDP_PROVIDER, 21,
                '<Data Name="Address">192.0.2.1</Data><Data Name="User">demo</Data>')},
            {"kind": "event", "xml": _windows_xml("OpenSSH", 4,
                '<Data Name="process">sshd</Data><Data Name="payload">Accepted publickey for demo from 192.0.2.1 port 54321 ssh2</Data>')},
        ]
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("\n".join(json.dumps(record) for record in records), ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        for token in ("4800,4801,4778,4779", "4624,4634", "21,23,24,25", "OpenSSH/Operational",
                      "OpenSSH/Admin", "FilterXPath", "Data[@Name='LogonType']='10'"):
            self.assertIn(token, script)
        self.assertEqual([event.kind for event in result.events], [app.EventKind.RDP_CONNECT, app.EventKind.SSH_CONNECT])
        self.assertEqual(result.statuses[0].state, app.SourceState.ERROR)

    def test_unix_collectors_request_sshd_logs(self) -> None:
        """Parser support must be reachable from native source queries on both Unix hosts."""
        for collector in (macos._collect_macos, linux_events._collect_linux):
            result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
            with patch.object(Environment, "which", return_value="journalctl"), patch.object(
                common, "_run_command", return_value=("", ""),
            ) as command:
                collector(result, threading.Event(), lambda _text: None)
            arguments = " ".join(" ".join(call.args[0]) for call in command.call_args_list)
            for process in ("sshd", "sshd-session", "sshd-auth"):
                self.assertIn(process, arguments)

    def test_unavailable_source_is_not_an_empty_success(self) -> None:
        """Permission failure leaves a source diagnostic rather than an empty success."""
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(common, "_run_command", side_effect=RuntimeError("Access denied")):
            common._collect_source(result, "Security", ["fixture"], lambda _text: [], threading.Event())
        self.assertEqual(result.statuses[0].state, app.SourceState.ERROR)

    def test_windows_failure_sources_do_not_conflate_reports_and_crashes(self) -> None:
        """Provider-qualified observations distinguish crashes, hangs, bugchecks and reports."""
        cases = (("Application Error", 1000, app.EventKind.APP_CRASH),
                 ("Application Hang", 1002, app.EventKind.APP_HANG),
                 ("Windows Error Reporting", 1001, app.EventKind.DIAGNOSTIC),
                 ("Microsoft-Windows-WER-SystemErrorReporting", 1001, app.EventKind.SYSTEM_CRASH),
                 ("Microsoft-Windows-WHEA-Logger", 17, app.EventKind.DIAGNOSTIC),
                 ("Microsoft-Windows-Diagnostics-Performance", 100, app.EventKind.DIAGNOSTIC))
        for provider, event_id, kind in cases:
            with self.subTest(provider=provider):
                xml = _windows_xml(provider, event_id, '<Data Name="AppName">demo.exe</Data>'
                    '<Data Name="ProcessId">0x123</Data><Data Name="EventName">APPCRASH</Data>')
                event = windows._parse_windows_xml(xml, "Rendered description")[0]
                self.assertEqual(event.kind, kind)
                self.assertIn("demo.exe", event.summary)
                self.assertIn("Rendered description", event.raw)
                self.assertEqual(event.xml, xml)
                self.assertEqual(event.session, "PID 0x123")
                self.assertEqual(windows._parse_windows_xml(xml.replace(provider, "Unrelated")), [])
        old_event = windows._parse_windows_xml(_windows_xml("Application Error", 1000, "<Data>legacy.exe</Data>"))[0]
        self.assertIn("legacy.exe", old_event.summary)
        event = windows._parse_windows_xml(_windows_xml("Microsoft-Windows-WER-SystemErrorReporting", 1001,
            '<Data Name="param1">0x0000009f</Data><Data Name="param2">C:\\Windows\\MEMORY.DMP</Data>'))[0]
        self.assertIn("report time", event.summary)
        self.assertIn("0x0000009f", event.summary)

    def test_mac_ips_uses_incident_time_and_preserves_complete_report(self) -> None:
        """Modern IPS has two JSON objects, not one JSON document or NDJSON body."""
        header = {"bug_type": "309", "app_name": "Demo", "timestamp": "2026-10-10 20:00:00 +0800"}
        body = {"procName": "Demo", "pid": 123, "captureTime": "2026-10-10 20:00:00.000 +0800",
                "exception": {"type": "EXC_BAD_ACCESS"}, "threads": []}
        text = json.dumps(header) + "\n" + json.dumps(body, indent=2)
        event = macos._parse_mac_report(text, Path("Demo.ips"), STAMP + dt.timedelta(days=4))
        self.assertEqual(event.kind, app.EventKind.APP_CRASH)
        self.assertEqual(event.timestamp, STAMP)
        self.assertEqual(event.session, "PID 123")
        self.assertIn("EXC_BAD_ACCESS", event.summary)
        self.assertIn(text, event.raw)
        body["isNonFatal"] = True
        self.assertEqual(macos._parse_mac_report(json.dumps(header) + "\n" + json.dumps(body),
                                              Path("Demo.ips"), STAMP).kind, app.EventKind.DIAGNOSTIC)

    def test_mac_unknown_reports_and_spin_samples_are_not_assumed_crashes_or_hangs(self) -> None:
        """Report extensions and explicit event evidence govern the category conservatively."""
        text = "Process: Demo [123]\nDate/Time: 2026-10-10 20:00:00 +0800\n"
        for suffix, extra, kind in ((".crash", "", app.EventKind.APP_CRASH),
                                   (".hang", "", app.EventKind.APP_HANG),
                                   (".spin", "Event: hang\n", app.EventKind.APP_HANG),
                                   (".spin", "Event: cpu usage\n", app.EventKind.DIAGNOSTIC),
                                   (".panic", "panic(cpu 0 caller): fault", app.EventKind.SYSTEM_CRASH),
                                   (".diag", "", app.EventKind.DIAGNOSTIC)):
            with self.subTest(suffix=suffix, extra=extra):
                event = macos._parse_mac_report(text + extra, Path("Demo" + suffix), STAMP + dt.timedelta(days=4))
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.timestamp, STAMP)
        unknown = macos._parse_mac_report('{"bug_type":"999","timestamp":"invalid"}', Path("unknown.ips"), STAMP)
        self.assertEqual(unknown.kind, app.EventKind.DIAGNOSTIC)
        self.assertIn("file modification time", unknown.summary)
        self.assertEqual(unknown.timestamp, STAMP)
        panic = macos._parse_mac_report('{"timestamp":"2026-10-10T12:00:00Z","panicString":"panic(cpu 0)"}', Path("panic.ips"), STAMP)
        self.assertEqual(panic.kind, app.EventKind.SYSTEM_CRASH)

    def test_mac_report_collection_is_bounded_and_keeps_partial_results(self) -> None:
        """Malformed and oversized files do not hide good reports or bypass query bounds."""
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="diagnostics-") as directory:
            folder = Path(directory)
            (folder / "Retired").mkdir()
            (folder / "good.crash").write_text("Process: Demo\nDate/Time: 2026-10-10 20:00:00 +0800\n", encoding="utf-8")
            (folder / "Retired/old.crash").write_text("Date/Time: 2026-10-09 20:00:00 +0800\n", encoding="utf-8")
            (folder / "bad.ips").write_text("{broken", encoding="utf-8")
            (folder / "large.diag").write_text("x" * 1025, encoding="utf-8")
            result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
            with patch.object(macos, "MAX_REPORT_BYTES", 1024):
                macos._collect_mac_reports(result, threading.Event(), (folder,))
            self.assertEqual(len(result.events), 1)
            self.assertEqual(result.events[0].kind, app.EventKind.APP_CRASH)
            self.assertEqual(result.statuses[0].state, app.SourceState.LIMITED)
            self.assertIn("Skipped 2", result.statuses[0].message)
            self.assertEqual(result.statuses[1].state, app.SourceState.EMPTY)
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(InterruptedError):
                macos._collect_mac_reports(result, cancelled, (folder,))
            limited = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
            with patch.object(macos, "MAX_REPORT_TOTAL_BYTES", 1):
                macos._collect_mac_reports(limited, threading.Event(), (folder,))
            self.assertEqual(limited.events, [])
            self.assertEqual(limited.statuses[0].state, app.SourceState.LIMITED)

    def test_linux_diagnostics_use_native_evidence_and_process_identity(self) -> None:
        """A coredump PID is the crashed process, not the reporting daemon's PID."""
        records = [
            {"MESSAGE_ID": app.COREDUMP_MESSAGE_ID, "SYSLOG_IDENTIFIER": "systemd-coredump",
             "COREDUMP_PID": "123", "_PID": "999", "COREDUMP_EXE": "/usr/bin/demo",
             "COREDUMP_SIGNAL_NAME": "SIGSEGV", "MESSAGE": "Process dumped core"},
            {"SYSLOG_IDENTIFIER": "systemd", "UNIT": "demo.service", "MESSAGE": "demo.service: Watchdog timeout (limit 1min)!"},
            {"_TRANSPORT": "kernel", "MESSAGE": "Kernel panic - not syncing: Fatal exception"},
            {"_TRANSPORT": "kernel", "PRIORITY": "3", "MESSAGE": "Out of memory: Killed process 123 (demo)"},
            {"SYSLOG_IDENTIFIER": "systemd", "PRIORITY": "3", "MESSAGE": "demo.service: Failed with result 'exit-code'."},
            {"SYSLOG_IDENTIFIER": "unrelated", "MESSAGE": "Kernel panic - not syncing: fake"},
            {"SYSLOG_IDENTIFIER": "systemd", "PRIORITY": "6", "MESSAGE": "Ignoring watchdog timeout (limit 1min)!"},
        ]
        for record in records:
            record["__REALTIME_TIMESTAMP"] = str(int(STAMP.timestamp() * 1_000_000))
        events = linux_events._parse_linux_journal("\n".join(json.dumps(record) for record in records))
        self.assertEqual([event.kind for event in events], [app.EventKind.APP_CRASH, app.EventKind.APP_HANG,
                         app.EventKind.SYSTEM_CRASH, app.EventKind.RESOURCE, app.EventKind.SERVICE])
        self.assertEqual(events[0].session, "PID 123")
        self.assertEqual(events[1].session, "demo.service")

    def test_diagnostic_collectors_request_new_sources_and_report_limits(self) -> None:
        """Exercise native command boundaries as well as parsers."""
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("", ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        for token in ("Application Error", "Application Hang", "Windows Error Reporting",
                      "Microsoft-Windows-WER-SystemErrorReporting", "Microsoft-Windows-WHEA-Logger",
                      "Microsoft-Windows-Diagnostics-Performance/Operational", "Level=@(1,2,3)"):
            self.assertIn(token, script)
        with patch.object(Environment, "which", return_value="journalctl"), patch.object(
            common, "_run_command", return_value=("{}\n{}", ""),
        ) as command, patch.object(linux_events, "_parse_linux_journal", return_value=[]), patch.object(linux_events, "MAX_EVENTS", 1):
            linux_events._collect_linux(result, threading.Event(), lambda _text: None)
        args = command.call_args.args[0]
        self.assertIn(f"MESSAGE_ID={app.COREDUMP_MESSAGE_ID}", args)
        self.assertIn("--lines=2", args)
        self.assertIn("--reverse", args)
        status = next(status for status in result.statuses if status.source == "Journal diagnostics")
        self.assertEqual(status.state, app.SourceState.LIMITED)

    def test_query_uses_half_open_range_and_deduplicates_exact_records(self) -> None:
        """End-boundary records are excluded while the start boundary is retained."""
        def collect(result: app.QueryResult, cancelled: threading.Event, progress: object) -> None:
            first = app.PowerEvent(STAMP, app.EventKind.WAKE, "wake", "fixture", "1")
            result.events.extend([first, first, app.PowerEvent(STAMP + dt.timedelta(hours=1), app.EventKind.LOCK, "lock", "fixture", "2")])

        with patch.object(sys, "platform", "darwin"), patch.object(macos, "_collect_macos", side_effect=collect):
            result = history.query_events(STAMP, STAMP + dt.timedelta(hours=1), threading.Event())
        self.assertEqual(len(result.events), 1)

    def test_cancellation_reaps_a_running_child(self) -> None:
        """Cancellation stops a waiting native-source process promptly."""
        cancelled = threading.Event()
        timer = threading.Timer(0.15, cancelled.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(InterruptedError):
                common._run_command([sys.executable, "-c", "import time; time.sleep(10)"], cancelled)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 3)

    def test_exports_preserve_evidence_and_escape_csv_formulas(self) -> None:
        """JSON keeps source coverage/raw evidence; CSV neutralizes formula-like log fields."""
        event = app.PowerEvent(STAMP, app.EventKind.LOCK, "=danger", "fixture", raw="raw\nrecord")
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), [event])
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="power-events-export-") as directory:
            path = Path(directory) / "events.json"
            history.export_events(path, [event], result)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["events"][0]["raw"], "raw\nrecord")
            path = path.with_suffix(".csv")
            history.export_events(path, [event], result)
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["summary"], "'=danger")


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is not installed")
class ActivityTests(unittest.TestCase):
    """Exercise all nine added categories through native parser and query boundaries."""

    def test_windows_activity_is_provider_qualified_and_queried(self) -> None:
        cases = (("Microsoft-Windows-Kernel-Power", 105, app.EventKind.BATTERY),
                 ("Microsoft-Windows-Kernel-General", 1, app.EventKind.TIME_CHANGE),
                 (app.SECURITY_PROVIDER, 4625, app.EventKind.AUTHENTICATION),
                 ("Microsoft-Windows-WindowsUpdateClient", 20, app.EventKind.UPDATE),
                 ("Microsoft-Windows-Resource-Exhaustion-Detector", 2004, app.EventKind.RESOURCE),
                 ("Service Control Manager", 7031, app.EventKind.SERVICE),
                 ("disk", 153, app.EventKind.FILESYSTEM),
                 ("Microsoft-Windows-Kernel-PnP", 410, app.EventKind.DEVICE_CHANGE),
                 ("Microsoft-Windows-NetworkProfile", 10001, app.EventKind.NETWORK))
        records = []
        for provider, event_id, kind in cases:
            with self.subTest(provider=provider):
                xml = _windows_xml(provider, event_id, '<Data Name="TargetUserName">demo</Data>')
                event = windows._parse_windows_xml(xml, "Native message")[0]
                self.assertEqual(event.kind, kind)
                self.assertIn("Native message", event.summary)
                self.assertEqual(event.xml, xml)
                self.assertEqual(windows._parse_windows_xml(xml.replace(provider, "Other")), [])
                records.append({"kind": "event", "xml": xml})
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("\n".join(map(json.dumps, records)), ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        self.assertEqual({event.kind for event in result.events}, {kind for _, _, kind in cases})
        for provider, event_id, _ in cases:
            self.assertTrue(any(f"ProviderName='{provider}'" in line and str(event_id) in line
                                for line in script.splitlines()))
        self.assertEqual(windows._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-PnP", 999)), [])
        battery = windows._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-Power", 105,
            '<Data Name="AcOnline">false</Data><Data Name="RemainingCapacity">0</Data>'
            '<Data Name="FullChargeCapacity">40000</Data>'))[0]
        self.assertIn("AcOnline=false", battery.summary)
        self.assertIn("RemainingCapacity=0", battery.summary)
        self.assertIn("FullChargeCapacity=40000", battery.summary)

    def test_linux_activity_requires_system_source_and_explicit_message(self) -> None:
        cases = (("upowerd", "battery state changed to discharging", app.EventKind.BATTERY),
                 ("systemd-timesyncd", "Initial clock synchronization to time server", app.EventKind.TIME_CHANGE),
                 ("sshd", "Failed password for demo from 192.0.2.1 port 22 ssh2", app.EventKind.AUTHENTICATION),
                 ("PackageKit", "update-packages transaction completed", app.EventKind.UPDATE),
                 ("kernel", "Out of memory: Killed process 45 (demo)", app.EventKind.RESOURCE),
                 ("systemd", "Started demo.service - Demo service.", app.EventKind.SERVICE),
                 ("kernel", "EXT4-fs error (device sda1): bad checksum", app.EventKind.FILESYSTEM),
                 ("kernel", "usb 1-2: USB disconnect, device number 3", app.EventKind.DEVICE_CHANGE),
                 ("NetworkManager", "device (wlan0): state change: activated -> disconnected", app.EventKind.NETWORK))
        for identifier, message, kind in cases:
            with self.subTest(kind=kind):
                record = {"SYSLOG_IDENTIFIER": identifier, "MESSAGE": message, "__CURSOR": "record-1",
                          "__REALTIME_TIMESTAMP": str(int(STAMP.timestamp() * 1_000_000))}
                if identifier == "kernel":
                    record["_TRANSPORT"] = "kernel"
                event = linux_events._parse_linux_journal(json.dumps(record))[0]
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.summary, message)
                record["SYSLOG_IDENTIFIER"] = "unrelated"
                record.pop("_TRANSPORT", None)
                self.assertEqual(linux_events._parse_linux_journal(json.dumps(record)), [])
        record = {"SYSLOG_IDENTIFIER": "NetworkManager", "MESSAGE": "state change requested",
                  "__REALTIME_TIMESTAMP": str(int(STAMP.timestamp() * 1_000_000))}
        self.assertEqual(linux_events._parse_linux_journal(json.dumps(record)), [])

    def test_macos_activity_requires_known_process_and_preserves_evidence(self) -> None:
        from personal_system_event_viewer import macos_activity
        cases = (("powerd", "Battery level low: 5 percent", app.EventKind.BATTERY),
                 ("timed", "System clock stepped by 3 seconds", app.EventKind.TIME_CHANGE),
                 ("authd", "Authentication failed for demo", app.EventKind.AUTHENTICATION),
                 ("softwareupdated", "Installation failed for update", app.EventKind.UPDATE),
                 ("kernel", "memorystatus: killing process 43 due to memory limit", app.EventKind.RESOURCE),
                 ("launchd", "demo: service exited with code 1", app.EventKind.SERVICE),
                 ("kernel", "apfs: I/O error on disk1", app.EventKind.FILESYSTEM),
                 ("diskarbitrationd", "disk appeared: disk3", app.EventKind.DEVICE_CHANGE),
                 ("airportd", "link down: en0", app.EventKind.NETWORK))
        predicate = macos_activity.activity_predicate()
        for process, message, kind in cases:
            with self.subTest(kind=kind):
                record = {"processImagePath": f"/usr/libexec/{process}", "eventMessage": message,
                          "timestamp": STAMP.isoformat(), "processID": 43, "machTimestamp": 100}
                event = macos_activity.parse_activity(json.dumps(record))[0]
                self.assertEqual(event.kind, kind)
                self.assertEqual(event.summary, message)
                self.assertEqual(json.loads(event.raw), record)
                self.assertIn(f'process == "{process}"', predicate)
                record["processImagePath"] = "/usr/bin/unrelated"
                self.assertEqual(macos_activity.parse_activity(json.dumps(record)), [])
        self.assertEqual(macos_activity.parse_activity(json.dumps({"process": "airportd", "eventMessage": "connection requested"})), [])

    def test_unix_activity_queries_and_ssh_failure_classification(self) -> None:
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(common, "_run_command", return_value=("", "")) as command, patch.object(
            macos, "_collect_mac_reports",
        ):
            macos._collect_macos(result, threading.Event(), lambda _text: None)
        self.assertTrue(any("--predicate" in call.args[0] and 'process == "softwareupdated"' in call.args[0][-1]
                            for call in command.call_args_list))
        with patch.object(Environment, "which", return_value="journalctl"), patch.object(
            common, "_run_command", return_value=("", ""),
        ) as command:
            linux_events._collect_linux(result, threading.Event(), lambda _text: None)
        self.assertTrue(any("SYSLOG_IDENTIFIER=NetworkManager" in call.args[0] and "--lines=50001" in call.args[0]
                            for call in command.call_args_list))
        message = "Failed password for demo from 192.0.2.1 port 22 ssh2"
        xml = _windows_xml("OpenSSH", 4, f'<Data Name="process">sshd</Data><Data Name="payload">{message}</Data>')
        self.assertEqual(windows._parse_windows_xml(xml)[0].kind, app.EventKind.AUTHENTICATION)
        record = {"process": "sshd", "eventMessage": message, "timestamp": STAMP.isoformat()}
        self.assertEqual(macos._parse_mac_ssh(json.dumps(record))[0].kind, app.EventKind.AUTHENTICATION)


class SmbTests(unittest.TestCase):
    """Separate network authentication, SMB failure and share authorization evidence."""

    def test_network_authentication_does_not_claim_smb(self) -> None:
        for event_id, outcome in ((4624, "succeeded"), (4625, "failed")):
            with self.subTest(event_id=event_id):
                xml = _windows_xml(app.SECURITY_PROVIDER, event_id,
                    '<Data Name="LogonType">3</Data><Data Name="TargetUserName">demo</Data>'
                    '<Data Name="TargetDomainName">EXAMPLE</Data><Data Name="TargetLogonId">0x123</Data>'
                    '<Data Name="IpAddress">192.0.2.10</Data><Data Name="Status">0xc000006d</Data>')
                event = windows._parse_windows_xml(xml)[0]
                self.assertEqual(event.kind, app.EventKind.NETWORK_AUTH)
                self.assertIn(outcome, event.summary)
                self.assertIn("protocol not established", event.summary)
                self.assertNotIn("SMB", event.summary)
                self.assertIn("192.0.2.10", event.summary)
                self.assertIn("EXAMPLE\\demo", event.session)
                self.assertIn("0x123", event.session)
        ordinary = windows._parse_windows_xml(_windows_xml(app.SECURITY_PROVIDER, 4625,
            '<Data Name="LogonType">2</Data>'))[0]
        self.assertEqual(ordinary.kind, app.EventKind.AUTHENTICATION)

    def test_share_audit_outcomes_use_keywords_and_retain_paths(self) -> None:
        for event_id in (5140, 5145):
            for keywords, expected in (("0x8020000000000000", "succeeded" if event_id == 5140 else "allowed at share level"),
                                       ("0x8010000000000000", "failed" if event_id == 5140 else "denied at share level"),
                                       ("", "outcome unavailable"), ("invalid", "outcome unavailable"),
                                       ("0x8030000000000000", "outcome unavailable")):
                with self.subTest(event_id=event_id, keywords=keywords):
                    xml = _windows_xml(app.SECURITY_PROVIDER, event_id,
                        '<Data Name="SubjectUserName">demo</Data><Data Name="SubjectLogonId">0x456</Data>'
                        '<Data Name="ShareName">\\\\HOST\\Share</Data><Data Name="RelativeTargetName">folder/file.txt</Data>'
                        '<Data Name="AccessMask">0x1</Data><Data Name="AccessReason">native check</Data>')
                    xml = xml.replace('</System>', f'<Keywords>{keywords}</Keywords></System>')
                    event = windows._parse_windows_xml(xml)[0]
                    self.assertEqual(event.kind, app.EventKind.SMB)
                    self.assertIn(expected, event.summary)
                    self.assertIn("folder/file.txt", event.summary)
                    self.assertIn("AccessMask=0x1", event.summary)
                    self.assertEqual(event.xml, xml)
                    self.assertIn("0x456", event.session)
                    self.assertEqual(windows._parse_windows_xml(xml.replace(app.SECURITY_PROVIDER, "Other")), [])
        self.assertIn("not proof of completed file access", windows._parse_windows_xml(
            _windows_xml(app.SECURITY_PROVIDER, 5145).replace('</System>', '<Keywords>0x8020000000000000</Keywords></System>'))[0].summary)

    def test_smb_failure_and_native_queries(self) -> None:
        xml = _windows_xml("Microsoft-Windows-SMBServer", 551,
            '<Data Name="UserName">EXAMPLE\\demo</Data><Data Name="ClientName">client</Data>'
            '<Data Name="Status">0xc000006d</Data><Data Name="SessionId">0x789</Data>')
        event = windows._parse_windows_xml(xml, "SMB authentication failed")[0]
        self.assertEqual(event.kind, app.EventKind.SMB)
        self.assertIn("authentication failed", event.summary)
        self.assertIn("0xc000006d", event.summary)
        self.assertIn("0x789", event.session)
        self.assertEqual(windows._parse_windows_xml(xml.replace("SMBServer", "SMBClient")), [])
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        records = [{"kind": "event", "xml": xml},
                   {"kind": "status", "source": "Security / 5145", "state": "Unavailable", "message": "Access denied"}]
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("\n".join(map(json.dumps, records)), ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        for selector in ("Id=@(5140)", "Id=@(5145)", "Id=@(4624)", "Id=@(551)",
                         "Microsoft-Windows-SMBServer/Security", "Data[@Name='LogonType']='3'", "$filter.Id.Count -eq 1"):
            self.assertIn(selector, script)
        self.assertEqual(len(result.events), 1)
        self.assertTrue(any(status.state == app.SourceState.ERROR for status in result.statuses))


class DeviceEjectionTests(unittest.TestCase):
    """Validate shared historical identities and resilience of mixed event queries."""

    def xml(self, device: str = r"USB\VID_1234&PID_5678\serial") -> str:
        """Build event 225 with the native process and device fields."""
        data = {"ProcessId": "4321", "ProcessName": r"\Device\HarddiskVolume3\应用\busy.exe",
                "DeviceInstance": device, "VetoingDevices": r"USBSTOR\Disk&Ven_Test"}
        return _windows_xml("Microsoft-Windows-Kernel-PnP", 225,
                            "".join(f'<Data Name="{key}">{escape(value)}</Data>' for key, value in data.items()))

    def test_recorded_identity_shared_with_cli_and_preserved_in_export(self) -> None:
        spec = importlib.util.spec_from_file_location("ejection_cli_test", ROOT / "tools/windows/device-ejection-history.py")
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        self.assertIs(cli._parse_event, parse_device_ejection_event)
        self.assertIs(cli.EjectEvent, DeviceEjectionEvent)
        for device in (r"USB\VID_1234&PID_5678\serial", r"PCI\VEN_1234&DEV_5678\0"):
            with self.subTest(device=device):
                xml = self.xml(device)
                parsed = parse_device_ejection_event(xml)
                event = windows._parse_windows_xml(xml, "Localized veto description")[0]
                self.assertEqual(event.kind, app.EventKind.DEVICE_EJECT_BLOCKED)
                self.assertEqual(parsed.pid, 4321)
                self.assertEqual(parsed.time, event.timestamp)
                self.assertEqual(event.session, "PID 4321")
                for value in (device, parsed.executable, parsed.affected_devices):
                    self.assertIn(value, event.summary)
                self.assertEqual(event.xml, xml)
                with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
                    output = Path(folder) / "events.json"
                    result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), [event])
                    history.export_events(output, [event], result)
                    exported = json.loads(output.read_text(encoding="utf-8"))["events"][0]
                    self.assertEqual(exported["summary"], event.summary)
                    self.assertIn(xml, exported["raw"])

    def test_decoder_rejects_wrong_sources_and_missing_identity(self) -> None:
        xml = self.xml()
        for invalid in (xml.replace("Kernel-PnP", "Other"), xml.replace("225", "226"),
                        xml.replace("4321", "-1"), xml.replace("4321", "invalid"),
                        xml.replace('Name="ProcessName"', 'Name="OtherName"'),
                        xml.replace("2026-10-10T12:00:00.0000000Z", "2026-10-10T12:00:00")):
            with self.subTest(xml=invalid), self.assertRaises(ValueError):
                parse_device_ejection_event(invalid)
        self.assertEqual(windows._parse_windows_xml(xml.replace("Kernel-PnP", "Other")), [])

    def test_invalid_ejection_does_not_drop_later_sources(self) -> None:
        records = [{"kind": "event", "xml": self.xml().replace("4321", "invalid")},
                   {"kind": "event", "xml": self.xml()},
                   {"kind": "event", "xml": _windows_xml("Application Error", 1000)},
                   {"kind": "status", "source": "System / Kernel-PnP", "state": "Read", "count": 2, "message": "Read"}]
        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1))
        with patch.object(Environment, "find_pwsh", return_value="pwsh"), patch.object(
            common, "_run_command", return_value=("\n".join(json.dumps(record) for record in records), ""),
        ) as command:
            windows._collect_windows(result, threading.Event(), lambda _text: None)
        script = base64.b64decode(command.call_args.args[0][-1]).decode("utf-16-le")
        self.assertIn("@{LogName='System'; ProviderName='Microsoft-Windows-Kernel-PnP'; Id=@(225)}", script)
        self.assertEqual([event.kind for event in result.events], [app.EventKind.DEVICE_EJECT_BLOCKED, app.EventKind.APP_CRASH])
        self.assertTrue(any(status.state == app.SourceState.LIMITED and "invalid" in status.message for status in result.statuses))
        self.assertTrue(any(status.source == "System / Kernel-PnP" for status in result.statuses))


class EntryIntegrationTests(unittest.TestCase):
    """Check real discovery rules and compiler staging without building executables."""

    def test_entry_discovery_and_compiler_staging(self) -> None:
        modules = []
        for filename in ("run-script.py", "compile-script.py"):
            spec = importlib.util.spec_from_file_location("system_event_" + filename[:-3], ROOT / filename)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            modules.append(module)
        launcher, compiler = modules
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
            scratch = Path(folder)
            shutil.copy2(ROOT / "launcher-config.yaml", scratch / "launcher-config.yaml")
            config = launcher._load_launcher_config(str(scratch))
            with patch.object(Environment, "find_bash", return_value=None), patch.object(Environment, "find_pwsh", return_value=None):
                listing = launcher.find_scripts(str(ROOT / "tools"), config)
            for paths in (listing, compiler.find_py_scripts(str(ROOT / "tools"))):
                normalized = [path.replace("\\", "/") for path in paths]
                self.assertIn("others/system-event-viewer.py", normalized)
                self.assertNotIn("others/power-event-viewer.py", normalized)
                self.assertFalse(any(path.startswith("others/system-event-viewer/") for path in normalized))
            stages: list[Path] = []

            def inspect(command: list[str], *, check: bool, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
                stage = Path(env["PYTHONPATH"].split(os.pathsep)[0])
                stages.append(stage)
                package = stage / entry.PACKAGE_NAME
                source = ROOT / "tools/others/system-event-viewer"
                self.assertEqual({path.name for path in source.glob("*.py")}, {path.name for path in package.glob("*.py")})
                self.assertFalse((package / "README.md").exists())
                self.assertTrue(any(entry.PACKAGE_NAME in option for option in command))
                return subprocess.CompletedProcess(command, 0)

            for builder in ("nuitka", "pyinstaller"):
                with patch.object(compiler.subprocess, "run", side_effect=inspect):
                    compiler._run_compiler(["compiler", entry.__file__], entry.__file__, folder, builder)
            self.assertTrue(all(not stage.exists() for stage in stages))


class GuiTests(unittest.TestCase):
    """Exercise actual Qt controls with fixture history and isolated settings."""

    def test_platform_filter_defaults_and_saved_choices(self) -> None:
        """Disabled types stay off through All, saved preferences and platform changes."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtCore, QtWidgets

        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        common = {app.EventKind.STARTUP, app.EventKind.SHUTDOWN, app.EventKind.SLEEP,
                  app.EventKind.WAKE, app.EventKind.HIBERNATE, app.EventKind.LOCK, app.EventKind.UNLOCK,
                  app.EventKind.SSH_CONNECT, app.EventKind.SSH_DISCONNECT,
                  app.EventKind.APP_CRASH, app.EventKind.APP_HANG, app.EventKind.SYSTEM_CRASH, app.EventKind.DIAGNOSTIC,
                  app.EventKind.BATTERY, app.EventKind.TIME_CHANGE, app.EventKind.AUTHENTICATION,
                  app.EventKind.UPDATE, app.EventKind.RESOURCE, app.EventKind.SERVICE,
                  app.EventKind.FILESYSTEM, app.EventKind.DEVICE_CHANGE, app.EventKind.NETWORK}
        default_off = {app.EventKind.APP_CRASH, app.EventKind.APP_HANG, app.EventKind.BATTERY,
                       app.EventKind.TIME_CHANGE, app.EventKind.AUTHENTICATION, app.EventKind.UPDATE,
                       app.EventKind.RESOURCE, app.EventKind.SERVICE, app.EventKind.FILESYSTEM,
                       app.EventKind.DEVICE_CHANGE, app.EventKind.NETWORK, app.EventKind.NETWORK_AUTH, app.EventKind.SMB}
        expected = {"linux": common, "darwin": common | {app.EventKind.DARK_WAKE},
                    "win32": set(app.EventKind) - {app.EventKind.DARK_WAKE}}
        original = QtCore.QSettings.defaultFormat()
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
        try:
            with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="power-platforms-") as directory:
                for platform_name, available in expected.items():
                    with self.subTest(platform=platform_name):
                        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope,
                                                str(Path(directory) / platform_name))
                        events = [app.PowerEvent(STAMP, kind, kind.value, "fixture") for kind in app.EventKind]
                        result = app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), events)
                        with patch.object(history, "query_events", return_value=result), patch.object(sys, "platform", platform_name):
                            self.assertEqual(ui._launch_gui(), 0)
                            window = application.property("powerEventsWindow")
                            deadline = time.monotonic() + 5
                            while window.result is None or window.worker is not None:
                                application.processEvents()
                                self.assertLess(time.monotonic(), deadline)
                                time.sleep(0.01)
                        for kind, checkbox in window.checkboxes.items():
                            self.assertEqual(checkbox.isEnabled(), kind in available)
                            self.assertEqual(checkbox.isChecked(), kind in available - default_off)
                        self.assertEqual(window.proxy.rowCount(), len(available - default_off))
                        window._select_types(False)
                        self.assertEqual(window.proxy.rowCount(), 0)
                        window._select_types(True)
                        self.assertEqual(window.proxy.rowCount(), len(available))
                        # Reset uses defaults without querying or changing the date range.
                        bounds = (window.start_edit.dateTime(), window.end_edit.dateTime())
                        window.reset_types_button.click()
                        self.assertEqual(window.proxy.rowCount(), len(available - default_off))
                        self.assertEqual((window.start_edit.dateTime(), window.end_edit.dateTime()), bounds)
                        self.assertIs(window.result, result)
                        window.resize(1000, 700)
                        application.processEvents()
                        narrow_columns = window.filter_columns
                        window.resize(1600, 900)
                        application.processEvents()
                        self.assertGreater(window.filter_columns, narrow_columns)
                        self.assertEqual(window.filter_grid.count(), len(app.EventKind) - 9)
                        # Group switches control all members, limited to platform support.
                        groups = {
                            app.EventKind.STARTUP: ("Startup / Shutdown", {app.EventKind.STARTUP, app.EventKind.SHUTDOWN}),
                            app.EventKind.SLEEP: ("Sleep / Wake", {app.EventKind.SLEEP, app.EventKind.WAKE,
                                                                 app.EventKind.STANDBY_ENTER, app.EventKind.STANDBY_EXIT}),
                            app.EventKind.LOCK: ("Lock / Unlock", {app.EventKind.LOCK, app.EventKind.UNLOCK}),
                            app.EventKind.LOGON: ("Logon / Logoff", {app.EventKind.LOGON, app.EventKind.LOGOFF}),
                            app.EventKind.RDP_CONNECT: ("RDP", {app.EventKind.RDP_CONNECT, app.EventKind.RDP_RECONNECT,
                                                               app.EventKind.RDP_DISCONNECT}),
                            app.EventKind.SSH_CONNECT: ("SSH", {app.EventKind.SSH_CONNECT, app.EventKind.SSH_DISCONNECT}),
                        }
                        for primary, (label, group) in groups.items():
                            self.assertEqual(window.checkboxes[primary].text(), label)
                            for member in group - {primary}:
                                self.assertNotIn(member, window.checkboxes)
                            window._select_types(False)
                            window.checkboxes[primary].setChecked(True)
                            members = group & available
                            self.assertEqual(window.proxy.allowed, members)
                            self.assertEqual(window.proxy.rowCount(), len(members))
                            window.checkboxes[primary].setChecked(False)
                            self.assertEqual(window.proxy.rowCount(), 0)
                            # A previously selected stop/disconnect member must survive migration.
                            window.settings.setValue("knownTypes", [kind.value for kind in app.EventKind])
                            for legacy_member in members:
                                window.settings.setValue("types", [legacy_member.value])
                                window._restore_settings()
                                self.assertEqual(window._selected_types(), members)
                        # Either old member being selected enables the combined group.
                        window.settings.setValue("knownTypes", [kind.value for kind in app.EventKind])
                        window.settings.setValue("types", [app.EventKind.STANDBY_ENTER.value, app.EventKind.WAKE.value])
                        window._restore_settings()
                        merged = {app.EventKind.SLEEP, app.EventKind.WAKE, app.EventKind.STANDBY_ENTER,
                                  app.EventKind.STANDBY_EXIT} & available
                        self.assertEqual(window._selected_types(), merged)
                        # Old/cross-platform settings cannot select unsupported categories.
                        window.settings.setValue("types", [kind.value for kind in app.EventKind])
                        window.settings.setValue("knownTypes", [kind.value for kind in app.EventKind])
                        window._restore_settings()
                        self.assertEqual(window._selected_types(), available)
                        window.checkboxes[app.EventKind.SLEEP].setChecked(False)
                        window.close()
                        application.processEvents()
                        self.assertEqual(set(window.settings.value("knownTypes")), {kind.value for kind in available})
                        window._restore_settings()
                        self.assertFalse(window.checkboxes[app.EventKind.SLEEP].isChecked())
                        for member in merged:
                            self.assertNotIn(member.value, window.settings.value("types"))
                        self.assertTrue(window.checkboxes[app.EventKind.NETWORK].isChecked())
        finally:
            QtCore.QSettings.setDefaultFormat(original)

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
                with patch.object(history, "query_events", return_value=result) as query, patch.object(sys, "platform", "win32"):
                    self.assertEqual(ui._launch_gui(), 0)
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
                    self.assertEqual(dialog.call_args.args[2], "system-events.csv")
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
                    modern_events = [windows._parse_windows_xml(_windows_xml("Microsoft-Windows-Kernel-Power", event_id))[0]
                                     for event_id in (506, 507, 566)]
                    window._loaded(app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), modern_events))
                    self.assertEqual(window.proxy.rowCount(), 3)
                    self.assertFalse(window.checkboxes[app.EventKind.STARTUP].isChecked())
                    self.assertTrue(app.LOGIN_EVENT_KINDS.issubset(window._selected_types()))
                    for kind in app.DIAGNOSTIC_EVENT_KINDS:
                        self.assertEqual(window.checkboxes[kind].isChecked(), kind not in
                                         {app.EventKind.APP_CRASH, app.EventKind.APP_HANG})
                    self.assertTrue(window.checkboxes[app.EventKind.DEVICE_EJECT_BLOCKED].isChecked())
                    window.checkboxes[app.EventKind.POWER_SESSION].setChecked(False)
                    self.assertEqual(window.proxy.rowCount(), 2)
                    self.assertEqual(query.call_count, 1)
                    window.close()
                    application.processEvents()
                    window._restore_settings()
                    self.assertFalse(window.checkboxes[app.EventKind.POWER_SESSION].isChecked())
                    self.assertTrue(window.checkboxes[app.EventKind.SLEEP].isChecked())
                    # Settings from the immediately preceding release know Modern Standby,
                    # but must still expose new login categories and let users persist filters.
                    window.settings.setValue("knownTypes", [kind.value for kind in app.EventKind
                                                           if kind not in app.LOGIN_EVENT_KINDS | app.DIAGNOSTIC_EVENT_KINDS])
                    window._restore_settings()
                    for kind in app.DIAGNOSTIC_EVENT_KINDS:
                        self.assertEqual(window.checkboxes[kind].isChecked(), kind not in
                                         {app.EventKind.APP_CRASH, app.EventKind.APP_HANG})
                    login_events = [app.PowerEvent(STAMP, kind, kind.value, "fixture") for kind in app.LOGIN_EVENT_KINDS]
                    window._loaded(app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), login_events))
                    self.assertEqual(window.proxy.rowCount(), len(app.LOGIN_EVENT_KINDS))
                    window.checkboxes[app.EventKind.SSH_CONNECT].setChecked(False)
                    self.assertEqual(window.proxy.rowCount(), len(app.LOGIN_EVENT_KINDS) - 2)
                    # XML remains separate from localized messages, with repeated nodes
                    # and markup-like values preserved as plain text in source order.
                    xml = _windows_xml(app.SECURITY_PROVIDER, 4800,
                        '<Data Name="TargetUserName">demo</Data>'
                        '<Data Name="Note">&lt;b&gt;literal&lt;/b&gt;</Data><Data Name="Note">second</Data>')
                    xml_event = windows._parse_windows_xml(xml, "Localized description")[0]
                    self.assertEqual(xml_event.xml, xml)
                    window._select_types(True)
                    window._loaded(app.QueryResult(STAMP, STAMP + dt.timedelta(hours=1), [xml_event]))
                    window.table.selectRow(0)
                    application.processEvents()
                    root_item = window.xml_tree.topLevelItem(0)
                    self.assertEqual(root_item.text(0), "Event")
                    self.assertIn("schemas.microsoft.com", root_item.toolTip(0))
                    data_item = root_item.child(1)
                    self.assertEqual(data_item.text(0), "EventData")
                    self.assertEqual(data_item.childCount(), 3)
                    self.assertEqual(data_item.child(1).text(0), "Data [Note]")
                    self.assertEqual(data_item.child(1).text(1), "<b>literal</b>")
                    self.assertEqual(data_item.child(2).text(1), "second")
                    self.assertIn('Name="Note"', data_item.child(1).text(2))
                    self.assertIn("Localized description", window.detail.toPlainText())
                    # Changing to non-XML evidence or clearing the filter removes stale XML.
                    window._loaded(result)
                    window.table.selectRow(0)
                    application.processEvents()
                    self.assertEqual(window.xml_tree.topLevelItemCount(), 0)
                    self.assertIn("no XML record", window.xml_notice.text())
                    window._show_xml(app.PowerEvent(STAMP, app.EventKind.LOCK, "bad", "fixture", xml="<broken>"))
                    self.assertIn("Cannot display", window.xml_notice.text())
                    window._select_types(False)
                    self.assertEqual(window.xml_tree.topLevelItemCount(), 0)
                    self.assertIn("Select an event", window.xml_notice.text())
            finally:
                QtCore.QSettings.setDefaultFormat(original)


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
