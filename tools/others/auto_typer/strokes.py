"""Translate printable US-layout characters to the project's physical key names."""

import re
from typing import Protocol


_SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', "`1234567890-=[]\\;',./", strict=True))
_SPECIAL = {" ": "space", "\n": "enter", "\t": "tab"}
_UNSUPPORTED = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")


def validate_text(text: str) -> None:
    """Reject unsupported controls in newline-normalized text before any output."""
    if match := _UNSUPPORTED.search(text):
        raise ValueError(f"Unsupported character U+{ord(match[0]):04X} at position {match.start() + 1}.")


def ascii_key(char: str) -> tuple[str, bool]:
    """Return the base key and Shift state for one supported ASCII character."""
    if char in _SHIFTED:
        return _SHIFTED[char], True
    return _SPECIAL.get(char, char.lower()), char.isupper()


class Sender(Protocol):
    """Operations needed by the panel; target zero means no external recipient."""

    def target(self) -> int: ...
    def restore(self, target: int) -> None: ...
    def check_ready(self) -> None: ...
    def send(self, char: str) -> None: ...
