"""Plan 10 row 10E-11: the scheduler's night plan per tier (review 13, section 7.3).

Each test is one acceptance case. The shipped records are the files in ``models/tiers``; tier A and tier C are
fixtures, because those profiles have no shipped record.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator import night, night_plan, scheduler
from orchestrator.scenarios import microbatch
from tb_common import tier_value
from tb_common.config import load_env, load_settings

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
TIERS = ROOT / "models" / "tiers"
TOKYO = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")


def _shipped(profile: str) -> dict[str, Any]:
    return json.loads((TIERS / f"{profile}.json").read_text(encoding="utf-8"))


def _field(basis: str, value: Any, *, by: str = "fixture") -> dict[str, Any]:
    if basis == "not_measured":
        return {"basis": basis, "value": None, "measured_by": by}
    return {"basis": basis, "value": value, "source": "fixture"}


def _record(
    *,
    profile: str,
    tier: str,
    models: str,
    concurrency: int,
    budget: dict[str, Any] | None = None,
    rate: dict[str, Any] | None = None,
    qualification: str | None = None,
    models_basis: str = "declared",
) -> dict[str, Any]:
    return {
        "schema": "tb-tier-record/1",
        "profile": profile,
        "tier": tier,
        "measured_on": {"serving_record": None, "qualification_record": qualification},
        "fields": {
            "models_on_card": _field(models_basis, models),
            "screen_concurrency": _field("declared", concurrency),
            "night_budget_patients": budget or _field("not_measured", None),
            "judge_calls_per_second": rate or _field("not_measured", None),
        },
    }


def _orch(plan: night_plan.NightPlan, jobs: list[Any] | None = None, *, budget: int = 2000) -> SimpleNamespace:
    rows = list(jobs or [])

    def find(type_: str | None = None, limit: int = 50) -> list[Any]:
        got = rows if type_ is None else [job for job in rows if getattr(job, "type", None) == type_]
        return got[:limit]

    return SimpleNamespace(
        cfg=SimpleNamespace(
            settings=SimpleNamespace(schedule=SimpleNamespace(ingest=plan.ingest)),
            env=SimpleNamespace(tz="Asia/Tokyo", extra={}, microbatch_night_budget=budget),
        ),
        db=SimpleNamespace(find=find),
        night_plan=plan,
    )


def _ingest(state: str, *, snapshot: date | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        type="INGEST",
        state=state,
        requested_by="scheduler",
        parent_job_id=None,
        options={"timer": "1", "chain": "1"},
        snapshot_date=snapshot,
        received_at=datetime(2026, 11, 18, 17, 0, tzinfo=UTC),
    )


def test_rtx5090_judge_pass_precedes_the_swap_and_verifier() -> None:
    """Shipped RTX 5090: judge, then the swap, then the verifier, at the record's concurrency of 4."""
    record = _shipped("rtx5090")
    plan = night_plan.build_night_plan(None, {"TB_PROFILE": "P-5090"})
    names = plan.names()
    assert names.index("judge") < names.index("swap") < names.index("verifier")
    assert plan.swap_scheduled is True
    assert plan.models_resident is False
    assert plan.models_on_card == "pair_sleep_swap_one_awake"
    assert plan.screen_concurrency == 4
    assert plan.screen_concurrency == record["fields"]["screen_concurrency"]["value"]
    assert record["fields"]["models_on_card"]["value"] == plan.models_on_card


def test_rtxpro6000_keeps_both_models_resident_without_a_swap() -> None:
    """Shipped RTX PRO 6000: both models stay resident, nothing is swapped, concurrency is 16."""
    record = _shipped("rtxpro6000")
    plan = night_plan.build_night_plan(None, {"TB_PROFILE": "P-PRO6000"})
    assert plan.models_resident is True
    assert plan.models_on_card == "pair_resident"
    assert plan.models_on_card == record["fields"]["models_on_card"]["value"]
    assert plan.swap_scheduled is False
    assert "swap" not in plan.names()
    assert plan.screen_concurrency == 16
    assert plan.screen_concurrency == record["fields"]["screen_concurrency"]["value"]


