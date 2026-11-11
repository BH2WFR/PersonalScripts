#!/usr/bin/env python3
"""Implementation notes.

Keep diagnosis/proxy inspection read-only. Repairs use shared elevation and
explicit confirmation. Continue reporting subsequent steps after a failed
command; command success alone does not establish network connectivity.
"""

import argparse
from dataclasses import dataclass
from enum import StrEnum
import ipaddress
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402,F403

HELP = f"""{FLYellow}WINDOWS NETWORK REPAIR{CRst}

Diagnose connectivity, renew DHCP leases, inspect/reset WinHTTP proxy settings,
or reset the network stack. Resets may affect static IP/DNS settings and require
a restart; WinHTTP actions do not change browser or VPN proxy settings.

{FLYellow}Requirements:{CRst}
  Windows 10+ built-in network tools; PowerShell 7 for diagnosis.
  Administrator privileges for repairs.

{FLYellow}Usage:{CRst}
  python fix-network-issue.py [--action ACTION] [--dry-run]
  python fix-network-issue.py --action renew --adapter Wi-Fi
  ACTION: diagnose, renew, proxy-check, proxy-reset or reset.
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)


COMMAND_TIMEOUT_SECONDS = 120
DIAGNOSTIC_TIMEOUT_SECONDS = 30
DEFAULT_TEST_IP = "1.1.1.1"
DEFAULT_TEST_HOST = "www.microsoft.com"
REPAIR_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("netsh", "winsock", "reset"),
    ("netsh", "int", "ip", "reset"),
    ("ipconfig", "/flushdns"),
)
GATEWAY_PROBE = r"""
$ErrorActionPreference = 'Stop'
try {
    $gateways = @(Get-NetIPConfiguration | ForEach-Object {
        $_.IPv4DefaultGateway.NextHop
    } | Where-Object { $_ } | Sort-Object -Unique)
    if ($gateways.Count -eq 0) {
        Write-Output 'No IPv4 default gateway found.'
        exit 1
    }
    $failed = $false
    foreach ($gateway in $gateways) {
        Write-Output "IPv4 gateway: $gateway"
        & ping.exe -n 2 -w 1000 $gateway
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if ($failed) { exit 1 }
    exit 0
} catch {
    Write-Output $_.Exception.Message
    exit 1
}
""".strip()


class Action(StrEnum):
    """Operations available through the menu and --action."""

    RENEW = "renew"
    DIAGNOSE = "diagnose"
    PROXY_CHECK = "proxy-check"
    PROXY_RESET = "proxy-reset"
    RESET = "reset"


ACTION_LABELS: dict[Action, str] = {
    Action.RENEW: "Renew DHCP IPv4 lease",
    Action.DIAGNOSE: "Network diagnostics (read-only)",
    Action.PROXY_CHECK: "Inspect WinHTTP proxy (read-only)",
    Action.PROXY_RESET: "Reset WinHTTP proxy to direct access",
    Action.RESET: "Reset Winsock / TCP-IP / DNS cache",
}
ACTION_WARNINGS: dict[Action, str] = {
    Action.RENEW: "Renew DHCP IPv4 leases; connectivity may change. No lease is released first.",
    Action.PROXY_RESET: "Remove the WinHTTP proxy configuration and use direct access. "
                        "Applications that require this proxy may lose access.",
    Action.RESET: "Connectivity may be interrupted and static IP/DNS settings may be affected. "
                  "Record custom settings first. Restart Windows manually afterward.",
}


@dataclass(frozen=True)
class Options:
    """Validated CLI selections and diagnostic targets."""

    action: Action | None
    dry_run: bool
    yes: bool
    menu: bool
    adapter: str | None
    test_ip: str
    host: str


@dataclass(frozen=True)
class Step:
    """A labeled native command and its maximum running time in seconds."""

    label: str
    command: tuple[str, ...]
    timeout: int = COMMAND_TIMEOUT_SECONDS


def _parse_args() -> Options:
    """Parse and validate CLI options before any commands or elevation."""
    parser = Console.argument_parser(HELP)
    parser.add_argument("--action", type=Action, choices=list(Action), help="run this action directly")
    parser.add_argument("--dry-run", action="store_true", help="preview without commands/elevation; defaults to reset")
    parser.add_argument("-y", "--yes", action="store_true", help="confirm the explicit --action without prompting")
    parser.add_argument("--menu", action="store_true", help="open the menu after the explicit action")
    parser.add_argument("--adapter", help="DHCP adapter name or wildcard; default: all DHCP adapters")
    parser.add_argument("--test-ip", default=DEFAULT_TEST_IP, help=f"diagnostic ping IP (default: {DEFAULT_TEST_IP})")
    parser.add_argument("--host", default=DEFAULT_TEST_HOST, help=f"DNS test hostname (default: {DEFAULT_TEST_HOST})")
    args = parser.parse_args()
    if args.yes and args.action is None:
        parser.error("--yes requires an explicit --action")
    if args.adapter is not None and (not args.adapter.strip() or args.adapter.startswith(("-", "/"))):
        parser.error("--adapter must be a nonempty adapter name or wildcard")
    try:
        test_ip = str(ipaddress.ip_address(args.test_ip))
    except ValueError:
        parser.error("--test-ip must be an IPv4 or IPv6 address")
    hostname = str(args.host).rstrip(".")
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in hostname.split(".")
    ):
        parser.error("--host must be a DNS hostname (not a URL or command option)")
    return Options(args.action, args.dry_run, args.yes, args.menu, args.adapter, test_ip, hostname)


def _build_steps(action: Action, options: Options) -> tuple[Step, ...]:
    """Build the selected action's command plan without executing anything."""
    match action:
        case Action.RENEW:
            suffix = (options.adapter,) if options.adapter else ()
            return (Step(ACTION_LABELS[action], ("ipconfig", "/renew", *suffix)),)
        case Action.PROXY_CHECK:
            return (Step(ACTION_LABELS[action], ("netsh", "winhttp", "show", "proxy")),)
        case Action.PROXY_RESET:
            return (
                Step("Current WinHTTP proxy", ("netsh", "winhttp", "show", "proxy")),
                Step(ACTION_LABELS[action], ("netsh", "winhttp", "reset", "proxy")),
                Step("WinHTTP proxy after reset", ("netsh", "winhttp", "show", "proxy")),
            )
        case Action.RESET:
            return tuple(Step(subprocess.list2cmdline(command), command) for command in REPAIR_COMMANDS)
        case Action.DIAGNOSE:
            return tuple(Step(label, command, DIAGNOSTIC_TIMEOUT_SECONDS) for label, command in (
                ("IP / DHCP / DNS configuration", ("ipconfig", "/all")),
                ("Routing table", ("route", "print")),
                ("IPv4 default gateway reachability", ("pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", GATEWAY_PROBE)),
                (f"IP reachability: {options.test_ip}", ("ping", "-n", "2", "-w", "1000", options.test_ip)),
                (f"DNS lookup: {options.host}", ("nslookup", options.host)),
            ))


def _select_action() -> Action | None:
    """Display the main menu and proxy submenu; return None when exiting."""
    while True:
        choice = Menu.select(
            [MenuOption(["1"], ACTION_LABELS[Action.RENEW], Action.RENEW),
             MenuOption(["2"], ACTION_LABELS[Action.DIAGNOSE], Action.DIAGNOSE),
             MenuOption(["3"], "WinHTTP proxy inspection / reset", "proxy"),
             MenuOption(["4"], ACTION_LABELS[Action.RESET], Action.RESET),
             MenuOption(["0", "Q"], "Exit", False)],
            prompt="Action", default_key="0",
        )
        if choice == "proxy":
            choice = Menu.select(
                [MenuOption(["1"], ACTION_LABELS[Action.PROXY_CHECK], Action.PROXY_CHECK),
                 MenuOption(["2"], ACTION_LABELS[Action.PROXY_RESET], Action.PROXY_RESET),
                 MenuOption(["0", "B"], "Back", False)],
                prompt="WinHTTP proxy", default_key="0",
            )
            if not isinstance(choice, Action):
                continue
        return choice if isinstance(choice, Action) else None


def _execute_action(action: Action, options: Options, *, return_to_menu: bool, assume_yes: bool) -> int:
    """Preview, confirm and execute one action, relaunching as admin if needed.

    Returns a process-style status (0/1/2). May raise SystemExit when the
    shared elevation helper relaunches the script. Only repair actions mutate
    network settings. Command output is inherited by the terminal.
    """
    steps = _build_steps(action, options)
    print(f"\n{FLCyan}{ACTION_LABELS[action]}{CRst}")
    for step in steps:
        display = step.label if step.command[0] == "pwsh" else subprocess.list2cmdline(step.command)
        print(f"  {FGray}{display}{CRst}")
    if options.dry_run:
        print(f"{FLYellow}Preview only. No commands executed or settings changed.{CRst}")
        return 0

    # ── prerequisites and confirmation ──────────────────────
    names = dict.fromkeys(step.command[0] for step in steps)
    checks = {name: CmdCheck(name, required=True) for name in names}
    if not Environment.check_commands(*checks.values()):
        return 1
    if action in ACTION_WARNINGS:
        print(f"{FLYellow}{ACTION_WARNINGS[action]}{CRst}")
        if not assume_yes:
            if not Console.has_interactive_input():
                print(f"{FLRed}Use --yes to confirm this repair, or --dry-run to preview.{CRst}")
                return 2
            confirmed = Menu.select(
                [MenuOption(["Y"], "Continue", True), MenuOption(["N"], "Cancel", False)],
                prompt="Confirm", default_key="N", inline=True, separator=False,
            )
            if confirmed is not True:
                print(f"{FGray}Cancelled. No network settings changed.{CRst}")
                return 0
        if not System.is_elevated():
            # Preserve the selected action/options through the shared relaunch.
            original_argv = sys.argv
            sys.argv = [original_argv[0], "--action", action.value, "--yes",
                        "--test-ip", options.test_ip, "--host", options.host]
            if options.adapter:
                sys.argv.extend(["--adapter", options.adapter])
            if return_to_menu:
                sys.argv.append("--menu")
            try:
                System.restart_elevated()
            finally:
                sys.argv = original_argv

    # ── bounded execution and result summary ────────────────
    failures: list[str] = []
    for index, step in enumerate(steps, start=1):
        print(f"\n{FLCyan}[{index}/{len(steps)}] {step.label}{CRst}", flush=True)
        executable = checks[step.command[0]].path
        if executable is None:
            failures.append(step.label)
            print(f"{FLRed}Executable unavailable: {step.command[0]}{CRst}")
            continue
        try:
            result = subprocess.run([executable, *step.command[1:]], check=False, timeout=step.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(step.label)
            print(f"{FLRed}Command failed: {exc}{CRst}")
            continue
        if result.returncode:
            failures.append(step.label)
            print(f"{FLRed}Command exited with code {result.returncode}.{CRst}")
        else:
            print(f"{FLGreen}Command reported success.{CRst}")
    print(f"\nCommands reporting success: {len(steps) - len(failures)}/{len(steps)}")
    for label in failures:
        print(f"  {FLRed}Failed: {label}{CRst}")
    if action == Action.RESET:
        print(f"{FLYellow}Review output for partial reset errors, then restart Windows manually.{CRst}")
    elif action == Action.DIAGNOSE:
        print(f"{FGray}Check for missing addresses/gateways and DNS errors. ICMP may be blocked;\n"
              f"a failed ping alone does not prove the Internet is unavailable.{CRst}")
    return 1 if failures else 0


def main() -> int:
    """Run an explicit action or the interactive menu using sys.argv.

    Returns:
        0 on success/preview/cancellation, 1 if any action failed, or 2 for
        missing interactive input. argparse exits with 2 for invalid options.

    Raises:
        SystemExit: On invalid options, platform rejection, or admin relaunch.
        KeyboardInterrupt: On user interruption.
    """
    options = _parse_args()
    if sys.platform != "win32":
        Console.print_error_and_exit(f"This script only runs on Windows. Current platform: {sys.platform}")
    Console.print_banner("FIX NETWORK ISSUE")
    action = options.action
    if action is None and options.dry_run:
        action = Action.RESET
    open_menu = options.menu or action is None
    if open_menu and not Console.has_interactive_input():
        print(f"{FLRed}The menu needs a terminal. Use --action, or --dry-run to preview.{CRst}")
        return 2

    # --yes applies only to the explicitly selected action, never later choices.
    status = 0
    try:
        if action is not None:
            status = _execute_action(action, options, return_to_menu=open_menu, assume_yes=options.yes)
        while open_menu:
            selected = _select_action()
            if selected is None:
                break
            result = _execute_action(selected, options, return_to_menu=True, assume_yes=False)
            status = max(status, result)
    except EOFError:
        print(f"{FLYellow}Input closed. No further actions will run.{CRst}")
        return max(status, 2)
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
