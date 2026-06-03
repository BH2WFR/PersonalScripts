#!/usr/bin/env bash
# ============================================
#  npy/npz file viewer launcher (Linux/macOS)
#  Usage:
#    double-click a .npy/.npz file (after setting
#    this script as the default opener), or
#    ./npy-viewer.sh <file.npy>
#
#  macOS: right-click .npy → Get Info → Open With
#         → select this script → Change All
#  Linux: right-click .npy → Open With → select
#         this script → set as default
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VIEWER_PY="$SCRIPT_DIR/npy-viewer.py"

# Find python: prefer conda, fall back to python3
if   command -v "$HOME/miniconda3/bin/python" &>/dev/null; then
    PYTHON="$HOME/miniconda3/bin/python"
elif command -v "$HOME/anaconda3/bin/python" &>/dev/null; then
    PYTHON="$HOME/anaconda3/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "ERROR: python not found. Install miniconda: https://docs.conda.io/en/latest/miniconda.html" >&2
    read -rp "Press Enter to exit..."
    exit 1
fi

if [ $# -ge 1 ] && [ -n "$1" ]; then
    "$PYTHON" "$VIEWER_PY" "$1"
else
    "$PYTHON" "$VIEWER_PY"
fi

if [ $? -ne 0 ]; then
    echo ""
    read -rp "Script exited with error. Press Enter to exit..."
fi
