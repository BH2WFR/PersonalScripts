"""macOS CGEvent/IOHID hooks, input sending and window metadata.

Private implementation; launch ../keyboard-hook-viewer.py.
Platform dependencies are loaded only when the backend is used.
Scroll display uses NSEvent scrollingDeltaX/Y to retain precise trackpad deltas;
legacy integer CGEvent line values remain available to callbacks.
Native pinch gestures display NSEvent magnification deltas and phase flags.
"""

from __future__ import annotations

from utils import *
import threading
from typing import Callable
from .models import GesturePhase, InputDevice, WindowInfo, EventSink
_OS = sys.platform


_MOD_FLAG_MAP: dict[int, int] = {
    0x38: 1 << 17, 0x3C: 1 << 17,
    0x3B: 1 << 18, 0x3E: 1 << 18,
    0x3A: 1 << 19, 0x3D: 1 << 19,
    0x37: 1 << 20, 0x36: 1 << 20,
}

_MOUSE_BTN_MAP: dict[int, str] = {
    0: "left", 1: "right", 2: "middle", 3: "back", 4: "forward",
}

class _MacHIDKeyboardMonitor:
    """Read physical keyboard values together with their IOHIDDevice source."""

    _CF_STRING_ENCODING_UTF8 = 0x08000100
    _CF_NUMBER_SINT64_TYPE = 4
    _IORETURN_EXCLUSIVE_ACCESS = -536870203

    def __init__(self, on_key: Callable[[str, bool, int, InputDevice], None]):
        self._on_key = on_key
        self._manager = None
        self._loop = None
        self._callback = None
        self._property_keys: dict[str, int] = {}
        self._device_cache: dict[int, InputDevice] = {}
        self._recent_physical: dict[tuple[int, bool], float] = {}
        self._iokit = None
        self._cf = None
        self.open_result = 0

    def _load(self) -> None:
        self._iokit = ctypes.CDLL(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        self._cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        I = self._iokit
        C = self._cf

        I.IOHIDManagerCreate.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDManagerCreate.restype = ctypes.c_void_p
        I.IOHIDManagerSetDeviceMatching.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        I.IOHIDManagerRegisterInputValueCallback.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerScheduleWithRunLoop.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerUnscheduleFromRunLoop.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        I.IOHIDManagerOpen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDManagerOpen.restype = ctypes.c_int32
        I.IOHIDManagerClose.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        I.IOHIDValueGetElement.argtypes = [ctypes.c_void_p]
        I.IOHIDValueGetElement.restype = ctypes.c_void_p
        I.IOHIDValueGetIntegerValue.argtypes = [ctypes.c_void_p]
        I.IOHIDValueGetIntegerValue.restype = ctypes.c_longlong
        I.IOHIDElementGetUsagePage.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetUsagePage.restype = ctypes.c_uint32
        I.IOHIDElementGetUsage.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetUsage.restype = ctypes.c_uint32
        I.IOHIDElementGetDevice.argtypes = [ctypes.c_void_p]
        I.IOHIDElementGetDevice.restype = ctypes.c_void_p
        I.IOHIDDeviceGetProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        I.IOHIDDeviceGetProperty.restype = ctypes.c_void_p
        I.IOHIDDeviceGetService.argtypes = [ctypes.c_void_p]
        I.IOHIDDeviceGetService.restype = ctypes.c_uint32
        I.IORegistryEntryGetRegistryEntryID.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint64),
        ]
        I.IORegistryEntryGetRegistryEntryID.restype = ctypes.c_int32

        C.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        C.CFStringCreateWithCString.restype = ctypes.c_void_p
        C.CFStringGetTypeID.restype = ctypes.c_ulong
        C.CFNumberGetTypeID.restype = ctypes.c_ulong
        C.CFBooleanGetTypeID.restype = ctypes.c_ulong
        C.CFGetTypeID.argtypes = [ctypes.c_void_p]
        C.CFGetTypeID.restype = ctypes.c_ulong
        C.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
        ]
        C.CFStringGetCString.restype = ctypes.c_bool
        C.CFNumberGetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ]
        C.CFNumberGetValue.restype = ctypes.c_bool
        C.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        C.CFBooleanGetValue.restype = ctypes.c_bool
        C.CFRelease.argtypes = [ctypes.c_void_p]
        C.CFRunLoopGetCurrent.argtypes = []
        C.CFRunLoopGetCurrent.restype = ctypes.c_void_p

    def _make_property_keys(self) -> None:
        for key in (
            "Product", "SerialNumber", "VendorID", "ProductID", "LocationID",
        ):
            ref = self._cf.CFStringCreateWithCString(
                None, key.encode("ascii"), self._CF_STRING_ENCODING_UTF8,
            )
            if ref:
                self._property_keys[key] = ref

    def _property(self, device: int, key: str) -> str:
        key_ref = self._property_keys.get(key)
        if not key_ref:
            return ""
        value = self._iokit.IOHIDDeviceGetProperty(device, key_ref)
        if not value:
            return ""
        type_id = self._cf.CFGetTypeID(value)
        if type_id == self._cf.CFStringGetTypeID():
            buf = ctypes.create_string_buffer(1024)
            if self._cf.CFStringGetCString(
                value, buf, len(buf), self._CF_STRING_ENCODING_UTF8,
            ):
                return buf.value.decode("utf-8", errors="replace")
        elif type_id == self._cf.CFNumberGetTypeID():
            number = ctypes.c_longlong()
            if self._cf.CFNumberGetValue(
                value, self._CF_NUMBER_SINT64_TYPE, ctypes.byref(number),
            ):
                return str(number.value)
        elif type_id == self._cf.CFBooleanGetTypeID():
            return "1" if self._cf.CFBooleanGetValue(value) else "0"
        return ""

    def _device(self, device_ref: int) -> InputDevice:
        cache_key = int(device_ref)
        cached = self._device_cache.get(cache_key)
        if cached is not None:
            return cached

        registry_id = ctypes.c_uint64()
        service = self._iokit.IOHIDDeviceGetService(device_ref)
        if service:
            self._iokit.IORegistryEntryGetRegistryEntryID(
                service, ctypes.byref(registry_id),
            )
        path = f"0x{registry_id.value:x}" if registry_id.value else "unknown"
        result = InputDevice(
            idx=0,
            name=self._property(device_ref, "Product") or "Unknown keyboard",
            kind="KBD",
            vendor_id=self._property(device_ref, "VendorID"),
            product_id=self._property(device_ref, "ProductID"),
            serial=self._property(device_ref, "SerialNumber"),
            path=path,
        )
        self._device_cache[cache_key] = result
        return result

    def start(self) -> bool:
        try:
            self._load()
            iokit = self._iokit
            cf = self._cf
            if iokit is None or cf is None:
                return False
            self._make_property_keys()
            self._manager = iokit.IOHIDManagerCreate(None, 0)
            if not self._manager:
                self.stop()
                return False

            callback_type = ctypes.CFUNCTYPE(
                None, ctypes.c_void_p, ctypes.c_int32,
                ctypes.c_void_p, ctypes.c_void_p,
            )

            def handle_value(_context, result, _sender, value):
                if result != 0 or not value:
                    return
                try:
                    element = self._iokit.IOHIDValueGetElement(value)
                    if not element or self._iokit.IOHIDElementGetUsagePage(element) != 0x07:
                        return
                    usage = self._iokit.IOHIDElementGetUsage(element)
                    # 0x00-0x03 are HID no-event/error codes.  Values beyond
                    # the Keyboard/Keypad page range are not physical keys.
                    if usage < 0x04 or usage > 0xE7:
                        return
                    name = Keyboard.hid_usage_name(usage)
                    device_ref = self._iokit.IOHIDElementGetDevice(element)
                    if not device_ref:
                        return
                    pressed = bool(self._iokit.IOHIDValueGetIntegerValue(value))
                    device = self._device(device_ref)
                    event_key = (usage, pressed)
                    now = time.monotonic()
                    is_virtual = "virtualhidkeyboard" in device.name.lower()
                    if is_virtual:
                        # Karabiner commonly re-emits an unchanged physical
                        # event through its virtual keyboard.  Hide that exact
                        # duplicate, while retaining genuinely remapped usages.
                        if now - self._recent_physical.get(event_key, 0.0) < 0.05:
                            return
                    else:
                        self._recent_physical[event_key] = now
                    self._on_key(name, pressed, usage, device)
                except Exception:
                    return

            self._callback = callback_type(handle_value)
            # Use the CoreFoundation C API on this worker thread.  PyObjC's
            # CFRunLoopRef wrapper cannot be passed directly to ctypes.
            self._loop = cf.CFRunLoopGetCurrent()
            mode = ctypes.c_void_p.in_dll(
                cf, "kCFRunLoopDefaultMode",
            ).value
            self._mode = mode
            iokit.IOHIDManagerSetDeviceMatching(self._manager, None)
            iokit.IOHIDManagerRegisterInputValueCallback(
                self._manager, self._callback, None,
            )
            iokit.IOHIDManagerScheduleWithRunLoop(
                self._manager, self._loop, self._mode,
            )
            self.open_result = iokit.IOHIDManagerOpen(self._manager, 0)
            if self.open_result not in (0, self._IORETURN_EXCLUSIVE_ACCESS):
                self.stop()
                return False
            return True
        except (AttributeError, OSError):
            self.stop()
            return False

    def stop(self) -> None:
        if self._manager and self._iokit:
            if self._loop and getattr(self, "_mode", None):
                self._iokit.IOHIDManagerUnscheduleFromRunLoop(
                    self._manager, self._loop, self._mode,
                )
            self._iokit.IOHIDManagerClose(self._manager, 0)
            if self._cf:
                self._cf.CFRelease(self._manager)
        if self._cf:
            for key_ref in self._property_keys.values():
                self._cf.CFRelease(key_ref)
        self._manager = None
        self._loop = None
        self._callback = None
        self._property_keys.clear()
        self._device_cache.clear()
        self._recent_physical.clear()


