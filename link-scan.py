from utils import *
import stat

# 扫描某个路径下所有的符号链接、Junction 和 Hard Link 文件，并打印出来，同时还会识别是否指向一个无效地址。
# 列举后，可自动删除所有指向地址无效的链接
# 列举后，Windows 下，可将指向文件夹的错误 symlink 修复成 symlinkd
#


#* 交互输入或 argv[1] 读取
print(f"{FLYellow}=========== LINK SCANNING TOOL ==========={CRst}")

script_name = os.path.basename(sys.argv[0])

if "--help" in sys.argv or "-h" in sys.argv:
    print(f"""
LINK SCANNING TOOL
==================

Usage:
  python {script_name} <path>       specify path, skip interaction
  python {script_name}              no arguments, interactive mode
  python {script_name} --help       show this help

{FLYellow}Description:{CRst}
  Recursively scan directories, list all symlinks, symlinkd, Junctions and hardlinks.
  Detect broken links and Windows symlinks incorrectly pointing to directories.
  Optionally auto-delete broken links or convert incorrect symlinks to symlinkd.
""")
    sys.exit(0)

IS_SCAN_JUNCTION = os.name == "nt"  # Windows 默认启用 Junction 扫描

if len(sys.argv) > 1:
    ROOT = sys.argv[1]
else:
    ROOT = "/volumeUSB1/usbshare1-2"   # ← 改成要检查的目录
    ROOT = input(f"{FLCyan}Enter path to check (default: {ROOT}): {CRst}") or ROOT

if not os.path.exists(ROOT):
    print(f"{FLRed}The specified root path does not exist. EXIT...{CRst}\n")
    sys.exit(1)

# enum
class EType(enum.Enum):
	SYMLINK = 1
	SYMLINKD = 2 # Windows only
	JUNCTION = 3 # Windows only
	HARDLINK = 4

class Info:
	path: str
	type: EType # symlink/symlinkd/junction/hardlink
	dest: str
	hardlink_count: int = 0
	is_broken: bool = False
	is_symlink_to_dir_win32: bool = False # windows 下，symlink 指向的是否是一个目录，导致链接失效，此时可以转换为 symlinkd
	def __init__(self, path, type, dest):
		self.path = path
		self.type = type
		self.dest = dest




def check_file_is_symlink(filepath : str) -> Info | None:
	if not os.path.lexists(filepath): # 不算损坏的符号链接
		return None

	#* Symlink (works for files and directory symlinks; also often works for junctions)
	if os.path.islink(filepath):
		try:
			dest = os.readlink(filepath) # 仅解析软链接指向，与 os.path.realpath 不同(会递归解析到最终的绝对路径)
		except OSError:
			dest = ""
		realpath = os.path.realpath(filepath) # 解析到最终的绝对路径
		if(os.name == "nt"):
			if os.path.isdir(filepath):
				ret = Info(filepath, EType.SYMLINKD, dest)
			else:
				ret = Info(filepath, EType.SYMLINK, dest)
				ret.is_symlink_to_dir_win32 = os.path.isdir(realpath) # Windows 下，检查这个文件 symlink 指向的是否是一个目录
		else: # linux 中，不存在 symlinkd，文件/文件夹软链接统一处理
			ret = Info(filepath, EType.SYMLINK, dest)
		ret.is_broken = not os.path.exists(realpath) # 检测是否指向不可用的地址
		return ret
	
	#* Hard link: link count > 1
	try:
		st = os.stat(filepath, follow_symlinks=False)
		# On Unix, directories naturally have st_nlink >= 2, so only treat regular files as hardlinks.
		if stat.S_ISREG(st.st_mode) and getattr(st, "st_nlink", 1) > 1:
			ret = Info(filepath, EType.HARDLINK, "")
			ret.hardlink_count = st.st_nlink
			return ret
	except Exception:
		return None

	#* Junction (Windows reparse point with MOUNT_POINT tag)
	if os.name == "nt" and IS_SCAN_JUNCTION:
		try:
			from ctypes import wintypes

			FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
			FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
			OPEN_EXISTING = 3
			GENERIC_READ = 0x80000000
			FSCTL_GET_REPARSE_POINT = 0x000900A8
			IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003

			CreateFileW = ctypes.windll.kernel32.CreateFileW
			CreateFileW.argtypes = [
				wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
				wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
			]
			CreateFileW.restype = wintypes.HANDLE

			h = CreateFileW(
				filepath, GENERIC_READ, 0, None, OPEN_EXISTING,
				FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, None
			)
			INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
			if h != INVALID_HANDLE_VALUE:
				try:
					class REPARSE_DATA_BUFFER(ctypes.Structure):
						_fields_ = [
							("ReparseTag", wintypes.ULONG),
							("ReparseDataLength", wintypes.USHORT),
							("Reserved", wintypes.USHORT),
							("SubstituteNameOffset", wintypes.USHORT),
							("SubstituteNameLength", wintypes.USHORT),
							("PrintNameOffset", wintypes.USHORT),
							("PrintNameLength", wintypes.USHORT),
							("PathBuffer", ctypes.c_byte * 0x3FF0),  # large enough buffer
						]
					
					buf = REPARSE_DATA_BUFFER()
					bytes_returned = wintypes.DWORD(0)
					DeviceIoControl = ctypes.windll.kernel32.DeviceIoControl
					ok = DeviceIoControl(
						h, FSCTL_GET_REPARSE_POINT,
						None, 0,
						ctypes.byref(buf), ctypes.sizeof(buf),
						ctypes.byref(bytes_returned),
						None
					)
					if ok and buf.ReparseTag == IO_REPARSE_TAG_MOUNT_POINT:
						# Extract substitute name (target)
						off = buf.SubstituteNameOffset
						ln = buf.SubstituteNameLength
						raw = ctypes.string_at(ctypes.addressof(buf.PathBuffer) + off, ln)
						try:
							dest = raw.decode("utf-16le")
						except Exception:
							dest = ""
						is_broken = not os.path.exists(filepath)
						ret = Info(filepath, EType.JUNCTION, dest)
						ret.is_broken = is_broken
						return ret
				finally:
					ctypes.windll.kernel32.CloseHandle(h)
		except Exception:
			return None
	# junction
