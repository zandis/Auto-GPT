"""The lake rebuild and the nightly ingest as polled jobs (T-690, D-472; scale review 2026-11-11 F-01, F-08).

F-01: the site publish timed a whole-hospital rebuild against its HTTP client's 330 s and, on the timeout, published
again on the next tick: a new rebuild every few minutes, the publish never recorded. F-08: the adapter timed the
rebuild against 7,200 s and the orchestrator the whole night likewise: a longer rebuild failed the night while the
lake finished it and moved CURRENT anyway. Both now start a job (202) and poll its state; a poll has an interval and
a bound on silence (declared settings), never a bound on the work (OD-10). Synthetic patients only; time is a fake
clock, so a 7,300 s rebuild takes no time."""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake

NIGHT = "2026-10-04"
TZ = "Asia/Taipei"


ROOT = Path(__file__).resolve().parents[2]
DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "deleted"]


def night_with(tmp_path: Path, rebuild: Callable[[str, Path], Any]) -> Any:
    """One small synthetic CSV night through the adapter's pipeline, with ``rebuild`` as its lake step."""
    import csv

    from adapter.pipeline import AdapterConfig, run_ingest

    src = tmp_path / "csv"
    src.mkdir()
    with (src / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DIAG)
        w.writeheader()
        w.writerow({"diag_no": "D1", "enc_no": "E1", "mrn": "10000001", "icd10": "E11.9", "diag_date": "2026-09-01",
                    "recorded_date": "2026-09-01", "status": "A", "deleted": ""})  # fmt: skip
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, site_id="T", audit_dir=tmp_path / "audit",
                        mapping_path=ROOT / "services/adapter/mapping/tw_core/demo_his.yaml", rebuild=rebuild)  # fmt: skip
    return run_ingest(cfg, "csv", str(src), snapshot=NIGHT, load_fhir=False, validate=False)


