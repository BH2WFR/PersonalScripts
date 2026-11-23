"""Verify operating-system integration helpers without requesting elevation.

Run with conda run -n base python -m unittest discover -s test -p test_system.py.
"""

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import System


def decode_windows_gsudo_restart_command(
    command: list[str],
) -> dict[str, object]:
    """Extract the data payload from the PowerShell command."""
    match = re.search(r"FromBase64String\('([^']+)'\)", command[-1])
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

    def test_explicit_entry_and_arguments_override_the_host_process(self) -> None:
        with patch.object(sys, "argv", ["host.py", "--other"]), patch.object(sys, "frozen", False, create=True):
            self.assertEqual(System._restart_command("entry.py", ["", "a b"]),
                             [os.path.abspath(sys.executable), os.path.abspath("entry.py"), "", "a b"])

    def test_frozen_command_does_not_repeat_executable(self) -> None:
        executable = os.path.abspath("C:/Program Files/Tools/tool.exe")
        with patch.object(sys, "executable", executable), \
                patch.object(sys, "argv", [executable, "--mode", "test"]), \
                patch.object(sys, "frozen", True, create=True):
            self.assertEqual(
                System._restart_command(),
                [executable, "--mode", "test"],
            )

    def test_posix_sudo_targets_root_and_preserves_linux_desktop_context(self) -> None:
        restart = ["/usr/bin/python", "/my tool.py", "a b"]
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "XDG_DATA_HOME": "/data"}, clear=True):
            for platform in ("linux", "darwin"):
                with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                    expected = ["sudo", "-u", "root"]
                    if platform == "linux":
                        expected.append("--preserve-env=WAYLAND_DISPLAY,XDG_DATA_HOME")
                    self.assertEqual(System._elevation_command("sudo", "sudo", restart), [*expected, *restart])

    def test_gsudo_waits_and_windows_sudo_requires_inline_mode(self) -> None:
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
            sudo_command = System._elevation_command("sudo", "sudo.exe", restart)
            self.assertEqual(sudo_command, ["sudo.exe", "--inline", *gsudo_command[3:]])
        self.assertEqual(
            gsudo_command[:-1],
            [
                "gsudo.exe", "--direct", "--wait",
                os.path.expandvars(r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
            ],
        )
        self.assertEqual(
            decode_windows_gsudo_restart_command(gsudo_command),
            {
                "program": restart[0],
                "argument_line": subprocess.list2cmdline(restart[1:]),
            },
        )

    @unittest.skipUnless(sys.platform == "win32", "Requires Windows gsudo")
    def test_gsudo_round_trips_child_argv_and_exit_status(self) -> None:
        """Run the actual wrapper at medium integrity and observe the child's argv."""
        gsudo = shutil.which("gsudo")
        if gsudo is None or not System._windows_helper_available("gsudo", gsudo):
            self.skipTest("A gsudo version supporting --direct is required")

        arguments = [
            "", "  leading and trailing  ", "中文 路径 🐍", 'a"b  c', '""',
            "C:\\目录 with spaces\\", 'backslashes\\\\"before quote',
            "C:/中文/with spaces/", r"\\server\share\中文/mixed", "/flag", "trailing/\\",
            "https://host/a/b?q=1", "--path=C:/a b/c", "tab\tand\nnewline", "%SystemRoot%", "$env:PATH", "&|<>^;()'",
            "quoted 中文 " * 100,
            "",
        ]
        scratch = ROOT / "tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=scratch, suffix=" 中文 argv probe.py", delete_on_close=False,
        ) as probe:
            probe.write("import json, sys\nprint(json.dumps(sys.argv))\nsys.exit(7)\n")
            probe.close()
            command = System._elevation_command("gsudo", gsudo, [sys.executable, probe.name, *arguments])
            result = subprocess.run(
                [gsudo, "--integrity", "Medium", *command[1:]],
                capture_output=True, timeout=30, check=False,
            )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(result.stdout), [probe.name, *arguments])


