"""Color foreground segmentation at the region detector's 1200-pixel width.

This supplements gray texture detection: saturated lettering and small icons
need no gray texture, and full-page illustrations must not hit its size cap.
Pale paper and chromatic JPEG fringes around neutral ink are excluded. Sparse
frames are split so their enclosing body text can still become one-bit pixels.
The text-like classification is geometric/color evidence, not OCR.
"""

import cv2
import numpy as np
from numpy.typing import NDArray

type Pixels = NDArray[np.uint8]
type Box = tuple[int, int, int, int]


def _split(mask: Pixels, depth: int = 0) -> list[Box]:
    """Bound recursion and cut long sparse networks into compact crop boxes."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return []
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    patch = mask[y0:y1, x0:x1]
    height, width = patch.shape
    density = float(patch.mean())
    if (density >= .24 or width * height < 8000 or min(width, height) < 14
            or depth >= 8 or (max(width, height) < 350 and density >= .06)):
        return [(x0, y0, x1, y1)]
    if depth == 0:
        horizontal = np.asarray(cv2.morphologyEx(patch, cv2.MORPH_OPEN, np.ones((1, 70), np.uint8)), dtype=np.uint8)
        vertical = np.asarray(cv2.morphologyEx(patch, cv2.MORPH_OPEN, np.ones((70, 1), np.uint8)), dtype=np.uint8)
        lines = horizontal | vertical
        if lines.sum() > patch.sum() * .15:
            result: list[Box] = []
            for direction in (horizontal, vertical):
                _, _, stats, _ = cv2.connectedComponentsWithStats(direction, connectivity=8)
                result.extend((x0 + int(x), y0 + int(y), x0 + int(x + w), y0 + int(y + h))
                              for x, y, w, h, _ in stats[1:])
            rest = patch & ~np.asarray(cv2.dilate(lines, np.ones((3, 3), np.uint8)), dtype=np.uint8)
            _, labels, stats, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
            for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
                if area < 6:
                    continue
                children = _split(np.asarray(labels[y:y + h, x:x + w] == label, dtype=np.uint8), depth + 1)
                result.extend((x0 + int(x) + a, y0 + int(y) + b,
                               x0 + int(x) + c, y0 + int(y) + d) for a, b, c, d in children)
            return result
    axis = 0 if width >= height else 1
    projection = patch.sum(axis=axis)
    length = len(projection)
    start, end = length // 4, length * 3 // 4
    cut = start + int(np.argmin(projection[start:end]))
    parts = (((0, 0), patch[:, :cut]), ((cut, 0), patch[:, cut:])) if axis == 0 else (
        ((0, 0), patch[:cut]), ((0, cut), patch[cut:]))
    return [(x0 + dx + a, y0 + dy + b, x0 + dx + c, y0 + dy + d)
            for (dx, dy), part in parts for a, b, c, d in _split(part, depth + 1)]


def _text_like(rgb: Pixels, gray: Pixels, ink: Pixels) -> bool:
    """Conservatively recognize small, mostly monochromatic colored strokes.

    Thin rules, filled panels and multicolor illustrations stay on the ordinary
    crop path. Small monochrome symbols can resemble letters; either path keeps
    their shape, but the optional palette path changes their color precision.
    """
    height, width = gray.shape
    if min(width, height) < 9 or height > 100 or width > 500:
        return False
    selected = ink != 0
    if not .025 <= float(selected.mean()) <= .55 or selected.sum() < 12:
        return False
    colors = rgb[selected].astype(np.float32)
    # Antialiased edges mix the ink with paper and vary greatly in RGB distance.
    # Normalized channel differences retain their hue throughout that mixture.
    colors -= colors.min(axis=1, keepdims=True)
    colors /= np.maximum(1, colors.max(axis=1, keepdims=True))
    center = np.median(colors, axis=0)
    if np.mean(np.max(np.abs(colors - center), axis=1) < .2) < .8:
        return False
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2)
    if np.mean((gray < 160) & (chroma < 15)) > .08:
        return False
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    components = stats[1:]
    glyphs = ((components[:, 2] >= 3) & (components[:, 2] <= 80)
              & (components[:, 3] >= 5) & (components[:, 3] <= 80)
              & (components[:, 4] >= 8)
              & (components[:, 4] < components[:, 2] * components[:, 3] * .8))
    return bool(components[glyphs, 4].sum() >= selected.sum() * .65)


def detect(rgb: Pixels, gray: Pixels, cutoff: float) -> list[tuple[Box, bool]]:
    """Return bounded color foreground crops and their text-like classifications.

    All geometry is in analysis pixels. Higher cutoff requires more independent
    color evidence per component, including evidence away from neutral strokes.
    """
    chroma = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2)
    strong = (chroma >= 35) & ((gray < 210) | (chroma >= 70))
    neutral = (gray < 160) & (chroma < 15)
    strong &= cv2.dilate(np.asarray(neutral, dtype=np.uint8), np.ones((3, 3), np.uint8)) == 0
    weak = (chroma >= 24) & ((gray < 215) | (chroma >= 65))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.asarray(weak, dtype=np.uint8), connectivity=8)
    counts = np.bincount(labels[strong], minlength=len(stats))
    selected = (counts >= 8 * cutoff) & (stats[:, 4] >= 12 * cutoff)
    selected[0] = False
    ink = np.asarray(selected[labels], dtype=np.uint8)
    mask = np.asarray(cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((5, 11), np.uint8)), dtype=np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        cv2.dilate(mask, np.ones((9, 9), np.uint8)), connectivity=8)
    result: list[tuple[Box, bool]] = []
    for label, (x, y, width, height, area) in enumerate(stats[1:], 1):
        if area < 16 * cutoff:
            continue
        patch = mask[y:y + height, x:x + width] & np.asarray(labels[y:y + height, x:x + width] == label, dtype=np.uint8)
        for a, b, c, d in _split(patch):
            x0, y0 = max(0, int(x) + a - 3), max(0, int(y) + b - 3)
            x1, y1 = min(gray.shape[1], int(x) + c + 3), min(gray.shape[0], int(y) + d + 3)
            text = _text_like(rgb[y0:y1, x0:x1], gray[y0:y1, x0:x1], ink[y0:y1, x0:x1])
            result.append(((x0, y0, x1, y1), text))
    return result
