#!/usr/bin/env python3
"""Calculate file hashes through the OpenSSL command-line tool.

Accepts multiple paths through the project's multiline input helper, validates
regular files and symbolic links, and calculates one or more requested digest
algorithms. Common algorithms supported by the current OpenSSL installation are
shown before input. Directories, broken links, missing paths, and non-regular
files are reported and skipped. Symbolic links to regular files hash the target
content.

Requirements:
    - system: OpenSSL (required)

Usage:
    python file-hash.py
    python file-hash.py --help
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from utils import *  # noqa: E402,F403


DEFAULT_ALGORITHM = "sha256,sha1,md5"
COMMON_ALGORITHMS = (
    "sha256",
    "sha512",
    "sha384",
    "sha224",
    "sha3-256",
    "sha3-512",
    "blake2b512",
    "blake2s256",
    "sm3",
    "sha1",
    "md5",
)
DIGEST_PATTERN = re.compile(r"^[0-9a-fA-F]+$")
ALGORITHM_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


class InputPathKind(Enum):
    """Classification of one user-supplied filesystem path."""

    REGULAR_FILE = "regular file"
    FILE_SYMLINK = "symbolic link to a file"
    DIRECTORY = "directory"
    DIRECTORY_SYMLINK = "symbolic link to a directory"
    BROKEN_SYMLINK = "broken symbolic link"
    MISSING = "missing path"
    OTHER = "non-regular filesystem entry"


@dataclass(frozen=True)
class FileInput:
    """One validated file whose content can be passed to OpenSSL."""

    input_path: str
    resolved_path: str
    is_symlink: bool


@dataclass(frozen=True)
class HashResult:
    """Result of one OpenSSL digest operation for one file and algorithm."""

    file_input: FileInput
    algorithm: str
    digest: Optional[str]
    error: Optional[str]


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the interactive hash calculator."""
    return argparse.ArgumentParser(
        description=(
            f"{FLYellow}FILE HASH - OpenSSL{CRst}\n\n"
            "Calculate one or more OpenSSL digest algorithms for multiple files. "
            "File paths are entered one per line; symbolic links to regular files "
            "are followed and clearly identified."
        ),
        epilog=(
            f"{FLYellow}Interaction:{CRst}\n"
            "  1. Enter file paths, one per line, then finish multiline input.\n"
            "  2. Review common algorithms supported by the installed OpenSSL.\n"
            f"  3. Enter comma-separated algorithms (default: {DEFAULT_ALGORITHM}).\n"
            "  4. Review results grouped by input file.\n\n"
            f"{FLYellow}Examples of algorithms:{CRst}\n"
            f"  {FGray}sha256{CRst}\n"
            f"  {FGray}sha256,md5,sha3-256{CRst}\n\n"
            f"{FLYellow}Requirements:{CRst}\n"
            "  OpenSSL command-line tool (required)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def _run_openssl(
    executable: str,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run OpenSSL with captured UTF-8 output.

    Args:
        executable: Resolved OpenSSL executable path.
        arguments: Arguments excluding the executable name.

    Returns:
        Completed process containing captured stdout, stderr, and exit code.

    Raises:
        OSError: If the executable cannot be started.
    """
    return subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _available_algorithms(executable: str) -> set[str]:
    """Query and return algorithms supported by ``openssl dgst``.

    Args:
        executable: Resolved OpenSSL executable path.

    Returns:
        Lowercase digest names without the leading option hyphen.

    Raises:
        RuntimeError: If OpenSSL cannot list any digest algorithms.
        OSError: If the executable cannot be started.
    """
    result = _run_openssl(executable, ["dgst", "-list"])
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())
        raise RuntimeError(detail or f"OpenSSL exited with code {result.returncode}.")
    algorithms = {
        token[1:].casefold()
        for token in (result.stdout or "").split()
        if token.startswith("-") and ALGORITHM_PATTERN.fullmatch(token[1:])
    }
    if not algorithms:
        raise RuntimeError("OpenSSL returned no supported digest algorithms.")
    return algorithms


def _inspect_input_path(path: str) -> tuple[InputPathKind, Optional[FileInput]]:
    """Classify one path and build a hashable file description when possible.

    Args:
        path: Absolute user-supplied path from the multiline input helper.

    Returns:
        Path classification and a ``FileInput`` for regular files or file
        symlinks. The second item is ``None`` for skipped entries.
    """
    if os.path.islink(path):
        if not os.path.exists(path):
            return InputPathKind.BROKEN_SYMLINK, None
        resolved_path = os.path.realpath(path)
        if os.path.isfile(path):
            return InputPathKind.FILE_SYMLINK, FileInput(path, resolved_path, True)
        if os.path.isdir(path):
            return InputPathKind.DIRECTORY_SYMLINK, None
        return InputPathKind.OTHER, None
    if not os.path.lexists(path):
        return InputPathKind.MISSING, None
    if os.path.isfile(path):
        return InputPathKind.REGULAR_FILE, FileInput(path, path, False)
    if os.path.isdir(path):
        return InputPathKind.DIRECTORY, None
    return InputPathKind.OTHER, None


def _collect_file_inputs(paths: list[str]) -> list[FileInput]:
    """Keep hashable inputs and print a reason for every skipped path."""
    file_inputs: list[FileInput] = []
    for path in paths:
        path_kind, file_input = _inspect_input_path(path)
        if file_input is not None:
            file_inputs.append(file_input)
            if file_input.is_symlink:
                print(
                    f"  {FLCyan}Symlink:{CRst} {FGray}{file_input.input_path}{CRst} "
                    f"-> {file_input.resolved_path}"
                )
            continue
        print(f"  {FLYellow}Skipped ({path_kind.value}):{CRst} {FGray}{path}{CRst}")
    return file_inputs


def _prompt_algorithms(available_algorithms: set[str]) -> list[str]:
    """Prompt until every requested comma-separated algorithm is supported."""
    common_algorithms = [
        algorithm
        for algorithm in COMMON_ALGORITHMS
        if algorithm in available_algorithms
    ]
    if common_algorithms:
        print(
            f"\n  {FLCyan}Supported common algorithms:{CRst} \n"
            f"{'    '.join(common_algorithms)}"
        )
        print(f"{FGray}  allow using comma-separated list of algorithms (e.g. `{CRst}sha256,md5{FGray}`){CRst}")
    while True:
        raw_value = Input.prompt(
            f"{FLYellow}Hash algorithms {FGray}[{DEFAULT_ALGORITHM}]"
            f"{CRst}{FLYellow} > {CRst}",
            default=DEFAULT_ALGORITHM,
        )
        algorithms: list[str] = []
        invalid_names: list[str] = []
        for raw_algorithm in raw_value.split(","):
            algorithm = raw_algorithm.strip().removeprefix("-").casefold()
            if not algorithm:
                continue
            if not ALGORITHM_PATTERN.fullmatch(algorithm):
                invalid_names.append(raw_algorithm.strip())
                continue
            if algorithm not in algorithms:
                algorithms.append(algorithm)
        if invalid_names:
            print(
                f"{FLRed}Invalid algorithm name(s):{CRst} "
                f"{', '.join(invalid_names)}"
            )
            continue
        if not algorithms:
            print(f"{FLRed}Enter at least one digest algorithm.{CRst}")
            continue
        unsupported = [
            algorithm
            for algorithm in algorithms
            if algorithm not in available_algorithms
        ]
        if unsupported:
            print(
                f"{FLRed}Unsupported by this OpenSSL installation:{CRst} "
                f"{', '.join(unsupported)}"
            )
            continue
        return algorithms


def _calculate_hash(
    executable: str,
    file_input: FileInput,
    algorithm: str,
) -> HashResult:
    """Calculate one file digest and validate OpenSSL's output.

    Args:
        executable: Resolved OpenSSL executable path.
        file_input: Validated file or file symlink.
        algorithm: Supported digest name without a leading hyphen.

    Returns:
        Digest result or a failure description; this function does not raise
        for ordinary OpenSSL failures.
    """
    try:
        result = _run_openssl(
            executable,
            ["dgst", f"-{algorithm}", "-r", file_input.resolved_path],
        )
    except OSError as exc:
        return HashResult(file_input, algorithm, None, str(exc))
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split())
        error = detail or f"OpenSSL exited with code {result.returncode}."
        return HashResult(file_input, algorithm, None, error)
    output_text = (result.stdout or "").strip()
    output_line = output_text.splitlines()
    digest = output_line[-1].split(maxsplit=1)[0] if output_line else ""
    if not DIGEST_PATTERN.fullmatch(digest):
        return HashResult(
            file_input,
            algorithm,
            None,
            f"Unexpected OpenSSL output: {output_text or '(empty)'}",
        )
    return HashResult(file_input, algorithm, digest.casefold(), None)


def _calculate_all(
    executable: str,
    file_inputs: list[FileInput],
    algorithms: list[str],
) -> list[HashResult]:
    """Calculate every file/algorithm combination with task-count progress."""
    results: list[HashResult] = []
    total_tasks = len(file_inputs) * len(algorithms)
    task_index = 0
    for file_input in file_inputs:
        for algorithm in algorithms:
            task_index += 1
            print(
                f"  {FGray}[{task_index}/{total_tasks}]{CRst} "
                f"{FLCyan}{algorithm}{CRst} {file_input.input_path}"
            )
            results.append(_calculate_hash(executable, file_input, algorithm))
    return results


def _print_results(
    file_inputs: list[FileInput],
    algorithms: list[str],
    results: list[HashResult],
) -> int:
    """Print results grouped by input file and return the failure count."""
    failures = 0
    result_map = {
        (result.file_input.input_path, result.algorithm): result
        for result in results
    }
    print(f"\n{FLYellow}Hash results{CRst}")
    for file_input in file_inputs:
        print(f"\n  {FLYellow}File:{CRst} {file_input.input_path}")
        if file_input.is_symlink:
            print(f"  {FLCyan}Target:{CRst} {file_input.resolved_path}")
        for algorithm in algorithms:
            result = result_map[(file_input.input_path, algorithm)]
            label = algorithm.upper()
            if result.error is not None:
                failures += 1
                print(f"  {FLRed}{label}:{CRst} ERROR: {result.error}")
            else:
                print(f"  {FLCyan}{label}:{CRst} {result.digest}")
    return failures


def main(argv: Optional[list[str]] = None) -> int:
    """Collect paths and algorithms, calculate hashes, and print grouped results."""
    parser = _build_argument_parser()
    parser.parse_args(argv)

    Utils.set_locale_utf8()
    Utils.print_banner("FILE HASH - OpenSSL")

    openssl_check = CmdCheck(
        "openssl",
        required=True,
        hints={
            "windows": f"  {FGray}scoop install openssl{CRst}",
            "macos": f"  {FGray}brew install openssl@3{CRst}",
            "linux": f"  {FGray}sudo apt install openssl{CRst}",
        },
    )
    if not Utils.check_commands(openssl_check) or openssl_check.path is None:
        return 1
    try:
        available_algorithms = _available_algorithms(openssl_check.path)
    except (OSError, RuntimeError) as exc:
        print(f"{FLRed}Cannot query OpenSSL digest algorithms:{CRst} {exc}")
        return 1

    paths = Input.resolve_input_paths_multi(
        prompt_text="Enter file paths (one per line)",
        path_type="any",
        validate_exists=False,
        glob=False,
    )
    file_inputs = _collect_file_inputs(paths)
    if not file_inputs:
        print(f"{FLRed}No regular files are available to hash.{CRst}")
        return 1
    algorithms = _prompt_algorithms(available_algorithms)

    print(
        f"\n  {FLCyan}Calculating:{CRst} {len(file_inputs)} file(s) x "
        f"{len(algorithms)} algorithm(s)"
    )
    results = _calculate_all(openssl_check.path, file_inputs, algorithms)
    failures = _print_results(file_inputs, algorithms, results)
    if failures:
        print(f"\n{FLRed}Completed with {failures} failed hash operation(s).{CRst}")
        return 1
    print(f"\n{FLGreen}All hash operations completed successfully.{CRst}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        Utils.print_keyboard_interrupt_message_and_exit()
