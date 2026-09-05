#!/usr/bin/env python3
"""Interactively select, confirm, and forcibly restart a Windows service.

Provides a documented global service catalog with a Windows Audio preset and
two final custom lookup choices: exact service name and exact display name.
The selected service is resolved through Windows before confirmation. It can
then be forcibly restarted either while monitoring it until running or by
launching the restart operation without waiting for completion.

Requirements:
    - Windows 10 or later
    - Administrator privileges
    - system: Windows PowerShell (built into Windows)

Usage:
    python restart-windows-service.py
    python restart-windows-service.py --help
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402,F403


class LookupMode(StrEnum):
    """Supported exact-match methods for resolving a Windows service."""

    SERVICE_NAME = "service-name"
    DISPLAY_NAME = "display-name"


class RestartMode(StrEnum):
    """Available waiting behaviors for the confirmed restart operation."""

    WAIT_UNTIL_RUNNING = "wait-until-running"
    WITHOUT_WAITING = "without-waiting"


class ServiceOption(TypedDict):
    """Configuration for one entry in the interactive service catalog."""

    service_name: str | None
    display_name: str
    purpose: str
    when_to_use: str
    lookup_mode: LookupMode


# Keep the two custom lookup entries last so the menu remains predictable.
SERVICE_OPTIONS: dict[str, ServiceOption] = {
    "windows-audio": {
        "service_name": "Audiosrv",
        "display_name": "Windows Audio",
        "purpose": "Manages audio for Windows programs and sessions.",
        "when_to_use": (
            "Audio is unavailable, especially when sound redirection fails "
            "in a Remote Desktop session."
        ),
        "lookup_mode": LookupMode.SERVICE_NAME,
    },
    "custom-service-name": {
        "service_name": None,
        "display_name": "Custom service name",
        "purpose": "Find any installed service by its exact system service name.",
        "when_to_use": (
            "You know the short service name shown by tools such as sc.exe "
            "or Get-Service."
        ),
        "lookup_mode": LookupMode.SERVICE_NAME,
    },
    "custom-display-name": {
        "service_name": None,
        "display_name": "Custom display name",
        "purpose": "Find any installed service by its exact display name.",
        "when_to_use": (
            "You know the human-readable name shown in the Windows Services app."
        ),
        "lookup_mode": LookupMode.DISPLAY_NAME,
    },
}

SERVICE_START_TIMEOUT_SECONDS = 30
LOOKUP_PROCESS_TIMEOUT_SECONDS = 15
RESTART_PROCESS_TIMEOUT_SECONDS = SERVICE_START_TIMEOUT_SECONDS + 15
LOOKUP_MODE_ENV_NAME = "PERSONAL_SCRIPTS_SERVICE_LOOKUP_MODE"
LOOKUP_VALUE_ENV_NAME = "PERSONAL_SCRIPTS_SERVICE_LOOKUP_VALUE"
RESTART_SERVICE_ENV_NAME = "PERSONAL_SCRIPTS_SERVICE_NAME"
QUIT_MENU_VALUE = "quit"

LOOKUP_SERVICE_COMMAND = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$lookupMode = $env:{LOOKUP_MODE_ENV_NAME}
$lookupValue = $env:{LOOKUP_VALUE_ENV_NAME}
$matches = @(
    Get-Service -ErrorAction Stop | Where-Object {{
        ($lookupMode -eq '{LookupMode.SERVICE_NAME.value}' -and
            $_.Name -ieq $lookupValue) -or
        ($lookupMode -eq '{LookupMode.DISPLAY_NAME.value}' -and
            $_.DisplayName -ieq $lookupValue)
    }}
)
if ($matches.Count -eq 0) {{
    [Console]::Error.WriteLine(
        "No service found with exact $lookupMode '$lookupValue'."
    )
    exit 3
}}
if ($matches.Count -gt 1) {{
    $matchingNames = ($matches | ForEach-Object {{ $_.Name }}) -join ', '
    [Console]::Error.WriteLine(
        "Multiple services have $lookupMode '$lookupValue': $matchingNames"
    )
    exit 4
}}
$service = $matches[0]
[PSCustomObject]@{{
    service_name = $service.Name
    display_name = $service.DisplayName
    start_type = $service.StartType.ToString()
    is_enabled = $service.StartType -ne
        [System.ServiceProcess.ServiceStartMode]::Disabled
    is_running = $service.Status -eq
        [System.ServiceProcess.ServiceControllerStatus]::Running
}} | ConvertTo-Json -Compress
"""

