"""Overlapping OCR tiles, page-coordinate reconstruction and seam deduplication."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
import numpy as np
from .model import Result, Settings, Token


@dataclass(frozen=True)
class Tile:
    """Pixel crop and disjoint ownership rectangle in whole-image coordinates."""

    rect: tuple[int, int, int, int]
    owner: tuple[float, float, float, float]


def tiles(width: int, height: int, size: int, overlap: int) -> Iterator[Tile]:
    """Cover every pixel, keeping context around each tile's ownership region."""
    def axis(length: int) -> list[tuple[int, int, float, float]]:
        if length <= size:
            return [(0, length, 0., float(length))]
        stride = max(1, round(size * (1 - overlap / 100)))
        starts = sorted(set([*range(0, length - size + 1, stride), length - size]))
        return [(start, start + size,
                 (starts[i - 1] + size + start) / 2 if i else 0.,
                 (start + size + starts[i + 1]) / 2 if i + 1 < len(starts) else float(length))
                for i, start in enumerate(starts)]
    for y0, y1, top, bottom in axis(height):
        for x0, x1, left, right in axis(width):
            yield Tile((x0, y0, x1, y1), (left, top, right, bottom))


def _subset_text(text: str, tokens: tuple[Token, ...], selected: list[int]) -> str:
    """Keep original separators between retained adjacent words/characters."""
    if len(selected) == len(tokens):
        return text
    selected_set = set(selected)
    pieces: list[str] = []
    cursor, previous_end, previous_index = 0, 0, -2
    for index, token in enumerate(tokens):
        start = text.find(token.text, cursor)
        if index in selected_set:
            if pieces:
                pieces.append(text[previous_end:start] if start >= previous_end and previous_index == index - 1 else " ")
            pieces.append(token.text)
            previous_end = start + len(token.text) if start >= 0 else cursor
            previous_index = index
        if start >= 0:
            cursor = start + len(token.text)
    return "".join(pieces).strip()


def _join_line_fragments(lines: list[tuple[str, tuple[Token, ...]]], width: int,
                         height: int) -> list[tuple[str, tuple[Token, ...]]]:
    """Join nearby horizontal fragments so tile boundaries do not become line breaks."""
    def geometry(tokens: tuple[Token, ...]) -> tuple[np.ndarray, bool]:
        points = np.asarray([token.quad for token in tokens]) * (width, height)
        low, high = points.min(axis=(0, 1)), points.max(axis=(0, 1))
        token_heights = np.ptp(points[:, :, 1], axis=1)
        edges = points[:, 1] - points[:, 0]
        horizontal = (high[1] - low[1] <= 1.6 * np.median(token_heights)
                      and np.all(np.abs(edges[:, 1]) <= .3 * np.abs(edges[:, 0])))
        return np.concatenate((low, high)), bool(horizontal)

    pending = [(text, tokens, *geometry(tokens)) for text, tokens in lines]
    merged: list[tuple[str, tuple[Token, ...], np.ndarray, bool]] = []
    for text, tokens, box, horizontal in sorted(pending, key=lambda row: row[2][0]):
        target = None
        if horizontal:
            for index, (_, _, prior, eligible) in enumerate(merged):
                h, ph = box[3] - box[1], prior[3] - prior[1]
                gap = box[0] - prior[2]
                if (eligible and -.15 * min(h, ph) <= gap <= max(h, ph)
                        and abs((box[1] + box[3] - prior[1] - prior[3]) / 2) < .4 * min(h, ph)):
                    target = index
                    break
        if target is None:
            merged.append((text, tokens, box, horizontal))
        else:
            old_text, old_tokens, _, _ = merged[target]
            separator = " " if old_text and text and old_text[-1].isascii() and old_text[-1].isalnum() and text[0].isascii() and text[0].isalnum() else ""
            combined = old_tokens + tokens
            merged[target] = (old_text + separator + text, combined, *geometry(combined))
    merged.sort(key=lambda row: (round(row[2][1] / 12), row[2][0]))
    return [(text, tokens) for text, tokens, _, _ in merged]


def recognize_tiled(rgb: np.ndarray, settings: Settings,
                    recognize: Callable[[np.ndarray, Callable[[], None]], Result],
                    checkpoint: Callable[[], None]) -> Result:
    """Run tiles serially; retain owned anchors and remove residual seam duplicates.

    Each anchor is assigned by its center to one tile's overlap midpoint region.
    A final cross-tile overlap check resolves position jitter. Original line text
    is retained where possible; no duplicate OCR text is appended at seams.
    """
    height, width = rgb.shape[:2]
    windows = list(tiles(width, height, settings.tile_size, settings.tile_overlap))
    if len(windows) == 1:
        return recognize(rgb, checkpoint)
    groups: list[tuple[str, tuple[Token, ...]]] = []
    records: list[tuple[int, int, int, Token]] = []
    for tile_index, tile in enumerate(windows):
        checkpoint()
        x0, y0, x1, y1 = tile.rect
        result = recognize(np.ascontiguousarray(rgb[y0:y1, x0:x1]), checkpoint)
        checkpoint()
        transformed = tuple(replace(token, quad=tuple(((x0 + x * (x1 - x0)) / width,
            (y0 + y * (y1 - y0)) / height) for x, y in token.quad)) for token in result.tokens)
        lengths = result.line_lengths or (len(transformed),)
        texts = result.text.split("\n") if result.line_lengths else [result.text]
        offset = 0
        for text, count in zip(texts, lengths):
            tokens = transformed[offset:offset + count]
            offset += count
            group = len(groups)
            groups.append((text, tokens))
            for index, token in enumerate(tokens):
                cx = sum(p[0] for p in token.quad) * width / 4
                cy = sum(p[1] for p in token.quad) * height / 4
                left, top, right, bottom = tile.owner
                if left <= cx < right and top <= cy < bottom:
                    records.append((tile_index, group, index, token))
    selected: dict[int, list[int]] = {}
    boxes: list[list[float]] = []
    tile_ids: list[int] = []
    for tile_index, group, index, token in sorted(records, key=lambda row: row[3].score, reverse=True):
        checkpoint()
        points = np.asarray(token.quad)
        box = np.concatenate((points.min(axis=0), points.max(axis=0)))
        if boxes:
            prior = np.asarray(boxes)
            intersection = np.maximum(0, np.minimum(prior[:, 2:], box[2:]) - np.maximum(prior[:, :2], box[:2])).prod(axis=1)
            area = np.maximum(0, box[2:] - box[:2]).prod()
            smaller = np.minimum(area, np.maximum(0, prior[:, 2:] - prior[:, :2]).prod(axis=1))
            if np.any((np.asarray(tile_ids) != tile_index) & (intersection > .65 * np.maximum(smaller, 1e-12))):
                continue
        boxes.append(box.tolist())
        tile_ids.append(tile_index)
        selected.setdefault(group, []).append(index)
    lines: list[tuple[str, tuple[Token, ...]]] = []
    for group, indexes in selected.items():
        text, tokens = groups[group]
        indexes.sort()
        lines.append((_subset_text(text, tokens, indexes), tuple(tokens[index] for index in indexes)))
    lines = _join_line_fragments(lines, width, height)
    return Result("\n".join(text for text, _ in lines), tuple(token for _, tokens in lines for token in tokens),
                  tuple(len(tokens) for _, tokens in lines))
