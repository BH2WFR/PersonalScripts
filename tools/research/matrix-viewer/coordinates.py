"""Uniform sample coordinates shared by transforms, renderers and exports.

Requirements: numpy. Usage: imported by the viewer's data model and workspace.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True)
class AxisMap:
    """Invertible affine map from source to displayed coordinates."""

    scale: float = 1.0
    offset: float = 0.0

    def forward(self, value: float) -> float:
        """Map a source coordinate to the display."""
        return value * self.scale + self.offset

    def inverse(self, value: float) -> float:
        """Recover the source coordinate from the display."""
        return (value - self.offset) / self.scale

    def array(self, values: ArrayLike) -> NDArray[np.float64]:
        """Map a numeric coordinate vector without modifying it."""
        return np.asarray(values, dtype=np.float64) * self.scale + self.offset

    def then(self, other: "AxisMap") -> "AxisMap":
        """Compose this map followed by another affine map."""
        return AxisMap(self.scale * other.scale, self.offset * other.scale + other.offset)


@dataclass(frozen=True)
class AxisCoordinates:
    """Positive, uniform sample spacing, physical unit and domain identity."""

    origin: float = 0.0
    spacing: float = 1.0
    unit: str = "sample"
    frequency: bool = False
    symbol: str | None = None

    @property
    def mapping(self) -> AxisMap:
        """Map absolute array indices to physical coordinates."""
        return AxisMap(self.spacing, self.origin)

    def values(self, start: int, count: int) -> NDArray[np.float64]:
        """Return the coordinates for a contiguous source-index range."""
        return self.mapping.array(np.arange(start, start + count, dtype=np.float64))

    def label(self, axis: str = "X") -> str:
        """Return a short axis label with its physical unit."""
        name = self.symbol or ('f' + axis.lower() if self.frequency else axis)
        return f"{name} ({self.unit})"


def reciprocal_unit(unit: str) -> str:
    """Express cycles per source unit, with common time-frequency abbreviations."""
    if unit == "s":
        return "Hz"
    if unit == "Hz":
        return "s"
    if unit.startswith("cycles/"):
        return unit[7:]
    return f"cycles/{unit}"
