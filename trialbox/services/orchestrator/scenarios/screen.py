"""SCREEN (SPEC §8.2): scope by practitioner appointments (+ recent encounters) → structured CQL per patient →
note criteria via RAG + judge for structured candidates → tiers → candidate workbook (phi) to ``list_to``, referral
workbooks per department (phi) to ``referral_to[dept]``, candidate_list.json (phi), summary PDF (aggregate) →
candidate pool persisted for MICROBATCH."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common.ruleset import Ruleset
from tb_common.subject import job_subject
from tb_common.timeutil import add_months
from tb_contracts import CandidateList, CandidateRow, Judging, Routing, ScreenRunScope, TierSummary, dump

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_language, job_stamp
from orchestrator.i18n import population_line, t
from orchestrator.reports import candidate_xlsx, screen_summary_pdf
from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios.evaluate import (
    NoteJudge,
    PatientVerdicts,
    StructuredEngine,
    check_judge,
    effective_note_block,
    engine_from_env,
    evaluate_patients,
    is_note_answer,
    note_block_policy,
    row,
    sort_key,
)
from orchestrator.scenarios.review import recipients, require_approved

SCOPE_SQL = """
WITH a AS (
  SELECT pid, min(start) AS next_appt, arg_min(practitioner_id, start) AS pr, arg_min(dept, start) AS dept
  FROM appointment
  WHERE list_contains(CAST($1 AS VARCHAR[]), practitioner_id) AND status = 'booked'
    AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
  GROUP BY pid),
e AS (
  SELECT pid, max(start) AS last_enc, arg_max(practitioner_id, start) AS pr, arg_max(dept, start) AS dept
  FROM encounter
  WHERE list_contains(CAST($1 AS VARCHAR[]), practitioner_id)
    AND CAST(start AS DATE) BETWEEN CAST($4 AS DATE) AND CAST($2 AS DATE)
  GROUP BY pid)
SELECT p.pid, CAST(a.next_appt AS VARCHAR) AS next_appt, coalesce(a.pr, e.pr) AS practitioner_id,
       coalesce(a.dept, e.dept) AS dept
FROM patient p LEFT JOIN a ON a.pid = p.pid LEFT JOIN e ON e.pid = p.pid
WHERE (a.pid IS NOT NULL OR e.pid IS NOT NULL)
  AND (p.deceased_date IS NULL OR p.deceased_date > CAST($2 AS DATE))
