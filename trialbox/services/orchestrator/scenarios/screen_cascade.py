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

import contextlib
import hashlib
import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from matching import decision
from matching.cascade import CascadeConfig, CascadeError, CascadeResult, run_cascade
from matching.cascade.engine import NOT_AT_INDEX
from matching.cascade.judge import JudgeReply
from matching.cascade.model import Outcome, PatientTrace
from tb_common.reasons import Reason, code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence, Opinion

from orchestrator.clients import StepFailed
from orchestrator.core import Ctx
from orchestrator.decision_context import decision_of
from orchestrator.jobs import llm_concurrency
from orchestrator.scenarios.evaluate import (
    MAX_JUDGE_FAILURE_SHARE,
    NoteJudge,
    PatientVerdicts,
    is_pair,
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
    def from_note_judge(cls, nj: NoteJudge, in_flight: int = 0) -> OrchestratorJudge:
        return cls(
            lake=nj.lake, llm=nj.llm, prompt=nj.prompt, job_id=nj.job_id, verifier=nj.verifier, in_flight=in_flight
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


log = logging.getLogger("orchestrator")
VEC_FLAG = "vec.s2b"  # T-203b (D-449): S2b from the vector store; off until the S2b threshold refit after G1 (D-429)


def vec_s2b_on() -> bool:
    """The flag ``vec.s2b`` as stored (``/ops/flags``); off when it has no row or the flag store cannot be read."""
    from tb_common.flags import read

    return read(VEC_FLAG) == "on"


VEC_OPTION = "vec_s2b"  # the job record's copy of the flag, written at the job's first S2b (D-449, review LOW 4)


def job_vec_s2b(ctx: Ctx) -> bool:
    """The flag ``vec.s2b`` for this job, decided once per job execution (MICROBATCH runs several studies; all
    take the same path) and, when on, written into the job record (``options.vec_s2b``; with the flag off the record
    stays as before). A re-run of an old job takes the path its record says, with one limit: a recorded "on" applies
    only while the flag is on, so an operator's switch-off is never overridden by a job record, and an option typed
    into a request can never switch the store on."""
    cached = getattr(ctx, "_tb_vec_s2b", None)
    if cached is not None:
        return bool(cached)
    flag_on = vec_s2b_on()
    opts = dict(getattr(ctx.job, "options", None) or {})
    recorded = opts.get(VEC_OPTION)
    if recorded is None:
        on = flag_on
        if on:  # written only when on: with the flag off the job record stays as before (D-449 item 2)
            ctx.update(options={**opts, VEC_OPTION: "on"})
    else:
        on = recorded == "on" and flag_on
    with contextlib.suppress(AttributeError):  # a stand-in context without attributes: read again next time
        ctx._tb_vec_s2b = on  # type: ignore[attr-defined]
    return on


class _VectorCache:
    """Vectors the embed service gave, by model and text hash, least recently used out first (red of 2026-11-15:
    S2b embeds a patient's window sentences for every zero-hit criterion, and again for every protocol; the same
    sentence is now embedded once). ``TB_EMBED_CACHE_VECTORS`` of them (about 4 kB each); in this process only."""

    def __init__(self, size: int) -> None:
        from collections import OrderedDict

        self.size = size
        self._d: OrderedDict[tuple[str, str], tuple[float, ...]] = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> _VectorCache:
        raw = (os.environ.get("TB_EMBED_CACHE_VECTORS") or "").strip()
        return cls(max(0, int(raw)) if raw else 20000)

    @staticmethod
    def _key(model: str, text: str) -> tuple[str, str]:
        return model, hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, model: str, text: str) -> list[float] | None:
        k = self._key(model, text)
        with self._lock:
            v = self._d.get(k)
            if v is None:
                return None
            self._d.move_to_end(k)
            return list(v)

    def put(self, model: str, text: str, vec: list[float]) -> None:
        if self.size <= 0:
            return
        k = self._key(model, text)
        with self._lock:
            self._d[k] = tuple(vec)
            self._d.move_to_end(k)
            while len(self._d) > self.size:
                self._d.popitem(last=False)


_VECTORS = _VectorCache.from_env()


class _Served:
    """The embed service's model for one job. NEW-LLM-2 (review): a service that stops answering, or changes its model,
    after the probe stops the job with a sentence; never a generic error, never two embedders in one run."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model = str(inner.model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        from matching.cascade.engine import CascadeError

        got: list[list[float] | None] = [_VECTORS.get(self.model, t) for t in texts]
        todo = list(dict.fromkeys(t for t, v in zip(texts, got, strict=True) if v is None))
        fresh: dict[str, list[float]] = {}
        if todo:
            try:
                out = self.inner.embed(todo)
            except Exception as exc:
                raise CascadeError(
                    f"the embed service stopped answering during the run ({type(exc).__name__}); send the request again"
                ) from exc
            if str(self.inner.model) != self.model:
                raise CascadeError(
                    f"the embed service changed its model during the run ({self.model} to {self.inner.model}); send "
                    f"the request again"
                )
            for t, v in zip(todo, out, strict=True):
                fresh[t] = list(v)
                _VECTORS.put(self.model, t, fresh[t])
        return [v if v is not None else fresh[t] for t, v in zip(texts, got, strict=True)]


def screen_embedder(url: str | None) -> Any:
    """The embedder SCREEN ranks note sentences with (NEW-LLM-2, LLM-002): the box's embed service when it serves a
    real model; the local hash stub when there is no service, it serves the stub or it does not answer (said in the
    log), so retrieval by meaning is off and a criterion with no lexicon term reads "not evaluated"."""
    from embed_service.embedder import HashEmbedder, HttpEmbedder

    if not url:
        return HashEmbedder()
    probe = None
    try:
        probe = HttpEmbedder(url)  # its own timeout: a refused connection fails at once, a hung one once per job
        probe.embed(["probe"])
    except Exception as exc:
        log.warning(
            "screening ranks note sentences with the hash stub: the embed service did not answer (%s)",
            type(exc).__name__,
        )
        return HashEmbedder()
    finally:
        if probe is not None:
            probe.client.close()
    if str(probe.model).startswith("hash"):
        return HashEmbedder()
    served = HttpEmbedder(url)
    served.model = probe.model
    return _Served(served)


_JOB_EMBEDDER: dict[str, Any] = {}  # job id -> its embedder: one probe per job (MICROBATCH screens many studies)


def job_embedder(ctx: Any) -> Any:
    """:func:`screen_embedder` once per job."""
    job_id = str(getattr(getattr(ctx, "job", None), "job_id", "") or "")
    if job_id and job_id in _JOB_EMBEDDER:
        return _JOB_EMBEDDER[job_id]
    url = getattr(getattr(getattr(ctx, "cfg", None), "env", None), "embed_url", None)
    got = screen_embedder(url)
    if job_id:
        while len(_JOB_EMBEDDER) >= 32:
            _JOB_EMBEDDER.pop(next(iter(_JOB_EMBEDDER)))
        _JOB_EMBEDDER[job_id] = got
    return got


def s2b_source(lake: Any, snapshot: str, on: bool) -> Any:
    """The cascade's stored-vector source on the job's pinned snapshot when the flag is on, else None (the S2b path
    of every run before T-203b, byte for byte)."""
    if not on:
        return None
    from vec.s2b import LakeVecSource

    return LakeVecSource(lake, snapshot)


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
def basis_of(o: Outcome, status: str, pair: bool) -> Any:
    """What a cascade outcome rests on (D-478): the records at S1, the models at S3/S4 (``pair`` when the run's
    judge is two different models; a hard fail is a pair's by the cascade's own rule, CAS-7), a person at S5.
    None for an answer nobody gave (unknown) and for S2's search rules, which no model and no record decides."""
    if status == "pending_human" or (o.stage == "S5" and status in ("pass", "fail")):
        return "person"
    if status not in ("pass", "fail"):
        return None
    if o.stage == "S1":
        return "coded"
    if o.stage in ("S3", "S4"):
        return "pair" if pair or o.hard else "single"
    return None


def _final(o: Outcome, status: str) -> bool | None:
    """T-707 (D-476): whether a "not met" was allowed to exclude when it was given. A soft fail (a single model's
    answer, CAS-7) says ``false`` in the stored row, so that no later re-tier reads it as an answer a pair gave; a
    judged fail that was allowed to exclude says ``true``; a coded answer needs neither."""
    if status != "fail":
        return None
    if not o.hard:
        return False
    return True if o.stage in ("S3", "S4") else None


def verdict_of(o: Outcome, pair: bool = False) -> CriterionVerdict:
    """One cascade outcome as the candidate-list verdict: the verified span (document, quote, date), the lake records
    of a coded answer, the judge's confidence and the stage's reason. ``pair``: the run's judge is two different
    models (the basis of its note answers, D-478)."""
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
        final=_final(o, status),
        basis=basis_of(o, status, pair),
    )


