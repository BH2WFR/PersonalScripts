"""Validated OCR settings and normalized, serializable recognition results."""

from dataclasses import asdict, dataclass, replace
import math
from typing import Any

from .models import EXTENSIONS

LANGUAGES = ("chinese", "english", "japanese", *EXTENSIONS)
LANGUAGE_LABELS = {"chinese": "Chinese", "english": "English", "japanese": "Japanese",
                   **{key: title for key, (title, _) in EXTENSIONS.items()}}


@dataclass(frozen=True)
class Settings:
    """Recognition settings; preview appearance and ignored pages are independent."""

    languages: tuple[str, ...] = ("chinese", "english")
    dpi: int = 300
    side: int = 1600
    threads: int = 4
    threshold: float = .3
    box_threshold: float = .4
    unclip: float = 1.6
    score: float = .1
    angle: bool = True
    tiled: bool = False
    tile_size: int = 1600
    tile_overlap: int = 20
    english_characters: bool = False
    margin_x: float = 0.
    margin_y: float = 0.
    grayscale: bool = False
    contrast: str = "off"
    contrast_clip: float = 2.
    denoise: str = "off"

    def __post_init__(self) -> None:
        if (not isinstance(self.languages, tuple) or not self.languages
                or any(language not in LANGUAGES for language in self.languages)
                or len(set(self.languages)) != len(self.languages)):
            raise ValueError("Select at least one supported recognition language, without duplicates.")
        object.__setattr__(self, "languages", tuple(language for language in LANGUAGES if language in self.languages))
        for name, low, high in (("dpi", 72, 600), ("side", 320, 4096), ("threads", 1, 32),
                                ("tile_size", 512, 4096), ("tile_overlap", 10, 50)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}.")
        for name, low, high in (("threshold", .01, .99), ("box_threshold", .01, .99),
                                ("unclip", 1., 3.), ("score", 0., 1.),
                                ("margin_x", -40., 50.), ("margin_y", -40., 50.), ("contrast_clip", 1., 8.)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be from {low} to {high}.")
        for name in ("angle", "tiled", "english_characters", "grayscale"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean.")
        if self.contrast not in ("off", "auto", "local") or self.denoise not in ("off", "median", "bilateral"):
            raise ValueError("Unknown preprocessing mode.")

    def for_recognition(self) -> "Settings":
        """Exclude output-only margins from inference/cache comparisons."""
        return replace(self, margin_x=0., margin_y=0.)

    def to_data(self) -> dict[str, Any]:
        """Return settings suitable for preferences and the worker protocol."""
        return {**asdict(self), "languages": list(self.languages)}

    def recognition_models(self) -> tuple[str, ...]:
        """Select only the shared and extension pipelines requested by the language list."""
        extensions = tuple(key for key in EXTENSIONS if key in self.languages)
        cjk = bool({"chinese", "japanese"}.intersection(self.languages)) or not extensions
        # Preserve Korean/English's single-model behavior. Other scripts keep an
        # English pipeline when explicitly selected rather than assuming coverage.
        cjk |= "english" in self.languages and extensions != ("korean",)
        return (("cjk",) if cjk else ()) + extensions

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "Settings":
        """Validate settings, rejecting unknown keys instead of silently ignoring them."""
        values = dict(data)
        legacy = values.pop("language", None)
        if "languages" not in values and legacy is not None:
            presets = {"cjk": ("chinese", "english"), "korean": ("english", "korean"), "mixed": ("chinese", "english", "japanese", "korean")}
            if not isinstance(legacy, str) or legacy not in presets:
                raise ValueError("Unknown recognition language.")
            values["languages"] = presets[legacy]
        if "languages" in values:
            if not isinstance(values["languages"], (list, tuple)):
                raise ValueError("Recognition languages must be a list.")
            values["languages"] = tuple(values["languages"])
        return cls(**values)


@dataclass(frozen=True)
class Token:
    """Recognized word/character, with TL/TR/BR/BL corners in rotated-page fractions."""

    text: str
    quad: tuple[tuple[float, float], ...]
    score: float


@dataclass(frozen=True)
class Result:
    """Text and anchors only; never retains page pixels or inference tensors."""

    text: str
    tokens: tuple[Token, ...]
    line_lengths: tuple[int, ...] = ()

    def to_data(self) -> dict[str, Any]:
        """Return a JSON-safe page result."""
        return asdict(self)

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "Result":
        """Reconstruct a result received from the local worker."""
        return cls(str(data["text"]), tuple(Token(str(t["text"]),
            tuple((float(x), float(y)) for x, y in t["quad"]), float(t["score"])) for t in data["tokens"]),
            tuple(int(length) for length in data.get("line_lengths", ())))


def adjusted_result(result: Result, settings: Settings) -> Result:
    """Expand each anchor along its own axes; percentages apply to each side.

    Positive margins enlarge anchors; negative margins shrink them. Cached OCR
    geometry stays unchanged, and the same adjustment serves previews and export.
    """
    if settings.margin_x == 0 and settings.margin_y == 0:
        return result
    tokens: list[Token] = []
    for token in result.tokens:
        p0, p1, p2, p3 = token.quad
        u = tuple((p1[i] - p0[i] + p2[i] - p3[i]) * settings.margin_x / 200 for i in range(2))
        v = tuple((p3[i] - p0[i] + p2[i] - p1[i]) * settings.margin_y / 200 for i in range(2))
        quad = tuple((p[0] + sx * u[0] + sy * v[0], p[1] + sx * u[1] + sy * v[1])
                     for p, sx, sy in ((p0, -1, -1), (p1, 1, -1), (p2, 1, 1), (p3, -1, 1)))
        tokens.append(replace(token, quad=quad))
    return replace(result, tokens=tuple(tokens))