ORDER BY p.pid
"""


@dataclass
class Scoped:
    pid: str
    next_appointment: str | None
    practitioner_id: str | None
    department: str | None


@dataclass
class ScreenRun:
    rs: Ruleset
    run_date: date
    snapshot: str
    scoped: list[Scoped]
    results: dict[str, PatientVerdicts]
    rows: list[CandidateRow]
    practitioners: list[str]
    departments: list[str]
    window_days: int
    judge: NoteJudge | None
    judging: dict[str, Any] | None = None


def judging_info(judge: NoteJudge | None) -> dict[str, Any]:
    """How note criteria were judged on this run: models, agreement mode, and whether a note answer could exclude
    (D-97). Aggregate metadata: goes into the candidate list, the summary PDF, the done mail and the console."""
    may_block, policy, reason = effective_note_block(judge)
    return {
        "mode": judge.mode if judge is not None else "none",
        "judge_model": judge.llm.model if judge is not None else None,
        "verifier_model": judge.verifier.model if judge is not None and judge.verifier is not None else None,
        "note_block": policy,
        "note_block_reason": reason,
        "configured_note_block": note_block_policy(),
        "may_block": may_block,
        "disagreements": judge.disagreements if judge is not None else 0,
        "failures": judge.failures if judge is not None else 0,
    }


def judging_sentence(j: dict[str, Any], lang: str = "en") -> str:
    """One sentence for the mail and the PDF: who judged the notes and whether a note answer could exclude."""
    if j.get("mode") == "none":
        return t(lang, "screen.judging.none")
    if j.get("may_block"):
        return t(lang, "screen.judging.pair", judge=j.get("judge_model"), verifier=j.get("verifier_model"))
    return t(lang, "screen.judging.single", judge=j.get("judge_model"), why=str(j.get("note_block_reason") or ""))


def scope_patients(
    ctx: Ctx, practitioners: list[str], run_date: date, window_days: int, recent_months: int, departments: list[str]
) -> list[Scoped]:
    rows = ctx.services.lake.query(
        SCOPE_SQL,
        [
            practitioners,
            run_date.isoformat(),
            (run_date + timedelta(days=window_days)).isoformat(),
            add_months(run_date, -recent_months).isoformat(),
        ],
    ).to_pylist()
    tz = ctx.cfg.env.tz
    out = [Scoped(r["pid"], local_iso(r["next_appt"], tz), r["practitioner_id"], r["dept"]) for r in rows]
    if departments:
        out = [s for s in out if s.department in departments]
    return out


def local_iso(value: object, tz: str) -> str | None:
    """Lake timestamps are hospital-local wall time; contracts carry ISO-8601 with offset (SPEC §1)."""
    if value in (None, ""):
        return None
    dt = datetime.fromisoformat(str(value))
    return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))).isoformat(timespec="minutes")


def judge_for(ctx: Ctx, rs: Ruleset) -> NoteJudge | None:
    """The note judge for a run: two-model agreement when a verifier build is configured (the default, D-89), the
    single judge with ``TB_SCREEN_JUDGE=single``."""
    if ctx.services.llm is None:
        return None
    prompt = rs.manifest.models.judge_prompt if rs.manifest.models and rs.manifest.models.judge_prompt else None
    mode = os.environ.get("TB_SCREEN_JUDGE", "agreement").strip().lower()
    verifier = ctx.services.verifier if mode != "single" else None
    return NoteJudge(ctx.services.lake, ctx.services.llm, prompt or "judge", job_id=ctx.job.job_id, verifier=verifier)


def structured_engine(ctx: Ctx, snapshot: str) -> StructuredEngine:
    return engine_from_env(os.environ.get("TB_SCREEN_ENGINE", "cql"), ctx.services.fhir, ctx.services.lake, snapshot)


def threshold(ctx: Ctx, rs: Ruleset) -> float:
    m, s = rs.manifest, ctx.cfg.settings
    if m.thresholds and m.thresholds.tier_high_confidence is not None:
        return float(m.thresholds.tier_high_confidence)
    if s.thresholds and s.thresholds.tier_high_confidence is not None:
        return float(s.thresholds.tier_high_confidence)
    return 0.75


def small_cell(ctx: Ctx, rs: Ruleset) -> int:
    m, s = rs.manifest, ctx.cfg.settings
    return int(
        (m.thresholds.small_cell if m.thresholds and m.thresholds.small_cell else None)
        or (s.thresholds.small_cell if s.thresholds and s.thresholds.small_cell else 5)
    )


NO_MODEL = "no model (filters only)"


def models_used(j: dict[str, Any] | None) -> str:
    """The footer's model field, from the run's ``judging`` record (D-101): never a configured model that was not
    called."""
    if not j or j.get("mode") == "none" or not j.get("judge_model"):
        return NO_MODEL
    if j["verifier_model"]:
        return f"{j['judge_model']} + {j['verifier_model']} (both agree)"
    return f"{j['judge_model']} (single, {j['note_block']}-exclude)"


def stage_funnel(rs: Ruleset, srun: ScreenRun, listed: int, n: Callable[[int], int]) -> list[list[Any]]:
    """The run as the one named funnel every page shows (M7), with the cascade's stage ids: S0 in scope, S1 after
    the coded filters, S3 patients whose notes the model read, S4 candidates (high + review) for a person."""
    by_id = {c.id: c for c in rs.criteria}
    after_codes = 0
    notes_read = 0
    for pv in srun.results.values():
        coded_fail = any(
            v.verdict == "fail" and (c := by_id.get(v.id)) is not None and not is_note_answer(c, v) for v in pv.verdicts
        )
        if not coded_fail:
            after_codes += 1
        if any(
            (c := by_id.get(v.id)) is not None
            and is_note_answer(c, v)
            and not (v.evidence is not None and v.evidence.reason == "not evaluated")
            for v in pv.verdicts
        ):
            notes_read += 1
    return [
        ["S0", n(len(srun.scoped))],
        ["S1", n(after_codes)],
        ["S3", n(notes_read)],
        ["S4", n(listed)],
    ]


def pinned_clock_note(ctx: Ctx) -> str:
    return "clock pinned (test stack)" if ctx.orch.clock_pinned else ""


def report_meta(
    ctx: Ctx, rs: Ruleset, snapshot: str, run_date: date, judging: dict[str, Any] | None = None
) -> ReportMeta:
    s = ctx.cfg.settings
    model = models_used(judging)
    return ReportMeta(
        s.site.id,
        s.site.name,
        rs.id,
        rs.version,
        model,
        snapshot,
        ctx.job.job_id,
        run_date.isoformat(),
        job_language(ctx),
        s.site.contact or "",
        pinned_clock_note(ctx),
    )


def pid_names(ctx: Ctx, pids: list[str]) -> dict[str, str]:
    """pid -> MRN from the in-box pid map (internal recipients only)."""
    return resolve_mrns(Path(ctx.cfg.env.secrets_dir), pids)


def resolve_mrns(sec: Path, pids: list[str]) -> dict[str, str]:
    """pid -> chart number from the pid map under ``sec``; empty when the box has no map (stub installs)."""
    db, key = sec / "pid_map.sqlite", sec / "pid_map.key"
    if not db.exists() or not key.exists():
        return {}
    from adapter.pidmap import PidMap

    pm = PidMap(db, key)
    try:
        return pm.resolve_many(pids)
    finally:
        pm.close()


def practitioner_names(ctx: Ctx) -> dict[str, str]:
    return {k: f"{v.name or k} ({k})" for k, v in (ctx.cfg.settings.practitioners or {}).items()}


def evaluate_scope(
    ctx: Ctx,
    rs: Ruleset,
    run_date: date,
    snapshot: str,
    scoped: list[Scoped],
    only: set[str] | None = None,
    all_candidates: bool = False,
) -> dict[str, PatientVerdicts]:
    judge = judge_for(ctx, rs)
    engine = structured_engine(ctx, snapshot)
    res = evaluate_patients(
        rs,
        [s.pid for s in scoped],
        run_date,
        engine,
        judge,
        threshold(ctx, rs),
        only=only,
        all_candidates=all_candidates,
    )
    check_judge(judge)
    tiers = {t: sum(1 for v in res.values() if v.tier == t) for t in ("high", "review", "excluded")}
    ctx.orch.audit.append(
        "screen.evaluated",
        job_id=ctx.job.job_id,
        ruleset=rs.id,
        ruleset_version=rs.version,
        snapshot=snapshot,
        model=judge.llm.model if judge is not None else None,
        prompt_version=judge.prompt if judge is not None else None,
        detail={
            "engine": engine.name,
            "index_date": run_date.isoformat(),
            "patients": len(scoped),
            "only": sorted(only) if only else None,
            "tiers": tiers,
            "judging": judging_info(judge),
        },
    )
    if judge is not None:
        m = ctx.job.metrics
        ctx.metrics(
            llm_calls=(m.llm_calls if m else 0) + judge.calls,
            tokens_in=(m.tokens_in if m else 0) + judge.tokens_in,
            tokens_out=(m.tokens_out if m else 0) + judge.tokens_out,
        )
    return res


def run_screen(ctx: Ctx, rs: Ruleset, run_date: date, snapshot: str) -> ScreenRun:
    opts = ctx.job.options or {}
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    practitioners = (
        [p.strip() for p in opts["pract"].split(",")]
        if opts.get("pract")
        else list(sc.practitioners if sc and sc.practitioners else [])
    )
    if not practitioners:
        raise StepFailed("running", f"No practitioners in scope: give pract=<id,...> or set scopes.screen for {rs.id}.")
    try:
        window = int(opts.get("window") or (sc.appointment_window_days if sc and sc.appointment_window_days else 180))
    except ValueError as exc:
        raise StepFailed("running", "window must be a number of days") from exc
    depts = [d.strip().upper() for d in opts["dept"].split(",")] if opts.get("dept") else []
    recent = int(sc.recent_encounter_months if sc and sc.recent_encounter_months else 12)
    scoped = scope_patients(ctx, practitioners, run_date, window, recent, depts)
    ctx.metrics(patients_scoped=len(scoped))
    results = evaluate_scope(ctx, rs, run_date, snapshot, scoped)
    by_pid = {s.pid: s for s in scoped}
    stamp = job_stamp(ctx)  # evaluation time = the job's receipt: same inputs → same bytes (D-82)
    rows = [
        row(pv, by_pid[p].next_appointment, by_pid[p].practitioner_id, by_pid[p].department, stamp)
        for p, pv in results.items()
    ]
    rows.sort(key=sort_key)
    judge = judge_for(ctx, rs)
    return ScreenRun(
        rs, run_date, snapshot, scoped, results, rows, practitioners, depts, window, judge, judging_info(judge)
    )


def candidate_list(run: ScreenRun) -> CandidateList:
    listed = [r for r in run.rows if r.tier in ("high", "review")]
    tiers = {t: sum(1 for r in run.rows if r.tier == t) for t in ("high", "review", "excluded")}
    return CandidateList(
        ruleset=run.rs.id,
        version=run.rs.version,
        snapshot=date.fromisoformat(run.snapshot),
        run_date=run.run_date,
        scope=ScreenRunScope(
            practitioners=run.practitioners,
            departments=run.departments,
            window_days=run.window_days,
            n_scoped=len(run.scoped),
        ),
        rows=listed,
        summary=TierSummary(**tiers),
        judging=Judging(**run.judging) if run.judging else None,
    )


def persist_pool(ctx: Ctx, rs: Ruleset, rows: list[CandidateRow]) -> None:
    ctx.orch.db.pool_upsert(
        rs.id,
        rs.version,
        [
            {
                "pid": r.pid,
                "tier": r.tier,
                "practitioner_id": r.practitioner_id,
                "next_appointment": r.next_appointment.isoformat() if r.next_appointment else None,
                "department": r.department,
                "verdicts": [v.model_dump(mode="json", exclude_none=True) for v in r.criteria],
            }
            for r in rows
        ],
        ctx.job.job_id,
        ctx.orch._now().isoformat(),
    )


def deliver_lists(
    ctx: Ctx,
    rs: Ruleset,
    rows: list[CandidateRow],
    meta: ReportMeta,
    stem: str,
    changes: list[candidate_xlsx.Change] | None = None,
    extra: tuple[str, bytes] | None = None,
) -> tuple[list[Delivery], dict[str, Any]]:
    """Candidate workbook + JSON to list_to; one referral workbook per routed department (phi)."""
    routing: Routing | None = rs.manifest.routing
    list_to = sorted(set(routing.list_to or [])) if routing else []
    if not list_to:
        raise StepFailed("routing", f"Ruleset {rs.id} has no routing.list_to; patient lists cannot be sent.")
    listed = [r for r in rows if r.tier in ("high", "review") or (changes is not None and r.changed)]
    mrns = pid_names(ctx, [r.pid for r in listed])
    names = practitioner_names(ctx)
    xlsx = ctx.publish(f"{stem}.xlsx", candidate_xlsx.render(listed, rs, meta, mrns, names, changes), "phi", list_to)
    out: list[Delivery] = []
    files = [xlsx]
    if extra is not None:
        files.append(ctx.publish(extra[0], extra[1], "phi", list_to))
    n_high = sum(r.tier == "high" for r in listed)
    lang = job_language(ctx)
    out.append(
        Delivery(
            to=list_to,
            outputs=files,
            routing=routing,
            kind="list",
            subject=job_subject(
                "candidates", ctx.job.type, rs.id, ctx.job.job_id, t(lang, "screen.list.headline", n=len(listed))
            ),
            body_md=t(
                lang, "screen.list", rs=rs.id, ver=rs.version, n=len(listed), high=n_high, review=len(listed) - n_high
            ),
        )
    )
    referrals: dict[str, int] = {}
    for dept, addr in sorted((routing.referral_to or {}).items() if routing else []):
        sub = [r for r in listed if (r.department or "") == dept]
        if not sub:
            continue
        ref = ctx.publish(
            f"referral_{dept}_{stem}.xlsx",
            candidate_xlsx.render(sub, rs, meta, mrns, names, None, title=f"referral {dept}"),
            "phi",
            [addr],
        )
        referrals[dept] = len(sub)
        out.append(
            Delivery(
                to=[addr],
                outputs=[ref],
                routing=routing,
                kind="referral",
                subject=job_subject(
                    "referral",
                    ctx.job.type,
                    rs.id,
                    ctx.job.job_id,
                    t(lang, "screen.referral.headline", dept=dept, n=len(sub)),
                ),
                body_md=t(
                    lang,
                    "screen.referral",
                    n=len(sub),
                    dept=dept,
                    rs=rs.id,
                    to=", ".join(routing.list_to or []) if routing else "",
                ),
            )
        )
    return out, {"listed": len(listed), "referrals": referrals}


def run(ctx: Ctx) -> Outcome:
    job = ctx.job
    rs = require_approved(ctx, (job.ruleset or "").upper(), (job.options or {}).get("version"))
    ctx.update(ruleset_version=rs.version)
    ctx.state("running")
    snapshot = ctx.services.lake.snapshot()
    if not snapshot:
        raise StepFailed("running", "The data lake has no snapshot yet; the nightly ingest must run first.")
    ctx.update(snapshot_date=date.fromisoformat(snapshot))
    run_date = ctx.today()
    srun = run_screen(ctx, rs, run_date, snapshot)
    ctx.state("reporting")
    cl = candidate_list(srun)
    meta = report_meta(ctx, rs, snapshot, run_date, srun.judging)
    stem = f"candidates_{rs.id}_v{rs.version}_{run_date.isoformat()}"
    body = json.dumps(dump(cl), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    deliveries, info = deliver_lists(
        ctx, rs, srun.rows, meta, stem, extra=(f"candidate_list_{rs.id}_v{rs.version}.json", body)
    )
    persist_pool(ctx, rs, [r for r in srun.rows if r.tier in ("high", "review")])
    agg_to = recipients(rs.manifest.routing, job.requested_by)

    def n(v: int) -> int:  # D-99: internal mail, PDF and console show exact counts; the sponsor pack suppresses
        return v

    judging = srun.judging or judging_info(None)
    lang = job_language(ctx)
    scope_lines = [
        t(lang, "screen.scope1", rs=rs.id, ver=rs.version, run=run_date.isoformat(), snapshot=snapshot),
        t(
            lang,
            "screen.scope2",
            pract=", ".join(srun.practitioners),
            window=srun.window_days,
            scoped=n(len(srun.scoped)),
        ),
        judging_sentence(judging, lang),
        *([population_line(lang, rs.manifest.population)] if population_line(lang, rs.manifest.population) else []),
    ]
    unknown_by: dict[str, int] = {}
    for r in srun.rows:
        if r.tier in ("high", "review"):
            for v in r.criteria:
                if v.verdict == "unknown":
                    unknown_by[v.id] = unknown_by.get(v.id, 0) + 1
    funnel = stage_funnel(rs, srun, info["listed"], n)
    ctx.publish(
        f"screen_{stem}.json",
        json.dumps(
            {
                "ruleset": rs.id,
                "version": rs.version,
                "run_date": run_date.isoformat(),
                "snapshot": snapshot,
                "practitioner_names": practitioner_names(ctx),
                "scope": {
                    "practitioners": srun.practitioners,
                    "departments": srun.departments,
                    "window_days": srun.window_days,
                    "n_scoped": n(len(srun.scoped)),
                },
                "tiers": {
                    "high": n(cl.summary.high),
                    "review": n(cl.summary.review),
                    "excluded": n(cl.summary.excluded),
                },
                "listed": n(info["listed"]),
                "funnel": funnel,
                "referrals": {k: n(v) for k, v in info["referrals"].items()},
                "unknown_by_criterion": {k: n(v) for k, v in sorted(unknown_by.items())},
                "judging": judging,
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        ).encode("utf-8"),
        "aggregate",
        agg_to,
    )
    summary = ctx.publish(
        f"summary_{stem}.pdf",
        screen_summary_pdf.render(
            t(lang, "pdf.screen.title", trial=rs.manifest.trial_alias or rs.id),
            srun.rows,
            rs,
            meta,
            scope_lines,
            1,  # D-99: exact counts inside the site
            practitioner_names(ctx),
        ),
        "aggregate",
        agg_to,
    )
    s = cl.summary
    text = t(
        lang,
        "screen.done",
        rs=rs.id,
        ver=rs.version,
        scoped=n(len(srun.scoped)),
        high=n(s.high),
        review=n(s.review),
        excluded=n(s.excluded),
        to=", ".join(rs.manifest.routing.list_to or []) if rs.manifest.routing else "",
        referrals=(
            t(lang, "screen.referrals", items=", ".join(f"{k} ({n(v)})" for k, v in info["referrals"].items()))
            if info["referrals"]
            else ""
        ),
        judging=judging_sentence(judging, lang),
    )
    deliveries.append(Delivery(to=agg_to, outputs=[summary], routing=rs.manifest.routing, body_md=text))
    return Outcome(
        summary_md=text, deliveries=deliveries, headline=t(lang, "screen.headline", high=n(s.high), review=n(s.review))
    )
