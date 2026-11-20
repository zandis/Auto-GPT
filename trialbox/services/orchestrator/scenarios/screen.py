"""SCREEN (SPEC §8.2): scope by practitioner appointments (+ recent encounters) → structured CQL per patient →
note criteria via RAG + judge for structured candidates → tiers → candidate workbook (phi) to ``list_to``, referral
workbooks per department (phi) to ``referral_to[dept]``, candidate_list.json (phi), summary PDF (aggregate) →
candidate pool persisted for MICROBATCH."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from matching import coded_values
from matching.coverage import unknown_system_counts
from tb_common import lakeprobe
from tb_common import provenance as ai_provenance
from tb_common.authz import COVER_RUN_OPTION, norm
from tb_common.dates import site_dates
from tb_common.llm import LlmError, LlmPromptUnqualified, load_prompt
from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset
from tb_common.subject import job_subject
from tb_common.timeutil import add_months
from tb_common.verdict_word import shown_of
from tb_contracts import CandidateList, CandidateRow, Judging, Routing, ScreenRunScope, TierSummary, dump

from orchestrator import answer_store, identifiers
from orchestrator import excluded as excluded_lines
from orchestrator.clients import StepFailed
from orchestrator.core import Ctx, Delivery, Outcome, job_language, job_stamp
from orchestrator.decision_context import (
    NO_CONTACT_ACTION,
    REFUSED_REASON,
    configured_note_block,
    decision_of,
    note_block_of,
)
from orchestrator.i18n import population_line, t
from orchestrator.reports import candidate_xlsx, screen_summary_pdf
from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios.evaluate import (
    NOTE_BLOCK_CODES,
    NoteJudge,
    PatientVerdicts,
    StructuredEngine,
    check_judge,
    engine_from_env,
    evaluate_patients,
    is_note_answer,
    not_in_snapshot,
    row,
    served,
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
WHERE pid IN (SELECT unnest(CAST($1 AS VARCHAR[]))) AND (deceased_date IS NOT NULL OR deceased IS TRUE)
ORDER BY pid
"""

log = logging.getLogger("orchestrator.screen")


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
    s2b_sources: dict[str, dict[str, Any]] | None = None  # T-203b (D-449): only when the flag vec.s2b was on
    coded_values_read: bool = True  # D-652: False when the values behind the coded answers could not be read

    @property
    def pipeline(self) -> str:
        return "cascade" if self.cascade else "v1"


def attach_values(lake: Any, rs: Ruleset, verdicts: dict[str, Any], run_date: date, snapshot: str | None) -> bool:
    """Put the coded values on the run's coded answers (:func:`matching.coded_values.attach`, display only). False:
    they could not be read (D-652); the run says so in what it stores."""
    return coded_values.attach(lake, rs.active(), verdicts, run_date, snapshot) is not None


def judging_info(judge: NoteJudge | None, ctx: Any = None) -> dict[str, Any]:
    """How note criteria were judged on this run: models, agreement mode, and whether a note answer could exclude
    (D-97). Aggregate metadata: goes into the candidate list, the summary PDF, the done mail and the console.
    ``ctx``: the job, so the record says the decision the job ran under (D-477); None for a caller with no job."""
    nb = note_block_of(judge, ctx)
    may_block, policy, reason, code = nb.may_block, nb.policy, nb.reason, nb.code
    return {
        "mode": judge.mode if judge is not None else "none",
        # G12 (D-960): the model that answered, by the name it answered under; the configured one until it has
        "judge_model": (served(judge, "judge") or judge.llm.model) if judge is not None else None,
        "verifier_model": (served(judge, "verifier") or judge.verifier.model)
        if judge is not None and judge.verifier is not None
        else None,
        "note_block": policy,
        "note_block_reason": reason,
        "note_block_code": code,
        "configured_note_block": configured_note_block(),
        "may_block": may_block,
        "disagreements": judge.disagreements if judge is not None else 0,
        "failures": judge.failures if judge is not None else 0,
    }


