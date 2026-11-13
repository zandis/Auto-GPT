"""Whether a lake snapshot has a table, asked of the lake (D-649, D-650).

Two places of the matching service tolerate one failure: a snapshot built before the site facts has no
``site_fact`` table (no proposed fact), and a lake without notes has no ``document`` table (every note pair is a
data gap). Both told that case from any other failure by words in the error's text. An error's text is whatever
its author put in it: another failure with those words was taken for a missing table.

Here the lake is asked. After a query of the table failed, one question: how many tables or views of that name the
snapshot has. Only one row with the integer 0 means "no such table". Any other answer, and a failure of the
question itself, leaves the first failure to stop the run (D-127, F-04).
"""

from __future__ import annotations

import re
from typing import Any, Protocol

_NAME = re.compile(r"[a-z][a-z0-9_]*")


class Lake(Protocol):
    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any: ...


def table_sql(table: str) -> str:
    """The question for ``table`` (a plain lower-case name of this code, never a value from outside): one row, one
    number, tables and views together, the name compared without its case."""
    if not _NAME.fullmatch(table):
        raise ValueError(f"not a plain table name: {table!r}")
    return (
        f"SELECT (SELECT count(*) FROM duckdb_tables() WHERE lower(table_name) = '{table}') + "
        f"(SELECT count(*) FROM duckdb_views() WHERE lower(view_name) = '{table}') AS n"
    )


def no_table(lake: Lake, snapshot: str | None, table: str) -> bool:
    """True only when the lake answers that the snapshot has no ``table``: one row with the integer 0."""
    try:
        rows = lake.query(table_sql(table), [], snapshot).to_pylist()
    except Exception:
        return False
    return len(rows) == 1 and type(rows[0].get("n")) is int and rows[0]["n"] == 0


def rows_or_no_table(
    lake: Lake, sql: str, params: list[Any], snapshot: str | None, table: str
) -> list[dict[str, Any]] | None:
    """The rows of a query of ``table``; None when the snapshot has no such table (:func:`no_table`); any other
    failure is raised.

    With no snapshot named, a failed query and the question after it would each read "current", which can move in
    between. So after a failure the lake is asked once which snapshot is current, and the query is put again, and
    then the question, to that name; a second try that works gives its rows (the first failure was passing). A
    lake that answers None for its current snapshot is asked nothing more. A stand-in that has no way to name its
    snapshot is asked the question as it was asked the query."""
    try:
        return list(lake.query(sql, params, snapshot).to_pylist())
    except Exception as first:
        name = snapshot
        current = getattr(lake, "snapshot", None)
        if name is None and callable(current):
            # whatever goes wrong from here on (the lake cannot name its snapshot, the second try fails), the
            # failure that stops the run is the first one
            try:
                name = current()
            except Exception:
                raise first from None
            if name is None:
                raise
            try:
                return list(lake.query(sql, params, name).to_pylist())
            except Exception:
                if no_table(lake, name, table):
                    return None
                raise first from None
        if no_table(lake, name, table):
            return None
        raise
