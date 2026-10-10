"""Display-only annotations for nonfinite and clamped matrix samples.

Requirements: numpy. Usage: shared by curve/image views and workspace snapshots.
No source arrays, validity masks or derivative inputs are modified.
MarkerStyle.size sets the 1D dot diameter; 2D retains whole-pixel annotations.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from .data_model import BoolArray, FloatArray, RealArray

DEFAULT_MARKER_SIZE = 1.5
MIN_MARKER_SIZE = 0.5
MAX_MARKER_SIZE = 20.0


class NonfiniteKind(StrEnum):
    """Nonfinite values with independent display colors."""

    POSITIVE = "Inf"
    NEGATIVE = "-Inf"
    NAN = "NaN"


@dataclass(frozen=True)
class MarkerStyle:
    """Per-channel visual flags; clipping itself remains a data-bound setting."""

    show_nonfinite: bool = False
    highlight_clipped: bool = True
    positive_color: str = "#0000ff"
    negative_color: str = "#00ff00"
    nan_color: str = "#ff00ff"
    size: float = DEFAULT_MARKER_SIZE

    def colors(self) -> tuple[tuple[NonfiniteKind, str], ...]:
        """Return annotation kinds and their opaque RGB colors in display order."""
        return ((NonfiniteKind.POSITIVE, self.positive_color),
                (NonfiniteKind.NEGATIVE, self.negative_color),
                (NonfiniteKind.NAN, self.nan_color))


def nonfinite_mask(values: RealArray, kind: NonfiniteKind) -> BoolArray:
    """Classify original real samples, independently of bounds and validity.

    Args:
        values: Real-valued signal or scalar matrix without data conversion.
        kind: Positive infinity, negative infinity, or NaN.

    Returns:
        A boolean mask with the input shape. Integer arrays contain no matches.
    """
    if kind == NonfiniteKind.POSITIVE:
        return np.isposinf(values)
    if kind == NonfiniteKind.NEGATIVE:
        return np.isneginf(values)
    return np.isnan(values)


@dataclass(frozen=True)
class MarkerSamples:
    """Original sample indices with finite annotation heights and one color."""

    kind: NonfiniteKind
    indices: NDArray[np.intp]
    heights: FloatArray
    color: str


def curve_markers(values: RealArray, shown: RealArray, valid: BoolArray,
                  style: MarkerStyle) -> tuple[MarkerSamples, ...]:
    """Locate nonfinite curve markers without changing the actual curve.

    Args:
        values: Original 1D values, used to distinguish Inf, -Inf and NaN.
        shown: Same-shape displayed values after value bounds.
        valid: Visibility mask; only finite visible values determine extrema.
        style: Flags and colors; disabled annotations return immediately.

    Returns:
        Nonempty marker groups. NaN sits at zero; infinities sit at the finite
        displayed maximum/minimum. With no finite visible samples both extrema
        fall back to zero. X coordinates are supplied by the caller, which must
        omit nonfinite X coordinates rather than inventing sample locations.

    Raises:
        ValueError: Enabled inputs are not matching 1D arrays.
    """
    if not style.show_nonfinite:
        return ()
    if values.ndim != 1 or values.shape != shown.shape or values.shape != valid.shape:
        raise ValueError("Nonfinite markers require matching 1D samples and visibility masks.")
    finite = shown[valid & np.isfinite(shown)]
    lower = float(np.min(finite)) if finite.size else 0.0
    upper = float(np.max(finite)) if finite.size else 0.0
    groups: list[MarkerSamples] = []
    for kind, color in style.colors():
        indices = np.flatnonzero(nonfinite_mask(values, kind))
        if indices.size:
            height = upper if kind == NonfiniteKind.POSITIVE else lower if kind == NonfiniteKind.NEGATIVE else 0.0
            groups.append(MarkerSamples(kind, indices, np.full(indices.size, height, dtype=np.float64), color))
    return tuple(groups)
