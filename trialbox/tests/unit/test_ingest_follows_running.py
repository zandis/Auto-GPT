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
    assert len(api.get("/run").json()["run"]) and api.get(f"/run/{first['run']}").json()["state"] == "done"
    assert _wait(lambda: api.get("/run").json())["run"] == first["run"]  # no second run was started


def test_the_followed_runs_failure_is_the_jobs_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.clients import AdapterHttp, StepFailed
    from tb_contracts import IngestRequest

    clock = Clock()
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.path}")
        if req.method == "POST":
            return httpx.Response(409, json={"detail": "an ingest is already running"})
        if req.url.path == "/run":
            return httpx.Response(200, json={"run": "r7", "state": "running"})
        return httpx.Response(200, json={"run": "r7", "state": "failed", "detail": "the source folder is empty"})

    ad = AdapterHttp("http://adapter", poll=_poll(clock))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(StepFailed, match="the source folder is empty"):
        ad.run(IngestRequest(source="csv"))
    assert seen[:3] == ["POST /run", "GET /run", "GET /run/r7"]


@pytest.mark.parametrize("latest", [{"state": "none"}, None])
def test_a_409_with_no_run_to_follow_is_the_step_failure_it_was(latest: dict[str, Any] | None) -> None:
    """The adapter restarted between the 409 and the question (it knows no run), or cannot be asked: nothing to
    follow, the job fails as before and the administrator's retry starts a new run."""
    from orchestrator.clients import AdapterHttp, StepFailed
    from tb_contracts import IngestRequest

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(409, json={"detail": "an ingest is already running"})
        return httpx.Response(200, json=latest) if latest is not None else httpx.Response(503, json={"detail": "down"})

    ad = AdapterHttp("http://adapter", poll=_poll(Clock()))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(StepFailed, match="already running"):
        ad.run(IngestRequest(source="csv"))


def test_another_refusal_is_not_followed() -> None:
    from orchestrator.clients import AdapterHttp, StepFailed
    from tb_contracts import IngestRequest

    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.method)
        return httpx.Response(400, json={"detail": "path required when overriding the source type"})

    ad = AdapterHttp("http://adapter", poll=_poll(Clock()))
    ad.c.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(StepFailed):
        ad.run(IngestRequest(source="csv"))
    assert asked == ["POST"]
