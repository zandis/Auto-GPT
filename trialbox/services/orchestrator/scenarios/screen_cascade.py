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
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from matching.cascade import CascadeConfig, CascadeError, CascadeResult, run_cascade
from matching.cascade.judge import JudgeReply
from matching.cascade.model import Outcome, PatientTrace
from tb_common.llm import LlmClient, LlmError
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.scenarios.evaluate import MAX_JUDGE_FAILURE_SHARE, NoteJudge, PatientVerdicts, effective_note_block

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
class OrchestratorJudge:
    """The cascade's ``JudgeClient`` over the orchestrator's LLM client(s).

    Same prompt, same gateway route and audit line as :class:`NoteJudge`; with a ``verifier`` every decided S3 answer
    is put to the second model and stands only when both agree (D-89, D-95). The S4 second opinion goes to the
    verifier when there is one, else back to the judge. Failures count like the v1 judge's (:func:`check_failures`)."""

    llm: LlmClient
    prompt: str = "judge"
    job_id: str | None = None
    verifier: LlmClient | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: int = 0
    disagreements: int = 0

    @classmethod
    def from_note_judge(cls, nj: NoteJudge) -> OrchestratorJudge:
        return cls(nj.llm, nj.prompt, nj.job_id, nj.verifier)

    def _ask(self, client: LlmClient, variables: dict[str, Any]) -> JudgeReply:
        res = client.chat_json(self.prompt, variables, job_id=self.job_id)
        self.calls += 1
        self.tokens_in += res.tokens_in
        self.tokens_out += res.tokens_out
        d = res.data if isinstance(res.data, dict) else {}
        qd = d.get("quote_date")
        return JudgeReply(
            verdict=str(d.get("verdict", "unknown")),
            confidence=float(d.get("confidence") or 0.0),
            quote=d.get("quote"),
            quote_date=None if qd is None else str(qd),
            reason=str(d.get("reason") or ""),
            call_id=res.output_sha[:16],
            build_sha=res.model,
            prompt=f"{res.prompt_id}@{res.prompt_version}",
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
        )

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
        variables = {
            "criterion_text": criterion_text,
            "note_question": note_question,
            "index_date": index_date.isoformat(),
            "excerpts": [{k: e.get(k) for k in ("date", "note_type", "text")} for e in excerpts],
        }
        primary = self.verifier if role != "judge" and self.verifier is not None else self.llm
        try:
            first = self._ask(primary, variables)
        except LlmError as exc:
            self.failures += 1
            return JudgeReply("unknown", 0.0, None, None, f"judge unavailable: {str(exc)[:120]}")
        if role != "judge" or self.verifier is None or first.verdict not in ("pass", "fail"):
            return first
        try:
            second = self._ask(self.verifier, variables)
        except LlmError as exc:
            self.failures += 1
            return JudgeReply("unknown", 0.0, None, None, f"verifier unavailable: {str(exc)[:120]}")
        t_in, t_out = first.tokens_in + second.tokens_in, first.tokens_out + second.tokens_out
        if second.verdict == first.verdict:
            return replace(first, tokens_in=t_in, tokens_out=t_out)
        self.disagreements += 1
        return JudgeReply(
            "unknown",
            0.0,
            None,
            None,
            f"judge/verifier disagree ({first.verdict}/{second.verdict}); needs a human look",
            call_id=first.call_id,
            build_sha=first.build_sha,
            prompt=first.prompt,
            tokens_in=t_in,
            tokens_out=t_out,
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
    for e in o.evidence:
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
            resource_refs=refs[:20], quote=quote, quote_date=quote_date, confidence=confidence, reason=o.reason or None
        ),
    )


def verdicts_of(rs: Ruleset, t: PatientTrace) -> PatientVerdicts:
    """A patient's trace as the row every report understands: verdicts in protocol order, the candidate-list tier,
    the actions of the open criteria and the number of unknowns."""
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
                    id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason="not evaluated")
                )
            )
            continue
        v = verdict_of(o)
        vs.append(v)
        if v.verdict == "unknown":
            unknown += 1
        if (v.verdict in ("unknown", "pending_human") or (o.status == "fail" and not o.hard)) and c.action:
            actions.append(c.action)
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
        "opted_out": sum(1 for t in res.traces.values() if not t.in_scope),
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
) -> CascadeScreen:
    """Run the cascade over the scoped patients and return their verdict rows, the judging record and the stage log.

    The note-block policy in force (D-95/D-97) becomes the cascade's ``note_block``: without a verifier a note
    ``fail`` sends the patient to review and never out. Screening spends its tokens: every zero-hit pair goes to
    the judge (``absence_semantics=False``), nobody is sampled."""
    judge = OrchestratorJudge.from_note_judge(note_judge) if note_judge is not None else None
    may_block, _policy, _why = effective_note_block(note_judge)
    from embed_service.embedder import HashEmbedder

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
    )
    try:
        res = run_cascade(ctx.services.lake, rs, cfg, judge=judge, embedder=HashEmbedder(), reviewer=None)
    except CascadeError as exc:
        raise StepFailed("running", f"The screening cascade could not run for {rs.id} v{rs.version}: {exc}") from exc
    check_failures(judge)
    results = {pid: verdicts_of(rs, res.traces[pid]) for pid in pids if pid in res.traces}
    for pid in pids:
        if pid not in results:  # not in the lake's patient table on this snapshot: nothing to say
            results[pid] = PatientVerdicts(pid, [], "excluded", ["not in the snapshot"], 0)
    if judge is not None:
        judging = {**judging, "disagreements": judge.disagreements, "failures": judge.failures}
        m = ctx.job.metrics
        ctx.metrics(
            llm_calls=(m.llm_calls if m else 0) + judge.calls,
            tokens_in=(m.tokens_in if m else 0) + judge.tokens_in,
            tokens_out=(m.tokens_out if m else 0) + judge.tokens_out,
        )
    return CascadeScreen(results, judging, summary(res), judge)


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
