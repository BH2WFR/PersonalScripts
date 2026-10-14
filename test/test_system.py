"""Verify operating-system integration helpers without requesting elevation.

Run with conda run -n base python -m unittest discover -s test -p test_system.py.
"""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import System


def decode_windows_gsudo_restart_command(
    command: list[str],
) -> dict[str, object]:
    """Extract the restart data carried by the encoded PowerShell bootstrap."""
    bootstrap = base64.b64decode(command[-1]).decode("utf-16le")
    match = re.search(r"FromBase64String\('([^']+)'\)", bootstrap)
    if match is None:
        raise AssertionError("gsudo bootstrap does not contain a command payload")
    return json.loads(base64.b64decode(match.group(1)).decode("utf-8"))


class RestartCommandTests(unittest.TestCase):
    """Build correct source and bundled application restart commands."""

    def test_source_command_preserves_arguments_with_spaces(self) -> None:
        executable = os.path.abspath("C:/Program Files/Python/python.exe")
        script = os.path.abspath("C:/Scripts With Spaces/tool.py")
        with patch.object(sys, "executable", executable), \
                patch.object(sys, "argv", [script, "value with spaces"]), \
                patch.object(sys, "frozen", False, create=True):
            self.assertEqual(
                System._restart_command(),
                [executable, script, "value with spaces"],
            )

    def test_frozen_command_does_not_repeat_executable(self) -> None:
        executable = os.path.abspath("C:/Program Files/Tools/tool.exe")
        with patch.object(sys, "executable", executable), \
                patch.object(sys, "argv", [executable, "--mode", "test"]), \
                patch.object(sys, "frozen", True, create=True):
            self.assertEqual(
                System._restart_command(),
                [executable, "--mode", "test"],
            )

    def test_gsudo_uses_direct_mode_but_sudo_does_not(self) -> None:
        restart = [
            "C:/Program Files/Python/python.exe",
            "C:/Scripts With Spaces/tool.py",
            "argument with spaces",
        ]
        with patch.object(sys, "platform", "win32"):
            gsudo_command = System._elevation_command(
                "gsudo",
                "gsudo.exe",
                restart,
            )
            self.assertEqual(
                System._elevation_command("sudo", "sudo.exe", restart),
                ["sudo.exe", *restart],
            )
        self.assertEqual(
            gsudo_command[:-1],
            [
                "gsudo.exe",
                "--direct",
                r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-OutputFormat",
                "Text",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
            ],
        )
        self.assertEqual(
            decode_windows_gsudo_restart_command(gsudo_command),
            {
                "program": restart[0],
                "argument_line": subprocess.list2cmdline(restart[1:]),
            },
        )


class TryRestartElevatedTests(unittest.TestCase):
    """Do not execute an elevated child more than once."""

    @patch.object(System, "is_elevated", return_value=False)
    def test_nonzero_gsudo_status_does_not_try_sudo(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py"]
        completed = subprocess.CompletedProcess([], 1)
        with patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch(
                    "utils.system.shutil.which",
                    side_effect=["gsudo.exe", "sudo.exe"],
                ) as which, \
                patch("utils.system.subprocess.run", return_value=completed) as run:
            self.assertFalse(System.try_restart_elevated())

        which.assert_called_once_with("gsudo")
        invoked_command = run.call_args.args[0]
        self.assertEqual(
            decode_windows_gsudo_restart_command(invoked_command),
            {
                "program": restart[0],
                "argument_line": subprocess.list2cmdline(restart[1:]),
            },
        )
        self.assertEqual(run.call_args.kwargs, {"check": False})

    @patch.object(System, "is_elevated", return_value=False)
    def test_launch_error_falls_through_to_sudo(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py"]
        completed = subprocess.CompletedProcess([], 0)
        with patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch(
                    "utils.system.shutil.which",
                    side_effect=["gsudo.exe", "sudo.exe"],
                ) as which, \
                patch(
                    "utils.system.subprocess.run",
                    side_effect=[OSError("failed"), completed],
                ) as run, \
                self.assertRaisesRegex(SystemExit, "0"):
            System.try_restart_elevated()

        self.assertEqual(which.call_args_list, [call("gsudo"), call("sudo")])
        self.assertEqual(
            [item.args[0][0] for item in run.call_args_list],
            ["gsudo.exe", "sudo.exe"],
        )
        self.assertEqual(
            decode_windows_gsudo_restart_command(run.call_args_list[0].args[0]),
            {
                "program": restart[0],
                "argument_line": subprocess.list2cmdline(restart[1:]),
            },
        )
        self.assertEqual(
            run.call_args_list[1],
            call(["sudo.exe", *restart], check=False),
        )

    @patch.object(System, "is_elevated", return_value=False)
    def test_missing_gsudo_uses_sudo(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py"]
        completed = subprocess.CompletedProcess([], 0)
        with patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch("utils.system.shutil.which", side_effect=[None, "sudo.exe"]), \
                patch("utils.system.subprocess.run", return_value=completed) as run, \
                self.assertRaisesRegex(SystemExit, "0"):
            System.try_restart_elevated()

        run.assert_called_once_with(["sudo.exe", *restart], check=False)


class RestartElevatedTests(unittest.TestCase):
    """Use the first runnable force-elevation helper exactly once."""

    @patch.object(System, "is_elevated", return_value=False)
    def test_gsudo_direct_exits_with_child_status(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py", "argument with spaces"]
        completed = subprocess.CompletedProcess([], 7)
        with patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch("utils.system.shutil.which", return_value="gsudo.exe"), \
                patch("utils.system.subprocess.run", return_value=completed) as run, \
                self.assertRaisesRegex(SystemExit, "7"):
            System.restart_elevated()

        invoked_command = run.call_args.args[0]
        self.assertEqual(
            decode_windows_gsudo_restart_command(invoked_command),
            {
                "program": restart[0],
                "argument_line": subprocess.list2cmdline(restart[1:]),
            },
        )
        self.assertEqual(run.call_args.kwargs, {"check": False})


if __name__ == "__main__":
    unittest.main()
