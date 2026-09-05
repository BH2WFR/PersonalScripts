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

# ----- find python: prefer bundled runtime, then cheap conda path derivation -----
python_cmd=""

# 1. Bundled Python
bundled_candidates=(
    "$script_dir/deps/python/bin/python"
    "$script_dir/deps/python/python"
    "$script_dir/deps/python/python.exe"
)
for candidate in "${bundled_candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
        python_cmd="$candidate"
        break
    fi
done

# 2. Derive the base environment from CONDA_EXE / command -v conda.
# Typical layouts place conda under <base>/Scripts, <base>/condabin, or
# <base>/bin, so no subprocess is needed for the common case.
if [[ -z "$python_cmd" ]] && command -v conda >/dev/null 2>&1; then
    conda_locations=("${CONDA_EXE:-}" "$(command -v conda)")
    for conda_location in "${conda_locations[@]}"; do
        [[ -f "$conda_location" ]] || continue
        conda_parent="$(cd -- "$(dirname -- "$conda_location")" && pwd)"
        case "$(basename -- "$conda_parent")" in
            Scripts|condabin|bin) conda_base="$(dirname -- "$conda_parent")" ;;
            *) continue ;;
        esac
        [[ -d "$conda_base/conda-meta" ]] || continue
        for candidate in "$conda_base/bin/python" "$conda_base/python.exe"; do
            if [[ -x "$candidate" ]]; then
                python_cmd="$candidate"
                break 2
            fi
        done
    done
fi

# 3. Check common base-environment locations without starting conda.
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
    for candidate in "${python_candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            python_cmd="$candidate"
            break
        fi
    done
fi

# 4. Slow but authoritative fallback for non-standard Conda layouts.
if [[ -z "$python_cmd" ]] && command -v conda >/dev/null 2>&1; then
    conda_base="$(conda info --base 2>/dev/null || true)"
    if [[ -n "$conda_base" ]]; then
        for candidate in "$conda_base/bin/python" "$conda_base/python.exe"; do
            if [[ -x "$candidate" ]]; then
                python_cmd="$candidate"
                break
            fi
        done
    fi
fi

# 5. Last-resort system candidates.
if [[ -z "$python_cmd" ]]; then
    for candidate in python3 python; do
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
