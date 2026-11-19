"""Shared image conversion, clipboard and PNG output for PySide6 tools."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from PIL.Image import Image


def qimage_from_pillow(image: "Image") -> QtGui.QImage:
    """Copy RGB or RGBA Pillow pixels into an independently owned QImage.

    Raises:
        ValueError: The caller supplied another pixel mode.
    """
    if image.mode == "RGB":
        pixel_format, channels = QtGui.QImage.Format.Format_RGB888, 3
    elif image.mode == "RGBA":
        pixel_format, channels = QtGui.QImage.Format.Format_RGBA8888, 4
    else:
        raise ValueError(f"Expected an RGB or RGBA image, got {image.mode}.")
    pixels = image.tobytes()
    return QtGui.QImage(pixels, image.width, image.height, image.width * channels, pixel_format).copy()


def copy_image_to_clipboard(image: QtGui.QImage) -> None:
    """Copy image pixels to the system clipboard on the Qt GUI thread."""
    QtWidgets.QApplication.clipboard().setImage(image)


def save_png(image: QtGui.QImage, path: str | Path) -> None:
    """Encode a QImage as PNG and atomically replace the chosen destination.

    Raises:
        OSError: Opening the output, encoding the image or committing the file failed.
    """
    output = QtCore.QSaveFile(str(path))
    if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    writer = QtGui.QImageWriter(output, b"PNG")
    if not writer.write(image):
        output.cancelWriting()
        raise OSError(writer.errorString())
    if not output.commit():
        raise OSError(output.errorString())
