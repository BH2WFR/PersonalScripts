import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from my_utils import *

# 移除 macOS 文件上的 quarantine（隔离）属性，解决 "无法打开，因为它来自身份不明的开发者" 问题


print(f"{FLYellow}=========== REMOVE QUARANTINE ATTRIBUTE TOOL ==========={CRst}")

#============ 系统检查 ===========
if sys.platform != "darwin":
    print(f"{FLRed}ERROR: This script only runs on macOS. Current platform: {sys.platform}{CRst}\n")
    sys.exit(1)


#============ 用户交互 ===========
if len(sys.argv) > 1:
    filepath = sys.argv[1]
else:
    filepath = input(f"{FLYellow}Enter file or directory path to remove quarantine attribute: {CRst}")

if not filepath or not os.path.exists(filepath):
    print(f"{FLRed}Invalid or non-existent path. EXIT...{CRst}\n")
    sys.exit(1)

filepath = os.path.abspath(filepath)
print(f"{FLYellow}  -> target: {filepath}{CRst}")


#============ 代码主体部分 ===========
print(f"{FLYellow}  -> removing quarantine attribute...{CRst}")
ret = os.system(f'xattr -d com.apple.quarantine "{filepath}" 2>/dev/null')

if ret == 0:
    print(f"{FLGreen}Quarantine attribute removed successfully.{CRst}\n")
else:
    # xattr -d 失败可能是文件本身没有 quarantine 属性，尝试递归移除
    print(f"{FLYellow}[WARNING]: xattr -d failed (maybe no quarantine attribute). Trying recursive removal...{CRst}")
    ret2 = os.system(f'xattr -cr "{filepath}" 2>/dev/null')
    if ret2 == 0:
        print(f"{FLGreen}Quarantine attribute(s) removed successfully (recursive).{CRst}\n")
    else:
        print(f"{FLRed}Failed to remove quarantine attribute. EXIT...{CRst}\n")
        sys.exit(1)
