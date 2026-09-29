"""Read numeric CSV tables without silently discarding malformed records.

Requirements: numpy. Usage: imported by data_model for CSV documents.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

type CSVArray = NDArray[np.int64 | np.uint64 | np.float64]
CSV_DELIMITERS = ",;\t"


@dataclass(frozen=True)
class CSVData:
    """Numeric table and optional first-record column labels."""

    values: CSVArray
    headers: tuple[str, ...]


def _number(text: str) -> int | float:
    text = text.strip()
    if not text:
        return float("nan")
    try:
        return int(text)
    except ValueError:
        return float(text)


def read_csv(path: Path) -> CSVData:
    """Load a UTF-8 numeric table with comma, semicolon or tab separators.

    Args:
        path: Existing CSV file; a UTF-8 BOM and blank records are accepted.

    Returns:
        A 2D numeric array. Entirely textual first records are column headers;
        empty cells are NaN. All-integer tables retain int64/uint64 precision.

    Raises:
        ValueError: Empty/ragged tables, invalid cells or integers beyond 64 bits.
        OSError: File access failure. UnicodeError: Input is not UTF-8.
    """
    rows: list[list[int | float]] = []
    headers: tuple[str, ...] = ()
    width = 0
    integral = True
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(8192)
        stream.seek(0)
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
        except csv.Error:
            first = next((line for line in sample.splitlines() if line.strip()), "")
            delimiter = max(CSV_DELIMITERS, key=first.count)
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        try:
            for record in reader:
                if not record or (len(record) == 1 and not record[0].strip()):
                    continue
                if not width:
                    width = len(record)
                if len(record) != width:
                    raise ValueError(f"CSV line {reader.line_num}: expected {width} fields, got {len(record)}.")
                parsed: list[int | float] = []
                invalid: list[int] = []
                for column, cell in enumerate(record):
                    try:
                        parsed.append(_number(cell))
                    except ValueError:
                        invalid.append(column)
                if invalid:
                    if not rows and not headers and len(invalid) == width:
                        headers = tuple(cell.strip() for cell in record)
                        continue
                    raise ValueError(f"CSV line {reader.line_num}, column {invalid[0] + 1}: expected a number or an empty cell.")
                integral &= all(isinstance(value, int) for value in parsed)
                rows.append(parsed)
        except csv.Error as exc:
            raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
    if not rows:
        raise ValueError("The CSV file contains no numeric records.")
    if integral:
        lowest = min(min(row) for row in rows)
        highest = max(max(row) for row in rows)
        if lowest < -(2 ** 63) or highest >= 2 ** 64 or (lowest < 0 and highest >= 2 ** 63):
            raise ValueError("CSV integer values cannot be represented exactly in a 64-bit integer array.")
        values: CSVArray = np.asarray(rows, dtype=np.uint64 if highest >= 2 ** 63 else np.int64)
    else:
        for row in rows:
            for value in row:
                if isinstance(value, int):
                    try:
                        exact = int(float(value)) == value
                    except OverflowError:
                        exact = False
                    if not exact:
                        raise ValueError("CSV mixes floating-point cells with integers that lose precision in float64. "
                                         "Rescale the integer coordinates or store separate arrays in NPZ.")
        values = np.asarray(rows, dtype=np.float64)
    return CSVData(values, headers)
