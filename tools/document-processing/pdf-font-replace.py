#!/usr/bin/env python3
"""Replace PDF fonts while retaining text origins, advances and drawing order.

Interactively select source fonts from used PDF text (whole document or page ranges), enter
their PDF names, or replace all fonts. Source fonts need not be installed.
Filter by effective font size and ignore physical page ranges. Target fonts can
be searched by installed names/localized aliases or selected as TTF/OTF/TTC files.
Regular, bold, italic and bold-italic use matching faces, retaining existing text
matrices and synthetic styling. Missing faces/glyphs fail instead of falling back.
Add multiple replacement rules for the same PDF before starting. Rules match
original text, never another rule's output; the first matching rule wins.
Each rule keeps its own font, size, ignored-page and embedding choices.
Each rule can retain original font embeddings (default) or remove them when no
remaining content uses them. Shared fonts requested by a retaining rule stay
embedded. Target fonts always remain embedded; unused original font names and
width dictionaries may remain as resources after their font data is removed.

The embedding menu offers a subset by default or the full face.
This tool changes glyph shapes, not text layout: original font advance widths,
text strings, positioning and non-text operations are retained. New glyph ink
bounds can differ. It supports horizontal Identity-H composite fonts and ordinary
simple fonts. Vertical fonts, Type3, ambiguous Unicode mappings, variable target
fonts, and inline-image content streams are rejected when encountered during
replacement. No reflow, redaction, rasterization, or silent font fallback is used.

After conversion, the PDF is saved directly without reopening or output validation.
Font scanning and conversion use tqdm progress bars in interactive terminals.
The shared PDF save policy removes encryption and PDF/A identification; other
metadata is retained. Sources are preserved and existing files are not overwritten.

Requirements:
    - pip: PyMuPDF>=1.28, fonttools, tqdm (MuPDF font APIs verified with PyMuPDF 1.28).

Usage:
    python pdf-font-replace.py
    python pdf-font-replace.py input.pdf
    python pdf-font-replace.py input.pdf -o output.pdf

Only input/output paths can be supplied on the command line. All font, size,
page and embedding choices are made interactively.
"""

import argparse
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import io
import math
import os
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

if TYPE_CHECKING:
    import pymupdf
    from pymupdf.mupdf import PdfFontDesc

