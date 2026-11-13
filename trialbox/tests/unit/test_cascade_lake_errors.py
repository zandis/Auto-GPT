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
from matching.cascade import engine
from tb_common import lakeprobe

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


def test_an_unpinned_run_whose_lake_cannot_name_a_snapshot_stops_on_the_first_failure() -> None:
    """The review: with ``snapshot()`` answering None the question must not be put to "current" after all; and
    whatever fails after the first failure (the lake's naming, the second try), the FIRST failure stops the run."""

    class Lake:
        def __init__(self, name: Any, again: str = "lake query failed (504)") -> None:
            self.name, self.again = name, again
            self.asked: list[tuple[str, str | None]] = []

        def snapshot(self) -> Any:
            if isinstance(self.name, Exception):
                raise self.name
            return self.name

        def query(self, sql: str, params: Any = None, snapshot: str | None = None) -> Any:
            self.asked.append(("question" if sql == QUESTION else "rows", snapshot))
            if sql == QUESTION:
                return pa.table({"n": [0 if snapshot is None else 1]})
            raise RuntimeError("lake query failed (503)" if snapshot is None else self.again)

    lake = Lake(None)
    with pytest.raises(RuntimeError, match="503"):
        _notes(lake, snapshot=None)
    assert lake.asked == [("rows", None)]
    lake = Lake(OSError("the lake cannot say which snapshot is current"))
    with pytest.raises(RuntimeError, match="503"):
        _notes(lake, snapshot=None)
    assert lake.asked == [("rows", None)]
    lake = Lake("2026-11-01")
    with pytest.raises(RuntimeError, match="503"):  # the second try failed too: the first failure is the one raised
        _notes(lake, snapshot=None)


def test_a_view_of_that_name_counts_as_there() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE VIEW document AS SELECT 1 AS did")
    assert con.execute(QUESTION).fetchall() == [(1,)]


def _text_uses(root: Any) -> list[str]:
    """Where the source under ``root`` uses a caught error other than by its type, a typed field, or to raise:
    ``str(exc)``, ``repr(exc)``, ``format(exc)``, ``f"{exc}"``, ``"%s" % exc``, ``exc.args``, the bare name passed
    on to a helper (which is how the note reader's check escaped the scan of D-700)."""
    import ast

    typed = {"reason"}  # a gateway refusal's own field (matching/cascade/judge.py)
    out = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for handler in (n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name):
            for use in (
                n for b in handler.body for n in ast.walk(b) if isinstance(n, ast.Name) and n.id == handler.name
            ):
                up = parents[use]
                if isinstance(up, ast.Raise):  # raise exc / raise ... from exc
                    continue
                if isinstance(up, ast.Attribute) and (up.attr in typed or up.attr.startswith("__")):
                    continue
                if isinstance(up, ast.Call) and isinstance(up.func, ast.Name) and up.func.id in ("type", "isinstance"):
                    continue
                out.append(f"{path.relative_to(root)}:{use.lineno}")
    return out


def test_no_place_in_the_matching_service_uses_a_caught_errors_text() -> None:
    """The scan of D-700 looks at statements inside an ``except`` that take the error's text; the note reader's
    check passed the error to a helper from an ``if`` and was not seen. Here every use of a caught error in the
    service is looked at, whatever its spelling: one listed place keeps a model's own refusal as an answer's
    error."""
    from pathlib import Path

    root = Path(engine.__file__).resolve().parents[1]
    found = _text_uses(root)
    assert [f.rsplit(":", 1)[0] for f in found] == ["registry_match/llm.py"], found
    assert not hasattr(engine, "missing_table")


def test_the_scan_sees_every_spelling(tmp_path: Any) -> None:
    spellings = ["str(exc)", "repr(exc)", "format(exc)", 'f"{exc}"', '"%s" % exc', "exc.args", "helper(exc, 1)"]
    for i, use in enumerate(spellings):
        (tmp_path / f"m{i}.py").write_text(f"try:\n    pass\nexcept Exception as exc:\n    x = {use}\n")
    (tmp_path / "ok.py").write_text(
        "try:\n    pass\nexcept Exception as exc:\n    x = type(exc).__name__\n    y = exc.reason\n"
        "    raise RuntimeError('stopped') from exc\n"
    )
    assert [f.split(":")[0] for f in _text_uses(tmp_path)] == [f"m{i}.py" for i in range(len(spellings))]
