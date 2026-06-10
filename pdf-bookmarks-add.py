# 给 PDF 书籍添加目录书签（Bookmark/Outline）
# 从大模型获取目录 JSON 后，写入到 PDF 中
#
#
import sys
from utils import *
import pypdf # pip install pypdf
from typing import Optional


def parse_bookmark_line(bookmarkObj, page_offset: int) -> typing.Optional[typing.Tuple[int, int, str]]:
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

    # 计算在 PDF 中的页码（0 基）: pdf 第 page_offset 页为书的第 1 页
    page_index = logical_page + page_offset - 2
    return (page_index, level, title)


def main() -> int:
    Utils.print_banner("PDF BOOKMARK INSERTING TOOL")

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
  Add table-of-contents bookmarks to PDF books.
  Reads JSON outline (page/level/index/title format) from an LLM and writes it into the PDF.
  `page` supports negative numbers: -1 = the page before page 1, -2 = two pages before page 1, etc.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install pypdf{CRst}
""")
        return 0


    #============ LLM prompt ===========
    # Model: Qwen3-VL-235B-A22B-Instruct or similar multimodal model
    # Prompt:
    """
    You are a tool that converts the table of contents section of a scanned PDF book into a JSON string. I will provide images of the book's table of contents; you analyze the titles, page numbers, and hierarchy levels, then output in the following format:

    ```json
    [
        {"page": -2, "level": 1, "index": "", "title": "Index"},
        {"page": 1, "level": 1, "index": "", "title": "Preface"},
        {"page": 3, "level": 1, "index": "Chapter 1", "title": "Subject Overview"},
        {"page": 3, "level": 2, "index": "1.1", "title": "History"},
        {"page": 3, "level": 3, "index": "1.1.1", "title": "1920-1950: Early Period"},
        {"page": 7, "level": 3, "index": "1.1.2", "title": "1950-2000: Growth Period"},
        {"page": 8, "level": 3, "index": "1.1.3", "title": "2000-Present: Maturity"},
        {"page": 10, "level": 2, "index": "1.2", "title": "Basic Concepts"},
        {"page": 10, "level": 3, "index": "1.2.1", "title": "Politics"},
        {"page": 12, "level": 3, "index": "1.2.2", "title": "State"},
        {"page": 14, "level": 3, "index": "1.2.3", "title": "Government"},
        {"page": 16, "level": 2, "index": "1.3", "title": "Research Methods"},
        {"page": 16, "level": 3, "index": "1.3.1", "title": "Qualitative Analysis"},
        {"page": 18, "level": 3, "index": "1.3.2", "title": "Quantitative Analysis"},
        {"page": 20, "level": 1, "index": "Chapter 2", "title": "Camera Calibration and Imaging Model"},
        {"page": 20, "level": 2, "index": "2.1", "title": "Calibration Parameters"},
        {"page": 20, "level": 3, "index": "2.1.1", "title": "Intrinsic Parameters"},
        {"page": 22, "level": 3, "index": "2.1.2", "title": "Extrinsic Parameters"},
        {"page": 24, "level": 2, "index": "2.2", "title": "Camera Imaging Model"},
        {"page": 24, "level": 3, "index": "2.2.1", "title": "Pinhole Model"},
        {"page": 26, "level": 3, "index": "2.2.2", "title": "Distortion Model"}
        {"page": 28, "level": 2, "index": "2.3", "title": "Overview of Camera Calibration Methods"},
        {"page": 30, "level": 1, "index": "Chapter 3", "title": "Image Processing Basics"},
        {"_omitted below": "Use standard JSON format. page = page number (supports negative: -1 = before page 1), level = hierarchy depth, index and title together form the bookmark heading"},
        {"page": 100, "level": 1, "index": "", "title": "Afterword"},
        {"page": 102, "level": 1, "index": "", "title": "References"},
    ]
    ```

    You must output strictly in this format without any comments, as the output will be parsed by a Python script. The `page` and `level` fields are required. `page` supports negative numbers (-1 = one page before page 1, -2 = two pages before page 1, and so on). `index` is optional; `index` and `title` are concatenated with a space to form the bookmark heading.

    If the book has a preface (p0), references, or afterword, include them as level-1 chapter headings.
    If the book has "parts" or "sections" above the chapter level, treat them as level 1, chapters as level 2, sub-sections as level 3, and so on.

    If the book has no chapter or section numbers, leave `index` as an empty string.
    """


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

    page_offset = 10 # pdf 第十页是 书的 第一页, 则写为 10
    bookmarks_text = "" # 按行分隔，格式见上方提示词
    page_offset_str = input(f"{FLYellow}Enter page offset (default: {page_offset}): {FLCyan}(it means page N of the pdf is the first page of the book) {CRst}\n") or str(page_offset)
    try:
        page_offset = int(page_offset_str)
        if(page_offset < 1):
            raise ValueError("Page offset must be >= 1")
    except ValueError:
        print(f"{FLRed}Invalid page offset. EXIT...{CRst}\n")
        return 1

    # 多行文本的输入
    text_prompt = """
    [
        {"page": -1, "level": 1, "index": "", "title": "封面"},
        {"page": 1, "level": 1, "index": "", "title": "Preface"},
        {"page": 3, "level": 1, "index": "Chapter 1", "title": "Subject Overview"},
        {"page": 3, "level": 2, "index": "1.1", "title": "History"},
        {"page": 3, "level": 3, "index": "1.1.1", "title": "1920-1950: Early Period"},
        {"page": 7, "level": 3, "index": "1.1.2", "title": "1950-2000: Growth Period"},
        {"page": 20, "level": 1, "index": "Chapter 2", "title": "Camera Calibration and Imaging Model"},
        {"page": 20, "level": 2, "index": "2.1", "title": "Calibration Parameters"},
        {"page": 102, "level": 1, "index": "", "title": "References"},
    ]
    """
    print(f"{FLYellow}Enter bookmarks text in Json. {CRst}")
    print(f"{FLCyan}Example format:{CRst}\n{FLMagenta}{text_prompt}{CRst}\n")
    bookmarks_text = Input.read_stdin_multiline(
        prompt_text="Paste the JSON bookmark data",
        split_lines=False,
    )
    if not bookmarks_text:
        print(f"{FLRed}No input provided. EXIT...{CRst}")
        return 1

    print(f"{FLYellow}  -> start parsing...")

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

    # 动态数组，当前每一级最后一个书签对象，用于作为子书签的 parent
    last_at_level = {}

    # 一项一项解析 json 对象中的书签信息
    try:
        jsonObj = json.loads(bookmarks_text)
    except json.JSONDecodeError as e:
        print(f"{FLRed}Failed to parse bookmarks text as JSON: {str(e)}{CRst}\n")
        return 1

    if not isinstance(jsonObj, list):
        print(f"{FLRed}Invalid bookmarks json object. Expected a JSON array.{CRst}\n")
        return 1

    for bookmarkObj in jsonObj:
        if not isinstance(bookmarkObj, dict):
            print(f"{FLRed}[WARNING]: Invalid bookmark json object, skipping: {bookmarkObj}{CRst}")
            continue

        #* 解析书签对象
        parsed = parse_bookmark_line(bookmarkObj, page_offset)
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
    raise sys.exit(main())