def judging_sentence(j: dict[str, Any], lang: str = "en") -> str:
    """One sentence for the mail and the PDF: who judged the notes and whether a note answer could exclude."""
    if j.get("mode") == "nothing":  # D-909: every criterion is a person's
        return t(lang, "screen.judging.nothing")
    if j.get("mode") == "none":
        return t(lang, "screen.judging.none")
    if j.get("may_block"):
        return t(lang, "screen.judging.pair", judge=j.get("judge_model"), verifier=j.get("verifier_model"))
    # the reason in the reader's language, from its code: the reason text is the English diagnostic (a failed canary's
    # is every failed model's line) and stays in the list's metadata and the log. A list from before the code: its text
    code = str(j.get("note_block_code") or "")
    why = t(lang, f"screen.judging.why.{code}") if code in NOTE_BLOCK_CODES else str(j.get("note_block_reason") or "")
    return t(lang, "screen.judging.single", judge=j.get("judge_model"), why=why)


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
    gone = decision_of(ctx).drop([s.pid for s in scoped], "screen.opt_out_removed")
    return [s for s in scoped if s.pid not in gone]


def opted_out_now(ctx: Ctx, pids: Iterable[str], where: str) -> frozenset[str]:
    """D-441 (review MED-3): the register read again, as it stands now, just before a run publishes or stores its
    lists: a patient who opted out while the run was going (or before a re-run of an old job) leaves its files, its
    mail and the pool. The scope read (:func:`drop_opted_out`) stays as of the job's receipt. Audited by count."""
    return decision_of(ctx).drop_now(pids, "screen.opt_out_at_publish", where=where)


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
    usable_judge_prompt(rs, prompt or "judge", ctx.services.llm)
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


def usable_judge_prompt(rs: Ruleset, prompt: str, llm: Any) -> None:
    """Stop the run before any model call when this box may not use the ruleset's judge prompt: the version the
    approval pinned has no qualification record where the box's model calls are checked (a PRODUCTION gateway,
    D-359), or the registry refuses it for another reason (said as such: a new approval does not mend a registry).
    Every note call would be refused with the same words, and the run would end as "the model did not answer" (G1
    rehearsal, 2026-11-12: a healthy model, 0 calls sent). Never another version in its place: the pinned prompt is
    what the investigator approved (D-318)."""
    env = getattr(getattr(llm, "gateway", None), "prompt_environment", None)  # a harness's gateway names its own
    head = f"Ruleset {rs.id} v{rs.version}: this box may not use its judge prompt {prompt}"
    try:
        load_prompt(prompt, env)
    except LlmPromptUnqualified as exc:
        raise StepFailed(
            "running",
            f"{head} ({exc}). No model was asked and nothing was sent. The model service is not the cause: the "
            f"study was approved on a prompt version this box does not serve. Approve the study again on this box "
            f"(it then pins the served version), or install the prompt's qualification record.",
        ) from exc
    except LlmError as exc:
        # any other refusal (a file that differs from the registry, an unregistered version, a broken file): a new
        # approval would pin the same broken entry, so the advice is the registry's, not the investigator's
        raise StepFailed(
            "running",
            f"{head} ({exc}). No model was asked and nothing was sent. The model service is not the cause: the "
            f"box's prompt registry refuses this prompt (its file or its entry is not what the release holds). "
            f"Approving again would not help: install the release's prompts again.",
        ) from exc


def structured_engine(ctx: Ctx, snapshot: str) -> StructuredEngine:
    """The SQL engine on ``snapshot``; it reads the stored derived rows while the flag is on (D-442)."""
    from orchestrator import derive

    return engine_from_env(
        os.environ.get("TB_SCREEN_ENGINE", "sql"),
        ctx.services.fhir,
        ctx.services.lake,
        snapshot,
        derive.reader_for(ctx),
    )


def scores_unverified(ctx: Ctx, rs: Ruleset, snapshot: str) -> bool:
    """D-442: while the stored-score read is on, whether this snapshot's scores were not verified (no finished derive
    batch) for a ruleset that decides on stored scores: the list's header says so."""
    from matching.stored_scores import unverified

    from orchestrator import derive

    try:
        return unverified(rs.active(), derive.reader_for(ctx), snapshot)
    except Exception:  # the store cannot be read: every score answer is unknown already, the line says so
        return derive.reader_for(ctx) is not None


