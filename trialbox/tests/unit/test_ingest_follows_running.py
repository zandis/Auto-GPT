"""NEW-PERF-2 / NEW-ARCH-1 (PERF-008, ARCH-002): on 409 the orchestrator follows the ingest that is running.

After an orchestrator restart during the night's ingest the INGEST job is queued again and asks the adapter to
start a run. The adapter is still running the first one and answers 409. Before: the job failed ("an ingest is
already running") while the adapter finished the night and moved ``CURRENT``: a published night with a failed job,
no stored report, no micro-batch for the new patients, a "failed" mail. Now the job follows the running run to its
end and takes its report."""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest

from tests.unit.test_polled_jobs import Clock, _poll, _report, _wait


def _adapter(monkeypatch: pytest.MonkeyPatch, go: threading.Event, passed: bool = True) -> Any:
    from adapter import app as adapter_app
    from fastapi.testclient import TestClient
    from tb_contracts import IngestReport

    def fake_run_ingest(*a: Any, **k: Any) -> IngestReport:
        assert go.wait(60)
        return IngestReport.model_validate({**_report(), "passed": passed})

    monkeypatch.setattr(adapter_app, "_runs", {})
    monkeypatch.setattr(adapter_app, "build_config", lambda: (None, "csv", "/data/in"))
    monkeypatch.setattr(adapter_app, "run_ingest", fake_run_ingest)
    return TestClient(adapter_app.app, base_url="http://adapter")


def test_a_requeued_ingest_job_follows_the_run_the_adapter_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.clients import AdapterHttp
    from tb_common.jobpoll import Poll
    from tb_contracts import IngestRequest

    go = threading.Event()
    api = _adapter(monkeypatch, go)
    first = api.post("/run", json={"source": "csv"}).json()  # the run the job started before the restart
    assert first["state"] == "running"
    ad = AdapterHttp("http://adapter", poll=Poll(interval=0.01, lost_after=30.0, sleep=time.sleep))
    ad.c.client = api
    got: dict[str, Any] = {}

    def job() -> None:  # the job queued again after the restart
        try:
            got["report"] = ad.run(IngestRequest(source="csv"))
        except Exception as exc:
            got["error"] = exc

    t = threading.Thread(target=job)
    t.start()
    time.sleep(0.2)
    assert t.is_alive() and "error" not in got  # it waits for the running night; before: StepFailed at once
    go.set()
    t.join(30)
    assert "error" not in got, got.get("error")
    assert got["report"].passed
    assert api.get(f"/run/{first['run']}").json()["state"] == "done"
    assert _wait(lambda: api.get("/run").json())["run"] == first["run"]  # no second run was started


def _client(handler: Any) -> Any:
    from orchestrator.clients import AdapterHttp

    ad = AdapterHttp("http://adapter", poll=_poll(Clock()))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    return ad


BUSY = {"detail": "an ingest is already running"}


def test_the_followed_runs_failure_is_the_jobs_failure() -> None:
    from orchestrator.clients import StepFailed
    from tb_contracts import IngestRequest

    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.path}")
        if req.method == "POST":
            return httpx.Response(409, json=BUSY, headers={"X-TB-Run": "r7"})
        return httpx.Response(200, json={"run": "r7", "state": "failed", "detail": "the source folder is empty"})

    with pytest.raises(StepFailed, match="the source folder is empty"):
        _client(handler).run(IngestRequest(source="csv"))
    assert seen == ["POST /run", "GET /run/r7"]


def test_the_run_the_409_names_is_followed_not_the_adapters_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F2: the adapter holds its lock before it registers the new run, so "the newest run" can be last
    night's, ended. The job follows the run the 409 names; it never takes an ended run's report as tonight's."""
    from tb_contracts import IngestRequest

    seen: list[str] = []
    polls = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.path}")
        if req.method == "POST":
            return httpx.Response(409, json=BUSY, headers={"X-TB-Run": "tonight"})
        if req.url.path == "/run":  # the newest registered run: last night's
            return httpx.Response(200, json={"run": "old", "state": "done",
                                             "report": {**_report(), "snapshot": "2026-10-03"}})  # fmt: skip
        polls[0] += 1
        if polls[0] < 3:
            return httpx.Response(200, json={"run": "tonight", "state": "running"})
        return httpx.Response(200, json={"run": "tonight", "state": "done", "report": _report()})

    notes: list[tuple[str, bool]] = []
    rep = _client(handler).run_followed(
        IngestRequest(source="csv"), lambda rid, followed: notes.append((rid, followed))
    )
    assert str(rep.snapshot) == _report()["snapshot"] and "GET /run" not in seen
    assert notes == [("tonight", True)]


def test_a_409_that_names_no_run_is_the_step_failure_it_was() -> None:
    """The adapter was still starting the run that holds it (no id yet), or an older adapter that names none:
    nothing to follow, the job fails as before and the administrator's retry starts or follows."""
    from orchestrator.clients import StepFailed
    from tb_contracts import IngestRequest

    for headers in ({}, {"X-TB-Run": ""}):
        with pytest.raises(StepFailed, match="already running"):
            _client(lambda req, h=headers: httpx.Response(409, json=BUSY, headers=h)).run(IngestRequest(source="csv"))