class Clock:
    """A fake clock: ``sleep`` moves it on; nothing waits."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def _poll(clock: Clock, interval: float = 5.0, lost: float = 900.0) -> Any:
    from tb_common.jobpoll import Poll

    return Poll(interval=interval, lost_after=lost, sleep=clock.sleep, clock=clock)


# ------------------------------------------------------------------ F-01: the site publish against a slow lake


class _Store:
    def __init__(self, facts: bool = True) -> None:
        self.pub: dict[str, Any] | None = None
        self.has_facts = facts

    def facts(self, ws: str, *a: Any, **k: Any) -> list[dict[str, Any]]:
        if not self.has_facts:
            return []
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
        self.pub = {"snapshot": snapshot, "digest": digest, "counts": counts, "at": at}


class SlowLake:
    """A lake whose rebuild takes ``seconds`` on the fake clock. Its blocking ``rebuild`` is what an HTTP client with
    a 330 s read limit sees (master before T-690); ``start_rebuild``/``rebuild_state`` is the polled job."""

    CLIENT_LIMIT = 330.0

    def __init__(self, clock: Clock, seconds: float) -> None:
        self.clock, self.seconds = clock, seconds
        self.rebuilds = 0
        self.job: dict[str, Any] | None = None
        self.current: str | None = NIGHT

    def snapshot(self) -> str | None:
        return self.current

    def put_site(self, res: Any) -> dict[str, int]:
        return {k: len(v) for k, v in res.items()}

    def holds(self) -> dict[str, str]:
        return {}

    def _running(self) -> bool:
        return self.job is not None and self.clock() < self.job["started"] + self.seconds

    def rebuild(self, snap: str, allow_empty: bool = False) -> dict[str, Any]:
        if self._running():
            raise RuntimeError("lake snapshot is already building")
        self.rebuilds += 1
        self.job = {"job": f"j{self.rebuilds}", "snapshot": snap, "started": self.clock()}
        raise httpx.ReadTimeout("timed out")  # the client gives up at 330 s; the lake carries on

    def start_rebuild(self, snap: str, allow_empty: bool = False) -> dict[str, Any]:
        if self._running():
            raise RuntimeError("lake snapshot is already building")
        self.rebuilds += 1
        self.job = {"job": f"j{self.rebuilds}", "snapshot": snap, "started": self.clock()}
        return self.rebuild_state(snap)

    def rebuild_state(self, snap: str) -> dict[str, Any]:
        if self.job is None or self.job["snapshot"] != snap:
            return {"snapshot": snap, "state": "none"}
        state = "running" if self._running() else "done"
        result = {"snapshot": snap, "tables": {"condition": 1}, "chunks": 0, "embedded_new": 0,
                  "seconds": self.seconds, "promoted": True}  # fmt: skip
        return {**self.job, "state": state, "result": result if state == "done" else None}


def _setup(tmp_path: Path, lake: Any, clock: Clock, store: _Store | None = None) -> tuple[Any, _Store]:
    from sitesetup.service import SiteSetup
    from tb_common.audit import AuditLog

    st = store or _Store()
    base = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)

    def now() -> datetime:
        from datetime import timedelta

        return base + timedelta(seconds=clock())

    svc = SiteSetup(st, tmp_path / "setup", lake, None, AuditLog(tmp_path / "audit"),  # type: ignore[arg-type]
                    now, lambda: date(2026, 10, 5), lambda: b"k" * 32)  # fmt: skip
    return svc, st


def _events(tmp_path: Path) -> list[str]:
    out = []
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        out += [json.loads(line)["event"] for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def test_a_publish_whose_rebuild_takes_400_s_rebuilds_once_and_is_recorded(tmp_path: Path) -> None:
    """The row's acceptance test: a lake stub whose rebuild takes 400 s; ``SiteSetup.flush`` twice gives one rebuild
    and a recorded publish."""
    clock = Clock()
    lake = SlowLake(clock, 400)
    svc, st = _setup(tmp_path, lake, clock)
    first = svc.flush("main")
    assert first["pending"] and first["building"] and st.pub is None
    clock.sleep(60)  # the scheduler's next tick, while the rebuild runs
    second = svc.flush("main")
    assert second["pending"] and second["building"]
    clock.sleep(400)
    third = svc.flush("main")  # the rebuild ended: the publish it carried is recorded, nothing rebuilt again
    assert lake.rebuilds == 1
    assert st.pub is not None and st.pub["snapshot"] == NIGHT and not third.get("pending")
    assert svc.flush("main")["unchanged"] and lake.rebuilds == 1
    ev = _events(tmp_path)
    assert ev.count("setup.publish_begin") == 1 and ev.count("setup.publish") == 1


def test_a_fresh_box_without_site_facts_starts_no_rebuild(tmp_path: Path) -> None:
    """F-01: a fresh box (nothing ever published, no site facts) rebuilt the whole lake on every tick."""
    clock = Clock()
    lake = SlowLake(clock, 400)
    svc, st = _setup(tmp_path, lake, clock, _Store(facts=False))
    for _ in range(3):
        out = svc.flush("main")
        clock.sleep(60)
    assert lake.rebuilds == 0 and st.pub is None and out["unchanged"] and out.get("empty")


def test_a_failed_publish_is_recorded_and_not_retried_every_minute(tmp_path: Path) -> None:
    clock = Clock()

    class Failing(SlowLake):
        def rebuild_state(self, snap: str) -> dict[str, Any]:
            out = super().rebuild_state(snap)
            if out["state"] == "done":
                return {**out, "state": "failed", "result": None, "detail": "OSError: disk full"}
            return out

    lake = Failing(clock, 30)
    svc, st = _setup(tmp_path, lake, clock)
    svc.flush("main")
    clock.sleep(60)
    out = svc.flush("main")
    assert out["failed"] and "disk full" in out["detail"] and st.pub is None
    clock.sleep(60)
    assert svc.flush("main")["failed"] and lake.rebuilds == 1  # the same facts are not rebuilt every minute
    svc.publish("main", "steward", force=True)  # a person presses Publish: tried again
    assert lake.rebuilds == 2
    assert "setup.publish_failed" in _events(tmp_path)


def test_a_publish_in_progress_survives_a_restart(tmp_path: Path) -> None:
    """The publish in progress is a record in the protected data folder, not a variable: a new service object (an
    orchestrator restart) follows the same rebuild instead of starting another."""
    clock = Clock()
    lake = SlowLake(clock, 400)
    svc, st = _setup(tmp_path, lake, clock)
    assert svc.flush("main")["building"]
    clock.sleep(120)
    again, _ = _setup(tmp_path, lake, clock, st)
    assert again.flush("main")["building"] and lake.rebuilds == 1
    clock.sleep(400)
    again.flush("main")
    assert st.pub is not None and lake.rebuilds == 1


# ------------------------------------------------------------------ the lake service's job


def _patients(lake_dir: Path, snap: str, n: int) -> None:
    nd = lake_dir / "ndjson" / snap
    nd.mkdir(parents=True, exist_ok=True)
    pats = [{"resourceType": "Patient", "id": f"syn-{i:03d}", "gender": "female"} for i in range(n)]
    (nd / "Patient.ndjson").write_text("".join(json.dumps(p) + "\n" for p in pats), encoding="utf-8")


@pytest.fixture
def lake_dir(tmp_path: Path) -> Iterator[Path]:
    d = tmp_path / "lake"
    _patients(d, NIGHT, 3)
    Lake(d, TZ).rebuild(NIGHT, HashEmbedder())
    yield d


def _paused(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    from lake import store
    from lake.source import lake_rows

    inside, go = threading.Event(), threading.Event()

    def rows(*a: Any, **k: Any) -> Any:
        inside.set()
        assert go.wait(60), "the test never let the rebuild go"
        return lake_rows(*a, **k)

    monkeypatch.setattr(store, "lake_rows", rows)
    return inside, go


def _wait(read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    import time

    for _ in range(600):
        st = read()
        if st["state"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("the rebuild never ended")


def test_the_lake_answers_202_and_reports_the_state(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    monkeypatch.setattr(lake_app, "embedder", HashEmbedder)
    api = TestClient(lake_app.app)
    _patients(lake_dir, NIGHT, 5)
    inside, go = _paused(monkeypatch)
    r = api.post("/rebuild", json={"snapshot": NIGHT})
    assert r.status_code == 202 and r.json()["state"] == "running" and r.headers["Location"] == f"/rebuild/{NIGHT}"
    job = r.json()["job"]
    assert inside.wait(60)
    assert api.get(f"/rebuild/{NIGHT}").json()["state"] == "running"
    again = api.post("/rebuild", json={"snapshot": NIGHT})  # a second caller: one rebuild per snapshot
    assert again.status_code == 409 and again.headers["X-TB-Lake-Busy"] == "building"
    go.set()
    st = _wait(lambda: api.get(f"/rebuild/{NIGHT}").json())
    assert st["state"] == "done" and st["job"] == job and st["result"]["tables"]["patient"] == 5
    assert lake.current() == NIGHT
    assert api.get("/rebuild/2026-01-01").json()["state"] == "none"
    assert api.get("/rebuild/..%2Fx").status_code in (400, 404)


def test_a_refusal_found_during_the_build_is_a_state(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal that needs the records read (no patient record) happens in the job and is reported as ``refused``;
    a missing folder is refused at the start (409), as before."""
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    monkeypatch.setattr(lake_app, "embedder", HashEmbedder)
    api = TestClient(lake_app.app)
    assert api.post("/rebuild", json={"snapshot": "2026-10-09"}).status_code == 409  # no NDJSON folder
    nd = lake_dir / "ndjson" / "2026-10-06"
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text("\n")
    assert api.post("/rebuild", json={"snapshot": "2026-10-06"}).status_code == 202
    st = _wait(lambda: api.get("/rebuild/2026-10-06").json())
    assert st["state"] == "refused" and "holds no patient or clinical record" in st["detail"]
    assert lake.current() == NIGHT

    class OmopError(Exception):  # the OMOP store's refusal found in the build (D-271): refused, not failed
        pass

    def omop_refuses(*a: Any, **k: Any) -> Any:
        raise OmopError("OMOP feed batch 2026-10-04 would tombstone person: 3 of 3")

    monkeypatch.setattr(lake, "_rebuild", omop_refuses)
    assert api.post("/rebuild", json={"snapshot": NIGHT}).status_code == 202
    st = _wait(lambda: api.get(f"/rebuild/{NIGHT}").json())
    assert st["state"] == "refused" and "3 of 3" in st["detail"]