MAX_FORM_DEPTH = 32
SIZE_TOLERANCE = 0.0001
SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
NUMBER = re.compile(rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
WHITESPACE = b"\x00\t\n\x0c\r "
DELIMITERS = WHITESPACE + b"()<>[]{}/%"


class _Embedding(StrEnum):
    SUBSET = "subset"
    FULL = "full"


def _font_name(name: str) -> str:
    """Remove only the standard PDF subset prefix, retaining style suffixes."""
    return SUBSET_PREFIX.sub("", name)


def _select_face(faces: Sequence[FontFace], prompt: str) -> FontFace | None:
    """Select one face through the shared menu; R or Enter goes back."""
    options = [MenuOption([str(index)], face.label(), face, desc_color=CRst)
               for index, face in enumerate(faces, 1)]
    options.append(MenuOption(["R"], "Go back", False, desc_color=FGray))
    choice = Menu.select(options, prompt=prompt, default_key="R", key_color=FGray, separator=False)
    return choice if isinstance(choice, FontFace) else None


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    raw: bytes
    kind: str
    children: tuple["_Token", ...] = ()


def _tokens(data: bytes) -> Iterator[_Token]:
    """Lex PDF content, preserving offsets and opaque string/dictionary bytes.

    Inline image streams are deliberately rejected instead of guessing their
    binary EI boundary. The original source remains untouched on any failure.
    """
    def skip(position: int) -> int:
        while position < len(data):
            if data[position] in WHITESPACE:
                position += 1
            elif data[position] == ord("%"):
                while position < len(data) and data[position] not in b"\r\n":
                    position += 1
            else:
                break
        return position

    def read(position: int) -> _Token:
        start = position
        first = data[position:position + 1]
        if first == b"(":
            depth = 1
            position += 1
            while position < len(data) and depth:
                char = data[position:position + 1]
                if char == b"\\":
                    position += 2
                    continue
                depth += (char == b"(") - (char == b")")
                position += 1
            if depth:
                raise ValueError("Unterminated PDF literal string.")
            return _Token(start, position, data[start:position], "string")
        if first == b"[" or data[position:position + 2] == b"<<":
            ending = b"]" if first == b"[" else b">>"
            position += 1 if first == b"[" else 2
            children: list[_Token] = []
            while True:
                position = skip(position)
                if data[position:position + len(ending)] == ending:
                    position += len(ending)
                    return _Token(start, position, data[start:position], "array" if first == b"[" else "dict", tuple(children))
                if position >= len(data):
                    raise ValueError("Unterminated PDF array/dictionary.")
                child = read(position)
                children.append(child)
                position = child.end
        if first == b"<":
            end = data.find(b">", position + 1)
            if end < 0:
                raise ValueError("Unterminated PDF hexadecimal string.")
            return _Token(start, end + 1, data[start:end + 1], "string")
        if first == b"/":
            position += 1
        while position < len(data) and data[position] not in DELIMITERS:
            position += 1
        if position == start:
            raise ValueError(f"Unexpected PDF delimiter at byte {start}.")
        raw = data[start:position]
        kind = "name" if first == b"/" else "number" if NUMBER.fullmatch(raw) else "operator"
        if raw == b"BI":
            raise ValueError("Inline-image content streams are not supported for font replacement.")
        return _Token(start, position, raw, kind)

    position = skip(0)
    while position < len(data):
        token = read(position)
        yield token
        position = skip(token.end)


def _string_bytes(raw: bytes) -> bytes:
    """Decode a PDF byte string without interpreting its font encoding."""
    if raw.startswith(b"<"):
        value = re.sub(rb"\s", b"", raw[1:-1])
        if len(value) % 2:
            value += b"0"
        return bytes.fromhex(value.decode("ascii"))
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    value = raw[1:-1]
    output = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        index += 1
        if char == 92 and index < len(value):
            char = value[index]
            index += 1
            if char in b"01234567":
                octal = bytes([char])
                while index < len(value) and len(octal) < 3 and value[index] in b"01234567":
                    octal += value[index:index + 1]
                    index += 1
                output.append(int(octal, 8) & 255)
                continue
            if char in b"\r\n":
                if char == 13 and value[index:index + 1] == b"\n":
                    index += 1
                continue
            char = escapes.get(char, char)
        elif char == 13:
            if value[index:index + 1] == b"\n":
                index += 1
            char = 10
        output.append(char)
    return bytes(output)


def _name(raw: bytes) -> str:
    """Decode PDF name escapes for resource dictionary lookup."""
    return re.sub(rb"#([0-9A-Fa-f]{2})", lambda match: bytes([int(match[1], 16)]), raw[1:]).decode("latin1")


def _reference(document: "pymupdf.Document", xref: int, key: str) -> int:
    """Read an indirect object reference, accepting a single-reference array."""
    value = document.xref_get_key(xref, key)[1]
    match = re.fullmatch(r"\[?\s*(\d+)\s+\d+\s+R\s*\]?", value)
    if not match:
        raise ValueError(f"Expected an indirect reference for object {xref}/{key}.")
    return int(match[1])


def _dictionary(document: "pymupdf.Document", xref: int, key: str) -> str:
    """Resolve a direct or indirect PDF dictionary, treating null as empty."""
    kind, value = document.xref_get_key(xref, key)
    if kind == "xref":
        return document.xref_object(int(value.split()[0]))
    if kind == "dict":
        return value
    if kind == "null":
        return "<< >>"
    raise ValueError(f"Expected a dictionary for object {xref}/{key}.")


def _object(document: "pymupdf.Document", value: str, stream: bytes | None = None) -> int:
    """Allocate a new PDF object and optionally attach a decoded stream."""
    xref = document.get_new_xref()
    document.update_object(xref, value)
    if stream is not None:
        document.update_stream(xref, stream)
    return xref


def _unicode_map(document: "pymupdf.Document", xref: int, composite: bool) -> dict[int, str]:
    """Resolve ToUnicode through MuPDF; decode standard simple-font encodings otherwise."""
    import pymupdf.mupdf as mupdf
    from fontTools import agl
    from fontTools.encodings.StandardEncoding import StandardEncoding

    kind, _ = document.xref_get_key(xref, "ToUnicode")
    if kind != "null":
        native = mupdf.pdf_document_from_fz_document(document.this)
        obj = mupdf.pdf_new_indirect(native, _reference(document, xref, "ToUnicode"), 0)
        cmap = mupdf.pdf_load_embedded_cmap(native, obj)
        result: dict[int, str] = {}
        for code in range(65536 if composite else 256):
            # Use the explicit Python out-parameter wrapper, not its rebound C name.
            count, unicode_value = mupdf.pdf_lookup_cmap_full_outparams_fn(cmap, code)
            if count == 1 and 0 <= unicode_value <= 0x10FFFF:
                result[code] = chr(unicode_value)
        return result
    if composite:
        raise ValueError("Composite source font has no usable ToUnicode map.")
    kind, encoding = document.xref_get_key(xref, "Encoding")
    if kind in {"dict", "xref"}:
        base = document.xref_get_key(xref, "Encoding/BaseEncoding")[1]
    else:
        base = encoding
    mapping: dict[int, str] = {}
    for code in range(256):
        try:
            if base == "/WinAnsiEncoding":
                value = bytes([code]).decode("cp1252")
            elif base == "/MacRomanEncoding":
                value = bytes([code]).decode("mac_roman")
            elif base in ("null", "/StandardEncoding"):
                value = agl.toUnicode(StandardEncoding[code])
            else:
                raise ValueError(f"Unsupported simple-font encoding: {base}.")
            if len(value) == 1:
                mapping[code] = value
        except UnicodeError:
            continue
    if kind in {"dict", "xref"}:
        _, differences = document.xref_get_key(xref, "Encoding/Differences")
        if differences != "null":
            tokens = list(_tokens(differences.encode("latin1")))[0].children
            code = 0
            for token in tokens:
                if token.kind == "number":
                    code = int(token.raw)
                elif token.kind == "name":
                    value = agl.toUnicode(_name(token.raw))
                    mapping.pop(code, None)
                    if len(value) == 1:
                        mapping[code] = value
                    code += 1
    return mapping


@dataclass
class _SourceFont:
    xref: int
    name: str
    style: FontStyle
    composite: bool
    mapping: dict[int, str]
    default_width: float
    widths: dict[int, float]

    def codes(self, value: bytes) -> list[int]:
        """Decode selected string codes, failing on malformed composite strings."""
        if not self.composite:
            return list(value)
        if len(value) % 2:
            raise ValueError(f"Odd-length Identity-H string in {self.name}.")
        return [int.from_bytes(value[index:index + 2], "big") for index in range(0, len(value), 2)]


def _load_pdf_font(document: "pymupdf.Document", xref: int) -> "PdfFontDesc":
    """Load a PDF font descriptor for both resource and extracted-text naming."""
    import pymupdf.mupdf as mupdf

    native = mupdf.pdf_document_from_fz_document(document.this)
    obj = mupdf.pdf_new_indirect(native, xref, 0)
    return mupdf.PdfFontDesc(mupdf.ll_pdf_load_font(native.m_internal, None, obj.m_internal))


def _source_names(document: "pymupdf.Document", xref: int) -> set[str]:
    """Recognize both BaseFont and MuPDF's extracted-text name for one font."""
    import pymupdf.mupdf as mupdf

    base = _font_name(document.xref_get_key(xref, "BaseFont")[1].lstrip("/"))
    loaded = _load_pdf_font(document, xref)
    extracted = _font_name(mupdf.ll_fz_font_name(loaded.m_internal.font))
    return {base, extracted}


def _source_font(document: "pymupdf.Document", xref: int) -> _SourceFont:
    """Read source character mapping, style and original advances without its system font."""
    import pymupdf.mupdf as mupdf

    name = _font_name(document.xref_get_key(xref, "BaseFont")[1].lstrip("/"))
    subtype = document.xref_get_key(xref, "Subtype")[1]
    composite = subtype == "/Type0"
    if subtype not in ("/Type0", "/TrueType", "/Type1"):
        raise ValueError(f"Unsupported source font type {subtype}: {name}.")
    if composite and document.xref_get_key(xref, "Encoding")[1] != "/Identity-H":
        raise ValueError(f"Source font {name} requires horizontal Identity-H encoding.")
    mapping = _unicode_map(document, xref, composite)
    loaded = _load_pdf_font(document, xref)
    raw = loaded.m_internal
    flags = raw.flags
    bold = bool(flags & (1 << 18)) or bool(re.search(r"bold|black|heavy|semibold|demi", name, re.I))
    italic = bool(flags & 64) or bool(re.search(r"italic|oblique", name, re.I))
    # Embedded sfnt metadata can identify styles even with uninformative PDF names.
    _, extension, _, font_bytes = cast(tuple[str, str, str, bytes], document.extract_font(xref, named=False))
    if extension in ("ttf", "otf") and font_bytes:
        from fontTools.ttLib import TTFont
        with TTFont(io.BytesIO(font_bytes), lazy=True) as embedded:
            os2 = embedded.get("OS/2")
            if os2:
                bold = bold or int(getattr(os2, "usWeightClass")) >= 600
                italic = italic or bool(int(getattr(os2, "fsSelection")) & 1)
    widths = {code: float(mupdf.ll_pdf_lookup_hmtx(raw, code).w) for code in mapping}
    default_width = float(raw.dhmtx.w)
    return _SourceFont(xref, name, FontStyle((bold, italic)), composite, mapping, default_width, widths)


def _cmap(mapping: dict[int, int | str], code_bytes: int, *, unicode: bool = False) -> bytes:
    """Build a ToUnicode or encoding CMap using the original content-code width."""
    name = "FontReplaceUnicode" if unicode else "FontReplaceEncoding"
    operator = "bfchar" if unicode else "cidchar"
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def",
             f"/CMapName /{name} def", f"/CMapType {2 if unicode else 1} def", "/WMode 0 def",
             "1 begincodespacerange", f"<{'00' * code_bytes}> <{'FF' * code_bytes}>", "endcodespacerange"]
    items = sorted(mapping.items())
    for start in range(0, len(items), 100):
        batch = items[start:start + 100]
        lines.append(f"{len(batch)} begin{operator}")
        for code, value in batch:
            target = f"<{cast(str, value).encode('utf-16-be').hex()}>" if unicode else str(value)
            lines.append(f"<{code:0{code_bytes * 2}X}> {target}")
        lines.append(f"end{operator}")
    lines.extend(["endcmap", "CMapName currentdict /CMap defineresource pop", "end end"])
    return "\n".join(lines).encode("ascii")


