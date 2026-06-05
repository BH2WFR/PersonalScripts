import os
import sys
import typing
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

#* 轮子
class Utils:
    @staticmethod
    def get_time_str():
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    @staticmethod
    def print_error_and_exit(msg, code=1):
        print(f"{FLRed}Error: {msg}{CRst}")
        exit(code)
    
    @staticmethod
    def console_command_required(exe_name: str) -> str:
        p = shutil.which(exe_name)
        if not p:
            print(f"{FLRed}ERROR: `{exe_name}` not found in PATH. {CRst}"
                f"Please install it (scoop install {exe_name}) or add it to PATH.\033[0m")
            sys.exit(1)
        return p
    
    @staticmethod
    def set_locale_utf8():
        if os.name == 'nt':
            os.system('chcp 65001')  #* Windows 上设置控制台为 UTF-8 编码
            # Windows 上设置 UTF-8 locale (>= windows 10 1903)
            try:
                import locale
                locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
            except Exception as e:
                print(f"{FLRed}Warning: Failed to set locale to UTF-8: {str(e)}{CRst}")
    
    @staticmethod
    def print_argv_list():
        print(f"{FLYellow}Command line arguments:{CRst}")
        for i, arg in enumerate(sys.argv):
            print(f"  argv[{FLYellow}{i}{CRst}]: {FLCyan}{arg}{CRst}")
    
    
    @staticmethod
    def enable_dpi_awareness() -> None:
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        # Windows 10+ 推荐：Per Monitor V2
        try:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return
        except Exception:
            pass

        # Win8.1 回退
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass

        # 更老系统回退
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
            
            
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
            suggested = Utils._find_available_path(current_default)

            user_input = input(
                f"{FLYellow}{prompt} {FGray}[{os.path.basename(suggested)}]{CRst}: "
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
                f"{FLYellow}{prompt} {FGray}[{os.path.basename(current_default)}]{CRst}: "
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
                    current_default = Utils._find_available_path(user_path)
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
        print(f"{FLYellow}{prompt_text}{CRst}")
        print(f"{FLCyan}End with {FLYellow}Ctrl+Z (Windows) or Ctrl+D (Linux/macOS){FLCyan}:{CRst}")
        raw = sys.stdin.read().strip()
        if not raw:
            print(f"{FLRed}No paths provided.{CRst}")
            sys.exit(1)

        # Parse and de-duplicate (preserving order)
        paths: list[str] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            p = line.strip()
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
        pattern: str | None = None,
        *,
        split_lines: typing.Literal[True] = True,
    ) -> list[str]: ...
    @typing.overload
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        skip_empty: bool = True,
        trim_lines: bool = True,
        pattern: str | None = None,
        *,
        split_lines: typing.Literal[False],
    ) -> str: ...
    @staticmethod
    def read_stdin_multiline(
        prompt_text: str = "Enter text (one per line)",
        skip_empty: bool = True,
        trim_lines: bool = True,
        pattern: str | None = None,
        split_lines: bool = True,
    ) -> list[str] | str:
        """Read multi-line text from stdin with EOF prompt.

        Args:
            prompt_text: Description of what to enter.
            skip_empty: Whether to skip empty lines (only when *split_lines* is True).
            trim_lines: Whether to strip whitespace from each line (only when *split_lines* is True).
            pattern: Regex pattern for validation (reserved, not yet implemented).
            split_lines: If True, return list of lines; if False, return raw string.

        Returns:
            List of processed lines (``split_lines=True``) or raw string (``split_lines=False``).
            Calls ``sys.exit(1)`` if input is empty.
        """
        print(f"{FLYellow}{prompt_text}{CRst}")
        print(f"{FLCyan}End with {FLYellow}Ctrl+Z (Windows) or Ctrl+D (Linux/macOS){FLCyan}:{CRst}")
        raw = sys.stdin.read()
        if split_lines:
            raw_stripped = raw.strip()
            if not raw_stripped:
                print(f"{FLRed}No input provided. EXIT...{CRst}\n")
                sys.exit(1)
            lines: list[str] = []
            for line in raw_stripped.splitlines():
                if trim_lines:
                    line = line.strip()
                if skip_empty and not line:
                    continue
                lines.append(line)
            if not lines:
                print(f"{FLRed}No valid input provided. EXIT...{CRst}\n")
                sys.exit(1)
            return lines
        else:
            if not raw.strip():
                print(f"{FLRed}No input provided. EXIT...{CRst}\n")
                sys.exit(1)
            return raw


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
