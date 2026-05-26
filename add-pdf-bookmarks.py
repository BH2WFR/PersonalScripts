from my_utils import *
import pypdf # pip install pypdf


print(f"{FLYellow}=========== PDF BOOKMARK INSERTING TOOL ==========={CRst}")


#============ 大模型提示词 ===========
# 模型： Qwen3-VL-235B-A22B-Instruct 或类似的 多模态模型
# 提示词：
"""
你是一个将扫描版 pdf 书籍的目录部分转换为字符串的工具，我传入书籍目录图片，你分析标题、页码和层级后转换以下格式：

```json
[
	{"page": 1, "level": 1, "index": "", "title": "前言"},
	{"page": 3, "level": 1, "index": "第一章", "title": "学科概述"},
	{"page": 3, "level": 2, "index": "1.1", "title": "发展历史"},
	{"page": 3, "level": 3, "index": "1.1.1", "title": "1920-1950: 萌芽期"},
	{"page": 7, "level": 3, "index": "1.1.2", "title": "1950-2000: 成长期"},
	{"page": 8, "level": 3, "index": "1.1.3", "title": "2000-至今: 成熟期"},
	{"page": 10, "level": 2, "index": "1.2", "title": "基本概念"},
	{"page": 10, "level": 3, "index": "1.2.1", "title": "政治"},
	{"page": 12, "level": 3, "index": "1.2.2", "title": "国家"},
	{"page": 14, "level": 3, "index": "1.2.3", "title": "政府"},
	{"page": 16, "level": 2, "index": "1.3", "title": "研究方法"},
	{"page": 16, "level": 3, "index": "1.3.1", "title": "定性分析"},
	{"page": 18, "level": 3, "index": "1.3.2", "title": "定量分析"},
	{"page": 20, "level": 1, "index": "第二章", "title": "相机标定参数及相机成像模型"},
	{"page": 20, "level": 2, "index": "2.1", "title": "相机标定参数"},
	{"page": 20, "level": 3, "index": "2.1.1", "title": "内参"},
	{"page": 22, "level": 3, "index": "2.1.2", "title": "外参"},
	{"page": 24, "level": 2, "index": "2.2", "title": "相机成像模型"},
	{"page": 24, "level": 3, "index": "2.2.1", "title": "针孔模型"},
	{"page": 26, "level": 3, "index": "2.2.2", "title": "畸变模型"}
	{"page": 28, "level": 2, "index": "2.3", "title": "相机标定方法概述"},
	{"page": 30, "level": 1, "index": "第三章", "title": "图像处理基础"},
	{"_以下省略": "使用标准 json 格式。page 为页码，level 为层级，index和title共同构成目录项标题"},
	{"page": 100, "level": 1, "index": "", "title": "后记"},
	{"page": 102, "level": 1, "index": "", "title": "参考文献"},
]
```

需要严格按照这种格式输出，不得带有注释，因为需要用 python 脚本读取。`page` 和 `level` 项是必须的，`index` 是可选项，`index` 与 `title` 经过字符串拼接共同构成目录项的标题。

如果书籍中有绪论（p0)、参考文献和后记，则要求作为 level 1 的章节标题写入。
如果书中有超过章节的「大分类」，则将「大分类」作为章节（level 1），「章节」作为小节（level2），「小节」类推 level 加 1。

如果书籍中没有章节号或小节号，则 `index` 保持为空。
"""


#============ 用户交互 ===========
filepath = "D:/input.pdf"
output_path = "D:/input_bookmarked.pdf"
page_offset = 10 # pdf 第十页是 书的 第一页, 则写为 10
bookmarks_text = "" # 按行分隔，格式见上方提示词

filepath = input(f"{FLYellow}Enter input PDF file path (default: {filepath}): {CRst}")
if(not filepath or os.path.exists(filepath) == False):
	print(f"{FLRed}Invalid input file path. EXIT...{CRst}\n")
	sys.exit(1)
