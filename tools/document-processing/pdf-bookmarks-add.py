#!/usr/bin/env python3
"""Write PDF bookmarks from per-image JSON, optionally generating page labels.

Merge validated JSON arrays, then choose to replace existing bookmarks or
append new bookmarks while preserving the original outline hierarchy; Replace
is the default. Pasting JSON starting with '[' at the action menu continues
input automatically, retaining that first line. End the paste with EOF as usual.
Blank input, empty JSON strings/arrays, and null return to the action menu
without discarding earlier entries. Finishing with no entries writes no PDF.
Both write modes add root-level Cover and Table of Contents bookmarks.
Set the PDF page containing the first book page, then its printed page number
(default 1). For example, PDF page 17 can correspond to book page 20.
Before saving, choose whether to reset page labels from the book-page mapping
(Y by default); N preserves the existing labels.
Reset labels use C1, C2, ... for the chosen TOC PDF-page range. Body pages use
book numbers (or ranges for 2/4-up layouts). Other front-matter labels remain
unchanged. Without existing label rules, they retain physical page numbering.
The first body page shows only book pages at or after the chosen starting number. TOC labels take priority
if the TOC and body begin on the same PDF page. Printed page content is unchanged.
For standalone label editing or clearing, use pdf-page-tag.py.
PyMuPDF edits the document in memory and saves an unencrypted new file, retaining
document metadata and attachments. Passwords are prompted without echo.
PDF/A identification is automatically removed from the output metadata.

Requirements:
    - pip: PyMuPDF

Usage:
    python pdf-bookmarks-add.py input.pdf
    python pdf-bookmarks-add.py input.pdf -o output.pdf
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

import pymupdf
from pymupdf.mupdf import FzErrorBase
from typing import Optional


#============ LLM prompt ===========
# Model: Qwen3-VL-235B-A22B-Instruct or similar vision model
# Prompt:
"""
You are a tool that converts exactly one table-of-contents PDF page from a scanned book into JSON.

The input must contain exactly one image showing exactly one PDF page. That PDF page may contain 1, 2, or 4 physical book pages; transcribe all visible table-of-contents entries on it. If the input contains multiple images or more than one PDF page, append a following warning incidentally:

WARNING: Multiple TOC PDF pages detected. Please submit exactly one PDF page at a time.

Transcribe every visible table-of-contents entry from top to bottom. Do not summarize, omit entries, add placeholders, or invent titles and page numbers that are not visible in the image.

The script adds the root-level "Cover" and "Table of Contents" bookmarks separately. Do not invent them in the JSON; include either title only if it is visibly printed as a table-of-contents entry.

The first visible entry may continue a section from the preceding page and is very likely not a level-1 heading. Determine its actual level from its numbering, indentation, typography, surrounding entries, and any preceding-page context available. Do not reset the hierarchy at the start of each image.

Output one valid JSON array in the following format. Put each complete table-of-contents entry on one physical line:

```json
[
{"page": 1, "level": 1, "index": "", "title": "Preface"},
{"page": 3, "level": 1, "index": "Chapter 1", "title": "Discipline Overview"},
{"page": 3, "level": 2, "index": "1.1", "title": "Historical Development"},
{"page": 3, "level": 3, "index": "1.1.1", "title": "1920-1950: Emergence"},
{"page": 7, "level": 3, "index": "1.1.2", "title": "1950-2000: Growth"},
{"page": 10, "level": 2, "index": "1.2", "title": "Basic Concepts"},
{"page": 10, "level": 3, "index": "1.2.1", "title": "Politics"},
{"page": 20, "level": 1, "index": "Chapter 2", "title": "Camera Calibration and Imaging Model"},
{"page": 20, "level": 2, "index": "2.1", "title": "Camera Calibration Parameters"},
{"page": 20, "level": 3, "index": "2.1.1", "title": "Intrinsic Parameters"},
{"page": 100, "level": 1, "index": "", "title": "Afterword"},
{"page": 102, "level": 1, "index": "", "title": "References"}
]
```

