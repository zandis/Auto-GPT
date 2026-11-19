"""10E-11 (D-1336): the night plan follows the tier, from measured values only; the scheduler states it at start.

One test per tier (the shipped records, no record, an unknown label, a ballast record, a malformed record, a pipe),
and one per finding of PR #1203: the plan names only passes a job runs (high 1), a record's "no model" does not make
a coded-only claim the screen step does not keep (high 2), the scheduler adds no 06:00 job and cancels nothing (high 3,
medium 4 and 5), the stated budget is the enforced one on every label (medium 6), pass names are unique (medium 7).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from orchestrator import night, night_plan, scheduler
from orchestrator.scenarios import microbatch
from tb_common import tier_value

from tests.unit import test_screen_limit_stated

SHIPPED = tier_value.TIERS_DIR


def cfg(budget: int = 2000, ingest: str | None = None) -> Any:
    sch = SimpleNamespace(ingest=ingest) if ingest else None
    return SimpleNamespace(settings=SimpleNamespace(schedule=sch), env=SimpleNamespace(microbatch_night_budget=budget))


@pytest.fixture
def tiers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tier_value, "TIERS_DIR", tmp_path)
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    return tmp_path


def write(tiers: Path, profile: str, fields: dict[str, Any], **top: Any) -> None:
    doc = {"profile": profile, "fields": fields, **top}
    (tiers / f"{profile}.json").write_text(json.dumps(doc), encoding="utf-8")


def measured(value: Any) -> dict[str, Any]:
    return {"basis": "measured", "value": value, "source": "x"}


def enforced(c: Any) -> int:
    return microbatch.night_budget(cast(Any, SimpleNamespace(cfg=c)))


# ------------------------------------------------------------------------------------------------ the shipped tiers
def test_the_rtxpro6000_plan_is_the_resident_pair_with_the_safe_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    plan = night_plan.build(cfg())
    assert plan.profile == "rtxpro6000" and not plan.safe
    assert plan.models_on_card.value == "pair_resident" and "both resident" in plan.residency
    # declared 16 in the record: not taken, the plan says so (D-1322)
    assert plan.screen_concurrency.value is None and plan.screen_concurrency.text() == "declared, not measured"
    assert plan.night_budget.value is None and plan.night_budget.text() == "not measured"
    assert plan.judge_calls_per_second.text() == "not measured"
    assert (plan.budget_patients, plan.budget_from) == (2000, "fallback")
    assert plan.warnings == ()


def test_the_32gb_site_box_is_unmeasured_and_runs_the_safe_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    plan = night_plan.build(cfg())
    assert plan.profile == "rtx5090" and plan.safe
    assert plan.residency.startswith("not measured: the safe plan")
    assert plan.models_on_card.value is None  # declared pair_sleep_swap_one_awake: not a tier value
    assert plan.screen_concurrency.value is None and plan.night_budget.value is None
    assert (plan.budget_patients, plan.budget_from) == (2000, "fallback")
    line = plan.lines()[0]
    assert "safe plan" in line and "not measured" in line and "2000 patients (fallback" in line


@pytest.mark.parametrize("label", ["", "P-GB10", "P-CPU", "stub"])
def test_a_box_with_no_record_runs_the_safe_plan(label: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", label)
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    plan = night_plan.build(cfg())
    assert plan.profile is None and plan.safe and plan.budget_patients == 2000
    assert plan.night_budget.text() == "no tier record for this TB_PROFILE"
    assert "no tier record" in plan.lines()[0]


def test_a_measured_tier_sizes_the_plan_and_the_screen_step_alike(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    write(tiers, "rtx5090", {
        "models_on_card": measured("pair_sleep_swap_one_awake"), "screen_concurrency": measured(4),
        "night_budget_patients": measured(750), "judge_calls_per_second": measured(2.5),
    })  # fmt: skip
    plan = night_plan.build(cfg())
    assert not plan.safe and "swap" in plan.residency
    assert plan.screen_concurrency.value == 4 and plan.judge_calls_per_second.value == 2.5
    assert (plan.budget_patients, plan.budget_from) == (750, "tier record") and enforced(cfg()) == 750
    assert (night_plan.build(cfg(500)).budget_patients, night_plan.build(cfg(500)).budget_from) == (500, "setting")


def test_settings_keep_the_ingest_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    assert night_plan.build(cfg(ingest="01:30")).ingest == "01:30"
    assert night_plan.build(cfg()).ingest == "02:00"


# ------------------------------------------------------------------------- not a tier record: ballast, broken, pipe
def test_a_ballast_record_is_never_a_tier_record(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-5090")
    write(tiers, "rtx5090", {"models_on_card": measured("pair_resident"), "night_budget_patients": measured(900)},
          measured_on={"serving_record": "x", "capped_to": "32607 MiB by ballast"})  # fmt: skip
    plan = night_plan.build(cfg())
    assert plan.safe and plan.night_budget.case == "malformed" and plan.budget_patients == 2000
    assert enforced(cfg()) == 2000  # the screen step refuses it too
    assert tier_value.measured("night_budget_patients").why.endswith(
        "made under the ballast stand-in, never a tier record"
    )


def test_the_ballast_walk_does_not_recurse() -> None:
    deep: Any = "made By  Ballast"
    for _ in range(100_000):
        deep = [deep]
    assert tier_value.made_under_ballast({"a": deep}) is True
    assert tier_value.made_under_ballast({"by ballast": 1}) is True
    assert tier_value.made_under_ballast({"a": ["ballast", 1, None]}) is False


@pytest.mark.parametrize("body", [b"{", b"\xff", b"[]", b'{"fields": {"models_on_card": 3}}', b"[" * 200_000])
def test_a_malformed_record_gives_the_safe_plan(body: bytes, tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    (tiers / "rtxpro6000.json").write_bytes(body)
    plan = night_plan.build(cfg())
    assert plan.safe and plan.night_budget.case == "malformed" and plan.budget_patients == 2000


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes on this system")
def test_a_pipe_in_place_of_the_record_does_not_hang(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    os.mkfifo(tiers / "rtxpro6000.json")
    got: list[night_plan.NightPlan] = []
    t = threading.Thread(target=lambda: got.append(night_plan.build(cfg())), daemon=True)
    t.start()
    t.join(10)
    assert got and got[0].safe and got[0].budget_patients == 2000


def test_a_plan_that_cannot_be_built_is_the_safe_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_ctx: Any) -> int:
        raise ValueError("x")

    monkeypatch.setattr(microbatch, "night_budget", boom)
    plan = night_plan.build(cfg())
    assert plan.safe and plan.warnings == ("night plan: not built (ValueError): the night runs as configured",)


# ------------------------------------------------------------------------------------------------ the stated limit
def test_the_stated_limit_is_the_measurement_pages() -> None:
    assert night_plan.STATED_PATIENT_LIMIT == test_screen_limit_stated._limit() == 45_000


def test_a_measured_budget_over_the_stated_limit_is_not_taken(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    write(tiers, "rtxpro6000", {"night_budget_patients": measured(45_001)})
    plan = night_plan.build(cfg())
    assert plan.night_budget.value is None and plan.night_budget.case == "over_limit"
    assert plan.budget_patients == 2000 == enforced(cfg())
    assert any("over the stated limit of 45,000 patients" in w for w in plan.warnings)
    write(tiers, "rtxpro6000", {"night_budget_patients": measured(45_000)})
    assert night_plan.build(cfg()).budget_patients == 45_000 == enforced(cfg())


def test_a_configured_budget_over_the_limit_wins_and_is_warned(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    for budget, shown in ((60_000, "60000"), (0, "no limit")):
        plan = night_plan.build(cfg(budget))
        assert plan.budget_patients == budget and plan.budget_from == "setting"
        assert any(f"({shown}) is over the stated limit" in w for w in plan.warnings)


# -------------------------------------------------------------------------------------------- the findings of #1203
def test_high1_the_plan_names_only_steps_a_job_runs(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The builders' plan named first-load slices, judge/swap/verifier and a CPU note pass that no job runs."""
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    for models in ("pair_resident", "pair_sleep_swap_one_awake", "none", "cpu"):
        write(tiers, "rtxpro6000", {"models_on_card": measured(models), "screen_concurrency": measured(12)})
        plan = night_plan.build(cfg())
        assert plan.steps == ("ingest", *night.STEPS)  # ingest, then the chain's own steps (D-492)
        assert set(plan.steps[1:]) <= set(night.STEP_TYPE)
    assert not hasattr(plan, "dispatch")  # nothing is written into a job's options


