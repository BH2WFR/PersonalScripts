"""Present Cocoa tool windows on the GUI thread."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from AppKit import (  # pyright: ignore[reportAttributeAccessIssue]
    NSApplication, NSApplicationActivateIgnoringOtherApps, NSApplicationActivationPolicyAccessory, NSRunningApplication,
)


@contextmanager
def nonactivating_qt_session() -> Iterator[None]:
    """Preserve the source app's focus from Qt startup through the overlay event loop."""
    variable = "QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"
    previous = os.environ.get(variable)
    os.environ[variable] = "1"
    try:
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        yield
    finally:
        if previous is None:
            del os.environ[variable]
        else:
            os.environ[variable] = previous


def order_window_front(window: Any, *, activate: bool) -> None:
    """Raise an NSWindow, optionally activating its app and giving it keyboard focus."""
    if window.isMiniaturized():
        window.deminiaturize_(None)
    if activate:
        NSRunningApplication.currentApplication().activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        window.makeKeyAndOrderFront_(None)
    else:
        window.orderFrontRegardless()
