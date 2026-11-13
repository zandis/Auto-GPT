"""T-726 (D-492), the adversarial review of 2026-11-12: what the chain did not hold.

* H1: the administrator's retry of the timer's failed ingest is followed by the night's chain;
* H2: a step that was started in part (the process died between two of its jobs) is completed, not passed;
* M1: one run per study and night is a key in the job store, not a lock of one process;
* M2: a step that was passed over stays passed once a later step of the night has started;
* M4: a newer night does not start beside an older night's jobs that have not ended;
* L1: a weekly run made before this card counts as the week's run.

The real orchestrator and job store of ``test_t726_night_runner``'s box."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from orchestrator import night, scheduler
from orchestrator.core import Ctx, Outcome
from tb_contracts import JobCreate

from tests.unit.test_t726_night_runner import MON, TUE, Box, box

__all__ = ["box"]
WED = date(2026, 11, 18)


def test_the_administrators_retry_of_the_timers_ingest_is_followed_by_the_night(box: Box) -> None:
    box.timer_ingest(MON, passes=False)
    box.orch.drain()
    (failed,) = box.orch.db.find(type_="INGEST", state="failed")
    assert box.chain() == []
    box.ingests.append((MON, True))
    again = box.orch.retry_scheduled(failed.job_id, by="console:admin", role="admin", reply_to="it@site.example")
    assert again.requested_by != "scheduler" and (again.options or {}).get("chain") == "1"
    box.orch.drain()
    assert [t for t, *_ in box.pinned] == ["MICROBATCH", "MICROBATCH", "NAV", "RETENTION"]
    assert all(snap == MON for _t, _s, snap, _k in box.pinned)


def test_a_step_that_was_started_in_part_is_completed_after_a_restart(box: Box) -> None:
    """The process dies after the screen step made ADX's job and before GZQO's. After the restart ADX runs; the
    chain must make GZQO's job before it goes on to NAV and retention."""

    class Killed(BaseException):
        pass

    box.timer_ingest(MON)
    real = box.orch.create
    made: list[str] = []

    def dies_at_the_second(req: JobCreate, *a: Any, **kw: Any) -> Any:
        if req.type == "MICROBATCH":
            if made:
                raise Killed
            made.append(str(req.ruleset))
        return real(req, *a, **kw)

    box.orch.create = dies_at_the_second  # type: ignore[method-assign]
    with pytest.raises(Killed):
        box.orch.drain()
    assert box.chain() == [("MICROBATCH", "ADX")]
    orch = box.start()  # a new process on the same job store
    orch.start()
    night.advance(orch)
    orch.drain()
    assert [(t, s) for t, s, *_ in box.pinned] == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO"), ("NAV", "NHI1"),
                                                   ("RETENTION", None)]  # fmt: skip


