"""Solid blocks and hollow reading frames in a per-user desktop session."""

import hashlib
import os
import sys
import time
from collections.abc import Callable
from functools import partial
from typing import Literal

from PySide6.QtCore import QEvent, QLockFile, QPoint, QRect, Qt
from PySide6.QtGui import (
    QCloseEvent, QColor, QContextMenuEvent, QCursor, QGuiApplication, QMouseEvent,
    QPainter, QPaintEvent, QRegion,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QGridLayout, QLabel, QMenu, QMessageBox, QPushButton,
    QWidget, QWidgetAction,
)

from utils import ConfigStore
from utils.qt_widgets import NoWheelSpinBox, configure_qt_application, show_nonactivating_tool

if sys.platform == "darwin":
    import AppKit  # pyright: ignore[reportMissingImports]
    import objc  # pyright: ignore[reportMissingImports]
    from .mac_cursor import track_panel_cursor


ColorKey = Literal["background_color", "border_color"]
DEFAULT_COLORS: dict[ColorKey, str] = {"background_color": "#000000", "border_color": "#0000ff"}
WidthKey = Literal["border_width", "hollow_border_width"]
DEFAULT_WIDTHS: dict[WidthKey, int] = {"border_width": 2, "hollow_border_width": 5}
MAX_BORDER_WIDTH = 32
RESIZE_MARGIN = 12
MIN_OPENING = 8
MIN_OPACITY = 31
FULL_OPACITY = 100


