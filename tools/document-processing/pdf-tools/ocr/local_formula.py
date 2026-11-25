"""Pinned PaddleOCR formula weights and CPU inference on a single formula per image."""

from collections.abc import Callable
from importlib.util import find_spec
import json
from pathlib import Path
from dataclasses import dataclass

from . import models
from ..common.task_control import TaskControl

NAME = "LaTeX_OCR_rec"
REVISION = "26e649f3604d35e06aed24fb7d0425236459b7cd"
SOURCE = "https://www.modelscope.cn/models/PaddlePaddle/LaTeX_OCR_rec"
FILES = {
    "config.json": (76351, "61246c3a0675bf57034340f9ea8e79752ce392cc97bc1f936c20b7ba84350336"),
    "inference.json": (1234034, "9684e0125dbc0fa8a3e81a6d7db5ae32759878ea8b73bcd6ee55eba87f811650"),
    "inference.pdiparams": (102384761, "1b2b27fa532e4e687116c9e3a141e4f17420c75ab53a0ef10692b5bb797e67d2"),
    "inference.yml": (39883, "56da5be526cc56fd6a6e1eb8720e91a2b60c8f520710503de51259e983d2f3ee"),
}


def runtime_hint() -> str:
    """Describe missing optional packages without importing a native runtime in Qt."""
    missing = [package for name, package in (("paddle", "paddlepaddle"),
                                             ("tokenizers", "tokenizers")) if find_spec(name) is None]
    return ("Install the optional offline formula packages in the Python environment running Image to Text and Formula:\n"
            "python -m pip install " + " ".join(missing)) if missing else ""


def directory() -> Path:
    """Return the directory reserved for the pinned formula model."""
    return models.cache_directory() / NAME


class Asset(models.Model):
    @property
    def directory(self) -> Path:
        return directory()

    @property
    def filename(self) -> str:
        if self.key not in FILES:
            raise ValueError("Unknown formula model file.")
        return self.key


def assets() -> list[Asset]:
    return [Asset(name, name, REVISION, f"{SOURCE}/resolve/{REVISION}/{name}", digest)
            for name, (_, digest) in FILES.items()]


@dataclass(frozen=True)
class Inventory:
    """Installed bytes and completeness of the four local model files."""
    size: int
    complete: bool


def inventory() -> Inventory:
    """Read file sizes without loading Paddle or contacting the model host."""
    sizes: dict[str, int] = {}
    for asset in assets():
        path = models.model_path(asset)
        sizes[asset.key] = path.stat().st_size if path.is_file() else 0
    return Inventory(sum(sizes.values()), all(sizes[name] == size for name, (size, _) in FILES.items()))


def manage(action: str, control: TaskControl) -> None:
    """Install or verify pinned files individually so interrupted downloads can resume."""
    for asset in assets():
        control.checkpoint()
        if action == "download":
            try:
                models.verify(asset, control)
            except (FileNotFoundError, ValueError):
                models.download(asset, control)
        elif action == "verify":
            models.verify(asset, control)
        elif action == "delete":
            models.delete(asset)
        else:
            raise ValueError("Unknown formula model action.")


def recognizer(control: TaskControl, brackets: bool) -> Callable[[Path], str]:
    """Load the pinned PaddleOCR graph once and return a CPU image recognizer."""
    if hint := runtime_hint():
        raise RuntimeError(hint)
    manage("verify", control)
    import cv2
    import numpy as np
    from paddle import inference
    from PIL import Image
    from tokenizers import Tokenizer
    from .image_batch import image_rgb

    folder = directory()
    definition = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    tokenizer = Tokenizer.from_str(json.dumps(definition["PostProcess"]["character_dict"]))
    config = inference.Config(str(folder / "inference.json"), str(folder / "inference.pdiparams"))
    # The oneDNN-optimized graph mismatches residual feature-map sizes on Windows CPU.
    config.disable_gpu()
    config.disable_mkldnn()
    config.switch_ir_optim(False)
    config.disable_glog_info()
    config.set_cpu_math_library_num_threads(4)
    engine = inference.create_predictor(config)
    input_handle = engine.get_input_handle(engine.get_input_names()[0])
    output_handle = engine.get_output_handle(engine.get_output_names()[0])

    def recognize(path: Path) -> str:
        with image_rgb(path) as image:
            gray = image.convert("L")
        low, high = gray.getextrema()
        if low == high:
            return ""
        _, ink = cv2.threshold(np.asarray(gray), 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        if np.count_nonzero(ink) > ink.size // 2:
            ink = 255 - ink
            gray = Image.fromarray(255 - np.asarray(gray))
        x, y, width, height = cv2.boundingRect(ink)
        if not width or not height:
            return ""
        # This model was trained on typeset glyphs. Normalize screenshot zoom by
        # typical glyph height, excluding dots, noise and long fraction bars.
        _, _, stats, _ = cv2.connectedComponentsWithStats(ink[y:y+height, x:x+width])
        glyphs = [h for _, _, w, h, area in stats[1:] if h >= 4 and w < 4 * h and area >= 6]
        scale = min(12 / float(np.median(glyphs)) if glyphs else 1., 664 / width, 184 / height)
        crop = gray.crop((x, y, x + width, y + height))
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        crop = crop.resize((w, h), Image.Resampling.LANCZOS)
        paper = Image.new("L", (((w + 39) // 32) * 32, ((h + 39) // 32) * 32), 255)
        paper.paste(crop, (4, 4))
        # Normalization values and maximum input dimensions come from inference.yml.
        pixels = ((np.asarray(paper, dtype=np.float32) / 255 - 0.7931) / 0.1738)[None, None]
        control.checkpoint()
        input_handle.reshape(pixels.shape)
        input_handle.copy_from_cpu(pixels)
        engine.run()
        ids = output_handle.copy_to_cpu().reshape(-1).tolist()
        latex = tokenizer.decode(ids).replace(" ", "").replace("Ġ", " ").strip()
        if not latex:
            return ""
        start, end = (r"\[", r"\]") if brackets else ("$$", "$$")
        return f"{start}\n{latex}\n{end}"

    return recognize
