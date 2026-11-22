"""APPROVE (SPEC §5 approval loop): apply the reviewer's workbook through the compiler; on approval resume the jobs
that were waiting for this ruleset version, on edits re-send the review (max 3 rounds)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from criteria_compiler.semantics import human_heavy
from tb_common.ruleset import Ruleset, RulesetNotApproved, load_approved
from tb_common.steptime import COMPILER_STEPS, StepClock, numbers_only
from tb_contracts import ApproveRequest, JobFile

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.scenarios.review import recipients, review_delivery

log = logging.getLogger("orchestrator")


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


def amendment_options(options: dict[str, str]) -> dict[str, Any]:
    """D-364: ``effective=YYYY-MM-DD irb=<number> irbdate=YYYY-MM-DD`` on the APPROVE line, for the compiler."""
    out: dict[str, Any] = {}
    for key, field in (("effective", "effective_from"), ("irbdate", "irb_approved_on")):
        if options.get(key):
            try:
                out[field] = date.fromisoformat(options[key])
            except ValueError as exc:
                raise StepFailed("approve", f"{key}= must be a date YYYY-MM-DD") from exc
    if options.get("irb"):
        out["irb_reference"] = options["irb"]
    return out


def _approved(ctx: Ctx, ruleset: str, version: str) -> Ruleset | None:
    try:
        return load_approved(ctx.rulesets_dir, ruleset, version)
    except RulesetNotApproved:
        return None


def issue_on_approval(ctx: Ctx, ruleset: str, version: str) -> str | None:
    """Gate 4: a version approved during the day gets its SCREEN record for the night's published generation from
    gate 4's one writer, the function the night calls, with the same tamper and staleness checks, audited there.
    No published generation yet (or any refusal): the approval stands and a list asked for later is refused with
    the plain reason until a night publishes. Returns the record's hash, or None."""
    from tb_common.screening_inputs import ScreeningRefused, issue_screening_record

    try:
        generation = ctx.orch.services.lake.generation(recover=True) or ""
    except Exception as exc:  # no served generation: the gate refuses and audits it
        log.warning("no served generation at the approval of %s v%s (%s)", ruleset, version, type(exc).__name__)
        generation = ""
    try:
        return issue_screening_record(
            ctx.cfg.settings,
            root=Path(ctx.cfg.env.data_dir),
            repo_dir=Path(ctx.rulesets_dir),
            generation=generation,
            study=ruleset,
            version=version,
            db_url=ctx.orch.db.url,
            audit=ctx.orch.audit,
            actor=ctx.job.requested_by,
        )
    except ScreeningRefused:
        return None


def _compiler_steps(clock: StepClock, steps: object) -> None:
    """H-45: the compiler's own steps, and the rest of the call as the HTTP round trip; no steps (a compiler that
    gave none): the whole call by its own name."""
    call = clock.since_mark()
    named = numbers_only(steps if isinstance(steps, dict) else None)
    named = {k: v for k, v in named.items() if k in COMPILER_STEPS}
    if named:
        for k, v in named.items():
            clock.add(k, v)
        clock.add("orch.compiler_transport", call - sum(named.values()))
    else:
        clock.add("orch.compiler_call", call)
    clock.mark()