RESTART_SERVICE_COMMAND = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$serviceName = $env:{RESTART_SERVICE_ENV_NAME}
$service = Get-Service -Name $serviceName -ErrorAction Stop
Restart-Service -InputObject $service -Force -ErrorAction Stop
$service.WaitForStatus(
    [System.ServiceProcess.ServiceControllerStatus]::Running,
    [TimeSpan]::FromSeconds({SERVICE_START_TIMEOUT_SECONDS})
)
$service.Refresh()
if ($service.Status -ne [System.ServiceProcess.ServiceControllerStatus]::Running) {{
    throw "Service '$serviceName' did not reach the Running state."
}}
"""


@dataclass(frozen=True)
class ServiceIdentity:
    """Canonical identity and current state returned by Windows."""

    service_name: str
    display_name: str
    start_type: str
    is_enabled: bool
    is_running: bool


def _print_help() -> None:
    """Print command usage, behavior, options, and requirements."""
    script_name = os.path.basename(sys.argv[0])
    print(
        f"""{FLYellow}RESTART WINDOWS SERVICE{CRst}

{FLYellow}Usage:{CRst}
  {FGray}python {script_name}{CRst}
  {FGray}python {script_name} --help{CRst}

{FLYellow}Description:{CRst}
  Select a documented preset service or find a custom service by its exact
  service name or display name. After Windows resolves the service, review its
  canonical names and current state, confirm the action, and forcibly restart
  it. The confirmation menu can wait for Running status or launch the restart
  without waiting for completion.

  In waiting mode, the script verifies that the selected service returns to
  the Running state before reporting success.

{FLYellow}Options:{CRst}
  {FGray}-h, --help{CRst}  Show this help message and exit.

{FLYellow}Requirements:{CRst}
  Windows 10 or later; administrator privileges; built-in Windows PowerShell.
