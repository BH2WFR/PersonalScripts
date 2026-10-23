"""Verify event-225 decoding, historical filtering and elevation guards.

Run: conda run -n base python -m unittest discover -s test -p test_usb_eject_log.py
Tests do not elevate, read real logs, or modify devices/logs.
"""

from collections.abc import Generator
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("usb_eject_log_test_target", ROOT / "tools/windows/usb-eject-log.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def event_xml(pid: int = 123, affected: str = "") -> str:
    """Build a localized-path event with publisher PID deliberately different."""
    return f'''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
<System><Provider Name="Microsoft-Windows-Kernel-PnP"/><EventID>225</EventID>
<TimeCreated SystemTime="2026-10-23T01:02:03.1234567Z"/><EventRecordID>987</EventRecordID>
<Execution ProcessID="4"/></System><EventData>
<Data Name="DeviceInstance">USB\\VID_1234&amp;PID_ABCD\\example</Data>
<Data Name="ProcessName">\\Device\\HarddiskVolume2\\工具 🔴\\viewer.exe</Data>
<Data Name="ProcessId">{pid}</Data>
<Data Name="VetoingDevices">{escape(affected)}</Data>
</EventData></Event>'''


class UsbEjectLogTests(unittest.TestCase):
    """Test historical identity, named fields, filtered limits and failures."""

    def test_named_fields_use_blocker_not_publisher_pid(self) -> None:
        event = runner._parse_event(event_xml())
        self.assertEqual(event.pid, 123)
        self.assertEqual(event.device, r"USB\VID_1234&PID_ABCD\example")
        self.assertIn("工具 🔴", event.executable)
        self.assertEqual(event.time.microsecond, 123456)
        self.assertIsNotNone(event.time.tzinfo)
        self.assertEqual(event.affected_devices, "")

    def test_other_events_and_missing_fields_are_rejected(self) -> None:
        for xml in (event_xml().replace("<EventID>225", "<EventID>226"),
                    event_xml().replace('Name="ProcessId"', 'Name="Other"'),
                    event_xml().replace("Kernel-PnP", "Other")):
            with self.assertRaises(ValueError):
                runner._parse_event(xml)

    def test_filters_precede_limit_and_generator_is_closed(self) -> None:
        closed: list[bool] = []

        def records(minutes: int) -> Generator[str, None, None]:
            try:
                yield event_xml(999)
                yield event_xml(123, "STORAGE\\target")
                yield event_xml(123, "STORAGE\\target")
                self.fail("Should stop after detecting one additional match")
            finally:
                closed.append(True)

        with patch.object(runner, "_event_xml", side_effect=records), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner._show_events(60, 1, 123, "VIEWER", "storage\\TARGET"), 0)
        self.assertEqual(closed, [True])
        self.assertEqual(output.getvalue().count("viewer.exe"), 2)
        self.assertIn("More matches exist", output.getvalue())
        self.assertIn("Displayed records: 1", output.getvalue())

    def test_empty_success_differs_from_failed_or_partial_query(self) -> None:
        for records, expected in (([], 0), (["<bad>", event_xml()], 1)):
            with patch.object(runner, "_event_xml", side_effect=lambda minutes: (xml for xml in records)):
                with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                    self.assertEqual(runner._show_events(60, 50, None, None, None), expected)
            if expected:
                self.assertIn("incomplete", output.getvalue())
                self.assertIn("Displayed records: 1", output.getvalue())
            else:
                self.assertIn("No matching events", output.getvalue())
        with patch.object(runner, "_event_xml", side_effect=OSError("Access denied")):
            with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
                self.assertEqual(runner._show_events(60, 50, None, None, None), 1)
        self.assertIn("Access denied", error.getvalue())
        self.assertNotIn("No matching events", output.getvalue())

    def test_help_invalid_args_and_other_platform_never_elevate(self) -> None:
        with patch.object(runner.System, "restart_elevated") as elevate:
            for arguments, status in ((["--help"], 0), (["--minutes", "0"], 2),
                                      (["--limit", "-1"], 2), (["--pid", "abc"], 2)):
                with patch.object(sys, "argv", ["usb-eject-log.py", *arguments]):
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as caught:
                            runner.main()
                    self.assertEqual(caught.exception.code, status)
            with patch.object(sys, "platform", "linux"), patch.object(sys, "argv", ["usb-eject-log.py"]):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 1)
            elevate.assert_not_called()

    def test_elevation_failure_prevents_query(self) -> None:
        with patch.object(sys, "platform", "win32"), patch.object(sys, "argv", ["usb-eject-log.py"]):
            with patch.object(runner.System, "restart_elevated"), patch.object(runner.System, "is_elevated", return_value=False):
                with patch.object(runner, "_show_events") as query, redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), 1)
                query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
