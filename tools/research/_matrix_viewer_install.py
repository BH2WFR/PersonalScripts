#!/usr/bin/env python3
"""Build and incrementally install the Windows MatrixViewer directory release.

Run with Conda Python. The interactive destination is the directory containing
MatrixViewer.exe, not its parent; Enter reuses the last successful destination.
The first default is D:/Portable_Programs/MatrixViewer. Optional --output skips
the prompt, --environment selects an existing dedicated Conda environment, and
--clean clears PyInstaller's build cache. No dependencies are installed here.

Requirements: Windows 10+, Python 3.13+, Conda, and PyInstaller plus the viewer's
runtime dependencies in matrix-viewer-build (or --environment). The driver uses
only the standard library and project utils; base may run the driver but is
never used to compile the application.

Builds finish in BUILD/MatrixViewer/install-stage before touching the release.
SHA-256 comparisons preserve identical destination files, including timestamps;
changed files are replaced individually through temporary sibling files. Only
previously managed files are removed. A legacy MatrixViewer release is adopted
by its build-manifest.json; its _internal directory is considered managed.
Other user files are preserved. Close the installed viewer before updating.
The per-project OS lock prevents simultaneous builds through this driver.

A failed build leaves the installed release intact. Deployment is not a whole-
directory transaction: an I/O failure during copying is reported, and rerunning
repairs the release. The install inventory is committed after all file changes.
Build artifacts and remembered settings remain under the Gitignored BUILD tree.

Usage:
    In an activated Conda PowerShell:
    & "$env:CONDA_PREFIX/python.exe" tools/research/_matrix_viewer_install.py
    Noninteractive:
    conda run -n base python tools/research/_matrix_viewer_install.py --output D:/Portable_Programs/MatrixViewer
    conda run -n base python tools/research/_matrix_viewer_install.py --help
"""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import tempfile
from collections.abc import Iterator

import sys

PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR))
from utils import *  # noqa: E402


APP_NAME = "MatrixViewer"
EXECUTABLE = f"{APP_NAME}.exe"
DEFAULT_OUTPUT = Path("D:/Portable_Programs/MatrixViewer")
DEFAULT_ENVIRONMENT = "matrix-viewer-build"
BUILD_DIR = PROJECT_DIR / "BUILD" / APP_NAME
STAGE_DIR = BUILD_DIR / "install-stage"
SPEC_FILE = Path(__file__).with_name("matrix-viewer") / "packaging" / f"{APP_NAME}.spec"
SETTINGS_FILE = BUILD_DIR / "install-settings.json"
INSTALL_RECORD = ".matrix-viewer-install.json"
BUILD_RECORD = "_internal/build-manifest.json"
RECORD_VERSION = 1


@dataclass(frozen=True)
class InstallResult:
    """File counts from a completed release update; unchanged files were not written."""

    updated: int
    unchanged: int
    removed: int