def create_hook(sink: EventSink):
    """Unified CGEvent tap.  Returns object with .start() / .stop()."""
    if _OS != "darwin":
        return None

    try:
        from Quartz import (
            CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent,
            CFRunLoopRemoveSource, CFRunLoopRunInMode, CFRunLoopStop,
            CGEventGetFlags, CGEventGetIntegerValueField, CGEventGetLocation,
            CGEventKeyboardGetUnicodeString, CGEventMaskBit,
            CGEventTapCreate, CGEventTapEnable,
            kCFRunLoopDefaultMode, kCFRunLoopRunTimedOut,
            kCGEventFlagsChanged, kCGEventKeyDown, kCGEventKeyUp,
            kCGEventLeftMouseDown, kCGEventLeftMouseDragged, kCGEventLeftMouseUp,
            kCGEventOtherMouseDown, kCGEventOtherMouseDragged, kCGEventOtherMouseUp,
            kCGEventRightMouseDown, kCGEventRightMouseDragged, kCGEventRightMouseUp,
            kCGEventScrollWheel,
            kCGEventTapOptionListenOnly, kCGHeadInsertEventTap,
            kCGKeyboardEventKeycode, kCGMouseEventButtonNumber,
            kCGScrollWheelEventDeltaAxis1, kCGScrollWheelEventDeltaAxis2,
            kCGSessionEventTap,
            NSEvent, NSSystemDefined, NSEventTypeGesture, NSEventTypeMagnify,
        )
    except ImportError:
        return None

    kSystemDefinedEventMediaKeysSubtype = 8

    _MASK = (
        CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(NSSystemDefined)
        | CGEventMaskBit(kCGEventLeftMouseDown) | CGEventMaskBit(kCGEventLeftMouseUp)
        | CGEventMaskBit(kCGEventLeftMouseDragged)
        | CGEventMaskBit(kCGEventRightMouseDown) | CGEventMaskBit(kCGEventRightMouseUp)
        | CGEventMaskBit(kCGEventRightMouseDragged)
        | CGEventMaskBit(kCGEventOtherMouseDown) | CGEventMaskBit(kCGEventOtherMouseUp)
        | CGEventMaskBit(kCGEventOtherMouseDragged)
        | CGEventMaskBit(kCGEventScrollWheel)
        # CGEvent taps generally wrap pinch events in the generic gesture type;
        # NSEvent.type() identifies the magnify subtype after conversion.
        | CGEventMaskBit(NSEventTypeGesture) | CGEventMaskBit(NSEventTypeMagnify)
    )

    _MOUSE_PRESS = {
        kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventOtherMouseDown,
    }
    _MOUSE_RELEASE = {
        kCGEventLeftMouseUp, kCGEventRightMouseUp, kCGEventOtherMouseUp,
    }

    class MacHook:
        def __init__(self):
            self._tap = None
            self._loop_source = None
            self._loop = None
            self._hid_monitor = _MacHIDKeyboardMonitor(self._handle_hid_key_event)
            self._hid_keyboard_seen = False
            self._ready = threading.Event()
            self.running = False

        def _handle_hid_key_event(self, name, pressed, usage, device):
            self._hid_keyboard_seen = True
            sink._emit_key(name, pressed, usage, device)

        def _handle_key_event(self, event_type, event):
            if self._hid_keyboard_seen:
                return
            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            length, chars = CGEventKeyboardGetUnicodeString(event, 100, None, None)
            chars = chars if length > 0 else None
            if event_type == kCGEventKeyDown:
                sink._emit_key(Keyboard.macos_key_name(vk, chars), True, vk)
            elif event_type == kCGEventKeyUp:
                sink._emit_key(Keyboard.macos_key_name(vk, chars), False, vk)

        def _handle_flags_changed(self, event):
            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            # Fn/Globe is not part of the standard HID keyboard usage page.
            # Other modifiers arrive through IOHID with their physical source.
            if self._hid_keyboard_seen and vk not in (63, 179):
                return
            flags = CGEventGetFlags(event)
            if vk == 0x39:
                name = Keyboard.macos_key_name(vk)
                sink._emit_key(name, True, vk)
                return
            flag = _MOD_FLAG_MAP.get(vk)
            if flag is not None:
                name = Keyboard.macos_key_name(vk)
                sink._emit_key(name, bool(flags & flag), vk)

        def _handle_system_defined(self, event):
            sys_event = NSEvent.eventWithCGEvent_(event)
            if sys_event.subtype() != kSystemDefinedEventMediaKeysSubtype:
                return
            data1 = sys_event.data1()
            media_vk = (data1 & 0xFFFF0000) >> 16
            is_press = ((data1 & 0x0000FFFF) >> 8) == 0x0A
            name = Keyboard.macos_media_name(media_vk)
            if name is not None:
                sink._emit_key(name, is_press, media_vk)

        def _handle_mouse_event(self, event_type, event):
            btn = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
            (x, y) = CGEventGetLocation(event)
            x, y = int(x), int(y)
            if event_type == kCGEventScrollWheel:
                dx = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis2)
                dy = CGEventGetIntegerValueField(event, kCGScrollWheelEventDeltaAxis1)
                # Integer line fields can be zero throughout smooth scrolling.
                # NSEvent exposes precise device deltas, including momentum.
                # https://developer.apple.com/documentation/appkit/nsevent/scrollingdeltay
                scroll_event = NSEvent.eventWithCGEvent_(event)
                raw_delta = (
                    (float(scroll_event.scrollingDeltaX()), float(scroll_event.scrollingDeltaY()))
                    if scroll_event is not None else None
                )
                sink._emit_scroll(dx, dy, raw_delta=raw_delta)
            elif event_type in _MOUSE_PRESS:
                sink._emit_mouse(x, y, _MOUSE_BTN_MAP.get(btn, f"button{btn}"), True)
            elif event_type in _MOUSE_RELEASE:
                sink._emit_mouse(x, y, _MOUSE_BTN_MAP.get(btn, f"button{btn}"), False)

        def _handle_gesture_event(self, event: object) -> None:
            """Display only native magnify events, retaining zero-valued phase edges."""
            gesture = NSEvent.eventWithCGEvent_(event)
            if gesture is None or gesture.type() != NSEventTypeMagnify:
                return
            sink._emit_magnify(
                float(gesture.magnification()), GesturePhase(int(gesture.phase())),
            )

        def _handle(self, _proxy, event_type, event, _refcon):
            try:
                if event_type == kCGEventKeyDown:
                    self._handle_key_event(event_type, event)
                elif event_type == kCGEventKeyUp:
                    self._handle_key_event(event_type, event)
                elif event_type == kCGEventFlagsChanged:
                    self._handle_flags_changed(event)
                elif event_type == NSSystemDefined:
                    self._handle_system_defined(event)
                elif event_type in (NSEventTypeGesture, NSEventTypeMagnify):
                    self._handle_gesture_event(event)
                elif event_type in (
                    kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                    kCGEventLeftMouseDragged,
                    kCGEventRightMouseDown, kCGEventRightMouseUp,
                    kCGEventRightMouseDragged,
                    kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                    kCGEventOtherMouseDragged,
                    kCGEventScrollWheel,
                ):
                    self._handle_mouse_event(event_type, event)
            except Exception:
                pass
            return event

        def start(self):
            self._tap = CGEventTapCreate(
                kCGSessionEventTap, kCGHeadInsertEventTap,
                kCGEventTapOptionListenOnly, _MASK, self._handle, None,
            )
            if self._tap is None:
                self._ready.set()
                raise OSError(
                    "Failed to create event tap — grant Input Monitoring permission"
                )
            self._loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._loop = CFRunLoopGetCurrent()
            CFRunLoopAddSource(self._loop, self._loop_source, kCFRunLoopDefaultMode)
            if self._hid_monitor.start():
                if self._hid_monitor.open_result:
                    print(
                        f"{FLYellow}  HID source tracking is partial: one or more "
                        f"devices are held exclusively (for example by Karabiner).{CRst}"
                    )
            else:
                print(
                    f"{FLYellow}  HID source tracking unavailable; keyboard events "
                    f"will fall back to CGEvent without device identity.{CRst}"
                )
            CGEventTapEnable(self._tap, True)
            self._ready.set()
            self.running = True
            while self.running:
                result = CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1, False)
                if result != kCFRunLoopRunTimedOut:
                    break

        def stop(self):
            self.running = False
            self._hid_monitor.stop()
            if self._tap is not None:
                CGEventTapEnable(self._tap, False)
                CFRunLoopRemoveSource(
                    self._loop, self._loop_source, kCFRunLoopDefaultMode,
                )
                CFRunLoopStop(self._loop)
                self._tap = None
                self._loop_source = None
                self._loop = None

    return MacHook()