def threshold(ctx: Ctx, rs: Ruleset) -> float:
    return decision_of(ctx).threshold(rs)


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
        "language": meta.locale,  # the report's language (the site's locale), not the notes' (G12, D-980)
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
        dates=site_dates(s.site)[0],  # 10C-13
    )


def pid_names(ctx: Ctx, pids: list[str]) -> dict[str, str]:
    """pid -> MRN from the in-box pid map (internal recipients only)."""
    return resolve_mrns(Path(ctx.cfg.env.secrets_dir), pids, ctx.orch.db.url)


def resolve_mrns(sec: Path, pids: list[str], url: str | None = None) -> dict[str, str]:
    """pid -> chart number from the pid map of the key under ``sec``; empty when the box has no map (no key: stub
    installs, no ingest yet). ``url``: the trial database (the orchestrator's; ``TB_DB_URL`` when None)."""
    return identifiers.charts_of(sec, pids, url)


def practitioner_names(ctx: Ctx) -> dict[str, str]:
    """``id -> "Name (id)"`` for the lists. The name comes from the records (the HIS practitioner table, D-120);
    ``settings.practitioners`` only fills a name the records do not hold (a settings name such as "Dr. A
    (synthetic)" is a placeholder, and showed on a public-data site before D-120)."""
    configured = ctx.cfg.settings.practitioners or {}
    try:
        rows = ctx.services.lake.query("SELECT practitioner_id, name FROM practitioner WHERE name IS NOT NULL")
        found = rows.to_pylist()
    except Exception as exc:
        # D-652: the names could not be read (the lake is down, or an older snapshot without the column). A settings
        # name is then all there is, and the list says that it is the settings' name, not the records'; a doctor
        # with no settings name is listed by the id, with "name not read". (A doctor who is not in the settings has
        # no label here at all: the lists show the bare id, as they do for any doctor without a name.)
        log.error("practitioner names were not read from the lake (%s)", type(exc).__name__)
        return {
            k: f"{v.name} ({k}; name from settings)" if v.name else f"{k} (name not read)"
            for k, v in sorted(configured.items())
        }
    names = {k: v.name for k, v in configured.items() if v.name}
    names.update({str(r["practitioner_id"]): str(r["name"]) for r in found if r.get("name")})
    ids = set(names) | set(configured)
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
        note_block=decision_of(ctx).note_block(judge).may_block,
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
            "judging": judging_info(judge, ctx),
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


def screen_v1(
    ctx: Ctx, rs: Ruleset, run_date: date, snapshot: str, scoped: list[Scoped], judge: NoteJudge | None
) -> dict[str, PatientVerdicts]:
    """SCREEN and MICROBATCH's new patients on the v1 evaluator, with the consent rule the cascade's S0 applies
    (D-477, review M2 and M1b): a patient whose latest statement refuses research use is out of scope and not
    evaluated; one whose latest statement denies contact is evaluated and never listed."""
    d = decision_of(ctx)
    refused, no_contact = d.refused(), d.no_contact()
    res = evaluate_scope(ctx, rs, run_date, snapshot, [s for s in scoped if s.pid not in refused], judge=judge)
    out: dict[str, PatientVerdicts] = {}
    for s in scoped:
        if s.pid in refused:
            pv = not_in_snapshot(rs, s.pid, reason=Reason.NOT_EVALUATED)
            out[s.pid] = PatientVerdicts(s.pid, pv.verdicts, "excluded", [REFUSED_REASON], pv.n_unknown)
            continue
        pv = res[s.pid]
        if s.pid in no_contact and pv.tier != "excluded":
            pv = PatientVerdicts(s.pid, pv.verdicts, "excluded", [*pv.actions, NO_CONTACT_ACTION], pv.n_unknown)
        out[s.pid] = pv
    return out


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


