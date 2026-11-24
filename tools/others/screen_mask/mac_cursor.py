"""Cursor handling for Cocoa panels that stay visible while another app has focus."""

import ctypes
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import AppKit  # pyright: ignore[reportMissingImports]
from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from .app import Mask


class ScreenMaskCursorOwner(AppKit.NSObject):  # pyright: ignore[reportAttributeAccessIssue]
    """Receive AppKit tracking events even while Qt suppresses background hover."""

    update_cursor: Callable[[Any], None]

    def mouseEntered_(self, event: Any) -> None:
        self.update_cursor(event)

    def mouseMoved_(self, event: Any) -> None:
        self.update_cursor(event)

    def cursorUpdate_(self, event: Any) -> None:
        self.update_cursor(event)

    def mouseExited_(self, event: Any) -> None:
        pass  # AppKit hands the cursor back to the newly hovered window.


def track_panel_cursor(block: "Mask", view: Any) -> Callable[[], None] | None:
    """Install native cursor tracking and return its cleanup callback."""
    panel = view.window()
    handle = block.windowHandle()
    if handle is None or not view.respondsToSelector_("cursor"):
        return None

    # WindowServer normally lets only the foreground app set the pointer. Apply
    # kCGSSetsCursorInBackgroundTagBit to this panel, scoped to its input region.
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        connection = cg.CGSMainConnectionID
        set_tags = cg.CGSSetWindowTags
    except (OSError, AttributeError):
        pass  # The foreground cursor still works if these private symbols are unavailable.
    else:
        connection.argtypes = []
        connection.restype = ctypes.c_int32
        set_tags.argtypes = [ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64), ctypes.c_int32]
        set_tags.restype = ctypes.c_int32
        background_cursor_tag = ctypes.c_uint64(1 << 5)
        set_tags(connection(), panel.windowNumber(), ctypes.byref(background_cursor_tag), 64)

    def update_cursor(event: Any) -> None:
        if QApplication.activePopupWidget() or QApplication.activeModalWidget():
            return
        point = view.convertPoint_fromView_(event.locationInWindow(), None)
        pos = QPoint(math.floor(point.x), math.floor(point.y))
        if not block.rect().contains(pos) or (block.hollow and not handle.mask().contains(pos)):
            return
        shape = block.cursor_at(pos)
        if handle.cursor().shape() != shape:
            handle.setCursor(QCursor(shape))
        # Qt has converted the shape to an NSCursor, but skips cursorUpdate:
        # for an inactive app and may defer it indefinitely for a non-key panel.
        cursor = view.cursor()
        if cursor is not None:
            cursor.set()

    owner = ScreenMaskCursorOwner.new()
    owner.update_cursor = update_cursor
    options = (
        AppKit.NSTrackingActiveAlways | AppKit.NSTrackingInVisibleRect  # pyright: ignore[reportAttributeAccessIssue]
        | AppKit.NSTrackingMouseMoved | AppKit.NSTrackingCursorUpdate  # pyright: ignore[reportAttributeAccessIssue]
        | AppKit.NSTrackingMouseEnteredAndExited  # pyright: ignore[reportAttributeAccessIssue]
    )
    area = AppKit.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(  # pyright: ignore[reportAttributeAccessIssue]
        AppKit.NSZeroRect, options, owner, None)  # pyright: ignore[reportAttributeAccessIssue]
    view.addTrackingArea_(area)

    def stop() -> None:
        view.removeTrackingArea_(area)
        # NSTrackingArea does not retain its owner. Keep it alive until removal.
        del owner.update_cursor

    return stop