def test_tier_c_uses_the_fixture_concurrency_and_first_load_after_delta() -> None:
    """A tier C fixture with both models resident: its concurrency, then first-load slices after the delta."""
    record = _record(profile="gb10", tier="C", models="pair_resident", concurrency=12)
    plan = night_plan.build_night_plan(None, {}, record=record)
    names = plan.names()
    assert plan.screen_concurrency == 12
    assert plan.models_resident is True
    assert plan.swap_scheduled is False
    assert names.index("delta_screening") < names.index("first_load")
    assert names.count("first_load") >= 2
    first = next(step for step in plan.slices if step.name == "first_load")
    assert first.after == "delta_screening"


def test_coded_only_tier_a_screens_codes_after_ingest_and_schedules_no_note_pass() -> None:
    """A coded-only tier A installation: coded screening follows ingest, and no note-model pass is scheduled."""
    record = _record(profile="cpu", tier="A", models="none", concurrency=1)
    plan = night_plan.build_night_plan(None, {}, record=record)
    names = plan.names()
    assert names.index("ingest") < names.index("coded")
    coded = next(step for step in plan.slices if step.name == "coded")
    assert coded.after == "ingest"
    assert plan.note_model is False
    for name in ("note_cpu", "judge", "swap", "verifier", "delta_screening"):
        assert name not in names


def test_qualified_tier_a_stops_cpu_notes_at_0600_and_opens_the_backup_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qualified tier A with CPU note screening: at 06:00 local the notes stop and the backup window begins."""
    record = _record(
        profile="cpu",
        tier="A",
        models="cpu",
        concurrency=2,
        qualification="fixtures/cpu-qualification.json",
    )
    plan = night_plan.build_night_plan(None, {}, record=record)
    note = next(step for step in plan.slices if step.name == "note_cpu")
    backup = next(step for step in plan.slices if step.name == "backup")
    assert plan.note_model is True
    assert note.end == "06:00"
    assert (backup.start, backup.end) == ("06:00", "08:00")
    monkeypatch.setattr(night, "advance", lambda orch, **_kwargs: [])
    orch = _orch(plan)
    # 06:00 in Asia/Tokyo is 21:00 UTC the day before. The plan uses the site's zone, not UTC.
    at_six = scheduler.advance_night(orch, now=datetime(2026, 11, 18, 21, 0, tzinfo=UTC))
    assert at_six.cpu_note_screening is False
    assert at_six.stop_cpu_note_screening is True
    assert at_six.backup_window == ("06:00", "08:00")
    assert "note_cpu" not in at_six.started
    assert "backup" in at_six.started
    still = scheduler.advance_night(orch, now=datetime(2026, 11, 18, 20, 59, tzinfo=UTC))
    assert still.cpu_note_screening is True
    assert still.stop_cpu_note_screening is False
    assert still.backup_window is None
    assert "note_cpu" in still.started


def test_shipped_records_label_the_unmeasured_budget_and_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Either shipped record: the budget and the rate stay "not measured", even though the runtime fallback is 2,000."""
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    for label, profile in (("P-5090", "rtx5090"), ("P-PRO6000", "rtxpro6000")):
        record = _shipped(profile)
        assert record["fields"]["night_budget_patients"]["basis"] == "not_measured"
        assert record["fields"]["judge_calls_per_second"]["basis"] == "not_measured"
        plan = night_plan.build_night_plan(None, {"TB_PROFILE": label})
        report = plan.report()
        assert plan.runtime_budget == microbatch.DEFAULT_NIGHT_BUDGET == 2000
        assert report["runtime_budget_patients"] == 2000
        for key, unit in (("patient_budget", "patients"), ("judge_calls_per_second", "judge_calls_per_second")):
            figure = report[key]
            assert figure["basis"] == "not_measured"
            assert figure["value"] is None
            assert figure["unit"] == unit
            assert figure["label"] == {"en": "not measured", "zh-TW": "尚未測量", "ja": "未測定"}
            assert figure["value"] != 2000


