"""Finite-sample 1D Laplace planes and contour-based inverse transforms.

Requirements: numpy and scipy. Usage: run_laplace in a viewer worker.
Rows sample sigma; columns sample the complete centered angular-frequency grid.
The convention is dt * sum(f[n] * exp(-s*n*dt)); the first selected sample is
the local time origin. This is a finite-record numerical transform, not symbolic
continuation of an infinite signal. Inversion uses one complete sigma row.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from time import perf_counter
from typing import cast

import numpy as np
from scipy import fft

from .coordinates import AxisCoordinates
from .data_model import (ComplexArray, Crop, Document, FloatArray, Limits, Selection,
                         ViewMode, _extract_raw)
from .fourier import TransformOptions, TransformRange, TransformResult, transform_input

DEFAULT_SIGMA_COUNT = 129
DEFAULT_EXPONENT_SPAN = 4.0
MAX_EXPONENT_SPAN = 30.0
MAX_OUTPUT_BYTES = 1024**3


class LaplaceDirection(StrEnum):
    """Operations supported by the finite-record Laplace pair."""

    FORWARD = "Laplace — signal to complex plane"
    INVERSE = "Inverse Laplace — complex plane to signal"


@dataclass(frozen=True)
class LaplaceOptions:
    """Immutable worker settings; external inverse frequencies are in rad/unit."""

    direction: LaplaceDirection = LaplaceDirection.FORWARD
    range: TransformRange = TransformRange.FULL
    spacing: float = 1.0
    unit: str = "sample"
    sigma_min: float | None = None
    sigma_max: float | None = None
    sigma_count: int = DEFAULT_SIGMA_COUNT
    fft_size: int = 0
    single_precision: bool = False
    display_component: bool = False
    apply_bounds: bool = False
    fill_zero: bool = False
    inverse_row: int | None = None
    omega_spacing: float = 1.0
    external_sigma: float = 0.0
    output_count: int = 0
    output_origin: float = 0.0
    input_centered: bool = True


@dataclass(frozen=True)
class LaplaceRecord:
    """Small provenance record; no reference to the source array is retained."""

    direction: LaplaceDirection
    source_name: str
    source_channel: str
    source_range: str
    time_grid: AxisCoordinates
    input_count: int
    fft_size: int
    sigma_min: float
    sigma_max: float
    sigma_count: int
    preprocessing: str = "None"
    inverse_row: int | None = None

    @property
    def description(self) -> str:
        """Describe the transform convention and the parameters needed to invert."""
        return (f"{self.direction.value}\nSource: {self.source_name} / {self.source_channel}\n"
                f"Range: {self.source_range}\nInput N: {self.input_count}; frequency bins: {self.fft_size}\n"
                f"dt: {self.time_grid.spacing}; unit: {self.time_grid.unit}; source origin: {self.time_grid.origin}\n"
                f"Sigma: [{self.sigma_min}, {self.sigma_max}], {self.sigma_count} rows\n"
                f"Convention: dt * FFT(f[n] * exp(-sigma*n*dt)); centered omega columns.\n"
                f"Time origin for the kernel: first selected sample. Preprocessing: {self.preprocessing}\n"
                f"Inverse row: {self.inverse_row if self.inverse_row is not None else 'not inverted'}")


def sigma_values(record: LaplaceRecord) -> FloatArray:
    """Return the recorded, uniformly sampled real-frequency coordinates."""
    return np.linspace(record.sigma_min, record.sigma_max, record.sigma_count, dtype=np.float64)


def default_sigma_range(count: int, spacing: float) -> tuple[float, float]:
    """Choose symmetric sigma bounds with moderate exponential weighting."""
    extent = max(count - 1, 1) * spacing
    if not np.isfinite(extent) or extent <= 0:
        raise ValueError("The signal duration must be positive and finite.")
    bound = DEFAULT_EXPONENT_SPAN / extent
    if not np.isfinite(bound) or bound <= 0:
        raise ValueError("The default sigma range is outside floating-point range.")
    return -bound, bound


def _time_weights(sigma: float, count: int, spacing: float, *, inverse: bool = False) -> FloatArray:
    """Reject weights that would make contour inversion severely ill-conditioned."""
    extent = sigma * (count - 1) * spacing
    if not np.isfinite(extent) or abs(extent) > MAX_EXPONENT_SPAN:
        raise ValueError(f"abs(sigma) * duration must be <= {MAX_EXPONENT_SPAN:g}. "
                         "Use a sigma nearer zero or a shorter signal; exponential weighting would lose precision.")
    exponent = sigma * (np.arange(count, dtype=np.float64) * spacing)
    return np.exp(exponent if inverse else -exponent)


def run_laplace(document: Document, selection: Selection, crop: Crop, limits: Limits,
                options: LaplaceOptions, source_name: str, name: str = "") -> TransformResult:
    """Transform an indexed/XY signal to a plane or invert a complete contour.

    Args:
        document: Stable, unmodified source data and optional Laplace metadata.
        selection: Current numeric interpretation; points and images are excluded.
        crop: Forward sample crop. Inversion always requires complete frequencies.
        limits: Forward-only bounds, applied solely when requested.
        options: Sampling, sigma grid, precision and inverse contour settings.
        source_name: Source session label, printed and retained in provenance.
        name: Optional result label; empty uses an automatic descriptive name.

    Returns:
        A complex 2D plane or complex 1D signal with physical axis coordinates.

    Raises:
        ValueError: Invalid input, nonuniform XY, incomplete spectrum, excessive
            exponential weighting, overflow, or unsupported preprocessing.
        MemoryError: The output exceeds 1 GiB or available memory.

    Side effects:
        Prints source, sampling, contour, sizes and timing to the console.
    """
    started = perf_counter()
    if document.is_image or selection.mode == ViewMode.POINTS:
        raise ValueError("Laplace transforms accept numeric 1D signals or complex 2D Laplace planes, not images or point clouds.")
    result = (_inverse(document, selection, options, source_name, name)
              if options.direction == LaplaceDirection.INVERSE else
              _forward(document, selection, crop, limits, options, source_name, name))
    print(f"[Laplace] Finished: {result.name}; shape={result.document.array.shape}; "
          f"dtype={result.document.array.dtype}; {(perf_counter() - started) * 1000:.1f} ms", flush=True)
    return result


def _forward(document: Document, selection: Selection, crop: Crop, limits: Limits,
             options: LaplaceOptions, source_name: str, name: str) -> TransformResult:
    """Evaluate each sigma contour with a full FFT, using only one working row."""
    if selection.mode not in (ViewMode.SIGNAL, ViewMode.XY) or options.range.is_slice:
        raise ValueError("Forward Laplace requires a 1D signal / XY interpretation. Save a matrix slice as 1D NPY first.")
    source = transform_input(document, selection, crop, TransformOptions(
        range=options.range, display_component=options.display_component, apply_bounds=options.apply_bounds), limits)
    values = source.values
    if values.ndim != 1 or values.size < 2:
        raise ValueError("Laplace requires at least two 1D samples.")
    count = values.size
    grid = source.grids[0]
    spacing = grid.spacing if source.explicit_coordinates else options.spacing
    if not np.isfinite(spacing) or spacing <= 0:
        raise ValueError("Sampling interval dt must be positive and finite.")
    origin = grid.origin * spacing if not document.axes and not source.explicit_coordinates else grid.origin
    grid = AxisCoordinates(origin, spacing, options.unit.strip() or "sample", grid.frequency, grid.symbol)
    if not np.isfinite(origin):
        raise ValueError("The source coordinate origin must be finite.")
    size = options.fft_size or count
    if size < count:
        raise ValueError("Frequency bins cannot be fewer than the input samples.")
    if options.sigma_count < 2:
        raise ValueError("Choose at least two sigma rows.")
    default_low, default_high = default_sigma_range(count, spacing)
    low = default_low if options.sigma_min is None else options.sigma_min
    high = default_high if options.sigma_max is None else options.sigma_max
    if not np.isfinite(low) or not np.isfinite(high) or low >= high:
        raise ValueError("Sigma minimum and maximum must be finite, with minimum < maximum.")
    _time_weights(max(abs(low), abs(high)), count, spacing)
    dtype = np.complex64 if options.single_precision else np.complex128
    needed = options.sigma_count * size * np.dtype(dtype).itemsize
    if needed > MAX_OUTPUT_BYTES:
        raise MemoryError("Laplace output exceeds 1 GiB. Reduce sigma rows, padding or the input crop.")
    missing = ~np.isfinite(values)
    if np.any(missing) and not options.fill_zero:
        raise ValueError("Input contains NaN/Inf or filtered samples. Repair the source or explicitly enable zero filling.")
    with np.errstate(over="ignore", invalid="ignore"):
        work = np.array(values, dtype=dtype, copy=True)
    if np.any(~np.isfinite(work) & ~missing):
        raise ValueError("Input overflows the selected precision; use double precision or rescale it.")
    if values.dtype.kind in "iu":
        with np.errstate(over="ignore", invalid="ignore"):
            if not np.array_equal(work.real.astype(values.dtype), values):
                raise ValueError("Selected precision would round large integer samples. Use double precision or rescale them.")
    work[missing] = 0
    omega_step = 2 * np.pi / (size * spacing)
    sigma_step = (high - low) / (options.sigma_count - 1)
    if not np.isfinite(omega_step) or omega_step <= 0 or not np.isfinite(sigma_step) or sigma_step <= 0:
        raise ValueError("The output coordinate spacing is outside floating-point range.")
    notes: list[str] = []
    if options.apply_bounds:
        notes.append(f"value bounds: {limits}")
    if np.any(missing):
        notes.append(f"zero-filled {np.count_nonzero(missing)} samples")
    record = LaplaceRecord(LaplaceDirection.FORWARD, source_name, source.channel_label, source.range_label,
                           grid, count, size, low, high, options.sigma_count, "; ".join(notes) or "None")
    print(f"[Laplace] Forward: {source_name} / {source.channel_label}; {source.range_label}; "
          f"N={count}; dt={spacing}; sigma=[{low}, {high}] x {options.sigma_count}; "
          f"omega bins={size}; delta omega={omega_step}; preprocessing={record.preprocessing}", flush=True)
    plane = np.empty((options.sigma_count, size), dtype=dtype)
    for row, sigma in enumerate(sigma_values(record)):
        with np.errstate(over="ignore", invalid="ignore", under="ignore"):
            weighted = np.asarray(work * _time_weights(float(sigma), count, spacing), dtype=dtype)
            spectrum = cast(ComplexArray, fft.fft(weighted, n=size, norm="backward", workers=1))
            plane[row] = cast(ComplexArray, fft.fftshift(spectrum)) * spacing
        if not np.all(np.isfinite(plane[row])):
            raise ValueError(f"Laplace overflow at sigma row {row}. Reduce the sigma range or rescale the signal.")
    axes = (AxisCoordinates(low, sigma_step, f"1/{grid.unit}", True, "σ"),
            AxisCoordinates(-(size // 2) * omega_step, omega_step, f"rad/{grid.unit}", True, "ω"))
    return TransformResult(Document(document.path, plane, axes=axes, laplace=record),
                           name.strip() or f"{source_name} · {source.channel_label} · Laplace")


def _inverse(document: Document, selection: Selection, options: LaplaceOptions,
             source_name: str, name: str) -> TransformResult:
    """Recover one local-time record from a complete, evenly spaced omega row."""
    if selection.mode != ViewMode.MATRIX or not np.iscomplexobj(document.array):
        raise ValueError("Inverse Laplace requires a complex 2D matrix in matrix mode.")
    if options.apply_bounds or options.display_component or options.fill_zero or options.range != TransformRange.FULL:
        raise ValueError("Inverse Laplace uses the full complex spectrum without crop, bounds or zero filling.")
    record = document.laplace
    paired = record is not None and record.direction == LaplaceDirection.FORWARD
    if paired and (selection.x_axis != 1 or selection.y_axis != 0 or selection.channel_axis is not None):
        raise ValueError("Recorded Laplace planes require X = omega (axis 1), Y = sigma (axis 0), with no channel axis.")
    values = _extract_raw(document, selection, Crop())
    if values.ndim != 2 or min(values.shape) < 2:
        raise ValueError("A Laplace plane needs at least two sigma rows and two frequency columns.")
    rows, size = values.shape
    if paired and record is not None:
        if values.shape != (record.sigma_count, record.fft_size):
            raise ValueError("The recorded Laplace spectrum is incomplete. Invert the original full plane.")
        sigmas = sigma_values(record)
        row = int(np.argmin(np.abs(sigmas))) if options.inverse_row is None else options.inverse_row
        if not 0 <= row < rows:
            raise ValueError("The inverse sigma row is outside the matrix.")
        sigma = float(sigmas[row])
        grid, count, centered = record.time_grid, record.input_count, True
    else:
        row = 0 if options.inverse_row is None else options.inverse_row
        if not 0 <= row < rows:
            raise ValueError("The inverse sigma row is outside the matrix.")
        if not np.isfinite(options.omega_spacing) or options.omega_spacing <= 0:
            raise ValueError("External spectra need a positive angular-frequency interval in rad/unit.")
        spacing = 2 * np.pi / (size * options.omega_spacing)
        if not np.isfinite(spacing) or spacing <= 0 or not np.isfinite(options.output_origin):
            raise ValueError("The restored sampling interval and origin must be finite, with dt > 0.")
        grid = AxisCoordinates(options.output_origin, spacing, options.unit.strip() or "sample")
        count = options.output_count or size
        if not 1 <= count <= size:
            raise ValueError("Output samples must be between 1 and the frequency-column count.")
        sigma, centered = options.external_sigma, options.input_centered
    weights = _time_weights(sigma, count, grid.spacing, inverse=True)
    spectrum = values[row]
    if not np.all(np.isfinite(spectrum)):
        raise ValueError("The chosen sigma row contains NaN/Inf; it cannot be inverted.")
    print(f"[Laplace] Inverse: {source_name}; row={row}; sigma={sigma}; omega bins={size}; "
          f"output N={count}; dt={grid.spacing}; paired={paired}; centered={centered}", flush=True)
    ordered = cast(ComplexArray, fft.ifftshift(spectrum)) if centered else spectrum
    with np.errstate(over="ignore", invalid="ignore"):
        # Double precision reduces amplification when undoing exponential weights.
        inverse = cast(ComplexArray, fft.ifft(np.asarray(ordered, dtype=np.complex128), norm="backward", workers=1))
        signal = np.asarray((inverse[:count] / grid.spacing) * weights, dtype=np.complex128)
    if not np.all(np.isfinite(signal)):
        raise ValueError("Inverse Laplace overflowed. Use a sigma row nearer zero or rescale the spectrum.")
    history = (replace(record, direction=LaplaceDirection.INVERSE, source_name=source_name, inverse_row=row)
               if paired and record is not None else
               LaplaceRecord(LaplaceDirection.INVERSE, source_name, "Complex", "External complete spectrum",
                             grid, count, size, sigma, sigma, rows, inverse_row=row))
    return TransformResult(Document(document.path, signal, axes=(grid,), laplace=history),
                           name.strip() or f"{source_name} · Inverse Laplace")