def _file_hash(path: Path) -> str:
    """Read a file and return its SHA-256 digest, propagating I/O errors."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _release_path(root: Path, name: str) -> Path:
    """Validate a managed release path and reject traversal, links and junctions."""
    relative = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or relative.is_absolute()
            or ".." in relative.parts or relative.as_posix() != name
            or not (name == EXECUTABLE or (len(relative.parts) > 1 and relative.parts[0] == "_internal"))):
        raise ValueError(f"Invalid managed release path: {name!r}")
    target = root
    for index, part in enumerate(relative.parts):
        target = target / part
        if target.is_symlink() or target.is_junction():
            raise ValueError(f"Links and junctions are not allowed in release files: {target}")
        if index < len(relative.parts) - 1 and target.exists() and not target.is_dir():
            raise ValueError(f"A release directory conflicts with a file: {target}")
    # Callers supply a resolved root. Relative components contain no traversal,
    # and every component above was checked for links before filesystem writes.
    return target


def _inventory(root: Path) -> dict[str, Path]:
    """List release-owned files, checking directory links before traversal."""
    files: dict[str, Path] = {}
    exe = _release_path(root, EXECUTABLE)
    if exe.is_file():
        files[EXECUTABLE] = exe
    internal = root / "_internal"
    _release_path(root, BUILD_RECORD)
    directories = [internal] if internal.is_dir() else []
    while directories:
        for path in directories.pop().iterdir():
            _release_path(root, path.relative_to(root).as_posix())
            if path.is_dir():
                directories.append(path)
            else:
                files[path.relative_to(root).as_posix()] = path
    return files


def _read_record(path: Path) -> dict[str, object]:
    """Read an application-owned JSON object, rejecting malformed/foreign data."""
    if path.is_symlink() or path.is_junction():
        raise ValueError(f"A release record cannot be a link: {path}")
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("application") != APP_NAME:
        raise ValueError(f"Not a {APP_NAME} record: {path}")
    return value


def _managed_files(destination: Path) -> set[str]:
    """Load the install inventory, or adopt an existing verified onedir release."""
    record_path = destination / INSTALL_RECORD
    if record_path.is_symlink() or record_path.is_junction():
        raise ValueError(f"A release record cannot be a link: {record_path}")
    if record_path.exists():
        record = _read_record(record_path)
        names = record.get("files")
        if record.get("version") != RECORD_VERSION or not isinstance(names, dict):
            raise ValueError(f"Unsupported installation record: {record_path}")
        managed: set[str] = set()
        for name, digest in names.items():
            if not isinstance(name, str) or not isinstance(digest, str):
                raise ValueError(f"Invalid installation inventory: {record_path}")
            _release_path(destination, name)
            managed.add(name)
        return managed
    legacy = _release_path(destination, BUILD_RECORD)
    if legacy.is_file():
        if _read_record(legacy).get("layout") != "onedir":
            raise ValueError(f"Expected an onedir release: {destination}")
        return set(_inventory(destination))
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Choose an empty directory or an existing MatrixViewer release directory.")
    return set()


def _replace_file(source: Path, target: Path) -> None:
    """Copy to a temporary sibling and replace one file; clean up on failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".matrix-viewer-", suffix=".tmp", dir=target.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    try:
        shutil.copy2(source, temporary_path)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def install_release(source: Path, destination: Path) -> InstallResult:
    """Synchronize a finished build without rewriting unchanged runtime libraries.

    Args:
        source: Completed PyInstaller onedir release with its build manifest.
        destination: Empty directory or a recognized existing release directory.

    Returns:
        Counts of updated, unchanged and obsolete files (excluding the inventory).

    Raises:
        ValueError: The release, inventory or path is unsafe or invalid.
        OSError: Reading, copying, deleting or checking locked files fails.

    Side effects:
        Writes changed files and the install inventory; removes only obsolete
        managed files. Unchanged files and unrelated user files are preserved.
    """
    source, destination = source.resolve(), destination.resolve()
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Build and install directories must not overlap.")
    if _read_record(_release_path(source, BUILD_RECORD)).get("layout") != "onedir":
        raise ValueError("The build did not produce an onedir release.")
    files = _inventory(source)
    if EXECUTABLE not in files:
        raise ValueError(f"The build is missing {EXECUTABLE}.")
    previous = _managed_files(destination)
    digests = {name: _file_hash(path) for name, path in files.items()}
    changed: list[str] = []
    for name, path in files.items():
        target = _release_path(destination, name)
        if target.exists() and not target.is_file():
            raise ValueError(f"A release file conflicts with a directory: {target}")
        if not target.exists() or target.stat().st_size != path.stat().st_size or _file_hash(target) != digests[name]:
            changed.append(name)
    obsolete = sorted(previous - files.keys())

    # Check locks before any modifications. The executable is checked even when
    # unchanged because the running viewer could otherwise load mixed DLLs.
    for name in {*changed, *obsolete, EXECUTABLE}:
        target = _release_path(destination, name)
        if target.exists():
            with target.open("r+b"):
                pass
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(changed, key=lambda value: (value == EXECUTABLE, value)):
        _replace_file(files[name], _release_path(destination, name))
    for name in obsolete:
        _release_path(destination, name).unlink(missing_ok=True)

    # Publish the new inventory last; a failed copy can be repaired on the next run.
    record = {"application": APP_NAME, "version": RECORD_VERSION, "files": digests}
    payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
    inventory_path = destination / INSTALL_RECORD
    if not inventory_path.exists() or inventory_path.read_text(encoding="utf-8") != payload:
        with tempfile.TemporaryDirectory(prefix="matrix-viewer-record-", dir=destination) as temporary:
            staged_record = Path(temporary) / INSTALL_RECORD
            staged_record.write_text(payload, encoding="utf-8")
            _replace_file(staged_record, inventory_path)
    return InstallResult(len(changed), len(files) - len(changed), len(obsolete))


