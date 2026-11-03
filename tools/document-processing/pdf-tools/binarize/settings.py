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


class _BinarizeMode(enum.StrEnum):
    FIXED = "fixed"
    SAUVOLA = "sauvola"


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



