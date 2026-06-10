#!/usr/bin/env python3
"""Unified script launcher for PersonalScripts.

Usage:
    python run-script.py                  # interactive: list & select
    python run-script.py --list           # list scripts and exit
    python run-script.py <script-name>    # run script by name
"""

import sys
import os
import subprocess
import importlib.util
from typing import Optional

from utils import Utils, FLYellow, FLGreen, FLCyan, FLRed, FGray, CRst

# ============ Helpers ============

def _get_script_dir() -> str:
    """Directory containing this launcher (works in source and Nuitka-compiled modes)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _detect_platform() -> tuple[bool, bool, bool]:
    """Return (is_windows, is_macos, is_linux)."""
    name = sys.platform
    if name == "darwin":
        return False, True, False
    if name == "linux":
        return False, False, True
    if name in ("win32", "cygwin", "msys"):
        return True, False, False
    return False, False, False


def _get_excluded_dirs() -> set[str]:
    """Return directories excluded from script discovery and resolution."""
    is_win, is_mac, is_linux = _detect_platform()
    exclude_dirs = {"utils", "BUILD", "__pycache__", ".git", ".venv", "node_modules", ".idea", "dist", "INSTALL"}
    if not is_win:
        exclude_dirs.add("windows")
    if not is_mac:
        exclude_dirs.add("macos")
    if not is_linux:
        exclude_dirs.add("linux")
    return exclude_dirs


_LAUNCHER_NAMES = {"run-script.py", "run-script.sh", "run-script.ps1"}


def _is_valid_script(script_dir: str, script_path: str) -> bool:
    """Return True if *script_path* is not a launcher file and not in an excluded dir."""
    rel = os.path.relpath(script_path, script_dir)
    parts = rel.replace("\\", "/").split("/")
    if len(parts) == 1 and parts[0] in _LAUNCHER_NAMES:
        return False
    exclude_dirs = _get_excluded_dirs()
    for part in parts[:-1]:
        if part in exclude_dirs:
            return False
    return True


# ============ Interpreter Discovery ============

# ============ Script Discovery ============

def _prefer_py_over_alt(paths: list[str], alt_ext: str) -> list[str]:
    """If both foo.py and foo.<alt_ext> exist, keep only foo.py."""
    result: list[str] = []
    for p in paths:
        if p.endswith(alt_ext):
            py_path = p[: -len(alt_ext)] + ".py"
            if os.path.isfile(py_path):
                continue
        result.append(p)
    return result


def find_scripts(script_dir: str) -> list[str]:
    """Find all runnable scripts, returning relative paths from script_dir.

    Excludes:
      - __init__.py (any depth)
      - run-script.py / run-script.sh / run-script.ps1 (root only)
      - utils/, BUILD/, __pycache__/, .git/, .venv/, node_modules/, .idea/, dist/
      - platform directories that don't match the current OS
      - .sh scripts if bash is not available
      - .ps1 scripts if pwsh is not available
    """
    exclude_dirs = _get_excluded_dirs()

    has_bash = Utils.find_bash() is not None
    has_pwsh = Utils.find_pwsh() is not None

    extensions: list[str] = [".py"]
    if has_bash:
        extensions.append(".sh")
    if has_pwsh:
        extensions.append(".ps1")

    scripts: list[str] = []

    for root, dirs, files in os.walk(script_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for f in files:
            if f.startswith("_"):
                continue
            if root == script_dir and f in _LAUNCHER_NAMES:
                continue
            if any(f.endswith(ext) for ext in extensions):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, script_dir)
                scripts.append(rel)

    scripts.sort()

    if has_bash:
        scripts = _prefer_py_over_alt(scripts, ".sh")
    if has_pwsh:
        scripts = _prefer_py_over_alt(scripts, ".ps1")

    return scripts


# ============ Script Resolution ============

def resolve_script_path(script_dir: str, name: str) -> Optional[str]:
    """Resolve a user-supplied script name to a full path.

    Handles:
      - Full path (absolute)
      - Relative path with extension (e.g. macos/screen-utils.py)
      - Name without extension → tries .py first, then platform-preferred fallback:
        Windows: .ps1 → .sh (if bash available)
        macOS / Linux: .sh → .ps1 (if pwsh available)

    Returns ``None`` when the name matches a launcher file or an excluded
    directory.
    """
    name = name.replace("\\", "/").lstrip("/")

    if os.path.isabs(name):
        if os.path.isfile(name) and _is_valid_script(script_dir, name):
            return name
        return None

    if name.endswith((".py", ".sh", ".ps1")):
        candidate = os.path.join(script_dir, name)
        if os.path.isfile(candidate) and _is_valid_script(script_dir, candidate):
            return candidate
        return None

    # No extension → try .py first (always preferred)
    py_candidate = os.path.join(script_dir, name + ".py")
    if os.path.isfile(py_candidate) and _is_valid_script(script_dir, py_candidate):
        return py_candidate

    # Platform-specific fallback
    is_win, _, _ = _detect_platform()
    if is_win:
        ps1_candidate = os.path.join(script_dir, name + ".ps1")
        if os.path.isfile(ps1_candidate) and _is_valid_script(script_dir, ps1_candidate):
            return ps1_candidate
        if Utils.find_bash() is not None:
            sh_candidate = os.path.join(script_dir, name + ".sh")
            if os.path.isfile(sh_candidate) and _is_valid_script(script_dir, sh_candidate):
                return sh_candidate
    else:
        sh_candidate = os.path.join(script_dir, name + ".sh")
        if os.path.isfile(sh_candidate) and _is_valid_script(script_dir, sh_candidate):
            return sh_candidate
        if Utils.find_pwsh() is not None:
            ps1_candidate = os.path.join(script_dir, name + ".ps1")
            if os.path.isfile(ps1_candidate) and _is_valid_script(script_dir, ps1_candidate):
                return ps1_candidate

    # Final fallback for error reporting
    final = os.path.join(script_dir, name + ".py")
    if os.path.isfile(final) and not _is_valid_script(script_dir, final):
        return None
    return final


# ============ Display ============

def _script_color(path: str) -> str:
    if path.endswith(".py"):
        return FLCyan
    if path.endswith(".sh"):
        return FLGreen
    return FLGreen  # .ps1


def show_scripts(script_dir: str, scripts: list[str]) -> list[str]:
    """Print the numbered script list. Returns the flat list of relative paths."""
    if not scripts:
        print(f"No scripts found in: `{script_dir}`")
        return []

    root_scripts = [s for s in scripts if os.sep not in s]
    sub_scripts = [s for s in scripts if os.sep in s]

    # Build dynamic type label
    types: list[str] = []
    if any(s.endswith(".py") for s in scripts):
        types.append(f"{FLCyan}python{CRst}")
    if any(s.endswith(".sh") for s in scripts):
        types.append(f"{FLGreen}bash{CRst}")
    if any(s.endswith(".ps1") for s in scripts):
        types.append(f"{FLGreen}PowerShell{CRst}")
    type_str = " / ".join(types) if types else "scripts"

    
    Utils.print_separator(width=60, color_ansi_esc=None, indent=2)
    
    print(f"  Available {type_str} scripts in `{FGray}{script_dir}{CRst}`:\n")
    
    all_scripts: list[str] = []
    cnt = 0

    for rel in root_scripts:
        color = _script_color(rel)
        fname = os.path.basename(rel)
        print(f"  {FGray}[{cnt}]{CRst}:  {color}{fname}{CRst}")
        all_scripts.append(rel)
        cnt += 1

    if sub_scripts:
        print()
        print(f"  {FLYellow}─── Subfolders ───{CRst}")
        for rel in sub_scripts:
            color = _script_color(rel)
            subdir = os.path.dirname(rel)
            fname = os.path.basename(rel)
            if cnt < 10:
                print(f"  {FGray}[{cnt}]{CRst}:  {FLYellow}{subdir}{CRst}/{color}{fname}{CRst}")
            else:
                print(f"  {FGray}[{cnt}]{CRst}: {FLYellow}{subdir}{CRst}/{color}{fname}{CRst}")
            all_scripts.append(rel)
            cnt += 1
    
    Utils.print_separator(width=60, color_ansi_esc=None, indent=2)
    
    return all_scripts


# ============ Script Execution ============

def run_py_script(script_path: str) -> int:
    """Load and execute a .py script via importlib, calling its main().

    The target script reads arguments from sys.argv, which must be set up
    by the caller before invoking this function.
    """
    abs_path = os.path.abspath(script_path)

    module_name = "_entry_" + abs_path \
        .replace(os.sep, "_") \
        .replace(".", "_") \
        .replace("-", "_") \
        .lstrip("_")

    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        print(f"{FLRed}Cannot load script: {abs_path}{CRst}", file=sys.stderr)
        return 1

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"{FLRed}Error loading script {abs_path}: {e}{CRst}", file=sys.stderr)
        return 1

    if not hasattr(module, "main"):
        print(f"{FLRed}Script has no main() function: {abs_path}{CRst}", file=sys.stderr)
        return 1

    try:
        return module.main()
    except SystemExit as e:
        if e.code is None:
            return 0
        if isinstance(e.code, int):
            return e.code
        return 1


def run_sh_script(script_path: str, args: list[str]) -> int:
    """Execute a .sh script via bash."""
    bash = Utils.find_bash()
    if bash is None:
        print(f"{FLRed}Cannot find bash interpreter{CRst}", file=sys.stderr)
        return 1
    result = subprocess.run([bash, script_path] + args, check=False)
    return result.returncode


def run_ps1_script(script_path: str, args: list[str]) -> int:
    """Execute a .ps1 script via PowerShell."""
    pwsh = Utils.find_pwsh()
    if pwsh is None:
        print(f"{FLRed}Cannot find PowerShell interpreter (pwsh/powershell){CRst}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path] + args,
        check=False,
    )
    return result.returncode


# ============ Main ============

def main() -> int:
    Utils.print_banner("PERSONAL SCRIPT LAUNCHER")
    Utils.print_env_info()

    script_dir = _get_script_dir()

    script_name: Optional[str] = None
    remaining_args: list[str] = []

    if len(sys.argv) >= 2:
        script_name = sys.argv[1]
        remaining_args = sys.argv[2:]

    show_list = script_name is None or script_name == "--list"

    if show_list:
        scripts = find_scripts(script_dir)
        all_rel = show_scripts(script_dir, scripts)

        if script_name == "--list":
            return 0
        if "--list" in remaining_args:
            return 0
        if not all_rel:
            return 0

        print(f"\nAll of the python scripts support argument {FLCyan}--help{CRst} for usage details.")
        print(f"Examples:")
        print(f"    {FLYellow}5{CRst}                              select by number")
        print(f"    {FLYellow}5{CRst} {FLCyan}--help{CRst}                       number + passthrough args")
        print(f"    {FLYellow}test/print-argv{CRst} {FLCyan}arg1 arg2{CRst}      name + passthrough args")
        print(f"\n{FLYellow}Enter number or script name to execute{CRst} (or {FLYellow}Enter{CRst} to exit): ", end="")
        try:
            choice_line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(f"{FLGreen}Bye.{CRst}")
            return 0

        if not choice_line:
            print(f"{FLGreen}Bye.{CRst}")
            return 0

        parts = choice_line.split()
        first_token = parts[0]
        remaining_args = parts[1:]

        if first_token.isdigit():
            idx = int(first_token)
            if idx < 0 or idx >= len(all_rel):
                print(f"{FLRed}Invalid selection: {idx}{CRst}", file=sys.stderr)
                return 1
            script_name = all_rel[idx]
        else:
            script_name = first_token

    assert script_name is not None

    script_path: str
    if os.path.isfile(script_name):
        script_path = script_name
    else:
        resolved = resolve_script_path(script_dir, script_name)
        if resolved is None or not os.path.isfile(resolved):
            normalized = script_name.replace("\\", "/").lstrip("/")
            if not normalized.endswith((".py", ".sh", ".ps1")):
                print(
                    f"{FLRed}Cannot find script: "
                    f"`{os.path.join(script_dir, normalized + '.py')}` (preferred) "
                    f"or `{os.path.join(script_dir, normalized + '.sh')}`{CRst}",
                    file=sys.stderr,
                )
            else:
                print(f"{FLRed}Cannot find script: `{os.path.join(script_dir, normalized)}`{CRst}", file=sys.stderr)
            return 1
        script_path = resolved

    if os.path.abspath(script_path) == os.path.abspath(__file__):
        print(f"{FLRed}Refusing to run itself: `{script_path}`{CRst}", file=sys.stderr)
        return 1

    sys.argv = [script_path] + remaining_args

    print(f"{FLYellow}Resolved script path:{CRst} {FLGreen}{script_path}{CRst}")

    if script_path.endswith(".py"):
        print()
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        return run_py_script(script_path)

    if script_path.endswith(".sh"):
        print()
        return run_sh_script(script_path, remaining_args)

    if script_path.endswith(".ps1"):
        print()
        return run_ps1_script(script_path, remaining_args)

    ext = os.path.splitext(script_path)[1]
    print(f"{FLRed}Unsupported script type: `{ext}`{CRst}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
