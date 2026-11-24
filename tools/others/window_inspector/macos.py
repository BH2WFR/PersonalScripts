"""WindowServer discovery remains available when an application's AX thread is hung."""

import ctypes
import os
import subprocess
from functools import cache
from typing import Any

import AppKit as A  # pyright: ignore[reportMissingImports]
import ApplicationServices as AX  # pyright: ignore[reportMissingImports]
import Quartz as CG  # pyright: ignore[reportMissingImports]
import objc  # pyright: ignore[reportMissingImports]

from utils.macos_input import frontmost_target
from .model import Properties, PropertyGroup, Rect, Rows, Snapshot, Window


def _records(hidden: bool) -> list[Any]:
    mode = CG.kCGWindowListOptionAll if hidden else CG.kCGWindowListOptionOnScreenOnly
    return CG.CGWindowListCopyWindowInfo(mode | CG.kCGWindowListExcludeDesktopElements, 0) or []


def _rect(record: Any) -> Rect:
    bounds = record[CG.kCGWindowBounds]
    return round(bounds["X"]), round(bounds["Y"]), round(bounds["Width"]), round(bounds["Height"])


def _entry(record: Any) -> Window:
    return Window(int(record[CG.kCGWindowNumber]), int(record[CG.kCGWindowOwnerPID]),
                  str(record.get(CG.kCGWindowName, "")), str(record.get(CG.kCGWindowOwnerName, "")))


def windows(hidden: bool) -> list[Window]:
    """Include floating panels and untitled windows as well as ordinary app windows."""
    entries = [_entry(r) for r in _records(hidden) if int(r[CG.kCGWindowOwnerPID]) != os.getpid()
               and int(r[CG.kCGWindowLayer]) >= 0]
    if not AX.AXIsProcessTrusted():
        return entries
    # WindowServer can omit captions without Screen Recording permission. Query
    # each affected application just once for its accessible window titles.
    titles: dict[int, str] = {}
    for pid in dict.fromkeys(w.pid for w in entries if not w.title):
        for candidate in _ax_windows(pid):
            number = _window_id(candidate)
            if number:
                titles[number] = str(_attribute(candidate, "AXTitle", ""))
    return [Window(w.id, w.pid, w.title or titles.get(w.id, ""), w.kind) for w in entries]


def _attribute(element: Any, name: str, default: Any = None) -> Any:
    error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return default if error else value


@cache
def _number_function() -> Any:
    # Accessibility has no public window-number attribute. Join by the WindowServer
    # number, never by a title shared by several windows of the same application.
    framework = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    get_number = getattr(framework, "_AXUIElementGetWindow", None)
    if get_number is not None:
        get_number.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        get_number.restype = ctypes.c_int32
    return get_number


def _window_id(element: Any) -> int:
    get_number = _number_function()
    if get_number is None:
        return 0
    number = ctypes.c_uint32()
    return number.value if get_number(objc.pyobjc_id(element), ctypes.byref(number)) == 0 else 0


def foreground() -> Window | None:
    pid = frontmost_target()
    if not pid:
        return None
    entries = [_entry(r) for r in _records(False) if int(r[CG.kCGWindowOwnerPID]) == pid]
    if AX.AXIsProcessTrusted():
        ref = AX.AXUIElementCreateApplication(pid)
        AX.AXUIElementSetMessagingTimeout(ref, 0.2)
        focused = _attribute(ref, "AXFocusedWindow")
        if focused is not None:
            number = _window_id(focused)
            for w in entries:
                if w.id == number:
                    return w
    return next(iter(entries), None)


def at_pointer() -> Window | None:
    point = CG.CGEventGetLocation(CG.CGEventCreate(None))
    for record in _records(False):
        x, y, width, height = _rect(record)
        if not (x <= point.x < x + width and y <= point.y < y + height):
            continue
        if record.get(CG.kCGWindowAlpha, 1) <= 0 or int(record[CG.kCGWindowLayer]) < 0:
            continue
        if int(record[CG.kCGWindowOwnerPID]) == os.getpid():
            # Four thin, input-transparent inspector edges may overlap the pointer.
            if min(width, height) <= 4:
                continue
            return None
        return _entry(record)
    return None


def _record(target: Window) -> Any:
    records = CG.CGWindowListCopyWindowInfo(CG.kCGWindowListOptionIncludingWindow, target.id)
    if not records or _entry(records[0]) != target:
        raise RuntimeError("The window has closed. Select another window.")
    return records[0]


def checked(target: Window) -> Window:
    return _entry(_record(target))


def _ax_windows(pid: int) -> list[Any]:
    ref = AX.AXUIElementCreateApplication(pid)
    AX.AXUIElementSetMessagingTimeout(ref, 0.25)
    candidates = list(_attribute(ref, "AXWindows", []))
    for key in ("AXFocusedWindow", "AXMainWindow"):
        extra = _attribute(ref, key)
        if extra is not None and extra not in candidates:
            candidates.append(extra)
    for candidate in candidates:
        AX.AXUIElementSetMessagingTimeout(candidate, 0.25)
    return candidates


def _ax_window(target: Window) -> Any:
    if not AX.AXIsProcessTrusted():
        raise RuntimeError("Allow this app under System Settings → Privacy & Security → Accessibility.")
    for candidate in _ax_windows(target.pid):
        if _window_id(candidate) == target.id:
            return candidate
    raise RuntimeError("The app is unresponsive or does not expose this window through Accessibility.")


