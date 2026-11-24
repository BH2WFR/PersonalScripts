"""Preserve code points that QTextDocument or the native text clipboard folds."""

import re

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit

from utils.qt_clipboard import original_mime_text

_ORIGINAL_CODEPOINT = int(QTextFormat.Property.UserProperty)
_EXACT_MIME = "application/x-personalscripts-unicode-utf8"
_QT_SPECIAL = re.compile(r"[\r\u2029\ufdd0\ufdd1\ud800-\udfff]")


def _display_char(char: str) -> str:
    if char == "\r":
        return "\u2060"  # Zero width before LF in a CRLF pair.
    if char == "\u2029":
        return "\u2028"
    return "\ufffd"


def text_mime(text: str) -> QMimeData:
    """Publish plain text plus an exact copy for NULs and isolated surrogates."""
    mime = QMimeData()
    mime.setText(text)
    mime.setData(_EXACT_MIME, text.encode("utf-8", errors="surrogatepass"))
    return mime


def mime_text(mime: QMimeData | None) -> str | None:
    """Read a text payload, preserving empty text and distinguishing non-text."""
    if mime is not None:
        if mime.hasFormat(_EXACT_MIME):
            try:
                return bytes(mime.data(_EXACT_MIME)).decode("utf-8", errors="surrogatepass")
            except UnicodeDecodeError:
                pass
        return original_mime_text(mime)
    return None


def _original_text(document: QTextDocument) -> str:
    parts: list[str] = []
    block = document.begin()
    while block.isValid():
        if block.blockNumber():
            parts.append("\n")
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            text = fragment.text()
            code = fragment.charFormat().property(_ORIGINAL_CODEPOINT)
            if code is not None:
                char = chr(int(code))
                text = text.replace(_display_char(char), char)
            parts.append(text)
            it += 1
        block = block.next()
    return "".join(parts)


class OriginalEditor(QPlainTextEdit):
    """Attach original code points to editable spans so undo restores them too."""

    def __init__(self) -> None:
        super().__init__()
        self.cursorPositionChanged.connect(self._reset_typing_format)

    def _reset_typing_format(self) -> None:
        if not self.textCursor().hasSelection() and self.currentCharFormat().hasProperty(_ORIGINAL_CODEPOINT):
            self.setCurrentCharFormat(QTextCharFormat())

    def original_text(self) -> str:
        """Return the exact current source, including whitespace and controls."""
        return _original_text(self.document())

    def insert_source(self, text: str) -> None:
        """Replace the selection in one undo step without Qt normalization."""
        cursor = self.textCursor()
        plain = QTextCharFormat()
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        start = 0
        for match in _QT_SPECIAL.finditer(text):
            cursor.insertText(text[start:match.start()], plain)
            char = match.group()
            tagged = QTextCharFormat()
            tagged.setProperty(_ORIGINAL_CODEPOINT, ord(char))
            cursor.insertText(_display_char(char), tagged)
            start = match.end()
        cursor.insertText(text[start:], plain)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self._reset_typing_format()

    def insertFromMimeData(self, source: QMimeData) -> None:
        text = mime_text(source)
        if text is not None:
            self.insert_source(text)

    def createMimeDataFromSelection(self) -> QMimeData:
        selected = QTextDocument()
        QTextCursor(selected).insertFragment(self.textCursor().selection())
        return text_mime(_original_text(selected))
