"""Gap-aware finite differences for the optional signal derivative view.

Requirements: numpy. Usage: differentiate a displayed, unscaled source profile.
"""

from dataclasses import dataclass

import numpy as np

from .data_model import BoolArray, FloatArray, IndexArray, RealArray


@dataclass(frozen=True)
class DerivativeResult:
    """Derivative samples and indices whose derivative is deliberately omitted.

    Values use unit or explicitly supplied X spacing and retain source order.
    Undefined values are NaN; their indices identify finite, visible source
    samples at or bordering a gap, repeated X coordinate or suspected jump.
    Jump count counts rejected neighboring pairs, not the red markers.
    """

    values: FloatArray
    valid: BoolArray
    undefined_indices: IndexArray
    jump_count: int


def _differences(values: RealArray) -> FloatArray:
    """Compute signed neighboring differences without losing large integer steps."""
    if values.dtype.kind in "iu":
        # Unsigned subtraction preserves the exact magnitude modulo 2**64,
        # including differences spanning the full signed int64 domain.
        integers = values.astype(np.uint64)
        rising = values[1:] >= values[:-1]
        upward = (integers[1:] - integers[:-1]).astype(np.float64)
        downward = (integers[:-1] - integers[1:]).astype(np.float64)
        return np.where(rising, upward, -downward)
    return np.diff(values.astype(np.float64))


def differentiate(values: RealArray, valid: BoolArray,
                  jump_threshold: float | None = None, *, x_values: RealArray | None = None) -> DerivativeResult:
    """Estimate dy/dx while excluding differences across gaps or suspected jumps.

    Interior points use central differences; the two outer endpoints use
    one-sided differences. Explicit X coordinates are sorted for calculation;
    results are mapped back to source order without modifying the inputs.
    Every repeated X coordinate is a gap, even when its Y values agree.
    Both visible samples bordering a rejected edge
    are undefined, including samples next to filtered/nonfinite values.
    A threshold detects suspected discontinuities, not mathematical proof
    of non-differentiability. No phase unwrapping is performed.

    Args:
        values: One-dimensional, original real samples; spacing is one index.
        valid: Boolean mask with the same shape; False means an excluded value.
        jump_threshold: Positive finite maximum allowed absolute neighboring
            difference. None disables jump detection but still respects gaps.
        x_values: Optional source X coordinates. Nonuniform spacing uses
            three-point differences in ascending X order. Repeated X samples
            are excluded from every stencil, as are filtered/nonfinite samples.

    Returns:
        Float64 derivatives, validity mask and red-marker indices in source
        order, plus a count of rejected jumps between neighboring X positions.

    Raises:
        ValueError: If shapes differ, input is not 1D, or threshold is invalid.
    """
    if values.ndim != 1 or valid.shape != values.shape:
        raise ValueError("Derivative samples and visibility mask must be matching 1D arrays.")
    if x_values is not None and x_values.shape != values.shape:
        raise ValueError("X coordinates must match the one-dimensional samples.")
    if jump_threshold is not None and (not np.isfinite(jump_threshold) or jump_threshold <= 0):
        raise ValueError("The jump threshold must be positive and finite.")
    order: IndexArray | None = None
    if x_values is not None:
        order = np.argsort(x_values, kind="stable").astype(np.int64, copy=False)
        values, valid, x_values = values[order], valid[order], x_values[order]
    finite = valid & np.isfinite(values)
    if x_values is not None:
        finite &= np.isfinite(x_values)
    usable = finite.copy()
    if x_values is not None and values.size >= 2:
        repeated = x_values[:-1] == x_values[1:]
        usable[:-1] &= ~repeated
        usable[1:] &= ~repeated
    gradient = np.full(values.shape, np.nan, dtype=np.float64)
    accepted = np.zeros(values.shape, dtype=np.bool_)
    jump_count = 0

    # ── classify edges before forming any derivative ──────
    if values.size >= 2:
        with np.errstate(over="ignore", invalid="ignore"):
            delta = _differences(values)
            paired = usable[:-1] & usable[1:]
            jumps = paired & (np.abs(delta) > jump_threshold) if jump_threshold is not None else np.zeros_like(paired)
            edges = paired & np.isfinite(delta) & ~jumps
            jump_count = int(np.count_nonzero(jumps))
            if x_values is None:
                gradient[0], gradient[-1] = delta[0], delta[-1]
                gradient[1:-1] = delta[:-1] / 2 + delta[1:] / 2
            else:
                dx = _differences(x_values)
                edges &= np.isfinite(dx) & (dx != 0)
                slope = np.divide(delta, dx, out=np.full_like(delta, np.nan), where=edges)
                gradient[0], gradient[-1] = slope[0], slope[-1]
                denominator = dx[:-1] + dx[1:]
                weight = np.divide(dx[1:], denominator, out=np.full_like(denominator, np.nan),
                                   where=denominator != 0)
                gradient[1:-1] = weight * slope[:-1] + (1 - weight) * slope[1:]
        accepted[0], accepted[-1] = edges[0], edges[-1]
        accepted[1:-1] = edges[:-1] & edges[1:]
        accepted &= finite & np.isfinite(gradient)
        gradient[~accepted] = np.nan
    if order is not None:
        source_gradient = np.empty_like(gradient)
        source_accepted = np.empty_like(accepted)
        source_finite = np.empty_like(finite)
        source_gradient[order], source_accepted[order], source_finite[order] = gradient, accepted, finite
        gradient, accepted, finite = source_gradient, source_accepted, source_finite
    undefined = np.flatnonzero(finite & ~accepted).astype(np.int64, copy=False)
    return DerivativeResult(gradient, accepted, undefined, jump_count)
