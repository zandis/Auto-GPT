"""NEW-B-45 (D-746): a lake query's time limit is the job's, and a query stopped at it is the lake's limit.

T-694 / F-29 (``docs/reviews/2026-11-11-scale-timeouts.md``): every lake query had 300 s and the client 330 s; the
lake accepted another value (``LakeQuery.timeout_s``) but no caller sent one. Feasibility is one query over the whole
lake and crosses 300 s at about 140,000 patients. A query stopped at its limit came back as a generic error."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from lake import app as lake_app
from lake import store
from lake.client import READ_MARGIN_S, LakeHttp, LakeQueryFailed
from orchestrator.jobs import PinnedLake, lake_query_limit

from tests.unit.test_polled_jobs import NIGHT, TZ, _patients
from tests.unit.test_snapshot_pin import make as _make_job_fixture  # noqa: F401  (the fixture "make")

# long enough to be stopped at a one-second limit
SLOW = "SELECT sum(hash(a.range * b.range)) AS n FROM range(200000) a, range(200000) b"


@pytest.fixture
def lake(tmp_path: Path) -> store.Lake:
    from embed_service.embedder import HashEmbedder

    _patients(tmp_path / "lake", NIGHT, 3)
    real = store.Lake(tmp_path / "lake", TZ)
    real.rebuild(NIGHT, HashEmbedder())
    return real


def test_a_query_stopped_at_its_limit_is_the_lakes_time_limit(lake: store.Lake) -> None:
    with pytest.raises(store.LakeTimeLimitError, match="LAKE-TIME.*1 s"):
        lake.query(SLOW, timeout_s=1)
    assert lake.query("SELECT count(*) AS n FROM patient").to_pylist() == [{"n": 3}]  # the next query is served


def test_the_service_answers_503_with_the_limits_words(lake: store.Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    with pytest.raises(LakeQueryFailed) as got:
        http.query(SLOW, timeout_s=1)
    assert got.value.status == 503 and "LakeTimeLimitError: LAKE-TIME" in str(got.value), str(got.value)


def test_the_client_sends_the_limit_and_waits_longer_than_it() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["read"] = request.extensions["timeout"]["read"]
        return httpx.Response(500, json={"detail": "x"})

    http = LakeHttp("http://lake")
    http.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LakeQueryFailed):
        http.query("SELECT 1", timeout_s=1800)
    assert seen["body"]["timeout_s"] == 1800
    assert seen["read"] == 1800 + READ_MARGIN_S  # the lake's answer, not the client's own timeout, is what is seen
    with pytest.raises(LakeQueryFailed):
        http.query("SELECT 1")  # no limit asked: the lake's own (the contract's default), as before
    assert "timeout_s" not in seen["body"] or seen["body"]["timeout_s"] == 300


def test_the_limit_per_job_type_is_a_declared_setting() -> None:
    env = {"TB_LAKE_QUERY_LIMITS": "FEAS=1800, COHORT=1200"}
    assert lake_query_limit("FEAS", env) == 1800 and lake_query_limit("COHORT", env) == 1200
    assert lake_query_limit("SCREEN", env) is None  # not listed: the lake's own limit
    assert lake_query_limit("FEAS", {}) == 1800  # the declared default
    for bad in ("FEAS=", "FEAS=0", "FEAS=ten", "=10", "FEAS"):
        with pytest.raises(ValueError, match="TB_LAKE_QUERY_LIMITS"):
            lake_query_limit("FEAS", {"TB_LAKE_QUERY_LIMITS": bad})


class _Lake:
    def __init__(self) -> None:
        self.asked: list[Any] = []

    def snapshot(self) -> str:
        return NIGHT

    def query(self, sql: str, params: Any = None, snapshot: str | None = None, timeout_s: int | None = None) -> str:
        self.asked.append(timeout_s)
        return "t"


class _OldLake:  # a stand-in with the old signature (tests, a library lake): still served
    def snapshot(self) -> str:
        return NIGHT

    def query(self, sql: str, params: Any = None, snapshot: str | None = None) -> str:
        return "t"


def _pinned(lake: Any, limit: int | None) -> PinnedLake:
    from datetime import date

    return PinnedLake(lake, today=lambda: date.fromisoformat(NIGHT), max_age_days=9999, query_limit_s=limit)


def test_a_jobs_queries_carry_its_limit() -> None:
    lk = _Lake()
    _pinned(lk, 1800).query("SELECT 1")
    _pinned(lk, None).query("SELECT 1")
    _pinned(lk, 1800).query("SELECT 1", timeout_s=60)  # a caller's own limit for one query
    assert lk.asked == [1800, None, 60]
    assert _pinned(_OldLake(), 1800).query("SELECT 1") == "t"


def test_the_jobs_lake_takes_the_limit_of_its_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import jobs

    monkeypatch.setenv("TB_LAKE_QUERY_LIMITS", "FEAS=1700")
    assert jobs.lake_query_limit("FEAS") == 1700


# ---------------------------------------------------------------------------------------------- review (D-746)
def test_an_empty_setting_keeps_the_default_and_bad_values_are_refused() -> None:
    assert lake_query_limit("FEAS", {"TB_LAKE_QUERY_LIMITS": ""}) == 1800  # an empty line in .env is not "none"
    for bad in ("FEAS=1800,FEAS=60", "FEAS=１０", "FEAS=²", "FEAS=86401", "feas"):
        with pytest.raises(ValueError, match="TB_LAKE_QUERY_LIMITS"):
            lake_query_limit("FEAS", {"TB_LAKE_QUERY_LIMITS": bad})


def test_the_client_keeps_its_connect_wait() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.extensions["timeout"])
        return httpx.Response(500, json={"detail": "x"})

    http = LakeHttp("http://lake")
    http.client = httpx.Client(transport=httpx.MockTransport(handler), timeout=330)
    with pytest.raises(LakeQueryFailed):
        http.query("SELECT 1", timeout_s=1800)
    assert seen["read"] == 1800 + READ_MARGIN_S and seen["connect"] == 330 and seen["pool"] == 330


def test_the_lake_refuses_a_limit_that_is_no_limit(lake: store.Lake) -> None:
    for bad in (0, -10, store.MAX_QUERY_LIMIT_S + 1):
        with pytest.raises(store.LakeSaid, match="time limit"):
            lake.query("SELECT 1", timeout_s=bad)
    assert store.query_failure_status(store.LakeSaid("x")) == 422  # the caller's fault, not the lake's


def test_a_rerun_and_the_library_lake_pass_the_limit_on() -> None:
    from orchestrator.rerun import PinnedLake as RerunLake

    lk = _Lake()
    _pinned(RerunLake(lk, NIGHT), 1800).query("SELECT 1")
    assert lk.asked == [1800]  # a re-run of a FEAS job has the job's limit, as the run had
    import inspect

    from lake.client import LakeLocal

    assert "timeout_s" in inspect.signature(LakeLocal.query).parameters


def test_the_lakes_time_limit_is_said_in_the_jobs_failure() -> None:
    from orchestrator.core import _error

    said = _error(LakeQueryFailed(503, "LakeTimeLimitError: LAKE-TIME: the lake query was stopped at ..."), "running")
    assert said.detail and "LAKE-TIME" in said.detail and "503" in said.detail
    plain = _error(LakeQueryFailed(503, "OSError: LAKE-QUERY: the lake's engine could not run the query"), "running")
    assert plain.detail == "HTTP 503"  # any other failure of the lake: as before (D-557)


def test_a_feas_job_sends_its_limit_and_a_bad_setting_fails_the_job_naming_it(
    _make_job_fixture: Any,  # noqa: F811  (the fixture, by its imported name)
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date

    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from orchestrator.core import Ctx, Outcome

    from tests.unit.test_snapshot_pin import NIGHT_1, _night, _run

    _night(tmp_path / "lake", NIGHT_1, 2)
    seen: list[Any] = []

    class Spy(LakeLocal):
        def query(self, sql: str, params: Any = None, snapshot: str | None = None, timeout_s: int | None = None) -> Any:
            seen.append(timeout_s)
            return super().query(sql, params, snapshot, timeout_s)

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        ctx.services.lake.query("SELECT count(*) AS n FROM patient")
        return Outcome(summary_md="ok")

    orch = _make_job_fixture(
        {"FEAS": scenario}, date.fromisoformat(NIGHT_1), 3, Spy(tmp_path / "lake", HashEmbedder(), "Asia/Taipei")
    )
    assert _run(orch).state == "done" and seen == [1800]
    monkeypatch.setenv("TB_LAKE_QUERY_LIMITS", "FEAS=30min")
    job = _run(orch)
    assert job.state == "failed" and job.error and "TB_LAKE_QUERY_LIMITS" in job.error.message, job.error
