"""Linux X11 hooks, input sending and window metadata.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
"""

from __future__ import annotations

from utils import *
import threading
from .models import WindowInfo, EventSink
_OS = sys.platform


def _is_x11_session() -> bool:
    """Return True if running under X11 (not Wayland)."""
    session = os.environ.get("XDG_SESSION_TYPE", "")
    if session:
        return session.lower() == "x11"
    # Fallback: check if DISPLAY is set and X11-specific vars
    if os.environ.get("DISPLAY", ""):
        if os.environ.get("WAYLAND_DISPLAY", ""):
            return False
        return True
    return False

def create_hook(sink: EventSink):
    """X11 hook via XRecord.  Returns object with .start() / .stop()."""
    if _OS != "linux2" and _OS != "linux":
        return None
    if not _is_x11_session():
        # Wayland — not supported yet
        raise NotImplementedError(
            "Wayland is not yet supported. "
            "Please run under X11 or check back for future Wayland support."
        )

    try:
        from Xlib import X, XK, display
        from Xlib.ext import record
        from Xlib.protocol import rq
    except ImportError:
        raise ImportError(
            "python-xlib is required on Linux. "
            "Install with: pip install python-xlib"
        )

    class X11Hook:
        def __init__(self):
            self._ctx = None
            self._display_stop = None
            self._display_record = None
            self._ready = threading.Event()
            self.running = False

        def _key_name(self, event):
            """Extract key name from an X11 KeyPress/KeyRelease event."""
            keysym = event.detail
            try:
                name = XK.keysym_to_string(keysym)
                if name and name.isprintable() and len(name) == 1:
                    return name
                if name:
                    return name.lower()
            except Exception:
                pass
            return f"key({keysym})"

        def _btn_name(self, detail: int) -> str:
            btn_map = {1: "left", 2: "middle", 3: "right",
                       4: "scroll_up", 5: "scroll_down",
                       6: "scroll_left", 7: "scroll_right"}
            if detail in btn_map:
                return btn_map[detail]
            if detail >= 8:
                return f"button{detail}"
            return f"button{detail}"

        def _handler(self, reply):
            if not self.running:
                return
            data = reply.data
            while data:
                event, data = rq.EventField("").parse_binary_value(
                    data, self._display_record.display, 0, None,
                )
                if event is None:
                    continue

                etype = event.type
                if etype == X.KeyPress:
                    sink._emit_key(self._key_name(event), True, event.detail)
                elif etype == X.KeyRelease:
                    sink._emit_key(self._key_name(event), False, event.detail)
                elif etype == X.ButtonPress:
                    detail = event.detail
                    if detail in (4, 5, 6, 7):
                        # scroll events
                        mapping = {4: (0, 1), 5: (0, -1), 6: (1, 0), 7: (-1, 0)}
                        dx, dy = mapping.get(detail, (0, 0))
                        sink._emit_scroll(dx, dy)
                    else:
                        sink._emit_mouse(
                            event.root_x, event.root_y,
                            self._btn_name(detail), True,
                        )
                elif etype == X.ButtonRelease:
                    detail = event.detail
                    if detail not in (4, 5, 6, 7):
                        sink._emit_mouse(
                            event.root_x, event.root_y,
                            self._btn_name(detail), False,
                        )
                # MotionNotify not captured (too noisy)

        def start(self):
            self._display_stop = display.Display()
            self._display_record = display.Display()
            if not self._display_record.has_extension("RECORD"):
                self._ready.set()
                raise OSError("X server does not have RECORD extension")

            self._ctx = self._display_record.record_create_context(
                0, [record.AllClients],
                [record.ClientStarted, record.ClientDied, record.EnableData],
            )

            self._ready.set()
            self.running = True
            self._display_record.record_enable_context(self._ctx, self._handler)
            # record_enable_context blocks until record_disable_context is called

        def stop(self):
            self.running = False
            if self._display_record is not None and self._ctx is not None:
                try:
                    self._display_record.record_disable_context(self._ctx)
                    self._display_record.record_free_context(self._ctx)
                except Exception:
                    pass
            if self._display_stop is not None:
                try:
                    self._display_stop.close()
                except Exception:
                    pass
            if self._display_record is not None:
                try:
                    self._display_record.close()
                except Exception:
                    pass
            self._ctx = None

    return X11Hook()

