"""Pure Scancode Map encoding and validated backup documents.

Standard library only. Used by ../keyboard-remap.py; no registry or GUI access.
Unknown 16-bit words are preserved, including prefixes not in the key catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import struct

REGISTRY_PATH = r"SYSTEM\CurrentControlSet\Control\Keyboard Layout"
VALUE_NAME = "Scancode Map"
BACKUP_FORMAT = "PersonalScripts.KeyboardRemap/1"
MAX_BYTES = 1024 * 1024
WORD_MAX = 0xFFFF
HEADER = bytes(8)
TERMINATOR = bytes(4)


@dataclass(frozen=True)
class Mapping:
    """One source-to-target scan-word mapping; target zero disables the key.

    Args:
        source: Nonzero 16-bit scan word.
        target: 16-bit scan word, including zero for Disable.

    Raises:
        ValueError: A value is not an integer in its permitted range.
    """

    source: int
    target: int

    def __post_init__(self) -> None:
        for name, value, minimum in (("Source", self.source, 1), ("Target", self.target, 0)):
            if type(value) is not int or not minimum <= value <= WORD_MAX:
                raise ValueError(f"{name} must be an integer from {minimum} to {WORD_MAX}.")


def validate_mappings(rows: tuple[Mapping, ...]) -> None:
    """Reject duplicate sources; each physical key can have only one target.

    Args:
        rows: Immutable mapping sequence; order is retained.

    Raises:
        ValueError: A source occurs more than once, or the data exceeds 1 MiB.
    """
    if 16 + 4 * len(rows) > MAX_BYTES:
        raise ValueError("Mapping data exceeds the 1 MiB safety limit.")
    sources: set[int] = set()
    for row in rows:
        if row.source in sources:
            raise ValueError(f"Duplicate source scan code: 0x{row.source:04X}.")
        sources.add(row.source)


def decode_map(data: bytes | None) -> tuple[Mapping, ...]:
    """Decode a registry value; None means the value does not exist.

    Args:
        data: REG_BINARY bytes or None. Unknown scan words are not rewritten.

    Returns:
        Mappings in stored order, never sorted or deduplicated implicitly.

    Raises:
        ValueError: Header, DWORD count, length, terminator or sources are invalid.
    """
    if data is None:
        return ()
    if len(data) < 16 or len(data) > MAX_BYTES or data[:8] != HEADER:
        raise ValueError("Invalid Scancode Map header or size; editing is blocked.")
    count = struct.unpack_from("<I", data, 8)[0]
    if count < 1 or len(data) != 12 + count * 4 or data[-4:] != TERMINATOR:
        raise ValueError("Invalid Scancode Map count, length or terminator; editing is blocked.")
    rows = tuple(Mapping(source, target)
                 for target, source in struct.iter_unpack("<HH", data[12:-4]))
    validate_mappings(rows)
    return rows


def encode_map(rows: tuple[Mapping, ...]) -> bytes:
    """Encode rows as REG_BINARY, with destination before source, little-endian.

    Args:
        rows: Mapping sequence, including an empty sequence for a present empty map.

    Returns:
        Eight reserved zero bytes, a 32-bit count including the terminator,
        mapping DWORDs and a zero terminator.

    Raises:
        ValueError: Duplicate sources or excessive size.
    """
    validate_mappings(rows)
    body = b"".join(struct.pack("<HH", row.target, row.source) for row in rows)
    return HEADER + struct.pack("<I", len(rows) + 1) + body + TERMINATOR


@dataclass(frozen=True)
class Snapshot:
    """Exact saved registry bytes, preserving absent versus present-empty state.

    Args:
        data: Validated REG_BINARY data or None when the value is absent.

    Raises:
        ValueError: The binary layout is invalid.
    """

    data: bytes | None

    def __post_init__(self) -> None:
        if self.data is not None and not isinstance(self.data, bytes):
            raise ValueError("Snapshot data must be bytes or None.")
        decode_map(self.data)

    @property
    def rows(self) -> tuple[Mapping, ...]:
        """Return the decoded mapping sequence without accessing Windows."""
        return decode_map(self.data)


def hex_view(snapshot: Snapshot) -> str:
    """Format exact pending bytes as offset-prefixed, 16-byte hexadecimal rows.

    Args:
        snapshot: Validated draft; None data means delete the registry value.

    Returns:
        Read-only display text with byte count and uppercase hexadecimal bytes.
        An absent value is described explicitly, never encoded as an empty map.
    """
    if snapshot.data is None:
        return "Scancode Map: value absent / will be deleted when applied.\nNo REG_BINARY bytes."
    data = snapshot.data
    lines = [f"Scancode Map | REG_BINARY | {len(data)} bytes", "Offset    Hexadecimal bytes"]
    width = 16
    lines.extend(f"{offset:08X}  {data[offset:offset + width].hex(' ').upper()}"
                 for offset in range(0, len(data), width))
    return "\n".join(lines)


def backup_text(snapshot: Snapshot) -> str:
    """Return a UTF-8-compatible JSON backup of exactly one registry value.

    Args:
        snapshot: Saved state, not necessarily the GUI's current draft.

    Returns:
        Versioned JSON text; absent values use null, present values use hex.
    """
    return json.dumps({"format": BACKUP_FORMAT, "path": REGISTRY_PATH,
                       "value": VALUE_NAME,
                       "data": None if snapshot.data is None else snapshot.data.hex()},
                      indent=2) + "\n"


def parse_backup(text: str) -> Snapshot:
    """Validate a backup document without accepting arbitrary registry paths.

    Args:
        text: A backup produced by backup_text, at most 3 MiB of text.

    Returns:
        Validated snapshot. Restoring it must still require user confirmation.

    Raises:
        ValueError: Schema, target path, hex or binary content is invalid.
    """
    if len(text) > MAX_BYTES * 3:
        raise ValueError("Backup exceeds the size limit.")
    obj: object = json.loads(text)
    if not isinstance(obj, dict) or set(obj) != {"format", "path", "value", "data"}:
        raise ValueError("Not a keyboard-remap backup document.")
    if (obj["format"], obj["path"], obj["value"]) != (BACKUP_FORMAT, REGISTRY_PATH, VALUE_NAME):
        raise ValueError("Backup format or registry target does not match this application.")
    raw = obj["data"]
    if raw is None:
        return Snapshot(None)
    if not isinstance(raw, str):
        raise ValueError("Backup data must be hexadecimal text or null.")
    return Snapshot(bytes.fromhex(raw))
