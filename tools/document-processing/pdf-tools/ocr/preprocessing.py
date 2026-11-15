"""Geometry-preserving OCR input cleanup; never modifies PDF image streams."""

import cv2
import numpy as np
from .model import Settings


def preprocess(rgb: np.ndarray, settings: Settings) -> np.ndarray:
    """Apply optional denoising and luminance contrast, returning packed RGB.

    Auto levels stretch luminance's 1st/99th percentiles. Local contrast uses
    CLAHE. Color is retained unless grayscale is requested; no rotation, resize
    or crop is performed, so recognition coordinates still match the source.
    """
    if not settings.grayscale and settings.contrast == "off" and settings.denoise == "off":
        return rgb
    working = rgb
    if settings.denoise == "median":
        working = cv2.medianBlur(working, 3)
    elif settings.denoise == "bilateral":
        working = cv2.bilateralFilter(working, 5, 25, 25)
    if settings.grayscale:
        luminance = cv2.cvtColor(working, cv2.COLOR_RGB2GRAY)
        lab = None
    elif settings.contrast != "off":
        lab = cv2.cvtColor(working, cv2.COLOR_RGB2LAB)
        luminance = lab[:, :, 0]
    else:
        return np.ascontiguousarray(working)
    if settings.contrast == "auto":
        low, high = np.percentile(luminance, (1, 99))
        if high - low > 1:
            luminance = np.clip((luminance.astype(np.float32) - low) * (255 / (high - low)), 0, 255).astype(np.uint8)
    elif settings.contrast == "local":
        luminance = cv2.createCLAHE(clipLimit=settings.contrast_clip, tileGridSize=(8, 8)).apply(luminance)
    if lab is None:
        return cv2.cvtColor(luminance, cv2.COLOR_GRAY2RGB)
    lab[:, :, 0] = luminance
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
