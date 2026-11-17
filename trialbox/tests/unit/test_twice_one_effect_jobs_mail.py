"""V-11: twice has one effect (the mail gateway and the job queue).

* A retried mail: the gateway's own ``deliver`` and ``drain`` (what ``POST /send`` and the outbox loop call) with a
  stand-in MTA that fails before accepting (nothing left) or after accepting (the answer is lost: "uncertain").
  How many copies can the recipient get? An uncertain mail waits for a person (D-401, T-108c).
* A job re-queued: the real orchestrator and job store of ``test_t726_night_runner``'s box. The timer fires twice
  for one night; the administrator's retry (D-474) is sent twice, also from two threads at once; a done job is run
  again; the worker dies in the middle of a job and a new process starts.

Counts go to ``twice.json`` when ``TB_TWICE_OUT`` names a folder. All data is synthetic."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from mail_gateway.gateway import Gateway
from orchestrator import night
from orchestrator.core import Ctx, NotRetryable, Outcome

from tests.console.test_twice_one_effect import record
from tests.unit.test_mail_resolve import MTA, _gw, _req
from tests.unit.test_t726_night_runner import MON, Box, box

__all__ = ["box"]


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
    record("mail_same_key", {"place": "Gateway.deliver", "states": [a.state, b.state], "copies": len(mta.sent)})
    assert (a.state, b.state) == ("sent", "duplicate") and len(mta.sent) == 1


def test_a_send_refused_before_accepting_is_sent_once_on_retry(tmp_path: Path) -> None:
    mta = MTA()  # down: nothing can have left
    gw = _gw(tmp_path, mta)
    first = gw.deliver(_req("k-down"))
    again = gw.deliver(_req("k-down"))  # the caller retries while it waits in the outbox
    mta.cause = None
    passes = [gw.drain(force=True), gw.drain(force=True)]
    record("mail_refused_then_retry", {"place": "Gateway.deliver, Gateway.drain", "states": [first.state,
           again.state], "drains": passes, "copies": len(mta.sent), "final": _state(gw, "k-down")})  # fmt: skip
    assert first.state == "queued" and again.state == "queued" and len(mta.sent) == 1 and _state(gw, "k-down") == "sent"


def test_an_uncertain_send_is_never_resent_without_a_person(tmp_path: Path) -> None:
    mta = LostAnswer()
    gw = _gw(tmp_path, mta)
    first = gw.deliver(_req("k-lost"))
    mta.lose = False
    again = gw.deliver(_req("k-lost"))  # the caller retries
    passes = [gw.drain(force=True), gw.drain()]  # the outbox loop and ``trialbox mail resolve`` without a decision
    record("mail_uncertain", {"place": "Gateway.deliver, Gateway.drain", "states": [first.state, again.state],
           "drains": passes, "copies": len(mta.sent), "final": _state(gw, "k-lost")})  # fmt: skip
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
    record("mail_race", {"place": "Gateway.deliver, two threads", "states": sorted(states), "copies": len(mta.sent)})
    assert len(mta.sent) == 1 and len(states) == 2


# ---------------------------------------------------------------------------------------------- a job re-queued
def test_the_timer_fired_twice_for_one_night_counts(box: Box) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    box.timer_ingest(MON)
    box.timer_ingest(MON)
    ingests = box.orch.db.find(type_="INGEST")
    box.orch.drain()
    work = [(t, s) for t, s, *_ in box.pinned]
    record("timer_twice", {"place": "scheduler._submit (the timer)", "ingest_jobs": len(ingests),
           "work_runs": work})  # fmt: skip
    assert sorted(work) == sorted(set(work))  # the night's chain still runs once


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-06: the ingest timer fired twice for one night makes two INGEST jobs",
)
def test_the_timer_fired_twice_for_one_night_is_one_ingest(box: Box) -> None:
    box.timer_ingest(MON)
    box.timer_ingest(MON)
    assert len(box.orch.db.find(type_="INGEST")) == 1


def test_the_night_advanced_twice_makes_no_second_chain(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    first = box.chain()
    night.advance(box.orch)
    night.advance(box.orch)
    box.orch.drain()
    record("night_twice", {"place": "night.advance", "chain_before": len(first), "chain_after": len(box.chain()),
           "work_runs": len(box.pinned)})  # fmt: skip
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
           "second_answer": str(second.value)[:120]})  # fmt: skip
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
    record("retry_race", {"place": "Orchestrator.retry_scheduled, two threads", "rounds": rows})
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
           "work_added": len(box.pinned) - len(before)})  # fmt: skip
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
           "microbatch_states": states})  # fmt: skip
    assert len(work) == len(set(work))
    assert sum(1 for t, s in work if (t, s) == ("MICROBATCH", killed[0])) <= 1
