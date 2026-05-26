# 对有密码保护的 PDF 进行解密，含能打开但不能编辑/打印的权限保护
from my_utils import *
import pypdf # pip install pypdf

# 对有密码保护的 PDF 进行解密，含能打开但不能编辑/打印的权限保护



print(f"{FLYellow}=========== PDF DECRYPTING TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
PDF DECRYPTING TOOL
===================

Usage:
  python {script_name} <input.pdf>                     指定输入 PDF，输出交互
  python {script_name} <input.pdf> -o <output.pdf>     指定输入和输出
  python {script_name} --help                          显示此帮助

参数说明：
  <input.pdf>          输入的 PDF 文件路径
  -o, --output <path>  输出的 PDF 文件路径

功能：
  对有密码保护的 PDF 进行解密，含能打开但不能编辑/打印的权限保护。
  克隆整个文档结构（页面、书签、命名目标等），输出完全解密的 PDF。
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


#============ 用户交互 ===========
filepath = "D:/input.pdf"
output_path = "D:/input_bookmarked.pdf"

if _arg_path:
    filepath = _arg_path
else:
    filepath = input(f"{FLYellow}Enter input PDF file path (default: {filepath}): {CRst}") or filepath

if not filepath or os.path.exists(filepath) == False:
	print(f"{FLRed}Invalid input file path. EXIT...{CRst}\n")
	sys.exit(1)

if _arg_output:
    output_path = _arg_output
else:
    output_path = input(f"{FLYellow}Enter output PDF file path (default: {output_path}): {CRst}") or output_path
out_dir = os.path.dirname(output_path) or "."
if(not output_path or os.path.exists(out_dir) == False):
	print(f"{FLRed}Invalid or unexisting output file path. EXIT...{CRst}\n")
	sys.exit(1)
if(os.path.exists(output_path)):
	print(f"{FLRed}Output file already exists. EXIT...{CRst}\n")
	sys.exit(1)

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
				需要我把
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
