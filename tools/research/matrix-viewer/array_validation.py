"""Validate ordinary numeric file arrays before they reach the viewer.

Requirements: numpy. Usage: shared by NumPy, text and MATLAB file loaders.
Image channel buffers are validated separately by the image decoder.
"""

import numpy as np
from numpy.typing import NDArray

NUMERIC_KINDS = frozenset("buifc")
SUPPORTED_RANKS = (1, 2)


def validate_shape(shape: tuple[int, ...], label: str, *, allow_3d: bool = False) -> None:
    """Reject empty arrays and ranks outside the file-loading contract.

    Args:
        shape: Source dimensions, without squeezing singleton axes.
        label: Array or variable description included in errors.
        allow_3d: Accept rank 3 only during explicit channel-split import.

    Raises:
        ValueError: The shape is empty, scalar or exceeds the permitted rank.
    """
    if len(shape) not in SUPPORTED_RANKS and not (allow_3d and len(shape) == 3):
        remedy = "Save a one-element vector instead." if not shape else "Select a 1D/2D slice before saving."
        raise ValueError(f"{label}: unsupported {len(shape)}D array, shape={shape}. "
                         f"Only 1D and 2D arrays are supported. {remedy}")
    if any(size == 0 for size in shape):
        raise ValueError(f"{label}: the array is empty (shape={shape}).")


def validate_numeric_array(value: object, label: str, *, allow_3d: bool = False) -> NDArray[np.generic]:
    """Require a nonempty dense 1D/2D numeric array, preserving source values.

    Args:
        value: Decoded source; objects and structured arrays are not accepted.
        label: Array or variable description included in errors.
        allow_3d: Accept rank 3 for splitting before workspace insertion.

    Returns:
        The original array, without copying, squeezing or changing its dtype.

    Raises:
        ValueError: The value is not a supported numeric array or shape.
    """
    if not isinstance(value, np.ndarray):
        raise ValueError(f"{label}: expected a dense numeric array, got {type(value).__name__}.")
    if value.dtype.kind not in NUMERIC_KINDS:
        raise ValueError(f"{label}: unsupported dtype={value.dtype}, shape={value.shape}. "
                         "Only boolean, integer, real and complex numeric arrays are supported; "
                         "object, string and structured arrays are not supported.")
    validate_shape(value.shape, label, allow_3d=allow_3d)
    return value
