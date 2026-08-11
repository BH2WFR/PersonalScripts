#!/usr/bin/env python3
"""Clear every registered Windows Event Log channel in one operation.

Enumerates channels with ``wevtutil el`` and attempts to clear each one with
``wevtutil cl``. The script requires administrator privileges, asks for an
explicit irreversible-action confirmation unless ``--force`` is supplied, and
reports channels that Windows refused to clear. Clearing does not disable
logging, so new events may appear immediately.

Requirements:
    - Windows 10 or later
    - system: wevtutil (built into Windows)

Usage:
    python clear-all-event-logs.py
    python clear-all-event-logs.py --force
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402,F403


PROGRESS_INTERVAL = 25
ERROR_DETAIL_LIMIT = 240


@dataclass(frozen=True)
class CliArgs:
    """Validated command-line arguments for the cleanup operation."""

    force: bool


@dataclass(frozen=True)
class LogFailure:
    """One Windows Event Log channel that could not be cleared."""

    name: str
    detail: str


@dataclass(frozen=True)
class ClearSummary:
    """Aggregate result of clearing all enumerated event-log channels."""

    total: int
    cleared: int
    failures: tuple[LogFailure, ...]


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the colored command-line parser for the cleanup tool."""
    return argparse.ArgumentParser(
        description=(
            f"{FLYellow}CLEAR ALL WINDOWS EVENT LOGS{CRst}\n\n"
            "Enumerate every Windows Event Log channel registered with the "
            "system and attempt to clear it. This operation is irreversible."
        ),
        epilog=(
            f"{FLYellow}Examples:{CRst}\n"
            f"  {FGray}python clear-all-event-logs.py{CRst}\n"
            f"  {FGray}python clear-all-event-logs.py --force{CRst}\n\n"
            f"{FLYellow}Notes:{CRst}\n"
            "  Clearing does not disable event logging; new events may appear immediately.\n"
            "  Windows may record an audit event stating that the Security log was cleared.\n"
            "  A non-zero exit code means at least one channel could not be cleared.\n\n"
            f"{FLYellow}Requirements:{CRst}\n"
            "  Windows 10 or later; administrator privileges; built-in wevtutil."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _parse_args(argv: Optional[list[str]]) -> CliArgs:
    """Parse command-line arguments into a precisely typed value."""
    parser = _build_argument_parser()
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="clear all enumerated logs without interactive confirmation",
    )
    namespace = parser.parse_args(argv)
    return CliArgs(force=bool(namespace.force))


def _run_wevtutil(
    executable: str,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run one ``wevtutil`` command and capture its UTF-8 text output.

    Args:
        executable: Resolved path to ``wevtutil.exe``.
        arguments: Command arguments without the executable name.

    Returns:
        Completed process containing the exit code and captured output.

    Raises:
        OSError: If Windows cannot start the executable.
    """
    return subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _error_detail(result: subprocess.CompletedProcess[str]) -> str:
    """Return a compact diagnostic extracted from a failed process result."""
    detail = " ".join((result.stderr or result.stdout or "").split())
    if not detail:
        detail = f"wevtutil exited with code {result.returncode}"
    if len(detail) > ERROR_DETAIL_LIMIT:
        return f"{detail[:ERROR_DETAIL_LIMIT - 3]}..."
    return detail


def _enumerate_event_logs(executable: str) -> list[str]:
    """Return every unique channel reported by ``wevtutil el``.

    Args:
        executable: Resolved path to ``wevtutil.exe``.

    Returns:
        Channel names in the order reported by Windows.

    Raises:
        RuntimeError: If enumeration fails or produces no channel names.
        OSError: If Windows cannot start ``wevtutil``.
    """
    result = _run_wevtutil(executable, ["el"])
    if result.returncode != 0:
        raise RuntimeError(_error_detail(result))
    log_names = list(dict.fromkeys(
        raw_name.strip()
        for raw_name in result.stdout.splitlines()
        if raw_name.strip()
    ))
    if not log_names:
        raise RuntimeError("wevtutil returned no registered event-log channels.")
    return log_names


def _clear_event_logs(executable: str, log_names: list[str]) -> ClearSummary:
    """Attempt to clear all supplied event-log channels without stopping early.

    Args:
        executable: Resolved path to ``wevtutil.exe``.
        log_names: Exact channel names returned by Windows.

    Returns:
        Counts and per-channel failure diagnostics. All channels are attempted
        even when an earlier clear operation fails.

    Side effects:
        Irreversibly clears Windows Event Log data and prints periodic progress.
    """
    cleared_count = 0
    failures: list[LogFailure] = []
    total = len(log_names)
    for index, log_name in enumerate(log_names, start=1):
        if index == 1 or index % PROGRESS_INTERVAL == 0 or index == total:
            print(f"  {FLCyan}Progress:{CRst} {index}/{total}")
        try:
            result = _run_wevtutil(executable, ["cl", log_name])
        except OSError as exc:
            failures.append(LogFailure(log_name, str(exc)))
            continue
        if result.returncode == 0:
            cleared_count += 1
        else:
            failures.append(LogFailure(log_name, _error_detail(result)))
    return ClearSummary(total, cleared_count, tuple(failures))


def _confirm_clear(log_count: int) -> bool:
    """Ask for explicit confirmation before irreversible log deletion."""
    print(
        f"{FLRed}Warning:{CRst} This will irreversibly clear "
        f"{FLYellow}{log_count}{CRst} registered Windows Event Log channels."
    )
    print(f"{FGray}The operation cannot be undone and does not disable future logging.{CRst}")
    selected = Menu.select(
        [
            MenuOption(["Y"], "Clear all event logs", value=True),
            MenuOption(["N"], "Cancel", value=False),
        ],
        prompt="Confirm cleanup",
        default_key="N",
        inline=True,
        separator=False,
    )
    return selected is True


def _print_summary(summary: ClearSummary, elapsed_seconds: float) -> None:
    """Print aggregate counts and all channels that Windows refused to clear."""
    print()
    print(f"  {FLYellow}Cleanup summary{CRst}")
    print(f"  {FLCyan}Enumerated:{CRst} {summary.total}")
    print(f"  {FLGreen}Cleared:{CRst}    {summary.cleared}")
    print(f"  {FLRed}Failed:{CRst}     {len(summary.failures)}")
    print(f"  {FLCyan}Elapsed:{CRst}    {elapsed_seconds:.1f}s")
    if not summary.failures:
        return
    print(f"\n  {FLRed}Channels not cleared:{CRst}")
    for failure in summary.failures:
        print(f"  {FGray}- {failure.name}:{CRst} {failure.detail}")


def main(argv: Optional[list[str]] = None) -> int:
    """Enumerate, confirm, and clear all Windows Event Log channels."""
    if sys.platform != "win32":
        Utils.print_error_and_exit(
            f"This script only runs on Windows. Current platform: {sys.platform}"
        )
    args = _parse_args(argv)

    # Elevate before printing operational output so the shared helper can keep
    # the cleanup in the same terminal when gsudo or sudo is available.
    if not Utils.is_elevated():
        Utils.restart_elevated()

    Utils.set_locale_utf8()
    Utils.print_banner("CLEAR ALL WINDOWS EVENT LOGS")

    wevtutil_check = CmdCheck(
        "wevtutil",
        required=True,
        hints={
            "windows": f"  {FGray}wevtutil is built into supported Windows versions.{CRst}",
        },
    )
    if not Utils.check_commands(wevtutil_check) or wevtutil_check.path is None:
        return 1

    try:
        log_names = _enumerate_event_logs(wevtutil_check.path)
    except (OSError, RuntimeError) as exc:
        print(f"{FLRed}Cannot enumerate Windows Event Logs:{CRst} {exc}")
        return 1
    print(f"  {FLCyan}Registered channels:{CRst} {len(log_names)}")

    if args.force:
        print(f"  {FLYellow}Force mode:{CRst} confirmation skipped.")
    elif not _confirm_clear(len(log_names)):
        Utils.print_exit_message("Cancelled.")
        return 0

    start_time = time.perf_counter()
    summary = _clear_event_logs(wevtutil_check.path, log_names)
    elapsed_seconds = time.perf_counter() - start_time
    _print_summary(summary, elapsed_seconds)
    return 1 if summary.failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
