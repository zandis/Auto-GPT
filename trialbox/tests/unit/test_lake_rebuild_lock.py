"""The lake's rebuild and hold under one lock (T-722, D-462; lifecycle review 2026-11-12 F-1, scale review F-01).

A hold taken while a rebuild of the same snapshot runs must protect the bytes the job pinned: the rebuild checks the
holds again at the swap and is refused there. Two rebuilds of one snapshot never write ``<snapshot>.building`` at the
same time: the second is refused with "already building". The lock works across processes (the lake runs two
uvicorn workers). Synthetic patients only."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from embed_service.embedder import HashEmbedder
from lake import store
from lake.source import lake_rows as source_lake_rows
from lake.store import Lake, SnapshotHeld
from tb_common import id_rule

ROOT = Path(__file__).resolve().parents[2]
NIGHT = "2026-10-04"
TZ = "Asia/Taipei"


def _patients(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    id_rule.write_snapshot_record(nd)  # D-1253: a snapshot of this release
    pats = [{"resourceType": "Patient", "id": f"syn-{i:03d}", "gender": "female"} for i in range(n)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")


def _count(lake: Lake, snap: str) -> int:
    return int(lake.query("SELECT count(*) AS n FROM patient", [], snap).to_pylist()[0]["n"])


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class _Paused:
    """A rebuild that stops inside its build (after its start checks, before it writes the new file) until let go."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, snap: str = NIGHT) -> None:
        self.inside = threading.Event()
        self.go = threading.Event()
        orig = source_lake_rows

        def rows(*a: Any, **k: Any) -> Any:
            if k.get("snapshot") == snap:  # only the paused snapshot's build stops
                self.inside.set()
                assert self.go.wait(60), "the test never let the rebuild go"
            return orig(*a, **k)

        monkeypatch.setattr(store, "lake_rows", rows)

    def start(self, lake_dir: Path, snap: str) -> tuple[threading.Thread, dict[str, Any]]:
        out: dict[str, Any] = {}

        def run() -> None:
            try:
                out["stats"] = Lake(lake_dir, TZ).rebuild(snap, HashEmbedder())
            except Exception as exc:
                out["error"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        assert self.inside.wait(60), "the rebuild never reached its build"
        return t, out


@pytest.fixture
def lake_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "lake"
    _patients(d, NIGHT, 3)
    Lake(d, TZ).rebuild(NIGHT, HashEmbedder())
    yield d


def test_a_hold_taken_while_a_rebuild_runs_protects_the_pinned_bytes(
    lake_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-1 turned round: the same pin read 3 patients, then 5. Now it reads 3 to its end and the rebuild is refused
    at the swap with nothing replaced."""
    lake = Lake(lake_dir, TZ)
    db = lake.db_path(NIGHT)
    before = _sha(db)
    parquet = lake_dir / "parquet" / f"snapshot={NIGHT}" / "patient.parquet"
    parquet_before = _sha(parquet)
    _patients(lake_dir, NIGHT, 5)  # the night's folder now says 5 (a site publish, a re-run of the served night)
    paused = _Paused(monkeypatch)
    t, out = paused.start(lake_dir, NIGHT)
    pinned = lake.pin(date(2026, 10, 5), 7)  # a SCREEN starts during the rebuild: pin, then hold (PinnedLake.pin)
    lake.hold(pinned, "01SCREEN")
    first = _count(lake, pinned)
    paused.go.set()
    t.join(60)
    later = _count(lake, pinned)
    assert (first, later) == (3, 3)
    assert isinstance(out.get("error"), SnapshotHeld) and "running job" in str(out["error"])
    assert _sha(db) == before and _sha(parquet) == parquet_before and lake.verify(NIGHT) == []
    assert lake.current() == NIGHT
    assert not (lake_dir / "db" / f"{NIGHT}.building").exists()
    assert not (lake_dir / "parquet" / ".building").exists() or not any((lake_dir / "parquet" / ".building").iterdir())
    lake.release("01SCREEN")  # the job ends: the next publish goes
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
    assert _count(lake, NIGHT) == 5 and lake.verify(NIGHT) == []


def test_two_rebuilds_of_one_snapshot_are_serialised(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lake.store import SnapshotBuilding

    _patients(lake_dir, NIGHT, 4)
    paused = _Paused(monkeypatch)
    t, out = paused.start(lake_dir, NIGHT)
    with pytest.raises(SnapshotBuilding, match="already building"):
        Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())  # a retry while the first runs writes nothing
    assert isinstance(SnapshotBuilding("x"), store.RebuildError)  # the service's 409, the adapter's held night
    paused.go.set()
    t.join(60)
    assert "error" not in out, out.get("error")
    assert _count(Lake(lake_dir, TZ), NIGHT) == 4
    # finished: the next rebuild of the snapshot goes; another snapshot was never blocked by the first
    other = "2026-10-05"
    _patients(lake_dir, other, 2)
    assert Lake(lake_dir, TZ).rebuild(other, HashEmbedder()).promoted is True
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())  # older than CURRENT now: built, not promoted
    assert Lake(lake_dir, TZ).current() == other


def test_current_is_read_again_at_the_swap(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A newer night promoted while an older one builds: the older one is not promoted over it (DATA-007)."""
    _patients(lake_dir, NIGHT, 4)
    newer = "2026-10-06"
    paused = _Paused(monkeypatch)
    t, out = paused.start(lake_dir, NIGHT)
    _patients(lake_dir, newer, 2)
    assert Lake(lake_dir, TZ).rebuild(newer, HashEmbedder()).promoted is True  # another snapshot is not blocked
    paused.go.set()
    t.join(60)
    assert "error" not in out, out.get("error")
    assert out["stats"].promoted is False and Lake(lake_dir, TZ).current() == newer
    assert _count(Lake(lake_dir, TZ), NIGHT) == 4  # built all the same


def test_a_failed_build_leaves_nothing_and_the_next_one_goes(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = Lake(lake_dir, TZ).db_path(NIGHT)
    before = _sha(db)
    orig = source_lake_rows

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "lake_rows", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
    assert _sha(db) == before
    monkeypatch.setattr(store, "lake_rows", orig)
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())  # the build lock was released by the failure


# ------------------------------------------------------------------ across processes (two uvicorn workers)

_CHILD = """
import sys
from pathlib import Path
from lake import store
from tb_common import id_rule
kind, lake_dir = sys.argv[1], Path(sys.argv[2])
cm = store.lake_lock(lake_dir) if kind == "lake" else store.building(lake_dir, sys.argv[3])
with cm:
    print("locked", flush=True)
    sys.stdin.readline()
"""


def _child(*args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))}
    p = subprocess.Popen(
        [sys.executable, "-c", _CHILD, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=ROOT,
    )
    assert p.stdout is not None and p.stdout.readline().strip() == "locked"
    return p


def _end(p: subprocess.Popen[str]) -> None:
    assert p.stdin is not None
    p.stdin.write("\n")
    p.stdin.flush()
    assert p.wait(60) == 0


def test_the_locks_hold_across_processes(lake_dir: Path) -> None:
    from lake.store import SnapshotBuilding

    # another worker is building the snapshot: this worker's rebuild is refused at once, nothing written
    p = _child("build", str(lake_dir), NIGHT)
    try:
        db = Lake(lake_dir, TZ).db_path(NIGHT)
        before = _sha(db)
        with pytest.raises(SnapshotBuilding, match="already building"):
            Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
        assert _sha(db) == before
    finally:
        _end(p)
    # another worker is at a swap (holds the lake lock): a hold here waits for it, then lands
    p = _child("lake", str(lake_dir))
    done = threading.Event()

    def hold() -> None:
        Lake(lake_dir, TZ).hold(NIGHT, "01OTHER")
        done.set()

    t = threading.Thread(target=hold, daemon=True)
    try:
        t.start()
        assert not done.wait(0.5)  # blocked by the other process's lock
    finally:
        _end(p)
    assert done.wait(60) and Lake(lake_dir, TZ).holds() == {"01OTHER": NIGHT}


# ------------------------------------------------------------------ the site publish sees "already building"


class _Store:
    def __init__(self) -> None:
        self.pub: dict[str, Any] | None = None

    def facts(self, ws: str, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "pid": "p1", "domain": "condition", "term": "gout", "code": "M10.1",
                 "system": "http://hl7.org/fhir/sid/icd-10", "value": "", "unit": "", "day": "2026-10-01",
                 "status": "coded", "local_code": "", "local_system": "", "quote": "", "input_id": 1}]  # fmt: skip

    def mapping(self, ws: str) -> dict[Any, Any]:
        return {}

    def inputs(self, ws: str, kind: str) -> list[dict[str, Any]]:
        return []

    def published(self, ws: str) -> dict[str, Any] | None:
        return self.pub

    def set_published(self, ws: str, at: str, snapshot: str, digest: str, counts: dict[str, int]) -> None:
        self.pub = {"snapshot": snapshot, "digest": digest, "counts": counts}


