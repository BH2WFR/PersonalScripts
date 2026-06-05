# 对有密码保护的 PDF 进行解密，含能打开但不能编辑/打印的权限保护
from utils import *
import pypdf # pip install pypdf

# 对有密码保护的 PDF 进行解密，含能打开但不能编辑/打印的权限保护



print(f"{FLYellow}=========== PDF DECRYPTING TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
PDF DECRYPTING TOOL
===================

Usage:
  python {script_name} <input.pdf>                     specify input PDF, output interactive
  python {script_name} <input.pdf> -o <output.pdf>     specify both input and output
  python {script_name} --help                          show this help

{FLYellow}Arguments:{CRst}
  <input.pdf>          input PDF file path
  -o, --output <path>  output PDF file path

{FLYellow}Description:{CRst}
  Decrypt password-protected PDFs (including permission-only protection).
  Clones the full document structure (pages, bookmarks, named destinations)
  and outputs a completely decrypted PDF.

{FLYellow}Requirements:{CRst}
  Python: {FGray}pip install pypdf{CRst}
""")
    sys.exit(0)


#============ 命令行参数解析 ===========
_arg_path: str | None = None
_arg_output: str | None = None
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
    sys.exit(1)

# 默认输出路径：输入文件名 + _decrypted 后缀
_stem, _ext = os.path.splitext(os.path.basename(filepath))
_default_output = os.path.join(os.path.dirname(filepath) or ".", f"{_stem}_decrypted{_ext or '.pdf'}")

output_path = Input.resolve_output_path(
    _arg_output if _arg_output else _default_output,
    prompt="Enter output PDF file path",
    path_type="file",
)

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
				sys.exit(1)
			res = reader.decrypt(password) # 解密
			if res == 0:
				print(f"{FLRed}Incorrect password. pls input again.{CRst}")
				continue
			else:
				print(f"{FLGreen}PDF decrypted successfully.{CRst}\n")
				break
	# end while
else:
	print(f"{FLYellow}[WARNING]: The PDF is not encrypted. Proceeding to copy as is.{CRst}")
# if encrypted

pages_cnt = len(reader.pages)
print(f"{FLGreen}PDF loaded successfully. Total pages: {pages_cnt}{CRst}")

# 直接克隆整个文档结构（包括页面、书签、命名目标等）
writer = pypdf.PdfWriter()
print("  -> cloning document (pages + outline + structure)...")
writer.clone_reader_document_root(reader)

# 不调用 writer.encrypt(...)，因此输出是完全解密的
print("  -> writing to output file...")
with open(output_path, "wb") as out_f:
	writer.write(out_f)

# 结束
print(f"{FLGreen}Decrypted PDF saved to: {output_path}{CRst}\n")
