"""Resource-preserving crop export and destination remapping, migrated from the CLI."""

from collections.abc import Callable
from dataclasses import dataclass, replace
import math
import re
from typing import Any

import pymupdf
from tqdm import tqdm
from utils import *
from .model import Settings, PageOverride, page_boxes


@dataclass(frozen=True)
class _Piece:
    """One output index and its crop in displayed source-page points."""

    output_index: int
    clip: pymupdf.Rect
    paper: pymupdf.Rect | None = None

    @property
    def viewport(self) -> pymupdf.Rect:
        """Return fixed output paper in original displayed coordinates, including padding."""
        return self.paper if self.paper is not None else self.clip


def build_plan(source: pymupdf.Document, settings: Settings,
               overrides: dict[int, PageOverride]) -> list[list[_Piece]]:
    """Validate all rules and resolve crops before mutating an output document.

    Args:
        source: Authenticated read-only input.
        settings: Global strip count, axis, order and physical range.
        overrides: One-based page overrides, each whole or explicit normalized crops.
    Returns:
        Output-indexed crops grouped by original page.
    Raises:
        ValueError: Invalid range, override, page dimensions or geometry.
    """
    settings.validate(source.page_count)
    for page, override in overrides.items():
        if not 1 <= page <= source.page_count:
            raise ValueError("Override page is outside the PDF.")
        override.validate()
    plan: list[list[_Piece]] = []
    output_index = 0
    for index in range(source.page_count):
        rect = source[index].rect
        if rect.is_empty or rect.is_infinite or not all(math.isfinite(v) for v in rect):
            raise ValueError(f"PDF page {index + 1} has invalid dimensions.")
        pieces: list[_Piece] = []
        override = overrides.get(index + 1)
        canvas = override.canvas if override and override.canvas else settings.canvas_size()
        if override and not override.keep:
            replace(override, canvas=canvas).validate()
        whole = override.keep if override else not settings.applies(index + 1, source.page_count)
        for box in page_boxes(settings, overrides, index + 1, source.page_count):
            box.validate()
            clip = pymupdf.Rect(rect.x0 + box.x0 * rect.width, rect.y0 + box.y0 * rect.height,
                                rect.x0 + box.x1 * rect.width, rect.y0 + box.y1 * rect.height)
            center = (clip.tl + clip.br) / 2
            width, height = (rect.width, rect.height) if whole else (canvas[0] * rect.width, canvas[1] * rect.height)
            paper = pymupdf.Rect(center.x - width / 2, center.y - height / 2,
                                 center.x + width / 2, center.y + height / 2)
            pieces.append(_Piece(output_index, clip, paper))
            output_index += 1
        plan.append(pieces)
    return plan


def _map_target(pieces: list[_Piece], point: pymupdf.Point | None) -> tuple[int, pymupdf.Point, bool]:
    """Translate a displayed destination; fall back to the first output piece."""
    if point is not None and math.isfinite(point.x) and math.isfinite(point.y):
        for piece in pieces:
            if point in piece.clip:
                return piece.output_index, point - piece.viewport.tl, False
    return pieces[0].output_index, pymupdf.Point(0, 0), len(pieces) > 1


def _bookmark_point(source: pymupdf.Document, detail: dict[str, Any]) -> pymupdf.Point | None:
    """Accept explicit XYZ locations; Fit and null-coordinate targets are ambiguous."""
    xref = detail.get("xref", 0)
    if not xref:
        return None
    destination = source.xref_get_key(xref, "A/D")
    if destination[0] == "null":
        destination = source.xref_get_key(xref, "Dest")
    match = re.search(r"/XYZ\s+([^\s]+)\s+([^\s]+)", destination[1])
    if match is None or "null" in match.groups():
        return None
    point = detail.get("to")
    return pymupdf.Point(point) if isinstance(point, pymupdf.Point) else None


def _pdf_point(page: pymupdf.Page, displayed: pymupdf.Point) -> pymupdf.Point:
    """Convert a displayed point to PDF space, including rotated CropBox offsets."""
    point = displayed * page.derotation_matrix
    return pymupdf.Point(point.x + page.cropbox.x0, page.mediabox.y1 - page.cropbox.y0 - point.y)


def _copy_bookmarks(source: pymupdf.Document, output: pymupdf.Document, plan: list[list[_Piece]]) -> int:
    """Keep outline hierarchy/styles and remap local targets; return ambiguous count."""
    toc = source.get_toc(False)
    ambiguous = 0
    for entry in toc:
        detail = dict(entry[3])
        if detail.get("kind") in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED) and 1 <= entry[2] <= len(plan):
            index, point, uncertain = _map_target(plan[entry[2] - 1], _bookmark_point(source, detail))
            detail.update(kind=pymupdf.LINK_GOTO, page=index, to=point)
            detail.pop("nameddest", None)
            detail.pop("view", None)
            entry[2] = index + 1
            ambiguous += uncertain
        detail.pop("xref", None)
        entry[3] = detail
    output.set_toc(toc, collapse=0)
    # set_toc's coordinate conversion omits some CropBox offsets on rotated
    # pages. Write remapped local destinations in PDF space explicitly.
    for xref, entry in zip(output.get_outline_xrefs(), toc):
        detail = entry[3]
        if "collapse" in detail:
            kind, count = output.xref_get_key(xref, "Count")
            if kind == "int":
                magnitude = abs(int(count))
                output.xref_set_key(xref, "Count", str(-magnitude if detail["collapse"] else magnitude))
        if detail.get("kind") == pymupdf.LINK_GOTO and entry[2] > 0:
            page = output[entry[2] - 1]
            point = _pdf_point(page, detail["to"])
            zoom = detail.get("zoom", 0)
            output.xref_set_key(xref, "A", f"<< /S /GoTo /D [{page.xref} 0 R /XYZ {point.x} {point.y} {zoom}] >>")
    return ambiguous


