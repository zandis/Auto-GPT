"""NEW-B-58 (D-924): S1 is one query when it fits what was measured, else D-748's batches.

The nightly perf-5k gate (5,000 patients, 36 index dates) went from 8.57 s of cascade to 29.34 s when D-748 split S1
into batches of 12,000 rows: each batch runs the ruleset's whole SQL again, about 0.5 s of fixed cost a query (16
queries at 5,000 patients). One query at 5,000 x 36 peaked at 1.9 GB on the gate (its baseline's own peak, from before
D-748). Within ``TB_CASCADE_S1_WHOLE_ROWS`` rows and on a lake that says it has at least ``TB_CASCADE_S1_WHOLE_GB``,
S1 is one query; otherwise the batches hold the memory as before (the 50,000-patient night is unchanged)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.unit.test_cascade_pipeline import (
    RecordingJudge,
    _answers,
    _run,
    e2e,  # noqa: F401  (the fixture the env fixture asks for)
)
from tests.unit.test_cascade_pipeline import env as _env_fixture  # noqa: F401  (fixture "env")

GB = 10**9


class _Told:
    def __init__(self, mem: Any) -> None:
        self.mem = mem

    def memory_limit_bytes(self) -> Any:
        if isinstance(self.mem, Exception):
            raise self.mem
        return self.mem


@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TB_CASCADE_S1_ROWS", "TB_CASCADE_S1_WHOLE_ROWS", "TB_CASCADE_S1_WHOLE_GB"):
        monkeypatch.delenv(name, raising=False)


def test_the_perf_5k_scope_is_one_query_on_a_lake_with_the_memory() -> None:
    from matching.cascade.engine import patients_per_query

    assert patients_per_query(_Told(6 * GB), 5000, 36) == 5000  # the gate's host: 40 % of 16 GB
    assert patients_per_query(_Told(4 * GB), 5000, 36) == 5000  # the floor: twice the 1.9 GB measured


@pytest.mark.parametrize(
    ("lake", "patients", "dates"),
    [
        (_Told(3 * GB), 5000, 36),  # a lake below the floor: D-748's 1 GB measurement holds there
        (_Told(None), 5000, 36),  # a lake that cannot say
        (_Told(OSError("down")), 5000, 36),  # nor answer
        (object(), 5000, 36),  # an older client
        (_Told(64 * GB), 50000, 36),  # the 50,000-patient night: its memory peak as today
        (_Told(64 * GB), 5001, 36),  # one row past the measurement
    ],
)
def test_otherwise_the_batches_of_d748_hold(lake: Any, patients: int, dates: int) -> None:
    from matching.cascade.engine import patients_per_query

    assert patients_per_query(lake, patients, dates) == 12000 // dates


def test_a_runs_own_rows_or_a_set_rows_keep_the_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    from matching.cascade.engine import CascadeError, patients_per_query

    assert patients_per_query(_Told(64 * GB), 5000, 36, rows=360) == 10  # a run that asked for batches gets them
    monkeypatch.setenv("TB_CASCADE_S1_ROWS", "3600")  # a site that set its rows (a small box) is never overruled
    assert patients_per_query(_Told(64 * GB), 5000, 36) == 100
    with pytest.raises(CascadeError, match="s1_rows"):
        patients_per_query(_Told(64 * GB), 10, 1, rows=0)


def test_the_measurement_is_a_declared_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from matching.cascade.engine import patients_per_query
    from tb_common.config import DECLARED

    assert (
        DECLARED["TB_CASCADE_S1_WHOLE_ROWS"].default == "180000" and DECLARED["TB_CASCADE_S1_WHOLE_GB"].default == "4"
    )
    monkeypatch.setenv("TB_CASCADE_S1_WHOLE_GB", "8")
    assert patients_per_query(_Told(6 * GB), 5000, 36) == 333
    monkeypatch.setenv("TB_CASCADE_S1_WHOLE_ROWS", "1000")
    monkeypatch.setenv("TB_CASCADE_S1_WHOLE_GB", "1")
    assert patients_per_query(_Told(6 * GB), 100, 10) == 100 and patients_per_query(_Told(6 * GB), 101, 10) == 1200


@pytest.mark.parametrize(
    ("limit", "want"), [("8GB", 8 * GB), ("8GiB", 8 * 2**30), ("500MB", 500 * 10**6), ("1.5GB", 1_500_000_000),
                        ("eight", None), ("", None)],
)  # fmt: skip
def test_the_lakes_limit_is_read_as_duckdb_reads_it(limit: str, want: int | None) -> None:
    from lake.store import memory_limit_bytes

    assert memory_limit_bytes(limit) == want


def test_the_lake_service_tells_its_limit_and_the_client_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from lake.client import LakeHttp

    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/limits"
        return httpx.Response(200, json={"memory_limit": "6GB", "memory_limit_bytes": 6 * GB})

    lake = LakeHttp("http://lake")
    lake.client = httpx.Client(transport=httpx.MockTransport(answer))
    assert lake.memory_limit_bytes() == 6 * GB
    for bad in (httpx.Response(404), httpx.Response(200, json={"memory_limit_bytes": "6GB"}), httpx.Response(200)):
        lake.client = httpx.Client(transport=httpx.MockTransport(lambda _r, b=bad: b))
        assert lake.memory_limit_bytes() is None  # an older lake, a wrong answer: not known, so the batches


def test_the_lake_route_answers_its_own_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "7GB")
    body = TestClient(lake_app.app).get("/limits").json()
    assert body == {"memory_limit": "7GB", "memory_limit_bytes": 7 * GB}


class _Counting:
    def __init__(self, lake: Any, mem: int) -> None:
        self.lake, self.mem, self.s1 = lake, mem, 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.lake, name)

    def memory_limit_bytes(self) -> int:
        return self.mem

    def query(self, sql: str, params: Any = None, snapshot: str | None = None, *a: Any, **kw: Any) -> Any:
        if params and len(params) == 2 and isinstance(params[1], list) and "idx_dates" in sql:
            self.s1 += 1
        return self.lake.query(sql, params, snapshot, *a, **kw)


def test_through_the_cascade_one_query_gives_the_answers_the_batches_give(_env_fixture: dict[str, Any]) -> None:  # noqa: F811
    whole, small = _Counting(_env_fixture["lake"], 64 * GB), _Counting(_env_fixture["lake"], 1 * GB)
    one = _run({**_env_fixture, "lake": whole}, RecordingJudge(), sample_per_stratum=None)
    many = _run({**_env_fixture, "lake": small}, RecordingJudge(), sample_per_stratum=None)
    assert whole.s1 == 1 and small.s1 > 1
    assert _answers(one) == _answers(many)
    assert [s.patients_out for s in one.stages] == [s.patients_out for s in many.stages]
