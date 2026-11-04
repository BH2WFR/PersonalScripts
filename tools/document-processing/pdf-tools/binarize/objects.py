"""Rewrite image invocations without flattening the surrounding PDF page.

pypdf parses content syntax (including inline images); MuPDF owns all PDF objects
and rendering on the main thread. Original streams/resources are never mutated.
Each changed page/form receives private resources; skipped pages keep originals.
"""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from hashlib import sha256
import io
import math
from typing import cast

from PIL import Image
import numpy as np
import pymupdf
from pymupdf import mupdf
from pypdf import PdfReader
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject, NameObject, PdfObject, read_object
from utils import *

from . import raster, regions
from .settings import _Processing

_MAX_DEPTH = 32
_POINTS_PER_INCH = 72
_PAINT = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
_STROKE = {b"S", b"s", b"B", b"B*", b"b", b"b*"}
_FILL = _PAINT - {b"S", b"s"}
_PATH = {b"m", b"l", b"c", b"v", b"y", b"h", b"re"}
_SPACES = {b"g": "/DeviceGray", b"rg": "/DeviceRGB", b"k": "/DeviceCMYK"}
type _Operands = list[PdfObject]
type _Operation = tuple[_Operands, bytes]
type _ImageKey = tuple[int, float, float, tuple[regions._Region, ...] | None]


class _SyntaxReader(PdfReader):
    """Reference owner for syntax parsing; actual object resolution stays in MuPDF.

    pypdf requires a non-null owner when parsing indirect references. A full
    second PdfReader would copy/parse the entire input unnecessarily. Only its
    strict flag and reference identity are used here; dereferencing is rejected.
    """

    def __init__(self) -> None:
        self.strict = True

    def get_object(self, indirect_reference: int | IndirectObject) -> PdfObject:
        """Reject accidental resolution through this syntax-only reader."""
        raise ValueError("Resolve PDF references through the owning MuPDF document.")


_SYNTAX_READER = _SyntaxReader()
_object = Pdf.new_object
_dictionary = Pdf.read_dictionary


def _resources(document: pymupdf.Document, page: pymupdf.Page) -> str:
    """Read inherited page resources without modifying the page tree."""
    owner, seen = page.xref, set()
    while document.xref_get_key(owner, "Resources")[0] == "null":
        kind, parent = document.xref_get_key(owner, "Parent")
        if kind != "xref" or owner in seen:
            return "<<>>"
        seen.add(owner)
        owner = int(parent.split()[0])
    return _dictionary(document, owner, "Resources")


def _parse(data: bytes) -> ContentStream:
    """Parse decoded PDF content with the library's inline-image boundary logic."""
    stream = ContentStream(None, None, forced_encoding="bytes")
    stream.set_data(data)
    return stream


def _entries(document: pymupdf.Document, owner: int, category: str) -> DictionaryObject:
    """Read resource names literally, including escaped slash/space characters."""
    value = read_object(io.BytesIO(_dictionary(document, owner, category).encode("utf-8")), _SYNTAX_READER)
    if not isinstance(value, DictionaryObject):
        raise ValueError(f"Invalid PDF resource dictionary: {category}")
    return value


def _entry(document: pymupdf.Document, owner: int, category: str, name: str) -> str:
    """Resolve a named resource without treating a slash inside its name as a path."""
    value = _entries(document, owner, category).get(NameObject(f"/{name}"))
    return _serialize(value) if value is not None else "null"


