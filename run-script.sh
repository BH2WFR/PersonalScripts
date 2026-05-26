#!/usr/bin/env bash

set -eo pipefail

esc=$'\033'
FLYellow="${esc}[33m"
FLGreen="${esc}[32m"
FLCyan="${esc}[36m"
FLRed="${esc}[31m"
FGray="${esc}[90m"
CRst="${esc}[0m"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
script_self="$script_dir/$(basename -- "${BASH_SOURCE[0]}")"

get_relative_script_path() {
    local full_path="$1"
    local relative_path="${full_path#"$script_dir"/}"
    printf '%s\n' "${relative_path//\\//}"
}

resolve_script_path() {
    local requested_script_name="$1"
    local normalized_script_name="${requested_script_name//\\//}"
    normalized_script_name="${normalized_script_name#/}"

    if [[ "$normalized_script_name" =~ \.py$ || "$normalized_script_name" =~ \.sh$ ]]; then
        printf '%s/%s\n' "$script_dir" "$normalized_script_name"
        return
    fi

    local candidate_py="$script_dir/${normalized_script_name}.py"
    if [[ -f "$candidate_py" ]]; then
        printf '%s\n' "$candidate_py"
        return
    fi

    local candidate_sh="$script_dir/${normalized_script_name}.sh"
    if [[ -f "$candidate_sh" ]]; then
        printf '%s\n' "$candidate_sh"
        return
    fi

    # Default to .py for a clearer error message, while still preferring .py when both exist.
    printf '%s\n' "$candidate_py"
}

show_supported_scripts() {
    local scripts=()
    local line
    while IFS= read -r line; do
        scripts+=("$line")
    done < <(
        find "$script_dir" -type f \( -name '*.py' -o -name '*.sh' \) \
            ! -name '__init__.py' \
            ! -path "$script_self" \
            | sort
    )

    if [[ "${#scripts[@]}" -eq 0 ]]; then
        printf 'No Python/Shell scripts found in: `%s`:\n' "$script_dir"
        return
    fi

    printf 'Supported scripts in: `%s`:\n' "$script_dir"

    local cnt=0
    local full_path relative_path file_name relative_directory color
    for full_path in "${scripts[@]}"; do
        relative_path="$(get_relative_script_path "$full_path")"
        file_name="$(basename -- "$relative_path")"
        relative_directory="$(dirname -- "$relative_path")"
        if [[ "$relative_directory" == "." ]]; then
            relative_directory=""
        else
            relative_directory="${FLYellow}${relative_directory}${CRst}/"
        fi

        if [[ "$full_path" =~ \.py$ ]]; then
            color="$FLCyan"
        else
            color="$FLGreen"
        fi
        printf '  %b[%d]%b: %b%b%b\n' "$FGray" "$cnt" "$CRst" "$relative_directory" "$color" "$file_name$CRst"
        cnt=$((cnt + 1))
    done
}

script_name="${1-}"
if [[ $# -gt 0 ]]; then
    shift
fi
remaining_args=("$@")

show_list=false
if [[ -z "$script_name" || "$script_name" == "--list" ]]; then
    show_list=true
else
    for arg in "${remaining_args[@]}"; do
        if [[ "$arg" == "--list" ]]; then
            show_list=true
            break
        fi
    done
fi

if [[ "$show_list" == true ]]; then
    show_supported_scripts
    exit 0
fi

script_path="$(resolve_script_path "$script_name")"

if [[ "$script_path" == "$script_self" ]]; then
    printf '%bRefusing to run itself: `%s`%b\n' "$FLRed" "$script_path" "$CRst" >&2
    exit 1
fi

if [[ ! -f "$script_path" ]]; then
    normalized_script_name="${script_name//\\//}"
    normalized_script_name="${normalized_script_name#/}"

    if [[ ! "$normalized_script_name" =~ \.py$ && ! "$normalized_script_name" =~ \.sh$ ]]; then
        candidate_py="$script_dir/${normalized_script_name}.py"
        candidate_sh="$script_dir/${normalized_script_name}.sh"
        printf '%bCannot find script: `%s` (preferred) or `%s`%b\n' "$FLRed" "$candidate_py" "$candidate_sh" "$CRst" >&2
    else
        printf '%bCannot find script: `%s`%b\n' "$FLRed" "$script_path" "$CRst" >&2
    fi
    exit 1
fi

printf '%bResolved script path:%b %b%s%b\n' "$FLYellow" "$CRst" "$FLGreen" "$script_path" "$CRst"

ext="${script_path##*.}"
if [[ "$ext" == "py" ]]; then
    if command -v cygpath >/dev/null 2>&1; then
        pathsep=';'
        export PYTHONPATH="$(cygpath -w "$script_dir")${PYTHONPATH:+${pathsep}${PYTHONPATH}}"
        python_script_path="$(cygpath -w "$script_path")"
    else
        pathsep=':'
        export PYTHONPATH="$script_dir${PYTHONPATH:+${pathsep}${PYTHONPATH}}"
        python_script_path="$script_path"
    fi

    python "$python_script_path" "${remaining_args[@]}"
    exit $?
fi

if [[ "$ext" == "sh" ]]; then
    bash_exe="${BASH:-bash}"
    "$bash_exe" "$script_path" "${remaining_args[@]}"
    exit $?
fi

printf '%bUnsupported script type: `%s`%b\n' "$FLRed" ".$ext" "$CRst" >&2
exit 1
