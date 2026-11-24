"""Console formatting and visible device/window state.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from threading import Lock
from typing import Literal, NamedTuple, TextIO

from utils import *
from .models import GesturePhase, InputDevice
from . import backend
_last_win_key: tuple[int, str] = (-1, "")
PRESS_COLOR = FLYellow
RELEASE_COLOR = FLGreen
_DIR_PREFIX = f"{FGray}dir={CRst}"
_SCROLL_ARROWS = {
    "up+left": "↖", "up": "↑", "up+right": "↗",
    "left": "←", "none": "-", "right": "→",
    "down+left": "↙", "down": "↓", "down+right": "↘",
}
_output_lock = Lock()
_sgr = re.compile(r"\x1b\[[0-9;]*m")
_GestureKind = Literal["scroll", "rotate", "magnify", "pressure"]


class _GestureLine(NamedTuple):
    kind: _GestureKind
    direction: str | None
    stream: TextIO
    columns: int
    rows: int


_last_gesture: _GestureLine | None = None


def _write_record(
    line: str, *, kind: _GestureKind | None = None, direction: str | None = None,
    replaces: _GestureKind | None = None,
) -> None:
    """Redraw adjacent samples with matching kind and direction on the same terminal."""
    global _last_gesture
    with _output_lock:
        stream = sys.stdout
        previous = _last_gesture
        _last_gesture = None
        redraw_kind = replaces or kind
        if redraw_kind is not None and Console.enable_ansi_output(stream):
            columns = max(1, Console.get_terminal_width())
            prefix = ""
            if (previous and previous.kind == redraw_kind and previous.direction == direction
                    and previous.stream is stream and previous.columns == columns):
                prefix = f"{Cursor.prev_line(previous.rows)}{CEraseDisplayToEnd}"
            print(f"{prefix}{line}", file=stream, flush=True)
            if kind is not None:
                width = Console.display_width(_sgr.sub("", line))
                rows = max(1, (width + columns - 1) // columns)
                _last_gesture = _GestureLine(kind, direction, stream, columns, rows)
        else:
            print(line, file=stream)


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
    _write_record(
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


def _format_event(kind: str, arrow: str, detail: str, extra: str = "", *, arrow_color: str = FLCyan) -> str:
    ts = f"{FGray}{Console.get_time_str()}{CRst}"
    kind_color = FLCyan if kind == "KBD" else FLMagenta
    kind_label = f"{kind_color}[{kind}{_device_idx(kind)}]{CRst}"
    a = f"{arrow_color}{arrow}{CRst}"
    d = f"{FLWhite}{detail}{CRst}"
    ext = f" {FGray}{extra}{CRst}" if extra else ""
    return f"{ts} {kind_label} {a} {d}{ext}"


def _print_mouse(x: int, y: int, btn_name: str, pressed: bool, *, pressure: float | None = None) -> None:
    arrow = "↓" if pressed else "↑"
    if sys.platform == "linux":
        btn_name = {"button8": "back", "button9": "forward"}.get(btn_name, btn_name)
    if btn_name.startswith("button"):
        btn_name = f"x{btn_name}"
    extra = f"({x}, {y})"
    if pressure is not None:
        label = "pressure" if pressed else "max pressure"
        extra += f" {label}={pressure:.3f}"
    line = _format_event("MOU", arrow, f"mouse_{btn_name}", extra, arrow_color=PRESS_COLOR if pressed else RELEASE_COLOR)
    _write_record(line, replaces="pressure" if pressure is not None else None)


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
    if display_dy:
        directions.append("up" if display_dy > 0 else "down")
    if right_delta:
        directions.append("right" if right_delta > 0 else "left")
    direction = "+".join(directions) or "none"
    line = _format_event("MOU", _SCROLL_ARROWS[direction], f"scroll ({display_dx:g}, {display_dy:g})")
    _write_record(f"{line} {_DIR_PREFIX}{FCyan}{direction}{CRst}",
                  kind="scroll" if directions else None, direction=direction)


def _print_magnify(delta: float, phase: GesturePhase) -> None:
    """Print signed magnification and cyan direction/phase, including gesture edges."""
    direction = "zoom in" if delta > 0 else "zoom out" if delta < 0 else ""
    arrow = "+" if delta > 0 else "-" if delta < 0 else "="
    _print_gesture("magnify", arrow, f"magnify ({delta:+g})", phase, direction=direction)


def _print_rotate(degrees: float, phase: GesturePhase) -> None:
    direction = "counterclockwise" if degrees > 0 else "clockwise" if degrees < 0 else ""
    arrow = "↺" if degrees > 0 else "↻" if degrees < 0 else "="
    _print_gesture("rotate", arrow, f"rotate ({degrees:+g}°)", phase, direction=direction)


def _print_pressure(pressure: float, stage: int, phase: GesturePhase) -> None:
    label = "force click" if stage == 2 else ""
    _print_gesture("pressure", "•", f"pressure={pressure:.3f} stage={stage}", phase, label=label)


def _print_gesture(
    kind: _GestureKind, arrow: str, detail: str, phase: GesturePhase, *, direction: str = "", label: str = "",
) -> None:
    phase_name = phase.name.lower() if phase.name is not None else f"0x{int(phase):x}"
    line = _format_event("MOU", arrow, detail)
    if direction:
        line += f" {_DIR_PREFIX}{FCyan}{direction}{CRst}"
    elif label:
        line += f" {FCyan}{label}{CRst}"
    _write_record(f"{line} {FGray}phase={CRst}{FCyan}{phase_name}{CRst}",
                  kind=kind if direction or kind == "pressure" else None, direction=direction or None)


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
    _write_record(_format_event("KBD", arrow, key_name, source, arrow_color=PRESS_COLOR if pressed else RELEASE_COLOR))
