#!/usr/bin/env python3
"""Display detailed information about all connected monitors on Windows.

Uses Win32 native APIs (EnumDisplayMonitors, GetMonitorInfo, EnumDisplaySettings,
GetDpiForMonitor) via ctypes to report accurate values regardless of DPI
virtualization.  Reports actual (physical pixel) resolution, DPI scale ratio,
effective resolution, monitor device name, and primary status.

Requirements:
    - Windows only (ctypes Win32 API)
    - No third-party packages required

Usage:
    python windows/show-screen-resolution.py
    python windows/show-screen-resolution.py --help
"""

import os
import sys
import ctypes
from ctypes import wintypes

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

# ============ platform guard ============
if sys.platform != "win32":
    Console.print_error_and_exit(
        f"This script only runs on Windows.  Current platform: {sys.platform}"
    )

# ============ constants ============
ENUM_CURRENT_SETTINGS = -1
MDT_EFFECTIVE_DPI = 0

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = ctypes.c_void_p(-3)
PROCESS_PER_MONITOR_DPI_AWARE = 2


# ============ Win32 structs ============
class RECT(ctypes.Structure):
    _fields_ = [
        ("left",   ctypes.c_int),
        ("top",    ctypes.c_int),
        ("right",  ctypes.c_int),
        ("bottom", ctypes.c_int),
    ]


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize",    ctypes.c_int),
        ("rcMonitor", RECT),
        ("rcWork",    RECT),
        ("dwFlags",   ctypes.c_int),
        ("szDevice",  ctypes.c_wchar * 32),
    ]


class DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName",        ctypes.c_wchar * 32),
        ("dmSpecVersion",       wintypes.WORD),
        ("dmDriverVersion",     wintypes.WORD),
        ("dmSize",              wintypes.WORD),
        ("dmDriverExtra",       wintypes.WORD),
        ("dmFields",            wintypes.DWORD),
        ("dmPositionX",         ctypes.c_int),
        ("dmPositionY",         ctypes.c_int),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor",             ctypes.c_short),
        ("dmDuplex",            ctypes.c_short),
        ("dmYResolution",       ctypes.c_short),
        ("dmTTOption",          ctypes.c_short),
        ("dmCollate",           ctypes.c_short),
        ("dmFormName",          ctypes.c_wchar * 32),
        ("dmLogPixels",         wintypes.WORD),
        ("dmBitsPerPel",        wintypes.DWORD),
        ("dmPelsWidth",         wintypes.DWORD),
        ("dmPelsHeight",        wintypes.DWORD),
        ("dmDisplayFlags",      wintypes.DWORD),
        ("dmDisplayFrequency",  wintypes.DWORD),
        ("dmICMMethod",         wintypes.DWORD),
        ("dmICMIntent",         wintypes.DWORD),
        ("dmMediaType",         wintypes.DWORD),
        ("dmDitherType",        wintypes.DWORD),
        ("dmReserved1",         wintypes.DWORD),
        ("dmReserved2",         wintypes.DWORD),
        ("dmPanningWidth",      wintypes.DWORD),
        ("dmPanningHeight",     wintypes.DWORD),
    ]


# ============ callback type & collected data ============
MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(RECT), wintypes.LPARAM,
)

_collected_monitors: list[dict] = []


def _enum_callback(
    hMonitor: wintypes.HMONITOR,
    hdcMonitor: wintypes.HDC,
    lprcMonitor: int,  # really ctypes.POINTER(RECT) — Pylance can't validate
    dwData: wintypes.LPARAM,
) -> bool:
    """EnumDisplayMonitors callback — collect monitor handles and device info."""
    del hdcMonitor, lprcMonitor, dwData
    info = MONITORINFOEX()
    info.cbSize = ctypes.sizeof(MONITORINFOEX)
    mdata: dict = {"hMonitor": hMonitor}

    user32 = ctypes.windll.user32
    if user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
        mdata["deviceName"] = info.szDevice
        mdata["primary"] = (info.dwFlags & 1) != 0
        mdata["left"] = info.rcMonitor.left
        mdata["top"] = info.rcMonitor.top
        mdata["right"] = info.rcMonitor.right
        mdata["bottom"] = info.rcMonitor.bottom
    else:
        mdata["deviceName"] = "UNKNOWN"
        mdata["primary"] = False
        mdata["left"] = 0
        mdata["top"] = 0
        mdata["right"] = 0
        mdata["bottom"] = 0

    _collected_monitors.append(mdata)
    return True