"""
    )


def _powershell_command(
    powershell_executable: str,
    command: str,
    *,
    environment: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    """Run one non-interactive Windows PowerShell command with UTF-8 capture.

    Args:
        powershell_executable: Absolute path to Windows PowerShell.
        command: PowerShell source passed to ``-Command``.
        environment: Complete child-process environment.
        timeout_seconds: Maximum runtime in seconds before termination.

    Returns:
        Captured process result, including its exit code and text streams.

    Raises:
        OSError: If Windows cannot start PowerShell.
        subprocess.TimeoutExpired: If the command exceeds ``timeout_seconds``.
    """
    return subprocess.run(
        [
            powershell_executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=timeout_seconds,
    )


def _process_error_detail(result: subprocess.CompletedProcess[str]) -> str:
    """Return a compact diagnostic from a failed PowerShell process."""
    detail = " ".join((result.stderr or result.stdout or "").split())
    if detail:
        return detail
    return f"Windows PowerShell exited with code {result.returncode}."


def _select_service_option() -> tuple[str, ServiceOption] | None:
    """Show the configured service catalog and return the selected entry.

    Returns:
        The stable catalog key and its service configuration, or ``None`` when
        the user selects Quit.

    Raises:
        RuntimeError: If the shared menu returns an unexpected value.

    Side effects:
        Prints the purpose and recommended use of each entry, then reads one
        selection from standard input.
    """
    menu_options: list[MenuOption] = []
    for index, (option_key, option) in enumerate(SERVICE_OPTIONS.items(), start=1):
        if option_key in ("custom-service-name", "custom-display-name"):
            service_label = f"{FLCyan}{option['display_name']}{CRst}"
        else:
            service_label = f"{FLYellow}{option['display_name']}"
            if option["service_name"] is not None:
                service_label = f"{service_label} ({option['service_name']})"
            service_label = f"{service_label}{CRst}"
        description = (
            f"{service_label} {FGray}— {option['purpose']} "
            f"Use when: {option['when_to_use']}{CRst}"
        )
        menu_options.append(
            MenuOption(
                [str(index)],
                description,
                value=option_key,
                desc_color=CRst,
            )
        )
    menu_options.append(
        MenuOption(["Q"], "Quit", value=QUIT_MENU_VALUE, desc_color=CRst)
    )

    selected = Menu.select(
        menu_options,
        prompt="Select service",
        required=True,
        separator_width=72,
    )
    if selected == QUIT_MENU_VALUE:
        return None
    if not isinstance(selected, str) or selected not in SERVICE_OPTIONS:
        raise RuntimeError("The service menu returned an invalid selection.")
    return selected, SERVICE_OPTIONS[selected]


def _custom_lookup_value(option_key: str, option: ServiceOption) -> str:
    """Read the exact custom name requested by a custom catalog entry.

    Args:
        option_key: Stable key of the selected catalog entry.
        option: Configuration associated with ``option_key``.

    Returns:
        A non-empty service name or display name entered by the user.

    Raises:
        RuntimeError: If the user submits an empty name.

    Side effects:
        Reads one line from standard input for either custom lookup mode.
    """
    if option_key not in ("custom-service-name", "custom-display-name"):
        raise RuntimeError(f"Catalog entry '{option_key}' is not a custom lookup.")

    if option["lookup_mode"] is LookupMode.SERVICE_NAME:
        prompt = f"{FLYellow}Enter exact service name > {CRst}"
    elif option["lookup_mode"] is LookupMode.DISPLAY_NAME:
        prompt = f"{FLYellow}Enter exact display name > {CRst}"
    else:
        raise RuntimeError(f"Catalog entry '{option_key}' has an invalid lookup mode.")

    value = Input.prompt(prompt)
    if not value:
        raise RuntimeError("A service name is required.")
    return value


def _lookup_service(
    powershell_executable: str,
    lookup_mode: LookupMode,
    lookup_value: str,
) -> ServiceIdentity:
    """Resolve an exact service or display name through Windows.

    Args:
        powershell_executable: Absolute path to Windows PowerShell.
        lookup_mode: Whether ``lookup_value`` is a service or display name.
        lookup_value: Exact, case-insensitive value to find. Wildcards are
            treated as ordinary characters.

    Returns:
        Canonical service and display names reported by Windows.

    Raises:
        OSError: If Windows cannot start PowerShell.
        RuntimeError: If the lookup times out, finds zero or multiple services,
            or PowerShell returns malformed identity data.
    """
    environment = os.environ.copy()
    environment[LOOKUP_MODE_ENV_NAME] = lookup_mode.value
    environment[LOOKUP_VALUE_ENV_NAME] = lookup_value
    try:
        result = _powershell_command(
            powershell_executable,
            LOOKUP_SERVICE_COMMAND,
            environment=environment,
            timeout_seconds=LOOKUP_PROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Service lookup timed out after {LOOKUP_PROCESS_TIMEOUT_SECONDS} seconds."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(_process_error_detail(result))

    try:
        payload: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Windows PowerShell returned invalid service data.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Windows PowerShell returned invalid service data.")

    service_name = payload.get("service_name")
    display_name = payload.get("display_name")
    start_type = payload.get("start_type")
    is_enabled = payload.get("is_enabled")
    is_running = payload.get("is_running")
    if not isinstance(service_name, str) or not service_name:
        raise RuntimeError("Windows PowerShell returned an invalid service name.")
    if not isinstance(display_name, str) or not display_name:
        raise RuntimeError("Windows PowerShell returned an invalid display name.")
    if not isinstance(start_type, str) or not start_type:
        raise RuntimeError("Windows PowerShell returned an invalid service start type.")
    if not isinstance(is_enabled, bool) or not isinstance(is_running, bool):
        raise RuntimeError("Windows PowerShell returned invalid service state data.")
    return ServiceIdentity(
        service_name=service_name,
        display_name=display_name,
        start_type=start_type,
        is_enabled=is_enabled,
        is_running=is_running,
    )


def _resolve_service(
    powershell_executable: str,
    option_key: str,
    option: ServiceOption,
) -> ServiceIdentity:
    """Resolve a preset or custom catalog selection to canonical names."""
    lookup_value = option["service_name"]
    if option_key in ("custom-service-name", "custom-display-name"):
        lookup_value = _custom_lookup_value(option_key, option)
    if lookup_value is None:
        raise RuntimeError(f"Catalog entry '{option_key}' has no lookup value.")
    return _lookup_service(
        powershell_executable,
        option["lookup_mode"],
        lookup_value,
    )


def _confirm_restart(service: ServiceIdentity) -> RestartMode | None:
    """Print canonical service details and request a restart mode.

    Args:
        service: Canonical identity returned by Windows.

    Returns:
        Selected waiting behavior, or ``None`` when the user cancels.

    Side effects:
        Prints the service and display names, then reads one menu selection.
        Pressing Enter chooses the safe default and cancels.
    """
    print(f"\n{FLYellow}Selected Windows service{CRst}")
    print(f"  {FLCyan}Service name:{CRst} {service.service_name}")
    print(f"  {FLCyan}Display name:{CRst} {service.display_name}")
    enabled_text = f"{FLGreen}Yes{CRst}" if service.is_enabled else f"{FLYellow}No{CRst}"
    running_text = f"{FLGreen}Yes{CRst}" if service.is_running else f"{FLYellow}No{CRst}"
    print(
        f"  {FLCyan}Enabled:{CRst}      {enabled_text} "
        f"{FGray}(startup type: {service.start_type}){CRst}"
    )
    print(f"  {FLCyan}Running:{CRst}      {running_text}\n")
    selected = Menu.select(
        [
            MenuOption(
                ["W"],
                "Forcibly restart and wait until the service is running",
                value=RestartMode.WAIT_UNTIL_RUNNING,
            ),
            MenuOption(
                ["N"],
                "Forcibly restart this service (without waiting)",
                value=RestartMode.WITHOUT_WAITING,
            ),
            MenuOption(["Q"], "Cancel", value=None),
        ],
        prompt="Confirm restart",
        default_key="Q",
    )
    if isinstance(selected, RestartMode):
        return selected
    return None


def _restart_service(
    powershell_executable: str,
    service_name: str,
) -> subprocess.CompletedProcess[str]:
    """Forcibly restart one Windows service and wait until it is running.

    Args:
        powershell_executable: Absolute path to Windows PowerShell.
        service_name: Exact canonical service name returned by Windows.

    Returns:
        Completed PowerShell process. Zero means the service reached the
        ``Running`` state within the configured timeout.

    Raises:
        OSError: If Windows cannot start PowerShell.
        subprocess.TimeoutExpired: If the operation exceeds the process limit.

    Side effects:
        Stops and starts the selected system-wide Windows service.
    """
    environment = os.environ.copy()
    environment[RESTART_SERVICE_ENV_NAME] = service_name
    return _powershell_command(
        powershell_executable,
        RESTART_SERVICE_COMMAND,
        environment=environment,
        timeout_seconds=RESTART_PROCESS_TIMEOUT_SECONDS,
    )


def _restart_service_without_waiting(
    powershell_executable: str,
    service_name: str,
) -> int:
    """Launch a forceful service restart and return without waiting.

    Args:
        powershell_executable: Absolute path to Windows PowerShell.
        service_name: Exact canonical service name returned by Windows.

    Returns:
        Process identifier of the independently running PowerShell child.

    Raises:
        OSError: If Windows cannot start PowerShell.

    Side effects:
        Starts a hidden PowerShell process that restarts the selected service.
        The caller receives no eventual success or failure result.
    """
    environment = os.environ.copy()
    environment[RESTART_SERVICE_ENV_NAME] = service_name
    process = subprocess.Popen(
        [
            powershell_executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            RESTART_SERVICE_COMMAND,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return process.pid


def main(argv: list[str] | None = None) -> int:
    """Select, resolve, confirm, and forcibly restart a Windows service.

    Args:
        argv: Optional arguments excluding the script name. ``None`` reads
            arguments from ``sys.argv``.

    Returns:
        ``0`` after success, help, or user cancellation; ``1`` when lookup or
        restart fails; otherwise ``2`` for an unsupported argument.

    Side effects:
        May re-execute with administrator privileges, prompt on standard input,
        query installed services, and restart the selected service.
    """
    if sys.platform != "win32":
        Console.print_error_and_exit(
            f"This script only runs on Windows. Current platform: {sys.platform}"
        )

    arguments = sys.argv[1:] if argv is None else argv
    if any(argument in ("-h", "--help") for argument in arguments):
        _print_help()
        return 0
    if arguments:
        print(f"{FLRed}Unsupported argument:{CRst} {arguments[0]}")
        print(f"{FGray}Run with --help to see supported options.{CRst}")
        return 2

    # Elevate before operational output so the selection and confirmation
    # appear only in the administrator process after UAC.
    if not System.is_elevated():
        System.restart_elevated()

    Console.set_locale_utf8()
    Console.print_banner("RESTART WINDOWS SERVICE")

    powershell_check = CmdCheck(
        "powershell.exe",
        required=True,
        hints={
            "windows": (
                f"  {FGray}Windows PowerShell is built into supported Windows "
                f"versions.{CRst}"
            ),
        },
    )
    if not Environment.check_commands(powershell_check) or powershell_check.path is None:
        return 1

    try:
        selection = _select_service_option()
        if selection is None:
            Console.print_exit_message("Quit.")
            return 0
        option_key, option = selection
        service = _resolve_service(powershell_check.path, option_key, option)
    except (OSError, RuntimeError) as exc:
        print(f"{FLRed}Cannot resolve the selected service:{CRst} {exc}")
        return 1

    restart_mode = _confirm_restart(service)
    if restart_mode is None:
        Console.print_exit_message("Cancelled.")
        return 0

    print(f"\n{FLCyan}Restarting {service.display_name} ({service.service_name})...{CRst}")
    if restart_mode is RestartMode.WITHOUT_WAITING:
        try:
            process_id = _restart_service_without_waiting(
                powershell_check.path,
                service.service_name,
            )
        except OSError as exc:
            print(f"{FLRed}Cannot start Windows PowerShell:{CRst} {exc}")
            return 1
        print(
            f"{FLGreen}Restart command started without waiting.{CRst} "
            f"{FGray}PowerShell process ID: {process_id}.{CRst}"
        )
        return 0

    try:
        result = _restart_service(powershell_check.path, service.service_name)
    except OSError as exc:
        print(f"{FLRed}Cannot start Windows PowerShell:{CRst} {exc}")
        return 1
    except subprocess.TimeoutExpired:
        print(
            f"{FLRed}Restart timed out after "
            f"{RESTART_PROCESS_TIMEOUT_SECONDS} seconds.{CRst}"
        )
        return 1

    if result.returncode != 0:
        print(f"{FLRed}Failed to restart {service.display_name}:{CRst}")
        print(f"  {_process_error_detail(result)}")
        return 1

    print(
        f"{FLGreen}{service.display_name} ({service.service_name}) restarted "
        f"successfully and is running.{CRst}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
