"""Native macOS keyboard output for floating input tools."""

import os


def frontmost_target() -> int:
    """Return the frontmost external process ID, or zero for this application."""
    import AppKit as A  # pyright: ignore[reportMissingImports]

    app = A.NSWorkspace.sharedWorkspace().frontmostApplication()
    pid = int(app.processIdentifier()) if app else 0
    return pid if pid != os.getpid() else 0


def post_key(code: int, down: bool, flags: int | None, tap: int | None = None, *,
             modifier: bool = False, text: str = "", repeat: bool = False) -> None:
    """Post one Quartz event. Use the default tap for session input and None for native flags."""
    import Quartz as Q  # pyright: ignore[reportMissingImports]

    event = Q.CGEventCreateKeyboardEvent(None, code, down)
    if event is None:
        raise RuntimeError("macOS could not create a keyboard event.")
    if modifier:
        Q.CGEventSetType(event, Q.kCGEventFlagsChanged)
    elif tap is not None and tap == Q.kCGHIDEventTap:
        # A remapper needs distinct down/up edges even for the Caps Lock position.
        Q.CGEventSetType(event, Q.kCGEventKeyDown if down else Q.kCGEventKeyUp)
    if flags is not None:
        Q.CGEventSetFlags(event, flags)
    if repeat:
        Q.CGEventSetIntegerValueField(event, Q.kCGKeyboardEventAutorepeat, 1)
    if text:
        Q.CGEventKeyboardSetUnicodeString(event, len(text.encode("utf-16-le")) // 2, text)
    Q.CGEventPost(Q.kCGSessionEventTap if tap is None else tap, event)
