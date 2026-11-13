"""NEW-B-35 (D-676): the twin's reader does not take a failing lake for an older snapshot.

``patient_profile.twin.lake_schema`` asked the snapshot for its layout version and read *every* error as "a
snapshot of schema 1" (no version column). A lake that failed on that one question (D-675: a 5xx) was then read
as an old layout, and the twins of the night were built without the provenance of their rows. Now only the
engine's own sentence about that one column is read as schema 1; anything else stops the build."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient
from lake import app as lake_app
from lake import store
from lake.client import LakeHttp, LakeQueryFailed
from patient_profile import twin

from tests.unit.test_lake_query_status import LAKE, QUESTION, VALUE, _ids, _service

SNAP = "2026-10-04"


def _engine_says(columns: str, sql: str) -> BaseException:
    """What the engine itself raises for ``sql`` on a ``lake_meta`` of ``columns``."""
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"CREATE TABLE lake_meta ({columns})")
        with pytest.raises(duckdb.Error) as got:
            con.execute(sql)
        return got.value
    finally:
        con.close()


def _no_version_column() -> BaseException:
    return _engine_says("snapshot VARCHAR, built_at VARCHAR", "SELECT schema_version FROM lake_meta")


class _Local:
    """A lake in the caller's process: the engine's and the lake's own classes, no status."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def query(self, *_a: Any, **_k: Any) -> Any:
        raise self.exc


def test_a_snapshot_without_the_version_column_is_schema_1_over_http_and_in_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = _no_version_column()
    assert "schema_version" in str(exc)  # the engine's sentence of the pinned version names the column
    assert twin.lake_schema(_Local(exc), SNAP) == 1
    assert twin.lake_schema(_service(monkeypatch, exc), SNAP) == 1


@pytest.mark.parametrize(("exc", "status", "says"), LAKE, ids=_ids)
def test_a_lake_that_fails_is_not_an_older_snapshot(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, status: int, says: str
) -> None:
    with pytest.raises(LakeQueryFailed) as got:
        twin.lake_schema(_service(monkeypatch, exc), SNAP)
    assert got.value.status == status and says in str(got.value) and VALUE not in str(got.value)
    with pytest.raises(type(exc)):  # the lake as a library: the same, by the error's own class
        twin.lake_schema(_Local(exc), SNAP)


@pytest.mark.parametrize(("exc", "status", "says"), QUESTION, ids=_ids)
def test_another_fault_of_the_question_stops_too(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, status: int, says: str
) -> None:
    with pytest.raises(LakeQueryFailed) as got:
        twin.lake_schema(_service(monkeypatch, exc), SNAP)
    assert got.value.status == status
    with pytest.raises(type(exc)):
        twin.lake_schema(_Local(exc), SNAP)


def test_the_lake_failing_with_words_about_the_column_is_still_the_lake_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exc = duckdb.IOException('IO Error: Referenced column "schema_version" not found: could not read the file')
    with pytest.raises(duckdb.IOException):
        twin.lake_schema(_Local(exc), SNAP)
    with pytest.raises(LakeQueryFailed) as got:
        twin.lake_schema(_service(monkeypatch, exc), SNAP)
    assert got.value.status == 500


def test_the_twins_reader_stops_when_only_the_version_question_fails() -> None:
    """Before: the version question failed, the rows were read all the same, without their provenance."""
    asked: list[str] = []

    class FailsOnce:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            asked.append(sql)
            if "lake_meta" in sql:
                raise store.LakeLimitError("LAKE-LIMIT: the query needed more memory than the box allows")
            raise AssertionError("the rows were asked for after the version question failed")

    with pytest.raises(store.LakeLimitError):
        twin.read_lake(FailsOnce(), ["p1"], SNAP)
    assert len(asked) == 1


def test_a_real_lake_says_its_version_through_the_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from embed_service.embedder import HashEmbedder

    from tests.unit.test_polled_jobs import NIGHT, TZ, _patients

    lake_dir = tmp_path / "lake"
    _patients(lake_dir, NIGHT, 3)
    real = store.Lake(lake_dir, TZ)
    real.rebuild(NIGHT, HashEmbedder())
    monkeypatch.setattr(lake_app, "lake", lambda: real)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    assert twin.lake_schema(http, NIGHT) == store.LAKE_SCHEMA_VERSION
    with pytest.raises(LakeQueryFailed) as gone:  # a night the lake does not hold: 503, never "schema 1"
        twin.lake_schema(http, "2031-01-01")
    assert gone.value.status == 503
