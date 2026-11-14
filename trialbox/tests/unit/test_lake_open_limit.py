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
        lake.connect()  # the query and the search open through it


def test_the_service_answers_503_with_the_limits_words(lake: store.Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", TINY)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    with pytest.raises(LakeQueryFailed) as got:
        http.query("SELECT count(*) AS n FROM patient")
    assert got.value.status == 503 and "LakeLimitError: LAKE-LIMIT" in str(got.value), str(got.value)
    monkeypatch.delenv("TB_LAKE_MEMORY_LIMIT")  # the limit lifted: the same question is answered
    assert http.query("SELECT count(*) AS n FROM patient").to_pylist() == [{"n": 3}]


def test_the_engines_own_out_of_memory_is_a_limit_wherever_it_comes_from() -> None:
    """The status rule places the engine's class too: a reader that met it outside ``connect`` and ``query``."""
    exc: Any = duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate data of size 32.0 KiB")
    assert store.query_failure_status(exc) == 503
    assert "LAKE-LIMIT" in store.error_answer(exc)


def test_the_note_search_answers_503_with_the_limits_words(lake: store.Lake, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review: ``/chunks/search`` handed the limit to the catch-all, which answered 500 "internal error"."""
    from embed_service.embedder import HashEmbedder

    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", TINY)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    monkeypatch.setattr(lake_app, "embedder", HashEmbedder)
    got = TestClient(lake_app.app, raise_server_exceptions=False).post(
        "/chunks/search", json={"pid": "p1", "query": "chest pain", "k": 3}
    )
    assert got.status_code == 503, got.text
    assert "LakeLimitError: LAKE-LIMIT" in got.json()["detail"]


def test_a_builds_out_of_memory_keeps_the_builds_words() -> None:
    """Review: the limit's sentence speaks of a query and passes the engine's first line; a build says neither."""
    exc: Any = duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate data of size 32.0 KiB")
    said = store.error_answer(exc, "build")
    assert "LAKE-BUILD" in said and "query" not in said and "32.0 KiB" not in said, said


def test_an_out_of_memory_without_words_is_still_answered() -> None:
    exc: Any = duckdb.OutOfMemoryException("")
    assert "LAKE-LIMIT" in store.error_answer(exc)


def test_the_limit_met_in_the_old_layouts_view_is_not_swallowed() -> None:
    """Review: the view an older snapshot gets swallowed every engine error, the limit too; the reader then failed
    later as a question that names a column that is not there (422)."""

    class Con:
        def execute(self, sql: str) -> Any:
            if sql.startswith("CREATE TEMP VIEW"):
                raise duckdb.OutOfMemoryException("Out of Memory Error: failed to allocate data of size 1 KiB")
            return duckdb.connect().execute("SELECT 'main'")

    with pytest.raises(duckdb.OutOfMemoryException):
        store._compat_views(Con(), 3)  # type: ignore[arg-type]
