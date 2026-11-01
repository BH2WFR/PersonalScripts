"""Merge explicitly selected scalar matrices into an owned 8-bit image.

Requirements: NumPy and existing matrix/channel extraction. No new dependencies.
Usage: ImageMergeDialog prepares selected channels once in a worker, previews
sampled pixels, then generates full-resolution RGB, RGBA or monochrome-alpha.
Source crop, value bounds and visual alignment are ignored. Shapes must match;
pixel indices define registration. Mapping precedes gain and final clipping.
Auto ranges use either each channel's finite extrema or the union of assigned
output sources, including alpha; unused candidates and constants are excluded.
NaN/-Inf map to zero, +Inf to full intensity (also for alpha); source data stays
unchanged. Generated images use the same ImageSource as decoded image files.
"""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import cast

import numpy as np

from .complex_merge import MergeInput
from .data_model import (Array, ColorArray, Crop, Document, ImageMember, ImageSource, RealArray,
                         ViewMode, select_image_member)
from .fourier import TransformOptions, TransformResult, transform_input
from .image_metadata import ImageMetadata

PREVIEW_EDGE = 512
RANGE_BUFFER_SIZE = 65536


class ImageMergeMode(StrEnum):
    """PNG pixel layouts; alpha is straight, not premultiplied."""

    RGB = "RGB"
    RGBA = "RGBA"
    MA = "Monochrome + alpha"

    @property
    def channels(self) -> tuple[ImageMember, ...]:
        """Return ordered stored pixel components."""
        if self == ImageMergeMode.MA:
            return ImageMember.MONO, ImageMember.ALPHA
        rgb = (ImageMember.RED, ImageMember.GREEN, ImageMember.BLUE)
        return rgb + (ImageMember.ALPHA,) if self == ImageMergeMode.RGBA else rgb


class ImageMapping(StrEnum):
    """Channel range presets, independent of white-balance gain."""

    BYTE = "0 .. 255"
    UNIT = "0 .. 1"
    AUTO = "Auto: current channel"
    AUTO_SHARED = "Auto: all assigned channels"
    MANUAL = "Manual range"


@dataclass(frozen=True)
class PreparedImages:
    """Full scalar channel snapshots and cached finite extrema."""

    sources: tuple[MergeInput, ...]
    values: tuple[RealArray, ...]
    ranges: tuple[tuple[float, float] | None, ...]
    shape: tuple[int, int]


@dataclass(frozen=True)
class ImageChannel:
    """One output channel: source index (-1 for constant), mapping and gain."""

    source: int
    gain: float = 1.0
    mapping: ImageMapping = ImageMapping.BYTE
    lower: float = 0.0
    upper: float = 255.0
    constant: int = 0
    range_source: int | None = None


def prepare_images(sources: tuple[MergeInput, ...]) -> PreparedImages:
    """Resolve selected numeric channels once, rejecting unequal/empty shapes.

    Args:
        sources: Only explicitly selected tree rows (or parent channels).

    Returns:
        Read-only source views or derived channels and their finite ranges.

    Raises:
        ValueError: A candidate is not a scalar 2D matrix or shapes differ.
    """
    if not sources:
        raise ValueError("Select 2D matrices or numeric channels in the matrix tree first.")
    values: list[RealArray] = []
    ranges: list[tuple[float, float] | None] = []
    shape: tuple[int, int] | None = None
    for source in sources:
        if source.selection.mode != ViewMode.MATRIX or source.document.is_text:
            raise ValueError(f"{source.label}: image merge requires a numeric 2D matrix.")
        data = transform_input(source.document, source.selection, Crop(),
            TransformOptions(display_component=True, image_key=source.image_key)).values
        if data.ndim != 2 or not data.size or np.iscomplexobj(data):
            raise ValueError(f"{source.label}: choose a nonempty real-valued 2D channel.")
        current = (data.shape[0], data.shape[1])
        if shape is not None and shape != current:
            raise ValueError(f"Selected channels must have identical dimensions: {shape} versus {current} ({source.label}).")
        shape = current
        real = cast(RealArray, data)
        values.append(real)
        # Bounded buffers avoid a full-sized mask/copy for extrema.
        low, high = math.inf, -math.inf
        for chunk in np.nditer(real, flags=["external_loop", "buffered"],
                               op_flags=["readonly"], buffersize=RANGE_BUFFER_SIZE):
            finite = chunk[np.isfinite(chunk)]
            if finite.size:
                low, high = min(low, float(finite.min())), max(high, float(finite.max()))
        ranges.append((low, high) if math.isfinite(low) else None)
    assert shape is not None
    return PreparedImages(sources, tuple(values), tuple(ranges), shape)


