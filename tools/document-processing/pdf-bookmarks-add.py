#!/usr/bin/env python3
# 给 PDF 书籍添加目录书签（Bookmark/Outline）
# 逐页接收大模型生成的目录 JSON，合并后写入 PDF
#
#
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

import pypdf # pip install pypdf
from typing import Optional


#============ LLM prompt ===========
# Model: Qwen3-VL-235B-A22B-Instruct or similar vision model
# Prompt:
"""
You are a tool that converts exactly one table-of-contents PDF page from a scanned book into JSON.

The input must contain exactly one image showing exactly one PDF page. That PDF page may contain 1, 2, or 4 physical book pages; transcribe all visible table-of-contents entries on it. If the input contains multiple images or more than one PDF page, output only the following warning and stop without producing JSON:

WARNING: Multiple TOC PDF pages detected. Please submit exactly one PDF page at a time.

Transcribe every visible table-of-contents entry from top to bottom. Do not summarize, omit entries, add placeholders, or invent titles and page numbers that are not visible in the image.

The script adds the root-level "Cover" and "Table of Contents" bookmarks separately. Do not invent them in the JSON; include either title only if it is visibly printed as a table-of-contents entry.

The first visible entry may continue a section from the preceding page and is very likely not a level-1 heading. Determine its actual level from its numbering, indentation, typography, surrounding entries, and any preceding-page context available. Do not reset the hierarchy at the start of each image.

Output one valid JSON array in the following format. Put each complete table-of-contents entry on one physical line:

```json
[
{"page": 10, "level": 3, "index": "1.2.1", "title": "Politics"},
{"page": 12, "level": 3, "index": "1.2.2", "title": "State"},
{"page": 14, "level": 3, "index": "1.2.3", "title": "Government"},
{"page": 16, "level": 2, "index": "1.3", "title": "Research Methods"},
{"page": 16, "level": 3, "index": "1.3.1", "title": "Qualitative Analysis"},
{"page": 18, "level": 3, "index": "1.3.2", "title": "Quantitative Analysis"},
{"page": 20, "level": 1, "index": "Chapter 2", "title": "Camera Calibration and Imaging Model"}
]
```

The JSON must not contain comments, trailing commas, or explanatory objects. The `page` and `level` fields are required. `page` supports negative numbers (-1 = one page before page 1, -2 = two pages before page 1, and so on). `index` is optional; `index` and `title` are concatenated with a space to form the bookmark heading.

If the book has a preface (p0), references, or afterword, include them as level-1 chapter headings.
If the book has "parts" or "sections" above the chapter level, treat them as level 1, chapters as level 2, sub-sections as level 3, and so on.

If the book has no chapter or section numbers, leave `index` as an empty string.

After the JSON array, output this warning outside the JSON code block:

WARNING: Vision models can omit entries, attach the wrong page number, or mix content between rows. Carefully compare every item with the source image. Submit the next TOC page only after this page has been fully verified and corrected.
"""


#* 全局变量
DEFAULT_PAGE_OFFSET = 10
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
        page_offset: One-based PDF page containing logical book page 1.
        pages_per_pdf: Fixed number of physical book-page positions per PDF page.
        first_pdf_page_count: Positive book pages beginning at page 1 that share
            the anchor PDF page.
    """

    page_offset: int
    pages_per_pdf: _BookPagesPerPdf
    first_pdf_page_count: _FirstPdfPageCount

    def pdf_index(self, logical_page: int) -> int:
        """Return the zero-based PDF index containing a logical book page.

        Args:
            logical_page: Non-zero printed or inferred book page number. Negative
                values count physical positions immediately preceding page 1.

        Returns:
            Zero-based index of the PDF page containing ``logical_page``.
        """
        sequence_index = logical_page - 1 if logical_page > 0 else logical_page
        leading_positions = int(self.pages_per_pdf) - int(self.first_pdf_page_count)
        return (
            self.page_offset
            - 1
            + (sequence_index + leading_positions) // int(self.pages_per_pdf)
        )


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


def _parse_bookmark_page(
    bookmarks_text: str,
    page_mapping: _PageMapping,
) -> Optional[list[dict[str, object]]]:
    """Parse and validate one TOC image's JSON array."""
    try:
        json_obj = json.loads(bookmarks_text)
    except json.JSONDecodeError as exc:
        print(f"{FLRed}Invalid JSON: {exc}{CRst}\n")
        return None

    if not isinstance(json_obj, list) or not json_obj:
        print(f"{FLRed}Expected a non-empty JSON array.{CRst}\n")
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

    while True:
        print()
        bookmarks_text = Input.read_stdin_multiline(
            prompt_text=f"Paste JSON for TOC image [{image_number}]",
            split_lines=False,
        )
        if not bookmarks_text:
            continue

        current_page = _parse_bookmark_page(bookmarks_text, page_mapping)
        if current_page is None:
            continue

        print(f"\n{FLGreen}Accepted:{CRst} {len(current_page)} entries")
        print(f"{FLCyan}First:{CRst} {FGray}{_bookmark_heading(current_page[0])}{CRst}")
        print(f"{FLCyan}Last:{CRst}  {FGray}{_bookmark_heading(current_page[-1])}{CRst}\n")

        action = Menu.select(
            [
                MenuOption(["N"], "Next image", _BookmarkInputAction.NEXT),
                MenuOption(["R"], "Re-enter this image", _BookmarkInputAction.REENTER),
                MenuOption(["F"], "Finish and merge", _BookmarkInputAction.FINISH),
                MenuOption(["Q"], "Quit", _BookmarkInputAction.QUIT, FLRed),
            ],
            prompt="Choose",
            default_key="N",
            separator=False,
        )
        if action is _BookmarkInputAction.REENTER:
            continue
        if action is _BookmarkInputAction.QUIT:
            return None

        bookmarks.extend(current_page)
        if action is _BookmarkInputAction.FINISH:
            return bookmarks
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
                "Book page 1 only; remaining positions are blank or precede page 1"
                if count is _FirstPdfPageCount.ONE
                else f"Book pages 1-{count.value}"
            )
            count_options.append(MenuOption([str(count.value)], description, count))

        first_pdf_page_count = typing.cast(
            _FirstPdfPageCount,
            Menu.select(
                count_options,
                prompt="Book pages starting at 1 in its first PDF page",
                default_key="1",
                separator=False,
            ),
        )

    page_offset = typing.cast(
        int,
        Input.input_number(
            "Enter the PDF page containing book page 1",
            default=DEFAULT_PAGE_OFFSET,
            min_value=1,
            allow_float=False,
        ),
    )
    page_mapping = _PageMapping(
        page_offset=page_offset,
        pages_per_pdf=pages_per_pdf,
        first_pdf_page_count=first_pdf_page_count,
    )

    print(f"\n{FLCyan}Page mapping preview:{CRst}")
    for logical_page in range(1, int(pages_per_pdf) + 2):
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

