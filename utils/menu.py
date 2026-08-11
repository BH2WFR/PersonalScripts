"""Interactive terminal menu helpers."""

import sys
import typing

from .ansi import *
from .menu_option import MenuOption

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
        
        if not key_color:
            key_color = CRst
            
        while True:
            if separator:
                print(sep_line)

            if inline:
                parts = []
                for opt in options:
                    k = opt.keys[0]
                    dc = opt.desc_color or default_desc_color
                    parts.append(
                        f"{indent}{FGray}[{key_color}{k}{FGray}]{CRst}"
                        f" {dc}{opt.description}{CRst}"
                    )
                print("  ".join(parts))
            else:
                for opt in options:
                    k = opt.keys[0]
                    dc = opt.desc_color or default_desc_color
                    print(
                        f"{indent}{FGray}[{key_color}{k}{FGray}]{CRst}"
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
            except EOFError:
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
