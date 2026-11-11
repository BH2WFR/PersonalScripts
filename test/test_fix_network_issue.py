#!/usr/bin/env python3
"""Test the Windows network menu without changing network configuration.

Requirements: standard library and the repository's utils package.
Usage: conda run -n base python -m unittest discover -s test -p test_fix_network_issue.py
"""

import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools/windows/network-repair.py"
SPEC = importlib.util.spec_from_file_location("fix_network_issue", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REPAIR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REPAIR
SPEC.loader.exec_module(REPAIR)


class NetworkRepairTests(unittest.TestCase):
    """Exercise menu routing, command plans and elevation boundaries."""

    def setUp(self) -> None:
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.output))
        self.stack.enter_context(patch.object(sys, "platform", "win32"))
        self.elevate = self.stack.enter_context(patch.object(REPAIR.System, "restart_elevated"))
        self.is_admin = self.stack.enter_context(patch.object(REPAIR.System, "is_elevated", return_value=True))
        self.interactive = self.stack.enter_context(
            patch.object(REPAIR.Console, "has_interactive_input", return_value=True)
        )
        self.menu = self.stack.enter_context(patch.object(REPAIR.Menu, "select", return_value=False))
        self.stack.enter_context(patch("shutil.which", side_effect=lambda name: f"C:/Windows/System32/{name}.exe"))
        self.run = self.stack.enter_context(patch.object(REPAIR.subprocess, "run"))
        self.run.return_value = subprocess.CompletedProcess([], 0)

    def invoke(self, *arguments: str) -> int:
        """Run main with isolated arguments and all system commands mocked."""
        with patch.object(sys, "argv", [str(SCRIPT), *arguments]):
            return REPAIR.main()

    def test_help_and_every_preview_avoid_commands_and_elevation(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            self.invoke("--help")
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(self.invoke("--dry-run"), 0)
        for action in REPAIR.Action:
            self.assertEqual(self.invoke("--action", action.value, "--dry-run"), 0)
        self.elevate.assert_not_called()
        self.run.assert_not_called()
        self.menu.assert_not_called()

    def test_menu_exit_and_proxy_back(self) -> None:
        self.menu.side_effect = ["proxy", False, False]
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.menu.call_count, 3)
        self.run.assert_not_called()
        self.elevate.assert_not_called()

    def test_proxy_menu_inspects_then_returns_to_main_menu(self) -> None:
        self.menu.side_effect = ["proxy", REPAIR.Action.PROXY_CHECK, False]
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.run.call_args.args[0][1:], ["winhttp", "show", "proxy"])
        self.elevate.assert_not_called()

    def test_read_only_actions_work_without_admin_or_confirmation(self) -> None:
        self.is_admin.return_value = False
        self.interactive.return_value = False
        for action in ("diagnose", "proxy-check"):
            self.assertEqual(self.invoke("--action", action), 0)
        self.elevate.assert_not_called()
        self.menu.assert_not_called()

    def test_dhcp_renewal_preserves_adapter_as_one_argument(self) -> None:
        self.assertEqual(self.invoke("--action", "renew", "--adapter", "Ethernet 2", "--yes"), 0)
        self.assertEqual(self.run.call_args.args[0][1:], ["/renew", "Ethernet 2"])
        self.assertEqual(self.run.call_count, 1)
        self.run.reset_mock()
        self.assertEqual(self.invoke("--action", "renew", "--yes"), 0)
        self.assertEqual(self.run.call_args.args[0][1:], ["/renew"])

    def test_proxy_reset_shows_before_and_after(self) -> None:
        self.assertEqual(self.invoke("--action", "proxy-reset", "--yes"), 0)
        self.assertEqual([call.args[0][1:] for call in self.run.call_args_list], [
            ["winhttp", "show", "proxy"], ["winhttp", "reset", "proxy"],
            ["winhttp", "show", "proxy"],
        ])

    def test_original_reset_runs_exact_commands(self) -> None:
        self.assertEqual(self.invoke("--action", "reset", "--yes"), 0)
        self.assertEqual([call.args[0] for call in self.run.call_args_list], [
            [f"C:/Windows/System32/{command[0]}.exe", *command[1:]]
            for command in REPAIR.REPAIR_COMMANDS
        ])
        self.assertIn("restart Windows manually", self.output.getvalue())

    def test_diagnostics_use_custom_targets_and_bounded_steps(self) -> None:
        self.assertEqual(self.invoke("--action", "diagnose", "--test-ip", "192.0.2.1", "--host", "example.com"), 0)
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual(len(commands), 5)
        self.assertEqual(commands[0][1:], ["/all"])
        self.assertEqual(commands[1][1:], ["print"])
        self.assertIn("Get-NetIPConfiguration", commands[2][-1])
        self.assertEqual(commands[3][-1], "192.0.2.1")
        self.assertEqual(commands[4][-1], "example.com")
        for call in self.run.call_args_list:
            self.assertEqual(call.kwargs, {"check": False, "timeout": 30})

    def test_cancel_eof_and_noninteractive_repair_do_not_elevate(self) -> None:
        self.is_admin.return_value = False
        self.assertEqual(self.invoke("--action", "reset"), 0)
        self.menu.side_effect = EOFError
        self.assertEqual(self.invoke("--action", "reset"), 2)
        self.interactive.return_value = False
        self.assertEqual(self.invoke("--action", "renew"), 2)
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(self.invoke("--action", "reset", "--yes", "--menu"), 2)
        self.elevate.assert_not_called()
        self.run.assert_not_called()

    def test_invalid_arguments_cannot_run_commands(self) -> None:
        for arguments in [("--yes",), ("--action", "unknown"),
                          ("--host=-debug",), ("--host", "x;exit"),
                          ("--test-ip", "example.com"), ("--adapter=/release",)]:
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as raised:
                self.invoke(*arguments)
            self.assertEqual(raised.exception.code, 2)
        self.elevate.assert_not_called()
        self.run.assert_not_called()

    def test_elevation_preserves_selected_action_and_returns_to_menu(self) -> None:
        self.is_admin.return_value = False
        self.menu.side_effect = [REPAIR.Action.RENEW, True]
        relaunched: list[str] = []

        def relaunch() -> None:
            relaunched.extend(sys.argv)
            raise SystemExit(0)

        self.elevate.side_effect = relaunch
        original_argv = [str(SCRIPT), "--adapter", "Ethernet 2"]
        with patch.object(sys, "argv", original_argv), self.assertRaises(SystemExit):
            try:
                REPAIR.main()
            finally:
                self.assertIs(sys.argv, original_argv)
        self.assertEqual(relaunched[1:4], ["--action", "renew", "--yes"])
        self.assertIn("--menu", relaunched)
        self.assertEqual(relaunched[relaunched.index("--adapter") + 1], "Ethernet 2")
        self.run.assert_not_called()

    def test_yes_does_not_apply_to_later_menu_choices(self) -> None:
        self.menu.side_effect = [REPAIR.Action.RESET, False, False]
        self.assertEqual(self.invoke("--action", "renew", "--yes", "--menu"), 0)
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.menu.call_count, 3)

    def test_failures_continue_and_menu_preserves_failure_status(self) -> None:
        for failure in [subprocess.CompletedProcess([], 5),
                        subprocess.TimeoutExpired("netsh", 120), OSError("launch failed")]:
            self.run.reset_mock()
            self.run.side_effect = [failure, subprocess.CompletedProcess([], 0),
                                    subprocess.CompletedProcess([], 0)]
            self.menu.return_value = False
            self.assertEqual(self.invoke("--action", "reset", "--yes", "--menu"), 1)
            self.assertEqual(self.run.call_count, 3)

    def test_missing_prerequisite_and_platform_rejection(self) -> None:
        with patch.object(REPAIR.Environment, "check_commands", return_value=False):
            self.assertEqual(self.invoke("--action", "diagnose"), 1)
        with patch.object(sys, "platform", "linux"), self.assertRaises(SystemExit):
            self.invoke("--action", "reset", "--yes")
        self.elevate.assert_not_called()
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
