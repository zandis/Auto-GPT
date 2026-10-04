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

import re
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, Protocol, cast

from lake.client import LakeAPI
from tb_common.fhir import FhirEvaluator
from tb_common.llm import LlmClient, LlmError
from tb_common.ruleset import Ruleset
from tb_contracts import CandidateRow, CriterionIR, CriterionVerdict, Evidence, PatientEvaluation

from orchestrator.scenarios.terms import keywords

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
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


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
    reason: str | None = None
    source: str = "chunks"  # chunks | full_record
    dids: list[str] = field(default_factory=list)


@dataclass
class NoteJudge:
    lake: LakeAPI
    llm: LlmClient
    prompt: str = "judge"
    job_id: str | None = None
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0

    def excerpts(self, pid: str, c: CriterionIR, index_date: date) -> list[dict[str, Any]]:
        lo, hi = note_window(c, index_date)
        query = " ".join([c.note_question or c.text, *keywords(c.text)])
        hits = self.lake.chunks_search(pid, query, k=5, date_from=lo, date_to=hi)
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
        rows = self.lake.query(
            "SELECT did, CAST(date AS DATE) AS d, type, text FROM document WHERE pid = $1 "
            "AND CAST(date AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE) ORDER BY date DESC, did",
            [pid, lo.isoformat(), hi.isoformat()],
        ).to_pylist()
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

    def judge(self, pid: str, c: CriterionIR, index_date: date, full: bool = False) -> NoteResult:
        excerpts = self.full_record(pid, c, index_date) if full else self.excerpts(pid, c, index_date)
        source = "full_record" if full else "chunks"
        if not excerpts:
            return NoteResult("unknown", 0.0, reason="no notes in the window", source=source)
        try:
            res = self.llm.chat_json(
                self.prompt,
                {
                    "criterion_text": c.text,
                    "note_question": c.note_question or c.text,
                    "index_date": index_date.isoformat(),
                    "excerpts": [{k: e[k] for k in ("date", "note_type", "text")} for e in excerpts],
                },
                job_id=self.job_id,
            )
        except LlmError as exc:
            return NoteResult("unknown", 0.0, reason=f"judge unavailable: {str(exc)[:120]}", source=source)
        self.calls += 1
        self.tokens_in += res.tokens_in
        self.tokens_out += res.tokens_out
        return postprocess(res.data, excerpts, source)


def postprocess(d: dict[str, Any], excerpts: list[dict[str, Any]], source: str = "chunks") -> NoteResult:
    """SPEC §7.3: the quote must be a substring of one excerpt (whitespace-normalised), else ``unknown``."""
    verdict = str(d.get("verdict", "unknown"))
    quote = d.get("quote")
    conf = float(d.get("confidence", 0.0))
    did = None
    if verdict != "unknown":
        nq = _norm(str(quote or ""))
        match = next((e for e in excerpts if nq and nq in _norm(str(e["text"]))), None)
        if match is None:
            return NoteResult("unknown", 0.0, reason="quote_not_found", source=source)
        did = match.get("did")
    return NoteResult(verdict, conf, quote, d.get("quote_date"), d.get("reason"), source, [str(did)] if did else [])


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
    return CriterionVerdict(
        id=c.id,
        verdict=eligibility(c.kind, pred if isinstance(pred, bool) else None),
        evidence=Evidence(resource_refs=refs[:20]),
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
    return CriterionVerdict(id=c.id, verdict="pending_human", evidence=Evidence(resource_refs=[]))


def structured_candidate(rs: Ruleset, ev: PatientEvaluation | None, ids: set[str] | None = None) -> bool:
    """SPEC §8.2: all structured inclusions in {true, null} and no structured exclusion true."""
    if ev is None:
        return False
    for c in rs.active():
        if (
            c.class_ != "structured"
            or (ids is not None and c.id not in ids)
            or c.kind not in ("inclusion", "exclusion")
        ):
            continue
        v = ev.results.get(c.id)
        if c.kind == "inclusion" and v is False:
            return False
        if c.kind == "exclusion" and v is True:
            return False
    return True


def tier(rs: Ruleset, verdicts: list[CriterionVerdict], threshold: float) -> tuple[str, list[str], int]:
    """high: every structured/note criterion passes (note with confidence ≥ t), only human criteria pending;
    excluded: any criterion fails (note fails only with confidence ≥ t); review otherwise. Returns tier, actions,
    number of unknowns."""
    by_id = rs.by_id()
    actions: list[str] = []
    unknown = 0
    failed = False
    weak = False
    for v in verdicts:
        c = by_id[v.id]
        conf = v.evidence.confidence if v.evidence and v.evidence.confidence is not None else 1.0
        if v.verdict == "fail":
            if c.class_ == "note" and conf < threshold:
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
        elif v.verdict == "pass" and c.class_ == "note" and conf < threshold:
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
) -> dict[str, PatientVerdicts]:
    """Structured screen of every pid, then note criteria for structured candidates only (SPEC §8.2)."""
    active = [c for c in rs.active() if c.kind in ("inclusion", "exclusion") and (only is None or c.id in only)]
    structured_ids = [c.id for c in active if c.class_ == "structured"]
    evals = engine.evaluate(rs, pids, index_date, structured_ids) if structured_ids else {}
    if not structured_ids:
        evals = {
            p: PatientEvaluation(pid=p, index_date=index_date, engine=cast(Any, engine.name), results={}) for p in pids
        }
    cands = [p for p in pids if all_candidates or structured_candidate(rs, evals.get(p), set(structured_ids))]
    notes = [c for c in active if c.class_ == "note"]
    note_res: dict[tuple[str, str], NoteResult] = {}
    if judge is not None and notes and cands:
        tasks = [(p, c) for p in cands for c in notes]

        def run(task: tuple[str, CriterionIR]) -> tuple[tuple[str, str], NoteResult]:
            p, c = task
            r = judge.judge(p, c, index_date)
            if r.predicate == "unknown" and full_record_fallback and len(cands) <= FULL_RECORD_MAX_CANDIDATES:
                r2 = judge.judge(p, c, index_date, full=True)
                if r2.predicate != "unknown" or r.reason == "no notes in the window":
                    r = r2
            return (p, c.id), r

        with ThreadPoolExecutor(max_workers=workers) as ex:
            note_res = dict(ex.map(run, tasks))
    out: dict[str, PatientVerdicts] = {}
    for p in pids:
        ev = evals.get(p)
        vs: list[CriterionVerdict] = []
        for c in active:
            if c.class_ == "structured":
                vs.append(structured_verdict(c, ev))
            elif c.class_ == "note":
                r = note_res.get((p, c.id))
                vs.append(
                    note_verdict(c, r)
                    if r is not None
                    else CriterionVerdict(
                        id=c.id, verdict="unknown", evidence=Evidence(resource_refs=[], reason="not evaluated")
                    )
                )
            else:
                vs.append(human_verdict(c))
        if p in cands:
            t, acts, n_unk = tier(rs, vs, threshold)
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
