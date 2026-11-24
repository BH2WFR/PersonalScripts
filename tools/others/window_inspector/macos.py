"""WindowServer discovery remains available when an application's AX thread is hung."""

import ctypes
import os
import subprocess
import time
from urllib.parse import unquote, urlsplit
from functools import cache
from typing import Any, cast

import AppKit  # pyright: ignore[reportMissingImports]
import ApplicationServices  # pyright: ignore[reportMissingImports]
import Quartz  # pyright: ignore[reportMissingImports]
import objc  # pyright: ignore[reportMissingImports]

from utils.macos_input import frontmost_target
from .model import Properties, PropertyGroup, Rect, Rows, Snapshot, Window

# PyObjC exposes native framework members dynamically.
A = cast(Any, AppKit)
AX = cast(Any, ApplicationServices)
CG = cast(Any, Quartz)
ObjC = cast(Any, objc)


def _records(hidden: bool) -> list[Any]:
    mode = CG.kCGWindowListOptionAll if hidden else CG.kCGWindowListOptionOnScreenOnly
    return CG.CGWindowListCopyWindowInfo(mode | CG.kCGWindowListExcludeDesktopElements, 0) or []


def _rect(record: Any) -> Rect:
    bounds = record[CG.kCGWindowBounds]
    return round(bounds["X"]), round(bounds["Y"]), round(bounds["Width"]), round(bounds["Height"])


def _entry(record: Any) -> Window:
    return Window(int(record[CG.kCGWindowNumber]), int(record[CG.kCGWindowOwnerPID]),
                  str(record.get(CG.kCGWindowName, "")), str(record.get(CG.kCGWindowOwnerName, "")))


def _system_overlay(record: Any) -> bool:
    return record.get(CG.kCGWindowOwnerName) in ("Dock", "Window Server", "WindowServer")


def windows(hidden: bool) -> list[Window]:
    """Include floating panels and untitled windows as well as ordinary app windows."""
    records = [_entry(r) for r in _records(hidden) if int(r[CG.kCGWindowOwnerPID]) != os.getpid()
               and int(r[CG.kCGWindowLayer]) >= 0 and not _system_overlay(r)
               and (hidden or r.get(CG.kCGWindowAlpha, 1) > 0)]
    if not AX.AXIsProcessTrusted():
        return records
    entries = {(w.pid, w.id): w for w in records}
    for app in A.NSWorkspace.sharedWorkspace().runningApplications():
        pid = int(app.processIdentifier())
        if pid == os.getpid() or app.isTerminated() or (app.isHidden() and not hidden):
            continue
        for element in _ax_windows(pid):
            target = _ax_entry(app, element)
            key = (pid, target.id)
            if not hidden and _attribute(element, "AXMinimized", False):
                entries.pop(key, None)
            else:
                entries[key] = target
    return list(entries.values())


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
    return number.value if get_number(ObjC.pyobjc_id(element), ctypes.byref(number)) == 0 else 0


def _ax_entry(app: Any, window: Any) -> Window:
    # Retain the actual AX reference, including windows absent from WindowServer.
    number = _window_id(window) or -(abs(hash(window)) + 1)
    return Window(number, int(app.processIdentifier()), str(_attribute(window, "AXTitle", "")),
                  str(app.localizedName() or ""), window)


def application_target(pid: int) -> Window | None:
    """Capture the focused window, retaining the process even if it has no windows."""
    app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        return None
    if AX.AXIsProcessTrusted():
        ref = AX.AXUIElementCreateApplication(pid)
        AX.AXUIElementSetMessagingTimeout(ref, 0.25)
        focused = _attribute(ref, "AXFocusedWindow")
        if focused is not None:
            return _ax_entry(app, focused)
        candidates = _ax_windows(pid)
        if candidates:
            return _ax_entry(app, candidates[0])
    for record in _records(False):
        if int(record[CG.kCGWindowOwnerPID]) == pid:
            return _entry(record)
    return Window(0, pid, "", str(app.localizedName() or ""))


