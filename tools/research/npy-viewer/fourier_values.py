"""Finite FFT inputs with independent nonfinite/out-of-bound replacements.

Requirements: numpy. Usage: prepare_fourier_values on the transform worker.
Extrema come from original finite, in-bound samples before any replacement.
Complex samples are invalid as a whole if either component is nonfinite and
are replaced by 0+0j. Phase channels use zero only and never apply value bounds.
Source arrays and sampling positions are unchanged. Counts describe this input,
before optional mean removal, windows or padding, and become result provenance.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import numpy as np

from .data_model import Array, Limits, RealArray, RealScalar


class ValueReplacement(StrEnum):
    """Finite replacements; BOUNDARY is reserved for finite out-of-bound values."""

    ZERO = "0"
    MAXIMUM = "Valid maximum"
    MINIMUM = "Valid minimum"
    BOUNDARY = "Clamp to bounds"


@dataclass(frozen=True)
class FourierValuePolicy:
    """Independent real-channel treatments; nonfinite defaults are all zero."""

    nan: ValueReplacement = ValueReplacement.ZERO
    positive: ValueReplacement = ValueReplacement.ZERO
    negative: ValueReplacement = ValueReplacement.ZERO
    clipped: ValueReplacement = ValueReplacement.BOUNDARY


def prepare_fourier_values(values: Array, limits: Limits, policy: FourierValuePolicy,
                           *, phase: bool = False) -> tuple[Array, tuple[str, ...]]:
    """Replace exceptional samples without resampling or mutating the input.

    Args:
        values: Selected 1D/2D real channel or full complex array.
        limits: Active real-channel bounds; ignored for complex and phase input.
        policy: Treatments for NaN, positive/negative infinity and finite outliers.
        phase: Force zero filling and ignore bounds for a real phase channel.

    Returns:
        Finite samples plus replacement counts/methods for result provenance.
        Unchanged input may be returned directly; callers must treat it as read-only.

    Raises:
        ValueError: Invalid bounds/policy, no valid samples for a requested
            extremum, or an integer cannot retain its precision during clamping.
    """
    finite = np.isfinite(values)
    if np.iscomplexobj(values):
        count = int(np.count_nonzero(~finite))
        if not count:
            return values, ()
        output = values.copy()
        output[~finite] = 0
        return output, (f"invalid complex samples: {count} -> 0+0j (whole sample)",)
    real = cast(RealArray, values)
    if phase:
        limits, policy = Limits(), FourierValuePolicy()
    if any(value is not None and not np.isfinite(value) for value in (limits.lower, limits.upper)):
        raise ValueError("Value bounds must be finite.")
    if limits.lower is not None and limits.upper is not None and limits.lower > limits.upper:
        raise ValueError("Value minimum exceeds maximum.")
    below = finite & (real < limits.lower) if limits.lower is not None else np.zeros(real.shape, dtype=np.bool_)
    above = finite & (real > limits.upper) if limits.upper is not None else np.zeros(real.shape, dtype=np.bool_)
    outside = below | above
    groups = (("NaN", np.isnan(real), policy.nan),
              ("+Inf", np.isposinf(real), policy.positive),
              ("-Inf", np.isneginf(real), policy.negative),
              ("outside bounds", outside, policy.clipped))
    active = tuple((label, mask, method, int(np.count_nonzero(mask)))
                   for label, mask, method in groups if np.any(mask))
    if not active:
        return values, ()
    valid = finite & ~outside
    extrema: dict[ValueReplacement, RealScalar] = {}
    for _, _, method, _ in active:
        if method in (ValueReplacement.MAXIMUM, ValueReplacement.MINIMUM) and method not in extrema:
            if not np.any(valid):
                raise ValueError("No finite, in-bound samples are available for a valid maximum/minimum. Choose 0 instead.")
            extrema[method] = cast(RealScalar, np.max(real[valid]) if method == ValueReplacement.MAXIMUM else np.min(real[valid]))
    # Fractional bounds need floating storage even for integer images/arrays.
    clamp = policy.clipped == ValueReplacement.BOUNDARY and np.any(outside)
    result: RealArray = real.astype(np.result_type(real.dtype, np.float64)) if clamp else real.copy()
    if clamp and real.dtype.kind in "iu":
        with np.errstate(over="ignore", invalid="ignore"):
            if not np.array_equal(result[valid].astype(real.dtype), real[valid]):
                raise ValueError("Clamping would round large integer samples. Rescale the data first.")
    notes: list[str] = []
    for label, mask, method, count in active:
        if method == ValueReplacement.BOUNDARY:
            if label != "outside bounds":
                raise ValueError("Clamp to bounds is only valid for finite out-of-bound samples.")
            if limits.lower is not None:
                result[below] = limits.lower
            if limits.upper is not None:
                result[above] = limits.upper
        elif method == ValueReplacement.ZERO:
            result[mask] = 0
        else:
            # Keep NumPy scalars, including exact integer extrema, for assignment.
            np.copyto(result, np.asarray(extrema[method], dtype=result.dtype), where=mask)
        notes.append(f"{label}: {count} -> {method.value}")
    return result, tuple(notes)
