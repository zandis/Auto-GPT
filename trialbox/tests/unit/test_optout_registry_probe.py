"""D-651: whether the lake has no opt-out registry is asked of the lake, not read out of an error's text.

``tb_common.optout.registry_state`` answered None, "the lake has no consent table", when a failed query's text
held "consent" with "does not exist" or "Catalog Error". Every caller takes None for "no opt-out to apply". So
another failure whose text held those words meant: nobody has opted out. The cascade then listed patients who
said no. Now the lake is asked how many tables of that name the snapshot has; only a clear 0 is None."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from lake.sqlguard import check_select
from tb_common import lakeprobe
from tb_common.optout import REGISTRY_SQL, registry_state

QUESTION = lakeprobe.table_sql("consent")
WORDS = "lake query failed (503): Catalog busy; consent does not exist in the cache"


class _Lake:
    """A lake stand-in over a DuckDB in memory, behind the lake's own query guard. ``fail``: what the registry
    query raises (the question is answered by the database as it is)."""

    def __init__(self, consent: bool, fail: Exception | None = None) -> None:
        self.con = duckdb.connect(":memory:")
        self.fail = fail
        self.asked: list[str] = []
        if consent:
            self.con.execute(
                "CREATE TABLE consent (pid TEXT, status TEXT, contact_ok BOOLEAN, date DATE, recorded TIMESTAMP)"
            )

    def snapshot(self) -> str:
        return "2026-11-01"

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> pa.Table:
        check_select(sql)
        self.asked.append(sql)
        if self.fail is not None and sql != QUESTION:
            raise self.fail
        try:
            return self.con.execute(sql, params or []).to_arrow_table()
        except duckdb.Error as exc:
            raise RuntimeError(f"lake query failed (422): {type(exc).__name__}: {exc}") from exc


def test_another_failure_whose_text_holds_the_words_is_not_no_registry() -> None:
    """The confirming case: before the change this gave None, and no opt-out was applied."""
    lake = _Lake(consent=True, fail=RuntimeError(WORDS))
    with pytest.raises(RuntimeError, match="503"):
        registry_state(lake, "2026-11-01", "2026-11-13")
    assert QUESTION in lake.asked


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("lake query failed (400): Catalog Error: Table with name consent does not exist!"),
        RuntimeError("lake query failed (503): upstream connect error"),
        TimeoutError("timed out"),
        RuntimeError("lake query failed (500): Binder Error: column contact_ok not found in consent"),
        PermissionError("snapshot locked"),
    ],
)
def test_every_failure_on_a_lake_that_has_the_table_stops(exc: Exception) -> None:
    with pytest.raises(type(exc)):
        registry_state(_Lake(consent=True, fail=exc), "2026-11-01", "2026-11-13")


def test_only_a_lake_that_answers_it_has_no_such_table_has_no_registry() -> None:
    lake = _Lake(consent=False)
    assert registry_state(lake, "2026-11-01", "2026-11-13") is None
    assert lake.asked[0] == REGISTRY_SQL and QUESTION in lake.asked


@pytest.mark.parametrize(
    "answer",
    [[], [{"n": None}], [{"n": "0"}], [{"x": 0}], [{"n": 1}], [{"n": 0}, {"n": 0}], [{"n": 0.0}], [{"n": False}]],
)
def test_only_a_clear_no_counts_and_a_failing_question_stops(answer: list[dict[str, Any]]) -> None:
    class Odd:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            if sql != QUESTION:
                raise RuntimeError("lake query failed (422): Table with name consent does not exist!")
            return pa.Table.from_pylist(answer) if answer else pa.table({"n": pa.array([], pa.int64())})

    with pytest.raises(RuntimeError, match="422"):
        registry_state(Odd(), "2026-11-01", "2026-11-13")

    class Down:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("the question failed" if sql == QUESTION else "lake query failed (503)")

    with pytest.raises(RuntimeError, match="503"):
        registry_state(Down(), "2026-11-01", "2026-11-13")


def test_a_lake_with_a_registry_is_read_and_the_question_is_not_asked() -> None:
    lake = _Lake(consent=True)
    lake.con.execute("INSERT INTO consent VALUES ('P1', 'rejected', NULL, DATE '2026-10-01', NULL)")
    lake.con.execute("INSERT INTO consent VALUES ('P2', 'active', TRUE, DATE '2026-10-02', NULL)")
    state = registry_state(lake, "2026-11-01", "2026-11-13")
    assert state is not None and state.refused == frozenset({"P1"})
    assert lake.asked == [REGISTRY_SQL]
    empty = registry_state(_Lake(consent=True), "2026-11-01", "2026-11-13")
    assert empty is not None and empty.refused == frozenset()  # a registry with no row is a registry


# ----------------------------------------------------------------------------------------------- every caller
def test_the_jobs_decision_context_stops_and_names_nobody_as_free_to_list() -> None:
    from orchestrator.decision_context import DecisionContext

    lake = _Lake(consent=True, fail=RuntimeError(WORDS))
    ctx: Any = SimpleNamespace(services=SimpleNamespace(lake=lake), today=lambda: date(2026, 11, 13))
    d = DecisionContext(ctx)
    for read in (d.refused, d.no_contact, lambda: d.consent(date(2026, 11, 13), "2026-11-01")):
        with pytest.raises(RuntimeError, match="503"):
            read()
    absent = DecisionContext(SimpleNamespace(services=SimpleNamespace(lake=_Lake(consent=False)), today=ctx.today))
    assert absent.consent() is None and absent.refused() == frozenset()  # a clear "no such table": as before


def test_the_opt_out_worker_reports_the_registry_as_not_read_and_still_runs_every_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datacore import optout_worker

    class Register:
        def effective(self) -> set[str]:
            return {"P-KEPT"}

    synced: list[Any] = []
    env = optout_worker.WorkerEnv(
        register=Register(),  # type: ignore[arg-type]
        audit=SimpleNamespace(append=lambda *a, **k: None),
        now=datetime(2026, 11, 13, 3, 0, tzinfo=UTC),
        lake=_Lake(consent=True, fail=RuntimeError(WORDS)),
    )
    cleared: list[frozenset[str]] = []

    def clear(pids: frozenset[str], _env: Any) -> dict[str, int]:
        cleared.append(pids)
        return {"t": 1}

    one = SimpleNamespace(name="a-store", resolve=lambda: (clear, lambda pids, _env: {"t": 0}))

    def sync(*a: Any, **_k: Any) -> tuple[int, int]:
        synced.append(a)
        return 0, 0

    monkeypatch.setattr(optout_worker, "sync_registry", sync)
    monkeypatch.setattr("tb_common.erasure.clears", lambda: [one])
    out = optout_worker.run_once(env)
    # before the change the worker read "no registry": nothing failed, nothing synced, and it said so to nobody
    assert out["failed"] == ["registry"] and out["registry"] is None and synced == []
    # lane E's rule: the tick goes on. The register it already holds still applies, and every clear still runs in
    # the same tick for those patients (stopping them would leave opted-out patients un-erased)
    assert out["opted_out"] == 1 and cleared == [frozenset({"P-KEPT"})] and out["stores"] == {"a-store": {"t": 1}}
