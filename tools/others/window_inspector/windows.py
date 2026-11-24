"""Win32 window discovery and manipulation in per-monitor-aware screen coordinates."""

import ctypes as C
import os
from ctypes import wintypes as W
from typing import Any

from .model import MIN_OPACITY_PERCENT, Properties, PropertyGroup, Rect, Rows, Snapshot, Window


U = C.WinDLL("user32", use_last_error=True)
DWM = C.WinDLL("dwmapi")
SHELL = C.WinDLL("shell32")
OLE = C.WinDLL("ole32")
SHCORE = C.WinDLL("shcore")
KERNEL = C.WinDLL("kernel32", use_last_error=True)
ADV = C.WinDLL("advapi32")
VERSION = C.WinDLL("version")
ENUM = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
PTR = C.c_void_p
LAYERED, TRANSPARENT, TOPMOST = 0x80000, 0x20, 0x8
EXSTYLE, STYLE = -20, -16
NO_ACTIVATE, ASYNC, NO_ZORDER = 0x10, 0x4000, 0x4
SW_SHOW = 5
MIIM_STATE = 0x1
MFS_DISABLED, MFS_ENABLED = 0x3, 0x0


class MonitorInfo(C.Structure):
    _fields_ = [("size", W.DWORD), ("monitor", W.RECT), ("work", W.RECT), ("flags", W.DWORD)]


class WindowPlacement(C.Structure):
    _fields_ = [("size", W.UINT), ("flags", W.UINT), ("show", W.UINT),
                ("minimized", W.POINT), ("maximized", W.POINT), ("normal", W.RECT)]


class MenuItemInfo(C.Structure):
    _fields_ = [("size", W.UINT), ("mask", W.UINT), ("type", W.UINT), ("state", W.UINT),
                ("id", W.UINT), ("submenu", W.HANDLE), ("checked", W.HANDLE), ("unchecked", W.HANDLE),
                ("data", C.c_size_t), ("type_data", W.LPWSTR), ("text", W.UINT), ("bitmap", W.HANDLE)]


def _bind(dll: Any, name: str, result: Any, *args: Any) -> None:
    proc = getattr(dll, name)
    proc.restype, proc.argtypes = result, args


for _name in ("IsWindowVisible", "IsIconic", "IsZoomed", "IsHungAppWindow", "SetForegroundWindow", "IsWindowEnabled"):
    _bind(U, _name, W.BOOL, W.HWND)
_bind(U, "EnableWindow", W.BOOL, W.HWND, W.BOOL)
_bind(U, "GetMenu", W.HANDLE, W.HWND)
_bind(U, "GetMenuItemCount", C.c_int, W.HANDLE)
_bind(U, "GetSubMenu", W.HANDLE, W.HANDLE, C.c_int)
_bind(U, "GetMenuItemInfoW", W.BOOL, W.HANDLE, W.UINT, W.BOOL, PTR)
_bind(U, "SetMenuItemInfoW", W.BOOL, W.HANDLE, W.UINT, W.BOOL, PTR)
_bind(U, "DrawMenuBar", W.BOOL, W.HWND)
for _name in ("GetWindowTextW", "GetClassNameW"):
    _bind(U, _name, C.c_int, W.HWND, W.LPWSTR, C.c_int)
