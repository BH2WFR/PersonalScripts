"""System event viewer: common implementation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time
from typing import cast
import xml.etree.ElementTree as ET
from .models import (
    COMMAND_TIMEOUT,
    EventKind,
    POLL_SECONDS,
    PowerEvent,
    QueryResult,
    SourceState,
    SourceStatus,
    UTC,
)


def _timestamp(value: str) -> dt.datetime:
    """Parse an ISO timestamp; a missing offset means the machine's local timezone."""
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed.astimezone(UTC)



def _json_records(text: str) -> Iterable[dict[str, object]]:
    """Yield JSON objects from NDJSON, ignoring command banners and non-object lines."""
    for line in text.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        record = json.loads(line)
        if isinstance(record, dict):
            yield cast(dict[str, object], record)



def _run_command(command: list[str], cancelled: threading.Event) -> tuple[str, str]:
    """Run a read-only log command with cancellation and a bounded lifetime.

    Args:
        command: Executable and literal arguments; no shell interpretation.
        cancelled: Set by the GUI to stop the child process.

    Returns:
        UTF-8 stdout and stderr (stderr may contain partial-access notices).

    Raises:
        InterruptedError: If cancelled; the child is killed and reaped.
        RuntimeError: On nonzero exit, timeout or process-launch failure.

    Side effects:
        Starts one child process; reads system logs without changing settings.
    """
    if cancelled.is_set():
        raise InterruptedError("Query cancelled.")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, text=True, encoding="utf-8", errors="replace",
        ) as process:
            deadline = time.monotonic() + COMMAND_TIMEOUT
            try:
                while True:
                    if cancelled.is_set():
                        raise InterruptedError("Query cancelled.")
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"Source query exceeded {COMMAND_TIMEOUT:.0f} seconds.")
                    try:
                        output, errors = process.communicate(timeout=POLL_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
            if process.returncode:
                raise RuntimeError(errors.strip()[:2000] or f"Command exited with code {process.returncode}.")
            return output, errors
    except InterruptedError:
        raise
    except OSError as exc:
        raise RuntimeError(f"Could not read this source: {exc}") from exc



def _parse_ssh_message(message: str) -> tuple[EventKind, str, str] | None:
    """Interpret trusted sshd messages; authentication attempts are not connections.

    The caller must verify the server process/provider. A transport-only close
    has no implied authenticated user. Addresses and ports identify endpoints,
    not a synthetic session ID, and records are never paired across queries.
    """
    message = re.sub(r"^sshd(?:-session|-auth)?(?:\[\d+\])?:\s*", "", message.strip())
    if "[preauth]" in message or re.search(r"\b(?:invalid|authenticating) user\b", message):
        return None
    accepted = re.match(r"^Accepted (\S+) for (.+?) from (\S+) port (\d+)\b", message)
    if accepted:
        method, user, address, port = accepted.groups()
        return (EventKind.SSH_CONNECT, f"SSH authentication accepted ({method}); client {address} port {port}", user)
    closed = re.match(
        r"^(?:Disconnected from|Connection (?:closed|reset) by|Received disconnect from) "
        r"(?:user (.+?) )?(\S+) port (\d+)\b", message,
    )
    if closed:
        user, address, port = closed.groups()
        summary = f"SSH transport disconnected; client {address} port {port}"
        if not user:
            summary += "; authentication unknown in this record"
        return EventKind.SSH_DISCONNECT, summary, user or ""
    return None



def _parse_auth_failure(message: str) -> tuple[EventKind, str, str] | None:
    """Recognize explicit SSH/PAM authentication failures after caller source validation."""
    if re.search(r"^(?:error: )?(?:Failed (?:password|publickey|keyboard-interactive) for |Invalid user )", message,
                 re.IGNORECASE) or re.search(r"\bpam_\w+\([^)]*:auth\): authentication failure\b", message):
        return EventKind.AUTHENTICATION, message, ""
    return None


def _collect_source(
    result: QueryResult, source: str, command: list[str],
    parser: Callable[[str], list[PowerEvent]], cancelled: threading.Event,
    *, record_limit: int | None = None,
) -> None:
    """Append one source's bounded-range events or an availability diagnostic; cancellation propagates."""
    try:
        text, errors = _run_command(command, cancelled)
        events = [event for event in parser(text) if result.start <= event.timestamp < result.end]
        result.events.extend(events)
        state = SourceState.LIMITED if errors.strip() else SourceState.OK if events else SourceState.EMPTY
        message = errors.strip()[:2000] or "Accessible retained records queried; completeness is not guaranteed."
        if record_limit is not None and sum(line.lstrip().startswith("{") for line in text.splitlines()) > record_limit:
            state = SourceState.LIMITED
            message += " Source record limit reached; narrow the time range."
        result.statuses.append(SourceStatus(source, state, message, len(events)))
    except (RuntimeError, ValueError, KeyError, ET.ParseError) as exc:
        result.statuses.append(SourceStatus(source, SourceState.ERROR, str(exc)))

