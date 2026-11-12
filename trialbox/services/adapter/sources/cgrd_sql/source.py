"""``cgrd_sql`` source: read-only SQL replica (any SQLAlchemy DSN; SQLite in tests, Oracle/MSSQL on site).

Delta (T-615b, DATA-008): ``--since`` filters on the table's change-time column (the mapping's ``delta:``, canonical
``updated_at``). A row whose change time is NULL is kept; a table without that column is read whole (a row read twice
is merged by its key, a row skipped is a correction lost).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from sqlalchemy import create_engine, text

from adapter.sources.base import Row

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class SqlSource:
    name = "cgrd_sql"

    def __init__(self, dsn: str) -> None:
        self.engine = create_engine(dsn, future=True)

    def _columns(self, source_name: str) -> set[str]:
        with self.engine.connect() as con:  # identifier validated by the caller
            names = list(con.execute(text(f"SELECT * FROM {source_name} WHERE 1 = 0")).keys())
        return {c.lower() for c in names}

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        if not _IDENT.match(source_name) or (delta_column and not _IDENT.match(delta_column)):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r} / {delta_column!r}")
        sql = f"SELECT * FROM {source_name}"  # identifiers validated above; values are bound
        params: dict[str, str] = {}
        if since and delta_column and delta_column.lower() in self._columns(source_name):
            sql += f" WHERE {delta_column} IS NULL OR {delta_column} >= :since"
            params["since"] = since
        with self.engine.connect() as con:
            result = con.execution_options(stream_results=True).execute(text(sql), params)
            cols = list(result.keys())
            for rec in result:
                yield {c: (None if v is None else str(v)) for c, v in zip(cols, rec, strict=True)}
