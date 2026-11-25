#!/usr/bin/env python3
"""Assemble the working tree and a shared, native-platform CPython installation."""

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from importlib.metadata import distributions
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from uuid import uuid4
import zipfile

from utils import *


HELP = """PROJECT RELEASE PACKAGER

Build the portable Python runtime in deps/python or create a release archive in
BUILD for the current platform. Packaging reuses a verified runtime or builds
one from requirements.txt, and can include local tools and OCR models.

Requirements:
  Python 3.13+, uv, distlib and filelock. Packaging also requires Git.
  Internet access on the first build, or populated uv caches.

Usage:
  python package-project.py
  python package-project.py build-runtime
  python package-project.py package [--with-resources] [--refresh]

  No arguments open the menu. Both commands run without prompts.
  build-runtime     Rebuild deps/python and exit.
  package           Create the archive, reusing the runtime when possible.
  --with-resources  Include deps/tools and deps/ocr-models when present.
  --refresh         Rebuild the runtime before packaging.
  Passing packaging flags alone also selects package.
"""

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "BUILD"
RUNTIME = ROOT / "deps" / "python"
REQUIREMENTS = ROOT / "requirements.txt"
PYTHON_VERSION = "3.13"
TARGET = f"{sys.platform}-{platform.machine().lower()}"
RECEIPT = ".personalscripts-runtime"
ROOT_FILES = (
    "run-script.py", "run-script.ps1", "run-script.sh", "launcher-config.yaml",
    "requirements.txt", "README.md", "README_zh.md", "Environmental_Variables.md", "LICENSE",
)


def interpreter(directory: Path) -> Path:
    """Return the runtime's native Python entry point."""
    return directory / ("python.exe" if os.name == "nt" else "bin/python3")


@contextmanager
def staging_directory(parent: Path, prefix: str) -> Iterator[Path]:
    """Stage beside the destination so published files inherit its normal permissions."""
    stage = parent / f".{prefix}-{uuid4().hex}"
    stage.mkdir()
    try:
        yield stage
    finally:
        shutil.rmtree(stage)


def make_entry_points_portable(directory: Path) -> None:
    """Recreate installed wheel entry points relative to the bundled interpreter."""
    try:
        # distlib is installed in the build environment only.
        from distlib.scripts import ScriptMaker  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise ValueError("Install the build dependency: python -m pip install distlib") from exc

    python = interpreter(directory)
    purelib = subprocess.check_output(
        [python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
    ).strip()
    windows = os.name == "nt"
    scripts = directory / ("Scripts" if windows else "bin")

    class PortableScriptMaker(ScriptMaker):
        # distlib uses this class attribute to write the launcher's shebang.
        executable = r"<launcher_dir>\..\python.exe" if windows else "/usr/bin/python3"

    maker = PortableScriptMaker(None, str(scripts))
    maker.clobber = True
    maker.variants.intersection_update({""})
    for distribution in distributions(path=[purelib]):
        for entry in distribution.entry_points:
            if entry.group not in {"console_scripts", "gui_scripts"}:
                continue
            destination = scripts / (entry.name + ".exe" if windows else entry.name)
            if destination.parent != scripts or not destination.is_file():
                continue
            maker.make(f"{entry.name} = {entry.value}", options={"gui": entry.group == "gui_scripts"})
            if not windows:
                _, body = destination.read_bytes().split(b"\n", 1)
                destination.write_bytes(
                    b"#!/bin/sh\n'''exec' \"$(dirname -- \"$0\")/python3\" \"$0\" \"$@\"\n' '''\n" + body
                )


def check_runtime(directory: Path) -> None:
    """Check installed dependency metadata and run the launcher with this Python."""
    python = interpreter(directory)
    subprocess.run(["uv", "pip", "check", "--python", python], check=True)
    env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONHOME", None)
    subprocess.run([python, ROOT / "run-script.py", "--list"], env=env, cwd=ROOT,
                   stdout=subprocess.DEVNULL, check=True)


def prepare_runtime(refresh: bool) -> None:
    """Verify a cached runtime or publish a freshly installed one after checks."""
    signature = f"v2 {TARGET} cpython-{PYTHON_VERSION} {hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()}\n"
    marker = RUNTIME / RECEIPT
    if RUNTIME.is_symlink() or RUNTIME.is_junction() or (RUNTIME.exists() and not marker.is_file()):
        raise ValueError(f"{RUNTIME} already exists outside this packager's management.")
    if not refresh and marker.is_file() and marker.read_text(encoding="utf-8") == signature:
        check_runtime(RUNTIME)
        return

    RUNTIME.parent.mkdir(exist_ok=True)
    with staging_directory(RUNTIME.parent, "runtime") as stage:
        subprocess.run(["uv", "python", "install", "--no-bin", "--no-registry",
                        "--install-dir", stage, PYTHON_VERSION], check=True)
        candidates = [p for p in stage.glob("cpython-*") if interpreter(p).is_file() and not p.is_symlink()]
        if len(candidates) != 1:
            raise ValueError(f"Expected one standalone CPython installation in {stage}.")
        candidate = candidates[0]
        subprocess.run(["uv", "pip", "install", "--python", interpreter(candidate),
                        "--break-system-packages", "-r", REQUIREMENTS], check=True)
        make_entry_points_portable(candidate)
        check_runtime(candidate)
        (candidate / RECEIPT).write_text(signature, encoding="utf-8")
        previous = stage / "previous"
        if RUNTIME.exists():
            RUNTIME.rename(previous)
        try:
            candidate.rename(RUNTIME)
            check_runtime(RUNTIME)
        except BaseException:
            if RUNTIME.exists():
                RUNTIME.rename(candidate)
            if previous.exists():
                previous.rename(RUNTIME)
            raise


def release_files(with_resources: bool) -> Iterator[Path]:
    """Select tracked project files and local runtime assets for this archive."""
    yield from (ROOT / name for name in ROOT_FILES)
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "tools", "utils"], cwd=ROOT)
    for entry in tracked.split(b"\0"):
        if entry:
            path = ROOT / os.fsdecode(entry)
            if path.exists() or path.is_symlink():
                yield path

    directories = [RUNTIME]
    if with_resources:
        directories.extend(ROOT / "deps" / name for name in ("tools", "ocr-models"))
    for directory in directories:
        if directory.is_dir():
            for parent, folders, files in directory.walk():
                folders[:] = sorted(name for name in folders if name != "__pycache__" and not name.startswith(".download-"))
                for name in sorted(files):
                    yield parent / name


