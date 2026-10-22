"""Private scan segmentation, denoising and layer codec for pdf-binarize.py.

Requires numpy, opencv-python, Pillow and PyMuPDF. Import through the adjacent
pdf-binarize.py entry point; this module is hidden from the script launcher.
All analysis/encoding functions are thread-local and use no MuPDF objects.
Only _assemble() touches MuPDF and must run on the caller's main thread.
Rectangles use normalized displayed-page coordinates (top-left origin).
Shaded-text cleanup uses local polarity and page-scaled stroke sizes; ambiguous
text panels are kept as original-image layers by the entry point.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import io
import json
import math
from pathlib import Path
from typing import cast
import zlib

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageEnhance
import pymupdf


_ANALYSIS_WIDTH = 1200
_INK_PERCENTILE = .1
_PAPER_PERCENTILE = 90
_INK_LIMIT = 110
_INK_GAP = 30
_PAPER_GAP = 22
_CHROMA_GAP = 24
_STROKE_CLOSE = 9
_TONE_OPEN = 5
_TONE_CLOSE = 13
_TEXTURE_CLOSE = 15
_TEXTURE_WINDOW = 41
_TEXTURE_DELTA = 10
_MIN_CANDIDATE_WIDTH = 35
_MIN_CANDIDATE_HEIGHT = 24
_MIN_CANDIDATE_AREA = 1600
_MAX_PAGE_WIDTH = .92
_MAX_PAGE_HEIGHT = .8
_DENSE_PANEL = .65
_INTERIOR_FRACTION = .035
_CHROMA_FRACTION = .05
_FRAME_MIN_SIZE = (25, 20)
_FRAME_MAX_SIZE = (220, 180)
_FRAME_INK_GAP = 35
_FRAME_COVERAGE = .65
_FRAME_MIN_AREA_RATIO = .55
_FRAME_MAX_AREA_RATIO = 2.5
_DUPLICATE_COVERAGE = .9
_PADDING = 2
_TEXTURE_MARGIN = 12
_MIN_AREA = 15000
_MIN_SIDE = 100
_MIN_TEXTURE = .075
_MIN_SPREAD = 30
_MAX_ASPECT = 5
_MAX_TEXT_FRACTION = .6
_GLYPH_MIN_WIDTH = 5
_GLYPH_MIN_HEIGHT = 8
_GLYPH_MAX_SIDE = 35
_GLYPH_MIN_AREA = 15
_GLYPH_RESIDUAL = 20
_REFERENCE_DPI = 240
_DENOISE_AREA = 4
_DENOISE_DISTANCE = 8
_GRAY_MAX = 255
_JPEG_QUALITY = 30
_MAX_JPEG_QUALITY = 95
_CONFIG_VERSION = 1
_MAX_REGIONS = 1000
_MAX_CONFIG_BYTES = 16 * 1024 * 1024
_DEFLATE_LEVEL = 9
_ANNOTATION_WIDTH = 1200
_POINTS_PER_INCH = 72
_HOLE_MEAN_LIMIT = 175
_HOLE_PAPER_GAP = 70
_PANEL_LIGHT_MIN = 200
_TABLE_EDGE_LOW = 35
_TABLE_EDGE_HIGH = 100
_TABLE_MEDIAN = 25
_TABLE_POLARITY_WINDOW = 41
_TABLE_NOISE = 12
_TABLE_STROKE = 12
_TABLE_STROKE_RATIO = .35
_TABLE_BORDER = 3
_PANEL_MIN_GLYPHS = 1
_PANEL_MIN_GLYPH_AREA = 4
_PANEL_MAX_GLYPH_SIDE = 60
_PANEL_MAX_GLYPH_EXTENT = 180
_PANEL_TEXT_FRACTION = .45
_PANEL_RELIABLE_FRACTION = .7
_PANEL_SMOOTH_FRACTION = .85
_PANEL_BACKGROUND_DELTA = 12
_PANEL_POLARITY_RATIO = 2.5
_PANEL_AMBIGUOUS_FRACTION = .15
_PANEL_FLAT_SPREAD = 25
_PANEL_MIN_COVERAGE = .45

type _Box = tuple[int, int, int, int]
type _Rect = tuple[float, float, float, float]
type _Pixels = NDArray[np.uint8]


class _Profile(StrEnum):
    TEXT_FIRST = "text-first"
    BALANCED = "balanced"
    IMAGE_FIRST = "image-first"


class _Mode(StrEnum):
    KEEP = "keep"
    GRAY2 = "gray2"
    GRAY4 = "gray4"
    COLOR2 = "color2"
    COLOR4 = "color4"
    TEXT = "text"
    TEXT_INVERT = "text-invert"


class _Dither(StrEnum):
    NONE = "none"
    ORDERED = "ordered"
    DIFFUSION = "diffusion"


class _Codec(StrEnum):
    JPEG = "jpeg"
    FLATE = "flate"


_PROFILE_THRESHOLDS: dict[_Profile, float] = {
    _Profile.TEXT_FIRST: 1.0, _Profile.BALANCED: .8, _Profile.IMAGE_FIRST: .6,
}


@dataclass(frozen=True)
class _Settings:
    """Immutable optional processing; old binary behavior remains the default."""

    enabled: bool = False
    profile: _Profile = _Profile.BALANCED
    threshold: float | None = None
    mode: _Mode = _Mode.KEEP
    dither: _Dither = _Dither.NONE
    contrast: float = 1.0
    quality: int = _JPEG_QUALITY
    codec: _Codec = _Codec.JPEG
    denoise: bool = False
    denoise_area: float = _DENOISE_AREA
    denoise_distance: float = _DENOISE_DISTANCE
    clean_background: bool = False
    input: Path | None = None
    export: Path | None = None
    preview_dir: Path | None = None

    @property
    def cutoff(self) -> float:
        return self.threshold if self.threshold is not None else _PROFILE_THRESHOLDS[self.profile]

    @property
    def active(self) -> bool:
        return self.enabled or self.input is not None or self.clean_background


@dataclass(frozen=True)
class _Region:
    """Resolved crop settings; list order is paint order (last region on top)."""

    rect: _Rect
    mode: _Mode = _Mode.KEEP
    dither: _Dither = _Dither.NONE
    contrast: float = 1.0
    quality: int = _JPEG_QUALITY
    codec: _Codec = _Codec.JPEG
    score: float | None = None


@dataclass(frozen=True)
class _Panel:
    """Shaded text candidate; uncertain panels can become original-image crops."""

    rect: _Rect
    reliable: bool
    reversed: bool


@dataclass(frozen=True)
class _Layer:
    """Compressed, immutable image payload transferred from worker to main thread."""

    box: _Box
    width: int
    height: int
    bits: int
    colorspace: str
    filter: str
    data: bytes
    predictor: bool = False


@dataclass(frozen=True)
class _Page:
    """Worker result containing a CCITT PDF base and independently encoded crops."""

    binary_pdf: bytes
    size: tuple[int, int]
    layers: tuple[_Layer, ...]
    regions: tuple[_Region, ...]
    annotation: bytes | None = None


def _validate(settings: _Settings) -> None:
    """Reject nonfinite/out-of-range values before rendering or writing files."""
    for value, kind in ((settings.profile, _Profile), (settings.mode, _Mode),
                        (settings.dither, _Dither), (settings.codec, _Codec)):
        if not isinstance(value, kind):
            raise ValueError(f"Invalid {kind.__name__}: {value}")
    if not .1 <= settings.cutoff <= 2:
        raise ValueError("Region threshold must be between 0.1 and 2 (higher = fewer boxes).")
    if not 1 <= settings.quality <= _MAX_JPEG_QUALITY:
        raise ValueError(f"Image quality must be between 1 and {_MAX_JPEG_QUALITY}; CCITT has no quality setting.")
    if not 1 <= settings.contrast <= 4:
        raise ValueError("Image contrast must be between 1 (off) and 4.")
    if not 0 < settings.denoise_area <= 100 or not 1 <= settings.denoise_distance <= 100:
        raise ValueError("Denoise area must be > 0 and <= 100; distance must be 1-100 at 240 DPI.")
    if settings.export or settings.preview_dir:
        if not settings.active:
            raise ValueError("Region export/annotations require illustration protection, shaded-text cleanup or an imported region file; repeat setup.")


def _pixel_box(rect: _Rect, size: tuple[int, int]) -> _Box:
    """Convert normalized bounds to clipped half-open pixel coordinates."""
    width, height = size
    x0, y0, x1, y1 = rect
    left, top = min(width - 1, round(x0 * width)), min(height - 1, round(y0 * height))
    return left, top, min(width, max(left + 1, round(x1 * width))), min(height, max(top + 1, round(y1 * height)))


def _analysis(image: Image.Image) -> tuple[_Pixels, _Pixels]:
    """Return fixed-width RGB/gray analysis rasters independent of export DPI."""
    with image.convert("RGB") as rgb_image:
        rgb = cv2.resize(np.asarray(rgb_image),
                         (_ANALYSIS_WIDTH, max(1, round(image.height * _ANALYSIS_WIDTH / image.width))))
    return rgb, cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _intersection(a: _Box, b: _Box) -> int:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(box: _Box) -> int:
    return (box[2] - box[0]) * (box[3] - box[1])


def _candidates(rgb: _Pixels, gray: _Pixels, *, text_panels: bool = False) -> list[_Box]:
    """Find broad interior gray/color evidence, excluding thin black connectors."""
    height, width = gray.shape
    ink = 0 if text_panels else min(_INK_LIMIT, float(np.percentile(gray, _INK_PERCENTILE)))
    paper = float(np.percentile(gray, _PAPER_PERCENTILE))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((_STROKE_CLOSE,) * 2, np.uint8))
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2)
    tone = ((background > ink + _INK_GAP) & (background < paper - _PAPER_GAP)) | (chroma > _CHROMA_GAP)
    meaningful = cv2.morphologyEx(np.uint8(tone) * _GRAY_MAX, cv2.MORPH_OPEN,
                                 np.ones((_TONE_OPEN,) * 2, np.uint8))
    close_size = _TONE_OPEN if text_panels else _TONE_CLOSE
    meaningful = cv2.morphologyEx(meaningful, cv2.MORPH_CLOSE, np.ones((close_size,) * 2, np.uint8))
    contours, _ = cv2.findContours(meaningful, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[_Box] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (w < _MIN_CANDIDATE_WIDTH or h < _MIN_CANDIDATE_HEIGHT
                or cv2.contourArea(contour) < _MIN_CANDIDATE_AREA
                or w >= width * _MAX_PAGE_WIDTH or h >= height * _MAX_PAGE_HEIGHT):
            continue
        patch = gray[y:y + h, x:x + w]
        local_ink = float(np.percentile(patch, 10))
        interior = (patch > max(ink + _INK_GAP, local_ink + _CHROMA_GAP)) & (patch < paper - _PAPER_GAP)
        interior = cv2.morphologyEx(np.uint8(interior), cv2.MORPH_OPEN, np.ones((_TONE_OPEN,) * 2, np.uint8))
        dense_panel = np.mean((patch > ink + _INK_GAP) & (patch < paper - _PAPER_GAP)) > _DENSE_PANEL
        if (dense_panel or np.mean(interior) >= _INTERIOR_FRACTION
                or np.mean(chroma[y:y + h, x:x + w] > _CHROMA_GAP) >= _CHROMA_FRACTION):
            candidates.append((x, y, x + w, y + h))

    # ── snap small patches to printed frames; never merge along arrows ──
    outlines, _ = cv2.findContours(np.uint8(gray < paper - _FRAME_INK_GAP) * _GRAY_MAX,
                                   cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    frames: list[_Box] = []
    for outline in outlines:
        x, y, w, h = cv2.boundingRect(outline)
        if (_FRAME_MIN_SIZE[0] <= w <= _FRAME_MAX_SIZE[0] and _FRAME_MIN_SIZE[1] <= h <= _FRAME_MAX_SIZE[1]
                and cv2.contourArea(outline) > _FRAME_COVERAGE * w * h):
            frames.append((x, y, x + w, y + h))
    snapped: list[_Box] = []
    for box in candidates:
        options = [frame for frame in frames if _intersection(box, frame) > _FRAME_COVERAGE * _area(box)
                   and _area(box) * _FRAME_MIN_AREA_RATIO < _area(frame) < _area(box) * _FRAME_MAX_AREA_RATIO]
        snapped.append(min(options, key=_area) if options else box)
    retained: list[_Box] = []
    for box in sorted(snapped, key=_area, reverse=True):
        if not any(_intersection(box, prior) >= _DUPLICATE_COVERAGE * _area(box) for prior in retained):
            retained.append(box)
    return [(max(0, x0 - _PADDING), max(0, y0 - _PADDING), min(width, x1 + _PADDING), min(height, y1 + _PADDING))
            for x0, y0, x1, y1 in sorted(retained, key=lambda box: (box[1], box[0]))]


def _detect(image: Image.Image, settings: _Settings) -> tuple[_Region, ...]:
    """Score interior texture, always rejecting text-dominated candidates.

    Threshold is a heuristic evidence ratio, not a probability. Lower values
    relax size/texture requirements without relaxing the text exclusion gate.
    """
    rgb, gray = _analysis(image)
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, np.ones((_TEXTURE_CLOSE,) * 2, np.uint8))
    smoothed = cv2.GaussianBlur(background.astype(np.float32), (_TEXTURE_WINDOW,) * 2, 0)
    texture = np.abs(background.astype(np.float32) - smoothed) > _TEXTURE_DELTA
    retained: list[_Region] = []
    for box in _candidates(rgb, gray):
        x0, y0, x1, y1 = box
        width, height = x1 - x0, y1 - y0
        if max(width / height, height / width) > _MAX_ASPECT:
            continue
        margin = min(_TEXTURE_MARGIN, min(width, height) // 5)
        patch = background[y0 + margin:y1 - margin, x0 + margin:x1 - margin]
        textured = float(texture[y0 + margin:y1 - margin, x0 + margin:x1 - margin].mean())
        spread = float(np.percentile(patch, 90) - np.percentile(patch, 10))
        original = gray[y0:y1, x0:x1]
        residual = cv2.absdiff(original, cv2.medianBlur(original, _TEXTURE_CLOSE)) > _GLYPH_RESIDUAL
        _, _, stats, _ = cv2.connectedComponentsWithStats(np.uint8(residual), connectivity=8)
        components = stats[1:]
        glyphs = ((components[:, 2] >= _GLYPH_MIN_WIDTH) & (components[:, 2] <= _GLYPH_MAX_SIDE)
                  & (components[:, 3] >= _GLYPH_MIN_HEIGHT) & (components[:, 3] <= _GLYPH_MAX_SIDE)
                  & (components[:, 4] >= _GLYPH_MIN_AREA))
        text_fraction = float(components[glyphs, 4].sum() / max(1, components[:, 4].sum()))
        score = min(width * height / _MIN_AREA, min(width, height) / _MIN_SIDE,
                    textured / _MIN_TEXTURE, spread / _MIN_SPREAD)
        if score >= settings.cutoff and text_fraction < _MAX_TEXT_FRACTION:
            rect = (x0 / gray.shape[1], y0 / gray.shape[0], x1 / gray.shape[1], y1 / gray.shape[0])
            retained.append(_Region(rect, settings.mode, settings.dither, settings.contrast,
                                    settings.quality, settings.codec, score))
    return tuple(retained)


def _denoise(binary: Image.Image, dpi: int, settings: _Settings) -> Image.Image:
    """Remove only isolated tiny ink components; retain nearby punctuation/strokes.

    Area and exclusion distance scale from 240 DPI. Neighbor checks use the
    original mask, so deletion cannot cascade through dots or dotted lines.
    Returns an owned 1-bit image and leaves the input unchanged.
    """
    ink = np.uint8(~np.asarray(binary.convert("1")))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    scale = dpi / _REFERENCE_DPI
    max_area = max(1, round(settings.denoise_area * scale * scale))
    distance = max(1, round(settings.denoise_distance * scale))
    max_side = max(1, math.ceil(math.sqrt(settings.denoise_area) * scale))
    remove = np.zeros(len(stats), dtype=np.bool_)
    for label in np.flatnonzero((stats[:, 4] <= max_area) & (stats[:, 2] <= max_side) & (stats[:, 3] <= max_side)):
        if label == 0:
            continue
        x, y, w, h, _ = stats[label]
        nearby = labels[max(0, y - distance):y + h + distance, max(0, x - distance):x + w + distance]
        remove[label] = not np.any((nearby != 0) & (nearby != label))
    white = (ink == 0) | remove[labels]
    return Image.fromarray(white)


def _panel_signal(gray: _Pixels, scale: float = 1.0) -> tuple[_Pixels, NDArray[np.float32], NDArray[np.float32], NDArray[np.float32]]:
    """Estimate local background and signed stroke evidence at page-scaled sizes.

    Scale is output page width / analysis width, not crop width. Median filtering
    follows smooth gradients without choosing an absolute gray-level cutoff.
    Signed evidence is pooled locally, so neighboring cells may have opposite ink.
    """
    median_size = max(3, round(_TABLE_MEDIAN * scale) | 1)
    window = max(3, round(_TABLE_POLARITY_WINDOW * scale) | 1)
    blur_size = max(3, round(3 * scale) | 1)
    cleaned = cv2.GaussianBlur(gray, (blur_size,) * 2, .6 * scale)
    background = cv2.medianBlur(cleaned, median_size)
    difference = cleaned.astype(np.float32) - background.astype(np.float32)
    bright = cv2.boxFilter(np.maximum(difference - _TABLE_NOISE, 0), -1, (window,) * 2)
    dark = cv2.boxFilter(np.maximum(-difference - _TABLE_NOISE, 0), -1, (window,) * 2)
    return background, difference, bright, dark


def _text_panels(image: Image.Image) -> tuple[_Panel, ...]:
    """Find horizontal/vertical shaded text independently of illustration scores.

    Text evidence uses small connected strokes on a locally smooth background;
    frames and large tonal boundaries are excluded from the glyph count. This is
    a conservative image heuristic, not OCR. Ambiguous shadows/embossing are marked
    for crop protection instead of being silently forced into one polarity.
    """
    rgb, gray = _analysis(image)
    panels: list[_Panel] = []
    for x0, y0, x1, y1 in _candidates(rgb, gray, text_panels=True):
        patch = gray[y0:y1, x0:x1]
        background, difference, bright, dark = _panel_signal(patch)
        support = (background > _INK_GAP) & (background < _GRAY_MAX - _PAPER_GAP)
        support = cv2.erode(np.uint8(support), np.ones((_TABLE_BORDER * 2 + 1,) * 2, np.uint8)) > 0
        support[:_TABLE_BORDER] = support[-_TABLE_BORDER:] = False
        support[:, :_TABLE_BORDER] = support[:, -_TABLE_BORDER:] = False
        if float(np.mean(support)) < _PANEL_MIN_COVERAGE:
            continue
        residual = (np.abs(difference) > _TABLE_STROKE) & support
        _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(residual), connectivity=8)
        glyphs = ((stats[:, 2] >= 2) & (stats[:, 3] >= 3)
                  & (np.minimum(stats[:, 2], stats[:, 3]) <= _PANEL_MAX_GLYPH_SIDE)
                  & (np.maximum(stats[:, 2], stats[:, 3]) <= _PANEL_MAX_GLYPH_EXTENT)
                  & (stats[:, 4] >= _PANEL_MIN_GLYPH_AREA))
        glyphs[0] = False
        text_fraction = float(stats[glyphs, 4].sum() / max(1, np.count_nonzero(residual)))
        if np.count_nonzero(glyphs) < _PANEL_MIN_GLYPHS or text_fraction < _PANEL_TEXT_FRACTION:
            continue
        # Normalize by shaded support so a panel's edge against white paper is
        # not mistaken for illustration texture (especially narrow/round labels).
        weights = cv2.GaussianBlur(support.astype(np.float32), (_TEXTURE_WINDOW,) * 2, 0)
        smooth = cv2.GaussianBlur(background.astype(np.float32) * support, (_TEXTURE_WINDOW,) * 2, 0)
        smooth /= np.maximum(weights, np.finfo(np.float32).eps)
        smooth_fraction = float(np.mean(np.abs(background.astype(np.float32) - smooth)[support] < _PANEL_BACKGROUND_DELTA))
        if smooth_fraction < _PANEL_SMOOTH_FRACTION:
            continue  # Textured illustrations remain the illustration detector's job.
        glyph_mask = glyphs[labels]
        ambiguous = np.maximum(bright, dark) < _PANEL_POLARITY_RATIO * np.minimum(bright, dark)
        reliable = (text_fraction >= _PANEL_RELIABLE_FRACTION
                    and float(np.mean(ambiguous[glyph_mask])) < _PANEL_AMBIGUOUS_FRACTION)
        tones = background[support]
        flat = float(np.percentile(tones, 90) - np.percentile(tones, 10)) < _PANEL_FLAT_SPREAD
        reversed_text = (flat and float(bright[glyph_mask].sum())
                         > _PANEL_POLARITY_RATIO * float(dark[glyph_mask].sum()))
        panels.append(_Panel((x0 / gray.shape[1], y0 / gray.shape[0],
                              x1 / gray.shape[1], y1 / gray.shape[0]), reliable, reversed_text))
    return tuple(panels)


def _text_panel(gray: _Pixels, fallback: _Pixels, scale: float = 1.0) -> _Pixels:
    """Remove gradient/mixed-polarity fills while retaining strokes and rules.

    Both bright and dark lettering becomes black on white. Outside the shaded
    support and along the crop boundary, retain the supplied binary fallback so
    circular outlines, connectors and adjacent ordinary text are not erased.
    """
    height, width = gray.shape
    original_edges = cv2.Canny(gray, _TABLE_EDGE_LOW, _TABLE_EDGE_HIGH)
    edges = cv2.dilate(original_edges, np.ones((_TONE_OPEN,) * 2, np.uint8))
    horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((1, max(_TEXTURE_CLOSE, width // 4)), np.uint8))
    vertical = cv2.morphologyEx(edges, cv2.MORPH_OPEN, np.ones((max(_TEXTURE_CLOSE, height // 2), 1), np.uint8))
    background, difference, bright, dark = _panel_signal(gray, scale)
    stroke_size = max(3, round(_STROKE_CLOSE * scale) | 1)
    local_contrast = cv2.dilate(np.abs(difference), np.ones((stroke_size,) * 2, np.uint8))
    cutoff = np.maximum(_TABLE_STROKE, local_contrast * _TABLE_STROKE_RATIO)
    ink = np.where(bright > dark, difference > cutoff, difference < -cutoff)
    long_rows = np.count_nonzero(horizontal, axis=1) > width * .6
    long_columns = np.count_nonzero(vertical, axis=0) > height * .8
    ink |= (original_edges > 0) & (long_rows[:, None] | long_columns[None, :])
    border = max(1, round(_TABLE_BORDER * scale))
    result = fallback.copy()
    support = background < _GRAY_MAX - _PAPER_GAP
    support[:border] = support[-border:] = False
    support[:, :border] = support[:, -border:] = False
    result[support] = np.uint8(~ink[support]) * _GRAY_MAX
    return result


def _clean_background(image: Image.Image, binary: Image.Image,
                      panels: tuple[_Panel, ...] | None = None) -> Image.Image:
    """Opt-in adaptive solid-fill and broad text-panel repair; return owned 1-bit.

    Flat reversed labels retain white-on-black; gradients/mixed cells use local
    polarity, including vertical labels. Uncertain panels retain the incoming
    binary pixels here; the page encoder protects them as original-image crops.
    """
    with image.convert("L") as gray_image:
        values = np.asarray(gray_image)
        white = np.asarray(binary).copy()
        _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(white), connectivity=8)
        totals = np.bincount(labels.ravel(), weights=values.ravel(), minlength=len(stats))
        means = totals / np.maximum(stats[:, cv2.CC_STAT_AREA], 1)
        enclosed = ((stats[:, 0] > 0) & (stats[:, 1] > 0)
                    & (stats[:, 0] + stats[:, 2] < image.width) & (stats[:, 1] + stats[:, 3] < image.height))
        fill = enclosed & (means < min(_HOLE_MEAN_LIMIT,
                         float(np.percentile(values, _PAPER_PERCENTILE)) - _HOLE_PAPER_GAP))
        fill[0] = False
        # Only fill near-uniform holes: a white glyph inside a gray fill must
        # not be erased merely because the entire component's mean is dark.
        bright = np.bincount(labels.ravel(), weights=(values >= _PANEL_LIGHT_MIN).ravel(), minlength=len(stats))
        fill &= bright == 0
        white[fill[labels]] = False
        base = Image.fromarray(white)
        for panel in _text_panels(image) if panels is None else panels:
            box = _pixel_box(panel.rect, image.size)
            a, b, c, d = box
            patch = values[b:d, a:c]
            if not panel.reliable:
                with binary.crop(box) as unchanged:
                    base.paste(unchanged, box)
                continue
            if panel.reversed:
                _, thresholded = cv2.threshold(patch, 0, _GRAY_MAX, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            else:
                thresholded = _text_panel(patch, np.uint8(np.asarray(binary)[b:d, a:c]) * _GRAY_MAX,
                                          image.width / _ANALYSIS_WIDTH)
            with Image.fromarray(thresholded).convert("1", dither=Image.Dither.NONE) as replacement:
                base.paste(replacement, box)
        return base


def _ordered_values(size: tuple[int, int]) -> NDArray[np.float32]:
    matrix = np.array([[0, 2], [3, 1]], dtype=np.float32)
    for _ in range(2):
        matrix = np.block([[4 * matrix, 4 * matrix + 2], [4 * matrix + 3, 4 * matrix + 1]])
    tile = (matrix + .5) / matrix.size - .5
    width, height = size
    return np.tile(tile, ((height + 7) // 8, (width + 7) // 8))[:height, :width]


def _quantize(image: Image.Image, bits: int, color: bool, dither: _Dither) -> tuple[_Pixels, bytes | None]:
    """Return indices and optional RGB palette; gray samples use uniform levels."""
    levels = 1 << bits
    with image.convert("RGB" if color else "L") as original:
        if not color and dither is not _Dither.DIFFUSION:
            values = np.asarray(original, dtype=np.float32) * ((levels - 1) / _GRAY_MAX)
            if dither is _Dither.ORDERED:
                values = values + _ordered_values(original.size)
            return np.floor(values + .5).clip(0, levels - 1).astype(np.uint8), None
        with original.convert("RGB") as rgb:
            if color:
                palette_image = rgb.quantize(colors=levels, method=Image.Quantize.MEDIANCUT,
                                             dither=Image.Dither.NONE)
                palette = bytes((palette_image.getpalette() or [])[:levels * 3])
            else:
                palette = bytes(channel for value in np.linspace(0, _GRAY_MAX, levels, dtype=np.uint8)
                                for channel in (int(value),) * 3)
                palette_image = Image.new("P", (1, 1))
            # Pad unused entries with the last valid color, not black/new colors.
            palette_image.putpalette(palette + palette[-3:] * (256 - levels))
            with palette_image:
                if dither is _Dither.ORDERED:
                    perturbed = np.asarray(rgb, dtype=np.float32) + _ordered_values(rgb.size)[:, :, None] * (_GRAY_MAX / (levels - 1))
                    prepared = Image.fromarray(np.rint(perturbed).clip(0, _GRAY_MAX).astype(np.uint8))
                else:
                    prepared = rgb.copy()
                with prepared:
                    pillow_dither = Image.Dither.FLOYDSTEINBERG if dither is _Dither.DIFFUSION else Image.Dither.NONE
                    with prepared.quantize(palette=palette_image, dither=pillow_dither) as quantized:
                        indices = np.minimum(np.asarray(quantized), levels - 1).astype(np.uint8)
                return indices, palette if color else None


def _pack(indices: _Pixels, bits: int) -> _Pixels:
    """Pack each row independently, high bits first; pad odd widths with zero."""
    count = 8 // bits
    padded = np.pad(indices, ((0, 0), (0, (-indices.shape[1]) % count)))
    packed = np.zeros((len(indices), padded.shape[1] // count), dtype=np.uint8)
    for offset in range(count):
        packed |= padded[:, offset::count] << (8 - bits * (offset + 1))
    return packed


def _deflate(rows: _Pixels) -> tuple[bytes, bool]:
    """Choose smallest raw, fixed PNG filter, or adaptive-row Deflate payload.

    All filters operate on packed bytes (one byte stride for sub-byte images).
    Trying several predictors changes compressed size, never decoded samples.
    """
    values = rows.astype(np.int16)
    left, above, diagonal = (np.zeros_like(values) for _ in range(3))
    left[:, 1:] = values[:, :-1]
    above[1:] = values[:-1]
    diagonal[1:, 1:] = values[:-1, :-1]
    estimate = left + above - diagonal
    pa, pb, pc = np.abs(estimate - left), np.abs(estimate - above), np.abs(estimate - diagonal)
    paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, above, diagonal))
    filters = [rows, (values - left).astype(np.uint8), (values - above).astype(np.uint8),
               (values - (left + above) // 2).astype(np.uint8), (values - paeth).astype(np.uint8)]
    best, predicted = zlib.compress(rows.tobytes(), _DEFLATE_LEVEL), False
    costs: list[NDArray[np.int64]] = []
    for number, residual in enumerate(filters):
        signed = residual.astype(np.int16)
        costs.append(np.minimum(signed, 256 - signed).sum(axis=1, dtype=np.int64))
        encoded = np.concatenate((np.full((len(rows), 1), number, np.uint8), residual), axis=1)
        compressed = zlib.compress(encoded.tobytes(), _DEFLATE_LEVEL)
        if len(compressed) < len(best):
            best, predicted = compressed, True
    choices = np.argmin(np.stack(costs), axis=0).astype(np.uint8)
    adaptive = np.stack(filters)[choices, np.arange(len(rows))]
    encoded = np.concatenate((choices[:, None], adaptive), axis=1)
    compressed = zlib.compress(encoded.tobytes(), _DEFLATE_LEVEL)
    return (compressed, True) if len(compressed) < len(best) else (best, predicted)


def _encode_crop(crop: Image.Image, box: _Box, region: _Region) -> _Layer:
    """Encode one crop without touching PDF APIs; never JPEG-encode reduced bits."""
    rgb = np.asarray(crop.convert("RGB"))
    gray = np.array_equal(rgb[:, :, 0], rgb[:, :, 1]) and np.array_equal(rgb[:, :, 0], rgb[:, :, 2])
    prepared = crop.convert("L" if gray else "RGB")
    try:
        if region.contrast != 1:
            enhanced = ImageEnhance.Contrast(prepared).enhance(region.contrast)
            prepared.close()
            prepared = enhanced
        if region.mode is _Mode.KEEP:
            colorspace = "/DeviceGray" if gray else "/DeviceRGB"
            if region.codec is _Codec.JPEG:
                with io.BytesIO() as stream:
                    prepared.save(stream, "JPEG", quality=region.quality, optimize=True, subsampling=0)
                    return _Layer(box, crop.width, crop.height, 8, colorspace, "/DCTDecode", stream.getvalue())
            return _Layer(box, crop.width, crop.height, 8, colorspace, "/FlateDecode",
                          zlib.compress(prepared.tobytes(), _DEFLATE_LEVEL))
        if region.mode in (_Mode.TEXT, _Mode.TEXT_INVERT):
            with prepared.convert("L") as gray_image:
                values = np.asarray(gray_image)
                if region.mode is _Mode.TEXT_INVERT:
                    values = _GRAY_MAX - values
                thresholded = _text_panel(values, np.full_like(values, _GRAY_MAX))
                with Image.fromarray(thresholded).convert("1", dither=Image.Dither.NONE) as binary, io.BytesIO() as stream:
                    binary.save(stream, "PDF", resolution=_POINTS_PER_INCH)
                    return _Layer(box, crop.width, crop.height, 1, "/DeviceGray", "pdf", stream.getvalue())
        bits = 2 if region.mode in (_Mode.GRAY2, _Mode.COLOR2) else 4
        indices, palette = _quantize(prepared, bits, region.mode in (_Mode.COLOR2, _Mode.COLOR4), region.dither)
        colorspace = "/DeviceGray" if palette is None else f"[/Indexed /DeviceRGB {(1 << bits) - 1} <{palette.hex()}>]"
        data, predictor = _deflate(_pack(indices, bits))
        return _Layer(box, crop.width, crop.height, bits, colorspace, "/FlateDecode", data, predictor)
    finally:
        prepared.close()


def _annotation(image: Image.Image, regions: tuple[_Region, ...]) -> bytes:
    """Encode a small numbered PNG for reviewing bounds; never alter PDF pixels."""
    with image.convert("RGB") as marked:
        marked.thumbnail((_ANNOTATION_WIDTH, _ANNOTATION_WIDTH * 3))
        draw = ImageDraw.Draw(marked)
        for number, region in enumerate(regions, 1):
            box = _pixel_box(region.rect, marked.size)
            draw.rectangle(box, outline="red", width=2)
            draw.text((box[0] + 2, box[1] + 2), f"{number}: {region.mode.value}", fill="red", stroke_width=1, stroke_fill="white")
        with io.BytesIO() as stream:
            marked.save(stream, "PNG")
            return stream.getvalue()


def _assemble(encoded: _Page) -> bytes:
    """Assemble compressed layers on the main thread; retain actual PDF bit depth."""
    with pymupdf.open(stream=encoded.binary_pdf, filetype="pdf") as document:
        page = document[0]
        for layer in encoded.layers:
            x0, y0, x1, y1 = layer.box
            rect = pymupdf.Rect(x0 / encoded.size[0] * page.rect.width, y0 / encoded.size[1] * page.rect.height,
                               x1 / encoded.size[0] * page.rect.width, y1 / encoded.size[1] * page.rect.height)
            if layer.filter == "pdf":
                with pymupdf.open(stream=layer.data, filetype="pdf") as text_pdf:
                    page.show_pdf_page(rect, text_pdf, 0, keep_proportion=False)
                continue
            # A fresh xref avoids image-cache aliasing when equal-sized crops
            # share pixels. Insert that xref only after installing its stream.
            xref = document.get_new_xref()
            document.update_object(xref, f"<< /Type /XObject /Subtype /Image /Width {layer.width} /Height {layer.height} "
                                   f"/BitsPerComponent {layer.bits} /ColorSpace {layer.colorspace} /Interpolate false >>")
            document.update_stream(xref, layer.data, compress=False)
            document.xref_set_key(xref, "Filter", layer.filter)
            if layer.predictor:
                document.xref_set_key(xref, "DecodeParms",
                    f"<< /Predictor 15 /Colors 1 /BitsPerComponent {layer.bits} /Columns {layer.width} >>")
            page.insert_image(rect, xref=xref, keep_proportion=False)
        return document.tobytes(garbage=4, deflate=True)


def _identity(source: Path) -> str:
    with source.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_config(path: Path | None, source: Path, page_count: int, settings: _Settings) -> dict[int, tuple[_Region, ...]]:
    """Read source-bound overrides; listed pages replace detection, [] disables it.

    Optional page defaults apply before individual region overrides. Unknown
    fields, invalid types/bounds, source mismatches and oversized files fail
    before any rendering. Absent pages use current automatic settings.
    """
    if path is None:
        return {}
    if path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("Region configuration exceeds 16 MiB.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) - {"version", "sha256", "page_count", "pages"}
            or data.get("version") != _CONFIG_VERSION or data.get("sha256") != _identity(source)
            or data.get("page_count") != page_count or not isinstance(data.get("pages"), dict)):
        raise ValueError("Invalid region configuration or source SHA-256/page-count mismatch.")
    result: dict[int, tuple[_Region, ...]] = {}
    fields = {"mode", "dither", "contrast", "quality", "codec"}
    for page_key, page_value in data["pages"].items():
        if not isinstance(page_key, str) or not page_key.isdecimal() or str(int(page_key)) != page_key or not 1 <= int(page_key) <= page_count:
            raise ValueError(f"Invalid physical page number: {page_key}")
        defaults: dict[str, object] = {}
        if isinstance(page_value, dict):
            if set(page_value) - {"defaults", "regions"} or not isinstance(page_value.get("defaults", {}), dict):
                raise ValueError(f"Invalid page configuration: {page_key}")
            defaults = page_value.get("defaults", {})
            page_value = page_value.get("regions")
        if set(defaults) - fields or not isinstance(page_value, list) or len(page_value) > _MAX_REGIONS:
            raise ValueError(f"Invalid regions/defaults on page {page_key}.")
        resolved: list[_Region] = []
        for item in page_value:
            if not isinstance(item, dict) or set(item) - (fields | {"rect", "score"}):
                raise ValueError(f"Invalid region on page {page_key}.")
            bounds = item.get("rect")
            if (not isinstance(bounds, list) or len(bounds) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in bounds)
                    or not (0 <= bounds[0] < bounds[2] <= 1 and 0 <= bounds[1] < bounds[3] <= 1)):
                raise ValueError(f"Region bounds must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 (page {page_key}).")
            values = defaults | item
            try:
                quality = values.get("quality", settings.quality)
                contrast = values.get("contrast", settings.contrast)
                if type(quality) is not int or type(contrast) not in (int, float):
                    raise ValueError("Quality must be an integer and contrast a number.")
                current = replace(settings, mode=_Mode(values.get("mode", settings.mode)),
                    dither=_Dither(values.get("dither", settings.dither)), codec=_Codec(values.get("codec", settings.codec)),
                    quality=quality, contrast=float(contrast))
                _validate(current)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid region settings on page {page_key}: {exc}") from exc
            resolved.append(_Region(cast(_Rect, tuple(float(v) for v in bounds)), current.mode,
                                    current.dither, current.contrast, current.quality, current.codec))
        result[int(page_key) - 1] = tuple(resolved)
    return result


def _write_config(path: Path, source: Path, page_count: int, pages: dict[int, tuple[_Region, ...]]) -> None:
    """Exclusively create source-bound resolved overrides; never overwrite files."""
    data = {"version": _CONFIG_VERSION, "sha256": _identity(source), "page_count": page_count,
            "pages": {str(index + 1): [{"rect": region.rect, "mode": region.mode.value,
                "dither": region.dither.value, "contrast": region.contrast, "quality": region.quality,
                "codec": region.codec.value, "score": region.score} for region in regions]
                for index, regions in sorted(pages.items())}}
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")