The JSON must not contain comments, trailing commas, or explanatory objects. The `page` and `level` fields are required. `page` supports negative numbers (-1 = one page before page 1, -2 = two pages before page 1, and so on). `index` is optional; `index` and `title` are concatenated with a space to form the bookmark heading.

If the book has a preface (p0), references, or afterword, include them as level-1 chapter headings.
If the book has "parts" or "sections" above the chapter level, treat them as level 1, chapters as level 2, sub-sections as level 3, and so on.

If the book has no chapter or section numbers, leave `index` as an empty string.

After the JSON array, output this warning outside the JSON code block:

WARNING: Vision models can omit entries, attach the wrong page number, or mix content between rows. Carefully compare every item with the source image. Submit the next TOC page only after this page has been fully verified and corrected.

Message above should be printed only once, not repeated for each page.
"""


#* 全局变量
DEFAULT_PAGE_OFFSET = 10
DEFAULT_FIRST_BOOK_PAGE = 1
DEFAULT_COVER_PDF_PAGE = 1
COVER_BOOKMARK_TITLE = "Cover"
TOC_BOOKMARK_TITLE = "Table of Contents"

class _BookPagesPerPdf(enum.IntEnum):
    SINGLE = 1
    TWO = 2
    FOUR = 4


class _FirstPdfPageCount(enum.IntEnum):
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4


@dataclasses.dataclass(frozen=True)
class _PageMapping:
    """Map logical book pages to zero-based PDF page indexes.

    Attributes:
        page_offset: One-based PDF page containing the first book page.
        pages_per_pdf: Fixed number of physical book-page positions per PDF page.
        first_pdf_page_count: Book pages beginning at first_book_page that share
            the anchor PDF page.
        first_book_page: Positive printed number of the first book page; defaults
            to 1. Earlier positive book numbers still map backwards from it.
    """

    page_offset: int
    pages_per_pdf: _BookPagesPerPdf
    first_pdf_page_count: _FirstPdfPageCount
    first_book_page: int = DEFAULT_FIRST_BOOK_PAGE

    def pdf_index(self, logical_page: int) -> int:
        """Return the zero-based PDF index containing a logical book page.

        Args:
            logical_page: Non-zero printed or inferred book page number. Negative
                values count physical positions immediately preceding book page 1,
                independent of the selected first_book_page anchor.

        Returns:
            Zero-based index of the PDF page containing ``logical_page``.
        """
        sequence_index = logical_page - 1 if logical_page > 0 else logical_page
        sequence_index -= self.first_book_page - 1
        leading_positions = int(self.pages_per_pdf) - int(self.first_pdf_page_count)
        return (
            self.page_offset
            - 1
            + (sequence_index + leading_positions) // int(self.pages_per_pdf)
        )

    def book_pages(self, pdf_index: int) -> tuple[int, ...]:
        """Return the logical book-page positions contained in a PDF page.

        Args:
            pdf_index: Zero-based PDF page index.

        Returns:
            One, two, or four logical page numbers; skips zero between the
            negative front-matter positions and positive body pages.
        """
        count = int(self.pages_per_pdf)
        first = (
            (pdf_index - self.page_offset + 1) * count
            - (count - int(self.first_pdf_page_count))
            + self.first_book_page - 1
        )
        return tuple(position + 1 if position >= 0 else position for position in range(first, first + count))


def parse_bookmark_line(
    bookmarkObj,
    page_mapping: _PageMapping,
) -> typing.Optional[typing.Tuple[int, int, str]]:
    """
    解析一行：
    例：'{"page": 1, "level": 1, "index": "", "title": "Preface"},'
    返回: (page_index, level, title)
    page 正整数为书的正常页码，负整数表示在第一页之前（如 -1 = 第一页的前一页），0 不允许。
    `index` 是可选的，经过字符串拼接 `index + " " + title` 形成目录项标题。
    """
    if not bookmarkObj:
        return None
    if not isinstance(bookmarkObj, dict):
        return None

    try:
        logical_page_raw = bookmarkObj.get('page')
        level_raw = bookmarkObj.get('level')
        if(logical_page_raw is not None and level_raw is not None):
            logical_page : int  = int(logical_page_raw)
            level : int = int(level_raw)
        else:
            return None
    except (TypeError, ValueError):
        return None

    if logical_page == 0 or level < 1:
        return None

    try:
        title : str = str(bookmarkObj.get('title', '')).strip() or ""
    except Exception:
        return None

    try:
        index : str = str(bookmarkObj.get('index', '')).strip() or ""
    except Exception:
        index = ""

    if index:
        title = f"{index} {title}"

    # 计算书页所在的 PDF 页码（0 基）
    page_index = page_mapping.pdf_index(logical_page)
    return (page_index, level, title)


class _BookmarkInputAction(enum.StrEnum):
    NEXT = "next"
    REENTER = "reenter"
    FINISH = "finish"
    QUIT = "quit"


class _BookmarkWriteMode(enum.StrEnum):
    REPLACE = "replace"
    APPEND = "append"


def _parse_bookmark_page(
    bookmarks_text: str,
    page_mapping: _PageMapping,
) -> Optional[list[dict[str, object]]]:
    """Parse one TOC image; return [] for empty input or None for invalid JSON."""
    if not bookmarks_text.strip():
        return []

    try:
        json_obj = json.loads(bookmarks_text)
    except json.JSONDecodeError as exc:
        print(f"{FLRed}Invalid JSON: {exc}{CRst}\n")
        return None

    if json_obj is None or (isinstance(json_obj, str) and not json_obj.strip()):
        return []
    if not isinstance(json_obj, list):
        print(f"{FLRed}Expected a JSON array.{CRst}\n")
        return None

    bookmarks: list[dict[str, object]] = []
    for position, item in enumerate(json_obj, start=1):
        if not isinstance(item, dict) or parse_bookmark_line(item, page_mapping) is None:
            print(f"{FLRed}Invalid bookmark at item {position}: {item}{CRst}\n")
            return None
        bookmarks.append(item)
    return bookmarks


def _bookmark_heading(bookmark: dict[str, object]) -> str:
    """Return one bookmark's combined index and title for a preview."""
    index = str(bookmark.get("index", "")).strip()
    title = str(bookmark.get("title", "")).strip()
    return f"{index} {title}".strip()


