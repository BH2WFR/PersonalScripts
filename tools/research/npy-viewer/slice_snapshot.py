"""Independent in-memory 1D documents captured from displayed matrix slices.

Requirements: numpy, already used by the viewer. Usage: freeze_slice from the
workspace's slice context menu. Copy the selected scalar/image trace at full
resolution, retaining original nonfinite values and affine display coordinates.
Complex sources can instead copy the corresponding raw complex slice, preserving
both parts in one 1D array. Scalar copies retain value bounds as independent
settings; complex copies ignore those channel-specific bounds, as file exports do.
No source array, frame, transform history or file handle is retained by the copy;
the path and provenance identify its source but no file is created.
"""

from dataclasses import replace

import numpy as np

from .coordinates import AxisCoordinates, AxisMap
from .data_model import Array, Document, Frame, RealArray


def freeze_slice(document: Document, frame: Frame, values: RealArray, *, row: bool,
                 index: int, name: str, alignment: AxisMap = AxisMap(),
                 preserve_complex: bool = False) -> Document:
    """Copy a scalar or complex slice and preserve its sampled X coordinates.

    Args:
        document: Original source; only its path is retained in the result.
        frame: Applied matrix crop and coordinate grids belonging to the trace.
        values: Full-resolution scalar channel, before value bounds. For image
            color views this includes any alpha weighting already displayed.
        row: True for a row, False for a column.
        index: Absolute source row/column index, before cropping or alignment.
        name: Source/channel identity for provenance.
        alignment: Current horizontal display mapping; identity by default.
        preserve_complex: Copy the raw complex slice instead of the scalar
            trace; default False. Requires a complex source and matching raw frame.

    Returns:
        Independent 1D document with its own array and uniform coordinate grid.
        Scalar bounds are recorded for the workspace to retain as settings;
        complex data retains both parts without applying channel value bounds.

    Raises:
        ValueError: Non-matrix frame, absent slice, mismatched trace length, or
            invalid alignment coordinates, or unavailable raw complex values.
        MemoryError: The array cannot be copied.
    """
    if frame.scalar.ndim != 2 or values.ndim != 1:
        raise ValueError("A Slice snapshot requires a 2D matrix and a 1D trace.")
    across = 0 if row else 1
    origin = frame.y_start if row else frame.x_start
    if not origin <= index < origin + frame.scalar.shape[across]:
        raise ValueError("The selected Slice is outside the current crop.")
    if len(values) != frame.scalar.shape[1 - across]:
        raise ValueError("The Slice trace does not match the current matrix crop.")
    copied_values: Array = values
    if preserve_complex:
        raw = frame.raw
        if not document.is_complex or raw is None or raw.dtype.kind != "c" or raw.shape != frame.scalar.shape:
            raise ValueError("The original complex values for this Slice are unavailable.")
        local = index - origin
        copied_values = raw[local, :] if row else raw[:, local]
    start = frame.x_start if row else frame.y_start
    grid = (frame.x_grid if row else frame.y_grid) or AxisCoordinates(unit="pixel" if document.is_image else "sample")
    mapping = grid.mapping.then(alignment)
    frozen_grid = replace(grid, origin=mapping.forward(start), spacing=mapping.scale)
    if not np.isfinite(frozen_grid.origin) or not np.isfinite(frozen_grid.spacing) or frozen_grid.spacing <= 0:
        raise ValueError("Slice coordinates must be finite with positive spacing.")
    bounds = "ignored for complex data" if preserve_complex else str(frame.value_limits)
    representation = "Complex data (real + imaginary)" if preserve_complex else "Displayed scalar channel"
    provenance = (
        f"Slice snapshot: {name}\nSource file: {document.path}\n"
        f"Representation: {representation}\n"
        f"{'Row' if row else 'Column'}: {index}; source sample indices: {start}..{start + len(values) - 1}\n"
        f"Retained value bounds: {bounds}\nDisplay alignment: {alignment}\n"
        "Independent in-memory 1D copy; source changes/removal do not affect it. No file was saved.")
    return Document(document.path, copied_values.copy(), axes=(frozen_grid,), import_provenance=provenance)
