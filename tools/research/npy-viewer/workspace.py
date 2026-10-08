"""Independent matrix entries and non-destructive overlay coordinate alignment.

Requirements: numpy and the viewer's data loaders. Usage: imported by the Qt
workspace and renderers; this module has no GUI or polling dependencies.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np

from .data_model import (BoolArray, Component, Crop, Document, FloatArray, Frame, Limits, RealArray,
                         Selection, ViewMode, default_selection, load_document)
from .coordinates import AxisMap

COLORS: tuple[str, ...] = ("#e53935", "#1976d2", "#279638", "#ab47bc", "#ef8c00", "#00a6a6", "#bc557f")
type Setting = str | int | float | bool


class Alignment(StrEnum):
    """Independent axis transformations, expressed in increasing coordinates."""

    ORIGINAL = "Original coordinates"
    START = "Start"
    CENTER = "Center"
    END = "End"
    STRETCH = "Stretch"


def align_axis(source: tuple[float, float], reference: tuple[float, float], mode: Alignment) -> AxisMap:
    """Align sample-center ranges; singleton spans remain centered without collapse.

    Args:
        source: Increasing source coordinate bounds.
        reference: Increasing target coordinate bounds.
        mode: Original, start/end, center or stretch.

    Returns:
        Positive-scale invertible transform, also for singleton arrays.
    """
    a, b = source
    c, d = reference
    if mode == Alignment.ORIGINAL:
        return AxisMap()
    if mode == Alignment.START:
        return AxisMap(offset=c - a)
    if mode == Alignment.END:
        return AxisMap(offset=d - b)
    if mode == Alignment.STRETCH and b > a and d > c:
        scale = (d - c) / (b - a)
        return AxisMap(scale, c - a * scale)
    return AxisMap(offset=(c + d - a - b) / 2)


def family(mode: ViewMode) -> ViewMode:
    """Treat indexed signals and explicit XY tables as compatible curves."""
    return ViewMode.SIGNAL if mode == ViewMode.XY else mode


@dataclass(eq=False)
class MatrixEntry:
    """One channel view with independently retained settings and a source group.

    matrix_uid groups channels of the same file/member in the selector tree.
    image_key can request a derived image member before its lazy conversion.
    """

    uid: int
    document: Document
    selection: Selection
    color: str
    visible: bool = True
    opacity: float = 0.65
    align_x: Alignment = Alignment.ORIGINAL
    align_y: Alignment = Alignment.ORIGINAL
    crop: Crop = field(default_factory=Crop)
    limits: Limits = field(default_factory=Limits)
    frame: Frame | None = None
    settings: dict[str, Setting] = field(default_factory=dict)
    revision: int = 0
    instance: int = 1
    name: str = ""
    matrix_uid: int = 0
    image_key: str | None = None

    @property
    def label(self) -> str:
        """Return the session alias or the original file/member identity."""
        return self.name or self.source_label

    @property
    def source_label(self) -> str:
        """Keep the original identity available after a session-only rename."""
        document = self.document
        name = (f"{document.path.name} :: {document.key}"
                if document.key is not None and not document.is_image else document.path.name)
        return f"{name} [{self.instance}]" if self.instance > 1 else name


@dataclass(frozen=True)
class ChannelChoice:
    """One selectable channel, shown as a child or a single-channel matrix row."""

    label: str
    component: Component = Component.REAL
    image_key: str | None = None
    channel: int = 0


def channel_choices(entry: MatrixEntry) -> tuple[ChannelChoice, ...]:
    """List image members, complex components or interpreted numeric channels.

    Args:
        entry: Source matrix and its current axis interpretation.

    Returns:
        Available channels; each can be checked independently. Ordinary scalar
        matrices have one Value channel, displayed directly on the matrix row.
    """
    document, selection = entry.document, entry.selection
    if document.image_source is not None:
        return tuple(ChannelChoice(key, image_key=key) for key in document.keys)
    components = tuple(Component) if np.iscomplexobj(document.array) else (Component.REAL,)
    channels = (range(document.array.shape[selection.channel_axis])
                if selection.channel_axis is not None else (0,))
    return tuple(ChannelChoice(
        f"Channel {channel} / {component.value}" if selection.channel_axis is not None and np.iscomplexobj(document.array)
        else f"Channel {channel}" if selection.channel_axis is not None
        else component.value if np.iscomplexobj(document.array) else "Value",
        component, channel=channel) for channel in channels for component in components)


def active_channel(entry: MatrixEntry) -> ChannelChoice:
    """Describe the currently selected channel without allocating other choices."""
    document, selection = entry.document, entry.selection
    if document.image_source is not None:
        key = entry.image_key or document.key
        return ChannelChoice(key or "Value", image_key=key)
    component = selection.component
    label = (f"Channel {selection.channel} / {component.value}" if selection.channel_axis is not None and np.iscomplexobj(document.array)
             else f"Channel {selection.channel}" if selection.channel_axis is not None
             else component.value if np.iscomplexobj(document.array) else "Value")
    return ChannelChoice(label, component, channel=selection.channel)


@dataclass(frozen=True)
class LoadedFile:
    """Supported members plus explicit diagnostics for rejected archive members."""

    documents: tuple[Document, ...]
    errors: tuple[str, ...] = ()


def load_file(path: Path, key: str | None = None) -> LoadedFile:
    """Load one file, expanding NPZ/MAT members while reporting invalid members.

    Args:
        path: One user-selected source file.
        key: Optional first member to select.

    Returns:
        Supported documents in stable member order, with the requested member first.

    Raises:
        ValueError: No supported members, or an explicitly requested invalid member.
        OSError: File read failure.
    """
    if path.suffix.lower() == ".npz":
        loaded = np.load(path, allow_pickle=False)
        if not isinstance(loaded, np.lib.npyio.NpzFile):
            raise ValueError(f"{path.name}: the contents are not an NPZ archive.")
        with loaded as archive:
            keys = tuple(archive.files)
        if key is not None and key not in keys:
            raise ValueError(f"NPZ member {key!r} was not found in {path.name}.")
        first = None
    else:
        first = load_document(path, key)
        if path.suffix.lower() != ".mat":
            return LoadedFile((first,))
        keys = first.keys
        key = first.key
    ordered = ((key,) + tuple(name for name in keys if name != key)) if key is not None else keys
    documents: list[Document] = []
    errors: list[str] = []
    for name in ordered:
        try:
            document = first if first is not None and name == first.key else load_document(path, name)
            default_selection(document)
            documents.append(document)
        except (ValueError, OSError, TypeError) as exc:
            if name == key:
                raise ValueError(f"{path.name} :: {name}: {exc}") from exc
            errors.append(f"{path.name} :: {name}: {exc}")
    if not documents:
        raise ValueError("No supported matrices in this archive.\n" + "\n".join(errors))
    return LoadedFile(tuple(documents), tuple(errors))


def coordinate_bounds(frame: Frame) -> tuple[tuple[float, float], tuple[float, float]]:
    """Get source sample-center bounds, using actual X/XYZ for coordinate tables."""
    def finite_bounds(values: RealArray) -> tuple[float, float]:
        finite = values[np.isfinite(values)]
        return (float(np.min(finite)), float(np.max(finite))) if finite.size else (0.0, 0.0)

    if frame.point_coordinates is not None:
        return finite_bounds(frame.point_coordinates[:, 0]), finite_bounds(frame.point_coordinates[:, 1])
    if frame.x_values is not None:
        return finite_bounds(frame.x_values), (0.0, 0.0)
    x = (float(frame.x_start), float(frame.x_start + frame.scalar.shape[-1] - 1))
    y = ((float(frame.y_start), float(frame.y_start + frame.scalar.shape[0] - 1))
         if frame.scalar.ndim == 2 else (0.0, 0.0))
    return ((frame.x_mapping.forward(x[0]), frame.x_mapping.forward(x[1])),
            (frame.y_mapping.forward(y[0]), frame.y_mapping.forward(y[1])))


@dataclass(frozen=True, eq=False)
class RenderLayer:
    """Immutable render snapshot; workers never access Qt widget state."""

    uid: int
    label: str
    frame: Frame
    color: str
    opacity: float
    x: AxisMap = AxisMap()
    y: AxisMap = AxisMap()
    height: float = 1.0
    point_size: float = 2.0
    clip_color: str = "#ff0000"
    threshold: float | None = None
    data_key: tuple[object, ...] = ()

    @property
    def signature(self) -> tuple[object, ...]:
        """Small identity key for avoiding unchanged image/mesh rebuilds."""
        return (self.uid, self.label, id(self.frame), self.color, self.opacity, self.x, self.y,
                self.height, self.point_size, self.clip_color)


@dataclass(frozen=True, eq=False)
class ProfileSeries:
    """Original signal or selected source slice, with display-only X alignment."""

    layer: RenderLayer
    values: RealArray
    shown: RealArray
    valid: BoolArray
    clipped: BoolArray
    source_x: RealArray
    mapping: AxisMap
    index: int | None = None
    row: bool = True

    @property
    def key(self) -> tuple[object, ...]:
        """Cache calculations independently of color, alignment and selection."""
        data = self.layer.data_key or (id(self.layer.frame.scalar), id(self.layer.frame.valid))
        return (self.layer.uid, data,
                self.layer.frame.value_limits, self.row, self.index, self.layer.threshold)

    @property
    def label(self) -> str:
        """Describe the actual source row/column after coordinate alignment."""
        suffix = f" / {'Row' if self.row else 'Column'} {self.index}" if self.index is not None else ""
        return f"{self.layer.label}{suffix}"


def profile_series(layer: RenderLayer, row: bool = True, position: float = 0) -> ProfileSeries | None:
    """Sample the nearest source row/column at a shared display position.

    Returns None for point clouds or slices outside this layer. Derivatives use
    original X coordinates; stretching never resamples or changes source values.
    """
    frame = layer.frame
    if frame.point_coordinates is not None:
        return None
    index: int | None = None
    if frame.scalar.ndim == 2:
        coordinate = (layer.y if row else layer.x).inverse(position)
        source = (frame.y_mapping if row else frame.x_mapping).inverse(coordinate)
        start = frame.y_start if row else frame.x_start
        extent = frame.scalar.shape[0 if row else 1]
        if source < start - 0.5 or source >= start + extent - 0.5:
            return None
        index = int(np.floor(source + 0.5))
        local = index - start
        samples = (local, slice(None)) if row else (slice(None), local)
        values, shown = frame.scalar[samples], frame.display_scalar[samples]
        valid, clipped = frame.valid[samples], frame.clip_kind[samples] != 0
        x_start = frame.x_start if row else frame.y_start
        mapping = frame.x_mapping if row else frame.y_mapping
        x = mapping.array(np.arange(x_start, x_start + len(values), dtype=np.float64))
    else:
        values, shown, valid, clipped = frame.scalar, frame.display_scalar, frame.valid, frame.clip_kind != 0
        x = frame.x_values if frame.x_values is not None else np.arange(frame.x_start, frame.x_start + len(values), dtype=np.float64)
    return ProfileSeries(layer, values, shown, valid, clipped, x, layer.x if row else layer.y, index, row)
