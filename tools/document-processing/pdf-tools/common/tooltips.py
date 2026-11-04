"""Window-scoped Qt tooltips with a strict 250 logical-pixel width limit.

Requires PySide6. Install one TooltipFilter on a tool window; widget/action and
tree-cell tooltip strings remain plain text and retain their original contents.
"""

import math
from PySide6 import QtCore, QtGui, QtWidgets

MAX_TOOLTIP_WIDTH = 250
_MARGIN = 8


class _Popup(QtWidgets.QWidget):
    """Paint a wrapped text document using the platform's tooltip palette."""

    def __init__(self, owner: QtWidgets.QWidget) -> None:
        super().__init__(owner, QtCore.Qt.WindowType.ToolTip)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.document = QtGui.QTextDocument(self)
        self.document.setDocumentMargin(0)
        options = QtGui.QTextOption()
        options.setWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document.setDefaultTextOption(options)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_text(self, text: str, point: QtCore.QPoint) -> None:
        self.document.setDefaultFont(QtWidgets.QToolTip.font())
        self.document.setPlainText(text)
        self.document.setTextWidth(MAX_TOOLTIP_WIDTH - 2 * _MARGIN)
        width = min(MAX_TOOLTIP_WIDTH, math.ceil(self.document.idealWidth()) + 2 * _MARGIN)
        self.document.setTextWidth(max(1, width - 2 * _MARGIN))
        self.resize(width, math.ceil(self.document.size().height()) + 2 * _MARGIN)
        screen = QtGui.QGuiApplication.screenAt(point) or self.screen()
        bounds = screen.availableGeometry()
        self.move(max(bounds.left(), min(point.x() + 12, bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(point.y() + 18, bounds.bottom() - self.height() + 1)))
        self.show()
        self.update()
        self.timer.start(max(10000, min(30000, len(text) * 50)))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        palette = QtWidgets.QToolTip.palette()
        painter.fillRect(self.rect(), palette.brush(QtGui.QPalette.ColorRole.ToolTipBase))
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.Mid))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.translate(_MARGIN, _MARGIN)
        context = QtGui.QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QtGui.QPalette.ColorRole.Text, palette.color(QtGui.QPalette.ColorRole.ToolTipText))
        self.document.documentLayout().draw(painter, context)


class TooltipFilter(QtCore.QObject):
    """Display bounded tooltips for one window, including rebuilt child controls.

    Args:
        window: Tool window owning this filter and its nonactivating tooltip.
    Installs an application event filter scoped to window descendants; Qt removes
    it when the owning window is destroyed. No settings or tooltip text is changed.
    """

    def __init__(self, window: QtWidgets.QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.popup = _Popup(window)
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if not isinstance(watched, QtWidgets.QWidget) or watched.window() is not self.window:
            return False
        if event.type() in (QtCore.QEvent.Type.Leave, QtCore.QEvent.Type.MouseButtonPress,
                            QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.Wheel,
                            QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.WindowDeactivate):
            self.popup.hide()
        if event.type() != QtCore.QEvent.Type.ToolTip or not isinstance(event, QtGui.QHelpEvent):
            return False
        text = watched.toolTip()
        parent = watched.parentWidget()
        if isinstance(parent, QtWidgets.QTreeWidget) and watched is parent.viewport():
            item = parent.itemAt(event.pos())
            column = parent.columnAt(event.pos().x())
            text = (item.toolTip(column) if item is not None and column >= 0 else "") or parent.toolTip()
        if not text:
            self.popup.hide()
            return False
        QtWidgets.QToolTip.hideText()
        self.popup.show_text(text, event.globalPos())
        event.accept()
        return True
