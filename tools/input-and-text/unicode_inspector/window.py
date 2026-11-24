"""Unicode inspector window and its read-only, on-demand character table."""

import os
import sys

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from utils import System, UnicodeReport, UnicodeText
from utils.qt_widgets import configure_qt_application, with_cjk_fallbacks
from .editor import OriginalEditor, mime_text, text_mime


class CharacterModel(QAbstractTableModel):
    """Read visible cells directly from the most recent analysis."""

    COLORS = {tag: QColor(color) for tag, color in (
        ("control", "#b71c1c"), ("special", "#267333"),
        ("non_ascii", "#1565c0"), ("non_bmp", "#875020"),
    )}

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.report = UnicodeText.inspect("")

    def replace(self, report: UnicodeReport) -> None:
        self.beginResetModel()
        self.report = report
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.report.characters)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(UnicodeText.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> str | QColor | None:
        if not index.isValid():
            return None
        row = self.report.characters[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.columns()[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            return self.COLORS.get(row.style)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> str | None:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return UnicodeText.COLUMNS[section]
        return None


class CharacterTable(QTableView):
    """Keep columns draggable and share spare width among the three text columns."""

    copyRequested = Signal()
    FLEX_COLUMNS = (1, 5, 6)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copyRequested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        header = self.horizontalHeader()
        if header.count() != len(UnicodeText.COLUMNS):
            return
        remaining = self.viewport().width() - header.length()
        for i, column in enumerate(self.FLEX_COLUMNS):
            width = header.sectionSize(column)
            target = max(header.minimumSectionSize(), width + round(remaining / (len(self.FLEX_COLUMNS) - i)))
            header.resizeSection(column, target)
            remaining -= target - width


class UnicodeInspector(QWidget):
    """Edit source text, inspect its code points and copy reports."""

    def __init__(self, text: str, editor_points: int) -> None:
        super().__init__()
        self.setWindowTitle("Unicode Inspector")
        self.resize(1100, 720)
        self.setMinimumSize(800, 500)
        body = QVBoxLayout(self)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(0)
        header = QHBoxLayout()
        header.setSpacing(8)
        body.addLayout(header)
        header.addWidget(QLabel("Text to inspect"), 1)
        for label, action in (("Paste", self.paste), ("Clear", lambda: self.set_text("")), ("Analyze", self.analyze)):
            button = QPushButton(label)
            if label in ("Paste", "Analyze"):
                font = button.font()
                font.setBold(True)
                button.setFont(font)
            button.clicked.connect(action)
            header.addWidget(button)

        self.original = OriginalEditor()
        self.original.setAccessibleName("Text to inspect")
        font = self.original.font()
        font.setPointSize(editor_points)
        self.original.setFont(with_cjk_fallbacks(font))
        self.original.setFixedHeight(self.original.fontMetrics().lineSpacing() * 6
                                     + 2 * (self.original.frameWidth() + int(self.original.document().documentMargin())))
        self.original.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.original.setTabChangesFocus(False)
        body.addSpacing(6)
        body.addWidget(self.original)

        self.model = CharacterModel(self)
        self.statistics: dict[str, QLineEdit] = {}
        summary = QHBoxLayout()
        summary.setSpacing(5)
        for label, _ in self.model.report.statistics.items():
            summary.addWidget(QLabel(label))
            value = QLineEdit()
            value.setReadOnly(True)
            value.setAccessibleName(label)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            value.setFixedWidth(value.fontMetrics().horizontalAdvance("0" * 9) + 8)
            self.statistics[label] = value
            summary.addWidget(value)
            summary.addSpacing(9)
        summary.addStretch()
        body.addSpacing(12)
        body.addLayout(summary)

        self.table = CharacterTable()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(max(20, self.table.fontMetrics().lineSpacing() + 6))
        self.table.horizontalHeader().setMinimumSectionSize(50)
        for column, width in enumerate((60, 150, 95, 80, 120, 180, 330)):
            self.table.setColumnWidth(column, width)
        self.table.copyRequested.connect(self.copy_rows)
        body.addSpacing(12)
        body.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.status = QLabel()
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        for label, action in (("Copy Original", self.copy_original), ("Copy Selected Rows", self.copy_rows),
                              ("Copy Full Report", self.copy_report)):
            button = QPushButton(label)
            button.clicked.connect(action)
            footer.addWidget(button)
        body.addSpacing(10)
        body.addLayout(footer)

        for key, action in (("Ctrl+Return", self.analyze), ("Ctrl+Enter", self.analyze),
                            ("Ctrl+W", self.close), ("Escape", self.close)):
            QShortcut(QKeySequence(key), self, activated=action)
        self.original.textChanged.connect(self._edited)
        self.set_text(text)
        self.original.document().clearUndoRedoStacks()
        self.original.setFocus()

    def _edited(self) -> None:
        self.status.setText("Text changed. Analyze to update the table.")

    def set_text(self, text: str) -> None:
        """Replace all source text and analyze it immediately."""
        self.original.selectAll()
        self.original.insert_source(text)
        self.analyze()

    def analyze(self) -> None:
        """Refresh statistics and table from the exact current editor contents."""
        report = UnicodeText.inspect(self.original.original_text())
        self.model.replace(report)
        for label, value in report.statistics.items():
            self.statistics[label].setText(str(value) if value is not None else "Invalid")
        self.status.setText(f"{len(report.characters):,} code points. Indexes start at 0.")

    def paste(self) -> None:
        """Replace the source with clipboard text if a text format is available."""
        text = mime_text(QApplication.clipboard().mimeData())
        if text is None:
            self.status.setText("Clipboard has no readable text. Enter or paste text manually.")
        else:
            self.set_text(text)

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setMimeData(text_mime(text))
        self.status.setText("Copied to clipboard.")

    def copy_original(self) -> None:
        """Copy the current editor contents, including pending edits."""
        self._copy(self.original.original_text())

    def copy_rows(self) -> None:
        """Copy selected rows in source order as tab-separated text."""
        indices = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        if indices:
            rows = self.model.report.characters
            self._copy("\n".join("\t".join(rows[i].columns()) for i in indices))
        else:
            self.status.setText("Select one or more character rows to copy.")

    def copy_report(self) -> None:
        """Analyze pending edits before exporting the complete report."""
        self.analyze()
        self._copy(UnicodeText.format_report(self.model.report))


def run(text: str, clipboard: bool, editor_points: int) -> int:
    """Configure Qt before constructing the window and reading the clipboard."""
    existing = QApplication.instance()
    if existing is None and System.is_headless() and not os.environ.get("QT_QPA_PLATFORM"):
        print("Cannot open the desktop window. A graphical desktop is required.", file=sys.stderr)
        return 1
    app = existing if isinstance(existing, QApplication) else QApplication([sys.argv[0]])
    configure_qt_application(app)
    window = UnicodeInspector(text, editor_points)
    if clipboard:
        window.paste()
    window.show()
    return app.exec()
