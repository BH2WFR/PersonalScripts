#!/usr/bin/env python3
from utils import *
import os, sys
from typing import Optional

# 用于在 NAS 等设备上, 截断过长的文件名 (UTF-8 字节长度)
# 如在群晖的加密文件夹中, 文件名长度限制为 143 字节 (UTF-8), 此工具可检查并截断超长的文件名 (保留扩展名)
# 如截断后有重名, 则会在扩展名前加入 "_1" 等数字后缀


#* 自动截断文件名，并保留扩展名
def get_truncated_filename(name, limit, encoding, de_dupe_idx=0):
    stem, ext = os.path.splitext(name)

    if(de_dupe_idx > 0):
        ext = f"_{de_dupe_idx}{ext}" # 在扩展名前加后缀以防重名
        name = f"{stem}{ext}" # 写回 name 以便后续长度检查

    original_bytes = name.encode(encoding)
    if len(original_bytes) <= limit: # 不需要截断
        return name

    stem_bytes = stem.encode(encoding)
    ext_bytes = ext.encode(encoding)
    ext_len = len(ext_bytes)

    allowed_stem_len = (limit - ext_len) # 去除扩展名，剩余给主文件名的字节数
    if allowed_stem_len <= 0: # 连扩展名都放不下，直接截前 limit 个字节再安全解码
        return original_bytes[:limit].decode(encoding, errors="ignore")

    truncated_stem_bytes = stem_bytes[:allowed_stem_len] # 截断主文件名部分
    safe_stem = truncated_stem_bytes.decode(encoding, errors="ignore")
    return f"{safe_stem}{ext}" # 组合


def main() -> int:
    #* 交互输入
    Utils.print_banner("FILENAME LENGTH CHECKING AND TRUNCATING TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
FILENAME LENGTH CHECKING AND TRUNCATING TOOL
============================================

Usage:
  python {script_name} <path>        specify path, limit/encoding interactive
  python {script_name} --limit=143 --encoding=utf-8
  python {script_name} <path> --limit=143 --encoding=utf-8
  python {script_name}                no arguments, interactive mode
  python {script_name} --help         show this help

{FLYellow}Arguments:{CRst}
  <path>              directory path to scan
  --limit=N           filename UTF-8 byte length limit (default: 143)
  --encoding=ENC      encoding (default: utf-8)

{FLYellow}Description:{CRst}
  Recursively scan directory for filenames whose UTF-8 byte length exceeds
  the limit, then truncate them while preserving the file extension.
  When truncation produces a name collision, appends _1, _2, etc. before
  the extension to avoid duplicates. Commonly used for NAS devices
  (e.g., Synology encrypted shared folder has a 143-byte filename limit).
""")
        return 0

    ROOT = "/volumeUSB1/usbshare1-2"   # ← 改成要检查的目录
    LIMIT = 143
    ENCODING = "utf-8"

    # 解析命令行参数
    _arg_path: Optional[str] = None
    _arg_limit: Optional[int] = None
    _arg_encoding: Optional[str] = None
    for i in range(1, len(sys.argv)):
        arg = sys.argv[i]
        if arg.startswith("--limit="):
            _arg_limit = int(arg.split("=", 1)[1])
        elif arg.startswith("--encoding="):
            _arg_encoding = arg.split("=", 1)[1]
        elif not arg.startswith("--"):
            _arg_path = arg

    if _arg_path:
        ROOT = _arg_path
    else:
        ROOT = Input.resolve_input_path(ROOT, prompt="Enter path to check", path_type="dir")

    if _arg_limit is not None:
        LIMIT = _arg_limit
    else:
        LIMIT = Input.input_number(
            "Enter byte length limit",
            default=LIMIT,
            min_value=33,
            allow_float=False,
        )

    if _arg_encoding is not None:
        ENCODING = _arg_encoding
    else:
        ENCODING = input(f"{FLCyan}Enter encoding (default: {ENCODING}): {CRst}") or ENCODING
    try:
        ''.encode(ENCODING)
    except LookupError:
        print(f"{FLRed}Invalid encoding. EXIT...{CRst}\n")
        return 1



    #* 用户确认
    print(f"path={FLYellow}{ROOT}{CRst}, limit={FLCyan}{LIMIT}{CRst} bytes" \
            f", encoding={FLCyan}{ENCODING}{CRst}. proceed? (y/n): ", end="")
    confirm = input().strip().lower()
    if confirm != 'y':
        print(f"{FLRed}Cancelled by user. EXIT...{CRst}\n")
        return 0


    cnt = 0
    overlongList = []
    print("")
    #* 遍历目录及子目录
    for dirpath, dirnames, filenames in os.walk(ROOT):
        for name in dirnames + filenames:
            byte_len = len(name.encode(ENCODING)) # UTF-8 编码的字节长度
            if byte_len > LIMIT:
                cnt += 1
                print(f"IDX={FLYellow}{cnt}{CRst} BYTES={FLCyan}{byte_len}{CRst} PATH={FLBlue}{dirpath}{CRst}/{FLRed}{name}{CRst}")
                overlongList.append(os.path.join(dirpath, name))


    if(cnt != 0):
        is_truncate = False
        truncate_input = input(f"\n{FLCyan}Found {cnt} overlong filenames. Truncate them? (y/n, default: n): {CRst}") or "n"
        if truncate_input.strip().lower() == 'y':
            truncated_paths = []
            for full_path in overlongList:
                dirpath, name = os.path.split(full_path)
                name_byte_len = len(name.encode(ENCODING))
                de_dupe_idx = 0
                truncated_name = ""
                while True: # 为了防止截断后重名，循环尝试加后缀
                    truncated_name = get_truncated_filename(name, LIMIT, ENCODING, de_dupe_idx)
                    new_full_path = os.path.join(dirpath, truncated_name)
                    if not (os.path.exists(new_full_path) or (new_full_path in truncated_paths)): # 不重名就行
                        break
                    if(de_dupe_idx > 5000): # 防止死循环
                        print(f"    {FLRed}Failed to find non-duplicate truncated name for:{CRst} `{full_path}` after 5000 attempts. Skipping...")
                        truncated_name = ""
                        break
                    de_dupe_idx += 1
                if truncated_name == "":
                    continue
                truncated_byte_len = len(truncated_name.encode(ENCODING))
                new_full_path = os.path.join(dirpath, truncated_name)
                truncated_paths.append(new_full_path)
                try:
                    # 检查 truncate 后会不会重名
                    os.rename(full_path, dst=new_full_path) #* 重命名
                    print(f"{FLYellow}RENAMED:{CRst} `{FLRed}{full_path}{CRst}` -> `{FLGreen}{new_full_path}{CRst}`" \
                        f"，bytes: {FLCyan}{name_byte_len} -> {truncated_byte_len}{CRst}")
                except Exception as e:
                    print(f"{FLRed}ERROR: Failed to rename:{CRst} `{full_path}`, Error: {e}")


    #* 结束
    print(f"\nDone. Overlong entries count = {FLGreen if cnt==0 else FLRed}{cnt}{CRst}.\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
