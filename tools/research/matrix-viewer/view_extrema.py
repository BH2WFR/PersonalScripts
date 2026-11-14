"""Explicit, asynchronous data-extrema calculation for the displayed view.

Requirements: existing NumPy/PySide6. Rendering retains its own finite range
calculations. This module scans full-resolution samples only after a button
click, includes source infinities, applies finite-value crop/clamp settings,
and rejects stale results after data/slice changes. No timers or polling.
Busy actions transfer keyboard focus to their own tab bar before disabling,
preventing Qt from focusing tree color buttons and scrolling away checkboxes.
"""

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import numpy as np
from PySide6 import QtCore

from .data_model import BoolArray, RealArray, ViewMode
from .profile_view import CurvePane, ProfileView
from .image_view import ImageView
from .surface_view import SurfaceView

if TYPE_CHECKING:
    from .workspace_window import WorkspaceWindow

EXTREMA_BUFFER_SIZE = 65536
type ExtremaTarget = CurvePane | ImageView | SurfaceView


@dataclass(frozen=True)
class ExtremaInput:
    """Original values, finite-value display transform and visibility mask."""

    original: RealArray
    shown: RealArray
    valid: BoolArray


@dataclass(frozen=True)
class ExtremaResult:
    """Maximum/minimum strings, including infinity and finite fallback values."""

    maximum: str
    minimum: str


def calculate_extrema(sources: tuple[ExtremaInput, ...]) -> ExtremaResult:
    """Reduce visible data in bounded chunks, retaining original infinities.

    Finite samples excluded by value bounds do not contribute; clamped samples
    use their displayed value. NaN is omitted. Infinities remain explicit even
    when marker drawing is disabled. Source arrays are never modified.
    """
    low: int | float | np.longdouble | None = None
    high: int | float | np.longdouble | None = None
    negative = positive = False
    for source in sources:
        iterator = np.nditer([source.original, source.shown, source.valid],
            flags=["external_loop", "buffered", "zerosize_ok"], op_flags=[["readonly"], ["readonly"], ["readonly"]],
            buffersize=EXTREMA_BUFFER_SIZE, order="K")
        for original, shown, valid in iterator:
            negative |= bool(np.any(np.isneginf(original)))
            positive |= bool(np.any(np.isposinf(original)))
            finite = shown[valid & np.isfinite(shown)]
            if finite.size:
                a, b = finite.min().item(), finite.max().item()
                low = a if low is None else min(low, a)
                high = b if high is None else max(high, b)

    def number(value: int | float | np.longdouble | None) -> str:
        return "N/A" if value is None else str(value) if isinstance(value, int) else f"{value:.10g}"

    minimum = f"-inf ({number(low)})" if negative else number(low) if low is not None else "inf (N/A)" if positive else "N/A"
    maximum = f"inf ({number(high)})" if positive else number(high) if high is not None else "-inf (N/A)" if negative else "N/A"
    return ExtremaResult(maximum, minimum)


class _Signals(QtCore.QObject):
    done = QtCore.Signal(int, object)
    failed = QtCore.Signal(int, str)


class _Job(QtCore.QRunnable):
    def __init__(self, number: int, sources: tuple[ExtremaInput, ...],
                 target: ExtremaTarget) -> None:
        super().__init__()
        self.number, self.sources, self.target = number, sources, target
        self.generation = target.extrema_generation
        self.signals = _Signals()

    def run(self) -> None:
        """Compute without Qt/VTK access, then deliver a generation-tagged result."""
        try:
            self.signals.done.emit(self.number, calculate_extrema(self.sources))
        except Exception as error:
            self.signals.failed.emit(self.number, f"{type(error).__name__}: {error}")