def channel_limits(prepared: PreparedImages, channel: ImageChannel,
                   channels: tuple[ImageChannel, ...] = ()) -> tuple[float, float]:
    """Resolve cached finite bounds before gain; shared auto uses assigned sources.

    Args:
        prepared: Source values and cached finite ranges; None means no finite values.
        channel: Channel whose mapping is being resolved. For current-channel
            auto, range_source optionally selects a linked leader's source;
            -1 represents the constant black leader used by RGB/MA layouts.
        channels: All output assignments, required for shared auto (including alpha).
            Constants and unused candidates do not contribute.

    Returns:
        Input limits, or (0, 0) when automatic inputs have no finite values.

    Raises:
        ValueError: Manual limits or shared-auto source assignments are invalid.
    """
    if channel.mapping == ImageMapping.AUTO:
        source = channel.source if channel.range_source is None else channel.range_source
        if source == -1:
            return 0.0, 0.0
        if not 0 <= source < len(prepared.ranges):
            raise ValueError("Choose a valid source for the automatic input range.")
        return prepared.ranges[source] or (0.0, 0.0)
    if channel.mapping == ImageMapping.AUTO_SHARED:
        if not channels or any(item.source < -1 or item.source >= len(prepared.ranges) for item in channels):
            raise ValueError("Shared auto range requires valid output channel assignments.")
        ranges = [prepared.ranges[index] for index in {item.source for item in channels if item.source >= 0}]
        finite_ranges = [limits for limits in ranges if limits is not None]
        return ((min(low for low, _ in finite_ranges), max(high for _, high in finite_ranges))
                if finite_ranges else (0.0, 0.0))
    if channel.mapping == ImageMapping.UNIT:
        return 0.0, 1.0
    if channel.mapping == ImageMapping.BYTE:
        return 0.0, 255.0
    if not all(math.isfinite(value) for value in (channel.lower, channel.upper)) or channel.lower >= channel.upper:
        raise ValueError("Manual range minimum must be finite and smaller than maximum.")
    return channel.lower, channel.upper


def merge_pixels(prepared: PreparedImages, mode: ImageMergeMode,
                 channels: tuple[ImageChannel, ...], *, preview: bool = False) -> ColorArray:
    """Apply range -> gain -> clip -> round to 8-bit, without source changes.

    Args:
        prepared: Validated equally shaped source channels.
        mode: Output component layout.
        channels: One assignment for each output component, in stored order.
        preview: Sample a bounded preview grid instead of all pixels.

    Returns:
        Owned H-by-W-by-C uint8 pixels (RGB, RGBA or MA).

    Raises:
        ValueError: Invalid assignment, gain or range.
    """
    if len(channels) != len(mode.channels):
        raise ValueError("Assign every output channel.")
    stride = max(1, math.ceil(max(prepared.shape) / PREVIEW_EDGE)) if preview else 1
    height, width = ((size + stride - 1) // stride for size in prepared.shape)
    pixels = np.empty((height, width, len(channels)), dtype=np.uint8)
    for index, channel in enumerate(channels):
        if not math.isfinite(channel.gain) or channel.gain < 0:
            raise ValueError("Channel gain must be finite and nonnegative.")
        if channel.source == -1:
            pixels[..., index] = round(min(255.0, max(0.0, channel.constant * channel.gain)))
            continue
        if not 0 <= channel.source < len(prepared.values):
            raise ValueError("Choose a source from the selected candidates.")
        low, high = channel_limits(prepared, channel, channels)
        data = prepared.values[channel.source][::stride, ::stride]
        # Normalize in scaled coordinates if high-low overflows float64.
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            if high == low:
                unit = np.zeros(data.shape, dtype=np.float64)
            elif math.isfinite(high - low):
                unit = (np.asarray(data, dtype=np.float64) - low) / (high - low)
            else:
                scale = max(abs(low), abs(high))
                unit = (np.asarray(data, dtype=np.float64) / scale - low / scale) / (high / scale - low / scale)
            unit *= channel.gain
        # Undefined source samples have deterministic output, independent of
        # the chosen range. Alpha is not multiplied into stored RGB/M pixels.
        unit = np.nan_to_num(unit, nan=0.0, posinf=1.0, neginf=0.0)
        unit[np.isposinf(data)] = 1.0
        unit[np.isnan(data) | np.isneginf(data)] = 0.0
        pixels[..., index] = np.rint(np.clip(unit, 0, 1) * 255).astype(np.uint8)
    return pixels


def generate_image(prepared: PreparedImages, mode: ImageMergeMode,
                   channels: tuple[ImageChannel, ...], name: str) -> TransformResult:
    """Create an in-memory image document with native and fusion subchannels.

    The result can be displayed or saved as PNG with its straight alpha intact.
    Original source arrays and files are unchanged; no file is written here.
    """
    pixels = merge_pixels(prepared, mode, channels)
    source = ImageSource(cast(RealArray, pixels), mode.channels,
                        ImageMetadata("Generated image", "LA" if mode == ImageMergeMode.MA else mode.value,
                                      "8-bit per channel", mode == ImageMergeMode.MA))
    details = [f"Image merge: {mode.value}; full channels, pixel-index alignment; range -> gain -> clip."]
    for component, channel in zip(mode.channels, channels, strict=True):
        label = prepared.sources[channel.source].label if channel.source >= 0 else f"constant {channel.constant}"
        limits = channel_limits(prepared, channel, channels) if channel.source >= 0 else (0.0, 255.0)
        details.append(f"{component.value}: {label}; range={limits}; gain={channel.gain:g}")
    provenance = "\n".join(details)
    document = Document(prepared.sources[0].document.path, cast(Array, pixels), source.keys,
                        is_image=True, image_source=source, conversion_provenance=provenance)
    key = ImageMember.RGB_COLOR if mode == ImageMergeMode.RGB else ImageMember.RGBA_COLOR
    document = select_image_member(document, key.value)
    print(f"[Image merge] {provenance}\nOutput: {pixels.shape}, uint8", flush=True)
    return TransformResult(document, name.strip() or f"Image merge · {mode.value}")
