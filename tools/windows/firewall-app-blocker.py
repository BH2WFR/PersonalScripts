#!/usr/bin/env python3
"""Interactively block or unblock Windows executables with firewall rules.

The tool accepts one ``.exe``/``.com`` file or a directory to scan recursively.
Directory symlinks and junctions are never followed silently. Existing complete
block rules are skipped, and removal only targets enabled local persistent rules
that block every profile, protocol, port, and address for the selected program.

Requirements:
    - Windows 10 or later
    - administrator privileges
    - system: PowerShell with the built-in NetSecurity module

Usage:
    python firewall-app-blocker.py
    python firewall-app-blocker.py --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Optional, Sequence, cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402,F403


SUPPORTED_SUFFIXES = frozenset({".exe", ".com"})
RULE_GROUP = "PersonalScripts Firewall App Blocker"
RULE_NAME_PREFIX = "PersonalScripts-FAB"
POWERSHELL_TIMEOUT_SECONDS = 120
ERROR_DETAIL_LIMIT = 300


class _Action(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    OPEN_SETTINGS = "open-settings"
    EXIT = "exit"


class _BlockMode(StrEnum):
    OUTBOUND = "outbound"
    BOTH = "both"


class _Direction(StrEnum):
    OUTBOUND = "Outbound"
    INBOUND = "Inbound"


class _LinkDecision(StrEnum):
    ENTER = "enter"
    ENTER_ALL = "enter-all"
    IGNORE = "ignore"
    IGNORE_ALL = "ignore-all"


class _LinkPolicy(StrEnum):
    ASK = "ask"
    ENTER_ALL = "enter-all"
    IGNORE_ALL = "ignore-all"


@dataclass(frozen=True)
class _ExecutableCandidate:
    path: Path
    relative_name: str


@dataclass(frozen=True)
class _ScanResult:
    executables: tuple[_ExecutableCandidate, ...]
    included_directories: tuple[Path, ...]


@dataclass(frozen=True)
class _TargetSelection:
    input_path: Path
    is_directory: bool
    executables: tuple[_ExecutableCandidate, ...]
    included_directories: tuple[Path, ...]


@dataclass(frozen=True)
class _FirewallRule:
    name: str
    display_name: str
    group: str
    program: Path
    direction: str
    action: str
    enabled: str
    profile: str
    source_type: str
    protocol: str
    local_port: str
    remote_port: str
    local_address: str
    remote_address: str
    is_full_block: bool


@dataclass(frozen=True)
class _RuleRequest:
    name: str
    display_name: str
    description: str
    program: Path
    direction: _Direction


@dataclass(frozen=True)
class _MutationResult:
    name: str
    succeeded: bool
    detail: str


QUERY_RULES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
Import-Module NetSecurity -ErrorAction Stop

function Test-AnyValue {
    param([object] $Value)
    $items = @($Value)
    return $items.Count -eq 1 -and [string]$items[0] -eq 'Any'
}

function Test-AllProfiles {
    param([object] $Value)
    $text = [string]$Value
    if ($text -eq 'Any') {
        return $true
    }
    $parts = @($text -split ',\s*')
    return (
        $parts -contains 'Domain' -and
        $parts -contains 'Private' -and
        $parts -contains 'Public'
    )
}

function Test-BlankValue {
    param([object] $Value)
    return [string]::IsNullOrWhiteSpace([string]$Value)
}

$rulesById = @{}
Get-NetFirewallRule -PolicyStore PersistentStore | ForEach-Object {
    $rulesById[[string]$_.InstanceID] = $_
}
$portsById = @{}
Get-NetFirewallPortFilter -PolicyStore PersistentStore | ForEach-Object {
    $portsById[[string]$_.InstanceID] = $_
}
$addressesById = @{}
Get-NetFirewallAddressFilter -PolicyStore PersistentStore | ForEach-Object {
    $addressesById[[string]$_.InstanceID] = $_
}
$servicesById = @{}
Get-NetFirewallServiceFilter -PolicyStore PersistentStore | ForEach-Object {
    $servicesById[[string]$_.InstanceID] = $_
}
$interfacesById = @{}
Get-NetFirewallInterfaceFilter -PolicyStore PersistentStore | ForEach-Object {
    $interfacesById[[string]$_.InstanceID] = $_
}
$interfaceTypesById = @{}
Get-NetFirewallInterfaceTypeFilter -PolicyStore PersistentStore | ForEach-Object {
    $interfaceTypesById[[string]$_.InstanceID] = $_
}
$securityById = @{}
Get-NetFirewallSecurityFilter -PolicyStore PersistentStore | ForEach-Object {
    $securityById[[string]$_.InstanceID] = $_
}

$output = [System.Collections.Generic.List[object]]::new()
$applicationFilters = Get-NetFirewallApplicationFilter -PolicyStore PersistentStore
foreach ($application in $applicationFilters) {
    $program = [Environment]::ExpandEnvironmentVariables([string]$application.Program)
    if ([string]::IsNullOrWhiteSpace($program) -or $program -eq 'Any') {
        continue
    }

    $instanceId = [string]$application.InstanceID
    $rule = $rulesById[$instanceId]
    $port = $portsById[$instanceId]
    $address = $addressesById[$instanceId]
    $service = $servicesById[$instanceId]
    $interface = $interfacesById[$instanceId]
    $interfaceType = $interfaceTypesById[$instanceId]
    $security = $securityById[$instanceId]
    if (
        $null -eq $rule -or
        $null -eq $port -or
        $null -eq $address -or
        $null -eq $service -or
        $null -eq $interface -or
        $null -eq $interfaceType -or
        $null -eq $security
    ) {
        continue
    }

    $packageIsAny = Test-BlankValue $application.Package
    if (-not $packageIsAny) {
        $packageIsAny = Test-AnyValue $application.Package
    }
    $securityIsAny = (
        ([string]$security.Authentication -in @('NotRequired', 'NotConfigured')) -and
        ([string]$security.Encryption -in @('NotRequired', 'NotConfigured')) -and
        -not [bool]$security.OverrideBlockRules -and
        (Test-BlankValue $security.LocalUserAuthorizedList) -and
        (Test-BlankValue $security.RemoteUserAuthorizedList) -and
        (Test-BlankValue $security.RemoteMachineAuthorizedList)
    )
    $isFullBlock = (
        [string]$rule.Enabled -eq 'True' -and
        [string]$rule.Action -eq 'Block' -and
        (Test-AllProfiles $rule.Profile) -and
        (Test-AnyValue $port.Protocol) -and
        (Test-AnyValue $port.LocalPort) -and
        (Test-AnyValue $port.RemotePort) -and
        (Test-AnyValue $port.IcmpType) -and
        (Test-AnyValue $port.DynamicTarget) -and
        (Test-AnyValue $address.LocalAddress) -and
        (Test-AnyValue $address.RemoteAddress) -and
        (Test-AnyValue $service.Service) -and
        (Test-AnyValue $interface.InterfaceAlias) -and
        (Test-AnyValue $interfaceType.InterfaceType) -and
        $packageIsAny -and
        $securityIsAny -and
        (Test-BlankValue $rule.Owner)
    )

    $output.Add([pscustomobject]@{
        Name = [string]$rule.Name
        DisplayName = [string]$rule.DisplayName
        Group = [string]$rule.Group
        Program = $program
        Direction = [string]$rule.Direction
        Action = [string]$rule.Action
        Enabled = [string]$rule.Enabled
        Profile = [string]$rule.Profile
        SourceType = [string]$rule.PolicyStoreSourceType
        Protocol = [string]$port.Protocol
        LocalPort = [string]$port.LocalPort
        RemotePort = [string]$port.RemotePort
        LocalAddress = [string]$address.LocalAddress
        RemoteAddress = [string]$address.RemoteAddress
        IsFullBlock = [bool]$isFullBlock
    })
}

ConvertTo-Json -InputObject $output.ToArray() -Depth 4 -Compress
"""