def _copy_links(source: pymupdf.Document, output: pymupdf.Document, plan: list[list[_Piece]]) -> int:
    """Clip link regions and remap local targets; return unsupported action count."""
    skipped = 0
    supported = {pymupdf.LINK_GOTO, pymupdf.LINK_URI, pymupdf.LINK_GOTOR, pymupdf.LINK_LAUNCH}
    for index, pieces in enumerate(plan):
        for original in source[index].get_links():
            link = dict(original)
            if link["kind"] not in supported:
                skipped += 1
                continue
            if link["kind"] == pymupdf.LINK_GOTO:
                target = link.get("page", -1)
                if not 0 <= target < len(plan):
                    skipped += 1
                    continue
                target_index, point, _ = _map_target(plan[target], link.get("to"))
                target_page = output[target_index]
                link.update(page=target_index, to=_pdf_point(target_page, point) * target_page.transformation_matrix)
            link.pop("xref", None)
            link.pop("id", None)
            for piece in pieces:
                region = original["from"] & piece.clip & source[index].rect
                if region.is_empty:
                    continue
                page = output[piece.output_index]
                relative = pymupdf.Rect(region.x0 - piece.viewport.x0, region.y0 - piece.viewport.y0,
                                        region.x1 - piece.viewport.x0, region.y1 - piece.viewport.y0)
                pdf_rect = pymupdf.Rect(_pdf_point(page, relative.tl), _pdf_point(page, relative.br)).normalize()
                link["from"] = pdf_rect * page.transformation_matrix
                page.insert_link(link)
    return skipped


def _pdf_rectangle(page: pymupdf.Page, rect: pymupdf.Rect) -> pymupdf.Rect:
    """Map a displayed rectangle to absolute PDF coordinates before changing page boxes."""
    return pymupdf.Rect(_pdf_point(page, rect.tl), _pdf_point(page, rect.br)).normalize()


def _array(rect: pymupdf.Rect) -> str:
    return f"[{rect.x0:.8f} {rect.y0:.8f} {rect.x1:.8f} {rect.y1:.8f}]"


def _numbers(value: str) -> list[float]:
    return [float(number) for number in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)", value)]


def _clipped_appearance(document: pymupdf.Document, xref: int, original: pymupdf.Rect,
                        clipped: pymupdf.Rect) -> int:
    """Wrap an annotation appearance without scaling its ink when its hit rectangle shrinks."""
    bbox = _numbers(document.xref_get_key(xref, "BBox")[1])
    matrix = _numbers(document.xref_get_key(xref, "Matrix")[1])
    if len(bbox) != 4 or (matrix and len(matrix) != 6):
        raise ValueError("Cannot clip an annotation with an invalid appearance box/matrix.")
    bounds = pymupdf.Rect(bbox) * (pymupdf.Matrix(*matrix) if matrix else pymupdf.Identity)
    if bounds.is_empty:
        raise ValueError("Cannot clip an annotation with an empty appearance.")
    sx, sy = original.width / bounds.width, original.height / bounds.height
    tx, ty = original.x0 - bounds.x0 * sx, original.y0 - bounds.y0 * sy
    content = f"q {sx:.8f} 0 0 {sy:.8f} {tx:.8f} {ty:.8f} cm /Original Do Q".encode("ascii")
    return Pdf.new_object(document, f"<< /Type /XObject /Subtype /Form /BBox {_array(clipped)} "
        f"/Resources << /XObject << /Original {xref} 0 R >> >> >>", content)


