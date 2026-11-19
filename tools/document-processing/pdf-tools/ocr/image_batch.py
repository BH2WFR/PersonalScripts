"""Read local rasters and apply one set of recognition settings across a batch."""

from pathlib import Path
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageOps
from ..common.protocol import Json
from ..common.task_control import TaskControl, Cancelled
from .backend import Recognizer
from .model import Settings
from .preprocessing import preprocess

FORMATS = ("PNG", "JPEG", "TIFF", "BMP", "WEBP", "GIF")
SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif")


def image_rgb(path: Path, thumbnail: tuple[int, int] | None = None) -> Image.Image:
    """Read the first frame in display orientation and composite transparency over white."""
    with Image.open(path, formats=FORMATS) as source:
        if thumbnail:
            source.thumbnail(thumbnail)
        image = ImageOps.exif_transpose(source)
        if "A" in image.getbands() or "transparency" in image.info:
            rgba = image.convert("RGBA")
            paper = Image.new("RGB", image.size, "white")
            paper.paste(rgba, mask=rgba.getchannel("A"))
            return paper
        return image.convert("RGB")


def scan_images(paths: list[str], settings: Settings, engine: Recognizer,
                control: TaskControl) -> dict[str, Json]:
    """Report each result immediately so stopping or a bad file preserves completed work."""
    def recognize(path: Path) -> str:
        rgb = np.asarray(image_rgb(path))
        return engine.recognize(preprocess(rgb, settings), control.checkpoint).text

    return scan_batch(paths, recognize, control)


def scan_batch(paths: list[str], recognize: Callable[[Path], str], control: TaskControl) -> dict[str, Json]:
    """Process one image at a time with a shared local recognizer."""
    failed = 0
    for index, path in enumerate(paths, 1):
        control.checkpoint()
        message: dict[str, Json] = {"kind": "progress", "image": path, "done": index, "total": len(paths)}
        try:
            message["text"] = recognize(Path(path))
            control.checkpoint()
        except Cancelled:
            raise
        except Exception as exc:
            failed += 1
            message["error"] = str(exc)
        control.progress(message)
    return {"kind": "images-complete", "total": len(paths), "failed": failed}
