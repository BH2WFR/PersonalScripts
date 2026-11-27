"""Offline catalog and explicit extension downloads using the existing serial worker."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtGui, QtWidgets
from ..common.jobs import JobRunner
from ..common.protocol import Json
from .ui_models import Ui_ModelDialog


class ModelDialog(QtWidgets.QDialog, Ui_ModelDialog):
    """Manage small recognition models without installing more Python packages."""

    def __init__(self, runner: JobRunner, submit: Callable[[dict[str, Json]], bool],
                 parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.runner, self.submit = runner, submit
        self.rows: dict[str, dict] = {}
        self.directory = ""
        self.setupUi(self)
        self.setModal(True)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.tree.header().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._selected)
        self.details.setReadOnly(True)
        for button, callback in ((self.download_button, lambda: self._action("download")),
                                 (self.verify_button, lambda: self._action("verify")),
                                 (self.delete_button, self._delete),
                                 (self.refresh_button, self.refresh),
                                 (self.folder_button, self._open_folder)):
            button.clicked.connect(callback)
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.controls.bind_runner(runner, with_progress=True)
        self.close_button.clicked.connect(self.reject)
        runner.busyChanged.connect(self._enabled)
        runner.progress.connect(self._progress)
        runner.controlStatus.connect(self.status.setText)
        self._enabled()

    def refresh(self) -> None:
        """Refresh local sizes without querying remote servers."""
        self.submit({"operation": "model-list"})

    def _selected(self, *_args: object) -> None:
        row = self._row()
        self.details.setPlainText(f"File: {row['path']}\nSource: {row['url']}\nSHA-256: {row['sha256']}" if row else "")
        self._enabled()

    def _row(self) -> dict:
        item = self.tree.currentItem()
        return self.rows.get(str(item.data(0, QtCore.Qt.ItemDataRole.UserRole)), {}) if item else {}

    def _enabled(self, *_args: object) -> None:
        idle, row = not self.runner.busy, self._row()
        self.tree.setEnabled(idle)
        self.download_button.setEnabled(idle and bool(row) and not row.get("bundled", True))
        self.verify_button.setEnabled(idle and bool(row.get("size")))
        self.delete_button.setEnabled(idle and bool(row.get("size")) and not row.get("bundled", True))
        self.refresh_button.setEnabled(idle)
        self.folder_button.setEnabled(idle and bool(self.directory))
        self.close_button.setEnabled(idle)

    def _action(self, action: str) -> None:
        row = self._row()
        if row and not self.runner.busy:
            self.status.setText(f"{action.title()}: {row['title']}...")
            self.submit({"operation": f"model-{action}", "model": str(row["key"])})

    def _delete(self) -> None:
        row = self._row()
        if row and QtWidgets.QMessageBox.question(self, "Delete model", f"Delete {row['title']} from the local cache?\n"
                "Existing PDFs and completed OCR results are retained. You can download the model again.") == QtWidgets.QMessageBox.StandardButton.Yes:
            self._action("delete")

    def _open_folder(self) -> None:
        path = Path(self.directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path))):
                raise OSError("The system could not open the model folder.")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "Model folder", str(exc))

    def _progress(self, message: dict[str, Json]) -> None:
        if "stage" in message:
            self.status.setText(str(message["stage"]))

    def completed(self, message: dict[str, Json]) -> None:
        """Display a worker result; errors leave the previous inventory available."""
        if message.get("kind") == "models":
            selected = self._row().get("key")
            self.rows = {row["key"]: row for row in cast(list[dict], message["rows"])}
            self.directory = str(message["directory"])
            self.tree.clear()
            total = extra = 0
            for key, row in self.rows.items():
                size = int(row["size"])
                total += size
                extra += size if not row["bundled"] else 0
                item = QtWidgets.QTreeWidgetItem([row["title"], row["version"], row["status"],
                                                 f"{size / 1048576:.2f} MiB" if size else "—"])
                item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
                self.tree.addTopLevelItem(item)
                if key == selected:
                    self.tree.setCurrentItem(item)
            first = self.tree.topLevelItem(0)
            if self.tree.currentItem() is None and first is not None:
                self.tree.setCurrentItem(first)
            self.summary.setText(f"Local models: {total / 1048576:.2f} MiB (downloaded: {extra / 1048576:.2f} MiB)\n{self.directory}")
            action = str(message["action"])
            self.status.setText("Local inventory refreshed. Use Verify to check file integrity." if action == "list" else
                                "SHA-256 verified." if action in ("verify", "download") else "Model deleted.")
        elif message.get("kind") == "cancelled":
            self.status.setText("Stopped. Incomplete downloads were discarded; existing model files were kept.")
        else:
            self.status.setText(str(message.get("message", "Model operation failed.")))
        self._enabled()

    def reject(self) -> None:
        """Keep the dialog attached until its worker operation has finished."""
        if not self.runner.busy:
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)
