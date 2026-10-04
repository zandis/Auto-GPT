"""STATUS, CANCEL and INGEST jobs."""

from __future__ import annotations

import json

from tb_contracts import IngestRequest, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_markdown


def _target(ctx: Ctx) -> str:
    target = (ctx.job.options or {}).get("target")
    if not target:
        raise StepFailed("received", "Give the job id, e.g. STATUS 01J…")
    return target


def status(ctx: Ctx) -> Outcome:
    target = ctx.orch.db.get(_target(ctx))
    if target is None:
        raise StepFailed("received", f"No job {_target(ctx)} on this box.")
    body = f"Job `{target.job_id}` is **{target.state}**.\n\n" + job_markdown(target)
    return Outcome(
        summary_md=body,
        deliveries=[
            Delivery(
                to=[ctx.job.requested_by],
                subject=f"Status {target.job_id} — {target.state}",
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
    return Outcome(summary_md=f"Ingest {report.snapshot}: passed.")
