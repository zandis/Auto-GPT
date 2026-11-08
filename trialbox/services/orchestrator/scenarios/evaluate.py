"""Per-patient evaluation for SCREEN / MICROBATCH / NAV (SPEC §8.2, §7.3, §7.5).

* Structured criteria: CQL ``Library/$evaluate`` per patient in fhir-store (8 concurrent calls; SPEC §4.4). The lake
  SQL engine evaluates the same approved ruleset and is selectable with ``TB_SCREEN_ENGINE=sql`` (CPU CI, DECISIONS
  D-49); the equivalence gate guarantees ≥98 % agreement between the two.
* Note criteria: RAG over ``/chunks/search`` (k=5, window ``[index-365d, index]`` unless the IR window is narrower,
  ≤2,500 tokens, newest first) and the ``judge`` prompt (local only); full-record fallback for small candidate sets.
  The quote must be a substring of one excerpt, else the verdict becomes ``unknown`` (``quote_not_found``).
* Verdicts are reported from the eligibility perspective (D-25): inclusion pass = predicate true, exclusion pass =
  predicate false.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Literal, Protocol, cast

from lake.client import LakeAPI
from tb_common.fhir import FhirEvaluator
from tb_common.llm import LlmClient, LlmError
from tb_common.pair import Vote, combine, needs_verifier
from tb_common.quotes import quote_in
from tb_common.reasons import Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionIR, CriterionVerdict, Evidence, PatientEvaluation

from orchestrator.scenarios.terms import keywords
from orchestrator.twophase import two_phase

Verdict = Literal["pass", "fail", "unknown", "pending_human"]
CHUNK_TOKENS = 2500
FULL_RECORD_TOKENS = 28000
FULL_RECORD_MAX_CANDIDATES = 100


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

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        if not pids:
            return {}
        t = self.lake.query(rs.sql, [[index_date.isoformat()], list(pids)], self.snapshot).to_pylist()
        out: dict[str, PatientEvaluation] = {}
        for row in t:
            res = {k[2:]: row[k] for k in row if k.startswith("C_") and k[2:] in ids}
            ev = {
                k[2:]: [x for x in (row[k] or "").split(";") if x] for k in row if k.startswith("E_") and k[2:] in ids
            }
            out[row["pid"]] = PatientEvaluation(
                pid=row["pid"], index_date=index_date, engine="sql", results=res, evidence=ev
            )
        return out


def engine_from_env(name: str, fhir: FhirEvaluator | None, lake: LakeAPI, snapshot: str | None) -> StructuredEngine:
    if name == "sql" or fhir is None:
        return SqlEngine(lake, snapshot)
    return CqlEngine(fhir)


# --------------------------------------------------------------------------------------------- note criteria
def _tokens(text: str) -> int:
    """Conservative token estimate: CJK characters ~1 token each, Latin ~4 characters per token."""
    cjk = sum(1 for ch in text if "　" <= ch <= "鿿" or "豈" <= ch <= "﫿")
    return cjk + (len(text) - cjk) // 4 + 1


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
    model_reason: str = ""  # the judge model's own sentence: audit and debugging only, never shown on a page
    call_id: str = ""  # the judge call behind the answer (the cascade's evidence meta)
    model: str = ""
    prompt: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


def _vote(r: NoteResult) -> Vote:
    return Vote(r.predicate, r.confidence, r.reason)


@dataclass
class NoteJudge:
    """The note judge of both screening paths, with the two-model rule of :mod:`tb_common.pair` (D-118).

    :meth:`judge_excerpts` is the one place a note criterion is put to the models: the v1 evaluator (NAV,
    MICROBATCH, CASE), the v4 cascade through ``OrchestratorJudge`` and the CASE chart upload all call it. With a
    verifier every decided judge answer is put to the verifier with the same excerpts, and the pair's answer is
    :func:`tb_common.pair.combine`: it stands only when both agree, else it is ``unknown`` with the reason
    (``disagree``, ``verifier_quote_missing``, ``model_down``), which the tiering sends to review. So a note criterion
    blocks a patient only when both models say so. A model that does not answer counts as a failure for
    :func:`check_judge`; its error text never reaches a reason (``model_down``)."""

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

    @property
    def mode(self) -> str:
        return "agreement" if self.verifier is not None else "single"

    def _lake(self) -> LakeAPI:
        if self.lake is None:
            raise RuntimeError("this note judge has no lake: pass the excerpts to judge_excerpts")
        return self.lake

    def excerpts(self, pid: str, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
        lo, hi = note_window(c, index_date)
        query = " ".join([c.note_question or c.text, *keywords(c.text)])
        hits = self._lake().chunks_search(pid, query, k=5, date_from=lo, date_to=hi)
        hits = [h for h in hits if h.get("date") and lo.isoformat() <= str(h["date"])[:10] <= hi.isoformat()]
        hits.sort(key=lambda h: (str(h["date"]), str(h.get("did", ""))), reverse=True)
        out: list[dict[str, Any]] = []
        budget = CHUNK_TOKENS
        for h in hits:
            n = _tokens(str(h["text"]))
            if n > budget:
                break
            budget -= n
            out.append(
                {
                    "date": str(h["date"])[:10],
                    "note_type": h.get("type") or "note",
                    "text": h["text"],
                    "did": h.get("did"),
                }
            )
        return out

    def full_record(self, pid: str, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
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
        budget = FULL_RECORD_TOKENS
        for r in rows:
            n = _tokens(str(r["text"]))
            if n > budget:
                break
            budget -= n
            out.append(
                {"date": r["d"].isoformat(), "note_type": r["type"] or "note", "text": r["text"], "did": r["did"]}
            )
        return out

    def judge_patient(self, pid: str, c: CriterionIR, index_date: date, full: bool = False) -> NoteResult:
        excerpts = self.full_record(pid, c, index_date) if full else self.excerpts(pid, c, index_date)
        source = "full_record" if full else "chunks"
        if not excerpts:
            return NoteResult("unknown", 0.0, reason=Reason.NO_NOTES.value, source=source)
        return self.judge_excerpts(c.text, c.note_question or c.text, index_date, excerpts, source)

    def _ask(
        self, client: LlmClient, variables: dict[str, Any], excerpts: list[dict[str, Any]], source: str
    ) -> NoteResult:
        try:
            res = client.chat_json(self.prompt, variables, job_id=self.job_id)
        except LlmError:
            self.failures += 1
            return NoteResult("unknown", 0.0, reason=Reason.MODEL_DOWN.value, source=source)
        self.calls += 1
        self.tokens_in += res.tokens_in
        self.tokens_out += res.tokens_out
        r = postprocess(res.data, excerpts, source)
        return replace(
            r,
            call_id=res.output_sha[:16],
            model=res.model,
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
            self.disagreements += 1
        t_in = first.tokens_in + (second.tokens_in if second else 0)
        t_out = first.tokens_out + (second.tokens_out if second else 0)
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
            )
        return replace(first, confidence=d.confidence, reason=d.reason, tokens_in=t_in, tokens_out=t_out)


# a few unanswered note checks stay "unknown" (manual review); more than this share means the model was down and the
# list would silently be a structured-only list, so the job fails instead
MAX_JUDGE_FAILURE_SHARE = 0.1


def check_judge(judge: NoteJudge | None) -> None:
    if judge is None or not judge.failures:
        return
    total = judge.calls + judge.failures
    if judge.failures > MAX_JUDGE_FAILURE_SHARE * total:
        from orchestrator.clients import StepFailed

        raise StepFailed(
            "judging",
            f"The model did not answer {judge.failures} of {total} note checks, so the note-based criteria could not "
            f"be judged. Nothing was sent; send the request again when the model is back.",
        )


def postprocess(d: dict[str, Any], excerpts: list[dict[str, Any]], source: str = "chunks") -> NoteResult:
    """SPEC §7.3: the quote must be a substring of one excerpt (whitespace-normalised), else ``unknown``."""
    verdict = str(d.get("verdict", "unknown"))
    quote = d.get("quote")
    conf = float(d.get("confidence", 0.0))
    did = None
    if verdict != "unknown":
        q = str(quote or "")
        match = next((e for e in excerpts if quote_in(q, str(e["text"]))), None)
        if match is None:
            return NoteResult("unknown", 0.0, reason=Reason.QUOTE_NOT_FOUND.value, source=source)
        did = match.get("did")
    why = Reason.NOTE.value if verdict in ("pass", "fail") else Reason.ABSTAINED.value
    model_reason = str(d.get("reason") or "")
    return NoteResult(
        verdict, conf, quote, d.get("quote_date"), why, source, [str(did)] if did else [], model_reason=model_reason
    )


# --------------------------------------------------------------------------------------------- verdicts & tiers
def eligibility(kind: str, predicate: bool | None) -> Verdict:
    if predicate is None:
        return "unknown"
    ok = predicate if kind != "exclusion" else not predicate
    return "pass" if ok else "fail"


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
    # D-113: unknown with records attached = coded inside the grouper's family but outside its code list
    if known is None:
        why = Reason.CODE_OUTSIDE_LIST.value if refs else Reason.DATA_GAP.value
    else:
        why = Reason.CODED.value
    return CriterionVerdict(
        id=c.id,
        verdict=eligibility(c.kind, known),
        evidence=Evidence(resource_refs=refs[:20], reason=why),
    )


def note_verdict(c: CriterionIR, r: NoteResult) -> CriterionVerdict:
    pred = {"pass": True, "fail": False}.get(r.predicate)
    refs = [f"DocumentReference/{d}" for d in r.dids]
    return CriterionVerdict(
        id=c.id,
        verdict=eligibility(c.kind, pred),
        evidence=Evidence(
            resource_refs=refs, quote=r.quote, quote_date=r.quote_date, confidence=r.confidence, reason=r.reason
        ),
    )


def human_verdict(c: CriterionIR) -> CriterionVerdict:
    return CriterionVerdict(
        id=c.id, verdict="pending_human", evidence=Evidence(resource_refs=[], reason=Reason.HUMAN.value)
    )


def not_in_snapshot(rs: Ruleset, pid: str, kinds: tuple[str, ...] = ("inclusion", "exclusion")) -> PatientVerdicts:
    """A scoped patient the records snapshot does not hold (moved, merged, a late registration): nothing is known,
    so a person looks (tier ``review``), never an exclusion (Fable review 2026-11-08, finding 10; D-118)."""
    vs = [
        CriterionVerdict(
            id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason=Reason.NOT_IN_SNAPSHOT.value)
        )
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
    """A verdict that came from the note judge (and so follows the confidence and note-block rules): every ``note``
    verdict, and a ``mixed`` verdict the coded data did not settle (it carries a model confidence)."""
    if c.class_ == "note":
        return True
    return c.class_ == "mixed" and v.evidence is not None and v.evidence.confidence is not None


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
    if policy == "never":
        return False, "never", "configured: note answers never exclude"
    if judge is None:
        return False, "never", "no note judge on this box"
    if judge.verifier is None:
        return False, "never", "no verifier configured: a single model may not exclude"
    from orchestrator.canary_gate import allows_block

    ok, why = allows_block()  # D-117: only on a pair that passed its canary (and every wake check since)
    if not ok:
        return False, "never", why
    return True, "both_agree", "judge and verifier must both say fail"


def tier(
    rs: Ruleset, verdicts: list[CriterionVerdict], threshold: float, note_block: bool | None = None
) -> tuple[str, list[str], int]:
    """high: every structured/note criterion passes (note with confidence ≥ t), only human criteria pending;
    excluded: any criterion fails (note fails only with confidence ≥ t, and only when note answers may block, see
    :func:`note_block_policy`); review otherwise. Returns tier, actions, number of unknowns."""
    if note_block is None:
        note_block = note_block_policy() != "never"
    by_id = rs.by_id()
    actions: list[str] = []
    unknown = 0
    failed = False
    weak = False
    for v in verdicts:
        c = by_id[v.id]
        conf = v.evidence.confidence if v.evidence and v.evidence.confidence is not None else 1.0
        if v.verdict == "fail":
            if is_note_answer(c, v) and (conf < threshold or not note_block):
                weak = True
            else:
                failed = True
        elif v.verdict == "unknown":
            unknown += 1
            if c.action:
                actions.append(c.action)
        elif v.verdict == "pending_human":
            if c.action:
                actions.append(c.action)
        elif v.verdict == "pass" and is_note_answer(c, v) and conf < threshold:
            weak = True
            if c.action:
                actions.append(c.action)
    if failed:
        t = "excluded"
    elif unknown or weak:
        t = "review"
    else:
        t = "high"
    seen: set[str] = set()
    acts = [a for a in actions if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
    return t, acts, unknown


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
    if note_block is None:
        note_block = effective_note_block(judge)[0]
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
                    note_verdict(c, r)
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
