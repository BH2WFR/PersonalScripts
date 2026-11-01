"""Modal selected-channel image composer with gains and checkerboard preview.

Requirements: existing PySide6/NumPy. Usage: WorkspaceWindow supplies only tree
selection candidates. Source extraction and full output run in background jobs;
small previews are debounced with a single-shot timer, never a polling timer.
Finite extrema are cached per source; auto mapping can use each source alone
or all currently assigned output sources (including alpha). ImagePreview owns
the shared raster pan/zoom behavior used by figure export too.
Optional range linking makes the first row drive every mapping and limit;
current-channel auto then uses the first row's source, without linking gains.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from typing import cast

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from .complex_merge import MergeInput
from .data_model import ColorArray, ImageMember
from .fourier import TransformResult
from .image_merge import (ImageChannel, ImageMapping, ImageMergeMode, PreparedImages,
                          channel_limits, generate_image, merge_pixels, prepare_images)
from .image_preview import ImagePreview
from .qt_widgets import NoWheelComboBox, NoWheelDoubleSpinBox

PREVIEW_DELAY_MS = 120
MAX_GAIN = 1000.0
MANUAL_LIMIT = 1e300


class _Signals(QtCore.QObject):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class _Job(QtCore.QRunnable):
    def __init__(self, operation: Callable[[], PreparedImages | TransformResult]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.operation())
        except Exception as error:
            self.signals.failed.emit(f"{type(error).__name__}: {error}")


def _preview_image(pixels: ColorArray) -> QtGui.QImage:
    """Copy H-by-W-by-2/3/4 pixels into Qt-owned RGBA; reject other layouts."""
    if pixels.ndim != 3 or pixels.shape[2] not in (2, 3, 4):
        raise ValueError("Preview requires an H-by-W-by-2/3/4 image (MA, RGB or RGBA).")
    height, width, channels = pixels.shape
    rgba = np.full((height, width, 4), 255, dtype=np.uint8)
    if channels == 2:
        rgba[..., :3] = pixels[..., :1]
        rgba[..., 3] = pixels[..., 1]
    else:
        rgba[..., :channels] = pixels
    return QtGui.QImage(rgba.data, width, height, rgba.strides[0],
                       QtGui.QImage.Format.Format_RGBA8888).copy()


@dataclass
class _Row:
    member: ImageMember
    source: NoWheelComboBox
    gain: NoWheelDoubleSpinBox
    mapping: NoWheelComboBox
    lower: NoWheelDoubleSpinBox
    upper: NoWheelDoubleSpinBox
    extrema: QtWidgets.QLabel

    def snapshot(self) -> ImageChannel:
        """Capture a row without retaining any widget in the worker input."""
        return ImageChannel(int(self.source.currentData()), self.gain.value(),
                            ImageMapping(self.mapping.currentData()), self.lower.value(), self.upper.value(),
                            255 if self.member == ImageMember.ALPHA else 0)


class ImageMergeDialog(QtWidgets.QDialog):
    """Assign selected sources to output channels, preview, then generate.

    Args:
        sources: Explicitly selected scalar candidates; no session-wide fallback.
        parent: Owning workspace. The generated signal delivers an image result.
    """

    generated = QtCore.Signal(object)

    def __init__(self, sources: tuple[MergeInput, ...], parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.sources = sources
        self.prepared: PreparedImages | None = None
        self._job: _Job | None = None
        self._busy = False
        self.rows: list[_Row] = []
        self.setWindowTitle("Image merge — selected matrices / channels")
        self.setModal(True)
        self.resize(1000, 720)
        layout = QtWidgets.QVBoxLayout(self)
        self.settings = QtWidgets.QWidget()
        fields = QtWidgets.QVBoxLayout(self.settings)
        top = QtWidgets.QFormLayout()
        self.mode = NoWheelComboBox()
        for mode in ImageMergeMode:
            self.mode.addItem(mode.value, mode)
        self.result_name = QtWidgets.QLineEdit()
        self.result_name.setPlaceholderText("Automatic: Image merge · RGB / RGBA / Monochrome + alpha")
        top.addRow("Output (8-bit per channel)", self.mode)
        top.addRow("Result name", self.result_name)
        self.link_ranges = QtWidgets.QCheckBox("Link input ranges")
        self.link_ranges.setToolTip("Use the first row's range mode and limits for all output channels.\n"
                                    "Current-channel auto uses the first row's source; shared auto uses all assigned sources.\n"
                                    "Source assignments and gains remain independent.")
        top.addRow(self.link_ranges)
        fields.addLayout(top)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(6)
        fields.addLayout(self.grid)
        layout.addWidget(self.settings)
        note = QtWidgets.QLabel("Full-size channels → range → gain → 8-bit image. Hover for details.")
        note.setToolTip(
            "Crop, value bounds and overlay alignment are ignored. All shapes must match. "
            "RGB/M gains adjust brightness / white balance; A gain adjusts opacity. "
            "NaN / -Inf become 0, +Inf becomes 255. Constant auto-range channels become 0. "
            "Alpha is stored separately, without multiplying the color channels.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.preview = ImagePreview()
        layout.addWidget(self.preview, 1)
        self.status = QtWidgets.QLabel("Preparing selected sources…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.generate = self.buttons.addButton("Generate image matrix", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.generate.clicked.connect(self._generate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self._preview)
        self.mode.currentIndexChanged.connect(self._build_rows)
        self.link_ranges.toggled.connect(self._changed)
        self._build_rows()
        self.set_busy(True)
        QtCore.QTimer.singleShot(0, self._prepare)

    def _build_rows(self) -> None:
        previous = {row.member: row.snapshot() for row in self.rows}
        leader = self.rows[0].snapshot() if self.rows and self.link_ranges.isChecked() else None
        self.rows.clear()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.deleteLater()
        for column, title in enumerate(("Output", "Source matrix / channel", "Finite min / max", "Gain", "Input range", "Minimum", "Maximum")):
            self.grid.addWidget(QtWidgets.QLabel(title), 0, column)
        mode = ImageMergeMode(self.mode.currentData())
        for index, member in enumerate(mode.channels):
            source, mapping = NoWheelComboBox(), NoWheelComboBox()
            source.setMinimumContentsLength(25)
            source.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            source.addItem("Constant 255 (opaque)" if member == ImageMember.ALPHA else "Constant 0 (black)", -1)
            for candidate, item in enumerate(self.sources):
                source.addItem(item.label, candidate)
            source.setCurrentIndex(index + 1 if index < len(self.sources) else 0)
            gain = NoWheelDoubleSpinBox()
            gain.setRange(0, MAX_GAIN)
            gain.setDecimals(4)
            gain.setSingleStep(0.05)
            gain.setValue(1.0)
            for preset in ImageMapping:
                mapping.addItem(preset.value, preset)
            mapping.setToolTip("Current channel: its own finite min/max.\n"
                               "All assigned channels: shared finite min/max across assigned sources, including A.\n"
                               "Constants and unused candidates are excluded. Gain is applied after mapping.")
            lower, upper = NoWheelDoubleSpinBox(), NoWheelDoubleSpinBox()
            for field in (lower, upper):
                field.setRange(-MANUAL_LIMIT, MANUAL_LIMIT)
                field.setDecimals(8)
            upper.setValue(255)
            extrema = QtWidgets.QLabel("Preparing…")
            row = _Row(member, source, gain, mapping, lower, upper, extrema)
            self.rows.append(row)
            if member in previous:
                old = previous[member]
                source.setCurrentIndex(source.findData(old.source))
                gain.setValue(old.gain)
                mapping.setCurrentIndex(mapping.findData(old.mapping))
                lower.setValue(old.lower)
                upper.setValue(old.upper)
            elif leader is not None:
                mapping.setCurrentIndex(mapping.findData(leader.mapping))
                lower.setValue(leader.lower)
                upper.setValue(leader.upper)
            for column, widget in enumerate((QtWidgets.QLabel(member.value), source, extrema, gain, mapping, lower, upper)):
                self.grid.addWidget(widget, index + 1, column)
            source.currentIndexChanged.connect(self._changed)
            mapping.currentIndexChanged.connect(self._changed)
            for field in (gain, lower, upper):
                field.valueChanged.connect(self._changed)
        self.grid.setColumnStretch(1, 1)
        self._changed()

    def _channels(self) -> tuple[ImageChannel, ...]:
        """Capture output assignments, applying the linked leader without rounding."""
        channels = tuple(row.snapshot() for row in self.rows)
        if not self.link_ranges.isChecked() or not channels:
            return channels
        leader = channels[0]
        return tuple(replace(channel, mapping=leader.mapping, lower=leader.lower, upper=leader.upper,
                             range_source=leader.source) for channel in channels)

    def _changed(self) -> None:
        channels = self._channels()
        linked = self.link_ranges.isChecked()
        for index, (row, channel) in enumerate(zip(self.rows, channels, strict=True)):
            has_source = channel.source >= 0
            editable = index == 0 if linked else has_source
            row.mapping.setEnabled(editable)
            manual = channel.mapping == ImageMapping.MANUAL
            row.lower.setEnabled(editable and manual)
            row.upper.setEnabled(editable and manual)
            if linked and index > 0:
                with QtCore.QSignalBlocker(row.mapping), QtCore.QSignalBlocker(row.lower), QtCore.QSignalBlocker(row.upper):
                    row.mapping.setCurrentIndex(row.mapping.findData(channel.mapping))
                    row.lower.setValue(channel.lower)
                    row.upper.setValue(channel.upper)
            if not has_source:
                row.extrema.setText(f"{channel.constant} / {channel.constant} (constant)")
                row.extrema.setToolTip("Constant output before gain; excluded from shared auto range.")
            elif self.prepared is not None:
                limits = self.prepared.ranges[channel.source]
                row.extrema.setText(f"{limits[0]:.6g} / {limits[1]:.6g}" if limits is not None else "No finite values")
                row.extrema.setToolTip(f"Finite min: {limits[0]:.17g}\nFinite max: {limits[1]:.17g}"
                                       if limits is not None else "NaN and infinities are excluded from auto range.")
            if (has_source or linked) and not manual and self.prepared is not None:
                low, high = channel_limits(self.prepared, channel, channels)
                with QtCore.QSignalBlocker(row.lower), QtCore.QSignalBlocker(row.upper):
                    row.lower.setValue(low)
                    row.upper.setValue(high)
        self.generate.setEnabled(False)
        if self.prepared is not None and not self._busy:
            self._timer.start()

    def _start(self, operation: Callable[[], PreparedImages | TransformResult]) -> None:
        self.set_busy(True)
        self._job = _Job(operation)
        self._job.signals.done.connect(self._done)
        self._job.signals.failed.connect(self._failed)
        QtCore.QThreadPool.globalInstance().start(self._job)

    def _prepare(self) -> None:
        self._start(partial(prepare_images, self.sources))

    def _done(self, result: object) -> None:
        self._job = None
        self.set_busy(False)
        if isinstance(result, PreparedImages):
            self.prepared = result
            self._changed()
            self._timer.stop()
            self._preview()
        else:
            self.generated.emit(cast(TransformResult, result))

    def _failed(self, message: str) -> None:
        self._job = None
        self.set_busy(False)
        self.generate.setEnabled(False)
        self.status.setText(message)
        QtWidgets.QMessageBox.warning(self, "Cannot merge images", message)

    def _preview(self) -> None:
        if self.prepared is None or self._busy:
            return
        try:
            mode = ImageMergeMode(self.mode.currentData())
            pixels = merge_pixels(self.prepared, mode, self._channels(), preview=True)
            self.preview.set_image(_preview_image(pixels))
            self.status.setText(f"Output: {self.prepared.shape[1]} × {self.prepared.shape[0]} pixels; {mode.value}, 8-bit. "
                                "Sampled preview; the generated image keeps full resolution.")
            self.generate.setEnabled(True)
        except ValueError as error:
            self.status.setText(str(error))
            self.generate.setEnabled(False)

    def _generate(self) -> None:
        if self.prepared is None or self._busy:
            return
        self._timer.stop()
        self.status.setText("Generating full-resolution image…")
        self._start(partial(generate_image, self.prepared, ImageMergeMode(self.mode.currentData()),
                            self._channels(), self.result_name.text()))

    def set_busy(self, busy: bool) -> None:
        """Retain inputs and prevent closing until the background job finishes."""
        self._busy = busy
        self.settings.setEnabled(not busy)
        self.buttons.setEnabled(not busy)

    def reject(self) -> None:
        if not self._busy:
            self._timer.stop()
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            self._timer.stop()
            super().closeEvent(event)
