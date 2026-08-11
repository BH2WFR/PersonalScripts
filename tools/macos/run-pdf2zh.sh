#!/usr/bin/env bash

set -euo pipefail

WORK_DIR="$HOME/Data"
FILES_DIR="pdf2zh_files"

PDF2ZH_CANDIDATES=(
    "pdf2zh"
    "pdf2zh_next"
    "$HOME/.local/bin/pdf2zh"
    "$HOME/.local/bin/pdf2zh_next"
    "$HOME/.local/share/uv/tools/pdf2zh-next/bin/pdf2zh"
    "$HOME/.local/share/uv/tools/pdf2zh-next/bin/pdf2zh_next"
)

ORIGINAL_DIR="$(pwd -P)"

restore_original_dir() {
    cd "$ORIGINAL_DIR" 2>/dev/null || true
}
trap restore_original_dir EXIT

find_pdf2zh() {
    local candidate
    for candidate in "${PDF2ZH_CANDIDATES[@]}"; do
        if [[ "$candidate" == */* ]]; then
            if [[ -x "$candidate" ]]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        elif command -v "$candidate" >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

PDF2ZH_BIN="$(find_pdf2zh || true)"
if [[ -z "$PDF2ZH_BIN" ]]; then
    echo "ERROR: pdf2zh not found. Checked:" >&2
    printf '  %s\n' "${PDF2ZH_CANDIDATES[@]}" >&2
    exit 1
fi

mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
mkdir -p "$FILES_DIR"

if [[ $# -gt 0 ]]; then
    "$PDF2ZH_BIN" "$@"
else
    "$PDF2ZH_BIN" --gui
fi
