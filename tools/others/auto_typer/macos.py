"""CoreGraphics typing and a native nonactivating panel for the shared Qt controls."""

from functools import cache
import os
from typing import Any, cast

import AppKit  # pyright: ignore[reportMissingImports]
import objc as pyobjc  # pyright: ignore[reportMissingImports]
import Quartz  # pyright: ignore[reportMissingImports]
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QWidget

from utils import Keyboard, System
from utils.macos_input import frontmost_target, post_key as _post
from .panel import run
from .strokes import ascii_key

# PyObjC resolves native framework and bridge members at runtime.
A = cast(Any, AppKit)
Q = cast(Any, Quartz)
objc = cast(Any, pyobjc)


@cache
def _code(name: str) -> int:
    code = Keyboard.macos_virtual_key(name)
    if code is None:
        raise ValueError(f"Missing macOS virtual key for {name!r}.")
    return code


class MacSender:
    """Post Quartz events while the chosen external application is frontmost."""

    def target(self) -> int:
        """Return the external frontmost application's process ID, or zero."""
        return frontmost_target()

    def restore(self, target: int) -> None:
        """Return focus from the text editor to the previously active application."""
        app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(target)
        if app:
            app.activateWithOptions_(A.NSApplicationActivateIgnoringOtherApps)

    def check_ready(self) -> None:
        """Report missing Accessibility access before posting any keys."""
        if not System.check_macos_accessibility_permission(prompt=True):
            raise RuntimeError("Allow Accessibility access for Python or its launcher in System Settings, then retry.")

    def send(self, char: str) -> None:
        """Post a balanced physical key chord or a native Unicode key pair."""
        code, flags, text = 0, 0, ""
        if char.isascii():
            name, shifted = ascii_key(char)
            code = _code(name)
            if shifted:
                flags = Q.kCGEventFlagMaskShift | 0x0002  # Left Shift device flag.
        else:
            text = char
        if flags:
            _post(_code("left_shift"), True, flags, modifier=True)
        try:
            _post(code, True, flags, text=text)
            _post(code, False, flags, text=text)
        finally:
            if flags:
                _post(_code("left_shift"), False, 0, modifier=True)


def activate_editor() -> None:
    """Allow the explicitly opened text editor to receive keyboard input."""
    A.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


class AutoTyperPanel(A.NSPanel):
    def canBecomeKeyWindow(self) -> bool:
        return False

    def canBecomeMainWindow(self) -> bool:
        return False

    def windowWillClose_(self, notification: object) -> None:
        """End the Qt event loop when AppKit closes the native panel."""
        QApplication.exit(0)


def show_panel(widget: QWidget) -> tuple[object, QWindow]:
    """Embed the Qt controls in an NSPanel created with nonactivating style.

    The returned objects must stay alive until the Qt event loop exits.
    """
    style = (A.NSWindowStyleMaskNonactivatingPanel | A.NSWindowStyleMaskTitled
             | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable)
    # Cocoa and the embedded Qt view must start at the same layout-safe size.
    minimum = widget.minimumSizeHint()
    widget.resize(widget.size().expandedTo(minimum))
    rect = A.NSMakeRect(0, 0, widget.width(), widget.height())
    panel = AutoTyperPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, A.NSBackingStoreBuffered, False)
    panel.setReleasedWhenClosed_(False)
    panel.setDelegate_(panel)
    panel.setTitle_(widget.windowTitle())
    panel.setFloatingPanel_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setLevel_(A.NSFloatingWindowLevel)
    panel.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | A.NSWindowCollectionBehaviorFullScreenAuxiliary)
    panel.setContentMinSize_(A.NSMakeSize(minimum.width(), minimum.height()))
    host = QWindow.fromWinId(objc.pyobjc_id(panel.contentView()))
    view = objc.objc_object(c_void_p=int(widget.winId()))
    handle = widget.windowHandle()
    if host is None or handle is None:
        raise RuntimeError("Could not create the macOS panel.")
    handle.setParent(host)
    handle.setPosition(0, 0)
    view.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
    widget.show()
    panel.center()
    panel.orderFrontRegardless()
    return panel, host


def run_macos() -> int:
    """Keep Cocoa's Qt launch delegate from activating the process at startup."""
    variable = "QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"
    previous = os.environ.get(variable)
    os.environ[variable] = "1"
    try:
        A.NSApplication.sharedApplication().setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
        return run(MacSender(), show_panel)
    finally:
        if previous is None:
            del os.environ[variable]
        else:
            os.environ[variable] = previous
