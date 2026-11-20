"""10E-12 (D-1259): the night's pre-filter funnel of a study, as the card on a finished nightly job's page.

:func:`night_card` is the whole rule, apart from the page so it can be asked directly: the pre-filter records
(``JobMetrics.prefilter``) of the study's finished MICROBATCH jobs of the job's ``run_date``, summed
(``tb_common.prefilter.night_funnel``; sums of per-job counts, not distinct patients). Exact counts: an internal page
(D-99). Only to an account the study's own candidate list admits (the first-load card's rule,
``Helpers.admits_candidates``; no break-glass grant opens it), asked before any other job is read.

None, and nothing on the page, when:

* the job is not a finished nightly job with a record (a job from before the record has none);
* the account is not admitted;
* the night's jobs cannot all be read (the newest ``limit`` of the study all belong to this night or a later one: an
  earlier job of the night may be missing; never a short count);
* a record of the night does not add up (a fault: logged with its count, never shown).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tb_common import prefilter

log = logging.getLogger(__name__)

#: how many of a study's newest finished nightly jobs the card reads (the orchestrator's cap on ``GET /jobs``)
NIGHT_JOBS = 500


def night_card(
    job: Any,
    user: Any,
    admits: Callable[[Any, str], bool] | None,
    list_jobs: Callable[..., list[Any]],
    limit: int = NIGHT_JOBS,
) -> dict[str, Any] | None:
    """The card's figures for ``user`` on ``job``'s page, or None (see the module)."""
    rec = job.metrics.prefilter if job.metrics is not None else None
    if job.type != "MICROBATCH" or job.state != "done" or rec is None or not job.ruleset or job.run_date is None:
        return None
    if admits is None or not admits(user, job.ruleset):
        return None
    night = job.run_date
    jobs = list_jobs(limit, "done", ruleset=job.ruleset, type_="MICROBATCH")
    if len(jobs) >= limit and all(j.run_date is None or j.run_date >= night for j in jobs):
        return None
    mine = {j.job_id: j for j in [*jobs, job]}
    f = prefilter.night_funnel(mine.values(), job.ruleset, night)
    if f is None:
        return None
    if f.faults:
        log.error("night funnel %s %s: %d pre-filter record(s) do not add up; not shown", f.ruleset, night, f.faults)
        return None
    drops = prefilter.STAGES[:-1]  # the last stage is what is left: listed
    rows = [{"key": s, "removed": f.drops[s], "left": f.remaining[i + 1]} for i, s in enumerate(drops)]
    return {"study": f.ruleset, "date": night.isoformat(), "jobs": f.jobs, "in_scope": f.in_scope,
            "rows": rows, "listed": f.listed}  # fmt: skip
