"""Display-only sample rendering choices shared by views and workspace layers.

Requirements: standard library. Usage: CurveStyle defines 1D signal/derivative
lines and points; ImageStyle and SurfaceStyle define 2D/3D rendering. Views,
controls and overlays import these canonical definitions. CurveStyle retains
its integer IDs for existing per-channel settings. Point sizes are screen
pixels and never change source samples or numeric exports.
"""

from enum import IntEnum, StrEnum

DEFAULT_POINT_SIZE = 2.0
MIN_POINT_SIZE = 0.5
MAX_POINT_SIZE = 64.0


class CurveStyle(IntEnum):
    """Available 1D line/marker combinations, with stable control/settings IDs."""

    LINE = 0
    POINTS = 1
    BOTH = 2

    @property
    def label(self) -> str:
        """Return the shared user-facing label for signal/derivative controls."""
        return {CurveStyle.LINE: "Line", CurveStyle.POINTS: "Points", CurveStyle.BOTH: "Line + points"}[self]


class ImageStyle(StrEnum):
    """Render a matrix as filled pixels or discrete sample centers."""

    IMAGE = "Image"
    POINTS = "Points"


class SurfaceStyle(StrEnum):
    """Render a height field as connected faces or discrete XYZ samples."""

    SURFACE = "Surface"
    POINTS = "Points"