def _clip_annotations(page: pymupdf.Page, clip: pymupdf.Rect) -> None:
    """Limit copied annotations/widgets to the crop, preserving independent appearance resources."""
    document = page.parent
    assert document is not None
    retained: list[int] = []
    annotations = page.annot_xrefs()
    # insert_pdf's reusable graft map can share annotation dictionaries between
    # copied pages. Never alter those dictionaries in place when clipping.
    # Widgets are already isolated by insert_pdf and registered in AcroForm.
    # Retain their xrefs so the field tree and page annotation references agree.
    widgets = {widget.xref: widget for widget in page.widgets() if isinstance(widget, pymupdf.Widget)}
    copies = {xref: xref if xref in widgets else
              Pdf.new_object(document, document.xref_object(xref)) for xref, _kind, _ in annotations}
    for original_xref, _kind, _name in annotations:
        xref = copies[original_xref]
        document.xref_set_key(xref, "P", f"{page.xref} 0 R")
        for key in ("Popup", "IRT", "Parent"):
            kind, value = document.xref_get_key(xref, key)
            if kind == "xref" and int(value.split()[0]) in copies:
                document.xref_set_key(xref, key, f"{copies[int(value.split()[0])]} 0 R")
        values = _numbers(document.xref_get_key(xref, "Rect")[1])
        if len(values) != 4:
            retained.append(xref)
            continue
        original = pymupdf.Rect(values).normalize()
        clipped = original & clip
        if clipped.is_empty:
            if original_xref in widgets:
                page.delete_widget(widgets[original_xref])
            continue
        retained.append(xref)
        if clipped == original:
            continue
        # Keep the old appearance's placement, but give each copied annotation a
        # private AP dictionary/form so sibling and ignored pages stay unchanged.
        appearance = Pdf.read_dictionary(document, xref, "AP")
        ap = Pdf.new_object(document, appearance)
        for state in ("N", "R", "D"):
            kind, value = document.xref_get_key(ap, state)
            if kind == "xref":
                wrapped = _clipped_appearance(document, int(value.split()[0]), original, clipped)
                document.xref_set_key(ap, state, f"{wrapped} 0 R")
            elif kind == "dict":
                entries = re.findall(r"(/[^\s<>\[\]()/]+)\s+(\d+)\s+\d+\s+R", value)
                mapped = [f"{name} {_clipped_appearance(document, int(ref), original, clipped)} 0 R"
                          for name, ref in entries]
                document.xref_set_key(ap, state, f"<< {' '.join(mapped)} >>")
        document.xref_set_key(xref, "AP", f"{ap} 0 R")
        document.xref_set_key(xref, "Rect", _array(clipped))
    document.xref_set_key(page.xref, "Annots", f"[{' '.join(f'{xref} 0 R' for xref in retained)}]")


def _pad_page(source_page: pymupdf.Page, page: pymupdf.Page, piece: _Piece) -> None:
    """Clip original vector content in a Form, then set fixed paper bounds around it.

    Absolute PDF coordinates avoid resampling or translating original streams.
    Out-of-source areas and margins around reduced crops contain no content.
    """
    document = page.parent
    assert document is not None
    visible = piece.clip & source_page.rect
    paper = _pdf_rectangle(source_page, piece.viewport)
    clip = _pdf_rectangle(source_page, visible) if not visible.is_empty else pymupdf.Rect()
    if visible.is_empty:
        contents = Pdf.new_object(document, data=b"")
    else:
        resources = Pdf.read_dictionary(document, page.xref, "Resources")
        form = Pdf.new_object(document,
            f"<< /Type /XObject /Subtype /Form /BBox {_array(clip)} /Resources {resources} >>",
            b"\n".join(document.xref_stream(xref) for xref in page.get_contents()))
        document.xref_set_key(page.xref, "Resources", f"<< /XObject << /CropContent {form} 0 R >> >>")
        contents = Pdf.new_object(document, data=b"q /CropContent Do Q")
    document.xref_set_key(page.xref, "Contents", f"{contents} 0 R")
    _clip_annotations(page, clip)
    page.set_mediabox(paper)
    document.xref_set_key(page.xref, "CropBox", _array(paper))


def _split_document(
    source: pymupdf.Document, output: pymupdf.Document, plan: list[list[_Piece]], *, progress: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    """Copy/crop pages and remap navigation in memory; return warning counts."""
    with tqdm(total=source.page_count, desc="Splitting pages", unit="page", disable=not progress) as bar:
        for index, pieces in enumerate(plan):
            page = source[index]
            for piece in pieces:
                output.insert_pdf(source, from_page=index, to_page=index, links=False,
                                  annots=True, widgets=True, final=0)
                if piece.clip != piece.viewport or not page.rect.contains(piece.clip):
                    _pad_page(page, output[piece.output_index], piece)
                elif piece.clip != page.rect:
                    # CropBox coordinates are unrotated and offset from the
                    # visible origin; retain the original rotation and resources.
                    rect = piece.clip * page.derotation_matrix
                    offset = page.cropbox.tl
                    crop = pymupdf.Rect(rect.x0 + offset.x, rect.y0 + offset.y,
                                        rect.x1 + offset.x, rect.y1 + offset.y)
                    output[piece.output_index].set_cropbox(crop)
            bar.update(1)
            if on_progress is not None:
                on_progress(index + 1, source.page_count)
    output.set_metadata(source.metadata or {})
    xml = source.get_xml_metadata()
    if xml:
        output.set_xml_metadata(xml)
    for name in source.embfile_names():
        info = source.embfile_info(name)
        output.embfile_add(name, source.embfile_get(name), filename=info.get("filename"),
                           ufilename=info.get("ufilename"), desc=info.get("description"))
    ambiguous = _copy_bookmarks(source, output, plan)
    skipped_links = _copy_links(source, output, plan)
    # Remove the rule tree, rather than writing blank or sequential labels.
    output.xref_set_key(output.pdf_catalog(), "PageLabels", "null")
    return ambiguous, skipped_links
