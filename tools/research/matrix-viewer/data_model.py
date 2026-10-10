"""Load numeric data and prepare linked views without changing source values.

Requirements: numpy, opencv-python, Pillow, scipy, h5py and openpyxl;
xlrd for legacy XLS input.
Usage: imported by the viewer; CPU preparation can run in a worker thread.
Complex phase views ignore Z/value bounds while retaining spatial crops.
Nonfinite complex source samples produce phase gaps, even when atan2 would
otherwise return a finite angle; zero complex samples retain NumPy's zero angle.
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from mmap import mmap
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from .image_metadata import ImageMetadata, read_image_metadata
from .csv_loader import read_csv
from .excel_io import EXCEL_EXTENSIONS, read_excel
from .table_data import HeaderMode, TableRange
from .array_validation import validate_numeric_array
from .mat_loader import read_mat
from .coordinates import AxisCoordinates, AxisMap

if TYPE_CHECKING:
    from .fourier import TransformRecord
    from .laplace import LaplaceRecord

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
type ColorArray = NDArray[np.uint8]

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"})
TEXT_EXTENSIONS = frozenset({".csv", ".txt"})
COLORMAPS: tuple[str, ...] = ("viridis", "cividis", "gray", "plasma", "inferno", "magma", "turbo", "coolwarm")
DEFAULT_CLIP_COLOR = "#ff0000"
LUMINANCE_WEIGHTS: tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
DEFAULT_MAX_POINTS = 100_000


class ImageMember(StrEnum):
    """Source channels and derived image matrices exposed like NPZ members."""

    RED = "R"
    GREEN = "G"
    BLUE = "B"
    ALPHA = "A"
    MONO = "Monochrome"
    RGB_GRAY = "RGB fusion (grayscale)"
    RGBA_GRAY = "RGBA fusion (grayscale x alpha)"
    RGB_COLOR = "RGB color"
    RGBA_COLOR = "RGBA color"
    MONO_COLOR = "Monochrome color"


@dataclass(frozen=True)
class ImageSource:
    """Shared original pixels and header metadata retained across member changes.

    Pixels use RGB/RGBA or monochrome/monochrome-alpha ordering. Selecting a
    source channel returns a view; derived matrices never overwrite this buffer.
    """

    pixels: RealArray
    channels: tuple[ImageMember, ...]
    metadata: ImageMetadata

    @property
    def layout(self) -> str:
        """Return the decoded channel layout, independently of the file mode."""
        if ImageMember.MONO in self.channels:
            return "Monochrome + alpha" if ImageMember.ALPHA in self.channels else "Monochrome"
        return "RGBA" if ImageMember.ALPHA in self.channels else "RGB"


class FilterMode(StrEnum):
    """Treatment of finite values outside the selected numeric interval."""

    CLAMP = "Clamp"
    HIDE = "Hide outside"


class ExportMode(StrEnum):
    """Numeric processing applied when saving the current cropped array."""

    CROP = "Crop only (source values)"
    PROCESSED = "Crop + value bounds"


class ViewMode(StrEnum):
    """Interpretation of spatial dimensions, independent of array rank."""

    MATRIX = "matrix"
    SIGNAL = "signal"
    XY = "xy"
    POINTS = "points"


class Component(StrEnum):
    """Real-valued representation of a complex array."""

    REAL = "Real"
    IMAGINARY = "Imaginary"
    MAGNITUDE = "Magnitude"
    PHASE = "Phase (rad)"
    MAGNITUDE_DB = "Magnitude (dB)"


@dataclass(frozen=True)
class Document:
    """An open numeric array and the archive/image metadata needed by the UI.

    NPY arrays may be read-only memory maps. NPZ/MAT contain only the selected
    variable in memory; archive handles are closed before this object returns.
    """

    path: Path
    array: Array
    keys: tuple[str, ...] = ()
    key: str | None = None
    is_image: bool = False
    image_source: ImageSource | None = None
    csv_headers: tuple[str, ...] = ()
    axes: tuple[AxisCoordinates, ...] = ()
    transform: "TransformRecord | None" = None
    laplace: "LaplaceRecord | None" = None
    complex_provenance: str = ""
    conversion_provenance: str = ""
    import_provenance: str = ""

    @property
    def is_complex(self) -> bool:
        """Identify complex storage independently of the displayed component.

        The dtype is the persistent flag in NPY/MAT, including arrays whose
        imaginary part is entirely zero. Derived real display channels do not
        change this source identity.
        """
        return self.array.dtype.kind == "c"


@dataclass(frozen=True)
class Selection:
    """Axis assignment and indices into the original array.

    x_axis is the sample/column axis; y_axis is the row axis. A channel index
    of -1 requests RGB composition, with luminance for the surface/profile.
    Other, unused axes are indexed by the matching entries in slices.
    XY/point modes instead use coordinate_axis (0 = coordinate rows, 1 =
    coordinate columns) and coordinate_order to assign X/Y[/Z] components.
    """

    mode: ViewMode
    x_axis: int
    y_axis: int | None
    channel_axis: int | None
    channel: int
    slices: tuple[int, ...]
    component: Component = Component.REAL
    coordinate_axis: int | None = None
    coordinate_order: tuple[int, ...] = (0, 1, 2)
    db_floor: float = -120.0


def is_phase_view(document: Document, selection: Selection) -> bool:
    """Return whether a complex source is displayed as an angular phase channel.

    Args:
        document: Source array; real arrays never count as complex phase views.
        selection: Current interpreted component, independently of spatial crop.

    Returns:
        True only for the phase component of a complex source.
    """
    return document.is_complex and selection.component == Component.PHASE


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
    """Sampled geometry mapped to source pixels or XYZ records.

    For a point cloud, rows contains original record indices, columns is zero,
    and faces is empty. Surface colors are optional RGBA display bytes.
    """

    points: FloatArray
    faces: IndexArray
    rows: IndexArray
    columns: IndexArray
    valid: BoolArray
    sampled_shape: tuple[int, int]
    colors: ColorArray | None = None


@dataclass(frozen=True)
class Frame:
    """Prepared region with source coordinates and original scalar precision.

    Scalar/image buffers are local to the crop. Mesh coordinates and source
    row/column mappings are absolute, using x_start and y_start as the origin.
    Raw retains selected cells before complex conversion or filtering.
    XY curves retain original X in x_values; clouds retain XYZ source records
    in point_coordinates, independently of their sampled display geometry.
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
    raw: Array | None = None
    x_values: RealArray | None = None
    point_coordinates: RealArray | None = None
    x_grid: AxisCoordinates | None = None
    y_grid: AxisCoordinates | None = None
    xy: bool = False

    @property
    def x_mapping(self) -> AxisMap:
        """Map matrix source columns to physical X coordinates."""
        return self.x_grid.mapping if self.x_grid is not None else AxisMap()

    @property
    def y_mapping(self) -> AxisMap:
        """Map matrix source rows to physical Y coordinates."""
        return self.y_grid.mapping if self.y_grid is not None else AxisMap()


