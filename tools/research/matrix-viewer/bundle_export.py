"""Pack all workspace source matrices into a numeric NPZ, MAT or XLSX file.

Requirements: numpy, scipy and openpyxl, already used by the viewer. Usage:
prepare_bundle and serialize_bundle inside the existing export worker. Each
matrix group is supplied once, including hidden and generated matrices. Views,
crops, bounds, display components and transform metadata are not serialized.
Native image channels become separate 2D arrays so every bundle can be reopened
as ordinary matrices. Complex values remain complex in NPZ/MAT; XLSX uses the
existing real/imaginary worksheet convention. No pickle/object arrays are used.
"""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np

from .data_model import Array, Document
from .excel_io import serialize_excel
from .exporting import ExportFormat, ExportSnapshot
from .workspace_export import safe_stem, serialize_displayed_mat

BUNDLE_FORMATS: tuple[ExportFormat, ...] = (ExportFormat.NPZ, ExportFormat.MAT, ExportFormat.XLSX)


def prepare_bundle(sources: tuple[tuple[str, Document], ...]) -> tuple[ExportSnapshot, ...]:
    """Copy full source arrays once per supplied matrix group.

    Args:
        sources: Stable names/documents, one per workspace matrix in list order.
            Callers retain unchecked matrices and consolidate display channels.

    Returns:
        Independent named 1D/2D numeric arrays; image pixels split into their
        native channels without grayscale conversion or alpha weighting.

    Raises:
        ValueError: No matrices or unsupported nonnumeric/empty/higher-rank data.
        MemoryError: Insufficient memory for independent array snapshots.

    Side effects:
        Allocates copies. Does not modify sources or write files.
    """
    snapshots: list[ExportSnapshot] = []
    for name, document in sources:
        image = document.image_source
        arrays: tuple[tuple[str, Array], ...]
        if image is None:
            arrays = ((name, document.array),)
        elif image.pixels.ndim == 2:
            arrays = ((f"{name} / {image.channels[0].value}", image.pixels),)
        else:
            arrays = tuple((f"{name} / {channel.value}", image.pixels[..., index])
                           for index, channel in enumerate(image.channels))
        for label, values in arrays:
            if values.ndim not in (1, 2) or not values.size or values.dtype.kind not in "buifc":
                raise ValueError(f"{label}: bundles require nonempty numeric 1D/2D arrays; got {values.shape}, {values.dtype}.")
            snapshots.append(ExportSnapshot(values.copy(), label))
    if not snapshots:
        raise ValueError("No matrices to save.")
    return tuple(snapshots)


def npz_member_names(snapshots: tuple[ExportSnapshot, ...]) -> tuple[str, ...]:
    """Return portable, unique archive keys derived from matrix names.

    Args:
        snapshots: Named arrays in stable list order.

    Returns:
        Keys without directories; collisions after sanitization gain _2, _3, etc.
    """
    names: list[str] = []
    used: set[str] = set()
    for snapshot in snapshots:
        base = safe_stem(snapshot.stem)
        name, suffix = base, 2
        while name in used:
            name, suffix = f"{base}_{suffix}", suffix + 1
        names.append(name)
        used.add(name)
    return tuple(names)


def serialize_bundle(snapshots: tuple[ExportSnapshot, ...], format_: ExportFormat) -> bytes:
    """Serialize independent matrices into one archive without merging shapes.

    Args:
        snapshots: Owned numeric arrays returned by prepare_bundle.
        format_: NPZ, MAT or XLSX; no ordinary NPY/object-array packaging.

    Returns:
        Complete file bytes for the viewer's atomic writer. NPZ preserves shape
        and dtype; MAT/XLSX store 1D as columns. Names follow format constraints
        and are disambiguated. XLSX splits complex matrices into real/imag sheets.

    Raises:
        ValueError: No data, unsupported format or a format's size/precision limit.
        MemoryError: Insufficient serialization memory.
    """
    if not snapshots:
        raise ValueError("No matrices to save.")
    if format_ == ExportFormat.MAT:
        return serialize_displayed_mat(snapshots)
    if format_ == ExportFormat.XLSX:
        return serialize_excel(tuple((item.stem, item.values) for item in snapshots))
    if format_ != ExportFormat.NPZ:
        raise ValueError("Choose NPZ, MAT or XLSX to package multiple matrices. NPY stores a single array.")
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, allowZip64=True) as archive:
        # Write NPY members directly: names such as 'file' and 'allow_pickle'
        # remain ordinary matrix keys, without colliding with savez arguments.
        for name, snapshot in zip(npz_member_names(snapshots), snapshots, strict=True):
            with archive.open(f"{name}.npy", "w", force_zip64=True) as stream:
                np.lib.format.write_array(stream, snapshot.values, allow_pickle=False)
    return buffer.getvalue()
