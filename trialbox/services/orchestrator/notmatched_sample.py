"""The weekly PI sample of "criteria not matched" (T-310a, D-446; URS-PI-05, CR-014).

Every week (``schedule.not_matched_sample``, default ``MON 06:00`` in the site's zone, after the Monday night runs)
the orchestrator draws, for each study with a finished SCREEN that stored its not-matched list, ten of those patients
for the study's PI and stores them in schema ``tuned`` (:mod:`tb_common.notmatched`). The console shows them on
``/studies/{rs}/not-matched/sample``, where the PI answers each one.

* **The run's own snapshot.** The draw reads the run's stored list (``excluded_*.json``), which the run made from the
  snapshot it pinned (T-305a, D-383), and records that snapshot. It never asks the lake: a night published since the
  run does not change what was sampled.
* **Opted-out patients** (``tb_common.optout.opted_out``) are never drawn. A register that cannot be read stops the
  whole draw (logged), never a sample with someone who said no.
* **Held studies.** Where the list waits for the site's check (``TB_NOT_MATCHED_GATE``), a study whose check has not
  passed is skipped and the skip audited (``notmatched.held``).
* One sample per study and week: a second call (or the console drawing first on a page view) keeps the first one.

Each sample drawn is the audit event ``notmatched.sample`` (study, run, snapshot, week, size).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from tb_common.notmatched import NotMatchedStore, gate_on, iso_week, sample_week
from tb_common.optout import opted_out

if TYPE_CHECKING:
    from tb_contracts import Job

log = logging.getLogger("orchestrator.notmatched_sample")
DEFAULT_AT = "MON 06:00"
BY = "scheduler"


def latest_screens(orch: Any) -> list[Job]:
    """Per study, its latest finished SCREEN that stored a not-matched list (newest first in the job table)."""
    out: dict[str, Job] = {}
    for job in orch.db.find(type_="SCREEN", state="done", limit=500):
        rid = (job.ruleset or "").upper()
        if rid and rid not in out and _excluded_key(job):
            out[rid] = job
    return [out[k] for k in sorted(out)]


def _excluded_key(job: Job) -> str | None:
    for o in job.outputs or []:
        if o.filename.startswith("excluded_") and o.filename.endswith(".json"):
            return str(o.minio_key)
    return None


def weekly(orch: Any, today: date | None = None, store: NotMatchedStore | None = None,
           env: dict[str, str] | None = None) -> dict[str, int]:  # fmt: skip
    """Draw this week's sample for every study. Returns {study: patients drawn by this call} (0: kept the sample
    the week has, or nothing to draw). Never raises: the timer must keep running."""
    from tb_common.timeutil import today as site_today

    environ = env if env is not None else dict(os.environ)
    from orchestrator.scheduler import restore_held

    if (
        restore_held()
    ):  # NEW-B-3 (D-522): the sample filters by the opt-out register, which a restore may not have whole
        log.warning("not-matched sample not drawn: the box is held after a restore")
        return {}
    try:
        gated = gate_on(environ)
        gone = opted_out()  # raises when the register does not answer: no sample rather than one with an opt-out
    except Exception as exc:
        log.error("not-matched sample not drawn: %s", exc)
        return {}
    day = today or site_today(orch.cfg.env.tz)
    week = iso_week(day)
    st = store or NotMatchedStore()
    done: dict[str, int] = {}
    try:
        for job in latest_screens(orch):
            rid = (job.ruleset or "").upper()
            try:
                if not st.shown(rid, gated):
                    orch.audit.append("notmatched.held", ruleset=rid, detail={"week": week})
                    continue
                key = _excluded_key(job)
                doc = json.loads(orch.store.get(key)) if key else None
                if not isinstance(doc, dict):
                    continue
                snapshot = job.snapshot_date.isoformat() if job.snapshot_date else str(doc.get("snapshot") or "")
                rows, drawn = sample_week(st, rid, week, doc, job_id=job.job_id, snapshot=snapshot, gone=gone, by=BY,
                                          at=datetime.now(UTC).isoformat())  # fmt: skip
                done[rid] = len(rows) if drawn else 0
                if drawn:
                    detail = {"week": week, "n": len(rows), "snapshot": snapshot, "by": BY}
                    orch.audit.append("notmatched.sample", ruleset=rid, job_id=job.job_id, detail=detail)
            except Exception as exc:  # one study's failure does not stop the others
                log.exception("not-matched sample of %s not drawn: %s", rid, exc)
    finally:
        if store is None:
            st.close()
    return done
