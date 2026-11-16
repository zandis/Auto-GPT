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


def _old_layout(lake_dir: Path, version: int | None) -> None:
    """Every built file of the lake made to say an older layout: the version column dropped (schema 1) or set."""
    for f in (lake_dir / "db").rglob("*.duckdb"):
        if ".open" in f.parts:
            continue
        con = duckdb.connect(str(f))
        if version is None:
            con.execute("ALTER TABLE lake_meta DROP COLUMN IF EXISTS schema_version")
        else:
            con.execute(f"UPDATE lake_meta SET schema_version = {int(version)}")
        con.execute("CHECKPOINT")
        con.close()


@pytest.mark.parametrize("version", [None, 2], ids=["schema 1 (no version column)", "schema 2"])
def test_a_snapshot_older_than_schema_3_is_refused_with_a_plain_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int | None
) -> None:
    """NEW-B-40 (D-741): the twin's rows need the encounter's status and each row's provenance, which came with lake
    schema 3. A snapshot of schema 1 or 2 failed at the encounter query with the engine's sentence (a 422), and the
    "schema 1: rows without provenance" branch never ended in a twin. Now the reader says what to do, before any
    row is asked for."""
    real, night = _real_lake(tmp_path / "lake")
    _old_layout(tmp_path / "lake", version)
    local = LakeLocal(tmp_path / "lake", real_embedder(), real.tz)
    http = _http(monkeypatch, store.Lake(tmp_path / "lake", real.tz))
    for lake in (local, http):
        assert twin.lake_schema(lake, night) == (version or 1)
        with pytest.raises(twin.TwinError) as got:
            twin.read_lake(lake, ["p1"], night)
        said = str(got.value)
        assert f"lake schema {version or 1}" in said and "schema 3 or later" in said and "rebuild" in said


def test_a_snapshot_of_schema_3_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The floor is 3, not 4: a file of schema 3 (no ``patient.deceased``, which came with schema 4; the lake's compat
    view gives it as null) is read, through the service and in process (the review: a reader that refused schema 3
    passed every other test)."""
    real, night = _real_lake(tmp_path / "lake")
    done: set[tuple[int, int]] = set()
    for f in (tmp_path / "lake" / "db").rglob("*.duckdb"):
        st = f.stat()
        if ".open" in f.parts or (st.st_dev, st.st_ino) in done:  # one file may have two names (a generation)
            continue
        done.add((st.st_dev, st.st_ino))
        con = duckdb.connect(str(f))
        con.execute("ALTER TABLE patient DROP COLUMN IF EXISTS deceased")
        con.execute("UPDATE lake_meta SET schema_version = 3")
        con.execute("CHECKPOINT")
        con.close()
    for lake in (
        LakeLocal(tmp_path / "lake", real_embedder(), real.tz),
        _http(monkeypatch, store.Lake(tmp_path / "lake", real.tz)),
    ):
        assert twin.lake_schema(lake, night) == 3
        pids = [r["pid"] for r in lake.query("SELECT pid FROM patient", [], night).to_pylist()]
        rows = twin.read_lake(lake, pids, night)
        assert pids and all(rows[p]["patient"] and rows[p]["patient"][0]["deceased"] is None for p in pids)


def test_the_reader_asks_only_the_layout_before_it_refuses() -> None:
    asked: list[str] = []

    class Old:
        def query(self, sql: str, *_a: Any, **_k: Any) -> Any:
            asked.append(sql)
            if "duckdb_columns" in sql:
                return pa.Table.from_pylist([{"n": 1}])
            if "lake_meta" in sql:
                return pa.Table.from_pylist([{"schema_version": 2}])
            raise AssertionError("a row was asked for")

    with pytest.raises(twin.TwinError, match="lake schema 2"):
        twin.read_lake(Old(), ["p1"], SNAP)
    assert len(asked) == 2


def test_the_night_step_says_why_no_twin_was_built(
    db_url: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The night step never fails the ingest; it logs the reader's own sentence (it names no patient), and keeps no
    twin. The generation ledger keeps "building" (it has no field for a reason)."""
    from tests.unit import test_twin as tt

    store.Lake(tmp_path / "lake", tt.ZONE).rebuild(tt.S1, real_embedder(), tt._write(tmp_path / "nd1", tt._feed()))
    _old_layout(tmp_path / "lake", 2)
    lake = LakeLocal(tmp_path / "lake", real_embedder(), tt.ZONE)
    assert twin.after_ingest(tt._OrchDb(), lake, tt.S1, tt.NOW, db_url) is None
    assert "has lake schema 2; a twin needs schema 3 or later" in caplog.text
    kept = twin.ProfileStore(db_url)
    try:
        assert kept.current(tt.P1) is None
    finally:
        kept.close()


def real_embedder() -> Any:
    from embed_service.embedder import HashEmbedder

    return HashEmbedder()


def test_the_night_keeps_no_twin_built_on_a_guess_when_the_lake_fails_on_the_layout_question(
    db_url: str, tmp_path: Path
) -> None:
    """The defect, end to end on a real lake and a real store: the lake fails on the layout question only. Before,
    the night step read "schema 1" and kept two twins without the provenance of their rows; now it keeps none and
    answers None (the build did not run: the ledger of the night keeps "building", the ingest has passed)."""
    from tests.unit import test_twin as tt

    store.Lake(tmp_path / "lake", tt.ZONE).rebuild(tt.S1, real_embedder(), tt._write(tmp_path / "nd1", tt._feed()))
    real = LakeLocal(tmp_path / "lake", real_embedder(), tt.ZONE)

    class FailsOnTheLayout:
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            if "lake_meta" in sql:
                raise store.LakeLimitError("LAKE-LIMIT: the query needed more memory than the box allows")
            return real.query(sql, params, snapshot)

    assert twin.after_ingest(tt._OrchDb(), FailsOnTheLayout(), tt.S1, tt.NOW, db_url) is None
    kept = twin.ProfileStore(db_url)
    try:
        assert kept.current(tt.P1) is None and kept.current(tt.P2) is None
    finally:
        kept.close()
    rep = twin.after_ingest(tt._OrchDb(), real, tt.S1, tt.NOW, db_url)  # the next run, the lake well: built
    assert rep is not None and rep.inserted == 2