def foreground() -> Window | None:
    pid = frontmost_target()
    return application_target(pid) if pid else None


def at_pointer() -> Window | None:
    point = CG.CGEventGetLocation(CG.CGEventCreate(None))
    if AX.AXIsProcessTrusted():
        system = AX.AXUIElementCreateSystemWide()
        AX.AXUIElementSetMessagingTimeout(system, 0.2)
        error, element = AX.AXUIElementCopyElementAtPosition(system, point.x, point.y, None)
        if not error and element is not None:
            error, pid = AX.AXUIElementGetPid(element, None)
            if not error:
                if pid == os.getpid():
                    return None
                window = element if _attribute(element, "AXRole") == "AXWindow" else _attribute(element, "AXWindow")
                if window is not None:
                    app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
                    if app is not None:
                        return _ax_entry(app, window)
    # Hung applications and non-AX popups can still expose a WindowServer frame.
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
        if _system_overlay(record):
            continue
        return _entry(record)
    return None


def _record(target: Window) -> Any:
    records = CG.CGWindowListCopyWindowInfo(CG.kCGWindowListOptionIncludingWindow, target.id)
    if not records or _entry(records[0]) != target:
        raise RuntimeError("The window has closed. Select another window.")
    return records[0]


def checked(target: Window) -> Window:
    if target.ax_window is not None:
        error, pid = AX.AXUIElementGetPid(target.ax_window, None)
        if error or pid != target.pid or _attribute(target.ax_window, "AXRole") != "AXWindow":
            raise RuntimeError("The window has closed. Select another window.")
        return target
    if target.id == 0:
        if A.NSRunningApplication.runningApplicationWithProcessIdentifier_(target.pid) is None:
            raise RuntimeError("The application has exited.")
        return target
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
    if target.ax_window is not None:
        return target.ax_window
    for candidate in _ax_windows(target.pid):
        if _window_id(candidate) == target.id:
            return candidate
    raise RuntimeError("The app is unresponsive or does not expose this window through Accessibility.")


def _geometry(window: Any) -> Rect:
    values: list[int] = []
    for attr, kind in (("AXPosition", AX.kAXValueCGPointType), ("AXSize", AX.kAXValueCGSizeType)):
        value = _attribute(window, attr)
        if value is None:
            raise RuntimeError("The window does not expose its bounds.")
        ok, pair = AX.AXValueGetValue(value, kind, None)
        if not ok:
            raise RuntimeError("Could not read the window bounds.")
        values.extend(round(n) for n in pair)
    x, y, width, height = values
    return x, y, width, height


def _application_details(w: Window) -> tuple[Properties, dict[str, str]]:
    app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(w.pid)
    rows: Properties = [(PropertyGroup.PROCESS, "Process ID", str(w.pid)),
                        (PropertyGroup.PROCESS, "Application name", w.kind)]
    paths: dict[str, str] = {}
    if app is not None:
        rows.append((PropertyGroup.BUNDLE, "Bundle ID", str(app.bundleIdentifier() or "")))
        if url := app.executableURL():
            paths["Executable"] = str(url.path())
            rows.append((PropertyGroup.PROCESS, "Executable", paths["Executable"]))
            try:
                binary = subprocess.run(["/usr/bin/file", "-b", paths["Executable"]], timeout=3,
                                        capture_output=True, text=True, check=True)
            except (OSError, subprocess.SubprocessError):
                pass
            else:
                rows.append((PropertyGroup.FILE, "Binary type", binary.stdout.strip()))
        if url := app.bundleURL():
            paths["Application bundle"] = str(url.path())
            rows.append((PropertyGroup.BUNDLE, "Bundle path", paths["Application bundle"]))
            bundle = A.NSBundle.bundleWithPath_(paths["Application bundle"])
            if bundle:
                for label, key in (("Display name", "CFBundleDisplayName"), ("Name", "CFBundleName"),
                                   ("Identifier", "CFBundleIdentifier"), ("Short version", "CFBundleShortVersionString"),
                                   ("Bundle version", "CFBundleVersion"), ("Package type", "CFBundlePackageType"),
                                   ("Minimum system", "LSMinimumSystemVersion")):
                    rows.append((PropertyGroup.BUNDLE, label, str(bundle.objectForInfoDictionaryKey_(key) or "")))
    return rows, paths


