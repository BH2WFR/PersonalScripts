"""Shared table ranges and strict numeric conversion for text and Excel files.

Requirements: numpy. Usage: loaders provide numbered rows; blank cells become
NaN, while malformed selected cells report their original row and column.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

type TableArray = NDArray[np.int64 | np.uint64 | np.float64]


class HeaderMode(StrEnum):
    """Treatment of the first selected nonempty record."""

    AUTO = "Auto: first all-text row is a header"
    NONE = "No header (all selected rows are data)"
    FIRST = "First selected row is a header"


@dataclass(frozen=True)
class TableRange:
    """One-based inclusive source bounds; None reads through the last row/column."""

    row_start: int = 1
    column_start: int = 1
    row_end: int | None = None
    column_end: int | None = None

    def validate(self) -> None:
        """Raise ValueError for nonpositive starts or reversed bounds."""
        if self.row_start < 1 or self.column_start < 1:
            raise ValueError("Starting row and column must be at least 1.")
        if self.row_end is not None and self.row_end < self.row_start:
            raise ValueError("Ending row must not precede the starting row.")
        if self.column_end is not None and self.column_end < self.column_start:
            raise ValueError("Ending column must not precede the starting column.")


@dataclass(frozen=True)
class TableData:
    """Numeric cells and optional column labels, after selecting a source range."""

    values: TableArray
    headers: tuple[str, ...] = ()


def table_number(value: object) -> int | float:
    """Parse a numeric cell; None/blank is NaN and other objects are rejected."""
    if value is None:
        return float("nan")
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        raise ValueError("Expected a number or an empty cell.")
    text = value.strip()
    if not text:
        return float("nan")
    try:
        return int(text)
    except ValueError:
        return float(text)


def numeric_table(records: Iterable[tuple[int, Sequence[object]]], region: TableRange = TableRange(),
                  header: HeaderMode = HeaderMode.AUTO, label: str = "Table") -> TableData:
    """Select columns and convert numbered records without silent row loss.

    Args:
        records: Original one-based row numbers and cells, in source order.
        region: Inclusive row/column bounds, applied before validation.
        header: Auto detection, no header, or explicit first selected row.
        label: File/sheet name included in diagnostics.

    Returns:
        Nonempty 2D array retaining integer precision where possible.

    Raises:
        ValueError: Invalid bounds, ragged records, malformed selected cells,
            empty data, or mixed integer/float data that would lose precision.
    """
    region.validate()
    rows: list[list[int | float]] = []
    headers: tuple[str, ...] = ()
    width = 0
    integral = True
    first = True
    has_cells = False
    for number, record in records:
        if number < region.row_start:
            continue
        if region.row_end is not None and number > region.row_end:
            break
        if not record:
            continue
        cells = record[region.column_start - 1:region.column_end]
        if not cells or (region.column_end is not None and len(record) < region.column_end):
            raise ValueError(f"{label} row {number}: selected columns exceed this record's {len(record)} fields.")
        if not width:
            width = len(cells)
        if len(cells) != width:
            raise ValueError(f"{label} row {number}: expected {width} selected fields, got {len(cells)}.")
        if first and header == HeaderMode.FIRST:
            headers = tuple(str(cell).strip() if cell is not None else "" for cell in cells)
            first = False
            continue
        parsed: list[int | float] = []
        invalid: list[int] = []
        for column, cell in enumerate(cells):
            try:
                parsed.append(table_number(cell))
            except (ValueError, OverflowError):
                invalid.append(column)
        if invalid:
            if first and header == HeaderMode.AUTO and len(invalid) == width:
                headers = tuple(str(cell).strip() for cell in cells)
                first = False
                continue
            raise ValueError(f"{label} row {number}, column {region.column_start + invalid[0]}: expected a number or an empty cell. Adjust the input range to exclude headings/notes.")
        first = False
        has_cells |= any(cell is not None and (not isinstance(cell, str) or bool(cell.strip())) for cell in cells)
        integral &= all(isinstance(value, int) for value in parsed)
        rows.append(parsed)
    if not rows or not has_cells:
        raise ValueError(f"{label}: the selected range contains no numeric records.")
    if integral:
        lowest = min(min(row) for row in rows)
        highest = max(max(row) for row in rows)
        if lowest < -(2 ** 63) or highest >= 2 ** 64 or (lowest < 0 and highest >= 2 ** 63):
            raise ValueError(f"{label}: integer values cannot be represented exactly in a 64-bit array.")
        values: TableArray = np.asarray(rows, dtype=np.uint64 if highest >= 2 ** 63 else np.int64)
    else:
        for row in rows:
            for value in row:
                if isinstance(value, int):
                    try:
                        exact = int(float(value)) == value
                    except OverflowError:
                        exact = False
                    if not exact:
                        raise ValueError(f"{label}: floating-point cells mixed with integers would lose precision in float64. Use separate arrays in NPZ.")
        values = np.asarray(rows, dtype=np.float64)
    return TableData(values, headers)
