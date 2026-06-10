import os
import sys
import typing
import dataclasses
import string
import math
import json
import enum
import random
import time
import datetime
import copy
import shutil
import subprocess
import ctypes
import pathlib
import unicodedata
import platform

#* 控制台颜色
# Foreground (text) colors
FBlack     = "\033[30m"
FRed       = "\033[31m"
FGreen     = "\033[32m"
FYellow    = "\033[33m"
FBlue      = "\033[34m"
FMagenta   = "\033[35m"
FCyan      = "\033[36m"
FWhite     = "\033[37m"

FLBlack    = "\033[90m"
FGray      = "\033[90m"
FLRed      = "\033[91m"
FLGreen    = "\033[92m"
FLYellow   = "\033[93m"
FLBlue     = "\033[94m"
FLMagenta  = "\033[95m"
FLCyan     = "\033[96m"
FLWhite    = "\033[97m"

# Background colors
BBlack     = "\033[40m"
BRed       = "\033[41m"
BGreen     = "\033[42m"
BYellow    = "\033[43m"
BBlue      = "\033[44m"
BMagenta   = "\033[45m"
BCyan      = "\033[46m"
BWhite     = "\033[47m"

BGray      = "\033[100m"
BLBlack    = "\033[100m"
BLRed      = "\033[101m"
BLGreen    = "\033[102m"
BLYellow   = "\033[103m"
BLBlue     = "\033[104m"
BLMagenta  = "\033[105m"
BLCyan     = "\033[106m"
BLWhite    = "\033[107m"

# styles
CBold       = "\033[1m"
CWeak       = "\033[2m"
CItalic     = "\033[3m"
CUnderline  = "\033[4m"
CFlash      = "\033[5m"
CQFlash     = "\033[6m"
CInverse    = "\033[7m"
CHidden     = "\033[8m"

# Reset
FDefault    = "\033[39m"
BDefault    = "\033[49m"
CRst        = "\033[0m"

# Cursor / screen control
CCursorHome             = f"\033[H"
CCursorSave             = "\0337"
CCursorRestore          = "\0338"
CCursorHide             = f"\033[?25l"
CCursorShow             = f"\033[?25h"

CEraseDisplay           = f"\033[2J"
CEraseDisplayToEnd      = f"\033[J"
CEraseDisplayToStart    = f"\033[1J"
CEraseDisplayAllScroll  = f"\033[3J"

CEraseLine              = f"\033[2K"
CEraseLineToEnd         = f"\033[K"
CEraseLineToStart       = f"\033[1K"



# 注意：本文件中不应存在全局函数，应当全部包裹到类中。

@dataclasses.dataclass
class CmdCheck:
    """Describes a command-line tool to check for in PATH.

    Attributes:
        cmd: Command name(s) to look up. A ``str`` for a single name, or
            ``list[str]`` to try multiple names in order (first found wins).
        required: If True, a missing command is an error; otherwise a warning.
        hints: Platform-specific install hints. Keys: ``"any"`` (always shown),
            ``"windows"``, ``"linux"``, ``"macos"``. Both ``"any"`` and the
            current platform hint are printed if present.
            Caller controls all color formatting inside hint strings.
        path: Populated by :meth:`Utils.check_commands` — resolved executable
            path, or ``None`` if not found.
    """
    cmd: typing.Union[str, list[str]]
    required: bool = True
    hints: typing.Optional[dict[str, str]] = None
    path: typing.Optional[str] = dataclasses.field(default=None, init=False)