def load_document(path: Path, key: str | None = None, *, region: TableRange = TableRange(),
                  header: HeaderMode = HeaderMode.AUTO, delimiter: str | None = None) -> Document:
    """Read one array or image, preserving numeric precision and image channels.

    Args:
        path: Existing NPY, NPZ, MAT, Excel, numeric CSV/TXT or supported image file.
        key: NPZ member, MAT variable or image matrix label. None chooses the
            first usable array, RGB grayscale for color images, or monochrome.
        region: One-based inclusive original table range for Excel/CSV/TXT only.
        header: Table header treatment, applied after selecting the range.
        delimiter: CSV/TXT delimiter; None auto-detects.

    Returns:
        Document containing numeric data, with RGB(A) image channel ordering.

    Raises:
        ValueError: Unreadable files, missing members, empty, unsupported or
            malformed data. Includes the path, requested member and reason.

    Side effects:
        Prints image loading, header and decoder diagnostics to the console.
    """
    try:
        return _read_document(path, key, region, header, delimiter)
    except Exception as exc:
        if isinstance(exc, FileNotFoundError):
            reason = "The file does not exist or is no longer accessible."
        elif isinstance(exc, PermissionError):
            reason = "Permission denied. Check file permissions and whether another program has locked it."
        elif isinstance(exc, IsADirectoryError):
            reason = "The selected path is a directory, not a matrix file."
        elif isinstance(exc, MemoryError):
            reason = "Not enough memory to load this array. Save a smaller array or close other large datasets."
        else:
            reason = str(exc) or type(exc).__name__
            if "Python objects in dtype" in reason or "Object arrays cannot be loaded" in reason:
                reason = ("Object arrays are not supported. Save a nonempty 1D/2D boolean, integer, "
                          "real or complex numeric array without Python objects.")
        member = f"\nArray / variable: {key}" if key is not None else ""
        raise ValueError(f"Cannot open file:\n{path}{member}\n\n{reason}") from exc