def test_the_site_publish_answers_already_building(tmp_path: Path) -> None:
    from lake.store import SnapshotBuilding
    from sitesetup import service as svc_mod
    from sitesetup.service import SiteSetup
    from tb_common.audit import AuditLog

    class Resp:
        status_code = 409
        text = '{"detail":"lake snapshot 2026-10-04 is already building (another rebuild runs)"}'

    class HttpError(Exception):
        response = Resp()

    class Busy:
        def __init__(self, exc: Exception) -> None:
            self.exc, self.rebuilds = exc, 0

        def snapshot(self) -> str:
            return NIGHT

        def put_site(self, res: Any) -> dict[str, int]:
            return {}

        def holds(self) -> dict[str, str]:
            return {}

        def rebuild(self, snap: str, allow_empty: bool = False) -> dict[str, Any]:
            self.rebuilds += 1
            raise self.exc

    for exc in (SnapshotBuilding("lake snapshot 2026-10-04 is already building"), HttpError()):
        st = _Store()
        audit = AuditLog(tmp_path / f"audit-{type(exc).__name__}")
        svc = SiteSetup(st, tmp_path / "setup", Busy(exc), None, audit,  # type: ignore[arg-type]
                        lambda: datetime(2026, 10, 5, tzinfo=UTC), lambda: date(2026, 10, 5), lambda: b"k" * 32)  # fmt: skip
        out = svc.publish("main", "batch")
        assert out["pending"] and out["building"] and out["held_by_jobs"] == 0 and st.pub is None
        logs = "".join(f.read_text(encoding="utf-8") for f in audit.directory.glob("*.jsonl"))
        assert "setup.publish_building" in logs
    assert not svc_mod._building_refusal(ValueError("x")) and not svc_mod._held_refusal(HttpError())

    class HeaderResp:  # the service's own marker, whatever the text
        status_code = 409
        text = "{}"
        headers: ClassVar[dict[str, str]] = {"X-TB-Lake-Busy": "building"}

    class HeaderError(Exception):
        response = HeaderResp()

    assert svc_mod._building_refusal(HeaderError())
    # review 6: the practice site's double click is "building" too, not a crash
    st = _Store()
    svc = SiteSetup(st, tmp_path / "setup", Busy(RuntimeError("unused")), None, AuditLog(tmp_path / "audit-p"),  # type: ignore[arg-type]
                    lambda: datetime(2026, 10, 5, tzinfo=UTC), lambda: date(2026, 10, 5), lambda: b"k" * 32)  # fmt: skip
    svc._lakes["prac"] = Busy(SnapshotBuilding("lake snapshot 2026-10-05 is already building"))
    out = svc.publish("prac", "crc")
    assert out["pending"] and out["building"] and st.pub is None
    svc._lakes["prac"] = Busy(SnapshotHeld("held by a running job"))
    with pytest.raises(SnapshotHeld):  # a practice site has no batching: a refusal other than busy stays an error
        svc.publish("prac", "crc")


