"""Console formatting and terminal interaction helpers."""

import datetime
import os
import sys
import typing

from .ansi import *


class Console:
    @staticmethod
    def format_size(size_bytes: typing.Union[int, float], precision: int = 1) -> str:
        """Format a byte count using binary units from B through PB."""
        if size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")
        if precision < 0:
            raise ValueError("precision cannot be negative")

        value = float(size_bytes)
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        for index, unit in enumerate(units):
            if value < 1024 or index == len(units) - 1:
                if unit == "B":
                    return f"{value:.0f} {unit}"
                return f"{value:.{precision}f} {unit}"
            value /= 1024
        raise RuntimeError("Unreachable size-formatting state.")

    @staticmethod
    def get_time_str() -> str:
        """Return current time as ``YYYY-MM-DD HH:MM:SS`` string."""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def resolve_ansi_color(name: str) -> str:
        """Resolve an ANSI foreground/background color constant by name.

        Args:
            name: Exact project color constant name, such as ``"FLYellow"``,
                ``"BBlue"``, or ``"CRst"``.

        Returns:
            The ANSI escape sequence stored in the named constant.

        Raises:
            ValueError: If ``name`` does not identify a supported ANSI color
                or reset constant.
        """
        normalized_name = name.strip()
        value = globals().get(normalized_name)
        is_color_name = normalized_name.startswith(("F", "B")) or normalized_name == "CRst"
        if (
            not is_color_name
            or not isinstance(value, str)
            or not value.startswith("\033[")
            or not value.endswith("m")
        ):
            raise ValueError(f"Unknown ANSI color name: {name}")
        return value

    @staticmethod
    def get_terminal_width() -> int:
        """Return the current terminal width (columns), or a conservative default.

        Returns ``os.get_terminal_size().columns`` on success, or 120 when the
        size cannot be queried.
        """
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 120

    @staticmethod
    def display_width(s: str) -> int:
        """Calculate the display width of *s* in a terminal.

        CJK full-width / wide characters count as 2 columns; everything else
        counts as 1 column.  Uses :func:`unicodedata.east_asian_width`.
        """
        try:
            import unicodedata
        except ImportError:
            return len(s)

        w = 0
        for ch in s:
            ea = unicodedata.east_asian_width(ch)
            w += 2 if ea in ("W", "F") else 1
        return w

    @staticmethod
    def print_banner(title: str, width: int = 60, color_ansi_esc: typing.Optional[str] = f"{FLYellow}") -> None:
        """Print *title* centered inside a double-line box-drawing banner.

        The box uses ``╔`` / ``╗`` / ``╚`` / ``╝`` / ``║`` / ``═`` characters.
        CJK full-width characters in *title* are counted as 2 columns via
        :meth:`display_width`. If the title's display width exceeds *width*,
        the box is extended with at least 4 ``═`` characters flanking each side.

        :param title: Text to display centered in the banner.
        :param width: Desired total width of the box (border included).
                      Defaults to 40; may be extended if *title* is too long.
        :param color_ansi_esc: ANSI escape sequence for the box colour.
                               Defaults to :data:`FLYellow`.  Pass ``None`` for no colour.
        """
        if color_ansi_esc is None:
            color_ansi_esc = ""
        title_width = Console.display_width(title)
        # Content area: at least 8 (4 ═ padding each side) beyond title width
        min_content = title_width + 8
        content = max(width - 2, min_content)
        total = content + 2
        h_line = "═" * content
        left_pad = (content - title_width) // 2
        right_pad = content - title_width - left_pad
        print(f"{color_ansi_esc}╔{h_line}╗{CRst}")
        print(f"{color_ansi_esc}║{' ' * left_pad}{title}{' ' * right_pad}║{CRst}")
        print(f"{color_ansi_esc}╚{h_line}╝{CRst}")

    @staticmethod
    def print_separator(width: int = 50, color_ansi_esc: typing.Optional[str] = f"{FLYellow}", indent: int = 0) -> None:
        """Print a horizontal separator line using ``─`` characters.

        :param width: Width of the line in columns. Defaults to 50.
                      When 0 or ``None``, uses :meth:`get_terminal_width`.
        :param color_ansi_esc: ANSI escape sequence for the line colour.
                               Defaults to :data:`FLYellow`.  Pass ``None`` for no colour.
        :param indent: Number of leading spaces before the separator. Defaults to 0.
        """
        if not width:
            width = Console.get_terminal_width()
        if color_ansi_esc is None:
            color_ansi_esc = ""
        print(f"{' ' * indent}{color_ansi_esc}{'─' * width}{CRst}")

    @staticmethod
    def print_error_and_exit(msg: str, code: int = 1) -> None:
        """Print a red error message and call ``exit(code)``."""
        print(f"{FLRed}Error: {msg}{CRst}")
        exit(code)

    @staticmethod
    def print_keyboard_interrupt_message_and_exit(key : str = "Ctrl+C") -> None:
        """Print a standardized message for KeyboardInterrupt exceptions."""
        print(f"\n{FLGreen}[Exit by {FLYellow}{key}{FLGreen}]{CRst}")
    

    @staticmethod
    def print_exit_message(msg: str = "Bye.") -> None:
        """Print a standardized exit message without calling ``exit()``."""
        print(f"{FLGreen}{msg}{CRst}")

    @staticmethod
    def print_exit_message_and_exit(
        msg: str = "Exiting.",
        color_ansi_esc: typing.Optional[str] = f"{FLGreen}",
        exit_code: int = 0
    ) -> None:
        """Print a standardized exit message and call ``exit(0)``."""
        if color_ansi_esc is None:
            color_ansi_esc = ""
        print(f"{color_ansi_esc}{msg}{CRst}")
        sys.exit(exit_code)
    

    @staticmethod
    def set_locale_utf8() -> None:
        """Set console to UTF-8 mode (Windows: chcp 65001 + en_US.UTF-8 locale)."""
        if os.name == 'nt':
            os.system('chcp 65001 > nul')
            try:
                import locale
                locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
            except Exception as e:
                print(f"{FLRed}Warning: Failed to set locale to UTF-8: {e}{CRst}")
        print(f"UTF-8 test: 中文한글🤣")

    @staticmethod
    def print_argv_list() -> None:
        """Print ``sys.argv`` with index and color formatting."""
        print(f"{FLYellow}Command line arguments:{CRst}")
        for i, arg in enumerate(sys.argv):
            print(f"  argv[{FLYellow}{i}{CRst}]: {FLCyan}{arg}{CRst}")