def _read_document(path: Path, key: str | None, region: TableRange, header: HeaderMode,
                   delimiter: str | None) -> Document:
    """Decode one source; the public boundary adds file context to failures."""
    if path.is_dir():
        raise IsADirectoryError(str(path))
    if not path.is_file():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    keys: tuple[str, ...] = ()
    image = suffix in IMAGE_EXTENSIONS
    if suffix == ".npz":
        loaded = np.load(path, allow_pickle=False)
        if not isinstance(loaded, np.lib.npyio.NpzFile):
            raise ValueError("The file is not an NPZ archive. Check its contents and extension.")
        with loaded as archive:
            keys = tuple(archive.files)
            if not keys:
                raise ValueError("The NPZ archive has no arrays.")
            if key is not None:
                if key not in keys:
                    raise ValueError(f"NPZ member {key!r} does not exist. Available: {', '.join(keys)}")
                array = archive[key]
            else:
                # Metadata/object/empty members should not hide usable arrays.
                problems: list[str] = []
                for candidate in keys:
                    try:
                        member = validate_numeric_array(archive[candidate], f"NPZ member {candidate!r}")
                    except ValueError as exc:
                        problems.append(f"{candidate}: {exc}")
                        continue
                    key, array = candidate, member
                    break
                else:
                    details = "\n".join(problems)
                    raise ValueError(f"The NPZ archive has no supported nonempty 1D/2D numeric arrays.\n{details}")
    elif suffix == ".npy":
        with path.open("rb") as stream:
            if stream.read(len(np.lib.format.MAGIC_PREFIX)) != np.lib.format.MAGIC_PREFIX:
                raise ValueError("Invalid NPY file header. The file is damaged or is not a NumPy NPY file.")
        array = np.load(path, allow_pickle=False, mmap_mode="r")
    elif suffix == ".mat":
        try:
            mat = read_mat(path, key)
        except (OSError, ValueError, TypeError, IndexError, NotImplementedError) as exc:
            raise ValueError(f"Cannot read this MATLAB MAT file.\n{exc}") from exc
        return Document(path, cast(Array, mat.values), mat.keys, mat.key)
    elif suffix in EXCEL_EXTENSIONS:
        table, keys, selected = read_excel(path, key, region, header)
        validate_numeric_array(table.values, f"Worksheet {selected!r}")
        return Document(path, table.values, keys, selected, csv_headers=table.headers,
                        import_provenance=f"Excel input: {region}; {header.value}")
    elif suffix in TEXT_EXTENSIONS:
        try:
            table = read_csv(path, region, header, delimiter)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Cannot read {path.name} as a numeric CSV table. "
                             f"Expected UTF-8 with comma, semicolon or tab separators.\n{exc}") from exc
        validate_numeric_array(table.values, "Text matrix")
        return Document(path, table.values, csv_headers=table.headers,
                        import_provenance=f"Text input: {region}; {header.value}; delimiter={delimiter or 'automatic'!r}")
    elif image:
        started = perf_counter()
        print(f"[Image] Opening: {path}", flush=True)
        # Decode bytes for Unicode paths and preserve 16-bit image data.
        decoded = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None:
            raise ValueError("The image could not be decoded.")
        array = decoded
        if array.ndim == 3 and array.shape[-1] in (3, 4):
            order = [2, 1, 0] if array.shape[-1] == 3 else [2, 1, 0, 3]
            array = array[..., order]
        metadata = read_image_metadata(path)
        if array.ndim == 2:
            channels = (ImageMember.MONO,)
        elif array.ndim == 3 and array.shape[-1] in (2, 3, 4):
            if metadata.grayscale or array.shape[-1] == 2:
                if array.shape[-1] in (2, 4):
                    array = array[..., [0, array.shape[-1] - 1]]
                    channels = (ImageMember.MONO, ImageMember.ALPHA)
                else:
                    array = array[..., 0]
                    channels = (ImageMember.MONO,)
            else:
                channels = (ImageMember.RED, ImageMember.GREEN, ImageMember.BLUE)
                if array.shape[-1] == 4:
                    channels += (ImageMember.ALPHA,)
        else:
            raise ValueError(f"Unsupported decoded image layout: {array.shape}")
        source = ImageSource(cast(RealArray, array), channels, metadata)
        members = tuple(channel.value for channel in channels)
        if ImageMember.RED in channels:
            members += (ImageMember.RGB_GRAY.value,)
        if ImageMember.ALPHA in channels:
            members += (ImageMember.RGBA_GRAY.value,)
        if ImageMember.RED in channels:
            members += (ImageMember.RGB_COLOR.value,)
        if ImageMember.ALPHA in channels:
            members += (ImageMember.RGBA_COLOR.value,)
        members += (ImageMember.MONO_COLOR.value,)
        document = Document(path, cast(Array, array), members, is_image=True, image_source=source)
        document = select_image_member(document, key or (
            ImageMember.RGB_GRAY.value if ImageMember.RED in channels else ImageMember.MONO.value))
        print(
            f"[Image] Format: {metadata.format}; file mode: {metadata.mode}; file depth: {metadata.depth}\n"
            f"[Image] Decoded: {source.layout}; channels: {', '.join(channel.value for channel in channels)}; "
            f"shape: {source.pixels.shape}; dtype: {source.pixels.dtype}; "
            f"{source.pixels.dtype.itemsize * 8}-bit/channel; {source.pixels.nbytes / (1024 ** 2):.2f} MiB\n"
            f"[Image] Matrices: {' | '.join(members)}\n"
            f"[Image] Selected: {document.key}; shape: {document.array.shape}; dtype: {document.array.dtype}; "
            f"loaded in {(perf_counter() - started) * 1000:.1f} ms",
            flush=True,
        )
        return document
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")
    label = f"NPZ member {key!r}" if suffix == ".npz" else "NPY array"
    try:
        numeric = validate_numeric_array(array, label)
    except ValueError:
        # A retained exception traceback can otherwise keep a rejected NPY
        # mapping alive and lock the file on Windows until garbage collection.
        if isinstance(array, np.memmap) and isinstance(array.base, mmap):
            array.base.close()
        raise
    return Document(path, cast(Array, numeric), keys, key, image)


