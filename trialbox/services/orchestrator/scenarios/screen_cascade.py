"""SCREEN through the v4 cascade (D-103).

A screening run scopes its patients as before (practitioner appointments and recent encounters, ``screen.py``) and
then hands that population to :func:`matching.cascade.run_cascade`: S0 consent and scope, S1 the compiled SQL of the
approved ruleset (filters first, never a model), S2 the bilingual lexicon on the notes in the window, S2b the
semantic ranking that picks the excerpts, S3 the note judge in exclusion-power order, S4 a second opinion on
would-be strong candidates, tiers. S5 (the person's decision) stays with the coordinator on the console and in the
candidate workbook, so the cascade runs without a reviewer.

The judge is the orchestrator's own LLM client (the same gateway route, prompt, audit line and two-model agreement
rule as the v1 note judge), wrapped as a cascade :class:`JudgeClient`. The cascade's traces come back as the same
``CandidateRow`` verdicts, tiers and actions every report, mail, pool and console page already understands, so the
one named funnel (S0 / S1 / S3 / S4, D-102) is now the engine's own stage log.

``TB_SCREEN_PIPELINE=v1`` restores the v1 evaluator (per-patient CQL/SQL plus RAG judge) for a measured comparison.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from matching.cascade import CascadeConfig, CascadeError, CascadeResult, run_cascade
from matching.cascade.engine import NOT_AT_INDEX
from matching.cascade.judge import JudgeReply
from matching.cascade.model import Outcome, PatientTrace
from tb_common.reasons import Reason, code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence, Opinion

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.scenarios.evaluate import (
    MAX_JUDGE_FAILURE_SHARE,
    NoteJudge,
    PatientVerdicts,
    effective_note_block,
    not_in_snapshot,
)
from orchestrator.twophase import two_phase

PIPELINES = ("cascade", "v1")

# cascade tier → candidate-list tier (the v1 vocabulary every output uses)
TIER = {
    "strong": "high",
    "potential:uncertain": "review",
    "potential:data_gap": "review",
    "excluded": "excluded",
    "watchlist": "excluded",
    "out_of_scope": "excluded",
}


def pipeline() -> str:
    """``TB_SCREEN_PIPELINE``: ``cascade`` (default, D-103) or ``v1``."""
    v = os.environ.get("TB_SCREEN_PIPELINE", "cascade").strip().lower() or "cascade"
    if v not in PIPELINES:
        raise ValueError(f"TB_SCREEN_PIPELINE must be one of {', '.join(PIPELINES)}, not {v!r}")
    return v


@dataclass
class OrchestratorJudge(NoteJudge):
    """The cascade's ``JudgeClient`` over the orchestrator's note judge (D-118: one note-judge path).

    It *is* the :class:`NoteJudge`: the S3 question goes through :meth:`NoteJudge.judge_excerpts`, so the same prompt,
    gateway route, audit line, quote check and two-model rule (:func:`tb_common.pair.combine`) apply as on every other
    path. The S4 second opinion goes to the verifier when there is one, else back to the judge, as one plain call.
    Failures count like the v1 judge's (:func:`check_failures`)."""

    @classmethod
    def from_note_judge(cls, nj: NoteJudge) -> OrchestratorJudge:
        return cls(lake=nj.lake, llm=nj.llm, prompt=nj.prompt, job_id=nj.job_id, verifier=nj.verifier)

    def judge(
        self,
        *,
        role: str,
        criterion_text: str,
        note_question: str,
        index_date: date,
        excerpts: list[dict[str, Any]],
        study_id: str,
        data_class: str,
        step_id: str,
        purpose: str,
    ) -> JudgeReply:
        if role == "judge":
            r = self.judge_excerpts(criterion_text, note_question, index_date, excerpts)
        else:  # S4: one opinion from the other model
            other = self.verifier if self.verifier is not None else self.llm
            r = self.judge_excerpts(criterion_text, note_question, index_date, excerpts, verify=False, primary=other)
        return JudgeReply(
            verdict=r.predicate,
            confidence=r.confidence,
            quote=r.quote,
            quote_date=r.quote_date,
            reason=r.reason or "",
            call_id=r.call_id,
            build_sha=r.model,
            prompt=r.prompt,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            opinions=list(r.opinions),
        )