output_path = input(f"{FLYellow}Enter output PDF file path (default: {output_path}): {CRst}") or output_path
out_dir = os.path.dirname(output_path) or "."
if(not output_path or os.path.exists(out_dir) == False):
	print(f"{FLRed}Invalid or unexisting output file path. EXIT...{CRst}\n")
	sys.exit(1)
if(os.path.exists(output_path)):
	print(f"{FLRed}Output file already exists. EXIT...{CRst}\n")
	sys.exit(1)
page_offset_str = input(f"{FLYellow}Enter page offset (default: {page_offset}): {FLCyan}(it means page N of the pdf is the first page of the book) {CRst}\n") or str(page_offset)
try:
	page_offset = int(page_offset_str)
	if(page_offset < 1):
		raise ValueError("Page offset must be >= 1")
except ValueError:
	print(f"{FLRed}Invalid page offset. EXIT...{CRst}\n")
	sys.exit(1)

# 多行文本的输入
text_prompt = """
[
	{"page": 1, "level": 1, "index": "", "title": "前言"},
	{"page": 3, "level": 1, "index": "第一章", "title": "学科概述"},
	{"page": 3, "level": 2, "index": "1.1", "title": "发展历史"},
	{"page": 3, "level": 3, "index": "1.1.1", "title": "1920-1950: 萌芽期"},
	{"page": 7, "level": 3, "index": "1.1.2", "title": "1950-2000: 成长期"},
	{"page": 20, "level": 1, "index": "第二章", "title": "相机标定参数及相机成像模型"},
	{"page": 20, "level": 2, "index": "2.1", "title": "相机标定参数"},
	{"page": 102, "level": 1, "index": "", "title": "参考文献"},
]
"""
print(f"{FLYellow}Enter bookmarks text in Json. {CRst}")
print(f"{FLCyan}End with a `EOF`, Windows: {FLYellow}Enter->Ctrl+Z{FLCyan}; Linux: {FLYellow}Enter->Ctrl+D{FLCyan}):{CRst}")
print(f"{FLCyan}Example format:{CRst}\n{FLMagenta}{text_prompt}{CRst}\n")
bookmarks_text = sys.stdin.read()
if(not bookmarks_text.strip()):
	print(f"{FLRed}No bookmarks text provided. EXIT...{CRst}\n")
	sys.exit(1)

print(f"{FLYellow}  -> start parsing...")

#============ 代码主体部分 ===========


def parse_bookmark_line(bookmarkObj: typing.Any) -> typing.Optional[typing.Tuple[int, int, str]]:
	"""
	解析一行：
	例：'{"page": 1, "level": 1, "index": "", "title": "前言"},'
	返回: (page, level, title)
	注意：输入项目中，`index` 是可选的，经过字符串拼接 `index + " " + title` 形成目录项标题, 作为返回 tuple 中的 title 部分。
	"""
	if not bookmarkObj:
		return None
	if not isinstance(bookmarkObj, dict):
		return None
	# 例如：{"page": 3, "level": 2, "index": "1.1", "title": "发展历史"},
	
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
	
	if logical_page < 1 or level < 1:
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


if(__name__ == "__main__"): # 添加书签
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
					sys.exit(1)
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
			# md = dict(reader.metadata)
			# md = {str(k): "" if v is None else str(v) for k, v in md.items()}
			# writer.add_metadata(md)
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
		sys.exit(1)
	
	if not isinstance(jsonObj, list):
		print(f"{FLRed}Invalid bookmarks json object. Expected a JSON array.{CRst}\n")
		sys.exit(1)
	
	for bookmarkObj in jsonObj:
		if not isinstance(bookmarkObj, dict):
			print(f"{FLRed}[WARNING]: Invalid bookmark json object, skipping: {bookmarkObj}{CRst}")
			continue
		
		#* 解析书签对象
		parsed = parse_bookmark_line(bookmarkObj)
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
