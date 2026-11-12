"""Per-patient evaluation for SCREEN / MICROBATCH / NAV (SPEC §8.2, §7.3, §7.5).

* Structured criteria: the lake SQL engine, the only runtime engine (owner decision 3, TB-PLAN-04 step 6). CQL
  (``CqlEngine``) is kept for the compile-time equivalence gate and the bench; ``TB_SCREEN_ENGINE`` other than ``sql``
  is refused.
* Note criteria: RAG over ``/chunks/search`` (k=5, window ``[index-365d, index]`` unless the IR window is narrower,
  ≤2,500 tokens, newest first) and the ``judge`` prompt (local only); full-record fallback for small candidate sets.
  Both budgets are cut to what the judge's and the verifier's context leave beside the prompt and the answer (T-603,
  review LLM-015; :meth:`NoteJudge.budget`). A note that does not fit is not dropped in silence: the answer carries
  the reason ``notes_over_budget`` and the patient goes to review (T-603, review LLM-016 / CR-004 flag half).
  The quote must be a substring of one excerpt, else the verdict becomes ``unknown`` (``quote_not_found``).
* Verdicts are reported from the eligibility perspective (D-25): inclusion pass = predicate true, exclusion pass =
  predicate false.
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Literal, Protocol, cast

from criteria_compiler.compile_sql.overlay import safe_sql
from guard.injection import planted_in
from lake.client import LakeAPI
from matching import decision
from matching import verdict as verdict_table
from matching.coverage import Coverage
from matching.proposed import Proposed
from matching.stored_scores import apply_rows
from tb_common.fhir import FhirEvaluator
from tb_common.labunit import reason_of as derived_reason
from tb_common.llm import LlmClient, LlmError, LlmPromptTooLong
from tb_common.pair import DECIDED, Vote, combine, needs_verifier, same_model, served_keys
from tb_common.quotes import quote_in
from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionIR, CriterionVerdict, Evidence, Opinion, PatientEvaluation
from tb_llm.budget import excerpt_tokens

from orchestrator.scenarios.terms import keywords
from orchestrator.twophase import two_phase

Verdict = Literal["pass", "fail", "unknown", "pending_human"]
CHUNK_TOKENS = 2500  # the retrieval budget (k=5 chunks); cut further to the models' context (T-603)
FULL_RECORD_TOKENS = 28000  # used only when neither model's context is known; else the context decides (T-603)
FULL_RECORD_MAX_CANDIDATES = 100
NOTES_FLAG = "notes.reading"  # T-609 (OPS-042): off holds note reading (tb_common.flags, RUNBOOK §19)
NOTES_HELD = "note reading is held (flag notes.reading is off): note answers never exclude"


def notes_held() -> bool:
    """True while an operator holds note reading (``trialbox model hold``, the flag ``notes.reading`` set to off).

    Read before every model call of the note stage, through the flag's five-second cache, so a hold stops the note
    stage within one step of a running job, without a restart. A flag store that cannot be read (no ``TB_DB_URL``,
    the database down) is not a hold: the job's own database calls fail then anyway."""
    from tb_common.flags import read

    return read(NOTES_FLAG) == "off"


class StructuredEngine(Protocol):
    name: str

    def evaluate(
        self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]
    ) -> dict[str, PatientEvaluation]: ...


@dataclass
class CqlEngine:
    fhir: FhirEvaluator
    name: str = "cql"

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        from criteria_compiler.compile_cql.generator import CqlGenerator

        if not pids:
            return {}
        self.ensure_loaded(rs)
        crit = [c for c in rs.active() if c.id in set(ids)]
        exprs = CqlGenerator.expression_names(crit)
        return {e.pid: e for e in self.fhir.evaluate_many(rs.library, pids, index_date, exprs)}

    def ensure_loaded(self, rs: Ruleset) -> None:
        """Load the approved Library (+ TB_Common, FHIRHelpers, ValueSets) unless fhir-store already has exactly this
        content-addressed version (D-34); the compiler loads it on approval, this covers a rebuilt fhir-store."""
        from tb_common.fhir import library_id, library_resource

        resp = self.fhir.client.get(f"{self.fhir.base}/Library/{library_id(rs.library)}")
        if resp.status_code == 200 and resp.json().get("version") == rs.library_version:
            return
        libs = []
        try:
            from criteria_compiler.compile_cql.translator import fhirhelpers_source

            libs.append(library_resource("FHIRHelpers", "4.0.1", fhirhelpers_source(), None))
        except (FileNotFoundError, OSError):
            pass  # translator jars absent: rely on the copy loaded by the compiler
        if "TB_Common" in rs.cql:
            libs.append(library_resource("TB_Common", "1.0.0", rs.cql["TB_Common"], rs.elm.get("TB_Common")))
        libs.append(library_resource(rs.library, rs.library_version, rs.cql[rs.library], rs.elm.get(rs.library)))
        self.fhir.load(libs, rs.valuesets.values())


