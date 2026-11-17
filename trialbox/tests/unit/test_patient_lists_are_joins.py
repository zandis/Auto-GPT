"""NEW-B-49 (D-750): a query that takes a list of patients or record ids reads it as a join (T-694 part 4).

``list_contains(list, pid)`` is checked row by row against the whole list: the cost is rows times the list's length
(F-07 of the scale review: 1 M rows x 50,000 patients, 28 s). ``pid IN (SELECT unnest(list))`` is a hash semi join:
rows plus list. Measured (DuckDB, 1 M rows): 10,000 patients 2.34 s as a list, 0.51 s as a join."""

from __future__ import annotations

import collections
import random
import re
from pathlib import Path
from typing import Any

import duckdb
import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
ID_COLUMNS = ("pid", "oid", "cid", "mid", "prid", "rid", "eid", "kid")  # patients and the record ids of a scope
# a per-row list check (DuckDB's names for it) whose second argument is a patient or record-id column
PER_ROW = re.compile(
    r"\b(?:list_contains|list_has|array_contains|array_has)\s*\(\s*(?:[^,()]|\([^()]*\))*?,\s*(?:\w+\.)?"
    rf"(?:{'|'.join(ID_COLUMNS)})\s*\)",
    re.IGNORECASE,
)
# what still asks that way, and why
STILL: dict[str, tuple[int, str]] = {
    "services/matching/cascade/engine.py": (1, "NOTES_SQL: the note stage in batches, T-694 part 3 (lane A2)"),
    "services/criteria_compiler/compile_sql/generator.py": (1, "the approved S1 SQL (D-275), asked in batches (D-748)"),
}


def _found() -> dict[str, int]:
    out: dict[str, int] = {}
    for d in ("services", "libs", "tools"):
        for p in (ROOT / d).rglob("*.py"):
            if "tests" in p.parts:
                continue
            n = len(PER_ROW.findall(p.read_text(encoding="utf-8")))
            if n:
                out[str(p.relative_to(ROOT))] = n
    return out


def test_no_query_checks_each_row_against_a_patient_list() -> None:
    assert _found() == {k: n for k, (n, _) in STILL.items()}, "read the list as a join: pid IN (SELECT unnest(...))"


@pytest.mark.parametrize(
    "sql",
    [
        "WHERE list_contains(CAST($1 AS VARCHAR[]), pid)",
        "WHERE list_contains($1::VARCHAR[], pid)",
        "AND LIST_CONTAINS( CAST( $3 AS varchar[] ), e.pid )",
        "AND array_has(CAST($2 AS TEXT[]), kid)",
        "list_contains((SELECT pids FROM params), p.pid)",
        "list_has($2::VARCHAR[], oid)",
    ],
)
def test_the_pattern_finds_each_form(sql: str) -> None:
    assert PER_ROW.search(sql)


@pytest.mark.parametrize(
    "sql", ["list_contains(CAST($2 AS VARCHAR[]), code)", "list_contains(CAST($2 AS VARCHAR[]), did)", "pid = $1"]
)
def test_the_pattern_leaves_code_lists_and_one_patient(sql: str) -> None:
    assert not PER_ROW.search(sql)


# ---------------------------------------------------------------------------------------------- the code's own SQL
def _lake() -> duckdb.DuckDBPyConnection:
    """Every lake table (``lake.flatten.SCHEMAS``) with synthetic rows: NULL and repeated patients and ids."""
    from lake.flatten import SCHEMAS

    rnd = random.Random(7)
    con = duckdb.connect()
    pids = [f"p{i}" for i in range(12)] + [None]
    values: dict[str, list[Any]] = {
        "VARCHAR": ["x1", "x2", "x7", None, ""],
        "DATE": ["2026-01-01", "2026-06-01", None],
        "TIMESTAMP": ["2026-01-01 10:00", "2026-06-01 09:00", None],
        "DOUBLE": [1.0, None],
        "BOOLEAN": [True, False, None],
    }
    for table, cols in SCHEMAS.items():
        names = [n for n, _ in cols]
        allc = cols + [(c, "VARCHAR") for c in ("src_table", "src_row_hash", "mapping_version") if c not in names]
        con.execute(f'CREATE TABLE "{table}" (' + ", ".join(f'"{n}" {t}' for n, t in allc) + ")")
        rows = []
        for _ in range(80):
            row = []
            for n, t in allc:
                if n == "pid":
                    row.append(rnd.choice(pids))
                elif n == "status":
                    row.append(rnd.choice(["booked", "final", None]))
                else:
                    row.append(rnd.choice(values.get(t, [None])))
            rows.append(row)
        con.executemany(f'INSERT INTO "{table}" VALUES (' + ",".join("?" * len(allc)) + ")", rows)
    return con


_JOIN = re.compile(r"(\w+) IN \(SELECT unnest\(CAST\((\$\d+) AS VARCHAR\[\]\)\)\)")


def _as_list(sql: str) -> str:
    return _JOIN.sub(lambda m: f"list_contains(CAST({m.group(2)} AS VARCHAR[]), {m.group(1)})", sql)


def _queries() -> list[tuple[str, str, Any]]:
    from matching import coded_values, coverage, proposed
    from orchestrator.scenarios import feas_profile, microbatch, nav, screen

    span = ["2025-01-01", "2027-01-01"]
    return [
        ("coverage", coverage.SQL, lambda ls, _: [ls, ["s1", "x1"]]),
        ("proposed", proposed.SQL, lambda ls, _: [ls]),
        ("coded", coded_values.SQL, lambda ls, ids: [ls, ids, "atc", "nhi", "dept"]),
        ("coded.patients", coded_values.PATIENTS, lambda ls, _: [ls]),
        ("feas.demo", feas_profile.DEMO_SQL, lambda ls, _: [ls]),
        ("feas.visit", feas_profile.VISIT_SQL, lambda ls, _: [ls, *span]),
        ("micro.appt", microbatch.APPT_SQL, lambda ls, _: [ls, *span]),
        ("nav.claim", nav.CLAIM_SQL.format(product=""), lambda ls, _: [ls, "2026-03-01"]),
        ("screen.deceased", screen.DECEASED_SQL, lambda ls, _: [ls]),
    ]


LISTS = {
    "empty": [],
    "repeats": ["p1", "p1", "p3", "nobody"],
    "all": [f"p{i}" for i in range(12)],
    "null-in": ["p1", None],
}


@pytest.fixture(scope="module")
def lake() -> duckdb.DuckDBPyConnection:
    return _lake()


@pytest.mark.parametrize("name", [q[0] for q in _queries()])
def test_each_changed_query_reads_the_rows_the_list_read(lake: duckdb.DuckDBPyConnection, name: str) -> None:
    from lake.sqlguard import check_select

    _, sql, params = next(q for q in _queries() if q[0] == name)
    check_select(sql)
    assert _JOIN.search(sql) and not PER_ROW.search(sql)
    lists = dict(LISTS, **({"null": None} if "IS NULL" in sql else {}))
    for ls in lists.values():
        for ids in [["x1", "x7", "x7", ""], [], ["nobody"]] if name == "coded" else [None]:
            old = lake.execute(_as_list(sql), params(ls, ids)).fetchall()
            new = lake.execute(sql, params(ls, ids)).fetchall()
            # the same rows, as many times (no row doubled by the join); an unchanged ORDER BY keeps the order, whose
            # ties (the synthetic ids repeat) DuckDB may break either way
            assert collections.Counter(map(repr, new)) == collections.Counter(map(repr, old))