def _scope_terms(ctx: Ctx, rs: Ruleset, ask: bool) -> tuple[list[str] | None, list[str], int, int]:
    """Who a screen of ``rs`` looks at: the practitioners (``ask``: False when the patients are given), the
    departments, the appointment window in days and the months an encounter counts as recent."""
    opts = ctx.job.options or {}
    sc = rs.manifest.scopes.screen if rs.manifest.scopes and rs.manifest.scopes.screen else None
    practitioners = practitioners_of(ctx, rs) if ask else []
    try:
        window = int(opts.get("window") or (sc.appointment_window_days if sc and sc.appointment_window_days else 180))
    except ValueError as exc:
        raise StepFailed("running", "window must be a number of days") from exc
    depts = [d.strip().upper() for d in opts["dept"].split(",")] if opts.get("dept") else []
    recent = int(sc.recent_encounter_months if sc and sc.recent_encounter_months else 12)
    return practitioners, depts, window, recent


def screen_scope(ctx: Ctx, rs: Ruleset, run_date: date, snapshot: str) -> list[Scoped]:
    """The patients a screen of ``rs`` would look at now, the opt-out register applied: what :func:`run_screen`
    hands its ``select`` (D-646: the weekly run counts its excluded patients in scope before it spends its
    allowance, and passes the list on as ``scope``)."""
    return screen_scope_read(ctx, rs, run_date, snapshot)[0]


def screen_scope_read(ctx: Ctx, rs: Ruleset, run_date: date, snapshot: str) -> tuple[list[Scoped], list[str]]:
    """:func:`screen_scope`, and the patients of the scope the opt-out register removed (10E-12, D-1259: the
    nightly job counts them in its pre-filter record; the ids are never stored)."""
    practitioners, depts, window, recent = _scope_terms(ctx, rs, True)
    raw = scope_patients(ctx, practitioners, run_date, window, recent, depts, snapshot)
    kept = drop_opted_out(ctx, raw)
    keep = {s.pid for s in kept}
    return kept, [s.pid for s in raw if s.pid not in keep]


def run_screen(
    ctx: Ctx,
    rs: Ruleset,
    run_date: date,
    snapshot: str,
    select: Callable[[list[Scoped]], list[Scoped]] | None = None,
    given: list[Scoped] | None = None,
    scope: list[Scoped] | None = None,
) -> ScreenRun:
    """``select`` (MICROBATCH, D-397): picks the patients to evaluate from the scope (the new ones, within the night
    budget); SCREEN evaluates the whole scope. ``given`` (MICROBATCH, T-707, D-476): exactly these patients, with no
    scope query (pool rows of another criteria version, screened again in full); the register still applies.
    ``scope`` (MICROBATCH, D-646): the study's scope as :func:`screen_scope` gave it to the caller a moment ago, so
    it is not asked for twice."""
    opts = ctx.job.options or {}
    practitioners, depts, window, recent = _scope_terms(ctx, rs, given is None)
    # D-147: the research office's opt-out register applies to every screening run (and MICROBATCH's incident run)
    if given is not None:
        scoped = drop_opted_out(ctx, list(given))
    elif scope is not None:
        scoped = list(scope)
    else:
        scoped = drop_opted_out(ctx, scope_patients(ctx, practitioners, run_date, window, recent, depts, snapshot))
    if select is not None:
        scoped = select(scoped)
    ctx.metrics(patients_scoped=len(scoped))
    judge = judge_for(ctx, rs)
    chosen = select is not None or given is not None
    if chosen and not scoped:  # nobody to evaluate: no model call, no audit of an empty run
        return ScreenRun(
            rs, run_date, snapshot, [], {}, [], list(practitioners or []), depts, window, judge,
            judging_info(judge, ctx),
            whole_hospital=practitioners is None,
        )  # fmt: skip
    judging = judging_info(judge, ctx)
    cascade: dict[str, Any] | None = None
    s2b_sources: dict[str, dict[str, Any]] | None = None
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
        results, judging, cascade, s2b_sources = cs.results, cs.judging, cs.summary, cs.s2b_sources
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
        results = screen_v1(ctx, rs, run_date, snapshot, scoped, judge)
        judging = judging_info(judge, ctx)  # after the run: its disagreements and failures, as the cascade path does
    # T-514 (D-362, review UX-008): each coded answer carries the record's value, unit, date and code for the person
    # who checks it; display only, after every answer is decided
    values_read = attach_values(
        ctx.services.lake, rs, {p: pv.verdicts for p, pv in results.items()}, run_date, snapshot
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
        cascade, whole_hospital=practitioners is None, s2b_sources=s2b_sources, coded_values_read=values_read,
    )  # fmt: skip