def test_one_run_per_study_and_night_holds_across_processes(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two orchestrator processes advance the same night at once: the process-local lock does not hold them apart.
    The job of a type, study and night has one id, so the second start is the first one's job."""
    box.timer_ingest(MON)
    assert box.orch.run(box.orch.db.claim() or "").state == "done"
    first = box.chain()
    assert first == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO")]
    # the other process read the job store before these jobs were made: its reads show no job of the step
    monkeypatch.setattr(box.orch.db, "find", lambda **kw: [])
    monkeypatch.setattr(night, "_exists", lambda *a: False, raising=False)
    night._start_step(box.orch, "screen", MON.isoformat(), MON)
    monkeypatch.undo()
    assert box.chain("MICROBATCH") == first  # no second MICROBATCH of a study for the night


def test_a_step_passed_over_stays_passed_once_a_later_step_has_started(box: Box) -> None:
    """The self-test failed: the model steps are passed over and retention runs. A restart (the self-test's answer
    is in memory only) must not start the model steps after retention, in the daytime."""
    box.gate = False
    box.timer_ingest(MON)
    box.orch.drain()
    assert box.pinned == [("RETENTION", None, MON, "")]
    box.gate = True  # the restarted process asks the self-test again, and it passes
    orch = box.start()
    orch.start()
    assert night.advance(orch) == []
    orch.drain()
    assert box.pinned == [("RETENTION", None, MON, "")]
    box.pinned.clear()
    box.timer_ingest(TUE)  # the week's steps are made up on the next night, on its snapshot
    box.orch.drain()
    assert [(t, k) for t, _s, _snap, k in box.pinned] == [("MICROBATCH", "weekly"), ("MICROBATCH", "weekly"),
                                                          ("NAV", ""), ("RETENTION", "")]  # fmt: skip


def test_a_newer_night_waits_for_an_older_nights_jobs_that_have_not_ended(box: Box) -> None:
    """Monday's screen step is still queued when Tuesday's ingest passes: no second MICROBATCH of a study beside
    the first. When Monday's jobs have ended, Tuesday's night goes on (and makes up what Monday did not reach)."""
    box.timer_ingest(MON)
    assert box.orch.run(box.orch.db.claim() or "").state == "done"  # Monday's ingest; its screen step is queued
    monday = [j for j in box.orch.db.find(type_="MICROBATCH")]
    assert len(monday) == 2
    box.timer_ingest(TUE)
    tuesday = next(j for j in box.orch.db.find(type_="INGEST") if j.state != "done")
    assert box.orch.run(tuesday.job_id).state == "done"  # Tuesday's ingest passes while Monday's jobs wait
    assert len(box.orch.db.find(type_="MICROBATCH")) == 2  # nothing of Tuesday beside them
    box.orch.drain()
    unfinished = [j for j in box.orch.db.find(limit=500) if j.state not in ("done", "failed")]
    assert not unfinished
    nights = [(j.type, j.ruleset, (j.options or {})["night"]) for j in box.orch.db.find(limit=500)
              if (j.options or {}).get("step")]  # fmt: skip
    assert sorted(n for n in nights if n[2] == TUE.isoformat()) == [
        ("MICROBATCH", "ADX", TUE.isoformat()), ("MICROBATCH", "GZQO", TUE.isoformat()),
        ("NAV", "NHI1", TUE.isoformat()), ("RETENTION", None, TUE.isoformat())]  # fmt: skip
    assert [n for n in nights if n[2] == MON.isoformat() and n[0] != "MICROBATCH"] == []  # said in the log


def test_a_weekly_run_made_before_this_card_counts_as_the_weeks_run(box: Box) -> None:
    """A box updated on Tuesday: Monday's weekly jobs were made by the old timers (no ``options.step``)."""

    def old(ctx: Ctx) -> Outcome:
        return Outcome(summary_md="ok")

    box.current = MON
    scenarios = box.orch.scenarios
    scenarios["MICROBATCH"], scenarios["NAV"] = old, old
    for rid in ("ADX", "GZQO"):
        scheduler._submit(box.orch, "MICROBATCH", rid)
    scheduler._submit(box.orch, "NAV", "NHI1")
    box.orch.drain()
    for j in box.orch.db.find(limit=50):  # made on Monday
        j.received_at = j.received_at.replace(year=MON.year, month=MON.month, day=MON.day, hour=3)
        with box.orch.db.tx() as tx:
            tx.execute("UPDATE jobs SET received_at = ?, data = ? WHERE job_id = ?",
                       (j.received_at.isoformat(), j.model_dump_json(by_alias=True, exclude_none=True), j.job_id))  # fmt: skip
    scenarios["MICROBATCH"], scenarios["NAV"] = box.work, box.work
    box.timer_ingest(TUE)
    box.orch.drain()
    assert [(t, k) for t, _s, _snap, k in box.pinned] == [("MICROBATCH", "ingest"), ("MICROBATCH", "ingest"),
                                                          ("RETENTION", "")]  # fmt: skip
