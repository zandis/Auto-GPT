"""MICROBATCH (SPEC §8.2, Monday 03:00): candidate pool ∩ appointments in the next 14 days → re-evaluate only the
``time_sensitive`` criteria (structured via CQL, note via judge) → ``this_week_visit1.xlsx`` (phi) with changed
verdicts highlighted and a ``changes`` sheet → ``list_to``. On the first Monday of a month (or ``incident=1``) new
in-scope patients are screened and appended to the pool."""

from __future__ import annotations

from datetime import date, timedelta

from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionVerdict

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome
from orchestrator.reports import screen_summary_pdf
from orchestrator.reports.candidate_xlsx import Change
from orchestrator.scenarios.evaluate import row, sort_key, tier
from orchestrator.scenarios.review import recipients, require_approved
from orchestrator.scenarios.screen import (
    Scoped,
    deliver_lists,
    evaluate_scope,
    local_iso,
    persist_pool,
    practitioner_names,
    report_meta,
    run_screen,
    small_cell,
    threshold,
)

APPT_SQL = """
SELECT pid, CAST(min(start) AS VARCHAR) AS next_appt, arg_min(practitioner_id, start) AS practitioner_id,
       arg_min(dept, start) AS dept
FROM appointment
WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND status = 'booked'
  AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
GROUP BY pid ORDER BY pid
"""


def first_monday(d: date) -> bool:
    return d.weekday() == 0 and d.day <= 7


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    rs: Ruleset = require_approved(ctx, (job.ruleset or "").upper(), None)
    ctx.update(ruleset_version=rs.version)
    pool = ctx.orch.db.pool(rs.id)
    if not pool:
        raise StepFailed("running", f"No candidate pool for {rs.id}; run SCREEN first.")
    ctx.state("running")
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        raise StepFailed("running", "The data lake has no snapshot yet.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    run_date = ctx.today()
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    window = int(
        (job.options or {}).get("window") or (sc.microbatch_window_days if sc and sc.microbatch_window_days else 14)
    )
    appts = {
        r["pid"]: r
        for r in ctx.services.lake.query(
            APPT_SQL, [[p["pid"] for p in pool], run_date.isoformat(), (run_date + timedelta(days=window)).isoformat()]
        ).to_pylist()
    }
    week = [p for p in pool if p["pid"] in appts]
    ts = {c.id for c in rs.active() if c.time_sensitive and c.kind in ("inclusion", "exclusion")}
    tz = ctx.cfg.env.tz
    scoped = [
        Scoped(
            p["pid"],
            local_iso(appts[p["pid"]]["next_appt"], tz),
            appts[p["pid"]]["practitioner_id"],
            appts[p["pid"]]["dept"],
        )
        for p in week
    ]
    ctx.metrics(patients_scoped=len(scoped))
    fresh = evaluate_scope(ctx, rs, run_date, snapshot, scoped, only=ts, all_candidates=True) if ts and scoped else {}
    t = threshold(ctx, rs)
    rows: list[CandidateRow] = []
    changes: list[Change] = []
    stamp = ctx.orch._now().isoformat(timespec="seconds")
    for p, s in zip(week, scoped, strict=True):
        old = {v["id"]: CriterionVerdict.model_validate(v) for v in p["verdicts"]}
        new = dict(old)
        changed: list[str] = []
        for v in fresh[p["pid"]].verdicts if p["pid"] in fresh else []:
            if v.id not in ts:
                continue
            prev = old.get(v.id)
            if prev is None or prev.verdict != v.verdict:
                changed.append(v.id)
                changes.append(
                    Change(
                        p["pid"],
                        v.id,
                        prev.verdict if prev else "",
                        v.verdict,
                        (v.evidence.quote or "") if v.evidence else "",
                    )
                )
            new[v.id] = v
        ordered = [new[c.id] for c in rs.active() if c.id in new]
        tr, acts, n_unk = tier(rs, ordered, t)
        from orchestrator.scenarios.evaluate import PatientVerdicts

        rows.append(
            row(
                PatientVerdicts(p["pid"], ordered, tr, acts, n_unk),
                s.next_appointment,
                s.practitioner_id,
                s.department,
                stamp,
                changed,
            )
        )
    added = 0
    incident = (job.options or {}).get("incident", "auto")
    if incident == "1" or (incident == "auto" and first_monday(run_date)):
        known = {p["pid"] for p in pool}
        srun = run_screen(ctx, rs, run_date, snapshot)
        new_rows = [r for r in srun.rows if r.pid not in known and r.tier in ("high", "review")]
        persist_pool(ctx, rs, new_rows)
        added = len(new_rows)
        horizon = run_date + timedelta(days=window)
        rows += [
            r.model_copy(update={"changed": [v.id for v in r.criteria]})
            for r in new_rows
            if r.next_appointment and r.next_appointment.date() <= horizon
        ]
    rows.sort(key=sort_key)
    persist_pool(ctx, rs, [r for r in rows if r.pid in {p["pid"] for p in week}])
    ctx.state("reporting")
    meta = report_meta(ctx, rs, snapshot, run_date)
    stem = f"this_week_visit1_{rs.id}_{run_date.isoformat()}"
    deliveries, _ = deliver_lists(ctx, rs, rows, meta, stem, changes=changes)
    agg_to = recipients(rs.manifest.routing, job.requested_by)
    lines = [
        f"Weekly microbatch {rs.id} v{rs.version}, run {run_date.isoformat()}: {len(week)} pool patients with an "
        f"appointment in the next {window} days; time-sensitive criteria re-evaluated: {', '.join(sorted(ts))}.",
        f"Verdict changes: {len(changes)}; new patients added to the pool: {added}.",
    ]
    summary = ctx.publish(
        f"summary_{stem}.pdf",
        screen_summary_pdf.render(
            f"Weekly visit list — {rs.manifest.trial_alias or rs.id}",
            rows,
            rs,
            meta,
            lines,
            small_cell(ctx, rs),
            practitioner_names(ctx),
        ),
        "aggregate",
        agg_to,
    )
    text = " ".join(lines)
    deliveries.append(Delivery(to=agg_to, outputs=[summary], routing=rs.manifest.routing, body_md=text))
    return Outcome(summary_md=text, deliveries=deliveries)
