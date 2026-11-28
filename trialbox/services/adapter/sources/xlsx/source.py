"""``xlsx`` source: one workbook, each sheet a table (the mapping's ``source:`` names the sheet).

The door of the proof-of-concept upload: a person fills one workbook (nine sheets, Japanese headers) and the adapter
reads it through the same row path as the ``csv`` source, so ``rename:`` maps a Japanese header like any local column.

Values only. The workbook is opened read-only and no formula is ever run: a cell that holds a formula makes its row a
**refused row** (the row is left out and counted, with its sheet row number and the reason; the night goes on, the
other rows and sheets load). A sheet over ``MAX_ROWS`` rows, a workbook over ``MAX_BYTES`` bytes, or a file that is not
a readable workbook is refused whole with a reason. All are warnings: nothing here stops the night, and the run
report says what was left out and why. A sheet the workbook does not have is a missing table (``has_table``), as a
missing CSV file is.

Cells. A date cell is read as ``YYYY-MM-DD`` (with ``HH:MM:SS`` when it has a time). A date cell whose number format
shows no day (``yyyy-mm``, ``yyyy"年"m"月"``) is read as ``YYYY-MM``: a spreadsheet stores such a month as its first
day, and the day was never typed. A whole number is read without a decimal point.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from adapter.sources.base import Row

log = logging.getLogger("adapter")

MAX_ROWS = 100_000  # data rows of one sheet
MAX_BYTES = 25 * 1024 * 1024  # one workbook

_DAY_TOKEN = re.compile(r"(?<![a-z])d+(?![a-z])|日", re.I)
_MONTH_TOKEN = re.compile(r"m+|月", re.I)


def _month_only(number_format: str) -> bool:
    """Whether a date format shows a year and a month and no day."""
    fmt = re.sub(r'"[^"]*"', lambda mt: "日" if "日" in mt.group(0) else "", number_format or "")
    return bool(_MONTH_TOKEN.search(fmt)) and not _DAY_TOKEN.search(fmt)


def _text(cell: Any) -> str | None:
    value = cell.value
    if value is None:
        return None
    if isinstance(value, datetime):
        if _month_only(str(getattr(cell, "number_format", ""))):
            return f"{value.year:04d}-{value.month:02d}"
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat(timespec="seconds")
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class XlsxSource:
    name = "xlsx"

    def __init__(self, path: Path) -> None:
        if path.is_dir():
            books = sorted(p for p in path.glob("*.xlsx") if not p.name.startswith("~$"))
            if len(books) != 1:
                raise FileNotFoundError(f"xlsx source: the folder {path} must hold exactly one .xlsx file")
            path = books[0]
        if not path.is_file():
            raise FileNotFoundError(f"xlsx source file not found: {path}")
        self.path = path
        self._file_refused: str | None = None
        self._sheets: list[str] = []
        self._rows_refused: dict[str, list[tuple[int, str]]] = {}
        self._sheet_refused: dict[str, str] = {}
        self._open()

    def _open(self) -> None:
        if (size := self.path.stat().st_size) > MAX_BYTES:
            self._file_refused = f"the workbook is {size} bytes, over the limit of {MAX_BYTES}"
        else:
            try:
                wb = load_workbook(self.path, read_only=True, data_only=False)
            except Exception as exc:  # a damaged or foreign file: nothing of it is read
                self._file_refused = f"not a readable workbook ({type(exc).__name__})"
            else:
                self._sheets = list(wb.sheetnames)
                wb.close()
        if self._file_refused:
            log.warning("xlsx source: %s refused: %s", self.path.name, self._file_refused)

    # -- what the run report says
    def has_table(self, source_name: str) -> bool:
        """Whether the workbook has the sheet (a missing sheet is not an empty one)."""
        return source_name in self._sheets

    def refused_rows(self, source_name: str) -> list[tuple[int, str]]:
        """``(sheet row number, reason)`` of every row left out of ``source_name`` on this read; no cell text."""
        return list(self._rows_refused.get(source_name, ()))

    def refused_sheet(self, source_name: str) -> str | None:
        """Why the whole sheet (or the whole file) was left out, or None."""
        return self._sheet_refused.get(source_name) or self._file_refused

    def _refuse_row(self, sheet: str, number: int, why: str) -> None:
        self._rows_refused.setdefault(sheet, []).append((number, why))
        log.warning("xlsx source: %s row %d refused: %s", sheet, number, why)

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        """The sheet's rows one at a time (the first row is the header); a workbook is read whole."""
        if self._file_refused or source_name not in self._sheets:
            return
        self._rows_refused.pop(source_name, None)
        self._sheet_refused.pop(source_name, None)
        wb = load_workbook(self.path, read_only=True, data_only=False)
        try:
            ws = wb[source_name]
            if (ws.max_row or 0) - 1 > MAX_ROWS:  # judged before a row is given: a sheet is refused whole
                why = f"the sheet has {(ws.max_row or 0) - 1} rows, over the limit of {MAX_ROWS}"
                self._sheet_refused[source_name] = why
                log.warning("xlsx source: %s refused: %s", source_name, why)
                return
            header: list[str] | None = None
            for number, cells in enumerate(ws.iter_rows(), start=1):
                if header is None:
                    header = [(_text(c) or "") for c in cells]
                    continue
                values = [_text(c) for c in cells]
                if not any(v for v in values):
                    continue  # a blank line is no row
                if any(getattr(c, "data_type", None) == "f" for c in cells):
                    self._refuse_row(source_name, number, "a cell holds a formula (values only are read)")
                    continue
                yield {h: (v if v is not None else "") for h, v in zip(header, values, strict=False) if h}
        finally:
            wb.close()