_bind(U, "EnumWindows", W.BOOL, ENUM, W.LPARAM)
_bind(U, "EnumChildWindows", W.BOOL, W.HWND, ENUM, W.LPARAM)
_bind(U, "GetWindowThreadProcessId", W.DWORD, W.HWND, C.POINTER(W.DWORD))
_bind(U, "GetForegroundWindow", W.HWND)
_bind(U, "GetPhysicalCursorPos", W.BOOL, C.POINTER(W.POINT))
_bind(U, "WindowFromPhysicalPoint", W.HWND, W.POINT)
_bind(U, "GetAncestor", W.HWND, W.HWND, W.UINT)
_bind(U, "GetParent", W.HWND, W.HWND)
_bind(U, "GetWindowRect", W.BOOL, W.HWND, C.POINTER(W.RECT))
_bind(U, "GetWindowPlacement", W.BOOL, W.HWND, C.POINTER(WindowPlacement))
_bind(U, "GetWindowLongW", W.LONG, W.HWND, C.c_int)
_bind(U, "SetWindowLongW", W.LONG, W.HWND, C.c_int, W.LONG)
_bind(U, "GetLayeredWindowAttributes", W.BOOL, W.HWND, PTR, PTR, PTR)
_bind(U, "SetLayeredWindowAttributes", W.BOOL, W.HWND, W.DWORD, W.BYTE, W.DWORD)
_bind(U, "MonitorFromWindow", W.HANDLE, W.HWND, W.DWORD)
_bind(U, "GetMonitorInfoW", W.BOOL, W.HANDLE, C.POINTER(MonitorInfo))
_bind(U, "SetWindowPos", W.BOOL, W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT)
_bind(U, "ShowWindowAsync", W.BOOL, W.HWND, C.c_int)
_bind(U, "PostMessageW", W.BOOL, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
_bind(U, "SendMessageTimeoutW", W.LPARAM, W.HWND, W.UINT, W.WPARAM, PTR, W.UINT, W.UINT, PTR)
_bind(DWM, "DwmGetWindowAttribute", W.LONG, W.HWND, W.DWORD, PTR, W.DWORD)
_bind(SHCORE, "GetScaleFactorForMonitor", W.LONG, W.HANDLE, C.POINTER(C.c_int))
_bind(SHELL, "SHObjectProperties", W.BOOL, W.HWND, W.DWORD, W.LPCWSTR, W.LPCWSTR)
_bind(SHELL, "SHParseDisplayName", W.LONG, W.LPCWSTR, PTR, C.POINTER(PTR), W.DWORD, PTR)
_bind(SHELL, "SHOpenFolderAndSelectItems", W.LONG, PTR, W.UINT, PTR, W.DWORD)
_bind(OLE, "CoTaskMemFree", None, PTR)
_bind(KERNEL, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
_bind(KERNEL, "CloseHandle", W.BOOL, W.HANDLE)
_bind(KERNEL, "GetBinaryTypeW", W.BOOL, W.LPCWSTR, C.POINTER(W.DWORD))
_bind(ADV, "OpenProcessToken", W.BOOL, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE))
_bind(ADV, "GetTokenInformation", W.BOOL, W.HANDLE, C.c_int, PTR, W.DWORD, C.POINTER(W.DWORD))
_bind(VERSION, "GetFileVersionInfoSizeW", W.DWORD, W.LPCWSTR, PTR)
_bind(VERSION, "GetFileVersionInfoW", W.BOOL, W.LPCWSTR, W.DWORD, W.DWORD, PTR)
_bind(VERSION, "VerQueryValueW", W.BOOL, PTR, W.LPCWSTR, PTR, C.POINTER(W.UINT))
if hasattr(U, "HungWindowFromGhostWindow"):
    _bind(U, "HungWindowFromGhostWindow", W.HWND, W.HWND)
if hasattr(U, "GhostWindowFromHungWindow"):
    _bind(U, "GhostWindowFromHungWindow", W.HWND, W.HWND)


def _require(result: int) -> None:
    if not result:
        raise C.WinError(C.get_last_error())


def _text(hwnd: int, *, kind: bool = False) -> str:
    buffer = C.create_unicode_buffer(256 if kind else 4096)
    (U.GetClassNameW if kind else U.GetWindowTextW)(hwnd, buffer, len(buffer))
    return buffer.value


def _entry(hwnd: int) -> Window | None:
    if not hwnd:
        return None
    kind = _text(hwnd, kind=True)
    if kind == "Ghost" and hasattr(U, "HungWindowFromGhostWindow"):
        hwnd = U.HungWindowFromGhostWindow(hwnd) or hwnd
        kind = _text(hwnd, kind=True)
    pid = W.DWORD()
    if not U.GetWindowThreadProcessId(hwnd, C.byref(pid)) or pid.value == os.getpid():
        return None
    return Window(hwnd, pid.value, _text(hwnd), kind)


def _handles(parent: int = 0) -> list[int]:
    handles: list[int] = []
    @ENUM
    def append(hwnd: int, _: int) -> bool:
        handles.append(hwnd)
        return True
    if parent:
        U.EnumChildWindows(parent, append, 0)
    else:
        _require(U.EnumWindows(append, 0))
    return handles


def windows(hidden: bool) -> list[Window]:
    """Enumerate top-level windows in native Z order, including owned popups."""
    return list(dict.fromkeys(w for hwnd in _handles() if hidden or U.IsWindowVisible(hwnd)
                              if (w := _entry(hwnd)) is not None))


def foreground() -> Window | None:
    return _entry(U.GetForegroundWindow())


def at_pointer() -> Window | None:
    point = W.POINT()
    _require(U.GetPhysicalCursorPos(C.byref(point)))
    hwnd = U.WindowFromPhysicalPoint(point)
    return _entry(U.GetAncestor(hwnd, 2)) if hwnd else None  # GA_ROOT preserves owned popups.


def checked(target: Window) -> Window:
    current = _entry(target.id)
    if current != target or current is None:
        raise RuntimeError("The window has closed. Select another window.")
    return current


def _rect(hwnd: int, visible_frame: bool = False) -> Rect:
    r = W.RECT()
    if not visible_frame or DWM.DwmGetWindowAttribute(hwnd, 9, C.byref(r), C.sizeof(r)) != 0:
        _require(U.GetWindowRect(hwnd, C.byref(r)))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _scale(hwnd: int) -> float:
    factor = C.c_int()
    monitor = U.MonitorFromWindow(hwnd, 2)
    return factor.value / 100 if SHCORE.GetScaleFactorForMonitor(monitor, C.byref(factor)) == 0 else 1.0


def _work_area(hwnd: int) -> W.RECT:
    monitor = MonitorInfo()
    monitor.size = C.sizeof(monitor)
    _require(U.GetMonitorInfoW(U.MonitorFromWindow(hwnd, 2), C.byref(monitor)))
    return monitor.work


def frame(target: Window) -> tuple[Rect, int]:
    original = checked(target).id
    hwnd = original
    if hasattr(U, "GhostWindowFromHungWindow") and U.IsHungAppWindow(hwnd):
        hwnd = U.GhostWindowFromHungWindow(hwnd) or hwnd
    cloaked = W.DWORD()
    DWM.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
    if U.IsIconic(hwnd) or not U.IsWindowVisible(hwnd) or cloaked.value:
        raise RuntimeError("The window is not visible. Activate it first.")
    bounds = _rect(hwnd, True)
    if U.IsZoomed(original):
        # A maximized frame can include resize borders outside the work area.
        area = _work_area(hwnd)
        x, y, width, height = bounds
        left, top = max(x, area.left), max(y, area.top)
        bounds = (left, top, min(x + width, area.right) - left, min(y + height, area.bottom) - top)
    return bounds, max(1, round(4 * _scale(hwnd)))


def position_edge(hwnd: int, rect: Rect) -> None:
    """Place overlay edges using DWM physical coordinates, including across mixed-DPI screens."""
    _require(U.SetWindowPos(hwnd, -1, *rect, NO_ACTIVATE | 0x40))


def _layer(hwnd: int) -> tuple[int, int, int]:
    key, alpha, flags = W.DWORD(), W.BYTE(), W.DWORD()
    U.GetLayeredWindowAttributes(hwnd, C.byref(key), C.byref(alpha), C.byref(flags))
    return key.value, alpha.value if flags.value & 2 else 255, flags.value


def snapshot(target: Window) -> Snapshot:
    w = checked(target)
    hwnd = w.id
    x, y, width, height = _rect(hwnd)
    style = U.GetWindowLongW(hwnd, STYLE) & 0xffffffff
    ex = U.GetWindowLongW(hwnd, EXSTYLE) & 0xffffffff
    top, layered = bool(ex & TOPMOST), bool(ex & LAYERED)
    through = layered and bool(ex & TRANSPARENT)
    opacity = round(_layer(hwnd)[1] * 100 / 255)
    state = "Normal"
    if not U.IsWindowVisible(hwnd):
        state = "Hidden"
    elif U.IsIconic(hwnd):
        state = "Minimized"
    elif U.IsZoomed(hwnd):
        state = "Maximized"
    parent = U.GetParent(hwnd) or 0
    yes = {True: "Yes", False: "No"}
    pid = W.DWORD()
    count = sum(1 for handle in _handles() if U.GetWindowThreadProcessId(handle, C.byref(pid)) and pid.value == w.pid)
    rows: Properties = [
        (PropertyGroup.WINDOW, "HWND", f"0x{hwnd:08X}"),
        (PropertyGroup.WINDOW, "Window class", w.kind),
        (PropertyGroup.WINDOW, "Window state", state),
        (PropertyGroup.WINDOW, "Unresponsive", yes[bool(U.IsHungAppWindow(hwnd))]),
        (PropertyGroup.PROCESS, "Process ID", str(w.pid)),
        (PropertyGroup.PROCESS, "Thread ID", str(U.GetWindowThreadProcessId(hwnd, None))),
        (PropertyGroup.PROCESS, "Windows in process", str(count)),
        (PropertyGroup.GEOMETRY, "Position (pixels)", f"{x}, {y}"),
        (PropertyGroup.GEOMETRY, "Size (pixels)", f"{width} × {height}"),
        (PropertyGroup.GEOMETRY, "Display scaling", f"{_scale(hwnd):.0%}"),
        (PropertyGroup.STYLES, "Always on Top", yes[top]),
        (PropertyGroup.STYLES, "Layered", yes[layered]),
        (PropertyGroup.STYLES, "Layered click-through", yes[through]),
        (PropertyGroup.STYLES, "Opacity", f"{opacity}%"),
        (PropertyGroup.STYLES, "Tool window", yes[bool(ex & 0x80)]),
        (PropertyGroup.STYLES, "No-activate style", yes[bool(ex & 0x08000000)]),
        (PropertyGroup.STYLES, "Style", f"0x{style:08X}"),
        (PropertyGroup.STYLES, "ExStyle", f"0x{ex:08X}"),
        (PropertyGroup.PARENT, "Parent HWND", f"0x{parent:08X}"),
        (PropertyGroup.PARENT, "Parent title", _text(parent) if parent else ""),
        (PropertyGroup.PARENT, "Parent class", _text(parent, kind=True) if parent else ""),
    ]
    return Snapshot(w, rows, opacity, top, through)


def controls(target: Window) -> Rows:
    """Read child controls with bounded messaging even if their owner stops responding."""
    rows: Rows = []
    counts: dict[str, int] = {}
    for child in _handles(checked(target).id):
        try:
            x, y, width, height = _rect(child)
        except OSError:
            continue
        kind = _text(child, kind=True)
        counts[kind] = counts.get(kind, 0) + 1
        buffer = C.create_unicode_buffer(4096)
        if not U.IsHungAppWindow(child):
            U.SendMessageTimeoutW(child, 0x000D, len(buffer), buffer, 2, 100, None)
        rows.append((str(len(rows) + 1), f"0x{child:08X}", f"{kind}{counts[kind]}", buffer.value,
                     kind, f"{x}, {y}, {width} × {height}"))
    return rows


def enable_controls(target: Window) -> tuple[int, int]:
    """Enable disabled child controls in the selected window.

    Returns (total, enabled). Windows may reject changes to a
    higher-integrity window, in which case those controls stay as they were
    while the count still records the attempt.
    """
    hwnd = checked(target).id
    total = enabled = 0
    for child in _handles(hwnd):
        total += 1
        if not U.IsWindowEnabled(child):
            U.EnableWindow(child, True)
            enabled += 1
    return total, enabled


def show_controls(target: Window) -> tuple[int, int]:
    """Show hidden child controls in the selected window.

    Returns (total, shown). Windows may reject changes to a higher-integrity
    window, in which case those controls stay as they were while the count
    still records the attempt.
    """
    hwnd = checked(target).id
    total = shown = 0
    for child in _handles(hwnd):
        total += 1
        if not U.IsWindowVisible(child):
            U.ShowWindowAsync(child, SW_SHOW)
            shown += 1
    return total, shown


def _menu_item_state(menu: int, index: int) -> int:
    """Read a menu item's state, treating a failed read as already enabled."""
    info = MenuItemInfo()
    info.size = C.sizeof(info)
    info.mask = MIIM_STATE
    return info.state if U.GetMenuItemInfoW(menu, index, True, C.byref(info)) else MFS_ENABLED


def _set_menu_item_state(menu: int, index: int, state: int) -> bool:
    info = MenuItemInfo()
    info.size = C.sizeof(info)
    info.mask = MIIM_STATE
    info.state = state
    return bool(U.SetMenuItemInfoW(menu, index, True, C.byref(info)))


def _enable_menu_items(menu: int) -> tuple[int, int]:
    """Recursively enable disabled items in a menu and its submenus."""
    total = enabled = 0
    for index in range(U.GetMenuItemCount(menu)):
        total += 1
        if _menu_item_state(menu, index) & MFS_DISABLED and _set_menu_item_state(menu, index, MFS_ENABLED):
            enabled += 1
        if submenu := U.GetSubMenu(menu, index):
            sub_total, sub_enabled = _enable_menu_items(submenu)
            total += sub_total
            enabled += sub_enabled
    return total, enabled


def enable_menu(target: Window) -> tuple[int, int]:
    """Enable disabled items in the selected window's standard menu bar.

    Returns (total, enabled) over the whole menu tree, or (0, 0) when the
    window has no standard menu bar. Applications that re-disable items when a
    menu opens may restore the disabled state, so the change may not persist.
    """
    hwnd = checked(target).id
    menu = U.GetMenu(hwnd)
    if not menu:
        return 0, 0
    total, enabled = _enable_menu_items(menu)
    U.DrawMenuBar(hwnd)
    return total, enabled


def elevated(pid: int) -> bool | None:
    """Return the process token's elevation, or None when it cannot be inspected."""
    handle = KERNEL.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        token = W.HANDLE()
        try:
            if ADV.OpenProcessToken(handle, 0x0008, C.byref(token)):  # TOKEN_QUERY
                value, length = W.DWORD(), W.DWORD()
                try:
                    if ADV.GetTokenInformation(token, 20, C.byref(value), C.sizeof(value), C.byref(length)):
                        return bool(value.value)
                finally:
                    KERNEL.CloseHandle(token)
        finally:
            KERNEL.CloseHandle(handle)
    return None


def process_rows(pid: int, path: str) -> Properties:
    """Read elevation and executable metadata when the selected process permits access."""
    rows: Properties = []
    if (admin := elevated(pid)) is not None:
        rows.append((PropertyGroup.PROCESS, "Elevated", "Yes" if admin else "No"))
    kind = W.DWORD()
    if path and KERNEL.GetBinaryTypeW(path, C.byref(kind)) and kind.value in (0, 6):
        rows.append((PropertyGroup.PROCESS, "Process architecture", "64-bit" if kind.value == 6 else "32-bit"))
    size = VERSION.GetFileVersionInfoSizeW(path, None) if path else 0
    if size:
        buffer = C.create_string_buffer(size)
        fixed, length = C.POINTER(W.DWORD)(), W.UINT()
        if (VERSION.GetFileVersionInfoW(path, 0, size, buffer)
                and VERSION.VerQueryValueW(buffer, "\\", C.byref(fixed), C.byref(length))
                and length.value >= 16 and fixed[0] == 0xFEEF04BD):
            major, minor = fixed[2], fixed[3]
            rows.append((PropertyGroup.FILE, "File version", f"{major >> 16}.{major & 0xffff}.{minor >> 16}.{minor & 0xffff}"))
    return rows


def _set_style(hwnd: int, ex: int) -> None:
    C.set_last_error(0)
    if not U.SetWindowLongW(hwnd, EXSTYLE, ex) and C.get_last_error():
        raise C.WinError(C.get_last_error())


def _set_layer(hwnd: int, percent: int, through: bool | None = None) -> None:
    if not MIN_OPACITY_PERCENT <= percent <= 100:
        raise ValueError(f"Opacity must be between {MIN_OPACITY_PERCENT}% and 100%.")
    old = U.GetWindowLongW(hwnd, EXSTYLE)
    ex = old
    if through is not None:
        ex = ex | TRANSPARENT if through else ex & ~TRANSPARENT
    key, _, flags = _layer(hwnd)
    if percent < 100 or ex & TRANSPARENT or flags & 1:
        _set_style(hwnd, ex | LAYERED)
        try:
            # Round the minimum upward so the native alpha also meets the floor.
            alpha = max((MIN_OPACITY_PERCENT * 255 + 99) // 100, round(percent * 255 / 100))
            _require(U.SetLayeredWindowAttributes(hwnd, key, alpha, flags | 2))
        except OSError:
            _set_style(hwnd, old)
            raise
    else:
        _set_style(hwnd, ex & ~LAYERED)


def act(target: Window, action: str, value: int = 0) -> None:
    hwnd = checked(target).id
    if action == "Close Window":
        _require(U.PostMessageW(hwnd, 0x0010, 0, 0))
    elif action == "Minimize":
        _require(U.ShowWindowAsync(hwnd, 6 if U.GetWindowLongW(hwnd, STYLE) & 0x20000 else 0))
    elif action == "Activate":
        if U.IsIconic(hwnd) or not U.IsWindowVisible(hwnd):
            U.ShowWindowAsync(hwnd, 9)
        if not U.SetForegroundWindow(hwnd):
            raise RuntimeError("Windows did not allow the target window to take focus.")
    elif action in ("Center", "Reset Size"):
        area = _work_area(hwnd)
        _, _, width, height = _rect(hwnd)
        if action == "Reset Size":
            scale = _scale(hwnd)
            width, height = round(1000 * scale), round(800 * scale)
        if U.IsIconic(hwnd) or U.IsZoomed(hwnd):
            if action == "Center":
                placement = WindowPlacement()
                placement.size = C.sizeof(placement)
                _require(U.GetWindowPlacement(hwnd, C.byref(placement)))
                r = placement.normal
                width, height = r.right - r.left, r.bottom - r.top
            _require(U.ShowWindowAsync(hwnd, 9))
        width, height = min(width, area.right - area.left), min(height, area.bottom - area.top)
        _require(U.SetWindowPos(hwnd, None, (area.left + area.right - width) // 2,
                                (area.top + area.bottom - height) // 2, width, height, NO_ZORDER | NO_ACTIVATE | ASYNC))
    elif action == "Opacity":
        _set_layer(hwnd, value)
    elif action in ("Always on Top", "Click-through"):
        if action == "Click-through":
            alpha = _layer(hwnd)[1]
            percent = round(alpha * 100 / 255) if alpha < 255 else 59
            _set_layer(hwnd, max(MIN_OPACITY_PERCENT, percent) if value else 100, bool(value))
        _require(U.SetWindowPos(hwnd, -1 if value else -2, 0, 0, 0, 0, 3 | NO_ACTIVATE | ASYNC))
    else:
        raise ValueError(action)


def file_action(path: str, properties: bool) -> None:
    if properties:
        _require(SHELL.SHObjectProperties(None, 2, path, None))
        return
    item = PTR()
    result = SHELL.SHParseDisplayName(path, None, C.byref(item), 0, None)
    if result >= 0:
        try:
            result = SHELL.SHOpenFolderAndSelectItems(item, 0, None, 0)
        finally:
            OLE.CoTaskMemFree(item)
    if result < 0:
        raise OSError(f"File Explorer could not locate the file (HRESULT 0x{result & 0xffffffff:08X}).")