def snapshot(target: Window) -> Snapshot:
    record = _record(target)
    w = _entry(record)
    x, y, width, height = _rect(record)
    rows: Properties = [
        (PropertyGroup.WINDOW, "Window ID", str(w.id)),
        (PropertyGroup.WINDOW, "On screen", "Yes" if record.get(CG.kCGWindowIsOnscreen) else "No"),
        (PropertyGroup.PROCESS, "Process ID", str(w.pid)),
        (PropertyGroup.PROCESS, "Application name", w.kind),
        (PropertyGroup.GEOMETRY, "Position (points)", f"{x}, {y}"),
        (PropertyGroup.GEOMETRY, "Size (points)", f"{width} × {height}"),
        (PropertyGroup.STYLES, "Window layer", str(record[CG.kCGWindowLayer])),
    ]
    app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(w.pid)
    if app is not None:
        rows.append((PropertyGroup.BUNDLE, "Bundle ID", str(app.bundleIdentifier() or "")))
        if bundle := app.bundleURL():
            rows.append((PropertyGroup.BUNDLE, "Bundle path", str(bundle.path())))
    if AX.AXIsProcessTrusted() and not w.title:
        try:
            title = _attribute(_ax_window(w), "AXTitle", "")
            w = Window(w.id, w.pid, str(title), w.kind)
        except RuntimeError:
            pass
    return Snapshot(w, rows)


def frame(target: Window) -> tuple[Rect, int]:
    record = _record(target)
    if not record.get(CG.kCGWindowIsOnscreen):
        raise RuntimeError("The window is not visible. Activate it first.")
    return _rect(record), 4


def configure_edge(view_id: int) -> None:
    """Keep the outline visible over floating panels and fullscreen windows in this Space."""
    panel = objc.objc_object(c_void_p=view_id).window()
    panel.setLevel_(A.NSStatusWindowLevel)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(A.NSWindowCollectionBehaviorFullScreenAuxiliary | A.NSWindowCollectionBehaviorIgnoresCycle)


def controls(target: Window) -> Rows:
    window = _ax_window(checked(target))
    return [(str(i), str(_attribute(child, "AXRole", "")), str(_attribute(child, "AXSubrole", "")),
             str(_attribute(child, "AXTitle", "") or _attribute(child, "AXDescription", "")))
            for i, child in enumerate(_attribute(window, "AXChildren", []), 1)]


def enable_controls(target: Window) -> tuple[int, int]:
    raise NotImplementedError("Enable Controls requires Windows.")


def enable_menu(target: Window) -> tuple[int, int]:
    raise NotImplementedError("Enable Menus requires Windows.")


def show_controls(target: Window) -> tuple[int, int]:
    raise NotImplementedError("Show Controls requires Windows.")


def _check_ax(error: int) -> None:
    if error:
        raise RuntimeError(f"The window did not respond or does not support this action (AX error {error}).")


def act(target: Window, action: str, value: int = 0) -> None:
    window = _ax_window(checked(target))
    if action == "Activate":
        app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(target.pid)
        if app is None:
            raise RuntimeError("The process has exited.")
        app.unhide()
        if _attribute(window, "AXMinimized", False):
            _check_ax(AX.AXUIElementSetAttributeValue(window, "AXMinimized", False))
        app.activateWithOptions_(A.NSApplicationActivateIgnoringOtherApps)
        _check_ax(AX.AXUIElementPerformAction(window, "AXRaise"))
    elif action == "Minimize":
        _check_ax(AX.AXUIElementSetAttributeValue(window, "AXMinimized", True))
    elif action == "Close Window":
        button = _attribute(window, "AXCloseButton")
        if button is None:
            raise RuntimeError("This window has no close button.")
        _check_ax(AX.AXUIElementPerformAction(button, "AXPress"))
    elif action in ("Center", "Reset Size"):
        x, y, width, height = _rect(_record(target))
        screens = A.NSScreen.screens()
        top = screens[0].frame().size.height
        def overlap(screen: Any) -> float:
            r = screen.frame()
            left, upper = r.origin.x, top - r.origin.y - r.size.height
            return (max(0, min(x + width, left + r.size.width) - max(x, left))
                    * max(0, min(y + height, upper + r.size.height) - max(y, upper)))
        area = max(screens, key=overlap).visibleFrame()
        if action == "Reset Size":
            width, height = min(1024, area.size.width), min(768, area.size.height)
            size = AX.AXValueCreate(AX.kAXValueCGSizeType, (width, height))
            _check_ax(AX.AXUIElementSetAttributeValue(window, "AXSize", size))
        center = (area.origin.x + (area.size.width - width) / 2, top - area.origin.y - (area.size.height + height) / 2)
        position = AX.AXValueCreate(AX.kAXValueCGPointType, center)
        _check_ax(AX.AXUIElementSetAttributeValue(window, "AXPosition", position))
    else:
        raise ValueError(action)


def file_action(path: str, properties: bool) -> None:
    if properties:
        script = '''on run argv
tell application "Finder"
    open information window of (POSIX file (item 1 of argv) as alias)
    activate
end tell
end run'''
        subprocess.run(["/usr/bin/osascript", "-e", script, path], check=True, timeout=15)
    else:
        subprocess.run(["/usr/bin/open", "-R", path], check=True, timeout=5)
