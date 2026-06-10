#!/bin/sh
set -eu

esc="$(printf '\033')"
FLYellow="${esc}[33m"
FLGreen="${esc}[32m"
FLCyan="${esc}[36m"
FGray="${esc}[90m"
CRst="${esc}[0m"

resolve_script_path() {
  # Best-effort absolute path without requiring realpath/readlink -f.
  case "$0" in
    */*)
      dir="$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd -P 2>/dev/null || pwd)"
      printf '%s/%s\n' "$dir" "$(basename "$0")"
      ;;
    *)
      p="$(command -v "$0" 2>/dev/null || true)"
      if [ -n "$p" ] && [ "$p" != "$0" ] && [ "${p#*/}" != "$p" ]; then
        dir="$(CDPATH= cd "$(dirname "$p")" 2>/dev/null && pwd -P 2>/dev/null || pwd)"
        printf '%s/%s\n' "$dir" "$(basename "$p")"
      else
        printf '%s\n' "$0"
      fi
      ;;
  esac
}

printf '%s\n' "${FLYellow}Command line arguments:${CRst}"

script_path="$(resolve_script_path)"
bash_path="$(command -v bash 2>/dev/null || command -v sh 2>/dev/null || printf 'unknown')"
printf '%s\n' "${FLCyan}Interpreter:${CRst}  ${FLGreen}bash${CRst}  ${FGray}${bash_path}${CRst}"
printf '%s\n' "  PATH: ${FLGreen}${script_path}${CRst}"

i=0
for arg in "$@"; do
  printf '%s\n' "  argv[${FLYellow}${i}${CRst}]: ${FLCyan}${arg}${CRst}"
  i=$((i + 1))
done
