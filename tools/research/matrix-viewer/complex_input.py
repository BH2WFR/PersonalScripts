"""Shared scalar-channel/full-complex questions for viewer operations.

Requirements: PySide6. Usage: choose_complex_data before opening an operation's
settings. Export, slice snapshots and processing share the same buttons and
cancellation semantics; callers describe their own mathematical constraints.
No source data, selection or persistent setting is modified by this dialog.
"""

from enum import StrEnum

from PySide6 import QtCore, QtWidgets


class ComplexDataChoice(StrEnum):
    """Source representation, independent of the resulting array's dtype."""

    CHANNEL = "Current channel"
    COMPLEX = "Complex data (real + imaginary)"


def choose_complex_data(parent: QtWidgets.QWidget, source: str, channel: str, *,
                        title: str, action: str, details: str, prefer_complex: bool = True,
                        channel_unavailable: str | None = None) -> ComplexDataChoice | None:
    """Ask which representation an operation should consume.

    Args:
        parent: Owning window.
        source: Source matrix's session label.
        channel: Current component or visible component labels.
        title: Dialog title naming the operation.
        action: Action phrase following 'Which values should be'.
        details: Operation-specific consequences and supported scopes.
        prefer_complex: Default to full complex data; False defaults to channel.
        channel_unavailable: Optional explanation disabling current-channel input.

    Returns:
        Chosen representation, or None when cancelled or closed.

    Side effects:
        Runs a modal question. Does not calculate or mutate source data.
    """
    question = QtWidgets.QMessageBox(parent)
    question.setWindowTitle(title)
    question.setIcon(QtWidgets.QMessageBox.Icon.Question)
    question.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    question.setText(f"Complex matrix: {source}\nCurrent channel: {channel}\n\nWhich values should be {action}?")
    explanation = f"\nCurrent channel unavailable: {channel_unavailable}" if channel_unavailable else ""
    question.setInformativeText(
        "Current channel: use only the displayed scalar values.\n"
        "Complex data: use both original real and imaginary parts.\n"
        f"{details}{explanation}")
    channel_button = question.addButton(ComplexDataChoice.CHANNEL.value, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    complex_button = question.addButton(ComplexDataChoice.COMPLEX.value, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    cancel = question.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
    channel_button.setEnabled(channel_unavailable is None)
    if channel_unavailable:
        channel_button.setToolTip(channel_unavailable)
    question.setDefaultButton(complex_button if prefer_complex or channel_unavailable else channel_button)
    question.setEscapeButton(cancel)
    try:
        question.exec()
        clicked = question.clickedButton()
        if clicked is channel_button and channel_unavailable is None:
            return ComplexDataChoice.CHANNEL
        if clicked is complex_button:
            return ComplexDataChoice.COMPLEX
        return None
    finally:
        question.deleteLater()