@dataclass
class SqlEngine:
    lake: LakeAPI
    snapshot: str | None = None
    name: str = "sql"
    # D-442: the stored derived rows (``tb_common.derived_store.stored_read``: given only while the flag
    # ``derived.stored_read`` is on). Given, :func:`matching.stored_scores.apply_rows` runs on the SQL's rows, as on
    # the cascade's: a decided score answer stands only on its stored row of the snapshot's batch
    stored: Any = None

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        if not pids:
            return {}
        t = self.lake.query(safe_sql(rs), [[index_date.isoformat()], list(pids)], self.snapshot).to_pylist()
        crit = [c for c in rs.active() if c.id in set(ids)]
        apply_rows(t, crit, self.stored, self.snapshot, getattr(rs.manifest, "derived_pins", None))
        cov = Coverage.for_criteria(self.lake, crit, pids, self.snapshot, rs.valuesets)
        prop = Proposed.for_criteria(self.lake, crit, pids, self.snapshot, rs.valuesets)
        out: dict[str, PatientEvaluation] = {}
        for row in t:
            res = {k[2:]: row[k] for k in row if k.startswith("C_") and k[2:] in ids}
            ev = {
                k[2:]: [x for x in (row[k] or "").split(";") if x] for k in row if k.startswith("E_") and k[2:] in ids
            }
            reasons: dict[str, str] = {}
            for cid, items in list(ev.items()):  # D-149: a score with no value says why (missing input, unit)
                why, refs = derived_reason(items)
                if why is not None:
                    ev[cid] = refs
                    if res.get(cid) is None:
                        reasons[cid] = why
            for c in crit:  # F-10 (D-130): FALSE beside an unreadable code is unknown, not an exclusion
                gap = cov.refs(c, str(row["pid"]), index_date) if res.get(c.id) is False else []
                if gap:
                    res[c.id], ev[c.id], reasons[c.id] = None, gap, Reason.UNKNOWN_CODE_SYSTEM.value
                # D-135: a proposed fact that could change a decided answer makes it unknown ("needs information");
                # it never decides one: it is not in the coded tables the SQL reads
                fids = prop.refs(c, str(row["pid"]), index_date, res.get(c.id))
                if fids:  # a suspected diagnosis (疑い, D-142) the same way, with its own reason
                    res[c.id], ev[c.id], reasons[c.id] = None, fids, prop.reason(str(row["pid"]), fids)
            out[row["pid"]] = PatientEvaluation(
                pid=row["pid"], index_date=index_date, engine="sql", results=res, evidence=ev, reasons=reasons or None
            )
        return out


def engine_from_env(
    name: str, fhir: FhirEvaluator | None, lake: LakeAPI, snapshot: str | None, stored: Any = None
) -> StructuredEngine:
    """The runtime engine: SQL on the lake, always (owner decision 3, 2026-11-08; review F-05). CQL is kept for the
    compile-time equivalence gate (``criteria_compiler.equivalence``) and the bench, never to screen a patient, so a
    weekly list can no longer change with the engine a job type happened to use."""
    if (name or "sql").strip().lower() != "sql":
        raise ValueError(f"TB_SCREEN_ENGINE={name!r}: SQL is the only runtime engine (CQL is compile-time only)")
    return SqlEngine(lake, snapshot, stored=stored)


# --------------------------------------------------------------------------------------------- note criteria
def _tokens(text: str) -> int:
    """What a note of ``text`` adds to the judge prompt (:func:`tb_llm.budget.excerpt_tokens`, T-603): CJK characters
    ~1 token each, Latin ~4 characters per token, plus its JSON keys and escaping."""
    return excerpt_tokens({"date": "0000-00-00", "note_type": "progress", "text": text})


def note_window(c: CriterionIR, index_date: date) -> tuple[date, date]:
    lo = index_date - timedelta(days=365)
    w = getattr(c.logic, "window", None)
    if w is not None and w.from_days is not None and w.from_days > -365:
        lo = index_date + timedelta(days=int(w.from_days))
    return lo, index_date


@dataclass
class NoteResult:
    predicate: str  # pass | fail | unknown  (answer to note_question)
    confidence: float
    quote: str | None = None
    quote_date: str | None = None
    reason: str | None = None  # a tb_common.reasons code, never free text (D-118)
    source: str = "chunks"  # chunks | full_record
    dids: list[str] = field(default_factory=list)
    left_out: int = 0  # notes of the window the token budget did not show (T-603: flagged, never silent)
    model_reason: str = ""  # the judge model's own sentence: audit and debugging only, never shown on a page
    call_id: str = ""  # the judge call behind the answer (the cascade's evidence meta)
    model: str = ""
    build_sha: str = ""  # through the gateway: the build that answered (D-276)
    prompt: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    # D-120: when the two checks disagree, each model's answer and verified quote, so a person sees both
    opinions: list[dict[str, Any]] = field(default_factory=list)