def snapshot(target: Window) -> Snapshot:
    w = checked(target)
    rows, paths = _application_details(w)
    if w.id == 0:
        rows.append((PropertyGroup.WINDOW, "Status", "No window exposed by the application."))
        return Snapshot(w, rows, paths=paths)
    rect = None
    if w.id > 0:
        rows.append((PropertyGroup.WINDOW, "Window ID", str(w.id)))
        # A minimized AX window may not have a WindowServer record.
        try:
            record = _record(w)
        except RuntimeError:
            if w.ax_window is None:
                raise
        else:
            rect = _rect(record)
            rows.extend(((PropertyGroup.WINDOW, "On screen", "Yes" if record.get(CG.kCGWindowIsOnscreen) else "No"),
                         (PropertyGroup.STYLES, "Window layer", str(record[CG.kCGWindowLayer]))))
    if AX.AXIsProcessTrusted():
        candidates = _ax_windows(w.pid)
        rows.append((PropertyGroup.WINDOW, "Window count", str(len(candidates))))
        window = w.ax_window
        if window is None:
            window = next((candidate for candidate in candidates if _window_id(candidate) == w.id), None)
        if window is not None:
            w = Window(w.id, w.pid, str(_attribute(window, "AXTitle", w.title)), w.kind, window)
            for label, attr in (("Role", "AXRole"), ("Subrole", "AXSubrole"), ("Minimized", "AXMinimized"),
                                ("Fullscreen", "AXFullScreen"), ("Modal", "AXModal"), ("Document", "AXDocument")):
                value = _attribute(window, attr, "")
                if attr == "AXDocument":
                    document = urlsplit(str(value))
                    if document.scheme == "file" and document.netloc in ("", "localhost") and document.path:
                        paths["Document"] = unquote(document.path)
                elif value != "" and attr in ("AXMinimized", "AXFullScreen", "AXModal"):
                    value = "Yes" if value else "No"
                rows.append((PropertyGroup.WINDOW, label, str(value)))
            try:
                rect = _geometry(window)
            except RuntimeError:
                pass
        else:
            rows.append((PropertyGroup.WINDOW, "Accessibility", "This window is unavailable through Accessibility."))
    else:
        rows.append((PropertyGroup.WINDOW, "Accessibility", "Grant Accessibility permission for window details and actions."))
    if rect is not None:
        x, y, width, height = rect
        rows.extend(((PropertyGroup.GEOMETRY, "Position (points)", f"{x}, {y}"),
                     (PropertyGroup.GEOMETRY, "Size (points)", f"{width} × {height}")))
    rows.append((PropertyGroup.WINDOW, "Title", w.title))
    return Snapshot(w, rows, paths=paths)


def frame(target: Window) -> tuple[Rect, int]:
    if target.ax_window is not None:
        window = _ax_window(checked(target))
        app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(target.pid)
        if app is None or app.isHidden() or _attribute(window, "AXMinimized", False):
            raise RuntimeError("The window is not visible. Activate it first.")
        return _geometry(window), 4
    record = _record(target)
    if not record.get(CG.kCGWindowIsOnscreen):
        raise RuntimeError("The window is not visible. Activate it first.")
    return _rect(record), 4


def check_active(target: Window) -> None:
    """Verify the selected window was actually raised before previewing it."""
    if frontmost_target() != target.pid:
        raise RuntimeError("The application did not come to the foreground.")
    ref = AX.AXUIElementCreateApplication(target.pid)
    AX.AXUIElementSetMessagingTimeout(ref, 0.25)
    focused = _attribute(ref, "AXFocusedWindow")
    if focused is not None and focused != _ax_window(target):
        raise RuntimeError("The application activated a different window.")