class _MacController:
    """Send keyboard / mouse events via CGEvent API."""

    _Q = None  # Quartz module, lazy-loaded

    @classmethod
    def _quartz(cls):
        if cls._Q is None:
            from Quartz import (
                CGEventCreateKeyboardEvent, CGEventCreateMouseEvent,
                CGEventCreateScrollWheelEvent,
                CGEventKeyboardSetUnicodeString, CGEventPost, CGEventSetFlags,
                CGEventGetLocation,
                kCGHIDEventTap, kCGScrollEventUnitPixel,
                kCGEventKeyDown, kCGEventKeyUp,
                kCGEventMouseMoved,
                kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                kCGEventRightMouseDown, kCGEventRightMouseUp,
                kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                kCGEventFlagMaskShift, kCGEventFlagMaskControl,
                kCGEventFlagMaskAlternate, kCGEventFlagMaskCommand,
            )
            cls._Q = type(sys)("Quartz")  # namespace
            for n in (
                "CGEventCreateKeyboardEvent", "CGEventCreateMouseEvent",
                "CGEventCreateScrollWheelEvent",
                "CGEventKeyboardSetUnicodeString", "CGEventPost", "CGEventSetFlags",
                "CGEventGetLocation",
                "kCGHIDEventTap", "kCGScrollEventUnitPixel",
                "kCGEventKeyDown", "kCGEventKeyUp",
                "kCGEventMouseMoved",
                "kCGEventLeftMouseDown", "kCGEventLeftMouseUp",
                "kCGEventRightMouseDown", "kCGEventRightMouseUp",
                "kCGEventOtherMouseDown", "kCGEventOtherMouseUp",
                "kCGEventFlagMaskShift", "kCGEventFlagMaskControl",
                "kCGEventFlagMaskAlternate", "kCGEventFlagMaskCommand",
            ):
                setattr(cls._Q, n, locals()[n])
        return cls._Q

    def press(self, name: str) -> None:
        Q = self._quartz()
        vk = (Keyboard.macos_virtual_key(name) or 0)
        event = Q.CGEventCreateKeyboardEvent(None, vk, True)
        if vk == 0 and len(name) == 1:
            Q.CGEventKeyboardSetUnicodeString(event, 1, name)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def release(self, name: str) -> None:
        Q = self._quartz()
        vk = (Keyboard.macos_virtual_key(name) or 0)
        event = Q.CGEventCreateKeyboardEvent(None, vk, False)
        if vk == 0 and len(name) == 1:
            Q.CGEventKeyboardSetUnicodeString(event, 1, name)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def tap(self, name: str) -> None:
        self.press(name)
        self.release(name)

    def move(self, x: int, y: int) -> None:
        Q = self._quartz()
        event = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (x, y), 0)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def _mouse_pos(self):
        """Get current mouse position as (x, y) tuple."""
        from AppKit import NSEvent
        from Quartz import CGDisplayPixelsHigh
        pos = NSEvent.mouseLocation()
        return (pos.x, CGDisplayPixelsHigh(0) - pos.y)

    def _btn_event(self, down: bool, button: str):
        Q = self._quartz()
        x, y = self._mouse_pos()
        btn_map = {
            "left": (
                Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, 0,
            ),
            "right": (
                Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, 1,
            ),
            "middle": (
                Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp, 2,
            ),
        }
        ev_down, ev_up, btn_num = btn_map.get(button, btn_map["middle"])
        ev_type = ev_down if down else ev_up
        event = Q.CGEventCreateMouseEvent(None, ev_type, (x, y), btn_num)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def mouse_down(self, button: str = "left") -> None:
        self._btn_event(True, button)

    def mouse_up(self, button: str = "left") -> None:
        self._btn_event(False, button)

    def click(self, button: str = "left", count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def scroll(self, dx: int = 0, dy: int = 0) -> None:
        Q = self._quartz()
        event = Q.CGEventCreateScrollWheelEvent(
            None, Q.kCGScrollEventUnitPixel, 2, dy * 10, dx * 10,
        )
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def set_modifier(self, name: str, on: bool) -> None:
        """Set a modifier key state directly (without generating key events).
        Useful for toggling caps_lock / num_lock when the physical state
        differs from the desired logical state.
        """
        flag_map = {
            "shift": _MacController._Q.kCGEventFlagMaskShift
                     if _MacController._Q else 1 << 17,
            "ctrl": 1 << 18,
            "alt": 1 << 19,
            "cmd": 1 << 20,
            "super": 1 << 20,
        }
        # For modifiers, we send a flags-changed event
        # This is a simplified approach — for full toggle support use press/release
        self.press(name) if on else self.release(name)

def _get_foreground_window_darwin() -> WindowInfo:
    """Return foreground window info.

    Uses only CGWindowList (CoreGraphics C API) which is thread-safe.
    CGWindowListCopyWindowInfo returns windows in front-to-back order,
    so the first layer-0 window is the frontmost.
    """
    from Quartz import (
        CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )

    try:
        wins = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID,
        )
    except Exception:
        return WindowInfo()

    for w in wins:
        if w.get("kCGWindowLayer", 999) != 0:
            continue
        pid = w.get("kCGWindowOwnerPID", 0)
        return WindowInfo(
            pid=pid,
            process_name=w.get("kCGWindowOwnerName", "") or "",
            title=w.get("kCGWindowName", "") or "",
            window_class="",
            bundle_id="",
        )

    return WindowInfo()