#* 轮子
class Utils:
    @staticmethod
    def get_time_str() -> str:
        """Return current time as ``YYYY-MM-DD HH:MM:SS`` string."""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def get_terminal_width() -> int:
        """Return the current terminal width (columns), or a conservative default.

        Returns ``os.get_terminal_size().columns - 1`` on success, or 119
        (equivalent to a 120-column terminal) when the size cannot be queried.
        """
        try:
            return os.get_terminal_size().columns - 1
        except OSError:
            return 119

    @staticmethod
    def display_width(s: str) -> int:
        """Calculate the display width of *s* in a terminal.

        CJK full-width / wide characters count as 2 columns; everything else
        counts as 1 column.  Uses :func:`unicodedata.east_asian_width`.
        """
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
        title_width = Utils.display_width(title)
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
            width = Utils.get_terminal_width()
        if color_ansi_esc is None:
            color_ansi_esc = ""
        print(f"{' ' * indent}{color_ansi_esc}{'─' * width}{CRst}")

    @staticmethod
    def get_os_name() -> str:
        """Return a human-readable OS name with version."""
        if sys.platform == "darwin":
            ver = platform.mac_ver()[0]
            return f"macOS {ver}" if ver else "macOS"
        if sys.platform == "linux":
            return f"Linux ({platform.release()})"
        if sys.platform in ("win32", "cygwin", "msys"):
            edition = platform.win32_edition()
            base = f"Windows {platform.release()} {platform.version()}"
            return f"{base} {edition}" if edition else base
        return sys.platform

    @staticmethod
    def get_conda_env() -> typing.Optional[str]:
        """Return the conda environment name, or ``None`` if not running in conda."""
        prefix = sys.prefix
        if not any(kw in prefix.lower() for kw in ("conda", "anaconda", "miniconda")):
            return None
        parent = os.path.dirname(prefix)
        if os.path.basename(parent) == "envs":
            return os.path.basename(prefix)
        if os.path.isdir(os.path.join(prefix, "conda-meta")):
            return "base"
        return None

    @staticmethod
    def find_bash() -> typing.Optional[str]:
        """Find a bash executable. Returns path or ``None``."""
        if sys.platform in ("win32", "cygwin", "msys"):
            for candidate in (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                r"C:\msys64\usr\bin\bash.exe",
                r"C:\cygwin64\bin\bash.exe",
            ):
                if os.path.isfile(candidate):
                    return candidate
        found = shutil.which("bash")
        return found if found else None

    @staticmethod
    def find_pwsh() -> typing.Optional[str]:
        """Find a PowerShell executable. Returns path or ``None``."""
        for exe in ("pwsh", "powershell"):
            found = shutil.which(exe)
            if found:
                return found
        return None

    @staticmethod
    def _get_shell_version(exe_path: str) -> typing.Optional[str]:
        """Get the version string of a shell, or ``None`` on failure."""
        try:
            base = os.path.basename(exe_path).lower()
            if base.startswith("pwsh") or base.startswith("powershell"):
                result = subprocess.run(
                    [exe_path, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                    capture_output=True, text=True, timeout=5,
                )
                return result.stdout.strip() or None

            result = subprocess.run(
                [exe_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            out = result.stdout.strip()
            if out:
                return out.splitlines()[0]
            if result.stderr.strip():
                return result.stderr.strip().splitlines()[0]
        except Exception:
            pass
        return None

    @staticmethod
    def print_env_info() -> None:
        """Print conda environment, Python version, OS, pwsh, and bash info."""
        lines: list[str] = []

        lines.append(f"{FLYellow}OS:{CRst}           {Utils.get_os_name()}")

        lines.append(f"{FLCyan}Python:{CRst}       {sys.version.split()[0]}")
        lines.append(f"              {FGray}{sys.executable}{CRst}")

        conda_env = Utils.get_conda_env()
        if conda_env is None:
            lines.append(f"{FLCyan}Conda env:{CRst}    {FLRed}(no conda){CRst}")
        else:
            lines.append(f"{FLCyan}Conda env:{CRst}    {FLYellow}{conda_env}{CRst}")

        pwsh = Utils.find_pwsh()
        if pwsh:
            ver = Utils._get_shell_version(pwsh)
            if ver:
                lines.append(f"{FLGreen}pwsh:{CRst}         {ver}")
            lines.append(f"              {FGray}{pwsh}{CRst}")
        else:
            lines.append(f"{FLGreen}pwsh:{CRst}         {FLRed}(not found){CRst}")

        bash = Utils.find_bash()
        if bash:
            ver = Utils._get_shell_version(bash)
            if ver:
                lines.append(f"{FLGreen}bash:{CRst}         {ver}")
            lines.append(f"              {FGray}{bash}{CRst}")
        else:
            lines.append(f"{FLGreen}bash:{CRst}         {FLRed}(not found){CRst}")

        print()
        for line in lines:
            print(f"  {line}")
        print()

    @staticmethod
    def print_error_and_exit(msg: str, code: int = 1) -> None:
        """Print a red error message and call ``exit(code)``."""
        print(f"{FLRed}Error: {msg}{CRst}")
        exit(code)

    @staticmethod
    def check_commands(*checks: CmdCheck) -> bool:
        """Verify all commands in *checks* exist in PATH.

        Resolves ``.path`` on each :class:`CmdCheck` to the found executable,
        or ``None`` if not found. Prints per-platform install hints for missing
        commands. Required commands cause the check to fail; optional ones only
        print a warning.

        Returns True if all *required* commands are found, False otherwise.
        Callers should ``sys.exit(1)`` when False.
        """
        all_ok = True
        for c in checks:
            # Resolve: list = try in order, str = single lookup
            names = c.cmd if isinstance(c.cmd, list) else [c.cmd]
            c.path = next((shutil.which(n) for n in names if shutil.which(n)), None)
            if c.path is not None:
                continue

            # Build error/warning message
            prefix = f"{FLRed}ERROR:{CRst}" if c.required else f"{FLYellow}WARNING:{CRst}"
            label = " or ".join(names)
            print(f"{prefix} `{label}` not found in PATH.")

            # Print platform-specific hints
            if c.hints:
                platform = (
                    "windows" if sys.platform == "win32"
                    else "macos" if sys.platform == "darwin"
                    else "linux"
                )
                for key in ("any", platform):
                    if key in c.hints:
                        print(f"  {c.hints[key]}")
            print()

            if c.required:
                all_ok = False
        return all_ok

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
    def is_headless() -> bool:
        """Return True if the environment likely has no GUI/display available."""
        if sys.platform == "darwin":
            return False
        if sys.platform != "win32":
            return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
        return False

    @staticmethod
    def open_browser_safe(url: str) -> None:
        """Open *url* in the default browser, silently skip on headless systems."""
        if Utils.is_headless():
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    @staticmethod
    def print_argv_list() -> None:
        """Print ``sys.argv`` with index and color formatting."""
        print(f"{FLYellow}Command line arguments:{CRst}")
        for i, arg in enumerate(sys.argv):
            print(f"  argv[{FLYellow}{i}{CRst}]: {FLCyan}{arg}{CRst}")

    @staticmethod
    def enable_dpi_awareness() -> None:
        """Enable per-monitor DPI awareness on Windows (no-op on other platforms)."""
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        # Windows 10+ recommended: Per Monitor V2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except Exception:
            pass

        # Win8.1 fallback
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # Older systems fallback
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    @staticmethod
    def is_elevated() -> bool:
        """Check if the current process has administrator/root privileges.

        Returns True on Windows (admin), macOS/Linux (root), or if detection fails.
        """
        if sys.platform == "win32":
            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            try:
                return os.geteuid() == 0
            except AttributeError:
                return False

    @staticmethod
    def elevate() -> None:
        """Re-execute the current script with administrator/root privileges.

        If already elevated, returns immediately. Otherwise tries ``sudo``, then
        ``gsudo`` (Windows only), then OS-specific elevation APIs. Does not return
        if elevation succeeds — the current process is replaced.
        """
        if Utils.is_elevated():
            return

        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        if sys.platform == "win32":
            for tool in ("sudo", "gsudo"):
                exe = shutil.which(tool)
                if exe:
                    os.execv(exe, [tool, sys.executable, script] + args)
            # Fallback: ShellExecute with runas verb
            params = subprocess.list2cmdline([script] + args)
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1,
            )
            if ret <= 32:
                print(f"{FLRed}Elevation failed (ShellExecute error {ret}).{CRst}")
                sys.exit(1)
            sys.exit(0)
        else:
            if shutil.which("sudo"):
                os.execv("/usr/bin/sudo", ["sudo", sys.executable, script] + args)
            print(f"{FLRed}Cannot elevate: sudo not found in PATH.{CRst}")
            sys.exit(1)
            

class Input:
    #* ============ 输出路径解析工具 ============
    @staticmethod
    def _find_available_path(base_path: str) -> str:
        """Find the first non-existing path by appending _2, _3, etc. to the base path."""
        if not os.path.exists(base_path):
            return base_path

        dir_name = os.path.dirname(base_path) or "."
        base_name = os.path.basename(base_path)
        stem, ext = os.path.splitext(base_name)

        n = 2
        while n <= 500:
            if ext:
                candidate = os.path.join(dir_name, f"{stem}_{n}{ext}")
            else:
                candidate = os.path.join(dir_name, f"{base_name}_{n}")
            if not os.path.exists(candidate):
                return candidate
            n += 1

        print(f"{FLRed}Cannot find an available path: over 500 variants of '{FGray}{base_path}{CRst}' already exist. Please enter a path manually.{CRst}")
        return base_path

    @staticmethod
    def resolve_output_path(default_path: str, prompt: str = "Enter output path", path_type: str = "file") -> str:
        """Interactive output path resolution with automatic collision avoidance.

        Args:
            default_path: The base suggested path.
            prompt: Prompt text shown to the user.
            path_type: ``"file"`` — checks that the parent directory exists (prompts to
                create if missing), then checks the file itself for collisions.
                ``"dir"`` — checks the directory itself; creates it if missing, or
                offers overwrite / rename / exit if it already exists.
                ``"link"`` — checks for an existing symlink at the path.

        Returns the final absolute path, or calls ``sys.exit(0)`` if the user chooses to quit.
        """
        current_default = os.path.expanduser(default_path)
        action_label = "Replace" if path_type == "file" else "Still use"

        while True:
            suggested = Input._find_available_path(current_default)

            user_input = input(
                f"{FLYellow}{prompt} {FGray}[{suggested}]{CRst}: "
            ).strip()
            if not user_input:
                user_path = suggested
            else:
                user_path = user_input.strip("'\"")

            user_path = os.path.expanduser(user_path)

            # Resolve relative paths against the suggested path's directory
            if os.path.dirname(user_path) == "":
                user_path = os.path.join(os.path.dirname(suggested) or ".", user_path)

            user_path = os.path.abspath(user_path)

            # ----- ensure containing directory exists -----
            parent_dir = user_path if path_type == "dir" else (os.path.dirname(user_path) or ".")
            if not os.path.isdir(parent_dir):
                print(f"{FLRed}Directory does not exist: {FGray}{parent_dir}{CRst}")
                create = input(f"{FLCyan}Create it? (y/n, default: y): {CRst}").strip().lower() or "y"
                if create == "y":
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                        print(f"{FLGreen}Created: {FGray}{parent_dir}{CRst}")
                        if path_type == "dir":
                            return user_path
                    except Exception as e:
                        print(f"{FLRed}Failed to create: {e}{CRst}")
                        current_default = user_path
                        continue
                else:
                    current_default = user_path
                    continue

            # ----- check what exists at this path -----
            if not os.path.exists(user_path):
                return user_path

            # ----- collision menu (shown for any existing path, regardless of type) -----
            print(f"{FLYellow}Path already exists:{CRst} {FGray}{user_path}{CRst}")
            while True:
                choice = (
                    input(
                        f"{FLCyan}{action_label} ({FLYellow}o{FLCyan}), Rename ({FLYellow}r{FLCyan}),"
                        f" or Exit ({FLRed}e{FLCyan})? "
                        f"{FGray}[r]{CRst}: "
                    )
                    .strip()
                    .lower()
                    or "r"
                )
                if choice in ("o", "overwrite", "replace"):
                    # ----- type check only after user decides to replace -----
                    if path_type == "file":
                        type_ok = os.path.isfile(user_path)
                    elif path_type == "dir":
                        type_ok = os.path.isdir(user_path)
                    elif path_type == "link":
                        type_ok = os.path.islink(user_path)
                    else:
                        type_ok = True

                    if type_ok:
                        return user_path

                    # type mismatch — error, then loop back to same collision menu
                    if path_type == "file":
                        if os.path.isdir(user_path):
                            print(f"{FLRed}This path is a folder, cannot overwrite as file: {FGray}{user_path}{CRst}")
                        elif os.path.islink(user_path):
                            print(f"{FLRed}This path is a symlink, cannot overwrite as file: {FGray}{user_path}{CRst}")
                        else:
                            print(f"{FLRed}This path is not a regular file: {FGray}{user_path}{CRst}")
                    elif path_type == "dir":
                        if os.path.isfile(user_path):
                            print(f"{FLRed}This path is a file, cannot use as folder: {FGray}{user_path}{CRst}")
                        elif os.path.islink(user_path):
                            print(f"{FLRed}This path is a symlink, cannot use as folder: {FGray}{user_path}{CRst}")
                        else:
                            print(f"{FLRed}This path is not a regular directory: {FGray}{user_path}{CRst}")
                    elif path_type == "link":
                        if os.path.isfile(user_path):
                            print(f"{FLRed}This path is a regular file, not a symlink: {FGray}{user_path}{CRst}")
                        elif os.path.isdir(user_path):
                            print(f"{FLRed}This path is a regular directory, not a symlink: {FGray}{user_path}{CRst}")
                        else:
                            print(f"{FLRed}This path is not a symlink: {FGray}{user_path}{CRst}")
                    else:
                        return user_path
                    # loop back to collision menu

                elif choice in ("e", "exit"):
                    print(f"{FLRed}Exiting.{CRst}")
                    sys.exit(0)
                elif choice in ("r", "rename"):
                    current_default = user_path
                    break
                else:
                    print(f"{FLRed}Invalid choice. Enter {FLYellow}o{FLRed}, {FLYellow}r{FLRed}, or {FLYellow}e{FLRed}.{CRst}")


    @staticmethod
    def resolve_input_path(default_path: str, prompt: str = "Enter input path", path_type: str = "file") -> str:
        """Interactive input path resolution with existence and type validation.

        Args:
            default_path: The base suggested path.
            prompt: Prompt text shown to the user.
            path_type: ``"file"``, ``"dir"``, ``"link"``, or ``"any"`` (only checks existence).

        Returns the final absolute path, or calls ``sys.exit(0)`` if the user chooses to quit.
        """
        current_default = os.path.expanduser(default_path)
        if path_type == "file":
            action_label = "Replace"
        elif path_type == "dir":
            action_label = "Still use"
        else:
            action_label = "Still use"

        while True:
            user_input = input(
                f"{FLYellow}{prompt} {FGray}[{current_default}]{CRst}: "
            ).strip()
            if not user_input:
                user_path = current_default
            else:
                user_path = user_input.strip("'\"")

            user_path = os.path.expanduser(user_path)
            if os.path.dirname(user_path) == "":
                user_path = os.path.join(os.path.dirname(current_default) or ".", user_path)
            user_path = os.path.abspath(user_path)

            # ----- check existence and type -----
            if path_type == "link":
                exists = os.path.lexists(user_path)
            else:
                exists = os.path.exists(user_path)

            if path_type == "any":
                type_ok = True  # accept any existing path
            elif path_type == "link":
                type_ok = os.path.islink(user_path)
            elif path_type == "file":
                type_ok = os.path.isfile(user_path)
            else:  # dir
                type_ok = os.path.isdir(user_path)

            if exists and type_ok:
                return user_path

            # ----- error message -----
            if not exists:
                print(f"{FLRed}Path does not exist: {FGray}{user_path}{CRst}")
            else:
                if os.path.isdir(user_path):
                    actual = "folder"
                elif os.path.islink(user_path):
                    actual = "symlink"
                else:
                    actual = "file"
                print(f"{FLRed}Path is a {actual}, but a {path_type} was expected: {FGray}{user_path}{CRst}")

            # ----- conflict / error menu -----
            while True:
                choice = (
                    input(
                        f"{FLCyan}Rename ({FLYellow}r{FLCyan}), {action_label} ({FLYellow}f{FLCyan}),"
                        f" or Exit ({FLRed}e{FLCyan})? "
                        f"{FGray}[r]{CRst}: "
                    )
                    .strip()
                    .lower()
                    or "r"
                )
                if choice in ("r", "rename"):
                    current_default = Input._find_available_path(user_path)
                    break
                elif choice in ("f", "force"):
                    return user_path
                elif choice in ("e", "exit"):
                    print(f"{FLRed}Exiting.{CRst}")
                    sys.exit(0)
                else:
                    print(f"{FLRed}Invalid choice. Enter {FLYellow}r{FLRed}, {FLYellow}f{FLRed}, or {FLYellow}e{FLRed}.{CRst}")


    @staticmethod
    def resolve_input_paths_multi(prompt_text: str = "Enter paths (one per line)", path_type: str = "any") -> list[str]:
        """Read multiple paths interactively from stdin (EOF-terminated).

        - De-duplicates input
        - Validates each path (existence + type unless *path_type* is ``"any"``)
        - For non-existing or wrong-type paths, prompts to keep or drop each one
        - Prints the final count of accepted paths
        - Exits with ``sys.exit(1)`` if no paths remain
        - Returns list of absolute paths
        """
        _eof_hint = f"{FLYellow}Enter{FGray}→{FLYellow}Ctrl+Z{FGray}→{FLYellow}Enter" if sys.platform == "win32" else f"{FLYellow}Ctrl+D"
        print(f"{FLYellow}{prompt_text}{CRst}")
        print(f"{FLCyan}End with {_eof_hint}{FLCyan}:{CRst}")
        raw = sys.stdin.read().strip()
        if not raw:
            print(f"{FLRed}No paths provided.{CRst}")
            sys.exit(1)

        # Parse and de-duplicate (preserving order)
        paths: list[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            p = line.strip().strip("'\"")
            if p and p not in seen:
                seen.add(p)
                paths.append(p)

        accepted: list[str] = []
        for p in paths:
            p = os.path.expanduser(p)
            p = os.path.abspath(p)

            # ----- validate existence and type -----
            if path_type == "link":
                exists = os.path.lexists(p)
                type_ok = os.path.islink(p) if exists else False
            elif path_type == "any":
                exists = os.path.exists(p)
                type_ok = True
            elif path_type == "file":
                exists = os.path.exists(p)
                type_ok = os.path.isfile(p) if exists else False
            else:  # dir
                exists = os.path.exists(p)
                type_ok = os.path.isdir(p) if exists else False

            if exists and type_ok:
                accepted.append(p)
                continue

            # ----- error message -----
            if not exists:
                print(f"{FLRed}Path does not exist: {FGray}{p}{CRst}")
            else:
                if os.path.isdir(p):
                    actual = "folder"
                elif os.path.islink(p):
                    actual = "symlink"
                else:
                    actual = "file"
                print(f"{FLRed}Path is a {actual}, but a {path_type} was expected: {FGray}{p}{CRst}")

            # ----- keep or drop -----
            choice = (
                input(f"{FLCyan}Keep ({FLYellow}k{FLCyan}) or Drop ({FLYellow}d{FLCyan})? {FGray}[d]{CRst}: ")
                .strip()
                .lower()
                or "d"
            )
            if choice == "k":
                accepted.append(p)

        print(f"{FLYellow}  -> {len(accepted)} path(s) accepted{CRst}")
        if not accepted:
            print(f"{FLRed}No valid paths to process. EXIT...{CRst}")
            sys.exit(1)
        return accepted


    @typing.overload
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        skip_empty: bool = True,
        trim_lines: bool = True,
        strip_trailing_newline: bool = True,
        pattern: typing.Optional[str] = None,
        *,
        split_lines: typing.Literal[True] = True,
        raw: typing.Literal[False] = False,
    ) -> list[str]: ...
    @typing.overload
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        skip_empty: bool = True,
        trim_lines: bool = True,
        strip_trailing_newline: bool = True,
        pattern: typing.Optional[str] = None,
        *,
        split_lines: typing.Literal[False],
        raw: typing.Literal[False] = False,
    ) -> str: ...
    @typing.overload
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        *,
        raw: typing.Literal[True],
        strip_trailing_newline: bool = True,
    ) -> str: ...
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        skip_empty: bool = True,
        trim_lines: bool = True,
        strip_trailing_newline: bool = True,
        pattern: typing.Optional[str] = None,
        split_lines: bool = True,
        raw: bool = False,
    ) -> typing.Union[list[str], str]:
        """Read multi-line text from stdin with EOF prompt.

        Args:
            prompt_text: Description of what to enter.
            skip_empty: Whether to skip empty lines (only when *split_lines* is True).
            trim_lines: Whether to strip whitespace from each line (only when *split_lines* is True).
            strip_trailing_newline: Whether to remove the trailing ``\\n`` from the result.
            pattern: Regex pattern for validation (reserved, not yet implemented).
            split_lines: If True, return list of lines; if False, return raw string.
            raw: If True, return the raw input string as-is (only strips trailing ``\\n``
                when *strip_trailing_newline* is True). Overrides all other processing options.

        Returns:
            List of processed lines or raw string. Returns empty list/string if input is empty.
        """
        _eof_hint = f"{FLYellow}Enter{FGray}→{FLYellow}Ctrl+Z{FGray}→{FLYellow}Enter" if sys.platform == "win32" else f"{FLYellow}Ctrl+D"
        print(f"{FLYellow}{prompt_text}{CRst}")
        print(f"{FLCyan}End with {_eof_hint}{FLCyan}:{CRst}")
        text = sys.stdin.read()
        if raw:
            if not text.strip():
                print(f"{FLRed}No input provided.{CRst}\n")
                return ""
            if strip_trailing_newline:
                text = text.removesuffix("\n")
            return text
        if split_lines:
            if not text.strip():
                print(f"{FLRed}No input provided.{CRst}\n")
                return []
            lines: list[str] = []
            for line in text.splitlines():
                if trim_lines:
                    line = line.strip()
                if skip_empty and not line:
                    continue
                lines.append(line)
            if not lines:
                print(f"{FLRed}No valid input provided.{CRst}\n")
                return []
            return lines
        else:
            if not text.strip():
                print(f"{FLRed}No input provided.{CRst}\n")
                return ""
            if strip_trailing_newline:
                text = text.removesuffix("\n")
            return text


