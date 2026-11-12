"""The site's trial-opportunity feed (D-467): every recruiting ClinicalTrials.gov study in the site's areas, counted.

For each condition in ``site_params.yaml`` ``opportunity.conditions`` (the site's therapeutic areas), the compiler's
``/ctgov/search`` returns the recruiting studies (live, offline refdata pack or cassette, as the hospital chose at
install, D-140); the top ``per_condition`` by :func:`orchestrator.scenarios.trials.rank` are counted with the same
automatic compile and lake counts as COHORT's trial simulation (:func:`simulate_one`). The rows are reduced to the
publishable feed (:mod:`tb_common.opportunity`) and audited; signing and the hand-over to the hub are the caller's
(``tools/opportunity_feed.py``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tb_common import opportunity as opp
from tb_contracts import CtgovSearchRequest

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.scenarios.trials import rank, simulate_one


def build_feed(
    ctx: Ctx,
    *,
    site_id: str,
    site_label: str,
    country: str,
    conditions: list[str],
    snapshot: str,
    per_condition: int = 20,
    threshold: int = opp.DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    run_date = min(ctx.today(), date.fromisoformat(snapshot))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources: set[str] = set()
    for cond in conditions:
        found = ctx.services.compiler.ctgov_search(CtgovSearchRequest(condition=cond))
        sources.add(str(found.source))
        for s in rank([s for s in found.studies if s.nct_id not in seen], per_condition):
            seen.add(s.nct_id)
            try:
                sim = simulate_one(ctx, s, run_date, snapshot, threshold)
            except StepFailed as exc:
                rows.append(
                    {
                        **opp.row_from_sim(
                            {"nct_id": s.nct_id, "title": s.title, "last_update": s.last_update, "eligible_now": 0},
                            cond,
                            threshold,
                        ),
                        "note": f"not counted: {exc.message}"[:300],
                    }
                )
                continue
            rows.append(opp.row_from_sim(sim.model_dump(mode="json"), cond, threshold))
    feed = opp.build(
        site_id=site_id,
        site_label=site_label,
        country=country,
        snapshot=snapshot,
        registry_source=",".join(sorted(sources)),
        registry_sha256=None,
        conditions=conditions,
        rows=rows,
        threshold=threshold,
    )
    ctx.orch.audit.append(
        "opportunity.feed",
        job_id=ctx.job.job_id,
        detail={"conditions": conditions, "trials": [r["nct_id"] for r in rows], "threshold": threshold},
    )
    return feed