def _isolate_skipped(document: pymupdf.Document, skipped: set[int]) -> None:
    """Copy shared image/form resources onto skipped pages before processing.

    Fonts, links and appearance resources stay shared because they are never
    mutated. Changed pages also use copy-on-write, protecting annotation images.
    """
    if not skipped or len(skipped) == document.page_count:
        return
    shared: set[int] = set()
    for index in range(document.page_count):
        if index not in skipped:
            page = document[index]
            shared.update(item[0] for item in page.get_images(full=True))
            shared.update(item[0] for item in page.get_xobjects())
            shared.update(page.get_contents())
    copied: dict[int, int] = {}

    def clone_resources(value: str, ancestors: tuple[int, ...] = ()) -> tuple[int, bool]:
        if len(ancestors) > _MAX_DEPTH:
            raise ValueError("PDF form nesting exceeds the supported depth.")
        resource = _object(document, value)
        dictionary = _entries(document, resource, "XObject")
        changed = False
        for name, reference in list(dictionary.items()):
            if not isinstance(reference, IndirectObject):
                continue
            source = reference.idnum
            target = source
            if document.xref_get_key(source, "Subtype")[1] == "/Form":
                if source in ancestors:
                    raise ValueError("Cyclic PDF form reference.")
                own = _dictionary(document, source, "Resources") if document.xref_get_key(source, "Resources")[0] != "null" else value
                children, children_changed = clone_resources(own, (*ancestors, source))
                if source in shared or children_changed:
                    target = _object(document, document.xref_object(source), document.xref_stream(source))
                    document.xref_set_key(target, "Resources", f"{children} 0 R")
            elif source in shared:
                if source not in copied:
                    copied[source] = _object(document)
                    document.xref_copy(source, copied[source])
                target = copied[source]
            if target != source:
                changed = True
                dictionary[name] = IndirectObject(target, 0, _SYNTAX_READER)
        document.xref_set_key(resource, "XObject", _serialize(dictionary))
        return resource, changed

    for index in sorted(skipped):
        page = document[index]
        resource, changed = clone_resources(_resources(document, page))
        if changed:
            document.xref_set_key(page.xref, "Resources", f"{resource} 0 R")
        if shared.intersection(page.get_contents()):
            page.set_contents(_object(document, data=page.read_contents()))


def _serialize(value: PdfObject) -> str:
    """Encode one parsed PDF operand without interpreting text character codes."""
    with io.BytesIO() as stream:
        value.write_to_stream(stream)
        return stream.getvalue().decode("latin1")


def _native(document: pymupdf.Document) -> mupdf.PdfDocument:
    """Return the MuPDF PDF handle associated with an owned high-level document."""
    return mupdf.pdf_document_from_fz_document(document.this)


def _graft(target: pymupdf.Document, source: pymupdf.Document, xref: int) -> int:
    """Copy an object graph between independent documents, including masks."""
    reference = mupdf.pdf_new_indirect(_native(source), xref, 0)
    return mupdf.pdf_to_num(mupdf.pdf_graft_object(_native(target), reference))


def _form(document: pymupdf.Document, encoded: bytes | regions._Page) -> int:
    """Import an encoded image/crops PDF as a unit-square Form XObject."""
    data = regions._assemble(encoded) if isinstance(encoded, regions._Page) else encoded
    with pymupdf.open(stream=data, filetype="pdf") as source:
        page = source[0]
        resource = _object(source, _resources(source, page))
        copied = _graft(document, source, resource)
        width, height = page.rect.width, page.rect.height
        return _object(document,
            f"<< /Type /XObject /Subtype /Form /BBox [0 0 {width} {height}] "
            f"/Group << /S /Transparency /I true /CS /DeviceRGB >> "
            f"/Matrix [{1 / width:.12g} 0 0 {1 / height:.12g} 0 0] /Resources {copied} 0 R >>",
            page.read_contents())


def _render_image(document: pymupdf.Document, xref: int, width: float, height: float,
                  dpi: int | tuple[float, float], color: bool) -> tuple[Image.Image, Image.Image | None]:
    """Render only this image, preserving its Decode, color space and transparency.

    The image's on-page axis lengths determine base DPI. Rotation, shear and
    clipping remain in the original content stream. Returned images are owned.
    """
    with pymupdf.open() as isolated:
        dpi_x, dpi_y = (dpi, dpi) if isinstance(dpi, int) else dpi
        scale = pymupdf.Matrix(dpi_x / 72, dpi_y / 72)
        copied = _graft(isolated, document, xref)
        page = isolated.new_page(width=width, height=height)
        isolated.xref_set_key(page.xref, "Resources", f"<< /XObject << /Image {copied} 0 R >> >>")
        content = _object(isolated, data=f"{width:.12g} 0 0 {height:.12g} 0 0 cm /Image Do".encode())
        page.set_contents(content)
        pixmap = page.get_pixmap(matrix=scale, colorspace=pymupdf.csRGB if color else pymupdf.csGRAY, alpha=False)
        image = Image.frombytes("RGB" if color else "L", (pixmap.width, pixmap.height), pixmap.samples)
        mask = None
        if (any(document.xref_get_key(xref, key)[0] != "null" for key in ("SMask", "Mask"))
                or document.xref_get_key(xref, "SMaskInData")[1] not in ("null", "0")):
            image.close()
            rgba = page.get_pixmap(matrix=scale, colorspace=pymupdf.csRGB if color else pymupdf.csGRAY, alpha=True)
            image, mask = _unpremultiply(rgba)
        return image, mask