class ViewExtrema(QtCore.QObject):
    """Wire tab-corner actions to on-demand matrix/slice/derivative statistics."""

    def __init__(self, window: "WorkspaceWindow") -> None:
        super().__init__(window)
        self.window = window
        self._jobs: dict[int, _Job] = {}
        self._number = 0
        window.extrema_button.clicked.connect(self.calculate_current)
        for profile in (window.profile_view, window.overlay_profile):
            profile.extrema_button.clicked.connect(partial(self.calculate_profile, profile))
        window.tabs.currentChanged.connect(self._sync_buttons)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.window.extrema_button.setVisible(self.window.tabs.currentIndex() != 2)
        for button, tabs in ((self.window.extrema_button, self.window.tabs),
                             (self.window.profile_view.extrema_button, self.window.profile_view.tabs),
                             (self.window.overlay_profile.extrema_button, self.window.overlay_profile.tabs)):
            if self._jobs and button.hasFocus():
                # Disabling a focused widget advances through the global tab
                # chain, which can reveal an offscreen matrix color button.
                tabs.tabBar().setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            button.setEnabled(not self._jobs)
            button.setText("Calculating…" if self._jobs else "Calculate extrema")

    def calculate_current(self) -> None:
        """Calculate full-resolution values of the visible matrix(s) or 1D page."""
        window = self.window
        if window._layout_mode == ViewMode.SIGNAL:
            self.calculate_profile(window.overlay_profile if window._profile_uses_overlay else window.profile_view)
            return
        index = window.tabs.currentIndex()
        if index not in (0, 1):
            return
        target = window.image_view if index == 0 else window.surface_view
        # A 3D tab must have a current scene before its generation can be tagged.
        if index == 1 and window._surface_dirty:
            window.statusBar().showMessage("Wait for the 3D scene to finish rendering.", 5000)
            return
        sources = tuple(ExtremaInput(entry.frame.scalar, entry.frame.display_scalar, entry.frame.valid)
                        for entry in window.entries if entry.visible and entry.frame is not None
                        and not entry.document.is_text)
        self._start(target, sources)

    def calculate_profile(self, profile: ProfileView) -> None:
        """Use the visible slice/derivative, without calculating another page."""
        derivative = profile.tabs.currentIndex() == 1
        target = profile.derivative_pane if derivative else profile.signal_pane
        if derivative:
            profile._derivative_timer.stop()
            profile._ensure_derivative()
        if profile is self.window.overlay_profile:
            overlay = self.window.overlay_profile
            if derivative:
                sources = tuple(ExtremaInput(result.values, result.values, result.valid)
                                for series in overlay._series if (result := overlay._cache.get(series.key)) is not None)
            else:
                sources = tuple(ExtremaInput(series.values, series.shown, series.valid) for series in overlay._series)
        elif derivative:
            sources = tuple(ExtremaInput(result.values, result.values, result.valid)
                            for result in profile.derivative_results.values())
        else:
            sources = tuple(ExtremaInput(trace.values, trace.shown, trace.valid) for trace in profile.signal_traces)
        self._start(target, sources)

    def _start(self, target: ExtremaTarget, sources: tuple[ExtremaInput, ...]) -> None:
        cached = target.range_notes.data_extrema is not None if isinstance(target, CurvePane) else bool(target.extrema_label.text())
        if cached or self._jobs:
            return
        if not sources:
            self.window.statusBar().showMessage("No data available for extrema calculation.", 5000)
            return
        self._number += 1
        job = _Job(self._number, sources, target)
        self._jobs[job.number] = job
        job.signals.done.connect(self._done)
        job.signals.failed.connect(self._failed)
        self._sync_buttons()
        QtCore.QThreadPool.globalInstance().start(job)

    def _done(self, number: int, result: ExtremaResult) -> None:
        job = self._jobs.pop(number)
        target = job.target
        if job.generation == target.extrema_generation:
            if isinstance(target, CurvePane):
                target.range_notes.data_extrema = (result.maximum, result.minimum)
                target.range_notes.update()
            else:
                target.extrema_label.setText(f"Data max:{result.maximum} min:{result.minimum}")
                target.extrema_label.setToolTip("Full-resolution current crop; finite value bounds applied. Original infinities retained. Before 3D height/alignment scaling.")
                target.extrema_label.show()
        self._sync_buttons()

    def _failed(self, number: int, message: str) -> None:
        self._jobs.pop(number)
        self.window.statusBar().showMessage(f"Extrema calculation failed: {message}", 10000)
        self._sync_buttons()