def test_high2_no_model_in_the_record_is_not_a_coded_only_claim(tiers: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    write(tiers, "rtxpro6000", {"models_on_card": measured("none")})
    plan = night_plan.build(cfg())
    assert "coded" not in plan.residency.split()  # the plan does not promise that no model is asked
    assert any("still asks each study's configured judge" in w for w in plan.warnings)


def test_high3_and_mediums_the_scheduler_adds_no_cutoff_and_cancels_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    added: dict[str, Any] = {}
    cancelled: list[Any] = []

    class Sched:
        def __init__(self, **kw: Any) -> None:
            pass

        def add_job(self, fn: Any, trigger: str, id: str, args: Any = None, **kw: Any) -> None:
            added[id] = kw

        def start(self) -> None:
            pass

    monkeypatch.setattr("apscheduler.schedulers.background.BackgroundScheduler", Sched)
    monkeypatch.setattr("tb_common.config.schedule_on_demand", lambda settings, env: False)
    monkeypatch.setattr(night, "advance", lambda orch: [])
    monkeypatch.setenv("TB_PROFILE", "P-PRO6000")
    monkeypatch.delenv("TB_MICROBATCH_NIGHT_BUDGET", raising=False)
    orch: Any = SimpleNamespace(
        cfg=SimpleNamespace(settings=SimpleNamespace(schedule=None), env=SimpleNamespace(tz="Asia/Tokyo", extra={})),
        on_terminal=[],
        cancel=lambda *a: cancelled.append(a),
    )
    with caplog.at_level(logging.INFO, logger="orchestrator.night_plan"):
        scheduler.start(orch)
    assert sorted(added) == ["calibration", "cohort", "ingest", "not_matched_sample"]  # no 06:00 job
    assert cancelled == []  # the plan stops no job (the builders cancelled CPU note jobs at 06:00)
    assert isinstance(orch.night_plan, night_plan.NightPlan) and orch.night_plan.profile == "rtxpro6000"
    assert any(r.getMessage().startswith("night plan (rtxpro6000): ingest 02:00, then screen > nav > retention")
               for r in caplog.records)  # fmt: skip


def test_the_plan_is_said_when_the_schedule_is_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tb_common.config.schedule_on_demand", lambda settings, env: True)
    orch: Any = SimpleNamespace(cfg=SimpleNamespace(settings=SimpleNamespace(schedule=None),
                                                    env=SimpleNamespace(tz="UTC", extra={})))  # fmt: skip
    assert scheduler.start(orch) is None and isinstance(orch.night_plan, night_plan.NightPlan)


@pytest.mark.parametrize("label", ["P-GB10", "P-CPU", "P-5090", "P-PRO6000", ""])
def test_medium6_the_stated_budget_is_the_enforced_one(
    label: str, tiers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builders' plan read gb10.json for P-GB10 while the screen step did not: 750 stated, 2000 enforced."""
    monkeypatch.setenv("TB_PROFILE", label)
    for profile in ("gb10", "cpu", "rtx5090", "rtxpro6000"):
        write(tiers, profile, {"night_budget_patients": measured(750)})
    assert night_plan.build(cfg()).budget_patients == enforced(cfg())


def test_medium7_step_names_are_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    for label in ("P-PRO6000", "P-5090", ""):
        monkeypatch.setenv("TB_PROFILE", label)
        steps = night_plan.build(cfg()).steps
        assert len(set(steps)) == len(steps)


def test_the_shipped_records_are_still_read_unchanged() -> None:
    assert tier_value.TIERS_DIR == SHIPPED
    for name in ("rtx5090", "rtxpro6000"):
        assert not tier_value.made_under_ballast(tier_value.read_record(SHIPPED / f"{name}.json"))
