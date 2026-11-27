"""O1 (OPT-1; prof16, CODED-PROFILE R2-R4): the coded SCREEN's lake reads keep their rows while they get cheaper.

* the seven ``Recorded`` queries are one ``UNION ALL`` that reads the same domains per patient;
* the compiled S1 SQL's scope filter is a semi join that keeps the rows ``list_contains`` kept;
* the record ``coded_values.attach`` shows for an id does not depend on the order the lake returns its rows (an
  existing non-determinism: no ORDER BY, ``preserve_insertion_order=false``; prof16 ruling Q1);
* binding a 100,000-pid list parameter stays cheap on the pinned DuckDB (the 53.7 % of a SCREEN job that failed
  ``import pandas`` twice per element, CODED-PROFILE §3)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
LISTS: dict[str, Any] = {
    "empty": [],
    "repeats": ["p1", "p1", "p3", "nobody"],
    "all": [f"p{i}" for i in range(12)],
    "null-in": ["p1", None],
    "null": None,
}


@pytest.fixture(scope="module")
def lake() -> duckdb.DuckDBPyConnection:
    from tests.unit.test_patient_lists_are_joins import _lake

    return _lake()


def test_one_recorded_query_reads_the_domains_the_seven_read(lake: duckdb.DuckDBPyConnection) -> None:
    from lake.sqlguard import check_select
    from matching import recorded

    check_select(recorded.QUERY)
    for ls in (v for v in LISTS.values() if v is not None):
        old: set[tuple[str, str]] = set()
        for table in recorded.DOMAINS:
            old |= {
                (table, r[0])
                for r in lake.execute(f"SELECT DISTINCT pid FROM {table} WHERE pid = ANY(?)", [ls]).fetchall()
            }
        new = {(r[0], r[1]) for r in lake.execute(recorded.QUERY, [ls]).fetchall()}
        assert new == old


def test_recorded_load_gives_each_patient_the_domains_of_their_rows(lake: duckdb.DuckDBPyConnection) -> None:
    from matching import recorded

    class _Rows:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def to_pylist(self) -> list[dict[str, Any]]:
            return self.rows

    class _Lake:
        calls = 0

        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> _Rows:
            self.calls += 1
            cur = lake.execute(sql, params)
            names = [d[0] for d in cur.description]
            return _Rows([dict(zip(names, r, strict=True)) for r in cur.fetchall()])

    ids = [f"p{i}" for i in range(12)] + ["nobody"]
    fake = _Lake()
    got = recorded.Recorded.load(fake, ids, None)
    assert fake.calls == 1  # not one a domain
    for pid in ids:
        want = {
            t
            for t in recorded.DOMAINS
            if lake.execute(f"SELECT count(*) FROM {t} WHERE pid = ?", [pid]).fetchone()[0]  # type: ignore[index]
        }
        assert got.domains[pid] == want
    assert got.read


# the template's scope filter, before and after, over the patients of the synthetic lake
_BASE = "SELECT p.pid FROM patient p WHERE ((SELECT pids FROM params) IS NULL OR {scope})"
_PARAMS = "WITH params AS (SELECT CAST($1 AS VARCHAR[]) AS pids) "
_LIST = "list_contains((SELECT pids FROM params), p.pid)"
_JOIN = "p.pid IN (SELECT unnest(pids) FROM params)"


def test_the_s1_scope_semi_join_keeps_the_rows_list_contains_kept(lake: duckdb.DuckDBPyConnection) -> None:
    from criteria_compiler.compile_sql import generator

    assert _JOIN in Path(generator.__file__).read_text(encoding="utf-8")  # the template says what this test checks
    for ls in LISTS.values():
        rows = {}
        for name, scope in (("list", _LIST), ("join", _JOIN)):
            rows[name] = sorted(
                (r[0] for r in lake.execute(_PARAMS + _BASE.format(scope=scope), [ls]).fetchall()), key=repr
            )
        assert rows["join"] == rows["list"]  # same rows, as many times (no row doubled by the join)


def test_the_coded_values_come_back_in_one_order_whatever_the_rows_order() -> None:
    from lake.flatten import SCHEMAS
    from matching import coded_values

    from tests.unit.test_patient_lists_are_joins import _lake

    lake = _lake()  # its own: the tables are rewritten below

    params = [LISTS["all"], ["x1", "x2", "x7", ""], "atc", "nhi", "dept"]
    unordered = coded_values.SQL.replace(
        "ORDER BY domain, rid, d, code, system, value_num, unit, value_code, value_cmp\n", ""
    )
    assert unordered != coded_values.SQL
    before = lake.execute(coded_values.SQL, params).fetchall()
    before_free = lake.execute(unordered, params).fetchall()
    for table in SCHEMAS:  # the same rows, stored the other way round
        lake.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{table}" ORDER BY rowid DESC')
    after = lake.execute(coded_values.SQL, params).fetchall()
    after_free = lake.execute(unordered, params).fetchall()
    assert before_free != after_free  # the test bites: without the ORDER BY the order follows the storage
    assert [repr(r) for r in after] == [repr(r) for r in before]


# a fresh interpreter, as in the lake image (no pandas); the best of three binds of 100,000 pids after the lake starts
BIND = r"""
import time

import duckdb
import lake.store  # noqa: F401  the lake's start

pids = [f"p{i:06d}" for i in range(100_000)]
con = duckdb.connect()
best = 1e9
for _ in range(3):
    t = time.perf_counter()
    con.execute("SELECT count(*) FROM range(3) WHERE list_contains($1, range::VARCHAR)", [pids]).fetchall()
    best = min(best, time.perf_counter() - t)
print(best)
"""


def test_binding_a_100k_pid_list_stays_cheap() -> None:
    """The gate's guard on the pinned DuckDB's binding (CODED-PROFILE: 8.5 s before the lake marked pandas absent,
    0.45 s after on the B200, about 1.2 s on a slow loaded PC). The bound is 3 s: far under the 8-25 s of a failed
    pandas look per element, loose enough for a loaded host. A DuckDB upgrade that changes the cost either way shows
    here, not in a night's report."""
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    out = subprocess.run([sys.executable, "-c", BIND], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert float(out.stdout.split()[-1]) <= 3.0, out.stdout
