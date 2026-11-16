"""NEW-B-53: the FEAS funnel, the cohort list and SqlEngine ask the lake for their patients in batches of rows.

D-748 batched the cascade's S1; the FEAS funnel (36 month-ends times every patient), ``cohort.items_at`` and
``SqlEngine.evaluate`` still asked for the whole scope in one query. A patient's rows depend on that patient alone
(the funnel groups by patient), so batches of any size give the same answers as one query."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from tests.unit.test_cascade_pipeline import e2e  # noqa: F401  (the fixture the env fixture asks for)
from tests.unit.test_cascade_pipeline import env as _env_fixture  # noqa: F401  (fixture "env")


class _Counting:
    def __init__(self, lake: Any) -> None:
        self.lake = lake
        self.batches: list[list[str]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.lake, name)

    def query(self, sql: str, params: Any = None, snapshot: str | None = None, *a: Any, **kw: Any) -> Any:
        if params and len(params) >= 2 and isinstance(params[1], list) and "idx_dates" in sql:
            self.batches.append(list(params[1]))
        return self.lake.query(sql, params, snapshot, *a, **kw)


def _feas(env: dict[str, Any]) -> Any:
    from orchestrator.scenarios.feas_compute import FeasParams, compute

    p = FeasParams(run_date=date(2026, 10, 5), snapshot=env["cfg"].snapshot, lookback_months=12, iterations=1)
    return compute(env["lake"], env["rs"], p)


@pytest.mark.parametrize("patients", [37, 250])  # 600 patients: 17 and 3 queries
def test_the_feas_funnel_in_batches_counts_the_same(
    _env_fixture: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    patients: int,
) -> None:
    whole_res, whole_raw = _feas(_env_fixture)
    counted = _Counting(_env_fixture["lake"])
    monkeypatch.setenv("TB_CASCADE_S1_ROWS", str(patients * 12))  # 12 month-ends
    res, raw = _feas({**_env_fixture, "lake": counted})
    assert raw == whole_raw and res == whole_res
    asked = [p for b in counted.batches for p in b]
    assert len(set(asked)) == len(asked) and max(len(b) for b in counted.batches) <= patients
    assert len(counted.batches) == -(-len(asked) // patients)  # one query per batch


@pytest.mark.parametrize(
    ("pids", "rows"), [(None, 37), (None, 12000), ("some", 1), ("some", 37)]
)  # one patient a query only on a few (each query has a fixed cost)
def test_the_approved_sql_in_batches_gives_the_same_rows(
    _env_fixture: dict[str, Any],  # noqa: F811
    pids: str | None,
    rows: int,
) -> None:
    """``cohort.items_at`` (every patient) and ``SqlEngine.evaluate`` (given patients) through the helper."""
    from criteria_compiler.compile_sql.overlay import safe_sql
    from matching.batches import ALL_PATIENTS_SQL, query_by_patients

    lake, snap, sql = _env_fixture["lake"], _env_fixture["cfg"].snapshot, safe_sql(_env_fixture["rs"])
    every = [str(r["pid"]) for r in lake.query(ALL_PATIENTS_SQL, [], snap).to_pylist()]
    who = None if pids is None else every[3::50][::-1] + every[3:4]  # out of order, one twice
    day = ["2026-10-05"]
    whole = lake.query(sql, [day, who], snap).to_pylist()
    parts = query_by_patients(lake, sql, day, who, snap, rows=rows).to_pylist()
    assert whole and parts == whole  # in the same order too (the SQL orders by patient)


def test_no_patients_is_one_empty_query_and_a_batch_of_none_is_refused(_env_fixture: dict[str, Any]) -> None:  # noqa: F811
    from criteria_compiler.compile_sql.overlay import safe_sql
    from matching.batches import query_by_patients
    from matching.cascade.engine import CascadeError

    lake, snap, sql = _env_fixture["lake"], _env_fixture["cfg"].snapshot, safe_sql(_env_fixture["rs"])
    assert query_by_patients(lake, sql, ["2026-10-05"], [], snap).num_rows == 0
    for bad in (0, -1):
        with pytest.raises(CascadeError, match="rows="):
            query_by_patients(lake, sql, ["2026-10-05"], None, snap, rows=bad)
