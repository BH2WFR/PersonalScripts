#!/usr/bin/env bash
set -eu

FLYellow="\033[33m"
FLCyan="\033[36m"
FLGreen="\033[32m"
FLRed="\033[31m"
FGray="\033[90m"
CRst="\033[0m"

# ============ 帮助文本 ============
show_help() {
    cat << 'EOF'
Usage: batch-add-chmod-x.sh [TARGET] [--suffix EXT[;EXT...]] [--ignore PATTERN [...]]

Recursively add chmod +x to files by extension.

Arguments:
  TARGET                File or directory path. If not provided, prompts interactively.
                        (default: .)

Options:
  --suffix EXT ...      File extensions to process (without leading dot).
                        Semicolons split into multiple values.
                        Can be specified multiple times.
                        After --suffix, all following non-option arguments are consumed
                        as extensions until the next flag or end of arguments.
                        (default: py;sh)

  --ignore PATTERN ...  Ignore files matching PATTERN. PATTERN is relative to TARGET.
                        Semicolons in PATTERN split into multiple patterns.
                        Can be specified multiple times.
                        After --ignore, all following non-option arguments are consumed
                        as patterns until the next flag or end of arguments.

                        Pattern types:
                          name                e.g. "*.png"       → matches any file named *.png
                          relative-path       e.g. "test/*"      → matches under test/ subdirectory
                          anchored-path       e.g. "/test/*"     → matches under TARGET's test/ dir

  --help, -h            Show this help message and exit.

Examples:
  batch-add-chmod-x.sh /path/to/project
  batch-add-chmod-x.sh . --suffix "py;sh;pl"
  batch-add-chmod-x.sh . --suffix "py" --suffix "sh"
  batch-add-chmod-x.sh . --ignore "*.png"
  batch-add-chmod-x.sh . --ignore "*.png;/test/*"
  batch-add-chmod-x.sh /path --ignore "*.png" --ignore "/test/*"
  batch-add-chmod-x.sh /path --suffix "py" --ignore "*.png"
EOF
    exit 0
}

