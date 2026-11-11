"""STATUS, CANCEL and INGEST jobs."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from tb_common.db import ENV
from tb_common.subject import job_subject
from tb_contracts import IngestRequest, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_language, job_markdown
from orchestrator.i18n import t

log = logging.getLogger("orchestrator.admin")


def _target(ctx: Ctx) -> str:
    target = (ctx.job.options or {}).get("target")
    if not target:
        raise StepFailed("received", "Give the job id, e.g. STATUS 01J…")
    return target


def status(ctx: Ctx) -> Outcome:
    target = ctx.orch.db.get(_target(ctx))
    if target is None:
        raise StepFailed("received", f"No job {_target(ctx)} on this box.")
    body = t(job_language(ctx), "mail.status", job=target.job_id, state=target.state) + "\n\n" + job_markdown(target)
    return Outcome(
        summary_md=body,
        deliveries=[
            Delivery(
                to=[ctx.job.requested_by],
                subject=job_subject("status", target.type, target.ruleset, target.job_id, target.state),
                body_md=body,
                kind="status",
            )
        ],
    )


def cancel(ctx: Ctx) -> Outcome:
    tid = _target(ctx)
    target = ctx.orch.db.get(tid)
    if target is None:
        raise StepFailed("received", f"No job {tid} on this box.")
    if target.requested_by != ctx.job.requested_by and ctx.job.requested_by not in (ctx.cfg.settings.reviewers or []):
        raise StepFailed("received", "Only the requester or a reviewer can cancel a job.")
    done = ctx.orch.cancel(tid, ctx.job.requested_by)
    note = "was already finished" if done.state == "done" else f"is now {done.state} (cancel requested)"
    return Outcome(summary_md=f"Job `{tid}` {note}.")


def twins_after_ingest(ctx: Ctx, snapshot: object) -> None:
    """T-204 (D-440): the study patients' twins from the snapshot this ingest published (one step of the night; a
    confirmed fact reaches the twin with the publish that carries it). Never fails the ingest."""
    if not os.environ.get(ENV):
        return  # no trial database: there is no twin store (a bare test stack)
    from patient_profile.twin import after_ingest as build_twins

    try:
        orch_db, lake = ctx.orch.db, ctx.services.lake
    except Exception as exc:  # an orchestrator without its job store or lake (a test's stand-in): nothing to build
        log.warning("twin build after the ingest skipped (%s)", type(exc).__name__)
        return
    build_twins(orch_db, lake, str(snapshot), datetime.now(UTC).isoformat(timespec="seconds"))


def ingest(ctx: Ctx) -> Outcome:
    if ctx.services.adapter is None:
        raise StepFailed("running", "adapter service not configured")
    ctx.state("running")
    ds = ctx.cfg.settings.data_source
    opts = ctx.job.options or {}
    report = ctx.services.adapter.run(IngestRequest(source=ds.type, since=opts.get("since")))
    ctx.update(snapshot_date=report.snapshot)
    ctx.state("reporting")
    body = json.dumps(dump(report), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ctx.publish(f"ingest_report_{report.snapshot}.json", body, "aggregate", [])
    if not report.passed:
        raise StepFailed("ingest", "The nightly ingest finished with errors: " + "; ".join((report.errors or [])[:5]))
    from orchestrator.scheduler import after_ingest

    # D-397: the new patients booked in each study's window are screened now, not next week
    after_ingest(ctx.orch, timed=opts.get("timer") == "1")
    twins_after_ingest(ctx, report.snapshot)
    return Outcome(summary_md=f"Ingest {report.snapshot}: passed.")
