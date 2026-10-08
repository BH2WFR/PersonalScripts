"""Full-resolution exports of visible matrices in aligned display coordinates.

Requirements: numpy and scipy, already used by the viewer.
Usage: imported by the workspace. Each source remains an independent numeric
table; no resampling, blending, screen-resolution sampling or derivative work.
"""

from io import BytesIO
from enum import StrEnum
from pathlib import Path
import re
from typing import cast

import numpy as np
from scipy.io import savemat

from .data_model import RealArray, ViewMode
from .exporting import (ExportLayout, ExportOptions, ExportSnapshot, ExportTarget,
                        _coordinate_table, prepare_export, validate_mat_array)
from .workspace import AxisMap, MatrixEntry, RenderLayer, active_channel, profile_series


class ExportScope(StrEnum):
    """Choose one source matrix or independent tables matching visible results."""

    SELECTED = "Selected matrix"
    VISIBLE = "All visible matrices (as displayed)"


def safe_stem(name: str) -> str:
    """Return a portable filename stem while retaining non-ASCII display names."""
    result = re.sub(r'[^\w.\-]+', "_", name).strip(". _")[:150] or "matrix"
    # These names are reserved on Windows, including when followed by a suffix.
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", result.split(".")[0]):
        result = f"matrix_{result}"
    return result


def default_stem(entry: MatrixEntry, target: ExportTarget, *, displayed: bool = False,
                 row: bool = True, index: int = 0, preserve_complex: bool = False) -> str:
    """Name exports by matrix alias, active channel and processing target."""
    identity = entry.name or Path(entry.document.path.name).stem
    if not entry.name and entry.document.key is not None and not entry.document.is_image:
        identity = f"{identity}_{entry.document.key}"
    if not entry.name and entry.instance > 1:
        identity = f"{identity}_{entry.instance}"
    channel = ("" if target == ExportTarget.ORIGINAL else "_complex"
               if preserve_complex and entry.document.is_complex else f"_{active_channel(entry).label}")
    suffix = ("original" if target == ExportTarget.ORIGINAL else
              f"{'row' if row else 'column'}-{index}" if target == ExportTarget.SLICE else "result")
    return safe_stem(f"{identity}{channel}_{suffix}{'_aligned' if displayed else ''}")


def _mapped(values: RealArray, mapping: AxisMap) -> RealArray:
    """Keep exact coordinate dtype when alignment is the identity."""
    return values if mapping == AxisMap() else mapping.array(values)


def prepare_displayed_export(entry: MatrixEntry, layer: RenderLayer, target: ExportTarget,
                             *, row: bool = True, position: float = 0) -> ExportSnapshot | None:
    """Snapshot one visible result as XY or XYZ in its displayed coordinates.

    Args:
        entry: Matrix identity and interpretation belonging to layer.
        layer: Applied crop, bounds, component and XY alignment snapshot.
        target: Current result or current slice; original is intentionally excluded.
        row: True selects rows when target is a slice.
        position: Common displayed slice position, mapped to each source matrix.

    Returns:
        Independent full-resolution table, or None when this layer has no slice
        at the displayed position. Signal gaps are NaN; nonfinite XYZ rows are
        omitted, as in the existing point-cloud exporter. Z is the data value,
        independent of the 3D height multiplier and camera.

    Raises:
        ValueError: Unsupported target, empty point set or lossy dtype conversion.
        MemoryError: Insufficient memory for the full-resolution output.
    """
    if target == ExportTarget.ORIGINAL:
        raise ValueError("Visible-matrix export requires a current result or slice.")
    sliced = target == ExportTarget.SLICE
    index = 0
    if sliced:
        series = profile_series(layer, row, position)
        if series is None or series.index is None:
            return None
        index = series.index
    signal = sliced or entry.selection.mode in (ViewMode.SIGNAL, ViewMode.XY)
    layout = ExportLayout.XY_COLUMNS if signal else ExportLayout.XYZ_COLUMNS
    snapshot = prepare_export(entry.document, entry.selection, layer.frame,
                              ExportOptions(target, layout, row=row, index=index))
    table = cast(RealArray, snapshot.values)
    if signal:
        mapping = layer.y if sliced and not row else layer.x
        values = _coordinate_table((_mapped(table[:, 0], mapping), table[:, 1]))
    else:
        values = _coordinate_table((_mapped(table[:, 0], layer.x),
                                    _mapped(table[:, 1], layer.y), table[:, 2]))
    return ExportSnapshot(values, default_stem(entry, target, displayed=True, row=row, index=index))


def mat_variable_names(snapshots: tuple[ExportSnapshot, ...]) -> tuple[str, ...]:
    """Create unique ASCII MATLAB identifiers of at most 63 characters."""
    names: list[str] = []
    for snapshot in snapshots:
        base = re.sub(r"[^a-zA-Z0-9_]", "_", snapshot.stem).strip("_") or "matrix"
        if not base[0].isalpha():
            base = f"matrix_{base}"
        name, suffix = base[:63], 2
        while name in names:
            ending = f"_{suffix}"
            name = f"{base[:63-len(ending)]}{ending}"
            suffix += 1
        names.append(name)
    return tuple(names)


def serialize_displayed_mat(snapshots: tuple[ExportSnapshot, ...]) -> bytes:
    """Save independent visible tables as uniquely named MATLAB Level 5 variables.

    Args:
        snapshots: Owned real-valued XY/XYZ tables in displayed coordinates.

    Returns:
        MAT bytes containing one numeric variable per snapshot.

    Raises:
        ValueError: No snapshots or precision unsupported by MATLAB Level 5.
    """
    if not snapshots:
        raise ValueError("No visible matrices to export.")
    for snapshot in snapshots:
        validate_mat_array(snapshot.values)
    buffer = BytesIO()
    matrices = {name: item.values for name, item in zip(mat_variable_names(snapshots), snapshots, strict=True)}
    savemat(buffer, matrices, appendmat=False, do_compression=True, oned_as="column", long_field_names=True)
    return buffer.getvalue()
