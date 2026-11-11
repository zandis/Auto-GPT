"""The large CDM tables, partitioned by year (T-106, D-339).

Migration 4 of the ``omop`` schema (:func:`migration`, from ``ddl/partitions.sql``) turns each table of
:data:`PARTITIONED` into a table partitioned by range of its required date, with a default partition that takes the
rows it already held. Before the loader writes rows it calls :func:`ensure_years`: each year it is about to write
gets its partition ``<table>_y<year>`` (rows of that year still in the default partition are moved into it first), so
the default partition only ever holds rows from before the migration.

The pinned official DDL is unchanged: migration 1 still applies it byte for byte. This migration then rebuilds the
tables with the same columns and the same official indexes. The one change is the primary key, ``(id, date)`` in
place of ``(id)``: PostgreSQL asks that a partitioned table's key holds the partition column. The ids still come from
one sequence and the Data Quality checks still test that the id alone is unique (``isPrimaryKey``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from omop.schema import DDL_DIR, OmopError, _statements, pinned

# table -> (id column, partition column: the table's required date)
PARTITIONED: dict[str, tuple[str, str]] = {
    "visit_occurrence": ("visit_occurrence_id", "visit_start_date"),
    "condition_occurrence": ("condition_occurrence_id", "condition_start_date"),
    "drug_exposure": ("drug_exposure_id", "drug_exposure_start_date"),
    "procedure_occurrence": ("procedure_occurrence_id", "procedure_date"),
    "measurement": ("measurement_id", "measurement_date"),
    "observation": ("observation_id", "observation_date"),
    "note": ("note_id", "note_date"),
}
DEFAULT = "ydefault"
_INDEX = re.compile(r"CREATE INDEX (\w+)\s+ON @cdmDatabaseSchema\.(\w+)\s*\(", re.IGNORECASE)


def _official_indexes(table: str) -> list[str]:
    """The pinned indices file's ``CREATE INDEX`` statements on ``table`` (its ``CLUSTER`` statements are left out:
    PostgreSQL does not cluster a partitioned table)."""
    pinned()
    text = (DDL_DIR / "OMOPCDM_postgresql_5.4_indices.sql").read_text(encoding="utf-8")
    out = []
    for st in _statements(text):
        m = _INDEX.match(st)
        if m and m.group(2).lower() == table:
            out.append(st.replace("@cdmDatabaseSchema.", ""))
    return out


def migration() -> str:
    """Migration 4: the template of ``ddl/partitions.sql`` for each table, then the table's official indexes."""
    raw = (DDL_DIR / "partitions.sql").read_text(encoding="utf-8")
    template = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("--")).strip()
    stmts: list[str] = []
    for table, (id_col, date_col) in PARTITIONED.items():
        body = template.replace("{table}", table).replace("{id}", id_col).replace("{date}", date_col)
        stmts.extend(s.strip() for s in body.split(";") if s.strip())
        stmts.extend(_official_indexes(table))
    return ";\n".join(stmts)


def partition_name(table: str, year: int) -> str:
    return f"{table}_y{year:04d}"


def partitions(tx: Any, table: str) -> list[str]:
    """The partitions of ``table`` in the current schema, by name."""
    return sorted(
        str(r[0])
        for r in tx.fetchall(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p "
            "ON p.oid = i.inhparent JOIN pg_namespace n ON n.oid = p.relnamespace WHERE p.relname = ? "
            "AND n.nspname = current_schema()",
            (table,),
        )
    )


def years_of(rows: Iterable[dict[str, Any]], date_col: str) -> set[int]:
    return {d.year for d in (r.get(date_col) for r in rows) if isinstance(d, date)}


def ensure_years(tx: Any, table: str, years: Iterable[int]) -> list[str]:
    """Create the year partitions of ``table`` that ``years`` need and do not have; return the ones made. A year whose
    rows sit in the default partition (written before migration 4) is moved out of it first, inside the caller's
    transaction, so nothing is lost and the partition can be attached."""
    if table not in PARTITIONED:
        raise OmopError(f"{table} is not partitioned")
    date_col = PARTITIONED[table][1]
    have = set(partitions(tx, table))
    made = []
    default = f"{table}_{DEFAULT}"
    for year in sorted(set(years)):
        name = partition_name(table, year)
        if name in have:
            continue
        lo, hi = f"{year:04d}-01-01", f"{year + 1:04d}-01-01"
        held = int(
            tx.fetchval(
                f"SELECT count(*) FROM {default} WHERE {date_col} >= ?::date AND {date_col} < ?::date", (lo, hi)
            )
            or 0
        )
        if held:
            tx.execute(f"CREATE TABLE {name} (LIKE {table} INCLUDING DEFAULTS)")
            tx.execute(
                f"INSERT INTO {name} SELECT * FROM {default} WHERE {date_col} >= ?::date AND {date_col} < ?::date",
                (lo, hi),
            )
            tx.execute(f"DELETE FROM {default} WHERE {date_col} >= ?::date AND {date_col} < ?::date", (lo, hi))
            tx.execute(f"ALTER TABLE {table} ATTACH PARTITION {name} FOR VALUES FROM ('{lo}') TO ('{hi}')")
        else:
            tx.execute(f"CREATE TABLE {name} PARTITION OF {table} FOR VALUES FROM ('{lo}') TO ('{hi}')")
        made.append(name)
    return made


def layout(tx: Any) -> dict[str, dict[str, int]]:
    """Rows per partition of every partitioned table (what the backup drill compares before and after a restore)."""
    out: dict[str, dict[str, int]] = {}
    for table in PARTITIONED:
        out[table] = {p: int(tx.fetchval(f"SELECT count(*) FROM {p}") or 0) for p in partitions(tx, table)}
    return out
