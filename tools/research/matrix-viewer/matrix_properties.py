"""Inspect source metadata and display settings; calculate statistics on demand.

Requirements: NumPy and PySide6, already used by the viewer.
Usage: MatrixPropertiesDialog snapshots a selected entry without changing it.
Opening the dialog never scans samples. The Calculate button uses a background
worker with chunked reductions and one finite-value buffer for exact quartiles.
NaN is excluded from extrema; infinity is retained with the finite extreme.
Other statistics use finite values only; variance uses the population (ddof=0).
Statistics form a population/category/property tree instead of a wide table.
Complex source statistics report real, imaginary and magnitude separately.
Array bytes describe logical storage, not process RSS or exclusive ownership.
View snapshots include the shared color mapping bounds and actual source slice
after overlay alignment. Slice statistics remain button-triggered, and reuse
the profile's channel/alpha interpretation without calculating derivatives.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
from PySide6 import QtCore, QtWidgets

from .data_model import Array, RealArray, ViewMode
from .workspace import MatrixEntry, Setting, active_channel
from .plot_support import range_texts

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow

STAT_BUFFER_SIZE = 65536


@dataclass(frozen=True)
class ViewProperties:
    """Read-only display metadata and slice populations captured on the UI thread."""

    color: tuple[tuple[str, str], ...] = ()
    slice: tuple[tuple[str, str], ...] = ()
    sources: tuple[tuple[str, Array], ...] = ()


def capture_view_properties(window: "WorkspaceWindow", entry: MatrixEntry) -> ViewProperties:
    """Read the currently rendered color bounds and this entry's selected slice.

    Hidden, unprepared and out-of-range layers have no current slice. Overlay
    indices come from the existing profile series, including alignment and crop.
    The operation never fits a view, learns lock bounds or scans sample values.
    """
    frame = entry.frame
    if frame is None or entry.document.is_text or entry.selection.mode not in (ViewMode.MATRIX, ViewMode.POINTS):
        return ViewProperties()
    color_rows: list[tuple[str, str]] = [("Shared by", "2D image / 3D surface"),
        ("Expand-only lock", str(window.color_range_lock.isChecked()))]
    if not entry.visible:
        color_rows.append(("Current color range", "Not displayed (hidden channel)"))
    elif window._overlay():
        color_rows.append(("Current color range", "Not applicable: solid-color overlay"))
    elif frame.composite:
        color_rows.append(("Current color range", "Not applicable: original image colors"))
    else:
        limits = (window.image_view._levels if entry.selection.mode == ViewMode.MATRIX
                  else window.surface_view._color_limits)
        if limits is None:
            color_rows.append(("Current color range", "Not rendered yet"))
        else:
            maximum, minimum = range_texts(limits, (False, False))
            color_rows.extend((("Color minimum", minimum), ("Color maximum", maximum),
                ("Finite mapping bounds", f"{limits[0]:.12g} .. {limits[1]:.12g}"),
                ("Range meaning", "Current finite color mapping, including manual bounds / lock. Data extrema are calculated separately.")))
    if entry.selection.mode != ViewMode.MATRIX:
        return ViewProperties(tuple(color_rows))
    if not entry.visible or not window._profile_selected:
        return ViewProperties(tuple(color_rows), (("Current slice", "No selected slice for this channel"),))

    row = window.profile_direction.currentIndex() == 0
    index = window.profile_index.value()
    sources: tuple[tuple[str, Array], ...] = ()
    if window._overlay():
        series = next((item for item in window.overlay_profile._series if item.layer.uid == entry.uid), None)
        if series is None or series.index is None:
            return ViewProperties(tuple(color_rows), (("Current slice", "Outside this matrix's displayed extent"),))
        index = series.index
        sources = (("Current slice / current channel (before value bounds)", series.values),)
    else:
        sources = tuple((f"Current slice / {trace.label} (before value bounds)", trace.values)
                        for trace in window.profile_view.signal_traces)
    local = index - (frame.y_start if row else frame.x_start)
    if not 0 <= local < frame.scalar.shape[0 if row else 1]:
        return ViewProperties(tuple(color_rows), (("Current slice", "Outside the current index crop"),))
    values = frame.scalar[local, :] if row else frame.scalar[:, local]
    if not sources:
        sources = (("Current slice / current channel (before value bounds)", values),)
    slice_label = f"Current slice / {'Row' if row else 'Column'} {index}"
    sources = tuple((name.replace("Current slice", slice_label, 1), values) for name, values in sources)
    source_position = (frame.y_mapping if row else frame.x_mapping).forward(index)
    start = frame.x_start if row else frame.y_start
    along = frame.x_mapping if row else frame.y_mapping
    rows = (("Direction", "Row" if row else "Column"),
            ("Source row / column (zero-based)", str(index)),
            ("Position in current crop (zero-based)", str(local)),
            ("Source Y" if row else "Source X", f"{source_position:.12g}"),
            ("Selected display Y" if row else "Selected display X", f"{window._profile_position():.12g}"),
            ("Samples per channel", f"{values.size:,}"),
            ("Source sample indices (inclusive)", f"{start} .. {start + values.size - 1}"),
            ("Source X extent" if row else "Source Y extent",
             f"{along.forward(start):.12g} .. {along.forward(start + values.size - 1):.12g}"),
            ("Statistics", "Use Calculate statistics: Current slice rows. Values precede value bounds; image alpha weighting matches the profile."))
    return ViewProperties(tuple(color_rows), rows, sources)


@dataclass(frozen=True)
class Statistics:
    """Finite-only population statistics, with separate nonfinite counts."""

    count: int
    finite: int
    nan: int
    positive_inf: int
    negative_inf: int
    minimum: str
    maximum: str
    mean: str
    standard_deviation: str
    variance: str
    rms: str
    peak_to_peak: str
    zeros: int
    median: str
    first_quartile: str
    third_quartile: str
    interquartile_range: str


def calculate_statistics(values: Array, *, magnitude: bool = False) -> Statistics:
    """Calculate descriptive statistics without modifying source values.

    Args:
        values: Real values, or complex values when magnitude is requested.
        magnitude: Calculate absolute values per chunk rather than allocating
            a full-size magnitude array. Real/imaginary views need no copy.

    Returns:
        Counts, extrema excluding NaN, and finite-only descriptive statistics.
        Missing finite statistics are marked N/A. Variance uses ddof=0;
        quartiles use linear interpolation on an owned finite-value buffer.
    """
    finite_count = nan_count = positive = negative = zeros = 0
    low: int | float | np.longdouble | None = None
    high: int | float | np.longdouble | None = None
    mean = np.longdouble(0)
    if np.iscomplexobj(values) and not magnitude:
        raise ValueError("Choose real, imaginary or magnitude statistics for complex data.")
    iterator = np.nditer(values, flags=["external_loop", "buffered", "zerosize_ok"],
                         op_flags=["readonly"], buffersize=STAT_BUFFER_SIZE, order="K")
    for chunk in iterator:
        data = np.abs(chunk) if magnitude else chunk
        nan_count += int(np.count_nonzero(np.isnan(data)))
        positive += int(np.count_nonzero(np.isposinf(data)))
        negative += int(np.count_nonzero(np.isneginf(data)))
        finite = data[np.isfinite(data)]
        zeros += int(np.count_nonzero(finite == 0))
        if not finite.size:
            continue
        chunk_low, chunk_high = finite.min().item(), finite.max().item()
        low = chunk_low if low is None else min(low, chunk_low)
        high = chunk_high if high is None else max(high, chunk_high)
        # Normalize each chunk before reduction to avoid overflow for finite
        # float64 samples near their maximum (Windows longdouble is float64).
        floats = finite.astype(np.longdouble, copy=False)
        peak = np.max(np.abs(floats))
        chunk_mean = np.mean(floats / peak, dtype=np.longdouble) * peak if peak else np.longdouble(0)
        new_count = finite_count + int(finite.size)
        mean = mean * (finite_count / new_count) + chunk_mean * (int(finite.size) / new_count)
        finite_count = new_count

    def number(value: int | float | np.longdouble | None) -> str:
        return "N/A" if value is None else str(value) if isinstance(value, int) else f"{value:.12g}"

    finite_low, finite_high = number(low), number(high)
    minimum = f"-inf ({finite_low})" if negative else finite_low if finite_count else "inf (N/A)" if positive else "N/A"
    maximum = f"inf ({finite_high})" if positive else finite_high if finite_count else "-inf (N/A)" if negative else "N/A"
    deviation = variance = rms = span = median = q1 = q3 = iqr = "N/A"
    if finite_count:
        assert low is not None and high is not None
        scale = max(abs(np.longdouble(low)), abs(np.longdouble(high)))
        normalized_mean = mean / scale if scale else np.longdouble(0)
        squared_deviations = squared_values = np.longdouble(0)
        # One owned buffer supports exact order statistics; partition it in
        # place so source arrays (including memory maps) remain untouched.
        samples = np.empty(finite_count, dtype=values.real.dtype)
        offset = 0
        iterator = np.nditer(values, flags=["external_loop", "buffered", "zerosize_ok"],
                             op_flags=["readonly"], buffersize=STAT_BUFFER_SIZE, order="K")
        for chunk in iterator:
            data = np.abs(chunk) if magnitude else chunk
            finite = data[np.isfinite(data)]
            samples[offset:offset + finite.size] = finite
            offset += finite.size
            floats = finite.astype(np.longdouble)
            normalized = floats / scale if scale else np.zeros(finite.size, dtype=np.longdouble)
            # Subtract before scaling to retain small deviations on a large
            # baseline. Only opposite extreme signs need scaled subtraction.
            with np.errstate(over="ignore", invalid="ignore"):
                centered = (floats - mean) / scale if scale else np.zeros(finite.size, dtype=np.longdouble)
            overflow = ~np.isfinite(centered)
            centered[overflow] = normalized[overflow] - normalized_mean
            squared_deviations += np.sum(np.square(centered), dtype=np.longdouble)
            squared_values += np.sum(np.square(normalized), dtype=np.longdouble)
        std = min(np.sqrt(squared_deviations / finite_count), np.longdouble(1)) * scale
        deviation = number(std)
        rms = number(min(np.sqrt(squared_values / finite_count), np.longdouble(1)) * scale)
        # An unrepresentably large variance/range is legitimately infinite,
        # even when standard deviation and all input values remain finite.
        with np.errstate(over="ignore"):
            variance = number(std * std)
            span = number(np.longdouble(high) - np.longdouble(low))
        positions = tuple((finite_count - 1) * fraction for fraction in (0.25, 0.5, 0.75))
        indices = sorted({index for position in positions for index in (int(np.floor(position)), int(np.ceil(position)))})
        samples.partition(indices)
        quartiles: list[np.longdouble] = []
        for position in positions:
            lower, upper = int(np.floor(position)), int(np.ceil(position))
            weight = np.longdouble(position - lower)
            quartiles.append(np.longdouble(samples[lower]) * (1 - weight) + np.longdouble(samples[upper]) * weight)
        q1, median, q3 = (number(value) for value in quartiles)
        with np.errstate(over="ignore"):
            iqr = number(quartiles[2] - quartiles[0])
    return Statistics(int(values.size), finite_count, nan_count, positive, negative, minimum, maximum,
                      number(mean) if finite_count else "N/A", deviation, variance, rms, span, zeros,
                      median, q1, q3, iqr)


class _StatisticsSignals(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class _StatisticsJob(QtCore.QRunnable):
    """Keep numeric work outside Qt; source arrays remain strongly referenced."""

    def __init__(self, sources: tuple[tuple[str, Array], ...]) -> None:
        super().__init__()
        self.sources = sources
        self.signals = _StatisticsSignals()

    def run(self) -> None:
        """Report per-source statistics or an explicit error to the GUI thread."""
        try:
            rows: list[tuple[str, Statistics]] = []
            for name, array in self.sources:
                if np.iscomplexobj(array):
                    rows.extend(((f"{name} / Real", calculate_statistics(cast(RealArray, array.real))),
                                 (f"{name} / Imaginary", calculate_statistics(cast(RealArray, array.imag))),
                                 (f"{name} / Magnitude", calculate_statistics(array, magnitude=True))))
                else:
                    rows.append((name, calculate_statistics(array)))
            self.signals.finished.emit(tuple(rows))
        except Exception as error:
            self.signals.failed.emit(f"{type(error).__name__}: {error}")


class MatrixPropertiesDialog(QtWidgets.QDialog):
    """Read-only snapshot with manually requested statistics and no data edits.

    Args:
        entry: Target source/channel, independently of its visibility.
        settings: Current effective settings, including shared view ranges.
        parent: Workspace owning this modal dialog and its lifetime.
        view: Optional snapshot of rendered color bounds and selected slice.
    """

    def __init__(self, entry: MatrixEntry, settings: dict[str, Setting],
                 parent: QtWidgets.QWidget | None = None, *, view: ViewProperties | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Matrix properties")
        self.resize(880, 640)
        self._job: _StatisticsJob | None = None
        document, frame = entry.document, entry.frame
        source = document.image_source.pixels if document.image_source is not None else document.array
        self._sources: tuple[tuple[str, Array], ...] = () if document.is_text else (
            ("Original matrix", cast(Array, source)),)
        if frame is not None and not document.is_text:
            self._sources += (("Current channel / index crop (before value bounds)", frame.scalar),)
        if view is not None:
            self._sources += view.sources

        layout = QtWidgets.QVBoxLayout(self)
        identity = QtWidgets.QLabel(f"{entry.label} / {active_channel(entry).label}")
        identity.setWordWrap(True)
        identity.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(identity)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.metadata = QtWidgets.QTreeWidget()
        self.metadata.setHeaderLabels(["Property", "Value"])
        self.metadata.setColumnWidth(0, 235)
        self.metadata.setWordWrap(True)
        self.tabs.addTab(self.metadata, "Metadata / display")

        def group(title: str, rows: list[tuple[str, str]]) -> None:
            node = QtWidgets.QTreeWidgetItem(self.metadata, [title])
            for key, value in rows:
                item = QtWidgets.QTreeWidgetItem(node, [key, value])
                item.setToolTip(0, key)
                item.setToolTip(1, value)
            node.setExpanded(True)

        if view is not None:
            if view.color:
                group("Current color range", list(view.color))
            if view.slice:
                group("Current slice", list(view.slice))
        try:
            file_size = f"{document.path.stat().st_size:,} bytes (whole file / archive)"
        except OSError:
            file_size = "Not available (in-memory result or missing file)"
        group("Source", [("Name", entry.label), ("File / source", str(document.path)),
              ("Format", document.path.suffix.upper().lstrip(".") or "In memory"),
              ("Archive member / sheet", document.key or "—"),
              ("Shape", str(source.shape)), ("Dimensions", str(source.ndim)),
              ("Elements", f"{source.size:,}"), ("dtype", str(source.dtype)),
              ("Bytes per element", str(source.dtype.itemsize)),
              ("Array storage", f"{source.nbytes:,} bytes ({source.nbytes / 1048576:.3f} MiB); logical size, may be shared"),
              ("File size", file_size), ("Complex", str(document.is_complex)),
              ("Writeable", str(source.flags.writeable)),
              ("Contiguous", f"C: {source.flags.c_contiguous}; F: {source.flags.f_contiguous}")])
        if document.image_source is not None:
            image = document.image_source
            group("Image", [("File format", image.metadata.format), ("Stored mode", image.metadata.mode),
                  ("Stored bit depth", image.metadata.depth), ("Decoded layout", image.layout),
                  ("Channels", ", ".join(channel.value for channel in image.channels))])
        crop = entry.crop
        selection = entry.selection
        coordinate_rows = [
            ("X axis / sample axis", str(selection.x_axis)),
            ("Y axis / row axis", str(selection.y_axis) if selection.y_axis is not None else "Not applicable"),
            ("Channel axis", str(selection.channel_axis) if selection.channel_axis is not None else "Not applicable")]
        if selection.coordinate_axis is not None:
            coordinate_rows.append(("Coordinate table", f"Axis {selection.coordinate_axis}; X/Y/Z order {selection.coordinate_order}"))
        group("Current interpretation", [("Channel", active_channel(entry).label),
              ("Mode", entry.selection.mode.value), ("Visible", str(entry.visible)),
              ("Prepared shape", str(frame.scalar.shape) if frame is not None else "Not prepared"),
              ("Index crop (inclusive, zero-based)",
               f"X: {crop.x_start} .. {crop.x_end if crop.x_end is not None else 'end'}; "
               f"Y: {crop.y_start} .. {crop.y_end if crop.y_end is not None else 'end'}"),
              ("Value bounds", f"{entry.limits.mode.value}: "
               f"{entry.limits.lower if entry.limits.lower is not None else 'unbounded'} .. "
               f"{entry.limits.upper if entry.limits.upper is not None else 'unbounded'}"),
              *coordinate_rows,
              ("Overlay color", entry.color), ("Opacity", f"{entry.opacity:g}"),
              ("Alignment", f"X: {entry.align_x.value}; Y: {entry.align_y.value}; Z: {entry.align_z.value}")])
        group("Display settings", [(name.replace("_", " "), str(value)) for name, value in sorted(settings.items())])
        provenance = [(name, str(value)) for name, value in (
            ("Import", document.import_provenance), ("Complex merge", document.complex_provenance),
            ("Conversion", document.conversion_provenance), ("Fourier", document.transform),
            ("Laplace", document.laplace)) if value]
        if provenance:
            group("Provenance", provenance)

        page = QtWidgets.QWidget()
        stats_layout = QtWidgets.QVBoxLayout(page)
        help_text = QtWidgets.QLabel("Click Calculate statistics to scan samples. Statistics use finite values only; variance / standard deviation use ddof=0.\n"
            "NaN is excluded from extrema. inf (90000) means an infinite extreme with finite extreme 90000.\n"
            "Original matrix and current channel/crop are separate populations; value bounds do not alter these statistics.\n"
            "Exact quartiles use linear interpolation and require a temporary copy of finite values, one population at a time.")
        help_text.setWordWrap(True)
        stats_layout.addWidget(help_text)
        self.calculate = QtWidgets.QPushButton("Calculate statistics")
        self.calculate.setEnabled(bool(self._sources))
        self.calculate.clicked.connect(self._calculate)
        stats_layout.addWidget(self.calculate)
        self.status = QtWidgets.QLabel("Not calculated" if self._sources else "String arrays: numeric statistics unavailable")
        stats_layout.addWidget(self.status)
        self.statistics = QtWidgets.QTreeWidget()
        self.statistics.setHeaderLabels(["Population / statistic", "Value"])
        self.statistics.setColumnWidth(0, 430)
        self.statistics.setRootIsDecorated(True)
        self.statistics.setAlternatingRowColors(True)
        stats_layout.addWidget(self.statistics, 1)
        self.tabs.addTab(page, "Statistics")
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def _calculate(self) -> None:
        self.calculate.setEnabled(False)
        self.status.setText("Calculating…")
        self._job = _StatisticsJob(self._sources)
        self._job.signals.finished.connect(self._finished)
        self._job.signals.failed.connect(self._failed)
        QtCore.QThreadPool.globalInstance().start(self._job)

    def _finished(self, result: tuple[tuple[str, Statistics], ...]) -> None:
        self.statistics.clear()
        for name, stats in result:
            population = QtWidgets.QTreeWidgetItem(self.statistics, [name])
            population.setToolTip(0, name)
            population.setExpanded(True)
            groups = (
                ("Size / validity", (("Total count", f"{stats.count:,}"), ("Finite count", f"{stats.finite:,}"),
                    ("NaN count", f"{stats.nan:,}"), ("+Inf count", f"{stats.positive_inf:,}"),
                    ("-Inf count", f"{stats.negative_inf:,}"), ("Zero count", f"{stats.zeros:,}"))),
                ("Extrema", (("Minimum", stats.minimum), ("Maximum", stats.maximum))),
                ("Location (finite)", (("Mean", stats.mean), ("Median (Q2)", stats.median),
                    ("First quartile (Q1, 25%)", stats.first_quartile), ("Third quartile (Q3, 75%)", stats.third_quartile))),
                ("Spread (finite)", (("Standard deviation (population, ddof=0)", stats.standard_deviation),
                    ("Variance (population, ddof=0)", stats.variance), ("Peak-to-peak range", stats.peak_to_peak),
                    ("Interquartile range (Q3 - Q1)", stats.interquartile_range))),
                ("Amplitude (finite)", (("Root mean square (RMS)", stats.rms),)),
            )
            for title, rows in groups:
                group = QtWidgets.QTreeWidgetItem(population, [title])
                group.setExpanded(True)
                for label, value in rows:
                    item = QtWidgets.QTreeWidgetItem(group, [label, value])
                    item.setToolTip(0, label)
                    item.setToolTip(1, value)
        self.status.setText("Calculated. Finite-only statistics; source arrays unchanged.")
        self.calculate.setEnabled(True)

    def _failed(self, message: str) -> None:
        self.status.setText(message)
        self.calculate.setEnabled(True)