def test_pruning_leaves_a_snapshot_that_is_building_and_never_deletes_a_build_lock(tmp_path: Path) -> None:
    """Review 1 and 2: pruning deleted a build lock someone had open (two writers then) and a snapshot a rebuild was
    building (it came back at the swap). Pruning now takes the build lock without waiting and skips that snapshot."""
    from adapter.ndjson import snapshot_dir
    from adapter.pipeline import PASSED, AdapterConfig, prune_snapshots
    from lake.store import building

    lake_dir = tmp_path / "lake"
    nights = [f"2026-10-{d:02d}" for d in range(1, 6)]
    for s_ in nights:
        nd = snapshot_dir(lake_dir, s_)
        nd.mkdir(parents=True)
        (nd / PASSED).write_text("{}")
        (lake_dir / "db").mkdir(exist_ok=True)
        (lake_dir / "db" / f"{s_}.duckdb").write_bytes(b"")
    (lake_dir / "CURRENT").write_text(nights[-1])
    cfg = AdapterConfig(lake_dir=lake_dir, secrets_dir=tmp_path, mapping_path=tmp_path, site_id="T", keep_nightly=2,
                        keep_month_end_months=0)  # fmt: skip
    with building(lake_dir, nights[0]):  # a rebuild of the oldest night runs
        gone = prune_snapshots(cfg, date(2026, 10, 5))
        assert nights[0] not in gone and set(gone) == set(nights[1:3])
        assert (lake_dir / "db" / f"{nights[0]}.duckdb").exists() and snapshot_dir(lake_dir, nights[0]).exists()
    assert prune_snapshots(cfg, date(2026, 10, 5)) == [nights[0]]
    assert (lake_dir / "locks" / f"{nights[0]}.build.lock").exists()  # never deleted


