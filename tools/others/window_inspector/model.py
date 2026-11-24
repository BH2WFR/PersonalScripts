"""Window identities, search semantics and process inspection shared by both desktops."""

import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import psutil


type Rect = tuple[int, int, int, int]  # x, y, width, height in native desktop coordinates
type Rows = list[tuple[str, ...]]
MIN_OPACITY_PERCENT = 30
INITIAL_HINT = "Click Refresh List to load windows, or drag the finder onto a window."
LOADED_HINT = "Select a window, refresh the list, or drag the finder onto a window."
CONTROLS_HINT = "Click Read Controls to list the selected window's controls."


class PropertyGroup(StrEnum):
    """Display order for sections in the window and process property tree."""

    WINDOW = "Window"
    PROCESS = "Process"
    GEOMETRY = "Geometry and display"
    STYLES = "Window styles"
    PARENT = "Parent window"
    RESOURCES = "Resource usage"
    BUNDLE = "Application bundle"
    FILE = "Executable file"


type Properties = list[tuple[PropertyGroup, str, str]]


@dataclass(frozen=True)
class Window:
    """A top-level window. Its caption may change without changing identity."""

    id: int
    pid: int
    title: str = field(compare=False)
    kind: str = field(compare=False)
    ax_window: Any = field(default=None, compare=False, repr=False)

    @property
    def label(self) -> str:
        if sys.platform == "darwin":
            return f"PID:{self.pid}, {self.kind}" + (f" — {self.title}" if self.title else "")
        return f"ID:0x{self.id:08X}, {self.title or self.kind}"


@dataclass
class Snapshot:
    window: Window
    rows: Properties
    opacity: int = 100
    topmost: bool = False
    through: bool = False
    paths: dict[str, str] = field(default_factory=dict)


class Backend(Protocol):
    def windows(self, hidden: bool) -> list[Window]: ...
    def foreground(self) -> Window | None: ...
    def at_pointer(self) -> Window | None: ...
    def checked(self, target: Window) -> Window: ...
    def snapshot(self, target: Window) -> Snapshot: ...
    def frame(self, target: Window) -> tuple[Rect, int]: ...
    def controls(self, target: Window) -> Rows: ...
    def enable_controls(self, target: Window) -> tuple[int, int]: ...
    def enable_menu(self, target: Window) -> tuple[int, int]: ...
    def show_controls(self, target: Window) -> tuple[int, int]: ...
    def act(self, target: Window, action: str, value: int = 0) -> None: ...
    def file_action(self, path: str, properties: bool) -> None: ...


def find_window(entries: Iterable[Window], query: str) -> Window | None:
    """Resolve explicit ID/PID selectors exactly, otherwise match text in Z order."""
    query = query.strip().casefold()
    if not query:
        return None
    number = re.fullmatch(r"(?:(id\s*[:：]|ahk_id\s+|pid\s*[:：]|ahk_pid\s+)\s*)?(0x[\da-f]+|\d+)(?:,.*)?", query)
    if number:
        prefix, raw = number.groups()
        value = int(raw, 16 if raw.startswith("0x") else 10)
        by_pid = "pid" in (prefix or "")
        if sys.platform == "darwin" and prefix is None and raw.isdecimal():
            items = list(entries)
            return next((w for w in items if w.pid == value), None) or next((w for w in items if w.id == value), None)
        return next((w for w in entries if (w.pid if by_pid else w.id) == value), None)
    names: dict[int, str] = {}
    for w in entries:
        if query.startswith("ahk_class "):
            if w.kind.casefold() == query[10:].strip():
                return w
            continue
        if query in w.title.casefold() or query in w.kind.casefold():
            return w
        if w.pid not in names:
            try:
                names[w.pid] = psutil.Process(w.pid).name().casefold()
            except psutil.Error:
                names[w.pid] = ""
        if query.removeprefix("ahk_exe ") in names[w.pid]:
            return w
    return None


@dataclass
class ProcessInfo:
    name: str
    path: str
    command: str
    priority: int | None
    rows: Properties
    arguments: list[str] = field(default_factory=list)


