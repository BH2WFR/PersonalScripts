
#!/bin/bash
set -euo pipefail

FLYellow="\033[33m"
FLCyan="\033[36m"
FLGreen="\033[32m"
FLRed="\033[31m"
FGray="\033[90m"
CRst="\033[0m"


#============ root 权限检查 ===========
if [ "$(id -u)" -ne 0 ]; then
    echo "${FLRed}ERROR: This script must be run as root. Use ${CRst}${FLYellow}sudo${CRst}."
    exit 1
fi

#============ 用户交互 ===========
if [ -n "${1:-}" ]; then
    TARGET="$1"
else
    read -rp "${FLYellow}Enter file or directory path${CRst}: " TARGET
fi

if [ -z "$TARGET" ] || [ ! -e "$TARGET" ]; then
    echo -e "${FLRed}ERROR: Invalid or non-existent path${CRst}: ${TARGET:-"(empty)"}"
    exit 1
fi

TARGET="$(realpath "$TARGET")"
echo -e "  -> ${FLCyan}target${CRst}: ${FLYellow}$TARGET${CRst}"

#============ 代码主体部分 ===========
if [ -f "$TARGET" ]; then
    echo -e "  -> adding +x to file: ${FLYellow}$TARGET${CRst}"
    chmod +x "$TARGET"
    echo -e "${FLGreen}Done. +x added to${CRst} ${FLYellow}$TARGET${CRst}"
elif [ -d "$TARGET" ]; then
    echo -e "  -> adding +x to .py and .sh files recursively in ${FLYellow}$TARGET${CRst}..."
    find "$TARGET" -type f \( -name "*.py" -o -name "*.sh" \) -print -exec chmod +x {} \;
    echo -e "${FLGreen}Done.${CRst}"
else
    echo -e "${FLRed}ERROR: Unknown path type${CRst}: ${FLYellow}$TARGET${CRst}"
    exit 1
fi
