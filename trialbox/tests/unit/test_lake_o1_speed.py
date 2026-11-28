"""O1 (OPT-1; prof16, CODED-PROFILE R2-R4): the coded SCREEN's lake reads keep their rows while they get cheaper.

* the seven ``Recorded`` queries are one ``UNION ALL`` that reads the same domains per patient;
* the compiled S1 SQL's scope filter is a semi join that keeps the rows ``list_contains`` kept;
* the record ``coded_values.attach`` shows for an id does not depend on the order the lake returns its rows (an
  existing non-determinism: no ORDER BY, ``preserve_insertion_order=false``; prof16 ruling Q1), and it is the record
  the query showed before it was ordered, when it was read one branch after the other (ties included);
* ``Recorded.load`` makes Python rows a bounded batch at a time, not one per patient and domain at once;
* binding a pid list parameter after the lake starts stays far cheaper than before it (the 53.7 % of a SCREEN job
  that failed ``import pandas`` twice per element, CODED-PROFILE §3)."""

from __future__ import annotations

import hashlib
import os
import re
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
    from matching.carried import DOMAINS

    check_select(recorded.QUERY)
    for ls in (v for v in LISTS.values() if v is not None):
        old: set[tuple[str, str]] = set()
        for table in DOMAINS:
            old |= {
                (table, r[0])
                for r in lake.execute(f"SELECT DISTINCT pid FROM {table} WHERE pid = ANY(?)", [ls]).fetchall()
            }
        new = {(r[0], r[1]) for r in lake.execute(recorded.QUERY, [ls]).fetchall()}
        assert new == old


def test_recorded_load_gives_each_patient_the_domains_of_their_rows(lake: duckdb.DuckDBPyConnection) -> None:
    from matching import recorded
    from matching.carried import DOMAINS

    class _Rows:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

        def to_pylist(self) -> list[dict[str, Any]]:
            return self.rows

        def to_batches(self, max_chunksize: int | None = None) -> list[_Rows]:
            return [self]

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
            for t in DOMAINS
            if lake.execute(f"SELECT count(*) FROM {t} WHERE pid = ?", [pid]).fetchone()[0]  # type: ignore[index]
        }
        assert got.domains[pid] == want
    assert got.read