def _read_bookmark_pages(page_mapping: _PageMapping) -> Optional[list[dict[str, object]]]:
    """Read, validate, and merge one JSON array per TOC image."""
    bookmarks: list[dict[str, object]] = []
    image_number = 1
    pending_first_line = ""

    while True:
        print()
        bookmarks_text = Input.read_stdin_multiline(
            prompt_text=f"Paste JSON for TOC image [{image_number}]",
            split_lines=False,
        )
        if pending_first_line:
            bookmarks_text = f"{pending_first_line}\n{bookmarks_text}"
            pending_first_line = ""
        current_page = _parse_bookmark_page(bookmarks_text, page_mapping)
        if current_page is None:
            continue

        if current_page:
            print(f"\n{FLGreen}Accepted:{CRst} {len(current_page)} entries")
            print(f"{FLCyan}First:{CRst} {FGray}{_bookmark_heading(current_page[0])}{CRst}")
            print(f"{FLCyan}Last:{CRst}  {FGray}{_bookmark_heading(current_page[-1])}{CRst}\n")
        else:
            print(f"{FGray}No new entries. Previously collected: {len(bookmarks)}.{CRst}\n")

        print(f"{FGray}You can also paste the next JSON array starting with '[' here.{CRst}")
        while True:
            action = Menu.select(
                [
                    MenuOption(["N"], "Continue input / next image", _BookmarkInputAction.NEXT),
                    MenuOption(["R"], "Re-enter this image", _BookmarkInputAction.REENTER),
                    MenuOption(["F"], "Finish and merge", _BookmarkInputAction.FINISH),
                    MenuOption(["Q"], "Quit", _BookmarkInputAction.QUIT, FLRed),
                ],
                prompt="Choose",
                default_key="N",
                separator=False,
                accept_custom_string=True,
            )
            if isinstance(action, _BookmarkInputAction):
                break
            if isinstance(action, str) and action.startswith("["):
                pending_first_line = action
                action = _BookmarkInputAction.NEXT
                break
            print(f"{FLRed}Choose N, R, F, or Q, or paste a JSON array starting with '['.{CRst}\n")
        if action is _BookmarkInputAction.REENTER:
            continue
        if action is _BookmarkInputAction.QUIT:
            return None

        bookmarks.extend(current_page)
        if action is _BookmarkInputAction.FINISH:
            return bookmarks
        if current_page:
            image_number += 1


