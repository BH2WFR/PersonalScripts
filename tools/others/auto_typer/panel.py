"""Floating text preview, focusable editor and paced keyboard output."""

from collections.abc import Callable
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from utils.qt_widgets import install_no_wheel_controls
from .strokes import Sender, validate_text


_INTERVAL_MS = 20
_READY = "Focus the target window, then click Start Typing."


class TypingPanel(QWidget):
    """Keep the input recipient focused while a timer sends one character at a time."""

    def __init__(self, sender: Sender) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("Auto Typer")
        self._key_sender: Sender = sender
        self.text = ""
        self.recipient = 0
        self.sent = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(_INTERVAL_MS)
        self.timer.timeout.connect(self._type_next)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.preview.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.preview.setPlaceholderText("Paste from the clipboard or click Edit to enter text.")
        self.paste = QPushButton("Paste from Clipboard")
        self.edit = QPushButton("Edit")
        self.start = QPushButton("Start Typing")
        self.start.setStyleSheet("font-weight: bold;")
        self.stop = QPushButton("Stop")
        self.stop.setEnabled(False)
        self.paste.clicked.connect(self._paste)
        self.edit.clicked.connect(self._edit)
        self.start.clicked.connect(self._start)
        self.stop.clicked.connect(self._stop)
        buttons = QHBoxLayout()
        buttons.addWidget(self.paste)
        buttons.addWidget(self.edit)
        buttons.addStretch()
        buttons.addWidget(self.start)
        buttons.addWidget(self.stop)
        for control in (self.preview, self.paste, self.edit, self.start, self.stop):
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.preview)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        ime_notice = QLabel("Please make sure that your IDE is in English mode | 请确保输入法为英文模式 ")
        ime_notice.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(ime_notice)
        self.resize(480, 230)
        self._paste()

    def _set_text(self, text: str) -> None:
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.preview.setPlainText(self.text)
        self.start.setEnabled(bool(self.text))
        self.status.setText(_READY if self.text else "No text to type.")

    def _paste(self) -> None:
        self._set_text(QApplication.clipboard().text())

    def _edit(self) -> None:
        previous = self._key_sender.target()
        dialog = QDialog(None, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowTitle("Edit text")
        editor = QPlainTextEdit(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(editor)
        layout.addWidget(buttons)
        dialog.resize(self.size())
        dialog.setModal(True)
        if QApplication.platformName() == "cocoa":
            from .macos import activate_editor
            activate_editor()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        editor.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted and editor.document().isModified():
            # toPlainText changes non-breaking spaces into ordinary spaces.
            self._set_text(editor.document().toRawText().replace("\u2029", "\n"))
        self._key_sender.restore(previous)

    def _start(self) -> None:
        self.recipient = self._key_sender.target()
        if not self.recipient:
            self.status.setText(_READY)
            return
        try:
            validate_text(self.text)
            self._key_sender.check_ready()
        except (ValueError, OSError, RuntimeError) as exc:
            self._finish(str(exc))
            return
        self.sent = 0
        self.paste.setEnabled(False)
        self.edit.setEnabled(False)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.status.setText(f"Typing 0 / {len(self.text)}")
        self.timer.start()

    def _type_next(self) -> None:
        if self._key_sender.target() != self.recipient:
            self._finish(f"Focus changed. Stopped after {self.sent} of {len(self.text)} characters.")
            return
        try:
            self._key_sender.send(self.text[self.sent])
        except (OSError, RuntimeError, ValueError) as exc:
            self._finish(f"Stopped after {self.sent} characters. {exc}")
            return
        self.sent += 1
        if self.sent == len(self.text):
            self._finish(f"Sent {self.sent} characters.")
        else:
            self.status.setText(f"Typing {self.sent} / {len(self.text)}")

    def _stop(self) -> None:
        self._finish(f"Stopped after {self.sent} of {len(self.text)} characters.")

    def _finish(self, message: str) -> None:
        self.timer.stop()
        self.recipient = 0
        self.stop.setEnabled(False)
        self.start.setEnabled(bool(self.text))
        self.edit.setEnabled(True)
        self.paste.setEnabled(True)
        self.status.setText(message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop pending output before closing the floating tool."""
        self._stop()
        super().closeEvent(event)
        QApplication.quit()


def run(sender: Sender, show_native: Callable[[QWidget], object]) -> int:
    """Run the panel, retaining its native host for the entire event loop."""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if not isinstance(app, QApplication):
        raise RuntimeError("Auto Typer requires a QApplication.")
    app.setStyle("Fusion")
    install_no_wheel_controls(app)
    app.setQuitOnLastWindowClosed(False)
    panel = TypingPanel(sender)
    native_host = show_native(panel)
    try:
        return app.exec()
    finally:
        panel._stop()
        del native_host
