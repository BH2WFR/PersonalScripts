#!/usr/bin/env python3
"""Repair macOS clipboard images received through Windows App / RDP.

Shows advertised image types, the first 16 file-header bytes, actual encoding
and dimensions. After Proceed? confirmation, decodes the image bytes and writes
real PNG representations to the clipboard. --force skips confirmation. This is
a one-shot operation, not a background listener. Other clipboard representations
are removed; multiple readable image items are retained as separate PNG items.
Text, file references without embedded image data, and unreadable images fail
without clearing the clipboard. A change during confirmation cancels the write.

Requirements:
    - macOS: built-in /usr/bin/osascript and AppKit; no third-party packages.

Usage:
    conda run --no-capture-output -n base python tools/macos/rdp-clipboard-image-fix.py
    conda run -n base python tools/macos/rdp-clipboard-image-fix.py --force
"""

import base64
from dataclasses import dataclass
from enum import StrEnum
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402


OSASCRIPT = "/usr/bin/osascript"
BACKEND_TIMEOUT_SECONDS = 60
HEADER_BYTES = 16
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# AppKit performs decoding/encoding entirely inside this child process. Only
# metadata and a 16-byte header cross stdout, never complete image data.
JXA_SOURCE = r"""
ObjC.import('AppKit');
const HEADER_BYTES = 16;
const MAX_DATA_BYTES = 128 * 1024 * 1024;
const MAX_ITEMS = 16;
const MAX_TYPES = 64;
const PNG_SIGNATURE = 'iVBORw0KGgo=';

function run(argv) {
    const action = argv[0];
    if (action !== 'inspect' && action !== 'repair') throw new Error('Invalid action.');
    const pb = $.NSPasteboard.generalPasteboard;
    const before = Number(pb.changeCount);
    if (action === 'repair' && before !== Number(argv[1])) {
        throw new Error('Clipboard changed since inspection. Run the script again.');
    }
    const items = pb.pasteboardItems;
    const count = items && !items.isNil() ? Number(items.count) : 0;
    if (count > MAX_ITEMS) throw new Error('Too many clipboard items; clipboard unchanged.');
    const supported = new Set(ObjC.deepUnwrap($.NSBitmapImageRep.imageTypes));
    supported.add('public.png');
    supported.add('public.tiff');
    const formats = [];
    const images = [];
    const prepared = $.NSMutableArray.array;

    // Inspect every image item; prefer its PNG representation, even if mislabeled.
    for (let index = 0; index < count; index++) {
        const item = items.objectAtIndex(index);
        const types = ObjC.deepUnwrap(item.types);
        if (types.length > MAX_TYPES) throw new Error('Too many formats; clipboard unchanged.');
        const imageTypes = types.filter(type => supported.has(type));
        imageTypes.sort((a, b) => Number(b === 'public.png') - Number(a === 'public.png'));
        let selected = null;
        for (const type of imageTypes) {
            const entry = {item: index + 1, type, bytes: 0, header: '', readable: false};
            formats.push(entry);
            const data = item.dataForType($(type));
            if (!data || data.isNil()) continue;
            entry.bytes = Number(data.length);
            entry.header = ObjC.unwrap(data.subdataWithRange(
                $.NSMakeRange(0, Math.min(HEADER_BYTES, entry.bytes))
            ).base64EncodedStringWithOptions(0));
            if (entry.bytes > MAX_DATA_BYTES) {
                throw new Error('Image exceeds 128 MiB limit; clipboard unchanged.');
            }
            const bitmap = $.NSBitmapImageRep.imageRepWithData(data);
            if (!bitmap || bitmap.isNil()) continue;
            entry.readable = true;
            if (selected === null) selected = {bitmap, type};
        }
        if (selected === null) continue;
        const bitmap = selected.bitmap;
        const summary = {
            item: index + 1, type: selected.type,
            width: Number(bitmap.pixelsWide), height: Number(bitmap.pixelsHigh)
        };
        images.push(summary);
        if (action !== 'repair') continue;

        // Prepare all output before clearing the clipboard, retaining alpha.
        const png = bitmap.representationUsingTypeProperties(
            $.NSBitmapImageFileTypePNG, $.NSDictionary.dictionary
        );
        if (!png || png.isNil() || Number(png.length) < 8) {
            throw new Error('PNG encoding failed; clipboard unchanged.');
        }
        const signature = ObjC.unwrap(png.subdataWithRange(
            $.NSMakeRange(0, 8)
        ).base64EncodedStringWithOptions(0));
        const verified = $.NSBitmapImageRep.imageRepWithData(png);
        if (signature !== PNG_SIGNATURE || !verified || verified.isNil()
            || Number(verified.pixelsWide) !== summary.width
            || Number(verified.pixelsHigh) !== summary.height) {
            throw new Error('PNG validation failed; clipboard unchanged.');
        }
        const output = $.NSPasteboardItem.alloc.init;
        if (!output.setDataForType(png, $('public.png'))) {
            throw new Error('Cannot prepare PNG item; clipboard unchanged.');
        }
        prepared.addObject(output);
    }
    if (Number(pb.changeCount) !== before) {
        throw new Error('Clipboard changed during reading. Run the script again.');
    }
    if (action === 'repair') {
        if (images.length === 0) throw new Error('Clipboard contains no readable bitmap image.');
        pb.clearContents;
        if (!pb.writeObjects(prepared)) {
            throw new Error('Clipboard write failed after clearing. Copy the source image again.');
        }
        const writtenCount = Number(pb.changeCount);
        const written = pb.pasteboardItems;
        if (!written || written.isNil() || Number(written.count) !== images.length) {
            throw new Error('Clipboard changed or write verification failed.');
        }
        for (let index = 0; index < images.length; index++) {
            const actual = written.objectAtIndex(index).dataForType($('public.png'));
            const expected = prepared.objectAtIndex(index).dataForType($('public.png'));
            if (!actual || actual.isNil() || !actual.isEqualToData(expected)) {
                throw new Error('Clipboard changed or PNG read-back verification failed.');
            }
        }
        if (Number(pb.changeCount) !== writtenCount) {
            throw new Error('Clipboard changed during write verification.');
        }
    }
    return JSON.stringify({change_count: Number(pb.changeCount), formats, images});
}
"""