def normalize_image_alpha(alpha: RealArray) -> FloatArray:
    """Convert image opacity samples to weights without altering source data.

    Args:
        alpha: Alpha samples in their original dtype and any shape. Integer
            opacity uses the dtype maximum (255 for uint8, 65535 for uint16);
            floating-point and boolean opacity already use the range 0..1.

    Returns:
        Float64 weights clipped to 0..1. NaNs remain gaps. Normalization uses
        the source dtype, never the minimum/maximum of the selected slice.
    """
    maximum = (float(np.iinfo(cast(np.dtype[IntegerScalar], alpha.dtype)).max)
               if np.issubdtype(alpha.dtype, np.integer) else 1.0)
    return np.clip(np.asarray(alpha, dtype=np.float64) / maximum, 0, 1)


def select_image_member(document: Document, key: str) -> Document:
    """Select an image channel or compute a derived matrix from cached pixels.

    Args:
        document: Loaded image retaining its original ImageSource.
        key: One of document.keys; source channel values retain their dtype.

    Returns:
        A document sharing the original pixels. RGB grayscale uses weighted
        luminance in source units. RGBA grayscale multiplies that luminance by
        normalized source alpha (black background). RGB color ignores source
        alpha. RGBA modes require an actual source alpha channel; none is added.
        Monochrome is replicated into three color channels for RGBA display.
        Monochrome color displays source gray values or RGB luminance in black
        and white at the source bit-depth scale, ignoring alpha.
        Monochrome sources hide RGB color. All images offer RGBA modes only
        when an alpha channel is present.

    Raises:
        ValueError: The document is not a loaded image.
        KeyError: The requested image matrix does not exist.
    """
    source = document.image_source
    if source is None:
        raise ValueError("The document has no image channels.")
    if key not in document.keys:
        raise KeyError(f"Unknown image matrix: {key}")
    member = ImageMember(key)
    if member in (ImageMember.RGBA_GRAY, ImageMember.RGBA_COLOR) and ImageMember.ALPHA not in source.channels:
        raise KeyError(f"Image matrix requires a source alpha channel: {key}")
    pixels = source.pixels
    array: RealArray
    if member in source.channels:
        array = pixels if pixels.ndim == 2 else pixels[..., source.channels.index(member)]
    elif member == ImageMember.MONO_COLOR and ImageMember.MONO in source.channels:
        array = pixels if pixels.ndim == 2 else pixels[..., 0]
    elif member in (ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR):
        if ImageMember.MONO in source.channels:
            monochrome = pixels if pixels.ndim == 2 else pixels[..., 0]
            array = np.repeat(monochrome[..., None], 3, axis=-1)
        else:
            array = pixels[..., :3]
        if member == ImageMember.RGBA_COLOR:
            if ImageMember.MONO not in source.channels:
                array = pixels
            else:
                array = np.concatenate((array, pixels[..., -1:]), axis=-1)
    else:
        if ImageMember.MONO in source.channels:
            array = np.asarray(pixels[..., 0], dtype=np.float64)
        else:
            array = np.asarray(pixels[..., :3], dtype=np.float64) @ np.asarray(LUMINANCE_WEIGHTS)
        if member == ImageMember.RGBA_GRAY:
            alpha = pixels[..., source.channels.index(ImageMember.ALPHA)]
            array = array * normalize_image_alpha(alpha)
    return replace(document, array=array, key=key)


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
    if mode in (ViewMode.XY, ViewMode.POINTS):
        count = 2 if mode == ViewMode.XY else 3
        if rank != 2 or count not in shape or np.iscomplexobj(document.array):
            raise ValueError(f"{mode.value} mode requires a real 2D array with exactly {count} rows or columns.")
        coordinate_axis = 1 if shape[1] == count else 0
        return Selection(mode, 1 - coordinate_axis, None, None, 0, (0, 0),
                         coordinate_axis=coordinate_axis, coordinate_order=tuple(range(count)))
    if mode is None and document.path.suffix.lower() in TEXT_EXTENSIONS | EXCEL_EXTENSIONS | {".mat"} and 1 in shape:
        mode = ViewMode.SIGNAL
    mode = mode or (ViewMode.SIGNAL if rank == 1 else ViewMode.MATRIX)
    if channel_axis is not None:
        if not -rank <= channel_axis < rank:
            raise ValueError("Channel axis is out of range.")
        channel_axis %= rank
    elif document.is_image and rank == 3:
        channel_axis = 2
    elif mode == ViewMode.MATRIX and rank == 3:
        channel_axis = min(reversed(range(rank)), key=lambda axis: shape[axis])
    elif mode == ViewMode.SIGNAL and rank >= 2 and document.image_source is None:
        channel_axis = min(reversed(range(rank)), key=lambda axis: shape[axis])
    spatial = [axis for axis in range(rank) if axis != channel_axis]
    needed = 2 if mode == ViewMode.MATRIX else 1
    if len(spatial) < needed:
        raise ValueError("Not enough spatial axes; select signal mode or disable the channel axis.")
    rgb = document.is_image and channel_axis is not None and shape[channel_axis] in (3, 4)
    if document.image_source is not None and document.key in (
        ImageMember.RGB_COLOR, ImageMember.RGBA_COLOR, ImageMember.MONO_COLOR,
    ):
        if mode != ViewMode.MATRIX:
            raise ValueError("Color display uses matrix mode; select a scalar image matrix for signal mode.")
    return Selection(mode, spatial[-1], spatial[-2] if needed == 2 else None,
                     channel_axis, -1 if rgb else 0, (0,) * rank)


