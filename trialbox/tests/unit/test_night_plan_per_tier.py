"""Plan 10 row 10E-11: the scheduler's night plan per tier (review 13, section 7.3).

Each test is one acceptance case. The shipped records are the files in ``models/tiers``; tier A and tier C are
fixtures, because those profiles have no shipped record.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator import night, night_plan, scheduler
from orchestrator.scenarios import microbatch
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


def _ingest(state: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="INGEST", state=state, requested_by="scheduler", options={"timer": "1", "chain": "1"}
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
    monkeypatch.setattr(night, "advance", lambda orch: [])
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
    monkeypatch.setattr(night, "advance", lambda orch: [])
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
    monkeypatch.setattr(night, "advance", lambda orch: calls.append("advance") or [])
    at = datetime(2026, 11, 18, 17, 20, tzinfo=UTC)  # 02:20 in Asia/Tokyo
    running = _orch(plan, [_ingest("running")])
    assert night_plan.local_clock(running, at) == time(2, 20)
    waiting = scheduler.advance_night(running, now=at)
    assert waiting.coded_screening == "wait_for_ingest"
    assert waiting.started == ()
    assert "coded" not in waiting.started
    finished = _orch(plan, [_ingest("done")])
    gone = scheduler.advance_night(finished, now=at)
    assert gone.coded_screening == "run"
    assert "coded" in gone.started
    assert calls == ["advance", "advance"]
