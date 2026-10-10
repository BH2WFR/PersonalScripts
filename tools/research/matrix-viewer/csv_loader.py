"""Read numeric CSV/TXT ranges without discarding malformed selected cells.

Requirements: numpy. Usage: imported by data_model for CSV documents.
"""

import csv
from pathlib import Path

from .table_data import HeaderMode, TableData, TableRange, numeric_table

CSV_DELIMITERS = ",;\t"


def detect_delimiter(sample: str) -> str:
    """Infer comma/semicolon/tab even with a preamble before the actual table."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return max(CSV_DELIMITERS, key=sample.count)


def read_csv(path: Path, region: TableRange = TableRange(), header: HeaderMode = HeaderMode.AUTO,
             delimiter: str | None = None) -> TableData:
    """Load a UTF-8 numeric table with comma, semicolon or tab separators.

    Args:
        path: Existing CSV file; a UTF-8 BOM and blank records are accepted.
        region: One-based inclusive source record/column bounds, before headers.
        header: First selected nonblank record treatment; auto detection by default.
        delimiter: Comma, semicolon or tab; None infers from the file sample.

    Returns:
        A 2D numeric array. Entirely textual first records are column headers;
        empty cells are NaN. All-integer tables retain int64/uint64 precision.

    Raises:
        ValueError: Empty/ragged tables, invalid cells or integers beyond 64 bits.
        OSError: File access failure. UnicodeError: Input is not UTF-8.
    """
    region.validate()
    if delimiter is not None and delimiter not in tuple(CSV_DELIMITERS):
        raise ValueError("CSV delimiter must be comma, semicolon or tab.")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        if delimiter is None:
            delimiter = detect_delimiter(stream.read(8192))
            stream.seek(0)
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        try:
            records = ((number, row) for number, row in enumerate(reader, 1)
                       if row and not (len(row) == 1 and not row[0].strip()))
            return numeric_table(records, region, header, f"{path.name} (CSV)")
        except csv.Error as exc:
            raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