@dataclass
class _Replacement:
    source: _SourceFont
    face: FontFace
    xref: int
    embedding: _Embedding
    codes: set[int] = field(default_factory=set)


def _embed(document: "pymupdf.Document", replacement: _Replacement, embedding: _Embedding) -> None:
    """Embed the selected face and transplant source widths into its PDF font."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables.C_F_F_ import table_C_F_F_

    source, face = replacement.source, replacement.face
    used = replacement.codes
    with TTFont(face.path, fontNumber=face.index) as font:
        if "fvar" in font or "CFF2" in font:
            raise ValueError(f"Use a static TTF/OTF face instead of variable font {face.name}.")
        cmap = font.getBestCmap() or {}
        missing = [code for code in used if code not in source.mapping
                   or ord(source.mapping[code]) not in cmap or cmap[ord(source.mapping[code])] == ".notdef"]
        if missing:
            labels = [f"U+{ord(source.mapping[code]):04X}" if code in source.mapping else f"source code {code:#x}"
                      for code in sorted(missing)[:12]]
            raise ValueError(f"{face.name}: missing or ambiguous characters: {', '.join(labels)}.")
        glyphs = {code: cmap[ord(source.mapping[code])] for code in used}
        if embedding is _Embedding.SUBSET:
            options = subset.Options()
            options.layout_features = []
            subsetter = subset.Subsetter(options=options)
            subsetter.populate(glyphs=set(glyphs.values()))
            subsetter.subset(font)
        # Scalar table fields are populated dynamically by fontTools' decoder.
        units = int(getattr(font["head"], "unitsPerEm"))
        scale = 1000 / units
        bbox = [float(getattr(font["head"], key)) * scale for key in ("xMin", "yMin", "xMax", "yMax")]
        ascent = float(getattr(font["hhea"], "ascent")) * scale
        descent = float(getattr(font["hhea"], "descent")) * scale
        italic_angle = float(getattr(font["post"], "italicAngle"))
        is_cff = "CFF " in font
        if is_cff:
            cff_table = cast(table_C_F_F_, font["CFF "])
            top = cff_table.cff.topDictIndex[0]
            if not hasattr(top, "ROS"):
                # Convert name-keyed CFF into a CID-keyed font with a single FD.
                from fontTools.cffLib import FDArrayIndex, FontDict, FDSelect
                fd = FontDict()
                # CFF dictionaries expose their operator fields dynamically.
                setattr(fd, "Private", top.Private)
                setattr(fd, "FontName", face.name)
                array = FDArrayIndex()
                array.append(fd)
                selection = FDSelect(format=3)
                selection.gidArray = [0] * len(top.charset)
                old_names = list(top.charset)
                new_names = [".notdef"] + [f"cid{index:05d}" for index in range(1, len(old_names))]
                names = dict(zip(old_names, new_names))
                top.CharStrings.charStrings = {names[name]: value for name, value in top.CharStrings.charStrings.items()}
                top.charset = new_names
                top.FDArray = array
                top.FDSelect = selection
                top.CharStrings.fdArray = array
                top.CharStrings.fdSelect = selection
                top.ROS = ("Adobe", "Identity", 0)
                top.CIDCount = len(new_names)
                del top.Private
                glyphs = {code: names[name] for code, name in glyphs.items()}
            code_to_cid = {code: int(name[3:]) for code, name in glyphs.items()}
            font_bytes = cff_table.compile(font)
            font_file = _object(document, "<< /Subtype /CIDFontType0C >>", font_bytes)
            file_entry = f"/FontFile3 {font_file} 0 R"
            cid_entry = ""
        else:
            code_to_cid = {code: code for code in used}
            buffer = io.BytesIO()
            font.save(buffer)
            font_bytes = buffer.getvalue()
            font_file = _object(document, f"<< /Length1 {len(font_bytes)} >>", font_bytes)
            file_entry = f"/FontFile2 {font_file} 0 R"
            gid_map = bytearray((max(used) + 1) * 2)
            for code, glyph in glyphs.items():
                gid_map[code * 2:code * 2 + 2] = font.getGlyphID(glyph).to_bytes(2, "big")
            gid_xref = _object(document, "<< >>", bytes(gid_map))
            cid_entry = f"/CIDToGIDMap {gid_xref} 0 R"
    unique = sha256(f"{face.name}:{source.xref}:{sorted(used)}".encode()).digest()[:6]
    prefix = "".join(chr(65 + value % 26) for value in unique)
    base_name = re.sub(r"[^A-Za-z0-9_.-]", "_", face.name)
    pdf_name = f"{prefix}+{base_name}" if embedding is _Embedding.SUBSET else base_name
    bold, italic = face.style.value
    flags = 4 | (64 if italic else 0) | ((1 << 18) if bold else 0)
    descriptor = _object(document, f"<< /Type /FontDescriptor /FontName /{pdf_name} /Flags {flags} "
                         f"/FontBBox [{' '.join(f'{value:g}' for value in bbox)}] /ItalicAngle {italic_angle:g} "
                         f"/Ascent {ascent:g} /Descent {descent:g} /CapHeight {ascent:g} /StemV {120 if bold else 80} {file_entry} >>")
    widths: dict[int, float] = {}
    for code, cid in code_to_cid.items():
        width = source.widths.get(code, source.default_width)
        if cid in widths and widths[cid] != width:
            raise ValueError(f"{source.name}: aliased CFF glyphs have incompatible source widths.")
        widths[cid] = width
    width_array = " ".join(f"{cid} [{width:.12g}]" for cid, width in sorted(widths.items()))
    descendant = _object(document, f"<< /Type /Font /Subtype /{'CIDFontType0' if is_cff else 'CIDFontType2'} "
                         f"/BaseFont /{pdf_name} /FontDescriptor {descriptor} 0 R "
                         f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                         f"/DW {source.default_width:.12g} /W [{width_array}] {cid_entry} >>")
    code_bytes = 2 if source.composite else 1
    encoding = _object(document, "<< /Type /CMap >>", _cmap(dict(code_to_cid), code_bytes))
    to_unicode = _object(document, "<< >>", _cmap({code: source.mapping[code] for code in used}, code_bytes, unicode=True))
    document.update_object(replacement.xref, f"<< /Type /Font /Subtype /Type0 /BaseFont /{pdf_name} "
                           f"/DescendantFonts [{descendant} 0 R] /Encoding {encoding} 0 R /ToUnicode {to_unicode} 0 R >>")


type _Matrix = tuple[float, float, float, float, float, float]
IDENTITY: _Matrix = (1, 0, 0, 1, 0, 0)


def _multiply(left: _Matrix, right: _Matrix) -> _Matrix:
    """Concatenate affine matrices in PDF application order."""
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j,
            e * g + f * i + k, e * h + f * j + l)


def _matrix(values: Sequence[float]) -> _Matrix:
    """Validate and return the six values of an affine matrix."""
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        raise ValueError("Invalid PDF transformation matrix.")
    return cast(_Matrix, tuple(values))


@dataclass
class _State:
    ctm: _Matrix = IDENTITY
    text_matrix: _Matrix = IDENTITY
    font: int = 0
    size: float = 0
    horizontal_scale: float = 1

    def effective_size(self) -> float:
        """Match MuPDF's baseline-direction size, including horizontal scaling."""
        a, b, _, _, _, _ = _multiply(self.text_matrix, self.ctm)
        return abs(self.size * self.horizontal_scale) * math.hypot(a, b)


