"""Verified local PaddleOCR ONNX models; downloads are explicit manager operations."""

from collections.abc import Callable
from typing import Any

import numpy as np
from ..common.task_control import TaskControl
from .models import EXTENSIONS, cache_directory, catalog, verify
from .model import Result, Settings, Token
from .tiling import recognize_tiled


class Recognizer:
    """Own at most the active preset's models; return anchors without retaining pixels."""

    def __init__(self, settings: Settings, checkpoint: Callable[[], None] = lambda: None) -> None:
        from rapidocr import RapidOCR, ModelType, OCRVersion

        self.settings = settings
        registry = catalog()
        control = TaskControl()
        control.checkpoint = checkpoint
        # RapidOCR constructs the classifier even when angle inference is off.
        # Always provide its local path so initialization never downloads it.
        keys = ["detector", "classifier", *settings.recognition_models()]
        paths = {key: verify(registry[key], control) for key in keys}
        params: dict[str, Any] = {
            "Global.model_root_dir": str(cache_directory()),
            "Global.log_level": "warning", "Global.text_score": settings.score,
            "Global.max_side_len": 6000, "Global.use_cls": settings.angle,
            "Global.return_word_box": True,
            "Global.return_single_char_box": settings.english_characters,
            "Det.ocr_version": OCRVersion.PPOCRV6, "Det.model_type": ModelType.SMALL,
            "Rec.ocr_version": OCRVersion.PPOCRV6, "Rec.model_type": ModelType.SMALL,
            "Det.limit_type": "max", "Det.limit_side_len": settings.side,
            "Det.thresh": settings.threshold, "Det.box_thresh": settings.box_threshold,
            "Det.unclip_ratio": settings.unclip,
            "EngineConfig.onnxruntime.intra_op_num_threads": settings.threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
        params["Det.model_path"] = str(paths["detector"])
        params["Cls.model_path"] = str(paths["classifier"])
        self.engines: list[Any] = []
        for language in settings.recognition_models():
            current = dict(params)
            current["Rec.model_path"] = str(paths[language])
            if language in EXTENSIONS:
                current.update({"Rec.lang_type": EXTENSIONS[language][1], "Rec.model_type": ModelType.MOBILE,
                                "Rec.ocr_version": OCRVersion.PPOCRV5})
            self.engines.append(RapidOCR(params=current))

    def recognize(self, rgb: np.ndarray, checkpoint: Callable[[], None]) -> Result:
        """Run a whole page or overlapping tiles using the same model instances."""
        if self.settings.tiled:
            return recognize_tiled(rgb, self.settings, self._recognize_region, checkpoint)
        return self._recognize_region(rgb, checkpoint)

    def _recognize_region(self, rgb: np.ndarray, checkpoint: Callable[[], None]) -> Result:
        """Recognize CJK/English, Korean/English, or merge competing mixed-language lines."""
        height, width = rgb.shape[:2]
        lines: list[tuple[str, float, np.ndarray, tuple[Token, ...]]] = []
        for engine_index, engine in enumerate(self.engines):
            prior_count = len(lines)
            checkpoint()
            output = engine(np.ascontiguousarray(rgb[:, :, ::-1]))  # RapidOCR ndarray input is BGR.
            checkpoint()
            if output.txts is None or output.boxes is None:
                continue
            for index, (text, score, box) in enumerate(zip(output.txts, output.scores, output.boxes)):
                words = output.word_results[index] if output.word_results and index < len(output.word_results) else None
                if not isinstance(words, (list, tuple)) or not words or not isinstance(words[0], (list, tuple)) or len(words[0]) != 3:
                    words = [(text, score, box)]
                tokens = tuple(Token(str(word), tuple((float(x) / width, float(y) / height) for x, y in quad),
                                     float(conf)) for word, conf, quad in words if quad is not None and str(word).strip())
                candidate = (str(text), float(score), np.asarray(box), tokens)
                # Both models use the same detector. Resolve overlapping lines once;
                # confidence is a heuristic, not calibrated across languages.
                overlapping = next((i for i, old in enumerate(lines[:prior_count])
                                    if _overlap(old[2], candidate[2]) > .5), None) if engine_index else None
                if overlapping is None:
                    lines.append(candidate)
                elif candidate[1] > lines[overlapping][1]:
                    lines[overlapping] = candidate
        lines.sort(key=lambda line: (round(float(line[2][:, 1].min()) / 12), float(line[2][:, 0].min())))
        return Result("\n".join(line[0] for line in lines), tuple(token for line in lines for token in line[3]),
                      tuple(len(line[3]) for line in lines))


def _overlap(first: np.ndarray, second: np.ndarray) -> float:
    """Return intersection over the smaller bounding rectangle for duplicate lines."""
    low = np.maximum(first.min(axis=0), second.min(axis=0))
    high = np.minimum(first.max(axis=0), second.max(axis=0))
    area = float(np.prod(np.maximum(0, high - low)))
    smaller = min(float(np.prod(np.ptp(first, axis=0))), float(np.prod(np.ptp(second, axis=0))))
    return area / smaller if smaller > 0 else 0.
