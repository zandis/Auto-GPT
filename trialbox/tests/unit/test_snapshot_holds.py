"""Held snapshots and the batched site publish (T-305b, D-403; FR-REP-02, MR-183).

A running job holds the snapshot it pinned (T-305a): the lake refuses to rebuild it under the job, the adapter's
pruning keeps it, and the site's publish on ``main`` waits for the job and goes as one batch afterwards. Synthetic
patients only; the clock is frozen."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import PASSED, AdapterConfig, prune_snapshots
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import HOLD_TTL_SECONDS, Lake, SnapshotHeld, held_snapshots
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from sitesetup.service import SiteSetup
from tb_common.audit import AuditLog
from tb_common.config import Config, ConfigError, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate

ROOT = Path(__file__).resolve().parents[2]
NIGHT = "2026-10-04"
TZ = "Asia/Taipei"


def _night(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    pats = [{"resourceType": "Patient", "id": f"syn-{i:03d}", "gender": "female"} for i in range(n)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")
    Lake(lake_dir, TZ).rebuild(snap, HashEmbedder())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ the lake


def test_a_held_snapshot_is_not_rebuilt_under_its_job(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    db = lake.db_path(NIGHT)
    before = _sha(db)
    lake.hold(NIGHT, "01JOBA")
    assert lake.holds() == {"01JOBA": NIGHT}
    (lake_dir / "ndjson" / NIGHT / "Patient.ndjson").write_text("", encoding="utf-8")  # a publish would change it
    with pytest.raises(SnapshotHeld, match="running job"):
        lake.rebuild(NIGHT, HashEmbedder(), allow_empty=True)
    assert _sha(db) == before and lake.current() == NIGHT  # nothing written
    assert lake.release("01JOBA") and not lake.release("01JOBA")
    lake.rebuild(NIGHT, HashEmbedder(), allow_empty=True)  # released: the publish goes
    assert _sha(db) != before
    with pytest.raises(ValueError):
        lake.hold(NIGHT, "../etc")


def test_an_expired_hold_protects_nothing(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 1)
    Lake(lake_dir, TZ).hold(NIGHT, "01DEAD")
    f = lake_dir / "holds" / "01DEAD.json"
    body = json.loads(f.read_text())
    body["at"] = time.time() - HOLD_TTL_SECONDS - 60  # a job that died without releasing
    f.write_text(json.dumps(body))
    (lake_dir / "holds" / "junk.json").write_text("not json")
    assert held_snapshots(lake_dir) == {}
    Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())


def test_pruning_never_removes_a_held_snapshot(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    nights = [f"2026-10-{d:02d}" for d in range(1, 8)]
    for s in nights:
        nd = snapshot_dir(lake_dir, s)
        nd.mkdir(parents=True)
        (nd / PASSED).write_text("{}")
        (lake_dir / "db").mkdir(exist_ok=True)
        (lake_dir / "db" / f"{s}.duckdb").write_bytes(b"")
    (lake_dir / "CURRENT").write_text(nights[-1])
    Lake(lake_dir, TZ).hold(nights[0], "01LONG")  # a SCREEN still reading the first night
    cfg = AdapterConfig(lake_dir=lake_dir, secrets_dir=tmp_path, mapping_path=tmp_path, site_id="T", keep_nightly=3,
                        keep_month_end_months=0)  # fmt: skip
    gone = prune_snapshots(cfg, date(2026, 10, 7))
    assert nights[0] not in gone and set(gone) == set(nights[1:4])
    assert (lake_dir / "db" / f"{nights[0]}.duckdb").exists() and snapshot_dir(lake_dir, nights[0]).exists()
    Lake(lake_dir, TZ).release("01LONG")
    assert prune_snapshots(cfg, date(2026, 10, 7)) == [nights[0]]


# ------------------------------------------------------------------ the job holds and releases


class _Mail:
    def send(self, req: Any) -> Any:
        from tb_contracts import SendResult

        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=False)


def _orch(tmp_path: Path, scenario: Any, lake: Any) -> Orchestrator:
    cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                 settings=load_settings(ROOT / "deploy/settings.example.yaml"))  # fmt: skip
    services = Services(lake=lake, parser=None, compiler=None, mail=_Mail())  # type: ignore[arg-type]
    return Orchestrator(cfg, JobDB(), FsStore(tmp_path / "obj"), AuditLog(tmp_path / "audit"), services,
                        {"FEAS": scenario}, tmp_path / "rulesets", tmp_path, today=lambda: date(2026, 10, 5),
                        workers=0, async_notify=False)  # fmt: skip


def test_a_publish_during_a_run_leaves_the_runs_snapshot_untouched(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    db = Lake(lake_dir, TZ).db_path(NIGHT)
    before = _sha(db)
    seen: dict[str, Any] = {}

    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        lake = ctx.services.lake
        seen["n1"] = lake.query("SELECT count(*) AS n FROM patient").to_pylist()[0]["n"]
        seen["holds"] = Lake(lake_dir, TZ).holds()
        # the site publishes on main (same snapshot id) while the job runs. T-724 (D-490): the job pinned a
        # generation, so the publish is not refused any more: it makes the next generation beside the job's
        seen["mine"] = Lake(lake_dir, TZ).db_path(f"{NIGHT}.g1")
        seen["mine_sha"] = _sha(seen["mine"])
        seen["published"] = Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder(), allow_empty=True).generation
        seen["n2"] = lake.query("SELECT count(*) AS n FROM patient").to_pylist()[0]["n"]
        seen["mine_after"] = _sha(seen["mine"])
        return Outcome(summary_md="ok")

    orch = _orch(tmp_path, scenario, LakeLocal(lake_dir, HashEmbedder(), TZ))
    after: list[dict[str, str]] = []
    orch.after_job.append(lambda: after.append(Lake(lake_dir, TZ).holds()))
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="scheduler"))
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None and got.state == "done", got
    assert seen["holds"] == {job.job_id: NIGHT} and seen["published"] == f"{NIGHT}.g2"
    # the run's bytes did not move: its generation's file is as it was (the date's own file is now generation 2)
    assert seen["n1"] == seen["n2"] == 3 and seen["mine_sha"] == seen["mine_after"] == before
    assert Lake(lake_dir, TZ).generation(NIGHT) == f"{NIGHT}.g2" and seen["mine"].exists()
    assert after == [{}] and Lake(lake_dir, TZ).holds() == {}  # released at the end, then the hooks ran


# ------------------------------------------------------------------ the batched site publish on main


class _Store:
    def __init__(self) -> None:
        self.facts_: list[dict[str, Any]] = []
        self.pub: dict[str, Any] | None = None

    def facts(self, ws: str, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return list(self.facts_)

    def mapping(self, ws: str) -> dict[Any, Any]:
        return {}

    def inputs(self, ws: str, kind: str) -> list[dict[str, Any]]:
        return []

    def published(self, ws: str) -> dict[str, Any] | None:
        return self.pub

    def set_published(self, ws: str, at: str, snapshot: str, digest: str, counts: dict[str, int]) -> None:
        self.pub = {"ws": ws, "at": at, "snapshot": snapshot, "digest": digest, "counts": counts}


class _Lake:
    def __init__(self) -> None:
        self.rebuilds: list[str] = []
        self.held: dict[str, str] = {}

    def snapshot(self) -> str:
        return NIGHT

    def put_site(self, res: Any) -> dict[str, int]:
        return {}

    def rebuild(self, snap: str) -> dict[str, Any]:
        if snap in self.held.values():
            raise SnapshotHeld("held by a running job")
        self.rebuilds.append(snap)
        return {}

    def holds(self) -> dict[str, str]:
        return dict(self.held)


def _fact(i: int) -> dict[str, Any]:
    return {"id": i, "pid": "p1", "domain": "condition", "term": "gout", "code": f"M10.{i}",
            "system": "http://hl7.org/fhir/sid/icd-10", "value": "", "unit": "", "day": "2026-10-01",
            "status": "coded", "local_code": "", "local_system": "", "quote": "", "input_id": 1}  # fmt: skip


def test_site_decisions_on_main_go_as_one_batch_after_the_running_job(tmp_path: Path) -> None:
    clock = [datetime(2026, 10, 5, 1, 0, tzinfo=UTC)]
    store, lake = _Store(), _Lake()
    svc = SiteSetup(store, tmp_path / "setup", lake, None, AuditLog(tmp_path / "audit"), lambda: clock[0],  # type: ignore[arg-type]
                    lambda: date(2026, 10, 5), lambda: b"k" * 32, publish_batch_seconds=300)  # fmt: skip
    store.facts_.append(_fact(1))
    assert svc.publish("main", "crc")["unchanged"] is False and lake.rebuilds == [NIGHT]  # the first one goes
    store.facts_.append(_fact(2))
    clock[0] += timedelta(seconds=30)
    out = svc.publish("main", "crc")  # a second tap inside the window waits
    assert out["pending"] and out["wait_seconds"] == 270 and lake.rebuilds == [NIGHT]
    store.facts_.append(_fact(3))
    assert svc.flush("main")["pending"] and lake.rebuilds == [NIGHT]
    clock[0] += timedelta(seconds=300)
    lake.held = {"01SCREEN": NIGHT}  # a SCREEN pinned the night meanwhile
    out = svc.publish("main", "steward", force=True)  # even "publish now" waits for the job
    assert out["pending"] and out["held_by_jobs"] == 1 and lake.rebuilds == [NIGHT]
    lake.held = {}
    assert svc.flush("main")["unchanged"] is False and lake.rebuilds == [NIGHT, NIGHT]  # both taps, one rebuild
    assert svc.flush("main")["unchanged"] is True  # nothing waits any more


def test_the_batch_window_is_a_declared_setting(tmp_path: Path) -> None:
    assert load_env(dotenv=tmp_path / "x.env", environ={}).site_publish_batch_seconds == 0
    env = load_env(dotenv=tmp_path / "x.env", environ={"TB_SITE_PUBLISH_BATCH_SECONDS": "300"})
    assert env.site_publish_batch_seconds == 300 and "TB_SITE_PUBLISH_BATCH_SECONDS" not in env.extra
    with pytest.raises(ConfigError, match="TB_SITE_PUBLISH_BATCH_SECONDS"):
        load_env(dotenv=tmp_path / "x.env", environ={"TB_SITE_PUBLISH_BATCH_SECONDS": "-5"})
    compose = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    assert 'TB_SITE_PUBLISH_BATCH_SECONDS: "${TB_SITE_PUBLISH_BATCH_SECONDS:-300}"' in compose


# ------------------------------------------------------------------ the lake service and its clients


def test_holds_through_the_lake_service_and_both_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from lake.client import LakeHttp

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 2)
    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    api = TestClient(lake_app.app)
    assert api.post("/holds", json={"snapshot": NIGHT}).status_code == 400
    assert api.post("/holds", json={"snapshot": NIGHT, "holder": "../x"}).status_code == 400
    assert api.post("/holds", json={"snapshot": "2020-01-01", "holder": "01J"}).status_code == 404
    http = LakeHttp("http://testserver")
    http.client = api
    http.hold(NIGHT, "01HTTP")
    assert http.holds() == {"01HTTP": NIGHT}
    r = api.post("/rebuild", json={"snapshot": NIGHT})
    assert r.status_code == 409 and "running job" in r.text  # the service refuses a held rebuild
    assert http.release("01HTTP") is True and http.release("01HTTP") is False
    assert http.snapshot() == NIGHT
    assert http.put_site({"Patient": []}) == {"Patient": 0}
    assert http.rebuild(NIGHT)["snapshot"] == NIGHT  # released: the service rebuilds it
    assert lake.release("../x") is False
    local = LakeLocal(lake_dir, HashEmbedder(), TZ)
    local.hold(NIGHT, "01LOCAL")
    assert local.holds() == {"01LOCAL": NIGHT} and local.release("01LOCAL") and local.holds() == {}


def test_a_rebuild_passes_the_nights_tombstones_to_the_omop_source(tmp_path: Path, monkeypatch: Any) -> None:
    import lake.store as store

    seen: dict[str, Any] = {}

    def rows(*a: Any, deleted: Any = None, **k: Any) -> Any:
        seen["deleted"] = deleted
        raise RuntimeError("stop")

    lake_dir = tmp_path / "lake"
    nd = lake_dir / "ndjson" / NIGHT
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "p"}) + "\n")
    (nd / "tombstones.json").write_text(json.dumps({"Condition": ["c1", "c2"]}))
    monkeypatch.setattr(store, "lake_rows", rows)
    with pytest.raises(RuntimeError, match="stop"):
        Lake(lake_dir, TZ).rebuild(NIGHT, HashEmbedder())
    assert seen["deleted"] == {"Condition": ["c1", "c2"]}
    (nd / "tombstones.json").write_text("not json")
    assert store._tombstones(nd) == {} and store._tombstones(tmp_path / "none") == {}
    (nd / "tombstones.json").write_text("[1]")
    assert store._tombstones(nd) == {}


def test_a_hold_that_lands_during_the_publish_defers_the_batch(tmp_path: Path) -> None:
    """A job pins the night between the check and the rebuild: the lake's refusal (in process, or the service's 409)
    turns the publish into a waiting batch; any other error is raised. A lake that cannot list holds counts none."""
    from sitesetup import service as svc_mod

    class Racing(_Lake):
        def __init__(self, exc: Exception) -> None:
            super().__init__()
            self.exc = exc

        def rebuild(self, snap: str) -> dict[str, Any]:
            raise self.exc

    class Resp:
        status_code = 409
        text = "lake snapshot 2026-10-04 is being read by a running job"

    class HttpError(Exception):
        response = Resp()

    for exc in (SnapshotHeld("held by a running job"), HttpError()):
        store = _Store()
        store.facts_.append(_fact(1))
        svc = SiteSetup(store, tmp_path / "setup", Racing(exc), None, AuditLog(tmp_path / "audit"),  # type: ignore[arg-type]
                        lambda: datetime(2026, 10, 5, tzinfo=UTC), lambda: date(2026, 10, 5), lambda: b"k" * 32)  # fmt: skip
        out = svc.publish("main", "crc")
        assert out["pending"] and out["held_by_jobs"] == 1 and out["snapshot"] is None and store.pub is None
    store = _Store()
    store.facts_.append(_fact(1))
    svc = SiteSetup(store, tmp_path / "setup", Racing(RuntimeError("disk full")), None,  # type: ignore[arg-type]
                    AuditLog(tmp_path / "audit"), lambda: datetime(2026, 10, 5, tzinfo=UTC), lambda: date(2026, 10, 5),
                    lambda: b"k" * 32)  # fmt: skip
    with pytest.raises(RuntimeError, match="disk full"):
        svc.publish("main", "crc")
    assert not svc_mod._held_refusal(ValueError("x"))

    class Blind:
        def holds(self) -> dict[str, str]:
            raise OSError("lake down")

    assert svc._held_by(Blind(), NIGHT) == 0 and svc._held_by(object(), NIGHT) == 0 and svc._held_by(Blind(), None) == 0
    svc.publish_batch_seconds = 300
    assert svc._batch_wait({"at": "not a time"}) == 0 and svc._batch_wait(None) == 0