_monitor_proc = MonitorEnumProc(_enum_callback)  # keep alive to prevent GC


# ============ helpers ============
def _configure_native_functions() -> None:
    """Declare ctypes signatures for the Win32 APIs used by this script."""
    user32 = ctypes.windll.user32
    shcore = ctypes.windll.shcore

    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL

    shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
    shcore.SetProcessDpiAwareness.restype = ctypes.c_long

    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.c_void_p,
        MonitorEnumProc,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL

    user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(MONITORINFOEX),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    user32.EnumDisplaySettingsW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(DEVMODE),
    ]
    user32.EnumDisplaySettingsW.restype = wintypes.BOOL

    shcore.GetDpiForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_uint),
    ]
    shcore.GetDpiForMonitor.restype = ctypes.c_long

    shcore.GetScaleFactorForMonitor.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(ctypes.c_int),
    ]
    shcore.GetScaleFactorForMonitor.restype = ctypes.c_long


def _set_dpi_awareness() -> bool:
    """Try to set the process to per-monitor DPI aware.  Returns True on success."""
    user32 = ctypes.windll.user32
    shcore = ctypes.windll.shcore

    for ctx in (
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE,
    ):
        try:
            if user32.SetProcessDpiAwarenessContext(ctx):
                return True
        except Exception:
            pass

    try:
        hr = shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        if hr == 0:
            return True
    except Exception:
        pass

    return False


def _get_actual_resolution(device_name: str) -> tuple[int, int] | None:
    """Get physical pixel resolution via EnumDisplaySettingsW.

    Returns ``(width, height)`` or None on failure.
    """
    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    user32 = ctypes.windll.user32
    ok = user32.EnumDisplaySettingsW(
        device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm),
    )
    if ok:
        return (dm.dmPelsWidth, dm.dmPelsHeight)
    return None


def _get_dpi_scale(hMonitor: wintypes.HMONITOR) -> float:
    """Get the DPI scale factor for *hMonitor*.

    Tries GetDpiForMonitor first; if the returned DPI is 96 (possibly
    virtualized), falls back to GetScaleFactorForMonitor.  Returns 1.0 if
    both fail.
    """
    shcore = ctypes.windll.shcore

    dpi_x = ctypes.c_uint()
    dpi_y = ctypes.c_uint()
    dpi_scale: float | None = None

    hr = shcore.GetDpiForMonitor(
        hMonitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y),
    )
    if hr == 0 and dpi_x.value > 0:
        dpi_scale = dpi_x.value / 96.0

    factor = ctypes.c_int()
    factor_scale: float | None = None
    hr2 = shcore.GetScaleFactorForMonitor(hMonitor, ctypes.byref(factor))
    if hr2 == 0 and factor.value > 0:
        factor_scale = factor.value / 100.0

    # Prefer DPI unless it's virtualized (96 = 100%)
    if dpi_scale is not None and abs(dpi_scale - 1.0) > 0.001:
        return dpi_scale
    if factor_scale is not None:
        return factor_scale
    if dpi_scale is not None:
        return dpi_scale
    return 1.0


def _extract_display_index(device_name: str, fallback: int) -> int:
    """Extract the display number from a device name like ``\\\\.\\DISPLAY1``."""
    import re
    m = re.search(r"DISPLAY(\d+)", device_name)
    if m:
        return int(m.group(1))
    return fallback


# ============ main ============
def main() -> int:
    # ── help text ──────────────────────────────────────────
    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
{FLYellow}SHOW SCREEN RESOLUTION{CRst}
=======================

