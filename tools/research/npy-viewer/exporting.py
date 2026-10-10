"""Prepare full-resolution arrays, numeric files and normalized grayscale images.

Requirements: numpy, scipy, Pillow and openpyxl (already used by the viewer).
Usage: imported by app; functions never modify source arrays or open dialogs.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from io import BytesIO, StringIO
import math
from pathlib import Path
import re
from typing import cast

import numpy as np
from PIL import Image
from scipy.io import savemat

from .data_model import (Array, Crop, Document, ExportMode, FilterMode, Frame, RealArray,
                         Selection, ViewMode, apply_value_limits, export_array, prepare_frame)
from .excel_io import serialize_excel


class ExportTarget(StrEnum):
    """Source of the exported values."""

    RESULT = "Current matrix / signal (cropped)"
    SLICE = "Selected row / column"
    ORIGINAL = "Original source matrix"


class ExportLayout(StrEnum):
    """Storage layout, independent of the selected file format."""

    ARRAY = "Array (keep shape)"
    XY_COLUMNS = "XY: two columns (N x 2)"
    XY_ROWS = "XY: two rows (2 x N)"
    XYZ_COLUMNS = "Point cloud: columns (N x 3)"
    XYZ_ROWS = "Point cloud: rows (3 x N)"


class ExportFormat(StrEnum):
    """Output formats; NPZ is for workspace bundles, TXT is tab-separated."""

    NPY = "npy"
    NPZ = "npz"
    MAT = "mat"
    XLSX = "xlsx"
    CSV = "csv"
    TXT = "txt"
    PNG = "png"
    BMP = "bmp"


@dataclass(frozen=True)
class ExportOptions:
    """Export choices captured before any modal dialog or background work."""

    target: ExportTarget = ExportTarget.RESULT
    layout: ExportLayout = ExportLayout.ARRAY
    crop_xy: bool = True
    bound_values: bool = True
    row: bool = True
    index: int = 0
    preserve_complex: bool = False
    preserve_channels: bool = False


@dataclass(frozen=True)
class ExportSnapshot:
    """Owned array and descriptive name, isolated from subsequent GUI changes."""

    values: Array
    stem: str


def _coordinate_table(columns: tuple[RealArray, ...]) -> RealArray:
    """Stack coordinates without silently rounding integer values during promotion."""
    dtype = np.result_type(*(column.dtype for column in columns))
    if dtype.kind == "f" and all(column.dtype.kind in "biu" for column in columns):
        minimum = min(int(np.min(column)) for column in columns)
        maximum = max(int(np.max(column)) for column in columns)
        if minimum >= 0:
            dtype = np.dtype(np.uint64)
        elif maximum <= np.iinfo(np.int64).max:
            dtype = np.dtype(np.int64)
        else:
            raise ValueError("Signed coordinates and uint64 values cannot share an exact numeric dtype.")
    converted = [column.astype(dtype, copy=False) for column in columns]
    for source, result in zip(columns, converted, strict=True):
        if source.dtype.kind in "biu" and dtype.kind == "f":
            with np.errstate(invalid="ignore", over="ignore"):
                if not np.array_equal(result.astype(source.dtype), source):
                    raise ValueError("Coordinate layout would lose integer precision. Export the array without coordinates.")
    return np.column_stack(converted)


def prepare_export(document: Document, selection: Selection, frame: Frame,
                   options: ExportOptions) -> ExportSnapshot:
    """Freeze the requested source, crop, slice and coordinate layout.

    Args:
        document: Selected source array/member; original export keeps its dtype.
        selection: Axis/component interpretation belonging to frame.
        frame: Last successfully prepared frame, including applied value bounds.
        options: Target, layout, independent XY/value processing, and slice index.

    Returns:
        Independent array plus a filesystem-safe default filename stem.

    Raises:
        ValueError: Unsupported layout, absent slice, or lossy numeric conversion.
        MemoryError: Insufficient memory for a full-resolution snapshot.
    """
    parts = [document.path.stem]
    if document.key and not (options.preserve_channels and document.is_image):
        parts.append(document.key)
    origin_x = origin_y = 0
    x_values: RealArray | None = None
    cloud = False
    xy = False
    selected = frame
    all_channels = options.preserve_channels and options.target != ExportTarget.SLICE
    source = document.image_source.pixels if all_channels and document.image_source is not None else document.array
    if options.target == ExportTarget.ORIGINAL:
        values = source.copy()
        parts.append("original")
    else:
        if not options.crop_xy:
            selected = prepare_frame(document, selection, frame.value_limits, 2, Crop(), max_points=1)
        origin_x, origin_y = selected.x_start, selected.y_start
        mode = ExportMode.PROCESSED if options.bound_values else ExportMode.CROP
        if all_channels:
            if options.layout != ExportLayout.ARRAY:
                raise ValueError("Whole multichannel matrices require Array layout. Export a channel for coordinate layouts.")
            slices = [slice(None)] * source.ndim
            x_axis, y_axis = selection.x_axis, selection.y_axis
            if options.crop_xy:
                slices[x_axis] = slice(selected.x_start, selected.x_start + selected.scalar.shape[-1])
                if y_axis is not None:
                    slices[y_axis] = slice(selected.y_start, selected.y_start + selected.scalar.shape[0])
            values = source[tuple(slices)].copy()
            if np.iscomplexobj(values):
                if options.bound_values:
                    raise ValueError("Complex values have no ordered Z interval. Disable value bounds or export a display component.")
                if not options.preserve_complex:
                    raise ValueError("Export a channel to select a real component of a complex multichannel matrix.")
            elif options.bound_values:
                real = cast(RealArray, values)
                display, valid, clipped = apply_value_limits(real, np.isfinite(real), selected.value_limits)
                values = export_array(replace(selected, scalar=real, raw=real, valid=valid,
                                              display_scalar=display, clip_kind=clipped, xy=False,
                                              point_coordinates=None), ExportMode.PROCESSED)
            parts.append("all-channels")
        elif options.preserve_complex and document.is_complex:
            if options.bound_values:
                raise ValueError("Complex values have no ordered Z interval. Disable value bounds or export a display component.")
            if selected.raw is None:
                raise ValueError("No complex source values are available.")
            values = selected.raw.copy()
        elif selection.mode == ViewMode.POINTS:
            coordinates = selected.point_coordinates
            if coordinates is None:
                raise ValueError("No point coordinates are available.")
            z = export_array(replace(selected, point_coordinates=None), mode)
            values = _coordinate_table((coordinates[:, 0], coordinates[:, 1], z))
            cloud = True
        else:
            values = export_array(selected, mode)
            xy = selected.xy
            x_values = selected.x_values
        if document.is_complex:
            parts.append("complex" if options.preserve_complex else selection.component.value)
        if options.target == ExportTarget.SLICE:
            if selection.mode != ViewMode.MATRIX:
                raise ValueError("Slice export requires a selected matrix row or column.")
            local = options.index - (origin_y if options.row else origin_x)
            if not 0 <= local < values.shape[0 if options.row else 1]:
                raise ValueError("The selected slice is outside the exported region.")
            values = values[local, :] if options.row else values[:, local]
            grid = selected.x_grid if options.row else selected.y_grid
            start = selected.x_start if options.row else selected.y_start
            x_values = grid.values(start, len(values)) if grid is not None else None
            origin_x = origin_x if options.row else origin_y
            parts.append(f"{'row' if options.row else 'column'}-{options.index}")
        else:
            parts.append("result")
        if options.crop_xy:
            width = selected.scalar.shape[-1]
            parts.append(f"x{selected.x_start}-{selected.x_start + width - 1}")
            if selected.scalar.ndim == 2:
                parts.append(f"y{selected.y_start}-{selected.y_start + selected.scalar.shape[0] - 1}")
        if options.bound_values:
            lower, upper = selected.value_limits.lower, selected.value_limits.upper
            parts.append(f"z{lower if lower is not None else 'min'}-{upper if upper is not None else 'max'}")
            parts.append("clamp" if selected.value_limits.mode == FilterMode.CLAMP else "hide")

    # ── output layout; coordinates remain in source units ──
    if options.layout in (ExportLayout.XY_COLUMNS, ExportLayout.XY_ROWS):
        if xy:
            table = values
        elif values.ndim == 1 and not np.iscomplexobj(values):
            x = np.arange(origin_x, origin_x + len(values), dtype=np.int64) if x_values is None else x_values
            table = _coordinate_table((x, cast(RealArray, values)))
        else:
            raise ValueError("XY export requires a real one-dimensional signal or an XY view.")
        values = table.T if options.layout == ExportLayout.XY_ROWS else table
        parts.append("xy-rows" if options.layout == ExportLayout.XY_ROWS else "xy-columns")
    elif options.layout in (ExportLayout.XYZ_COLUMNS, ExportLayout.XYZ_ROWS):
        if cloud:
            table = values
        elif values.ndim == 2 and not np.iscomplexobj(values) and not xy:
            y, x = np.indices(values.shape, dtype=np.int64)
            x_coordinates = selected.x_mapping.array((x + origin_x).ravel()) if options.target != ExportTarget.ORIGINAL and selected.x_grid is not None else (x + origin_x).ravel()
            y_coordinates = selected.y_mapping.array((y + origin_y).ravel()) if options.target != ExportTarget.ORIGINAL and selected.y_grid is not None else (y + origin_y).ravel()
            table = _coordinate_table((x_coordinates, y_coordinates,
                                       cast(RealArray, values).ravel()))
        else:
            raise ValueError("Point-cloud export requires a real 2D matrix or an XYZ view.")
        table = table[np.all(np.isfinite(table), axis=1)]
        if not len(table):
            raise ValueError("No finite points remain to export.")
        values = table.T if options.layout == ExportLayout.XYZ_ROWS else table
        parts.append("xyz-rows" if options.layout == ExportLayout.XYZ_ROWS else "xyz-columns")
    elif options.layout != ExportLayout.ARRAY:
        raise ValueError(f"Unsupported export layout: {options.layout}")
    stem = re.sub(r'[^\w.\-]+', "_", "_".join(parts)).strip(". _")[:180]
    # All branches already own their buffers (slice/transpose views reference
    # those copies). Avoid another full-size copy for large XYZ exports.
    return ExportSnapshot(values, stem or "matrix_export")


def output_paths(path: Path, values: Array, format_: ExportFormat) -> tuple[Path, ...]:
    """Resolve actual destinations, splitting complex text into real/imag files.

    Args:
        path: User-selected filename; its suffix must match format_.
        values: Snapshot used to determine whether text needs two files.
        format_: Explicit chosen output format.

    Returns:
        One path, or two same-directory paths suffixed _real and _imag.
    """
    if format_ in (ExportFormat.CSV, ExportFormat.TXT) and np.iscomplexobj(values):
        return tuple(path.with_name(f"{path.stem}_{part}{path.suffix}") for part in ("real", "imag"))
    return (path,)


def serialize_array(values: Array, format_: ExportFormat) -> bytes:
    """Serialize a numeric array without silently discarding complex components.

    Args:
        values: Numeric snapshot; complex text must be split by the caller.
        format_: NPY, MATLAB Level 5, XLSX, CSV/TXT, or normalized PNG/BMP.

    Returns:
        Complete file contents. MAT/XLSX store 'matrix' and 1D as a column.
        Complex XLSX uses matrix_real/matrix_imag worksheets.

    Raises:
        ValueError: Text with complex or higher-dimensional data, unsupported MAT
            precision, or unsupported format. Use NPY for exact arbitrary dtypes.
    """
    if format_ == ExportFormat.NPY:
        buffer = BytesIO()
        np.save(buffer, values, allow_pickle=False)
        return buffer.getvalue()
    if format_ == ExportFormat.MAT:
        validate_mat_array(values)
        buffer = BytesIO()
        savemat(buffer, {"matrix": values}, appendmat=False, do_compression=True, oned_as="column")
        return buffer.getvalue()
    if format_ == ExportFormat.XLSX:
        return serialize_excel((("matrix", values),))
    if format_ in (ExportFormat.PNG, ExportFormat.BMP):
        pixels = normalized_grayscale(values)
        buffer = BytesIO()
        Image.fromarray(pixels).save(buffer, format=format_.value.upper())
        return buffer.getvalue()
    if format_ not in (ExportFormat.CSV, ExportFormat.TXT):
        raise ValueError(f"Unsupported format: {format_}")
    if values.ndim not in (1, 2) or np.iscomplexobj(values):
        raise ValueError("Text requires a real 1D/2D matrix. Select an image channel or split complex components.")
    text = StringIO()
    # Decimal integer formatting preserves uint64; floating point uses sufficient
    # significant digits for its dtype, independently of compact plot labels.
    precision = 0
    if values.dtype.kind == "f":
        # The kind check does not narrow Array's dtype union for static typing;
        # its canonical name selects finfo's string overload without conversion.
        precision = math.ceil(1 + (np.finfo(values.dtype.name).nmant + 1) * math.log10(2))
    np.savetxt(text, values, fmt=f"%.{precision}g" if precision else "%d",
               delimiter="," if format_ == ExportFormat.CSV else "\t")
    return text.getvalue().encode("utf-8")


def normalized_grayscale(values: Array) -> np.ndarray[tuple[int, ...], np.dtype[np.uint8]]:
    """Map finite 2D real values to an 8-bit grayscale image without modifying them.

    Args:
        values: A nonempty real numeric matrix, after requested crop/bounds.

    Returns:
        Same-shaped uint8 pixels. Finite min/max map to 0/255 with rounding;
        constants and nonfinite gaps map to black. No transpose or resizing.

    Raises:
        ValueError: Complex, nonnumeric, non-2D, empty or entirely nonfinite data.
    """
    if values.ndim != 2 or not values.size or values.dtype.kind not in "biuf":
        raise ValueError("PNG/BMP require a nonempty real 2D matrix. Export a real-valued channel first.")
    real = cast(RealArray, values)
    finite = np.isfinite(real)
    if not np.any(finite):
        raise ValueError("Cannot normalize a matrix with no finite values.")
    pixels = np.zeros(values.shape, dtype=np.uint8)
    samples = real[finite]
    low, high = samples.min(), samples.max()
    if low == high:
        return pixels
    if values.dtype.kind in "iu":
        # Subtract in modular uint64 before converting to float: close values
        # near uint64.max must not collapse to a constant in float64.
        offset = samples.astype(np.uint64) - np.uint64(int(low) % (1 << 64))
        unit = offset.astype(np.float64) / (int(high) - int(low))
    else:
        data = samples.astype(np.longdouble)
        lower, upper = np.longdouble(low), np.longdouble(high)
        with np.errstate(over="ignore"):
            span = upper - lower
        if np.isfinite(span):
            unit = (data - lower) / span
        else:
            scale = max(abs(lower), abs(upper))
            unit = (data / scale - lower / scale) / (upper / scale - lower / scale)
    pixels[finite] = np.rint(np.clip(unit, 0, 1) * 255).astype(np.uint8)
    return pixels


def validate_mat_array(values: Array) -> None:
    """Reject extended precision that MATLAB Level 5 cannot preserve.

    Args:
        values: Numeric array to serialize.

    Raises:
        ValueError: Float or complex precision exceeds MATLAB double precision.
    """
    if (values.dtype.kind == "f" and values.dtype.itemsize > 8
            or values.dtype.kind == "c" and values.dtype.itemsize > 16):
        raise ValueError("MAT cannot preserve this extended precision. Use NPY instead.")