class TryRestartElevatedTests(unittest.TestCase):
    """Do not execute an elevated child more than once."""

    @patch.object(System, "is_elevated", return_value=False)
    def test_nonzero_gsudo_status_does_not_try_sudo(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py"]
        completed = subprocess.CompletedProcess([], 1)
        with patch.object(System, "_windows_helper_available", return_value=True), \
                patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch(
                    "utils.system.shutil.which",
                    side_effect=["gsudo.exe", "sudo.exe"],
                ) as which, \
                patch("utils.system.subprocess.run", return_value=completed) as run:
            with self.assertRaises(SystemExit) as raised:
                System.try_restart_elevated()
            self.assertEqual(raised.exception.code, 1)

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
        with patch.object(System, "_windows_helper_available", return_value=True), \
                patch.object(sys, "platform", "win32"), \
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
            call(["sudo.exe", "--inline", *System._windows_restart_powershell(restart)], check=False),
        )

    @patch.object(System, "is_elevated", return_value=False)
    def test_missing_gsudo_uses_sudo(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py"]
        completed = subprocess.CompletedProcess([], 0)
        with patch.object(System, "_windows_helper_available", return_value=True), \
                patch.object(sys, "platform", "win32"), \
                patch.object(System, "_restart_command", return_value=restart), \
                patch("utils.system.shutil.which", side_effect=[None, "sudo.exe"]), \
                patch("utils.system.subprocess.run", return_value=completed) as run, \
                self.assertRaisesRegex(SystemExit, "0"):
            System.try_restart_elevated()

        run.assert_called_once_with(["sudo.exe", "--inline", *System._windows_restart_powershell(restart)], check=False)


class RestartElevatedTests(unittest.TestCase):
    """Use the first runnable force-elevation helper exactly once."""

    @patch.object(System, "is_elevated", return_value=False)
    def test_gsudo_direct_exits_with_child_status(self, _is_elevated) -> None:
        restart = ["python.exe", "tool.py", "argument with spaces"]
        completed = subprocess.CompletedProcess([], 7)
        with patch.object(System, "_windows_helper_available", return_value=True), \
                patch.object(sys, "platform", "win32"), \
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

    def test_long_gsudo_command_falls_back_with_original_arguments(self) -> None:
        restart = [sys.executable, "中文 tool.py", "", 'a"b  c' * 2000]
        for sudo in ("sudo.exe", None):
            with self.subTest(sudo=sudo), patch.object(sys, "platform", "win32"), \
                    patch.object(System, "is_elevated", return_value=False), \
                    patch.object(System, "_restart_command", return_value=restart), \
                    patch.object(System, "_windows_helper_available", return_value=True), \
                    patch("utils.system.shutil.which", side_effect=["gsudo.exe", sudo]), \
                    patch("utils.system.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                    patch.object(System, "_windows_native_restart", return_value=37) as native, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                System.restart_elevated()
            if sudo:
                run.assert_called_once_with([sudo, "--inline", *System._windows_restart_powershell(restart)], check=False)
                native.assert_not_called()
                self.assertEqual(raised.exception.code, 0)
            else:
                run.assert_not_called()
                native.assert_called_once_with(restart)
                self.assertEqual(raised.exception.code, 37)

    def test_native_uac_denial_reports_error_and_install_hint(self) -> None:
        with patch.object(sys, "platform", "win32"), patch.object(System, "is_elevated", return_value=False), \
                patch("utils.system.shutil.which", return_value=None), \
                patch.object(System, "_windows_native_restart", side_effect=OSError("UAC cancelled")) as native, \
                contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as raised:
            System.restart_elevated()
        self.assertEqual(raised.exception.code, 1)
        native.assert_called_once()
        self.assertIn("UAC cancelled", error.getvalue())
        self.assertIn("scoop install gsudo", error.getvalue())

    def test_gsudo_requires_interactive_console_settings(self) -> None:
        for new_window, isolation, expected in (("False", "False", True), ("True", "False", False),
                                                ("False", "True", False)):
            config = f'NewWindow.Force = "{new_window}"\nSecurityEnforceUacIsolation = "{isolation}"'
            replies = [subprocess.CompletedProcess([], 0, b"--direct"), subprocess.CompletedProcess([], 0, config.encode())]
            with self.subTest(config=config), patch("utils.system.subprocess.run", side_effect=replies):
                self.assertEqual(System._windows_helper_available("gsudo", "gsudo.exe"), expected)

    @unittest.skipUnless(sys.platform == "win32", "Requires Windows sudo registry settings")
    def test_windows_sudo_requires_inline_mode_and_policy(self) -> None:
        import winreg

        sudo = os.path.expandvars(r"%SystemRoot%\System32\sudo.exe")
        for mode, policy, expected in ((1, 3, False), (2, 3, False), (3, 1, False), (3, 3, True), (3, None, True)):
            replies = [(mode, winreg.REG_DWORD), FileNotFoundError() if policy is None else (policy, winreg.REG_DWORD)]
            with self.subTest(mode=mode, policy=policy), patch("winreg.OpenKey"), \
                    patch("winreg.QueryValueEx", side_effect=replies):
                self.assertEqual(System._windows_helper_available("sudo", sudo), expected)

    @unittest.skipUnless(sys.platform == "win32", "Requires Windows native APIs")
    def test_native_warning_precedes_uac_request(self) -> None:
        from utils import _windows_elevation as native

        with patch.object(native.ctypes, "WinDLL") as library, \
                patch.object(native.ctypes.windll.user32, "MessageBoxW") as warning:
            def request_uac(_info: object) -> None:
                warning.assert_called_once()
                _, message, _, flags = warning.call_args.args
                self.assertIn("ShellExecuteExW", message)
                self.assertIn("scoop install gsudo", message)
                self.assertEqual(flags, 0x30)
                raise PermissionError("UAC cancelled")

            library.return_value.ShellExecuteExW.side_effect = request_uac
            with self.assertRaisesRegex(PermissionError, "UAC cancelled"):
                native.run_as_admin(["python.exe", "tool.py"], hidden=True)

    def test_native_console_launch_attaches_before_starting_target(self) -> None:
        restart = ["python.exe", "中文 script.py", "", r"\\server\share/path"]
        with patch("utils._windows_elevation.has_console", return_value=True), \
                patch("utils._windows_elevation.run_as_admin", return_value=37) as run:
            self.assertEqual(System._windows_native_restart(restart), 37)
        command = run.call_args.args[0]
        self.assertTrue(run.call_args.kwargs["hidden"])
        self.assertIn(f"AttachConsole({os.getpid()})", command[-1])
        self.assertEqual(decode_windows_gsudo_restart_command(command)["argument_line"], subprocess.list2cmdline(restart[1:]))

    @unittest.skipUnless(sys.platform == "win32", "Requires a Windows console")
    def test_detached_helper_rejoins_callers_console_and_round_trips_arguments(self) -> None:
        from utils._windows_elevation import has_console

        if not has_console():
            self.skipTest("The test runner has no console to attach to")
        arguments = ["", "C:\\中文 path\\", r"\\server\share/mixed", 'a\\\\"b  c', "/option/"]
        probe = (
            "import ctypes, sys\n"
            "pids = (ctypes.c_ulong * 1024)()\n"
            "count = ctypes.windll.kernel32.GetConsoleProcessList(pids, len(pids))\n"
            "assert int(sys.argv[1]) in pids[:count], 'different console'\n"
            f"assert sys.argv[2:] == {arguments!r}, repr(sys.argv[2:])\n"
            "sys.exit(37)\n"
        )
        pid = os.getpid()
        command = System._windows_restart_powershell(
            [sys.executable, "-I", "-c", probe, str(pid), *arguments], console_pid=pid,
        )
        result = subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30, check=False)
        self.assertEqual(result.returncode, 37)

    def test_native_consoleless_gui_and_cli(self) -> None:
        with patch("utils._windows_elevation.has_console", return_value=False), \
                patch("utils._windows_elevation.is_gui_executable", side_effect=[True, False]), \
                patch("utils._windows_elevation.run_as_admin", return_value=0) as run:
            self.assertEqual(System._windows_native_restart(["pythonw.exe", "gui.py"]), 0)
            with self.assertRaisesRegex(OSError, "No original Windows console"):
                System._windows_native_restart(["python.exe", "cli.py"])
        run.assert_called_once_with(["pythonw.exe", "gui.py"], hidden=False)

    def test_posix_sudo_launch_failure_exits_before_work(self) -> None:
        with patch.object(sys, "platform", "linux"), patch.object(System, "is_elevated", return_value=False), \
                patch("utils.system.shutil.which", return_value="/usr/bin/sudo"), \
                patch("utils.system.os.execv", side_effect=PermissionError("denied")), \
                contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as raised:
            System.restart_elevated()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("denied", error.getvalue())


if __name__ == "__main__":
    unittest.main()