def write_archive(with_resources: bool) -> Path:
    """Stream files into a temporary archive, then publish the completed archive."""
    windows = os.name == "nt"
    filename = f"PersonalScripts-{TARGET}" + (".zip" if windows else ".tar.gz")
    with staging_directory(BUILD, "archive") as stage:
        archive = stage / filename
        if windows:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1, strict_timestamps=False) as out:
                for path in release_files(with_resources):
                    if not path.resolve().is_relative_to(ROOT):
                        raise ValueError(f"Resource link points outside the project: {path}")
                    out.write(path, path.relative_to(ROOT))
        else:
            with tarfile.open(archive, "w:gz", compresslevel=1) as tar:
                for path in release_files(with_resources):
                    if path.is_symlink() and (path.readlink().is_absolute() or not path.resolve().is_relative_to(ROOT)):
                        raise ValueError(f"Resource link is not portable: {path}")
                    tar.add(path, arcname=path.relative_to(ROOT), recursive=False)
        destination = BUILD / filename
        archive.replace(destination)
    return destination


def main() -> int:
    """Select a release task and serialize changes to the runtime and archives."""
    Console.initialize_ansi_output()
    parser = Console.argument_parser(HELP)
    parser.add_argument("command", nargs="?", choices=("build-runtime", "package"))
    parser.add_argument("--with-resources", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    packaging_flags = args.with_resources or args.refresh
    if args.command == "build-runtime" and packaging_flags:
        parser.error("--with-resources and --refresh are packaging options; use them with package")
    Console.print_banner("PROJECT RELEASE PACKAGER")
    interactive = args.command is None and not packaging_flags
    task = args.command or "package"
    if interactive:
        task = Menu.select([
            MenuOption(["1"], "Build the portable Python runtime", "build-runtime"),
            MenuOption(["2"], "Create a project release archive", "package"),
        ], prompt="Select a task (Enter to exit)")
        if task is None:
            return 0

    package = task == "package"
    commands = [CmdCheck("uv", hints={"any": "Install uv on the build machine."})]
    if package:
        commands.append(CmdCheck("git"))
    if not Environment.check_commands(*commands):
        return 1
    try:
        from filelock import FileLock, Timeout
    except ImportError as exc:
        print(f"Missing build dependency {exc.name}: python -m pip install filelock", file=sys.stderr)
        return 1
    with_resources = args.with_resources
    if interactive and package:
        with_resources = Menu.select([
            MenuOption(["Y"], "Include local tools and OCR models", True),
            MenuOption(["N"], "Skip optional tools and models", False),
        ], prompt="Include deps/tools and deps/ocr-models?", default_key="N") is True
    try:
        BUILD.mkdir(exist_ok=True)
        with FileLock(BUILD / "package-project.lock", timeout=0):
            prepare_runtime(refresh=args.refresh or not package)
            if not package:
                print(f"{FLGreen}Runtime ready:{CRst} {FGray}{RUNTIME}{CRst}")
                return 0
            print(f"Writing archive for {TARGET}...", flush=True)
            destination = write_archive(with_resources)
    except Timeout:
        print("Another release build is running.", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"{FLRed}Build failed:{CRst} {exc}", file=sys.stderr)
        return 1
    print(f"{FLGreen}Saved:{CRst} {destination} ({destination.stat().st_size / 1024**2:.1f} MiB)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Console.print_keyboard_interrupt_message_and_exit()