def test_recorded_load_makes_python_rows_a_bounded_batch_at_a_time(
    lake: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex O1-02: one row per patient and domain is 700,000 at 100,000 patients in all seven; the read turns the
    Arrow result into Python a batch at a time, as the seven queries did a domain at a time."""
    from matching import recorded
    from matching.carried import DOMAINS

    class _Table:
        def __init__(self, table: Any) -> None:
            self.table = table
            self.sizes: list[int] = []

        def to_pylist(self) -> list[dict[str, Any]]:
            raise AssertionError("every row of the read made a Python object at once")

        def to_batches(self, max_chunksize: int | None = None) -> Any:
            for b in self.table.to_batches(max_chunksize):
                self.sizes.append(b.num_rows)
                yield b

    class _Lake:
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> _Table:
            self.result = _Table(lake.execute(sql, params).to_arrow_table())
            return self.result

    monkeypatch.setattr(recorded, "BATCH", 5)
    ids = [f"p{i}" for i in range(12)]
    fake = _Lake()
    got = recorded.Recorded.load(fake, ids, None)
    assert len(fake.result.sizes) > 1 and max(fake.result.sizes) <= 5, fake.result.sizes
    for pid in ids:
        want = {
            t
            for t in DOMAINS
            if lake.execute(f"SELECT count(*) FROM {t} WHERE pid = ?", [pid]).fetchone()[0]  # type: ignore[index]
        }
        assert got.domains[pid] == want


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


# the coded values query as it was before O1 (no ORDER BY, no k or rn column): sha256 of its text at 19bb88561
_BEFORE_O1 = "464e6732ee9a474de081846a7b1915c355244758c325b1aaa72488e6b0760f3e"


def _before_o1() -> str:
    from matching import coded_values

    old = re.sub(r", (?:0 AS k, rowid AS rn|\d, rowid)$", "", coded_values.SQL, flags=re.M)
    old = old.replace("ORDER BY k, rn\n", "")
    assert hashlib.sha256(old.encode()).hexdigest() == _BEFORE_O1  # exactly the old text: only k, rn and the order
    return old


def _read_one_branch_after_the_other(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """The old query's order where it had one: one thread, insertion order kept (each branch in turn, stored order)."""
    con.execute("SET threads = 1")
    con.execute("SET preserve_insertion_order = true")
    return con


def _as_the_lake_runs(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyConnection:
    """The lake's own settings (``LakeLocal._harden``): any order the plan likes unless the query names one."""
    con.execute("SET threads = 4")
    con.execute("SET preserve_insertion_order = false")
    return con


def test_the_coded_values_come_back_in_the_order_the_query_had_before_o1() -> None:
    """Codex O1-04: the same rows stored one way and the other way round; for each, the ordered query as the lake
    runs it gives the rows of the old query read one branch after the other, in that order (ties included)."""
    from lake.flatten import SCHEMAS
    from matching import coded_values

    from tests.unit.test_patient_lists_are_joins import _lake

    lake = _lake()  # its own: the tables are rewritten below; ids x1, x2, x7 and "" repeat across rows and tables
    params = [LISTS["all"], ["x1", "x2", "x7", ""], "atc", "nhi", "dept"]
    old_sql = _before_o1()
    got = {}
    for storage in ("as inserted", "the other way round"):
        if storage != "as inserted":
            for table in SCHEMAS:
                lake.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{table}" ORDER BY rowid DESC')
        old = _read_one_branch_after_the_other(lake).execute(old_sql, params).fetchall()
        new = _as_the_lake_runs(lake).execute(coded_values.SQL, params).fetchall()
        assert [repr(r[:-2]) for r in new] == [repr(r) for r in old], storage
        assert len({(r[0], r[1]) for r in old}) < len(old)  # ties: an id that a table holds more than once
        got[storage] = old
    assert got["as inserted"] != got["the other way round"]  # the stored order decides among ties, as it did


def test_attach_shows_the_record_it_showed_before_o1_when_ids_tie() -> None:
    """Codex O1-01: an id an observation and a claim share, and an id an observation table holds twice (two
    values). The code and value shown for each criterion are the ones the old query showed, stored either way."""
    from matching import coded_values as cv

    from tests.unit.test_coded_values import RUN, DuckLake, coded, crit, verdict

    obs = [
        {
            "oid": "x1",
            "pid": "P1",
            "code": "OBS-1",
            "system": "s",
            "effective": "2026-01-01 09:00:00",
            "value_num": 1.0,
        },
        {
            "oid": "x2",
            "pid": "P1",
            "code": "OBS-2",
            "system": "s",
            "effective": "2026-06-01 09:00:00",
            "value_num": 5.0,
        },
        {
            "oid": "x2",
            "pid": "P1",
            "code": "OBS-2",
            "system": "s",
            "effective": "2026-03-01 09:00:00",
            "value_num": 4.0,
        },
    ]
    claim = [{"kid": "x1", "pid": "P1", "product": "CLM-1", "created": "2026-02-01"}]
    proc = crit("T-INC-10", {"domain": "procedure", "quantifier": "any", "valueset": "VS_P"})  # neither domain
    lab = crit("T-INC-11", {"domain": "observation", "quantifier": "any", "valueset": "VS_L"})
    old_sql = _before_o1()

    class _Old(DuckLake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            assert sql == cv.SQL
            return _read_one_branch_after_the_other(self.con).execute(old_sql, params or []).to_arrow_table()

    class _New(DuckLake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            return _as_the_lake_runs(self.con).execute(sql, params or []).to_arrow_table()

    for rows, x2 in ((obs, 5.0), (obs[::-1], 4.0)):  # the first x2 stored is the one shown
        shown = {}
        for name, kind in (("old", _Old), ("new", _New)):
            verdicts = {"P1": [verdict(proc, "pass", ["x1"]), verdict(lab, "pass", ["Observation/x2|2026-06-01"])]}
            assert cv.attach(kind({"observation": rows, "claim": claim}), [proc, lab], verdicts, RUN, None) == 2
            shown[name] = [coded(v) for v in verdicts["P1"]]
        assert shown["new"] == shown["old"]
        (p,), (lb,) = shown["new"]  # type: ignore[misc]
        assert (p["domain"], p["code"], p.get("value")) == ("observation", "OBS-1", 1.0)  # the first branch's
        assert (lb["domain"], lb["code"], lb["value"]) == ("observation", "OBS-2", x2)


ABSENT = r"""
import importlib.abc
import importlib.machinery
import sys


class Absent(importlib.abc.MetaPathFinder):  # pandas not installed, as in the lake image, whatever this runner has
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "pandas":
            importlib.machinery.PathFinder.find_spec("pandas_not_installed")  # a failed look searches sys.path
            raise ModuleNotFoundError(name)
        return None


sys.meta_path.insert(0, Absent())
sys.modules.pop("pandas", None)
"""

ARROW = (
    ABSENT
    + r"""
import lake.store  # noqa: F401  the lake's start: pandas is marked absent
import pyarrow as pa
import pyarrow.parquet as pq

# what the lake's rebuild and the readers of its results do with Arrow after the mark
t = pa.Table.from_pylist([{"pid": "p1", "n": 1}], schema=pa.schema([("pid", pa.string()), ("n", pa.int64())]))
assert pa.array(["a", None]).to_pylist() == ["a", None] and pa.Table.from_pydict({"a": [1]}).num_rows == 1
assert sys.modules["pandas"] is None  # the mark was made: this ran the path of a lake without pandas
print(t.num_rows, t.to_pylist()[0]["pid"])
"""
)


def test_arrow_still_converts_python_values_once_pandas_is_marked_absent() -> None:
    """The first form of the stop-gap, ``sys.modules["pandas"] = None`` alone, made ``pa.Table.from_pylist`` fail on
    ``None.__version__`` (pyarrow's pandas shim): the lake's rebuild and every golden died on it. Codex O1-05: pandas
    is kept out of the interpreter, so a runner that has it installed still runs the lake's no-pandas start."""
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    out = subprocess.run([sys.executable, "-c", ARROW], check=False, cwd=ROOT, env=env, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.split() == ["1", "p1"], out.stderr[-600:]


# a fresh interpreter, as in the lake image (no pandas): the cost per pid of binding a list before the lake starts
# (two failed looks for pandas per element: the best of two binds of 1,000 pids) and after (the best of three binds
# of 100,000 pids), measured side by side on the same CPU
BIND = (
    ABSENT
    + r"""
import time

import duckdb


def per_pid(n, runs):
    pids = [f"p{i:06d}" for i in range(n)]
    con = duckdb.connect()
    best = 1e9
    for _ in range(runs):
        t = time.perf_counter()
        con.execute("SELECT count(*) FROM range(3) WHERE list_contains($1, range::VARCHAR)", [pids]).fetchall()
        best = min(best, time.perf_counter() - t)
    return best / n


before = per_pid(1_000, 2)
import lake.store  # noqa: E402,F401  the lake's start

print(before, per_pid(100_000, 3))
"""
)


def test_binding_a_100k_pid_list_stays_cheap() -> None:
    """The gate's guard on the pinned DuckDB's binding (CODED-PROFILE: 8.5 s for 100,000 pids before the lake marked
    pandas absent, 0.45 s after on the B200, a 19x gap; 29 s and 0.2 s for 20,000 on a loaded PC, 140x). Codex O1-03:
    a fixed number of seconds failed a CPU-limited runner, so the bound is relative: a pid costs at most a fifth of
    what it cost before the mark, both measured here. A DuckDB upgrade that brings the per-element look back shows
    here, not in a night's report."""
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    out = subprocess.run([sys.executable, "-c", BIND], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    before, after = (float(x) for x in out.stdout.split()[-2:])
    assert after * 5 <= before, out.stdout
