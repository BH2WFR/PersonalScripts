"""Nonactivating Cocoa panel using the Windows keyboard's six-row geometry."""

from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any, cast

import AppKit  # pyright: ignore[reportMissingImports]
import Foundation  # pyright: ignore[reportMissingImports]
from Foundation import NSRect, NSSize  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
import objc  # pyright: ignore[reportMissingImports]

from utils import System
from utils.gui_colors import text_hex
from utils.macos_windows import order_window_front
from .layout import (DEFAULT_SIZE, EXTRA_HEIGHT, MAC_EXTENDED, MAC_LABELS, MAC_ROWS, MINIMUM_SIZE, NUMPAD_KEYS,
                     TOOLBAR, TOOLBAR_DIVIDERS, TOOLBAR_TIPS, WINDOW_TITLE, frames, mac_frame_near_pointer, panel_width)
from .macos import MacOutput
from .state import DARK_THEME, LIGHT_THEME, KeyboardState, LeftKeyMode, WindowLayout, hover_color

# PyObjC resolves framework members at runtime from Objective-C metadata.
A = cast(Any, AppKit)
F = cast(Any, Foundation)

SHOW_NOTIFICATION = "PersonalScripts.ScreenKeyboard.Show"


@cache
def color(rgb: str):
    if rgb == "white":
        return A.NSColor.whiteColor()
    return A.NSColor.colorWithSRGBRed_green_blue_alpha_(*(int(rgb[i:i + 2], 16) / 255 for i in (1, 3, 5)), 1)


class KeyboardPanel(A.NSPanel):
    def canBecomeKeyWindow(self) -> bool:
        return False

    def canBecomeMainWindow(self) -> bool:
        return False


class KeyboardContent(A.NSView):
    def viewDidChangeEffectiveAppearance(self) -> None:
        objc.super(KeyboardContent, self).viewDidChangeEffectiveAppearance()
        window = self.window()
        if window is not None and (controller := window.delegate()) is not None:
            controller.update_theme()


class DragStrip(A.NSView):
    def acceptsFirstMouse_(self, event) -> bool:
        return True

    def mouseDown_(self, event) -> None:
        self.window().performWindowDragWithEvent_(event)


class KeyButton(A.NSButton):
    def acceptsFirstMouse_(self, event) -> bool:
        return True

    def needsPanelToBecomeKey(self) -> bool:
        return False

    def mouseDownCanMoveWindow(self) -> bool:
        return False

    def mouseDown_(self, event) -> None:
        if not self.isEnabled():
            return
        name, view = str(self.identifier()), self.target()
        if name == "Layer" and event.modifierFlags() & A.NSEventModifierFlagControl:
            self.rightMouseDown_(event)
            return
        if name not in view.actions:
            view.perform(lambda: view.state.press(name))
        else:
            self.tracking_toolbar = True

    def mouseUp_(self, event) -> None:
        if not self.isEnabled():
            return
        name, view = str(self.identifier()), self.target()
        if name in view.actions:
            if self.tracking_toolbar and A.NSPointInRect(self.convertPoint_fromView_(event.locationInWindow(), None),
                                                         self.bounds()):
                view.perform(view.actions[name])
            self.tracking_toolbar = False
        else:
            view.perform(view.state.release)

    def rightMouseDown_(self, event) -> None:
        if str(self.identifier()) == "Layer":
            self.target().update_menu()
            A.NSMenu.popUpContextMenu_withEvent_forView_(self.target().menu, event, self)

    def mouseEntered_(self, event) -> None:
        self.hovered = True
        self.target().paint(str(self.identifier()))

    def mouseExited_(self, event) -> None:
        self.hovered = False
        self.target().paint(str(self.identifier()))

    def performClick_(self, sender) -> None:
        name, view = str(self.identifier()), self.target()
        if name in view.actions:
            view.perform(view.actions[name])
        else:
            view.perform(lambda: view.state.press(name))
            view.perform(view.state.release)


