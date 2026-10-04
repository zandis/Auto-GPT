"""``cgrd_sql`` source: read-only SQL replica (any SQLAlchemy DSN; SQLite in tests, Oracle/MSSQL on site)."""

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

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        if not _IDENT.match(source_name) or (delta_column and not _IDENT.match(delta_column)):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r} / {delta_column!r}")
        sql = f"SELECT * FROM {source_name}"  # identifiers validated above; values are bound
        params: dict[str, str] = {}
        if since and delta_column:
            sql += f" WHERE {delta_column} >= :since"
            params["since"] = since
        with self.engine.connect() as con:
            result = con.execution_options(stream_results=True).execute(text(sql), params)
            cols = list(result.keys())
            for rec in result:
                yield {c: (None if v is None else str(v)) for c, v in zip(cols, rec, strict=True)}