def test_a_measured_budget_and_rate_are_reported_in_their_units() -> None:
    """A measured budget of 750 patients and 2.5 judge calls per second are reported in those units."""
    record = _record(
        profile="fixture",
        tier="D",
        models="pair_resident",
        concurrency=8,
        models_basis="measured",
        budget=_field("measured", 750),
        rate=_field("measured", 2.5),
    )
    plan = night_plan.build_night_plan(None, {}, record=record)
    patients = plan.patient_budget
    rate = plan.judge_calls_per_second
    assert patients.basis == "measured" and patients.value == 750 and patients.unit == "patients"
    assert rate.basis == "measured" and rate.value == 2.5 and rate.unit == "judge_calls_per_second"
    assert patients.label["en"] == "750 patients"
    assert rate.label["en"] == "2.5 judge calls per second"
    assert patients.label["zh-TW"] == "750 位病人" and patients.label["ja"] == "750 人"
    assert rate.label["zh-TW"] == "每秒 2.5 次判定" and rate.label["ja"] == "毎秒 2.5 回の判定"
    assert rate.value == 2.5  # the recorded rate, not a rescaled count
    assert plan.runtime_budget == 750


def test_no_tier_record_keeps_the_ingest_time_and_an_unlimited_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No tier record, ingest 01:15, budget 0: the scheduler leaves both as they are."""
    monkeypatch.delenv("TB_PROFILE", raising=False)
    monkeypatch.setenv("TB_MICROBATCH_NIGHT_BUDGET", "0")
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    settings = settings.model_copy(update={"schedule": settings.schedule.model_copy(update={"ingest": "01:15"})})
    env = load_env(
        dotenv=tmp_path / "none.env",
        environ={"TB_MICROBATCH_NIGHT_BUDGET": "0", "TB_TZ": "Asia/Tokyo"},
    )
    added: dict[str, Any] = {}
    seen: dict[str, Any] = {}

    class Sched:
        def __init__(self, **kw: Any) -> None:
            seen["timezone"] = kw.get("timezone")

        def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
            added[id] = kw

        def start(self) -> None:
            pass

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", Sched)
    monkeypatch.setattr(night, "advance", lambda orch, **_kwargs: [])
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=settings, env=env), on_terminal=[])
    scheduler.start(orch)
    plan = orch.night_plan
    assert plan.ingest == "01:15"
    assert plan.profile is None
    assert plan.runtime_budget == 0
    assert plan.runtime_unlimited is True
    assert plan.note_model is False
    assert plan.patient_budget.label == {"en": "no tier record", "zh-TW": "沒有層級紀錄", "ja": "ティアの記録はない"}
    assert added["ingest"]["hour"] == 1 and added["ingest"]["minute"] == 15
    assert seen["timezone"] == "Asia/Tokyo"
    assert microbatch.night_budget(SimpleNamespace(cfg=SimpleNamespace(env=env))) == 0


def test_coded_screening_waits_while_ingest_is_still_running_at_0220(monkeypatch: pytest.MonkeyPatch) -> None:
    """At 02:20 local, coded screening does not start while the night's ingest is still running."""
    settings = SimpleNamespace(schedule=SimpleNamespace(ingest="02:00"))
    plan = night_plan.build_night_plan(settings, {})
    coded = next(step for step in plan.slices if step.name == "coded")
    assert coded.after == "ingest" and coded.start == "02:20"
    calls: list[str] = []
    monkeypatch.setattr(night, "advance", lambda orch, **_kwargs: calls.append("advance") or [])
    at = datetime(2026, 11, 18, 17, 20, tzinfo=UTC)  # 02:20 in Asia/Tokyo
    running = _orch(plan, [_ingest("running")])
    assert night_plan.local_clock(running, at) == time(2, 20)
    waiting = scheduler.advance_night(running, now=at)
    assert waiting.coded_screening == "wait_for_ingest"
    assert waiting.started == ()
    assert "coded" not in waiting.started
    finished = _orch(plan, [_ingest("done", snapshot=date(2026, 11, 18))])
    gone = scheduler.advance_night(finished, now=at)
    assert gone.coded_screening == "run"
    assert "coded" in gone.started
    assert calls == ["advance", "advance"]


def _hhmm(spec: str) -> dict[str, Any]:
    """The cron fields ``scheduler.start`` records for one schedule entry."""
    return scheduler.cron_kwargs(spec)


