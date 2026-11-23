"""Lexical conversions for a single pasted path, independent of the host OS."""

from collections.abc import Callable, Mapping
import os
import ntpath
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote

from .paths import Paths


SEPARATORS = {"Backslash": "\\", "Forward slash": "/", "Double backslash": "\\\\"}
ENV_STYLES = {"cmd": "%{}%", "Bash": "${}", "PowerShell": "$env:{}"}
DIRECTORY_VARIABLES = (
    "USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramData", "ProgramFiles",
    "ProgramW6432", "CommonProgramFiles", "SystemRoot", "windir", "SystemDrive",
    "PUBLIC", "OneDrive", "OneDriveConsumer", "OneDriveCommercial", "TEMP", "TMP", "HOME",
)
_DRIVE = re.compile(r"^[A-Za-z]:")
_MSYS_DRIVE = re.compile(r"^/([a-zA-Z])(?:/|$)")
_VARIABLE = re.compile(
    r"^(?:%([a-z_]\w*)%|\$\{(?:env:)?([a-z_]\w*)\}|\$(?:env:)?([a-z_]\w*))(?=[\\/]|$)",
    re.I | re.ASCII,
)


def remove_quotes(line: str, allowed: str = "\"'") -> str:
    """Peel matching outer pairs. Preserve interior spaces and unmatched input."""
    result = line
    while len(candidate := result.strip()) >= 2:
        if candidate[0] != candidate[-1] or candidate[0] not in allowed:
            break
        result = candidate[1:-1]
    return result


def add_quotes(line: str, mark: str) -> str:
    """Wrap a nonblank line once in the selected quote character."""
    value = line.strip()
    if not value or (len(value) >= 2 and value[0] == value[-1] == mark):
        return line
    return mark + value + mark


def transform_quoted_path(line: str, transform: Callable[[str], str]) -> str:
    """Transform the path inside surrounding whitespace and matching quotes."""
    start = len(line) - len(line.lstrip())
    end = len(line.rstrip())
    while end - start >= 2 and line[start] == line[end - 1] and line[start] in "\"'":
        start += 1
        end -= 1
    if start >= end:
        return line
    return line[:start] + transform(line[start:end]) + line[end:]


def forward_path(path: str) -> str:
    """Convert single or escaped backslashes while preserving the UNC authority."""
    unc = path.startswith("\\\\") or path.startswith("//")
    body = path.lstrip("/\\") if unc else path
    return ("//" if unc else "") + body.replace("\\\\", "/").replace("\\", "/")


def remove_file_prefix(path: str) -> str:
    """Decode a file URL to path text, including UNC hosts and pasted drive paths."""
    if not path.lower().startswith("file://"):
        return path
    body = unquote(path[7:])
    if body.lower().startswith("localhost/"):
        body = body[len("localhost"):]
    if body.startswith("./"):
        return body[2:]  # Relative-path convention shared with add_file_prefix.
    if body.startswith("/") and _DRIVE.match(body[1:]):
        return body[1:]
    if not body or body.startswith(("/", "\\", "../")) or _DRIVE.match(body):
        return body
    return "//" + body


def add_file_prefix(path: str) -> str:
    """Encode a drive, UNC or rooted path. Use file://./ as a relative marker."""
    if not path or path.lower().startswith("file://"):
        return path
    value = forward_path(path)
    if value.startswith("//"):
        body = value if value[2:].lower().startswith("localhost/") else value[2:]
    elif re.match(r"^[A-Za-z]:/", value):
        body = "/" + value
    elif value.startswith("/"):
        body = value
    else:
        body = "./" + value
    return "file://" + quote(body, safe="/:")


def convert_separators(path: str, source: str, target: str) -> str:
    """Replace the selected separator literally. File URLs first decode to paths."""
    if path.lower().startswith("file://"):
        return forward_path(remove_file_prefix(path)).replace("/", target)
    return path.replace(source, target)


def to_msys(path: str) -> str:
    """Render drive-absolute paths as /c/... and keep relative or UNC roots."""
    value = forward_path(remove_file_prefix(path))
    if re.match(r"^[A-Za-z]:/", value):
        return "/" + value[0].lower() + value[2:]
    return value


