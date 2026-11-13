"""NEW-TRUST-6 (D-700), lane A2's place: a snapshot built before the site facts is told by asking the lake, not by
reading an error's text.

``Proposed.load`` and ``site_basis`` took a failed query for "this snapshot has no ``site_fact`` table" when the
error's text held certain words. An error's text is whatever its author put in it. Now a failed query is followed
by one question the lake answers with a number: is there such a table. Only a clear "no" gives "no proposed fact";
everything else stops the run, as before (D-127: the rule is never dropped silently)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from lake.sqlguard import check_select
from matching import proposed
from matching.proposed import Proposed, site_basis


class _Lake:
    """A lake stand-in over a DuckDB in memory, behind the lake's own query guard."""

    def __init__(self, site_fact: bool, text: str | None = None) -> None:
        self.con = duckdb.connect(":memory:")
        self.text, self.asked = text, []
        if site_fact:
            self.con.execute(
                "CREATE TABLE site_fact (fid TEXT, pid TEXT, domain TEXT, code TEXT, system TEXT, d DATE, basis TEXT)"
            )

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        check_select(sql)
        self.asked.append(sql)
        try:
            return self.con.execute(sql, params or []).to_arrow_table()
        except duckdb.Error as exc:
            # as the lake's client raises it, or with a text of the stand-in's choosing
            raise RuntimeError(self.text or f"lake query failed (422): {type(exc).__name__}: {exc}") from exc


def test_a_snapshot_without_the_table_has_no_proposed_fact_whatever_the_errors_text() -> None:
    for text in (None, "lake query failed (422)", "boom", "表がありません"):
        lake = _Lake(site_fact=False, text=text)
        assert Proposed.load(lake, None, None).rows == {}
        assert site_basis(lake, None) == (set(), set())
        assert proposed.TABLE_SQL in lake.asked