@dataclass(frozen=True)
class _Rule:
    """One replacement's original-text filters, target faces and embedding choice."""

    names: set[str] | None
    sizes: tuple[tuple[float, float], ...]
    ignored: tuple[int, ...]
    faces: dict[FontStyle, FontFace]
    embedding: _Embedding
    remove_original: bool = False


@dataclass
class _Engine:
    document: "pymupdf.Document"
    rules: Sequence[_Rule]
    source_fonts: dict[int, _SourceFont] = field(default_factory=dict)
    source_names: dict[int, set[str]] = field(default_factory=dict)
    replacements: dict[tuple[int, int], _Replacement] = field(default_factory=dict)
    selected_characters: int = 0
    current_page: int = -1
    retained_fonts: set[int] = field(default_factory=set)
    processed_forms: set[int] = field(default_factory=set)

    def selected(self, state: _State) -> int | None:
        """Return the first rule matching the original font, size and current page."""
        if not state.font:
            return None
        if state.font not in self.source_names:
            self.source_names[state.font] = {name.casefold() for name in _source_names(self.document, state.font)}
        names = self.source_names[state.font]
        size = state.effective_size()
        for index, rule in enumerate(self.rules):
            if self.current_page in rule.ignored:
                continue
            if rule.names is not None and not any(candidate.casefold() in names for candidate in rule.names):
                continue
            if not rule.sizes or any(low - SIZE_TOLERANCE <= size <= high + SIZE_TOLERANCE
                                     for low, high in rule.sizes):
                return index
        return None

    def replacement(self, state: _State, rule_index: int) -> _Replacement:
        """Resolve a face of exactly the original style and reserve its font object."""
        key = (rule_index, state.font)
        if key not in self.replacements:
            if state.font not in self.source_fonts:
                self.source_fonts[state.font] = _source_font(self.document, state.font)
            source = self.source_fonts[state.font]
            rule = self.rules[rule_index]
            if source.style not in rule.faces:
                raise ValueError(f"Missing target {source.style.name} face for {source.name}. Specify the matching style file.")
            self.replacements[key] = _Replacement(source, rule.faces[source.style],
                                                  _object(self.document, "<< >>"), rule.embedding)
        return self.replacements[key]

    def rewrite(
        self, data: bytes, resources: str, initial: _State, ancestors: tuple[int, ...] = (),
    ) -> tuple[bytes, int, bool]:
        """Clone resources and isolate changed forms for this single page/invocation.

        All non-text operators and operands retain their original bytes. The only
        inserted text operators select the replacement font before a text show,
        then restore the original font. No text matrices or advances are changed.
        """
        if len(ancestors) > MAX_FORM_DEPTH:
            raise ValueError("PDF form nesting is too deep.")
        document = self.document
        resource = _object(document, resources)
        for key in ("Font", "XObject"):
            document.xref_set_key(resource, key, _dictionary(document, resource, key))
        state = replace(initial)
        stack: list[_State] = []
        operands: list[_Token] = []
        patches: list[tuple[int, int, bytes]] = []

        def font_alias(xref: int) -> str:
            name = f"FR{xref}"
            while document.xref_get_key(resource, f"Font/{name}")[0] != "null":
                if document.xref_get_key(resource, f"Font/{name}")[1] == f"{xref} 0 R":
                    return name
                name += "x"
            document.xref_set_key(resource, f"Font/{name}", f"{xref} 0 R")
            return name

        # ── interpret state and collect byte patches ───────────
        for token in _tokens(data):
            if token.kind != "operator":
                operands.append(token)
                continue
            op = token.raw
            if op == b"q":
                stack.append(replace(state))
            elif op == b"Q":
                if not stack:
                    raise ValueError("Unbalanced PDF graphics-state stack.")
                restored = stack.pop()
                restored.text_matrix = state.text_matrix
                state = restored
            elif op == b"cm":
                state.ctm = _multiply(_matrix([float(item.raw) for item in operands]), state.ctm)
            elif op == b"BT":
                state.text_matrix = IDENTITY
            elif op == b"Tm":
                state.text_matrix = _matrix([float(item.raw) for item in operands])
            elif op == b"Tz":
                state.horizontal_scale = float(operands[0].raw) / 100
            elif op == b"Tf":
                state.font = _reference(document, resource, f"Font/{_name(operands[0].raw)}")
                state.size = float(operands[1].raw)
            elif op == b"gs":
                key = f"ExtGState/{_name(operands[0].raw)}/Font"
                kind, value = document.xref_get_key(resource, key)
                if kind != "null":
                    match = re.fullmatch(r"\[\s*(\d+)\s+\d+\s+R\s+([+-]?[\d.]+)\s*\]", value)
                    if match is None:
                        raise ValueError("Unsupported ExtGState font declaration.")
                    state.font, state.size = int(match[1]), float(match[2])
            elif op == b"Do":
                form = _reference(document, resource, f"XObject/{_name(operands[0].raw)}")
                if document.xref_get_key(form, "Subtype")[1] == "/Form":
                    self.processed_forms.add(form)
                    if form in ancestors:
                        raise ValueError("Cyclic Form XObject reference.")
                    kind, raw_matrix = document.xref_get_key(form, "Matrix")
                    matrix = IDENTITY if kind == "null" else _matrix([float(part.raw) for part in list(_tokens(raw_matrix.encode()))[0].children])
                    form_state = replace(state, ctm=_multiply(matrix, state.ctm))
                    own_resources = _dictionary(document, form, "Resources")
                    if document.xref_get_key(form, "Resources")[0] == "null":
                        own_resources = resources
                    form_data = document.xref_stream(form)
                    if form_data is None:
                        raise ValueError(f"Form XObject {form} has no content stream.")
                    rewritten, new_resources, changed = self.rewrite(
                        form_data, own_resources, form_state, (*ancestors, form),
                    )
                    if changed:
                        clone = _object(document, document.xref_object(form), rewritten)
                        self.processed_forms.add(clone)
                        document.xref_set_key(clone, "Resources", f"{new_resources} 0 R")
                        alias = f"FRForm{clone}"
                        while document.xref_get_key(resource, f"XObject/{alias}")[0] != "null":
                            alias += "x"
                        document.xref_set_key(resource, f"XObject/{alias}", f"{clone} 0 R")
                        patches.append((operands[0].start, token.end, f"/{alias} Do".encode("ascii")))
            elif op in (b"Tj", b"TJ", b"'", b'"') and (rule_index := self.selected(state)) is not None:
                strings = operands[-1].children if op == b"TJ" else operands[-1:]
                values = [_string_bytes(item.raw) for item in strings if item.kind == "string"]
                if any(values):
                    replacement = self.replacement(state, rule_index)
                    codes = [code for value in values for code in replacement.source.codes(value)]
                    replacement.codes.update(codes)
                    self.selected_characters += len(codes)
                    target_alias, original_alias = font_alias(replacement.xref), font_alias(state.font)
                    size = f"{state.size:.12g}"
                    start = operands[0].start
                    changed_show = (f"/{target_alias} {size} Tf\n".encode("ascii") + data[start:token.end]
                                    + f"\n/{original_alias} {size} Tf".encode("ascii"))
                    patches.append((start, token.end, changed_show))
            elif op in (b"Tj", b"TJ", b"'", b'"') and state.font:
                # Even hidden/clipping text must retain its original font data.
                self.retained_fonts.add(state.font)
            operands = []
        if operands:
            raise ValueError("PDF content ends with operands without an operator.")
        if stack:
            raise ValueError("Unbalanced PDF graphics-state stack.")
        output = bytearray()
        position = 0
        for start, end, value in patches:
            output.extend(data[position:start])
            output.extend(value)
            position = end
        output.extend(data[position:])
        return bytes(output), resource, bool(patches)

    def run(self, pages: Sequence[int]) -> int:
        """Replace selected text on allowed pages, then embed every used target face."""
        from tqdm import tqdm

        cleaning = any(rule.remove_original for rule in self.rules)
        if cleaning:
            selected_pages = set(pages)
            for index in range(self.document.page_count):
                if index not in selected_pages:
                    self.retained_fonts.update(row[0] for row in self.document[index].get_fonts(full=True))
        for index in tqdm(pages, desc="Replacing fonts", unit="page", disable=None, dynamic_ncols=True):
            self.current_page = index
            page = self.document[index]
            if not any(index not in rule.ignored and _matching_font_names(page, rule.names, rule.sizes)
                       for rule in self.rules):
                if cleaning:
                    self.retained_fonts.update(row[0] for row in page.get_fonts(full=True))
                continue
            owner = page.xref
            seen: set[int] = set()
            while self.document.xref_get_key(owner, "Resources")[0] == "null":
                if owner in seen or self.document.xref_get_key(owner, "Parent")[0] == "null":
                    break
                seen.add(owner)
                owner = _reference(self.document, owner, "Parent")
            resources = _dictionary(self.document, owner, "Resources")
            transform = page.transformation_matrix
            state = _State(ctm=_matrix([transform[index] for index in range(6)]))
            rewritten, new_resources, changed = self.rewrite(page.read_contents(), resources, state)
            if changed:
                stream = _object(self.document, "<< >>", rewritten)
                self.document.xref_set_key(page.xref, "Contents", f"{stream} 0 R")
                self.document.xref_set_key(page.xref, "Resources", f"{new_resources} 0 R")
        for replacement in tqdm(self.replacements.values(), desc="Embedding fonts", unit="font",
                                disable=None, dynamic_ncols=True):
            _embed(self.document, replacement, replacement.embedding)
        return self.selected_characters

    def remove_original_embeddings(self) -> None:
        """Remove only requested, unused originals; retaining rules take priority."""
        candidates: set[int] = set()
        retained = set(self.retained_fonts)
        for (rule_index, font_xref), _ in self.replacements.items():
            if self.rules[rule_index].remove_original:
                candidates.add(font_xref)
            else:
                retained.add(font_xref)
        if not candidates:
            return
        retained.update(_protected_font_resources(self.document, self.processed_forms))
        removed = sum(_remove_font_embedding(self.document, xref) for xref in sorted(candidates - retained))
        print(f"{FGray}Original font cleanup: {removed} embedding(s) removed; "
              f"{len(candidates & retained)} retained for other content or rules.{CRst}")