class PanelController(F.NSObject):
    @objc.python_method
    def setup(self, panel, force_layer: LeftKeyMode | None = None) -> None:
        self.panel = panel
        self.closed = self.resizing = False
        self.timer = None
        self.buttons = {}
        self.state = KeyboardState(MacOutput(self.call_later), self.schedule, self.cancel, self.refresh, force_layer)
        saved = self.state.window_layout
        self.expanded, self.numpad = saved.expanded, saved.numpad
        self.labels = {n: label for row in MAC_ROWS for n, label, _ in row}
        self.labels.update(MAC_EXTENDED)
        self.labels.update((n, label) for n, label, *_ in NUMPAD_KEYS)
        self.actions = {"extended": self.toggle_extended, "numpad": self.toggle_numpad,
                        "reset": self.state.reset, "redraw": self.redraw, "size": self.reset_size,
                        "settings": self.show_settings}
        self.menu = A.NSMenu.alloc().initWithTitle_("Layer")
        self.menu.setAutoenablesItems_(False)
        for mode in self.state.modes:
            item = self.menu.addItemWithTitle_action_keyEquivalent_(mode.menu_label, "adapt:", "")
            item.setRepresentedObject_(mode.value)
            item.setTarget_(self)
        self.menu.addItem_(A.NSMenuItem.separatorItem())
        self.remember_item = self.menu.addItemWithTitle_action_keyEquivalent_("Remember window size", "rememberSize:", "")
        self.remember_item.setTarget_(self)
        content = panel.contentView()
        content.setWantsLayer_(True)
        self.status = A.NSTextField.labelWithString_("")
        self.status.setFont_(A.NSFont.systemFontOfSize_(11))
        content.addSubview_(self.status)
        # The transparent header receives drags over the status, behind the buttons.
        self.header = DragStrip.alloc().initWithFrame_(((0, 0), (0, 0)))
        self.footer = DragStrip.alloc().initWithFrame_(((0, 0), (0, 0)))
        self.footer.setWantsLayer_(True)
        content.addSubview_(self.header)
        content.addSubview_(self.footer)
        self.dividers = {}
        for name in TOOLBAR_DIVIDERS.values():
            line = DragStrip.alloc().initWithFrame_(((0, 0), (0, 0)))
            line.setWantsLayer_(True)
            content.addSubview_(line)
            self.dividers[name] = line
        for name, label in [*TOOLBAR, *self.labels.items()]:
            button = KeyButton.alloc().initWithFrame_(((0, 0), (40, 20)))
            button.setIdentifier_(name)
            if name == "language":
                button.setTitle_("")
                button.setImage_(A.NSImage.imageWithSystemSymbolName_accessibilityDescription_("globe", "Switch input source"))
                button.setImagePosition_(A.NSImageOnly)
                button.setImageScaling_(A.NSImageScaleProportionallyDown)
                button.setContentTintColor_(A.NSColor.whiteColor())
                button.setAccessibilityLabel_("Switch input source")
            else:
                button.setTitle_(label)
            button.setTarget_(self)
            button.setRefusesFirstResponder_(True)
            button.setBordered_(False)
            button.cell().setWraps_(False)
            button.cell().setUsesSingleLineMode_(True)
            button.setWantsLayer_(True)
            button.layer().setActions_({"backgroundColor": F.NSNull.null()})
            button.layer().setBorderWidth_(int(name not in self.actions or name in {"extended", "numpad"}))
            button.hovered = button.tracking_toolbar = False
            button.appearance_key = None
            button.setToolTip_(TOOLBAR_TIPS.get(name, "Right-click for Layer settings" if name == "Layer" else label))
            tracking = A.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                button.bounds(), A.NSTrackingMouseEnteredAndExited | A.NSTrackingActiveAlways
                | A.NSTrackingInVisibleRect, button, None)
            button.addTrackingArea_(tracking)
            content.addSubview_(button)
            self.buttons[name] = button
        self.update_theme()
        self.resize(saved.width, saved.height)

    @objc.python_method
    def update_theme(self) -> None:
        content = self.panel.contentView()
        names = [A.NSAppearanceNameAqua, A.NSAppearanceNameDarkAqua]
        match = content.effectiveAppearance().bestMatchFromAppearancesWithNames_(names)
        self.theme = DARK_THEME if match == A.NSAppearanceNameDarkAqua else LIGHT_THEME
        content.layer().setBackgroundColor_(color(self.theme.surface).CGColor())
        self.status.setTextColor_(color(text_hex("gray", dark=self.theme.dark)))
        self.footer.layer().setBackgroundColor_(color(self.theme.footer).CGColor())
        for divider in self.dividers.values():
            divider.layer().setBackgroundColor_(color(self.theme.divider).CGColor())
        for button in self.buttons.values():
            button.layer().setBorderColor_(color(self.theme.border).CGColor())
        self.refresh()

    def adapt_(self, sender) -> None:
        self.perform(lambda: self.state.set_mode(LeftKeyMode(sender.representedObject())))

    def rememberSize_(self, sender) -> None:
        self.perform(lambda: self.state.set_remember_size(not self.state.remember_size, self.current_layout()))

    @objc.python_method
    def update_menu(self) -> None:
        for item in self.menu.itemArray():
            if item.representedObject() is not None:
                item.setEnabled_(self.state.force_layer is None)
                item.setState_(int(item.representedObject() == self.state.output.mode.value))
        self.remember_item.setState_(int(self.state.remember_size))

    @objc.python_method
    def show_settings(self) -> None:
        self.update_menu()
        self.menu.popUpMenuPositioningItem_atLocation_inView_(None, (0, 0), self.buttons["settings"])

    @objc.python_method
    def perform(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            try:
                self.state.reset()
            finally:
                alert = A.NSAlert.alloc().init()
                alert.setMessageText_(WINDOW_TITLE)
                alert.setInformativeText_(str(exc))
                alert.runModal()

    @objc.python_method
    def cancel(self) -> None:
        if self.timer:
            self.timer.invalidate()
            self.timer = None

    @objc.python_method
    def schedule(self, ms: int, callback: Callable[[], None]) -> None:
        self.cancel()
        self.timer = self.call_later(ms, callback)

    @objc.python_method
    def call_later(self, ms: int, callback: Callable[[], None]) -> Any:
        def fire(_timer: Any) -> None:
            if not self.closed:
                self.perform(callback)

        timer = F.NSTimer.timerWithTimeInterval_repeats_block_(ms / 1000, False, fire)
        F.NSRunLoop.mainRunLoop().addTimer_forMode_(timer, F.NSRunLoopCommonModes)
        return timer

    @objc.python_method
    def paint(self, name: str) -> None:
        button = self.buttons[name]
        if name in self.actions:
            active = (name == "extended" and self.expanded) or (name == "numpad" and self.numpad)
            bg, fg = self.theme.toolbar(active)
            label = dict(TOOLBAR)[name]
        else:
            bg, fg = self.state.colors(name, dark=self.theme.dark)
            label = self.state.label(name, self.labels[name])
            button.setEnabled_(name != "Numpad5" or self.state.lock_states["NumLock"])
        size = self.panel.contentView().bounds().size
        unit = (size.width - 5) / (20 if self.numpad else 16)
        points = 14 if label == MAC_LABELS.get(name) or label == "⇪" else (11 if unit * 16 < 600 else 12)
        appearance = (label, bg, fg, points, button.hovered)
        if button.appearance_key == appearance:
            return
        button.appearance_key = appearance
        button.layer().setBackgroundColor_(color(hover_color(bg, fg, dark=self.theme.dark) if button.hovered else bg).CGColor())
        if name == "language":
            return
        title = F.NSAttributedString.alloc().initWithString_attributes_(label, {
            A.NSForegroundColorAttributeName: color(fg), A.NSFontAttributeName: A.NSFont.systemFontOfSize_(points)})
        button.setAttributedTitle_(title)

    @objc.python_method
    def refresh(self) -> None:
        if not self.resizing:
            self.status.setStringValue_(self.state.status())
            self.status.setToolTip_(self.state.status())
            for name in self.buttons:
                self.paint(name)

    @objc.python_method
    def layout(self) -> None:
        if self.resizing:
            return
        size = self.panel.contentView().bounds().size
        width, height = round(size.width), round(size.height)
        bounds = frames(width, height, 1, self.expanded, self.numpad, mac=True)
        controls = {"header": self.header, "footer": self.footer, "status": self.status, **self.dividers, **self.buttons}
        for name, control in controls.items():
            control.setHidden_(name not in bounds)
            if name in bounds:
                x, y, w, h = bounds[name]
                control.setFrame_(((x, height - y - h), (w, h)))
        self.refresh()

    @objc.python_method
    def resize(self, width: float, height: float) -> None:
        self.panel.setContentMinSize_((round(MINIMUM_SIZE[0] * (1.25 if self.numpad else 1)),
                                      MINIMUM_SIZE[1] + EXTRA_HEIGHT * self.expanded))
        top = self.panel.frame().origin.y + self.panel.frame().size.height
        self.panel.setContentSize_((width, height))
        if self.panel.isVisible():
            f = self.panel.frame()
            f.origin.y = top - f.size.height
            self.panel.setFrame_display_(self.panel.constrainFrameRect_toScreen_(f, self.panel.screen()), True)
        self.layout()

    @objc.python_method
    def toggle_extended(self) -> None:
        self.expanded = not self.expanded
        size = self.panel.contentView().bounds().size
        self.resize(size.width, size.height + (EXTRA_HEIGHT if self.expanded else -EXTRA_HEIGHT))
        self.save_window()

    @objc.python_method
    def toggle_numpad(self) -> None:
        self.numpad = not self.numpad
        size = self.panel.contentView().bounds().size
        self.resize(panel_width(round(size.width), self.numpad, 1), size.height)
        self.save_window()

    @objc.python_method
    def reset_size(self) -> None:
        self.expanded = self.numpad = False
        self.resize(*DEFAULT_SIZE)
        self.save_window()

    @objc.python_method
    def current_layout(self) -> WindowLayout:
        size = self.panel.contentView().bounds().size
        return WindowLayout(round(size.width), round(size.height), self.expanded, self.numpad)

    @objc.python_method
    def save_window(self) -> None:
        self.state.save_window(self.current_layout())

    @objc.python_method
    def redraw(self) -> None:
        self.state.lock_states = self.state.output.locks()
        for button in self.buttons.values():
            button.appearance_key = None
        self.layout()
        self.panel.display()

    def windowWillStartLiveResize_(self, note) -> None:
        self.resizing = True
        content = self.panel.contentView()
        for control in content.subviews():
            control.setHidden_(True)
        content.displayIfNeeded()

    def windowDidEndLiveResize_(self, note) -> None:
        self.resizing = False
        self.layout()
        self.perform(self.save_window)

    def windowDidResize_(self, note) -> None:
        self.layout()

    def windowShouldZoom_toFrame_(self, window: KeyboardPanel, frame: NSRect) -> bool:
        return False

    def windowWillResize_toSize_(self, window: KeyboardPanel, size: NSSize) -> NSSize:
        current = window.frame().size
        # AppKit also calls this delegate for a double-click on a resize edge.
        if not window.inLiveResize():
            return current
        screen = window.screen()
        if screen is not None:
            available = screen.visibleFrame().size
            if size.width >= available.width and size.width > current.width:
                size.width = current.width
            if size.height >= available.height and size.height > current.height:
                size.height = current.height
        return size

    def contextChanged_(self, note) -> None:
        self.perform(self.state.check_target)

    def showRequested_(self, note) -> None:
        value = (note.userInfo() or {}).get("force_layer")
        self.launch_mode = next((m for m in (LeftKeyMode.CAPS, LeftKeyMode.F1) if m.value == value), None)
        if hasattr(self, "state"):
            self.perform(lambda: self.state.apply_launch_mode(self.launch_mode))
            self.show_near_pointer()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible) -> bool:
        self.show_near_pointer()
        return False

    @objc.python_method
    def show_near_pointer(self) -> None:
        panel = self.panel
        mouse = A.NSEvent.mouseLocation()
        screen = next((s for s in A.NSScreen.screens() if A.NSPointInRect(mouse, s.frame())), A.NSScreen.mainScreen())
        frame = mac_frame_near_pointer(mouse, screen.visibleFrame(), panel.frame().size)
        panel.setFrame_display_(frame, True)
        order_window_front(panel, activate=False)

    def windowWillClose_(self, note) -> None:
        self.perform(self.save_window)
        self.closed = True