class Cursor:
    @staticmethod
    def up(count: int = 1) -> str:
        return f"\033[{max(1, count)}A"

    @staticmethod
    def down(count: int = 1) -> str:
        return f"\033[{max(1, count)}B"
        
    @staticmethod
    def forward(count: int = 1) -> str:
        return f"\033[{max(1, count)}C"
        
    @staticmethod
    def back(count: int = 1) -> str:
        return f"\033[{max(1, count)}D"
        
    @staticmethod
    def next_line(count: int = 1) -> str:
        return f"\033[{max(1, count)}E"
        
    @staticmethod
    def prev_line(count: int = 1) -> str:
        return f"\033[{max(1, count)}F"
        
    @staticmethod
    def column(column: int = 1) -> str:
        return f"\033[{max(1, column)}G"
        
    @staticmethod
    def position(row: int = 1, column: int = 1) -> str:
        return f"\033[{max(1, row)};{max(1, column)}H"
        
    @staticmethod
    def erase_display(mode: int = 2) -> str:
        return f"\033[{mode}J"
        
    @staticmethod
    def erase_line(mode: int = 2) -> str:
        return f"\033[{mode}K"
        
    @staticmethod
    def scroll_up(count: int = 1) -> str:
        return f"\033[{max(1, count)}S"
        
    @staticmethod
    def scroll_down(count: int = 1) -> str:
        return f"\033[{max(1, count)}T"


