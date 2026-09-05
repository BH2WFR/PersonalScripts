"""Runtime environment and executable discovery helpers."""

import os
import shutil
import subprocess
import sys
import typing

from .ansi import *
from .cmd_check import CmdCheck
from .system import System


class Environment:
    @staticmethod
    def get_conda_env() -> typing.Optional[str]:
        """Return the conda environment name, or ``None`` if not running in conda."""
        prefix = sys.prefix
        if not any(kw in prefix.lower() for kw in ("conda", "anaconda", "miniconda")):
            return None
        parent = os.path.dirname(prefix)
        if os.path.basename(parent) == "envs":
            return os.path.basename(prefix)
        if os.path.isdir(os.path.join(prefix, "conda-meta")):
            return "base"
        return None

    @staticmethod
    def find_conda() -> typing.Optional[str]:
        """Find a conda executable. Returns path or ``None``."""
        return shutil.which("conda") or None

    @staticmethod
    def find_bash() -> typing.Optional[str]:
        """Find a bash executable. Returns path or ``None``."""
        if sys.platform in ("win32", "cygwin", "msys"):
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

    @staticmethod
    def find_pwsh() -> typing.Optional[str]:
        """Find a PowerShell executable. Returns path or ``None``."""
        for exe in ("pwsh", "powershell"):
            found = shutil.which(exe)
            if found:
                return found
        return None

    @staticmethod
    def _get_shell_version(exe_path: str) -> typing.Optional[str]:
        """Get the version string of a shell, or ``None`` on failure."""
        try:
            base = os.path.basename(exe_path).lower()
            if base.startswith("pwsh") or base.startswith("powershell"):
                result = subprocess.run(
                    [exe_path, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                    capture_output=True, text=True, timeout=5,
                )
                return result.stdout.strip() or None

            result = subprocess.run(
                [exe_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            out = result.stdout.strip()
            if out:
                return out.splitlines()[0]
            if result.stderr.strip():
                return result.stderr.strip().splitlines()[0]
        except Exception:
            pass
        return None

    @staticmethod
    def print_env_info(*, probe_versions: bool = True) -> None:
        """Print Conda, Python, operating-system, and shell information.

        Args:
            probe_versions: Whether to start external Conda, PowerShell, and
                Bash processes to read their versions. When ``False``, their
                resolved paths are still shown without the version probes.

        Side effects:
            Prints environment information and, when ``probe_versions`` is
            enabled, briefly starts each discovered external tool.
        """
        lines: list[str] = []

        lines.append(f"{FLYellow}OS:{CRst}           {System.get_os_name()}")
        lines.append(f"{FLYellow}Arch:{CRst}         {FGray}{System.get_arch()}{CRst}")

        lines.append(f"{FLCyan}Python:{CRst}       {sys.version.split()[0]}")
        lines.append(f"              {FGray}{sys.executable}{CRst}")

        conda_env = Environment.get_conda_env()
        if conda_env is None:
            lines.append(f"{FLCyan}Conda env:{CRst}    {FLRed}(no conda){CRst}")
        else:
            conda_exe = Environment.find_conda()
            conda_ver = (
                Environment._get_shell_version(conda_exe)
                if probe_versions and conda_exe
                else None
            )
            ver_part = f"  {FGray}({conda_ver}){CRst}" if conda_ver else ""
            lines.append(f"{FLCyan}Conda env:{CRst}    {FLYellow}{conda_env}{CRst}{ver_part}")
            if conda_exe:
                lines.append(f"              {FGray}{conda_exe}{CRst}")

        pwsh = Environment.find_pwsh()
        if pwsh:
            ver = Environment._get_shell_version(pwsh) if probe_versions else None
            if ver:
                lines.append(f"{FLGreen}PowerShell:{CRst}   {ver}")
            else:
                lines.append(f"{FLGreen}PowerShell:{CRst}   {FGray}(found){CRst}")
            lines.append(f"              {FGray}{pwsh}{CRst}")
        else:
            lines.append(f"{FLGreen}PowerShell:{CRst}   {FLRed}(not found){CRst}")

        bash = Environment.find_bash()
        if bash:
            ver = Environment._get_shell_version(bash) if probe_versions else None
            if ver:
                lines.append(f"{FLGreen}Bash:{CRst}         {ver}")
            else:
                lines.append(f"{FLGreen}Bash:{CRst}         {FGray}(found){CRst}")
            lines.append(f"              {FGray}{bash}{CRst}")
        else:
            lines.append(f"{FLGreen}Bash:{CRst}         {FLRed}(not found){CRst}")

        print()
        for line in lines:
            print(f"  {line}")
        print()

    @staticmethod
    def check_commands(*checks: CmdCheck) -> bool:
        """Verify all commands in *checks* exist in PATH.

        Resolves ``.path`` on each :class:`CmdCheck` to the found executable,
        or ``None`` if not found. Prints per-platform install hints for missing
        commands. Required commands cause the check to fail; optional ones only
        print a warning.

        Returns True if all *required* commands are found, False otherwise.
        Callers should ``sys.exit(1)`` when False.
        """
        all_ok = True
        for c in checks:
            # Resolve: list = try in order, str = single lookup
            names = c.cmd if isinstance(c.cmd, list) else [c.cmd]
            c.path = next((shutil.which(n) for n in names if shutil.which(n)), None)
            if c.path is not None:
                continue

            # Build error/warning message
            prefix = f"{FLRed}ERROR:{CRst}" if c.required else f"{FLYellow}WARNING:{CRst}"
            label = " or ".join(names)
            print(f"{prefix} `{label}` not found in PATH.")

            # Print platform-specific hints
            if c.hints:
                platform = (
                    "windows" if sys.platform == "win32"
                    else "macos" if sys.platform == "darwin"
                    else "linux"
                )
                for key in ("any", platform):
                    if key in c.hints:
                        print(f"  {c.hints[key]}")
            print()

            if c.required:
                all_ok = False
        return all_ok

    @staticmethod
    def which(name: str) -> typing.Optional[str]:
        """Return the path to an executable, or ``None`` if not found.

        Thin wrapper around :func:`shutil.which`.
        """
        return shutil.which(name) or None  # type: ignore[return-value]