def s2b_source_doc(run: ScreenRun) -> dict[str, Any] | None:
    """T-203b (D-449): per patient of the run, where S2b ranked from (the vector store or on the fly), why a pair fell
    back and the model of each; None when the flag vec.s2b was off (no file, the run's outputs as before)."""
    if run.s2b_sources is None:
        return None
    return {"ruleset": run.rs.id, "version": run.rs.version, "run_date": run.run_date.isoformat(),
            "snapshot": run.snapshot, "flag": "vec.s2b", "patients": run.s2b_sources}  # fmt: skip


def publish_s2b_source(ctx: Ctx, run: ScreenRun) -> None:
    """T-203b (D-449): the S2b source per patient, with the job (label ``phi``, never mailed), on every path that ran
    the cascade with the flag ``vec.s2b`` on (SCREEN, MICROBATCH); nothing when it was off. The register is read
    again as it stands now (D-441): an opted-out patient leaves this file too."""
    sources = getattr(run, "s2b_sources", None)  # a run built before T-203b (or a test's stand-in) has none
    if sources is None:
        return
    gone = opted_out_now(ctx, list(sources), "s2b_source") if sources else frozenset()
    run.s2b_sources = {p: v for p, v in sources.items() if p not in gone}
    doc = s2b_source_doc(run)
    if doc is not None:
        ctx.publish(
            f"s2b_source_{run.rs.id}_v{run.rs.version}.json",
            json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"),
            "phi",
            [],
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
        summary=TierSummary(**tiers, coded_values_not_read=values_not_read(listed)),
        judging=Judging(**run.judging) if run.judging else None,
    )


def values_not_read(rows: list[CandidateRow]) -> int | None:
    """How many rows of the list say the values behind their coded answers were not read (D-653): the rows of the
    list itself, so the figure can be checked against it. None for none, so a run that read everything writes its
    summary as before."""
    return sum(1 for r in rows if r.coded_values == "not read") or None


def confirmed_facts(ctx: Ctx, pids: list[str]) -> set[str] | None:
    """The record ids of the site's confirmed facts for these patients (D-135): a coded record that a person typed
    or confirmed from a chart, not one the hospital's systems coded. Empty: there is none (also on a snapshot from
    before the site facts, which the lake is asked, D-649). None: they could not be read (D-652)."""
    if not pids:
        return set()
    try:
        rows = lakeprobe.rows_or_no_table(
            ctx.services.lake, "SELECT fid FROM site_fact WHERE basis = 'confirmed'", [], None, "site_fact"
        )
    except Exception as exc:
        log.error("the confirmed facts were not read from the lake (%s)", type(exc).__name__)
        return None
    return {str(r["fid"]) for r in rows or [] if r.get("fid")}


def excluded_doc(ctx: Ctx, run: ScreenRun) -> dict[str, Any]:
    """Every patient the run excluded, with the criterion (or the scope or consent rule) that excluded them, where
    the answer came from (the coded records, a confirmed fact, or the notes with both models agreeing) and its
    evidence (review 2026-11-09 P-04, D-143). Stored with the job for the console's "Excluded patients and why"
    page; never mailed.

    D-652: when the confirmed facts could not be read, an answer from the records is not said to come from "the
    coded records" (that would say no person confirmed it): its source is ``records`` and the document says
    ``confirmed_facts: not read``. ``coded_values``: whether the values behind the coded answers were read."""
    ex = [r for r in run.rows if r.tier == "excluded"]
    facts = confirmed_facts(ctx, [r.pid for r in ex])

    def source(v: Any) -> str:
        ev = v.evidence
        if ev is not None and (ev.reason == "note" or ev.quote):
            return "notes"
        if facts is None:
            return "records"
        refs = {x.rsplit("/", 1)[-1] for x in (ev.resource_refs or [])} if ev is not None else set()
        return "fact" if refs & facts else "coded"

    rows = []
    for r in ex:
        failing = [
            {"id": v.id, "source": source(v), **(v.evidence.model_dump(mode="json", exclude_none=True)
                                                 if v.evidence is not None else {}),
             # D-989: the calls behind the answer, for the console's review (``ai.confirmed``); [] is "no model"
             **({"prov": list(v.prov)} if v.prov is not None else {})}
            for v in r.criteria if shown_of(v)[0] == "fail"  # D-478: an answer that could not exclude is no reason
        ]  # fmt: skip
        rows.append({"pid": r.pid, "criteria": failing, "actions": list(r.actions)})
    return {"ruleset": run.rs.id, "version": run.rs.version, "run_date": run.run_date.isoformat(),
            "snapshot": run.snapshot, "judging": run.judging or {}, "rows": rows,
            "confirmed_facts": "not read" if facts is None else "read",
            "coded_values": "read" if getattr(run, "coded_values_read", True) else "not read"}  # fmt: skip


