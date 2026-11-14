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