# ============================================================
# Interactive menu helpers
# ============================================================

class MenuOption:
    """A single option in an interactive selection menu.

    Attributes:
        keys: Trigger keys, case-insensitive (e.g. ``["N"]`` or ``["1", "+"]``).
        description: Human-readable label (may contain ANSI color codes).
        value: Value returned when selected (defaults to *keys[0]* if ``None``).
        desc_color: ANSI color to wrap *description* (empty → use *default_desc_color*).
    """
    __slots__ = ("keys", "description", "value", "desc_color")

    def __init__(self, keys, description, value=None, desc_color=""):
        self.keys = [k.upper() for k in keys]
        self.description = description
        self.value = value if value is not None else keys[0]
        self.desc_color = desc_color


class Menu:
    """Interactive terminal menu helpers."""

    @staticmethod
    def select(
        options: list[MenuOption],
        *,
        prompt: str = "Choice",
        required: bool = False,
        default_key: typing.Optional[str] = None,
        inline: bool = False,
        key_color: str = FLGreen,
        default_desc_color: str = FLYellow,
        separator: bool = True,
        separator_char: str = "─",
        separator_width: int = 44,
        separator_color: str = FLCyan,
        indent: str = "  ",
        accept_custom_string: bool = False,
    ) -> typing.Optional[typing.Any]:
        """Display an interactive menu and return the selected value.

        Prints a list of options (each prefixed with a ``[Key]`` bracket), prompts
        the user for input, validates it, and returns the corresponding value.

        Args:
            options: MenuOption list to choose from.
            prompt: Input prompt text (e.g. ``"Choice"`` → ``"Choice > "``).
            required: If ``True``, empty input re-prompts. If ``False`` and
                *default_key* is ``None``, empty input returns ``None``.
            default_key: If set, empty input returns the value whose key matches.
                Takes precedence over *required*.
            inline: ``True`` → all options on one line; ``False`` → one per line.
            key_color: ANSI color for the key character inside brackets.
            default_desc_color: Fallback *desc_color* for options without one.
            separator: Print separator lines before / after the options.
            separator_char: Character for separator lines.
            separator_width: Length of separator lines.
            separator_color: ANSI color for separator lines.
            indent: Leading whitespace for each option line.
            accept_custom_string: If ``True``, non-empty input that does not match
                any key is returned as-is instead of showing an error.

        Returns:
            The ``MenuOption.value`` corresponding to the chosen key, or the raw
            input string when *accept_custom_string* is ``True`` and no key matches.

        Raises:
            ValueError: If *options* is empty or contains duplicate keys.
        """
        if not options:
            raise ValueError("options must not be empty")

        # Build key → option map (case-insensitive)
        key_map: dict[str, MenuOption] = {}
        for opt in options:
            for k in opt.keys:
                if k in key_map:
                    raise ValueError(f"Duplicate key '{k}' in options")
                key_map[k] = opt

        all_keys = sorted(key_map.keys())
        sep_line = f"{separator_color}{separator_char * separator_width}{CRst}"

        while True:
            if separator:
                print(sep_line)

            if inline:
                parts = []
                for opt in options:
                    k = opt.keys[0]
                    dc = opt.desc_color or default_desc_color
                    parts.append(
                        f"{indent}{FLYellow}[{key_color}{k}{FLYellow}]{CRst}"
                        f" {dc}{opt.description}{CRst}"
                    )
                print("  ".join(parts))
            else:
                for opt in options:
                    k = opt.keys[0]
                    dc = opt.desc_color or default_desc_color
                    print(
                        f"{indent}{FLYellow}[{key_color}{k}{FLYellow}]{CRst}"
                        f" {dc}{opt.description}{CRst}"
                    )

            if separator:
                print(sep_line)

            try:
                if default_key is not None:
                    prompt_line = f"{FLYellow}{prompt} {FGray}[{default_key}]{CRst}{FLYellow} > {CRst}"
                else:
                    prompt_line = f"{FLYellow}{prompt} > {CRst}"
                raw_input = input(prompt_line).strip()
                choice = raw_input.upper()
            except (EOFError, KeyboardInterrupt):
                print()
                sys.exit(0)

            if not choice:
                if default_key is not None:
                    wanted = default_key.upper()
                    if wanted in key_map:
                        return key_map[wanted].value
                if required:
                    continue
                return None

            if choice in key_map:
                return key_map[choice].value

            if accept_custom_string and raw_input:
                return raw_input

            keys_hint = ", ".join(all_keys)
            hint = (
                f"{FLRed}Invalid choice. Try {FLYellow}{keys_hint}{FLRed}."
                f" Press {FLCyan}Enter{FLRed} to {'retry' if required else 'exit'}.{CRst}\n"
            )
            print(hint)

    @staticmethod
    def from_enum(
        enum_cls,
        *,
        name_transform=None,
        desc_color: str = "",
    ) -> list[MenuOption]:
        """Build a MenuOption list from an :class:`~enum.Enum`.

        Keys are ``str(member.value)``, descriptions derive from ``member.name``
        (split on ``_`` and title-cased by default).

        Args:
            enum_cls: An :class:`~enum.Enum` subclass.
            name_transform: Callable ``(name: str) -> str`` to convert member names
                to display text. ``None`` → ``name.replace("_", " ").title()``.
            desc_color: ANSI color applied to every option's description.
        """
        options = []
        for item in enum_cls:
            raw = item.name
            label = name_transform(raw) if name_transform else raw.replace("_", " ").title()
            options.append(MenuOption(
                keys=[str(item.value)],
                description=label,
                value=item,
                desc_color=desc_color,
            ))
        return options