#: the policy of a caller that names none (a tool, a test): the cascade's default floor, and notes may **not**
#: exclude (review of T-709, LOW 7: the safe default; a run states its policy)
DEFAULT_POLICY = decision.Policy(threshold=0.75, note_block=False)


def verdicts_of(
    rs: Ruleset, t: PatientTrace, dated: bool = False, policy: decision.Policy | None = None, pair: bool = False
) -> PatientVerdicts:
    """A patient's trace as the row every report understands: verdicts in protocol order, the candidate-list tier,
    the actions of the open criteria and the number of unknowns. ``dated``: the snapshot holds this patient, so a
    patient without a base row was dropped for a death or birth date, not for being absent.

    The tier is the one status function's (:func:`matching.decision.status_of`, T-709, D-478) over the verdict rows
    under the run's ``policy``, not a mapping of the cascade's own label: a "met" below the confidence threshold is
    a person's check here as on every other path (review M1a)."""
    vs: list[CriterionVerdict] = []
    judged_rows: list[CriterionVerdict] = []  # the criteria the cascade has an outcome for: what the status reads
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
        vs.append(verdict_of(o, pair))
        judged_rows.append(vs[-1])
    if not t.in_scope and t.scope_reason == NOT_AT_INDEX:
        # no base row: never "excluded" with the engine's words; a person looks (D-142, review B-02)
        return not_in_snapshot(rs, t.pid, reason=Reason.CHECK_DATES if dated else Reason.NOT_IN_SNAPSHOT)
    # a criterion with no outcome (the cascade stopped at a hard fail before it) is listed as "not evaluated" and,
    # as before, does not count: the status is the one function's over the outcomes the cascade has
    st = decision.status_of(rs.by_id(), judged_rows, policy or DEFAULT_POLICY)
    tier, actions, unknown = st.tier, list(st.actions), st.n_unknown
    if tier == "excluded" and TIER.get(t.tier, "review") != "excluded":
        tier = "review"  # the engine did not exclude: the rows never exclude on their own (cannot happen by CAS-7)
    if tier == "high" and (t.notes_over_budget or TIER.get(t.tier, "review") == "review"):
        tier = "review"  # the engine's own open question (a record that did not fit, a data gap it kept): a person
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
            "context_unknown": dict(sorted(m.context_unknown.items())),  # SCR-18: prompts sized on the default
            "no_retrieval": dict(sorted(m.no_retrieval.items())),  # NEW-LLM-2: criteria nothing could retrieve for
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
    # T-203b (D-449): per patient, where S2b's ranking came from (stored vectors or on the fly, why, which model);
    # patient level (D3), published with the job only when the flag vec.s2b was on; None when it was off
    s2b_sources: dict[str, dict[str, Any]] | None = None


