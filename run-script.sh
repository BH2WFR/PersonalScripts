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
            ! -path "*/windows/*" \
            | sort
    )

    if [[ "${#scripts[@]}" -eq 0 ]]; then
        printf 'No Python/Shell scripts found in: `%s`:\n' "$script_dir"
        return 1
    fi

    # Separate root-level and subfolder scripts
    local root_scripts=()
    local sub_scripts=()
    for full_path in "${scripts[@]}"; do
        local rel_dir
        rel_dir="$(dirname -- "$full_path")"
        if [[ "$rel_dir" == "$script_dir" ]]; then
            root_scripts+=("$full_path")
        else
            sub_scripts+=("$full_path")
        fi
    done

    printf 'Supported scripts in: `%s`:\n' "$script_dir"

    local cnt=0
    local full_path relative_path file_name color

    for full_path in "${root_scripts[@]}"; do
        relative_path="$(get_relative_script_path "$full_path")"
        file_name="$(basename -- "$relative_path")"
        if [[ "$full_path" =~ \.py$ ]]; then
            color="$FLCyan"
        else
            color="$FLGreen"
        fi
        printf '  %b[%d]%b: %b%s%b\n' "$FGray" "$cnt" "$CRst" "$color" "$file_name$CRst"
        cnt=$((cnt + 1))
    done

    if [[ "${#sub_scripts[@]}" -gt 0 ]]; then
        printf '\n'
        printf '  %b--- Subfolders ---%b\n' "$FLYellow" "$CRst"
        for full_path in "${sub_scripts[@]}"; do
            relative_path="$(get_relative_script_path "$full_path")"
            file_name="$(basename -- "$relative_path")"
            local relative_directory
            relative_directory="$(dirname -- "$relative_path")"
            if [[ "$full_path" =~ \.py$ ]]; then
                color="$FLCyan"
            else
                color="$FLGreen"
            fi
            printf '  %b[%d]%b: %b%s%b/%b%s%b\n' "$FGray" "$cnt" "$CRst" "$FLYellow" "$relative_directory" "$CRst" "$color" "$file_name$CRst"
            cnt=$((cnt + 1))
        done
    fi

    # Return all scripts as a combined array via a global variable
    ALL_SCRIPTS=("${root_scripts[@]}" "${sub_scripts[@]}")
    return 0
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

ALL_SCRIPTS=()

if [[ "$show_list" == true ]]; then
    show_supported_scripts
    ret=$?
    if [[ "$script_name" == "--list" ]]; then
        exit 0
    fi
    for arg in "${remaining_args[@]}"; do
        if [[ "$arg" == "--list" ]]; then
            exit 0
        fi
    done

    if [[ $ret -ne 0 ]]; then
        exit 0
    fi

    printf '\n%bEnter number to execute (or Enter to exit):%b ' "$FLYellow" "$CRst"
    read -r choice
    if [[ -z "$choice" ]]; then
        exit 0
    fi
    if [[ ! "$choice" =~ ^[0-9]+$ ]] || [[ "$choice" -ge "${#ALL_SCRIPTS[@]}" ]]; then
        printf '%bInvalid selection: %s%b\n' "$FLRed" "$choice" "$CRst" >&2
        exit 1
    fi
    script_name="${ALL_SCRIPTS[$choice]}"
    remaining_args=()
fi

if [[ -f "$script_name" ]]; then
    script_path="$script_name"
else
    script_path="$(resolve_script_path "$script_name")"
fi

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

printf '%bResolved script path:%b %b%s%b\n\n' "$FLYellow" "$CRst" "$FLGreen" "$script_path" "$CRst"

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

    # Find python command: prefer miniconda/anaconda, then python3
    python_cmd=""
    for candidate in \
        "$HOME/miniconda3/bin/python" \
        "$HOME/anaconda3/bin/python" \
        "/opt/miniconda3/bin/python" \
        "/opt/anaconda3/bin/python" \
        python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            python_cmd="$candidate"
            break
        fi
    done
    if [[ -z "$python_cmd" ]]; then
        printf '%bCannot find python (miniconda/anaconda/python3)%b\n' "$FLRed" "$CRst" >&2
        exit 1
    fi

    # If using system python3 (not conda), auto-create .venv for isolated packages
    if [[ "$python_cmd" == "python3" ]]; then
        VENV_DIR="$script_dir/.venv"
        if [[ ! -f "$VENV_DIR/bin/python" ]]; then
            printf '%bCreating virtual environment at: %s%b\n' "$FLYellow" "$VENV_DIR" "$CRst"
            python3 -m venv "$VENV_DIR" 2>/dev/null || {
                # If venv fails (missing python3-venv), try without pip and bootstrap
                python3 -m venv --without-pip "$VENV_DIR"
                "$VENV_DIR/bin/python" -m ensurepip --upgrade 2>/dev/null || true
            }
            if [[ ! -f "$VENV_DIR/bin/pip" && ! -f "$VENV_DIR/bin/pip3" ]]; then
                printf '%bCannot install pip in venv. Run: sudo apt install python3-venv python3-pip%b\n' "$FLRed" "$CRst" >&2
                rm -rf "$VENV_DIR"
                exit 1
            fi
        fi
        python_cmd="$VENV_DIR/bin/python"
        export PYTHONPATH="$script_dir${PYTHONPATH:+:$PYTHONPATH}"
    fi

    "$python_cmd" "$python_script_path" "${remaining_args[@]}"
    exit $?
fi

if [[ "$ext" == "sh" ]]; then
    bash_exe="${BASH:-bash}"
    "$bash_exe" "$script_path" "${remaining_args[@]}"
    exit $?
fi

printf '%bUnsupported script type: `%s`%b\n' "$FLRed" ".$ext" "$CRst" >&2
exit 1
