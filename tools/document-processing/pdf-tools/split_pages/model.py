"""Pure split geometry in normalized, displayed-page coordinates; no PDF or Qt I/O."""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import cast

from utils import *
from ..common.protocol import Json

MAX_PIECES = 16
EPSILON = 1e-7


class Axis(StrEnum):
    LEFT_RIGHT = "left_right"
    TOP_BOTTOM = "top_bottom"


@dataclass(frozen=True)
class Box:
    """One normalized crop, measured from the displayed page's top-left corner."""

    x0: float
    y0: float
    x1: float
    y1: float

    def values(self) -> tuple[float, float, float, float]:
        """Return normalized left/top/right/bottom for previews and transport."""
        return self.x0, self.y0, self.x1, self.y1

    def validate(self) -> None:
        """Reject nonfinite or empty geometry; out-of-page areas are allowed and padded."""
        if (not all(math.isfinite(value) for value in self.values())
                or not self.x0 < self.x1 or not self.y0 < self.y1):
            raise ValueError("Crop boxes must have finite coordinates and positive size.")

    def moved(self, dx: float, dy: float) -> "Box":
        """Translate by normalized offsets; raise ValueError instead of clipping edges."""
        result = Box(self.x0 + dx, self.y0 + dy, self.x1 + dx, self.y1 + dy)
        result.validate()
        return result


WHOLE_PAGE = Box(0, 0, 1, 1)


@dataclass(frozen=True)
class Settings:
    """Global split rules; start/end are physical one-based pages, end=0 means last."""

    count: int = 2
    axis: Axis = Axis.LEFT_RIGHT
    reverse: bool = False
    order: str = ""
    start: int = 1
    end: int = 0

    def sequence(self) -> tuple[int, ...]:
        """Return zero-based spatial box indexes in output order; reject bad permutations."""
        if not 1 <= self.count <= MAX_PIECES:
            raise ValueError(f"Pieces per page must be between 1 and {MAX_PIECES}.")
        indexes = (tuple(value - 1 for value in Input.parse_integer_ranges(self.order, allow_zero=False))
                   if self.order.strip() else tuple(range(self.count)))
        if sorted(indexes) != list(range(self.count)):
            raise ValueError(f"Order must contain each number from 1 to {self.count} exactly once.")
        return tuple(reversed(indexes)) if self.reverse else indexes

    def validate(self, page_count: int) -> None:
        """Validate physical range and ordering before changing UI state or exporting."""
        self.sequence()
        if not 1 <= self.start <= (self.end or page_count) <= page_count:
            raise ValueError("Split range must be inside the PDF, with first page <= last page.")

    def applies(self, page: int, page_count: int) -> bool:
        """Whether a one-based physical page is inside the global split range."""
        return self.start <= page <= (self.end or page_count)

    def boxes(self) -> tuple[Box, ...]:
        """Generate equal strips, in output order, along the chosen displayed axis."""
        indexes = self.sequence()
        return tuple(Box(i / self.count, 0, (i + 1) / self.count, 1)
                     if self.axis == Axis.LEFT_RIGHT else Box(0, i / self.count, 1, (i + 1) / self.count)
                     for i in indexes)

    def canvas_size(self) -> tuple[float, float]:
        """Return the fixed normalized output width/height for every split child page."""
        return (1 / self.count, 1) if self.axis == Axis.LEFT_RIGHT else (1, 1 / self.count)

    def to_data(self) -> dict[str, Json]:
        """Serialize scalar settings for the serial worker; no session files are written."""
        return {"count": self.count, "axis": self.axis.value, "reverse": self.reverse,
                "order": self.order, "start": self.start, "end": self.end}

    @classmethod
    def from_data(cls, data: dict[str, Json]) -> "Settings":
        """Read worker settings; invalid scalar values raise ValueError or TypeError."""
        return cls(int(cast(int, data.get("count", 2))), Axis(str(data.get("axis", Axis.LEFT_RIGHT))),
                   data.get("reverse") is True, str(data.get("order", "")),
                   int(cast(int, data.get("start", 1))), int(cast(int, data.get("end", 0))))