class ClipboardAction(StrEnum):
    """Supported native operations: read metadata or re-encode and replace images."""

    INSPECT = "inspect"
    REPAIR = "repair"


@dataclass(frozen=True)
class ImageFormat:
    """Metadata for an advertised image representation; header is at most 16 bytes."""

    item: int
    declared_type: str
    size: int
    header: bytes
    readable: bool


@dataclass(frozen=True)
class ClipboardImage:
    """Selected decodable bitmap and its item number, advertised type and dimensions."""

    item: int
    declared_type: str
    width: int
    height: int


@dataclass(frozen=True)
class ClipboardSnapshot:
    """Clipboard revision, representation metadata and selected bitmap images."""

    change_count: int
    formats: tuple[ImageFormat, ...]
    images: tuple[ClipboardImage, ...]


def _run_backend(
    action: ClipboardAction, expected_change_count: int | None = None,
) -> ClipboardSnapshot:
    """Run the native operation and return metadata, raising RuntimeError on failure.

    Args:
        action: Inspect or repair the clipboard.
        expected_change_count: Required inspected revision for a repair operation.

    Returns:
        A snapshot containing only format headers and image metadata.

    Raises:
        RuntimeError: If AppKit fails, times out, or returns invalid metadata.
        ValueError: If repair is requested without an inspected revision.

    Side effects:
        Starts osascript; REPAIR replaces clipboard contents with PNG images.
    """
    if action == ClipboardAction.REPAIR and expected_change_count is None:
        raise ValueError("Repair requires an inspected clipboard revision.")
    command = [OSASCRIPT, "-l", "JavaScript", "-", action.value]
    if expected_change_count is not None:
        command.append(str(expected_change_count))
    try:
        result = subprocess.run(
            command, input=JXA_SOURCE, capture_output=True, text=True,
            encoding="utf-8", timeout=BACKEND_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Clipboard operation timed out; its final state is unverified.") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot run macOS clipboard helper: {exc}") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "macOS clipboard helper failed.")
    try:
        report = json.loads(result.stdout)
        return ClipboardSnapshot(
            change_count=int(report["change_count"]),
            formats=tuple(ImageFormat(
                item=int(entry["item"]), declared_type=str(entry["type"]),
                size=int(entry["bytes"]),
                header=base64.b64decode(entry["header"], validate=True)[:HEADER_BYTES],
                readable=bool(entry["readable"]),
            ) for entry in report["formats"]),
            images=tuple(ClipboardImage(
                item=int(entry["item"]), declared_type=str(entry["type"]),
                width=int(entry["width"]), height=int(entry["height"]),
            ) for entry in report["images"]),
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Invalid clipboard metadata returned by native helper.") from exc


def _detect_encoding(header: bytes) -> str:
    """Identify common bitmap signatures from a bounded header without decoding pixels."""
    if header.startswith(PNG_SIGNATURE):
        return "PNG"
    if header.startswith((b"II*\0", b"MM\0*", b"II+\0", b"MM\0+")):
        return "TIFF"
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header.startswith(b"BM"):
        return "BMP"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "WebP"
    return "Unknown (see header)"


def _show_snapshot(snapshot: ClipboardSnapshot) -> None:
    """Print bounded format/header metadata and selected image dimensions to stdout."""
    print(f"Clipboard revision: {snapshot.change_count}")
    for entry in snapshot.formats:
        print(f"\n{FLCyan}Item {entry.item}: {entry.declared_type!r}{CRst}")
        print(f"  Size: {Console.format_size(entry.size)} ({entry.size} bytes)")
        print(f"  Actual encoding: {_detect_encoding(entry.header)}")
        print(f"  Header (up to {HEADER_BYTES} bytes): {entry.header.hex(' ').upper() or '(unavailable)'}")
        if not entry.readable:
            print(f"{FLYellow}  No readable bitmap in this representation.{CRst}")
        elif entry.declared_type == "public.png" and not entry.header.startswith(PNG_SIGNATURE):
            print(f"{FLYellow}  Mismatch: public.png contains non-PNG data.{CRst}")
    for image in snapshot.images:
        print(f"\nImage item {image.item}: {image.width} x {image.height} pixels")


def main() -> int:
    """Inspect, confirm and repair clipboard images; return 0 on success/cancel, 1 on error.

    Reads command-line arguments and stdin, prints diagnostics, and replaces the
    clipboard only after confirmation or --force. --help never reads the clipboard.
    Ctrl+C propagates to the module-level handler. No files are written.
    """
    # ── help and argument validation ────────────────────
    arguments = sys.argv[1:]
    if "--help" in arguments or "-h" in arguments:
        Console.print_banner("RDP CLIPBOARD IMAGE FIX")
        print(f"""{FGray}Usage:
  python rdp-clipboard-image-fix.py [--force]

Description:
  Show current clipboard image formats, actual encoding and first 16 header
  bytes, then re-encode images as PNG to repair Windows App / RDP pasting.
  Asks Proceed? [y/N] by default. Replaces all clipboard representations with
  PNG image items. Non-image/unreadable content returns exit code 1 unchanged.
  Aborts if the clipboard changes before writing. Runs once; does not monitor.
  Limits: 16 items, 64 formats per item, 128 MiB per image representation.

Options:
  --force      Skip confirmation and repair automatically.
  --help, -h   Show this help without accessing the clipboard.

Requirements:
  macOS; built-in /usr/bin/osascript and AppKit. No third-party packages.
{CRst}""")
        return 0
    Console.print_banner("RDP CLIPBOARD IMAGE FIX")
    if sys.platform != "darwin":
        print(f"{FLRed}This script only runs on macOS. Current platform: {sys.platform}{CRst}", file=sys.stderr)
        return 1
    unknown = [argument for argument in arguments if argument != "--force"]
    if unknown:
        print(f"{FLRed}Unknown arguments: {unknown!r}. Use --help.{CRst}", file=sys.stderr)
        return 1

    # ── inspect before requesting confirmation ──────────
    try:
        snapshot = _run_backend(ClipboardAction.INSPECT)
        _show_snapshot(snapshot)
        if not snapshot.images:
            raise RuntimeError("Clipboard contains no readable bitmap image; clipboard unchanged.")
        print(f"\nReplace clipboard contents with {len(snapshot.images)} PNG image item(s).")
        if "--force" not in arguments:
            answer = Input.prompt(f"{FLYellow}Proceed? [y/N]: {CRst}", default="n", transform=str.casefold)
            if answer not in ("y", "yes"):
                print(f"{FGray}Cancelled; clipboard unchanged.{CRst}")
                return 0

        # ── repair and verify native clipboard write ────
        repaired = _run_backend(ClipboardAction.REPAIR, snapshot.change_count)
        print(f"{FLGreen}Repaired {len(repaired.images)} image(s) as PNG; clipboard read-back verified.{CRst}")
        return 0
    except EOFError:
        print(f"{FLRed}No confirmation input. Use --force for unattended repair.{CRst}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"{FLRed}Error: {exc}{CRst}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
