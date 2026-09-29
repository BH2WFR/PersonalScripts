"""Piecewise-linear profile clipping with explicit horizontal cap segments.

Requirements: numpy. Usage: build display geometry from untouched source values.
"""

from dataclasses import dataclass

import numpy as np

from .data_model import BoolArray, FilterMode, FloatArray, Limits, RealArray


@dataclass(frozen=True)
class ClippedCurve:
    """Display polyline and separate NaN-delimited horizontal cap segments."""

    x: FloatArray
    y: FloatArray
    cap_x: FloatArray
    cap_y: FloatArray


def clip_curve(values: RealArray, valid: BoolArray, limits: Limits,
               x_start: int = 0) -> ClippedCurve:
    """Insert exact threshold crossings and clamp finite line segments.

    Args:
        values: Original one-dimensional samples.
        valid: Same-size draw mask; invalid samples remain gaps.
        limits: Optional lower/upper bounds and the chosen clipping mode.
        x_start: Source coordinate of the first sample.

    Returns:
        A clamped polyline and disconnected cap segments in source coordinates.
        Arrays include NaNs to prevent connecting across gaps or separate caps.

    Raises:
        ValueError: If input dimensions or mask shape do not match.
    """
    if values.ndim != 1 or values.shape != valid.shape:
        raise ValueError("Curve samples and mask must be matching 1D arrays.")
    x = np.arange(x_start, x_start + len(values), dtype=np.float64)
    y = np.where(valid, values, np.nan).astype(np.float64)
    empty = np.empty(0, dtype=np.float64)
    if limits.mode != FilterMode.CLAMP:
        return ClippedCurve(x, y, empty, empty)
    shown = y.copy()
    nodes_x, nodes_y = [x], [shown]
    caps_x: list[FloatArray] = []
    caps_y: list[FloatArray] = []
    paired = valid[:-1] & valid[1:] & np.isfinite(y[:-1]) & np.isfinite(y[1:])
    for bound, lower in ((limits.lower, True), (limits.upper, False)):
        if bound is None:
            continue
        outside = valid & (values < bound if lower else values > bound)
        shown[outside] = bound
        crossing = paired & (outside[:-1] != outside[1:])
        fraction = np.zeros(len(paired), dtype=np.float64)
        indices = np.flatnonzero(crossing)
        # Rescaling avoids overflow when endpoints have opposite large signs.
        left, right = y[:-1][crossing], y[1:][crossing]
        scale = np.maximum(np.maximum(np.abs(left), np.abs(right)), max(abs(bound), 1.0))
        fraction[crossing] = (bound / scale - left / scale) / (right / scale - left / scale)
        nodes_x.append(x[indices] + fraction[crossing])
        nodes_y.append(np.full(len(indices), bound, dtype=np.float64))
        selected = np.flatnonzero(paired & (outside[:-1] | outside[1:]))
        start = x[selected] + np.where(outside[selected], 0.0, fraction[selected])
        end = x[selected] + np.where(outside[selected + 1], 1.0, fraction[selected])
        caps_x.append(np.column_stack((start, end, np.full(len(selected), np.nan))).ravel())
        caps_y.append(np.column_stack((np.full(len(selected), bound), np.full(len(selected), bound),
                                       np.full(len(selected), np.nan))).ravel())
    all_x, all_y = np.concatenate(nodes_x), np.concatenate(nodes_y)
    order = np.argsort(all_x, kind="stable")
    return ClippedCurve(all_x[order], all_y[order],
                        np.concatenate(caps_x) if caps_x else empty,
                        np.concatenate(caps_y) if caps_y else empty)
