"""Expose PyObjC's dynamically resolved Quartz symbols to the macOS backend."""

from typing import Any


def __getattr__(name: str) -> Any:
    import Quartz

    return getattr(Quartz, name)
