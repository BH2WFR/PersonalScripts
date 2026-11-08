"""Keyboard utility and viewer integration tests without live input hooks.

Requirements: project runtime (PyYAML/pathspec for launcher checks).
Run: conda run -n base python -m unittest discover -s test -p "test_keyboard*.py"
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import *


def load_module(name: str, relative: str) -> ModuleType:
    """Load a repository entry by path without invoking its main function."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


entry = load_module("keyboard_test_entry", "tools/others/keyboard-hook-viewer.py")
app = entry.load_app()
models = importlib.import_module(f"{entry.PACKAGE_NAME}.models")
runtime = importlib.import_module(f"{entry.PACKAGE_NAME}.runtime")
windows = importlib.import_module(f"{entry.PACKAGE_NAME}.windows")
api = importlib.import_module(f"{entry.PACKAGE_NAME}.api")
launcher = load_module("keyboard_test_launcher", "run-script.py")
compiler = load_module("keyboard_test_compiler", "compile-script.py")


class KeyboardNamesTests(unittest.TestCase):
    """Public mappings preserve physical identity while supporting hotkeys."""

    def test_modifier_sides_and_generic_matching(self) -> None:
        for alias, expected in (("RControl", "rcontrol"), ("Control_R", "right_ctrl"),
                                ("rctrl", "right_ctrl"), ("Shift_L", "left_shift"),
                                ("cmd_r", "right_super"), ("Alt_R", "right_alt")):
            with self.subTest(alias=alias):
                self.assertEqual(Keyboard.normalize_name(alias), expected)
        self.assertEqual(Keyboard.normalize_name("rctrl", collapse_modifiers=True), "ctrl")
        self.assertEqual(Keyboard.normalize_name("Caps_Lock"), "caps_lock")
        self.assertEqual(Keyboard.normalize_name("caps"), "caps_lock")
        self.assertEqual(Keyboard.normalize_name("F12"), "f12")

    def test_enter_and_keypad_enter_are_distinct(self) -> None:
        main = Keyboard.windows_scan_code("enter")
        keypad = Keyboard.windows_scan_code("KP_Enter")
        self.assertEqual(main, WindowsScanCode(0x1C))
        self.assertEqual(keypad, WindowsScanCode(0x1C, ScanCodePrefix.E0))
        self.assertEqual(Keyboard.windows_key_name(0x0D, main), "enter")
        self.assertEqual(Keyboard.windows_key_name(0x0D, keypad), "kp_enter")
        self.assertEqual(Keyboard.windows_virtual_key("kp_enter"), 0x0D)

    def test_navigation_and_keypad_codes_are_distinct(self) -> None:
        self.assertEqual(Keyboard.windows_scan_code("home"), WindowsScanCode.from_value(0xE047))
        self.assertEqual(Keyboard.windows_scan_code("kp7"), WindowsScanCode.from_value(0x0047))
        self.assertEqual(Keyboard.windows_scan_code("rctrl"), WindowsScanCode.from_value(0xE01D))
        self.assertEqual(Keyboard.windows_scan_code("lctrl"), WindowsScanCode.from_value(0x001D))
        self.assertEqual(Keyboard.windows_scan_name(WindowsScanCode(0x1E)), "a")

    def test_virtual_keys_and_unknowns(self) -> None:
        self.assertEqual(Keyboard.windows_virtual_key("right_ctrl"), 0xA3)
        self.assertEqual(Keyboard.windows_virtual_key("left_shift"), 0xA0)
        self.assertEqual(Keyboard.windows_virtual_key("F24"), 0x87)
        self.assertEqual(Keyboard.windows_virtual_key("a"), 0x41)
        self.assertIsNone(Keyboard.windows_virtual_key("not_a_key"))
        self.assertIsNone(Keyboard.windows_scan_code("pause"))
        self.assertEqual(Keyboard.windows_scan_name(WindowsScanCode(0xFF)), "scan(0x00FF)")

    def test_macos_hid_and_x11_are_distinct_code_spaces(self) -> None:
        self.assertEqual(Keyboard.macos_key_name(0x3E), "right_ctrl")
        self.assertEqual(Keyboard.macos_virtual_key("right_ctrl"), 0x3E)
        self.assertEqual(Keyboard.macos_virtual_key("a"), 0)
        self.assertEqual(Keyboard.hid_usage_name(0xE4), "right_ctrl")
        self.assertEqual(Keyboard.hid_usage_name(0x58), "kp_enter")
        self.assertEqual(Keyboard.x11_keysym_name("right_ctrl"), "Control_R")
        self.assertEqual(Keyboard.x11_keysym_name("f12"), "F12")
        self.assertEqual(Keyboard.x11_keysym_name("kp7"), "KP_7")

    def test_scan_word_validation_and_hook_flags(self) -> None:
        for value in (0, 0x1C, 0xE01C, 0xE11D):
            self.assertEqual(WindowsScanCode.from_value(value).value, value)
        for value in (-1, 0x10000, 0x1234, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                WindowsScanCode.from_value(value)
        with self.assertRaises(ValueError):
            WindowsScanCode(256)
        self.assertEqual(WindowsScanCode.from_hook(0x1D, 0x81).value, 0xE01D)
        self.assertEqual(WindowsScanCode.from_hook(0x45, 0).prefix, ScanCodePrefix.NONE)

    def test_high_function_keys_use_windows_scan_codes_not_vk_or_hid(self) -> None:
        for number, value in zip(range(13, 25), (*range(0x64, 0x6F), 0x76)):
            with self.subTest(number=number):
                name = f"f{number}"
                code = WindowsScanCode.from_value(value)
                self.assertEqual(Keyboard.windows_scan_code(name), code)
                self.assertEqual(Keyboard.windows_scan_name(code), name)
                self.assertEqual(Keyboard.windows_virtual_key(name), number + 0x6F)
                self.assertEqual(Keyboard.hid_usage_name(number + 0x5B), name)
        self.assertEqual(Keyboard.windows_scan_name(WindowsScanCode(0x6F)), "scan(0x006F)")
        self.assertEqual(Keyboard.windows_key_name(0x76), "f7")

    def test_regional_key_names_and_scan_words(self) -> None:
        cases = (
            ("iso_extra", 0x0056, "non_us_backslash"),
            ("jis_ro", 0x0073, "international1"),
            ("jis_yen", 0x007D, "international3"),
            ("katakana_hiragana", 0x0070, "kana"),
            ("henkan", 0x0079, "convert"),
            ("muhenkan", 0x007B, "nonconvert"),
            ("hangeul", 0x0072, "hangul"),
            ("hanja", 0x0071, "hanja"),
            ("hangul_legacy", 0x00F2, "hangul_legacy"),
            ("hanja_legacy", 0x00F1, "hanja_legacy"),
            ("katakana", 0x0078, "katakana"),
            ("hiragana", 0x0077, "hiragana"),
            ("international6", 0x005C, "international6"),
        )
        for alias, value, name in cases:
            with self.subTest(alias=alias):
                code = WindowsScanCode.from_value(value)
                self.assertEqual(Keyboard.windows_scan_code(alias), code)
                self.assertEqual(Keyboard.windows_scan_name(code), name)
                self.assertEqual(Keyboard.windows_scan_code(name), code)
        self.assertEqual(Keyboard.windows_scan_code("right_alt"), WindowsScanCode.from_value(0xE038))
        self.assertEqual(Keyboard.windows_scan_code("right_ctrl"), WindowsScanCode.from_value(0xE01D))
        self.assertEqual(WindowsScanCode.from_hook(0xF2, 0).value, 0x00F2)

    def test_shared_regional_positions_do_not_overwrite_default_names(self) -> None:
        for alias, value, default in (
            ("non_us_hash", 0x002B, "\\"),
            ("hankaku_zenkaku", 0x0029, "`"),
            ("eisu", 0x003A, "caps_lock"),
            ("lang5", 0x0076, "f24"),
        ):
            with self.subTest(alias=alias):
                code = WindowsScanCode.from_value(value)
                self.assertEqual(Keyboard.windows_scan_code(alias), code)
                self.assertEqual(Keyboard.windows_scan_name(code), default)
        self.assertIsNone(Keyboard.windows_scan_code("oem_102"))
        self.assertIsNone(Keyboard.windows_scan_code("kana_or_hangul"))
        self.assertEqual(Keyboard.windows_scan_name(WindowsScanCode.from_value(0xE076)), "scan(0xE076)")

    def test_ime_virtual_keys_require_context_to_disambiguate(self) -> None:
        self.assertEqual(Keyboard.windows_key_name(0x15), "kana_or_hangul")
        self.assertEqual(Keyboard.windows_key_name(0x19), "kanji_or_hanja")
        for name, vk in (("kana", 0x15), ("hangul", 0x15), ("hangeul", 0x15),
                         ("hanja", 0x19), ("kanji", 0x19), ("henkan", 0x1C),
                         ("muhenkan", 0x1D), ("ime_on", 0x16), ("ime_off", 0x1A),
                         ("ime_accept", 0x1E), ("ime_mode_change", 0x1F)):
            with self.subTest(name=name):
                self.assertEqual(Keyboard.windows_virtual_key(name), vk)
        for vk, scan, name in ((0x15, 0x70, "kana"), (0x15, 0x72, "hangul"),
                               (0x15, 0xF2, "hangul"), (0x19, 0x71, "hanja"),
                               (0x19, 0xF1, "hanja")):
            with self.subTest(vk=vk, scan=scan):
                self.assertEqual(Keyboard.windows_key_name(vk, WindowsScanCode(scan)), name)
        self.assertEqual(Keyboard.windows_key_name(0x15, WindowsScanCode(0x71)), "kana_or_hangul")
        self.assertEqual(Keyboard.windows_key_name(0x87, WindowsScanCode(0x76)), "f24")

    def test_oem_virtual_key_keeps_layout_printable_fallback(self) -> None:
        self.assertEqual(Keyboard.windows_virtual_key("VK_OEM_102"), 0xE2)
        with patch("utils.keyboard._windows_printable_name", return_value="<"):
            self.assertEqual(Keyboard.windows_key_name(0xE2), "<")
        with patch("utils.keyboard._windows_printable_name", return_value=None):
            self.assertEqual(Keyboard.windows_key_name(0xE2), "oem_102")

    def test_international_hid_usages_remain_distinct_from_scan_words(self) -> None:
        for usage, name in (
            (0x64, "non_us_backslash"), (0x85, "kp,"),
            (0x87, "international1"), (0x88, "kana"), (0x89, "international3"),
            (0x8A, "convert"), (0x8B, "nonconvert"), (0x8C, "international6"),
            (0x8D, "international7"), (0x8E, "international8"), (0x8F, "international9"),
            (0x90, "hangul"), (0x91, "hanja"), (0x92, "katakana"),
            (0x93, "hiragana"), (0x94, "zenkaku_hankaku_usb"), (0x98, "lang9"),
        ):
            with self.subTest(usage=usage):
                self.assertEqual(Keyboard.hid_usage_name(usage), name)
        self.assertIsNone(Keyboard.windows_scan_code("international7"))
        self.assertIsNone(Keyboard.windows_scan_code("lang9"))
        self.assertNotEqual(Keyboard.hid_usage_name(0x73), Keyboard.windows_scan_name(WindowsScanCode(0x73)))

    def test_extended_media_keys_and_keypad_extras(self) -> None:
        for name, value in (
            ("media_previous", 0xE010), ("media_next", 0xE019),
            ("media_volume_mute", 0xE020), ("media_play_pause", 0xE022),
            ("media_stop", 0xE024), ("media_volume_down", 0xE02E),
            ("media_volume_up", 0xE030), ("browser_home", 0xE032),
            ("browser_search", 0xE065), ("browser_favorites", 0xE066),
            ("browser_refresh", 0xE067), ("browser_stop", 0xE068),
            ("browser_forward", 0xE069), ("browser_back", 0xE06A),
            ("launch_app1", 0xE06B), ("launch_app2", 0xE021),
            ("launch_mail", 0xE06C), ("launch_media_select", 0xE06D),
            ("power", 0xE05E), ("sleep", 0xE05F), ("wake", 0xE063),
            ("kp=", 0x0059), ("kp,", 0x007E),
        ):
            with self.subTest(name=name):
                code = WindowsScanCode.from_value(value)
                self.assertEqual(Keyboard.windows_scan_code(name), code)
                self.assertEqual(Keyboard.windows_scan_name(code), name)

    def test_regional_tables_are_portable_without_native_api_calls(self) -> None:
        with patch("utils.keyboard.sys.platform", "linux"):
            self.assertEqual(Keyboard.windows_scan_code("henkan"), WindowsScanCode(0x79))
            self.assertEqual(Keyboard.windows_scan_name(WindowsScanCode(0xF2)), "hangul_legacy")
            self.assertEqual(Keyboard.windows_virtual_key("hangul"), 0x15)
            self.assertEqual(Keyboard.windows_key_name(0x15, WindowsScanCode(0x70)), "kana")
            self.assertEqual(Keyboard.windows_key_name(0xE2), "oem_102")
            self.assertEqual(Keyboard.hid_usage_name(0x94), "zenkaku_hankaku_usb")

    @unittest.skipUnless(sys.platform == "win32", "Requires the native Windows key mapper")
    def test_function_scan_codes_against_native_windows(self) -> None:
        # Read-only conversion: never installs hooks, switches layout or sends input.
        function = ctypes.WinDLL("user32", use_last_error=True).MapVirtualKeyW
        function.argtypes = [ctypes.c_uint, ctypes.c_uint]
        function.restype = ctypes.c_uint
        map_vsc_to_vk_ex = 3
        for number in range(13, 25):
            with self.subTest(number=number):
                code = Keyboard.windows_scan_code(f"f{number}")
                assert code is not None
                self.assertEqual(function(code.value, map_vsc_to_vk_ex), number + 0x6F)


class ViewerEventsTests(unittest.TestCase):
    """Synthetic native messages exercise the real dispatch and callback chain."""

    def setUp(self) -> None:
        runtime._held.clear()
        runtime._physical_held.clear()
        runtime._toggled.clear()
        runtime._hotkeys.clear()
        runtime._on_key_cb = None
        runtime._on_mouse_cb = None
        for name in ("_check_win_change", "_print_key", "_print_mouse", "_print_scroll", "_print_magnify"):
            mocker = patch.object(runtime.ui, name)
            mocker.start()
            self.addCleanup(mocker.stop)

    def tearDown(self) -> None:
        runtime._on_key_cb = None
        runtime._on_mouse_cb = None
        runtime._hotkeys.clear()
        runtime._held.clear()
        runtime._physical_held.clear()
        runtime._toggled.clear()

    def test_extended_scan_and_flags_reach_callback(self) -> None:
        callback = Mock()
        runtime._on_key_cb = callback
        packed = windows._pack_keyboard(0x0D, 0x1C, 0x11)
        windows._dispatch_keyboard(runtime, packed, windows._WM_SYSKEYDOWN)
        event = callback.call_args.args[0]
        self.assertEqual((event.name, event.raw_name, event.raw_vk), ("kp_enter", "kp_enter", 0x0D))
        self.assertEqual(event.scan_code.value, 0xE01C)
        self.assertEqual(event.raw_flags, 0x11)
        self.assertTrue(event.pressed)
        windows._dispatch_keyboard(runtime, windows._pack_keyboard(0x0D, 0x1C, 0x81), windows._WM_KEYUP)
        self.assertFalse(callback.call_args.args[0].pressed)
        self.assertEqual(callback.call_args.args[0].raw_flags, 0x81)

    def test_legacy_language_release_preserves_full_scan_byte(self) -> None:
        callback = Mock()
        runtime._on_key_cb = callback
        packed = windows._pack_keyboard(0x15, 0xF2, 0x80)
        windows._dispatch_keyboard(runtime, packed, windows._WM_KEYUP)
        callback.assert_called_once()
        event = callback.call_args.args[0]
        self.assertEqual((event.name, event.raw_name, event.raw_vk), ("hangul", "hangul", 0x15))
        self.assertEqual(event.scan_code.value, 0x00F2)
        self.assertEqual(event.raw_flags, 0x80)
        self.assertFalse(event.pressed)

    def test_windows_wheel_steps_are_symmetric_and_keep_small_deltas(self) -> None:
        for raw, expected in ((0, 0), (1, 1), (60, 1), (119, 1), (120, 1),
                              (121, 1), (239, 1), (240, 2), (360, 3)):
            for sign in (1, -1):
                with self.subTest(raw=raw * sign):
                    # Match the hook's 48-bit unsigned auxiliary representation.
                    packed = (raw * sign) & 0xFFFFFFFFFFFF
                    self.assertEqual(windows._wheel_steps(packed), expected * sign)

    def test_windows_wheel_messages_reach_display_and_callback(self) -> None:
        native = Mock()
        # Build the real processor with fake API handles; never start a hook.
        with patch.object(windows, "_OS", "win32"), \
                patch.object(ctypes, "windll", native, create=True), \
                patch.object(ctypes, "WINFUNCTYPE", return_value=ctypes.c_void_p, create=True):
            hook = windows.create_hook(runtime)
        assert hook is not None
        callback = Mock()
        runtime._on_mouse_cb = callback
        for message in (windows._WM_MOUSEHWHEEL, windows._WM_MOUSEWHEEL):
            for raw, steps in ((1, 1), (60, 1), (120, 1), (-1, -1), (-60, -1),
                               (-120, -1), (239, 1), (-239, -1), (240, 2),
                               (-240, -2), (32767, 273), (-32768, -273), (0, 0)):
                with self.subTest(message=message, raw=raw):
                    callback.reset_mock()
                    runtime.ui._print_scroll.reset_mock()
                    packed = message | ((raw & 0xFFFFFFFFFFFF) << 16)
                    hook._process_message(0, ctypes.c_ssize_t(packed).value)
                    if steps == 0:
                        callback.assert_not_called()
                        runtime.ui._print_scroll.assert_not_called()
                        continue
                    expected = (steps, 0) if message == windows._WM_MOUSEHWHEEL else (0, steps)
                    raw_delta = (raw, 0) if message == windows._WM_MOUSEHWHEEL else (0, raw)
                    runtime.ui._print_scroll.assert_called_once_with(*expected, raw_delta=raw_delta)
                    callback.assert_called_once()
                    event = callback.call_args.args[0]
                    self.assertTrue(event.is_scroll)
                    self.assertEqual((event.scroll_dx, event.scroll_dy), expected)
        native.user32.SetWindowsHookExW.assert_not_called()
        native.user32.SendInput.assert_not_called()

    def test_scroll_without_native_metadata_keeps_portable_callback(self) -> None:
        callback = Mock()
        runtime._on_mouse_cb = callback
        runtime._emit_scroll(-2, 3)
        runtime.ui._print_scroll.assert_called_once_with(-2, 3, raw_delta=None)
        callback.assert_called_once_with(models.MouseEvent(scroll_dx=-2, scroll_dy=3, is_scroll=True))

    def test_macos_smooth_scroll_uses_precise_values_even_with_zero_line_delta(self) -> None:
        macos = importlib.import_module(f"{entry.PACKAGE_NAME}.macos")
        quartz = Mock()
        quartz.CGEventMaskBit.return_value = 0
        quartz.CGEventGetLocation.return_value = (0, 0)
        with patch.dict(sys.modules, {"Quartz": quartz}), patch.object(macos, "_OS", "darwin"):
            hook = macos.create_hook(runtime)
        assert hook is not None
        callback = Mock()
        runtime._on_mouse_cb = callback

        # Start, steady movement, acceleration, diagonal/momentum, phase end.
        for line_dy, precise in (
            (1, (0.0, 2.5)), (0, (0.0, 2.5)), (0, (0.0, 7.75)),
            (0, (0.125, -0.25)), (-1, (0.0, -12.5)), (0, (0.0, 0.0)),
            (1, None),  # Unconvertible CGEvent retains the legacy fallback.
        ):
            with self.subTest(line_dy=line_dy, precise=precise):
                fields = {quartz.kCGScrollWheelEventDeltaAxis1: line_dy}
                quartz.CGEventGetIntegerValueField.side_effect = lambda event, field: fields.get(field, 0)
                scroll_event = Mock() if precise is not None else None
                if precise is not None and scroll_event is not None:
                    scroll_event.scrollingDeltaX.return_value = precise[0]
                    scroll_event.scrollingDeltaY.return_value = precise[1]
                quartz.NSEvent.eventWithCGEvent_.return_value = scroll_event
                callback.reset_mock()
                runtime.ui._print_scroll.reset_mock()
                hook._handle_mouse_event(quartz.kCGEventScrollWheel, object())
                runtime.ui._print_scroll.assert_called_once_with(0, line_dy, raw_delta=precise)
                callback.assert_called_once_with(models.MouseEvent(scroll_dy=line_dy, is_scroll=True))
        quartz.CGEventTapCreate.assert_not_called()

    def test_macos_native_pinch_packets_preserve_delta_and_phase(self) -> None:
        macos = importlib.import_module(f"{entry.PACKAGE_NAME}.macos")
        quartz = Mock()
        quartz.CGEventMaskBit.return_value = 0
        with patch.dict(sys.modules, {"Quartz": quartz}), patch.object(macos, "_OS", "darwin"):
            hook = macos.create_hook(runtime)
        assert hook is not None
        quartz.CGEventMaskBit.assert_any_call(quartz.NSEventTypeGesture)
        quartz.CGEventMaskBit.assert_any_call(quartz.NSEventTypeMagnify)
        runtime._on_mouse_cb = Mock()
        runtime._on_key_cb = Mock()

        # Generic CG gesture packets must be decoded as NSEvent magnify events.
        for packet_type in (quartz.NSEventTypeGesture, quartz.NSEventTypeMagnify):
            for delta, phase in ((0.0, 1), (0.025, 4), (-0.015, 4), (0.0, 8), (0.0, 16)):
                with self.subTest(packet_type=packet_type, delta=delta, phase=phase):
                    native_event = object()
                    gesture = Mock()
                    gesture.type.return_value = quartz.NSEventTypeMagnify
                    gesture.magnification.return_value = delta
                    gesture.phase.return_value = phase
                    quartz.NSEvent.eventWithCGEvent_.return_value = gesture
                    runtime.ui._print_magnify.reset_mock()
                    self.assertIs(hook._handle(None, packet_type, native_event, None), native_event)
                    runtime.ui._print_magnify.assert_called_once_with(delta, models.GesturePhase(phase))

        # Never call magnification on a non-magnify NSEvent or failed conversion.
        for other_type in (quartz.NSEventTypeRotate, quartz.NSEventTypeSwipe, None):
            gesture = Mock() if other_type is not None else None
            if gesture is not None:
                gesture.type.return_value = other_type
            quartz.NSEvent.eventWithCGEvent_.return_value = gesture
            runtime.ui._print_magnify.reset_mock()
            hook._handle(None, quartz.NSEventTypeGesture, object(), None)
            runtime.ui._print_magnify.assert_not_called()
            if gesture is not None:
                gesture.magnification.assert_not_called()
        runtime.ui._print_scroll.assert_not_called()
        runtime._on_mouse_cb.assert_not_called()
        runtime._on_key_cb.assert_not_called()
        quartz.CGEventTapCreate.assert_not_called()

    def test_sided_modifiers_and_auto_repeat_do_not_lose_held_state(self) -> None:
        trigger = Mock()
        runtime._hotkeys.append(models.Hotkey("ctrl+a", trigger))
        runtime._emit_key("left_ctrl", True)
        runtime._emit_key("right_ctrl", True)
        runtime._emit_key("left_ctrl", False)
        runtime._emit_key("a", True)
        runtime._emit_key("a", True)
        trigger.assert_called_once()
        runtime._emit_key("a", False)
        runtime._emit_key("right_ctrl", False)
        runtime._emit_key("a", True)
        trigger.assert_called_once()

    def test_caps_shift_hotkey_and_scan_metadata(self) -> None:
        trigger = Mock()
        callback = Mock()
        runtime._on_key_cb = callback
        runtime._hotkeys.append(models.Hotkey("caps+shift+a", trigger))
        runtime._emit_key("caps_lock", True, 0x14, scan_code=WindowsScanCode(0x3A))
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(callback.call_args.args[0].scan_code.value, 0x3A)
        runtime._emit_key("right_shift", True)
        runtime._emit_key("a", True)
        trigger.assert_called_once()

    def test_import_platform_modules_and_help_have_no_monitor_side_effects(self) -> None:
        for name in ("macos", "x11", "devices", "api"):
            importlib.import_module(f"{entry.PACKAGE_NAME}.{name}")
        with patch.object(app.backend, "create_hook") as create, patch.object(app, "enumerate_devices") as devices:
            with patch.object(sys, "argv", ["keyboard-hook-viewer.py", "--help"]), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(entry.main(), 0)
            create.assert_not_called()
            devices.assert_not_called()
            self.assertIn("Requirements:", output.getvalue())

    def test_api_preserves_sides_for_input_controller(self) -> None:
        controller = Mock()
        with patch.object(api, "_CTRL", controller):
            api.press("rctrl")
            api.tap("KP_Enter")
        controller.press.assert_called_once_with("right_ctrl")
        controller.tap.assert_called_once_with("kp_enter")


class ViewerScrollDisplayTests(unittest.TestCase):
    """Check actual terminal output with and without Windows wheel metadata."""

    def test_windows_shows_one_raw_pair_and_cyan_direction(self) -> None:
        for steps, raw, direction in (
            ((0, -1), (0, -30), "down"), ((0, 1), (0, 120), "up"),
            ((1, 0), (120, 0), "right"), ((-1, 0), (-1, 0), "left"),
        ):
            with self.subTest(raw=raw), patch.object(runtime.ui.sys, "platform", "win32"), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                runtime.ui._print_scroll(*steps, raw_delta=raw)
            rendered = output.getvalue()
            self.assertIn(f"scroll ({raw[0]}, {raw[1]})", rendered)
            self.assertNotIn("delta", rendered)
            self.assertTrue(rendered.endswith(f" {FCyan}{direction}{CRst}\n"))

    def test_macos_precise_values_drive_direction_without_integer_rounding(self) -> None:
        for raw, label, direction in (
            ((0.0, 0.125), "0, 0.125", "up"),
            ((0.0, -18.5), "0, -18.5", "down"),
            ((0.125, 0.0), "0.125, 0", "left"),
            ((-0.25, 0.125), "-0.25, 0.125", "up+right"),
            ((0.0, 0.00001), "0, 1e-05", "up"),
        ):
            with self.subTest(raw=raw), patch.object(runtime.ui.sys, "platform", "darwin"), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                runtime.ui._print_scroll(0, 0, raw_delta=raw)
            self.assertIn(f"scroll ({label})", output.getvalue())
            self.assertTrue(output.getvalue().endswith(f" {FCyan}{direction}{CRst}\n"))

    def test_zero_native_delta_does_not_print_a_directionless_event(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runtime.ui._print_scroll(0, 0, raw_delta=(0.0, 0.0))
        self.assertEqual(output.getvalue(), "")

    def test_platform_directions_preserve_values_and_handle_both_axes(self) -> None:
        for platform in ("win32", "darwin", "linux"):
            right_sign = 1 if platform == "win32" else -1
            for dx, dy, direction, arrow in (
                (0, 1, "up", "↑"), (0, -1, "down", "↓"),
                (right_sign, 0, "right", "→"), (-right_sign, 0, "left", "←"),
                (right_sign, 2, "up+right", "↑→"),
                (-right_sign, -2, "down+left", "↓←"), (0, 0, "none", "-"),
            ):
                with self.subTest(platform=platform, dx=dx, dy=dy), \
                        patch.object(runtime.ui.sys, "platform", platform), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    runtime.ui._print_scroll(dx, dy)
                rendered = output.getvalue()
                self.assertIn(f"scroll ({dx}, {dy})", rendered)
                self.assertIn(arrow, rendered)
                self.assertTrue(rendered.endswith(f" {FCyan}{direction}{CRst}\n"))


class ViewerMagnifyDisplayTests(unittest.TestCase):
    """Native pinch has a signed delta and cyan direction/phase, not wheel steps."""

    def test_signed_magnification_and_phase_use_cyan(self) -> None:
        for delta, phase, label in (
            (0.025, models.GesturePhase.CHANGED, "zoom in phase=changed"),
            (-0.015, models.GesturePhase.CHANGED, "zoom out phase=changed"),
            (0.0, models.GesturePhase.BEGAN, "phase=began"),
            (0.0, models.GesturePhase.ENDED, "phase=ended"),
            (0.0, models.GesturePhase.CANCELLED, "phase=cancelled"),
            (0.0, models.GesturePhase.NONE, "phase=none"),
            (0.001, models.GesturePhase(64), "zoom in phase=0x40"),
        ):
            with self.subTest(delta=delta, phase=phase), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                runtime.ui._print_magnify(delta, phase)
            rendered = output.getvalue()
            self.assertIn(f"magnify ({delta:+g})", rendered)
            self.assertNotIn("scroll", rendered)
            self.assertTrue(rendered.endswith(f" {FCyan}{label}{CRst}\n"))


class ViewerDiscoveryTests(unittest.TestCase):
    """Use the actual repository configuration and compiler staging workflow."""

    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="keyboard-tests-", dir=ROOT / "tmp")
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        shutil.copy2(ROOT / "launcher-config.yaml", self.scratch / "launcher-config.yaml")

    def test_only_entry_is_listed_and_others_is_gray(self) -> None:
        config = launcher._load_launcher_config(str(self.scratch))
        self.assertEqual(launcher._highlight_subdirectory("others", config), f"{FGray}others/{CRst}")
        with patch.object(Environment, "find_bash", return_value=None), patch.object(Environment, "find_pwsh", return_value=None):
            listing = launcher.find_scripts(str(ROOT / "tools"), config)
        for paths in (listing, compiler.find_py_scripts(str(ROOT / "tools"))):
            normalized = [path.replace("\\", "/") for path in paths]
            self.assertIn("others/keyboard-hook-viewer.py", normalized)
            self.assertFalse(any(path.startswith("others/keyboard-hook-viewer/") for path in normalized))

    def test_linux_filter_paths_after_move(self) -> None:
        for gui in (LinuxGui.NO_GUI, LinuxGui.WAYLAND, LinuxGui.X11):
            with patch.object(launcher, "_platform_key", return_value="linux"), patch.object(System, "get_linux_gui", return_value=gui):
                config = launcher._load_launcher_config(str(self.scratch))
            self.assertEqual(launcher._is_ignored(config.ignore_spec, "others/keyboard-hook-viewer.py"), gui != LinuxGui.X11)
            self.assertEqual(launcher._is_ignored(config.ignore_spec, "others/script-to-app.py"), gui == LinuxGui.NO_GUI)

    def test_compiler_stages_all_private_modules_for_both_builders(self) -> None:
        stages: list[Path] = []

        def inspect(command: list[str], *, check: bool, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
            stage = Path(env["PYTHONPATH"].split(os.pathsep)[0])
            stages.append(stage)
            package = stage / entry.PACKAGE_NAME
            for name in ("__init__", "app", "api", "models", "runtime", "ui", "devices", "backend", "windows", "macos", "x11"):
                self.assertTrue((package / f"{name}.py").is_file(), name)
            self.assertTrue(any(entry.PACKAGE_NAME in option for option in command))
            return subprocess.CompletedProcess(command, 0)

        for tool in ("nuitka", "pyinstaller"):
            with patch.object(compiler.subprocess, "run", side_effect=inspect):
                result = compiler._run_compiler(["compiler", str(entry.__file__)], str(entry.__file__), str(self.scratch), tool)
            self.assertEqual(result.returncode, 0)
        self.assertTrue(all(not stage.exists() for stage in stages))


if __name__ == "__main__":
    try:
        unittest.main()
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