def _referenced_fonts(document: "pymupdf.Document", value: str) -> set[int]:
    """Conservatively collect fonts reachable from a PDF resource/appearance value."""
    def references(tokens: Sequence[_Token]) -> Iterator[int]:
        for index, token in enumerate(tokens):
            if (token.kind == "number" and index + 2 < len(tokens)
                    and tokens[index + 1].kind == "number" and tokens[index + 2].raw == b"R"):
                yield int(token.raw)
            if token.children:
                yield from references(token.children)

    pending = list(references(tuple(_tokens(value.encode("utf-8")))))
    visited: set[int] = set()
    fonts: set[int] = set()
    while pending:
        xref = pending.pop()
        if xref in visited:
            continue
        visited.add(xref)
        if (document.xref_get_key(xref, "Type")[1] == "/Font"
                or document.xref_get_key(xref, "Subtype")[1] in
                {"/Type0", "/Type1", "/TrueType", "/Type3", "/MMType1", "/CIDFontType0", "/CIDFontType2"}):
            fonts.add(xref)
        else:
            pending.extend(references(tuple(_tokens(document.xref_object(xref).encode("utf-8")))))
    return fonts


def _protected_font_resources(document: "pymupdf.Document", processed_forms: set[int]) -> set[int]:
    """Retain fonts in appearances, form defaults, patterns and unprocessed forms.

    These resources are outside the rewritten page text. Traversing their font
    references is deliberately conservative, including unused resources.
    """
    from tqdm import tqdm

    fonts = _referenced_fonts(document, document.xref_get_key(document.pdf_catalog(), "AcroForm")[1])
    for page in document:
        for xref, _, _ in page.annot_xrefs():
            fonts.update(_referenced_fonts(document, document.xref_get_key(xref, "AP")[1]))
    for xref in tqdm(range(1, document.xref_length()), desc="Checking font resources", unit="object",
                     disable=None, dynamic_ncols=True):
        subtype = document.xref_get_key(xref, "Subtype")[1]
        if (subtype == "/Type3" or document.xref_get_key(xref, "PatternType")[0] != "null"
                or (subtype == "/Form" and xref not in processed_forms)):
            fonts.update(_referenced_fonts(document, document.xref_get_key(xref, "Resources")[1]))
    return fonts


