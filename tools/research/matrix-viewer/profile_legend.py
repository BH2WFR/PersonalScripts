"""Compact, horizontally scrollable Qt legend outside the plotting canvas.

Requirements: PySide6. Usage: placed beside the signal/profile title.
"""

from PySide6 import QtCore, QtGui, QtWidgets


class ProfileLegend(QtWidgets.QScrollArea):
    """Keep curve colors and names readable without covering plotted data."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.entries: tuple[tuple[str, str], ...] = ()
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(80)
        self.setFixedHeight(self.fontMetrics().height() + self.style().pixelMetric(QtWidgets.QStyle.PixelMetric.PM_ScrollBarExtent) + 6)
        self.content = QtWidgets.QWidget()
        self.line = QtWidgets.QHBoxLayout(self.content)
        self.line.setContentsMargins(2, 2, 2, 2)
        self.line.setSpacing(12)
        self.line.setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetMinAndMaxSize)
        self.setWidget(self.content)
        self.hide()

    def set_entries(self, entries: tuple[tuple[str, str], ...]) -> None:
        """Set (label, color) pairs, retaining scroll position when unchanged."""
        if entries == self.entries:
            return
        self.entries = entries
        while self.line.count():
            item = self.line.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for name, color in entries:
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            swatch = QtWidgets.QLabel()
            pixmap = QtGui.QPixmap(20, 12)
            pixmap.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 3))
            painter.drawLine(1, 6, 19, 6)
            painter.end()
            swatch.setPixmap(pixmap)
            row.addWidget(swatch)
            label = QtWidgets.QLabel(self.fontMetrics().elidedText(name, QtCore.Qt.TextElideMode.ElideMiddle, 220))
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            row.addWidget(label)
            holder.setToolTip(name)
            self.line.addWidget(holder)
        self.line.addStretch()
        self.setVisible(bool(entries))
