"""Combine two full-resolution real channels into an owned complex matrix.

Requirements: numpy and the viewer's existing numeric extraction helpers.
Usage: run_merge from a viewer worker; sources are never modified. Input
channels ignore display crop, value bounds and overlay alignment.
"""

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import cast

import numpy as np

from .data_model import ComplexArray, Component, Crop, Document, RealArray, Selection
from .fourier import TransformOptions, TransformResult, transform_input


class MergeMode(StrEnum):
    """Pair of real-valued components used to reconstruct complex samples."""

    CARTESIAN = "Real + imaginary"
    POLAR = "Magnitude + phase"


class PhaseUnit(StrEnum):
    """Unit of the second input in polar mode."""

    RADIANS = "Radians (rad)"
    DEGREES = "Degrees (deg)"


@dataclass(frozen=True)
class MergeInput:
    """Immutable source channel, including a lazily decoded image member."""

    document: Document
    selection: Selection
    label: str
    image_key: str | None = None
    channel_label: str = "Value"


@dataclass(frozen=True)
class MergeMatrix:
    """A source matrix and the numeric channel choices shown by the dialog."""

    label: str
    channels: tuple[MergeInput, ...]


def run_merge(first: MergeInput, second: MergeInput, mode: MergeMode,
              phase_unit: PhaseUnit = PhaseUnit.RADIANS, name: str = "") -> TransformResult:
    """Build real + i*imaginary or magnitude*exp(i*phase) without resampling.

    Args:
        first: Real part or nonnegative linear magnitude, not normalized dB.
        second: Imaginary part or phase; selected components remain real arrays.
        mode: Cartesian or polar reconstruction.
        phase_unit: Explicit polar phase unit, ignored for Cartesian input.
        name: Optional session alias; otherwise derived from both source labels.

    Returns:
        New complex document with source coordinates and readable provenance.
        Precision is at least complex128; wider source floats retain precision.
        Cartesian NaN/Inf components survive independently. Undefined polar
        samples remain nonfinite gaps rather than becoming zeros.

    Raises:
        ValueError: Unequal shapes/grids, negative magnitude, point clouds,
            XY coordinates that are nonuniform/duplicate, or integer precision
            that cannot fit the chosen complex dtype.
        MemoryError: Insufficient memory for the full-resolution output.

    Side effects:
        Prints input identities, reconstruction settings and elapsed time.
    """
    started = perf_counter()
    if mode == MergeMode.POLAR and first.document.is_complex and first.selection.component == Component.MAGNITUDE_DB:
        raise ValueError("Magnitude must be linear. Select Magnitude, not Magnitude (dB).")
    inputs = tuple(transform_input(
        item.document, item.selection, Crop(),
        TransformOptions(display_component=True, image_key=item.image_key),
    ) for item in (first, second))
    left, right = inputs
    if left.values.shape != right.values.shape:
        raise ValueError(f"Component shapes must match exactly: {left.values.shape} versus {right.values.shape}. No broadcasting or resizing is applied.")
    if any(a.mapping != b.mapping for a, b in zip(left.grids, right.grids, strict=True)):
        raise ValueError("Component sample coordinates do not match. Overlay alignment is visual only; align the source data before merging.")
    if first.document.axes and second.document.axes and left.grids != right.grids:
        raise ValueError("Component coordinate units or domains do not match.")
    a, b = cast(RealArray, left.values), cast(RealArray, right.values)
    if mode == MergeMode.POLAR and np.any(a < 0):
        raise ValueError("Magnitude contains negative values. Select a nonnegative linear magnitude channel.")

    # Assign Cartesian parts independently: 1j * inf would contaminate the
    # real component with NaN. Choose at least double precision for arithmetic.
    dtype = np.result_type(left.values.dtype, right.values.dtype, np.complex128)
    values = cast(ComplexArray, np.empty(left.values.shape, dtype=dtype))
    for source, destination in ((a, values.real), (b, values.imag)):
        destination[...] = source
        if source.dtype.kind in "iu":
            with np.errstate(invalid="ignore", over="ignore"):
                if not np.array_equal(destination.astype(source.dtype), source):
                    raise ValueError("Integer components exceed exact complex floating-point precision. Convert/rescale explicitly before merging.")
    if mode == MergeMode.POLAR:
        if phase_unit == PhaseUnit.DEGREES:
            np.deg2rad(values.imag, out=values.imag)
        phase = values.imag.copy()
        with np.errstate(invalid="ignore", over="ignore"):
            values.imag = values.real * np.sin(phase)
            values.real *= np.cos(phase)

    grids = left.grids if first.document.axes or not second.document.axes else right.grids
    formula = "real + i * imaginary" if mode == MergeMode.CARTESIAN else f"magnitude * exp(i * phase); {phase_unit.value}"
    provenance = (f"Complex matrix merge: {formula}\nFirst: {first.label}\nSecond: {second.label}\n"
                  "Full source channels; display crop, bounds and alignment ignored.")
    document = Document(first.document.path, values, axes=grids, complex_provenance=provenance)
    result_name = name.strip() or f"Complex merge · {first.label} + {second.label}"
    print(f"[Complex merge] {provenance}\nOutput: {values.shape}, {values.dtype}; {perf_counter() - started:.3f} s", flush=True)
    return TransformResult(document, result_name)