class _Clock:
    """An APScheduler stand-in that keeps the callable, so a test can fire the clock."""

    def __init__(self) -> None:
        self.added: dict[str, Any] = {}
        self.timezone: str | None = None

    def build(self) -> type:
        added = self.added
        holder = self

        class Sched:
            def __init__(self, **kw: Any) -> None:
                holder.timezone = kw.get("timezone")

            def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
                added[id] = {"fn": fn, "args": args, "kw": kw}

            def start(self) -> None:
                pass

        return Sched


def _tier_dir(tmp_path: Path, name: str, record: dict[str, Any]) -> Path:
    folder = tmp_path / "tiers"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


def _freeze(monkeypatch: pytest.MonkeyPatch, when: datetime) -> None:
    """``night_plan.local_clock`` reads ``datetime.now`` when the caller does not pass a time."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return when if tz is None else when.astimezone(tz)

    monkeypatch.setattr(night_plan, "datetime", Frozen)


class _Chain:
    """The job store ``night.advance`` actually writes. Not a stand-in for ``night.advance`` itself."""

    def __init__(self, tmp_path: Path, snap: date) -> None:
        self.jobs: list[Any] = []
        self.created: list[Any] = []
        self.cancelled: list[tuple[str, str]] = []
        self.ingest = SimpleNamespace(
            type="INGEST",
            state="done",
            requested_by="scheduler",
            parent_job_id=None,
            options={"timer": "1", "chain": "1", "lake_generation": snap.isoformat()},
            snapshot_date=snap,
            received_at=datetime(snap.year, snap.month, snap.day, 17, 5, tzinfo=UTC),
            updated_at=datetime(snap.year, snap.month, snap.day, 17, 10, tzinfo=UTC),
            job_id="INGEST1",
        )
        self.orch = SimpleNamespace(
            cfg=SimpleNamespace(
                settings=SimpleNamespace(
                    schedule=SimpleNamespace(
                        ingest="02:00", microbatch="MON 03:00", nav="MON 03:30", retention="05:00"
                    )
                ),
                env=SimpleNamespace(tz="Asia/Tokyo", extra={}, microbatch_night_budget=2000, data_dir=str(tmp_path)),
            ),
            db=self,
            scenarios={"MICROBATCH": object, "NAV": object, "RETENTION": object},
            services=SimpleNamespace(llm=None),
            data_dir=str(tmp_path),
            audit=SimpleNamespace(append=lambda *a, **k: None),
            create=self.create,
            cancel=self.cancel,
        )

    def find(self, type_: str | None = None, limit: int = 50) -> list[Any]:
        rows = self.jobs if type_ is None else [job for job in self.jobs if job.type == type_]
        return rows[:limit]

    def chained_ingest(self, before: str | None = None) -> Any:
        return self.ingest if self.ingest.state == "done" and self.ingest.snapshot_date is not None else None

    def scheduler_jobs(self, **_kw: Any) -> list[Any]:
        return []

    def get(self, job_id: str) -> Any:
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def pool_rulesets(self) -> list[str]:
        return ["ADX"]

    def create(self, req: Any) -> Any:
        self.created.append(req)
        job = SimpleNamespace(
            job_id=req.job_id or f"J{len(self.jobs)}",
            type=req.type,
            state="received",
            ruleset=req.ruleset,
            requested_by=req.requested_by,
            options=dict(req.options or {}),
            snapshot_date=None,
            parent_job_id=None,
            received_at=datetime.now(UTC),
            updated_at=None,
        )
        self.jobs.append(job)
        return job

    def cancel(self, job_id: str, by: str) -> None:
        self.cancelled.append((job_id, by))
        job = self.get(job_id)
        if job is not None and job.state not in ("done", "failed"):
            job.state = "failed"


def _open_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chain's own holds, not the runner: a unit test has no trial database and no model."""
    monkeypatch.setattr(scheduler, "restore_held", lambda url=None: False)
    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "open")
    monkeypatch.setattr(scheduler, "committee_held", lambda rid, url=None: [])
    monkeypatch.setattr(scheduler, "night_gate", lambda orch, today=None, clock=None: True)


