"""Unicode inspector window and its read-only, on-demand character table."""

import os
import sys
from typing import cast

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QHeaderView, QWidget

from utils import System, UnicodeReport, UnicodeText
from utils.gui_colors import TextColor
from utils.qt_styles import on_theme_change, set_button_style, theme_text_color
from utils.qt_widgets import configure_qt_application
from .editor import mime_text, text_mime
from .ui_mainwindow import Ui_UnicodeInspector


class CharacterModel(QAbstractTableModel):
    """Read visible cells directly from the most recent analysis."""

    COLORS: dict[str, TextColor] = {
        "control": "red", "special": "green", "non_ascii": "blue", "non_bmp": "brown",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.report = UnicodeText.inspect("")

    def replace(self, report: UnicodeReport) -> None:
        self.beginResetModel()
        self.report = report
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.report.characters)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(UnicodeText.COLUMNS)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> str | QColor | None:
        if not index.isValid():
            return None
        row = self.report.characters[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.columns()[index.column()]
        if role == Qt.ItemDataRole.ForegroundRole:
            color = self.COLORS.get(row.style)
            return theme_text_color(color, cast(QWidget, self.parent())) if color else None
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> str | None:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return UnicodeText.COLUMNS[section]
        return None


class UnicodeInspector(QWidget, Ui_UnicodeInspector):
    """Edit source text, inspect its code points and copy reports."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setupUi(self)
        self.paste_button.clicked.connect(self.paste)
        self.clear_button.clicked.connect(lambda: self.set_text(""))
        self.analyze_button.clicked.connect(self.analyze)
        set_button_style(self.analyze_button, "blue")
        self.original.setFixedHeight(self.original.fontMetrics().lineSpacing() * 6
                                     + 2 * (self.original.frameWidth() + int(self.original.document().documentMargin())))

        self.model = CharacterModel(self)
        self.statistics = {
            "Characters": self.character_count,
            "UTF-8 bytes": self.utf8_bytes,
            "UTF-16 bytes": self.utf16_bytes,
            "Words": self.word_count,
            "Lines": self.line_count,
        }
        for field in self.statistics.values():
            field.setFixedWidth(field.fontMetrics().horizontalAdvance("0" * 9) + 8)

        self.table.setModel(self.model)
        on_theme_change(self.table, self.table.viewport().update)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(max(20, self.table.fontMetrics().lineSpacing() + 6))
        for column, width in enumerate((60, 150, 95, 80, 120, 180, 330)):
            self.table.setColumnWidth(column, width)
        self.table.copyRequested.connect(self.copy_rows)
        self.copy_original_button.clicked.connect(self.copy_original)
        self.copy_rows_button.clicked.connect(self.copy_rows)
        self.copy_report_button.clicked.connect(self.copy_report)

        for key, action in (("Ctrl+Return", self.analyze), ("Ctrl+Enter", self.analyze),
                            ("Ctrl+W", self.close), ("Escape", self.close)):
            QShortcut(QKeySequence(key), self, action)
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


def run(text: str, clipboard: bool) -> int:
    """Configure Qt before constructing the window and reading the clipboard."""
    existing = QApplication.instance()
    if existing is None and System.is_headless() and not os.environ.get("QT_QPA_PLATFORM"):
        print("Cannot open the desktop window. A graphical desktop is required.", file=sys.stderr)
        return 1
    app = existing if isinstance(existing, QApplication) else QApplication([sys.argv[0]])
    configure_qt_application(app)
    window = UnicodeInspector(text)
    if clipboard:
        window.paste()
    window.show()
    return app.exec()
