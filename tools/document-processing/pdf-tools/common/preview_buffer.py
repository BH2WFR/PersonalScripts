"""One reusable RGB shared-memory slot for the serial PDF preview worker."""

from multiprocessing.shared_memory import SharedMemory
from PySide6 import QtGui

from .protocol import PREVIEW_BUFFER_BYTES


class PreviewBuffer:
    """Transfer full-resolution pixels without PNG encoding, base64 or disk files.

    The desktop owns one lazily allocated segment. The worker attaches only during
    a write, and replies after finishing. Reading copies pixels before another job
    may use the segment. Call close after the worker stops.
    """

    def __init__(self) -> None:
        self._memory: SharedMemory | None = None

    @property
    def name(self) -> str:
        """Allocate the bounded slot on first use and return its transport name."""
        if self._memory is None:
            self._memory = SharedMemory(create=True, size=PREVIEW_BUFFER_BYTES)
        return self._memory.name

    def read(self, width: int, height: int) -> QtGui.QPixmap:
        """Copy validated RGB dimensions into a detached, GUI-owned pixmap."""
        if self._memory is None or width <= 0 or height <= 0 or width * height * 3 > self._memory.size:
            raise ValueError("Invalid shared preview dimensions.")
        image = QtGui.QImage(self._memory.buf, width, height, width * 3, QtGui.QImage.Format.Format_RGB888)
        return QtGui.QPixmap.fromImage(image.copy())

    def close(self) -> None:
        """Release only this window's segment after its worker has stopped."""
        if self._memory is not None:
            self._memory.close()
            self._memory.unlink()
            self._memory = None
