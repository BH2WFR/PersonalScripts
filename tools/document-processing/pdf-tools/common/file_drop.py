"""Route PDF/project drops from child controls to their owning tool window."""

from pathlib import Path
from typing import Callable
from PySide6 import QtCore, QtGui, QtWidgets


class FileDropFilter(QtCore.QObject):
    """Accept local files throughout a window, including child viewports.

    Args:
        window: Owning top-level tool window; dialogs are deliberately excluded.
        open_path: Callback invoked for each accepted path in drop order.
        multiple: Accept batches when every URL is a supported local file.
        enabled: Predicate that prevents file changes during a running PDF task.
        suffixes: Accepted filename suffixes; defaults to PDF and project JSON.

    Installs an application event filter owned by window. Text-only drag/drop
    remains available to editors; file URLs cannot accidentally become profile names.
    """

    def __init__(self, window: QtWidgets.QWidget, open_path: Callable[[Path], None],
                 enabled: Callable[[], bool], *, suffixes: tuple[str, ...] = (".pdf", ".json"),
                 multiple: bool = False) -> None:
        super().__init__(window)
        self.window = window
        self.open_path = open_path
        self.enabled = enabled
        self.suffixes = suffixes
        self.multiple = multiple
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
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if (not self.enabled() or not paths or len(paths) != len(urls) or
                (not self.multiple and len(paths) != 1) or
                any(path.suffix.lower() not in self.suffixes for path in paths)):
            event.ignore()
            return True
        event.acceptProposedAction()
        if event.type() == QtCore.QEvent.Type.Drop:
            for path in paths:
                self.open_path(path)
        return True
