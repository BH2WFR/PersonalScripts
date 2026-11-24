"""Read clipboard text and copied file paths on the Qt GUI thread."""

from collections.abc import Sequence
import ntpath
import plistlib
import re
import sys
from xml.parsers.expat import ExpatError

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication

from .path_text import forward_path, remove_file_prefix, remove_quotes


def _windows_unicode_text() -> str | None:
    """Read bounded CF_UNICODETEXT before Qt folds native CRLF pairs."""
    import ctypes as ct
    from ctypes import wintypes as wt

    user = ct.WinDLL("user32")
    kernel = ct.WinDLL("kernel32")
    user.OpenClipboard.argtypes = [wt.HWND]
    user.CloseClipboard.argtypes = []
    user.GetClipboardData.argtypes = [wt.UINT]
    user.GetClipboardData.restype = wt.HANDLE
    kernel.GlobalLock.argtypes = [wt.HANDLE]
    kernel.GlobalLock.restype = ct.c_void_p
    kernel.GlobalUnlock.argtypes = [wt.HANDLE]
    kernel.GlobalSize.argtypes = [wt.HANDLE]
    kernel.GlobalSize.restype = ct.c_size_t
    if not user.OpenClipboard(None):
        return None
    try:
        handle = user.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        address = kernel.GlobalLock(handle)
        if not address:
            return None
        try:
            size = kernel.GlobalSize(handle)
            if size < 2:
                return None
            data = ct.string_at(address, size - size % 2)
            return data.decode("utf-16-le", errors="surrogatepass").partition("\0")[0]
        finally:
            kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


def original_mime_text(mime: QMimeData) -> str | None:
    """Read plain text, retaining native Windows clipboard line endings when available."""
    if not mime.hasText():
        return None
    if sys.platform == "win32" and QGuiApplication.platformName() == "windows":
        clipboard = QGuiApplication.clipboard()
        if mime is clipboard.mimeData() and not clipboard.ownsClipboard():
            original = _windows_unicode_text()
            if original is not None:
                return original
    return mime.text()


def _absolute_paths(values: Sequence[object]) -> list[str]:
    return [path for path in values if isinstance(path, str) and path.startswith("/")]


def _plist_paths(data: bytes) -> list[str]:
    try:
        value = plistlib.loads(data)
    except (ValueError, plistlib.InvalidFileException, ExpatError):
        return []
    return _absolute_paths(value) if isinstance(value, list) else []


def _finder_paths() -> list[str]:
    """Read Finder's filename list, including the per-item property lists used by Caps+V."""
    try:
        from AppKit import NSPasteboard  # pyright: ignore[reportMissingImports]
    except ImportError:
        return []

    kind = "NSFilenamesPboardType"
    board = NSPasteboard.generalPasteboard()
    if kind in (board.types() or ()):
        values = board.propertyListForType_(kind)
        if values is not None and not isinstance(values, (str, bytes, dict)):
            try:
                paths = _absolute_paths(values)
            except TypeError:
                paths = []
            if paths:
                return paths

    paths = []
    for item in board.pasteboardItems() or ():
        if kind not in (item.types() or ()):
            continue
        data = item.dataForType_(kind)
        item_paths = _plist_paths(bytes(data)) if data is not None else []
        if not item_paths and (text := item.stringForType_(kind)):
            item_paths = _plist_paths(str(text).encode("utf-8"))
        paths.extend(item_paths)
    return paths


def _local_path(url: QUrl, windows: bool) -> str:
    """Decode once, treating localhost as a local file URL authority."""
    if url.host().lower() == "localhost" and (not windows or re.match(r"^/[A-Za-z]:/", url.path())):
        url = QUrl(url)
        url.setHost("")
    path = url.toLocalFile()
    if windows and re.match(r"^/[a-zA-Z]:/", path):
        path = path[1:]
    return path.replace("/", "\\") if windows else path


def read_clipboard_paths(*, preserve_text_separators: bool = False) -> tuple[str, list[str]]:
    """Return the clipboard's displayable source and its extracted file paths.

    Prefer explicit plain text for the source, including quotes and URL escapes.
    A file-only selection supplies its Finder filenames or encoded URLs instead.
    Set preserve_text_separators to keep the slash spelling of pasted path text.
    Native file selections retain their platform's separators in either mode.
    Non-path text is returned alongside an empty list.
    """
    mime = QGuiApplication.clipboard().mimeData()
    plain = mime.text() if mime is not None and mime.hasFormat("text/plain") else None
    if sys.platform == "darwin" and (found := _finder_paths()):
        return plain if plain is not None else "\n".join(found), found
    if mime is None:
        return "", []
    windows = sys.platform == "win32"
    if mime.hasUrls():
        urls = mime.urls()
        source = plain if plain is not None else "\n".join(bytes(url.toEncoded()).decode("ascii") for url in urls)
        return source, [path for url in urls if url.isLocalFile() and (path := _local_path(url, windows))]

    found = []
    source = plain if plain is not None else mime.text()
    for line in re.split(r"\r\n|[\r\n]", source):
        if not line.strip():
            continue
        value = remove_quotes(line if preserve_text_separators else line.strip())
        if value.lower().startswith("file://"):
            value = remove_file_prefix(value)
        elif not (ntpath.isabs(value) if windows else value.startswith("/")):
            return source, []
        if value:
            if windows and not preserve_text_separators:
                value = forward_path(value).replace("/", "\\")
            found.append(value)
    return source, found


def clipboard_file_paths() -> list[str]:
    """Return just the native paths from read_clipboard_paths(), in clipboard order."""
    return read_clipboard_paths()[1]