# ============ 参数解析 ============
TARGET=""
SUFFIXES=()
IGNORE_PATTERNS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            show_help
            ;;
        --suffix)
            shift
            while [[ $# -gt 0 && ! "$1" =~ ^- ]]; do
                IFS=';' read -ra _parts <<< "$1"
                for _p in "${_parts[@]}"; do
                    _p="${_p#"${_p%%[![:space:]]*}"}"
                    _p="${_p%"${_p##*[![:space:]]}"}"
                    # Strip leading dot if present
                    _p="${_p#.}"
                    [[ -n "$_p" ]] && SUFFIXES+=("$_p")
                done
                shift
            done
            ;;
        --ignore)
            shift
            # Greedily consume all following non-option arguments as ignore patterns
            while [[ $# -gt 0 && ! "$1" =~ ^- ]]; do
                # Split by semicolon
                IFS=';' read -ra _parts <<< "$1"
                for _p in "${_parts[@]}"; do
                    # Trim leading/trailing whitespace
                    _p="${_p#"${_p%%[![:space:]]*}"}"
                    _p="${_p%"${_p##*[![:space:]]}"}"
                    [[ -n "$_p" ]] && IGNORE_PATTERNS+=("$_p")
                done
                shift
            done
            ;;
        *)
            if [[ -z "$TARGET" ]]; then
                TARGET="$1"
            else
                printf "${FLRed}ERROR: Unexpected extra argument: %s${CRst}\n" "$1" >&2
                printf "Run with --help for usage.\n" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

# ============ root 权限检查 ============
if [ "$(id -u)" -ne 0 ]; then
    printf "${FLYellow}Not running as root, re-launching with sudo...${CRst}\n"
    exec sudo bash "$0" "$@"
    printf "${FLRed}ERROR: Failed to elevate privileges. Please run manually with sudo.${CRst}\n"
    exit 1
fi

# ============ 用户交互 ============
if [[ -z "$TARGET" ]]; then
    printf "${FLYellow}Enter file or directory path (default: .)${CRst}: "
    read -r TARGET
fi

TARGET="${TARGET:-.}"

if [[ ${#SUFFIXES[@]} -eq 0 ]]; then
    printf "${FLYellow}Enter file extensions without dot, semicolon-separated${CRst} (default: ${FGray}py;sh${CRst}): "
    read -r _suffix_line
    _suffix_line="${_suffix_line:-py;sh}"
    IFS=';' read -ra _parts <<< "$_suffix_line"
    for _p in "${_parts[@]}"; do
        _p="${_p#"${_p%%[![:space:]]*}"}"
        _p="${_p%"${_p##*[![:space:]]}"}"
        _p="${_p#.}"
        [[ -n "$_p" ]] && SUFFIXES+=("$_p")
    done
fi

if [[ ${#IGNORE_PATTERNS[@]} -eq 0 ]]; then
    printf "${FLYellow}Enter ignore patterns, semicolon-separated${CRst} (e.g. ${FGray}*.png;/test/*${CRst}, or ${FLYellow}Enter${CRst} to skip): "
    read -r _ignore_line
    if [[ -n "$_ignore_line" ]]; then
        IFS=';' read -ra _parts <<< "$_ignore_line"
        for _p in "${_parts[@]}"; do
            _p="${_p#"${_p%%[![:space:]]*}"}"
            _p="${_p%"${_p##*[![:space:]]}"}"
            [[ -n "$_p" ]] && IGNORE_PATTERNS+=("$_p")
        done
    fi
fi

if [ ! -e "$TARGET" ]; then
    printf "${FLRed}ERROR: Invalid or non-existent path${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"
    exit 1
fi

TARGET="$(realpath "$TARGET")"
printf "  -> ${FLCyan}target${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"

# ============ 构建 find 排除参数 ============
FIND_EXCLUDES=()
for _pat in "${IGNORE_PATTERNS[@]}"; do
    if [[ "$_pat" == */* ]]; then
        # Contains path separator — use -path
        if [[ "$_pat" == /* ]]; then
            # Anchored to TARGET root
            FIND_EXCLUDES+=(! -path "${TARGET}${_pat}")
        else
            # Relative path
            FIND_EXCLUDES+=(! -path "*/${_pat}")
        fi
    else
        # Simple name pattern
        FIND_EXCLUDES+=(! -name "$_pat")
    fi
done

if [[ ${#SUFFIXES[@]} -gt 0 ]]; then
    printf "  -> ${FLCyan}suffixes${CRst}: ${FLYellow}%s${CRst}\n" "${SUFFIXES[*]}"
fi

if [[ ${#IGNORE_PATTERNS[@]} -gt 0 ]]; then
    printf "  -> ${FLCyan}ignore patterns${CRst}: ${FLYellow}%s${CRst}\n" "${IGNORE_PATTERNS[*]}"
fi

# ============ 构建 find 文件名条件 ============
FIND_NAME_COND=()
_first=true
for _s in "${SUFFIXES[@]}"; do
    if [[ "$_first" == true ]]; then
        FIND_NAME_COND=(-name "*.$_s")
        _first=false
    else
        FIND_NAME_COND+=(-o -name "*.$_s")
    fi
done

# ============ 代码主体部分 ============
if [ -f "$TARGET" ]; then
    printf "  -> adding +x to file: ${FLYellow}%s${CRst}\n" "$TARGET"
    chmod +x "$TARGET"
    printf "${FLGreen}Done. +x added to${CRst} ${FLYellow}%s${CRst}\n" "$TARGET"
elif [ -d "$TARGET" ]; then
    printf "  -> adding +x to files in ${FLYellow}%s${CRst}...\n" "$TARGET"
    find "$TARGET" -type f \( "${FIND_NAME_COND[@]}" \) \
        "${FIND_EXCLUDES[@]}" \
        -print -exec chmod +x {} \;
    printf "${FLGreen}Done.${CRst}\n"
else
    printf "${FLRed}ERROR: Unknown path type${CRst}: ${FLYellow}%s${CRst}\n" "$TARGET"
    exit 1
fi
