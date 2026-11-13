"""D-127 (review F-04): only a lake without a note table is tolerated; any other lake error stops the run.

D-650: whether the lake has no note table is asked of the lake, not read out of the error's text. The cascade took
a failed note query for "this lake has no ``document`` table" (the MIMIC demo) when the error's text held the
table's name and "does not exist" or "Catalog Error". Another failure whose text held those words then turned
every note pair of the run into a data gap, without saying why."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from lake.sqlguard import check_select
from matching import lakeprobe
from matching.cascade import engine

QUESTION = lakeprobe.table_sql("document")


class _Lake:
    """A lake stand-in over a DuckDB in memory, behind the lake's own query guard."""

    def __init__(self, document: bool, text: str | None = None) -> None:
        self.con = duckdb.connect(":memory:")
        self.text = text
        self.asked: list[str] = []
        if document:
            self.con.execute("CREATE TABLE document (did TEXT, pid TEXT, date DATE, type TEXT, text TEXT)")
            self.con.execute("INSERT INTO document VALUES ('D1', 'P1', DATE '2026-10-01', 'note', '痛風發作。')")

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        check_select(sql)
        self.asked.append(sql)
        try:
            return self.con.execute(sql, params or []).to_arrow_table()
        except duckdb.Error as exc:
            raise RuntimeError(self.text or f"lake query failed (422): {type(exc).__name__}: {exc}") from exc


def _notes(lake: Any, snapshot: str | None = "2026-11-01") -> dict[str, Any]:
    run: Any = SimpleNamespace(
        lake=lake, cfg=SimpleNamespace(snapshot=snapshot), traces={"P1": SimpleNamespace(index_date=date(2026, 11, 1))}
    )
    return engine._Run.notes(run, ["P1"])


def test_a_lake_with_notes_is_read_and_the_question_is_not_asked() -> None:
    lake = _Lake(document=True)
    assert [n.did for n in _notes(lake)["P1"]] == ["D1"]
    assert QUESTION not in lake.asked


@pytest.mark.parametrize("text", [None, "lake query failed (422)", "boom", "表がありません"])
def test_a_lake_without_a_note_table_has_no_notes_whatever_the_errors_text(text: str | None) -> None:
    lake = _Lake(document=False, text=text)
    assert _notes(lake) == {}
    assert QUESTION in lake.asked


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("lake query failed (503): upstream connect error"),
        TimeoutError("timed out"),
        RuntimeError("lake query failed (500): Binder Error: column text not found in document"),
        PermissionError("snapshot locked"),
        # the words the old check looked for, in the text of another failure
        RuntimeError("lake query failed (400): Catalog Error: Table with name document does not exist!"),
        RuntimeError("lake query failed (503): Catalog busy; document does not exist in the cache"),
    ],
)
def test_any_other_failure_stops_the_run_whatever_its_text_says(exc: Exception) -> None:
    class Failing(_Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
            if sql != QUESTION:
                raise exc
            return super().query(sql, params, snapshot)

    with pytest.raises(type(exc)):
        _notes(Failing(document=True))  # the table is there: the lake answers 1


def test_when_the_question_itself_fails_the_first_failure_stops_the_run() -> None:
    class Down:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("the question failed" if sql == QUESTION else "lake query failed (503)")

    with pytest.raises(RuntimeError, match="503"):
        _notes(Down())


@pytest.mark.parametrize("answer", [[], [{"n": None}], [{"n": "0"}], [{"x": 0}], [{"n": 1}], [{"n": 0}, {"n": 0}]])
def test_only_a_clear_no_counts(answer: list[dict[str, Any]]) -> None:
    class Odd:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            if sql != QUESTION:
                raise RuntimeError("lake query failed (422): Table with name document does not exist!")
            return pa.Table.from_pylist(answer) if answer else pa.table({"n": pa.array([], pa.int64())})

    with pytest.raises(RuntimeError, match="422"):
        _notes(Odd())


def test_an_unpinned_run_asks_the_question_of_the_snapshot_the_lake_names() -> None:
    class Moving:
        def __init__(self) -> None:
            self.asked: list[tuple[str, str | None]] = []

        def snapshot(self) -> str:
            return "2026-11-01"

        def query(self, sql: str, params: Any = None, snapshot: str | None = None) -> Any:
            self.asked.append(("question" if sql == QUESTION else "rows", snapshot))
            if sql == QUESTION:
                return pa.table({"n": [0 if snapshot is None else 1]})  # "current" has moved to a lake without notes
            raise RuntimeError("lake query failed (503)")

    lake = Moving()
    with pytest.raises(RuntimeError, match="503"):
        _notes(lake, snapshot=None)
    assert lake.asked == [("rows", None), ("rows", "2026-11-01"), ("question", "2026-11-01")]


def test_the_question_names_only_a_plain_table_and_passes_the_lakes_guard() -> None:
    for table in ("document", "site_fact"):
        check_select(lakeprobe.table_sql(table))
    for bad in ("document; DROP TABLE x", "Document", "doc'ument", "", "a b"):
        with pytest.raises(ValueError):
            lakeprobe.table_sql(bad)
    con = duckdb.connect(":memory:")
    assert con.execute(QUESTION).fetchall() == [(0,)]
    con.execute('CREATE TABLE "Document" (did TEXT)')
    assert con.execute(QUESTION).fetchall() == [(1,)]


def test_no_place_in_the_matching_service_reads_an_errors_text_to_tell_a_missing_table() -> None:
    """The scan of D-700 looks at statements inside an ``except``; this check was in a helper called from an ``if``
    there, and was not seen. Nothing in the service takes ``str(exc)`` of a caught error apart from the one listed
    place (a model's own refusal class, kept as the answer's error)."""
    import re
    from pathlib import Path

    root = Path(engine.__file__).resolve().parents[1]
    found = sorted(
        f"{p.relative_to(root)}:{i}"
        for p in root.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bstr\((exc|e|err|error)\)", line)
    )
    assert [f.rsplit(":", 1)[0] for f in found] == ["registry_match/llm.py"], found
    assert not hasattr(engine, "missing_table")
