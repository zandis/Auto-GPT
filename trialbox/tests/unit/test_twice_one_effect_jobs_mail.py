"""V-11: twice has one effect (the mail gateway and the job queue).

* A retried mail: the gateway's own ``deliver`` and ``drain`` (what ``POST /send`` and the outbox loop call) with a
  stand-in MTA that fails before accepting (nothing left) or after accepting (the answer is lost: "uncertain").
  How many copies can the recipient get? An uncertain mail waits for a person (D-401, T-108c).
* A job re-queued: the real orchestrator and job store of ``test_t726_night_runner``'s box. The timer fires twice
  for one night; the administrator's retry (D-474) is sent twice, also from two threads at once; a done job is run
  again; the worker dies in the middle of a job and a new process starts.

Counts go to ``twice.json`` when ``TB_TWICE_OUT`` names a folder. All data is synthetic."""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mail_gateway.gateway import Gateway
from orchestrator import night
from orchestrator.core import Ctx, NotRetryable, Outcome
from tb_common import service_auth as sa
from tb_contracts import JobCreate, JobError

from tests.console.test_twice_one_effect import record
from tests.service_tokens import per_service_tokens, token_of
from tests.unit.test_admin_retry_scheduled import _as, _failed, _retry, client, orch
from tests.unit.test_admin_retry_scheduled import _events as _orch_events
from tests.unit.test_mail_resolve import MTA, _gw, _req
from tests.unit.test_t726_night_runner import MON, Box, box

__all__ = ["box", "client", "orch"]


class LostAnswer(MTA):
    """Accepts the message, then the connection drops before the answer: the message has arrived."""

    def __init__(self) -> None:
        super().__init__()
        self.cause = None
        self.lose = True

    def __call__(self, frm: str, to: list[str], data: bytes) -> None:
        super().__call__(frm, to, data)
        if self.lose:
            raise TimeoutError("the answer was lost")


def _state(gw: Gateway, key: str) -> str:
    row = gw.db.get(key)
    return row.state if row else ""


# ---------------------------------------------------------------------------------------------- a retried mail
def test_the_same_send_key_twice_is_one_copy(tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta)
    a, b = gw.deliver(_req("k-same")), gw.deliver(_req("k-same"))
    record(
        "mail_same_key",
        {
            "place": "Gateway.deliver",
            "states": [a.state, b.state],
            "copies": len(mta.sent),
            "audit": dict(sorted(_mail_events(tmp_path).items())),
            "one_effect": len(mta.sent) == 1,
        },
    )
    assert (a.state, b.state) == ("sent", "duplicate") and len(mta.sent) == 1


def test_a_send_refused_before_accepting_is_sent_once_on_retry(tmp_path: Path) -> None:
    mta = MTA()  # down: nothing can have left
    gw = _gw(tmp_path, mta)
    first = gw.deliver(_req("k-down"))
    again = gw.deliver(_req("k-down"))  # the caller retries while it waits in the outbox
    mta.cause = None
    passes = [gw.drain(force=True), gw.drain(force=True)]
    record("mail_refused_then_retry", {"place": "Gateway.deliver, Gateway.drain", "states": [first.state,
           again.state], "drains": passes, "copies": len(mta.sent), "final": _state(gw, "k-down"),
           "audit": dict(sorted(_mail_events(tmp_path).items())), "one_effect": len(mta.sent) == 1})  # fmt: skip
    assert first.state == "queued" and again.state == "queued" and len(mta.sent) == 1 and _state(gw, "k-down") == "sent"


def test_an_uncertain_send_is_never_resent_without_a_person(tmp_path: Path) -> None:
    mta = LostAnswer()
    gw = _gw(tmp_path, mta)
    first = gw.deliver(_req("k-lost"))
    mta.lose = False
    again = gw.deliver(_req("k-lost"))  # the caller retries
    passes = [gw.drain(force=True), gw.drain()]  # the outbox loop and ``trialbox mail resolve`` without a decision
    record("mail_uncertain", {"place": "Gateway.deliver, Gateway.drain", "states": [first.state, again.state],
           "drains": passes, "copies": len(mta.sent), "final": _state(gw, "k-lost"),
           "audit": dict(sorted(_mail_events(tmp_path).items())),
           "one_effect": len(mta.sent) == 1 and _state(gw, "k-lost") == "uncertain"})  # fmt: skip
    assert first.state == "uncertain" and len(mta.sent) == 1 and _state(gw, "k-lost") == "uncertain"


