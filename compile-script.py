#!/usr/bin/env python3
"""Compile any Python script in the project into a standalone executable.

Usage:
    python compile-script.py

Lists all Python scripts in the project, lets you choose one by number,
then compiles it with Nuitka or PyInstaller. Output goes to BUILD/ with
directory structure preserved (e.g. BUILD/link-create_nuitka/).
"""

import sys
import os
import subprocess
import shutil

from utils import *


# ============ Helpers ============

def _get_script_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _detect_platform() -> tuple[bool, bool, bool]:
    name = sys.platform
    if name == "darwin":
        return False, True, False
    if name == "linux":
        return False, False, True
    if name in ("win32", "cygwin", "msys"):
        return True, False, False
    return False, False, False


def _get_excluded_dirs() -> set[str]:
    is_win, is_mac, is_linux = _detect_platform()
    exclude_dirs = {"utils", "BUILD", "__pycache__", ".git", ".venv", "node_modules", ".idea", "dist", "INSTALL"}
    if not is_win:
        exclude_dirs.add("windows")
    if not is_mac:
        exclude_dirs.add("macos")
    if not is_linux:
        exclude_dirs.add("linux")
    return exclude_dirs


# Scripts that are launchers or the compiler itself — hidden from the list.
_SKIP_NAMES = {"run-script.py", "run-script.sh", "run-script.ps1", "compile-script.py"}


def find_py_scripts(script_dir: str) -> list[str]:
    """Find all .py scripts, excluding launchers, self, and excluded dirs."""
    exclude_dirs = _get_excluded_dirs()
    scripts: list[str] = []

    for root, dirs, files in os.walk(script_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for f in files:
            if f.startswith("_"):
                continue
            if not f.endswith(".py"):
                continue
            if root == script_dir and f in _SKIP_NAMES:
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, script_dir)
            scripts.append(rel)

    scripts.sort()
    return scripts


# ============ Display ============

def show_scripts(script_dir: str, scripts: list[str]) -> list[str]:
    if not scripts:
        print(f"No Python scripts found in: `{script_dir}`")
        return []

    root_scripts = [s for s in scripts if os.sep not in s]
    sub_scripts = [s for s in scripts if os.sep in s]

    Utils.print_separator(width=60, color_ansi_esc=None, indent=2)
    print(f"  Available Python scripts in `{FGray}{script_dir}{CRst}`:\n")

    total = len(scripts)
    max_digits = len(str(total - 1)) if total > 0 else 1

    all_scripts: list[str] = []
    cnt = 0

    for rel in root_scripts:
        fname = os.path.basename(rel)
        print(f"  {FGray}[{cnt:>{max_digits}}]{CRst}: {FLCyan}{fname}{CRst}")
        all_scripts.append(rel)
        cnt += 1

    if sub_scripts:
        print()
        print(f"  {FLYellow}─── Subfolders ───{CRst}")
        for rel in sub_scripts:
            subdir = os.path.dirname(rel)
            fname = os.path.basename(rel)
            print(f"  {FGray}[{cnt:>{max_digits}}]{CRst}: {FLYellow}{subdir}{CRst}/{FLCyan}{fname}{CRst}")
            all_scripts.append(rel)
            cnt += 1

    Utils.print_separator(width=60, color_ansi_esc=None, indent=2)

    return all_scripts


# ============ Tool selection ============

def _check_tool(name: str) -> bool:
    """Check whether *name* is importable via ``python -m {name}``."""
    try:
        subprocess.run(
            [sys.executable, "-m", name, "--version"],
            capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def choose_tool() -> str:
    """Ask the user to pick Nuitka or PyInstaller. Returns ``"nuitka"`` or ``"pyinstaller"``."""
    nuitka_ok = _check_tool("nuitka")
    pyinst_ok = _check_tool("PyInstaller")

    if not nuitka_ok and not pyinst_ok:
        print(f"{FLRed}Neither Nuitka nor PyInstaller is installed.{CRst}")
        print(f"{FGray}  pip install nuitka   # for Nuitka{CRst}")
        print(f"{FGray}  pip install pyinstaller   # for PyInstaller{CRst}")
        sys.exit(1)

    opts: list[tuple[str, str, str, bool]] = [
        ("n", "nuitka",     "Nuitka (C compiler, slower build, faster runtime)", nuitka_ok),
        ("p", "pyinstaller","PyInstaller (pure Python, faster build, larger output)", pyinst_ok),
    ]

    if not nuitka_ok or not pyinst_ok:
        # Only one available — auto-select
        for _, name, label, ok in opts:
            if ok:
                print(f"{FLCyan}Only {label} is available. Using {name}.{CRst}")
                return name

    print()
    for key, name, label, ok in opts:
        tag = f"{FLGreen}{key}{CRst}" if ok else f"{FGray}(not installed){CRst}"
        desc = label if ok else f"{FGray}{label}{CRst}"
        print(f"  [{tag}] {desc}")

    while True:
        choice = input(f"\n{FLYellow}Choose compiler {FGray}[n]{CRst}: ").strip().lower() or "n"
        if choice in ("n", "nuitka"):
            if nuitka_ok:
                return "nuitka"
            print(f"{FLRed}Nuitka is not installed. Run: pip install nuitka{CRst}")
            continue
        if choice in ("p", "pyinstaller"):
            if pyinst_ok:
                return "pyinstaller"
            print(f"{FLRed}PyInstaller is not installed. Run: pip install pyinstaller{CRst}")
            continue
        print(f"{FLRed}Invalid choice. Enter {FLYellow}n{FLRed} or {FLYellow}p{FLRed}.{CRst}")


# ============ Build ============

def _build_nuitka(script_dir: str, script_rel: str, out_dir: str) -> int:
    """Compile *script_rel* with Nuitka --standalone, output to *out_dir*."""
    script_path = os.path.join(script_dir, script_rel)
    script_basename = os.path.splitext(os.path.basename(script_rel))[0]
    parent_dir = os.path.dirname(out_dir)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        f"--output-dir={parent_dir}",
        f"--output-filename={script_basename}",
        "--include-package=utils",
        script_path,
    ]

    print(f"\n{FLYellow}Compiling with Nuitka (standalone)...{CRst}")
    print(f"{FGray}  Source: {script_path}{CRst}")
    result = subprocess.run(cmd, check=False)

    if result.returncode != 0:
        print(f"\n{FLRed}Nuitka build failed with exit code {result.returncode}{CRst}")
        return result.returncode

    # Nuitka creates {parent_dir}/{basename}.dist/ — rename to the desired out_dir
    dist_dir = os.path.join(parent_dir, script_basename + ".dist")
    build_dir = os.path.join(parent_dir, script_basename + ".build")

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    if os.path.isdir(dist_dir):
        os.rename(dist_dir, out_dir)

    # Remove build artifacts
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir)

    print(f"\n{FLGreen}Build successful!{CRst}")
    print(f"{FLGreen}  Output: {FGray}{out_dir}{CRst}")
    return 0