def _crop_slice(start: int, end: int | None, size: int, label: str) -> slice:
    end = size - 1 if end is None else end
    if not 0 <= start <= end < size:
        raise ValueError(f"{label} crop must satisfy 0 <= start <= end < {size}; got {start}..{end}.")
    return slice(start, end + 1)


def _extract_raw(document: Document, selection: Selection, crop: Crop) -> Array:
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
    if selection.channel_axis is not None and selection.channel != -1:
        data = data[..., selection.channel]
    return data


def _extract(document: Document, selection: Selection, crop: Crop) -> tuple[RealArray, RealArray | None]:
    data = _extract_raw(document, selection, crop)
    rgb: RealArray | None = None
    if selection.channel_axis is not None:
        if selection.channel == -1:
            if selection.mode != ViewMode.MATRIX or data.shape[-1] not in (3, 4) or np.iscomplexobj(data):
                raise ValueError("RGB composition requires 3 or 4 real-valued channels in matrix mode.")
            rgb = cast(RealArray, data)  # The complex-dtype guard above establishes real RGB data.
            data = np.asarray(data[..., :3], dtype=np.float64) @ np.asarray(LUMINANCE_WEIGHTS)
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
                data = np.where(np.isfinite(complex_data), np.angle(complex_data), np.nan)
            case Component.MAGNITUDE_DB:
                # Reuse the conversion tool's amplitude convention and zero handling.
                from .data_conversion import ConversionOptions, convert_values
                if not np.isfinite(selection.db_floor) or selection.db_floor >= 0:
                    raise ValueError("The dB floor must be finite and negative.")
                data = (convert_values(complex_data, ConversionOptions(db_floor=selection.db_floor))[0]
                        if np.any(np.isfinite(complex_data)) else np.full(complex_data.shape, np.nan))
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