def test_two_sends_of_one_key_at_once_are_one_copy(tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta)
    go = threading.Barrier(2)
    states: list[str] = []

    def one() -> None:
        go.wait()
        try:
            states.append(gw.deliver(_req("k-race")).state)
        except Exception as exc:  # in flight in the other request: refused (409 at the route), never sent
            states.append(type(exc).__name__)

    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    record(
        "mail_race",
        {
            "place": "Gateway.deliver, two threads",
            "states": sorted(states),
            "copies": len(mta.sent),
            "one_effect": len(mta.sent) == 1,
        },
    )
    assert len(mta.sent) == 1 and len(states) == 2


# ---------------------------------------------------------------------------------------------- a job re-queued
def test_the_timer_fired_twice_for_one_night_counts(box: Box) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    box.timer_ingest(MON)
    box.timer_ingest(MON)
    ingests = box.orch.db.find(type_="INGEST")
    box.orch.drain()
    work = [(t, s) for t, s, *_ in box.pinned]
    record("timer_twice", {"place": "scheduler._submit called twice (what the timer calls; not the timer firing)",
           "ingest_jobs": len(ingests), "work_runs": work, "one_effect": len(ingests) == 1})  # fmt: skip
    assert sorted(work) == sorted(set(work))  # the night's chain still runs once


