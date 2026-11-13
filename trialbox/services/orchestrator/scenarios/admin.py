"""STATUS, CANCEL and INGEST jobs."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from tb_common.db import ENV
from tb_common.subject import job_subject
from tb_contracts import IngestReport, IngestRequest, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_language, job_markdown
from orchestrator.i18n import t

log = logging.getLogger("orchestrator.admin")


def _ingest_errors(report: IngestReport) -> str:
    """D-557: the report's error lines can hold an error's own text (a validator that failed to run); the job's
    record says how many there are and where they are, the published ingest report holds the lines."""
    n = len(report.errors or [])
    return f"The nightly ingest finished with {n} error(s): see ingest_report_{report.snapshot}.json."


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
    # T-725 (D-491, review F-4): the build of "twin" from this night's generation; an older night is refused and
    # the newer twins stay (a late re-run of an earlier night superseded them before)
    from datacore.generations import generation_of, guarded

    night = str(snapshot)

    def build() -> object:
        # review of T-725 (H2): the build never raises and answers None when it could not run; a build that did
        # not run, or that failed for a patient, is not a finished build (the ledger keeps "building")
        rep = build_twins(orch_db, lake, night, datetime.now(UTC).isoformat(timespec="seconds"))
        if rep is None:
            raise RuntimeError("the twin build did not run")
        if rep.failed:
            raise RuntimeError(f"the twin build failed for {len(rep.failed)} patient(s)")
        return rep

    try:
        guarded("twin", generation_of(lake, night), build)
    except Exception as exc:  # neither the ledger's failure nor the build's fails the ingest
        log.warning("twin build after the ingest is not finished (%s: %s)", type(exc).__name__, exc)


def ingest(ctx: Ctx) -> Outcome:
    if ctx.services.adapter is None:
        raise StepFailed("running", "adapter service not configured")
    ctx.state("running")
    ds = ctx.cfg.settings.data_source
    opts = ctx.job.options or {}
    # NEW-PERF-2 (D-523): the adapter run this job is on is written into its record as soon as it is known.
    # ``followed``: the run was already running (this job queued again after a restart, or another caller's run)
    on = {"run": "", "followed": False, "own": False}

    def on_run(rid: str, followed: bool) -> None:
        on.update(run=rid, followed=followed, own=opts.get("adapter_run") == rid)
        ctx.update(options={**opts, "adapter_run": rid, **({"followed": "1"} if followed and not on["own"] else {})})

    req = IngestRequest(source=ds.type, since=opts.get("since"))
    follow = getattr(ctx.services.adapter, "run_followed", None)
    report = follow(req, on_run) if follow is not None else ctx.services.adapter.run(req)
    ctx.update(snapshot_date=report.snapshot)
    if on["followed"] and not on["own"]:
        if opts.get("since"):  # review F3: "done" would say a back-fill ran that did not
            raise StepFailed(
                "ingest",
                f"Another ingest was running (adapter run {on['run']}) and this job followed it to its end; this "
                "job's own request (with since=) was not run. Send it again.",
            )
        # review F1: the steps that follow an ingest run once for an adapter run, in the first job that is on it
        mine = ctx.job.job_id
        others = [j for j in ctx.orch.db.with_option("INGEST", "adapter_run", str(on["run"]))
                  if j.job_id != mine and j.state != "failed"]  # fmt: skip
        if any((j.received_at, j.job_id) < (ctx.job.received_at, mine) for j in others):
            if not report.passed:
                raise StepFailed("ingest", _ingest_errors(report))
            return Outcome(
                summary_md=f"Ingest {report.snapshot}: passed. This job followed a run another job started; the "
                "steps that follow the ingest run in that job."
            )
    ctx.state("reporting")
    body = json.dumps(dump(report), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ctx.publish(f"ingest_report_{report.snapshot}.json", body, "aggregate", [])
    if not report.passed:
        raise StepFailed("ingest", _ingest_errors(report))
    from orchestrator import derive
    from orchestrator.scheduler import after_ingest

    # D-442: the stored derived rows of the new snapshot before anything screens it
    derive.after_ingest(getattr(ctx, "orch", None), str(report.snapshot))
    # D-397: the new patients booked in each study's window are screened now, not next week
    # T-726 (D-492): the timer's ingest on a box whose scheduler runs is followed by the night's chain, which
    # starts when this job has ended (its end is what the chain reads); an ingest by hand as before
    if opts.get("chain") != "1":
        after_ingest(ctx.orch, timed=opts.get("timer") == "1")
    twins_after_ingest(ctx, report.snapshot)
    return Outcome(summary_md=f"Ingest {report.snapshot}: passed.")