def check_failures(judge: OrchestratorJudge | None) -> None:
    """The v1 rule (:func:`orchestrator.scenarios.evaluate.check_judge`): a few unanswered checks stay ``unknown``;
    more than the share means the model was down and the list would silently be a filters-only list."""
    if judge is None or not judge.failures:
        return
    total = judge.calls + judge.failures
    if judge.failures > MAX_JUDGE_FAILURE_SHARE * total:
        raise StepFailed(
            "judging",
            f"The model did not answer {judge.failures} of {total} note checks, so the note-based criteria could not "
            f"be judged. Nothing was sent; send the request again when the model is back.",
        )


# --------------------------------------------------------------------------------------------- traces → verdicts
def verdict_of(o: Outcome) -> CriterionVerdict:
    """One cascade outcome as the candidate-list verdict: the verified span (document, quote, date), the lake records
    of a coded answer, the judge's confidence and the stage's reason."""
    refs: list[str] = []
    quote: str | None = None
    quote_date: str | None = None
    confidence: float | None = None
    opinions: list[Opinion] = []
    for e in o.evidence:
        if e.get("opinions"):
            opinions = [Opinion(**x) for x in e["opinions"]]
        if e.get("did"):
            refs.append(f"DocumentReference/{e['did']}")
            quote = str(e.get("quote")) if e.get("quote") else quote
            quote_date = str(e.get("date")) if e.get("date") else quote_date
        elif e.get("source") == "lake" and e.get("record"):
            refs.append(str(e["record"]))
        if e.get("confidence") is not None:
            confidence = float(e["confidence"])
    status = o.status
    if status == "pass" and o.unknown_kind == "data_gap":
        status = "unknown"  # S1 kept the patient on a null exclusion value; the list says "unknown" as v1 did
    return CriterionVerdict(
        id=o.criterion_id,
        verdict=status,
        evidence=Evidence(
            resource_refs=refs[:20],
            quote=quote,
            quote_date=quote_date,
            confidence=confidence,
            reason=code_of(o.reason, status, bool(quote)),  # a code, never the engine's or the model's words (D-118)
            opinions=opinions or None,  # both quotes when the two checks disagree (D-120)
        ),
    )