def _remove_font_embedding(document: "pymupdf.Document", xref: int) -> bool:
    """Detach an unused font's program with copied descriptors to protect sharers.

    Keeps font names, encodings and widths. The shared save function garbage
    collects program streams only when no other PDF object references them.
    """
    composite = document.xref_get_key(xref, "Subtype")[1] == "/Type0"
    owner = _reference(document, xref, "DescendantFonts") if composite else xref
    descriptor = _dictionary(document, owner, "FontDescriptor")
    if descriptor == "<< >>":
        return False
    font_files = ("FontFile", "FontFile2", "FontFile3")
    if not any(document.xref_get_key(owner, f"FontDescriptor/{key}")[0] != "null" for key in font_files):
        return False
    copied_descriptor = _object(document, descriptor)
    for key in font_files:
        document.xref_set_key(copied_descriptor, key, "null")
    if composite:
        owner = _object(document, document.xref_object(owner))
        document.xref_set_key(xref, "DescendantFonts", f"[{owner} 0 R]")
    document.xref_set_key(owner, "FontDescriptor", f"{copied_descriptor} 0 R")
    return True


def _convert(
    document: "pymupdf.Document", output: Path, rules: Sequence[_Rule],
) -> int:
    """Convert and directly save a new unprotected PDF without output verification.

    Returns the replaced character count, or zero without writing any output.
    Modifies the caller's in-memory document; never overwrites an existing file.
    """
    if output.exists() or (document.name and Path(document.name).resolve() == output.resolve()):
        raise FileExistsError(f"Output must be a new file: {output}")
    pages = [index for index in range(document.page_count) if any(index not in rule.ignored for rule in rules)]
    engine = _Engine(document, rules)
    count = engine.run(pages)
    if not count:
        print(f"{FLYellow}No text matched the selected fonts, sizes and pages. No PDF written.{CRst}")
        return 0
    engine.remove_original_embeddings()
    Pdf.save_new(document, output, compact=False)
    print(f"{FLGreen}Replaced {count} characters.{CRst}")
    print(f"{FLGreen}Saved:{CRst} {output}")
    return count


def _pdf_fonts(document: "pymupdf.Document", pages: Sequence[int]) -> list[str]:
    """List unique fonts actually used by text, without sizes or page occurrences."""
    names: set[str] = set()
    for index in pages:
        used = {_font_name(span["font"]) for span in document[index].get_texttrace() if span["chars"]}
        resources = {_font_name(row[3]) for row in document[index].get_fonts(full=True)}
        names.update(name for name in resources if name in used)
        names.update(used - resources)
    return sorted(names, key=str.casefold)