def _unpremultiply(pixmap: pymupdf.Pixmap) -> tuple[Image.Image, Image.Image]:
    """Recover straight color before thresholding and retain fractional coverage."""
    samples = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    alpha = samples[:, :, -1]
    colors = np.minimum(255, np.rint(samples[:, :, :-1].astype(np.float32) * 255 /
                                  np.maximum(alpha[:, :, None], 1))).astype(np.uint8)
    colors[alpha == 0] = 255
    return Image.fromarray(colors[:, :, 0] if pixmap.n == 2 else colors), Image.fromarray(alpha.copy())


def _mask_form(document: pymupdf.Document, form: int, mask: Image.Image) -> int:
    """Apply the original alpha coverage to the complete binary/crop composition."""
    with mask:
        image = _object(document, f"<< /Type /XObject /Subtype /Image /Width {mask.width} "
                        f"/Height {mask.height} /ColorSpace /DeviceGray /BitsPerComponent 8 >>", mask.tobytes())
    # update_stream owns compression, so the image dictionary needs no Filter here.
    group = _object(document,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] "
        f"/Group << /S /Transparency /CS /DeviceGray >> "
        f"/Resources << /XObject << /Alpha {image} 0 R >> >> >>", b"/Alpha Do")
    return _object(document,
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 1 1] "
        f"/Group << /S /Transparency /I true /CS /DeviceRGB >> "
        f"/Resources << /XObject << /Image {form} 0 R >> "
        f"/ExtGState << /Mask << /SMask << /S /Luminosity /G {group} 0 R >> >> >> >> >>",
        b"q /Mask gs /Image Do Q")


@dataclass(frozen=True)
class _Color:
    """Resolved color-space definition plus original values, independent of names."""

    space: str = "/DeviceGray"
    values: tuple[str, ...] = ("0",)
    pattern: str | None = None

    def commands(self, document: pymupdf.Document, resources: int, stroke: bool) -> bytes:
        """Select this exact color in a private resource dictionary."""
        if self.space in _SPACES.values():
            op = next(key for key, value in _SPACES.items() if value == self.space)
            return f"{' '.join(self.values)} ".encode() + (op.upper() if stroke else op)
        identity = sha256(repr(self).encode()).hexdigest()[:16]
        alias = f"BC{identity}"
        document.xref_set_key(resources, f"ColorSpace/{alias}", self.space)
        values = " ".join(self.values)
        if self.pattern:
            pattern = f"BP{identity}"
            document.xref_set_key(resources, f"Pattern/{pattern}", self.pattern)
            values = f"{values} /{pattern}"
        return f"/{alias} {'CS' if stroke else 'cs'} {values} {'SCN' if stroke else 'scn'}".encode()

    def white(self, document: pymupdf.Document) -> bool:
        """Test exact device white; convert other solid color spaces with MuPDF."""
        values = tuple(float(value) for value in self.values)
        if self.space in ("/DeviceGray", "/DeviceRGB"):
            return all(value == 1 for value in values)
        if self.space == "/DeviceCMYK":
            return all(value == 0 for value in values)
        with pymupdf.open() as probe:
            resources = _object(document, "<< /ColorSpace <<>> /Pattern <<>> >>")
            command = self.commands(document, resources, False)
            copied = _graft(probe, document, resources)
            page = probe.new_page(width=2, height=2)
            probe.xref_set_key(page.xref, "Resources", f"{copied} 0 R")
            page.set_contents(_object(probe, data=command + b" 0 0 2 2 re f"))
            return page.get_pixmap().samples == bytes([255] * 12)


