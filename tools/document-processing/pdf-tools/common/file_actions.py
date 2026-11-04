"""Shared PDF output selection with numbered defaults and explicit replacement.

Requires PySide6. Workers stage output before honoring the returned overwrite flag.
"""

import os
from pathlib import Path
from PySide6 import QtWidgets
from utils import *


def choose_pdf_output(parent: QtWidgets.QWidget, source: Path, default: Path) -> tuple[Path, bool] | None:
    """Choose an output and return its path plus explicit overwrite permission.

    Args:
        parent: Owner of the save and confirmation dialogs.
        source: Protected source PDF, including aliases/hard links.
        default: Desired filename, numbered by Paths.available_path if occupied.
    Returns:
        (path, overwrite), or None when the user cancels or returns.
    Raises:
        OSError: Filesystem inspection or finding an unused default fails.
    No file is created or removed. A worker must still reject new collisions.
    """
    suggested = Paths.available_path(default)
    selected, _ = QtWidgets.QFileDialog.getSaveFileName(parent, "Export PDF", str(suggested),
        "PDF (*.pdf)", options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
    if not selected:
        return None
    output = Path(selected)
    if output.suffix.lower() != ".pdf":
        output = output.with_suffix(".pdf")
    if output.resolve() == source.resolve() or output.exists() and os.path.samefile(output, source):
        QtWidgets.QMessageBox.warning(parent, "Source PDF", "Choose a destination other than the source PDF.")
        return None
    overwrite = output.exists()
    if overwrite:
        dialog = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question, "Output already exists",
            f"Replace this output after processing succeeds?\n{output}", parent=parent)
        replace = dialog.addButton("Overwrite", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        back = dialog.addButton("Return", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(back)
        dialog.exec()
        if dialog.clickedButton() is not replace:
            return None
    return output, overwrite
