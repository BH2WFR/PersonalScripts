"""Drag capture and non-activating four-edge window outlines."""

import sys

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QLabel, QWidget

from .model import Backend, Window


class Outline:
    def __init__(self, owner: QWidget, backend: Backend) -> None:
        self.backend = backend
        self.timer = QTimer(owner, singleShot=True)
        self.timer.timeout.connect(self.hide)
        self.edges: list[QWidget] = []
        for _ in range(4):
            edge = QWidget(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                           Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                           Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
            edge.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            if sys.platform == "darwin":
                edge.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
            edge.setStyleSheet("background: #ff4422;")
            self.edges.append(edge)

    def show(self, target: Window, duration: int = 0) -> None:
        """Mark the visible frame without stealing mouse input or keyboard focus."""
        self.timer.stop()
        (x, y, width, height), thickness = self.backend.frame(target)
        if min(width, height) <= 0:
            raise RuntimeError("The window has no visible bounds.")
        dx, dy = min(thickness, width), min(thickness, height)
        rectangles = [(x, y, width, dy), (x, y + height - dy, width, dy),
                      (x, y, dx, height), (x + width - dx, y, dx, height)]
        try:
            for edge, rect in zip(self.edges, rectangles):
                if sys.platform == "win32":
                    from .windows import position_edge
                    if not edge.isVisible():
                        edge.resize(1, 1)
                        edge.show()
                    position_edge(int(edge.winId()), rect)
                else:
                    edge.setGeometry(*rect)
                    if not edge.isVisible():
                        from .macos import configure_edge
                        edge.show()
                        configure_edge(int(edge.winId()))
            if duration:
                self.timer.start(duration)
        except Exception:
            self.hide()
            raise

    def hide(self) -> None:
        self.timer.stop()
        for edge in self.edges:
            edge.hide()


class Finder(QLabel):
    picked = Signal(object)
    message = Signal(str)
    started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dragging = False
        self.hovered: Window | None = None

    def configure(self, backend: Backend, outline: Outline) -> None:
        """Bind the native window lookup and outline before the inspector is shown."""
        self.backend, self.outline = backend, outline

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.WindowText), 1.6))
        center = QPointF(self.width() / 2, self.height() / 2)
        for radius in (9.0, 4.5):
            painter.drawEllipse(center, radius, radius)
        painter.end()

    def cancel(self) -> None:
        self.dragging = False
        self.hovered = None
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self.outline.hide()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.cancel()
            self.started.emit()
            self.dragging = True
            self.grabMouse(Qt.CursorShape.CrossCursor)
            self.message.emit("Drag onto a window and release to inspect it. Press Esc to cancel.")
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.dragging:
            try:
                target = self.backend.at_pointer()
                if target != self.hovered:
                    self.hovered = target
                    if target is None:
                        self.outline.hide()
                    else:
                        self.outline.show(target)
                        self.message.emit(f"Release to inspect {target.label}")
            except (OSError, RuntimeError) as exc:
                self.hovered = None
                self.outline.hide()
                self.message.emit(str(exc))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.dragging and event.button() == Qt.MouseButton.LeftButton:
            try:
                target = self.backend.at_pointer()
            except (OSError, RuntimeError) as exc:
                self.message.emit(str(exc))
                target = None
            finally:
                self.cancel()
            if target is not None:
                self.picked.emit(target)
            else:
                self.message.emit("No window selected.")

    def event(self, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.Hide) and self.dragging:
            self.cancel()
        return super().event(event)
