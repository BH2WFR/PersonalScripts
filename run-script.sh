#!/usr/bin/env bash
# Thin wrapper: find Python, then delegate to run-script.py with all arguments.

set -eo pipefail

esc=$'\033'
FLRed="${esc}[31m"
FGray="${esc}[90m"
CRst="${esc}[0m"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# ----- platform flag for conda path resolution -----
_os_name="$(uname -s)"
case "$_os_name" in
    MINGW*|MSYS*|CYGWIN*) _is_windows=true  ;;
    *)                     _is_windows=false ;;
esac

# ----- find python: prefer conda command, then known paths, then system python3/python -----
python_cmd=""

# 1. Try conda info --base (most reliable)
if command -v conda >/dev/null 2>&1; then
    conda_base="$(conda info --base 2>/dev/null || true)"
    if [[ -n "$conda_base" ]]; then
        conda_py="$conda_base/bin/python"
        [[ "$_is_windows" == "true" ]] && conda_py="$conda_base/python.exe"
        [[ -x "$conda_py" ]] && python_cmd="$conda_py"
    fi
fi

# 2. Fallback: known paths
if [[ -z "$python_cmd" ]]; then
    python_candidates=(
        "$HOME/miniconda3/bin/python"
        "$HOME/anaconda3/bin/python"
        "/opt/miniconda3/bin/python"
        "/opt/anaconda3/bin/python"
    )
    if [[ "$_is_windows" == "true" ]]; then
        python_candidates+=(
            "${USERPROFILE:-$HOME}/miniconda3/python.exe"
            "${USERPROFILE:-$HOME}/anaconda3/python.exe"
            "${PROGRAMDATA:-}/miniconda3/python.exe"
            "${PROGRAMDATA:-}/anaconda3/python.exe"
        )
    fi
    python_candidates+=(python3 python)

    for candidate in "${python_candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1; then
            python_cmd="$candidate"
            break
        fi
    done
fi
if [[ -z "$python_cmd" ]]; then
    printf '%bCannot find python (miniconda/anaconda/python3).%b\n' "$FLRed" "$CRst" >&2
    printf 'Install miniconda: %bhttps://docs.conda.io/en/latest/miniconda.html%b\n' "$FGray" "$CRst" >&2
    exit 1
fi

# ----- delegate to run-script.py -----
export PYTHONPATH="$script_dir${PYTHONPATH:+:${PYTHONPATH}}"
exec "$python_cmd" "$script_dir/run-script.py" "$@"
