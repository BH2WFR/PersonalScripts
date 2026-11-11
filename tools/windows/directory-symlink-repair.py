#!/usr/bin/env python3
"""Implementation notes.

Inspect native reparse metadata before recreating a link. Preserve its target
and do not recurse into that target during the directory walk.
"""


import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *

HELP = f"""{FLYellow}DIRECTORY SYMLINK REPAIR{CRst}

Repair Windows file-type symlinks that target directories so other tools can
traverse them correctly.

{FLYellow}Requirements:{CRst}
  Windows; project runtime and permission to recreate symbolic links.

{FLYellow}Usage:{CRst}
  python directory-symlink-repair.py [PATH]
"""

if __name__ == "__main__" and sys.argv[1:] in (["--help"], ["-h"]):
    print(HELP)
    raise SystemExit(0)

from typing import Optional


def main() -> int:
    #* Windows only
    if(os.name != "nt"):
        print(f"{FLRed}ERROR: This script only runs on Windows. Current platform: {sys.platform}{CRst}\n")
        return 1

    #* 交互输入
    Console.print_banner("DIRECTORY SYMLINK REPAIR")

    if "--help" in sys.argv or "-h" in sys.argv:

        print(HELP)
        return 0

    ROOT = "D:/test"   # ← 改成要检查的目录
    if len(sys.argv) > 1:
        ROOT = sys.argv[1]
    else:
        ROOT = Input.resolve_input_path(ROOT, prompt="Enter path to check", path_type="dir")

    # enum
    class EType(enum.Enum):
        SYMLINK = 1
        SYMLINKD = 2

    class Info:
        path: str
        type: EType # symlink/symlinkd/junction/hardlink
        dest: str
        def __init__(self, path, type, dest):
            self.path = path
            self.type = type
            self.dest = dest

    symlinkInfos : list[Info] = []
    symlinkdInfos : list[Info] = []

    def check_file_is_symlink(filepath : str) -> Optional[Info]:
        if not os.path.lexists(filepath): # 不算损坏的符号链接
            return None

        #* Symlink (works for files and directory symlinks; also often works for junctions)
        if os.path.islink(filepath):
            try:
                dest = os.readlink(filepath)
            except OSError:
                dest = ""
            if os.path.isdir(filepath):
                return Info(filepath, EType.SYMLINKD, dest)
            else:
                return Info(filepath, EType.SYMLINK, dest)

    # 递归遍历目录，查找每个文件和文件夹
    for dirpath, dirnames, filenames in os.walk(ROOT):
        for name in dirnames + filenames:
            fullpath =  os.path.join(dirpath, name)
            info = check_file_is_symlink(fullpath)
            if info:
                if info.type == EType.SYMLINK:
                    symlinkInfos.append(info)
                elif info.type == EType.SYMLINKD:
                    symlinkdInfos.append(info)

    # 对 symlinkInfos 检查dest，如果 dest 指向的是一个目录，则保留，否则丢弃
    validSymlinkInfos : list[Info] = []
    for info in symlinkInfos:
        targetPath = os.path.realpath(info.path)
        if os.path.isdir(targetPath):
            print(f"{FLRed}FOUND: {FLCyan}{info.path}{CRst} -> {FLGreen}{info.dest}{CRst}")
            validSymlinkInfos.append(info)

    # 输出结果
    if len(validSymlinkInfos) == 0:
        print(f"{FLGreen}No symlink linked to a directory found under the specified path.{CRst}\n")
        return 0

    # 转换 symlink -> symlinkd
    print(f"{FLCyan}Found {len(validSymlinkInfos)} symlink(s) linked to a directory:{CRst}. {FLYellow}Fix them? (y/n): {CRst}", end="")
    IS_CONVERT = input().strip().lower() == 'y'
    if not IS_CONVERT:
        print(f"{FLRed}Cancelled by user. EXIT...{CRst}\n")
        return 0

    print(f"{FLYellow}Converting...{CRst}\n")
    for info in validSymlinkInfos:
        print(f"  {FLYellow}L{CRst}: `{FLCyan}{info.path}{CRst}`	-> `{FLGreen}{info.dest}{CRst}`")
        try:
            # 删除原有的 symlink
            os.unlink(info.path)
            # 创建 symlinkd
            os.symlink(info.dest, info.path, target_is_directory=True)
        except Exception as e:
            print(f"{FLRed}    ERROR: {str(e)}{CRst}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
