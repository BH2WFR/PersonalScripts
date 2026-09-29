"""Load numeric data and prepare linked views without changing source values.

Requirements: numpy and opencv-python.
Usage: imported by the viewer; CPU preparation can run in a worker thread.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

type IntegerScalar = (np.int8 | np.int16 | np.int32 | np.int64 | np.longlong
                      | np.uint8 | np.uint16 | np.uint32 | np.uint64 | np.ulonglong)
type RealScalar = np.bool_ | IntegerScalar | np.float16 | np.float32 | np.float64 | np.longdouble
type ComplexScalar = np.complex64 | np.complex128 | np.clongdouble
type Array = NDArray[RealScalar | ComplexScalar]
type RealArray = NDArray[RealScalar]
type ComplexArray = NDArray[ComplexScalar]
type FloatArray = NDArray[np.float64]
type BoolArray = NDArray[np.bool_]
type IndexArray = NDArray[np.int64]
type ClipArray = NDArray[np.int8]

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"})
COLORMAPS: tuple[str, ...] = ("viridis", "cividis", "gray", "plasma", "inferno", "magma", "turbo", "coolwarm")
NUMERIC_KINDS = frozenset("buifc")
DEFAULT_CLIP_COLOR = "#ff0000"


class FilterMode(StrEnum):
    """Treatment of finite values outside the selected numeric interval."""

    CLAMP = "Clamp + highlight"
    HIDE = "Hide outside"


class ViewMode(StrEnum):
    """Interpretation of spatial dimensions, independent of array rank."""

    MATRIX = "matrix"
    SIGNAL = "signal"


class Component(StrEnum):
    """Real-valued representation of a complex array."""

    REAL = "Real"
    IMAGINARY = "Imaginary"
    MAGNITUDE = "Magnitude"
    PHASE = "Phase (rad)"


@dataclass(frozen=True)
class Document:
    """An open numeric array and the archive/image metadata needed by the UI.

    NPY arrays may be read-only memory maps. NPZ contains only the selected
    member in memory; the ZIP file is closed before this object is returned.
    """

    path: Path
    array: Array
    keys: tuple[str, ...] = ()
    key: str | None = None
    is_image: bool = False


@dataclass(frozen=True)
class Selection:
    """Axis assignment and indices into the original array.

    x_axis is the sample/column axis; y_axis is the row axis. A channel index
    of -1 requests RGB composition, with luminance for the surface/profile.
    Other, unused axes are indexed by the matching entries in slices.
    """

    mode: ViewMode
    x_axis: int
    y_axis: int | None
    channel_axis: int | None
    channel: int
    slices: tuple[int, ...]
    component: Component = Component.REAL


@dataclass(frozen=True)
class Limits:
    """Inclusive bounds with optional visual clamping; None leaves a bound open."""

    lower: float | None = None
    upper: float | None = None
    mode: FilterMode = FilterMode.HIDE


@dataclass(frozen=True)
class Crop:
    """Inclusive spatial/sample index bounds in the selected source axes.

    An end of None means the last source index. Y bounds apply only to matrices;
    signal mode uses X. Bounds always refer to the original selected array,
    so applying another crop never accumulates offsets.
    """

    x_start: int = 0
    x_end: int | None = None
    y_start: int = 0
    y_end: int | None = None


@dataclass(frozen=True)
class SurfaceData:
    """Sampled mesh with a direct map from mesh vertices to original pixels."""

    points: FloatArray
    faces: IndexArray
    rows: IndexArray
    columns: IndexArray
    valid: BoolArray
    sampled_shape: tuple[int, int]


@dataclass(frozen=True)
class Frame:
    """Prepared region with source coordinates and original scalar precision.

    Scalar/image buffers are local to the crop. Mesh coordinates and source
    row/column mappings are absolute, using x_start and y_start as the origin.
    """

    scalar: RealArray
    valid: BoolArray
    image: RealArray | None
    limits: tuple[float, float]
    surface: SurfaceData | None
    composite: bool
    display_scalar: RealArray
    clip_kind: ClipArray
    value_limits: Limits
    clip_outline: BoolArray | None = None
    x_start: int = 0
    y_start: int = 0


def load_document(path: Path, key: str | None = None) -> Document:
    """Read one array or image, preserving numeric precision and image channels.

    Args:
        path: Existing NPY, NPZ or supported image file.
        key: NPZ member to load; None chooses the first member.

    Returns:
        Document containing numeric data, with RGB(A) image channel ordering.

    Raises:
        ValueError: Empty, nonnumeric, unsupported or undecodable data.
        OSError: The file cannot be read.
        KeyError: The requested NPZ member does not exist.
    """
    suffix = path.suffix.lower()
    keys: tuple[str, ...] = ()
    image = suffix in IMAGE_EXTENSIONS
    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as archive:
            keys = tuple(archive.files)
            if not keys:
                raise ValueError("The NPZ archive has no arrays.")
            if key is not None:
                array = archive[key]
            else:
                # Metadata/object/empty members should not hide usable arrays.
                for candidate in keys:
                    try:
                        member = archive[candidate]
                    except ValueError:
                        continue
                    if member.dtype.kind in NUMERIC_KINDS and member.size:
                        key, array = candidate, member
                        break
                else:
                    raise ValueError("The NPZ archive has no nonempty numeric arrays.")
    elif suffix == ".npy":
        array = np.load(path, allow_pickle=False, mmap_mode="r")
    elif image:
        # Decode bytes for Unicode paths and preserve 16-bit image data.
        decoded = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None:
            raise ValueError("The image could not be decoded.")
        array = decoded
        if array.ndim == 3 and array.shape[-1] in (3, 4):
            order = [2, 1, 0] if array.shape[-1] == 3 else [2, 1, 0, 3]
            array = array[..., order]
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")
    if array.dtype.kind not in NUMERIC_KINDS:
        raise ValueError(f"Numeric arrays are required, got {array.dtype}.")
    if array.size == 0:
        raise ValueError("The selected array is empty.")
    if array.ndim == 0:
        array = array.reshape(1)
    return Document(path, cast(Array, array), keys, key, image)


def default_selection(document: Document, mode: ViewMode | None = None,
                      channel_axis: int | None = None) -> Selection:
    """Choose an editable initial axis assignment without squeezing dimensions.

    Args:
        document: Source array and image metadata.
        mode: Requested interpretation; None chooses by rank.
        channel_axis: Explicit channel axis; negative indices are accepted.

    Returns:
        Valid selection using trailing spatial axes and zero extra-axis slices.

    Raises:
        ValueError: The requested axes leave insufficient spatial dimensions.
    """
    shape = document.array.shape
    rank = len(shape)
    mode = mode or (ViewMode.SIGNAL if rank == 1 else ViewMode.MATRIX)
    if channel_axis is not None:
        if not -rank <= channel_axis < rank:
            raise ValueError("Channel axis is out of range.")
        channel_axis %= rank
    elif document.is_image and rank == 3:
        channel_axis = 2
    elif mode == ViewMode.MATRIX and rank == 3:
        channel_axis = min(reversed(range(rank)), key=lambda axis: shape[axis])
    elif mode == ViewMode.SIGNAL and rank >= 2:
        channel_axis = min(reversed(range(rank)), key=lambda axis: shape[axis])
    spatial = [axis for axis in range(rank) if axis != channel_axis]
    needed = 2 if mode == ViewMode.MATRIX else 1
    if len(spatial) < needed:
        raise ValueError("Not enough spatial axes; select signal mode or disable the channel axis.")
    rgb = document.is_image and channel_axis is not None and shape[channel_axis] in (3, 4)
    return Selection(mode, spatial[-1], spatial[-2] if needed == 2 else None,
                     channel_axis, -1 if rgb else 0, (0,) * rank)


def _crop_slice(start: int, end: int | None, size: int, label: str) -> slice:
    end = size - 1 if end is None else end
    if not 0 <= start <= end < size:
        raise ValueError(f"{label} crop must satisfy 0 <= start <= end < {size}; got {start}..{end}.")
    return slice(start, end + 1)


def _extract(document: Document, selection: Selection, crop: Crop) -> tuple[RealArray, RealArray | None]:
    axes = [selection.x_axis]
    if selection.y_axis is not None:
        axes.insert(0, selection.y_axis)
    if selection.channel_axis is not None:
        axes.append(selection.channel_axis)
    if len(set(axes)) != len(axes):
        raise ValueError("Row, column/sample and channel axes must be different.")
    rank = document.array.ndim
    if any(axis < 0 or axis >= rank for axis in axes):
        raise ValueError("Axis number is outside the array dimensions.")
    # Crop before channel conversion, luminance and complex components so large
    # source arrays do not require full-size derived buffers for a small region.
    x_slice = _crop_slice(crop.x_start, crop.x_end, document.array.shape[selection.x_axis], "X")
    y_slice = (_crop_slice(crop.y_start, crop.y_end, document.array.shape[selection.y_axis], "Y")
               if selection.y_axis is not None else slice(None))
    indices = tuple(
        x_slice if axis == selection.x_axis else
        y_slice if axis == selection.y_axis else
        slice(None) if axis == selection.channel_axis else selection.slices[axis]
        for axis in range(rank)
    )
    remaining = sorted(axes)
    data = document.array[indices].transpose(tuple(remaining.index(axis) for axis in axes))
    rgb: RealArray | None = None
    if selection.channel_axis is not None:
        if selection.channel == -1:
            if selection.mode != ViewMode.MATRIX or data.shape[-1] not in (3, 4) or np.iscomplexobj(data):
                raise ValueError("RGB composition requires 3 or 4 real-valued channels in matrix mode.")
            rgb = cast(RealArray, data)  # The complex-dtype guard above establishes real RGB data.
            data = np.asarray(data[..., :3], dtype=np.float64) @ np.array([0.2126, 0.7152, 0.0722])
        else:
            data = data[..., selection.channel]
    if np.iscomplexobj(data):
        complex_data = cast(ComplexArray, data)  # NumPy's predicate is not a static TypeGuard.
        match selection.component:
            case Component.REAL:
                data = complex_data.real
            case Component.IMAGINARY:
                data = complex_data.imag
            case Component.MAGNITUDE:
                data = np.abs(complex_data)
            case Component.PHASE:
                data = np.angle(complex_data)
    # Every complex branch above produces a real component without coercing integers.
    return cast(RealArray, data), rgb


def _surface(data: RealArray, valid: BoolArray, max_edge: int,
             x_start: int = 0, y_start: int = 0) -> SurfaceData:
    height, width = data.shape
    scale = min(1.0, max_edge / max(height, width)) if max_edge else 1.0
    ny, nx = max(1, int(height * scale)), max(1, int(width * scale))
    if height > 1:
        ny = max(2, ny)
    if width > 1:
        nx = max(2, nx)
    ys = np.linspace(0, height - 1, ny, dtype=np.int64)
    xs = np.linspace(0, width - 1, nx, dtype=np.int64)
    xx, yy = np.meshgrid(xs, ys)
    sample = np.asarray(data[np.ix_(ys, xs)], dtype=np.float64)
    mask = valid[np.ix_(ys, xs)]
    points = np.column_stack((xx.ravel() + x_start, yy.ravel() + y_start,
                              np.where(mask, sample, 0).ravel())).astype(np.float64, copy=False)
    ids = np.arange(nx * ny, dtype=np.int64).reshape(ny, nx)
    if nx > 1 and ny > 1:
        keep = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
        # Prevent coarse cells from bridging filtered-out original pixels.
        if (ny, nx) != (height, width) and not np.all(valid):
            # Inclusive block reduction avoids a full-resolution integer table.
            row_bad = np.logical_or.reduceat(~valid, ys[:-1], axis=0)
            row_bad |= ~valid[ys[1:]]
            cell_bad = np.logical_or.reduceat(row_bad, xs[:-1], axis=1)
            cell_bad |= row_bad[:, xs[1:]]
            keep &= ~cell_bad
        quads = np.column_stack((np.full(np.count_nonzero(keep), 4, dtype=np.int64),
                                 ids[:-1, :-1][keep], ids[:-1, 1:][keep],
                                 ids[1:, 1:][keep], ids[1:, :-1][keep]))
        faces = quads.ravel()
    else:
        faces = np.empty(0, dtype=np.int64)
    if faces.size:
        cells = faces.reshape(-1, 5)
        used = np.unique(cells[:, 1:])
        remap = np.full(len(points), -1, dtype=np.int64)
        remap[used] = np.arange(len(used))
        cells[:, 1:] = remap[cells[:, 1:]]
    else:
        used = np.flatnonzero(mask.ravel())
    return SurfaceData(points[used], faces, yy.ravel()[used] + y_start, xx.ravel()[used] + x_start,
                       mask.ravel()[used], (ny, nx))


def prepare_frame(document: Document, selection: Selection, limits: Limits,
                  max_edge: int, crop: Crop = Crop()) -> Frame:
    """Prepare filtered display buffers and a sampled surface on a CPU worker.

    Args:
        document: Read-only original data.
        selection: Spatial axes, channel and complex component.
        limits: Inclusive bounds; either hide or visually clamp outlying values.
            Nonfinite values always form gaps. Original scalar values remain intact.
        max_edge: Maximum surface edge length; zero keeps every sample.
        crop: Inclusive source-index region; defaults to the complete array.

    Returns:
        Linked view buffers with original scalar values and source indices.

    Raises:
        ValueError: Invalid axis assignment, crop, filter interval or sampling size.
    """
    if max_edge < 0 or max_edge == 1:
        raise ValueError("Surface edge limit must be zero (full resolution) or at least 2.")
    if limits.lower is not None and limits.upper is not None and limits.lower > limits.upper:
        raise ValueError("Filter minimum must not exceed maximum.")
    if any(bound is not None and not np.isfinite(bound) for bound in (limits.lower, limits.upper)):
        raise ValueError("Filter bounds must be finite numbers.")
    scalar, rgb = _extract(document, selection, crop)
    valid = np.isfinite(scalar)
    clip_kind = np.zeros(scalar.shape, dtype=np.int8)
    if limits.lower is not None:
        clip_kind[valid & (scalar < limits.lower)] = -1
    if limits.upper is not None:
        clip_kind[valid & (scalar > limits.upper)] = 1
    display_scalar = scalar
    if limits.mode == FilterMode.HIDE:
        valid &= clip_kind == 0
        clip_kind.fill(0)
    elif np.any(clip_kind):
        display_scalar = scalar.astype(np.float64)
        if limits.lower is not None:
            display_scalar[clip_kind < 0] = limits.lower
        if limits.upper is not None:
            display_scalar[clip_kind > 0] = limits.upper
    finite = display_scalar[valid]
    low, high = (float(np.min(finite)), float(np.max(finite))) if finite.size else (0.0, 1.0)
    if low == high:
        padding = max(abs(low) * 1e-6, 0.5)
        low, high = low - padding, high + padding
    display: RealArray | None = None
    surface: SurfaceData | None = None
    outline: BoolArray | None = None
    if selection.mode == ViewMode.MATRIX:
        if rgb is None:
            display = np.where(valid, display_scalar, np.nan)
        else:
            color = np.asarray(rgb, dtype=np.float64)
            if np.issubdtype(rgb.dtype, np.integer):
                integer_dtype = cast(np.dtype[IntegerScalar], rgb.dtype)
                color = color / np.iinfo(integer_dtype).max
            color = np.nan_to_num(np.clip(color, 0, 1))
            rgba = np.ones((*scalar.shape, 4), dtype=np.float64)
            rgba[..., :3] = color[..., :3]
            rgba[..., 3] = valid * (color[..., 3] if rgb.shape[-1] == 4 else 1)
            display = (rgba * 255).astype(np.uint8)
        surface = _surface(scalar, valid, max_edge, crop.x_start, crop.y_start)
        if np.any(clip_kind):
            outline = np.zeros(scalar.shape, dtype=np.bool_)
            kernel = np.ones((5, 5), dtype=np.uint8)
            for side in (-1, 1):
                region = (clip_kind == side).astype(np.uint8)
                interior = cv2.erode(region, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
                outline |= (region != 0) & (interior == 0)
    return Frame(scalar, valid, display, (low, high), surface, rgb is not None,
                 display_scalar, clip_kind, limits, outline,
                 crop.x_start, crop.y_start if selection.mode == ViewMode.MATRIX else 0)


def format_value(value: RealScalar | float | int) -> str:
    """Format a source scalar for a coordinate readout without integer rounding.

    Args:
        value: NumPy scalar or Python float.

    Returns:
        Compact numeric text, including NaN and infinity when present.
    """
    return str(value)


def format_sample(values: RealArray, *indices: int) -> str:
    """Format one fully indexed original sample without converting its dtype.

    Args:
        values: Real-valued source samples, including integer and Boolean data.
        indices: One integer index per dimension, in NumPy axis order.

    Returns:
        Numeric text retaining NumPy's scalar formatting and integer precision.

    Raises:
        ValueError: The index count would select an array instead of a scalar.
        IndexError: An index is outside its source dimension.
    """
    if len(indices) != values.ndim:
        raise ValueError("Provide one index per array dimension to read a sample.")
    # NumPy's stubs cannot infer the scalar result from a runtime array rank.
    return format_value(cast(RealScalar, values[indices]))
