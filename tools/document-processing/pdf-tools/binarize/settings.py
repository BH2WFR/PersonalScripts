"""Immutable settings for image and vector processing."""

import dataclasses
import enum
import os
from . import regions

DEFAULT_DPI = 300
MIN_DPI = 36
MAX_DPI = 1200
DEFAULT_THRESHOLD = 180
MIN_THRESHOLD = 1
MAX_THRESHOLD = 255
GRAY_LEVELS = 256
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)
DEFAULT_SKIP_PAGES: tuple[int, ...] = (1, 2)
MAX_WORKERS = 32
PROGRESS_INTERVAL_SECONDS = 3.0
COPY_CHUNK_BYTES = 1024 * 1024
DEFAULT_SAUVOLA_WINDOW = 31
MAX_SAUVOLA_WINDOW = 501
DEFAULT_SAUVOLA_K = 0.2
SAUVOLA_R = 128.0
SAUVOLA_STRIP_ROWS = 256
DEFAULT_SHARPEN_RADIUS = 1.0
DEFAULT_SHARPEN_PERCENT = 100
SHARPEN_NOISE_THRESHOLD = 3
MAX_SHARPEN_RADIUS = 10.0
MAX_SHARPEN_PERCENT = 500
DEFAULT_BLACK_POINT = 0
DEFAULT_WHITE_POINT = GRAY_LEVELS - 1
DEFAULT_UPSCALE = 1
MAX_UPSCALE = 4
_RegionSettings = regions._Settings
_PROFILE_LABELS: dict[regions._Profile, str] = {
    regions._Profile.TEXT_FIRST: "Text first - fewer protected illustrations",
    regions._Profile.BALANCED: "Balanced protection",
    regions._Profile.IMAGE_FIRST: "Image first - more protected illustrations",
}
_IMAGE_MODE_LABELS: dict[regions._Mode, str] = {
    regions._Mode.KEEP: "Keep original colors / grayscale",
    regions._Mode.GRAY2: "2-bit grayscale (4 gray levels)",
    regions._Mode.GRAY4: "4-bit grayscale (16 gray levels)",
    regions._Mode.GRAY8: "8-bit grayscale (256 gray levels; remove color only)",
    regions._Mode.COLOR2: "2-bit color (4 palette colors)",
    regions._Mode.COLOR4: "4-bit color (16 palette colors)",
}
_CODEC_LABELS: dict[regions._Codec, str] = {
    regions._Codec.JPEG: "JPEG - smaller files, lossy",
    regions._Codec.FLATE: "Flate - lossless",
}
_DITHER_LABELS: dict[regions._Dither, str] = {
    regions._Dither.NONE: "No dithering - usually smaller files",
    regions._Dither.ORDERED: "Ordered dithering - regular dot pattern",
    regions._Dither.DIFFUSION: "Error diffusion - smoother tones, may increase size",
}


class _BinarizeMode(enum.StrEnum):
    FIXED = "fixed"
    SAUVOLA = "sauvola"


class _Action(enum.StrEnum):
    PREVIEW = "preview"
    SETTINGS = "settings"
    CONVERT = "convert"
    QUIT = "quit"


@dataclasses.dataclass(frozen=True)
class _Processing:
    """Immutable image-processing settings shared by preview and page workers."""

    mode: _BinarizeMode = _BinarizeMode.FIXED
    window: int = DEFAULT_SAUVOLA_WINDOW
    k: float = DEFAULT_SAUVOLA_K
    sharpen: bool = False
    sharpen_radius: float = DEFAULT_SHARPEN_RADIUS
    sharpen_percent: int = DEFAULT_SHARPEN_PERCENT
    levels: bool = False
    black_point: int = DEFAULT_BLACK_POINT
    white_point: int = DEFAULT_WHITE_POINT
    upscale: int = DEFAULT_UPSCALE
    vectors: bool = False
    regions: _RegionSettings = dataclasses.field(default_factory=_RegionSettings)


DEFAULT_PROCESSING = _Processing()


@dataclasses.dataclass(frozen=True)
class _OutputOptions:
    """Interactive session choices, separate from per-page image settings."""

    workers: int = DEFAULT_WORKERS
    open_preview: bool = True
    export_regions: bool = False
    annotate_regions: bool = False


def _validate_settings(dpi: int, threshold: int, workers: int, processing: _Processing) -> None:
    """Reject invalid conversion settings before rendering or creating files."""
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")
    if not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD:
        raise ValueError(f"Threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}.")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"Workers must be between 1 and {MAX_WORKERS}.")
    if not isinstance(processing.mode, _BinarizeMode):
        raise ValueError("Choose fixed or sauvola mode.")
    if not 3 <= processing.window <= MAX_SAUVOLA_WINDOW or processing.window % 2 != 1:
        raise ValueError(f"Sauvola window must be an odd integer from 3 to {MAX_SAUVOLA_WINDOW}.")
    if not 0 < processing.k <= 1:
        raise ValueError("Sauvola k must be greater than 0 and at most 1.")
    if not 0 < processing.sharpen_radius <= MAX_SHARPEN_RADIUS:
        raise ValueError(f"Sharpening radius must be greater than 0 and at most {MAX_SHARPEN_RADIUS}.")
    if not 1 <= processing.sharpen_percent <= MAX_SHARPEN_PERCENT:
        raise ValueError(f"Sharpening amount must be between 1 and {MAX_SHARPEN_PERCENT} percent.")
    if not 0 <= processing.black_point < processing.white_point < GRAY_LEVELS:
        raise ValueError("Levels must satisfy 0 <= black point < white point <= 255.")
    if not isinstance(processing.upscale, int) or not 1 <= processing.upscale <= MAX_UPSCALE:
        raise ValueError(f"Upscaling must be an integer from 1 to {MAX_UPSCALE}.")
    regions._validate(processing.regions)
    if processing.regions.clean_background and processing.mode is not _BinarizeMode.SAUVOLA:
        raise ValueError("Background cleanup requires Sauvola mode; repeat setup to change the mode or disable cleanup.")



