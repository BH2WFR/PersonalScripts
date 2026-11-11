"""System event viewer: common implementation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import datetime as dt
import json
import os
import re
import selectors
import subprocess
import threading
import time
from typing import cast
import xml.etree.ElementTree as ET
from .models import (
    COMMAND_TIMEOUT,
    EventKind,
    MAX_LOG_BYTES,
    MAX_LOG_ERROR_BYTES,
    MAX_LOG_LINE_BYTES,
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



def _read_bounded_ndjson(
    process: subprocess.Popen[bytes], cancelled: threading.Event, deadline: float, record_limit: int,
) -> tuple[bytes, bytes, bool]:
    """Read macOS log pipes with byte/record bounds, retaining only complete records.

    POSIX pipe selectors drain stderr alongside stdout. Limits return a partial
    chronological prefix and a coverage warning; the caller kills/reaps the child.
    Cancellation and timeout propagate so they cannot appear as successful reads.
    """
    assert process.stdout is not None and process.stderr is not None
    output = bytearray()
    errors = bytearray()
    pending = bytearray()
    read_bytes = 0
    records = 0
    reason = ""

    def append_line(line: bytes) -> bool:
        """Append one complete line unless it exceeds the JSON-record budget."""
        nonlocal records, reason
        if line.lstrip().startswith(b"{"):
            if records >= record_limit:
                reason = f"Source record limit ({record_limit:,}) reached."
                return False
            records += 1
        output.extend(line)
        return True

    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map() and not reason:
            if cancelled.is_set():
                raise InterruptedError("Query cancelled.")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Source query exceeded {COMMAND_TIMEOUT:.0f} seconds.")
            for key, _ in selector.select(timeout=POLL_SECONDS):
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    if key.fileobj is process.stdout and pending:
                        append_line(bytes(pending))
                        pending.clear()
                    if reason:
                        break
                    continue
                if key.fileobj is process.stderr:
                    remaining = MAX_LOG_ERROR_BYTES - len(errors)
                    errors.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        reason = "Source stderr byte limit reached."
                        break
                    continue
                remaining = MAX_LOG_BYTES - read_bytes
                read_bytes += len(chunk)
                parts = chunk[:remaining].split(b"\n")
                for index, part in enumerate(parts):
                    pending.extend(part)
                    if len(pending) > MAX_LOG_LINE_BYTES:
                        reason = "Source line byte limit reached."
                        break
                    if index < len(parts) - 1:
                        if not append_line(bytes(pending) + b"\n"):
                            break
                        pending.clear()
                if not reason and read_bytes > MAX_LOG_BYTES:
                    reason = "Source output byte limit reached."
                if reason:
                    break
    if reason:
        # Keep the warning first so source-status shortening cannot hide it.
        warning = (f"{reason} Partial output retained from the beginning of the query; "
                   "later records may be missing. Narrow the time range.\n").encode("utf-8")
        return bytes(output), warning + bytes(errors), True
    return bytes(output), bytes(errors), False


def _run_command(
    command: list[str], cancelled: threading.Event, *, ndjson_limit: int | None = None,
) -> tuple[str, str]:
    """Run a read-only log command with cancellation and a bounded lifetime.

    Args:
        command: Executable and literal arguments; no shell interpretation.
        cancelled: Set by the GUI to stop the child process.
        ndjson_limit: macOS unified-log record cap; also bounds stdout, stderr
            and individual lines while reading. Requires POSIX pipe selectors.

    Returns:
        UTF-8 stdout and stderr (including partial-access or truncation notices).

    Raises:
        ValueError: If the requested record limit is not positive.
        InterruptedError: If cancelled; the child is killed and reaped.
        RuntimeError: On nonzero exit, timeout or process-launch failure.

    Side effects:
        Starts one child process; reads system logs without changing settings.
    """
    if cancelled.is_set():
        raise InterruptedError("Query cancelled.")
    if ndjson_limit is not None and ndjson_limit <= 0:
        raise ValueError("The log record limit must be positive.")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    try:
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment,
        ) as process:
            deadline = time.monotonic() + COMMAND_TIMEOUT
            limited = False
            try:
                if ndjson_limit is not None:
                    output, errors, limited = _read_bounded_ndjson(process, cancelled, deadline, ndjson_limit)
                    if not limited:
                        while process.poll() is None:
                            if cancelled.is_set():
                                raise InterruptedError("Query cancelled.")
                            if time.monotonic() >= deadline:
                                raise RuntimeError(f"Source query exceeded {COMMAND_TIMEOUT:.0f} seconds.")
                            try:
                                process.wait(timeout=POLL_SECONDS)
                            except subprocess.TimeoutExpired:
                                continue
                else:
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
                process.wait()
            decoded_errors = errors.decode("utf-8", errors="replace")
            if process.returncode and not limited:
                raise RuntimeError(decoded_errors.strip()[:2000] or f"Command exited with code {process.returncode}.")
            return output.decode("utf-8", errors="replace"), decoded_errors
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
    *, record_limit: int | None = None, stream_ndjson: bool = False,
) -> None:
    """Append one source's bounded-range events or an availability diagnostic; cancellation propagates."""
    try:
        if stream_ndjson:
            if record_limit is None:
                raise ValueError("Streaming log sources require a record limit.")
            text, errors = _run_command(command, cancelled, ndjson_limit=record_limit)
        else:
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

