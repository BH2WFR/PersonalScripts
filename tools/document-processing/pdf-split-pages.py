#!/usr/bin/env python3
"""Split scanned PDF pages left/right or top/bottom without rasterizing them.

Load a PDF, choose the axis, reading order and split percentage (default 50),
then select physical pages to leave whole using ranges such as 1,2-3,-1.
Directions follow the displayed page, including its rotation and crop box.
Copies reuse PDF resources and crop each half without resampling scan images.
No temporary PDF or per-page image files are created. Saves an unencrypted new
copy with collision avoidance, standard metadata, XMP and embedded attachments.

ALL navigation page labels are removed, including labels on ignored pages;
printed page numbers are unchanged. Bookmarks and ordinary links are remapped.
Bookmarks with explicit XYZ coordinates follow the corresponding half; targets
without usable coordinates go to the first output half and may be one page
early. Their count is reported. Unsupported link actions are counted and skipped.
Page annotations and widgets are copied and clipped with their page contents.

Requirements:
    - pip: PyMuPDF, tqdm

Usage:
    python pdf-split-pages.py [input.pdf]
    python pdf-split-pages.py input.pdf -o output.pdf
"""

import argparse
from dataclasses import dataclass
from enum import StrEnum
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, cast

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

try:
    import pymupdf
    from pymupdf.mupdf import FzErrorBase
    from tqdm import tqdm
except ImportError as exc:
    print(f"{FLRed}Missing dependency: {exc.name}{CRst}")
    print(f"{FGray}Install with: pip install PyMuPDF tqdm{CRst}")
    sys.exit(1)


class _Axis(StrEnum):
    LEFT_RIGHT = "left_right"
    TOP_BOTTOM = "top_bottom"


@dataclass(frozen=True)
class _Piece:
    """One output page and its region in the original displayed page."""

    output_index: int
    clip: pymupdf.Rect


def _build_plan(
    source: pymupdf.Document, ignored: set[int], axis: _Axis, reverse: bool, percent: float,
) -> list[list[_Piece]]:
    """Map original pages to output rectangles, including unsplit ignored pages."""
    if not math.isfinite(percent) or not 0 < percent < 100:
        raise ValueError("Split percentage must be strictly between 0 and 100.")
    if any(index < 0 or index >= source.page_count for index in ignored):
        raise ValueError("Ignored pages must be inside the input PDF.")
    plan: list[list[_Piece]] = []
    output_index = 0
    for index in range(source.page_count):
        page = source.load_page(index)
        rect = page.rect
        if rect.is_empty or rect.is_infinite:
            raise ValueError(f"PDF page {index + 1} has invalid dimensions.")
        if index in ignored:
            clips = [rect]
        else:
            if axis is _Axis.LEFT_RIGHT:
                cut = rect.x0 + rect.width * percent / 100
                clips = [pymupdf.Rect(rect.x0, rect.y0, cut, rect.y1),
                         pymupdf.Rect(cut, rect.y0, rect.x1, rect.y1)]
            else:
                cut = rect.y0 + rect.height * percent / 100
                clips = [pymupdf.Rect(rect.x0, rect.y0, rect.x1, cut),
                         pymupdf.Rect(rect.x0, cut, rect.x1, rect.y1)]
            if reverse:
                clips.reverse()
        plan.append([_Piece(output_index + offset, clip) for offset, clip in enumerate(clips)])
        output_index += len(clips)
    return plan


def _map_target(pieces: list[_Piece], point: pymupdf.Point | None) -> tuple[int, pymupdf.Point, bool]:
    """Translate a displayed destination; fall back to the first output piece."""
    if point is not None and math.isfinite(point.x) and math.isfinite(point.y):
        for piece in pieces:
            if point in piece.clip:
                return piece.output_index, point - piece.clip.tl, False
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
                region = original["from"] & piece.clip
                if region.is_empty:
                    continue
                page = output[piece.output_index]
                relative = pymupdf.Rect(region.x0 - piece.clip.x0, region.y0 - piece.clip.y0,
                                        region.x1 - piece.clip.x0, region.y1 - piece.clip.y0)
                pdf_rect = pymupdf.Rect(_pdf_point(page, relative.tl), _pdf_point(page, relative.br)).normalize()
                link["from"] = pdf_rect * page.transformation_matrix
                page.insert_link(link)
    return skipped