def _screen(created: list[Any]) -> Any:
    return next(req for req in created if req.type == "MICROBATCH")


def test_clock_at_0600_stops_active_cpu_notes_and_starts_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Qualified tier A: the 06:00 clock cancels a note pass that is still running and opens the backup window.

    The clock is the job ``scheduler.start`` registers. Firing it is the run; the returned flags are not.
    """
    monkeypatch.delenv("TB_PROFILE", raising=False)
    monkeypatch.delenv("TB_OPS_DIR", raising=False)
    record = _record(
        profile="cpu",
        tier="A",
        models="cpu",
        concurrency=2,
        qualification="fixtures/cpu-qualification.json",
    )
    monkeypatch.setattr(tier_value, "TIERS_DIR", _tier_dir(tmp_path, "cpu", record))
    monkeypatch.setenv("TB_PROFILE", "P-CPU")
    ops = tmp_path / "ops"
    ops.mkdir()
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    env = load_env(
        dotenv=tmp_path / "none.env",
        environ={"TB_PROFILE": "P-CPU", "TB_TZ": "Asia/Tokyo", "TB_OPS_DIR": str(ops), "TB_ENV": "PRODUCTION"},
    )
    clock = _Clock()
    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", clock.build())
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=settings, env=env), data_dir=str(tmp_path))
    scheduler.start(orch)
    plan = orch.night_plan
    assert plan.note_model is True
    assert "night_backup" in clock.added
    assert clock.timezone == "Asia/Tokyo"
    assert clock.added["night_backup"]["kw"] == {"hour": 6, "minute": 0}
    note = SimpleNamespace(
        job_id="NOTE1",
        type="MICROBATCH",
        state="running",
        options={"night_pass": "note_cpu"},
        requested_by="scheduler",
    )
    done = SimpleNamespace(
        job_id="NOTE0",
        type="MICROBATCH",
        state="done",
        options={"night_pass": "note_cpu"},
        requested_by="scheduler",
    )
    cancelled: list[tuple[str, str]] = []

    def cancel(job_id: str, by: str) -> None:
        cancelled.append((job_id, by))
        if job_id == note.job_id:
            note.state = "failed"

    orch.db = SimpleNamespace(find=lambda type_=None, limit=50: [note, done])
    orch.cancel = cancel
    early = datetime(2026, 11, 18, 20, 59, tzinfo=UTC)  # 05:59 in Asia/Tokyo
    before = scheduler.advance_night(orch, now=early)
    assert before.stop_cpu_note_screening is False
    assert cancelled == []
    assert list(ops.glob("requests/*.json")) == []
    _freeze(monkeypatch, datetime(2026, 11, 18, 21, 0, tzinfo=UTC))  # 06:00 in Asia/Tokyo
    clock.added["night_backup"]["fn"]()
    assert cancelled == [("NOTE1", "scheduler")]
    assert note.state == "failed"
    assert done.state == "done"
    from tools.trialbox.ops import OpsDir

    requests = OpsDir(ops).requests()
    assert [r.get("action") for r in requests] == ["backup"]
    assert requests[0]["by"] == "scheduler"
    assert requests[0]["args"] == {"day": "2026-11-19", "window": "06:00-08:00"}
    clock.added["night_backup"]["fn"]()  # the same morning does not ask for a second backup
    assert [r.get("action") for r in OpsDir(ops).requests()] == ["backup"]


def test_shipped_tiers_reach_the_microbatch_the_chain_creates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RTX 5090 and RTX PRO 6000: ``night.advance`` is called with each plan's dispatch and stores it on the job."""
    _open_gates(monkeypatch)
    seen: list[dict[str, str] | None] = []
    real = night.advance

    def spy(orch: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("dispatch"))
        return real(orch, *args, **kwargs)

    monkeypatch.setattr(night, "advance", spy)
    snap = date(2026, 11, 16)  # a Monday, so the chain's weekly screen is due
    at = datetime(2026, 11, 16, 17, 30, tzinfo=UTC)  # 02:30 in Asia/Tokyo, after ingest
    jobs = []
    for label in ("P-5090", "P-PRO6000"):
        box = _Chain(tmp_path / label, snap)
        box.orch.night_plan = night_plan.build_night_plan(box.orch.cfg.settings, {"TB_PROFILE": label})
        box.orch.cfg.env.extra = {"TB_PROFILE": label}
        scheduler.advance_night(box.orch, now=at)
        jobs.append(_screen(box.created).options)
    assert seen[0] is not None and seen[1] is not None
    assert seen[0] != seen[1]
    assert seen[0]["passes"] == "judge>swap>verifier"
    assert seen[0]["screen_concurrency"] == "4"
    assert seen[0]["models_resident"] == "0"
    assert seen[0]["swap"] == "1"
    assert seen[1]["passes"] == "delta_screening>first_load>first_load"
    assert seen[1]["screen_concurrency"] == "16"
    assert seen[1]["models_resident"] == "1"
    assert seen[1]["swap"] == "0"
    assert "swap" not in seen[1]["passes"]
    assert jobs[0]["passes"] == seen[0]["passes"] and jobs[0]["screen_concurrency"] == "4"
    assert jobs[1]["passes"] == seen[1]["passes"] and jobs[1]["screen_concurrency"] == "16"
    assert jobs[0]["models_on_card"] == "pair_sleep_swap_one_awake"
    assert jobs[1]["models_on_card"] == "pair_resident"


