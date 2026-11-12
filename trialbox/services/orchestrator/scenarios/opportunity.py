"""The site's trial-opportunity feed (D-467): the steward's approved recruiting studies, counted in the site's lake.

For each condition (the site's therapeutic areas), the compiler's ``/ctgov/search`` returns the recruiting studies
(live, offline refdata pack or cassette, as the hospital chose at install, D-140). Only studies on the steward's
approved list are counted (an empty list counts and publishes nothing), at most ``per_condition_cap`` per condition
(a declared setting), ranked as COHORT ranks them. Each is counted with COHORT's automatic compile and the FEAS lake
counts, as of the first day of the publication period, with the patients on the opt-out register (as of the job's
receipt, the way SCREEN reads it) left out of every count. The exact counts stay here;
:func:`tb_common.opportunity.build` reduces them to the feed. Signing and the hand-over are the caller's
(``tools/opportunity_feed.py``, T-741, T-742).

A study that cannot be counted is a row with a fixed reason code; the failure's message never reaches the feed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from tb_common import opportunity as opp
from tb_contracts import CtgovSearchRequest, CtgovStudy

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.scenarios import feas_compute as fc
from orchestrator.scenarios.trials import _compiled, _rates, rank

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def registry_label(candidates: Iterable[str | None], registry_text: str, n: int) -> str:
    """A criterion's label only as it stands in the public registry text; otherwise a fixed ``criterion n``."""
    hay = _norm(registry_text)
    for c in candidates:
        if c and len(_norm(c)) >= 3 and _norm(c) in hay:
            return _WS.sub(" ", c).strip()
    return f"criterion {n}"


def _meta(s: CtgovStudy, cond: str) -> dict[str, Any]:
    return {
        "nct_id": s.nct_id,
        "title": s.title,
        "condition": cond,
        "phases": tuple(s.phases or ()),
        "sponsor": s.sponsor,
        "countries": tuple(s.countries or ()),
        "last_update": str(s.last_update),
        "target_enrollment": s.enrollment,
    }


def count_study(
    ctx: Ctx, s: CtgovStudy, cond: str, run_date: date, snapshot: str, gone: frozenset[str], threshold: int
) -> opp.StudyCounts:
    """The exact counts of one study in the site's lake, without the opted-out patients (never published as such)."""
    meta = _meta(s, cond)
    try:
        rs, _pct, _on = _compiled(ctx, s, run_date)
    except StepFailed:
        return opp.StudyCounts(**meta, reason="not_compiled")
    steps = fc.steps(rs)
    applied = [st for st in steps if st.applied]
    if not applied:
        return opp.StudyCounts(**meta, criteria_total=len(steps), reason="no_countable_criteria")
    p = fc.FeasParams(
        run_date=run_date,
        snapshot=snapshot,
        lookback_months=12,
        small_cell=threshold,
        iterations=1,  # FEAS's own band is not used here: the feed's band comes from rounded inputs (D-467 rule 5)
        exclude_pids=gone,
    )
    try:
        _, raw = fc.compute(ctx.services.lake, rs, p)
    except (StepFailed, fc.FeasError):
        return opp.StudyCounts(**meta, criteria_total=len(steps), reason="count_failed")
    return opp.StudyCounts(
        **meta,
        criteria_total=len(steps),
        criteria_applied=len(applied),
        steps=tuple(
            (registry_label((st.criterion.text, st.criterion.label), s.eligibility_text, i), raw.remaining[st.id])
            for i, st in enumerate(applied, start=1)
        ),
        prevalent=raw.prevalent,
        incident_12m=sum(raw.first_eligible.values()),
    )


def build_feed(
    ctx: Ctx,
    *,
    site_id: str,
    site_label: str,
    country: str,
    conditions: list[str],
    snapshot: str,
    approved: Iterable[str],
    per_condition_cap: int,
    period_days: int = opp.DEFAULT_PERIOD_DAYS,
    secret: bytes | None = None,
    threshold: int = opp.DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    ok = frozenset(approved)
    if not ok:
        raise opp.FeedRefused("the steward's approved list is empty: nothing is counted or published")
    period = opp.period_of(min(ctx.today(), date.fromisoformat(snapshot)), period_days)
    from orchestrator.decision_context import decision_of

    gone = decision_of(ctx).register()
    reach, accept = _rates(ctx, "")

    def simulate(prevalent: int, monthly: float, seed: int) -> dict[str, float]:
        out = fc.simulate(
            prevalent=prevalent,
            monthly_rate=monthly,
            reach=reach,
            accept=accept,
            capacity=None,
            months=12,
            iterations=500,
            seed=seed,
        )
        return {k: float(out[k]) for k in ("low", "mid", "high")}

    counts: list[opp.StudyCounts] = []
    seen: set[str] = set()
    sources: set[str] = set()
    for cond in conditions:
        found = ctx.services.compiler.ctgov_search(CtgovSearchRequest(condition=cond))
        sources.add(str(found.source))
        wanted = [s for s in found.studies if s.nct_id in ok and s.nct_id not in seen]
        for s in rank(wanted, per_condition_cap):
            seen.add(s.nct_id)
            counts.append(count_study(ctx, s, cond, period.start, snapshot, gone, threshold))
    feed = opp.build(
        site_id=site_id,
        site_label=site_label,
        country=country,
        period=period,
        snapshot=snapshot,
        registry_source=[x for x in sources if x in opp.REGISTRY_SOURCES],
        conditions=conditions,
        counts=counts,
        approved=ok,
        per_condition_cap=per_condition_cap,
        threshold=threshold,
        secret=secret,
        simulate=simulate,
    )
    ctx.orch.audit.append(
        "opportunity.feed",
        job_id=ctx.job.job_id,
        detail={
            "conditions": conditions,
            "counted": len(counts),
            "published": len(feed["rows"]),
            "period": feed["period"],
            "threshold": threshold,
            "opt_out_register": "optout",
        },
    )
    return feed
