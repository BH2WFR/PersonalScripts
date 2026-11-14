"""Shared Rime text-table I/O; conversion policies belong to the IME entries."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
import sys
import tempfile


class RimeFormat(StrEnum):
    """Column layout of a Rime text dictionary."""

    AUTO = "auto"
    DICT = "dict"
    USERDB = "userdb"


@dataclass(frozen=True)
class RimeEntry:
    """One text/code pair, with an integer weight (negative means deleted)."""

    text: str
    code: str
    weight: int = 0


@dataclass
class RimeReadResult:
    """Parsed entries and malformed-row counts, with at most five line samples."""

    entries: list[RimeEntry] = field(default_factory=list)
    invalid_rows: int = 0
    invalid_lines: list[int] = field(default_factory=list)


class Rime:
    """Read UTF-8 Rime dictionaries and safely write generated text tables."""

    @staticmethod
    def read(
        path: Path,
        *,
        format: RimeFormat = RimeFormat.AUTO,
        read_weights: bool = True,
        progress: bool = False,
    ) -> RimeReadResult:
        """Read a dict.yaml/TSV export or a userdb.txt sync snapshot.

        YAML headers may reorder columns; text and code must be present.
        AUTO detects snapshot metadata or a c= field in the first data row;
        otherwise it assumes text/code/weight. Blank lines and comments are
        ignored. Bad rows are counted and skipped. A BOM is accepted.

        Args:
            path: Text input; binary databases are unsupported.
            format: Explicit layout, or automatic detection per file.
            read_weights: False ignores weights (useful for shape tables).
            progress: Show tqdm line progress only on an interactive terminal.

        Raises:
            ValueError: Invalid YAML header, unsupported columns, or binary data.
            OSError: Input cannot be read.
            UnicodeError: Input is not UTF-8.
        """
        import yaml
        from tqdm import tqdm

        result = RimeReadResult()
        selected = RimeFormat(format)
        columns = ["text", "code", "weight"]
        header: list[str] = []
        in_header = False
        body_started = False
        with path.open("r", encoding="utf-8-sig") as stream:
            for number, line in enumerate(tqdm(
                stream, desc=path.name, unit="lines",
                disable=not (progress and sys.stderr.isatty()),
            ), 1):
                if "\0" in line:
                    raise ValueError("Binary databases are unsupported; export or sync to text first.")
                stripped = line.strip()
                if in_header:
                    if stripped == "...":
                        try:
                            metadata = yaml.safe_load("".join(header))
                        except yaml.YAMLError as exc:
                            raise ValueError(f"Invalid Rime YAML header: {exc}") from exc
                        if not isinstance(metadata, dict):
                            raise ValueError("The Rime YAML header must be a mapping.")
                        columns = metadata.get("columns", columns)
                        if (not isinstance(columns, list)
                                or not all(isinstance(item, str) for item in columns)
                                or len(set(columns)) != len(columns)
                                or "text" not in columns or "code" not in columns):
                            raise ValueError("Dictionary columns must include unique text and code columns.")
                        in_header = False
                        body_started = True
                        if selected == RimeFormat.AUTO:
                            selected = RimeFormat.DICT
                    else:
                        header.append(line)
                    continue
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    if (selected == RimeFormat.AUTO
                            and stripped.lower() == "# rime user dictionary"):
                        selected = RimeFormat.USERDB
                    continue
                if stripped == "---" and not body_started:
                    in_header = True
                    continue
                body_started = True
                fields = [item.strip() for item in line.rstrip("\r\n").split("\t")]
                if selected == RimeFormat.AUTO and len(fields) >= 2:
                    selected = (RimeFormat.USERDB if len(fields) >= 3
                                and re.search(r"(?:^|\s)c=", fields[2]) else RimeFormat.DICT)
                try:
                    weight = 0
                    if selected == RimeFormat.USERDB:
                        code, text = fields[:2]
                        match = re.search(r"(?:^|\s)c=(-?[0-9]+)(?=\s|$)", fields[2])
                        if match is None:
                            raise ValueError("Missing commit count")
                        if read_weights:
                            weight = int(match[1])
                    else:
                        text = fields[columns.index("text")]
                        code = fields[columns.index("code")]
                        if read_weights and "weight" in columns:
                            index = columns.index("weight")
                            if index < len(fields) and fields[index]:
                                weight = int(fields[index])
                    if not text or not code:
                        raise ValueError("Empty text or code")
                except (IndexError, ValueError):
                    result.invalid_rows += 1
                    if len(result.invalid_lines) < 5:
                        result.invalid_lines.append(number)
                    continue
                result.entries.append(RimeEntry(text, code, weight))
        if in_header:
            raise ValueError("Unterminated Rime YAML header; expected '...'.")
        return result

    @staticmethod
    def write_rows(
        path: Path,
        rows: Iterable[str],
        *,
        sources: Iterable[Path] = (),
        overwrite: bool = False,
    ) -> None:
        """Write UTF-8 without BOM and LF endings through a temporary file.

        Each row receives a newline. Parent directories must exist. Rejects
        source aliases (including hard links), and existing outputs unless
        overwrite=True. A generation/write failure retains the existing file.
        Only replaces the destination after all rows have been written.
        """
        for source in sources:
            if path.resolve() == source.resolve() or (
                path.exists() and source.exists() and path.samefile(source)
            ):
                raise ValueError("Output must differ from every input file.")
        if path.exists() and not overwrite:
            raise FileExistsError(f"Output already exists: {path}")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                for row in rows:
                    stream.write(row + "\n")
            if overwrite:
                os.replace(temporary, path)
            else:
                # Linking fails if a competing process created the destination.
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
