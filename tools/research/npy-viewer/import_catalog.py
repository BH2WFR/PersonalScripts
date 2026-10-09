"""Metadata-first selection for NPZ/MAT archives and ranged tabular input.

Requirements: numpy, scipy/h5py for MAT, openpyxl for XLSX/XLSM and xlrd for XLS.
Usage: inspect_source runs in a worker; only chosen members are then decoded.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from .array_validation import NUMERIC_KINDS, validate_shape
from .csv_loader import detect_delimiter
from .excel_io import EXCEL_EXTENSIONS, PREVIEW_COLUMNS, PREVIEW_ROWS, inspect_excel
from .mat_loader import inspect_mat
from .table_data import HeaderMode, TableRange

INSPECT_EXTENSIONS = frozenset({".npz", ".mat", ".csv", ".txt", *EXCEL_EXTENSIONS})


@dataclass(frozen=True)
class ImportMember:
    """One source matrix/sheet and metadata safe to display before loading."""

    key: str | None
    label: str
    shape: tuple[int, ...]
    kind: str
    error: str = ""
    preview: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class ImportChoice:
    """Selected member plus optional original table bounds/header/delimiter."""

    key: str | None
    region: TableRange = TableRange()
    header: HeaderMode = HeaderMode.AUTO
    delimiter: str | None = None


@dataclass(frozen=True)
class ImportCatalog:
    """One file's selectable metadata and format-specific range support."""

    path: Path
    members: tuple[ImportMember, ...]
    tabular: bool = False
    text: bool = False
    delimiter: str | None = None
    preferred_key: str | None = None


def inspect_source(path: Path, key: str | None = None) -> ImportCatalog:
    """Inspect dimensions/types and small table previews without decoding arrays.

    Args:
        path: NPZ/MAT/XLSX/XLSM/XLS/CSV/TXT input.
        key: Optional preferred archive member; unknown names are errors.

    Returns:
        Catalog with invalid array members marked unselectable. Table dimensions
        include headings and notes; CSV rows count parsed records, including blanks.

    Raises:
        ValueError: Empty/unsupported files or unknown requested member.
        OSError/ImportError: Inaccessible source or unavailable Excel dependency.
    """
    suffix = path.suffix.lower()
    delimiter: str | None = None
    text = suffix in (".csv", ".txt")
    tabular = text or suffix in EXCEL_EXTENSIONS
    members: list[ImportMember] = []
    if suffix == ".npz":
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                label = name[:-4] if name.endswith(".npy") else name
                shape: tuple[int, ...] = ()
                kind = "unknown"
                error = ""
                try:
                    with archive.open(name) as stream:
                        version = np.lib.format.read_magic(stream)
                        if version == (1, 0):
                            shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                        elif version in ((2, 0), (3, 0)):
                            shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                        else:
                            raise ValueError(f"Unsupported NPY header version: {version}")
                    kind = str(dtype)
                    validate_shape(shape, label)
                    if dtype.kind not in NUMERIC_KINDS:
                        raise ValueError(f"Unsupported dtype: {dtype}; select a numeric array.")
                except (ValueError, EOFError, TypeError) as exc:
                    error = str(exc)
                members.append(ImportMember(label, label, shape, kind, error))
    elif suffix == ".mat":
        members = [ImportMember(item.name, item.name, item.shape, item.kind, item.error) for item in inspect_mat(path)]
    elif suffix in EXCEL_EXTENSIONS:
        members = [ImportMember(item.name, item.name, item.shape, "Worksheet", preview=item.preview)
                   for item in inspect_excel(path)]
    elif text:
        preview: list[tuple[str, ...]] = []
        rows, columns = 0, 0
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            delimiter = detect_delimiter(stream.read(8192))
            stream.seek(0)
            for rows, record in enumerate(csv.reader(stream, delimiter=delimiter, strict=True), 1):
                columns = max(columns, len(record))
                if len(preview) < PREVIEW_ROWS:
                    preview.append(tuple(record[:PREVIEW_COLUMNS]))
        if rows == 0 or columns == 0:
            raise ValueError("The text file contains no table records.")
        members = [ImportMember(None, path.name, (rows, columns), "Text table", preview=tuple(preview))]
    else:
        raise ValueError(f"Unsupported table/archive format: {suffix}")
    if not members:
        raise ValueError(f"No matrices or worksheets were found in {path.name}.")
    if not any(not member.error for member in members):
        raise ValueError(f"No supported numeric matrices in {path.name}.\n" + "\n".join(f"{member.label}: {member.error}" for member in members))
    if key is not None:
        selected = next((member for member in members if member.key == key), None)
        if selected is None:
            raise ValueError(f"Member {key!r} is unavailable in {path.name}.")
        if selected.error:
            raise ValueError(f"{key}: {selected.error}")
    return ImportCatalog(path, tuple(members), tabular, text, delimiter, key)