def test_pgb10_record_is_read_when_the_scheduler_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TB_PROFILE=P-GB10`` and a ``gb10.json`` record: startup keeps residency, concurrency and first-load slices."""
    monkeypatch.delenv("TB_PROFILE", raising=False)
    record = _record(profile="gb10", tier="C", models="pair_resident", concurrency=12)
    monkeypatch.setattr(tier_value, "TIERS_DIR", _tier_dir(tmp_path, "gb10", record))
    monkeypatch.setenv("TB_PROFILE", "P-GB10")
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    env = load_env(
        dotenv=tmp_path / "none.env",
        environ={"TB_PROFILE": "P-GB10", "TB_TZ": "Asia/Tokyo", "TB_ENV": "PRODUCTION"},
    )
    clock = _Clock()
    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", clock.build())
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=settings, env=env))
    scheduler.start(orch)
    plan = orch.night_plan
    assert plan.profile == "gb10"
    assert plan.screen_concurrency == 12
    assert plan.models_resident is True
    assert plan.swap_scheduled is False
    names = plan.names()
    assert names.index("delta_screening") < names.index("first_load")
    _open_gates(monkeypatch)
    box = _Chain(tmp_path / "run", date(2026, 11, 16))
    box.orch.night_plan = plan
    box.orch.cfg.env = env
    scheduler.advance_night(box.orch, now=datetime(2026, 11, 16, 17, 30, tzinfo=UTC))
    options = _screen(box.created).options
    assert options["screen_concurrency"] == "12"
    assert options["models_resident"] == "1"
    assert "first_load" in options["passes"]
    assert "swap" not in options["passes"]


def test_a_failed_first_ingest_does_not_report_coded_as_started(monkeypatch: pytest.MonkeyPatch) -> None:
    """02:20, the night's first ingest failed, no earlier success: coded is not started; nothing is screened."""
    plan = night_plan.build_night_plan(SimpleNamespace(schedule=SimpleNamespace(ingest="02:00")), {})
    failed = SimpleNamespace(
        type="INGEST",
        state="failed",
        requested_by="scheduler",
        parent_job_id=None,
        options={"timer": "1", "chain": "1"},
        snapshot_date=None,
        received_at=datetime(2026, 11, 18, 17, 5, tzinfo=UTC),
        job_id="INGEST1",
    )
    created: list[Any] = []

    class DB:
        def find(self, type_: str | None = None, limit: int = 50) -> list[Any]:
            rows = [failed] if type_ in (None, "INGEST") else []
            return rows[:limit]

        def chained_ingest(self, before: str | None = None) -> None:
            return None

        def scheduler_jobs(self, **_kw: Any) -> list[Any]:
            return []

        def get(self, _job_id: str) -> None:
            return None

        def pool_rulesets(self) -> list[str]:
            return ["ADX"]

    orch = SimpleNamespace(
        cfg=SimpleNamespace(
            settings=SimpleNamespace(
                schedule=SimpleNamespace(ingest="02:00", microbatch="MON 03:00", nav="MON 03:30", retention="05:00")
            ),
            env=SimpleNamespace(tz="Asia/Tokyo", extra={}, microbatch_night_budget=2000),
        ),
        db=DB(),
        night_plan=plan,
        scenarios={"MICROBATCH": object, "NAV": object, "RETENTION": object},
        services=SimpleNamespace(llm=None),
        data_dir="/tmp/night-plan-failed-ingest",
        audit=SimpleNamespace(append=lambda *a, **k: None),
        create=created.append,
    )
    at = datetime(2026, 11, 18, 17, 20, tzinfo=UTC)  # 02:20 in Asia/Tokyo
    assert night_plan.local_clock(orch, at) == time(2, 20)
    decision = scheduler.advance_night(orch, now=at)
    assert night.current_night(orch) is None
    assert created == []
    assert decision.coded_screening != "run"
    assert "coded" not in decision.started