def test_an_errors_text_that_names_the_table_does_not_drop_the_rule_when_the_table_is_there() -> None:
    """The words the old check looked for, in the text of another failure, on a snapshot that has the table."""

    class Failing(_Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
            if sql != proposed.TABLE_SQL:
                raise RuntimeError("lake query failed (503): Catalog busy; site_fact does not exist in the cache")
            return super().query(sql, params, snapshot)

    lake = Failing(site_fact=True)
    with pytest.raises(RuntimeError, match="503"):
        Proposed.load(lake, ["P1"], None)
    with pytest.raises(RuntimeError, match="503"):
        site_basis(lake, None)


def test_when_the_question_itself_fails_the_first_failure_stops_the_run() -> None:
    class Down:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("lake query failed (503)" if sql != proposed.TABLE_SQL else "the question failed")

    with pytest.raises(RuntimeError, match="503"):
        Proposed.load(Down(), None, None)
    with pytest.raises(RuntimeError, match="503"):
        site_basis(Down(), None)


@pytest.mark.parametrize("answer", [[], [{"n": None}], [{"n": "0"}], [{"x": 0}], [{"n": 1}], [{"n": 0}, {"n": 0}]])
def test_only_a_clear_no_counts(answer: list[dict[str, Any]]) -> None:
    class Odd:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            if sql != proposed.TABLE_SQL:
                raise RuntimeError("lake query failed (422): Table with name site_fact does not exist!")
            return pa.Table.from_pylist(answer) if answer else pa.table({"n": pa.array([], pa.int64())})

    with pytest.raises(RuntimeError, match="422"):
        Proposed.load(Odd(), None, None)


def test_a_snapshot_with_the_table_is_read_and_the_question_is_not_asked() -> None:
    lake = _Lake(site_fact=True)
    lake.con.execute("INSERT INTO site_fact VALUES ('F1','P1','condition','M10','icd10',DATE '2026-01-02','proposed')")
    assert list(Proposed.load(lake, ["P1"], None).rows) == ["P1"]
    assert site_basis(lake, None) == (set(), {"P1"})
    assert proposed.TABLE_SQL not in lake.asked


def test_the_question_passes_the_lakes_query_guard_and_sees_a_view_too() -> None:
    check_select(proposed.TABLE_SQL)
    con = duckdb.connect(":memory:")
    assert con.execute(proposed.TABLE_SQL).fetchall() == [(0,)]
    con.execute("CREATE VIEW site_fact AS SELECT 1 AS pid")
    assert con.execute(proposed.TABLE_SQL).fetchall() == [(1,)]


# ------------------------------------------------------------------------------------- the review of the first form
def test_an_unpinned_read_asks_the_question_of_the_snapshot_it_names_not_of_current_again() -> None:
    """The review, by running: with no snapshot named, the question read "current" a second time. If current had
    moved to a snapshot without the table between a failure on one that has it and the question, the rule was
    dropped. Now the lake is asked which snapshot is current once, and the query and the question are both put to
    that name."""

    class Moving:
        def __init__(self) -> None:
            self.asked: list[tuple[str, str | None]] = []

        def snapshot(self) -> str:
            return "2026-11-01"  # what the lake names as current when asked, after the failure

        def query(self, sql: str, params: Any = None, snapshot: str | None = None) -> Any:
            self.asked.append(("question" if sql == proposed.TABLE_SQL else "rows", snapshot))
            if sql == proposed.TABLE_SQL:
                # asked of "current" it would answer 0 (current is now an old snapshot); the named one has the table
                return pa.table({"n": [0 if snapshot is None else 1]})
            raise RuntimeError("lake query failed (503)")

    for read in (lambda lk: Proposed.load(lk, None, None), lambda lk: site_basis(lk, None)):
        lake = Moving()
        with pytest.raises(RuntimeError, match="503"):
            read(lake)
        assert lake.asked == [("rows", None), ("rows", "2026-11-01"), ("question", "2026-11-01")]


def test_an_unpinned_read_of_an_old_current_snapshot_still_has_no_proposed_fact() -> None:
    class OldCurrent(_Lake):
        def snapshot(self) -> str:
            return "2026-01-01"

    lake = OldCurrent(site_fact=False)
    assert Proposed.load(lake, None, None).rows == {} and site_basis(lake, None) == (set(), set())


def test_the_tables_name_is_compared_without_its_case() -> None:
    con = duckdb.connect(":memory:")
    con.execute('CREATE TABLE "Site_Fact" (pid TEXT)')
    assert con.execute(proposed.TABLE_SQL).fetchall() == [(1,)]


def test_on_a_real_lake_a_snapshot_without_the_table_and_one_with_it(tmp_path: Path) -> None:
    """Through the lake's own store (read-only, external access off, locked configuration) and its client."""
    import json

    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from lake.store import Lake, write_sidecar

    nd = tmp_path / "nd"
    nd.mkdir()
    (nd / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}) + "\n",
        encoding="utf-8",
    )
    store = Lake(tmp_path / "lake")
    for snap in ("2026-10-01", "2026-11-01"):
        store.rebuild(snap, HashEmbedder(), nd)
    old = store.db_path("2026-10-01")
    con = duckdb.connect(str(old))
    con.execute("DROP TABLE site_fact")  # as a snapshot built before step 5b
    con.close()
    write_sidecar(old)
    lake = LakeLocal(tmp_path / "lake", HashEmbedder())
    assert lake.query(proposed.TABLE_SQL, [], "2026-10-01").to_pylist() == [{"n": 0}]
    assert lake.query(proposed.TABLE_SQL, [], "2026-11-01").to_pylist() == [{"n": 1}]
    assert Proposed.load(lake, None, "2026-10-01").rows == {}
    assert site_basis(lake, "2026-10-01") == (set(), set())
    assert Proposed.load(lake, None, "2026-11-01").rows == {} and site_basis(lake, None) == (set(), set())
