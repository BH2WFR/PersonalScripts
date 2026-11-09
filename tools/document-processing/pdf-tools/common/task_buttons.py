"""Shared Pause/Resume and Stop buttons for controlled worker requests."""

from collections.abc import Callable

from PySide6 import QtWidgets
from .jobs import JobRunner
from .protocol import Json


class TaskButtons(QtWidgets.QWidget):
    """Keep button state tied to the runner, including pending pauses and errors."""

    def __init__(self, runner: JobRunner, parent: QtWidgets.QWidget | None = None, *,
                 with_progress: bool = False,
                 external_pause: Callable[[], None] | None = None,
                 external_stop: Callable[[], None] | None = None) -> None:
        super().__init__(parent)
        self.runner = runner
        self._external_pause = external_pause
        self._external_stop = external_stop
        self._external_active = self._external_pausable = self._external_pause_requested = False
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QtWidgets.QProgressBar() if with_progress else None
        if self.progress_bar is not None:
            self.progress_bar.setFixedWidth(120)
            layout.addWidget(self.progress_bar)
            runner.progress.connect(self._progress)
            runner.busyChanged.connect(self._busy_changed)
            self._busy_changed(runner.busy)
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self._pause_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPause)
        self._resume_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaPlay)
        self.stop_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.setToolTip("Cancel this task, including while paused, and return to editing settings.")
        self.pause_button.clicked.connect(self._pause_clicked)
        self.stop_button.clicked.connect(self._stop_clicked)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_button)
        runner.controlChanged.connect(self.refresh)
        runner.busyChanged.connect(self.refresh)
        self.refresh()

    @property
    def _use_external(self) -> bool:
        return self._external_active and not (self.runner.busy and self.runner.controllable)

    def set_external_state(self, active: bool, *, pausable: bool = False, pause_requested: bool = False) -> None:
        """Use the same footer buttons for a window-owned serial network queue."""
        self._external_active = active
        self._external_pausable = pausable
        self._external_pause_requested = pause_requested
        self.refresh()

    def _pause_clicked(self) -> None:
        if self._use_external:
            if self._external_pause is not None:
                self._external_pause()
        else:
            self.runner.toggle_pause()

    def _stop_clicked(self) -> None:
        if self._use_external:
            if self._external_stop is not None:
                self._external_stop()
        else:
            self.runner.stop()

    def _busy_changed(self, busy: bool) -> None:
        assert self.progress_bar is not None
        active = busy and self.runner.controllable
        self.progress_bar.setEnabled(active)
        self.progress_bar.setRange(0, 0 if active else 100)
        self.progress_bar.setValue(0)

    def _progress(self, message: dict[str, Json]) -> None:
        assert self.progress_bar is not None
        total, done = message.get("total"), message.get("done")
        if isinstance(total, int) and total > 0:
            self.progress_bar.setRange(0, total)
        if isinstance(done, int):
            self.progress_bar.setValue(done)

    def refresh(self, *_args: object) -> None:
        active = self.runner.busy and self.runner.controllable
        external = self._use_external
        resume = self._external_pause_requested if external else self.runner.pause_requested
        self.pause_button.setText("Resume" if resume else "Pause")
        self.pause_button.setIcon(self._resume_icon if resume else self._pause_icon)
        self.pause_button.setToolTip("Finish the current recognition request, then pause before the next page. Resume continues the queue."
                                    if external else "Pause at the next safe step. A current page or PDF save may need to finish first.")
        self.pause_button.setEnabled(self._external_pausable if external else active and not self.runner.stopping)
        self.stop_button.setEnabled(self._external_stop is not None if external else active and not self.runner.stopping)
