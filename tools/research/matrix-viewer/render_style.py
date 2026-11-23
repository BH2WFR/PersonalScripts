"""Display-only sample rendering choices shared by views and workspace layers.

Requirements: standard library. Usage: CurveStyle defines 1D signal/derivative
lines and points; ImageStyle and SurfaceStyle define 2D/3D rendering. Views,
controls and overlays import these canonical definitions. CurveStyle retains
its integer IDs for existing per-channel settings. Line widths and point sizes are screen
pixels and never change source samples or numeric exports.
"""

from enum import IntEnum, StrEnum

DEFAULT_POINT_SIZE = 2.0
MIN_POINT_SIZE = 0.5
MAX_POINT_SIZE = 64.0
DEFAULT_LINE_WIDTH = 1.0
DEFAULT_DASH_SCALE = 1.0
DEFAULT_LINE_COLOR = "#0066ff"
MIN_LINE_WIDTH = 0.5
MAX_LINE_WIDTH = 20.0


class CurveStyle(IntEnum):
    """Available 1D line/marker combinations, with stable control/settings IDs."""

    LINE = 0
    POINTS = 1
    BOTH = 2

    @property
    def label(self) -> str:
        """Return the shared user-facing label for signal/derivative controls."""
        return {CurveStyle.LINE: "Line", CurveStyle.POINTS: "Points", CurveStyle.BOTH: "Line + points"}[self]


class LineStyle(IntEnum):
    """Stable pattern IDs; the first five match Qt's visible built-in styles."""

    SOLID = 1
    DASH = 2
    DOT = 3
    DASH_DOT = 4
    DASH_DOT_DOT = 5
    LONG_DASH = 6
    LONG_SHORT = 7
    DASH_THREE_DOTS = 8

    @property
    def label(self) -> str:
        """Return the user-facing pen pattern name."""
        return {LineStyle.SOLID: "Solid", LineStyle.DASH: "Dashed", LineStyle.DOT: "Dotted",
                LineStyle.DASH_DOT: "Dash-dot", LineStyle.DASH_DOT_DOT: "Dash-dot-dot",
                LineStyle.LONG_DASH: "Long dash", LineStyle.LONG_SHORT: "Alternating long / short",
                LineStyle.DASH_THREE_DOTS: "Dash and three dots"}[self]


# Alternating strokes and spaces in Qt pen-width units.
DASH_PRESETS: dict[LineStyle, tuple[float, ...]] = {
    LineStyle.LONG_DASH: (10, 3),
    LineStyle.LONG_SHORT: (8, 3, 3, 3),
    LineStyle.DASH_THREE_DOTS: (6, 2, 1, 2, 1, 2, 1, 2),
}


class PointShape(StrEnum):
    """All built-in pyqtgraph scatter symbols, using stable library keys."""

    CIRCLE = "o"
    SQUARE = "s"
    DIAMOND = "d"
    TRIANGLE_UP = "t1"
    TRIANGLE_DOWN = "t"
    TRIANGLE_RIGHT = "t2"
    TRIANGLE_LEFT = "t3"
    PLUS = "+"
    CROSS = "x"
    PENTAGON = "p"
    HEXAGON = "h"
    STAR = "star"
    VERTICAL_BAR = "|"
    HORIZONTAL_BAR = "_"
    ARROW_UP = "arrow_up"
    ARROW_RIGHT = "arrow_right"
    ARROW_DOWN = "arrow_down"
    ARROW_LEFT = "arrow_left"
    CROSSHAIR = "crosshair"

    @property
    def label(self) -> str:
        """Return a readable symbol name without exposing library keys."""
        return self.name.replace("_", " ").capitalize()


class ImageStyle(StrEnum):
    """Render a matrix as filled pixels or discrete sample centers."""

    IMAGE = "Image"
    POINTS = "Points"


class SurfaceStyle(StrEnum):
    """Render a height field as connected faces or discrete XYZ samples."""

    SURFACE = "Surface"
    POINTS = "Points"
