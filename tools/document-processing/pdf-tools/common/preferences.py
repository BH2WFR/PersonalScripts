"""PDF-wide user preferences and remembered dialog directories via utils.ConfigStore."""

from pathlib import Path
from typing import Any
from PySide6 import QtGui, QtWidgets
from utils import *

PDF_CONFIG = "config-pdf-tools.yaml"


def report_config_error(parent: QtWidgets.QWidget | None, error: Exception) -> None:
    """Report nonblocking configuration failures without a modal dialog."""
    message = str(error)
    print(f"{FLYellow}Configuration error: {message}{CRst}", file=sys.stderr)
    if parent is not None:
        parent.setToolTip(message)
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), message, parent)


def read_preferences(parent: QtWidgets.QWidget, section: str) -> dict[str, Any]:
    try:
        value = ConfigStore(PDF_CONFIG).load().get(section, {})
        if not isinstance(value, dict):
            raise ValueError(f"PDF preferences section must be a mapping: {section}")
        return value
    except (OSError, ValueError) as exc:
        report_config_error(parent, exc)
        return {}


def save_preferences(parent: QtWidgets.QWidget, section: str, changes: dict[str, Any]) -> bool:
    try:
        ConfigStore(PDF_CONFIG).update({section: changes})
        return True
    except (OSError, ValueError) as exc:
        report_config_error(parent, exc)
        return False


def dialog_directory(parent: QtWidgets.QWidget, kind: str, fallback: Path | None = None) -> str:
    value = read_preferences(parent, "directories").get(kind)
    if isinstance(value, str) and Path(value).is_dir():
        return value
    return str(fallback) if fallback is not None else ""


def remember_directory(parent: QtWidgets.QWidget, kind: str, path: Path) -> bool:
    return save_preferences(parent, "directories", {kind: str(path.absolute().parent)})


def choose_open_file(parent: QtWidgets.QWidget, title: str, filters: str, *, kind: str = "open-pdf",
                     fallback: Path | None = None) -> str:
    selected, _ = QtWidgets.QFileDialog.getOpenFileName(parent, title, dialog_directory(parent, kind, fallback), filters)
    if selected:
        remember_directory(parent, kind, Path(selected))
    return selected


def choose_save_file(parent: QtWidgets.QWidget, title: str, default: Path, filters: str, *, kind: str) -> str:
    suggested = Path(dialog_directory(parent, kind, default.parent)) / default.name
    selected, _ = QtWidgets.QFileDialog.getSaveFileName(parent, title, str(suggested), filters)
    if selected:
        remember_directory(parent, kind, Path(selected))
    return selected