Usage:
  python {script_name}
  python {script_name} --help

{FLYellow}Description:{CRst}
  Displays detailed information about all connected monitors:
    - Actual (physical pixel) resolution via EnumDisplaySettings
    - DPI scale ratio and percentage
    - Effective resolution (actual / scale)
    - Monitor device name, position, and primary status

  Uses Windows native APIs (EnumDisplayMonitors, GetMonitorInfo,
  EnumDisplaySettings, GetDpiForMonitor) to report accurate values
  regardless of DPI virtualization.

{FLYellow}Requirements:{CRst}
  Windows only.  No third-party packages required.
""")
        return 0

    Console.print_banner("SHOW SCREEN RESOLUTION")

    _configure_native_functions()

    # ── set DPI awareness ─────────────────────────────────
    if not _set_dpi_awareness():
        print(
            f"{FLYellow}Warning: Could not set per-monitor DPI awareness. "
            f"DPI values may be affected by virtualization.{CRst}\n"
        )

    # ── enumerate monitors ────────────────────────────────
    user32 = ctypes.windll.user32
    _collected_monitors.clear()
    user32.EnumDisplayMonitors(None, None, _monitor_proc, 0)

    if not _collected_monitors:
        Console.print_error_and_exit("No monitors detected.")

    # ── gather per-monitor data ───────────────────────────
    rows: list[dict] = []

    for i, m in enumerate(_collected_monitors):
        device_name: str = m["deviceName"]
        display_index = _extract_display_index(device_name, i + 1)

        # Physical resolution
        actual_res = _get_actual_resolution(device_name)
        if actual_res is None:
            # Fallback: use monitor rect dimensions
            actual_width = int(m["right"]) - int(m["left"])
            actual_height = int(m["bottom"]) - int(m["top"])
        else:
            actual_width, actual_height = actual_res

        # DPI scale
        scale = _get_dpi_scale(m["hMonitor"])
        scale_pct = round(scale * 100)

        # Effective resolution
        effective_width = round(actual_width / scale)
        effective_height = round(actual_height / scale)

        rows.append({
            "index":    display_index,
            "actual":   f"{actual_width}x{actual_height}",
            "scale":    f"{scale:.4f}",
            "scale_pct": f"{scale_pct}%",
            "effective": f"{effective_width}x{effective_height}",
            "device":   device_name,
            "primary":  "Yes" if m["primary"] else "",
        })

    rows.sort(key=lambda r: r["index"])

    # ── print table ───────────────────────────────────────
    # Column widths
    idx_w = 5
    act_w = max(max(len(r["actual"]) for r in rows), 17)
    sc_w  = max(max(len(r["scale"]) for r in rows), 10)
    pct_w = max(max(len(r["scale_pct"]) for r in rows), 6)
    eff_w = max(max(len(r["effective"]) for r in rows), 19)
    dev_w = max(max(len(r["device"]) for r in rows), 17)

    # Header
    header = (
        f"{'Idx':>{idx_w}}  "
        f"{'ActualResolution':>{act_w}}  "
        f"{'ScaleRatio':>{sc_w}}  "
        f"{'Scale%':>{pct_w}}  "
        f"{'EffectiveResolution':>{eff_w}}  "
        f"{'DeviceName':<{dev_w}}  "
        f"{'Primary':<7}"
    )
    sep = "-" * len(header)
    print(f"\n{FLCyan}{header}{CRst}")
    print(f"{FGray}{sep}{CRst}")

    for r in rows:
        primary_marker = f"{FLGreen}Yes{CRst}" if r["primary"] else ""
        print(
            f"{FLYellow}{r['index']:>{idx_w}}{CRst}  "
            f"{r['actual']:>{act_w}}  "
            f"{r['scale']:>{sc_w}}  "
            f"{r['scale_pct']:>{pct_w}}  "
            f"{r['effective']:>{eff_w}}  "
            f"{FGray}{r['device']:<{dev_w}}{CRst}  "
            f"{primary_marker:<7}"
        )

    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