def apply_value_limits(values: RealArray, valid: BoolArray, limits: Limits) -> tuple[RealArray, BoolArray, ClipArray]:
    """Apply validated display bounds without modifying source arrays or masks.

    Args:
        values: Numeric source samples of any shape.
        valid: Matching mask excluding nonfinite/invalid samples.
        limits: Finite, ordered bounds already validated by frame preparation.

    Returns:
        Display values, visibility mask and clipping codes (-1 below, 1 above,
        0 unchanged). Hidden samples have no clipping code. Unclamped values
        keep their source dtype; clamped display values use float64.
    """
    clip_kind = np.zeros(values.shape, dtype=np.int8)
    if limits.lower is not None:
        clip_kind[valid & (values < limits.lower)] = -1
    if limits.upper is not None:
        clip_kind[valid & (values > limits.upper)] = 1
    display = values
    if limits.mode == FilterMode.HIDE:
        valid = valid & (clip_kind == 0)
        clip_kind.fill(0)
    elif np.any(clip_kind):
        display = values.astype(np.float64)
        if limits.lower is not None:
            display[clip_kind < 0] = limits.lower
        if limits.upper is not None:
            display[clip_kind > 0] = limits.upper
    return display, valid, clip_kind


def prepare_frame(document: Document, selection: Selection, limits: Limits,
                  max_edge: int, crop: Crop = Crop(), *, max_points: int = DEFAULT_MAX_POINTS) -> Frame:
    """Prepare filtered display buffers and a sampled surface on a CPU worker.

    Args:
        document: Read-only original data.
        selection: Spatial axes, channel and complex component.
        limits: Inclusive bounds; either hide or visually clamp outlying values.
            Nonfinite values always form gaps. Original scalar values remain intact.
        max_edge: Maximum surface edge length; zero keeps every sample.
        crop: Inclusive source-index region; defaults to the complete array.
        max_points: Point-cloud preview limit; zero displays every valid point.

    Returns:
        Linked view buffers with original scalar values and source indices.

    Raises:
        ValueError: Invalid axis assignment, crop, filter interval or sampling size.
    """
    if max_edge < 0 or max_edge == 1:
        raise ValueError("Surface edge limit must be zero (full resolution) or at least 2.")
    if is_phase_view(document, selection):
        limits = Limits()
    if limits.lower is not None and limits.upper is not None and limits.lower > limits.upper:
        raise ValueError("Filter minimum must not exceed maximum.")
    if any(bound is not None and not np.isfinite(bound) for bound in (limits.lower, limits.upper)):
        raise ValueError("Filter bounds must be finite numbers.")
    if max_points < 0:
        raise ValueError("Point limit must be nonnegative.")
    coordinates: RealArray | None = None
    x_values: RealArray | None = None
    x_grid = document.axes[selection.x_axis] if document.axes else None
    y_grid = document.axes[selection.y_axis] if document.axes and selection.y_axis is not None else None
    if selection.mode in (ViewMode.XY, ViewMode.POINTS):
        count = 2 if selection.mode == ViewMode.XY else 3
        axis = selection.coordinate_axis
        if (document.array.ndim != 2 or axis not in (0, 1) or document.array.shape[axis] != count
                or np.iscomplexobj(document.array) or sorted(selection.coordinate_order) != list(range(count))):
            raise ValueError(f"Choose {count} distinct coordinate rows/columns for {selection.mode.value} mode.")
        samples = document.array.T if axis == 0 else document.array
        raw = samples[_crop_slice(crop.x_start, crop.x_end, len(samples), "Sample"), :][:, selection.coordinate_order]
        coordinate_data = cast(RealArray, raw)
        scalar, rgb = coordinate_data[:, -1], None
        if selection.mode == ViewMode.XY:
            x_values = coordinate_data[:, 0]
        else:
            coordinates = coordinate_data
    else:
        raw = _extract_raw(document, selection, crop)
        scalar, rgb = _extract(document, selection, crop)
        if selection.mode == ViewMode.SIGNAL and x_grid is not None:
            x_values = x_grid.values(crop.x_start, len(scalar))
    source = document.image_source
    monochrome = source is not None and document.key == ImageMember.MONO_COLOR
    composite = rgb is not None or monochrome
    valid = np.isfinite(scalar)
    if coordinates is not None:
        valid &= np.all(np.isfinite(coordinates), axis=1)
    if x_values is not None:
        valid &= np.isfinite(x_values)
    display_scalar, valid, clip_kind = apply_value_limits(scalar, valid, limits)
    finite = display_scalar[valid]
    low, high = (float(np.min(finite)), float(np.max(finite))) if finite.size else (0.0, 1.0)
    if low == high:
        padding = max(abs(low) * 1e-6, 0.5)
        low, high = low - padding, high + padding
    display: RealArray | None = None
    surface: SurfaceData | None = None
    outline: BoolArray | None = None
    if selection.mode == ViewMode.MATRIX:
        if not composite:
            display = np.where(valid, display_scalar, np.nan)
        else:
            color_data = rgb if rgb is not None else scalar[..., None]
            color = np.asarray(color_data, dtype=np.float64)
            # Derived luminance is float64 but retains the original image units.
            color_dtype = source.pixels.dtype if monochrome and source is not None else color_data.dtype
            if np.issubdtype(color_dtype, np.integer):
                integer_dtype = cast(np.dtype[IntegerScalar], color_dtype)
                color = color / np.iinfo(integer_dtype).max
            color = np.nan_to_num(np.clip(color, 0, 1))
            rgba = np.ones((*scalar.shape, 4), dtype=np.float64)
            rgba[..., :3] = color[..., :3]
            rgba[..., 3] = valid * (color[..., 3] if color.shape[-1] == 4 else 1)
            display = (rgba * 255).astype(np.uint8)
        surface = _surface(scalar, valid, max_edge, crop.x_start, crop.y_start)
        if x_grid is not None:
            surface.points[:, 0] = x_grid.mapping.array(surface.points[:, 0])
        if y_grid is not None:
            surface.points[:, 1] = y_grid.mapping.array(surface.points[:, 1])
        if composite and display is not None:
            # Reuse the exact 2D display colors at the sampled surface vertices.
            colors = np.asarray(display[surface.rows - crop.y_start, surface.columns - crop.x_start], dtype=np.uint8)
            surface = replace(surface, colors=colors)
        if np.any(clip_kind):
            outline = np.zeros(scalar.shape, dtype=np.bool_)
            kernel = np.ones((5, 5), dtype=np.uint8)
            for side in (-1, 1):
                region = (clip_kind == side).astype(np.uint8)
                interior = cv2.erode(region, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
                outline |= (region != 0) & (interior == 0)
    elif coordinates is not None:
        indices = np.flatnonzero(valid).astype(np.int64, copy=False)
        if max_points and len(indices) > max_points:
            indices = indices[np.linspace(0, len(indices) - 1, max_points, dtype=np.int64)]
        surface = SurfaceData(np.asarray(coordinates[indices], dtype=np.float64),
                              np.empty(0, dtype=np.int64), indices + crop.x_start,
                              np.zeros(len(indices), dtype=np.int64), valid[indices], (1, len(indices)))
    return Frame(scalar, valid, display, (low, high), surface, composite,
                 display_scalar, clip_kind, limits, outline,
                 crop.x_start, crop.y_start if selection.mode == ViewMode.MATRIX else 0,
                 raw, x_values, coordinates, x_grid, y_grid, selection.mode == ViewMode.XY)


def export_array(frame: Frame, mode: ExportMode = ExportMode.PROCESSED) -> RealArray:
    """Copy full-resolution selected data for NPY export, preserving its shape.

    Args:
        frame: Currently displayed, cropped numeric component. Color displays
            export their grayscale matrix. XY curves export two columns, X/Y.
        mode: Crop only retains original selected values and dtype. Processed
            export applies finite value caps and writes excluded samples as NaN.

    Returns:
        Independent 1D/2D numeric array. Integer dtype is retained for integral,
        representable caps; NaN or fractional caps require floating-point data.

    Raises:
        ValueError: Point-cloud frame, unknown mode, or a required floating-point
            conversion would round untouched integer samples.
    """
    if frame.point_coordinates is not None:
        raise ValueError("Array export is available in matrix and signal modes.")
    if mode not in (ExportMode.CROP, ExportMode.PROCESSED):
        raise ValueError(f"Unknown export mode: {mode}")
    source = (cast(RealArray, frame.raw) if frame.xy and frame.raw is not None
              else frame.scalar)
    if mode == ExportMode.CROP:
        return source.copy()
    missing = ~frame.valid
    below, above = frame.clip_kind < 0, frame.clip_kind > 0
    bounds = [(below, frame.value_limits.lower), (above, frame.value_limits.upper)]
    active_bounds = [(mask, bound) for mask, bound in bounds if bound is not None and np.any(mask)]
    dtype = source.dtype
    if dtype.kind in "biu":
        minimum, maximum = ((0, 1) if dtype.kind == "b" else
                            (int(np.iinfo(cast(np.dtype[IntegerScalar], dtype)).min),
                             int(np.iinfo(cast(np.dtype[IntegerScalar], dtype)).max)))
        integral_caps = all(float(bound).is_integer() and minimum <= int(bound) <= maximum
                            for _, bound in active_bounds)
        if np.any(missing) or not integral_caps:
            dtype = np.dtype(np.float64)
    elif active_bounds:
        with np.errstate(over="ignore", invalid="ignore"):
            exact_caps = all(float(np.asarray(bound, dtype=dtype)) == bound for _, bound in active_bounds)
        if not exact_caps:
            dtype = np.result_type(dtype, np.float64)
    result = source.astype(dtype, copy=True)
    if source.dtype.kind in "biu" and dtype.kind == "f":
        kept = frame.valid & ~below & ~above
        if frame.xy:
            preserved = np.ones(source.shape, dtype=np.bool_)
            preserved[:, 1] = kept
        else:
            preserved = kept
        # Integer comparisons against floats promote before comparison; instead,
        # round-trip just the unchanged cells to detect lost low integer bits.
        with np.errstate(invalid="ignore", over="ignore"):
            exact = np.array_equal(result[preserved].astype(source.dtype), source[preserved])
        if not exact:
            raise ValueError("Value bounds require floating-point output and would lose integer precision. "
                             "Choose Crop only or adjust the bounds.")
    values = result[:, 1] if frame.xy else result
    for mask, bound in active_bounds:
        values[mask] = int(bound) if dtype.kind in "biu" else bound
    if np.any(missing):
        values[missing] = np.nan
    return result


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
