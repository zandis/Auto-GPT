"""``cgrd_sql`` source: read-only SQL replica (any SQLAlchemy DSN; SQLite in tests, Oracle/MSSQL on site).

Delta (T-615b, DATA-008): ``--since`` filters on the table's change-time column (the mapping's ``delta:``, canonical
``updated_at``). A row whose change time is NULL is kept; a table without that column is read whole (a row read twice
is merged by its key, a row skipped is a correction lost).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

from sqlalchemy import Date, bindparam, create_engine, text

from adapter.sources.base import Row

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class SqlSource:
    name = "cgrd_sql"

    def __init__(self, dsn: str) -> None:
        self.engine = create_engine(dsn, future=True)
        self._present: dict[str, bool] = {}  # CGRD-SQL (D-814): source name -> the database has it
        self.absent_why: dict[str, str] = {}  # the kind of error that found a table absent (never its text)

    def columns(self, source_name: str) -> list[str]:
        """The column names of a table or view as the database gives them; no row is read."""
        if not _IDENT.match(source_name):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r}")
        with self.engine.connect() as con:
            result = con.execute(text(f"SELECT * FROM {source_name} WHERE 1 = 0"))
            return [str(c) for c in list(result.keys())]

    def has_table(self, source_name: str) -> bool:
        """CGRD-SQL (D-814): whether the database has the table or view. Absent only when reading it fails **and**
        the catalogue has no table or view by that name; any other failure (a lost connection, no right to read it)
        is raised, never taken for an absent table. Asked once per table."""
        if source_name in self._present:
            return self._present[source_name]
        if not _IDENT.match(source_name):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r}")
        try:
            self.columns(source_name)
            present = True
        except Exception as exc:
            from sqlalchemy import inspect

            self.absent_why[source_name] = type(exc).__name__  # its kind only: the text may hold the connection

            schema, _, name = source_name.rpartition(".")
            insp = inspect(self.engine)  # a catalogue that cannot be read raises: never "absent"
            if insp.has_table(name, schema or None) or name in insp.get_view_names(schema or None):
                raise
            present = False
        self._present[source_name] = present
        return present

    def unlisted(self, listed: set[str]) -> dict[str, int]:
        """M6-TW: the views this account can see that the mapping does not name, with their row counts: said in the
        night's report, never read as data. A view the DBA added for another purpose is told, not dropped silently.
        ponytail: the default schema only, and a COUNT per view; a schema list or a sampled count if a site needs it."""
        from sqlalchemy import inspect

        named = {n.rpartition(".")[2].lower() for n in listed}
        found = {}
        with self.engine.connect() as con:
            for view in sorted(inspect(self.engine).get_view_names()):
                if view.lower() not in named and _IDENT.match(view):
                    found[view] = int(con.execute(text(f"SELECT COUNT(*) FROM {view}")).scalar_one())
        return found

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

    def any_in_window(self, source_name: str, delta_column: str, since: Any, until: Any) -> bool:
        """Whether the table holds a row whose change time is in ``[since, until)`` (D-688): one row asked for at
        most, nothing of it read. The bounds are bound as given (text, or a date for a column of a date type)."""
        from sqlalchemy import column, select, table

        if not _IDENT.match(source_name) or not _IDENT.match(delta_column):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r} / {delta_column!r}")
        schema, _, name = source_name.rpartition(".")
        col: Any = column(delta_column)
        q = select(col).select_from(table(name, col, schema=schema or None)).where(col >= since, col < until).limit(1)
        with self.engine.connect() as con:
            return con.execute(q).first() is not None

    def rows(
        self,
        table: str,
        source_name: str,
        delta_column: str | None,
        since: Any,
        until: Any = None,
        columns: list[str] | None = None,
    ) -> Iterator[Row]:
        """``until`` (T-731): with ``since``, a window of the change-time column, its end not included; a row
        whose change time is NULL is then left out. ``columns``: read only these (matched without regard to case,
        returned under the names given); a column the table does not have is not asked for."""
        if not _IDENT.match(source_name) or (delta_column and not _IDENT.match(delta_column)):
            raise ValueError(f"unsafe identifier in mapping: {source_name!r} / {delta_column!r}")
        if not self.has_table(source_name):  # CGRD-SQL (D-814): absent, said in the night's report; no rows
            return
        what, names = "*", None
        if columns is not None:
            have = {c.lower(): c for c in self.columns(source_name)}
            names = {have[c.lower()]: c for c in columns if c.lower() in have}
            if not names:
                return
            if all(_IDENT.match(c) for c in names):  # else every column is read and the others dropped here
                what = ", ".join(names)
        sql = f"SELECT {what} FROM {source_name}"  # identifiers validated above; values are bound
        params: dict[str, Any] = {}
        if since and delta_column and delta_column.lower() in self._columns(source_name):
            if until:
                sql += f" WHERE {delta_column} >= :since AND {delta_column} < :until"
                params.update(since=since, until=until)
            else:
                sql += f" WHERE {delta_column} IS NULL OR {delta_column} >= :since"
                params["since"] = since
        stmt = text(sql)
        typed = [bindparam(k, type_=Date()) for k, v in params.items() if isinstance(v, date)]
        if typed:  # a day given as a date (D-688): bound as a date, for a column of a date type
            stmt = stmt.bindparams(*typed)
        with self.engine.connect() as con:
            try:
                result = con.execution_options(stream_results=True).execute(stmt, params)
            except Exception:
                if what == "*":
                    raise
                # a column named by a word the database reserves: every column is read and the others dropped here
                con.rollback()
                sql = sql.replace(f"SELECT {what} FROM", "SELECT * FROM", 1)
                stmt = text(sql).bindparams(*typed) if typed else text(sql)
                result = con.execution_options(stream_results=True).execute(stmt, params)
            cols = list(result.keys())
            for rec in result:
                row = {c: (None if v is None else str(v)) for c, v in zip(cols, rec, strict=True)}
                yield row if names is None else {names[c]: v for c, v in row.items() if c in names}
