"""Tk presentation of the Windows reference keyboard."""

from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox

from utils import System, TkDpi
from .layout import DEFAULT_SIZE, EXTRA_HEIGHT, EXTENDED_KEYS, MINIMUM_SIZE, NUMPAD_KEYS, ROWS, TOOLBAR, frames, panel_width
from .state import KeyboardState, WindowLayout, hover_color
from .window import NonactivatingWindow
from .windows import WindowsOutput


class ScreenKeyboard:
    def __init__(self) -> None:
        System.enable_dpi_awareness()
        self.window = root = tk.Tk()
        root.withdraw()
        root.title("屏幕键盘 — Custom Autohotkey Config")
        root.configure(background="#f1f3f5")
        self.dpi = TkDpi(root)
        self.closing = False
        self.timer: str | None = None
        self.poll: str | None = None
        self.signature = None
        self.buttons: dict[str, tk.Label] = {}
        self.hovered: set[str] = set()
        self.labels = {name: label for row in ROWS for name, label, _ in row}
        self.labels.update(EXTENDED_KEYS)
        self.labels.update((name, label) for name, label, *_ in NUMPAD_KEYS)
        self.actions = {"extended": self.toggle_extended, "numpad": self.toggle_numpad,
                        "reset": lambda: self.state.reset(), "redraw": self.redraw, "size": self.reset_size,
                        "settings": self.popup}
        self.state = KeyboardState(WindowsOutput(),
                                   self.schedule, self.cancel, self.refresh)
        saved = self.state.window_layout
        self.expanded, self.numpad = saved.expanded, saved.numpad
        self.status = tk.Label(root, anchor="w", background="#f1f3f5", foreground="#505760")
        for name, label in [*TOOLBAR, *self.labels.items()]:
            toolbar = name in self.actions
            button = tk.Label(root, text=label, cursor="hand2" if toolbar else "arrow", borderwidth=0,
                              highlightthickness=int(not toolbar or name in {"extended", "numpad"}),
                              highlightcolor="#c1c9ce", highlightbackground="#c1c9ce")
            if toolbar:
                button.bind("<ButtonRelease-1>", lambda e, n=name: self.perform(self.actions[n]))
            else:
                button.bind("<ButtonPress-1>", lambda e, n=name: self.perform(lambda: self.state.press(n)))
            button.bind("<Enter>", lambda e, n=name: self.hover(n, True))
            button.bind("<Leave>", lambda e, n=name: self.hover(n, False))
            button.bind("<Unmap>", lambda e, n=name: self.hover(n, False))
            self.buttons[name] = button
        self.selection = tk.BooleanVar(root, self.state.adapted)
        self.menu = tk.Menu(root, tearoff=False)
        for enabled, label in ((False, "左侧键：CapsLock（默认）"),
                               (True, "左侧键：Layer（适配 custom-autohotkey-config）")):
            self.menu.add_radiobutton(label=label, variable=self.selection, value=int(enabled),
                                      command=lambda: self.perform(lambda: self.state.set_adapted(self.selection.get())))
        self.buttons["Layer"].bind("<Button-3>", self.popup)
        self.status.bind("<Button-3>", self.popup)
        root.bind("<ButtonRelease-1>", lambda e: self.perform(self.state.release))
        root.bind("<Configure>", lambda e: self.layout() if e.widget is root else None)
        self.dpi.start(lambda scale: self.rescaled())
        self.native = NonactivatingWindow(root, self.finish_resize)
        self.layout()
        root.bind("<Unmap>", self.unmapped)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        # Resolve the cursor monitor's DPI before converting the stored logical size.
        self.native.place_near_cursor()
        self.resize(saved.width, saved.height, logical=True)
        self.native.show()
        self.poll_locks()

    def popup(self, event: tk.Event | None = None) -> None:
        button = self.buttons["settings"]
        x, y = ((event.x_root, event.y_root) if event else
                (button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()))
        self.selection.set(self.state.adapted)
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def perform(self, action: Callable[[], object]) -> None:
        try:
            action()
        except Exception as exc:
            try:
                self.state.reset()
            finally:
                messagebox.showerror("屏幕键盘", str(exc), parent=self.window)

    def schedule(self, milliseconds: int, callback: Callable[[], None]) -> None:
        self.cancel()
        self.timer = self.window.after(milliseconds, lambda: self.perform(callback))

    def cancel(self) -> None:
        if self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None

    def unmapped(self, event: tk.Event) -> None:
        if event.widget is self.window and not self.closing:
            self.perform(self.state.reset)

    def paint(self, name: str) -> None:
        if name in self.actions:
            active = (name == "extended" and self.expanded) or (name == "numpad" and self.numpad)
            bg, fg = ("#34657c", "white") if active else ("#f1f3f5", "#202124")
        else:
            bg, fg = self.state.colors(name)
        self.buttons[name].configure(background=hover_color(bg) if name in self.hovered else bg, foreground=fg)

    def hover(self, name: str, entered: bool) -> None:
        if entered:
            self.hovered.add(name)
        else:
            self.hovered.discard(name)
        self.paint(name)

    def refresh(self) -> None:
        if getattr(self, "native", None) and self.native.is_resizing:
            return
        self.status.configure(text=self.state.status())
        for name in self.buttons:
            self.paint(name)
            if name in self.labels:
                self.buttons[name].configure(text=self.state.label(name, self.labels[name]))

    def poll_locks(self) -> None:
        if self.state.held:
            self.perform(self.state.check_target)
        current = self.state.output.locks()
        if self.state.lock_states != current:
            self.state.lock_states = current
            self.refresh()
        self.poll = self.window.after(250, self.poll_locks)

    def layout(self) -> None:
        if getattr(self, "native", None) and self.native.is_resizing:
            return
        width, height = self.window.winfo_width(), self.window.winfo_height()
        signature = (width, height, self.dpi.scale, self.expanded, self.numpad)
        if self.signature == signature:
            return
        self.signature = signature
        bounds = frames(*signature, mac=False)
        unit = (width - 2 * self.dpi.pixels(4) + self.dpi.pixels(3)) / (20 if self.numpad else 16)
        key_size = 8 if unit * 16 < self.dpi.pixels(600) else 9
        main = {n for row in ROWS for n, _, _ in row}
        for name, widget in {"status": self.status, **self.buttons}.items():
            if name not in bounds:
                widget.place_forget()
                continue
            x, y, w, h = bounds[name]
            points = key_size if name in main else 8
            family = "Microsoft YaHei UI" if name in self.actions or name in {"status", "language"} else "Segoe UI"
            widget.configure(font=(family, -self.dpi.pixels(points * 96 / 72)))
            widget.place(x=x, y=y, width=w, height=h)

    def rescaled(self) -> None:
        if getattr(self, "native", None) and self.native.is_resizing:
            return
        self.window.minsize(self.dpi.pixels(MINIMUM_SIZE[0] * (1.25 if self.numpad else 1)),
                            self.dpi.pixels(MINIMUM_SIZE[1] + EXTRA_HEIGHT * self.expanded))
        self.layout()
        self.refresh()

    def resize(self, width: int, height: int, *, logical: bool = False) -> None:
        self.rescaled()
        if logical:
            width, height = self.dpi.pixels(width), self.dpi.pixels(height)
        self.window.geometry(f"{width}x{height}")
        self.window.update_idletasks()
        if hasattr(self, "native"):
            min_width, min_height = self.window.minsize()
            self.native.fit_client(max(width, min_width), max(height, min_height))
            self.window.update_idletasks()
        self.layout()

    def toggle_extended(self) -> None:
        self.expanded = not self.expanded
        delta = self.dpi.pixels(EXTRA_HEIGHT) * (1 if self.expanded else -1)
        self.resize(self.window.winfo_width(), self.window.winfo_height() + delta)
        self.save_window()

    def toggle_numpad(self) -> None:
        self.numpad = not self.numpad
        self.resize(panel_width(self.window.winfo_width(), self.numpad, self.dpi.scale), self.window.winfo_height())
        self.save_window()

    def reset_size(self) -> None:
        self.expanded = self.numpad = False
        self.resize(*DEFAULT_SIZE, logical=True)
        self.save_window()

    def save_window(self) -> None:
        scale = self.dpi.scale
        self.state.save_window(WindowLayout(round(self.window.winfo_width() / scale),
                                            round(self.window.winfo_height() / scale), self.expanded, self.numpad))

    def finish_resize(self) -> None:
        self.rescaled()
        self.perform(self.save_window)

    def redraw(self) -> None:
        self.signature = None
        self.state.lock_states = self.state.output.locks()
        self.rescaled()
        self.native.redraw()

    def close(self) -> None:
        self.closing = True
        if self.poll:
            self.window.after_cancel(self.poll)
        try:
            self.perform(self.save_window)
            self.state.reset()
        finally:
            self.native.close()
            self.dpi.close()
            self.window.destroy()


def run() -> int:
    keyboard = ScreenKeyboard()
    try:
        keyboard.window.mainloop()
    finally:
        if not keyboard.closing:
            keyboard.close()
    return 0