def _split_document(
    source: pymupdf.Document, output: pymupdf.Document, plan: list[list[_Piece]], *, progress: bool = True,
) -> tuple[int, int]:
    """Copy/crop pages and remap navigation in memory; return warning counts."""
    with tqdm(total=source.page_count, desc="Splitting pages", unit="page", disable=not progress) as bar:
        for index, pieces in enumerate(plan):
            page = source[index]
            for piece in pieces:
                output.insert_pdf(source, from_page=index, to_page=index, links=False,
                                  annots=True, widgets=True, final=0)
                if len(pieces) == 2:
                    # CropBox coordinates are unrotated and offset from the
                    # visible origin; retain the original rotation and resources.
                    rect = piece.clip * page.derotation_matrix
                    offset = page.cropbox.tl
                    crop = pymupdf.Rect(rect.x0 + offset.x, rect.y0 + offset.y,
                                        rect.x1 + offset.x, rect.y1 + offset.y)
                    output[piece.output_index].set_cropbox(crop)
            bar.update(1)
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


def main() -> int:
    """Prompt for splitting options, write a new PDF, and return 0 or 1."""
    if "--help" in sys.argv or "-h" in sys.argv:
        name = os.path.basename(sys.argv[0])
        print(f"""{FLYellow}PDF PAGE SPLITTER{CRst}

{FLYellow}Usage:{CRst}
  python {name} [input.pdf] [-o output.pdf]

{FLYellow}Description:{CRst}
  Split displayed pages left/right or top/bottom; choose either reading order.
  Split position defaults to 50%, measured from the left or top regardless of order.
  Ignore physical pages with 1,2-3,-1 (-1 = last); ignored pages remain whole.
  Copies and crops PDF resources without rasterizing or creating temporary files.
  ALL page tags / page labels are removed, including those on ignored pages.
  Printed page numbers remain unchanged. Bookmarks and ordinary links are remapped.
  Bookmarks without usable coordinates target the first output half and may be
  one page early. Unsupported link actions are skipped with a count.
  Saves a new unencrypted PDF; existing files are never overwritten.

{FLYellow}Options:{CRst}
  input.pdf          input PDF; prompted when omitted
  -o, --output PATH  suggested output path (default: <input>_split.pdf)
  -h, --help         show this help

{FLYellow}Requirements:{CRst}
  {FGray}pip install PyMuPDF tqdm{CRst}
""")
        return 0

    Console.print_banner("PDF PAGE SPLITTER")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("input", nargs="?")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    filepath = args.input or Input.resolve_input_path(
        os.path.expanduser("~/input.pdf"), prompt="Enter input PDF file path", path_type="file",
    )
    try:
        with Pdf.open_document(filepath) as (source, _):
            if not source.page_count:
                raise ValueError("The PDF contains no pages.")
            print(f"{FLGreen}PDF loaded. Total pages: {source.page_count}{CRst}")
            axis = cast(_Axis, Menu.select(
                [MenuOption(["L", "1"], "Left / right halves", _Axis.LEFT_RIGHT),
                 MenuOption(["T", "2"], "Top / bottom halves", _Axis.TOP_BOTTOM)],
                prompt="Split direction", required=True, default_key="L",
            ))
            first, second = ("Left", "right") if axis is _Axis.LEFT_RIGHT else ("Top", "bottom")
            reverse = bool(Menu.select(
                [MenuOption(["1"], f"{first} then {second}", False),
                 MenuOption(["2"], f"{second.capitalize()} then {first.lower()}", True)],
                prompt="Output order", required=True, default_key="1",
            ))
            percent = float(Input.input_number(
                f"Split position (% from the {first.lower()})", default=50,
                min_value=0, max_value=100, min_value_allowed=False, max_value_allowed=False,
            ))
            ignored = set(Input.input_index_ranges(
                "Pages to leave whole (empty = split all)", item_count=source.page_count,
            ) or ())
            plan = _build_plan(source, ignored, axis, reverse, percent)
            print(f"{FLCyan}Output: {sum(map(len, plan))} pages; {len(ignored)} original pages left whole.{CRst}")
            print(f"{FLYellow}WARNING: ALL page tags / page labels will be removed, including on ignored pages."
                  f" Printed page numbers are unchanged.{CRst}")
            if source.get_toc():
                print(f"{FLYellow}WARNING: Bookmarks without usable coordinates target the first output half"
                      f" and may be one page early. Please check bookmarks after splitting.{CRst}")
            path = Path(filepath)
            output_path = Input.resolve_output_path(
                args.output or str(path.with_name(f"{path.stem}_split.pdf")),
                prompt="Enter output PDF file path", path_type="file",
            )
            with pymupdf.open() as output:
                ambiguous, skipped_links = _split_document(source, output, plan)
                if ambiguous:
                    print(f"{FLYellow}Check {ambiguous} bookmarks assigned to the first output half.{CRst}")
                if skipped_links:
                    print(f"{FLYellow}Skipped {skipped_links} unsupported or unresolved page links.{CRst}")
                Pdf.save_new(output, output_path)
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}PDF splitting failed: {exc}{CRst}")
        return 1
    print(f"{FLGreen}Split PDF saved:{CRst} {FGray}{output_path}{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        Console.print_keyboard_interrupt_message_and_exit()
