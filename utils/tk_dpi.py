"""Per-window Tk fonts and Windows per-monitor DPI changes, without eager Tk imports."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter.font import Font
    from ._win_subclass import WindowSubclass


class TkDpi:
    """Track a toplevel's logical-to-pixel scale and notify its layout callback.

    Call System.enable_dpi_awareness() before creating Tk on Windows. Construct
    on the GUI thread, build widgets using font()/pixels(), then call start().
    The callback must recompute pixel dimensions from logical values; it must
    not recreate widgets, change text/selection, or run a nested event loop.
    """

    def __init__(self, root: tk.Tk | tk.Toplevel) -> None:
        self.root = root
        self._fonts: dict[str, tuple[Font, int]] = {}
        self._handler: Callable[[float], None] | None = None
        self._hook: WindowSubclass | None = None
        self._job: str | None = None
        self._closed = False
        self._spacing: list[tuple[tk.Misc, str, dict[str, tuple[int, ...]]]] = []
        self._window_system = str(root.tk.call("tk", "windowingsystem"))
        if sys.platform == "win32":
            import ctypes as ct
            from ctypes import wintypes as wt

            self._ct = ct
            self._rect_type = wt.RECT
            self._user32 = ct.WinDLL("user32", use_last_error=True)
            self._user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
            self._user32.GetAncestor.restype = wt.HWND
            self._user32.GetDpiForWindow.argtypes = [wt.HWND]
            self._user32.GetDpiForWindow.restype = wt.UINT
            self._user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ct.c_int, ct.c_int,
                                                ct.c_int, ct.c_int, wt.UINT]
            self._user32.SetWindowPos.restype = wt.BOOL
            # DPI messages target Tk's outer decorated HWND, not its client HWND.
            root.update_idletasks()  # Tk creates the decorated wrapper lazily.
            self._hwnd = self._user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
            dpi = self._user32.GetDpiForWindow(self._hwnd)
            self.scale = (dpi or 96) / 96
        else:
            self.scale = self._desktop_scale()
        root.bind("<Destroy>", self._on_destroy, add=True)

    def _desktop_scale(self) -> float:
        # Cocoa window coordinates already use logical points, including Retina.
        if self._window_system == "aqua":
            return 1.0
        return float(self.root.tk.call("tk", "scaling")) * 72 / 96

    def pixels(self, logical: float) -> int:
        """Convert a dimension expressed at 96 DPI into current window pixels."""
        return round(logical * self.scale)

    def font(self, name: str = "TkDefaultFont") -> Font:
        """Return an owned named-font copy; never modify another window's fonts."""
        from tkinter import font

        if name not in self._fonts:
            source = font.nametofont(name, root=self.root)
            result = font.Font(root=self.root, **source.actual())
            size = int(source.cget("size"))
            # Named point sizes are logical; negative sizes are already pixels.
            logical_size = round(size * 96 / 72) if size > 0 else round(-size / self.scale)
            self._fonts[name] = result, logical_size
            if self._window_system != "aqua":
                result.configure(size=-max(1, self.pixels(logical_size)))
        return self._fonts[name][0]

    def start(self, on_change: Callable[[float], None]) -> None:
        """Apply the initial layout and start automatic DPI tracking once."""
        if self._handler is not None:
            raise RuntimeError("DPI tracking is already started")
        self._handler = on_change
        self._apply_spacing()
        on_change(self.scale)
        if sys.platform == "win32":
            from ._win_subclass import WindowSubclass

            self._hook = WindowSubclass(self._hwnd, self._window_message,
                                        self.root._root().report_callback_exception)
            # Mapping a window initially on another monitor can change its DPI.
            self.root.bind("<Map>", self._on_map, add=True)
        elif self._window_system != "aqua":
            self._poll_desktop_scale()

    def track_spacing(self) -> None:
        """Capture unscaled widget/layout padding once, after building the UI.

        Captures grid/pack padding and explicit widget padding/wrap lengths;
        dimensions measured in characters (Text/Entry width, etc.) stay intact.
        Application-specific sizes, table columns and styles belong in on_change.
        """
        if self._handler is not None:
            raise RuntimeError("Capture logical spacing before starting DPI tracking")
        self._spacing.clear()
        pending = list(self.root.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            options = set(widget.keys())
            names = {"padding", "padx", "pady", "wraplength", "insertwidth", "borderwidth", "highlightthickness"}
            if widget.winfo_class() == "Scrollbar":
                names.add("width")
            modes = [("configure", {name: widget.cget(name) for name in names & options})]
            manager = widget.winfo_manager()
            if manager in ("grid", "pack"):
                # ScrolledText proxies Python layout methods to its outer frame;
                # query the actual widget path so both frame and text are covered.
                info = widget.tk.splitlist(widget.tk.call(manager, "info", widget._w))
                values = dict(zip(info[::2], info[1::2]))
                modes.append((manager, {key: values[f"-{key}"] for key in
                                        ("padx", "pady", "ipadx", "ipady") if f"-{key}" in values}))
            for mode, values in modes:
                dimensions = {}
                for name, value in values.items():
                    parts = value if isinstance(value, tuple) else widget.tk.splitlist(str(value))
                    if parts:
                        dimensions[name] = tuple(widget.winfo_pixels(str(part)) for part in parts)
                if dimensions:
                    self._spacing.append((widget, mode, dimensions))

    def _apply_spacing(self) -> None:
        for widget, mode, values in self._spacing:
            options: list[object] = []
            for name, sizes in values.items():
                scaled = tuple(self.pixels(size) for size in sizes)
                options.extend((f"-{name}", scaled[0] if len(scaled) == 1 else scaled))
            if mode == "configure":
                widget.tk.call(widget._w, "configure", *options)
            else:
                widget.tk.call(mode, "configure", widget._w, *options)

    def _apply_scale(self, scale: float) -> None:
        if not math.isfinite(scale) or scale <= 0 or math.isclose(scale, self.scale, abs_tol=0.005):
            return
        self.scale = scale
        for value, logical_size in self._fonts.values():
            if self._window_system != "aqua":
                value.configure(size=-max(1, self.pixels(logical_size)))
        self._apply_spacing()
        if self._handler is not None:
            self._handler(scale)

    def _window_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        if message != 0x02E0:  # WM_DPICHANGED
            return None
        dpi = wparam & 0xFFFF
        if not dpi or not lparam:
            return None
        # Copy the borrowed RECT before calling Tk/layout code.
        rect = self._ct.cast(lparam, self._ct.POINTER(self._rect_type)).contents
        x, y, width, height = rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        self._apply_scale(dpi / 96)
        if not self._user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0014):
            raise self._ct.WinError(self._ct.get_last_error())
        return 0  # SWP_NOZORDER | SWP_NOACTIVATE; let Tk receive normal size events.

    def _on_map(self, event: tk.Event) -> None:
        if event.widget is self.root:
            hwnd = self._user32.GetAncestor(self.root.winfo_id(), 2)
            if hwnd != self._hwnd:
                from ._win_subclass import WindowSubclass

                if self._hook is not None:
                    self._hook.close()
                self._hwnd = hwnd
                self._hook = WindowSubclass(hwnd, self._window_message,
                                            self.root._root().report_callback_exception)
            dpi = self._user32.GetDpiForWindow(self._hwnd)
            if dpi:
                self._apply_scale(dpi / 96)

    def _poll_desktop_scale(self) -> None:
        if not self._closed:
            old = self.scale
            width, height = self.root.winfo_width(), self.root.winfo_height()
            self._apply_scale(self._desktop_scale())
            if old != self.scale and self.root.state() == "normal":
                self.root.geometry(f"{round(width * self.scale / old)}x{round(height * self.scale / old)}")
            self._job = self.root.after(500, self._poll_desktop_scale)

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self.close()

    def close(self) -> None:
        """Cancel monitoring and release the native callback before destruction."""
        self._closed = True
        if self._job is not None:
            self.root.after_cancel(self._job)
            self._job = None
        if self._hook is not None:
            self._hook.close()
