import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from my_utils import *

# 移除 macOS 文件上的 quarantine（隔离）属性，解决 "无法打开，因为它来自身份不明的开发者" 问题


print(f"{FLYellow}=========== REMOVE QUARANTINE ATTRIBUTE TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
REMOVE QUARANTINE ATTRIBUTE TOOL
================================

Usage:
  python {script_name} <path1> <path2> ...    指定多个路径，跳过交互
  python {script_name}                          无参数，进入交互输入模式
  python {script_name} --help                   显示此帮助

功能：
  macOS 专用。移除文件/文件夹上的 quarantine（隔离）属性，
  解决"无法打开，因为它来自身份不明的开发者"问题。
""")
    sys.exit(0)

#============ 系统检查 ===========
if sys.platform != "darwin":
    print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
    sys.exit(1)


#============ 用户交互 ===========
filepaths: list[str] = []
if len(sys.argv) > 1:
    for i in range(1, len(sys.argv)):
        p = sys.argv[i].strip()
        if not p.startswith("-") and p:
            filepaths.append(p)
else:
    print(f"{FLYellow}Enter file or directory paths (one per line).{CRst}")
    print(f"{FLCyan}End with {FLYellow}Ctrl+Z (Windows) or Ctrl+D (Linux/macOS){FLCyan}:{CRst}")
    input_text = sys.stdin.read().strip()
    if not input_text:
        print(f"{FLRed}No paths provided. EXIT...{CRst}\n")
        sys.exit(1)
    for line in input_text.splitlines():
        line = line.strip()
        if line:
            filepaths.append(line)

if not filepaths:
    print(f"{FLRed}No paths provided. EXIT...{CRst}\n")
    sys.exit(1)

# 去重并校验
filepaths = list(dict.fromkeys(filepaths))  # 保持顺序的去重
valid_paths: list[str] = []
for fp in filepaths:
    if not os.path.exists(fp):
        print(f"{FLRed}Path does not exist, skipped: {fp}{CRst}")
        continue
    valid_paths.append(os.path.abspath(fp))

if not valid_paths:
    print(f"{FLRed}No valid paths to process. EXIT...{CRst}\n")
    sys.exit(1)

print(f"{FLYellow}  -> {len(valid_paths)} path(s) to process{CRst}")


#============ 代码主体部分 ===========
succeed_count = 0
fail_count = 0

for filepath in valid_paths:
    print(f"\n{FLYellow}  -> removing quarantine from: {filepath}{CRst}")
    ret = os.system(f'xattr -d com.apple.quarantine "{filepath}" 2>/dev/null')

    if ret == 0:
        print(f"  {FLGreen}OK: {filepath}{CRst}")
        succeed_count += 1
    else:
        print(f"{FLYellow}  [WARNING]: xattr -d failed, trying recursive removal...{CRst}")
        ret2 = os.system(f'xattr -cr "{filepath}" 2>/dev/null')
        if ret2 == 0:
            print(f"  {FLGreen}OK (recursive): {filepath}{CRst}")
            succeed_count += 1
        else:
            print(f"  {FLRed}FAIL: {filepath}{CRst}")
            fail_count += 1

print(f"\n{FLGreen}Done. Succeed: {succeed_count}{CRst}, {FLRed}Failed: {fail_count}{CRst}, {FLYellow}Total: {succeed_count + fail_count}{CRst}\n")
