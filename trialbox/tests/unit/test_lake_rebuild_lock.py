"""The lake's rebuild and hold under one lock (T-722, D-462; lifecycle review 2026-11-12 F-1, scale review F-01).

A hold taken while a rebuild of the same snapshot runs must protect the bytes the job pinned: the rebuild checks the
holds again at the swap and is refused there. Two rebuilds of one snapshot never write ``<snapshot>.building`` at the
same time: the second is refused with "already building". The lock works across processes (the lake runs two
uvicorn workers). Synthetic patients only."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake import store
from lake.source import lake_rows as source_lake_rows
from lake.store import Lake, SnapshotHeld

ROOT = Path(__file__).resolve().parents[2]
NIGHT = "2026-10-04"
TZ = "Asia/Taipei"


def _patients(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
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

        def rebuild(self, snap: str) -> dict[str, Any]:
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


def test_pruning_removes_a_gone_snapshots_build_lock_unless_it_builds(tmp_path: Path) -> None:
    from lake.store import building, drop_build_lock

    lake_dir = tmp_path / "lake"
    with building(lake_dir, NIGHT):
        drop_build_lock(lake_dir, NIGHT)  # a rebuild of it runs: the file stays
        assert (lake_dir / "locks" / f"{NIGHT}.build.lock").exists()
    drop_build_lock(lake_dir, NIGHT)
    assert not (lake_dir / "locks" / f"{NIGHT}.build.lock").exists()
    drop_build_lock(lake_dir, NIGHT)  # nothing to drop
