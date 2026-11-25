#!/usr/bin/env bash
# Locate Python once, then pass the original arguments to the launcher.
set -eo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) windows=true ;;
    *) windows=false ;;
esac

config_home() {
    if [[ $windows == true ]]; then
        cygpath -u "${USERPROFILE:-$HOME}"
    elif [[ $EUID == 0 && -n ${SUDO_UID:-} && $SUDO_UID != 0 ]]; then
        if [[ $(uname -s) == Darwin ]]; then
            dscacheutil -q user -a uid "$SUDO_UID" | sed -n 's/^dir: //p'
        else
            getent passwd "$SUDO_UID" | cut -d: -f6
        fi
    else
        printf '%s\n' "$HOME"
    fi
}

python_cmd=""
for relative in deps/python/bin/python deps/python/bin/python3 deps/python/python deps/python/python.exe; do
    if [[ -f "$script_dir/$relative" && -x "$script_dir/$relative" ]]; then
        python_cmd="$script_dir/$relative"
        unset PYTHONHOME
        export PYTHONNOUSERSITE=1 PYTHONPATH="$script_dir"
        export PATH="$(dirname -- "$python_cmd"):$PATH"
        if [[ $windows == true ]]; then
            export PATH="$script_dir/deps/python/Scripts:$PATH"
        fi
        exec "$python_cmd" "$script_dir/run-script.py" "$@"
    fi
done

conda_cmd="${CONDA_EXE:-}"
if [[ ! -f $conda_cmd || ! -x $conda_cmd ]]; then
    conda_cmd=conda
fi
if command -v "$conda_cmd" >/dev/null 2>&1; then
    user_home="$(config_home)"
    if [[ -z $user_home ]]; then
        echo 'Cannot resolve the invoking user home directory.' >&2
        exit 1
    fi
    config_file="$user_home/.config/PersonalScripts/conda-env.txt"
    name=base
    if [[ -e $config_file ]]; then
        value="$(cat -- "$config_file")"
        value="${value#$'\xef\xbb\xbf'}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        name="${value:-base}"
    fi
    case "$name" in
        -*|*/*|*\\*|*$'\r'*|*$'\n'*) echo "Expected one Conda environment name in $config_file." >&2; exit 1 ;;
    esac
    if [[ $name == base ]]; then
        conda_path="$(command -v "$conda_cmd")"
        if [[ $windows == true && -f $conda_path ]]; then
            conda_path="$(cygpath -u "$conda_path")"
        fi
        if [[ -f $conda_path && -d "$(dirname -- "$conda_path")/../conda-meta" ]]; then
            prefix="$(cd -- "$(dirname -- "$conda_path")/.." && pwd)"
        else
            prefix="$("$conda_cmd" info --base)"
        fi
    else
        prefix="$("$conda_cmd" run --no-capture-output -n "$name" python -c "import os; print(os.environ['CONDA_PREFIX'])")"
    fi
    prefix="${prefix%$'\r'}"
    if [[ -z $prefix ]]; then
        echo "Cannot locate Conda environment '$name' ($config_file)." >&2
        exit 1
    fi
    if [[ $windows == true ]]; then
        python_cmd="$(cygpath -u "$prefix")/python.exe"
    else
        python_cmd="$prefix/bin/python"
    fi
    if [[ ! -f $python_cmd || ! -x $python_cmd ]]; then
        echo "No Python in Conda environment '$name' at $python_cmd." >&2
        exit 1
    fi
else
    python_cmd="$(command -v python3 || command -v python || true)"
fi

if [[ -z $python_cmd ]]; then
    echo 'Cannot find bundled Python, Conda, or Python on PATH.' >&2
    exit 1
fi
export PYTHONPATH="$script_dir${PYTHONPATH:+:${PYTHONPATH}}"
exec "$python_cmd" "$script_dir/run-script.py" "$@"
