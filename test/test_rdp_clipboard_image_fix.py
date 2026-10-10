"""Verify RDP image repair using isolated macOS pasteboards, never the user's clipboard.

Requirements: macOS, built-in osascript/AppKit, Python standard library.
Usage: conda run -n base python -m unittest discover -s test -p test_rdp_clipboard_image_fix.py
"""

import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "rdp_clipboard_image_fix", ROOT / "tools/macos/rdp-clipboard-image-fix.py"
)
assert SPEC is not None and SPEC.loader is not None
app = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = app
SPEC.loader.exec_module(app)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    """Build a PNG fixture chunk with a valid CRC from its type and payload."""
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


PNG_FIXTURE = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(bytes([0, 12, 34, 56, 128])))
    + _png_chunk(b"IEND", b"")
)


@unittest.skipUnless(sys.platform == "darwin", "Requires native macOS AppKit")
class ClipboardRepairTests(unittest.TestCase):
    """Exercise native decoding and CLI decisions against a private pasteboard."""

    def setUp(self) -> None:
        """Allocate a unique named pasteboard and redirect only the test helper to it."""
        self.name = f"org.personalscripts.rdp-test.{uuid.uuid4().hex}"
        self.pasteboard_expression = f"$.NSPasteboard.pasteboardWithName($({json.dumps(self.name)}))"
        source = app.JXA_SOURCE.replace("$.NSPasteboard.generalPasteboard", self.pasteboard_expression)
        self.source_patch = patch.object(app, "JXA_SOURCE", source)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.addCleanup(self._native, "pb.releaseGlobally; 'released';")

    def _native(self, body: str) -> str:
        """Run fixture code on the named pasteboard, returning bounded stdout."""
        source = f"ObjC.import('AppKit'); const pb = {self.pasteboard_expression};\n{body}"
        return subprocess.run(
            [app.OSASCRIPT, "-l", "JavaScript", "-"], input=source,
            text=True, encoding="utf-8", capture_output=True, check=True, timeout=15,
        ).stdout.strip()

    def _seed_image(self, *, mislabeled: bool = True, copies: int = 1) -> None:
        """Put one or more bitmap items on the private clipboard, optionally mislabeled."""
        fixture = base64.b64encode(PNG_FIXTURE).decode("ascii")
        encoding = "bitmap.TIFFRepresentation" if mislabeled else "png"
        self._native(f"""
const png = $.NSData.alloc.initWithBase64EncodedStringOptions($('{fixture}'), 0);
const bitmap = $.NSBitmapImageRep.imageRepWithData(png);
const items = $.NSMutableArray.array;
const empty = $.NSPasteboardItem.alloc.init;
empty.setDataForType($.NSData.data, $('public.tiff'));
items.addObject(empty);
for (let i = 0; i < {copies}; i++) {{
    const item = $.NSPasteboardItem.alloc.init;
    item.setDataForType({encoding}, $('public.png'));
    items.addObject(item);
}}
pb.clearContents;
if (!pb.writeObjects(items)) throw new Error('Fixture write failed.');
'seeded';
""")

    def _main(self, arguments: list[str], answer: str = "n") -> tuple[int, str, str]:
        """Run the actual CLI with controlled confirmation and capture bounded output."""
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["rdp-clipboard-image-fix.py", *arguments]), \
                patch("builtins.input", return_value=answer) as prompt, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = app.main()
            if "--force" in arguments:
                prompt.assert_not_called()
        return result, output.getvalue(), errors.getvalue()

    def test_force_reencodes_mislabeled_tiff_and_removes_empty_item(self) -> None:
        """TIFF under public.png becomes a verified PNG while preserving transparency."""
        self._seed_image()
        before = app._run_backend(app.ClipboardAction.INSPECT)
        self.assertEqual(app._detect_encoding(before.formats[1].header), "TIFF")
        result, output, errors = self._main(["--force"])
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("Mismatch", output)
        self.assertIn("Header (up to 16 bytes)", output)
        after = app._run_backend(app.ClipboardAction.INSPECT)
        self.assertEqual(len(after.formats), 1)
        self.assertEqual(after.formats[0].header[:8], app.PNG_SIGNATURE)
        self.assertEqual((after.images[0].width, after.images[0].height), (1, 1))
        alpha = self._native("""
const bitmap = $.NSBitmapImageRep.imageRepWithData(pb.dataForType($('public.png')));
JSON.stringify({has_alpha: Boolean(bitmap.hasAlpha), alpha: Number(bitmap.colorAtXY(0, 0).alphaComponent)});
""")
        self.assertTrue(json.loads(alpha)["has_alpha"])
        self.assertAlmostEqual(json.loads(alpha)["alpha"], 128 / 255, delta=1 / 255)

    def test_cancel_preserves_original_revision_and_tiff_bytes(self) -> None:
        """Declining Proceed leaves every original representation untouched."""
        self._seed_image()
        before = app._run_backend(app.ClipboardAction.INSPECT)
        result, output, _ = self._main([], answer="n")
        self.assertEqual(result, 0)
        self.assertIn("Cancelled", output)
        self.assertEqual(app._run_backend(app.ClipboardAction.INSPECT), before)

    def test_yes_repairs_existing_valid_png(self) -> None:
        """Explicit confirmation also accepts already correctly encoded bitmap data."""
        self._seed_image(mislabeled=False)
        result, output, errors = self._main([], answer="yes")
        self.assertEqual((result, errors), (0, ""))
        self.assertIn("read-back verified", output)

    def test_non_image_exits_with_error_and_preserves_text(self) -> None:
        """Text clipboard data fails with or without force and is never cleared."""
        self._native("pb.clearContents; pb.setStringForType($('keep me'), $('public.utf8-plain-text')); 'seeded';")
        for arguments in ([], ["--force"]):
            result, _, errors = self._main(arguments)
            self.assertEqual(result, 1)
            self.assertIn("no readable bitmap image", errors)
        self.assertEqual(self._native("ObjC.unwrap(pb.stringForType($('public.utf8-plain-text')));"), "keep me")

    def test_changed_clipboard_is_not_overwritten_after_confirmation(self) -> None:
        """An image copied while confirmation is pending remains intact."""
        self._seed_image()
        inspected = app._run_backend(app.ClipboardAction.INSPECT)
        self._native("pb.clearContents; pb.setStringForType($('new content'), $('public.utf8-plain-text')); 'changed';")
        with self.assertRaisesRegex(RuntimeError, "Clipboard changed since inspection"):
            app._run_backend(app.ClipboardAction.REPAIR, inspected.change_count)
        self.assertEqual(self._native("ObjC.unwrap(pb.stringForType($('public.utf8-plain-text')));"), "new content")

    def test_multiple_images_are_retained(self) -> None:
        """Repair retains all readable image items instead of dropping later images."""
        self._seed_image(copies=2)
        result, _, errors = self._main(["--force"])
        self.assertEqual((result, errors), (0, ""))
        after = app._run_backend(app.ClipboardAction.INSPECT)
        self.assertEqual(len(after.images), 2)
        self.assertTrue(all(entry.header.startswith(app.PNG_SIGNATURE) for entry in after.formats))


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
