#!/usr/bin/env python3
"""Unified script launcher for PersonalScripts.

Usage:
    python run-script.py                  # interactive: list & select
    python run-script.py --list           # list scripts and exit
    python run-script.py <script-name>    # run script by name
"""

import sys
import os
import shutil
import subprocess
import importlib.util

# ============ ANSI Colors (inline, no dependency on utils) ============
#* 不依赖 utils（避免自举问题）
FLYellow = "\033[93m"
FLGreen  = "\033[92m"
FLCyan   = "\033[96m"
FLRed    = "\033[91m"
FGray    = "\033[90m"
CRst     = "\033[0m"

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


# ============ Interpreter Discovery ============

def _find_bash() -> str | None:
    """Find a bash executable. Returns path or None."""
    is_win, _, _ = _detect_platform()
    if is_win:
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\msys64\usr\bin\bash.exe",
            r"C:\cygwin64\bin\bash.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
    found = shutil.which("bash")
    return found if found else None


def _find_pwsh() -> str | None:
    """Find a PowerShell executable. Returns path or None."""
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    return None


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
    is_win, is_mac, is_linux = _detect_platform()

    exclude_dirs = {"utils", "BUILD", "__pycache__", ".git", ".venv", "node_modules", ".idea", "dist"}

    if not is_win:
        exclude_dirs.add("windows")
    if not is_mac:
        exclude_dirs.add("macos")
    if not is_linux:
        exclude_dirs.add("linux")

    has_bash = _find_bash() is not None
    has_pwsh = _find_pwsh() is not None

    extensions: list[str] = [".py"]
    if has_bash:
        extensions.append(".sh")
    if has_pwsh:
        extensions.append(".ps1")

    scripts: list[str] = []
    _launcher_names = {"run-script.py", "run-script.sh", "run-script.ps1"}

    for root, dirs, files in os.walk(script_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for f in files:
            if f.startswith("_"):
                continue
            if root == script_dir and f in _launcher_names:
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

def resolve_script_path(script_dir: str, name: str) -> str | None:
    """Resolve a user-supplied script name to a full path.

    Handles:
      - Full path (absolute)
      - Relative path with extension (e.g. macos/screen-utils.py)
      - Name without extension → tries .py then .sh/.ps1
    """
    name = name.replace("\\", "/").lstrip("/")

    if os.path.isabs(name):
        if os.path.isfile(name):
            return name
        return None

    if name.endswith((".py", ".sh", ".ps1")):
        candidate = os.path.join(script_dir, name)
        if os.path.isfile(candidate):
            return candidate
        return None

    for ext in (".py", ".sh", ".ps1"):
        candidate = os.path.join(script_dir, name + ext)
        if os.path.isfile(candidate):
            return candidate

    return os.path.join(script_dir, name + ".py")


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

    print(f"{FLYellow}================== PERSONAL SCRIPTS ===================={CRst}")
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
        print(f"  {FLYellow}--- Subfolders ---{CRst}")
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
    bash = _find_bash()
    if bash is None:
        print(f"{FLRed}Cannot find bash interpreter{CRst}", file=sys.stderr)
        return 1
    result = subprocess.run([bash, script_path] + args, check=False)
    return result.returncode


def run_ps1_script(script_path: str, args: list[str]) -> int:
    """Execute a .ps1 script via PowerShell."""
    pwsh = _find_pwsh()
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
    script_dir = _get_script_dir()

    script_name: str | None = None
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

        print(f"\n{FGray}Examples:{CRst}")
        print(f"  {FLCyan}5{CRst}                         select by number")
        print(f"  {FLCyan}5 --help{CRst}                 number + passthrough args")
        print(f"  {FLCyan}webserver-run.py --port 9000{CRst}   name + passthrough args")
        print(f"\n{FLYellow}Enter number or script name to execute{CRst} (or {FLYellow}Enter{CRst} to exit): ", end="")
        try:
            choice_line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not choice_line:
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