def test_a_first_read_that_gets_no_answer_does_not_fail_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F4: the read of the followed run is part of the poll, which bears silence up to its declared bound."""
    from tb_contracts import IngestRequest

    reads = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(409, json=BUSY, headers={"X-TB-Run": "r7"})
        reads[0] += 1
        if reads[0] < 3:
            return httpx.Response(503, json={"detail": "starting"})
        return httpx.Response(200, json={"run": "r7", "state": "done", "report": _report()})

    assert _client(handler).run(IngestRequest(source="csv")).passed and reads[0] == 3


def test_another_refusal_is_not_followed() -> None:
    from orchestrator.clients import StepFailed
    from tb_contracts import IngestRequest

    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.method)
        return httpx.Response(400, json={"detail": "path required when overriding the source type"})

    with pytest.raises(StepFailed):
        _client(handler).run(IngestRequest(source="csv"))
    assert asked == ["POST"]


# ------------------------------------------------------------------------------------------- the job (review F1, F3)
class _Box:
    """A real orchestrator and job store with the real INGEST scenario over the real adapter app; the steps that
    follow an ingest are counted."""

    def __init__(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, go: threading.Event) -> None:
        from pathlib import Path

        from orchestrator import derive, scheduler
        from orchestrator.clients import AdapterHttp
        from orchestrator.core import Orchestrator, Services
        from orchestrator.db import JobDB
        from orchestrator.scenarios import admin
        from tb_common.audit import AuditLog
        from tb_common.config import Config, load_env, load_settings
        from tb_common.jobpoll import Poll
        from tb_common.objstore import FsStore

        root = Path(__file__).resolve().parents[2]
        self.api = _adapter(monkeypatch, go)
        ad = AdapterHttp("http://adapter", poll=Poll(interval=0.01, lost_after=30.0, sleep=time.sleep))
        ad.c.client = self.api
        self.followups: list[str] = []
        monkeypatch.setattr(derive, "after_ingest", lambda orch, snap: self.followups.append("derive"))

        def screen(orch: Any, timed: bool = False) -> list[str]:
            self.followups.append("screen")
            return []

        monkeypatch.setattr(scheduler, "after_ingest", screen)
        monkeypatch.setattr(admin, "twins_after_ingest", lambda ctx, snap: self.followups.append("twins"))
        cfg = Config(env=load_env(dotenv=tmp_path / "x.env", environ={}),
                     settings=load_settings(root / "deploy/settings.example.yaml"))  # fmt: skip
        self.orch = Orchestrator(
            cfg, JobDB(), FsStore(tmp_path / "obj"), AuditLog(tmp_path / "audit"),
            Services(lake=None, parser=None, compiler=None, mail=None, adapter=ad),  # type: ignore[arg-type]
            {"INGEST": admin.ingest}, tmp_path / "rulesets", tmp_path, workers=0, async_notify=False,
        )  # fmt: skip

    def job(self, **options: str) -> str:
        from tb_contracts import JobCreate

        return self.orch.create(JobCreate(type="INGEST", requested_by="scheduler", options=options or None)).job_id

    def run_all(self, ids: list[str], go: threading.Event) -> list[Any]:
        threads = [threading.Thread(target=self.orch.run, args=(i,)) for i in ids]
        for t in threads:
            t.start()
            time.sleep(0.3)  # the first job's run is registered before the second asks
        go.set()
        for t in threads:
            t.join(60)
        return [self.orch.db.get(i) for i in ids]


def test_two_ingest_jobs_at_once_run_the_follow_up_steps_once(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F1: an administrator's retry at 01:58 and the timer's job at 02:00. The second follows the first
    one's run; both end done with the night's report, and the derive batch, the screening that follows and the
    twin build run once, in the job that started the run."""
    go = threading.Event()
    box = _Box(tmp_path, monkeypatch, go)
    first, second = box.job(), box.job(timer="1")
    a, b = box.run_all([first, second], go)
    assert (a.state, b.state) == ("done", "done"), (a.error, b.error)
    assert sorted(box.followups) == ["derive", "screen", "twins"]  # once, not twice
    assert (a.options or {})["adapter_run"] == (b.options or {})["adapter_run"]
    assert (b.options or {}).get("followed") == "1" and "followed" not in (a.options or {})
    assert a.snapshot_date == b.snapshot_date is not None


def test_a_job_queued_again_after_a_restart_follows_its_own_run_and_runs_the_steps(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the card is for: the job started the run, the orchestrator restarted, the job is queued again and
    follows the run it started. Nobody else runs the steps that follow: this job does."""
    go = threading.Event()
    box = _Box(tmp_path, monkeypatch, go)
    started = box.api.post("/run", json={"source": "csv"}).json()["run"]  # what the job started before the restart
    job = box.job(adapter_run=started, since="2026-10-01")
    (done,) = box.run_all([job], go)
    assert done.state == "done", done.error
    assert sorted(box.followups) == ["derive", "screen", "twins"]


def test_a_job_whose_own_request_did_not_run_does_not_end_done(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F3: a job that asked for a back-fill (``since``) and followed another caller's run has not had its
    request run: it fails with words that say so, and starts no follow-up step of its own."""
    go = threading.Event()
    box = _Box(tmp_path, monkeypatch, go)
    box.api.post("/run", json={"source": "csv"})  # a person's ingest is running
    job = box.job(since="2020-01-01")
    (ended,) = box.run_all([job], go)
    assert ended.state == "failed" and "since" in ended.error.message and "again" in ended.error.message
    assert box.followups == []