# check_file_is_symlink

infos : list[Info] = []
brokenInfos : list[Info] = []
symlink2DirInfos : list[Info] = []

# 递归遍历目录，查找每个文件和文件夹
for dirpath, dirnames, filenames in os.walk(ROOT):
	for name in dirnames + filenames:
		fullpath =  os.path.join(dirpath, name)
		info = check_file_is_symlink(fullpath)
		if info:
			infos.append(info)
			if info.is_broken:
				brokenInfos.append(info)
			if info.type == EType.SYMLINK and info.is_symlink_to_dir_win32:
				symlink2DirInfos.append(info)
			

# 输出结果
if len(infos) == 0:
	if os.name == "nt":
		print(f"{FLGreen}No symlinks/junctions/hardlinks found under the specified path.{CRst}\n")
	else:
		print(f"{FLGreen}No symlinks/hardlinks found under the specified path.{CRst}\n")
else:
	if os.name == "nt":
		print(f"{FLYellow}Found{CRst} {FLGreen}{len(infos)}{CRst} {FLYellow}symlinks(S)/symlinkd(D)/junctions(J)/hardlinks(H):{CRst}\n")
	else:
		print(f"{FLYellow}Found{CRst} {FLGreen}{len(infos)}{CRst} {FLYellow}symlinks(S)/hardlinks(H):{CRst}\n")
	
	for info in infos:
		is_broken_str = f" {FLRed}[BROKEN]{CRst}" if info.is_broken else ""
		if info.type == EType.SYMLINK:
			if(info.is_symlink_to_dir_win32):
				is_broken_str += f" {FLRed}[SYMLINK TO DIR]{CRst}"
			print(f"  {FLYellow}L{CRst}{is_broken_str}: `{FLCyan}{info.path}{CRst}`	-> `{FLGreen}{info.dest}{CRst}`")
		elif info.type == EType.SYMLINKD:
			print(f"  {FLGreen}D{CRst}{is_broken_str}: `{FLCyan}{info.path}{CRst}`	-> `{FLGreen}{info.dest}{CRst}`")
		elif info.type == EType.JUNCTION:
			print(f"  {FLBlue}J{CRst}{is_broken_str}: `{FLCyan}{info.path}{CRst}`	-> `{FLGreen}{info.dest}{CRst}`")
		elif info.type == EType.HARDLINK:
			print(f"  {FLMagenta}H{CRst}{is_broken_str}: `{FLCyan}{info.path}{CRst}`, COUNT=`{FLRed}{info.hardlink_count}{CRst}`")
	print("")


# 修复
if(len(brokenInfos) > 0):
	print(f"{FLYellow}Found {len(brokenInfos)} broken symlinks/junctions/hardlinks. Delete them? {CRst}(y/n): ", end="")
	IS_FIX = input().strip().lower() == 'y'
	if IS_FIX:
		for info in brokenInfos:
			try:
				os.unlink(info.path)
				print(f"  {FLGreen}Removed broken link:{CRst} `{FLCyan}{info.path}{CRst}`")
			except Exception as e:
				print(f"  {FLRed}Failed to remove:{CRst} `{FLCyan}{info.path}{CRst}`. Error: {e}")
		print("")
	else:
		print("skipped.")

if(os.name == "nt" and len(symlink2DirInfos) > 0):
	print(f"{FLYellow}Found {len(symlink2DirInfos)} symlinks pointing to directories. Convert them to symlinkd? {CRst}(y/n): ", end="")
	IS_CONVERT = input().strip().lower() == 'y'
	if IS_CONVERT:
		for info in symlink2DirInfos:
			try:
				dest = info.dest
				os.unlink(info.path)
				os.symlink(dest, info.path, target_is_directory=True)
				print(f"  {FLGreen}Fixed to symlinkd:{CRst} `{FLCyan}{info.path}{CRst}` -> `{FLGreen}{dest}{CRst}`")
			except Exception as e:
				print(f"  {FLRed}Failed to convert:{CRst} `{FLCyan}{info.path}{CRst}`. Error: {e}")
		print("")
	else:
		print("skipped.")