def publish_excluded(ctx: Ctx, rs: Ruleset, srun: ScreenRun) -> None:
    """NEW-B-48 (D-749): the run's excluded patients, one line each (T-694 part 5), and the old document beside it
    until the console reads the lines (lane C2's card); then the old one goes. Both: the console only, never mailed
    (P-04)."""
    doc = excluded_doc(ctx, srun)
    rows = doc.pop("rows")
    ctx.publish(f"excluded_{rs.id}_v{rs.version}.jsonl", excluded_lines.write_jsonl(doc, rows), "phi", [])
    old = json.dumps({**doc, "rows": rows}, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    ctx.publish(f"excluded_{rs.id}_v{rs.version}.json", old, "phi", [])


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


def list_recipients(routing: Routing | None, kind: str | None, requester: str,
                    options: dict[str, str] | None) -> list[str]:  # fmt: skip
    """Who receives a run's patient-level lists: the ruleset's ``list_to``. D-108: a cohort (registry) ruleset has no
    clinic list address; its member list goes to the coordinator who asked (already allowed to request this study),
    never to the aggregate recipients. 9f-3 (D-1383): not to a person who asked by a right held only through a cover
    of the PI (``COVER_RUN_OPTION``, set by the console): a cover gives no export, so such a run has no recipient of
    its own and is refused for its routing, as a run with no ``list_to``."""
    list_to = sorted(set(routing.list_to or [])) if routing else []
    if not list_to and kind == "cohort" and (options or {}).get(COVER_RUN_OPTION) != "1":
        list_to = [norm(requester)]
    return list_to


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
    list_to = list_recipients(routing, rs.manifest.kind, ctx.job.requested_by, ctx.job.options)
    if list_to and not (routing and routing.list_to):
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


def record_model_uses(ctx: Ctx, rs: Ruleset, srun: ScreenRun) -> int:
    """D-989: ``ai.used`` for each verdict a model answered on this run, every row the run read (after the opt-outs)
    and not only the list: an excluded patient's too, an exclusion being the model use with the most at stake (lane
    C2's finding). The patient by pseudonym only. The number of verdicts recorded."""
    return ai_provenance.verdicts_used(ctx.orch.audit, rs.id, rs.version, ctx.job.job_id, srun.rows)


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
    record_model_uses(ctx, rs, srun)
    # D-1360 (card 10A-4): every answer of the run, listed or not, after the opt-outs, in the answer store
    answer_store.record(ctx, rs.id, rs.version, srun.results, run_date, snapshot)
    meta = report_meta(ctx, rs, snapshot, run_date, srun.judging)
    unverified = scores_unverified(ctx, rs, snapshot)  # D-442: the list says so in its own header
    if unverified:
        meta = replace(meta, notice=t(job_language(ctx), "screen.scores_unverified", snapshot=snapshot))
    stem = f"candidates_{rs.id}_v{rs.version}_{run_date.isoformat()}"
    body = json.dumps(dump(cl), ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    deliveries, info = deliver_lists(
        ctx, rs, srun.rows, meta, stem, extra=(f"candidate_list_{rs.id}_v{rs.version}.json", body)
    )
    persist_pool(ctx, rs, [r for r in srun.rows if r.tier in ("high", "review")])
    publish_excluded(ctx, rs, srun)
    publish_s2b_source(ctx, srun)
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
        *([meta.notice] if meta.notice else []),
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
                "scores_unverified": bool(meta.notice),
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
