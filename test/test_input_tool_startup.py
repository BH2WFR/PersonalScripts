"""Verify elevation before either input tool opens a window."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utils import System

TOOLS = ROOT / "tools" / "others"


class InputToolStartupTests(unittest.TestCase):
    def test_platform_specific_elevation(self) -> None:
        for filename, mac_module, mac_entry in (
            ("auto-typer.py", "auto_typer.macos", "run_macos"),
            ("screen-keyboard.py", "screen_keyboard.mac_ui", "run"),
        ):
            with self.subTest(tool=filename), patch.object(sys, "path", sys.path.copy()):
                main = runpy.run_path(str(TOOLS / filename))["main"]
                with (patch.object(sys, "platform", "win32"), patch.object(sys, "argv", [filename]),
                      patch.object(System, "restart_elevated", side_effect=SystemExit(7)) as elevate):
                    with (patch.object(sys, "argv", [filename, "--help"]), redirect_stdout(StringIO()),
                          self.assertRaises(SystemExit) as help_exit):
                        main()
                    self.assertEqual(help_exit.exception.code, 0)
                    elevate.assert_not_called()
                    with self.assertRaises(SystemExit) as exit_status:
                        main()
                    self.assertEqual(exit_status.exception.code, 7)
                    elevate.assert_called_once_with()

                backend = Mock()
                getattr(backend, mac_entry).return_value = 0
                with (patch.object(sys, "platform", "darwin"), patch.object(sys, "argv", [filename]),
                      patch.dict(sys.modules, {mac_module: backend, "auto_typer.panel": Mock()}),
                      patch.object(System, "restart_elevated") as elevate):
                    self.assertEqual(main(), 0)
                    getattr(backend, mac_entry).assert_called_once_with()
                    elevate.assert_not_called()