def _opinion(role: str, r: NoteResult) -> dict[str, Any]:
    return {"role": role, "verdict": r.predicate, "quote": r.quote, "quote_date": r.quote_date}


def _vote(r: NoteResult) -> Vote:
    return Vote(r.predicate, r.confidence, r.reason, served_keys(r.model, r.build_sha))


@dataclass
class NoteJudge:
    """The note judge of both screening paths, with the two-model rule of :mod:`tb_common.pair` (D-118).

    :meth:`judge_excerpts` is the one place a note criterion is put to the models: the v1 evaluator (NAV,
    MICROBATCH, CASE), the v4 cascade through ``OrchestratorJudge`` and the CASE chart upload all call it. With a
    verifier every decided judge answer is put to the verifier with the same excerpts, and the pair's answer is
    :func:`tb_common.pair.combine`: it stands only when both agree, else it is ``unknown`` with the reason
    (``disagree``, ``verifier_quote_missing``, ``model_down``), which the tiering sends to review. So a note criterion
    blocks a patient only when both models say so. A model that does not answer counts as a failure for
    :func:`check_judge`; its error text never reaches a reason (``model_down``). Two answers served under one model
    name or build are one model's answer, so the judge did not really answer: ``unknown`` / ``model_down``, counted
    as a failure (D-276, review LLM-002).

    D-276 (review S-10): when the token budget left some of the retrieved notes out (:meth:`judge_patient`), an
    answer that would exclude is not final: ``unknown`` / ``not_evaluated``, and the evaluator's full-record read
    gets its turn."""

    lake: LakeAPI | None
    llm: LlmClient
    prompt: str = "judge"
    job_id: str | None = None
    verifier: LlmClient | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: int = 0  # model calls that got no answer (model down, timeout, out-of-schema)
    disagreements: int = 0  # decided answers the verifier did not confirm (became unknown)
    same_model: int = 0  # decided answers the "verifier" gave as the judge's own model (became unknown, D-276)
    held: int = 0  # note questions not put to a model because note reading was held (T-609)
    # T-689 (D-456, review G1-3): model calls this judge has in flight together. Above 0 the share rule of
    # check_judge is also applied while the job runs (running_share_min); 0: only at the job's end, as before
    in_flight: int = 0
    # the counters are bumped from the evaluator's worker threads: one lock, so the >10 % model-down rule and the
    # audit counts never lose an increment (review F-27)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def _count(self, **inc: int) -> None:
        with self._lock:
            for name, n in inc.items():
                setattr(self, name, getattr(self, name) + n)
            failures, total = self.failures, self.calls + self.failures
        # T-689 (G1-3): past the share while the job runs, it stops now, not hours later with the same verdict
        watched = inc.get("failures") and self.in_flight > 0 and total >= running_share_min(self.in_flight)
        if watched and failures > MAX_JUDGE_FAILURE_SHARE * total:
            raise share_exceeded(failures, total, running=True)

    @property
    def mode(self) -> str:
        return "agreement" if self.verifier is not None else "single"

    def _lake(self) -> LakeAPI:
        if self.lake is None:
            raise RuntimeError("this note judge has no lake: pass the excerpts to judge_excerpts")
        return self.lake

    def excerpts(self, pid: str, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
        return self._chunks(pid, c, index_date)[0]

    def budget(self, c: CriterionIR, index_date: date, default: int) -> int:
        """Tokens of notes one judge prompt may hold (T-603, review LLM-015): what the judge's and the verifier's
        context leave beside the rest of the prompt and the answer (the smaller of the two: both read the same
        excerpts), at most ``default``. A client that cannot tell its context leaves ``default``."""
        fixed = {
            "criterion_text": c.text,
            "note_question": c.note_question or c.text,
            "index_date": index_date.isoformat(),
            "excerpts": [],
        }
        out = default
        for client in (self.llm, self.verifier):
            fn = getattr(client, "text_budget", None) if client is not None else None
            room = fn(self.prompt, fixed) if callable(fn) else None
            if isinstance(room, int):
                out = min(out, room)
        return out

    def _chunks(self, pid: str, c: CriterionIR, index_date: date) -> tuple[list[dict[str, Any]], int]:
        """The excerpts and how many retrieved chunks the token budget left out (D-276)."""
        lo, hi = note_window(c, index_date)
        query = " ".join([c.note_question or c.text, *keywords(c.text)])
        hits = self._lake().chunks_search(pid, query, k=5, date_from=lo, date_to=hi)
        hits = [h for h in hits if h.get("date") and lo.isoformat() <= str(h["date"])[:10] <= hi.isoformat()]
        hits.sort(key=lambda h: (str(h["date"]), str(h.get("did", ""))), reverse=True)
        out: list[dict[str, Any]] = []
        budget = self.budget(c, index_date, CHUNK_TOKENS)
        for h in hits:
            n = _tokens(str(h["text"]))
            if n > budget:
                continue  # T-603: an older, shorter chunk may still fit; this one is counted as left out
            budget -= n
            out.append(
                {
                    "date": str(h["date"])[:10],
                    "note_type": h.get("type") or "note",
                    "text": h["text"],
                    "did": h.get("did"),
                }
            )
        return out, len(hits) - len(out)

    def full_record(self, pid: str, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
        return self._record(pid, c, index_date)[0]

    def _record(self, pid: str, c: CriterionIR, index_date: date) -> tuple[list[dict[str, Any]], int]:
        """The window's notes, newest first, and how many the token budget left out (D-276). The budget is the
        models' context (T-603): 28,000 tokens did not fit on a 16k or 8k model, and the server refused the call."""
        lo, hi = note_window(c, index_date)
        rows = (
            self._lake()
            .query(
                "SELECT did, CAST(date AS DATE) AS d, type, text FROM document WHERE pid = $1 "
                "AND CAST(date AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE) ORDER BY date DESC, did",
                [pid, lo.isoformat(), hi.isoformat()],
            )
            .to_pylist()
        )
        out: list[dict[str, Any]] = []
        budget = self.budget(c, index_date, FULL_RECORD_TOKENS)
        for r in rows:
            n = _tokens(str(r["text"]))
            if n > budget:
                continue  # T-603: counted as left out (the answer is flagged), the older notes still read
            budget -= n
            out.append(
                {"date": r["d"].isoformat(), "note_type": r["type"] or "note", "text": r["text"], "did": r["did"]}
            )
        return out, len(rows) - len(out)

    def judge_patient(self, pid: str, c: CriterionIR, index_date: date, full: bool = False) -> NoteResult:
        excerpts, left_out = self._record(pid, c, index_date) if full else self._chunks(pid, c, index_date)
        source = "full_record" if full else "chunks"
        if not excerpts:
            return NoteResult("unknown", 0.0, reason=Reason.NO_NOTES.value, source=source)
        r = self.judge_excerpts(c.text, c.note_question or c.text, index_date, excerpts, source)
        if not left_out:
            return r
        # D-276 (review S-10): both models read the same excerpts, so their agreement says nothing about a note the
        # budget left out. An answer that would exclude is then not final: unknown, a person (or the full read) looks
        if r.predicate in DECIDED and eligibility(c.kind, r.predicate == "pass") == "fail":
            return replace(
                r, predicate="unknown", confidence=0.0, quote=None, quote_date=None, dids=[],
                reason=Reason.NOTES_OVER_BUDGET.value, left_out=left_out,
            )  # fmt: skip
        # T-603 (review LLM-016, CR-004 flag half): an answer that keeps the patient stands, flagged: the candidate
        # goes to review with the reason, so nobody reads "met" as "every note was read"
        if r.predicate in DECIDED:
            return replace(r, reason=Reason.NOTES_OVER_BUDGET.value, left_out=left_out)
        return replace(r, left_out=left_out)

    def _ask(
        self, client: LlmClient, variables: dict[str, Any], excerpts: list[dict[str, Any]], source: str
    ) -> NoteResult:
        if notes_held():  # T-609: no model is asked while note reading is held; a person reads the notes instead
            self._count(held=1)
            return NoteResult("unknown", 0.0, reason=Reason.NOT_EVALUATED.value, source=source)
        try:
            res = client.chat_json(self.prompt, variables, job_id=self.job_id)
        except LlmPromptTooLong:
            # T-603: the excerpts did not fit this model (the budget is an estimate, the server counted more): the
            # reason says so, and it counts as a failure, so a box whose sizing is wrong stops the run (check_judge)
            self._count(failures=1)
            return NoteResult("unknown", 0.0, reason=Reason.NOTES_OVER_BUDGET.value, source=source)
        except LlmError:  # also an answer from an alias the call did not expect (tb_llm, T-601)
            self._count(failures=1)
            return NoteResult("unknown", 0.0, reason=Reason.MODEL_DOWN.value, source=source)
        if getattr(client, "gateway", None) is not None and not getattr(res, "build_sha", ""):
            # T-601: through the gateway every answer names its build; one that does not cannot be told apart from
            # the other model's answer in the pair's build comparison, so it is no answer (fail closed)
            self._count(failures=1)
            return NoteResult("unknown", 0.0, reason=Reason.MODEL_DOWN.value, source=source)
        self._count(calls=1, tokens_in=res.tokens_in, tokens_out=res.tokens_out)
        r = postprocess(res.data, excerpts, source)
        return replace(
            r,
            call_id=res.output_sha[:16],
            model=res.model,
            build_sha=getattr(res, "build_sha", ""),
            prompt=f"{res.prompt_id}@{res.prompt_version}",
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
        )

    def judge_excerpts(
        self,
        criterion_text: str,
        note_question: str,
        index_date: date,
        excerpts: list[dict[str, Any]],
        source: str = "chunks",
        verify: bool = True,
        primary: LlmClient | None = None,
    ) -> NoteResult:
        """Put one note question to the judge (and, when ``verify`` and a verifier is wired, to the verifier) over the
        given excerpts: the lake's chunks, the full record, the cascade's selected excerpts or an uploaded chart."""
        variables = {
            "criterion_text": criterion_text,
            "note_question": note_question,
            "index_date": index_date.isoformat(),
            "excerpts": [{k: e.get(k) for k in ("date", "note_type", "text")} for e in excerpts],
        }
        first = self._ask(primary if primary is not None else self.llm, variables, excerpts, source)
        second: NoteResult | None = None
        if verify and self.verifier is not None and needs_verifier(_vote(first)):
            second = self._ask(self.verifier, variables, excerpts, source)  # counts its own failure
        d = combine(_vote(first), None if second is None else _vote(second))
        if d.disagreement:
            self._count(disagreements=1)
        if d.same_model:  # the same build answered twice: the judge did not answer (a failure, review LLM-002)
            self._count(same_model=1, failures=1)
        t_in = first.tokens_in + (second.tokens_in if second else 0)
        t_out = first.tokens_out + (second.tokens_out if second else 0)
        opinions = [_opinion("judge", first), _opinion("verifier", second)] if d.disagreement and second else []
        if d.verdict != first.predicate:  # the pair (or the confidence floor) did not keep the judge's answer
            return replace(
                first,
                predicate="unknown",
                confidence=0.0,
                quote=None,
                quote_date=None,
                dids=[],
                reason=d.reason,
                tokens_in=t_in,
                tokens_out=t_out,
                opinions=opinions,
            )
        return replace(first, confidence=d.confidence, reason=d.reason, tokens_in=t_in, tokens_out=t_out)


# a few unanswered note checks stay "unknown" (manual review); more than this share means the model was down and the
# list would silently be a structured-only list, so the job fails instead
MAX_JUDGE_FAILURE_SHARE = 0.1


def running_share_min(in_flight: int) -> int:
    """Note checks a job must have behind it before the share rule is applied while it runs (T-689, D-456): the
    number at which two full rounds of in-flight failures are exactly the share, so one event that fails every call
    in flight never stops a job by itself."""
    return math.ceil(2 * max(1, in_flight) / MAX_JUDGE_FAILURE_SHARE)


def share_exceeded(failures: int, total: int, running: bool = False) -> Exception:
    from orchestrator.clients import StepFailed

    so_far = " so far" if running else ""
    return StepFailed(
        "judging",
        f"The model did not answer {failures} of {total} note checks{so_far}, so the note-based criteria could not "
        f"be judged. Nothing was sent; send the request again when the model is back.",
    )


def check_judge(judge: NoteJudge | None) -> None:
    if judge is None or not judge.failures:
        return
    total = judge.calls + judge.failures
    if judge.failures > MAX_JUDGE_FAILURE_SHARE * total:
        raise share_exceeded(judge.failures, total)


def postprocess(d: dict[str, Any], excerpts: list[dict[str, Any]], source: str = "chunks") -> NoteResult:
    """SPEC §7.3: the quote must be a substring of one excerpt (whitespace-normalised), else ``unknown``. A quote from
    a sentence the guard's planted-instruction screen flags is ``unknown`` too (T-606, D-359)."""
    verdict = str(d.get("verdict", "unknown"))
    quote = d.get("quote")
    conf = float(d.get("confidence", 0.0))
    did = None
    if verdict != "unknown":
        q = str(quote or "")
        match = next((e for e in excerpts if quote_in(q, str(e["text"]))), None)
        if match is None:
            return NoteResult("unknown", 0.0, reason=Reason.QUOTE_NOT_FOUND.value, source=source)
        if planted_in(str(match["text"]), q):  # T-606 (D-359): an instruction found in a note is never evidence
            return NoteResult("unknown", 0.0, reason=Reason.PLANTED_INSTRUCTION.value, source=source)
        did = match.get("did")
    why = Reason.NOTE.value if verdict in ("pass", "fail") else Reason.ABSTAINED.value
    model_reason = str(d.get("reason") or "")
    return NoteResult(
        verdict, conf, quote, d.get("quote_date"), why, source, [str(did)] if did else [], model_reason=model_reason
    )


# --------------------------------------------------------------------------------------------- verdicts & tiers
def eligibility(kind: str, predicate: bool | None) -> Verdict:
    """The eligibility answer of a coded or note predicate: T-652's table (``matching.verdict``), called here since
    T-709 (D-478) instead of being written a second time."""
    return verdict_table.eligibility(kind, predicate)


def is_pair(judge: NoteJudge | None) -> bool:
    """Whether the run's note judge is two different models (the ``pair`` basis of a note answer, D-478): a
    verifier is configured and is not the judge's own model under another name (D-276)."""
    return judge is not None and judge.verifier is not None and same_model(judge.llm, judge.verifier) is None


@dataclass
class PatientVerdicts:
    pid: str
    verdicts: list[CriterionVerdict]
    tier: str
    actions: list[str]
    n_unknown: int


def structured_verdict(c: CriterionIR, ev: PatientEvaluation | None) -> CriterionVerdict:
    pred = None if ev is None else ev.results.get(c.id)
    refs = [] if ev is None or not ev.evidence else list((ev.evidence or {}).get(c.id) or [])
    known = pred if isinstance(pred, bool) else None
    told = (ev.reasons or {}).get(c.id) if ev is not None else None
    # D-113: unknown with records attached = coded inside the grouper's family but outside its code list;
    # D-130: or a record in a code system the mapping does not know (the engine says so in ``reasons``)
    if known is None and told:
        why = told
    elif known is None:
        why = Reason.CODE_OUTSIDE_LIST.value if refs else Reason.DATA_GAP.value
    else:
        why = Reason.CODED.value
    verdict = eligibility(c.kind, known)
    return CriterionVerdict(
        id=c.id,
        verdict=verdict,
        evidence=Evidence(resource_refs=refs[:20], reason=why),
        basis="coded" if verdict != "unknown" else None,  # D-478: the records decided it
    )


def note_verdict(c: CriterionIR, r: NoteResult, pair: bool | None = None) -> CriterionVerdict:
    """``pair``: whether the answer is the judge's and a second, different model's (:func:`is_pair`); it becomes
    the verdict's basis (D-478: ``pair`` or ``single``; a single model's "not met" never excludes). A caller that
    does not say (a tool, a test of the judge) leaves the basis unstated, and the run's policy alone decides, as
    before the field. Every screening path says."""
    pred = {"pass": True, "fail": False}.get(r.predicate)
    refs = [f"DocumentReference/{d}" for d in r.dids]
    verdict = eligibility(c.kind, pred)
    return CriterionVerdict(
        id=c.id,
        verdict=verdict,
        evidence=Evidence(
            resource_refs=refs,
            quote=r.quote,
            quote_date=r.quote_date,
            confidence=r.confidence,
            reason=r.reason,
            opinions=[Opinion(**o) for o in r.opinions] or None,
        ),
        basis=("pair" if pair else "single") if verdict != "unknown" and pair is not None else None,
    )


def not_final(c: CriterionIR, v: CriterionVerdict, note_block: bool) -> CriterionVerdict:
    """T-707 (D-476): a note fail says whether it was allowed to exclude when it was given: ``final: false`` on a
    run on which a note answer may not exclude, so a later re-tier (MICROBATCH) can never read it as a pair's
    answer; ``final: true`` otherwise. A stored note fail with neither is from before the field and never
    excludes."""
    if v.verdict != "fail" or not is_note_answer(c, v):
        return v
    return v.model_copy(update={"final": bool(note_block)})


def human_verdict(c: CriterionIR) -> CriterionVerdict:
    return CriterionVerdict(
        id=c.id,
        verdict="pending_human",
        evidence=Evidence(resource_refs=[], reason=Reason.HUMAN.value),
        basis="person",
    )


def not_in_snapshot(
    rs: Ruleset,
    pid: str,
    kinds: tuple[str, ...] = ("inclusion", "exclusion"),
    reason: Reason = Reason.NOT_IN_SNAPSHOT,
) -> PatientVerdicts:
    """A scoped patient the records snapshot does not hold (moved, merged, a late registration): nothing is known,
    so a person looks (tier ``review``), never an exclusion (Fable review 2026-11-08, finding 10; D-118). The same
    for a patient the snapshot holds as deceased or not yet born on the screening date (``check_dates``, D-142)."""
    vs = [
        CriterionVerdict(id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason=reason.value))
        for c in rs.active()
        if c.kind in kinds
    ]
    return PatientVerdicts(pid, vs, "review", [], len(vs))


FILTERED = ("structured", "mixed")  # classes whose logic the filters decide (D-32, D-98)
JUDGED = ("note", "mixed")  # classes whose note_question the model may be asked


def coded_settles(c: CriterionIR, ev: PatientEvaluation | None) -> bool:
    """D-98: a ``mixed`` criterion is settled by the coded data when its logic is true (an inclusion met, an
    exclusion present). A false or null coded answer only means the codes did not show it: the notes decide."""
    return c.class_ == "mixed" and ev is not None and ev.results.get(c.id) is True


def is_note_answer(c: CriterionIR, v: CriterionVerdict) -> bool:
    """A verdict that came from the note judge (:func:`matching.decision.is_note_answer`, the rule's own home)."""
    return decision.is_note_answer(c, v)


def structured_candidate(rs: Ruleset, ev: PatientEvaluation | None, ids: set[str] | None = None) -> bool:
    """SPEC §8.2: all structured inclusions in {true, null} and no structured exclusion true. A ``mixed`` inclusion
    whose codes say false stays a candidate (the notes may still show it); a ``mixed`` exclusion present in the codes
    drops the patient like a structured one (D-98)."""
    if ev is None:
        return False
    for c in rs.active():
        if c.class_ not in FILTERED or (ids is not None and c.id not in ids):
            continue
        if c.kind not in ("inclusion", "exclusion"):
            continue
        v = ev.results.get(c.id)
        if c.kind == "inclusion" and v is False and c.class_ == "structured":
            return False
        if c.kind == "exclusion" and v is True:
            return False
    return True


NOTE_BLOCK_POLICIES = ("both_agree", "never")


def note_block_policy() -> str:
    """``TB_NOTE_BLOCK`` (D-95): ``both_agree`` (default) lets a note criterion exclude a patient, which with a verifier
    configured means both models agreed (D-89); ``never`` (single-model boxes such as one RTX 4090) never lets a note
    answer exclude: a note ``fail`` keeps its verdict and quote but sends the patient to review."""
    v = os.environ.get("TB_NOTE_BLOCK", "both_agree").strip().lower() or "both_agree"
    if v not in NOTE_BLOCK_POLICIES:
        raise ValueError(f"TB_NOTE_BLOCK must be one of {', '.join(NOTE_BLOCK_POLICIES)}, not {v!r}")
    return v


def effective_note_block(judge: NoteJudge | None) -> tuple[bool, str, str]:
    """Whether a confident note ``fail`` may exclude a patient on this run (D-95, D-97).

    ``both_agree`` promises that two models agreed; without a verifier that promise cannot be kept, so the run falls
    back to ``never`` (a single model may send a patient to review, never out) and says so. The same holds when the
    pair has not passed its canary (:mod:`orchestrator.canary_gate`, D-117). Returns
    ``(may_block, effective_policy, reason)``."""
    policy = note_block_policy()
    if notes_held():  # T-609: before the configured policy, so a run under a hold always says why
        return False, "never", NOTES_HELD
    if policy == "never":
        return False, "never", "configured: note answers never exclude"
    if judge is None:
        return False, "never", "no note judge on this box"
    if judge.verifier is None:
        return False, "never", "no verifier configured: a single model may not exclude"
    one = same_model(judge.llm, judge.verifier)  # D-276 (review S-2): two clients are not yet two models
    if one:
        return False, "never", f"the verifier is not a second model ({one}): a single model may not exclude"
    from orchestrator.canary_gate import allows_block

    ok, why = allows_block()  # D-117: only on a pair that passed its canary (and every wake check since)
    if not ok:
        return False, "never", why
    return True, "both_agree", "judge and verifier must both say fail"


def tier(
    rs: Ruleset, verdicts: list[CriterionVerdict], threshold: float, *, note_block: bool
) -> tuple[str, list[str], int]:
    """A patient's tier, the actions of the open criteria and the number of unknowns: the one status function
    (:func:`matching.decision.status_of`, T-709, D-478), under this run's policy.

    high: every structured and note criterion says yes, only criteria a person decides are open; excluded: an
    answer says no (a note answer only when a pair gave it, it is final, sure enough and ``note_block``); review
    otherwise. ``note_block`` is required and comes from the job's decision context (D-477): the configured policy
    alone is not enough (no verifier, one model twice, the canary gate; D-276, review F-01)."""
    st = decision.status_of(rs.by_id(), verdicts, decision.Policy(threshold, note_block))
    return st.tier, st.actions, st.n_unknown


def evaluate_patients(
    rs: Ruleset,
    pids: list[str],
    index_date: date,
    engine: StructuredEngine,
    judge: NoteJudge | None,
    threshold: float,
    only: set[str] | None = None,
    full_record_fallback: bool = True,
    workers: int = 4,
    all_candidates: bool = False,
    kinds: tuple[str, ...] = ("inclusion", "exclusion"),
    note_block: bool | None = None,
) -> dict[str, PatientVerdicts]:
    """Structured screen of every pid, then note criteria for structured candidates only (SPEC §8.2). NAV passes
    ``kinds`` with renewal/documentation criteria and ``all_candidates`` (every scoped patient is judged).
    ``note_block`` defaults to :func:`effective_note_block` of the judge: without a verifier no note answer excludes."""
    if note_block is None:  # a caller with no job (a tool, a test): the rule applied now (D-477)
        from orchestrator.decision_context import note_block_of

        note_block = note_block_of(judge).may_block
    active = [c for c in rs.active() if c.kind in kinds and (only is None or c.id in only)]
    structured_ids = [c.id for c in active if c.class_ in FILTERED]
    evals = engine.evaluate(rs, pids, index_date, structured_ids) if structured_ids else {}
    if not structured_ids:
        evals = {
            p: PatientEvaluation(pid=p, index_date=index_date, engine=cast(Any, engine.name), results={}) for p in pids
        }
    cands = [p for p in pids if all_candidates or structured_candidate(rs, evals.get(p), set(structured_ids))]
    notes = [c for c in active if c.class_ in JUDGED]
    note_res: dict[tuple[str, str], NoteResult] = {}
    if judge is not None and notes and cands:
        tasks = [(p, c) for p in cands for c in notes if not coded_settles(c, evals.get(p))]

        def judge_all(j: NoteJudge) -> dict[tuple[str, str], NoteResult]:
            def run(task: tuple[str, CriterionIR]) -> tuple[tuple[str, str], NoteResult]:
                p, c = task
                r = j.judge_patient(p, c, index_date)
                if r.predicate == "unknown" and full_record_fallback and len(cands) <= FULL_RECORD_MAX_CANDIDATES:
                    r2 = j.judge_patient(p, c, index_date, full=True)
                    if r2.predicate != "unknown" or r.reason == Reason.NO_NOTES.value:
                        r = r2
                return (p, c.id), r

            with ThreadPoolExecutor(max_workers=workers) as ex:
                return dict(ex.map(run, tasks))

        # one GPU for both models (TB_MODEL_SWAP=sleep): judge pass, then the verifier pass, then the merge
        note_res = two_phase(judge, judge_all, workers=workers)
        if note_res and notes_held():
            # T-609: a hold that came during the note stage: the answers got before it are not used either (each
            # becomes unknown, not evaluated: review), so a run that ends under a hold uses no note answer
            note_res = {}
            note_block = False
    pair = is_pair(judge)  # D-478: the basis of this run's note answers
    out: dict[str, PatientVerdicts] = {}
    for p in pids:
        ev = evals.get(p)
        if structured_ids and ev is None and not all_candidates:
            out[p] = not_in_snapshot(rs, p, kinds)
            continue
        vs: list[CriterionVerdict] = []
        for c in active:
            if c.class_ == "structured" or coded_settles(c, ev):
                vs.append(structured_verdict(c, ev))
            elif c.class_ in JUDGED:
                r = note_res.get((p, c.id))
                vs.append(
                    not_final(c, note_verdict(c, r, pair), note_block)
                    if r is not None
                    else CriterionVerdict(
                        id=c.id,
                        verdict="unknown",
                        evidence=Evidence(resource_refs=[], reason=Reason.NOT_EVALUATED.value),
                    )
                )
            else:
                vs.append(human_verdict(c))
        if p in cands:
            t, acts, n_unk = tier(rs, vs, threshold, note_block=note_block)
        else:
            t, acts, n_unk = "excluded", [], 0
        out[p] = PatientVerdicts(p, vs, t, acts, n_unk)
    return out


def row(
    pv: PatientVerdicts,
    next_appt: str | None,
    practitioner: str | None,
    dept: str | None,
    evaluated: str,
    changed: list[str] | None = None,
) -> CandidateRow:
    return CandidateRow.model_validate(
        {
            "pid": pv.pid,
            "tier": pv.tier,
            "next_appointment": next_appt,
            "practitioner_id": practitioner,
            "department": dept,
            "criteria": pv.verdicts,
            "actions": pv.actions,
            "n_unknown": pv.n_unknown,
            "last_evaluated": evaluated,
            "changed": changed or [],
        }
    )


Sorter = Callable[[CandidateRow], tuple[Any, ...]]


def sort_key(r: CandidateRow) -> tuple[Any, ...]:
    """Next appointment ascending (none last), then tier (high before review), then pid."""
    nxt = r.next_appointment.isoformat() if r.next_appointment else ""
    return (r.next_appointment is None, nxt, {"high": 0, "review": 1}.get(r.tier, 2), r.pid)
