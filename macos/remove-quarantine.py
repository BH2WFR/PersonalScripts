import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from utils import *

# 移除 macOS 文件上的 quarantine（隔离）属性，解决 "无法打开，因为它来自身份不明的开发者" 问题


print(f"{FLYellow}=========== REMOVE QUARANTINE ATTRIBUTE TOOL ==========={CRst}")

if "--help" in sys.argv or "-h" in sys.argv:
    script_name = os.path.basename(sys.argv[0])
    print(f"""
REMOVE QUARANTINE ATTRIBUTE TOOL
================================

Usage:
  python {script_name} <path1> <path2> ...    specify multiple paths, skip interaction
  python {script_name} <path> -r              specify path, recursive for directories
  python {script_name}                        no arguments, interactive mode
  python {script_name} --help                 show this help

{FLYellow}Description:{CRst}
  macOS only. Remove quarantine attribute from files/folders to
  bypass "unidentified developer cannot be opened" warning.
  For directories, supports recursive or non-recursive processing.
""")
    sys.exit(0)

#============ 系统检查 ===========
if sys.platform != "darwin":
    print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
    sys.exit(1)


#============ 用户交互 ===========
is_recursive = "-r" in sys.argv or "--recursive" in sys.argv
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


#============ 目录处理方式 ===========
# 检查是否需要询问递归模式
dir_paths = [p for p in valid_paths if os.path.isdir(p)]
if dir_paths and not is_recursive:
    if len(sys.argv) > 1:
        # 命令行模式：有目录但未指定 -r，默认非递归
        print(f"{FLYellow}  -> directories detected, using non-recursive mode (use -r for recursive){CRst}")
    else:
        # 交互模式：询问用户
        print(f"\n{FLYellow}{len(dir_paths)} directory path(s) detected:{CRst}")
        for d in dir_paths:
            print(f"    {FLCyan}{d}{CRst}")
        print(f"  {FLMagenta}0{CRst}: {FLYellow}Non-recursive{CRst} (directory itself + files directly inside)")
        print(f"  {FLMagenta}1{CRst}: {FLYellow}Recursive{CRst} (all files/folders inside)")
        choice = input(f"{FLCyan}Choose (default 0): {CRst}").strip() or "0"
        is_recursive = choice == "1"


#============ 代码主体部分 ===========
succeed_count = 0
fail_count = 0

for filepath in valid_paths:
    print(f"\n{FLYellow}  -> removing quarantine from: {filepath}{CRst}")

    if os.path.isdir(filepath):
        if is_recursive:
            # 递归：xattr -cr 清除目录及所有子文件/子目录
            result = subprocess.run(["xattr", "-cr", filepath], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  {FLGreen}OK (recursive): {filepath}{CRst}")
                succeed_count += 1
            else:
                err = result.stderr.strip()
                print(f"  {FLRed}FAIL (recursive): {filepath}{CRst}")
                if err:
                    print(f"    {FLRed}{err}{CRst}")
                fail_count += 1
        else:
            # 非递归：xattr -c 清除目录自身 + 遍历一级文件
            result = subprocess.run(["xattr", "-c", filepath], capture_output=True, text=True)
            if result.returncode != 0:
                err = result.stderr.strip()
                if err:
                    print(f"  {FLYellow}  xattr -c failed: {err}{CRst}")
            try:
                for entry in os.listdir(filepath):
                    entry_path = os.path.join(filepath, entry)
                    if os.path.isfile(entry_path) and not os.path.islink(entry_path):
                        subprocess.run(["xattr", "-d", "com.apple.quarantine", entry_path],
                                    capture_output=True, text=True)
                print(f"  {FLGreen}OK (non-recursive): {filepath}{CRst}")
                succeed_count += 1
            except Exception as e:
                print(f"  {FLRed}FAIL (non-recursive): {filepath} -> {e}{CRst}")
                fail_count += 1
    else:
        # 文件：直接移除
        result = subprocess.run(["xattr", "-d", "com.apple.quarantine", filepath],
                                capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  {FLGreen}OK: {filepath}{CRst}")
            succeed_count += 1
        else:
            err = result.stderr.strip()
            print(f"  {FLYellow}  [WARNING]: xattr -d failed (maybe no quarantine attribute){CRst}")
            if err:
                print(f"    {FGray}{err}{CRst}")
            succeed_count += 1  # 文件没有 quarantine 不算失败

print(f"\n{FLGreen}Done. Succeed: {succeed_count}{CRst}, {FLRed}Failed: {fail_count}{CRst}, {FLYellow}Total: {succeed_count + fail_count}{CRst}\n")