def test_a_reader_after_a_swap_never_gets_the_old_copy(lake_dir: Path) -> None:
    """Review 7: DuckDB keeps one open copy of a file per path in a process; while a connection to the old file is
    open, a new connection to the same path after the swap read the OLD bytes. Readers now open a link per file
    identity."""
    lake = Lake(lake_dir, TZ)
    unrelated = lake.connect(NIGHT)  # an unheld console query still open in this worker
    try:
        _patients(lake_dir, NIGHT, 5)
        Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())  # no hold: allowed
        assert _count(lake, NIGHT) == 5  # a job that pins and holds now reads the new bytes from its first query
        assert unrelated.execute("SELECT count(*) FROM patient").fetchone() == (3,)  # its own copy, untouched
    finally:
        unrelated.close()
    links = sorted((lake_dir / "db" / ".open").glob(f"*/{NIGHT}.duckdb"))
    assert len(links) == 1 and links[0].stat().st_ino == lake.db_path(NIGHT).stat().st_ino  # old links removed
    assert lake.snapshots() == [NIGHT]


def test_the_reader_link_falls_back_to_the_file_without_hard_links(
    lake_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(*a: Any) -> None:
        raise PermissionError("no hard links here")

    shutil.rmtree(lake_dir / "db" / ".open", ignore_errors=True)
    monkeypatch.setattr(os, "link", no_links)
    db = Lake(lake_dir, TZ).db_path(NIGHT)
    assert store.reader_path(db) == db and _count(Lake(lake_dir, TZ), NIGHT) == 3


def test_verify_flags_a_missing_parquet_folder_and_a_rebuild_sweeps_leftovers(lake_dir: Path) -> None:
    """Review 9: a swap cut short can leave no Parquet folder; verify() said [] for it."""
    lake = Lake(lake_dir, TZ)
    shutil.rmtree(lake_dir / "parquet" / f"snapshot={NIGHT}")
    assert lake.verify(NIGHT) == [f"parquet/snapshot={NIGHT}: missing or empty"]
    stage = lake_dir / "parquet" / ".building"
    (stage / f"snapshot={NIGHT}").mkdir(parents=True)
    (stage / f"snapshot={NIGHT}" / "half.parquet").write_bytes(b"x")
    (stage / f"snapshot={NIGHT}.old").mkdir()
    (lake_dir / "db" / f"{NIGHT}.building").write_bytes(b"half")
    lake.rebuild(NIGHT, HashEmbedder())
    assert (
        lake.verify(NIGHT) == [] and not any(stage.iterdir()) and not (lake_dir / "db" / f"{NIGHT}.building").exists()
    )


def test_the_swap_does_not_hash_under_the_lake_lock(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review 5: every hold, release and prune waited for a second hash of the whole file inside the lock."""
    inside = {"n": 0, "hashed": 0}
    real_lock, real_sha = store.lake_lock, store._file_sha

    @contextlib.contextmanager
    def lock(d: Path) -> Iterator[None]:
        with real_lock(d):
            inside["n"] += 1
            try:
                yield
            finally:
                inside["n"] -= 1

    def sha(p: Path) -> str:
        if inside["n"] and p.suffix == ".duckdb":
            inside["hashed"] += 1
        return real_sha(p)

    monkeypatch.setattr(store, "lake_lock", lock)
    monkeypatch.setattr(store, "_file_sha", sha)
    _patients(lake_dir, NIGHT, 4)
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
    assert inside["hashed"] == 0 and Lake(lake_dir, TZ).verify(NIGHT) == []


def test_a_backup_skips_builds_in_progress_and_reader_links(tmp_path: Path) -> None:
    """Review 3: the Parquet stage (``parquet/.building/...``, ``snapshot=S.old``) was picked up by a backup."""
    from tools.trialbox import backup as bk

    lake = tmp_path / "lake"
    for rel in ("db/2026-10-04.duckdb", "db/2026-10-04.building", "parquet/snapshot=2026-10-04/patient.parquet",
                "parquet/.building/snapshot=2026-10-04/patient.parquet",
                "parquet/.building/snapshot=2026-10-04.old/patient.parquet",
                "db/.open/1-2-3/2026-10-04.duckdb"):  # fmt: skip
        (lake / rel).parent.mkdir(parents=True, exist_ok=True)
        (lake / rel).write_bytes(b"x")
    keep, left = bk.select_files("lake", lake)
    assert sorted(keep) == ["db/2026-10-04.duckdb", "parquet/snapshot=2026-10-04/patient.parquet"]
    assert left == {"lake snapshot being built": 3, "lake reader links (the same files as db/)": 1}


def test_a_rerun_holds_its_snapshot(lake_dir: Path) -> None:
    """Review 8: the re-run's lake had no ``hold``, so a publish could rebuild the snapshot under a running re-run."""
    from lake.client import LakeLocal
    from orchestrator import rerun
    from orchestrator.jobs import PinnedLake

    base = LakeLocal(lake_dir, HashEmbedder(), TZ)
    pinned = PinnedLake(rerun.PinnedLake(base, NIGHT), today=lambda: date(2026, 10, 5), max_age_days=7,
                        pinned=NIGHT, holder="01JOBX")  # fmt: skip
    assert pinned.pin() == NIGHT
    holds = Lake(lake_dir, TZ).holds()
    assert list(holds.values()) == [NIGHT] and next(iter(holds)).startswith("rerun.01JOBX.")
    _patients(lake_dir, NIGHT, 5)
    with pytest.raises(SnapshotHeld):
        Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
    pinned.release()
    assert Lake(lake_dir, TZ).holds() == {}
    assert rerun.PinnedLake(object(), NIGHT).release("x") is False
    rerun.PinnedLake(object(), NIGHT).hold(NIGHT, "x")  # a fake lake without holds: nothing to do


def test_the_service_marks_busy_and_the_adapter_reads_it(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review 4: busy (held, or already building) is one class in process and over HTTP, never refused data."""
    from adapter.pipeline import BUSY, REFUSALS
    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from lake.store import LakeBusy, SnapshotBuilding, building

    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    api = TestClient(lake_app.app)
    with building(lake_dir, NIGHT):
        r = api.post("/rebuild", json={"snapshot": NIGHT})
    assert r.status_code == 409 and r.headers["X-TB-Lake-Busy"] == "building" and "already building" in r.text
    lake.hold(NIGHT, "01J")
    r = api.post("/rebuild", json={"snapshot": NIGHT})
    assert r.status_code == 409 and r.headers["X-TB-Lake-Busy"] == "held"
    assert {c.__name__ for c in (LakeBusy, SnapshotHeld, SnapshotBuilding)} == set(BUSY)
    assert not set(BUSY) & set(REFUSALS)