# D-142 (review A-07), T-689 (D-456, review F-16): SCREEN's budget of model calls is the job option ``max_pairs``,
# else TB_SCREEN_MAX_PAIRS, else none: the population's own pairs (scoped patients x note criteria), so by default
# nothing is left unprocessed. The fixed 20,000 is gone. The run says when a budget ran out and which. Calls run
# TB_SCREEN_LLM_CONCURRENCY at a time (compose sets it to the serving profile's vLLM --max-num-seqs)
# T-694 part 3 (D-794): the cascade's note stage reads this many patients' notes at a time; the answers are the same for
# any size, only the memory the notes take changes
NOTE_BATCH = 1000


def note_batch_of(env: Mapping[str, str] | None = None) -> int:
    """The note stage's batch of patients: TB_SCREEN_NOTE_BATCH, else ``NOTE_BATCH``."""
    e = os.environ if env is None else env
    raw = str(e.get("TB_SCREEN_NOTE_BATCH") or "").strip()
    if not raw:
        return NOTE_BATCH
    try:
        v = int(raw)
    except ValueError as exc:
        raise StepFailed("running", "TB_SCREEN_NOTE_BATCH must be a whole number of patients") from exc
    if v < 1:
        raise StepFailed("running", "TB_SCREEN_NOTE_BATCH must be at least 1 patient")
    return v


