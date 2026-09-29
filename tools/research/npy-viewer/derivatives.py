"""Gap-aware finite differences for the optional signal derivative view.

Requirements: numpy. Usage: differentiate a displayed, unscaled source profile.
"""

from dataclasses import dataclass

import numpy as np

from .data_model import BoolArray, FloatArray, IndexArray, RealArray


@dataclass(frozen=True)
class DerivativeResult:
    """Derivative samples and indices whose derivative is deliberately omitted.

    Values use unit sample spacing. Undefined values are NaN; their indices
    identify finite, visible source samples bordering a gap or suspected jump.
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
                  jump_threshold: float | None = None) -> DerivativeResult:
    """Estimate dy/dx while excluding differences across gaps or suspected jumps.

    Interior points use central differences; the two outer endpoints use
    one-sided differences. Both visible samples bordering a rejected edge
    are undefined, including samples next to filtered/nonfinite values.
    A threshold detects suspected discontinuities, not mathematical proof
    of non-differentiability. No phase unwrapping is performed.

    Args:
        values: One-dimensional, original real samples; spacing is one index.
        valid: Boolean mask with the same shape; False means an excluded value.
        jump_threshold: Positive finite maximum allowed absolute neighboring
            difference. None disables jump detection but still respects gaps.

    Returns:
        Float64 derivatives, validity mask, red-marker indices and jump count.

    Raises:
        ValueError: If shapes differ, input is not 1D, or threshold is invalid.
    """
    if values.ndim != 1 or valid.shape != values.shape:
        raise ValueError("Derivative samples and visibility mask must be matching 1D arrays.")
    if jump_threshold is not None and (not np.isfinite(jump_threshold) or jump_threshold <= 0):
        raise ValueError("The jump threshold must be positive and finite.")
    finite = valid & np.isfinite(values)
    gradient = np.full(values.shape, np.nan, dtype=np.float64)
    accepted = np.zeros(values.shape, dtype=np.bool_)
    jump_count = 0

    # ── classify edges before forming any derivative ──────
    if values.size >= 2:
        with np.errstate(over="ignore", invalid="ignore"):
            delta = _differences(values)
            paired = finite[:-1] & finite[1:]
            jumps = paired & (np.abs(delta) > jump_threshold) if jump_threshold is not None else np.zeros_like(paired)
            edges = paired & np.isfinite(delta) & ~jumps
            jump_count = int(np.count_nonzero(jumps))
            gradient[0], gradient[-1] = delta[0], delta[-1]
            gradient[1:-1] = delta[:-1] / 2 + delta[1:] / 2
        accepted[0], accepted[-1] = edges[0], edges[-1]
        accepted[1:-1] = edges[:-1] & edges[1:]
        accepted &= finite & np.isfinite(gradient)
        gradient[~accepted] = np.nan
    undefined = np.flatnonzero(finite & ~accepted).astype(np.int64, copy=False)
    return DerivativeResult(gradient, accepted, undefined, jump_count)
