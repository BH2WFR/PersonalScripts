"""Keyboard utility and viewer integration tests without live input hooks.

Requirements: project runtime (PyYAML/pathspec for launcher checks).
Run: conda run -n base python -m unittest discover -s test -p "test_keyboard*.py"
"""

from __future__ import annotations

import contextlib
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


class ViewerEventsTests(unittest.TestCase):
    """Synthetic native messages exercise the real dispatch and callback chain."""

    def setUp(self) -> None:
        runtime._held.clear()
        runtime._physical_held.clear()
        runtime._toggled.clear()
        runtime._hotkeys.clear()
        runtime._on_key_cb = None
        runtime._on_mouse_cb = None
        for name in ("_check_win_change", "_print_key", "_print_mouse", "_print_scroll"):
            mocker = patch.object(runtime.ui, name)
            mocker.start()
            self.addCleanup(mocker.stop)

    def tearDown(self) -> None:
        runtime._on_key_cb = None
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
