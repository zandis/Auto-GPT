"""SCREEN (SPEC §8.2): scope by practitioner appointments (+ recent encounters) → structured CQL per patient →
note criteria via RAG + judge for structured candidates → tiers → candidate workbook (phi) to ``list_to``, referral
workbooks per department (phi) to ``referral_to[dept]``, candidate_list.json (phi), summary PDF (aggregate) →
candidate pool persisted for MICROBATCH."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from matching import coded_values
from matching.coverage import unknown_system_counts
from tb_common.authz import norm
from tb_common.kek import key_present
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
from orchestrator.scenarios.screen_cascade import max_pairs_of, pipeline, screen_with_cascade
from orchestrator.scheduler import require_open

SCOPE_SQL = """
WITH a AS (
  SELECT pid, min(start) AS next_appt, arg_min(practitioner_id, start) AS pr, arg_min(dept, start) AS dept
  FROM appointment
  WHERE (CAST($5 AS BOOLEAN) OR list_contains(CAST($1 AS VARCHAR[]), practitioner_id)) AND status = 'booked'
    AND CAST(start AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
  GROUP BY pid),
e AS (
  SELECT pid, max(start) AS last_enc, arg_max(practitioner_id, start) AS pr, arg_max(dept, start) AS dept
  FROM encounter
  WHERE (CAST($5 AS BOOLEAN) OR list_contains(CAST($1 AS VARCHAR[]), practitioner_id))
    AND CAST(start AS DATE) BETWEEN CAST($4 AS DATE) AND CAST($2 AS DATE)
  GROUP BY pid)
SELECT p.pid, CAST(a.next_appt AS VARCHAR) AS next_appt, coalesce(a.pr, e.pr) AS practitioner_id,
       coalesce(a.dept, e.dept) AS dept
FROM patient p LEFT JOIN a ON a.pid = p.pid LEFT JOIN e ON e.pid = p.pid
WHERE (a.pid IS NOT NULL OR e.pid IS NOT NULL)
  AND (p.deceased_date IS NULL OR p.deceased_date > CAST($2 AS DATE))
  AND (p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)
ORDER BY p.pid
"""


# FIT-U04 (T-629, D-415): who of a list the current snapshot records as dead, with a date or without one (T-616)
DECEASED_SQL = """
SELECT pid FROM patient
WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND (deceased_date IS NOT NULL OR deceased IS TRUE)
ORDER BY pid
"""


def deceased_now(lake: Any, pids: list[str]) -> list[str]:
    """The pseudonyms of ``pids`` whose record in the lake's current snapshot says the patient died. The console
    asks at each view of a list, so a death recorded after the run takes the patient off it at once. A snapshot
    built before schema 4 reads ``deceased`` as unknown and still gives the death date (``lake.store``)."""
    if not pids:
        return []
    return [str(r["pid"]) for r in lake.query(DECEASED_SQL, [list(pids)]).to_pylist()]


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
    cascade: dict[str, Any] | None = None  # D-103: the cascade's stage log and counts when it ran the screen
    whole_hospital: bool = False  # D-146: every doctor's patients (``practitioners`` is then empty)

    @property
    def pipeline(self) -> str:
        return "cascade" if self.cascade else "v1"


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
    ctx: Ctx,
    practitioners: list[str] | None,
    run_date: date,
    window_days: int,
    recent_months: int,
    departments: list[str],
    snapshot: str | None = None,
) -> list[Scoped]:
    """The patients in scope, read from the snapshot the screening then runs on (D-142, review B-02).
    ``practitioners`` None: the whole hospital (D-146), every patient with a booked appointment in the window or a
    recent visit, whoever the doctor."""
    rows = ctx.services.lake.query(
        SCOPE_SQL,
        [
            list(practitioners or []),
            run_date.isoformat(),
            (run_date + timedelta(days=window_days)).isoformat(),
            add_months(run_date, -recent_months).isoformat(),
            practitioners is None,
        ],
        snapshot=snapshot,
    ).to_pylist()
    tz = ctx.cfg.env.tz
    out = [Scoped(r["pid"], local_iso(r["next_appt"], tz), r["practitioner_id"], r["dept"]) for r in rows]
    if departments:
        out = [s for s in out if s.department in departments]
    return out


def drop_opted_out(ctx: Ctx, scoped: list[Scoped]) -> list[Scoped]:
    """D-147: patients on the research office's opt-out register (``tb_common.optout``) are never screened. The
    register is read as it stood when the job was received, so a re-run of an old job stays byte-identical (D-82).
    The removal is audited by count (who opted out is itself private)."""
    from tb_common.optout import opted_out

    gone = opted_out(as_of=ctx.job.received_at.isoformat())
    kept = [s for s in scoped if s.pid not in gone]
    if len(kept) != len(scoped):
        ctx.orch.audit.append(
            "screen.opt_out_removed",
            job_id=ctx.job.job_id,
            ruleset=ctx.job.ruleset,
            detail={"removed": len(scoped) - len(kept), "register": "optout"},
        )
    return kept


def opted_out_now(ctx: Ctx, pids: Iterable[str], where: str) -> frozenset[str]:
    """D-441 (review MED-3): the register read again, as it stands now, just before a run publishes or stores its
    lists: a patient who opted out while the run was going (or before a re-run of an old job) leaves its files, its
    mail and the pool. The scope read (:func:`drop_opted_out`) stays as of the job's receipt. Audited by count."""
    from tb_common.optout import opted_out

    want = set(pids)
    gone = frozenset(opted_out() & want) if want else frozenset()
    if gone:
        ctx.orch.audit.append(
            "screen.opt_out_at_publish",
            job_id=ctx.job.job_id,
            ruleset=ctx.job.ruleset,
            detail={"removed": len(gone), "where": where, "register": "optout"},
        )
    return gone


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
    prompt = pinned_judge(rs)
    mode = os.environ.get("TB_SCREEN_JUDGE", "agreement").strip().lower()
    verifier = ctx.services.verifier if mode != "single" else None
    return NoteJudge(ctx.services.lake, ctx.services.llm, prompt or "judge", job_id=ctx.job.job_id, verifier=verifier)


def pinned_judge(rs: Ruleset) -> str:
    """The judge prompt the approved ruleset pins (D-318): its version, held to the approved text and schema, so a
    newer registered version waits for the investigator's re-approval; a pinned text that changed is refused."""
    from tb_llm.prompt_registry import PromptRegistryError, pinned_name

    named = rs.manifest.models.judge_prompt if rs.manifest.models and rs.manifest.models.judge_prompt else "judge"
    try:
        return pinned_name(rs.manifest, named.rsplit("_v", 1)[0], named)
    except PromptRegistryError as exc:
        raise StepFailed("running", f"Ruleset {rs.id} v{rs.version}: {exc}") from exc


def structured_engine(ctx: Ctx, snapshot: str) -> StructuredEngine:
    """The SQL engine on ``snapshot``; with a trial database it reads the stored derived rows too (D-442)."""
    from orchestrator import derive

    return engine_from_env(
        os.environ.get("TB_SCREEN_ENGINE", "sql"),
        ctx.services.fhir,
        ctx.services.lake,
        snapshot,
        derive.store(derive.url_of(ctx.orch)),
    )


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


def provenance(ctx: Ctx, rs: Ruleset, meta: ReportMeta, judging: dict[str, Any] | None = None) -> dict[str, Any]:
    """FR-REP-01: what every report says about how it was made, as one block in the machine-readable JSON (the PDF
    and XLSX print the same values in their footer). Built only from the job, the ruleset and the run's ``judging``
    record, so a re-run of the job (same id, pinned clock and snapshot) writes the same bytes (FR-REP-02)."""
    s = ctx.cfg.settings
    ran = models_used(judging) != NO_MODEL
    prompts: list[str] = []
    if ran:
        pid = pinned_judge(rs)
        try:
            from tb_common.llm import load_prompt

            pr = load_prompt(pid)
            prompts.append(f"{pr.meta.id}_v{pr.meta.version}")
        except Exception:  # a missing prompt file is reported as the id alone, never fails the report
            prompts.append(pid)
    return {
        "study": rs.manifest.trial_alias or rs.id,
        "ruleset": rs.id,
        "ruleset_version": rs.version,
        "snapshot": meta.snapshot,
        "data_sources": [f"{s.data_source.type} (lake snapshot {meta.snapshot})"],
        "models": [m for m in [(judging or {}).get("judge_model"), (judging or {}).get("verifier_model")] if m]
        if ran
        else [],
        "model_summary": meta.model,
        "prompt_versions": prompts,
        "run_date": meta.run_date,
        "clock": meta.clock or "system clock",
        "job_id": meta.job_id,
        "language": meta.locale,
        "site": meta.site_id,
    }


def stage_funnel(rs: Ruleset, srun: ScreenRun, listed: int, n: Callable[[int], int]) -> list[list[Any]]:
    """The run as the one named funnel every page shows (M7), with the cascade's stage ids: S0 in scope, S1 after
    the coded filters, S3 patients whose notes the model read, S4 candidates (high + review) for a person. When the
    cascade ran the screen (D-103) the counts are its own stage log."""
    if srun.cascade:
        after = srun.cascade.get("n_after") or {}
        return [
            ["S0", n(int(after.get("S0", len(srun.scoped))))],
            ["S1", n(int(after.get("S1", 0)))],
            ["S3", n(int(srun.cascade.get("notes_read") or 0))],
            ["S4", n(listed)],
        ]
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
    return resolve_mrns(Path(ctx.cfg.env.secrets_dir), pids, ctx.orch.db.url)


def resolve_mrns(sec: Path, pids: list[str], url: str | None = None) -> dict[str, str]:
    """pid -> chart number from the pid map of the key under ``sec``; empty when the box has no map (no key: stub
    installs, no ingest yet). ``url``: the trial database (the orchestrator's; ``TB_DB_URL`` when None)."""
    key = sec / "pid_map.key"
    if not key_present(key):  # plain or wrapped under the KEK (T-210b)
        return {}
    from adapter.pidmap import PidMap

    pm = PidMap(key, url)
    try:
        return pm.resolve_many(pids)
    finally:
        pm.close()


def practitioner_names(ctx: Ctx) -> dict[str, str]:
    """``id -> "Name (id)"`` for the lists. The name comes from the records (the HIS practitioner table, D-120);
    ``settings.practitioners`` only fills a name the records do not hold (a settings name such as "Dr. A
    (synthetic)" is a placeholder, and showed on a public-data site before D-120)."""
    names = {k: v.name for k, v in (ctx.cfg.settings.practitioners or {}).items() if v.name}
    try:
        rows = ctx.services.lake.query("SELECT practitioner_id, name FROM practitioner WHERE name IS NOT NULL")
        found = rows.to_pylist()
    except Exception:  # an older snapshot without the name column: settings only
        found = []
    names.update({str(r["practitioner_id"]): str(r["name"]) for r in found if r.get("name")})
    ids = set(names) | set(ctx.cfg.settings.practitioners or {})
    return {k: f"{names.get(k) or k} ({k})" for k in sorted(ids)}


def evaluate_scope(
    ctx: Ctx,
    rs: Ruleset,
    run_date: date,
    snapshot: str,
    scoped: list[Scoped],
    only: set[str] | None = None,
    all_candidates: bool = False,
    judge: NoteJudge | None = None,
) -> dict[str, PatientVerdicts]:
    """The v1 evaluator over ``scoped``. ``judge``: the run's note judge, so its counts reach the run's ``judging``
    record (SCREEN with ``TB_SCREEN_PIPELINE=v1``); None builds one (:func:`judge_for`)."""
    judge = judge if judge is not None else judge_for(ctx, rs)
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


def study_scope(ctx: Ctx, ruleset: str) -> dict[str, Any] | None:
    """Who the study's set-up page says to screen (D-146, review J-26); None when it was never set (or the run has no
    trial database, as in some unit tests)."""
    url = getattr(getattr(ctx.orch, "db", None), "url", None)
    if not url:
        return None
    from orchestrator.studystore import screen_scope_of

    return screen_scope_of(str(url), ruleset)


def practitioners_of(ctx: Ctx, rs: Ruleset) -> list[str] | None:
    """The practitioners a run screens, None for the whole hospital. The job's ``pract=`` (or ``scope=hospital``)
    first, then the study's set-up page (D-146), then the ruleset's ``scopes.screen``."""
    opts = ctx.job.options or {}
    if opts.get("pract"):
        return [p.strip() for p in opts["pract"].split(",") if p.strip()]
    if (opts.get("scope") or "").lower() == "hospital":
        return None
    row = study_scope(ctx, rs.id)
    if row and row.get("mode") == "hospital":
        return None
    if row and row.get("mode") == "practitioners" and row.get("practitioners"):
        return list(row["practitioners"])
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    pract = list(sc.practitioners if sc and sc.practitioners else [])
    if not pract:
        raise StepFailed(
            "running",
            f"No one to screen for {rs.id}: choose the whole hospital or some doctors under 'Who to screen' on the "
            "study's set-up page, or give pract=<id,...>.",
        )
    return pract


def run_screen(
    ctx: Ctx,
    rs: Ruleset,
    run_date: date,
    snapshot: str,
    select: Callable[[list[Scoped]], list[Scoped]] | None = None,
) -> ScreenRun:
    """``select`` (MICROBATCH, D-397): picks the patients to evaluate from the scope (the new ones, within the night
    budget); SCREEN evaluates the whole scope."""
    opts = ctx.job.options or {}
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    practitioners = practitioners_of(ctx, rs)
    try:
        window = int(opts.get("window") or (sc.appointment_window_days if sc and sc.appointment_window_days else 180))
    except ValueError as exc:
        raise StepFailed("running", "window must be a number of days") from exc
    depts = [d.strip().upper() for d in opts["dept"].split(",")] if opts.get("dept") else []
    recent = int(sc.recent_encounter_months if sc and sc.recent_encounter_months else 12)
    # D-147: the research office's opt-out register applies to every screening run (and MICROBATCH's incident run)
    scoped = drop_opted_out(ctx, scope_patients(ctx, practitioners, run_date, window, recent, depts, snapshot))
    if select is not None:
        scoped = select(scoped)
    ctx.metrics(patients_scoped=len(scoped))
    judge = judge_for(ctx, rs)
    if select is not None and not scoped:  # nobody to evaluate: no model call, no audit of an empty run
        return ScreenRun(
            rs, run_date, snapshot, [], {}, [], list(practitioners or []), depts, window, judge, judging_info(judge),
            whole_hospital=practitioners is None,
        )  # fmt: skip
    judging = judging_info(judge)
    cascade: dict[str, Any] | None = None
    if pipeline() == "cascade":  # D-103: the v4 cascade is the screening engine
        cs = screen_with_cascade(
            ctx,
            rs,
            run_date,
            snapshot,
            [s.pid for s in scoped],
            judge,
            judging,
            threshold(ctx, rs),
            recent,
            max_pairs_of(opts),
        )
        results, judging, cascade = cs.results, cs.judging, cs.summary
        tiers = {t: sum(1 for v in results.values() if v.tier == t) for t in ("high", "review", "excluded")}
        ctx.orch.audit.append(
            "screen.evaluated",
            job_id=ctx.job.job_id,
            ruleset=rs.id,
            ruleset_version=rs.version,
            snapshot=snapshot,
            model=judge.llm.model if judge is not None else None,
            prompt_version=judge.prompt if judge is not None else None,
            detail={
                "engine": "cascade",
                "index_date": run_date.isoformat(),
                "patients": len(scoped),
                "tiers": tiers,
                "n_after": cascade["n_after"],
                "judging": judging,
                "budget": cascade.get("budget"),
            },
        )
    else:
        results = evaluate_scope(ctx, rs, run_date, snapshot, scoped, judge=judge)
        judging = judging_info(judge)  # after the run: its disagreements and failures, as the cascade path does
    # T-514 (D-362, review UX-008): each coded answer carries the record's value, unit, date and code for the person
    # who checks it; display only, after every answer is decided
    coded_values.attach(
        ctx.services.lake, rs.active(), {p: pv.verdicts for p, pv in results.items()}, run_date, snapshot
    )
    by_pid = {s.pid: s for s in scoped}
    stamp = job_stamp(ctx)  # evaluation time = the job's receipt: same inputs → same bytes (D-82)
    rows = [
        row(pv, by_pid[p].next_appointment, by_pid[p].practitioner_id, by_pid[p].department, stamp)
        for p, pv in results.items()
    ]
    rows.sort(key=sort_key)
    return ScreenRun(
        rs, run_date, snapshot, scoped, results, rows, list(practitioners or []), depts, window, judge, judging,
        cascade, whole_hospital=practitioners is None,
    )  # fmt: skip


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


def confirmed_facts(ctx: Ctx, pids: list[str]) -> set[str]:
    """The record ids of the site's confirmed facts for these patients (D-135): a coded record that a person typed
    or confirmed from a chart, not one the hospital's systems coded."""
    if not pids:
        return set()
    try:
        rows = ctx.services.lake.query("SELECT fid FROM site_fact WHERE basis = 'confirmed'").to_pylist()
    except Exception:  # an older snapshot has no site_fact table: no confirmed fact
        return set()
    return {str(r["fid"]) for r in rows if r.get("fid")}


def excluded_doc(ctx: Ctx, run: ScreenRun) -> dict[str, Any]:
    """Every patient the run excluded, with the criterion (or the scope or consent rule) that excluded them, where
    the answer came from (the coded records, a confirmed fact, or the notes with both models agreeing) and its
    evidence (review 2026-11-09 P-04, D-143). Stored with the job for the console's "Excluded patients and why"
    page; never mailed."""
    ex = [r for r in run.rows if r.tier == "excluded"]
    facts = confirmed_facts(ctx, [r.pid for r in ex])

    def source(v: Any) -> str:
        ev = v.evidence
        if ev is not None and (ev.reason == "note" or ev.quote):
            return "notes"
        refs = {x.rsplit("/", 1)[-1] for x in (ev.resource_refs or [])} if ev is not None else set()
        return "fact" if refs & facts else "coded"

    rows = []
    for r in ex:
        failing = [
            {"id": v.id, "source": source(v), **(v.evidence.model_dump(mode="json", exclude_none=True)
                                                 if v.evidence is not None else {})}
            for v in r.criteria if v.verdict == "fail"
        ]  # fmt: skip
        rows.append({"pid": r.pid, "criteria": failing, "actions": list(r.actions)})
    return {"ruleset": run.rs.id, "version": run.rs.version, "run_date": run.run_date.isoformat(),
            "snapshot": run.snapshot, "judging": run.judging or {}, "rows": rows}  # fmt: skip


def persist_pool(ctx: Ctx, rs: Ruleset, rows: list[CandidateRow]) -> None:
    gone = opted_out_now(ctx, [r.pid for r in rows], "pool")
    rows = [r for r in rows if r.pid not in gone]
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
    if not list_to and rs.manifest.kind == "cohort":
        # D-108: a cohort (registry) ruleset has no clinic list address; its member list goes to the coordinator who
        # asked (already allowed to request this study), never to the aggregate recipients
        list_to = [norm(ctx.job.requested_by)]
        routing = routing.model_copy(update={"list_to": list_to}) if routing else Routing(list_to=list_to)
    if not list_to:
        raise StepFailed("routing", f"Ruleset {rs.id} has no routing.list_to; patient lists cannot be sent.")
    listed = [r for r in rows if r.tier in ("high", "review") or (changes is not None and r.changed)]
    gone = opted_out_now(ctx, [r.pid for r in listed], "list")
    listed = [r for r in listed if r.pid not in gone]
    if changes is not None and gone:
        changes = [c for c in changes if c.pid not in gone]
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
    require_open(job.ruleset)  # D-386 (LIFE-008): no list for a study that is not open
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
    gone = opted_out_now(ctx, [r.pid for r in srun.rows], "publish")  # D-441: every file of the run
    if gone:
        srun.rows = [r for r in srun.rows if r.pid not in gone]
        srun.results = {p: v for p, v in srun.results.items() if p not in gone}
    cl = candidate_list(srun)
    meta = report_meta(ctx, rs, snapshot, run_date, srun.judging)
    stem = f"candidates_{rs.id}_v{rs.version}_{run_date.isoformat()}"
    body = json.dumps(dump(cl), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    deliveries, info = deliver_lists(
        ctx, rs, srun.rows, meta, stem, extra=(f"candidate_list_{rs.id}_v{rs.version}.json", body)
    )
    persist_pool(ctx, rs, [r for r in srun.rows if r.tier in ("high", "review")])
    excluded = json.dumps(excluded_doc(ctx, srun), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ctx.publish(f"excluded_{rs.id}_v{rs.version}.json", excluded, "phi", [])  # P-04: the console only, never mailed
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
            pract=t(lang, "screen.whole_hospital") if srun.whole_hospital else ", ".join(srun.practitioners),
            window=srun.window_days,
            scoped=n(len(srun.scoped)),
        ),
        judging_sentence(judging, lang),
        *([population_line(lang, rs.manifest.population)] if population_line(lang, rs.manifest.population) else []),
    ]
    # D-130 (review F-10): patients kept because a record is coded in a system the mapping does not know
    unknown_system = unknown_system_counts(srun.rows)
    if unknown_system:
        scope_lines.append(t(lang, "screen.unknown_system", n=n(unknown_system)))
    budget = (srun.cascade or {}).get("budget") or {}
    if budget.get("hit"):  # D-142 (review A-07): never a silent cap
        scope_lines.append(
            t(lang, "screen.budget_hit", max=budget.get("max_pairs"), n=n(int(budget.get("unprocessed") or 0)))
        )
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
                    "whole_hospital": srun.whole_hospital,
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
                "pipeline": srun.pipeline,
                "cascade": srun.cascade,
                "referrals": {k: n(v) for k, v in info["referrals"].items()},
                "unknown_by_criterion": {k: n(v) for k, v in sorted(unknown_by.items())},
                "unknown_code_system": n(unknown_system),
                "judging": judging,
                "provenance": provenance(ctx, rs, meta, judging),
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