{FLYellow}Description:{CRst}
  Add table-of-contents bookmarks to scanned PDF books.
  Send one TOC screenshot at a time to a vision LLM (e.g. Qwen3-VL), then paste
  each page's JSON array separately. The arrays are validated and merged in
  image order before the bookmarks are written into the PDF.
  Supports PDF pages containing 1, 2, or 4 consecutive physical book pages.
  Adds root-level Cover and Table of Contents bookmarks automatically.
  `page` supports negative numbers: -1 = the page before page 1, -2 = two pages before page 1, etc.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install pypdf{CRst}
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

    # 默认输出路径：输入文件名 + _bookmarked 后缀
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
    print(f"\n{FLGreen}Merged:{CRst} {len(bookmark_objects)} entries")

    #============ 代码主体部分 ===========
    reader = pypdf.PdfReader(filepath)
    # 判断是否加密
    if reader.is_encrypted:
        while(1):
            try:
                print("trying to decrypt...")
                _ = reader.pages[0] # 确认能不能读取
                break
            except Exception:
                print(f"{FLYellow}The PDF requires a password to open.{CRst} input password, or press (ctrl+c) to exit: ")
                password = input() #.strip()
                if not password:
                    print(f"{FLRed}No password provided. EXIT...{CRst}\n")
                    return 1
                res = reader.decrypt(password) # 解密
                if res == 0:
                    print(f"{FLRed}Incorrect password. pls input again.{CRst}")
                    continue
                else:
                    print(f"{FLGreen}PDF decrypted successfully.{CRst}\n")
                    break
        # end while
    # encrypted

    pages_cnt = len(reader.pages)
    print(f"{FLGreen}PDF loaded successfully. Total pages: {pages_cnt}{CRst}\n")

    # 逐页拷贝，生成新文档, 为了解决文档已有目录，或文档编辑权限被加密的情况
    writer = pypdf.PdfWriter()
    try:
        for page in reader.pages: # 页面内容
            writer.add_page(page)
        if reader.metadata: # 元数据
            writer.add_metadata(reader.metadata)
    except Exception as e:
        print(f"{FLRed}ERROR while copying pages and metadata: {str(e)}{CRst}\n")
        pass

    # 固定的顶级书签不参与正文目录的父子层级计算
    for title, pdf_page in (
        (COVER_BOOKMARK_TITLE, DEFAULT_COVER_PDF_PAGE),
        (TOC_BOOKMARK_TITLE, toc_pdf_page),
    ):
        page_index = pdf_page - 1
        if page_index >= len(writer.pages):
            print(f"{FLRed}[WARNING]: Page {pdf_page}, level 1 is out of range, skip: `{title}`{CRst}")
            continue
        writer.add_outline_item(title, page_number=page_index)
        print(f"-> Page: {FLYellow}{pdf_page}{CRst}, Level: {FLCyan}1{CRst}, Title: `{FLGreen}{title}{CRst}`")

    # 动态数组，当前每一级最后一个书签对象，用于作为子书签的 parent
    last_at_level = {}

    # 一项一项写入合并后的书签
    for bookmarkObj in bookmark_objects:
        #* 解析书签对象
        parsed = parse_bookmark_line(bookmarkObj, page_mapping)
        if not parsed:
            print(f"{FLRed}[WARNING]: bookmark json object parsing error, skipping: {bookmarkObj}{CRst}")
            continue
        page_index, level, title = parsed

        # 获取父书签（上一级）
        parent = last_at_level.get(level - 1)

        # 创建书签
        # 注意 page_index 要在范围内
        if (page_index >= len(writer.pages) or page_index < 0):
            print(f"{FLRed}[WARNING]: Page {page_index+1}, level {level} is out of range, skip: `{title}`{CRst}")
        else:
            bm = writer.add_outline_item(title, page_number=page_index, parent=parent)
            print(f"-> Page: {FLYellow}{page_index+1}{CRst}, Level: {FLCyan}{level}{CRst}, Title: `{FLGreen}{title}{CRst}`")
            last_at_level[level] = bm # 记录该层级最近的书签
        # endif
    # end for lines

    with open(output_path, "wb") as out_f:
        writer.write(out_f)

    print(f"{FLGreen}Bookmarked PDF saved to:{CRst} {FLBlue}{output_path}{CRst}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
