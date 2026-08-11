"""Interactive terminal input helpers."""

import glob as glob_module
import os
import re
import sys
import typing

from .ansi import *
from .menu import Menu
from .menu_option import MenuOption
from .paths import Paths

class Input:
    #* ============ 密码输入 ============
    @staticmethod
    def input_password(prompt: str = "Enter password") -> str:
        """Read a password from stdin without echoing characters.

        On Windows, falls back to plain ``input()`` when stdin is not a console
        (e.g. piped input).
        """
        if sys.platform == "win32":
            if not sys.stdin.isatty():
                return input(f"{FLYellow}{prompt}: {CRst}")
            import msvcrt
            print(f"{FLYellow}{prompt}: {CRst}", end="", flush=True)
            chars: list[str] = []
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    print()
                    break
                if ch == "\x08":  # backspace
                    if chars:
                        chars.pop()
                        print("\b \b", end="", flush=True)
                elif ch == "\x03":  # Ctrl+C
                    print("^C")
                    raise KeyboardInterrupt
                else:
                    chars.append(ch)
                    print("*", end="", flush=True)
            return "".join(chars)
        else:
            import termios
            import tty
            print(f"{FLYellow}{prompt}: {CRst}", end="", flush=True)
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                chars: list[str] = []
                while True:
                    b = sys.stdin.buffer.read(1)
                    if not b:
                        break
                    ch = b.decode("utf-8", errors="replace")
                    if ch in ("\r", "\n"):
                        print()
                        break
                    if ch == "\x7f":  # backspace
                        if chars:
                            chars.pop()
                            print("\b \b", end="", flush=True)
                    elif ord(ch) < 32:  # control char
                        pass
                    else:
                        chars.append(ch)
                        print("*", end="", flush=True)
                return "".join(chars)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    #* ============ 通用文本输入 ============
    @typing.overload
    @staticmethod
    def prompt(
        prompt_text: str,
        *,
        default: str = "",
        transform: typing.Optional[typing.Callable[[str], str]] = None,
        separator: None = None,
        deduplicate: bool = False,
    ) -> str: ...

    @typing.overload
    @staticmethod
    def prompt(
        prompt_text: str,
        *,
        default: str = "",
        transform: typing.Optional[typing.Callable[[str], str]] = None,
        separator: str,
        deduplicate: bool = False,
    ) -> list[str]: ...

    @staticmethod
    def prompt(
        prompt_text: str,
        *,
        default: str = "",
        transform: typing.Optional[typing.Callable[[str], str]] = None,
        separator: typing.Optional[str] = None,
        deduplicate: bool = False,
    ) -> typing.Union[str, list[str]]:
        """Prompt for text, optionally splitting it into a list.

        Args:
            prompt_text: The full prompt string (including formatting).
            default: Value returned when the user presses Enter without input.
            transform: Optional callable applied to the input string, or to
                each non-empty item when *separator* is set.
            separator: Split input on this string and return a list. Empty
                items are discarded. ``None`` preserves the ordinary string
                return behavior.
            deduplicate: Remove duplicate items while preserving input order.
                Only applies when *separator* is set.

        Returns:
            The user's input (or *default* if empty), either as a string or a
            list of stripped non-empty items.
        """
        if separator == "":
            raise ValueError("separator cannot be empty")

        value = input(prompt_text).strip() or default
        if separator is None:
            return transform(value) if transform is not None else value

        items: list[str] = []
        for raw_item in value.split(separator):
            item = raw_item.strip()
            if not item:
                continue
            if transform is not None:
                item = transform(item)
            if not deduplicate or item not in items:
                items.append(item)
        return items

    #* ============ 数字输入 ============
    @staticmethod
    def input_number(
        prompt: str,
        *,
        default: typing.Optional[typing.Union[int, float]] = None,
        min_value: typing.Optional[typing.Union[int, float]] = None,
        max_value: typing.Optional[typing.Union[int, float]] = None,
        min_value_allowed: bool = True,
        max_value_allowed: bool = True,
        allow_float: bool = True,
        allow_negative: bool = True,
        exit_on_empty: bool = True,
    ) -> typing.Union[int, float]:
        """Interactively read a number with validation.

        Empty input returns *default* when provided. If there is no default and
        *exit_on_empty* is True, the process exits cleanly; otherwise it re-prompts.
        Boundary inclusiveness is controlled by *min_value_allowed* and
        *max_value_allowed*. By default, bounds are inclusive.
        """
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError("min_value cannot be greater than max_value")
        if (
            min_value is not None
            and max_value is not None
            and min_value == max_value
            and (not min_value_allowed or not max_value_allowed)
        ):
            raise ValueError("empty numeric range: equal bounds must both be allowed")

        while True:
            default_hint = f" {FGray}[{default}]{CRst}" if default is not None else ""
            raw = input(f"{FLYellow}{prompt}{default_hint}: {CRst}").strip()

            if not raw:
                if default is not None:
                    value = default
                elif exit_on_empty:
                    print(f"{FLRed}Exiting.{CRst}")
                    sys.exit(0)
                else:
                    print(f"{FLRed}Input is required.{CRst}")
                    continue
            else:
                try:
                    if allow_float:
                        value = float(raw)
                    else:
                        if re.search(r"[.eE]", raw):
                            raise ValueError
                        value = int(raw, 10)
                except ValueError:
                    expected = "number" if allow_float else "integer"
                    print(f"{FLRed}Invalid {expected}: {FGray}{raw}{CRst}")
                    continue

            if not allow_negative and value < 0:
                print(f"{FLRed}Negative values are not allowed.{CRst}")
                continue
            if min_value is not None and (
                value < min_value or (value == min_value and not min_value_allowed)
            ):
                op = ">=" if min_value_allowed else ">"
                print(f"{FLRed}Value must be {op} {FLYellow}{min_value}{CRst}")
                continue
            if max_value is not None and (
                value > max_value or (value == max_value and not max_value_allowed)
            ):
                op = "<=" if max_value_allowed else "<"
                print(f"{FLRed}Value must be {op} {FLYellow}{max_value}{CRst}")
                continue

            if allow_float:
                return float(value)
            return int(value)

    @staticmethod
    def input_number_with_unit(
        prompt: str,
        *,
        default: typing.Optional[tuple[typing.Union[int, float], str]] = None,
        default_unit: typing.Optional[str] = None,
        allowed_units: typing.Optional[typing.Iterable[str]] = None,
        min_value: typing.Optional[typing.Union[int, float]] = None,
        max_value: typing.Optional[typing.Union[int, float]] = None,
        min_value_allowed: bool = True,
        max_value_allowed: bool = True,
        allow_float: bool = True,
        allow_negative: bool = True,
        allow_unit_only: bool = True,
        exit_on_empty: bool = True,
    ) -> tuple[typing.Union[int, float], str]:
        """Interactively read a number followed by a unit.

        Accepts inputs with or without a space between number and unit, such as
        ``90deg`` or ``90 deg``. If *default_unit* is provided, the unit may be
        omitted. Unit strings may not contain ``,`` or ``.``. Boundary
        inclusiveness is controlled by *min_value_allowed* and
        *max_value_allowed*. By default, bounds are inclusive.
        """
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError("min_value cannot be greater than max_value")
        if (
            min_value is not None
            and max_value is not None
            and min_value == max_value
            and (not min_value_allowed or not max_value_allowed)
        ):
            raise ValueError("empty numeric range: equal bounds must both be allowed")

        allowed: typing.Optional[set[str]] = None
        if allowed_units is not None:
            allowed = {u.lower() for u in allowed_units}
            for unit in allowed:
                if "," in unit or "." in unit:
                    raise ValueError("unit must not contain ',' or '.'")

        if default_unit is not None and ("," in default_unit or "." in default_unit):
            raise ValueError("unit must not contain ',' or '.'")

        number_pattern = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
        full_pattern = re.compile(rf"^\s*({number_pattern})\s*([^\s,.]+)?\s*$")
        unit_only_pattern = re.compile(r"^\s*([^\s,.]+)\s*$")

        while True:
            default_hint = ""
            if default is not None:
                default_hint = f" {FGray}[{default[0]}{default[1]}]{CRst}"
            raw = input(f"{FLYellow}{prompt}{default_hint}: {CRst}").strip()

            if not raw:
                if default is not None:
                    number, unit = default
                elif exit_on_empty:
                    print(f"{FLRed}Exiting.{CRst}")
                    sys.exit(0)
                else:
                    print(f"{FLRed}Input is required.{CRst}")
                    continue
            else:
                match = full_pattern.match(raw)
                if match:
                    number_raw = match.group(1)
                    unit = match.group(2) or default_unit
                    if unit is None:
                        print(f"{FLRed}Unit is required.{CRst}")
                        continue
                    try:
                        if allow_float:
                            number = float(number_raw)
                        else:
                            if re.search(r"[.eE]", number_raw):
                                raise ValueError
                            number = int(number_raw, 10)
                    except ValueError:
                        expected = "number" if allow_float else "integer"
                        print(f"{FLRed}Invalid {expected}: {FGray}{number_raw}{CRst}")
                        continue
                elif allow_unit_only:
                    unit_match = unit_only_pattern.match(raw)
                    if not unit_match:
                        print(f"{FLRed}Invalid number with unit: {FGray}{raw}{CRst}")
                        continue
                    number = 1.0 if allow_float else 1
                    unit = unit_match.group(1)
                else:
                    print(f"{FLRed}Invalid number with unit: {FGray}{raw}{CRst}")
                    continue

            unit = str(unit)
            if "," in unit or "." in unit:
                print(f"{FLRed}Unit must not contain ',' or '.': {FGray}{unit}{CRst}")
                continue

            unit_key = unit.lower()
            if allowed is not None and unit_key not in allowed:
                print(f"{FLRed}Invalid unit. Try {FLYellow}{', '.join(sorted(allowed))}{CRst}")
                continue
            if not allow_negative and number < 0:
                print(f"{FLRed}Negative values are not allowed.{CRst}")
                continue
            if min_value is not None and (
                number < min_value or (number == min_value and not min_value_allowed)
            ):
                op = ">=" if min_value_allowed else ">"
                print(f"{FLRed}Value must be {op} {FLYellow}{min_value}{CRst}")
                continue
            if max_value is not None and (
                number > max_value or (number == max_value and not max_value_allowed)
            ):
                op = "<=" if max_value_allowed else "<"
                print(f"{FLRed}Value must be {op} {FLYellow}{max_value}{CRst}")
                continue

            if allow_float:
                return float(number), unit_key
            return int(number), unit_key

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
    def _prompt_and_normalize_path(
        default_path: str,
        prompt: str,
        *,
        expand_env_vars: bool,
    ) -> str:
        """Prompt for one path and return its normalized absolute form."""
        default_hint = f" {FGray}[{default_path}]{CRst}" if default_path else ""
        while True:
            user_path = Input.prompt(
                f"{FLYellow}{prompt}{default_hint}: {CRst}",
                default=default_path,
            )
            if user_path:
                break
            print(f"{FLRed}Input is required.{CRst}")
        return Input._normalize_path(
            user_path,
            base_dir=os.path.dirname(default_path) or ".",
            expand_env_vars=expand_env_vars,
        )

    @staticmethod
    def _normalize_path(
        path: str,
        *,
        base_dir: str,
        expand_env_vars: bool,
    ) -> str:
        """Normalize one path without checking its existence or type."""
        normalized = os.path.expanduser(path.strip("'\""))
        if expand_env_vars:
            normalized = Paths.resolve_vars(normalized)
        if os.path.dirname(normalized) == "":
            normalized = os.path.join(base_dir, normalized)
        return os.path.abspath(normalized)

    @staticmethod
    def _path_status(path: str, path_type: str) -> tuple[bool, bool]:
        """Return ``(exists, matches_type)`` for a supported path type."""
        if path_type not in {"file", "dir", "link", "any"}:
            raise ValueError(f"Unsupported path_type: {path_type}")
        exists = os.path.lexists(path) if path_type == "link" else os.path.exists(path)
        if path_type == "any":
            matches_type = exists
        elif path_type == "link":
            matches_type = os.path.islink(path)
        elif path_type == "file":
            matches_type = os.path.isfile(path)
        else:
            matches_type = os.path.isdir(path)
        return exists, matches_type

    @staticmethod
    def _describe_path_kind(path: str) -> str:
        """Return a short description of the filesystem entry at *path*."""
        if os.path.islink(path):
            return "symlink"
        if os.path.isdir(path):
            return "folder"
        if os.path.isfile(path):
            return "file"
        return "non-regular filesystem entry"

    @staticmethod
    def _select_path_action(
        options: list[MenuOption],
        *,
        prompt: str,
        default_key: str,
    ) -> str:
        """Display a path-resolution action menu and return its action value."""
        action = Menu.select(
            options,
            prompt=prompt,
            required=True,
            default_key=default_key,
            inline=True,
            separator=False,
        )
        if not isinstance(action, str):
            raise RuntimeError("Path action menu returned an invalid value.")
        return action

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
            user_path = Input._prompt_and_normalize_path(
                suggested,
                prompt,
                expand_env_vars=False,
            )

            # ----- ensure containing directory exists -----
            parent_dir = user_path if path_type == "dir" else (os.path.dirname(user_path) or ".")
            if not os.path.isdir(parent_dir):
                print(f"{FLRed}Directory does not exist: {FGray}{parent_dir}{CRst}")
                create = Input._select_path_action(
                    [
                        MenuOption(["Y", "YES"], "Create", "create", FLGreen),
                        MenuOption(
                            ["N", "NO"],
                            "Choose another path",
                            "retry",
                            FLRed,
                        ),
                    ],
                    prompt="Create it?",
                    default_key="Y",
                )
                if create == "create":
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
            exists, matches_type = Input._path_status(user_path, path_type)
            if not exists:
                return user_path

            # ----- collision menu (shown for any existing path, regardless of type) -----
            print(f"{FLYellow}Path already exists:{CRst} {FGray}{user_path}{CRst}")
            while True:
                action = Input._select_path_action(
                    [
                        MenuOption(
                            ["O", "OVERWRITE", "REPLACE"],
                            action_label,
                            "overwrite",
                            FLGreen,
                        ),
                        MenuOption(
                            ["R", "RENAME"],
                            "Rename",
                            "rename",
                            FLYellow,
                        ),
                        MenuOption(["E", "EXIT"], "Exit", "exit", FLRed),
                    ],
                    prompt="Existing output path",
                    default_key="R",
                )
                if action == "overwrite":
                    if matches_type:
                        return user_path
                    actual = Input._describe_path_kind(user_path)
                    print(
                        f"{FLRed}Path is a {actual}, but a {path_type} "
                        f"was expected: {FGray}{user_path}{CRst}"
                    )
                elif action == "exit":
                    print(f"{FLRed}Exiting.{CRst}")
                    sys.exit(0)
                elif action == "rename":
                    current_default = user_path
                    break


    @staticmethod
    def resolve_input_path(
        default_path: str,
        prompt: str           = "Enter input path",
        path_type: str        = "file",  # ``"file"``, ``"dir"``, ``"link"``, or ``"any"`` (only checks existence)
        expand_env_vars: bool = True,    # whether to expand environment variables in the input path, use ``$VAR``/``${VAR}``/``%VAR%`` syntax
        validate_exists: bool = True    # whether to check that the path exists; if False, accepts any path without validation
    ) -> str:
        """Interactive input path resolution with existence and type validation.

        Args:
            default_path: The base suggested path.
            prompt: Prompt text shown to the user.
            path_type: ``"file"``, ``"dir"``, ``"link"``, or ``"any"`` (only checks existence).
            expand_env_vars: If True (default), expand ``$VAR``/``${VAR}``,
                        ``%VAR%``, ``$ENV:VAR`` and ``${ENV:VAR}`` variables.
            validate_exists: If True (default), check path existence and type.
                             If False, accept any path including non-existing ones.

        Returns the final absolute path, or calls ``sys.exit(0)`` if the user chooses to quit.
        """
        current_default = os.path.expanduser(default_path)

        while True:
            user_path = Input._prompt_and_normalize_path(
                current_default,
                prompt,
                expand_env_vars=expand_env_vars,
            )

            if not validate_exists:
                return user_path

            # ----- check existence and type -----
            exists, matches_type = Input._path_status(user_path, path_type)
            if exists and matches_type:
                return user_path

            # ----- error message -----
            if not exists:
                print(f"{FLRed}Path does not exist: {FGray}{user_path}{CRst}")
            else:
                actual = Input._describe_path_kind(user_path)
                print(f"{FLRed}Path is a {actual}, but a {path_type} was expected: {FGray}{user_path}{CRst}")

            # ----- conflict / error menu -----
            action = Input._select_path_action(
                [
                    MenuOption(["R", "RENAME"], "Rename", "rename", FLYellow),
                    MenuOption(["F", "FORCE"], "Force use", "force", FLGreen),
                    MenuOption(["E", "EXIT"], "Exit", "exit", FLRed),
                ],
                prompt="Invalid input path",
                default_key="R",
            )
            if action == "rename":
                current_default = Input._find_available_path(user_path)
            elif action == "force":
                return user_path
            elif action == "exit":
                print(f"{FLRed}Exiting.{CRst}")
                sys.exit(0)


    @staticmethod
    def resolve_input_paths_multi(
        prompt_text: str    = "Enter paths (one per line)",
        path_type: str      = "any",  # `file`, `dir`, `link`, or `any`
        expand_env_vars: bool = True,   # whether to expand environment variables in the input paths, use `$VAR` `${VAR}` `%VAR%` syntax
        validate_exists: bool = True, # whether to check that each path exists and matches the specified type; if False, accepts any paths without validation
        glob: bool          = False   # whether to expand glob patterns (`*` `?` `[abc]`) in the input paths; when True, patterns with no matches are kept as-is, and matched paths are validated individually
    ) -> list[str]:
        """Read multiple paths interactively from stdin (EOF-terminated).

        - De-duplicates input
        - Expands glob patterns (``*``/``?``/``[abc]``) when *glob* is True
        - Validates each path (existence + type) unless *validate_exists* is False
        - For non-existing or wrong-type paths, prompts to keep or drop each one
        - Prints the final count of accepted paths
        - Exits with ``sys.exit(1)`` if no paths remain
        - Returns list of absolute paths

        Args:
            prompt_text: Description of what to enter.
            path_type: ``"file"``, ``"dir"``, ``"link"``, or ``"any"``.
            expand_env_vars: If True (default), expand ``$VAR``/``${VAR}``,
                ``%VAR%``, ``$ENV:VAR`` and ``${ENV:VAR}`` variables.
            validate_exists: If True (default), check path existence and type.
                If False, accept any path including non-existing ones.
            glob: If True, expand wildcard patterns (``*``/``?``/``[abc]``).
                Patterns with no matches are kept as-is.
        """
        paths = Input.read_stdin_multiline(prompt_text)
        if not paths:
            print(f"{FLRed}No paths provided.{CRst}")
            sys.exit(1)

        accepted: list[str] = []
        processed: set[str] = set()
        for raw_path in dict.fromkeys(paths):
            normalized = Input._normalize_path(
                raw_path,
                base_dir=os.getcwd(),
                expand_env_vars=expand_env_vars,
            )

            candidates = [normalized]
            if glob and glob_module.has_magic(normalized):
                candidates = sorted(glob_module.glob(normalized)) or candidates

            for path in candidates:
                path = os.path.abspath(path)
                if path in processed:
                    continue
                processed.add(path)

                if not validate_exists:
                    accepted.append(path)
                    continue

                exists, matches_type = Input._path_status(path, path_type)
                if exists and matches_type:
                    accepted.append(path)
                    continue

                if not exists:
                    print(f"{FLRed}Path does not exist: {FGray}{path}{CRst}")
                else:
                    actual = Input._describe_path_kind(path)
                    print(
                        f"{FLRed}Path is a {actual}, but a {path_type} "
                        f"was expected: {FGray}{path}{CRst}"
                    )

                action = Input._select_path_action(
                    [
                        MenuOption(["K", "KEEP"], "Keep", "keep", FLGreen),
                        MenuOption(["D", "DROP"], "Drop", "drop", FLRed),
                    ],
                    prompt="Invalid input path",
                    default_key="D",
                )
                if action == "keep":
                    accepted.append(path)

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