def activate_inspector() -> None:
    """Bring a Launch Services background launch forward after capturing its target."""
    A.NSRunningApplication.currentApplication().activateWithOptions_(
        A.NSApplicationActivateIgnoringOtherApps | A.NSApplicationActivateAllWindows)


def configure_edge(view_id: int) -> None:
    """Keep the outline visible over floating panels and fullscreen windows in this Space."""
    panel = ObjC.objc_object(c_void_p=view_id).window()
    panel.setLevel_(A.NSStatusWindowLevel)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(A.NSWindowCollectionBehaviorFullScreenAuxiliary | A.NSWindowCollectionBehaviorIgnoresCycle)


def controls(target: Window) -> Rows:
    window = _ax_window(checked(target))
    return [(str(i), str(_attribute(child, "AXRole", "")), str(_attribute(child, "AXSubrole", "")),
             str(_attribute(child, "AXTitle", "") or _attribute(child, "AXDescription", "")))
            for i, child in enumerate(_attribute(window, "AXChildren", [])[:500], 1)]


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
    AX.AXUIElementSetMessagingTimeout(window, 1.0)
    if action == "Activate":
        app = A.NSRunningApplication.runningApplicationWithProcessIdentifier_(target.pid)
        if app is None:
            raise RuntimeError("The process has exited.")
        restoring = app.isHidden() or bool(_attribute(window, "AXMinimized", False))
        app.unhide()
        if _attribute(window, "AXMinimized", False):
            _check_ax(AX.AXUIElementSetAttributeValue(window, "AXMinimized", False))
        app.activateWithOptions_(A.NSApplicationActivateIgnoringOtherApps)
        error = AX.AXUIElementPerformAction(window, "AXRaise")
        if restoring and error == AX.kAXErrorCannotComplete:
            # Some toolkits cannot raise a window until its restore animation finishes.
            time.sleep(0.25)
            error = AX.AXUIElementPerformAction(window, "AXRaise")
        _check_ax(error)
    elif action == "Minimize":
        _check_ax(AX.AXUIElementSetAttributeValue(window, "AXMinimized", True))
    elif action == "Close Window":
        button = _attribute(window, "AXCloseButton")
        if button is None:
            raise RuntimeError("This window has no close button.")
        _check_ax(AX.AXUIElementPerformAction(button, "AXPress"))
    elif action in ("Center", "Reset Size"):
        x, y, width, height = _geometry(window)
        screens = A.NSScreen.screens()
        top = screens[0].frame().size.height
        areas = []
        for screen in screens:
            r = screen.frame()
            areas.append((r.origin.x, top - r.origin.y - r.size.height, r.size.width, r.size.height))
        cx, cy = x + width / 2, y + height / 2
        area = next((a for a in areas if a[0] <= cx < a[0] + a[2] and a[1] <= cy < a[1] + a[3]), None)
        if area is None:
            def overlap(a: tuple[float, ...]) -> float:
                return (max(0, min(x + width, a[0] + a[2]) - max(x, a[0]))
                        * max(0, min(y + height, a[1] + a[3]) - max(y, a[1])))
            area = max(areas, key=overlap)
        if action == "Reset Size":
            size = AX.AXValueCreate(AX.kAXValueCGSizeType, (1024, 768))
            _check_ax(AX.AXUIElementSetAttributeValue(window, "AXSize", size))
            deadline = time.monotonic() + 0.25
            while True:
                _, _, width, height = _geometry(window)
                if (width, height) == (1024, 768) or time.monotonic() >= deadline:
                    break
                time.sleep(0.025)
        center = (area[0] + (area[2] - width) / 2, area[1] + (area[3] - height) / 2)
        position = AX.AXValueCreate(AX.kAXValueCGPointType, center)
        _check_ax(AX.AXUIElementSetAttributeValue(window, "AXPosition", position))
        if action == "Reset Size" and (width, height) != (1024, 768):
            raise RuntimeError(f"Application limited the size to {width} × {height}. Window centered.")
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
