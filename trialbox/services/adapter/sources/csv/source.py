"""``csv`` source: one ``<table>.csv`` (UTF-8, header row) per source table in a directory."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from adapter.sources.base import Row, after


class CsvSource:
    name = "csv"

    def __init__(self, directory: Path) -> None:
        if not directory.is_dir():
            raise FileNotFoundError(f"csv source directory not found: {directory}")
        self.directory = directory

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        path = self.directory / f"{source_name}.csv"
        if not path.exists():
            return
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if delta_column and not after(row.get(delta_column), since):
                    continue
                yield dict(row)