@contextmanager
def _build_lock() -> Iterator[None]:
    """Hold a Windows byte-range lock until this build/deployment finishes."""
    import msvcrt

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    with (BUILD_DIR / "install.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Another MatrixViewer build/install is already running.") from exc
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _output_path(text: str) -> Path:
    """Resolve the requested directory, protecting source, build and root paths."""
    destination = Path(Paths.resolve_vars(text.strip().strip('"').strip("'"))).resolve()
    if (destination == Path(destination.anchor) or PROJECT_DIR.is_relative_to(destination)
            or destination.is_relative_to(PROJECT_DIR / "tools")
            or destination.is_relative_to(BUILD_DIR) or BUILD_DIR.is_relative_to(destination)):
        raise ValueError("The output must be separate from source/build directories and cannot be a drive root.")
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"The output is not a directory: {destination}")
    _managed_files(destination)
    return destination


def main() -> int:
    """Prompt, build in the dedicated environment, then publish changed files.

    Returns:
        Zero on success, one on a reported build/install error.

    Side effects:
        Prompts unless --output is supplied, runs PyInstaller, updates the chosen
        release and remembers its path. KeyboardInterrupt propagates to the CLI.
    """
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}MatrixViewer build and install{CRst}\nBuild an onedir release; preserve unchanged installed libraries.",
        epilog="Requirements: Windows 10+, Conda, Python 3.13+; PyInstaller and viewer dependencies in a dedicated environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output", help="Install directory containing MatrixViewer.exe; otherwise prompt")
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT, help=f"Existing Conda build environment (default: {DEFAULT_ENVIRONMENT})")
    parser.add_argument("--clean", action="store_true", help="Clear PyInstaller's cache before building")
    args = parser.parse_args()
    if sys.platform != "win32":
        print(f"{FLRed}This build script requires Windows. Current platform: {sys.platform}{CRst}")
        return 1
    try:
        # ── destination and build environment ──────────────
        default = str(DEFAULT_OUTPUT)
        if SETTINGS_FILE.is_file():
            saved = _read_record(SETTINGS_FILE).get("output")
            if isinstance(saved, str):
                default = saved
        requested = args.output or Input.prompt(
            f"{FLYellow}Install directory (contains {EXECUTABLE}){CRst}\n{FGray}[{default}]{CRst} > ", default=default,
        )
        destination = _output_path(requested)
        installed_exe = destination / EXECUTABLE
        if installed_exe.is_file():
            with installed_exe.open("r+b"):
                pass
        conda = Environment.find_conda_executable()
        if conda is None:
            raise RuntimeError("Conda is unavailable. No packages or environments were installed.")
        if args.environment.casefold() == "base":
            raise ValueError("Use a dedicated build environment, not Conda base.")
        if not SPEC_FILE.is_file():
            raise FileNotFoundError(f"Build configuration not found: {SPEC_FILE}")
        command = [conda, "run", "--no-capture-output", "-n", args.environment, "python", "-I", "-m", "PyInstaller",
                   "--noconfirm", "--distpath", str(STAGE_DIR), "--workpath", str(BUILD_DIR / "work")]
        if args.clean:
            command.append("--clean")
        command.append(str(SPEC_FILE))
        environment = os.environ.copy()
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0")
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)

        # ── build first, then compare and install ──────────
        with _build_lock():
            if not STAGE_DIR.resolve().is_relative_to(BUILD_DIR.resolve()):
                raise ValueError("The staging directory must remain inside the build directory.")
            print(f"{FLCyan}Building with {args.environment}; install to {destination}{CRst}", flush=True)
            result = subprocess.run(command, cwd=PROJECT_DIR, env=environment, check=False)
            if result.returncode:
                raise RuntimeError(f"PyInstaller exited with code {result.returncode}; installed release was not modified.")
            print(f"{FLCyan}Comparing release files and installing changes...{CRst}", flush=True)
            counts = install_release(STAGE_DIR / APP_NAME, destination)
            SETTINGS_FILE.write_text(json.dumps({"application": APP_NAME, "output": str(destination)}, indent=2), encoding="utf-8")
        print(f"{FLGreen}Installed: {destination / EXECUTABLE}{CRst}")
        print(f"Updated: {counts.updated}; unchanged: {counts.unchanged}; removed obsolete: {counts.removed}")
        return 0
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"{FLRed}Build/install failed: {exc}{CRst}")
        if isinstance(exc, PermissionError):
            print(f"{FYellow}Close MatrixViewer and check directory permissions, then rerun this script.{CRst}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()