CREATE_RULES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
Import-Module NetSecurity -ErrorAction Stop
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$results = [System.Collections.Generic.List[object]]::new()

foreach ($item in @($payload)) {
    try {
        New-NetFirewallRule `
            -PolicyStore PersistentStore `
            -Name ([string]$item.Name) `
            -DisplayName ([string]$item.DisplayName) `
            -Group ([string]$item.Group) `
            -Description ([string]$item.Description) `
            -Program ([string]$item.Program) `
            -Direction ([string]$item.Direction) `
            -Action Block `
            -Profile Any `
            -Enabled True `
            -ErrorAction Stop | Out-Null
        $results.Add([pscustomobject]@{
            Name = [string]$item.Name
            Succeeded = $true
            Detail = ''
        })
    }
    catch {
        $results.Add([pscustomobject]@{
            Name = [string]$item.Name
            Succeeded = $false
            Detail = [string]$_.Exception.Message
        })
    }
}

ConvertTo-Json -InputObject $results.ToArray() -Depth 3 -Compress
"""


REMOVE_RULES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
Import-Module NetSecurity -ErrorAction Stop
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$results = [System.Collections.Generic.List[object]]::new()
$rulesByName = @{}
Get-NetFirewallRule -PolicyStore PersistentStore | ForEach-Object {
    $rulesByName[[string]$_.Name] = $_
}

foreach ($item in @($payload)) {
    try {
        $name = [string]$item.Name
        $exactRule = $rulesByName[$name]
        if ($null -eq $exactRule) {
            throw "The exact rule no longer exists: $name"
        }
        $application = $exactRule | Get-NetFirewallApplicationFilter
        $currentProgram = [Environment]::ExpandEnvironmentVariables(
            [string]$application.Program
        )
        if (
            [string]$exactRule.Action -ne 'Block' -or
            [string]$exactRule.Enabled -ne 'True' -or
            [string]$exactRule.Direction -ne [string]$item.Direction -or
            $currentProgram -ine [string]$item.Program
        ) {
            throw "The rule changed after preview and will not be removed: $name"
        }
        $exactRule | Remove-NetFirewallRule -ErrorAction Stop
        $results.Add([pscustomobject]@{
            Name = $name
            Succeeded = $true
            Detail = ''
        })
    }
    catch {
        $results.Add([pscustomobject]@{
            Name = [string]$item.Name
            Succeeded = $false
            Detail = [string]$_.Exception.Message
        })
    }
}

ConvertTo-Json -InputObject $results.ToArray() -Depth 3 -Compress
"""


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for this interactive tool."""
    return argparse.ArgumentParser(
        description=(
            f"{FLYellow}WINDOWS FIREWALL APP BLOCKER{CRst}\n\n"
            "Interactively add complete outbound or inbound/outbound block "
            "rules for one executable or every .exe/.com file under a directory."
        ),
        epilog=(
            f"{FLYellow}Usage:{CRst}\n"
            f"  {FGray}python firewall-app-blocker.py{CRst}\n"
            f"  {FGray}python firewall-app-blocker.py --help{CRst}\n\n"
            f"{FLYellow}Requirements:{CRst}\n"
            "  Windows 10 or later; administrator privileges; PowerShell "
            "with the built-in NetSecurity module."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )


def _parse_args(argv: Optional[Sequence[str]]) -> None:
    """Validate command-line arguments; the tool otherwise runs interactively."""
    _build_argument_parser().parse_args(argv)


def _compact_error(text: str) -> str:
    """Return a single-line, length-bounded diagnostic."""
    detail = " ".join(text.split()) or "PowerShell returned no error detail."
    if len(detail) > ERROR_DETAIL_LIMIT:
        return f"{detail[:ERROR_DETAIL_LIMIT - 3]}..."
    return detail


def _run_powershell_json(
    powershell: str,
    script: str,
    payload: Optional[object] = None,
) -> object:
    """Run a fixed PowerShell script and decode its JSON result."""
    input_text = "" if payload is None else json.dumps(payload, ensure_ascii=False)
    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=POWERSHELL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(_compact_error(result.stderr or result.stdout))
    output = result.stdout.strip().lstrip("\ufeff")
    if not output:
        return []
    try:
        parsed: object = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"PowerShell returned invalid JSON: {_compact_error(output)}"
        ) from exc
    return parsed


def _json_array(value: object) -> list[dict[str, object]]:
    """Validate that a decoded JSON value is an array of objects."""
    if not isinstance(value, list):
        raise RuntimeError("PowerShell returned a JSON value that is not an array.")
    objects: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError("PowerShell returned a non-object array item.")
        objects.append(cast(dict[str, object], item))
    return objects


def _json_text(item: dict[str, object], key: str) -> str:
    """Read one JSON object property as text."""
    value = item.get(key, "")
    return "" if value is None else str(value)


def _normalize_windows_path(path: os.PathLike[str] | str) -> str:
    """Return a case-insensitive absolute Windows path comparison key."""
    expanded = os.path.expandvars(os.fspath(path))
    absolute = os.path.abspath(expanded)
    if absolute.startswith("\\\\?\\"):
        absolute = absolute[4:]
    return os.path.normcase(os.path.normpath(absolute))


def _is_supported_executable(path: Path) -> bool:
    """Return whether the path has a supported executable suffix."""
    return path.suffix.casefold() in SUPPORTED_SUFFIXES


def _direction_color(direction: _Direction | str) -> str:
    """Return the semantic console color for one firewall direction."""
    value = direction.value if isinstance(direction, _Direction) else direction
    if value.casefold() == _Direction.INBOUND.value.casefold():
        return FLCyan
    return FLYellow


def _format_direction(
    direction: _Direction | str,
    *,
    bracketed: bool = False,
) -> str:
    """Return one colorized inbound/outbound direction label."""
    value = direction.value if isinstance(direction, _Direction) else direction
    label = f"[{value}]" if bracketed else value
    return f"{_direction_color(value)}{label}{CRst}"


def _colorize_direction_words(text: str) -> str:
    """Color every canonical inbound/outbound word in display text."""
    return (
        text.replace(
            _Direction.INBOUND.value,
            _format_direction(_Direction.INBOUND),
        ).replace(
            _Direction.OUTBOUND.value,
            _format_direction(_Direction.OUTBOUND),
        )
    )


def _directory_link_kind(path: Path) -> Optional[str]:
    """Return the Windows directory-link kind without following its target."""
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return "junction"
    if not path.is_symlink():
        return None
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return "directory symlink" if path.is_dir() else None
    if attributes & stat.FILE_ATTRIBUTE_DIRECTORY:
        return "directory symlink"
    return None


def _resolved_link_target(path: Path) -> Path:
    """Return the normalized absolute target of a symlink or junction."""
    return Path(os.path.abspath(os.path.realpath(path)))


class _ExecutableScanner:
    """Recursively collect executables while controlling directory links."""

    def __init__(self) -> None:
        self._link_policy = _LinkPolicy.ASK
        self._visited_directories: set[tuple[int, int]] = set()
        self._visited_paths: set[str] = set()
        self._executables: dict[str, _ExecutableCandidate] = {}
        self._included_directories: dict[str, Path] = {}

    def scan(self, root: Path) -> _ScanResult:
        """Scan one directory and return unique executable candidates.

        Args:
            root: Existing directory, directory symlink, or junction to scan.

        Returns:
            Unique ``.exe``/``.com`` files and every real directory included in
            the scan. Directory links are followed only after user approval.

        Side effects:
            Prompts for directory-link traversal decisions and prints skipped
            links, duplicate directories, and inaccessible paths.
        """
        root_kind = _directory_link_kind(root)
        if root_kind is not None:
            target = _resolved_link_target(root)
            if not self._should_enter_link(root, target, root_kind):
                return _ScanResult((), ())
            self._walk(target, Path(root.name or target.name))
        else:
            self._walk(root, Path())

        executables = tuple(
            sorted(
                self._executables.values(),
                key=lambda item: item.relative_name.casefold(),
            )
        )
        directories = tuple(self._included_directories.values())
        return _ScanResult(executables, directories)

    def _should_enter_link(self, link: Path, target: Path, kind: str) -> bool:
        """Apply the current traversal policy to one directory link."""
        print()
        print(f"  {FLYellow}Directory link detected:{CRst} {kind}")
        print(f"  {FLCyan}Link:{CRst}   {FGray}{link}{CRst}")
        print(f"  {FLCyan}Target:{CRst} {FGray}{target}{CRst}")
        if not target.is_dir():
            print(f"  {FLRed}Target is missing or is not a directory; ignored.{CRst}")
            return False
        if self._link_policy is _LinkPolicy.ENTER_ALL:
            print(f"  {FGray}enter all selected; entering target{CRst}")
            return True
        if self._link_policy is _LinkPolicy.IGNORE_ALL:
            print(f"  {FGray}ignore all selected; ignored{CRst}")
            return False

        selected = cast(
            _LinkDecision,
            Menu.select(
                [
                    MenuOption(["E"], "Enter", _LinkDecision.ENTER),
                    MenuOption(["A"], "Enter all", _LinkDecision.ENTER_ALL),
                    MenuOption(["I"], "Ignore", _LinkDecision.IGNORE),
                    MenuOption(["S"], "Ignore all", _LinkDecision.IGNORE_ALL),
                ],
                prompt="Directory link action",
                required=True,
                default_key="I",
                inline=True,
                separator=False,
            ),
        )
        if selected is _LinkDecision.ENTER_ALL:
            self._link_policy = _LinkPolicy.ENTER_ALL
            return True
        if selected is _LinkDecision.IGNORE_ALL:
            self._link_policy = _LinkPolicy.IGNORE_ALL
            return False
        return selected is _LinkDecision.ENTER

    def _walk(self, directory: Path, logical_prefix: Path) -> None:
        """Walk one already-approved real directory without following links."""
        try:
            actual_directory = Path(os.path.abspath(os.path.realpath(directory)))
            info = actual_directory.stat()
        except OSError as exc:
            print(f"  {FLRed}Cannot access directory:{CRst} {FGray}{directory}{CRst} ({exc})")
            return

        identity = (int(info.st_dev), int(info.st_ino))
        normalized = _normalize_windows_path(actual_directory)
        if identity in self._visited_directories or normalized in self._visited_paths:
            print(f"  {FGray}duplicate or cyclic directory, skip: {actual_directory}{CRst}")
            return
        self._visited_directories.add(identity)
        self._visited_paths.add(normalized)
        self._included_directories[normalized] = actual_directory

        try:
            with os.scandir(actual_directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            print(f"  {FLRed}Cannot enumerate directory:{CRst} {FGray}{actual_directory}{CRst} ({exc})")
            return

        for entry in entries:
            entry_path = Path(entry.path)
            logical_path = logical_prefix / entry.name
            try:
                link_kind = _directory_link_kind(entry_path)
                if link_kind is not None:
                    target = _resolved_link_target(entry_path)
                    if self._should_enter_link(entry_path, target, link_kind):
                        self._walk(target, logical_path)
                    continue
                if entry.is_symlink():
                    print(f"  {FGray}file symlink ignored: {entry_path}{CRst}")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    self._walk(entry_path, logical_path)
                    continue
                if entry.is_file(follow_symlinks=False) and _is_supported_executable(entry_path):
                    actual_file = Path(os.path.abspath(entry_path))
                    key = _normalize_windows_path(actual_file)
                    self._executables.setdefault(
                        key,
                        _ExecutableCandidate(actual_file, str(logical_path)),
                    )
            except OSError as exc:
                print(f"  {FLRed}Cannot inspect path:{CRst} {FGray}{entry_path}{CRst} ({exc})")


def _confirm_file_symlink(path: Path) -> Optional[Path]:
    """Ask whether to use the target of a directly entered executable symlink."""
    target = _resolved_link_target(path)
    print()
    print(f"  {FLYellow}Executable file symlink detected.{CRst}")
    print(f"  {FLCyan}Link:{CRst}   {FGray}{path}{CRst}")
    print(f"  {FLCyan}Target:{CRst} {FGray}{target}{CRst}")
    if not target.is_file() or not _is_supported_executable(target):
        print(f"  {FLRed}The target is not an existing .exe or .com file.{CRst}")
        return None
    confirmed = Menu.select(
        [
            MenuOption(["Y"], "Use the target executable", True),
            MenuOption(["N"], "Exit", False),
        ],
        prompt="Add target executable",
        required=True,
        default_key="N",
        inline=True,
        separator=False,
    )
    if confirmed is not True:
        Console.print_exit_message_and_exit("Cancelled.")
    return target


def _select_target() -> Optional[_TargetSelection]:
    """Prompt for a file/directory and resolve its executable candidates."""
    raw_path = Input.resolve_input_path(
        os.getcwd(),
        prompt="Enter an executable file or directory path",
        path_type="any",
    )
    input_path = Path(raw_path)
    directory_link = _directory_link_kind(input_path)

    if input_path.is_symlink() and directory_link is None:
        target = _confirm_file_symlink(input_path)
        if target is None:
            return None
        actual = Path(os.path.abspath(target))
        return _TargetSelection(
            input_path=actual,
            is_directory=False,
            executables=(_ExecutableCandidate(actual, actual.name),),
            included_directories=(),
        )

    if input_path.is_file():
        if not _is_supported_executable(input_path):
            print(f"{FLRed}Only .exe and .com files are supported:{CRst} {FGray}{input_path}{CRst}")
            return None
        actual = Path(os.path.abspath(input_path))
        return _TargetSelection(
            input_path=actual,
            is_directory=False,
            executables=(_ExecutableCandidate(actual, actual.name),),
            included_directories=(),
        )

    if input_path.is_dir() or directory_link is not None:
        scan = _ExecutableScanner().scan(input_path)
        return _TargetSelection(
            input_path=Path(os.path.abspath(input_path)),
            is_directory=True,
            executables=scan.executables,
            included_directories=scan.included_directories,
        )

    print(f"{FLRed}The selected path is not a supported executable or directory.{CRst}")
    return None


def _query_firewall_rules(powershell: str) -> tuple[_FirewallRule, ...]:
    """Return local persistent application rules and their full-block status."""
    raw_rules = _json_array(_run_powershell_json(powershell, QUERY_RULES_SCRIPT))
    rules: list[_FirewallRule] = []
    for raw in raw_rules:
        program = _json_text(raw, "Program")
        if not program:
            continue
        rules.append(
            _FirewallRule(
                name=_json_text(raw, "Name"),
                display_name=_json_text(raw, "DisplayName"),
                group=_json_text(raw, "Group"),
                program=Path(program),
                direction=_json_text(raw, "Direction"),
                action=_json_text(raw, "Action"),
                enabled=_json_text(raw, "Enabled"),
                profile=_json_text(raw, "Profile"),
                source_type=_json_text(raw, "SourceType"),
                protocol=_json_text(raw, "Protocol"),
                local_port=_json_text(raw, "LocalPort"),
                remote_port=_json_text(raw, "RemotePort"),
                local_address=_json_text(raw, "LocalAddress"),
                remote_address=_json_text(raw, "RemoteAddress"),
                is_full_block=raw.get("IsFullBlock") is True,
            )
        )
    return tuple(rules)


def _stable_rule_name(program: Path, direction: _Direction) -> str:
    """Build a deterministic internal rule name from program and direction."""
    identity = f"{_normalize_windows_path(program)}\0{direction.value}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"{RULE_NAME_PREFIX}-{digest}"


def _display_name(
    prefix: str,
    target: _TargetSelection,
    candidate: _ExecutableCandidate,
    direction: _Direction,
) -> str:
    """Build one readable rule display name from the user-defined prefix."""
    if target.is_directory:
        return f"{prefix} - {candidate.relative_name} - {direction.value}"
    return f"{prefix} - {direction.value}"


def _rule_request(
    prefix: str,
    target: _TargetSelection,
    candidate: _ExecutableCandidate,
    direction: _Direction,
) -> _RuleRequest:
    """Create the exact specification for one new firewall rule."""
    display_name = _display_name(prefix, target, candidate, direction)
    return _RuleRequest(
        name=_stable_rule_name(candidate.path, direction),
        display_name=display_name,
        description=(
            f"Managed by {RULE_GROUP}. Blocks all {direction.value.lower()} "
            f"network traffic for {candidate.path}."
        ),
        program=candidate.path,
        direction=direction,
    )


def _matching_full_rule(
    rules: Sequence[_FirewallRule],
    program: Path,
    direction: _Direction,
) -> Optional[_FirewallRule]:
    """Return an existing complete block rule for program and direction."""
    wanted_program = _normalize_windows_path(program)
    for rule in rules:
        if not rule.is_full_block or rule.direction != direction.value:
            continue
        if _normalize_windows_path(rule.program) == wanted_program:
            return rule
    return None


def _mutation_results(value: object) -> tuple[_MutationResult, ...]:
    """Parse JSON results returned by add/remove PowerShell operations."""
    results: list[_MutationResult] = []
    for item in _json_array(value):
        results.append(
            _MutationResult(
                name=_json_text(item, "Name"),
                succeeded=item.get("Succeeded") is True,
                detail=_json_text(item, "Detail"),
            )
        )
    return tuple(results)


def _create_rules(
    powershell: str,
    requests: Sequence[_RuleRequest],
) -> tuple[_MutationResult, ...]:
    """Create exact local persistent firewall rules in one PowerShell process."""
    payload = [
        {
            "Name": request.name,
            "DisplayName": request.display_name,
            "Group": RULE_GROUP,
            "Description": request.description,
            "Program": str(request.program),
            "Direction": request.direction.value,
        }
        for request in requests
    ]
    return _mutation_results(
        _run_powershell_json(powershell, CREATE_RULES_SCRIPT, payload)
    )


def _remove_rules(
    powershell: str,
    rules: Sequence[_FirewallRule],
) -> tuple[_MutationResult, ...]:
    """Remove the exact local persistent rule names confirmed by the user."""
    payload = [
        {
            "Name": rule.name,
            "Program": str(rule.program),
            "Direction": rule.direction,
        }
        for rule in rules
    ]
    return _mutation_results(
        _run_powershell_json(powershell, REMOVE_RULES_SCRIPT, payload)
    )


def _select_block_mode() -> _BlockMode:
    """Ask whether to block outbound traffic only or both directions."""
    return cast(
        _BlockMode,
        Menu.select(
            [
                MenuOption(
                    ["1", "O"],
                    f"{_format_direction(_Direction.OUTBOUND)} only",
                    _BlockMode.OUTBOUND,
                    CRst,
                ),
                MenuOption(
                    ["2", "B"],
                    f"{_format_direction(_Direction.INBOUND)} and "
                    f"{_format_direction(_Direction.OUTBOUND)}",
                    _BlockMode.BOTH,
                    CRst,
                ),
            ],
            prompt="Block direction",
            required=True,
            default_key="1",
        ),
    )


def _default_rule_prefix(target: _TargetSelection) -> str:
    """Return the requested default user-visible rule-name prefix."""
    name = target.input_path.name
    if not name:
        name = target.input_path.drive.rstrip(":\\/") or "Root"
    return f"Block - {name}"


def _print_mutation_summary(
    operation: str,
    results: Sequence[_MutationResult],
    *,
    skipped: Optional[int] = None,
) -> int:
    """Print success/failure details and return a process-style exit code."""
    succeeded = sum(result.succeeded for result in results)
    failures = [result for result in results if not result.succeeded]
    print()
    print(f"  {FLYellow}{operation} summary{CRst}")
    print(f"  {FLGreen}Succeeded:{CRst} {succeeded}")
    if skipped is not None:
        print(f"  {FGray}Skipped:{CRst}   {skipped}")
    print(f"  {FLRed}Failed:{CRst}    {len(failures)}")
    for failure in failures:
        print(f"  {FGray}- {failure.name}:{CRst} {_compact_error(failure.detail)}")
    return 1 if failures else 0


def _confirm_add(requests: Sequence[_RuleRequest]) -> bool:
    """Print every pending rule and ask for one batch-add confirmation."""
    print()
    print(f"  {FLYellow}Rules to add:{CRst} {len(requests)}")
    for index, request in enumerate(requests, start=1):
        print(
            f"  {FLCyan}[{index}]{CRst} "
            f"{_colorize_direction_words(request.display_name)}"
        )
        print(
            f"      {FGray}{request.program}{CRst} "
            f"{_format_direction(request.direction, bracketed=True)}"
        )
    selected = Menu.select(
        [
            MenuOption(["Y"], f"Add all {len(requests)} rule(s)", True),
            MenuOption(["N"], "Cancel", False),
        ],
        prompt="Confirm rule creation",
        required=True,
        default_key="N",
        inline=True,
        separator=False,
    )
    return selected is True


def _add_workflow(powershell: str) -> int:
    """Collect, preview, and create complete application block rules."""
    target = _select_target()
    if target is None:
        return 1
    if not target.executables:
        print(f"{FLYellow}No .exe or .com files were found.{CRst}")
        return 0

    print(f"  {FLCyan}Executable files found:{CRst} {len(target.executables)}")
    mode = _select_block_mode()
    directions = (
        (_Direction.OUTBOUND,)
        if mode is _BlockMode.OUTBOUND
        else (_Direction.OUTBOUND, _Direction.INBOUND)
    )
    default_prefix = _default_rule_prefix(target)
    prefix = cast(
        str,
        Input.prompt(
            f"{FLYellow}Rule name prefix {FGray}[{default_prefix}]"
            f"{CRst}{FLYellow} > {CRst}",
            default=default_prefix,
        ),
    )

    try:
        existing_rules = _query_firewall_rules(powershell)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"{FLRed}Cannot query Windows Firewall rules:{CRst} {exc}")
        return 1

    pending: list[_RuleRequest] = []
    skipped = 0
    for candidate in target.executables:
        for direction in directions:
            existing = _matching_full_rule(existing_rules, candidate.path, direction)
            if existing is not None:
                print(
                    f"  {FGray}existed, skip: {candidate.path}{CRst} "
                    f"{_format_direction(direction, bracketed=True)} "
                    f"{FGray}({CRst}"
                    f"{_colorize_direction_words(existing.display_name)}"
                    f"{FGray}){CRst}"
                )
                skipped += 1
                continue
            pending.append(_rule_request(prefix, target, candidate, direction))

    if not pending:
        print(f"{FLGreen}Every requested direction is already completely blocked.{CRst}")
        return _print_mutation_summary("Add", (), skipped=skipped)
    if not _confirm_add(pending):
        Console.print_exit_message("Cancelled.")
        return 0

    try:
        results = _create_rules(powershell, pending)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"{FLRed}Cannot create Windows Firewall rules:{CRst} {exc}")
        return 1
    return _print_mutation_summary("Add", results, skipped=skipped)


def _is_path_within(program: Path, directory: Path) -> bool:
    """Return whether a program path is inside one directory boundary."""
    program_key = _normalize_windows_path(program)
    directory_key = _normalize_windows_path(directory)
    try:
        return os.path.commonpath([program_key, directory_key]) == directory_key
    except ValueError:
        return False


def _rule_matches_target(rule: _FirewallRule, target: _TargetSelection) -> bool:
    """Return whether a firewall rule belongs to the selected file/tree."""
    program_key = _normalize_windows_path(rule.program)
    executable_keys = {
        _normalize_windows_path(candidate.path) for candidate in target.executables
    }
    if program_key in executable_keys:
        return True
    if not target.is_directory or not _is_supported_executable(rule.program):
        return False
    directories = (target.input_path, *target.included_directories)
    return any(_is_path_within(rule.program, directory) for directory in directories)


def _print_removal_rules(rules: Sequence[_FirewallRule]) -> None:
    """Print every exact complete block rule proposed for removal."""
    print()
    print(f"  {FLRed}Complete block rules proposed for removal:{CRst} {len(rules)}")
    for index, rule in enumerate(rules, start=1):
        owner = "this tool" if rule.group == RULE_GROUP else "external/local"
        print(
            f"  {FLCyan}[{index}]{CRst} "
            f"{_colorize_direction_words(rule.display_name)}"
        )
        print(f"      {FGray}Name:       {rule.name}{CRst}")
        print(f"      {FGray}Program:    {rule.program}{CRst}")
        print(f"      {FGray}Direction:{CRst}  {_format_direction(rule.direction)}")
        print(f"      {FGray}Profile:    {rule.profile}{CRst}")
        print(f"      {FGray}Action:     {rule.action} (all protocols/ports/addresses){CRst}")
        print(f"      {FGray}Rule owner: {owner}; source={rule.source_type}{CRst}")


def _confirm_remove(rules: Sequence[_FirewallRule]) -> bool:
    """Ask for final confirmation after printing exact rule identities."""
    selected = Menu.select(
        [
            MenuOption(["Y"], f"Delete all {len(rules)} printed rule(s)", True),
            MenuOption(["N"], "Cancel", False),
        ],
        prompt="Confirm batch deletion",
        required=True,
        default_key="N",
        inline=True,
        separator=False,
    )
    return selected is True


def _revalidate_removal_rules(
    powershell: str,
    approved_rules: Sequence[_FirewallRule],
) -> tuple[_FirewallRule, ...]:
    """Recheck that every approved rule is still the same complete block rule."""
    current_rules = {rule.name: rule for rule in _query_firewall_rules(powershell)}
    validated: list[_FirewallRule] = []
    for approved in approved_rules:
        current = current_rules.get(approved.name)
        if (
            current is None
            or not current.is_full_block
            or current.direction != approved.direction
            or _normalize_windows_path(current.program)
            != _normalize_windows_path(approved.program)
        ):
            raise RuntimeError(
                f"Rule changed after preview; batch deletion aborted: {approved.name}"
            )
        validated.append(current)
    return tuple(validated)


def _open_firewall_settings() -> bool:
    """Open Windows Defender Firewall with Advanced Security in MMC."""
    try:
        subprocess.Popen(
            ["mmc.exe", "wf.msc"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        print(f"{FLRed}Cannot open Windows Firewall settings:{CRst} {exc}")
        return False
    print(f"{FLGreen}Opened Windows Firewall with Advanced Security (wf.msc).{CRst}")
    return True


def _confirm_scripted_removal() -> bool:
    """Warn about rule removal and recommend the manual settings interface."""
    print()
    print(
        f"{FLRed}Warning:{CRst} Removing firewall rules restores network access "
        "for the affected applications."
    )
    print(
        f"{FLYellow}Recommended:{CRst} inspect and delete rules manually in "
        "Windows Firewall with Advanced Security."
    )
    selected = Menu.select(
        [
            MenuOption(["O"], "Open firewall settings (recommended)", "open"),
            MenuOption(["C"], "Continue with exact scripted removal", "continue"),
            MenuOption(["B"], "Back to main menu", "back"),
        ],
        prompt="Removal method",
        required=True,
        default_key="O",
    )
    if selected == "open":
        _open_firewall_settings()
        return False
    return selected == "continue"


def _remove_workflow(powershell: str) -> int:
    """Discover, print, confirm, and delete exact complete block rules."""
    if not _confirm_scripted_removal():
        return 0
    target = _select_target()
    if target is None:
        return 1

    try:
        all_rules = _query_firewall_rules(powershell)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"{FLRed}Cannot query Windows Firewall rules:{CRst} {exc}")
        return 1

    path_matches = [rule for rule in all_rules if _rule_matches_target(rule, target)]
    removable = sorted(
        (rule for rule in path_matches if rule.is_full_block),
        key=lambda rule: (
            _normalize_windows_path(rule.program),
            rule.direction.casefold(),
            rule.display_name.casefold(),
        ),
    )
    ignored = len(path_matches) - len(removable)
    if ignored:
        print(
            f"  {FGray}Ignored {ignored} allow/disabled/partial block rule(s) "
            f"that do not explicitly block all traffic.{CRst}"
        )
    if not removable:
        print(f"{FLGreen}No complete block rules match the selected path.{CRst}")
        return 0

    _print_removal_rules(removable)
    if not _confirm_remove(removable):
        Console.print_exit_message("Cancelled. No firewall rules were removed.")
        return 0

    try:
        validated_rules = _revalidate_removal_rules(powershell, removable)
        results = _remove_rules(powershell, validated_rules)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"{FLRed}Cannot remove Windows Firewall rules:{CRst} {exc}")
        return 1
    return _print_mutation_summary("Removal", results)


def _select_main_action() -> _Action:
    """Display the main feature menu."""
    return cast(
        _Action,
        Menu.select(
            [
                MenuOption(["A"], "Add blocking rules", _Action.ADD),
                MenuOption(["R"], "Remove blocking rules", _Action.REMOVE),
                MenuOption(
                    ["F"],
                    "Open Windows Firewall settings",
                    _Action.OPEN_SETTINGS,
                ),
                MenuOption(["Q"], "Exit", _Action.EXIT),
            ],
            prompt="Feature",
            required=True,
            default_key="Q",
        ),
    )


def _restart_elevated_without_parent_interrupt() -> None:
    """Elevate while preventing the waiting launcher from echoing Ctrl+C.

    The elevated child retains Python's normal SIGINT handler. Only the
    non-elevated parent ignores Ctrl+C while it waits for that child, so one
    interrupt produces one exit message instead of one from each process.
    """
    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        System.restart_elevated()
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the elevated interactive firewall application-rule manager.

    Args:
        argv: Optional arguments excluding the executable name. ``None`` uses
            ``sys.argv[1:]`` through ``argparse``.

    Returns:
        Zero after normal interaction, or one when a firewall query/mutation
        fails.

    Side effects:
        Requests administrator elevation, may open ``wf.msc``, and creates or
        removes local persistent firewall rules only after explicit confirmation.
    """
    if sys.platform != "win32":
        Console.print_error_and_exit(
            f"This script only runs on Windows. Current platform: {sys.platform}"
        )
    _parse_args(argv)

    if not System.is_elevated():
        _restart_elevated_without_parent_interrupt()

    Console.print_banner("WINDOWS FIREWALL APP BLOCKER")
    powershell = Environment.find_pwsh()
    if powershell is None:
        print(f"{FLRed}PowerShell was not found in PATH.{CRst}")
        return 1

    exit_code = 0
    while True:
        action = _select_main_action()
        if action is _Action.EXIT:
            Console.print_exit_message()
            return exit_code
        if action is _Action.OPEN_SETTINGS:
            if not _open_firewall_settings():
                exit_code = 1
            continue
        if action is _Action.ADD:
            exit_code = max(exit_code, _add_workflow(powershell))
        elif action is _Action.REMOVE:
            exit_code = max(exit_code, _remove_workflow(powershell))
        print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
