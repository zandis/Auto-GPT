"""T-726 (D-492; scale review F-33): the night runner. Only the ingest and the monthly jobs keep a clock time; every
other step starts when the step before it has finished; one run per study and generation; a restart resumes the
step the night was in.

The row's acceptance test: Monday's jobs never pin last night's snapshot after a slow ingest. A real orchestrator
and job store, stand-in scenarios that record what they pinned and when they were created."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator import night, scheduler
from orchestrator.core import Ctx, Orchestrator, Outcome, Services
from orchestrator.db import JobDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]
SUN, MON, TUE = date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 17)
STUDIES = ["ADX", "GZQO"]


class Mail:
    def send(self, req: SendRequest) -> SendResult:
        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


class Box:
    """The parts of a box the night touches: the lake's CURRENT, what each job pinned, the order jobs were made."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp_path = tmp_path
        self.current = SUN  # last night's snapshot is served
        self.ingests: list[tuple[date, bool]] = []  # the nights the ingest will publish, and whether each passes
        self.pinned: list[tuple[str, str | None, date, str]] = []  # (type, study, snapshot it read, trigger)
        self.during_ingest: list[str] = []  # job types that existed while an ingest was still running
        self.gate = True
        monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "open")
        monkeypatch.setattr(scheduler, "night_gate", lambda orch: self.gate)
        monkeypatch.setattr(scheduler, "nav_rulesets", lambda orch: ["NHI1"])
        monkeypatch.setattr(night, "_said", set())
        self.orch = self.start()

    def start(self) -> Orchestrator:
        """An orchestrator process on the box's job store, with its scheduler's chain."""
        cfg = Config(
            env=load_env(dotenv=self.tmp_path / "x.env", environ={}),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        scenarios = {"INGEST": self.ingest, "MICROBATCH": self.work, "NAV": self.work, "RETENTION": self.work}
        orch = Orchestrator(
            cfg,
            JobDB(),
            FsStore(self.tmp_path / "obj"),
            AuditLog(self.tmp_path / "audit"),
            Services(lake=None, parser=None, compiler=None, mail=Mail()),  # type: ignore[arg-type]
            scenarios,  # type: ignore[arg-type]
            self.tmp_path / "rulesets",
            self.tmp_path,
            today=lambda: self.current,
            workers=0,
            async_notify=False,
        )
        orch.db.pool_rulesets = lambda: list(STUDIES)  # type: ignore[method-assign]

        def go_on(_job: Any) -> None:  # what scheduler.start wires
            night.advance(orch)

        orch.on_terminal.append(go_on)
        self.orch = orch
        return orch

    def ingest(self, ctx: Ctx) -> Outcome:
        ctx.state("running")
        night_day, passes = self.ingests.pop(0)
        # the ingest is slow: the clock passes 03:00 and 03:30 while it runs. Nothing but the ingest exists
        self.during_ingest += [j.type for j in ctx.orch.db.find(limit=200) if j.type != "INGEST"]
        if not passes:
            from orchestrator.clients import StepFailed

            raise StepFailed("ingest", "The nightly ingest finished with errors")
        self.current = night_day  # the lake promoted tonight's snapshot
        ctx.update(snapshot_date=night_day)
        return Outcome(summary_md="passed")

    def work(self, ctx: Ctx) -> Outcome:
        ctx.state("running")
        opts = ctx.job.options or {}
        self.pinned.append((ctx.job.type, ctx.job.ruleset, self.current, str(opts.get("trigger") or "")))
        return Outcome(summary_md="ok")

    def timer_ingest(self, night_day: date, passes: bool = True) -> None:
        """02:00: the scheduler's timer starts the ingest, as ``scheduler.start`` registers it."""
        self.ingests.append((night_day, passes))
        scheduler._submit(self.orch, "INGEST", None, {"timer": "1", "chain": "1"})

    def chain(self, kind: str | None = None) -> list[tuple[str, str | None]]:
        jobs = [j for j in self.orch.db.find(limit=500) if (j.options or {}).get("step")]
        jobs.sort(key=lambda j: (j.received_at, j.job_id))
        return [(j.type, j.ruleset) for j in jobs if kind is None or j.type == kind]


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    return Box(tmp_path, monkeypatch)


# ------------------------------------------------------------------------------------------- the acceptance test
def test_mondays_jobs_never_pin_last_nights_snapshot_after_a_slow_ingest(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    assert box.during_ingest == []  # no timer started a weekly job while the ingest ran
    assert box.pinned and all(snap == MON for _t, _s, snap, _k in box.pinned), box.pinned
    kinds = {(t, s): k for t, s, _snap, k in box.pinned}
    assert kinds == {("MICROBATCH", "ADX"): "weekly", ("MICROBATCH", "GZQO"): "weekly", ("NAV", "NHI1"): "",
                     ("RETENTION", None): ""}  # fmt: skip
    # each step was started only when the step before it had ended: the jobs ran in the chain's order
    assert [t for t, _s, _snap, _k in box.pinned] == ["MICROBATCH", "MICROBATCH", "NAV", "RETENTION"]
    for j in box.orch.db.find(limit=50):
        if (j.options or {}).get("step"):
            assert (j.options or {})["night"] == MON.isoformat() and j.state == "done"


def test_only_the_ingest_and_the_monthly_jobs_have_a_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    added: dict[str, Any] = {}

    class Sched:
        def __init__(self, **kw: Any) -> None:
            pass

        def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
            added[id] = (args, kw)

        def start(self) -> None:
            pass

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", Sched)
    monkeypatch.setattr("tb_common.config.schedule_on_demand", lambda settings, env: False)
    monkeypatch.setattr(night, "advance", lambda orch, **_kwargs: [])
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(settings=SimpleNamespace(schedule=None), env=SimpleNamespace(tz="Asia/Tokyo", extra={})),
        on_terminal=[],
    )
    scheduler.start(orch)
    assert sorted(added) == ["calibration", "cohort", "ingest", "not_matched_sample"]
    assert added["ingest"][0][1:] == ["INGEST", None, {"timer": "1", "chain": "1"}]
    assert added["cohort"][1]["day"] == 1 and added["calibration"][1]["day"] == 1  # the monthly ones, on the 1st
    assert len(orch.on_terminal) == 1  # the chain goes on when a job ends
    assert {t for t, _ in scheduler.plan(None)} >= {"MICROBATCH", "NAV", "RETENTION"}  # still scheduled types (D-474)


# ------------------------------------------------------------------------------------------- one run per study
def test_one_run_per_study_and_generation_whoever_asks(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    first = box.chain()
    for _ in range(5):  # a job's end, a restart, a second caller: nothing new
        assert night.advance(box.orch) == []
    box.timer_ingest(MON)  # the administrator runs the timer's ingest of the same night again (D-474)
    box.orch.drain()
    assert box.chain() == first and len(box.chain("MICROBATCH")) == 2
    assert [k for t, _s, _snap, k in box.pinned if t == "MICROBATCH"] == ["weekly", "weekly"]  # never both kinds


def test_on_another_night_the_micro_batch_is_the_ingests_and_nav_waits_for_its_day(box: Box) -> None:
    box.timer_ingest(MON)
    box.orch.drain()
    box.pinned.clear()
    box.timer_ingest(TUE)
    box.orch.drain()
    assert box.pinned == [("MICROBATCH", "ADX", TUE, "ingest"), ("MICROBATCH", "GZQO", TUE, "ingest"),
                          ("RETENTION", None, TUE, "")]  # fmt: skip


def test_a_weekly_step_that_missed_its_day_runs_at_the_next_night_that_passes(box: Box) -> None:
    box.timer_ingest(MON, passes=False)  # Monday's ingest fails: the box still serves Sunday
    box.orch.drain()
    assert box.pinned == [] and box.chain() == []  # nothing screens on the old snapshot, with or without notice
    box.timer_ingest(TUE)
    box.orch.drain()
    assert [(t, s, snap, k) for t, s, snap, k in box.pinned if t != "RETENTION"] == [
        ("MICROBATCH", "ADX", TUE, "weekly"),
        ("MICROBATCH", "GZQO", TUE, "weekly"),
        ("NAV", "NHI1", TUE, ""),
    ]
    box.pinned.clear()
    box.timer_ingest(date(2026, 11, 18))  # Wednesday: the week's run is done
    box.orch.drain()
    assert [k for t, _s, _snap, k in box.pinned if t == "MICROBATCH"] == ["ingest", "ingest"]
    assert not [t for t, *_ in box.pinned if t == "NAV"]


def test_a_failed_self_test_passes_over_the_model_steps_and_retention_still_runs(box: Box) -> None:
    box.gate = False
    box.timer_ingest(MON)
    box.orch.drain()
    assert box.pinned == [("RETENTION", None, MON, "")]
    box.gate = True  # the next night's self-test passes: the week's steps are made up on that night's snapshot
    box.pinned.clear()
    box.timer_ingest(TUE)
    box.orch.drain()
    assert [(t, k) for t, _s, _snap, k in box.pinned] == [("MICROBATCH", "weekly"), ("MICROBATCH", "weekly"),
                                                          ("NAV", ""), ("RETENTION", "")]  # fmt: skip


# ------------------------------------------------------------------------------------------- a restart
def test_a_restart_resumes_the_step_the_night_was_in(box: Box) -> None:
    class Killed(BaseException):
        pass

    box.timer_ingest(MON)
    assert box.orch.run(box.orch.db.claim() or "").state == "done"  # the ingest ended: the screen step is queued
    assert box.chain() == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO")]
    real = box.work

    def dies(ctx: Ctx) -> Outcome:
        if ctx.job.ruleset == "GZQO":
            raise Killed  # the box dies in the second micro-batch
        return real(ctx)

    box.orch.scenarios["MICROBATCH"] = dies
    with pytest.raises(Killed):
        box.orch.drain()
    assert [(t, s) for t, s, *_ in box.pinned] == [("MICROBATCH", "ADX")]
    orch = box.start()  # a new process: the interrupted job is queued again, the chain reads where the night is
    orch.start()
    assert night.advance(orch) == []  # the screen step is still running: nothing new, no second micro-batch
    orch.drain()
    assert [(t, s) for t, s, *_ in box.pinned] == [("MICROBATCH", "ADX"), ("MICROBATCH", "GZQO"), ("NAV", "NHI1"),
                                                   ("RETENTION", None)]  # fmt: skip
    assert len(box.chain("MICROBATCH")) == 2 and len(box.chain()) == 4


def test_an_ingest_asked_for_by_hand_is_followed_as_before(box: Box, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-397 unchanged: a person's ingest is followed by the micro-batch for the new booked patients, at once; it
    starts no weekly step and is not the night the chain is on."""
    box.ingests.append((MON, True))
    box.orch.create(JobCreate(type="INGEST", requested_by="scheduler"))
    box.orch.drain()
    assert night.current_night(box.orch) is None and box.chain() == []
    assert scheduler.after_ingest(box.orch) == STUDIES
    box.orch.drain()
    assert [(t, k) for t, _s, _snap, k in box.pinned] == [("MICROBATCH", "ingest"), ("MICROBATCH", "ingest")]


@pytest.mark.nodb
def test_the_day_of_a_schedule_entry_and_the_last_scheduled_day() -> None:
    assert night.weekday_of("MON 03:00", "") == 0 and night.weekday_of(None, "TUE 03:30") == 1
    assert night.weekday_of("05:00", "") is None
    assert night.last_scheduled(MON, 0) == MON and night.last_scheduled(TUE, 0) == MON
    assert night.last_scheduled(SUN, 0) == date(2026, 11, 9) and night.last_scheduled(TUE, None) == TUE