def _matching_font_names(
    page: "pymupdf.Page", names: set[str] | None, sizes: tuple[tuple[float, float], ...],
) -> set[str]:
    """Find actually used fonts with matching names/sizes, including hidden text."""
    folded = {name.casefold() for name in names} if names is not None else None
    return {_font_name(span["font"]) for span in page.get_texttrace() if span["chars"]
            and (folded is None or _font_name(span["font"]).casefold() in folded)
            and (not sizes or any(low - SIZE_TOLERANCE <= span["size"] <= high + SIZE_TOLERANCE for low, high in sizes))}


def _select_source_fonts(document: "pymupdf.Document") -> set[str] | None:
    """Select PDF font names, with a mandatory retry/exit branch for fontless pages.

    Returns None for all fonts. Raises KeyboardInterrupt for explicit exit; the
    document context closes normally through the caller's entry-point handler.
    """
    mode = Menu.select(
        [MenuOption(["P"], "Choose fonts from PDF pages", "P"),
         MenuOption(["N"], "Search or enter source PDF font names", "N"),
         MenuOption(["A"], "Replace all text fonts", "A")],
        prompt="Source fonts", default_key="P", separator=False,
    )
    if mode is None:
        raise KeyboardInterrupt
    if mode == "A":
        return None
    while True:
        if mode == "P":
            pages = Input.input_index_ranges(
                "Pages to inspect (Enter = whole document)", item_count=document.page_count,
                default=f"1-{document.page_count}",
            )
            names = _pdf_fonts(document, pages or ())
        else:
            query = Input.prompt("Source font name/search (Enter to exit): ")
            if not query:
                raise KeyboardInterrupt
            names = [name for name in _pdf_fonts(document, tuple(range(document.page_count)))
                     if query.casefold() in name.casefold()]
        if not names:
            print(f"{FLYellow}Warning: no text fonts were found in the selected pages or search. "
                  f"Image-only pages do not contain replaceable text fonts.{CRst}")
            choice = Menu.select(
                [MenuOption(["R"], "Select pages/search again", True), MenuOption(["E"], "Exit", False)],
                prompt="Next action", default_key="R", separator=False,
            )
            if not choice:
                raise KeyboardInterrupt
            continue
        options = [MenuOption([str(index)], name, str(index), desc_color=FLCyan)
                   for index, name in enumerate(names, 1)]
        options.extend([
            MenuOption(["R"], "Select pages/search again", "R", desc_color=FGray),
            MenuOption(["E"], "Exit", "E", desc_color=FGray),
        ])
        while True:
            answers = cast(list[str], Menu.select(
                options, prompt="Font numbers/ranges", required=True,
                allow_multiple=True, accept_custom_string=True, key_color=FGray, separator=False,
            ))
            try:
                actions = {answer.casefold() for answer in answers} & {"r", "e"}
                if actions:
                    if len(answers) != 1:
                        raise ValueError("Use R or E alone, without font numbers.")
                    if "e" in actions:
                        raise KeyboardInterrupt
                    break
                indexes = Input.parse_index_ranges(",".join(answers), item_count=len(names))
                if not indexes:
                    raise ValueError("Choose at least one font, R, or E.")
                return {names[index] for index in indexes}
            except ValueError as exc:
                print(f"{FLRed}{exc}{CRst}")


def _pick_target(catalog: list[FontFace]) -> FontFace:
    """Search installed canonical/localized names or read a user-specified file."""
    while True:
        mode = Menu.select(
            [MenuOption(["S"], "Search installed fonts", "S"),
             MenuOption(["F"], "Choose a font file (TTF/OTF/TTC)", "F")],
            prompt="Target font", default_key="S", separator=False,
        )
        if mode is None:
            raise KeyboardInterrupt
        if mode == "F":
            path = Path(Input.resolve_input_path("", prompt="Target font file", path_type="file"))
            faces = Font.read_faces(path)
            face = faces[0] if len(faces) == 1 else _select_face(faces, "Choose a collection face")
            if face is not None:
                # A manually supplied family may keep its other styles nearby.
                neighbors = [path for path in face.path.parent.iterdir()
                             if path.suffix.casefold() in Font.FILE_SUFFIXES and path.is_file()]
                catalog.extend(Font.read_catalog(neighbors, show_progress=True))
                return face
            continue
        query = Input.prompt("Font name or localized alias (Enter to go back): ")
        if not query:
            continue
        if not catalog:
            catalog.extend(Font.read_catalog(Font.system_font_paths(), show_progress=True))
        found = Font.search_faces(catalog, query)
        if not found:
            print(f"{FLYellow}No matching installed font. Try another name or choose a file.{CRst}")
            continue
        face = _select_face(found, "Choose a target face/family")
        if face is not None:
            return face


def _required_styles(
    document: "pymupdf.Document", names: set[str] | None,
    sizes: tuple[tuple[float, float], ...], ignored: Sequence[int],
) -> set[FontStyle]:
    """Determine required styles from text on pages eligible for replacement."""
    refs: set[int] = set()
    source_names: dict[int, set[str]] = {}
    for index in range(document.page_count):
        if index in ignored:
            continue
        page = document[index]
        used = _matching_font_names(page, names, sizes)
        if not used:
            continue
        for row in page.get_fonts(full=True):
            xref = row[0]
            if xref not in source_names:
                source_names[xref] = _source_names(document, xref)
            if source_names[xref] & used:
                refs.add(xref)
    return {_source_font(document, xref).style for xref in refs}


def _complete_styles(faces: dict[FontStyle, FontFace], required: set[FontStyle]) -> None:
    """Ask for absent styles before changing the document, or let the user exit."""
    for style in FontStyle:
        if style not in required or style in faces:
            continue
        while True:
            print(f"{FLYellow}The selected family lacks a {style.name} face required by this PDF.{CRst}")
            choice = Menu.select(
                [MenuOption(["F"], "Choose a matching style file", True), MenuOption(["E"], "Exit", False)],
                prompt="Missing font style", default_key="F", separator=False,
            )
            if not choice:
                raise KeyboardInterrupt
            path = Path(Input.resolve_input_path("", prompt=f"Target {style.name} font file", path_type="file"))
            candidates = [face for face in Font.read_faces(path) if face.style is style]
            if not candidates:
                print(f"{FLRed}This file does not contain a {style.name} face.{CRst}")
                continue
            face = candidates[0] if len(candidates) == 1 else _select_face(candidates, "Choose style face")
            if face is not None:
                faces[style] = face
                break