def test_a_rebuild_whose_process_died_reads_interrupted(lake_dir: Path) -> None:
    from lake.store import write_rebuild_job

    write_rebuild_job(lake_dir, {"job": "dead", "snapshot": NIGHT, "state": "running", "started": 1.0})
    st = Lake(lake_dir, TZ).rebuild_state(NIGHT)
    assert st["state"] == "interrupted" and st["job"] == "dead"


def test_lake_http_polls_a_rebuild_to_its_end(lake_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from lake.client import LakeHttp

    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    monkeypatch.setattr(lake_app, "embedder", HashEmbedder)
    http = LakeHttp("http://testserver")
    http.client = TestClient(lake_app.app)
    out = http.rebuild(NIGHT)
    assert out["snapshot"] == NIGHT and out["tables"]["patient"] == 3


# ------------------------------------------------------------------ F-08: the adapter's rebuild and the night


def _lake_transport(clock: Clock, seconds: float, calls: list[str]) -> httpx.MockTransport:
    return httpx.MockTransport(_lake_handler(clock, seconds, calls))


def _lake_handler(clock: Clock, seconds: float, calls: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    started: dict[str, float] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.method == "POST" and req.url.path == "/rebuild":
            snap = json.loads(req.content)["snapshot"]
            started[snap] = clock()
            return httpx.Response(202, json={"job": "j1", "snapshot": snap, "state": "running"})
        snap = req.url.path.rsplit("/", 1)[1]
        if clock() < started[snap] + seconds:
            return httpx.Response(200, json={"job": "j1", "snapshot": snap, "state": "running"})
        res = {"snapshot": snap, "tables": {"patient": 2}, "chunks": 0, "embedded_new": 0, "seconds": seconds}
        return httpx.Response(200, json={"job": "j1", "snapshot": snap, "state": "done", "result": res})

    return handler


def test_a_rebuild_of_7300_s_does_not_fail_the_night(tmp_path: Path) -> None:
    """The row's acceptance test: a rebuild of 7,300 s (time-mocked): the night is not failed."""
    from adapter.cli import http_rebuild
    from lake.client import LakeHttp

    clock, calls = Clock(), list[str]()
    lake = LakeHttp("http://lake", poll=_poll(clock))
    lake.client = httpx.Client(transport=_lake_transport(clock, 7300, calls), base_url="http://lake")
    res = http_rebuild(lake, NIGHT)
    assert res.snapshot == NIGHT and res.tables["patient"] == 2 and clock() >= 7300
    assert calls.count("POST /rebuild") == 1  # started once, then only read
    # the whole night with that rebuild: passed (the in-process ingest with the HTTP rebuild as its lake step)
    clock2, calls2 = Clock(), list[str]()
    lake2 = LakeHttp("http://lake", poll=_poll(clock2))
    lake2.client = httpx.Client(transport=_lake_transport(clock2, 7300, calls2), base_url="http://lake")
    rep = night_with(tmp_path, lambda snap, nd: http_rebuild(lake2, snap))
    assert rep.passed and not rep.errors and clock2() >= 7300


def test_a_busy_or_refused_rebuild_keeps_its_meaning_for_the_night() -> None:
    from adapter.cli import http_rebuild
    from adapter.pipeline import RebuildRefused
    from lake.client import LakeHttp
    from lake.store import LakeBusy

    def lake_for(final: dict[str, Any], start: httpx.Response | None = None) -> LakeHttp:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "POST":
                return start or httpx.Response(202, json={"job": "j", "snapshot": NIGHT, "state": "running"})
            return httpx.Response(200, json={"job": "j", "snapshot": NIGHT, **final})

        lake = LakeHttp("http://lake", poll=_poll(Clock()))
        lake.client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://lake")
        return lake

    with pytest.raises(LakeBusy):  # held at the swap: the night is run again, never held
        http_rebuild(lake_for({"state": "busy", "busy": "held", "detail": "held"}), NIGHT)
    with pytest.raises(LakeBusy):  # already building, at the start
        busy = httpx.Response(409, json={"detail": "already building"}, headers={"X-TB-Lake-Busy": "building"})
        http_rebuild(lake_for({}, busy), NIGHT)
    with pytest.raises(RebuildRefused, match="would drop"):
        http_rebuild(lake_for({"state": "refused", "detail": "would drop Patient"}), NIGHT)
    with pytest.raises(RuntimeError, match="interrupted"):
        http_rebuild(lake_for({"state": "interrupted", "detail": "its process ended"}), NIGHT)


def test_a_poll_is_bounded_by_silence_not_by_the_work() -> None:
    from tb_common.jobpoll import JobLost, Poll

    clock = Clock()
    seen = []

    def silent() -> dict[str, Any]:
        seen.append(clock())
        raise httpx.ConnectError("refused")

    with pytest.raises(JobLost, match="no answer"):
        Poll(interval=5, lost_after=900, sleep=clock.sleep, clock=clock).until_done(silent, "rebuild")
    assert 900 < clock() <= 900 + 5 and max(b - a for a, b in itertools.pairwise(seen)) <= 5 + 1e-6
    clock2 = Clock()
    n = {"reads": 0}

    def long_but_alive() -> dict[str, Any]:  # 30 hours of "running" with answers: never cut
        n["reads"] += 1
        return {"state": "running" if clock2() < 30 * 3600 else "done"}

    assert (
        Poll(interval=5, lost_after=900, sleep=clock2.sleep, clock=clock2).until_done(long_but_alive, "x")["state"]
        == "done"
    )
    with pytest.raises(JobLost, match="none"):
        Poll(interval=5, lost_after=900, sleep=clock.sleep, clock=clock).until_done(lambda: {"state": "none"}, "x")


def test_the_poll_settings_are_declared_and_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common.config import DECLARED, ConfigError
    from tb_common.jobpoll import lost_seconds, poll_seconds

    assert {"TB_JOB_POLL_SECONDS", "TB_JOB_LOST_SECONDS"} <= set(DECLARED)
    monkeypatch.setenv("TB_JOB_POLL_SECONDS", "2")
    monkeypatch.setenv("TB_JOB_LOST_SECONDS", "60")
    assert poll_seconds() == 2 and lost_seconds() == 60
    monkeypatch.setenv("TB_JOB_LOST_SECONDS", "1")  # shorter than one interval: refused
    with pytest.raises(ConfigError):
        lost_seconds()


# ------------------------------------------------------------------ /run: the adapter's job and its callers


def _report() -> dict[str, Any]:
    return {"snapshot": NIGHT, "source": "csv", "started_at": "2026-10-04T18:00:00+00:00", "counts": {"Patient": 2},
            "validation": {"sampled": 2, "errors": 0, "error_pct": 0.0, "validator": "stub"}, "passed": True}  # fmt: skip


def test_the_adapter_answers_202_and_the_orchestrator_polls_the_night(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient
    from orchestrator.clients import AdapterHttp
    from tb_contracts import IngestReport, IngestRequest

    go = threading.Event()

    def fake_run_ingest(*a: Any, **k: Any) -> IngestReport:
        assert go.wait(60)
        return IngestReport.model_validate(_report())

    monkeypatch.setattr(adapter_app, "build_config", lambda: (None, "csv", "/data/in"))
    monkeypatch.setattr(adapter_app, "run_ingest", fake_run_ingest)
    api = TestClient(adapter_app.app)
    r = api.post("/run", json={"source": "csv"})
    assert r.status_code == 202 and r.json()["state"] == "running"
    rid = r.json()["run"]
    assert api.post("/run", json={"source": "csv"}).status_code == 409  # one ingest at a time
    assert api.get(f"/run/{rid}").json()["state"] == "running" and api.get("/run").json()["run"] == rid
    go.set()
    st = _wait(lambda: api.get(f"/run/{rid}").json())
    assert st["state"] == "done" and st["report"]["passed"] is True
    assert api.get("/run/nope").status_code == 404

    # the orchestrator's client: start, then poll on the fake clock while the night takes 3 hours
    clock = Clock()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json={"run": "r1", "state": "running"})
        if clock() < 3 * 3600:
            return httpx.Response(200, json={"run": "r1", "state": "running"})
        rep = _report()
        return httpx.Response(200, json={"run": "r1", "state": "done", "report": rep})

    ad = AdapterHttp("http://adapter", poll=_poll(clock))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    rep = ad.run(IngestRequest(source="csv"))
    assert rep.passed and clock() >= 3 * 3600


def test_a_lost_or_refused_night_is_a_plain_step_failure() -> None:
    from orchestrator.clients import AdapterHttp, StepFailed
    from tb_contracts import IngestRequest

    def client(get: httpx.Response) -> AdapterHttp:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json={"run": "r1", "state": "running"}) if req.method == "POST" else get

        ad = AdapterHttp("http://adapter", poll=_poll(Clock()))
        ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
        return ad

    with pytest.raises(StepFailed, match="restarted"):
        client(httpx.Response(404, json={"detail": "unknown run"})).run(IngestRequest(source="csv"))
    with pytest.raises(StepFailed, match="site key"):
        refused = {"run": "r1", "state": "refused", "detail": "night refused: the site key changed"}
        client(httpx.Response(200, json=refused)).run(IngestRequest(source="csv"))


def test_the_console_starts_the_ingest_and_does_not_wait(tmp_path: Path) -> None:
    from console.backend import HttpBackend
    from tb_common.config import load

    cfg = load()
    bk = HttpBackend.__new__(HttpBackend)
    bk.cfg = cfg
    from tb_common.http import ServiceClient

    bk.adapter = ServiceClient("http://adapter", "adapter", timeout=60, retries=0, idempotent=False)
    bk.adapter.client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(202, json={"run": "r9", "state": "running"}))
    )
    assert bk.ingest() == {"run": "r9", "state": "running"}
    assert bk.adapter.client.timeout.read is not None and bk.adapter.client.timeout.read <= 60


