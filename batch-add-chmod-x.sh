
#!/usr/bin/env bash
set -eu

FLYellow="\033[33m"
FLCyan="\033[36m"
FLGreen="\033[32m"
FLRed="\033[31m"
FGray="\033[90m"
CRst="\033[0m"


#============ root 权限检查 ===========
if [ "$(id -u)" -ne 0 ]; then
    printf "${FLRed}ERROR: This script must be run as root. Use ${CRst}${FLYellow}sudo${CRst}.\n"
    exit 1
fi

#============ 用户交互 ===========
if [ -n "${1:-}" ]; then
    TARGET="$1"
else
    printf "${FLYellow}Enter file or directory path (default: .)${CRst}: "
    read -r TARGET
fi

TARGET="${TARGET:-.}"

if [ ! -e "$TARGET" ]; then
    printf "${FLRed}ERROR: Invalid or non-existent path${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"
    exit 1
fi

TARGET="$(realpath "$TARGET")"
printf "  -> ${FLCyan}target${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"

#============ 代码主体部分 ===========
if [ -f "$TARGET" ]; then
    printf "  -> adding +x to file: ${FLYellow}%s${CRst}\n" "$TARGET"
    chmod +x "$TARGET"
    printf "${FLGreen}Done. +x added to${CRst} ${FLYellow}%s${CRst}\n" "$TARGET"
elif [ -d "$TARGET" ]; then
    printf "  -> adding +x to .py and .sh files recursively in ${FLYellow}%s${CRst}...\n" "$TARGET"
    find "$TARGET" -type f \( -name "*.py" -o -name "*.sh" \) -print -exec chmod +x {} \;
    printf "${FLGreen}Done.${CRst}\n"
else
    printf "${FLRed}ERROR: Unknown path type${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"
    exit 1
fi
