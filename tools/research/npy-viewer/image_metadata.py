"""Read image header metadata separately from decoded numeric pixel storage.

Requirements: Pillow. Usage: read_image_metadata(path) before exposing channels.
PNG/TIFF depths come from file fields, including sub-byte PNG and 16-bit RGB.
"""

from dataclasses import dataclass
from pathlib import Path
import struct

from PIL import Image, UnidentifiedImageError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TIFF_BITS_PER_SAMPLE = 258
GRAYSCALE_MODES = frozenset({"1", "L", "LA", "I", "F", "I;16", "I;16L", "I;16B"})
PNG_COLOR_MODES: dict[int, str] = {0: "L", 2: "RGB", 3: "P", 4: "LA", 6: "RGBA"}


@dataclass(frozen=True)
class ImageMetadata:
    """Original file format, color mode and stored depth, independent of dtype."""

    format: str
    mode: str
    depth: str
    grayscale: bool


def read_image_metadata(path: Path) -> ImageMetadata:
    """Inspect headers without loading a second full-resolution pixel buffer.

    Args:
        path: Image file already accepted by the numeric image decoder.

    Returns:
        File metadata. Unsupported headers explicitly report unavailable fields;
        the viewer separately reports the decoder's channel layout and dtype.

    Raises:
        OSError: The source bytes cannot be read.
    """
    with path.open("rb") as stream:
        header = stream.read(32)
    try:
        with Image.open(path) as source:
            mode = source.mode
            depth = "Unavailable"
            if header.startswith(PNG_SIGNATURE) and len(header) >= 26 and header[12:16] == b"IHDR":
                mode = PNG_COLOR_MODES.get(header[25], mode)
                if mode == "L" and header[24] == 1:
                    mode = "1"
                unit = "palette indices" if header[25] == 3 else "per channel"
                depth = f"{header[24]}-bit {unit}"
            elif source.format == "TIFF":
                raw: object = source.getexif().get(TIFF_BITS_PER_SAMPLE, 1)
                bits = (raw,) if isinstance(raw, int) else tuple(raw) if isinstance(raw, (tuple, list)) else ()
                if bits and all(isinstance(bit, int) for bit in bits):
                    text = str(bits[0]) if len(set(bits)) == 1 else "/".join(str(bit) for bit in bits)
                    depth = f"{text}-bit per channel"
            elif header.startswith(b"BM") and len(header) >= 30:
                dib_size = struct.unpack_from("<I", header, 14)[0]
                offset = 24 if dib_size == 12 else 28
                depth = f"{struct.unpack_from('<H', header, offset)[0]}-bit per pixel"
            elif source.format in ("JPEG", "WEBP"):
                depth = "8-bit per channel"
            return ImageMetadata(source.format or path.suffix[1:].upper(), mode, depth,
                                 mode in GRAYSCALE_MODES)
    except (UnidentifiedImageError, OSError, ValueError):
        return ImageMetadata(path.suffix[1:].upper(), "Unavailable", "Unavailable", False)