class Mask(QWidget):
    """A frameless tool window with independently editable colors and opacity."""

    def __init__(self, session: "Session", *, hollow: bool = False) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.session = session
        self.colors = session.colors.copy()
        self.hollow = hollow
        self.widths = session.widths.copy()
        self.opacity_percent = FULL_OPACITY
        self.drag: tuple[QPoint, QRect, Qt.Edge] | None = None
        self._stop_cursor_tracking: Callable[[], None] | None = None
        self.setWindowTitle("Screen Mask")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(100, 50)
        self.resize(420, 78)
        if sys.platform == "darwin" and QGuiApplication.platformName() == "cocoa":
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
            view = objc.objc_object(c_void_p=int(self.winId()))  # pyright: ignore[reportAttributeAccessIssue]
            panel = view.window()
            spaces = AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces  # pyright: ignore[reportAttributeAccessIssue]
            auxiliary = AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary  # pyright: ignore[reportAttributeAccessIssue]
            panel.setCollectionBehavior_(spaces | auxiliary)
            self._stop_cursor_tracking = track_panel_cursor(self, view)

    @property
    def _width_key(self) -> WidthKey:
        return "hollow_border_width" if self.hollow else "border_width"

    @property
    def border_width(self) -> int:
        """Return this block's width for its active mode, in logical pixels."""
        return self.widths[self._width_key]

    def _interior(self) -> QRect:
        """Keep a visible rim and a usable opening even on a small hollow block."""
        width = self.border_width
        if self.hollow:
            width = min(max(1, width), (min(self.width(), self.height()) - MIN_OPENING) // 2)
        return self.rect().adjusted(width, width, -width, -width)

    def _update_input_region(self) -> None:
        window = self.windowHandle()
        if window is not None:
            region = QRegion(self.rect()).subtracted(QRegion(self._interior())) if self.hollow else QRegion()
            window.setMask(region)

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.DevicePixelRatioChange) and self.hollow:
            self._update_input_region()
        return handled

    def paintEvent(self, event: QPaintEvent) -> None:
        border = QColor(self.colors["border_color"])
        background = QColor(self.colors["background_color"])
        alpha = round(255 * self.opacity_percent / FULL_OPACITY)
        border.setAlpha(alpha)
        background.setAlpha(0 if self.hollow else alpha)
        inner = self._interior()
        with QPainter(self) as painter:
            # Replace the border underneath the fill so the two alpha values do not accumulate.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(self.rect(), border)
            if not inner.isEmpty():
                painter.fillRect(inner, background)

    def edges_at(self, pos: QPoint) -> Qt.Edge:
        """Return the resize edges under a widget-local position."""
        # Keep a draggable center on small blocks and draggable sides on small frames.
        x_margin = min(RESIZE_MARGIN, self.width() // 3)
        y_margin = min(RESIZE_MARGIN, self.height() // 3)
        edges = Qt.Edge(0)
        if pos.x() < x_margin:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - x_margin:
            edges |= Qt.Edge.RightEdge
        if pos.y() < y_margin:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - y_margin:
            edges |= Qt.Edge.BottomEdge
        if self.hollow and edges in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge, Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            return Qt.Edge(0)  # Move from any side; only corners resize a frame.
        return edges

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        edges = self.edges_at(event.position().toPoint())
        window = self.windowHandle()
        # The Windows system move/resize loop activates even a no-focus frame.
        use_system_drag = not (self.hollow and sys.platform == "win32")
        if window and use_system_drag and (window.startSystemResize(edges) if edges else window.startSystemMove()):
            return
        self.drag = (event.globalPosition().toPoint(), self.geometry(), edges)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            origin, rect, edges = self.drag
            delta = event.globalPosition().toPoint() - origin
            new = QRect(rect)
            if not edges:
                new.translate(delta)
            if edges & Qt.Edge.LeftEdge:
                new.setLeft(min(rect.left() + delta.x(), rect.right() - self.minimumWidth() + 1))
            if edges & Qt.Edge.RightEdge:
                new.setWidth(max(self.minimumWidth(), rect.width() + delta.x()))
            if edges & Qt.Edge.TopEdge:
                new.setTop(min(rect.top() + delta.y(), rect.bottom() - self.minimumHeight() + 1))
            if edges & Qt.Edge.BottomEdge:
                new.setHeight(max(self.minimumHeight(), rect.height() + delta.y()))
            self.setGeometry(new)
            return
        if self._stop_cursor_tracking is None:
            self.setCursor(self.cursor_at(event.position().toPoint()))

    def cursor_at(self, pos: QPoint) -> Qt.CursorShape:
        """Return the pointer shape for the same hit target used to start a drag."""
        edges = self.edges_at(pos)
        left, right = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
        top, bottom = Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if edges in (left | top, right | bottom):
            return Qt.CursorShape.SizeFDiagCursor
        elif edges in (left | bottom, right | top):
            return Qt.CursorShape.SizeBDiagCursor
        elif edges & (left | right):
            return Qt.CursorShape.SizeHorCursor
        elif edges & (top | bottom):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.OpenHandCursor if sys.platform == "darwin" else Qt.CursorShape.SizeAllCursor

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag = None
        super().mouseReleaseEvent(event)

    def _set_opacity(self, value: int) -> None:
        self.opacity_percent = value
        self.update()

    def _set_border_width(self, value: int) -> None:
        self.widths[self._width_key] = value
        if self.hollow:
            self._update_input_region()
        self.update()

    def _add_appearance_controls(self, menu: QMenu) -> None:
        """Embed live width and opacity controls in the open menu."""
        panel = QWidget()
        layout = QGridLayout(panel)
        width = NoWheelSpinBox()
        width.setAccessibleName("Border width")
        width.setRange(int(self.hollow), MAX_BORDER_WIDTH)
        width.setSuffix(" px")
        width.setValue(self.border_width)
        width.valueChanged.connect(self._set_border_width)
        layout.addWidget(QLabel("Border width"), 0, 0)
        layout.addWidget(width, 0, 1)

        opacity = NoWheelSpinBox()
        opacity.setAccessibleName("Opacity")
        opacity.setRange(MIN_OPACITY, FULL_OPACITY)
        opacity.setSuffix("%")
        opacity.setValue(self.opacity_percent)
        opacity.valueChanged.connect(self._set_opacity)
        layout.addWidget(QLabel("Opacity"), 1, 0)
        layout.addWidget(opacity, 1, 1)
        reset = QPushButton("Reset")
        reset.setToolTip("Restore 100% opacity")
        reset.clicked.connect(lambda: opacity.setValue(FULL_OPACITY))
        layout.addWidget(reset, 1, 2)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        hollow = menu.addAction("Hollow frame")
        hollow.setCheckable(True)
        hollow.setChecked(self.hollow)
        background = menu.addAction("Background color…")
        background.setEnabled(not self.hollow)
        border = menu.addAction("Border color…")
        previous_width = self.border_width
        self._add_appearance_controls(menu)
        menu.addSeparator()
        add_solid = menu.addAction("Add solid block")
        add_hollow = menu.addAction("Add hollow frame")
        close = menu.addAction("Close this block")
        quit_all = menu.addAction("Close all and quit")
        action = menu.exec(event.globalPos())
        menu.deleteLater()
        if self.border_width != previous_width:
            try:
                self.session.store.update({self._width_key: self.border_width})
                self.session.widths[self._width_key] = self.border_width
            except (OSError, ValueError) as exc:
                self._set_border_width(previous_width)
                QMessageBox.warning(self, "Could not save border width", str(exc))
        if action == hollow:
            self.hollow = hollow.isChecked()
            self._update_input_region()
            self.update()
        elif action == background or action == border:
            key: ColorKey = "background_color" if action == background else "border_color"
            color = QColorDialog.getColor(self.colors[key], self, action.text().rstrip("…"))
            if color.isValid():
                try:
                    self.session.store.update({key: color.name()})
                except (OSError, ValueError) as exc:
                    QMessageBox.warning(self, "Could not save color", str(exc))
                    return
                self.colors[key] = self.session.colors[key] = color
                self.update()
        elif action in (add_solid, add_hollow):
            self.session.add_block(hollow=action == add_hollow)
        elif action == close:
            self.close()
        elif action == quit_all:
            self.session.close_all()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._stop_cursor_tracking is not None:
            self._stop_cursor_tracking()
            self._stop_cursor_tracking = None
        self.session.blocks.discard(self)
        if not self.session.blocks:
            self.session.app.quit()
        super().closeEvent(event)


class Session:
    """Own all blocks on this desktop and the defaults used for new ones."""

    def __init__(self, app: QApplication, store: ConfigStore) -> None:
        self.app = app
        self.store = store
        settings = store.load()
        self.widths = DEFAULT_WIDTHS.copy()
        for width_key in DEFAULT_WIDTHS:
            width = settings.get(width_key)
            minimum = 1 if width_key == "hollow_border_width" else 0
            if type(width) is int and minimum <= width <= MAX_BORDER_WIDTH:
                self.widths[width_key] = width
        self.colors: dict[ColorKey, QColor] = {}
        for key, fallback in DEFAULT_COLORS.items():
            value = settings.get(key, fallback)
            color = QColor(value) if isinstance(value, str) else QColor()
            self.colors[key] = color.toRgb() if color.isValid() else QColor(fallback)
            self.colors[key].setAlpha(255)
        self.blocks: set[Mask] = set()
        self.servers: dict[bool, QLocalServer] = {}

    def add_block(self, *, hollow: bool = False) -> None:
        """Open a block on the pointer's display, offset from earlier blocks."""
        block = Mask(self, hollow=hollow)
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.app.primaryScreen()
        if screen and not QGuiApplication.platformName().startswith("wayland"):
            area = screen.availableGeometry()
            offset = 24 * (len(self.blocks) % 8)
            block.move(max(area.left(), min(area.right() - block.width() + 1,
                                           area.center().x() - block.width() // 2 + offset)),
                       max(area.top(), min(area.bottom() - block.height() + 1,
                                          area.center().y() - block.height() // 2 + offset)))
        self.blocks.add(block)
        show_nonactivating_tool(block)

    def listen(self, name: str) -> None:
        """Listen on the original solid endpoint and a separate hollow-frame endpoint."""
        for hollow in (False, True):
            endpoint = _launch_endpoint(name, hollow)
            server = QLocalServer()
            self.servers[hollow] = server
            server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            server.newConnection.connect(partial(self.accept_launches, hollow))
            # Only the owner of the common session lock cleans up stale endpoints.
            QLocalServer.removeServer(endpoint)
            if not server.listen(endpoint):
                raise OSError(server.errorString())

    def accept_launches(self, hollow: bool) -> None:
        """Create and acknowledge one window of the requested mode per connection."""
        server = self.servers[hollow]
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is None:
                break
            self.add_block(hollow=hollow)
            socket.disconnected.connect(socket.deleteLater)
            socket.write(b"1")
            socket.disconnectFromServer()

    def close_all(self) -> None:
        """Close every block, exiting when the last one closes."""
        for block in tuple(self.blocks):
            block.close()


def _server_name() -> str:
    """Scope the local endpoint to the user's desktop session."""
    identity = str(ConfigStore.directory())
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        session_id = wintypes.DWORD()
        if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            raise ctypes.WinError()
        identity += f":{session_id.value}"
    elif sys.platform == "linux":
        display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY", "")
        identity += f":{os.uname().nodename}:{display}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"personal-screen-mask-{digest}"


def _launch_endpoint(name: str, hollow: bool) -> str:
    return f"{name}-hollow" if hollow else name


def run(*, hollow: bool = False) -> int:
    """Elect a primary process or ask the existing one to open another block."""
    if sys.platform == "darwin" and QApplication.instance() is None:
        from utils.macos_windows import nonactivating_qt_session
        with nonactivating_qt_session():
            return _run_session(hollow)
    return _run_session(hollow)


def _run_session(hollow: bool) -> int:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    if sys.platform == "linux":
        app.setDesktopFileName("screen-mask")
    name = _server_name()
    directory = ConfigStore.directory()
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / f"{name}.lock"))
    lock.setStaleLockTime(0)
    deadline = time.monotonic() + 5
    while not lock.tryLock(0):
        if lock.error() != QLockFile.LockError.LockFailedError:
            raise OSError(f"Could not lock the Screen Mask session in {directory}.")
        socket = QLocalSocket()
        socket.connectToServer(_launch_endpoint(name, hollow))
        if socket.waitForConnected(200):
            if not socket.bytesAvailable():
                socket.waitForReadyRead(5000)
            if socket.readAll().data() != b"1":
                raise RuntimeError("The running Screen Mask did not confirm the new block.")
            return 0
        if time.monotonic() >= deadline:
            raise RuntimeError("Could not reach the running Screen Mask. Close all blocks and restart it.")
        time.sleep(0.05)
    try:
        configure_qt_application(app)
        session = Session(app, ConfigStore("screen-mask.yaml"))
        try:
            session.listen(name)
            session.add_block(hollow=hollow)
            return app.exec()
        finally:
            for server in session.servers.values():
                server.close()
    finally:
        lock.unlock()
