"""Console formatting and visible device/window state.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
from .models import GesturePhase, InputDevice
from . import backend
_last_win_key: tuple[int, str] = (-1, "")


def _check_win_change() -> None:
    """Print a banner when the foreground window changes.

    Called on every keyboard / mouse event.  Compares both PID and window
    title, so tab switches within the same app are also detected.
    """
    global _last_win_key
    try:
        wi = backend.get_foreground_window()
    except Exception:
        return
    key = (wi.pid, wi.title)
    if key == _last_win_key:
        return
    _last_win_key = key
    label = wi.process_name or f"PID:{wi.pid}"
    title = wi.title[:72] + "…" if len(wi.title) > 72 else wi.title
    wnd_class = wi.window_class
    ts = f"{FGray}{Console.get_time_str()}{CRst}"
    cls_str = f"  {FGray}[{FLWhite}{wnd_class}{FGray}]{CRst}" if wnd_class else ""
    print(
        f"{ts} {FLYellow}─── {FLWhite}{CBold}{label}{CRst} "
        f"{FLYellow}({wi.pid}){CRst}{cls_str}  {FLCyan}{title}{CRst}"
    )

_state: dict[str, list[InputDevice]] = {"kbd_devs": [], "mou_devs": []}
_show_event_device = True


def _device_idx(kind: str) -> str:
    devs = _state["kbd_devs"] if kind == "KBD" else _state["mou_devs"]
    n = len(devs)
    if n == 1:
        return f" {devs[0].idx}"
    if n > 1:
        return " ?"
    return ""


def _format_event(kind: str, arrow: str, detail: str, extra: str = "") -> str:
    ts = f"{FGray}{Console.get_time_str()}{CRst}"
    kind_color = FLCyan if kind == "KBD" else FLMagenta
    arrow_color = FLGreen if arrow == "↓" else FLYellow
    kind_label = f"{kind_color}[{kind}{_device_idx(kind)}]{CRst}"
    a = f"{arrow_color}{arrow}{CRst}"
    d = f"{FLWhite}{detail}{CRst}"
    ext = f" {FGray}{extra}{CRst}" if extra else ""
    return f"{ts} {kind_label} {a} {d}{ext}"


def _print_mouse(x: int, y: int, btn_name: str, pressed: bool):
    arrow = "↓" if pressed else "↑"
    print(_format_event("MOU", arrow, btn_name, f"({x}, {y})"))


def _print_scroll(
    dx: int, dy: int, *, raw_delta: tuple[float, float] | None = None,
) -> None:
    """Print one native-value pair and cyan scroll directions on every platform."""
    if raw_delta == (0, 0):
        return  # Gesture phase boundaries can carry no actual movement.
    display_dx, display_dy = raw_delta if raw_delta is not None else (dx, dy)
    # Quartz axis 2 and this viewer's X11 button-6 mapping are left-positive.
    right_delta = -display_dx if sys.platform in ("darwin", "linux") else display_dx
    directions: list[str] = []
    arrows: list[str] = []
    if display_dy:
        directions.append("up" if display_dy > 0 else "down")
        arrows.append("↑" if display_dy > 0 else "↓")
    if right_delta:
        directions.append("right" if right_delta > 0 else "left")
        arrows.append("→" if right_delta > 0 else "←")
    arrow = "".join(arrows) or "-"
    direction = "+".join(directions) or "none"
    line = _format_event("MOU", arrow, f"scroll ({display_dx:g}, {display_dy:g})")
    print(f"{line} {FCyan}{direction}{CRst}")


def _print_magnify(delta: float, phase: GesturePhase) -> None:
    """Print signed magnification and cyan direction/phase, including gesture edges."""
    direction = "zoom in" if delta > 0 else "zoom out" if delta < 0 else ""
    arrow = "+" if delta > 0 else "-" if delta < 0 else "="
    phase_name = phase.name.lower() if phase.name is not None else f"0x{int(phase):x}"
    label = f"{direction} phase={phase_name}".strip()
    line = _format_event("MOU", arrow, f"magnify ({delta:+g})")
    print(f"{line} {FCyan}{label}{CRst}")


def _print_key(
    key_name: str,
    pressed: bool,
    device: "InputDevice | None" = None,
    scan_code: WindowsScanCode | None = None,
) -> None:
    arrow = "↓" if pressed else "↑"
    source = ""
    if device is not None and _show_event_device:
        identity = f"S/N:{device.serial}" if device.serial else f"ID:{device.path}"
        source = f"{device.name}  {identity}" if device.name else identity
    if scan_code is not None:
        source = f"{source}  scan={scan_code}".strip()
    print(_format_event("KBD", arrow, key_name, source))
