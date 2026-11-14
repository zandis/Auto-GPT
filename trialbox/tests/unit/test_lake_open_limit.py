"""NEW-B-41 (D-742): a memory limit met while the lake opens a snapshot is the lake's limit, as in a query.

Lane C2's review by running against the real lake service (NEW-SITE-5): with the box's memory limit met while the
snapshot was opened, ``/query`` answered 500 "OutOfMemoryException: LAKE-QUERY", where a limit met in the query
answers 503 ``LAKE-LIMIT`` (D-675): ``Lake.connect`` was outside the query's limit handler. Reproduced here with a
256 KB limit on a real small lake."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from lake import app as lake_app
from lake import store
from lake.client import LakeHttp, LakeQueryFailed

from tests.unit.test_polled_jobs import NIGHT, TZ, _patients

TINY = "256KB"  # below what opening a snapshot needs: met while the lake opens it


@pytest.fixture
def lake(tmp_path: Path) -> store.Lake:
    from embed_service.embedder import HashEmbedder

    _patients(tmp_path / "lake", NIGHT, 3)
    real = store.Lake(tmp_path / "lake", TZ)
    real.rebuild(NIGHT, HashEmbedder())
    return real


def test_a_limit_met_while_the_snapshot_opens_is_the_lakes_limit(
    lake: store.Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", TINY)
    with pytest.raises(store.LakeLimitError, match="LAKE-LIMIT"):
        lake.query("SELECT count(*) AS n FROM patient")
    with pytest.raises(store.LakeLimitError, match="LAKE-LIMIT"):
        lake.connect()  # every reader opens through it (search, chunks, holds)


def test_the_service_answers_503_with_the_limits_words(lake: store.Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", TINY)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    with pytest.raises(LakeQueryFailed) as got:
        http.query("SELECT count(*) AS n FROM patient")
    assert got.value.status == 503 and "LAKE-LIMIT" in str(got.value), str(got.value)
    monkeypatch.delenv("TB_LAKE_MEMORY_LIMIT")  # the limit lifted: the same question is answered
    assert http.query("SELECT count(*) AS n FROM patient").to_pylist() == [{"n": 3}]


def test_the_engines_own_out_of_memory_is_a_limit_wherever_it_comes_from() -> None:
    """The status rule places the engine's class too: a reader that met it outside ``connect`` and ``query``."""
    exc: Any = duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate data of size 32.0 KiB")
    assert store.query_failure_status(exc) == 503
    assert "LAKE-LIMIT" in store.error_answer(exc)