def from_msys(path: str, separator: str) -> str:
    """Restore an MSYS drive mount and render all separators in the chosen style."""
    value = forward_path(remove_file_prefix(path))
    if match := _MSYS_DRIVE.match(value):
        value = match[1].upper() + ":/" + value[match.end():]
    return value.replace("/", separator)


def shorten_environment(path: str, style: str, environment: Mapping[str, str] = os.environ) -> str:
    """Replace the longest known directory prefix at a component boundary."""
    value = forward_path(remove_file_prefix(path))
    windows = bool(_DRIVE.match(value) or value.startswith("//"))
    variables = {key.upper(): val for key, val in environment.items()}
    best = ""
    best_name = ""
    for name in DIRECTORY_VARIABLES:
        prefix = forward_path(variables.get(name.upper(), "")).rstrip("/")
        if not prefix or len(prefix) <= len(best):
            continue
        head = value[:len(prefix)]
        matches = head.lower() == prefix.lower() if windows else head == prefix
        if matches and value[len(prefix):len(prefix) + 1] in ("", "/"):
            best, best_name = prefix, name
    if not best_name:
        return path
    # Use the environment's actual spelling for case-sensitive shells.
    name = next(key for key in environment if key.upper() == best_name.upper())
    token = ENV_STYLES[style].format(name)
    suffix = value[len(best):]
    if windows and style != "Bash":
        suffix = suffix.replace("/", "\\")
    return token + suffix


def expand_environment(path: str, environment: Mapping[str, str] = os.environ) -> str:
    """Expand a leading shell variable once. Leave unknown variables literal."""
    match = _VARIABLE.match(path)
    if not match:
        return path
    name = next(group for group in match.groups() if group is not None)
    try:
        root = Paths.expand_template(f"%{name}%", environment, {})
    except ValueError:
        return path
    tail = path[match.end():]
    if not tail:
        return root
    sep = "\\" if "\\" in root or re.fullmatch(r"[A-Za-z]:", root) else "/"
    return root.rstrip("/\\") + sep + forward_path(tail.lstrip("/\\")).replace("/", sep)


def home_path(path: str, target: str, *, home: str | None = None) -> str:
    """Render a path as absolute, tilde-relative or a shell's home variable.

    Relative paths are based on the working directory. Paths outside the home
    directory keep their original text when a home-relative form is requested.
    An explicit home directory also allows foreign Windows paths to be converted.
    """
    home = home or str(Path.home())
    windows = bool(ntpath.splitdrive(home)[0])
    home_name = "USERPROFILE" if windows and target != "Bash" else "HOME"
    value = forward_path(remove_file_prefix(path))
    head = value.partition("/")[0]
    reference = _VARIABLE.fullmatch(head)
    variable = next((v for v in reference.groups() if v), "") if reference else ""
    if head == "~" or variable.upper() in {"HOME", "USERPROFILE"}:
        value = home.rstrip("/\\") + value[len(head):] if len(value) > len(head) else home
    elif reference:
        value = expand_environment(value)
        if _VARIABLE.match(value):
            return path
    elif head.startswith("~"):
        return path

    if not value:
        return path
    if ntpath.splitdrive(value)[0]:
        absolute = ntpath.abspath(value)
    elif not windows and posixpath.isabs(value):
        absolute = posixpath.normpath(value)
    elif windows and os.name != "nt" and not posixpath.isabs(value):
        # A foreign home provides no Windows working directory for a relative path.
        return path
    else:
        absolute = Paths.resolve_path(value, os.getcwd(), expand_environment=False)
    if target == "Absolute":
        return absolute

    module = ntpath if windows else posixpath
    try:
        relative = module.relpath(absolute, home)
    except ValueError:  # Different drives or UNC shares.
        return path
    if relative == ".." or relative.startswith(".." + module.sep):
        return path
    root = "~" if target == "~" else ENV_STYLES[target].format(home_name)
    if relative == ".":
        return root
    sep = "\\" if windows and target in {"cmd", "PowerShell"} else "/"
    return root + sep + relative.replace(module.sep, sep)
