"""The night plan per tier (plan 10 row 10E-11, review 13 section 7.3, D-1336).

The scheduler builds one plan at start from this box's tier record and says it in the log. The plan states the night
the box runs, never one it does not run:

* **The order is the chain's.** The timer's ingest, then the night chain's steps (:data:`orchestrator.night.STEPS`):
  screen, NAV, retention, each when the step before it has ended (D-492). Coded screening never starts while the
  night's ingest runs, because the screen step follows the ingest's end. The plan names no pass that no job runs:
  no first-load slice, no CPU note pass, no 06:00 stop and no backup window (review 13 section 7.3 proposes them;
  they wait for the jobs that run them).
* **Tier values only when measured (D-1322).** The record is read through :func:`tb_common.tier_value.measured`, the
  one bounded reader: it never raises or hangs, and it refuses a record made under the ballast stand-in. A declared
  or not-measured field, a missing, malformed or ballast record and an unknown ``TB_PROFILE`` give no value, and the
  plan says "not measured" (or why there is none) instead of a figure.
* **An unmeasured tier runs the safe plan.** When ``models_on_card`` is not measured the plan is today's night,
  labelled as the safe plan. The night budget is what the screen step enforces
  (:func:`orchestrator.scenarios.microbatch.night_budget`): a setting, else a measured tier value, else 2000.
* **The stated limit.** A measured night budget over :data:`STATED_PATIENT_LIMIT` (45,000 patients, H23b-01: the
  orchestrator's memory cap as installed) is not taken; the screen step keeps its fallback, and the plan says why.

Nothing here writes a job option: the plan describes what the existing jobs do with the tier's measured values.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

from tb_common import tier_value

log = logging.getLogger("orchestrator.night_plan")

# The patients SCREEN can hold under the orchestrator's memory cap as installed (H23b-01; CHANGELOG "Known limits";
# tests/unit/test_screen_limit_stated.py derives the same figure from the measurement). No plan states more.
STATED_PATIENT_LIMIT = 45_000

_RESIDENCY = {
    "pair_resident": "judge and verifier both resident, the pair at the screen concurrency",
    "pair_sleep_swap_one_awake": "judge pass, swap, verifier pass (one model awake at a time)",
}
_WHY = {
    "declared": "declared, not measured",
    "not_measured": "not measured",
    "no_record": "no tier record",
    "unknown_profile": "no tier record for this TB_PROFILE",
    "malformed": "the tier record is not readable",
    "over_limit": f"over the stated limit of {STATED_PATIENT_LIMIT:,} patients",
}


@dataclass(frozen=True)
class Figure:
    """One tier value as the plan states it. ``value`` is set only when it was measured and is usable."""

    field: str
    case: str
    value: Any = None
    recorded: Any = None  # the measured number refused as over the stated limit, for the log line

    @property
    def measured(self) -> bool:
        return self.case == "measured" and self.value is not None

    def text(self) -> str:
        if self.measured:
            return f"{self.value} (measured)"
        if self.case == "over_limit":
            return f"measured {self.recorded}, {_WHY['over_limit']}: not taken"
        return _WHY.get(self.case, "not measured")


def _figure(field: str, env: Mapping[str, str] | None = None, *, count: bool) -> Figure:
    tv = tier_value.measured(field, env)
    if tv.case != "measured":
        return Figure(field, tv.case)
    if count:
        n = tier_value.positive_int(tv)
        return Figure(field, "measured", n) if n is not None else Figure(field, "malformed")
    v = tv.value
    if isinstance(v, str):
        return Figure(field, "measured", v.strip()) if v.strip() else Figure(field, "malformed")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return Figure(field, "malformed")
    return Figure(field, "measured", v)


def tier_budget(env: Mapping[str, str] | None = None) -> Figure:
    """This box's measured ``night_budget_patients`` within the stated limit, else a figure with no value.

    The screen step's budget (:func:`orchestrator.scenarios.microbatch.night_budget`) and the plan both read it here,
    so the plan never states a budget the screen step does not enforce. Never raises."""
    fig = _figure("night_budget_patients", env, count=True)
    if fig.measured and fig.value > STATED_PATIENT_LIMIT:
        return Figure(fig.field, "over_limit", None, fig.value)
    return fig


@dataclass(frozen=True)
class NightPlan:
    """The night the scheduler runs on this box, and the tier figures it is willing to state."""

    profile: str | None
    safe: bool  # the tier's shape is not measured: today's night, the safe plan
    ingest: str
    steps: tuple[str, ...]
    models_on_card: Figure
    screen_concurrency: Figure
    night_budget: Figure
    judge_calls_per_second: Figure
    budget_patients: int  # what the screen step enforces; 0 is no limit
    budget_from: str  # "setting", "tier record" or "fallback"
    warnings: tuple[str, ...] = ()

    @property
    def residency(self) -> str:
        if self.safe:
            return "not measured: the safe plan (the night as configured, no tier figure used)"
        value = str(self.models_on_card.value)
        return _RESIDENCY.get(value, f"{value} as the tier record states it")

    def lines(self) -> list[str]:
        """What the scheduler logs at start: one line for the plan, one per warning."""
        budget = "no limit" if self.budget_patients == 0 else f"{self.budget_patients} patients"
        head = (
            f"night plan ({self.profile or 'no tier record'}): ingest {self.ingest}, then "
            f"{' > '.join(self.steps[1:])} after it ends; models: {self.residency}; "
            f"night budget {budget} ({self.budget_from}; tier figure {self.night_budget.text()}); "
            f"screen concurrency {self.screen_concurrency.text()}; "
            f"judge calls per second {self.judge_calls_per_second.text()}"
        )
        return [head, *self.warnings]


def _ingest_of(settings: Any) -> str:
    sch = getattr(settings, "schedule", None)
    return str(getattr(sch, "ingest", None) or "02:00").strip() or "02:00"


def _enforced(cfg: Any, tier: Figure) -> tuple[int, str]:
    """The screen step's own budget (``microbatch.night_budget``, called here so the two never differ) and where it
    came from: a setting, the tier record or the fallback."""
    import os

    from orchestrator.scenarios import microbatch

    n = microbatch.night_budget(cast(Any, SimpleNamespace(cfg=cfg)))
    configured = int(getattr(cfg.env, "microbatch_night_budget", microbatch.DEFAULT_NIGHT_BUDGET))
    if configured != microbatch.DEFAULT_NIGHT_BUDGET or (os.environ.get("TB_MICROBATCH_NIGHT_BUDGET") or "").strip():
        return n, "setting"
    return n, "tier record" if tier.measured else "fallback"


def _safe(ingest: str, steps: tuple[str, ...], kind: str) -> NightPlan:
    none = Figure("", "malformed")
    return NightPlan(
        profile=None,
        safe=True,
        ingest=ingest,
        steps=steps,
        models_on_card=none,
        screen_concurrency=none,
        night_budget=none,
        judge_calls_per_second=none,
        budget_patients=-1,
        budget_from="unknown",
        warnings=(f"night plan: not built ({kind}): the night runs as configured",),
    )


def build(cfg: Any) -> NightPlan:
    """The night plan of this box (``cfg``: the orchestrator's config, with ``settings`` and ``env``). The tier record
    is the one the screen step reads (``TB_PROFILE`` from the process, ``tier_value.TIERS_DIR``). Never raises: a
    plan that cannot be built is the safe plan with a warning."""
    from orchestrator import night

    ingest = _ingest_of(getattr(cfg, "settings", None))
    steps = ("ingest", *night.STEPS)
    try:
        models = _figure("models_on_card", count=False)
        budget = tier_budget()
        patients, came_from = _enforced(cfg, budget)
        warnings: list[str] = []
        if models.measured and str(models.value) not in _RESIDENCY:
            warnings.append(
                f"night plan: the tier record measured models_on_card {models.value!r}; the screen step still asks "
                "each study's configured judge (the record and the configuration differ)"
            )
        if budget.case == "over_limit":
            warnings.append(f"night plan: the tier's night budget is {budget.text()}")
        if patients == 0 or patients > STATED_PATIENT_LIMIT:
            shown = "no limit" if patients == 0 else f"{patients}"
            warnings.append(
                f"night plan: the configured night budget ({shown}) is over the stated limit of "
                f"{STATED_PATIENT_LIMIT:,} patients"
            )
        return NightPlan(
            profile=tier_value.profile_of(),
            safe=not models.measured,
            ingest=ingest,
            steps=steps,
            models_on_card=models,
            screen_concurrency=_figure("screen_concurrency", count=True),
            night_budget=budget,
            judge_calls_per_second=_figure("judge_calls_per_second", count=False),
            budget_patients=patients,
            budget_from=came_from,
            warnings=tuple(warnings),
        )
    except Exception as exc:  # the plan is words at start: it never stops the scheduler
        return _safe(ingest, steps, type(exc).__name__)


def say(plan: NightPlan) -> None:
    """Log the plan at the scheduler's start."""
    for i, line in enumerate(plan.lines()):
        (log.info if i == 0 else log.warning)("%s", line)


__all__ = ["STATED_PATIENT_LIMIT", "Figure", "NightPlan", "build", "say", "tier_budget"]
