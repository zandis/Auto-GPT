"""Trial simulation inside COHORT (SPEC §8.3, DECISIONS D-74).

recruiting = criteria-compiler ``/ctgov/search`` (ClinicalTrials.gov API v2, or its cassette offline)
top-N      = Taiwan sites first, then later phase, larger target, newer update, NCT id
per trial  = eligibility text -> doc-parser -> compiler (automatic draft, never approved; cached by NCT id + last
             update for ``settings.cohort.ctgov_cache_days``) -> FEAS counts in the lake -> FEAS simulation
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, cast

from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import (
    CompileRequest,
    CtgovSearchRequest,
    CtgovStudy,
    ParseRequest,
    TrialSimResult,
    TrialSimRow,
    TrialSimStep,
    dump_json,
)

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.scenarios import feas_compute as fc

PHASE_RANK = {"PHASE4": 1, "PHASE1": 1, "PHASE2": 2, "PHASE3": 3, "EARLY_PHASE1": 0, "NA": 0}


def rank(studies: list[CtgovStudy], top_n: int) -> list[CtgovStudy]:
    def key(s: CtgovStudy) -> tuple[Any, ...]:
        taiwan = "Taiwan" in (s.countries or [])
        phase = max((PHASE_RANK.get(p, 0) for p in s.phases or []), default=0)
        return (not taiwan, -phase, -(s.enrollment or 0), _neg_date(s.last_update), s.nct_id)

    return sorted(studies, key=key)[: max(top_n, 0)]


def _neg_date(d: Any) -> int:
    return -date.fromisoformat(str(d)).toordinal()


def _rates(ctx: Ctx, rs_id: str) -> tuple[float, float]:
    cd = ctx.cfg.settings.calibration_defaults
    reach = float(cd.reach_rate if cd and cd.reach_rate is not None else 0.6)
    accept = float(cd.accept_rate if cd and cd.accept_rate is not None else 0.35)
    return reach, accept


def _compiled(ctx: Ctx, s: CtgovStudy, run_date: date) -> tuple[Ruleset, float | None, date]:
    """Draft ruleset for one study (cache hit or a fresh automatic compile)."""
    from orchestrator.scenarios.cohort import load_draft

    cs = ctx.cfg.settings.cohort
    days = int(cs.ctgov_cache_days if cs and cs.ctgov_cache_days else 30)
    hit = ctx.orch.db.trial_cache_get(s.nct_id, str(s.last_update))
    if hit and datetime.fromisoformat(hit["compiled_at"]).date() >= run_date - timedelta(days=days):
        return load_draft(ctx.store.get(hit["draft_zip_key"])), hit["equivalence_pct"], _day(hit["compiled_at"])
    base = f"ctgov/{s.nct_id}/{s.last_update}"
    text_key = f"{base}/{s.nct_id}_eligibility.txt"
    ctx.store.put(text_key, s.eligibility_text.encode("utf-8"), "text/plain")
    parsed = ctx.services.parser.parse(ParseRequest(minio_key=text_key, job_id=ctx.job.job_id))
    parsed_key = f"{base}/parsed.json"
    ctx.store.put(parsed_key, dump_json(parsed).encode("utf-8"), "application/json")
    if not (parsed.ie_block.inclusion or parsed.ie_block.exclusion):
        raise StepFailed("compiling", f"{s.nct_id}: no eligibility criteria found in the registry text")
    res = ctx.services.compiler.compile(
        CompileRequest(
            job_id=ctx.job.job_id,
            ruleset=s.nct_id,
            parsed_doc_key=parsed_key,
            kind=cast(Any, "trial"),
            title=s.title,
            requested_by=ctx.job.requested_by,
            options={"index_date": run_date.isoformat(), "incremental": "false"},
        )
    )
    if not res.draft_zip_key:
        raise StepFailed("compiling", f"{s.nct_id}: compiler returned no draft package")
    pct = res.tests.overall_pct if res.tests else None
    compiled_at = ctx.orch._now().isoformat(timespec="seconds")
    ctx.orch.db.trial_cache_put(
        {
            "nct_id": s.nct_id,
            "last_update": str(s.last_update),
            "version": res.version,
            "draft_zip_key": res.draft_zip_key,
            "equivalence_pct": pct,
            "compiled_at": compiled_at,
        }
    )
    return load_draft(ctx.store.get(res.draft_zip_key)), pct, _day(compiled_at)


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso).date()


def simulate_one(ctx: Ctx, s: CtgovStudy, run_date: date, snapshot: str, sc: int) -> TrialSimRow:
    rs, pct, compiled_on = _compiled(ctx, s, run_date)
    reach, accept = _rates(ctx, rs.id)
    p = fc.FeasParams(
        run_date=run_date,
        snapshot=snapshot,
        lookback_months=12,
        small_cell=sc,
        reach_rate=reach,
        accept_rate=accept,
        rate_source="settings.calibration_defaults",
        months=12,
        iterations=500,
    )
    _, raw = fc.compute(ctx.services.lake, rs, p)
    months = max(len(raw.index_dates), 1)
    monthly = sum(raw.first_eligible.values()) / months
    seed = int(hashlib.sha256(f"{s.nct_id}|{s.last_update}|{snapshot}".encode()).hexdigest()[:8], 16)
    sim = fc.simulate(
        prevalent=raw.prevalent,
        monthly_rate=monthly,
        reach=reach,
        accept=accept,
        capacity=None,
        months=12,
        iterations=500,
        seed=seed,
    )
    steps = fc.steps(rs)
    applied = [st for st in steps if st.applied]
    final = applied[-1].id if applied else None
    eligible = suppress(raw.remaining[final], sc) if final else suppress(raw.start_n, sc)
    small = isinstance(eligible, str)
    return TrialSimRow(
        nct_id=s.nct_id,
        title=s.title,
        phases=list(s.phases or []),
        countries=list(s.countries or []),
        sponsor=s.sponsor,
        last_update=s.last_update,
        target_enrollment=s.enrollment,
        ruleset_version=rs.version,
        criteria_total=len(steps),
        criteria_applied=len(applied),
        equivalence_pct=pct,
        eligible_now=eligible,
        new_per_month=None if small else round(monthly, 1),
        enrol_12m_low=None if small else sim["low"],
        enrol_12m_mid=None if small else sim["mid"],
        enrol_12m_high=None if small else sim["high"],
        draft_compiled_on=compiled_on,
        steps=[
            TrialSimStep(
                criterion_id=st.id,
                label=st.criterion.label or st.criterion.text,
                applied=st.applied,
                remaining=suppress(raw.remaining[st.id], sc) if st.applied else None,
            )
            for st in steps
        ],
        note="automatic compile of the registry text; not reviewed"
        + ("" if len(applied) == len(steps) else f"; {len(steps) - len(applied)} criteria not countable in the lake"),
    )


def simulate_for(ctx: Ctx, rs: Ruleset, q_end: date, snapshot: str) -> TrialSimResult | None:
    cfg = rs.manifest.cohort
    if cfg is None or not cfg.ctgov_condition:
        return None
    from orchestrator.scenarios.screen import small_cell

    found = ctx.services.compiler.ctgov_search(CtgovSearchRequest(condition=cfg.ctgov_condition))
    picked = rank(list(found.studies), int(cfg.top_n_trials or 3))
    run_date = min(ctx.today(), date.fromisoformat(snapshot))
    sc = small_cell(ctx, rs)
    rows = []
    for s in picked:
        try:
            rows.append(simulate_one(ctx, s, run_date, snapshot, sc))
        except StepFailed as exc:
            rows.append(
                TrialSimRow(
                    nct_id=s.nct_id,
                    title=s.title,
                    last_update=s.last_update,
                    criteria_total=0,
                    criteria_applied=0,
                    eligible_now=0,
                    note=f"not simulated: {exc.message}",
                )
            )
    reach, accept = _rates(ctx, rs.id)
    ctx.orch.audit.append(
        "cohort.trials",
        job_id=ctx.job.job_id,
        ruleset=rs.id,
        detail={"source": found.source, "condition": cfg.ctgov_condition, "trials": [r.nct_id for r in rows]},
    )
    return TrialSimResult(
        ruleset=rs.id,
        condition=cfg.ctgov_condition,
        run_date=run_date,
        snapshot=date.fromisoformat(snapshot),
        source=found.source,
        reach_rate=reach,
        accept_rate=accept,
        rows=rows,
    )