def _select_page_mapping() -> _PageMapping:
    """Prompt for the PDF page layout and return its logical-page mapping."""
    pages_per_pdf = typing.cast(
        _BookPagesPerPdf,
        Menu.select(
            [
                MenuOption(["1"], "Single book page per PDF page", _BookPagesPerPdf.SINGLE),
                MenuOption(["2"], "2 book pages per PDF page", _BookPagesPerPdf.TWO),
                MenuOption(["4"], "4 book pages per PDF page", _BookPagesPerPdf.FOUR),
            ],
            prompt="Book page layout",
            default_key="1",
            separator=False,
        ),
    )

    first_pdf_page_count = _FirstPdfPageCount.ONE
    if pages_per_pdf is not _BookPagesPerPdf.SINGLE:
        count_options: list[MenuOption] = []
        for count in _FirstPdfPageCount:
            if count.value > pages_per_pdf.value:
                break
            description = (
                "First book page only; remaining positions are blank or precede it"
                if count is _FirstPdfPageCount.ONE
                else f"First {count.value} book pages"
            )
            count_options.append(MenuOption([str(count.value)], description, count))

        first_pdf_page_count = typing.cast(
            _FirstPdfPageCount,
            Menu.select(
                count_options,
                prompt="Book pages starting with the first book page in its PDF page",
                default_key="1",
                separator=False,
            ),
        )

    page_offset = typing.cast(
        int,
        Input.input_number(
            "Enter the PDF page containing the first book page",
            default=DEFAULT_PAGE_OFFSET,
            min_value=1,
            allow_float=False,
        ),
    )
    first_book_page = typing.cast(
        int,
        Input.input_number(
            "Enter the page number of the first book page",
            default=DEFAULT_FIRST_BOOK_PAGE,
            min_value=1,
            allow_float=False,
        ),
    )
    page_mapping = _PageMapping(
        page_offset=page_offset,
        pages_per_pdf=pages_per_pdf,
        first_pdf_page_count=first_pdf_page_count,
        first_book_page=first_book_page,
    )

    print(f"\n{FLCyan}Page mapping preview:{CRst}")
    for logical_page in range(first_book_page, first_book_page + int(pages_per_pdf) + 1):
        pdf_page = page_mapping.pdf_index(logical_page) + 1
        print(
            f"  Book page {FLYellow}{logical_page}{CRst}"
            f" -> PDF page {FLGreen}{pdf_page}{CRst}"
        )
    return page_mapping


def _select_toc_pdf_page(page_mapping: _PageMapping) -> int:
    """Prompt for the first PDF page that contains the table of contents."""
    return typing.cast(
        int,
        Input.input_number(
            "Enter the first table-of-contents PDF page",
            default=max(DEFAULT_COVER_PDF_PAGE, page_mapping.page_offset - 1),
            min_value=DEFAULT_COVER_PDF_PAGE,
            max_value=page_mapping.page_offset,
            allow_float=False,
        ),
    )


