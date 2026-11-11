"""System event viewer: app implementation."""

from __future__ import annotations

import sys
from utils import CRst, FLRed, System
from .ui import _launch_gui


def main() -> int:
    """Launch the GUI, returning nonzero for missing requirements.

    Prints English diagnostics and opens a GUI. The GUI reads
    system logs, saves display preferences and writes only user-requested exports.
    Ctrl+C propagates to the module-level handler.
    """
    if sys.platform not in ("darwin", "win32", "linux"):
        print(f"{FLRed}Unsupported platform: {sys.platform}{CRst}", file=sys.stderr)
        return 1
    if System.is_headless():
        print(f"{FLRed}This version requires a graphical desktop.{CRst}", file=sys.stderr)
        return 1
    try:
        return _launch_gui()
    except ImportError as exc:
        print(f"{FLRed}GUI dependency unavailable: {exc}. Install PySide6 in this Python environment.{CRst}", file=sys.stderr)
        return 1

