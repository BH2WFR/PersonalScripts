"""Compact Unicode anchor font for scripts absent from MuPDF's bundled CJK font.

The outlines are deliberately generic: this font is used ONLY with rendering
mode 3. One distinct glyph ID per Unicode scalar preserves PDF ToUnicode maps;
preview text is drawn independently with Qt's real fonts. It does not shape text.
"""

import io
import unicodedata


def build_anchor_font(characters: set[int]) -> bytes:
    """Build an invisible-only font without downloading a full multilingual font."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    cmap = {code: f"u{code:06X}" for code in sorted(characters)}
    names = [".notdef", *cmap.values()]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap(cmap)
    glyphs = {}
    for name in names:
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        pen.lineTo((600, 0))
        pen.lineTo((600, 800))
        pen.lineTo((0, 800))
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    metrics = {name: (600, 0) for name in names}
    for code, name in cmap.items():
        if unicodedata.category(chr(code)) in ("Mn", "Me"):
            metrics[name] = (0, 0)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "OCR Anchors", "styleName": "Regular",
                           "uniqueFontIdentifier": "OCRAnchors-Regular", "fullName": "OCR Anchors",
                           "psName": "OCRAnchors-Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    buffer = io.BytesIO()
    builder.save(buffer)
    return buffer.getvalue()