def process_info(process: psutil.Process) -> ProcessInfo:
    """Keep available fields even when the OS denies access to individual details."""
    attrs = ["name", "exe", "cmdline", "ppid", "username", "create_time", "memory_info", "nice", "num_threads"]
    if sys.platform == "darwin":
        attrs.extend(("cpu_times", "cwd"))
    data = process.as_dict(attrs=attrs, ad_value=None)
    args = data["cmdline"] or []
    command = subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)

    def timestamp(seconds: float) -> str:
        return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")

    rows: Properties = [
        (PropertyGroup.PROCESS, "Parent PID", str(data["ppid"] or "")),
        (PropertyGroup.PROCESS, "User", data["username"] or ""),
        (PropertyGroup.PROCESS, "Process started", timestamp(data["create_time"]) if data["create_time"] else ""),
        (PropertyGroup.RESOURCES, "Threads", str(data["num_threads"] or "")),
    ]
    if memory := data["memory_info"]:
        rows.extend([(PropertyGroup.RESOURCES, "Resident memory", f"{memory.rss / 2**20:.2f} MiB"),
                     (PropertyGroup.RESOURCES, "Virtual memory", f"{memory.vms / 2**20:.2f} MiB")])
    path = data["exe"] or ""
    if sys.platform == "darwin":
        rows.append((PropertyGroup.PROCESS, "Working directory", data["cwd"] or "Unavailable"))
        if times := data["cpu_times"]:
            rows.append((PropertyGroup.RESOURCES, "CPU time", f"{times.user + times.system:.2f} s"))
        if data["cmdline"] is None:
            rows.append((PropertyGroup.PROCESS, "Argument access", "Permission denied"))
    if sys.platform == "win32":
        from .windows import process_rows
        rows.extend(process_rows(process.pid, path))
    if path:
        try:
            stat = Path(path).stat()
            rows.append((PropertyGroup.FILE, "File modified", timestamp(stat.st_mtime)))
            if hasattr(stat, "st_birthtime"):
                rows.append((PropertyGroup.FILE, "File created", timestamp(stat.st_birthtime)))
        except OSError:
            pass
    return ProcessInfo(data["name"] or "", path, command, data["nice"], rows, args)


@dataclass(frozen=True)
class RestartPlan:
    executable: str
    arguments: tuple[str, ...]
    cwd: str
    environment: dict[str, str] = field(repr=False)


def _check_process(process: psutil.Process) -> None:
    if process.pid <= 1 or process.pid == os.getpid() or not process.is_running():
        raise RuntimeError("The process has exited or cannot be managed.")


def prepare_restart(process: psutil.Process) -> RestartPlan:
    """Capture everything needed for relaunch before asking for confirmation."""
    _check_process(process)
    current = psutil.Process()
    if process.username() != current.username():
        raise RuntimeError("Restart requires the same user account as the selected process.")
    if sys.platform == "win32":
        from .windows import elevated
        target_elevation = elevated(process.pid)
        if target_elevation is None or target_elevation != elevated(current.pid):
            raise RuntimeError("Restart requires the inspector and the process to have the same elevation level.")
    executable, args, cwd, env = process.exe(), process.cmdline(), process.cwd(), process.environ()
    if not args or not os.access(executable, os.X_OK) or not os.path.isdir(cwd):
        raise RuntimeError("Could not reconstruct the original launch command.")
    return RestartPlan(executable, tuple(args), cwd, env)


def end_process(process: psutil.Process, restart: bool, plan: RestartPlan | None = None) -> None:
    """Act only on the captured process, and verify any previously reviewed launch plan."""
    _check_process(process)
    if not restart:
        process.kill()
        process.wait(timeout=5)
        return
    current = prepare_restart(process)
    if plan is not None and plan != current:
        raise RuntimeError("The launch details changed. Review the process and confirm again.")
    process.terminate()
    process.wait(timeout=5)
    try:
        subprocess.Popen(current.arguments, executable=current.executable, cwd=current.cwd,
                         env=current.environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=os.name == "posix")
    except OSError as exc:
        raise RuntimeError(f"The original process exited, but the restart failed: {exc}") from exc
