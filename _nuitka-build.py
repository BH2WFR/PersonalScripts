#!/usr/bin/env python3
"""Build run-script.py into a standalone executable using Nuitka.

Usage:
    python _nuitka-build.py

Output goes to BUILD/ directory.
"""

import sys
import os
import subprocess

# ANSI colors (inline, no dependency on utils)
FLYellow = "\033[93m"
FLGreen  = "\033[92m"
FLRed    = "\033[91m"
FGray    = "\033[90m"
CRst     = "\033[0m"


def main() -> int:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, "run-script.py")
    build_dir = os.path.join(script_dir, "BUILD")

    if not os.path.isfile(script_path):
        print(f"{FLRed}Cannot find run-script.py: {script_path}{CRst}", file=sys.stderr)
        return 1

    try:
        subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{FLRed}Nuitka is not installed. Run: pip install nuitka{CRst}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        f"--output-dir={build_dir}",
        "--output-filename=run-script",
        "--include-package=utils",
    ]

    for sub in ("macos", "windows", "research", "test"):
        sub_path = os.path.join(script_dir, sub)
        if os.path.isdir(sub_path):
            cmd.append(f"--include-data-dir={sub_path}={sub}")

    for f in sorted(os.listdir(script_dir)):
        if f.startswith("_"):
            continue
        if f in ("run-script.py", "run-script.sh", "run-script.ps1"):
            continue
        if f.endswith((".py", ".sh", ".ps1")):
            full = os.path.join(script_dir, f)
            if os.path.isfile(full):
                cmd.append(f"--include-data-files={full}={f}")

    for plugin in ("numpy", "matplotlib"):
        cmd.append(f"--enable-plugin={plugin}")

    cmd.append(script_path)

    print(f"{FLYellow}Building run-script standalone executable with Nuitka...{CRst}")
    print(f"{FGray}  Source: {script_path}{CRst}")
    print(f"{FGray}  Output: {build_dir}{CRst}")
    print()

    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        dist_path = os.path.join(build_dir, "run-script.dist")
        print(f"\n{FLGreen}Build successful!{CRst}")
        print(f"{FLGreen}  Executable: {dist_path}{CRst}")
    else:
        print(f"\n{FLRed}Build failed with exit code {result.returncode}{CRst}", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
