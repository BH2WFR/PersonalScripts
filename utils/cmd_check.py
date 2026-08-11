"""Command-check descriptor used by :class:`utils.Environment`."""

import dataclasses
import typing

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
        path: Populated by :meth:`Environment.check_commands` — resolved executable
            path, or ``None`` if not found.
    """
    cmd: typing.Union[str, list[str]]
    required: bool = True
    hints: typing.Optional[dict[str, str]] = None
    path: typing.Optional[str] = dataclasses.field(default=None, init=False)
