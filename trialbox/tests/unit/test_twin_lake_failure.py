"""NEW-B-35 (D-676): the twin's reader does not take a failing lake for an older snapshot.

``patient_profile.twin.lake_schema`` asked the snapshot for its layout version and read *every* error as "a
snapshot of schema 1" (no version column). A lake that failed on that one question (D-675: a 5xx) was then read
as an old layout, and the twins of the night were built without the provenance of their rows. Now the lake is
asked whether the column is there (one row, one number), and nothing is read from an error: any failure stops
the build."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from lake import app as lake_app
from lake import store
from lake.client import LakeHttp, LakeLocal, LakeQueryFailed
from patient_profile import twin

from tests.unit.test_lake_query_status import LAKE, QUESTION, VALUE, _ids, _service

SNAP = "2026-10-04"
#: the engine's own sentence for a ``lake_meta`` without the column: what the old code met on a schema-1 snapshot
NO_COLUMN = duckdb.BinderException('Binder Error: Referenced column "schema_version" not found in FROM clause!')
EVERY = [*LAKE, *QUESTION, (NO_COLUMN, 422, 'Referenced column "schema_version" not found')]


class _Local:
    """A lake in the caller's process that fails: the engine's and the lake's own classes, no status."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def query(self, *_a: Any, **_k: Any) -> Any:
        raise self.exc


class _Says:
    """A lake that answers the column question with ``rows`` and the version question with ``version``."""

    def __init__(self, rows: list[dict[str, Any]], version: Any = None) -> None:
        self.rows, self.version, self.asked = rows, version, []  # type: ignore[var-annotated]

    def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
        self.asked.append(sql)
        if "duckdb_columns" in sql:
            return pa.Table.from_pylist(self.rows) if self.rows else pa.table({"n": pa.array([], pa.int64())})
        if isinstance(self.version, BaseException):
            raise self.version
        return pa.Table.from_pylist([{"schema_version": self.version}])


def _real_lake(lake_dir: Path) -> tuple[store.Lake, str]:
    from embed_service.embedder import HashEmbedder

    from tests.unit.test_polled_jobs import NIGHT, TZ, _patients

    _patients(lake_dir, NIGHT, 3)
    real = store.Lake(lake_dir, TZ)
    real.rebuild(NIGHT, HashEmbedder())
    return real, NIGHT


def _http(monkeypatch: pytest.MonkeyPatch, real: store.Lake) -> LakeHttp:
    monkeypatch.setattr(lake_app, "lake", lambda: real)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    return http


@pytest.mark.parametrize(("exc", "status", "says"), EVERY, ids=_ids)
def test_no_failure_of_the_version_question_is_read_as_an_older_snapshot(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, status: int, says: str
) -> None:
    with pytest.raises(LakeQueryFailed) as got:
        twin.lake_schema(_service(monkeypatch, exc), SNAP)
    assert got.value.status == status and says in str(got.value) and VALUE not in str(got.value)
    with pytest.raises(type(exc)):  # the lake as a library: the same, by the error's own class
        twin.lake_schema(_Local(exc), SNAP)


def test_a_snapshot_without_the_column_is_schema_1_and_only_the_lakes_plain_zero_says_so() -> None:
    none = _Says([{"n": 0}])
    assert twin.lake_schema(none, SNAP) == 1 and len(none.asked) == 1  # the version is not asked for
    assert twin.lake_schema(_Says([{"n": 1}], 3), SNAP) == 3
    assert twin.lake_schema(_Says([{"n": 1}], None), SNAP) == 1  # a column that holds nothing: as before
    for rows in ([], [{"n": None}], [{"n": "0"}], [{"n": 0.0}], [{"n": False}], [{"n": 0}, {"n": 0}], [{"m": 0}]):
        with pytest.raises(twin.TwinError, match="did not say"):
            twin.lake_schema(_Says(rows), SNAP)


def test_the_lake_failing_on_the_version_after_saying_the_column_is_there_stops_too() -> None:
    for exc, _status, _says in EVERY:
        with pytest.raises(type(exc)):
            twin.lake_schema(_Says([{"n": 1}], exc), SNAP)


def test_the_twins_reader_asks_for_no_rows_when_the_layout_question_fails() -> None:
    """Before: the version question failed, the rows were read all the same, without their provenance."""
    asked: list[str] = []

    class FailsFirst:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            asked.append(sql)
            if len(asked) == 1:
                raise store.LakeLimitError("LAKE-LIMIT: the query needed more memory than the box allows")
            raise AssertionError("asked again after the layout question failed")

    with pytest.raises(store.LakeLimitError):
        twin.read_lake(FailsFirst(), ["p1"], SNAP)
    assert len(asked) == 1


def test_a_real_lake_says_its_version_and_a_night_it_does_not_hold_is_not_schema_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real, night = _real_lake(tmp_path / "lake")
    http = _http(monkeypatch, real)
    assert http.query(twin.VERSION_COLUMN_SQL, [], night).to_pylist() == [{"n": 1}]  # the guard lets it through
    assert twin.lake_schema(http, night) == store.LAKE_SCHEMA_VERSION
    assert twin.lake_schema(LakeLocal(tmp_path / "lake", real_embedder(), real.tz), night) == store.LAKE_SCHEMA_VERSION
    with pytest.raises(LakeQueryFailed) as gone:
        twin.lake_schema(http, "2031-01-01")
    assert gone.value.status == 503


def test_a_real_snapshot_built_before_the_version_was_recorded_is_schema_1_and_its_rows_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real lake file whose ``lake_meta`` has no version column (as a schema-1 snapshot), through the service
    and in process: schema 1, and the rows come without provenance, as before."""
    real, night = _real_lake(tmp_path / "lake")
    for f in (tmp_path / "lake" / "db").rglob("*.duckdb"):
        if ".open" in f.parts:
            continue
        con = duckdb.connect(str(f))
        con.execute("ALTER TABLE lake_meta DROP COLUMN IF EXISTS schema_version")
        con.execute("CHECKPOINT")
        con.close()
    local = LakeLocal(tmp_path / "lake", real_embedder(), real.tz)
    http = _http(monkeypatch, store.Lake(tmp_path / "lake", real.tz))
    for lake in (local, http):
        assert lake.query(twin.VERSION_COLUMN_SQL, [], night).to_pylist() == [{"n": 0}]
        assert twin.lake_schema(lake, night) == 1
        pids = [r["pid"] for r in lake.query("SELECT pid FROM patient", [], night).to_pylist()]
        rows = twin.read_lake(lake, pids, night)
        assert pids and all(rows[p]["patient"] for p in pids)
        assert all(r[c] is None for p in pids for r in rows[p]["patient"] for c in twin._PROV)


def real_embedder() -> Any:
    from embed_service.embedder import HashEmbedder

    return HashEmbedder()