def _build_pyinstaller(script_dir: str, script_rel: str, out_dir: str) -> int:
    """Compile *script_rel* with PyInstaller --onedir, output to *out_dir*."""
    script_path = os.path.join(script_dir, script_rel)
    parent_dir = os.path.dirname(out_dir)
    app_name = os.path.basename(out_dir)  # e.g. "npy-viewer_pyinstaller"

    # Use a temp build path under BUILD/ so it's easy to clean
    work_dir = os.path.join(parent_dir, "_pyi_build_temp_")
    spec_dir = parent_dir

    # Build --add-data for utils/
    sep = ";" if sys.platform == "win32" else ":"
    utils_src = os.path.join(script_dir, "utils")
    add_data = f"utils{sep}utils" if os.path.isdir(utils_src) else None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconfirm",
        "--clean",
        f"--distpath={parent_dir}",
        f"--workpath={work_dir}",
        f"--specpath={spec_dir}",
        f"--name={app_name}",
        "--add-data", add_data,
        script_path,
    ] if add_data else [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--noconfirm",
        "--clean",
        f"--distpath={parent_dir}",
        f"--workpath={work_dir}",
        f"--specpath={spec_dir}",
        f"--name={app_name}",
        script_path,
    ]

    print(f"\n{FLYellow}Compiling with PyInstaller (onedir)...{CRst}")
    print(f"{FGray}  Source: {script_path}{CRst}")
    result = subprocess.run(cmd, check=False)

    # Clean up build artifacts
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)

    # Remove .spec file
    spec_file = os.path.join(spec_dir, app_name + ".spec")
    if os.path.isfile(spec_file):
        os.remove(spec_file)

    if result.returncode != 0:
        print(f"\n{FLRed}PyInstaller build failed with exit code {result.returncode}{CRst}")
        return result.returncode

    print(f"\n{FLGreen}Build successful!{CRst}")
    print(f"{FLGreen}  Output: {FGray}{out_dir}{CRst}")
    return 0


def build_script(script_dir: str, script_rel: str, tool: str) -> int:
    """Build *script_rel* with *tool*, outputting to BUILD/ with preserved hierarchy."""
    build_base = os.path.join(script_dir, "BUILD")
    os.makedirs(build_base, exist_ok=True)

    script_basename = os.path.splitext(os.path.basename(script_rel))[0]
    folder_name = f"{script_basename}_{tool}"
    sub_dir = os.path.dirname(script_rel)
    out_dir = os.path.join(build_base, sub_dir, folder_name) if sub_dir else os.path.join(build_base, folder_name)

    # Ensure parent exists
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)

    if tool == "nuitka":
        return _build_nuitka(script_dir, script_rel, out_dir)
    else:
        return _build_pyinstaller(script_dir, script_rel, out_dir)


# ============ Main ============

def main() -> int:
    Utils.print_banner("SCRIPT COMPILER")
    Utils.print_env_info()

    script_dir = _get_script_dir()
    scripts = find_py_scripts(script_dir)
    all_rel = show_scripts(script_dir, scripts)

    if not all_rel:
        return 0

    print(f"\n  {FLYellow}Enter number to select a script{CRst} (or {FLYellow}Enter{CRst} to exit)")
    print(f"  Examples: {FGray}5{CRst} or {FGray}research/npy-viewer{CRst}\n")

    selected: str
    while True:
        try:
            choice_line = input(f"{FLYellow}Select script{CRst} {FGray}[#]{CRst}: ").strip()
        except EOFError:
            print()
            Utils.print_exit_message("Bye.")
            return 0

        if not choice_line:
            Utils.print_exit_message("Bye.")
            return 0

        if choice_line.isdigit():
            idx = int(choice_line)
            if 0 <= idx < len(all_rel):
                selected = all_rel[idx]
                break
            print(f"{FLRed}Invalid selection: {idx}{CRst}")
            continue

        # Try matching by name
        if choice_line in all_rel:
            selected = choice_line
            break
        # Try with .py extension
        candidate = choice_line if choice_line.endswith(".py") else choice_line + ".py"
        if candidate in all_rel:
            selected = candidate
            break
        print(f"{FLRed}Cannot find script: {FGray}{candidate}{CRst}")

    tool = choose_tool()
    return build_script(script_dir, selected, tool)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