def _add_bookmark(
    document: pymupdf.Document, title: str, page_index: int, parent: int | None = None,
) -> int:
    """Append a fit-page bookmark without rebuilding any existing outline items.

    Args:
        document: Open, authenticated PDF to modify in memory.
        title: Bookmark label, including Unicode characters.
        page_index: Valid zero-based target page index.
        parent: Parent outline xref, or None for a root-level bookmark.

    Returns:
        New outline xref, usable as a parent for subsequent entries.

    Existing destinations, actions, styles and expansion states are retained.
    """
    if parent is None:
        kind, reference = document.xref_get_key(document.pdf_catalog(), "Outlines")
        if kind == "xref":
            parent = int(reference.split()[0])
        else:
            parent = document.get_new_xref()
            document.update_object(parent, "<< /Type /Outlines /Count 0 >>")
            document.xref_set_key(document.pdf_catalog(), "Outlines", f"{parent} 0 R")

    kind, reference = document.xref_get_key(parent, "Last")
    previous = int(reference.split()[0]) if kind == "xref" else None
    xref = document.get_new_xref()
    page_xref = document.page_xref(page_index)
    document.update_object(
        xref, f"<< /Title {pymupdf.get_pdf_str(title)} /Parent {parent} 0 R "
        f"/Dest [{page_xref} 0 R /Fit] >>",
    )
    if previous is None:
        document.xref_set_key(parent, "First", f"{xref} 0 R")
    else:
        document.xref_set_key(previous, "Next", f"{xref} 0 R")
        document.xref_set_key(xref, "Prev", f"{previous} 0 R")
    document.xref_set_key(parent, "Last", f"{xref} 0 R")

    # A collapsed ancestor gains a hidden child but exposes no additional item
    # to its own parent. Open ancestors propagate the visible count upwards.
    ancestor = parent
    while ancestor:
        kind, value = document.xref_get_key(ancestor, "Count")
        count = int(value) if kind == "int" else 0
        document.xref_set_key(ancestor, "Count", str(count - 1 if count < 0 else count + 1))
        if count < 0:
            break
        kind, reference = document.xref_get_key(ancestor, "Parent")
        ancestor = int(reference.split()[0]) if kind == "xref" else 0
    return xref


def _write_bookmarks(
    document: pymupdf.Document,
    bookmark_objects: list[dict[str, object]],
    page_mapping: _PageMapping,
    toc_pdf_page: int,
    write_mode: _BookmarkWriteMode,
) -> None:
    """Add validated entries and the fixed cover/TOC entries to an open PDF.

    Replace detaches the old outline; append preserves its original dictionaries.
    Missing parent levels become roots, matching the original input behavior.
    Invalid target pages are reported and skipped. Changes stay in memory.
    """
    if write_mode is _BookmarkWriteMode.REPLACE:
        document.xref_set_key(document.pdf_catalog(), "Outlines", "null")
    for title, pdf_page in (
        (COVER_BOOKMARK_TITLE, DEFAULT_COVER_PDF_PAGE),
        (TOC_BOOKMARK_TITLE, toc_pdf_page),
    ):
        if 1 <= pdf_page <= document.page_count:
            _add_bookmark(document, title, pdf_page - 1)
        else:
            print(f"{FLYellow}Page {pdf_page} is out of range, skipping: {title}{CRst}")

    last_at_level: dict[int, int] = {}
    for bookmark in bookmark_objects:
        parsed = parse_bookmark_line(bookmark, page_mapping)
        if parsed is None:
            continue
        page_index, level, title = parsed
        if not 0 <= page_index < document.page_count:
            print(f"{FLYellow}Page {page_index + 1} is out of range, skipping: {title}{CRst}")
            continue
        last_at_level[level] = _add_bookmark(
            document, title, page_index, last_at_level.get(level - 1),
        )
        print(f"-> Page: {FLYellow}{page_index + 1}{CRst}, Level: {FLCyan}{level}{CRst}, Title: `{FLGreen}{title}{CRst}`")


