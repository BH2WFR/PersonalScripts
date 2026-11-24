"""Lazy platform selection for hooks, controllers and foreground windows.

No platform dependencies or native APIs are loaded until a factory is called.
Use through the viewer application or its api module; standard-library only.
"""

from __future__ import annotations

import sys

from .models import EventSink, Hook, InputController, WindowInfo


def create_hook(sink: EventSink) -> Hook:
    """Create an inactive hook for this platform.

    Args:
        sink: Receiver for normalized native event callbacks.

    Returns:
        Hook with start/stop methods and a readiness event.

    Raises:
        ImportError: A required platform library is missing.
        OSError: The platform is unsupported or construction fails.
        NotImplementedError: Linux is not running X11.
    """
    if sys.platform == "win32":
        from . import windows
        hook = windows.create_hook(sink)
    elif sys.platform == "darwin":
        from . import macos
        hook = macos.create_hook(sink)
        if hook is None:
            raise ImportError("macOS requires pyobjc-framework-Quartz.")
    elif sys.platform.startswith("linux"):
        from . import x11
        hook = x11.create_hook(sink)
    else:
        raise OSError(f"Unsupported platform: {sys.platform}")
    if hook is None:
        raise OSError(f"Cannot construct hooks on {sys.platform}")
    return hook


def create_controller() -> InputController:
    """Return a platform input controller without sending input.

    Raises:
        OSError: The platform is unsupported.
    """
    if sys.platform == "win32":
        from .windows import _WinController
        return _WinController()
    if sys.platform == "darwin":
        from .macos import _MacController
        return _MacController()
    if sys.platform.startswith("linux"):
        from .x11 import _X11Controller
        return _X11Controller()
    raise OSError(f"Unsupported platform: {sys.platform}")


def get_foreground_window() -> WindowInfo:
    """Read foreground window metadata, returning empty fields if unavailable.

    Side effects:
        Queries the platform window system. Optional platform imports may raise
        ImportError when their dependencies are missing.
    """
    if sys.platform == "win32":
        from .windows import _get_foreground_window_win
        return _get_foreground_window_win()
    if sys.platform == "darwin":
        from .macos import _get_foreground_window_darwin
        return _get_foreground_window_darwin()
    if sys.platform.startswith("linux"):
        from .x11 import _get_foreground_window_x11
        return _get_foreground_window_x11()
    return WindowInfo()