def max_pairs_of(opts: dict[str, Any] | None = None, env: Mapping[str, str] | None = None) -> int | None:
    """The pair budget an operator set (the job's option, else the setting), or None: the population's own pairs."""
    e = os.environ if env is None else env
    raw = str((opts or {}).get("max_pairs") or e.get("TB_SCREEN_MAX_PAIRS") or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError as exc:
        raise StepFailed("running", "max_pairs must be a whole number of model calls") from exc
    if v < 1:
        raise StepFailed("running", "max_pairs must be at least 1")
    return v


def held_in_snapshot(ctx: Ctx, pids: list[str], snapshot: str) -> set[str]:
    """Which of ``pids`` the snapshot's patient table holds (they were dropped for a date, not for being absent)."""
    if not pids:
        return set()
    rows = ctx.services.lake.query(
        "SELECT pid FROM patient WHERE pid IN (SELECT unnest(CAST($1 AS VARCHAR[])))", [pids], snapshot=snapshot
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
    max_pairs: int | None = None,
) -> CascadeScreen:
    """Run the cascade over the scoped patients and return their verdict rows, the judging record and the stage log.

    The note-block policy in force (D-95/D-97) becomes the cascade's ``note_block``: without a verifier a note
    ``fail`` sends the patient to review and never out. Screening spends its tokens: every zero-hit pair goes to
    the judge (``absence_semantics=False``), nobody is sampled."""
    in_flight = llm_concurrency()
    # T-689 (D-456, G1-3): the share of unanswered checks is watched while the cascade runs, not only at its end
    judge = OrchestratorJudge.from_note_judge(note_judge, in_flight) if note_judge is not None else None
    dctx = decision_of(ctx)
    may_block = dctx.note_block(note_judge).may_block
    from orchestrator import derive

    source = s2b_source(ctx.services.lake, snapshot, job_vec_s2b(ctx))  # once per job (D-449)
    embedder = job_embedder(ctx)  # NEW-LLM-2: the box's embed service when it serves a model, probed once per job
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
        require_retrieval=True,  # NEW-LLM-2: nothing to retrieve with is said, never the first sentences read
        max_llm_items=max_pairs,
        note_batch=note_batch_of(),  # T-694 part 3: the notes of a batch of patients at a time, same answers
        llm_concurrency=in_flight,
        stored=derive.reader_for(ctx),  # D-442: the stored-row read, as the v1 engine's (None: the flag is off)
        registry=lambda: dctx.consent(run_date, snapshot),  # D-477: S0 reads consent through the job's context
    )
    try:
        res = two_phase(  # one GPU for both models (TB_MODEL_SWAP=sleep): judge pass, verifier pass, merge
            judge,
            lambda j: run_cascade(
                ctx.services.lake, rs, cfg, judge=j, embedder=embedder, reviewer=None, s2b_source=source
            ),
        )
    except CascadeError as exc:
        raise StepFailed("running", f"The screening cascade could not run for {rs.id} v{rs.version}: {exc}") from exc
    check_failures(judge)
    dropped = [pid for pid, t in res.traces.items() if t.scope_reason == NOT_AT_INDEX]
    held = held_in_snapshot(ctx, dropped, snapshot)
    policy = decision.Policy(confidence_floor, may_block)  # the job's, from its decision context (D-477)
    pair = is_pair(note_judge)
    results = {pid: verdicts_of(rs, res.traces[pid], pid in held, policy, pair) for pid in pids if pid in res.traces}
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
    # T-689 (D-456, F-16): with no budget set it is the population's own pairs; which budget stopped the run, by name
    population_pairs = len(pids) * len(res.note_criteria)
    out["budget"] = {
        "max_pairs": max_pairs if max_pairs is not None else population_pairs,
        "source": "set" if max_pairs is not None else "population",
        "unprocessed": res.metrics.unprocessed,
        "hit": res.metrics.unprocessed > 0,
        "stopped_by": res.metrics.budget_stopped or None,
    }
    sources = None
    if source is not None:
        sources = {pid: dict(t.s2b_source) for pid, t in sorted(res.traces.items()) if t.s2b_source is not None}
    return CascadeScreen(results, judging, out, judge, sources)


__all__ = [
    "PIPELINES",
    "TIER",
    "CascadeScreen",
    "OrchestratorJudge",
    "check_failures",
    "job_vec_s2b",
    "judged",
    "llm_concurrency",
    "max_pairs_of",
    "note_batch_of",
    "pipeline",
    "s2b_source",
    "screen_with_cascade",
    "summary",
    "vec_s2b_on",
    "verdict_of",
    "verdicts_of",
]