@dataclass(frozen=True)
class PageOverride:
    """An explicit whole page or independent crops already stored in output order."""

    keep: bool = False
    boxes: tuple[Box, ...] = ()
    canvas: tuple[float, float] | None = None

    def validate(self) -> None:
        """Reject empty custom layouts or invalid boxes before using an override."""
        if not self.keep and not 1 <= len(self.boxes) <= MAX_PIECES:
            raise ValueError(f"A custom page needs 1 to {MAX_PIECES} crop boxes.")
        for box in self.boxes:
            box.validate()
        if self.canvas is not None:
            width, height = self.canvas
            if not all(math.isfinite(v) and v > 0 for v in self.canvas):
                raise ValueError("Output page dimensions must be finite and positive.")
            if any(box.x1 - box.x0 > width + EPSILON or box.y1 - box.y0 > height + EPSILON for box in self.boxes):
                raise ValueError("A crop cannot be larger than its fixed output page. Reduce width or height.")

    def to_data(self) -> dict[str, Json]:
        """Serialize the explicit override without PDF or Qt objects."""
        return {"keep": self.keep, "boxes": [list(box.values()) for box in self.boxes],
                "canvas": list(self.canvas) if self.canvas is not None else None}

    @classmethod
    def from_data(cls, data: dict[str, Json]) -> "PageOverride":
        """Read and validate a worker override; malformed geometry raises ValueError."""
        rows = cast(list[list[float]], data.get("boxes", []))
        if any(len(row) != 4 for row in rows):
            raise ValueError("Each crop requires four coordinates.")
        canvas = cast(list[float] | None, data.get("canvas"))
        if canvas is not None and len(canvas) != 2:
            raise ValueError("Output canvas needs width and height.")
        result = cls(data.get("keep") is True, tuple(Box(*(float(v) for v in row)) for row in rows),
                     (float(canvas[0]), float(canvas[1])) if canvas is not None else None)
        result.validate()
        return result


def page_boxes(settings: Settings, overrides: dict[int, PageOverride], page: int,
               page_count: int) -> tuple[Box, ...]:
    """Resolve one-based page rules; explicit overrides take priority over the global range."""
    if override := overrides.get(page):
        return (WHOLE_PAGE,) if override.keep else override.boxes
    return settings.boxes() if settings.applies(page, page_count) else (WHOLE_PAGE,)


def dividers(boxes: tuple[Box, ...], axis: Axis) -> tuple[tuple[int, int], ...]:
    """Find shared full edges; independent boxes with gaps/overlaps have no divider there."""
    indexes = sorted(range(len(boxes)), key=lambda i: boxes[i].x0 if axis == Axis.LEFT_RIGHT else boxes[i].y0)
    result: list[tuple[int, int]] = []
    for first, second in zip(indexes, indexes[1:]):
        a, b = boxes[first], boxes[second]
        pairs = ((a.x1, b.x0), (a.y0, b.y0), (a.y1, b.y1)) if axis == Axis.LEFT_RIGHT else (
                 (a.y1, b.y0), (a.x0, b.x0), (a.x1, b.x1))
        if all(abs(left - right) < EPSILON for left, right in pairs):
            result.append((first, second))
    return tuple(result)


def move_divider(boxes: tuple[Box, ...], axis: Axis, pair: tuple[int, int], position: float) -> tuple[Box, ...]:
    """Translate the whole layout to a shared edge position without changing crop sizes."""
    if pair not in dividers(boxes, axis):
        raise ValueError("These boxes no longer share a full edge. Adjust individual boxes instead.")
    first, _ = pair
    delta = position - (boxes[first].x1 if axis == Axis.LEFT_RIGHT else boxes[first].y1)
    return tuple(box.moved(delta, 0) if axis == Axis.LEFT_RIGHT else box.moved(0, delta) for box in boxes)
