"""SELECT-only guard for ``POST /query`` (SPEC §4.5): parsed with sqlglot; anything but one read query is rejected.

Defence in depth: the query connection is also read-only with ``enable_external_access=false`` and a locked
configuration, so file-reading table functions fail even if a new one slipped past this list.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_FORBIDDEN_FUNCS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_text",
    "read_blob",
    "parquet_scan",
    "glob",
    "query_table",
    "query",
    "sniff_csv",
    "parquet_metadata",
    "parquet_schema",
    "duckdb_secrets",
    "duckdb_settings",
    "getenv",
    "pragma_database_list",
}
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
LAKE_TABLES = {
    "patient",
    "practitioner",
    "encounter",
    "appointment",
    "condition",
    "observation",
    "medication",
    "procedure",
    "report",
    "document",
    "claim",
    "consent",
    "document_chunk",
    "lake_meta",
}


class SqlRejected(ValueError):
    pass


def check_select(sql: str) -> None:
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise SqlRejected(f"unparseable SQL: {str(exc)[:200]}") from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SqlRejected("exactly one statement is allowed")
    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise SqlRejected(f"only SELECT queries are allowed (got {type(root).__name__})")
    for node in root.walk():
        if isinstance(
            node,
            (
                exp.Insert,
                exp.Update,
                exp.Delete,
                exp.Create,
                exp.Drop,
                exp.Alter,
                exp.Command,
                exp.Pragma,
                exp.Set,
                exp.Copy,
                exp.Attach,
                exp.Detach,
                exp.Use,
                exp.Merge,
            ),
        ):
            raise SqlRejected(f"forbidden statement element {type(node).__name__}")
        if isinstance(node, exp.Func):
            name = (node.sql_name() if not isinstance(node, exp.Anonymous) else node.name).lower()
            if name in _FORBIDDEN_FUNCS or name.startswith("read_"):
                raise SqlRejected(f"forbidden function {name}")
    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        if isinstance(table.this, exp.Literal) or (
            table.this is not None and not isinstance(table.this, exp.Identifier)
        ):
            if isinstance(table.this, (exp.Anonymous, exp.Func)):
                continue  # table functions are checked above
            raise SqlRejected("file paths are not allowed as tables")
        name = table.name.lower()
        if table.db or (name not in LAKE_TABLES and name not in ctes):
            raise SqlRejected(f"unknown table {table.sql()!r}")
