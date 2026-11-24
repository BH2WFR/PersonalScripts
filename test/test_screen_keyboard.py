"""Interaction and geometry regressions for both screen keyboard layouts."""

from pathlib import Path
import sys
import importlib.util
import tempfile
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/input-and-text"))
from screen_keyboard.layout import (
    DEFAULT_SIZE, EXTENDED_KEYS, MAC_EXTENDED, MAC_ROWS, NUMPAD_KEYS, NUMPAD_NAVIGATION,
    ROWS, frames, mac_frame_near_pointer, panel_width,
)
from screen_keyboard.state import KeyboardState, KeyRepeat, LeftKeyMode, WindowLayout
from screen_keyboard.windows import WindowsOutput
from utils import ConfigStore


class KeyboardTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        directory = patch.object(ConfigStore, "directory", return_value=Path(scratch.name))
        directory.start()
        self.addCleanup(directory.stop)
        self.output = Mock(mac=False)
        self.output.target.return_value = 10
        self.output.key_down.return_value = None
        self.output.locks.return_value = {"CapsLock": False, "NumLock": True, "ScrollLock": False}
        self.schedule = Mock()
        self.state = self.new_state()

    def new_state(self) -> KeyboardState:
        return KeyboardState(self.output, self.schedule, Mock(), Mock())

    def click(self, name: str) -> None:
        self.state.press(name)
        self.state.release()

    def test_native_caps_and_separate_platform_preferences(self) -> None:
        self.click("Layer")
        self.output.key_down.assert_called_once_with("CapsLock", [])
        self.assertFalse(self.state.held)
        self.assertEqual(self.state.status(), "Normal")
        self.state.set_mode(LeftKeyMode.F24)
        self.assertTrue(self.new_state().adapted)
        self.output.mac = True
        self.state = self.new_state()
        self.assertFalse(self.state.adapted)
        self.assertEqual(self.state.label("Layer", ""), "⇪")
        self.click("Layer")
        self.output.hold.assert_not_called()
        self.state.set_mode(LeftKeyMode.CAPS)
        self.click("Layer")
        self.click("LAlt")
        self.assertEqual(self.state.status(), "Layer 3")
        self.assertEqual(self.state.label("Layer", ""), "Layer")

    def test_all_four_layers_and_one_shot_release(self) -> None:
        for mac in (False, True):
            self.output.mac = mac
            self.state = self.new_state()
            self.state.set_mode(LeftKeyMode.CAPS)
            self.assertEqual(self.state.status(), "Normal")
            for i, modifiers in enumerate([[], ["LShift"], ["LAlt"], ["LShift", "RAlt"]], 1):
                self.click("Layer")
                for name in modifiers:
                    self.click(name)
                self.assertEqual(self.state.status(), f"Layer {i}")
                self.click("2")
                self.output.key_down.assert_called_with("2", modifiers)
                self.assertFalse(self.state.held)
                self.assertEqual(self.state.status(), "Normal")

    def test_leaving_layer_releases_locked_and_one_shot_modifiers(self) -> None:
        for mac in (False, True):
            self.output.mac = mac
            self.state = self.new_state()
            self.state.set_mode(LeftKeyMode.F1)
            for finish in ("Layer", "a"):
                with self.subTest(mac=mac, finish=finish):
                    self.state.press("LControl")
                    self.state.lock("LControl")
                    self.state.release()
                    self.state.press("Layer")
                    if finish == "Layer":
                        self.state.lock("Layer")
                    self.state.release()
                    modifier = "Fn" if mac else "RAlt"
                    self.click(modifier)
                    self.assertEqual(self.state.held, ["LControl", "Layer", modifier])
                    self.output.reset_mock()
                    self.click(finish)
                    self.output.reset.assert_called_once_with()
                    self.assertFalse(self.state.held)
                    self.assertFalse(self.state.locked)
                    self.click("b")
                    self.output.key_down.assert_called_with("b", [])

    def test_supported_left_key_modes_round_trip(self) -> None:
        for mac in (False, True):
            self.output.mac = mac
            state = self.new_state()
            self.assertIs(state.output.mode, LeftKeyMode.NATIVE)
            self.assertEqual(LeftKeyMode.F24 in state.modes, not mac)
            if mac:
                with self.assertRaises(ValueError):
                    state.set_mode(LeftKeyMode.F24)
            for mode in state.modes:
                state.set_mode(mode)
                self.assertIs(self.new_state().output.mode, mode)

    def test_force_layer_overrides_prefs_only_for_the_launch(self) -> None:
        self.state.set_mode(LeftKeyMode.CAPS)
        self.state = KeyboardState(self.output, self.schedule, Mock(), Mock(), LeftKeyMode.F24)
        self.state.set_mode(LeftKeyMode.NATIVE)
        self.assertIs(self.state.output.mode, LeftKeyMode.F24)
        self.click("Layer")
        self.state.apply_launch_mode(LeftKeyMode.F1)
        self.assertFalse(self.state.held)
        self.assertIs(self.state.output.mode, LeftKeyMode.F1)
        self.assertEqual(self.state.store.load()[self.state.setting], "CapsLock")
        self.state.apply_launch_mode(None)
        self.assertIs(self.state.output.mode, LeftKeyMode.CAPS)

    def test_window_settings_are_platform_specific(self) -> None:
        layout = WindowLayout(680, 255, True, False)
        self.state.set_mode(LeftKeyMode.F1)
        self.state.set_remember_size(True, layout)
        self.output.mac = True
        mac = self.new_state()
        self.assertEqual(mac.window_layout, WindowLayout())
        self.assertFalse(mac.remember_size)
        mac.set_remember_size(True, mac.window_layout)
        mac.save_window(WindowLayout(800, 300, False, True))
        self.assertEqual(self.new_state().window_layout, WindowLayout(800, 300, False, True))
        self.output.mac = False
        self.state = self.new_state()
        self.assertEqual(self.state.window_layout, layout)
        self.assertTrue(self.state.adapted)
        self.state.store.update({"windows_window": {"width": False}})
        self.assertEqual(self.new_state().window_layout, WindowLayout())

    def test_size_memory_requires_opt_in(self) -> None:
        self.state.store.update({"windows_window": {"width": 700, "height": 320}})
        state = self.new_state()
        self.assertFalse(state.remember_size)
        self.assertEqual(state.window_layout, WindowLayout())
        with patch.object(state.store, "update") as write:
            state.save_window(WindowLayout(720, 300))
            write.assert_not_called()
        state.set_remember_size(True, WindowLayout(730, 310))
        self.assertEqual(self.new_state().window_layout, WindowLayout(730, 310))
        state.set_remember_size(False, WindowLayout(730, 310))
        state.save_window(WindowLayout(750, 330))
        self.assertEqual(state.store.load()["windows_window"], {"remember_size": False})
        self.assertEqual(self.new_state().window_layout, WindowLayout())

    def test_caps_uses_numlock_palette_with_independent_lock_state(self) -> None:
        for caps in (False, True):
            self.state.lock_states.update(CapsLock=caps, NumLock=caps)
            expected = self.state.colors("NumLock")
            self.state.lock_states["NumLock"] = not caps
            self.assertNotEqual(expected, self.state.colors("NumLock"))
            for key in ("Layer", "CapsLock"):
                self.assertEqual(self.state.colors(key), expected)
                self.state.pressed = key
                pressed = self.state.colors(key)
                self.state.pressed = "NumLock"
                self.assertEqual(pressed, self.state.colors("NumLock"))
                self.state.pressed = None

    def test_layer_hints_follow_the_keys_beside_space(self) -> None:
        for mac, keys, label, other in ((False, ("LAlt", "RAlt"), "Alt", "LWin"),
                                        (True, ("LWin", "RWin"), "⌘", "LAlt")):
            self.output.mac = mac
            self.state = self.new_state()
            self.state.set_mode(LeftKeyMode.F1)
            baseline = self.state.colors(keys[0])
            layer_idle = self.state.colors("Layer")
            self.assertNotEqual(baseline, layer_idle)
            self.click(keys[0])
            modifier_down = self.state.colors(keys[0])
            self.state.press("Layer")
            for key in keys:
                self.assertEqual(self.state.label(key, label), "L3/4")
            self.assertEqual(self.state.colors(keys[0]), self.state.colors("Layer"))
            self.assertEqual(self.state.colors(keys[1]), layer_idle)
            self.assertNotEqual(self.state.label(other, ""), "L3/4")
            self.state.lock("Layer")
            self.assertEqual(self.state.colors(keys[0]), modifier_down)
            self.assertEqual(self.state.colors(keys[1]), layer_idle)
            self.state.release()
            for key in keys:
                self.assertEqual(self.state.label(key, label), "L3/4")
            self.assertEqual(self.state.colors(keys[0]), modifier_down)
            self.assertEqual(self.state.colors(keys[1]), layer_idle)
            self.assertEqual(self.state.status(), "Layer 3")
            self.click("LShift")
            self.assertEqual(self.state.status(), "Layer 4")
            self.click("a")
            self.click("Layer")
            for key in keys:
                self.assertEqual(self.state.label(key, label), label)
                self.assertEqual(self.state.colors(key), baseline)
            self.state.press("Layer")
            self.assertEqual(self.state.colors(keys[0]), layer_idle)
            self.state.release()
            self.assertEqual(self.state.colors(keys[0]), layer_idle)
            self.assertEqual(self.state.label(keys[0], label), "L3/4")
            self.click("a")
            self.assertEqual(self.state.colors(keys[0]), baseline)
            self.assertEqual(self.state.label(keys[0], label), label)

    @patch("screen_keyboard.state.monotonic")
    def test_repeat_lock_and_target_switch(self, clock: Mock) -> None:
        clock.return_value = 10.0
        self.output.mac = True
        self.state = self.new_state()
        self.state.set_mode(LeftKeyMode.F1)
        self.output.key_down.return_value = KeyRepeat(.6, .025, self.output.repeat_key)
        self.state.press("Layer")
        ms, lock = self.schedule.call_args.args
        self.assertEqual(ms, 500)
        lock()
        self.state.release()
        self.click("a")
        self.assertEqual(self.state.locked, {"Layer"})
        self.state.press("b")
        ms, repeat = self.schedule.call_args.args
        self.assertEqual(ms, 600)
        clock.return_value = 10.602
        repeat()
        self.output.repeat_key.assert_called_once_with()
        self.assertEqual(self.schedule.call_args.args[0], 23)
        self.output.target.return_value = 20
        self.output.reset_mock()
        repeat()
        self.assertFalse(self.state.locked)
        self.assertFalse(self.state.held)
        self.output.repeat_key.assert_not_called()
        self.output.reset.assert_called_once_with()

    def test_press_repeats_and_release_keep_one_chord(self) -> None:
        self.output.key_down.return_value = KeyRepeat(.6, .025, self.output.repeat_key)
        for name in ("Backspace", "e"):
            self.click("LShift")
            self.output.reset_mock()
            self.state.press(name)
            repeat = self.schedule.call_args.args[1]
            repeat()
            repeat()
            self.output.key_up.assert_not_called()
            self.state.release()
            repeat()
            events = [c for c in self.output.method_calls if c[0] in {"key_down", "repeat_key", "key_up", "hold"}]
            self.assertEqual(events, [call.key_down(name, ["LShift"]), call.repeat_key(), call.repeat_key(),
                                      call.key_up(), call.hold("LShift", False)])

    def test_windows_holds_scan_code_until_release_or_reset(self) -> None:
        from screen_keyboard.windows import key_fields
        from utils.windows_input import KEYUP

        # Use the real Windows backend and packet builder, recording only the user32 calls.
        output = WindowsOutput.__new__(WindowsOutput)
        output.api = Mock()
        output.api.GetForegroundWindow.return_value = 10
        output.api.GetAsyncKeyState.return_value = output.api.GetKeyState.return_value = 0
        output.owned, output.chord = [], []
        with (patch.object(output, "send_packets") as send,
              patch.object(output, "repeat_timing", return_value=(.5, 1 / 30))):
            self.state = KeyboardState(output, self.schedule, Mock(), Mock())
            for name, finish in (("Backspace", self.state.release), ("e", self.state.reset)):
                send.reset_mock()
                self.click("LShift")
                self.schedule.reset_mock()
                self.state.press(name)
                repeat = self.schedule.call_args.args[1]
                downs = send.call_args.args[0]
                self.assertEqual([(p.data.keyboard.scan, p.data.keyboard.flags) for p in downs],
                                 [key_fields(k)[:2] for k in ("LShift", name)])
                send.assert_called_once()
                repeat()
                repeat()
                for repeated in send.call_args_list[1:]:
                    self.assertEqual([(p.data.keyboard.scan, p.data.keyboard.flags) for p in repeated.args[0]],
                                     [key_fields(name)[:2]])
                finish()
                self.state.release()
                repeat()
                self.assertEqual(send.call_count, 4)
                ups = send.call_args.args[0]
                self.assertEqual([(p.data.keyboard.scan, p.data.keyboard.flags) for p in ups],
                                 [(key_fields(k)[0], key_fields(k)[1] | KEYUP) for k in (name, "LShift")])

    def test_windows_system_repeat_timing(self) -> None:
        from screen_keyboard.windows import (
            FKF_FILTERKEYSON, SPI_GETFILTERKEYS, SPI_GETKEYBOARDDELAY, SPI_GETKEYBOARDSPEED,
        )

        output = WindowsOutput.__new__(WindowsOutput)
        output.api = Mock()
        settings = {SPI_GETKEYBOARDDELAY: 1, SPI_GETKEYBOARDSPEED: 31}
        filters = {"flags": 0, "delay": 650, "interval": 75}

        def query(action, size, pointer, flags):
            if action == SPI_GETFILTERKEYS:
                for name, value in filters.items():
                    setattr(pointer._obj, name, value)
            else:
                pointer._obj.value = settings[action]
            return True

        output.api.SystemParametersInfoW.side_effect = query
        self.assertEqual(output.repeat_timing(), (.5, 1 / 30))
        filters["flags"] = FKF_FILTERKEYSON
        self.assertEqual(output.repeat_timing(), (.65, .075))
        filters["interval"] = 0
        self.assertIsNone(output.repeat_timing())

    def test_keypad_and_failed_save(self) -> None:
        self.output.locks.return_value["NumLock"] = False
        self.click("Numpad7")
        self.output.key_down.assert_called_with("NumpadHome", [])
        self.assertEqual(self.state.label("Numpad7", "7"), "Home")
        with patch.object(self.state.store, "update", side_effect=OSError("busy")), self.assertRaises(OSError):
            self.state.set_mode(LeftKeyMode.F1)
        self.assertFalse(self.state.adapted)
        self.assertIs(self.output.mode, LeftKeyMode.NATIVE)

    def test_mac_placement_uses_the_pointer_display(self) -> None:
        screen = ((-1200, -100), (1200, 900))
        size = (500, 200)
        self.assertEqual(mac_frame_near_pointer((-900, 500), screen, size), ((-884, 284), size))
        self.assertEqual(mac_frame_near_pointer((-10, -90), screen, size), ((-526, -74), size))
        self.assertEqual(mac_frame_near_pointer((-10, -90), screen, (1500, 950)),
                         ((-1192, -92), (1184, 884)))

    def test_windows_and_mac_grid(self) -> None:
        for mac, rows, extended in [(False, ROWS, EXTENDED_KEYS), (True, MAC_ROWS, MAC_EXTENDED)]:
            self.assertTrue(all(sum(units for _, _, units in row) == 16 for row in rows))
            for scale in [1, 1.5, 2]:
                width, height = (round(n * scale) for n in DEFAULT_SIZE)
                basic = frames(width, height, scale, False, False, mac)
                for before, line, after in (("settings", "after_settings", "extended"),
                                            ("numpad", "after_numpad", "reset")):
                    self.assertLess(basic[before][0] + basic[before][2], basic[line][0])
                    self.assertLess(basic[line][0] + basic[line][2], basic[after][0])
                wide = panel_width(width, True, scale)
                full = frames(wide, height + round(30 * scale), scale, True, True, mac)
                self.assertEqual(basic["Space"], full["Space"])
                for bounds in (basic, full):
                    for name, (_, y, _, h) in bounds.items():
                        if name != "footer":
                            self.assertLessEqual(y + h, bounds["footer"][1], name)
                self.assertEqual(panel_width(wide, False, scale), width)
                for name, _ in extended:
                    self.assertIn(name, full)
                    self.assertNotIn(name, basic)
                self.assertEqual("Fn" in full, mac)
                self.assertEqual("ScrollLock" in full, not mac)
                self.assertEqual("AppsKey" in full, not mac)

    def test_bottom_keys_meet_the_drag_strip(self) -> None:
        for mac, rows, extras in ((False, ROWS, EXTENDED_KEYS), (True, MAC_ROWS, MAC_EXTENDED)):
            for scale in (1, 1.25, 1.5, 2):
                for width, height, footer in ((426, 166, 10.5), (900, 301, 12)):
                    for expanded in (False, True):
                        for numpad in (False, True):
                            bounds = frames(round(width * scale), round(height * scale), scale, expanded, numpad, mac)
                            _, top, _, h = bounds["footer"]
                            self.assertEqual(h, round(footer * scale))
                            self.assertEqual(top + h, round(height * scale))
                            bottom_keys = [key[0] for key in (extras if expanded else rows[-1])]
                            if numpad and not expanded:
                                bottom_keys.extend(("Numpad0", "NumpadDot", "NumpadEnter"))
                            for key in bottom_keys:
                                _, y, _, key_height = bounds[key]
                                self.assertEqual(y + key_height, top, key)

    @unittest.skipUnless(sys.platform == "win32", "Windows input packets")
    def test_windows_layer_events_and_owned_key_cleanup(self) -> None:
        from screen_keyboard.windows import key_fields
        from utils.windows_input import KEYUP

        output = WindowsOutput()
        events = []

        def record(packets):
            for packet in packets:
                key = packet.data.keyboard
                events.append((key.scan, key.flags, key.vk))

        def expected(name, down):
            scan, flags, vk = key_fields(name)
            return scan, flags if down else flags | KEYUP, vk

        with (patch.object(output, "target", return_value=10) as foreground,
              patch.object(output, "locks", return_value={"NumLock": True}),
              patch.object(output.api, "GetAsyncKeyState", return_value=0) as physical,
              patch.object(output, "send_packets", side_effect=record)):
            self.state = KeyboardState(output, self.schedule, Mock(), Mock())
            self.click("Layer")
            self.assertEqual(events, [expected("CapsLock", True), expected("CapsLock", False)])
            self.state.set_mode(LeftKeyMode.CAPS)
            for mode, next_mode in ((LeftKeyMode.CAPS, LeftKeyMode.F1), (LeftKeyMode.F1, LeftKeyMode.F24),
                                    (LeftKeyMode.F24, LeftKeyMode.NATIVE)):
                events.clear()
                self.click("Layer")
                self.assertEqual(events, [expected(mode.value, True)])
                self.state.set_mode(next_mode)
                self.assertEqual(events, [expected(mode.value, True), expected(mode.value, False)])
            self.state.set_mode(LeftKeyMode.F24)
            for modifiers in ([], ["LShift"], ["RAlt"], ["RShift", "LAlt"]):
                events.clear()
                chord = ["F24", *modifiers, "2"]
                for name in ["Layer", *modifiers, "2"]:
                    self.click(name)
                self.assertEqual(events, [expected(n, True) for n in chord] + [expected(n, False) for n in reversed(chord)])
                self.assertFalse(output.owned)
            events.clear()
            self.click("Layer")
            physical.return_value = -32768
            self.click("LAlt")  # The user already holds this key.
            foreground.return_value = 20
            self.state.check_target()
            self.assertEqual(events, [expected("F24", True), expected("F24", False)])
            events.clear()
            self.click("language")
            self.assertEqual(events, [expected("F24", True), expected("F24", False)])

    @unittest.skipUnless(sys.platform == "win32", "Windows input packets")
    def test_native_key_positions(self) -> None:
        from screen_keyboard.windows import key_fields
        for name in [*(n for row in ROWS for n, _, _ in row), *(n for n, _ in EXTENDED_KEYS),
                     *(row[0] for row in NUMPAD_KEYS), *(nav for nav, _ in NUMPAD_NAVIGATION.values())]:
            if name not in {"Layer", "language"}:
                self.assertTrue(key_fields(name)[0], name)
        self.assertNotEqual(key_fields("Enter"), key_fields("NumpadEnter"))
        self.assertNotEqual(key_fields("Home"), key_fields("NumpadHome"))
        self.assertNotEqual(key_fields("LControl"), key_fields("RControl"))

    def test_mac_event_routing_and_visible_positions(self) -> None:
        # Exercise the real lookup and modifier logic with recording Cocoa/Quartz endpoints.
        package = "screen_keyboard"
        quartz = Mock(kCGHIDEventTap=0, kCGSessionEventTap=1, kCGEventFlagMaskAlphaShift=1 << 16,
                      kCGEventFlagMaskNumericPad=1 << 21)
        quartz.CGEventSourceFlagsState.return_value = 0
        appkit = Mock()
        appkit.NSEvent.keyRepeatDelay.return_value = .5
        appkit.NSEvent.keyRepeatInterval.return_value = .025
        imports = {"Quartz": quartz, "AppKit": appkit, f"{package}.input_sources": Mock()}
        path = ROOT / "tools/input-and-text/screen_keyboard/macos.py"
        spec = importlib.util.spec_from_file_location(f"{package}.mac_backend_test", path)
        assert spec and spec.loader
        backend = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, imports):
            spec.loader.exec_module(backend)
            event = quartz.CGEventCreateKeyboardEvent.return_value
            for down, kind in ((True, quartz.kCGEventKeyDown), (False, quartz.kCGEventKeyUp)):
                backend.post(57, down, 0, quartz.kCGHIDEventTap)
                quartz.CGEventSetType.assert_called_with(event, kind)
                quartz.CGEventPost.assert_called_with(quartz.kCGHIDEventTap, event)
            backend.post(14, True, 0, quartz.kCGSessionEventTap, repeat=True)
            quartz.CGEventSetIntegerValueField.assert_called_once_with(event, quartz.kCGKeyboardEventAutorepeat, 1)
        for name in [*(n for row in MAC_ROWS for n, _, _ in row), *(n for n, _ in MAC_EXTENDED),
                     *(row[0] for row in NUMPAD_KEYS), *(nav for nav, _ in NUMPAD_NAVIGATION.values())]:
            if name not in {"Layer", "NumLock", "NumpadClear", "language", "Screenshot", *backend.DIRECT}:
                self.assertIsInstance(backend.keycode(name), int, name)
        out = backend.MacOutput(Mock())
        with patch.object(backend, "post") as post:
            out.hold("Fn", True)
            post.assert_called_with(63, True, 1 << 23, 1, modifier=True)
            out.reset()
            out.mode = LeftKeyMode.F1
            out.hold("Layer", True)
            self.assertIsNone(out.key_down("F1", []))
            out.key_up()
            out.reset()
            self.assertEqual(post.call_args_list[-2:], [call(122, True, 0, 0), call(122, False, 0, 0)])
            out.mode = LeftKeyMode.CAPS
            out.hold("Layer", True)
            post.assert_called_with(57, True, 0, 0)
            out.hold("LAlt", True)
            self.assertEqual(out.held, ["Layer", "LAlt"])
            self.assertIsNone(out.key_down("a", ["LAlt"]))
            out.key_up()
            flags = (1 << 19) | 0x20
            self.assertEqual(post.call_args_list[-2:], [call(0, True, flags, 0), call(0, False, flags, 0)])
            quartz.CGEventSourceFlagsState.return_value = 1 << 20
            repeat = out.key_down("NumpadEnter", ["LAlt"])
            assert repeat is not None
            self.assertEqual((repeat.delay, repeat.interval), (.5, .025))
            repeat.send()
            post.assert_called_with(76, True, (1 << 20) | (1 << 21), 1, repeat=True)
            post.reset_mock()
            out.reset()
            self.assertEqual(post.call_args_list, [call(76, False, (1 << 20) | (1 << 21), 1),
                             call(58, False, 0, 0, modifier=True), call(57, False, 0, 0)])
            self.assertFalse(out.held)

    @unittest.skipUnless(sys.platform == "darwin", "macOS text input services")
    def test_input_source_switch_goes_to_the_target_on_every_toggle(self) -> None:
        import plistlib
        from screen_keyboard import input_sources as sources

        bridge = Mock()
        bridge.kCFMessagePortSuccess = 0
        bridge.CFPropertyListCreateData.return_value = (b"request", None)
        bridge.CFMessagePortSendRequest.return_value = (0, plistlib.dumps({"tsmInputModeReplyToServerErrorKey": 0}))
        flatten = Mock(side_effect=lambda source, _: (True, {"source": source}))
        remote = Mock(return_value="target port")
        with (patch.object(sources, "frontmost_target", return_value=123),
              patch.dict(sources._tsm, _CreateFlattenedInputSource=flatten, CFMessagePortCreatePerProcessRemote=remote),
              patch.object(sources, "CoreFoundation", bridge),
              patch.object(sources, "_TIS") as carbon):
            for source in (1, 2, 1, 2):
                sources._select(str(source), source)
                remote.assert_called_with(None, "com.apple.tsm.portname", 123)
                flatten.assert_called_with(source, None)
            self.assertEqual(bridge.CFMessagePortSendRequest.call_count, 4)
            bridge.CFMessagePortSendRequest.return_value = (0, plistlib.dumps({"tsmInputModeReplyToServerErrorKey": -1}))
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                sources._select("1", 1)
            carbon.TISSelectInputSource.assert_not_called()

            remote.return_value = None
            carbon.TISSelectInputSource.return_value = 0
            with patch.object(sources, "current_input_source", return_value="1"):
                sources._select("1", 1)
            carbon.TISSelectInputSource.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
