#!/usr/bin/env bash
# ============================================
#  npy/npz file viewer launcher (Windows Git Bash/Linux/macOS)
#  Usage:
#    double-click a .npy/.npz file (after setting
#    this script as the default opener), or
#    ./npy-viewer.sh <file.npy>
#
#  macOS: right-click .npy → Get Info → Open With
#         → select this script → Change All
#  Linux: right-click .npy → Open With → select
#         this script → set as default
#  Windows: run through run-script.py when Git Bash is available
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VIEWER_PY="$SCRIPT_DIR/npy-viewer.py"

# Find Python: prefer conda, then known conda paths, then working PATH entries.
PYTHON=""
OS_NAME="$(uname -s)"
IS_WINDOWS=false
case "$OS_NAME" in
    MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
esac

if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base 2>/dev/null || true)"
    if [[ -n "$CONDA_BASE" ]]; then
        if [[ "$IS_WINDOWS" == true ]] && command -v cygpath >/dev/null 2>&1; then
            CONDA_BASE="$(cygpath -u "$CONDA_BASE")"
        fi
        CONDA_PYTHON="$CONDA_BASE/bin/python"
        [[ "$IS_WINDOWS" == true ]] && CONDA_PYTHON="$CONDA_BASE/python.exe"
        if [[ -x "$CONDA_PYTHON" ]] && "$CONDA_PYTHON" -c "import sys" >/dev/null 2>&1; then
            PYTHON="$CONDA_PYTHON"
        fi
    fi
fi

if [[ -z "$PYTHON" ]]; then
    PYTHON_CANDIDATES=(
        "$HOME/miniconda3/bin/python"
        "$HOME/anaconda3/bin/python"
        "/opt/miniconda3/bin/python"
        "/opt/anaconda3/bin/python"
    )
    if [[ "$IS_WINDOWS" == true ]]; then
        PYTHON_CANDIDATES+=(
            "$HOME/miniconda3/python.exe"
            "$HOME/anaconda3/python.exe"
            "/c/ProgramData/miniconda3/python.exe"
            "/c/ProgramData/anaconda3/python.exe"
        )
    fi
    PYTHON_CANDIDATES+=(python3 python)

    for CANDIDATE in "${PYTHON_CANDIDATES[@]}"; do
        if command -v "$CANDIDATE" >/dev/null 2>&1 \
                && "$CANDIDATE" -c "import sys" >/dev/null 2>&1; then
            PYTHON="$CANDIDATE"
            break
        fi
    done
fi

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: python not found. Install miniconda: https://docs.conda.io/en/latest/miniconda.html" >&2
    exit 1
fi

if "$PYTHON" "$VIEWER_PY" "$@"; then
    exit 0
else
    STATUS=$?
fi

if [[ -t 0 ]]; then
    echo
    read -rp "Script exited with error. Press Enter to exit..."
fi
exit "$STATUS"