@dataclass
class _State:
    ctm: pymupdf.Matrix = field(default_factory=lambda: pymupdf.Matrix(1, 1))
    fill: _Color = field(default_factory=_Color)
    stroke: _Color = field(default_factory=_Color)
    lines: tuple[tuple[bytes, bytes], ...] = ()


@dataclass
class _Job:
    """One main-thread rendering and worker encoding, followed by main-thread graft."""

    target: int
    matrix: pymupdf.Matrix
    future: Future[bytes | regions._Page]
    image: Image.Image
    mask: Image.Image | None
    key: _ImageKey


class _Engine:
    """Own object replacement, bounded image workers and page-region bookkeeping.

    Args:
        document: Authenticated, writable in-memory source PDF; never saved in place.
        dpi: Base sampling resolution for each image's on-page dimensions.
        threshold: Fixed cutoff; unused in Sauvola mode.
        processing: Immutable image settings and the vector-color toggle.
        workers: Maximum simultaneous Pillow encoders. MuPDF stays on this thread.

    close() must run even on cancellation to release workers and image buffers.
    """

    def __init__(self, document: pymupdf.Document, dpi: int, threshold: int,
                 processing: _Processing, workers: int) -> None:
        self.document, self.dpi, self.threshold, self.processing = document, dpi, threshold, processing
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdf-encode")
        self.pending: deque[_Job] = deque()
        self.cache: dict[_ImageKey, tuple[int, tuple[regions._Region, ...] | None]] = {}
        self.colors: dict[_Color, bool] = {}
        self.notices: set[str] = set()
        self.boxes: list[regions._Region] = []
        self.page_rect = pymupdf.Rect()
        self.overrides: tuple[regions._Region, ...] | None = None
        self.images = 0

    def close(self) -> None:
        """Wait for encoders and close even cancelled or failed jobs' images."""
        self.executor.shutdown(wait=True, cancel_futures=True)
        while self.pending:
            job = self.pending.popleft()
            job.image.close()
            if job.mask is not None:
                job.mask.close()

    def _mapped(self, boxes: tuple[regions._Region, ...], matrix: pymupdf.Matrix,
                inverse: bool = False) -> tuple[regions._Region, ...]:
        """Map top-left image rectangles to displayed page coordinates or back."""
        transform = pymupdf.Matrix(1, 0, 0, -1, 0, 1) * matrix
        normalized = transform * pymupdf.Matrix(1 / self.page_rect.width, 1 / self.page_rect.height)
        if inverse:
            normalized = ~normalized
        mapped: list[regions._Region] = []
        for box in boxes:
            rect = (pymupdf.Rect(box.rect) * normalized) & pymupdf.Rect(0, 0, 1, 1)
            if not rect.is_empty:
                mapped.append(replace(box, rect=cast(regions._Rect, tuple(rect))))
        return tuple(mapped)

    def _finish(self) -> None:
        """Publish one completed worker in submission order, keeping memory bounded."""
        job = self.pending.popleft()
        try:
            encoded = job.future.result()
            copied = _form(self.document, encoded)
            if job.mask is not None:
                copied = _mask_form(self.document, copied, job.mask)
            # The target is a freshly allocated placeholder, never a source xref.
            oc = self.document.xref_get_key(job.target, "OC")[1]
            self.document.xref_copy(copied, job.target)
            if oc != "null":
                self.document.xref_set_key(job.target, "OC", oc)
            boxes = encoded.regions if isinstance(encoded, regions._Page) else ()
            self.cache[job.key] = job.target, boxes
            self.boxes.extend(self._mapped(boxes, job.matrix))
        finally:
            job.image.close()
            if job.mask is not None:
                job.mask.close()

    def _image(self, xref: int, matrix: pymupdf.Matrix) -> int:
        """Render/queue an ordinary image; leave already binary stencil masks alone."""
        document = self.document
        if document.xref_get_key(xref, "ImageMask")[1] == "true":
            return xref
        width, height = math.hypot(matrix.a, matrix.b), math.hypot(matrix.c, matrix.d)
        if min(width, height) < .001 or not math.isfinite(width + height):
            return xref
        overrides = None if self.overrides is None else self._mapped(self.overrides, matrix, inverse=True)
        key = (xref, round(width, 8), round(height, 8), overrides)
        self.images += 1
        if key in self.cache:
            target, boxes = self.cache[key]
            while boxes is None:
                self._finish()
                target, boxes = self.cache[key]
            self.boxes.extend(self._mapped(boxes, matrix))
            return target
        if len(self.pending) >= self.workers:
            self._finish()
        target = _object(document)
        oc = document.xref_get_key(xref, "OC")[1]
        if oc != "null":
            document.xref_set_key(target, "OC", oc)
        dpi = self.dpi
        sampling: int | tuple[float, float] = dpi
        if self.processing.dpi_policy.value == "cap":
            pixels_x = int(document.xref_get_key(xref, "Width")[1])
            pixels_y = int(document.xref_get_key(xref, "Height")[1])
            sampling = min(dpi, pixels_x * 72 / width), min(dpi, pixels_y * 72 / height)
            dpi = max(1, math.floor(min(sampling) + 1e-6))
        image, mask = _render_image(document, xref, width, height, sampling, self.processing.regions.active)
        try:
            future = self.executor.submit(raster._encode_page, image, dpi, self.threshold,
                                          self.processing, overrides)
        except BaseException:
            image.close()
            if mask is not None:
                mask.close()
            raise
        self.cache[key] = target, None
        self.pending.append(_Job(target, matrix, future, image, mask, key))
        return target

    def _inline(self, inline: dict[str, object], resources: int) -> int:
        """Promote an inline image to a private image object before processing."""
        aliases = {"/W": "/Width", "/H": "/Height", "/BPC": "/BitsPerComponent",
                   "/CS": "/ColorSpace", "/F": "/Filter", "/DP": "/DecodeParms",
                   "/D": "/Decode", "/IM": "/ImageMask", "/I": "/Interpolate"}
        values = {"/G": "/DeviceGray", "/RGB": "/DeviceRGB", "/CMYK": "/DeviceCMYK",
                  "/AHx": "/ASCIIHexDecode", "/A85": "/ASCII85Decode", "/LZW": "/LZWDecode",
                  "/Fl": "/FlateDecode", "/RL": "/RunLengthDecode", "/CCF": "/CCITTFaxDecode",
                  "/DCT": "/DCTDecode"}
        settings = cast(DictionaryObject, inline["settings"])
        converted = DictionaryObject()
        for key, value in settings.items():
            converted[NameObject(aliases.get(str(key), str(key)))] = (
                NameObject(values[str(value)]) if isinstance(value, NameObject) and str(value) in values else value)
        converted[NameObject("/Type")] = NameObject("/XObject")
        converted[NameObject("/Subtype")] = NameObject("/Image")
        xref = _object(self.document)
        self.document.update_stream(xref, cast(bytes, inline["data"]), compress=False)
        # Retain original Filter/DecodeParms rather than decoding twice.
        self.document.update_object(xref, _serialize(converted))
        space = str(converted.get("/ColorSpace", ""))
        if space.startswith("/") and space not in _SPACES.values():
            definition = _entry(self.document, resources, "ColorSpace", space[1:])
            if definition != "null":
                self.document.xref_set_key(xref, "ColorSpace", definition)
        return xref

    def _color(self, state: _State, operands: _Operands, op: bytes, resources: int) -> None:
        """Track source colors without changing the original color operators."""
        color = state.stroke if op.isupper() else state.fill
        lower = op.lower()
        if lower in _SPACES:
            color = _Color(_SPACES[lower], tuple(_serialize(value) for value in operands))
        elif lower == b"cs":
            name = str(operands[0])
            space = name if name in (*_SPACES.values(), "/Pattern") else _entry(
                self.document, resources, "ColorSpace", name[1:])
            color = _Color(space, ("0", "0", "0", "1") if space == "/DeviceCMYK" else
                           ("0", "0", "0") if space == "/DeviceRGB" else ("0",))
        else:
            pattern = None
            if operands and isinstance(operands[-1], NameObject):
                pattern = _entry(self.document, resources, "Pattern", str(operands[-1])[1:])
                operands = operands[:-1]
            color = replace(color, values=tuple(_serialize(value) for value in operands), pattern=pattern)
        if op.isupper():
            state.stroke = color
        else:
            state.fill = color

    def _tile_color(self, color: _Color, state: _State, resources: int,
                    ancestors: tuple[int, ...]) -> _Color | None:
        """Rewrite tiling-pattern artwork recursively, retaining text in the tile."""
        if color.pattern is None:
            return None
        document = self.document
        target = int(color.pattern.split()[0]) if color.pattern.endswith(" R") else _object(document, color.pattern)
        if document.xref_get_key(target, "PatternType")[1] != "1":
            return None
        if target in ancestors:
            raise ValueError("Cyclic PDF pattern reference.")
        initial = replace(state)
        kind, matrix = document.xref_get_key(target, "Matrix")
        if kind != "null":
            initial.ctm = pymupdf.Matrix(*(float(value) for value in matrix.strip("[]").split())) * state.ctm
        own = _object(document, _dictionary(document, target, "Resources"))
        data = document.xref_stream(target)
        if document.xref_get_key(target, "PaintType")[1] == "2":
            # Turn an uncolored tile into a colored tile, recording its inherited
            # source color so text remains unchanged while paths can turn black.
            space = color.space
            if space.endswith(" R"):
                space = document.xref_object(int(space.split()[0]))
            definition = read_object(io.BytesIO(space.encode()), _SYNTAX_READER)
            if not isinstance(definition, ArrayObject) or len(definition) < 2:
                raise ValueError("Uncolored pattern lacks its base color space.")
            base = _Color(_serialize(definition[1]), color.values)
            initial.fill = initial.stroke = base
            for category in ("ColorSpace", "Pattern"):
                document.xref_set_key(own, category, _dictionary(document, own, category))
            data = base.commands(document, own, False) + b"\n" + base.commands(document, own, True) + b"\n" + data
        rewritten, new_resources, _ = self.rewrite(data, document.xref_object(own), initial, (*ancestors, target))
        clone = _object(document, document.xref_object(target), rewritten)
        document.xref_set_key(clone, "Resources", f"{new_resources} 0 R")
        document.xref_set_key(clone, "PaintType", "1")
        return _Color("/Pattern", (), f"{clone} 0 R")

    def _paint(self, state: _State, op: bytes, resources: int, patterns: dict[bool, _Color]) -> bytes:
        """Change path colors only; restore source colors before subsequent text.

        No q/Q is inserted around painting: that would undo a pending W/W* clip.
        """
        before, after = [], []
        for stroke, used, color in ((True, op in _STROKE, state.stroke), (False, op in _FILL, state.fill)):
            if not used:
                continue
            if stroke in patterns:
                before.append(patterns[stroke].commands(self.document, resources, stroke))
                after.append(color.commands(self.document, resources, stroke))
                continue
            if not self.processing.vectors:
                continue
            if color not in self.colors:
                self.colors[color] = color.white(self.document)
            before.append(f"{int(self.colors[color])} {'G' if stroke else 'g'}".encode())
            after.append(color.commands(self.document, resources, stroke))
        return b"\n".join([*before, op, *after])

    def _complex_paint(self, state: _State, resources: int, paint: bytes,
                       path: list[tuple[_Operands, bytes, pymupdf.Matrix]]) -> int:
        """Rasterize only a gradient/pattern paint, retaining the surrounding page.

        Flat paths stay vectors. Complex paint uses the requested base DPI and a
        separate alpha mask; native page text and existing clipping are untouched.
        """
        document = self.document
        commands: list[bytes] = [state.fill.commands(document, resources, False),
                                 state.stroke.commands(document, resources, True)]
        commands.extend(value for _, value in state.lines)
        for operands, op, matrix in path:
            values = [float(value) for value in operands]
            relative = matrix * ~state.ctm
            if op == b"re":
                x, y, width, height = values
                points = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
                for index, point in enumerate(points):
                    transformed = pymupdf.Point(point) * relative
                    commands.append(f"{transformed.x:.12g} {transformed.y:.12g} {'m' if index == 0 else 'l'}".encode())
                commands.append(b"h")
            else:
                transformed_values: list[str] = []
                for index in range(0, len(values), 2):
                    point = pymupdf.Point(values[index:index + 2]) * relative
                    transformed_values.extend((f"{point.x:.12g}", f"{point.y:.12g}"))
                commands.append(" ".join(transformed_values).encode() + b" " + op)
        commands.append(paint)
        width, height = self.page_rect.width, self.page_rect.height
        matrix = state.ctm * pymupdf.Matrix(1, 0, 0, -1, 0, height)
        with pymupdf.open() as isolated:
            # Exclude fonts/XObjects: rendering an individual paint never needs page text.
            limited = _object(document, "<<>>")
            for category in ("ColorSpace", "Pattern", "Shading"):
                document.xref_set_key(limited, category, _dictionary(document, resources, category))
            copied = _graft(isolated, document, limited)
            page = isolated.new_page(width=width, height=height)
            isolated.xref_set_key(page.xref, "Resources", f"{copied} 0 R")
            prefix = f"{' '.join(f'{value:.12g}' for value in matrix)} cm\n".encode()
            page.set_contents(_object(isolated, data=prefix + b"\n".join(commands)))
            color, mask = _unpremultiply(page.get_pixmap(dpi=self.dpi, alpha=True))
            # Compare all RGB components: near-white and colored paint must be black.
            with color:
                white = np.all(np.asarray(color) == 255, axis=2).astype(np.uint8) * 255
            image = Image.fromarray(white)
            try:
                encoded = raster._encode_page(image, self.dpi, 255, _Processing())
                return _mask_form(document, _form(document, encoded), mask)
            finally:
                mask.close()

    def rewrite(self, data: bytes, resources: str, initial: _State,
                ancestors: tuple[int, ...] = ()) -> tuple[bytes, int, bool]:
        """Copy changed image/form resources for one invocation, preserving paint order."""
        if len(ancestors) > _MAX_DEPTH:
            raise ValueError("PDF form nesting exceeds the supported depth.")
        document = self.document
        resource = _object(document, resources)
        for category in ("XObject", "ColorSpace", "Pattern"):
            document.xref_set_key(resource, category, _dictionary(document, resource, category))
        state, stack = replace(initial), []
        stream = _parse(data)
        output: list[_Operation] = []
        changed = False
        used: set[str] = set()
        path: list[tuple[_Operands, bytes, pymupdf.Matrix]] = []
        for raw_operands, op in stream.operations:
            operands = cast(_Operands, raw_operands)
            if op == b"q":
                stack.append(replace(state))
            elif op == b"Q":
                if not stack:
                    raise ValueError("Unbalanced PDF graphics-state stack.")
                state = stack.pop()
            elif op == b"cm":
                state.ctm = pymupdf.Matrix(*(float(value) for value in operands)) * state.ctm
            elif op in (b"w", b"J", b"j", b"M", b"d", b"i"):
                command = " ".join(_serialize(value) for value in operands).encode() + b" " + op
                state.lines = tuple(item for item in state.lines if item[0] != op) + ((op, command),)
            elif op.lower() in (*_SPACES, b"cs", b"sc", b"scn"):
                self._color(state, operands, op, resource)
            elif op in (b"Do", b"INLINE IMAGE"):
                if op == b"INLINE IMAGE":
                    target = self._inline(cast(dict[str, object], raw_operands), resource)
                    name = f"Inline{target}"
                else:
                    name = str(operands[0])[1:]
                    value = _entry(document, resource, "XObject", name)
                    if not value.endswith(" R"):
                        raise ValueError(f"Missing XObject resource: {name}")
                    target = int(value.split()[0])
                replacement = target
                subtype = document.xref_get_key(target, "Subtype")[1]
                if subtype == "/Image":
                    replacement = self._image(target, state.ctm)
                elif subtype == "/Form":
                    if target in ancestors:
                        raise ValueError("Cyclic PDF form reference.")
                    form_state = replace(state)
                    kind, matrix = document.xref_get_key(target, "Matrix")
                    if kind != "null":
                        form_state.ctm = pymupdf.Matrix(*(float(value) for value in matrix.strip("[]").split())) * state.ctm
                    own = _dictionary(document, target, "Resources") if document.xref_get_key(target, "Resources")[0] != "null" else resources
                    rewritten, own_resource, form_changed = self.rewrite(
                        document.xref_stream(target), own, form_state, (*ancestors, target))
                    if form_changed:
                        replacement = _object(document, document.xref_object(target), rewritten)
                        document.xref_set_key(replacement, "Resources", f"{own_resource} 0 R")
                if replacement != target or op == b"INLINE IMAGE":
                    name = f"Binary{replacement}"
                    document.xref_set_key(resource, f"XObject/{name}", f"{replacement} 0 R")
                    operands, op, changed = [NameObject(f"/{name}")], b"Do", True
                used.add(name)
            elif ((op in _PAINT and (self.processing.vectors or state.fill.pattern or state.stroke.pattern))
                  or (self.processing.vectors and op == b"sh")):
                patterns: dict[bool, _Color] = {}
                for stroke, used_color, color in ((True, op in _STROKE, state.stroke),
                                                  (False, op in _FILL, state.fill)):
                    if used_color and color.pattern:
                        converted = self._tile_color(color, state, resource, ancestors)
                        if converted is not None:
                            patterns[stroke] = converted
                complex_paint = self.processing.vectors and (op == b"sh" or (
                    op in _FILL and state.fill.pattern is not None and False not in patterns) or (
                    op in _STROKE and state.stroke.pattern is not None and True not in patterns))
                if complex_paint:
                    paint = " ".join(_serialize(value) for value in operands).encode() + b" " + op
                    replacement = self._complex_paint(state, resource, paint, path if op != b"sh" else [])
                    name = f"BinaryVector{replacement}"
                    used.add(name)
                    document.xref_set_key(resource, f"XObject/{name}", f"{replacement} 0 R")
                    placement = pymupdf.Matrix(self.page_rect.width, 0, 0, -self.page_rect.height,
                                               0, self.page_rect.height) * ~state.ctm
                    command = (b"n " if op in _PAINT else b"") + (
                        f"q {' '.join(f'{value:.12g}' for value in placement)} cm /{name} Do Q".encode())
                    output.extend(cast(list[_Operation], _parse(command).operations))
                    self.notices.add("Complex vector fills encoded separately as 1-bit images with alpha masks.")
                else:
                    output.extend(cast(list[_Operation], _parse(self._paint(state, op, resource, patterns)).operations))
                if op in _PAINT:
                    path.clear()
                changed = True
                continue
            if op in _PATH:
                path.append((operands, op, state.ctm))
            elif op in (*_PAINT, b"n"):
                path.clear()
            output.append((operands, op))
        if not changed:
            return data, resource, False
        # Discard unused original image/form references so compression can collect them.
        xobjects = " ".join(f"{_serialize(NameObject(f'/{name}'))} {_entry(document, resource, 'XObject', name)}"
                            for name in sorted(used))
        document.xref_set_key(resource, "XObject", f"<< {xobjects} >>")
        stream.operations = output
        return stream.get_data(), resource, True

    def page(self, index: int, overrides: tuple[regions._Region, ...] | None = None) -> tuple[regions._Region, ...]:
        """Process one page in place, retaining its dictionary, geometry and features."""
        page = self.document[index]
        self.page_rect, self.overrides, self.boxes = page.rect, overrides, []
        initial = _State(ctm=page.transformation_matrix * page.rotation_matrix)
        data, resource, changed = self.rewrite(page.read_contents(), _resources(self.document, page), initial)
        while self.pending:
            self._finish()
        if changed:
            self.document.xref_set_key(page.xref, "Resources", f"{resource} 0 R")
            page.set_contents(_object(self.document, data=data))
        return tuple(self.boxes)
