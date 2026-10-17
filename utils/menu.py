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
        default_desc_color: str = FLCyan,
        separator: bool = True,
        separator_char: str = "─",
        separator_width: int = 44,
        separator_color: str = FLCyan,
        indent: str = "  ",
        accept_custom_string: bool = False,
        allow_multiple: bool = False,
    ) -> typing.Optional[typing.Any]:
        """Display an interactive menu and return the selected value.

        Prints a list of options (each prefixed with a ``[Key]`` bracket), prompts
        the user for input, validates it, and returns the corresponding value.

        Args:
            options: MenuOption list to choose from.
            prompt: Input prompt text (e.g. ``"Choice"`` → ``"Choice > "``).
            required: If ``True``, empty input re-prompts. If ``False`` and
                *default_key* is ``None``, empty input returns ``None`` in single
                mode or [] in multiple mode.
            default_key: If set, empty input returns the value whose key matches.
                Takes precedence over *required*. In multiple mode, may contain
                comma-separated keys and is validated before prompting.
            inline: ``True`` → all options on one line; ``False`` → one per line.
            key_color: ANSI color for the key character inside brackets.
            default_desc_color: Fallback *desc_color* for options without one.
            separator: Print separator lines before / after the options.
            separator_char: Character for separator lines.
            separator_width: Length of separator lines.
            separator_color: ANSI color for separator lines.
            indent: Leading whitespace for each option line.
            accept_custom_string: If ``True``, non-empty input that does not match
                any key is returned as-is instead of showing an error. In
                multiple mode, this applies to each comma-separated item.
            allow_multiple: If ``True``, accept comma-separated keys such as
                ``1,2,3`` and return a list, including for a single selection.
                Preserve input order and deduplicate aliases of the same option.
                Repeated custom strings are deduplicated by exact spelling.
                Empty input without a default returns [] unless required=True.
                Defaults to False, preserving the original single-value API.

        Returns:
            The ``MenuOption.value`` corresponding to the chosen key, or the raw
            input string when *accept_custom_string* is ``True`` and no key matches.
            With *allow_multiple*, a list of selected values/custom strings.
            Invalid items or empty comma-separated items retry the whole entry.
            Keys are case-insensitive; an exact key takes precedence over comma
            splitting. Numeric ranges are not expanded by this generic menu.

        Raises:
            ValueError: If *options* is empty, contains duplicate keys, or a
                multiple-selection default cannot be resolved.
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

        def multiple_values(raw: str) -> list[object] | None:
            """Resolve one multi-selection entry; None means retry all items."""
            tokens = [raw] if raw.upper() in key_map else raw.split(",")
            selected: list[object] = []
            seen: set[tuple[str, str]] = set()
            for token in tokens:
                token = token.strip()
                if not token:
                    return None
                option = key_map.get(token.upper())
                if option is not None:
                    identity = ("option", option.keys[0])
                    value = option.value
                elif accept_custom_string:
                    identity = ("custom", token)
                    value = token
                else:
                    return None
                if identity not in seen:
                    selected.append(value)
                    seen.add(identity)
            return selected

        multiple_default: list[object] | None = None
        if allow_multiple and default_key is not None:
            multiple_default = multiple_values(default_key.strip())
            if multiple_default is None:
                raise ValueError(f"Invalid multiple-selection default: {default_key!r}")
        display_prompt = f"{prompt} (comma-separated)" if allow_multiple else prompt

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
                    prompt_line = f"{FLYellow}{display_prompt} {FGray}[{default_key}]{CRst}{FLYellow} > {CRst}"
                else:
                    prompt_line = f"{FLYellow}{display_prompt} > {CRst}"
                raw_input = input(prompt_line).strip()
                choice = raw_input.upper()
            except EOFError:
                print()
                sys.exit(0)

            if not choice:
                if allow_multiple:
                    if multiple_default is not None:
                        return multiple_default
                    if required:
                        continue
                    return []
                if default_key is not None:
                    wanted = default_key.upper()
                    if wanted in key_map:
                        return key_map[wanted].value
                if required:
                    continue
                return None

            if allow_multiple:
                selected = multiple_values(raw_input)
                if selected is not None:
                    return selected
            else:
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
