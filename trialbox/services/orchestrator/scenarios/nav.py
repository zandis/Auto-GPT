"""NAV (SPEC §8.4, weekly; or ``NAV <ruleset> dept=<code>`` by mail): NHI reimbursement navigation for patients with
an appointment in the next 14 days in the department(s).

    likely_eligible  = inclusions pass, no exclusion, no active approval, no application in the last 90 days
    renewal_due      = active approval ending within renewal_lead_days, renewal criteria not failing
    doc_gaps         = rows of the two lists above with documentation criteria missing (+ suggested orders)
    maybe_ineligible = active approval and a renewal criterion fails (note: with confidence ≥ t)

Every likely_eligible / renewal_due row gets an application draft (docx, ``[待補]`` markers); TWPAS bundles are
built when the ruleset enables TWPAS (phase 6 hook). Lists, drafts and JSON go encrypted to ``routing.list_to``;
the aggregate summary to ``aggregate_to``."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, JobOutput, MissingItem, NavLists, NavRow, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.reports import docx_draft, nav_xlsx
from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios import facts as factmod
from orchestrator.scenarios.evaluate import PatientVerdicts, evaluate_patients
from orchestrator.scenarios.review import recipients, require_approved
from orchestrator.scenarios.screen import (
    judge_for,
    local_iso,
    pid_names,
    practitioner_names,
    report_meta,
    small_cell,
    structured_engine,
    threshold,
)

SCOPE_SQL = """
SELECT pid, CAST(min(start) AS VARCHAR) AS next_appt, arg_min(practitioner_id, start) AS practitioner_id,
       arg_min(dept, start) AS dept
FROM appointment
WHERE status = 'booked' AND list_contains(CAST($1 AS VARCHAR[]), dept)
  AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
GROUP BY pid ORDER BY pid
"""
CLAIM_SQL = """
SELECT pid,
  max(approval_end) FILTER (WHERE outcome = 'approved' AND approval_end >= CAST($2 AS DATE)) AS active_end,
  max(created) AS last_application