def _collect_rules(document: "pymupdf.Document") -> tuple[_Rule, ...]:
    """Collect replacements against the unchanged input until the user starts."""
    rules: list[_Rule] = []
    print(f"{FGray}Rules match original text. If rules overlap, the first matching rule wins.{CRst}")
    while True:
        print(f"{FLCyan}Replacement rule {len(rules) + 1}{CRst}")
        # ── original text filters ──────────────────────────────
        names = _select_source_fonts(document)
        sizes = Input.input_real_ranges("Font sizes (Enter = all)") or ()
        if any(low <= 0 for low, _ in sizes):
            raise ValueError("Font sizes must be greater than zero.")

        # ── target face and style matching ─────────────────────
        catalog: list[FontFace] = []
        base = _pick_target(catalog)
        faces = Font.family_faces(base, catalog)
        ignored = Input.input_index_ranges("Pages to ignore for this rule (Enter = none)",
                                           item_count=document.page_count) or ()
        _complete_styles(faces, _required_styles(document, names, sizes, ignored))
        for style, face in faces.items():
            print(f"{style.name}: {face.label()}")
        embedding = cast(_Embedding, Menu.select(
            [MenuOption(["S"], "Embed used characters only", _Embedding.SUBSET),
             MenuOption(["F"], "Embed entire font face", _Embedding.FULL)],
            prompt="Font embedding", required=True, default_key="S", separator=False,
        ))
        print(f"{FGray}Original fonts still needed by other text, pages, appearances or retaining rules are kept.{CRst}")
        remove_original = cast(bool, Menu.select(
            [MenuOption(["K"], "Keep original embedded fonts", False),
             MenuOption(["D"], "Delete original embeddings when no longer used", True)],
            prompt="Original fonts for this rule", required=True, default_key="D", separator=False,
        ))
        rules.append(_Rule(names, sizes, ignored, faces, embedding, remove_original))

        # ── add another rule or process the document ───────────
        sources = ", ".join(sorted(names)) if names is not None else "All fonts"
        print(f"{FLGreen}Rule {len(rules)} added:{CRst} {sources} -> {base.name}")
        start = Menu.select(
            [MenuOption(["S"], f"Start replacement ({len(rules)} rule(s))", True),
             MenuOption(["A"], "Add another replacement to this PDF", False)],
            prompt="Next action", default_key="S", separator=False,
        )
        if start is None:
            raise KeyboardInterrupt
        if start:
            return tuple(rules)
        print()
        Console.print_separator()
        print()


def _parser() -> argparse.ArgumentParser:
    """Accept only paths and help; explain the interactive choices and dependencies."""
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}PDF FONT REPLACE{CRst}\n\nDescription:\n"
                    "  Replace selected fonts while preserving text positions and advances.\n"
                    "  Interactive selection supports PDF fonts, sizes, page exclusions, localized\n"
                    "  installed font names, and font files. Original bold/italic styles are retained.\n"
                    "  Add multiple replacement rules, then start once for the same PDF.\n"
                    "  Only paths are command-line arguments; all other choices are interactive.",
        epilog=f"{FGray}Requirements: PyMuPDF>=1.28, fonttools, tqdm. Windows / Linux / macOS.\n"
               "Font scanning and conversion show progress bars in interactive terminals.\n"
               "Rules match original text; the first matching rule wins when rules overlap.\n"
               "Each rule can keep original embeddings (default) or delete them if unused;\n"
               "fonts needed by other content or a retaining rule remain embedded.\n"
               "Only embedded output is offered: subset (default) or full face. Source fonts\n"
               "need not be installed. Unsupported source encodings, missing glyphs/styles,\n"
               "vertical/Type3 fonts, variable targets, and inline-image streams fail clearly.\n"
               "No reflow: glyph ink bounds may change, but original text advances are retained.\n"
               "Size filters use effective page-space font size. Ranges include both endpoints;\n"
               "negative page numbers count from the end; zero is not a page number.\n"
               "Output is saved directly without verification, unencrypted and non-PDF/A. Other\n"
               f"metadata, images, links, outlines and annotations are retained.{CRst}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", type=Path, help="input PDF; prompt if omitted")
    parser.add_argument("-o", "--output", type=Path, help="new output PDF; prompt if omitted, suggesting <input>_fonts.pdf")
    return parser


def main() -> int:
    """Run interactive font replacement and return 0 on success, 1 on error.

    Opens inputs through shared PDF authentication, prompts for replacement
    choices, and directly saves a new PDF without output verification.
    Prints English progress/errors; only input/output paths may bypass prompts.
    Explicit exit, EOF and Ctrl+C propagate to the module-level exit handler.
    """
    parser = _parser()
    args = parser.parse_args()
    Console.print_banner("PDF FONT REPLACE")
    # ── dependency checks ──────────────────────────────────
    try:
        import pymupdf
        from pymupdf.mupdf import FzErrorBase
        from fontTools.ttLib import TTLibError
        from tqdm import tqdm
    except ImportError as exc:
        print(f"{FLRed}Missing dependency: {exc.name}. Install PyMuPDF, fonttools and tqdm.{CRst}")
        return 1
    try:
        # ── open and select original text ──────────────────────
        source = args.input or Path(Input.resolve_input_path("", prompt="Input PDF", path_type="file"))
        with Pdf.open_document(source) as (document, _):
            if not document.page_count:
                raise ValueError("The PDF has no pages.")
            rules = _collect_rules(document)
            # ── convert and save ─────────────────────────────────
            default_output = source.with_name(f"{source.stem}_fonts.pdf")
            output = args.output or Path(Input.resolve_output_path(str(default_output), prompt="Output PDF", path_type="file"))
            _convert(document, output, rules)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, TTLibError, FzErrorBase) as exc:
        print(f"{FLRed}Font replacement failed: {exc}{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        Console.print_keyboard_interrupt_message_and_exit()
