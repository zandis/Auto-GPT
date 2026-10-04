"""APPROVE (SPEC §5 approval loop): apply the reviewer's workbook through the compiler; on approval resume the jobs
that were waiting for this ruleset version, on edits re-send the review (max 3 rounds)."""

from __future__ import annotations

from tb_contracts import ApproveRequest, JobFile

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.scenarios.review import recipients, review_delivery


def _workbook(ctx: Ctx) -> JobFile:
    books = [f for f in ctx.job.inputs or [] if f.filename.lower().endswith(".xlsx")]
    if not books:
        raise StepFailed("approve", "Attach the reviewed review.xlsx workbook to the APPROVE reply.")
    return sorted(books, key=lambda f: ("review" not in f.filename.lower(), f.filename))[0]


def _target(ctx: Ctx) -> tuple[str, str]:
    job = ctx.job
    ruleset = (job.ruleset or "").upper()
    version = (job.options or {}).get("version")
    if not version:
        waiting = ctx.orch.db.find(state="awaiting_approval", ruleset=ruleset, limit=1)
        if not waiting or not waiting[0].ruleset_version:
            raise StepFailed("approve", f"No draft of {ruleset} is waiting for approval; give version=<x.y.z>.")
        version = waiting[0].ruleset_version
    return ruleset, version


def run(ctx: Ctx) -> Outcome:
    from criteria_compiler.review import parse_review_xlsx

    ruleset, version = _target(ctx)
    ctx.update(ruleset=ruleset, ruleset_version=version)
    ctx.state("compiling")
    wb = _workbook(ctx)
    try:
        decisions, meta = parse_review_xlsx(ctx.input_bytes(wb))
    except ValueError as exc:
        raise StepFailed("approve", f"{wb.filename}: {exc}") from exc
    except Exception as exc:  # not an xlsx at all
        raise StepFailed("approve", f"The workbook {wb.filename} could not be read as a TrialBox review.xlsx.") from exc
    if meta.get("ruleset") and meta["ruleset"].upper() != ruleset:
        raise StepFailed("approve", f"The workbook is for ruleset {meta['ruleset']}, not {ruleset}.")
    if meta.get("version") and meta["version"] != version:
        raise StepFailed("approve", f"The workbook is for version {meta['version']}, not {version}.")
    res = ctx.services.compiler.approve(
        ApproveRequest(
            ruleset=ruleset, version=version, by=ctx.job.requested_by, job_id=ctx.job.job_id, decisions=decisions
        )
    )
    routing = res.manifest.routing if res.manifest else None
    to = recipients(routing, ctx.job.requested_by)
    if res.status == "approved":
        assert res.manifest is not None
        import yaml

        manifest = yaml.safe_dump(
            res.manifest.model_dump(mode="json", by_alias=True, exclude_none=True), allow_unicode=True, sort_keys=False
        )
        out = ctx.publish(f"manifest_{ruleset}_v{version}.yaml", manifest.encode("utf-8"), "aggregate", to)
        resumed = ctx.orch.resume_awaiting(ruleset, version)
        body = f"Ruleset **{ruleset} v{version}** is approved (tag `{res.tag}`, review round {res.round}).\n\n" + (
            f"Resumed waiting jobs: {', '.join(f'`{j}`' for j in resumed)}.\n" if resumed else ""
        )
        return Outcome(
            summary_md=body,
            deliveries=[
                Delivery(
                    to=to,
                    outputs=[out],
                    subject=f"Ruleset {ruleset} v{version} approved",
                    body_md=body,
                    kind="approved",
                    routing=routing,
                )
            ],
        )
    if res.status == "needs_review":
        assert res.review_html_key and res.review_xlsx_key and res.draft_zip_key
        review = review_delivery(
            ctx, ruleset, version, routing, res.review_html_key, res.review_xlsx_key, res.draft_zip_key, res.round
        )
        if res.blocking:
            review.body_md = (
                "**Not yet approvable:**\n\n"
                + "\n".join(f"- {b}" for b in res.blocking)
                + "\n\n"
                + (review.body_md or "")
            )
        return Outcome(summary_md=f"Review round {res.round} of {ruleset} v{version} sent.", deliveries=[review])
    reason = (
        f"Ruleset {ruleset} v{version} was rejected by the reviewer."
        if res.status == "rejected"
        else f"Ruleset {ruleset} v{version} reached the maximum number of review rounds without approval."
    )
    ctx.orch.fail_awaiting(ruleset, version, "approve", reason)
    return Outcome(summary_md=reason + (" " + "; ".join(res.blocking) if res.blocking else ""))
