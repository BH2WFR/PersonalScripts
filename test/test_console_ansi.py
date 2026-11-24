"""Exercise Windows output setup with independent standard streams."""

import ctypes
import io
import os
import sys
import unittest
from unittest.mock import Mock, patch

from utils import Console


class AnsiOutputTests(unittest.TestCase):
    def test_either_standard_stream_can_be_redirected(self) -> None:
        mode = ctypes.c_ulong(0x0002)  # Existing wrap-at-end-of-line setting.
        kernel = Mock()

        def get_mode(handle: ctypes.c_void_p, out: ctypes.c_void_p) -> int:
            self.assertEqual(handle.value, 12)
            ctypes.memmove(out, ctypes.byref(mode), ctypes.sizeof(mode))
            return 1

        def set_mode(handle: ctypes.c_void_p, value: int) -> int:
            self.assertEqual(handle.value, 12)
            mode.value = value
            return 1

        kernel.GetConsoleMode.side_effect = get_mode
        kernel.SetConsoleMode.side_effect = set_mode
        terminal = Mock(closed=False)
        terminal.isatty.return_value = True
        terminal.fileno.return_value = 2
        msvcrt = Mock()
        msvcrt.get_osfhandle.return_value = 12
        redirected = io.StringIO()
        for stdout, stderr in ((redirected, terminal), (terminal, redirected)):
            with (self.subTest(stdout_is_terminal=stdout is terminal), patch.object(os, "name", "nt"),
                  patch.dict(sys.modules, msvcrt=msvcrt), patch.object(sys, "stdout", stdout),
                  patch.object(sys, "stderr", stderr),
                  patch.object(ctypes, "windll", Mock(kernel32=kernel), create=True)):
                mode.value = 0x0002
                kernel.reset_mock()
                Console.initialize_ansi_output()
                Console.initialize_ansi_output()
                self.assertEqual(mode.value, 0x0007)
                kernel.SetConsoleMode.assert_called_once()
                self.assertEqual(kernel.GetConsoleMode.call_count, 2)

    def test_missing_or_unavailable_streams_are_skipped(self) -> None:
        stream = io.StringIO()
        stream.close()
        with (patch.object(os, "name", "nt"), patch.object(sys, "stdout", None),
              patch.object(sys, "stderr", stream)):
            Console.initialize_ansi_output()
            self.assertFalse(Console.enable_ansi_output(None))
            self.assertFalse(Console.enable_ansi_output(stream))

    def test_other_platforms_leave_streams_untouched(self) -> None:
        with patch.object(os, "name", "posix"), patch.object(Console, "enable_ansi_output") as enable:
            Console.initialize_ansi_output()
            enable.assert_not_called()
