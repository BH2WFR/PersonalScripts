"""Route PDF/project drops from child controls to their owning tool window."""

from pathlib import Path
from typing import Callable
from PySide6 import QtCore, QtGui, QtWidgets


class FileDropFilter(QtCore.QObject):
    """Accept one local PDF/JSON throughout a window, including image viewports.

    Args:
        window: Owning top-level tool window; dialogs are deliberately excluded.
        open_path: Callback invoked for one accepted file drop.
        enabled: Predicate that prevents file changes during a running PDF task.

    Installs an application event filter owned by window. Text-only drag/drop
    remains available to editors; file URLs cannot accidentally become profile names.
    """

    def __init__(self, window: QtWidgets.QWidget, open_path: Callable[[Path], None],
                 enabled: Callable[[], bool]) -> None:
        super().__init__(window)
        self.window = window
        self.open_path = open_path
        self.enabled = enabled
        application = QtWidgets.QApplication.instance()
        if application is None:
            raise RuntimeError("File drops require a QApplication.")
        window.setAcceptDrops(True)
        application.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Handle URL drops before a child viewport or text field consumes them."""
        if (not isinstance(watched, QtWidgets.QWidget) or watched.window() is not self.window or
                event.type() not in (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove, QtCore.QEvent.Type.Drop)
                or not isinstance(event, QtGui.QDropEvent) or not event.mimeData().hasUrls()):
            return False
        urls = event.mimeData().urls()
        if (not self.enabled() or len(urls) != 1 or not urls[0].isLocalFile() or
                Path(urls[0].toLocalFile()).suffix.lower() not in (".pdf", ".json")):
            event.ignore()
            return True
        event.acceptProposedAction()
        if event.type() == QtCore.QEvent.Type.Drop:
            self.open_path(Path(urls[0].toLocalFile()))
        return True