def test_the_minute_tick_follows_a_publish_with_batching_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tick that records a publish in progress runs batching on or off (T-690); a failing flush is logged only."""
    from orchestrator import app as orch_app

    calls: list[str] = []

    class Svc:
        def flush(self, ws: str) -> None:
            calls.append(ws)
            if len(calls) > 1:
                raise RuntimeError("lake away")

    monkeypatch.setattr(orch_app, "setup_of", lambda o: Svc())
    orch_app._flush_main(None, object())  # type: ignore[arg-type]
    orch_app._flush_main(Svc())  # the after-job hook; an error is logged, never raised
    assert calls == ["main", "main"]


def test_the_publish_over_the_real_lake_service_is_recorded_with_one_rebuild(
    lake_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-01 end to end (the shape of T-687's scale gate): the product's ``LakeHttp`` against the lake service, the
    publish ticking while the rebuild runs: one rebuild started, the publish recorded once it ends."""
    import time

    from fastapi.testclient import TestClient
    from lake import app as lake_app
    from lake.client import LakeHttp

    lake = Lake(lake_dir, TZ)
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    monkeypatch.setattr(lake_app, "embedder", HashEmbedder)
    starts: list[str] = []

    class Counting(LakeHttp):
        def start_rebuild(self, snapshot: str, allow_empty: bool = False, promote: bool = True) -> dict[str, Any]:
            starts.append(snapshot)
            return super().start_rebuild(snapshot, allow_empty, promote)

    http = Counting("http://testserver")
    http.client = TestClient(lake_app.app)
    inside, go = _paused(monkeypatch)
    svc, st = _setup(tmp_path, http, Clock())
    ticks = [svc.flush("main")]
    assert inside.wait(60)
    ticks += [svc.flush("main") for _ in range(3)]  # ticks while the build runs: followed, never restarted
    assert all(t.get("building") for t in ticks) and st.pub is None
    go.set()
    for _ in range(600):
        out = svc.flush("main")
        if st.pub is not None:
            break
        time.sleep(0.05)
    assert st.pub is not None and st.pub["snapshot"] == NIGHT and not out.get("pending")
    assert starts == [NIGHT] and lake.rebuild_state(NIGHT)["state"] == "done"


def test_the_adapters_lake_step_starts_and_follows_on_one_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter's lake step (``build_config``'s HTTP mode) starts and reads the job through the same module-level
    ``httpx`` calls, so a fake of that seam covers the whole step (the start and every state read)."""
    from adapter.cli import HttpLakeStep, http_rebuild

    clock, calls = Clock(), list[str]()
    handler = _lake_handler(clock, 7300, calls)

    def call(method: str) -> Callable[..., httpx.Response]:
        def send(url: str, **k: Any) -> httpx.Response:
            body = json.dumps(k["json"]).encode() if "json" in k else b""
            req = httpx.Request(method, url, content=body)
            resp = handler(req)
            resp.request = req
            return resp

        return send

    monkeypatch.setattr(httpx, "post", call("POST"))
    monkeypatch.setattr(httpx, "get", call("GET"))
    res = http_rebuild(HttpLakeStep("http://lake", poll=_poll(clock)), NIGHT)
    assert res.snapshot == NIGHT and clock() >= 7300 and calls.count("POST /rebuild") == 1
