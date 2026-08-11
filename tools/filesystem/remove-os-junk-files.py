#!/usr/bin/env python3
# 递归删除操作系统生成的垃圾文件（.DS_Store / __MACOSX__ / Thumbs.db 等）
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402

# OS junk files to remove
JUNK_NAMES = {".DS_Store", "__MACOSX__", "Thumbs.db", ".AppleDouble", ".Spotlight-V100", ".Trashes", "desktop.ini"}


def main() -> int:
    Utils.print_banner("OS JUNK FILE REMOVAL TOOL")

    if "--help" in sys.argv or "-h" in sys.argv:
        script_name = os.path.basename(sys.argv[0])
        print(f"""
OS JUNK FILE REMOVAL TOOL
=========================

Usage:
  python {script_name} <path>       specify path, skip interaction
  python {script_name}              no arguments, interactive mode
  python {script_name} --help       show this help

{FLYellow}Description:{CRst}
  Recursively remove all OS-generated junk files from a directory:
    .DS_Store, __MACOSX__, Thumbs.db, .AppleDouble,
    .Spotlight-V100, .Trashes, desktop.ini

{FLYellow}Requirements:{CRst}
  No external dependencies.
""")
        return 0


    #============ 用户交互 ===========
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        root = sys.argv[1]
    else:
        root = Input.resolve_input_path(".", prompt="Enter path to clean", path_type="dir")
    print(f"{FLYellow}  -> target: {root}{CRst}")


    #============ 扫描并删除 ===========
    deleted_count = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        # 跳过 __MACOSX__ 目录本身（作为文件夹整体删除）
        to_remove_dirs = [d for d in dirnames if d in JUNK_NAMES]
        for d in to_remove_dirs:
            full = os.path.join(dirpath, d)
            try:
                if os.path.isdir(full):
                    shutil.rmtree(full)
                else:
                    os.unlink(full)
                print(f"  {FLGreen}DEL:{CRst} {full}")
                deleted_count += 1
            except Exception as e:
                print(f"  {FLRed}FAIL:{CRst} {full} -> {e}")
            dirnames.remove(d)  # 防止 os.walk 继续进入已删除的目录

        # 删除垃圾文件
        for name in filenames:
            if name in JUNK_NAMES:
                full = os.path.join(dirpath, name)
                try:
                    os.unlink(full)
                    print(f"  {FLGreen}DEL:{CRst} {full}")
                    deleted_count += 1
                except Exception as e:
                    print(f"  {FLRed}FAIL:{CRst} {full} -> {e}")


    if deleted_count == 0:
        print(f"{FLGreen}No junk files found.{CRst}\n")
    else:
        print(f"\n{FLGreen}Done. {deleted_count} junk file(s) removed.{CRst}\n")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
