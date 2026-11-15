"""Image-only recognition input and additive, invisible PDF text anchors."""

from collections.abc import Callable, Iterable
import io
import uuid

import numpy as np
import pymupdf
from utils import Pdf
from .model import Result, Settings, Token
from .preprocessing import preprocess
from .anchor_font import build_anchor_font


def recognition_image(page: pymupdf.Page, settings: Settings) -> np.ndarray:
    """Render RGB without annotations, masking existing native/OCR text to avoid duplicates."""
    pixmap = Pdf.render_page(page, dpi=settings.dpi, max_pixels=24_000_000, annotations=False)
    pixels = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
    pixels = preprocess(pixels, settings)
    scale = pymupdf.Matrix(pixmap.width / page.rect.width, pixmap.height / page.rect.height)
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                rect = pymupdf.Rect(span["bbox"]) * page.rotation_matrix * scale
                x0, y0 = max(0, int(rect.x0) - 1), max(0, int(rect.y0) - 1)
                x1, y1 = min(pixmap.width, int(rect.x1) + 2), min(pixmap.height, int(rect.y1) + 2)
                pixels[y0:y1, x0:x1] = 255
    return pixels


def token_points(page: pymupdf.Page, token: Token) -> list[pymupdf.Point]:
    """Map rendered-page fractions back to unrotated PDF crop coordinates."""
    return [pymupdf.Point(x * page.rect.width, y * page.rect.height) * page.derotation_matrix
            for x, y in token.quad]


class TextLayer:
    """Embed one subset font for new OCR text, leaving all original fonts untouched."""

    def __init__(self, results: Iterable[Result]) -> None:
        from fontTools import subset
        from fontTools.ttLib import TTFont

        characters = {ord(char) for result in results for token in result.tokens for char in token.text}
        buffer = io.BytesIO()
        base_font = pymupdf.Font("cjk")
        if any(not base_font.has_glyph(code) for code in characters if not chr(code).isspace()):
            self.buffer = build_anchor_font(characters)
        else:
            with TTFont(io.BytesIO(base_font.buffer)) as font:
                options = subset.Options()
                subsetter = subset.Subsetter(options)
                subsetter.populate(unicodes=characters)
                subsetter.subset(font)
                font.save(buffer)
            self.buffer = buffer.getvalue()
        self.font = pymupdf.Font(fontbuffer=self.buffer)
        self.name = f"OCR{uuid.uuid4().hex[:12]}"

    def write(self, page: pymupdf.Page, result: Result,
              checkpoint: Callable[[], None] = lambda: None) -> int:
        """Append hidden text at the detected anchors; existing page contents remain intact."""
        if not result.tokens:
            return 0
        page.wrap_contents()
        page.insert_font(fontname=self.name, fontbuffer=self.buffer)
        shape = page.new_shape()
        height = self.font.ascender - self.font.descender
        count = 0
        for token in result.tokens:
            checkpoint()
            text = token.text.replace("\n", " ").replace("\r", " ")
            width = self.font.text_length(text, fontsize=1)
            if not text.strip() or width <= 0 or len(token.quad) != 4:
                continue
            p0, p1, _, p3 = token_points(page, token)
            across, down = (p1 - p0) / width, (p3 - p0) / height
            if abs(across.x * down.y - across.y * down.x) < 1e-8:
                continue
            baseline = p0 + down * self.font.ascender
            # PDF morph coordinates are y-up; Page points are y-down.
            matrix = pymupdf.Matrix(across.x, -across.y, -down.x, down.y, 0, 0)
            shape.insert_text(baseline, text, fontname=self.name, fontsize=1,
                              morph=(baseline, matrix), render_mode=3)
            count += 1
        shape.commit(overlay=True)
        return count
