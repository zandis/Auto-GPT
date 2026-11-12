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

    def columns(self, source_name: str) -> list[str]:
        """The column names of a table or view as the database gives them; no row is read."""
        if not _IDENT.match(source_name):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r}")
        with self.engine.connect() as con:
            result = con.execute(text(f"SELECT * FROM {source_name} WHERE 1 = 0"))
            return [str(c) for c in list(result.keys())]

    def _columns(self, source_name: str) -> set[str]:
        return {c.lower() for c in self.columns(source_name)}  # identifier validated by the caller too

    def column_types(self, source_name: str) -> dict[str, str]:
        """``{column: the database's type}`` when the driver can say (a view or a synonym may not): else empty."""
        from sqlalchemy import inspect

        schema, _, name = source_name.rpartition(".")
        try:
            return {str(c["name"]): str(c["type"]) for c in inspect(self.engine).get_columns(name, schema or None)}
        except Exception:
            return {}

    def rows(
        self,
        table: str,
        source_name: str,
        delta_column: str | None,
        since: str | None,
        until: str | None = None,
        columns: list[str] | None = None,
    ) -> Iterator[Row]:
        """``until`` (T-731): with ``since``, a window of the change-time column, its end not included; a row
        whose change time is NULL is then left out. ``columns``: read only these (matched without regard to case,
        returned under the names given); a column the table does not have is not asked for."""
        if not _IDENT.match(source_name) or (delta_column and not _IDENT.match(delta_column)):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r} / {delta_column!r}")
        what, names = "*", None
        if columns is not None:
            have = {c.lower(): c for c in self.columns(source_name)}
            names = {have[c.lower()]: c for c in columns if c.lower() in have}
            if not names:
                return
            if all(_IDENT.match(c) for c in names):  # else every column is read and the others dropped here
                what = ", ".join(names)
        sql = f"SELECT {what} FROM {source_name}"  # identifiers validated above; values are bound
        params: dict[str, str] = {}
        if since and delta_column and delta_column.lower() in self._columns(source_name):
            if until:
                sql += f" WHERE {delta_column} >= :since AND {delta_column} < :until"
                params.update(since=since, until=until)
            else:
                sql += f" WHERE {delta_column} IS NULL OR {delta_column} >= :since"
                params["since"] = since
        with self.engine.connect() as con:
            try:
                result = con.execution_options(stream_results=True).execute(text(sql), params)
            except Exception:
                if what == "*":
                    raise
                # a column named by a word the database reserves: every column is read and the others dropped here
                con.rollback()
                sql = sql.replace(f"SELECT {what} FROM", "SELECT * FROM", 1)
                result = con.execution_options(stream_results=True).execute(text(sql), params)
            cols = list(result.keys())
            for rec in result:
                row = {c: (None if v is None else str(v)) for c, v in zip(cols, rec, strict=True)}
                yield row if names is None else {names[c]: v for c, v in row.items() if c in names}