def _reset_page_labels(
    document: pymupdf.Document,
    page_mapping: _PageMapping,
    toc_first_page: int,
    toc_last_page: int,
) -> None:
    """Generate TOC and body labels, preserving other labels and all page content.

    TOC bounds are inclusive, one-based physical PDF pages. TOC pages receive
    C1, C2, ...; body pages receive positive logical numbers/ranges. Remaining
    front matter keeps its original labels or physical numbering if unlabelled.

    Raises:
        ValueError: TOC bounds or the body anchor are outside the document.
    """
    if not 1 <= toc_first_page <= toc_last_page <= page_mapping.page_offset <= document.page_count:
        raise ValueError("TOC pages and the first book page must be ordered and inside the PDF.")
    labels = Pdf.read_page_labels(document)
    for index in range(document.page_count):
        physical_page = index + 1
        if toc_first_page <= physical_page <= toc_last_page:
            labels[index] = f"C{physical_page - toc_first_page + 1}"
        elif physical_page >= page_mapping.page_offset:
            pages = tuple(page for page in page_mapping.book_pages(index) if page >= page_mapping.first_book_page)
            labels[index] = Input.format_integer_ranges(Input.merge_integer_ranges(pages))
    Pdf.write_page_labels(document, labels)


def main() -> int:
    Console.print_banner("PDF BOOKMARK INSERTING TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
PDF BOOKMARK INSERTING TOOL
===========================

Usage:
  python {script_name} <input.pdf>                     specify input PDF, output interactive
  python {script_name} <input.pdf> -o <output.pdf>     specify both input and output
  python {script_name} --help                          show this help

{FLYellow}Arguments:{CRst}
  <input.pdf>          input PDF file path
  -o, --output <path>  output PDF file path
  -h, --help          show this help

{FLYellow}Description:{CRst}
  Add table-of-contents bookmarks to scanned PDF books:
  Send one TOC screenshot at a time to a vision LLM (e.g. Qwen3-VL), then paste
  each page's JSON array separately. The arrays are validated and merged in
  image order before the bookmarks are written into the PDF.
  At the action menu, pasting JSON starting with '[' automatically continues
  input and retains the first line. End the paste with EOF as usual.
  Before writing, choose Replace (default) to rewrite the outline or Append to preserve
  existing bookmarks and add the new entries after them.
  Blank input, empty JSON strings/arrays, and null return to the action menu;
  earlier entries are retained. Finishing with no entries writes no PDF.
  Supports PDF pages containing 1, 2, or 4 consecutive physical book pages.
  Enter the PDF page containing the first book page, then its printed page number
  (default 1). Example: PDF page 17 corresponds to book page 20.
  Both bookmark write modes add root-level Cover and Table of Contents bookmarks.
  Reset page labels? defaults to Y, generating labels from the book-page mapping.
  Choose N to preserve existing labels. This does not change printed page content.
  For Y, confirm the last TOC PDF page (default: the page before the first book page).
  TOC labels use C1, C2, ...; other front-matter labels remain unchanged.
  With no existing labels, front matter keeps physical PDF page numbers.
  Body pages use book numbers or ranges for 2/4-up layouts.
  The first body label starts at the chosen first book-page number.
  TOC labels take priority if the TOC and body start on the same PDF page.
  Use pdf-page-tag.py for standalone label editing and clearing.
  Saves an unencrypted new file, preserving document metadata and attachments.
  Automatically removes PDF/A identification while retaining other metadata.
  Opening passwords are requested without echo; existing files are not overwritten.
  `page` supports negative numbers: -1 = the page before page 1, -2 = two pages before page 1, etc.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install PyMuPDF{CRst}
""")
        return 0



    #============ 命令行参数解析 ===========
    _arg_path: Optional[str] = None
    _arg_output: Optional[str] = None
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "-o" or arg == "--output":
            i += 1
            if i < len(sys.argv):
                _arg_output = sys.argv[i]
        elif not arg.startswith("-"):
            _arg_path = arg
        i += 1


    #============ 默认路径 (OS-aware) ===========
    if sys.platform == "win32":
        DEFAULT_INPUT = "D:/input.pdf"
    else:
        DEFAULT_INPUT = os.path.expanduser("~/input.pdf")


    #============ 用户交互 ===========
    filepath = _arg_path if _arg_path else Input.resolve_input_path(
        DEFAULT_INPUT,
        prompt="Enter input PDF file path",
        path_type="file",
    )

    if not filepath or not os.path.exists(filepath):
        print(f"{FLRed}Invalid input file path. EXIT...{CRst}\n")
        return 1

    _stem, _ext = os.path.splitext(os.path.basename(filepath))
    _default_output = os.path.join(os.path.dirname(filepath) or ".", f"{_stem}_bookmarked{_ext or '.pdf'}")

    output_path = Input.resolve_output_path(
        _arg_output if _arg_output else _default_output,
        prompt="Enter output PDF file path",
        path_type="file",
    )

    page_mapping = _select_page_mapping()
    toc_pdf_page = _select_toc_pdf_page(page_mapping)

    # 逐页读取并合并目录 JSON
    text_prompt = """[
{"page": -1, "level": 1, "index": "", "title": "Foreword"},
{"page": 1, "level": 1, "index": "", "title": "Preface"},
{"page": 3, "level": 1, "index": "Chapter 1", "title": "Subject Overview"},
{"page": 3, "level": 2, "index": "1.1", "title": "History"}
]"""
    print(f"{FLYellow}Enter one JSON array for each TOC image.{CRst}")
    print(f"{FGray}Paste only the JSON, without Markdown fences or the model warning.{CRst}")
    print(f"{FLCyan}Example format:{CRst}\n{FLMagenta}{text_prompt}{CRst}\n")
    bookmark_objects = _read_bookmark_pages(page_mapping)
    if bookmark_objects is None:
        Console.print_exit_message("Bye.")
        return 0
    if not bookmark_objects:
        Console.print_exit_message("No bookmarks collected. No PDF written.")
        return 0
    print(f"\n{FLGreen}Merged:{CRst} {len(bookmark_objects)} entries")

    # ── authenticate and update the original document in memory ──
    try:
        with Pdf.open_document(filepath) as (document, _):
            print(f"{FLGreen}PDF loaded successfully. Total pages: {document.page_count}{CRst}\n")
            write_mode = typing.cast(
                _BookmarkWriteMode,
                Menu.select(
                    [
                        MenuOption(["R"], "Replace existing bookmarks", _BookmarkWriteMode.REPLACE),
                        MenuOption(["A"], "Append to existing bookmarks", _BookmarkWriteMode.APPEND),
                    ],
                    prompt="Bookmark write mode", required=True, default_key="R", separator=False,
                ),
            )
            reset_labels = Menu.select(
                [
                    MenuOption(["Y", "YES"], "Generate body and TOC labels", True),
                    MenuOption(["N", "NO"], "Keep existing page labels", False),
                ],
                prompt="Reset page labels?", required=True, default_key="Y",
                inline=True, separator=False,
            )
            _write_bookmarks(document, bookmark_objects, page_mapping, toc_pdf_page, write_mode)
            if reset_labels:
                if not 1 <= toc_pdf_page <= page_mapping.page_offset <= document.page_count:
                    raise ValueError("The TOC and first book page must be inside the PDF to reset labels.")
                toc_last_page = max(toc_pdf_page, page_mapping.page_offset - 1)
                if toc_pdf_page < page_mapping.page_offset:
                    toc_last_page = typing.cast(
                        int,
                        Input.input_number(
                            "Enter the last table-of-contents PDF page",
                            default=page_mapping.page_offset - 1,
                            min_value=toc_pdf_page, max_value=page_mapping.page_offset - 1,
                            allow_float=False,
                        ),
                    )
                _reset_page_labels(document, page_mapping, toc_pdf_page, toc_last_page)
                print(f"{FLGreen}Page labels reset.{CRst}")
            Pdf.save_new(document, output_path)
    except (OSError, ValueError, RuntimeError, pymupdf.FileDataError, FzErrorBase) as exc:
        print(f"{FLRed}PDF update failed: {exc}{CRst}\n")
        return 1

    print(f"{FLGreen}Updated PDF saved to:{CRst} {FLBlue}{output_path}{CRst}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
