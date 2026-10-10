"""Full-resolution FFT/IFFT operations and reproducible, in-memory provenance.

Requirements: numpy and scipy. Usage: run_transform from a viewer worker.
Generated FFT arrays store centered, complete complex spectra; IFFT accepts
centered or standard external spectra. Rendering never changes these arrays.
Full slices use the selected original row/column across its entire source axis;
cropped slices retain inclusive X/Y bounds and their original coordinate origin.
Real channels independently replace NaN/+Inf/-Inf and finite outliers using
fourier_values; statistics use original finite, in-bound samples. Full complex
input replaces invalid samples as whole complex zeros. Phase uses zero filling.
Neither full complex nor phase input applies value bounds. Other tools sharing
transform_input retain their own preprocessing, with phase bounds also ignored.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from time import perf_counter
from typing import cast

import numpy as np
from scipy import fft
from scipy.signal.windows import get_window

from .coordinates import AxisCoordinates, reciprocal_unit
from .data_model import (Array, ComplexArray, Crop, Document, FloatArray, ImageMember, Limits, RealArray,
                         Selection, ViewMode, _extract, _extract_raw, apply_value_limits,
                         is_phase_view, prepare_frame, select_image_member)
from .fourier_values import FourierValuePolicy, prepare_fourier_values


class TransformDirection(StrEnum):
    FORWARD = "FFT — to frequency domain"
    INVERSE = "IFFT — from frequency domain"


class TransformRange(StrEnum):
    FULL = "Full matrix / signal"
    CROP = "Current X / Y crop"
    FULL_SLICE = "Full 1D Slice"
    SLICE = "Current 1D Slice (within crop)"

    @property
    def is_slice(self) -> bool:
        """Whether the input extracts one source row or column as a 1D signal."""
        return self in (TransformRange.FULL_SLICE, TransformRange.SLICE)

    @property
    def uses_crop(self) -> bool:
        """Whether inclusive source X/Y bounds apply before transformation."""
        return self in (TransformRange.CROP, TransformRange.SLICE)


class TransformWindow(StrEnum):
    NONE = "None"
    HANN = "Hann"
    HAMMING = "Hamming"
    BLACKMAN = "Blackman"


class TransformNorm(StrEnum):
    BACKWARD = "backward"
    ORTHO = "ortho"
    FORWARD = "forward"


@dataclass(frozen=True)
class TransformOptions:
    """Immutable dialog settings; spatial tuples follow array order (Y, X)."""

    direction: TransformDirection = TransformDirection.FORWARD
    range: TransformRange = TransformRange.FULL
    axes: tuple[int, ...] = ()
    spacing: tuple[float, ...] = ()
    units: tuple[str, ...] = ()
    output_shape: tuple[int, ...] = ()
    norm: TransformNorm = TransformNorm.BACKWARD
    window: TransformWindow = TransformWindow.NONE
    subtract_mean: bool = False
    value_policy: FourierValuePolicy = FourierValuePolicy()
    single_precision: bool = False
    display_component: bool = False
    apply_bounds: bool = False
    input_centered: bool = True
    image_key: str | None = None
    row: bool = True
    index: int = 0
    trim_padding: bool = False


@dataclass(frozen=True)
class TransformRecord:
    """Domain/axis history retained independently of the original array buffer."""

    direction: TransformDirection
    source_name: str
    source_channel: str
    source_range: str
    axes: tuple[int, ...]
    input_axes: tuple[AxisCoordinates, ...]
    input_shape: tuple[int, ...]
    output_shape: tuple[int, ...]
    norm: TransformNorm
    centered: bool
    preprocessing: str
    source_record: "TransformRecord | None" = None

    @property
    def description(self) -> str:
        """Readable provenance for source tooltips and the inverse dialog."""
        return (f"{self.direction.value}\nSource: {self.source_name} / {self.source_channel}\n"
                f"Range: {self.source_range}\nShape: {self.input_shape} -> {self.output_shape}\n"
                f"Axes: {self.axes}; norm: {self.norm.value}; centered spectrum: {self.centered}\n"
                f"Source grid (array-axis order): {[(grid.origin, grid.spacing, grid.unit) for grid in self.input_axes]}\n"
                f"Preprocessing: {self.preprocessing}\nPhase origin: first selected sample.")


@dataclass(frozen=True)
class TransformResult:
    """Owned derived document, proposed name and optional explicit interpretation."""

    document: Document
    name: str
    selection: Selection | None = None


@dataclass(frozen=True)
class TransformInput:
    """Selected numeric input, its grid and source-axis correspondence."""

    values: Array
    grids: tuple[AxisCoordinates, ...]
    source_axes: tuple[int, ...]
    range_label: str
    channel_label: str
    explicit_coordinates: bool = False


def transform_input(document: Document, selection: Selection, crop: Crop,
                    options: TransformOptions, limits: Limits = Limits()) -> TransformInput:
    """Extract the chosen channel/region without changing source values.

    Args:
        document: Numeric source or image with retained original pixels.
        selection: Current axis/component interpretation.
        crop: Applied crop; ignored for full matrices/signals and full slices.
        options: Range, component, preprocessing and image-member choices.
        limits: Applied value bounds, used only when explicitly requested.

    Returns:
        Real/complex samples in signal or Y/X order with source coordinates.

    Raises:
        ValueError: Points, unsampled color composites, invalid bounds, or an XY
            sequence with invalid, duplicate or nonuniform coordinates.
    """
    if selection.mode == ViewMode.POINTS:
        raise ValueError("Transforms require a sampled signal or grid, not a point cloud.")
    if document.image_source is not None:
        key = options.image_key or document.key
        if key is None or key in (ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR, ImageMember.MONO_COLOR):
            raise ValueError("Choose a numeric image channel or a grayscale fusion channel.")
        if key != document.key:
            document = select_image_member(document, key)
        selection = replace(selection, channel_axis=None, channel=0)
    region = crop if options.range.uses_crop else Crop()
    explicit = selection.mode == ViewMode.XY
    if explicit:
        frame = prepare_frame(document, selection, Limits(), 2, region)
        assert frame.x_values is not None
        x = np.asarray(frame.x_values, dtype=np.float64)
        if not np.all(np.isfinite(x)) or len(x) < 2:
            raise ValueError("XY input needs at least two finite X coordinates.")
        order = np.argsort(x, kind="stable")
        x = x[order]
        delta = np.diff(x)
        if np.any(delta <= 0):
            raise ValueError("Transforms cannot use repeated X coordinates. Each X must have one sample.")
        spacing = float(np.median(delta))
        if not np.allclose(delta, spacing, rtol=1e-6, atol=spacing * 1e-9):
            raise ValueError("Transforms require uniformly spaced X coordinates. Resample this XY data explicitly first.")
        values = frame.scalar[order]
        grids = (AxisCoordinates(float(x[0]), spacing, "sample"),)
        source_axes = (selection.x_axis,)
    else:
        values = (_extract(document, selection, region)[0] if options.display_component
                  else _extract_raw(document, selection, region))
        if values.ndim not in (1, 2):
            raise ValueError("Select one scalar image/numeric channel before transforming.")
        source_axes = ((selection.y_axis, selection.x_axis) if selection.y_axis is not None else (selection.x_axis,))
        starts = (region.y_start, region.x_start) if values.ndim == 2 else (region.x_start,)
        grids = tuple(replace(document.axes[axis], origin=document.axes[axis].mapping.forward(start))
                      if document.axes else AxisCoordinates(float(start), unit="pixel" if document.is_image else "sample")
                      for axis, start in zip(source_axes, starts, strict=True))
    range_label = f"Crop: {region}" if options.range.uses_crop else "Full input"
    if options.range.is_slice:
        if values.ndim != 2:
            raise ValueError("A row/column slice requires a 2D matrix.")
        local = options.index - (region.y_start if options.row else region.x_start)
        if not 0 <= local < values.shape[0 if options.row else 1]:
            raise ValueError("The selected source slice is outside the input range.")
        values = values[local, :] if options.row else values[:, local]
        along = 1 if options.row else 0
        grids, source_axes = (grids[along],), (source_axes[along],)
        range_label = f"Slice: {'Row' if options.row else 'Column'} {options.index}; {range_label}"
    if options.apply_bounds and not is_phase_view(document, selection):
        if np.iscomplexobj(values):
            raise ValueError("Value bounds require a real display component, not full complex input.")
        if any(bound is not None and not np.isfinite(bound) for bound in (limits.lower, limits.upper)):
            raise ValueError("Value bounds must be finite.")
        if limits.lower is not None and limits.upper is not None and limits.lower > limits.upper:
            raise ValueError("Value minimum exceeds maximum.")
        shown, valid, _ = apply_value_limits(cast(RealArray, values), np.isfinite(values), limits)
        values = np.where(valid, shown, np.nan)
    channel = (document.key or "Value") if document.is_image else (
        selection.component.value if options.display_component else "Complex" if np.iscomplexobj(values) else "Value")
    if selection.channel_axis is not None:
        channel = f"Channel {selection.channel} / {channel}"
    return TransformInput(values, grids, source_axes, range_label, channel, explicit)


def _reciprocal_interval(count: int, spacing: float) -> float:
    period = count * spacing
    if not np.isfinite(period) or period <= 0:
        raise ValueError("The transform sampling period is outside floating-point range. Change the sampling interval.")
    step = 1 / period
    if not np.isfinite(step) or step <= 0:
        raise ValueError("The output sampling interval is outside floating-point range. Change the input sampling interval.")
    return step


def run_transform(document: Document, selection: Selection, crop: Crop, limits: Limits,
                  options: TransformOptions, source_name: str, name: str = "") -> TransformResult:
    """Compute a complete complex FFT/IFFT, preserving enough metadata to invert.

    Args:
        document: Stable source document; its buffer is never overwritten.
        selection: Independent source interpretation.
        crop: Applied source-index crop.
        limits: Applied bounds, only used when requested.
        options: Immutable transform settings in array-axis order.
        source_name: Session alias used in provenance/default result names.
        name: Optional user-selected result alias.

    Returns:
        In-memory document with complex values and uniform physical coordinates.

    Raises:
        ValueError: Invalid grid/axes/size, missing extrema for replacements,
            cropped paired spectrum, overflow, or incompatible inverse settings.
        MemoryError: Insufficient memory for the requested transform.

    Side effects:
        Prints input identity, parameters, sizes and calculation timing.
    """
    started = perf_counter()
    # Extract original values first: bounds must not turn +/-Inf or finite
    # outliers into NaN before their independent treatments are chosen.
    source = transform_input(document, selection, crop, replace(options, apply_bounds=False), limits)
    phase = options.display_component and is_phase_view(document, selection)
    bound_values = options.apply_bounds and not np.iscomplexobj(source.values) and not phase
    values, treatments = prepare_fourier_values(source.values, limits if bound_values else Limits(),
                                                options.value_policy, phase=phase)
    rank = values.ndim
    inverse = options.direction == TransformDirection.INVERSE
    record = document.transform
    paired = inverse and record is not None and record.direction == TransformDirection.FORWARD and not options.display_component
    axes = options.axes or (tuple(i for i, axis in enumerate(source.source_axes) if axis in record.axes)
                            if paired and record is not None else tuple(range(rank)))
    if not axes or len(set(axes)) != len(axes) or any(axis < 0 or axis >= rank for axis in axes):
        raise ValueError("Choose distinct transform axes belonging to this input.")
    shape = options.output_shape or values.shape
    if len(shape) != rank or any(size < values.shape[i] or (i not in axes and size != values.shape[i]) for i, size in enumerate(shape)):
        raise ValueError("Output sizes cannot truncate data or resize an untransformed axis.")
    if inverse and shape != values.shape:
        raise ValueError("IFFT keeps the input spectrum size; padding is available for forward FFT only.")
    if inverse and (options.subtract_mean or options.window != TransformWindow.NONE):
        raise ValueError("Mean removal and windows are forward-FFT preprocessing options.")
    grids = list(source.grids)
    if inverse and not document.axes:
        grids = [replace(grid, unit="cycles/sample", frequency=True) for grid in grids]
    if (options.spacing and len(options.spacing) != rank) or (options.units and len(options.units) != rank):
        raise ValueError("Supply spacing and units for each input axis.")
    for axis in range(rank):
        spacing = options.spacing[axis] if options.spacing else grids[axis].spacing
        if paired:
            spacing = grids[axis].spacing
        if not np.isfinite(spacing) or spacing <= 0:
            raise ValueError("Sampling intervals must be positive and finite.")
        if source.explicit_coordinates and not np.isclose(spacing, grids[axis].spacing, rtol=1e-6):
            raise ValueError("XY sampling interval must match the actual X coordinates.")
        origin = grids[axis].origin * spacing if not document.axes and not source.explicit_coordinates else grids[axis].origin
        grids[axis] = replace(grids[axis], origin=origin, spacing=spacing,
                              unit=options.units[axis] if options.units and not paired else grids[axis].unit)
    dtype = np.complex64 if options.single_precision else np.complex128
    with np.errstate(over="ignore", invalid="ignore"):
        work = np.array(values, dtype=dtype, copy=True)
    if np.any(~np.isfinite(work)):
        raise ValueError("Input overflows the selected precision. Use double precision or rescale the data.")
    if values.dtype.kind in "iu":
        with np.errstate(over="ignore", invalid="ignore"):
            if not np.array_equal(work.real.astype(values.dtype), values):
                raise ValueError("Selected FFT precision would round large integer samples. Use double precision or explicitly rescale the source.")
    notes = list(treatments)
    if bound_values:
        notes.append(f"value bounds: {limits}")
    if options.subtract_mean:
        work -= np.mean(work, axis=axes, keepdims=True)
        notes.append("mean removed")
    if options.window != TransformWindow.NONE:
        for axis in axes:
            window_shape = [1] * rank
            window_shape[axis] = work.shape[axis]
            # SciPy's array-API wrappers obscure the NumPy return type in static analysis.
            weights = cast(FloatArray, get_window(options.window.value.lower(), work.shape[axis], fftbins=True))
            work *= weights.reshape(window_shape)
        notes.append(f"{options.window.value} window")
    norm = record.norm if paired and record is not None else options.norm
    output_grids = list(grids)
    print(f"[Fourier] {options.direction.value}: {source_name} / {source.channel_label}; {source.range_label}; "
          f"shape={values.shape} -> {shape}; axes={axes}; norm={norm.value}; dtype={work.dtype}; "
          f"sampling={[(grid.spacing, grid.unit) for grid in grids]}; preprocessing={'; '.join(notes) or 'None'}", flush=True)
    if inverse:
        if paired and record is not None:
            if any(source.source_axes[axis] not in record.axes for axis in axes):
                raise ValueError("This source axis was not Fourier-transformed. Select its recorded frequency axes.")
            if any(values.shape[axis] != record.output_shape[source.source_axes[axis]] for axis in axes):
                raise ValueError("Paired IFFT requires the complete frequency axis. Choose Full matrix / signal; spatial crop is available after inversion.")
        centered = record.centered if paired and record is not None else options.input_centered
        if centered:
            work = fft.ifftshift(work, axes=axes)
        # NumPy complex input produces an ndarray; the dispatcher body returns a
        # Dispatchable tuple only internally, not to callers of the public API.
        output = cast(ComplexArray, fft.ifftn(work, axes=axes, norm=norm.value, workers=1, overwrite_x=True))
        for axis in axes:
            if paired and record is not None:
                output_grids[axis] = record.input_axes[source.source_axes[axis]]
            else:
                output_grids[axis] = AxisCoordinates(0, _reciprocal_interval(shape[axis], grids[axis].spacing), reciprocal_unit(grids[axis].unit))
        if options.trim_padding and paired and record is not None:
            slices = tuple(slice(0, record.input_shape[source.source_axes[i]]) if i in axes else slice(None) for i in range(rank))
            output = output[slices].copy()
        if paired and record is not None and record.preprocessing != "None":
            notes.append(f"inverse of preprocessed input ({record.preprocessing})")
    else:
        output = cast(ComplexArray, fft.fftn(work, s=tuple(shape[axis] for axis in axes), axes=axes,
                                            norm=norm.value, workers=1, overwrite_x=True))
        output = cast(ComplexArray, fft.fftshift(output, axes=axes))
        for axis in axes:
            step = _reciprocal_interval(shape[axis], grids[axis].spacing)
            output_grids[axis] = AxisCoordinates(-(shape[axis] // 2) * step, step, reciprocal_unit(grids[axis].unit), True)
    if not np.all(np.isfinite(output)):
        raise ValueError("The transform overflowed. Use double precision or rescale the input.")
    history = TransformRecord(options.direction, source_name, source.channel_label, source.range_label,
                              axes, tuple(grids), values.shape, output.shape, norm, not inverse,
                              "; ".join(notes) or "None", record)
    suffix = "IFFT" if inverse else "FFT"
    result_name = name.strip() or f"{source_name} · {source.channel_label} · {suffix}{'2' if len(axes) == 2 else ''}"
    result = Document(document.path, output, axes=tuple(output_grids), transform=history)
    print(f"[Fourier] Finished: {result_name}; shape={output.shape}; dtype={output.dtype}; "
          f"{output.nbytes / 1024**2:.2f} MiB; {(perf_counter()-started)*1000:.1f} ms", flush=True)
    return TransformResult(result, result_name)