def run(force_layer: LeftKeyMode | None = None, warning: str = "") -> int:
    import fcntl

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    if warning:
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_(WINDOW_TITLE)
        alert.setInformativeText_(warning)
        alert.runModal()
    controller = PanelController.alloc().init()
    controller.launch_mode = force_layer
    notifications = F.NSDistributedNotificationCenter.defaultCenter()
    notifications.addObserver_selector_name_object_suspensionBehavior_(
        controller, "showRequested:", SHOW_NOTIFICATION, None, F.NSNotificationSuspensionBehaviorDeliverImmediately)
    try:
        with (Path(F.NSTemporaryDirectory()) / "PersonalScripts.ScreenKeyboard.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                info = {"force_layer": force_layer.value} if force_layer else {}
                notifications.postNotificationName_object_userInfo_deliverImmediately_(SHOW_NOTIFICATION, None, info, True)
                return 0
            return run_panel(app, controller)
    finally:
        notifications.removeObserver_(controller)


def create_panel() -> KeyboardPanel:
    """Create a manually resizable floating keyboard on every Space."""
    mask = (A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable
            | A.NSWindowStyleMaskNonactivatingPanel)
    panel = KeyboardPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        ((0, 0), DEFAULT_SIZE), mask, A.NSBackingStoreBuffered, False)
    panel.setContentView_(KeyboardContent.alloc().initWithFrame_(panel.contentView().frame()))
    panel.setTitle_(WINDOW_TITLE)
    panel.setRestorable_(False)
    panel.setContentMinSize_(MINIMUM_SIZE)
    panel.setReleasedWhenClosed_(False)
    panel.setHidesOnDeactivate_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setLevel_(A.NSFloatingWindowLevel)
    panel.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | A.NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | A.NSWindowCollectionBehaviorFullScreenDisallowsTiling)
    panel.standardWindowButton_(A.NSWindowZoomButton).setEnabled_(False)
    return panel


def run_panel(app, controller: PanelController) -> int:
    if not System.check_macos_accessibility_permission(prompt=True):
        raise RuntimeError("Allow Accessibility access in System Settings, then reopen Screen Keyboard.")
    panel = create_panel()
    controller.setup(panel, controller.launch_mode)
    panel.setDelegate_(controller)
    app.setDelegate_(controller)
    center = A.NSWorkspace.sharedWorkspace().notificationCenter()
    center.addObserver_selector_name_object_(controller, "contextChanged:", A.NSWorkspaceDidActivateApplicationNotification, None)
    try:
        controller.show_near_pointer()
        while not controller.closed:
            event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                A.NSEventMaskAny, F.NSDate.distantFuture(), F.NSDefaultRunLoopMode, True)
            if event:
                app.sendEvent_(event)
            app.updateWindows()
    finally:
        app.setDelegate_(None)
        center.removeObserver_(controller)
        try:
            controller.state.reset()
        finally:
            panel.orderOut_(None)
    return 0