FROM claim WHERE list_contains(CAST($1 AS VARCHAR[]), pid) {product} GROUP BY pid
"""


def _ok(v: CriterionVerdict, by: dict[str, Any], t: float) -> str:
    """yes / no / unknown from the eligibility-perspective verdict (weak note answers count as unknown)."""
    c = by[v.id]
    conf = v.evidence.confidence if v.evidence and v.evidence.confidence is not None else 1.0
    if v.verdict in ("unknown", "pending_human") or (c.class_ == "note" and conf < t):
        return "unknown"
    return "yes" if v.verdict == "pass" else "no"


def classify(
    rs: Ruleset,
    pv: PatientVerdicts,
    active_end: date | None,
    last_app: date | None,
    run_date: date,
    lead_days: int,
    lookback_days: int,
    t: float,
) -> tuple[str | None, list[MissingItem]]:
    by = rs.by_id()
    status: dict[str, list[tuple[str, str]]] = {"inclusion": [], "exclusion": [], "renewal": [], "documentation": []}
    for v in pv.verdicts:
        status[by[v.id].kind].append((v.id, _ok(v, by, t)))
    missing = [
        MissingItem(
            item=by[cid].label or by[cid].text[:40],
            suggested_order=by[cid].suggested_order or by[cid].action,
            criterion_id=cid,
        )
        for cid, ok in status["documentation"]
        if ok != "yes"
    ]
    for kind in ("inclusion", "exclusion", "renewal"):
        missing += [
            MissingItem(
                item=f"確認：{by[cid].label or by[cid].text[:30]}", suggested_order=by[cid].action, criterion_id=cid
            )
            for cid, ok in status[kind]
            if ok == "unknown"
        ]
    if active_end is not None:
        if any(ok == "no" for _, ok in status["renewal"]):
            return "maybe_ineligible", missing
        if active_end <= run_date + timedelta(days=lead_days):
            return "renewal_due", missing
        return None, missing
    if last_app is not None and last_app >= run_date - timedelta(days=lookback_days):
        return None, missing  # application already in progress
    if all(ok == "yes" for _, ok in status["inclusion"]) and not any(ok == "no" for _, ok in status["exclusion"]):
        return "likely_eligible", missing
    return None, missing


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    rs = require_approved(ctx, (job.ruleset or "").upper(), (job.options or {}).get("version"))
    if rs.manifest.kind != "nhi":
        raise StepFailed("ruleset", f"{rs.id} is a {rs.manifest.kind} ruleset; NAV needs an NHI ruleset.")
    ctx.update(ruleset_version=rs.version)
    ctx.state("running")
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        raise StepFailed("running", "The data lake has no snapshot yet.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    run_date = ctx.today()
    opts = job.options or {}
    nav = rs.manifest.scopes.nav if rs.manifest.scopes and rs.manifest.scopes.nav else None
    depts = (
        [d.strip().upper() for d in opts["dept"].split(",")]
        if opts.get("dept")
        else list(nav.departments if nav and nav.departments else [])
    )
    if not depts:
        raise StepFailed("running", f"No department: give dept=<code> or set scopes.nav.departments for {rs.id}.")
    window = int(opts.get("window") or (nav.appointment_window_days if nav and nav.appointment_window_days else 14))
    lead = int(nav.renewal_lead_days if nav and nav.renewal_lead_days else 42)
    lookback = int(nav.application_lookback_days if nav and nav.application_lookback_days else 90)
    lake = ctx.services.lake
    tz = ctx.cfg.env.tz
    scoped = lake.query(
        SCOPE_SQL, [depts, run_date.isoformat(), (run_date + timedelta(days=window)).isoformat()]
    ).to_pylist()
    pids = [r["pid"] for r in scoped]
    ctx.metrics(patients_scoped=len(pids))
    codes = list(rs.manifest.twpas.drug_codes or []) if rs.manifest.twpas else []
    product = "AND list_contains(CAST($3 AS VARCHAR[]), product)" if codes else ""
    claims = {
        r["pid"]: r
        for r in lake.query(
            CLAIM_SQL.format(product=product), [pids, run_date.isoformat(), *([codes] if codes else [])]
        ).to_pylist()
    }
    judge = judge_for(ctx, rs)
    t = threshold(ctx, rs)
    engine = structured_engine(ctx, snapshot)
    results = evaluate_patients(
        rs,
        pids,
        run_date,
        engine,
        judge,
        t,
        all_candidates=True,
        kinds=("inclusion", "exclusion", "renewal", "documentation"),
    )
    if judge is not None:
        m = ctx.job.metrics
        ctx.metrics(
            llm_calls=(m.llm_calls if m else 0) + judge.calls,
            tokens_in=(m.tokens_in if m else 0) + judge.tokens_in,
            tokens_out=(m.tokens_out if m else 0) + judge.tokens_out,
        )
    lists: dict[str, dict[str, list[NavRow]]] = {d: {k: [] for k in nav_xlsx.SHEETS} for d in depts}
    for r in scoped:
        cl = claims.get(r["pid"], {})
        name, missing = classify(
            rs, results[r["pid"]], cl.get("active_end"), cl.get("last_application"), run_date, lead, lookback, t
        )
        if name is None:
            continue
        row = NavRow.model_validate(
            {
                "pid": r["pid"],
                "next_appointment": local_iso(r["next_appt"], tz),
                "practitioner_id": r["practitioner_id"],
                "approval_end": cl.get("active_end").isoformat() if cl.get("active_end") else None,
                "criteria": results[r["pid"]].verdicts,
                "missing": missing,
            }
        )
        lists[r["dept"]][name].append(row)
        if name in ("likely_eligible", "renewal_due") and any(
            m.criterion_id and rs.by_id()[m.criterion_id].kind == "documentation" for m in missing
        ):
            lists[r["dept"]]["doc_gaps"].append(row)
    ctx.state("reporting")
    meta = report_meta(ctx, rs, snapshot, run_date)
    all_rows = [row for d in lists.values() for name in ("likely_eligible", "renewal_due") for row in d[name]]
    mrns = pid_names(ctx, [r.pid for d in lists.values() for rows in d.values() for r in rows])
    names = practitioner_names(ctx)
    list_to = sorted(set(rs.manifest.routing.list_to or [])) if rs.manifest.routing else []
    if not list_to:
        raise StepFailed("routing", f"Ruleset {rs.id} has no routing.list_to; NAV lists cannot be sent.")
    outputs: list[JobOutput] = []
    files: dict[str, str] = {}
    issues: list[str] = []
    for r in all_rows:
        draft = _draft(ctx, rs, r, meta, mrns.get(r.pid, ""), names, issues, run_date)
        if draft is not None:
            outputs.append(draft)
            files[f"draft:{r.pid}"] = draft.filename
            r.draft_doc_key = draft.minio_key
    for dept, sets in lists.items():
        stem = f"nav_lists_{rs.id}_{dept}_{run_date.isoformat()}"
        for name in ("likely_eligible", "renewal_due", "doc_gaps", "maybe_ineligible"):
            sets[name].sort(
                key=lambda x: (
                    x.next_appointment is None,
                    x.next_appointment.isoformat() if x.next_appointment else "",
                    x.pid,
                )
            )
        outputs.append(ctx.publish(f"{stem}.xlsx", nav_xlsx.render(sets, rs, meta, mrns, names, files), "phi", list_to))
        body = NavLists.model_validate(
            {
                "ruleset": rs.id,
                "version": rs.version,
                "snapshot": snapshot,
                "run_date": run_date.isoformat(),
                "department": dept,
                "lists": sets,
            }
        )
        outputs.append(
            ctx.publish(
                f"{stem}.json",
                (json.dumps(dump(body), ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode(),
                "phi",
                list_to,
            )
        )
    counts = {k: sum(len(d[k]) for d in lists.values()) for k in nav_xlsx.SHEETS}
    sc = small_cell(ctx, rs)
    from tb_common.smallcell import suppress

    text = (
        f"NAV **{rs.id} v{rs.version}** for {', '.join(depts)}: {len(pids)} patients with an appointment in the "
        f"next {window} days; "
        + ", ".join(f"{k} {suppress(v, sc)}" for k, v in counts.items())
        + f". Drafts: {sum(1 for k in files if k.startswith('draft:'))} (fields marked [待補] need completion)."
    )
    agg_to = recipients(rs.manifest.routing, job.requested_by)
    summary = ctx.publish(
        f"nav_summary_{rs.id}_{run_date.isoformat()}.pdf",
        _summary_pdf(rs, meta, depts, counts, window, sc),
        "aggregate",
        agg_to,
    )
    deliveries = [
        Delivery(
            to=list_to,
            outputs=outputs,
            routing=rs.manifest.routing,
            kind="list",
            subject=f"NAV {rs.id} {'/'.join(depts)} — job {job.job_id}",
            body_md=text + ("\n\nIssues:\n" + "\n".join(f"- {i}" for i in issues[:20]) if issues else ""),
        ),
        Delivery(to=agg_to, outputs=[summary], routing=rs.manifest.routing, body_md=text),
    ]
    return Outcome(summary_md=text, deliveries=deliveries)


def _draft(
    ctx: Ctx,
    rs: Ruleset,
    row: NavRow,
    meta: ReportMeta,
    mrn: str,
    names: dict[str, str],
    issues: list[str],
    run_date: date,
) -> JobOutput | None:
    if not rs.manifest.docx_template:
        return None
    f = factmod.collect(ctx.services.lake, rs, row.pid, run_date)
    course: str | None = None
    if ctx.services.llm is not None:
        cf = factmod.course_facts(f)
        try:
            res = ctx.services.llm.chat_json("draft_doc", {"facts": cf}, job_id=ctx.job.job_id)
            para = str(res.data.get("paragraph", "")).strip()
            if para and docx_draft.numbers_ok(para, cf):
                course = para
            else:
                issues.append(f"{row.pid[:12]}: clinical course left [待補] (number check failed)")
        except Exception as exc:  # the draft is still useful without the paragraph
            issues.append(f"{row.pid[:12]}: clinical course left [待補] ({type(exc).__name__})")
    by = rs.by_id()
    excl = [
        (
            by[v.id].label or by[v.id].text[:30],
            {"pass": "無", "fail": "有", "unknown": "[待補]", "pending_human": "[待補]"}[v.verdict],
        )
        for v in row.criteria
        if by[v.id].kind == "exclusion"
    ]
    apply_type = "續用" if row.approval_end else "新申請"
    data = docx_draft.render(
        rs.manifest.docx_template, f, mrn, names.get(row.practitioner_id or "", ""), "", apply_type, course, excl, meta
    )
    return ctx.publish(
        f"draft_{rs.id}_{row.pid[:12]}.docx",
        data,
        "phi",
        sorted(set(rs.manifest.routing.list_to or [])) if rs.manifest.routing else [],
    )


def _summary_pdf(rs: Ruleset, meta: ReportMeta, depts: list[str], counts: dict[str, int], window: int, t: int) -> bytes:
    from orchestrator.reports.common import pdf_fonts, pdf_invariant

    pdf_invariant()
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table
    from tb_common.smallcell import suppress

    reg, bold = pdf_fonts(meta.locale)
    body = ParagraphStyle("b", fontName=reg, fontSize=10, leading=14)
    h1 = ParagraphStyle("h", parent=body, fontName=bold, fontSize=15, leading=20)
    story: list[Any] = [
        Paragraph(f"NHI navigation summary — {rs.manifest.title or rs.id}", h1),
        Paragraph(
            f"Departments {', '.join(depts)}; appointments in the next {window} days; "
            f"run {meta.run_date}, snapshot {meta.snapshot}.",
            body,
        ),
    ]
    tbl = Table(
        [["list", "patients"]] + [[k, str(suppress(v, t))] for k, v in counts.items()], colWidths=[60 * mm, 30 * mm]
    )
    tbl.setStyle([("FONTNAME", (0, 0), (-1, -1), reg), ("GRID", (0, 0), (-1, -1), 0.3, "#9aa9b8")])
    story.append(tbl)

    def foot(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(reg, 7)
        canvas.drawString(15 * mm, 10 * mm, meta.footer)
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        title="NAV summary",
        author=f"TrialBox {meta.site_id}",
        creator="TrialBox",
        producer="TrialBox",
    ).build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()
