"""Runtime environment and executable discovery helpers."""

import os
import json
import shutil
import subprocess
import sys
import typing
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from .ansi import *
from .cmd_check import CmdCheck
from .system import LinuxGui, System


class RuntimeKind(StrEnum):
    """Distinct execution runtimes; discovery never switches between kinds."""

    POWERSHELL = "powershell-5.1"
    PWSH = "pwsh-7"
    CMD = "cmd"
    GIT_BASH = "git-bash"
    BASH = "bash"
    ZSH = "zsh"
    CONDA = "conda-python"
    PYTHON = "python"
    CURRENT_PYTHON = "python-current"
    NODE = "node"
    TSX = "tsx"
    DENO = "deno"
    BUN = "bun"


class Environment:
    DEFAULT_CONDA_ENV: str = "base"
    CONDA_INFO_TIMEOUT_SECONDS: int = 15

    @staticmethod
    def prepend_path(paths: Sequence[str]) -> None:
        """Prepend directories to this process's PATH without affecting its parent.

        Args:
            paths: Literal paths in priority order. No expansion, filtering, or
                deduplication is performed; an empty sequence leaves PATH alone.

        Side effects:
            Updates os.environ['PATH'], preserving its previous value verbatim.
            Empty/missing PATH does not introduce a trailing empty search entry.
        """
        if paths:
            current_path = os.environ.get("PATH")
            entries = (*paths, current_path) if current_path else paths
            os.environ["PATH"] = os.pathsep.join(entries)

    @staticmethod
    def resolve_conda_python(
        env_name: str, *, timeout: float = CONDA_INFO_TIMEOUT_SECONDS,
    ) -> str:
        """Resolve the Python executable belonging to a named Conda environment.

        Reuses the current interpreter without launching a process when it
        already belongs to the requested environment. Otherwise asks Conda for
        its environment list, honoring custom envs_dirs and rejecting ambiguity.
        This resolves an executable; it does not activate an environment.

        Args:
            env_name: Exact environment name, or base; comparisons use normcase.
            timeout: Positive timeout in seconds for the Conda info query,
                default 15. No version probes are performed.

        Returns:
            Absolute path to the requested environment's Python executable.

        Raises:
            RuntimeError: Conda is unavailable, its query fails, the environment
                is missing/ambiguous/invalid, or its Python executable is missing.

        Side effects:
            May execute conda info --envs --json and inspect environment paths.
            Does not install packages or modify the process environment.
        """
        # ── current-interpreter fast path ──────────────────
        current_env = Environment.get_conda_env()
        if current_env is not None and os.path.normcase(current_env) == os.path.normcase(env_name):
            return os.path.abspath(sys.executable)

        # ── query the configured Conda installation ────────
        conda_executable = Environment.find_conda()
        if conda_executable is None:
            raise RuntimeError(
                f"Cannot resolve Conda environment '{env_name}': conda is not in PATH."
            )
        try:
            result = subprocess.run(
                [conda_executable, "info", "--envs", "--json"], check=False,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Cannot inspect Conda environments: {exc}") from exc
        if result.returncode != 0:
            detail = " ".join((result.stderr or result.stdout or "").split())
            if not detail:
                detail = f"conda exited with code {result.returncode}"
            raise RuntimeError(f"Cannot inspect Conda environments: {detail}")
        try:
            payload: object = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Conda returned invalid environment data.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Conda returned invalid environment data.")
        root_prefix = payload.get("root_prefix")
        env_paths = payload.get("envs")
        if not isinstance(root_prefix, str) or not isinstance(env_paths, list):
            raise RuntimeError("Conda returned incomplete environment data.")

        # ── resolve a unique environment and Python ───────
        if os.path.normcase(env_name) == os.path.normcase(Environment.DEFAULT_CONDA_ENV):
            matching_prefixes = [root_prefix]
        else:
            matching_prefixes = [
                path for path in env_paths
                if isinstance(path, str)
                and os.path.normcase(os.path.basename(os.path.normpath(path))) == os.path.normcase(env_name)
            ]
        if not matching_prefixes:
            raise RuntimeError(f"Conda environment '{env_name}' does not exist.")
        if len(matching_prefixes) > 1:
            raise RuntimeError(
                f"Multiple Conda environments are named '{env_name}'; use a unique name."
            )
        env_prefix = os.path.abspath(matching_prefixes[0])
        if not os.path.isdir(os.path.join(env_prefix, "conda-meta")):
            raise RuntimeError(f"Conda environment '{env_name}' is invalid.")
        python_path = (
            os.path.join(env_prefix, "python.exe")
            if sys.platform in ("win32", "cygwin", "msys")
            else os.path.join(env_prefix, "bin", "python")
        )
        if not os.path.isfile(python_path):
            raise RuntimeError(f"Conda environment '{env_name}' has no Python executable.")
        return python_path

    @staticmethod
    def runtime_candidates(
        kind: RuntimeKind, environment: Mapping[str, str], *, cwd: str | os.PathLike[str] | None = None,
    ) -> list[str]:
        """Find candidate executable paths for one runtime without launching it.

        Args:
            kind: Runtime identity; Python requires an explicit path except for
                python-current and conda-python.
            environment: Child environment used for PATH and installation roots.
            cwd: Base for relative PATH entries, defaulting to this process's cwd.

        Returns:
            Ordered unique candidates. Windows batch wrappers are excluded.
        """
        if os.name == "nt":
            environment = {key.upper(): value for key, value in environment.items()}
        candidates: list[str] = []
        base_dir = os.fspath(cwd) if cwd is not None else os.getcwd()
        home = Path(environment.get("USERPROFILE", str(Path.home())))
        program_files = Path(environment.get("PROGRAMFILES", "C:/Program Files"))
        system_root = Path(environment.get("SYSTEMROOT", "C:/Windows"))
        names = {
            RuntimeKind.PWSH: "pwsh", RuntimeKind.POWERSHELL: "powershell",
            RuntimeKind.CMD: "cmd", RuntimeKind.GIT_BASH: "bash",
            RuntimeKind.BASH: "bash", RuntimeKind.ZSH: "zsh",
            RuntimeKind.CONDA: "conda", RuntimeKind.NODE: "node",
            RuntimeKind.TSX: "node", RuntimeKind.DENO: "deno", RuntimeKind.BUN: "bun",
        }
        if kind == RuntimeKind.CURRENT_PYTHON:
            return [sys.executable]
        if kind == RuntimeKind.PYTHON:
            return []
        if kind in names:
            found = Environment.which(names[kind], environment=environment, cwd=base_dir)
            if found:
                candidates.append(found)
        if kind == RuntimeKind.CONDA:
            roots = [Path(sys.prefix), Path(sys.base_prefix), home / "miniconda3", home / "anaconda3"]
            if Path(sys.prefix).parent.name == "envs":
                roots.insert(0, Path(sys.prefix).parent.parent)
            if environment.get("CONDA_EXE"):
                candidates.insert(0, environment["CONDA_EXE"])
            for candidate in list(candidates):
                location = Path(candidate)
                roots.extend(location.parents[:3])
            if os.name == "nt":
                data = Path(environment.get("PROGRAMDATA", "C:/ProgramData"))
                roots.extend([data / "miniconda3", data / "anaconda3"])
                candidates.extend(str(root / "Scripts/conda.exe") for root in roots)
            else:
                roots.extend([Path("/opt/miniconda3"), Path("/opt/anaconda3")])
                candidates.extend(str(root / "bin/conda") for root in roots)
        if os.name == "nt":
            if kind == RuntimeKind.POWERSHELL:
                candidates.insert(0, str(system_root / "System32/WindowsPowerShell/v1.0/powershell.exe"))
            elif kind == RuntimeKind.CMD:
                candidates = [environment.get("COMSPEC", environment.get("ComSpec", "")), str(system_root / "System32/cmd.exe")]
            elif kind == RuntimeKind.PWSH:
                candidates.extend([
                    str(program_files / "PowerShell/7/pwsh.exe"),
                    str(Path(environment.get("SCOOP", str(home / "scoop"))) / "apps/pwsh/current/pwsh.exe"),
                ])
            elif kind == RuntimeKind.GIT_BASH:
                git = Environment.which("git", environment=environment, cwd=base_dir)
                if git:
                    candidates.extend(str(root / "bin/bash.exe") for root in Path(git).resolve().parents[:3])
                candidates.extend([
                    str(program_files / "Git/bin/bash.exe"),
                    str(Path(environment.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Git/bin/bash.exe"),
                    str(Path(environment.get("LOCALAPPDATA", str(home / "AppData/Local"))) / "Programs/Git/bin/bash.exe"),
                    str(Path(environment.get("SCOOP", str(home / "scoop"))) / "apps/git/current/bin/bash.exe"),
                ])
        elif kind in {RuntimeKind.BASH, RuntimeKind.ZSH}:
            candidates.extend([f"/bin/{kind.value}", f"/usr/bin/{kind.value}"])
        candidates = [os.path.abspath(os.path.join(base_dir, path)) for path in candidates if path]
        return list(dict.fromkeys(
            path for path in candidates
            if path and Path(path).is_file() and (os.name != "nt" or Path(path).suffix.lower() == ".exe")
        ))

    @staticmethod
    def resolve_runtime(
        kind: RuntimeKind, *, executable: str | None = None,
        environment: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> tuple[str, str]:
        """Discover and verify a runtime, returning its path and version.

        Args:
            kind: Exact runtime kind; there is no cross-kind fallback.
            executable: Optional explicit executable path (the sole candidate).
            environment: Environment for discovery and short version probes.
            cwd: Working directory for lookup and probes; None uses process cwd.

        Returns:
            Absolute executable path and a one-line version description. The
            launch path preserves symlinks so virtual environments remain active.

        Raises:
            ValueError: The runtime is unsupported on this platform or no
                candidate passes verification. Explicit paths never fall back.

        Side effects:
            Starts bounded, non-interactive version probes, never installs tools.
        """
        env = dict(os.environ if environment is None else environment)
        windows_only = {RuntimeKind.POWERSHELL, RuntimeKind.CMD, RuntimeKind.GIT_BASH}
        if os.name != "nt" and kind in windows_only:
            raise ValueError(f"{kind.value} requires Windows")
        if os.name == "nt" and kind in {RuntimeKind.BASH, RuntimeKind.ZSH}:
            raise ValueError(f"{kind.value} is a POSIX runtime; select git-bash on Windows")
        if kind == RuntimeKind.CURRENT_PYTHON and getattr(sys, "frozen", False):
            raise ValueError("python-current is unavailable in a frozen executable")
        base_dir = os.fspath(cwd) if cwd is not None else os.getcwd()
        candidates = [executable] if executable else Environment.runtime_candidates(kind, env, cwd=base_dir)
        failures: list[str] = []
        for candidate in candidates:
            path = Path(os.path.abspath(os.path.join(base_dir, candidate)))
            if not path.is_file() or (os.name == "nt" and path.suffix.lower() != ".exe"):
                failures.append(f"{path}: not a native executable")
                continue
            if kind == RuntimeKind.GIT_BASH and not any(
                (root / "cmd/git.exe").is_file() for root in path.resolve().parents[:3]
            ):
                failures.append(f"{path}: not a Git for Windows installation")
                continue
            if kind in {RuntimeKind.PWSH, RuntimeKind.POWERSHELL}:
                args = ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"]
            elif kind == RuntimeKind.CMD:
                args = ["/d", "/c", "ver"]
            elif kind == RuntimeKind.ZSH:
                args = ["-f", "--version"]
            else:
                args = ["--version"]
            try:
                result = subprocess.run(
                    [str(path), *args], env=env, cwd=base_dir, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{path}: {type(exc).__name__}")
                continue
            version = (result.stdout or result.stderr).strip().splitlines()
            value = version[0] if version else ""
            valid = result.returncode == 0 and bool(value)
            if kind in {RuntimeKind.PWSH, RuntimeKind.POWERSHELL}:
                parts = value.split(".")
                valid = valid and parts[0].isdigit() and (
                    int(parts[0]) >= 7 if kind == RuntimeKind.PWSH else value.startswith("5.1.")
                )
            elif kind in {RuntimeKind.PYTHON, RuntimeKind.CURRENT_PYTHON}:
                valid = valid and value.startswith("Python 3.")
            elif kind == RuntimeKind.CONDA:
                valid = valid and value.lower().startswith("conda ")
            elif kind in {RuntimeKind.BASH, RuntimeKind.GIT_BASH}:
                valid = valid and "bash" in value.lower()
            elif kind == RuntimeKind.ZSH:
                valid = valid and value.startswith("zsh ")
            elif kind in {RuntimeKind.NODE, RuntimeKind.TSX}:
                valid = valid and value.startswith("v") and value[1:2].isdigit()
            elif kind == RuntimeKind.DENO:
                valid = valid and value.startswith("deno ")
            elif kind == RuntimeKind.BUN:
                valid = valid and value[0:1].isdigit()
            if valid:
                return str(path), value
            failures.append(f"{path}: version check failed")
        detail = "; ".join(failures) or "no executable found"
        raise ValueError(f"Cannot resolve {kind.value}: {detail}. Configure runtime-executable or install the runtime manually.")

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
        """Print Conda, Python, operating-system, display, and shell information.

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
        linux_gui = System.get_linux_gui()
        if linux_gui is not None:
            gui_color = FLRed if linux_gui is LinuxGui.NO_GUI else FGray
            lines.append(
                f"{FLCyan}Linux GUI:{CRst}    "
                f"{gui_color}{linux_gui.value}{CRst}"
            )

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
                lines.append(f"{FLGreen}PowerShell:{CRst}   [found]")
            lines.append(f"              {FGray}{pwsh}{CRst}")
        else:
            lines.append(f"{FLGreen}PowerShell:{CRst}   {FLRed}[not found]{CRst}")

        bash = Environment.find_bash()
        if bash:
            ver = Environment._get_shell_version(bash) if probe_versions else None
            if ver:
                lines.append(f"{FLGreen}Bash:{CRst}         {ver}")
            else:
                lines.append(f"{FLGreen}Bash:{CRst}         [found]")
            lines.append(f"              {FGray}{bash}{CRst}")
        else:
            lines.append(f"{FLGreen}Bash:{CRst}         {FLRed}[not found]{CRst}")

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
    def which(
        name: str, *, environment: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> str | None:
        """Find an executable, optionally using a child's environment and cwd.

        Args:
            name: Program name or explicit file path, without template expansion.
            environment: Child PATH/PATHEXT mapping. None uses os.environ.
            cwd: Base for relative paths. None uses this process's directory.

        Returns:
            Executable path or None. With either optional argument supplied,
            returns an absolute path preserving symlinks and searches only the
            supplied PATH (no implicit current-directory search). Empty entries
            in a nonempty PATH explicitly mean cwd. Without optional arguments,
            retains shutil.which's native search behavior.

        Side effects:
            Checks executable files; does not launch them or mutate os.environ.
        """
        if environment is None and cwd is None:
            return shutil.which(name)
        env = dict(os.environ if environment is None else environment)
        if os.name == "nt":
            env = {key.upper(): value for key, value in env.items()}
        base_dir = os.fspath(cwd) if cwd is not None else os.getcwd()
        if os.path.dirname(name):
            candidates = [os.path.abspath(os.path.join(base_dir, name))]
        else:
            search_path = env.get("PATH", os.defpath)
            candidates = [
                os.path.abspath(os.path.join(base_dir, directory.strip('"') if os.name == "nt" else directory, name))
                for directory in search_path.split(os.pathsep)
            ] if search_path else []
        suffixes: list[str] = []
        if os.name == "nt":
            suffixes = [ext for ext in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep) if ext]
        for candidate in candidates:
            filenames = [candidate] if os.name != "nt" or os.path.splitext(candidate)[1] else []
            filenames.extend(f"{candidate}{ext}" for ext in suffixes)
            for filename in dict.fromkeys(filenames):
                if os.path.isfile(filename) and os.access(filename, os.F_OK | os.X_OK):
                    return filename
        return None