def test_the_night_advanced_twice_makes_no_second_chain(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    first = box.chain()
    night.advance(box.orch)
    night.advance(box.orch)
    box.orch.drain()
    record("night_twice", {"place": "night.advance", "chain_before": len(first), "chain_after": len(box.chain()),
           "work_runs": len(box.pinned), "one_effect": box.chain() == first})  # fmt: skip
    assert box.chain() == first and len(box.pinned) == len(set((t, s) for t, s, *_ in box.pinned))


def _failed_ingest(box: Box) -> Any:
    box.timer_ingest(MON, passes=False)
    box.orch.drain()
    (failed,) = box.orch.db.find(type_="INGEST", state="failed")
    box.ingests.append((MON, True))
    return failed


def _newest_failed(box: Box) -> Any:
    jobs = sorted(box.orch.db.find(type_="INGEST", state="failed"), key=lambda j: (j.received_at, j.job_id))
    return jobs[-1]


def test_the_administrators_retry_sent_twice_is_one_job(box: Box) -> None:
    failed = _failed_ingest(box)
    box.orch.retry_scheduled(failed.job_id, by="console:admin", role="admin", reply_to="it@site.example")
    with pytest.raises(NotRetryable) as second:
        box.orch.retry_scheduled(failed.job_id, by="console:admin", role="admin", reply_to="it@site.example")
    n = len(box.orch.db.find(type_="INGEST"))
    record("retry_twice", {"place": "Orchestrator.retry_scheduled (D-474)", "ingest_jobs": n,
           "second_answer": str(second.value)[:120], "one_effect": n == 2})  # fmt: skip
    assert n == 2  # the failed one and its one retry


def _retry_race(box: Box, rounds: int = 5) -> list[dict[str, Any]]:
    """Two administrators press Retry at once (threads on the real job store). The store answers the "is one already
    queued?" read a little slowly (0.1 s), as a busy database does; nothing else is changed."""
    import time

    real = box.orch.db.unfinished

    def slow(*a: Any, **kw: Any) -> list[str]:
        out = real(*a, **kw)
        time.sleep(0.1)
        return out

    box.orch.db.unfinished = slow  # type: ignore[method-assign]
    rows = []
    box.timer_ingest(MON, passes=False)
    box.orch.drain()
    for _ in range(rounds):
        failed = _newest_failed(box)
        box.ingests.clear()
        box.ingests += [(MON, False)] * 2  # the retry fails again, so the next round has a failed job
        before = len(box.orch.db.find(type_="INGEST"))
        go = threading.Barrier(2)
        out: list[str] = []

        def one(fid: str = failed.job_id, go: threading.Barrier = go, out: list[str] = out) -> None:
            go.wait()
            try:
                box.orch.retry_scheduled(fid, by="console:admin", role="admin", reply_to="it@site.example")
                out.append("made")
            except NotRetryable:
                out.append("refused")
            except Exception as exc:
                out.append(type(exc).__name__)

        ts = [threading.Thread(target=one) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        rows.append({"answers": sorted(out), "jobs_made": len(box.orch.db.find(type_="INGEST")) - before})
        box.orch.drain()
    return rows


def test_two_retries_at_once_counts(box: Box) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    rows = _retry_race(box)
    record(
        "retry_race",
        {
            "place": "Orchestrator.retry_scheduled, two threads",
            "rounds": rows,
            "one_effect": all(r["jobs_made"] == 1 for r in rows),
        },
    )
    assert all(r["jobs_made"] >= 1 for r in rows)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-07: two retries of one failed scheduler job at once make two jobs (check, then admit)",
)
def test_two_retries_at_once_are_one_job(box: Box) -> None:
    rows = _retry_race(box, rounds=3)
    if not all(r["jobs_made"] >= 1 for r in rows):  # not an AssertionError: a fixture that made nothing is no measure
        raise RuntimeError(f"no retry was made: {rows}")
    assert all(r["jobs_made"] == 1 for r in rows), rows


def test_a_done_job_run_again_has_one_result(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    done = [j for j in box.orch.db.find(type_="MICROBATCH") if j.state == "done"]
    before = list(box.pinned)
    again = box.orch.run(done[0].job_id)
    record("run_done_again", {"place": "Orchestrator.run", "state": again.state,
           "work_added": len(box.pinned) - len(before), "one_effect": box.pinned == before})  # fmt: skip
    assert again.state == "done" and box.pinned == before


def test_a_worker_killed_mid_job_leaves_one_result_after_the_restart(box: Box) -> None:
    class Killed(BaseException):
        pass

    real = box.work
    killed: list[str] = []

    def dies_once(ctx: Ctx) -> Outcome:
        if ctx.job.type == "MICROBATCH" and not killed:
            killed.append(str(ctx.job.ruleset))
            ctx.state("running")
            raise Killed  # the process dies in the middle of the job
        return real(ctx)

    box.timer_ingest(MON)
    box.orch.scenarios["MICROBATCH"] = dies_once
    with pytest.raises(Killed):
        box.orch.drain()
    orch = box.start()  # a new process on the same job store
    orch.start()
    night.advance(orch)
    orch.drain()
    work = [(t, s) for t, s, *_ in box.pinned]
    states = sorted(j.state for j in orch.db.find(type_="MICROBATCH"))
    record("killed_mid_job", {"place": "Orchestrator.run after a restart", "killed": killed, "work_runs": work,
           "microbatch_states": states, "one_effect": len(work) == len(set(work))})  # fmt: skip
    assert len(work) == len(set(work))
    assert sum(1 for t, s in work if (t, s) == ("MICROBATCH", killed[0])) <= 1


# ---------------------------------------------------------------------------------------------- the real routes
def _mail_events(tmp_path: Path) -> Counter[str]:
    out: Counter[str] = Counter()
    for f in sorted((tmp_path / "audit").glob("*.jsonl")):
        out.update(json.loads(line)["event"] for line in f.read_text().splitlines() if line.strip())
    return out


@pytest.fixture
def mail_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MTA, Gateway]:
    """The mail gateway's own ``POST /send`` with this test's gateway (a stand-in MTA), signed as the console (a caller the gateway allows)."""
    from mail_gateway import app as mail_app

    per_service_tokens(tmp_path, monkeypatch, me="mail-gateway")
    mta = MTA()
    gw = _gw(tmp_path, mta)
    monkeypatch.setattr(mail_app, "_gw", gw)
    return TestClient(mail_app.app, raise_server_exceptions=False), mta, gw


def _send(client: TestClient, key: str) -> Any:
    return client.post("/send", json=_req(key).model_dump(mode="json"),
                       headers={sa.TOKEN_HEADER: token_of("console")})  # fmt: skip


def test_post_send_twice_with_one_key_is_one_copy(mail_route: tuple[TestClient, MTA, Gateway], tmp_path: Path) -> None:
    client, mta, _ = mail_route
    mta.cause = None
    a, b = _send(client, "r-same"), _send(client, "r-same")
    ev = _mail_events(tmp_path)
    one = len(mta.sent) == 1 and ev["mail.duplicate_suppressed"] == 1
    record("route_send_same_key", {"place": "POST /send (mail gateway)", "status": [a.status_code, b.status_code],
           "states": [a.headers.get("X-TB-Mail-State"), b.headers.get("X-TB-Mail-State")], "copies": len(mta.sent),
           "audit": dict(sorted(ev.items())), "one_effect": one})  # fmt: skip
    assert a.status_code == 200 and b.status_code == 200 and one


def test_post_send_retried_after_an_outage_is_one_copy(mail_route: tuple[TestClient, MTA, Gateway],
                                                       tmp_path: Path) -> None:  # fmt: skip
    client, mta, gw = mail_route
    a = _send(client, "r-down")  # the MTA is down: queued (202)
    mta.cause = None
    gw.drain(force=True)  # the outbox loop sends it
    b = _send(client, "r-down")  # the caller retries the same key
    ev = _mail_events(tmp_path)
    one = len(mta.sent) == 1 and _state(gw, "r-down") == "sent"
    record("route_send_retry", {"place": "POST /send (mail gateway), outbox between", "status": [a.status_code,
           b.status_code], "states": [a.headers.get("X-TB-Mail-State"), b.headers.get("X-TB-Mail-State")],
           "copies": len(mta.sent), "audit": dict(sorted(ev.items())), "one_effect": one})  # fmt: skip
    assert a.status_code == 202 and b.status_code == 200 and one


def _admin_retry_race(orch: Any, client: Any, rounds: int) -> list[dict[str, Any]]:
    """Two administrators press Retry at once on the orchestrator's own route (two clients, threads). The store's
    "is one already queued?" read answers 0.1 s slower, as a busy database does; nothing else is changed."""
    import time

    real = orch.db.unfinished

    def slow(*a: Any, **kw: Any) -> list[str]:
        out: list[str] = real(*a, **kw)
        time.sleep(0.1)
        return out

    orch.db.unfinished = slow
    rows = []
    for i in range(rounds):
        failed = _failed(orch, "INGEST")
        go = threading.Barrier(2)
        codes: list[int] = []

        def one(fid: str = failed.job_id, go: threading.Barrier = go, codes: list[int] = codes) -> None:
            c = TestClient(client.app, raise_server_exceptions=False)
            go.wait()
            codes.append(_retry(c, fid, _as("console")).status_code)

        ts = [threading.Thread(target=one) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        children = [j for j in orch.db.find(type_="INGEST") if j.parent_job_id == failed.job_id]
        rows.append({"round": i, "codes": sorted(codes), "jobs_made": len(children)})
        for j in children:  # end them, so the next round's failed job may be retried
            orch.set_state(j, "failed", error=JobError(step="running", message="test round over"))
    return rows


def test_the_admin_retry_route_twice_at_once_counts(orch: Any, client: Any) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    rows = _admin_retry_race(orch, client, 3)
    ev = Counter(e.get("event") for e in _orch_events(orch))
    record("route_retry_race", {"place": "POST /jobs/{job_id}/retry (orchestrator), two clients at once",
           "rounds": rows, "audit_job_retried": ev["job.retried"],
           "one_effect": all(r["jobs_made"] == 1 for r in rows)})  # fmt: skip
    assert all(r["jobs_made"] >= 1 for r in rows), rows


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-07: two retries of one failed scheduler job at once make two jobs (check, then admit)",
)
def test_the_admin_retry_route_twice_at_once_is_one_job(orch: Any, client: Any) -> None:
    rows = _admin_retry_race(orch, client, 3)
    if not all(r["jobs_made"] >= 1 for r in rows):  # not an AssertionError: a fixture that made nothing is no measure
        raise RuntimeError(f"no retry was made: {rows}")
    assert all(r["jobs_made"] == 1 for r in rows), rows


def test_a_job_requeued_while_it_runs_runs_once(box: Box) -> None:
    """A job is running (its worker holds the lease); it is queued again and a second worker takes it: the second
    run is refused by the lease, and the work is done once. Then the admin's retry while it runs is refused."""
    started, release = threading.Event(), threading.Event()
    runs: list[str] = []

    def slow(ctx: Ctx) -> Outcome:
        ctx.state("running")
        runs.append(ctx.job.job_id)
        started.set()
        release.wait(10)
        return Outcome(summary_md="ok")

    box.orch.scenarios["RETENTION"] = slow
    job = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    jid = box.orch.db.claim() or ""
    t = threading.Thread(target=box.orch.run, args=(jid,))
    t.start()
    assert started.wait(10)
    box.orch.db.enqueue(jid)  # queued again while it runs
    second = box.orch.db.claim() or ""
    again = box.orch.run(second)  # the second worker
    try:
        box.orch.retry_scheduled(jid, by="console:admin", role="admin", reply_to="it@site.example")
        retry = "made"
    except NotRetryable as exc:
        retry = f"refused: {str(exc)[:60]}"
    release.set()
    t.join(10)
    final = box.orch.db.get(job.job_id)
    row = {"place": "JobDB.enqueue + Orchestrator.run (second worker) + retry_scheduled", "second_claim": second == jid,
           "second_run_state": again.state, "runs": len(runs), "retry": retry,
           "final": final.state if final else "", "one_effect": len(runs) == 1 and retry != "made"}  # fmt: skip
    record("requeued_while_running", row)
    assert row["one_effect"], row
