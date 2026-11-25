"""Executable selection and per-launch locale overrides."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QStyle, QVBoxLayout, QWidget,
)
from utils.qt_clipboard import clipboard_file_paths, local_file_paths
from utils.path_text import remove_quotes
from utils.qt_widgets import configure_qt_application
from .settings import CODE_PAGES, EXECUTABLE_SUFFIXES, Selection, code_pages, host_settings, launch, locales, time_zones


class Launcher(QWidget):
    """Select a target and independently override its Windows locale settings."""

    def __init__(self) -> None:
        super().__init__()
        self.startup_directory = Path.cwd()
        self.setWindowTitle("Locale Launcher")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        target_row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setAcceptDrops(False)
        self.path.setPlaceholderText("Drop an .exe or .com here")
        self.path.setAccessibleName("Target executable")
        target_row.addWidget(self.path, 1)
        browse = QPushButton("Open…")
        browse.clicked.connect(self.browse)
        target_row.addWidget(browse)
        paste = QPushButton("Paste")
        paste.clicked.connect(self.paste)
        target_row.addWidget(paste)
        layout.addLayout(target_row)
        arguments_row = QHBoxLayout()
        arguments_label = QLabel("Arguments")
        self.arguments = QLineEdit()
        self.arguments.setPlaceholderText("Optional command-line arguments")
        self.arguments.setAccessibleName("Arguments")
        arguments_label.setBuddy(self.arguments)
        arguments_row.addWidget(arguments_label)
        arguments_row.addWidget(self.arguments, 1)
        layout.addLayout(arguments_row)
        directory_row = QHBoxLayout()
        directory_label = QLabel("Start in")
        self.directory = QLineEdit(str(self.startup_directory))
        self.directory.setPlaceholderText(str(self.startup_directory))
        self.directory.setAccessibleName("Working directory")
        directory_label.setBuddy(self.directory)
        open_folder = QPushButton("Open folder…")
        open_folder.clicked.connect(self.browse_directory)
        directory_row.addWidget(directory_label)
        directory_row.addWidget(self.directory, 1)
        directory_row.addWidget(open_folder)
        layout.addLayout(directory_row)
        QShortcut(QKeySequence.StandardKey.Open, self, self.browse)
        QShortcut(QKeySequence.StandardKey.Paste, self, self.paste)

        host = host_settings()
        regions = locales()
        zones = time_zones()
        fields = QGridLayout()
        fields.setRowMinimumHeight(0, layout.spacing())
        for column, title in ((1, "Launch settings"), (3, "This computer")):
            heading = QLabel(title)
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)
            fields.addWidget(heading, 1, column)
        layout.addLayout(fields)

        def add_field(title: str, choices: list[tuple[str, str]], current: str) -> QComboBox:
            row = fields.rowCount()
            label = QLabel(title)
            box = QComboBox()
            box.addItem("Unchanged (use host)", "")
            for display, value in choices:
                box.addItem(display, value)
            label.setBuddy(box)
            box.setAccessibleName(title)
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(27)
            fields.addWidget(label, row, 0)
            fields.addWidget(box, row, 1)
            current_label = QLabel(current)
            current_label.setWordWrap(True)
            fields.addWidget(current_label, row, 3)
            return box

        def user_and_system(user: str, system: str) -> str:
            return user if user == system else f"User: {user}\nSystem: {system}"

        self.region = add_field("Region", regions, user_and_system(host.user_region, host.system_region))
        current_page = f"{host.ansi_page} · {CODE_PAGES.get(host.ansi_page, 'ANSI')}"
        if host.oem_page != host.ansi_page:
            current_page = f"ANSI: {current_page}\nOEM: {host.oem_page}"
        self.page = add_field("Code page", code_pages(), current_page)
        self.language = add_field("UI language", regions, user_and_system(host.user_language, host.system_language))
        self.zone = add_field("Time zone", zones, host.time_zone)
        fields.setColumnStretch(1, 3)
        fields.setColumnStretch(3, 2)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        fields.addWidget(divider, 0, 2, -1, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.admin_button = QPushButton("Run as administrator")
        self.admin_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield))
        self.admin_button.clicked.connect(lambda: self.start(True))
        self.run_button = QPushButton("Run")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(lambda: self.start(False))
        for button in (self.admin_button, self.run_button):
            button.setEnabled(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.resize(max(self.sizeHint().width(), self.fontMetrics().horizontalAdvance("M") * 64),
                    self.sizeHint().height())

    def select(self, paths: list[str]) -> None:
        """Accept exactly one existing executable from any of the three inputs."""
        if len(paths) != 1 or Path(paths[0]).suffix.lower() not in EXECUTABLE_SUFFIXES or not Path(paths[0]).is_file():
            QMessageBox.warning(self, self.windowTitle(), "Select one existing .exe or .com file.")
            return
        self.path.setText(str(Path(paths[0]).resolve()))
        self.path.setToolTip(self.path.text())
        self.run_button.setEnabled(True)
        self.admin_button.setEnabled(True)

    def browse(self) -> None:
        """Select an executable using the native file picker."""
        path, _ = QFileDialog.getOpenFileName(self, "Open executable", self.path.text(), "Programs (*.exe *.com)")
        if path:
            self.select([path])

    def paste(self) -> None:
        """Accept an Explorer file selection or a copied path."""
        self.select(clipboard_file_paths())

    def working_directory(self) -> Path:
        """Resolve the field relative to the launcher's original working directory."""
        return self.startup_directory / remove_quotes(self.directory.text().strip(), '"')

    def browse_directory(self) -> None:
        """Choose the working directory for the target executable."""
        current = self.working_directory()
        initial = current if current.is_dir() else self.startup_directory
        folder = QFileDialog.getExistingDirectory(self, "Open folder", str(initial))
        if folder:
            self.directory.setText(str(Path(folder)))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        paths = local_file_paths(event.mimeData().urls())
        if len(paths) == 1 and Path(paths[0]).suffix.lower() in EXECUTABLE_SUFFIXES:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.select(local_file_paths(event.mimeData().urls()))
        event.acceptProposedAction()

    def start(self, administrator: bool) -> None:
        """Launch with the currently selected options and report errors in the window."""
        settings = Selection(self.region.currentData(), int(self.page.currentData() or 0),
                             self.language.currentData(), self.zone.currentData())
        try:
            launch(Path(self.path.text()), settings, administrator, self.arguments.text(), self.working_directory())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))


def run() -> int:
    """Open the GUI and run the Qt event loop."""
    app = cast(QApplication, QApplication.instance() or QApplication([]))
    configure_qt_application(app)
    try:
        window = Launcher()
    except (OSError, ValueError) as exc:
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Locale Launcher")
        dialog.setText(str(exc))
        dialog.exec()
        return 1
    window.show()
    return app.exec()