def verdicts_of(rs: Ruleset, t: PatientTrace, dated: bool = False) -> PatientVerdicts:
    """A patient's trace as the row every report understands: verdicts in protocol order, the candidate-list tier,
    the actions of the open criteria and the number of unknowns. ``dated``: the snapshot holds this patient, so a
    patient without a base row was dropped for a death or birth date, not for being absent."""
    vs: list[CriterionVerdict] = []
    actions: list[str] = []
    unknown = 0
    for c in rs.active():
        if c.kind not in ("inclusion", "exclusion"):
            continue
        o = t.outcomes.get(c.id)
        if o is None:
            vs.append(
                CriterionVerdict(
                    id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason=Reason.NOT_EVALUATED.value)
                )
            )
            continue
        v = verdict_of(o)
        vs.append(v)
        if v.verdict == "unknown":
            unknown += 1
        if (v.verdict in ("unknown", "pending_human") or (o.status == "fail" and not o.hard)) and c.action:
            actions.append(c.action)
    if not t.in_scope and t.scope_reason == NOT_AT_INDEX:
        # no base row: never "excluded" with the engine's words; a person looks (D-142, review B-02)
        return not_in_snapshot(rs, t.pid, reason=Reason.CHECK_DATES if dated else Reason.NOT_IN_SNAPSHOT)
    tier = TIER.get(t.tier, "review")
    if tier == "high" and unknown:
        tier = "review"  # an open question (null value, data gap) is a person's check, as in v1
    if not t.in_scope:
        tier = "excluded"
        actions.append(t.scope_reason or "out of scope")
    elif tier != "excluded" and not t.contact_ok:
        tier = "excluded"
        actions.append("contact: deny (FHIR Consent) — never listed")
    seen: set[str] = set()
    acts = [a for a in actions if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
    return PatientVerdicts(t.pid, vs, tier, acts, unknown)


def judged(t: PatientTrace) -> bool:
    """Whether the model read this patient's notes (an S3/S4 outcome with a judge call behind it)."""
    return any(o.stage in ("S3", "S4") and any("call_id" in e for e in o.evidence) for o in t.outcomes.values())


def summary(res: CascadeResult) -> dict[str, Any]:
    """The run's aggregate provenance for ``screen_<stem>.json`` and the console: stage log, counts and budgets. No
    patient ids."""
    m = res.metrics
    return {
        "pipeline": "cascade",
        "ir_hash": res.ir_hash,
        "semantics": res.semantics,
        "n_after": dict(m.n_after),
        "notes_read": sum(1 for t in res.traces.values() if judged(t)),
        "opted_out": sum(1 for t in res.traces.values() if not t.in_scope and t.scope_reason != NOT_AT_INDEX),
        "not_at_index": sum(1 for t in res.traces.values() if t.scope_reason == NOT_AT_INDEX),
        "contact_denied": sum(1 for t in res.traces.values() if t.in_scope and not t.contact_ok),
        "stages": [
            {
                "stage": s.stage,
                "patients_in": s.patients_in,
                "patients_out": s.patients_out,
                "pairs_in": s.pairs_in,
                "pairs_out": s.pairs_out,
                "detail": {k: v for k, v in s.detail.items() if isinstance(v, (str, int, float, bool)) or v is None},
            }
            for s in res.stages
        ],
        "metrics": {
            "note_criteria": m.note_criteria,
            "pairs_s2_hit": m.pairs_s2_hit,
            "pairs_s2_zero_hit": m.pairs_s2_zero_hit,
            "pairs_s2_no_notes": m.pairs_s2_no_notes,
            "pairs_s2b_above": m.pairs_s2b_above,
            "pairs_s2b_below": m.pairs_s2b_below,
            "pairs_judged": dict(m.pairs_judged),
            "tokens_in": m.tokens_in,
            "tokens_out": m.tokens_out,
            "cache_hits": m.cache_hits,
            "llm_share": m.llm_share,
            "unprocessed": m.unprocessed,
            "gateway_refusals": m.gateway_refusals,
        },
        "applied": list(res.applied),
        "note_criteria": list(res.note_criteria),
        "human_criteria": list(res.human_criteria),
    }


# --------------------------------------------------------------------------------------------- the run
@dataclass
class CascadeScreen:
    results: dict[str, PatientVerdicts]
    judging: dict[str, Any]
    summary: dict[str, Any]
    judge: OrchestratorJudge | None


# D-142 (review A-07): SCREEN's budget of model calls is explicit (job option ``max_pairs``, else
# TB_SCREEN_MAX_PAIRS, else this default) and the run says when it ran out; calls run TB_SCREEN_LLM_CONCURRENCY at a
# time (compose sets it to the serving profile's vLLM --max-num-seqs)
SCREEN_MAX_PAIRS = 20000


def max_pairs_of(opts: dict[str, Any] | None = None) -> int:
    raw = str((opts or {}).get("max_pairs") or os.environ.get("TB_SCREEN_MAX_PAIRS") or SCREEN_MAX_PAIRS)
    try:
        v = int(raw)
    except ValueError as exc:
        raise StepFailed("running", "max_pairs must be a whole number of model calls") from exc
    if v < 1:
        raise StepFailed("running", "max_pairs must be at least 1")
    return v


def llm_concurrency(env: dict[str, str] | None = None) -> int:
    e = os.environ if env is None else env
    try:
        return max(1, min(64, int(e.get("TB_SCREEN_LLM_CONCURRENCY") or 1)))
    except ValueError:
        return 1


def held_in_snapshot(ctx: Ctx, pids: list[str], snapshot: str) -> set[str]:
    """Which of ``pids`` the snapshot's patient table holds (they were dropped for a date, not for being absent)."""
    if not pids:
        return set()
    rows = ctx.services.lake.query(
        "SELECT pid FROM patient WHERE list_contains(CAST($1 AS VARCHAR[]), pid)", [pids], snapshot=snapshot
    ).to_pylist()
    return {str(r["pid"]) for r in rows}


def screen_with_cascade(
    ctx: Ctx,
    rs: Ruleset,
    run_date: date,
    snapshot: str,
    pids: list[str],
    note_judge: NoteJudge | None,
    judging: dict[str, Any],
    confidence_floor: float,
    lookback_months: int,
    max_pairs: int = SCREEN_MAX_PAIRS,
) -> CascadeScreen:
    """Run the cascade over the scoped patients and return their verdict rows, the judging record and the stage log.

    The note-block policy in force (D-95/D-97) becomes the cascade's ``note_block``: without a verifier a note
    ``fail`` sends the patient to review and never out. Screening spends its tokens: every zero-hit pair goes to
    the judge (``absence_semantics=False``), nobody is sampled."""
    judge = OrchestratorJudge.from_note_judge(note_judge) if note_judge is not None else None
    may_block, _policy, _why = effective_note_block(note_judge)
    from embed_service.embedder import HashEmbedder

    from orchestrator import derive

    cfg = CascadeConfig(
        study_id=rs.id,
        run_date=run_date,
        lookback_months=max(1, lookback_months),
        index_mode="single",
        purpose="screening",
        step_id=f"screen:{ctx.job.job_id}",
        confidence_floor=confidence_floor,
        language=ctx.cfg.settings.site.locale or "en",
        sample_per_stratum=None,
        snapshot=snapshot,
        population=pids,
        note_block=may_block,
        absence_semantics=False,
        max_llm_items=max_pairs,
        llm_concurrency=llm_concurrency(),
        stored=derive.reader(ctx.orch),  # D-442: the stored-row read, as the v1 engine's (None: the flag is off)
    )
    try:
        res = two_phase(  # one GPU for both models (TB_MODEL_SWAP=sleep): judge pass, verifier pass, merge
            judge,
            lambda j: run_cascade(ctx.services.lake, rs, cfg, judge=j, embedder=HashEmbedder(), reviewer=None),
        )
    except CascadeError as exc:
        raise StepFailed("running", f"The screening cascade could not run for {rs.id} v{rs.version}: {exc}") from exc
    check_failures(judge)
    dropped = [pid for pid, t in res.traces.items() if t.scope_reason == NOT_AT_INDEX]
    held = held_in_snapshot(ctx, dropped, snapshot)
    results = {pid: verdicts_of(rs, res.traces[pid], pid in held) for pid in pids if pid in res.traces}
    for pid in pids:
        if pid not in results:  # not in the lake's patient table on this snapshot: a person looks (D-118)
            results[pid] = not_in_snapshot(rs, pid)
    if judge is not None:
        judging = {**judging, "disagreements": judge.disagreements, "failures": judge.failures}
        m = ctx.job.metrics
        ctx.metrics(
            llm_calls=(m.llm_calls if m else 0) + judge.calls,
            tokens_in=(m.tokens_in if m else 0) + judge.tokens_in,
            tokens_out=(m.tokens_out if m else 0) + judge.tokens_out,
        )
    out = summary(res)
    # D-142 (review A-07): the budget of model calls and whether it ran out, for the report and the job record
    out["budget"] = {"max_pairs": max_pairs, "unprocessed": res.metrics.unprocessed, "hit": res.metrics.unprocessed > 0}
    return CascadeScreen(results, judging, out, judge)


__all__ = [
    "PIPELINES",
    "TIER",
    "CascadeScreen",
    "OrchestratorJudge",
    "check_failures",
    "judged",
    "pipeline",
    "screen_with_cascade",
    "summary",
    "verdict_of",
    "verdicts_of",
]
