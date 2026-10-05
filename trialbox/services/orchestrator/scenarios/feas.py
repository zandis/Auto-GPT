"""FEAS scenario (SPEC §8.1): parse → (compile → review → await APPROVE) → funnel, sensitivity, monthly new,
simulation → feasibility PDF + XLSX + JSON (tag ``aggregate``) to ``routing.aggregate_to``."""

from __future__ import annotations

import json
from datetime import date

from tb_contracts import Settings, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.reports import feasibility_pdf, feasibility_xlsx
from orchestrator.reports.common import ReportMeta, fmt_count
from orchestrator.scenarios import calibration
from orchestrator.scenarios.feas_compute import FeasError, FeasParams, compute, parse_variant_option, raw_json
from orchestrator.scenarios.review import approved_or_none, compile_draft, protocol_input, recipients, require_approved


def capacity(settings: Settings, practitioners: list[str] | None) -> float | None:
    """Sum of investigator capacity for the ruleset's screening practitioners (all practitioners if none listed)."""
    pr = settings.practitioners or {}
    ids = practitioners or sorted(pr)
    caps = [pr[p].capacity_per_month for p in ids if p in pr and pr[p].capacity_per_month is not None]
    return float(sum(c for c in caps if c is not None)) if caps else None


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    rs_id = (job.ruleset or "").upper()
    opts = dict(job.options or {})
    approved = approved_or_none(ctx, rs_id, opts.get("version"))
    resumed = approved is not None and job.ruleset_version == approved.version
    doc = protocol_input(ctx)
    if doc is not None and not resumed:
        review = compile_draft(ctx, rs_id, doc, approved, "trial")
        if review is not None:
            return Outcome(state="awaiting_approval", deliveries=[review])
    rs = approved if approved is not None else require_approved(ctx, rs_id, opts.get("version"))
    ctx.update(ruleset_version=rs.version)
    ctx.state("running")
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        raise StepFailed("running", "The data lake has no snapshot yet; the nightly ingest must run first.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    settings = ctx.cfg.settings
    m = rs.manifest
    feas_scope = m.scopes.feas if m.scopes and m.scopes.feas else None
    screen_scope = m.scopes.screen if m.scopes and m.scopes.screen else None
    try:
        lookback = int(opts.get("lookback") or (feas_scope.lookback_months if feas_scope else None) or 36)
    except ValueError as exc:
        raise StepFailed("running", f"lookback must be a number of months (got {opts.get('lookback')!r})") from exc
    if not 1 <= lookback <= 120:
        raise StepFailed("running", "lookback must be between 1 and 120 months")
    if opts.get("dept"):
        depts = [d.strip().upper() for d in opts["dept"].split(",") if d.strip()]
    elif feas_scope and feas_scope.population == "department":
        depts = list(feas_scope.departments or [])
    else:
        depts = []
    small_cell = (m.thresholds.small_cell if m.thresholds and m.thresholds.small_cell else None) or (
        settings.thresholds.small_cell if settings.thresholds and settings.thresholds.small_cell else 5
    )
    cal = calibration.load(ctx.data_dir, rs.id, settings)
    try:
        variants = parse_variant_option(opts["variant"]) if opts.get("variant") else {}
        params = FeasParams(
            run_date=ctx.today(),
            snapshot=snapshot,
            lookback_months=lookback,
            departments=depts,
            variants=variants,
            small_cell=small_cell,
            reach_rate=cal.reach_rate,
            accept_rate=cal.accept_rate,
            rate_source=cal.source,
            concentration=cal.concentration,
            capacity_per_month=capacity(settings, screen_scope.practitioners if screen_scope else None),
        )
        result, raw = compute(ctx.services.lake, rs, params)
    except FeasError as exc:
        raise StepFailed("running", str(exc)) from exc
    ctx.metrics(patients_scoped=raw.start_n)
    ctx.state("reporting")
    model = (m.models.judge if m.models and m.models.judge else None) or (
        settings.models.judge if settings.models and settings.models.judge else "n/a"
    )
    meta = ReportMeta(
        site_id=settings.site.id,
        site_name=settings.site.name,
        ruleset=rs.id,
        version=rs.version,
        model=model,
        snapshot=snapshot,
        job_id=job.job_id,
        run_date=params.run_date.isoformat(),
        locale=settings.site.locale or "zh-TW",
        contact=settings.site.contact or "",
    )
    to = recipients(m.routing, job.requested_by)
    stem = f"feasibility_{rs.id}_v{rs.version}_{snapshot}"
    caps = dict(settings.site_capabilities or {})
    pdf = ctx.publish(f"{stem}.pdf", feasibility_pdf.render(result, rs, meta, caps, small_cell), "aggregate", to)
    xlsx = ctx.publish(f"{stem}.xlsx", feasibility_xlsx.render(result, rs, meta), "aggregate", to)
    body = json.dumps(dump(result), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    js = ctx.publish(f"{stem}.json", body.encode("utf-8"), "aggregate", to)
    # unsuppressed counts stay in the box (funnel-compare harness); hashed + audited, never mailed
    ctx.publish(f"{stem}.raw.json", raw_json(raw), "phi", [])
    sim = result.simulation
    lines = [
        f"Feasibility for **{m.trial_alias or rs.id}** (ruleset {rs.id} v{rs.version}, snapshot {snapshot}).",
        "",
        f"- Estimated {sim.months}-month enrolment: **{sim.low:g}–{sim.high:g}** (most likely {sim.mid:g})",
        f"- Population: {result.population}: {fmt_count(result.start_n)}",
        f"- Eligible on structured criteria (any month-end): "
        f"{fmt_count(next((f.remaining for f in reversed(result.funnel) if f.applied is not False), 0))}",
    ]
    bars = feasibility_pdf.barriers(result)
    if bars:
        lines.append("- Biggest barriers: " + "; ".join(f"{lbl} (−{fmt_count(d)})" for _, lbl, d in bars))
    lines += ["", "Attached: feasibility report (PDF), workbook (XLSX) and the machine-readable result (JSON)."]
    return Outcome(
        state="done",
        summary_md="\n".join(lines),
        deliveries=[Delivery(to=to, outputs=[pdf, xlsx, js], routing=m.routing)],
    )