class _X11Controller:
    """Send keyboard / mouse events via X11 XTest extension."""

    _display = None

    @classmethod
    def _disp(cls):
        if cls._display is None:
            from Xlib.display import Display
            cls._display = Display()
        return cls._display

    def _name_to_keysym(self, name: str) -> int:
        from Xlib import XK
        x11_name = Keyboard.x11_keysym_name(name)
        # Try string_to_keysym
        ks = XK.string_to_keysym(x11_name)
        if ks != 0:
            return ks
        # Try as single character
        if len(name) == 1:
            return XK.string_to_keysym(name)
        return 0

    def press(self, name: str) -> None:
        from Xlib import X
        keysym = self._name_to_keysym(name)
        if keysym:
            keycode = self._disp().keysym_to_keycode(keysym)
            if keycode:
                self._disp().xtest_fake_input(X.KeyPress, keycode)
                self._disp().flush()

    def release(self, name: str) -> None:
        from Xlib import X
        keysym = self._name_to_keysym(name)
        if keysym:
            keycode = self._disp().keysym_to_keycode(keysym)
            if keycode:
                self._disp().xtest_fake_input(X.KeyRelease, keycode)
                self._disp().flush()

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        self._disp().warp_pointer(x, y)
        self._disp().flush()

    def _mouse_btn(self, down: bool, button: str):
        from Xlib import X
        btn_map = {"left": 1, "middle": 2, "right": 3}
        btn = btn_map.get(button, 1)
        ev = X.ButtonPress if down else X.ButtonRelease
        self._disp().xtest_fake_input(ev, btn)
        self._disp().flush()

    def mouse_down(self, button: str = "left") -> None:
        self._mouse_btn(True, button)

    def mouse_up(self, button: str = "left") -> None:
        self._mouse_btn(False, button)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        from Xlib import X
        d = self._disp()
        if dy > 0:
            for _ in range(abs(dy)):
                d.xtest_fake_input(X.ButtonPress, 4)
                d.xtest_fake_input(X.ButtonRelease, 4)
        elif dy < 0:
            for _ in range(abs(dy)):
                d.xtest_fake_input(X.ButtonPress, 5)
                d.xtest_fake_input(X.ButtonRelease, 5)
        if dx > 0:
            for _ in range(abs(dx)):
                d.xtest_fake_input(X.ButtonPress, 6)
                d.xtest_fake_input(X.ButtonRelease, 6)
        elif dx < 0:
            for _ in range(abs(dx)):
                d.xtest_fake_input(X.ButtonPress, 7)
                d.xtest_fake_input(X.ButtonRelease, 7)
        d.flush()

    def set_modifier(self, name: str, on: bool) -> None:
        self.press(name) if on else self.release(name)

def _get_foreground_window_x11() -> WindowInfo:
    try:
        from Xlib.display import Display
        from Xlib import X
        d = Display()
        root = d.screen().root

        # Get _NET_ACTIVE_WINDOW
        net_active = d.get_atom("_NET_ACTIVE_WINDOW", only_if_exists=True)
        if net_active is None:
            return WindowInfo()
        active_prop = root.get_full_property(net_active, X.AnyPropertyType)
        if active_prop is None:
            return WindowInfo()
        win_id = active_prop.value[0]

        win = d.create_resource_object("window", win_id)

        # Window title
        net_name = d.get_atom("_NET_WM_NAME", only_if_exists=True)
        wm_name = d.get_atom("WM_NAME", only_if_exists=True)
        title = ""
        for atom in (net_name, wm_name):
            if atom is None:
                continue
            prop = win.get_full_property(atom, X.AnyPropertyType)
            if prop and prop.value:
                title = prop.value.decode("utf-8", errors="replace") if isinstance(prop.value, bytes) else str(prop.value)
                break

        # PID
        net_pid = d.get_atom("_NET_WM_PID", only_if_exists=True)
        pid = 0
        proc_name = ""
        if net_pid is not None:
            pid_prop = win.get_full_property(net_pid, X.AnyPropertyType)
            if pid_prop and pid_prop.value:
                pid = pid_prop.value[0]
                try:
                    proc_name = os.readlink(f"/proc/{pid}/exe").rsplit("/", 1)[-1]
                except Exception:
                    pass

        # Window class
        wnd_class = ""
        try:
            cls_hint = win.get_wm_class()
            if cls_hint:
                wnd_class = cls_hint[1] if cls_hint[1] else cls_hint[0]
        except Exception:
            pass

        d.close()
        return WindowInfo(
            pid=pid, process_name=proc_name, title=title,
            window_class=wnd_class, bundle_id="",
        )
    except Exception:
        return WindowInfo()
