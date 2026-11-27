"""Executable selection and per-launch locale overrides."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QStyle, QWidget
from utils.qt_clipboard import clipboard_file_paths, local_file_paths
from utils.path_text import remove_quotes
from utils.qt_widgets import configure_qt_application
from .settings import CODE_PAGES, EXECUTABLE_SUFFIXES, Selection, code_pages, host_settings, launch, locales, time_zones
from .ui_launcher import Ui_Launcher


class Launcher(QWidget, Ui_Launcher):
    """Select a target and independently override its Windows locale settings."""

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        self.setAcceptDrops(True)
        self.path.setReadOnly(True)
        self.path.setAcceptDrops(False)
        self.startup_directory = Path.cwd()
        self.directory.setText(str(self.startup_directory))
        self.directory.setPlaceholderText(str(self.startup_directory))

        self.open_button.clicked.connect(self.browse)
        self.paste_button.clicked.connect(self.paste)
        self.folder_button.clicked.connect(self.browse_directory)
        QShortcut(QKeySequence.StandardKey.Open, self, self.browse)
        QShortcut(QKeySequence.StandardKey.Paste, self, self.paste)
        self.admin_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield))
        self.admin_button.clicked.connect(lambda: self.start(True))
        self.run_button.clicked.connect(lambda: self.start(False))
        self.run_button.setDefault(True)
        self.admin_button.setEnabled(False)
        self.run_button.setEnabled(False)

        self.fields.setRowMinimumHeight(0, self.main_layout.spacing())
        for heading in (self.launch_heading, self.host_heading):
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)

        regions = locales()
        for box, choices in ((self.region, regions), (self.page, code_pages()),
                             (self.language, regions), (self.zone, time_zones())):
            box.addItem("Unchanged (use host)", "")
            for display, value in choices:
                box.addItem(display, value)

        def user_and_system(user: str, system: str) -> str:
            return user if user == system else f"User: {user}\nSystem: {system}"

        host = host_settings()
        self.host_region.setText(user_and_system(host.user_region, host.system_region))
        current_page = f"{host.ansi_page} · {CODE_PAGES.get(host.ansi_page, 'ANSI')}"
        if host.oem_page != host.ansi_page:
            current_page = f"ANSI: {current_page}\nOEM: {host.oem_page}"
        self.host_page.setText(current_page)
        self.host_language.setText(user_and_system(host.user_language, host.system_language))
        self.host_zone.setText(host.time_zone)
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