def test_dotenv_profile_budget_is_the_budget_microbatch_enforces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TB_PROFILE`` only in the loaded dotenv, measured budget 750: the plan and the micro-batch agree."""
    monkeypatch.delenv("TB_PROFILE", raising=False)
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    record = _shipped("rtxpro6000")
    record["fields"]["night_budget_patients"] = {"basis": "measured", "value": 750, "source": "fixture"}
    monkeypatch.setattr(tier_value, "TIERS_DIR", _tier_dir(tmp_path, "rtxpro6000", record))
    dotenv = tmp_path / "box.env"
    dotenv.write_text("TB_PROFILE=P-PRO6000\nTB_TZ=Asia/Tokyo\n", encoding="utf-8")
    env = load_env(dotenv=dotenv, environ={"TB_TZ": "Asia/Tokyo"})
    assert os.environ.get("TB_PROFILE") in (None, "")
    assert env.extra["TB_PROFILE"] == "P-PRO6000"
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=None, env=env))
    plan = night_plan.build_night_plan(None, scheduler._box_env(orch), env_obj=env)
    enforced = microbatch.night_budget(SimpleNamespace(cfg=SimpleNamespace(env=env)))
    assert plan.runtime_budget == enforced == 750
    assert plan.patient_budget.value == 750 and plan.patient_budget.unit == "patients"


def test_weekly_and_monthly_ingest_keep_their_clock_on_the_coded_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MON 04:00`` and ``1st 04:00``: the timer keeps that clock, and coded screening starts twenty minutes later."""
    monkeypatch.delenv("TB_PROFILE", raising=False)
    weekly = _hhmm("MON 04:00")
    monthly = _hhmm("1st 04:00")
    assert weekly == {"hour": 4, "minute": 0, "day_of_week": "mon"}
    assert monthly["hour"] == 4 and monthly["minute"] == 0 and monthly["day"] == 1
    settings = load_settings(ROOT / "deploy/settings.example.yaml")
    settings = settings.model_copy(update={"schedule": settings.schedule.model_copy(update={"ingest": "MON 04:00"})})
    env = load_env(dotenv=tmp_path / "none.env", environ={"TB_TZ": "Asia/Tokyo", "TB_ENV": "PRODUCTION"})
    clock = _Clock()
    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", clock.build())
    orch = SimpleNamespace(cfg=SimpleNamespace(settings=settings, env=env), on_terminal=[])
    monkeypatch.setattr(night, "advance", lambda _orch, **_kwargs: [])
    scheduler.start(orch)
    assert clock.added["ingest"]["kw"]["hour"] == 4
    assert clock.added["ingest"]["kw"]["minute"] == 0
    assert clock.added["ingest"]["kw"]["day_of_week"] == "mon"
    coded = next(step for step in orch.night_plan.slices if step.name == "coded")
    assert orch.night_plan.ingest == "MON 04:00"
    assert coded.after == "ingest" and coded.start == "04:20"
    month = night_plan.build_night_plan(
        SimpleNamespace(schedule=SimpleNamespace(ingest="1st 04:00")), {}
    )
    coded_month = next(step for step in month.slices if step.name == "coded")
    assert coded_month.start == "04:20"