def run(ctx: Ctx) -> Outcome:
    from criteria_compiler.review import parse_review_xlsx

    # H-45: each step's seconds on the monotonic clock; the job's run (core) adds the delivery and the remainder and
    # writes them with the job's metrics, on the write it makes anyway (success or failure)
    clock = ctx.step_clock = StepClock()
    ruleset, version = _target(ctx)
    ctx.update(ruleset=ruleset, ruleset_version=version)
    done = _approved(ctx, ruleset, version)
    clock.lap("orch.target")
    if done is not None:
        # already tagged: this APPROVE was re-run after a restart that interrupted it after the compiler approved, or
        # the reviewer replied twice. Nothing to compile; the record is issued if it was not, the waiting jobs resume.
        issue_on_approval(ctx, ruleset, version)
        resumed = ctx.orch.resume_awaiting(ruleset, version)
        clock.lap("orch.resume_awaiting")
        body = f"Ruleset **{ruleset} v{version}** is already approved; nothing was changed.\n\n" + (
            f"Resumed waiting jobs: {', '.join(f'`{j}`' for j in resumed)}.\n" if resumed else ""
        )
        approved_routing = done.manifest.routing
        return Outcome(
            summary_md=body,
            deliveries=[
                Delivery(
                    to=recipients(approved_routing, ctx.job.requested_by),
                    subject=f"[{ruleset}] ruleset v{version} approved",
                    body_md=body,
                    kind="approved",
                    routing=approved_routing,
                )
            ],
        )
    clock.mark()
    ctx.state("compiling")
    clock.lap("orch.state")
    wb = _workbook(ctx)
    try:
        data = ctx.input_bytes(wb)
        clock.lap("orch.read_workbook")
        decisions, meta = parse_review_xlsx(data)
    except ValueError as exc:
        raise StepFailed("approve", f"{wb.filename}: {exc}") from exc
    except Exception as exc:  # not an xlsx at all
        raise StepFailed("approve", f"The workbook {wb.filename} could not be read as a TrialBox review.xlsx.") from exc
    if meta.get("ruleset") and meta["ruleset"].upper() != ruleset:
        raise StepFailed("approve", f"The workbook is for ruleset {meta['ruleset']}, not {ruleset}.")
    if meta.get("version") and meta["version"] != version:
        raise StepFailed("approve", f"The workbook is for version {meta['version']}, not the version= of the request.")
    clock.lap("orch.parse_review")
    via = "web console" if (ctx.job.comment or "").startswith("web console") else "e-mail"
    compiler = ctx.services.compiler
    req = ApproveRequest(
        ruleset=ruleset,
        version=version,
        by=ctx.job.requested_by,
        job_id=ctx.job.job_id,
        via=via,
        decisions=decisions,
        **amendment_options(ctx.job.options or {}),
    )
    clock.mark()
    try:
        res = compiler.approve(req)
    except BaseException:
        clock.lap("orch.compiler_call")
        raise
    _compiler_steps(clock, getattr(res, "step_seconds", None))
    routing = res.manifest.routing if res.manifest else None
    to = recipients(routing, ctx.job.requested_by)
    if res.status == "approved":
        assert res.manifest is not None
        import yaml

        manifest = yaml.safe_dump(
            res.manifest.model_dump(mode="json", by_alias=True, exclude_none=True), allow_unicode=True, sort_keys=False
        )
        out = ctx.publish(f"manifest_{ruleset}_v{version}.yaml", manifest.encode("utf-8"), "aggregate", to)
        clock.lap("orch.publish")
        issue_on_approval(ctx, ruleset, version)  # before the waiting lists run again
        resumed = ctx.orch.resume_awaiting(ruleset, version)
        clock.lap("orch.resume_awaiting")
        rev = res.manifest.review
        split = dict(rev.split.model_dump()) if rev and rev.split else {}
        split = {k: int(v or 0) for k, v in split.items()}
        body = (
            f"Ruleset **{ruleset} v{version}** is approved by {ctx.job.requested_by} via {via} (tag `{res.tag}`, "
            f"review round {res.round}). The box now uses it for counts and candidate lists; a person still confirms "
            f"each candidate.\n\n"
        )
        m = res.manifest
        if m.effective_from and m.effective_from > ctx.orch.today():
            body += (
                f"It takes effect on {m.effective_from}: until then the box keeps screening on the version before "
                f"it.\n\n"
            )
        if m.irb_reference or m.irb_approved_on:
            body += f"IRB approval of this protocol version: {m.irb_reference or '-'} ({m.irb_approved_on or '-'}).\n\n"
        if split:
            body += (
                f"Approval record: {split.get('structured', 0)} criteria by the filter, {split.get('mixed', 0)} by the "
                f"filter then the model, {split.get('note', 0)} by the model on notes, {split.get('human', 0)} by a "
                f"person at screening; the approver confirmed this routing.\n\n"
            )
            if human_heavy(split):
                body += (
                    "**Note:** at least half of the criteria are left to a person, so the box does little of the "
                    "screening for this trial. If that is not intended, edit the class column and re-approve.\n\n"
                )
        body += f"Resumed waiting jobs: {', '.join(f'`{j}`' for j in resumed)}.\n" if resumed else ""
        return Outcome(
            summary_md=body,
            deliveries=[
                Delivery(
                    to=to,
                    outputs=[out],
                    subject=f"[{ruleset}] ruleset v{version} approved",
                    body_md=body,
                    kind="approved",
                    routing=routing,
                )
            ],
        )
    if res.status == "needs_review":
        assert res.review_html_key and res.review_xlsx_key and res.draft_zip_key
        clock.mark()
        review = review_delivery(
            ctx, ruleset, version, routing, res.review_html_key, res.review_xlsx_key, res.draft_zip_key, res.round
        )
        clock.lap("orch.review_delivery")
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
    clock.mark()
    ctx.orch.fail_awaiting(ruleset, version, "approve", reason)
    clock.lap("orch.fail_awaiting")
    return Outcome(summary_md=reason + (" " + "; ".join(res.blocking) if res.blocking else ""))
