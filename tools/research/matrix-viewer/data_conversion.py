"""Pointwise numeric conversions that produce independent workspace matrices.

Requirements: numpy and the viewer data model. Usage: run_conversion in the
existing worker pool. Coordinates and source arrays are never transformed.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from time import perf_counter
from typing import cast

import numpy as np

from .coordinates import AxisCoordinates
from .data_model import (Array, Component, Crop, Document, Limits, RealArray,
                         Selection, ViewMode, default_selection, prepare_frame)
from .exporting import _coordinate_table
from .fourier import TransformRange, TransformResult


class Conversion(StrEnum):
    """Pointwise operations; dB power input is already a power quantity."""

    AMPLITUDE_DB = "Amplitude to dB (20 log10)"
    POWER_DB = "Power to dB (10 log10)"
    DEG2RAD = "Degrees to radians (deg2rad)"
    RAD2DEG = "Radians to degrees (rad2deg)"
    ABSOLUTE = "Absolute value / magnitude"
    LOG10 = "Base-10 logarithm (log10)"
    LN = "Natural logarithm (ln)"
    AFFINE = "Linear scale + offset"


class DBReference(StrEnum):
    """Reference for relative dB values; no physical unit is inferred."""

    PEAK = "Peak of selected input (0 dB)"
    FIXED = "Fixed reference"


DB_CONVERSIONS: frozenset[Conversion] = frozenset({Conversion.AMPLITUDE_DB, Conversion.POWER_DB})
COMPLEX_CONVERSIONS: frozenset[Conversion] = frozenset({Conversion.AMPLITUDE_DB, Conversion.ABSOLUTE, Conversion.AFFINE})
DEFAULT_DB_FLOOR = -120.0


@dataclass(frozen=True)
class ConversionOptions:
    """Immutable source scope and arithmetic settings captured by the dialog."""

    operation: Conversion = Conversion.AMPLITUDE_DB
    range: TransformRange = TransformRange.FULL
    full_complex: bool = False
    apply_bounds: bool = False
    reference_mode: DBReference = DBReference.PEAK
    reference: float = 1.0
    db_floor: float | None = DEFAULT_DB_FLOOR
    gain: float = 1.0
    offset: float = 0.0
    row: bool = True
    index: int = 0


def convert_values(values: Array, options: ConversionOptions) -> tuple[Array, str]:
    """Convert scalar samples, keeping invalid samples as gaps.

    Args:
        values: One selected numeric channel or full complex samples.
        options: dB reference/floor or affine gain/offset; unused fields ignored.

    Returns:
        Owned floating/complex array and a description of the applied formula.
        Real logs require positive inputs; power dB rejects negative samples
        as NaN. Zero dB inputs become the chosen floor, or -Inf without a floor.
        Amplitude dB uses magnitude and does not retain sign or phase.

    Raises:
        ValueError: Unsupported complex operation, invalid parameters, or no
            finite output. NaN/Inf inputs and overflow never become valid zeros.
    """
    operation = options.operation
    complex_input = np.iscomplexobj(values)
    if complex_input and operation not in COMPLEX_CONVERSIONS:
        raise ValueError("This operation requires a real channel. Select Real, Imaginary, Magnitude or Phase first.")
    dtype = np.result_type(values.dtype, np.complex128 if complex_input else np.float64)
    source = np.asarray(values, dtype=dtype)
    valid = np.isfinite(source)
    description = operation.value
    with np.errstate(divide="ignore", invalid="ignore", over="ignore", under="ignore"):
        if operation in DB_CONVERSIONS:
            magnitude = np.abs(source) if operation == Conversion.AMPLITUDE_DB else source
            eligible = valid & np.isfinite(magnitude) & (magnitude >= 0)
            if not np.any(eligible):
                raise ValueError("No finite nonnegative samples are available for the dB conversion.")
            if options.reference_mode == DBReference.PEAK:
                peak = np.max(magnitude, where=eligible, initial=0)
                reference = peak if peak > 0 else 1.0
            else:
                reference = options.reference
            if not np.isfinite(reference) or reference <= 0:
                raise ValueError("The dB reference must be finite and greater than zero.")
            factor = 20 if operation == Conversion.AMPLITUDE_DB else 10
            # Subtract logarithms to avoid overflowing/underflowing the ratio.
            result = factor * (np.log10(magnitude) - np.log10(reference))
            if options.db_floor is not None:
                if not np.isfinite(options.db_floor) or options.db_floor >= 0:
                    raise ValueError("The dB floor must be finite and negative.")
                result = np.maximum(result, options.db_floor)
            result = np.where(eligible, result, np.nan)
            description = f"{factor} * log10({'abs(x)' if factor == 20 else 'x'} / {reference:.12g}); reference={options.reference_mode.value}; floor={options.db_floor}"
        elif operation == Conversion.DEG2RAD:
            result = np.deg2rad(source)
        elif operation == Conversion.RAD2DEG:
            result = np.rad2deg(source)
        elif operation == Conversion.ABSOLUTE:
            result = np.abs(source)
        elif operation in (Conversion.LOG10, Conversion.LN):
            valid &= source > 0
            result = np.log10(source) if operation == Conversion.LOG10 else np.log(source)
        elif operation == Conversion.AFFINE:
            if not np.isfinite(options.gain) or not np.isfinite(options.offset):
                raise ValueError("Scale and offset must be finite numbers.")
            result = source * options.gain + options.offset
            description = f"x * {options.gain:.12g} + {options.offset:.12g}"
        else:
            raise ValueError(f"Unsupported conversion: {operation}")
    result = np.where(valid, result, np.nan)
    if operation not in DB_CONVERSIONS:
        result[~np.isfinite(result)] = np.nan
    if not np.any(np.isfinite(result)):
        raise ValueError("The conversion produced no finite samples. Check the input channel, operation and dB floor.")
    return cast(Array, result), description


def run_conversion(document: Document, selection: Selection, crop: Crop, limits: Limits,
                   options: ConversionOptions, source_name: str, name: str = "") -> TransformResult:
    """Convert a full channel, cropped region or selected slice in the worker.

    Args:
        document: Loaded numeric/image member; original storage is read-only.
        selection: Active interpretation and complex component.
        crop: Applied index crop; used for Crop and Slice scopes.
        limits: Applied value bounds, optionally used before conversion.
        options: Operation, source scope and numeric parameters.
        source_name: Human-readable source matrix/channel label.
        name: Optional result alias; blank derives a descriptive name.

    Returns:
        New document with physical axes and explicit XY/point interpretation.
        XY preserves repeated/irregular X and record order, converting only Y;
        points convert only Z. Image composites use their grayscale height.
        FFT/Laplace inverse records are not copied after changing sample values.

    Raises:
        ValueError: Invalid range, slice, parameters, complex bounds or operation.
        MemoryError: Insufficient memory for the full-resolution result.

    Side effects:
        Prints source, formula, scope, finite counts and elapsed calculation time.
    """
    started = perf_counter()
    full_complex = options.full_complex and document.is_complex
    if full_complex and options.apply_bounds:
        raise ValueError("Value bounds cannot be applied to full complex samples. Choose a real component.")
    region = Crop() if options.range == TransformRange.FULL else crop
    prepared_selection = replace(selection, component=Component.REAL) if full_complex else selection
    frame = prepare_frame(document, prepared_selection, limits if options.apply_bounds else Limits(), 2,
                          region, max_points=1)
    values: Array = frame.scalar
    if full_complex:
        if frame.raw is None:
            raise ValueError("Full complex source samples are unavailable.")
        values = frame.raw
    elif options.apply_bounds:
        values = np.where(frame.valid, frame.display_scalar, np.nan)
    starts = ((frame.y_grid, frame.y_start), (frame.x_grid, frame.x_start)) if values.ndim == 2 else ((frame.x_grid, frame.x_start),)
    grids = tuple(replace(grid, origin=grid.mapping.forward(start)) if grid is not None else
                  AxisCoordinates(float(start), unit="pixel" if document.is_image else "sample")
                  for grid, start in starts)
    scope = options.range.value
    if options.range != TransformRange.FULL:
        scope = f"{scope}; {region}"
    if options.range == TransformRange.SLICE:
        if selection.mode != ViewMode.MATRIX or values.ndim != 2:
            raise ValueError("Slice conversion requires a 2D matrix with a selected row/column.")
        local = options.index - (frame.y_start if options.row else frame.x_start)
        if not 0 <= local < values.shape[0 if options.row else 1]:
            raise ValueError("The selected source slice is outside the current crop.")
        values = values[local, :] if options.row else values[:, local]
        grids = (grids[1 if options.row else 0],)
        scope = f"{'Row' if options.row else 'Column'} {options.index}; {region}"
    converted, formula = convert_values(values, options)
    finite = int(np.count_nonzero(np.isfinite(converted)))
    sample_count = converted.size
    mode = ViewMode.SIGNAL if converted.ndim == 1 else ViewMode.MATRIX
    if selection.mode in (ViewMode.XY, ViewMode.POINTS):
        coordinates = frame.raw
        if coordinates is None:
            raise ValueError("Source coordinates are unavailable.")
        count = 1 if selection.mode == ViewMode.XY else 2
        converted = _coordinate_table((*tuple(cast(RealArray, coordinates[:, axis]) for axis in range(count)),
                                       cast(RealArray, converted)))
        mode, grids = selection.mode, ()
    channel = "Full complex values" if full_complex else "Grayscale height" if frame.composite else "Selected scalar channel"
    provenance = (f"Data conversion: {formula}\nSource: {source_name} / {channel}\nRange: {scope}\n"
                  f"Apply source value bounds: {options.apply_bounds}; {limits if options.apply_bounds else 'none'}\n"
                  f"Finite converted values: {finite:,} / {sample_count:,}. Coordinates retain source units/order.")
    result = Document(document.path, converted, axes=grids, conversion_provenance=provenance)
    result_name = name.strip() or f"{source_name} · {options.operation.name}"
    print(f"[Data conversion] {provenance}\nOutput: {converted.shape}, {converted.dtype}; {perf_counter() - started:.3f} s", flush=True)
    return TransformResult(result, result_name, default_selection(result, mode))
