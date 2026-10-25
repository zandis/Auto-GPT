"""The filter-first cascade S0 → S1 → S2 → S2b → S3 → S4 → S5 over the dataplat L5 snapshot (spec v4 §4.5).

:func:`run_cascade` evaluates one study's ruleset for the population of scope and returns a :class:`CascadeResult`:
per-patient traces (D3), the CAS-1 stage log (patients and pairs entering and leaving every stage, with the class
label and the IR hash), the CAS-7 metrics, the S5 review queue and the final list.

Stages:

* **S0** scope: ≥ 1 encounter in the lookback (the FEAS population of v1), research-use opt-outs removed
  (FHIR Consent ``status = rejected``), ``contact: deny`` flagged: kept in aggregates, never listed (§7, 1444).
* **S1** compiled SQL (IR → SQL, never hand-written) on the lake, three-valued. The patient is evaluated at the
  month-end where the sequential funnel reaches deepest (latest on ties), so the sequential attrition equals the v1
  FEAS funnel exactly. IR < 2.0.0 keeps v1 semantics (CAS-19); IR ≥ 2.0.0 uses affirmative exclusion (CAS-11) with the
  index-condition rescue through S2/S2b (CAS-18).
* **S2** approved-lexicon pre-filter on the note sentences in the window: hits → S3; zero hits → S2b (CAS-12), or
  absence semantics only for criteria certified under CAS-13; no note in the window → ``unknown:data_gap``.
* **S2b** semantic screen (``s2b_semantic``): above → S3, below → absence semantics (stratum ``S2b-below``).
* **S3** judge through ``tb-gateway`` in exclusion-power ÷ expected-token order, stopping at the first verified hard
  ``not_met`` (CAS-3); spans verified (CAS-16); budgets (CAS-4); sentence-set cache (CAS-5).
* **S4** second opinion (role ``second_opinion``) on would-be strong candidates; disagreement → ``potential:uncertain``.
* **S5** review queue (D3): candidates with contact allowed; an injected reviewer records decisions; the final list
  holds the confirmed candidates.

In a feasibility run (``CascadeConfig.sample_per_stratum``) S3/S4 see a seeded stratified sample (CAS-8).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tb_common.ruleset import Ruleset
from tb_common.timeutil import add_months, month_ends
from tb_contracts import CriterionIR

from matching.cascade.judge import JudgeClient, JudgeReply, expected_tokens, norm, sentence_hash, verify_span
from matching.cascade.model import (
    STAGES,
    STRATUM_INDEX,
    STRATUM_S1,
    STRATUM_S2B,
    STRATUM_S3,
    STRATUM_ZERO_HIT,
    CascadeMetrics,
    Outcome,
    PatientTrace,
    ReviewItem,
    Semantics,
    Stage,
    StageLog,
)
from matching.cascade.s2b_semantic import BatchEmbedder, Embedder, ThresholdTable, screen

PATIENT_CLASS = "D3"  # every cascade output is patient level (§7.1)
UNKNOWN_KEPT = "unknown_kept"  # v1: an unknown exclusion does not exclude (FEAS D-18)
EXCERPT_TOKENS = 2500
EXCLUSION_POWER_PRIOR = 0.5  # CAS-3 prior until the criterion library has site history
_SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")

Reviewer = Callable[[ReviewItem, PatientTrace], dict[str, Any]]


class CascadeError(RuntimeError):
    pass


class LakeLike:
    """The lake surface the cascade needs (``lake.client.LakeAPI``)."""

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        raise NotImplementedError


@dataclass
class CascadeConfig:
    study_id: str
    run_date: date
    lookback_months: int = 36
    index_mode: str = "month_ends"  # month_ends (FEAS population, v1) | single (screening at run_date)
    notes_class: str = "D0"  # class label of note text sent to the gateway (eval/DATASETS.yaml for D0 datasets)
    purpose: str = "feasibility"
    step_id: str = ""
    max_llm_items: int = 2000  # CAS-4 defaults
    max_tokens: int = 10_000_000
    zero_hit_allowed: frozenset[str] = frozenset()  # CAS-13 certified criteria, read from the registry
    semantics: Semantics | None = None  # None: from the IR version (CAS-19)
    exclusion_power: Mapping[str, float] = field(default_factory=dict)  # canonical hash -> pooled not_met share
    confidence_floor: float = 0.75  # below: abstained (not hard, CAS-7)
    thresholds: ThresholdTable = field(default_factory=ThresholdTable)
    lexicon: Mapping[str, Sequence[str]] = field(default_factory=dict)  # approved terms per criterion id
    language: str = "zh-TW"  # language stratum of the site notes (S2b thresholds)
    sample_per_stratum: int | None = None  # CAS-8: ≤ 200 in feasibility runs; None screens everyone
    seed: int = 20261025
    snapshot: str | None = None


@dataclass
class CascadeResult:
    study_id: str
    ruleset: str
    ruleset_version: str
    semantics: Semantics
    ir_hash: str
    criterion_hashes: dict[str, str]
    index_dates: list[date]
    traces: dict[str, PatientTrace]
    stages: list[StageLog]
    metrics: CascadeMetrics
    queue: list[ReviewItem]
    final_list: list[str]
    applied: list[str]  # structured criteria compiled into the SQL, protocol order
    note_criteria: list[str]
    human_criteria: list[str]
    data_class: str = PATIENT_CLASS

    def stage(self, name: Stage) -> StageLog:
        return next(s for s in self.stages if s.stage == name)

    def in_scope(self) -> list[PatientTrace]:
        return [t for t in self.traces.values() if t.in_scope]

    def tier_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.in_scope():
            out[t.tier] = out.get(t.tier, 0) + 1
        return out

    def manifest_block(self) -> dict[str, Any]:
        """The §6.9 run-manifest ``cascade`` block (CAS-1, CAS-7)."""
        m = self.metrics
        return {
            "n_scope": m.n_scope,
            "n_after": dict(m.n_after),
            "pairs_S2_zero_hit": m.pairs_s2_zero_hit,
            "pairs_S2b_above": m.pairs_s2b_above,
            "pairs_S2b_below": m.pairs_s2b_below,
            "pairs_judged": dict(m.pairs_judged),
            "tokens": {"in": m.tokens_in, "out": m.tokens_out},
            "cache_hits": m.cache_hits,
            "llm_share": m.llm_share,
            "unprocessed": m.unprocessed,
            "rescue_yield": m.rescued,
            "sampled_patients": m.sampled_patients,
            "zero_hit_exclusions": {"allowed_criteria": 0},
            "semantics": self.semantics,
            "ir_hash": self.ir_hash,
            "stages": [
                {
                    "stage": s.stage,
                    "patients_in": s.patients_in,
                    "patients_out": s.patients_out,
                    "pairs_in": s.pairs_in,
                    "pairs_out": s.pairs_out,
                    "data_class": s.data_class,
                    "ir_hash": s.ir_hash,
                    **({"detail": s.detail} if s.detail else {}),
                }
                for s in self.stages
            ],
            "data_class": self.data_class,
        }


# ------------------------------------------------------------------------------------------------ IR helpers
def criterion_hashes(rs: Ruleset) -> dict[str, str]:
    """Canonical hash per criterion (§6.2.7, IR v3 normal form of the v1 criterion, value sets by content)."""
    from tb_contracts.criterion_ir import canonical_hash, upgrade_v1, valueset_content_hash

    vs = {name: valueset_content_hash(v) for name, v in rs.valuesets.items()}
    return {c.id: canonical_hash(upgrade_v1(c), vs) for c in rs.active()}


def ruleset_ir_hash(hashes: Mapping[str, str]) -> str:
    body = "\n".join(f"{k}={v}" for k, v in sorted(hashes.items()))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def ir_semantics(rs: Ruleset) -> Semantics:
    """CAS-19: affirmative exclusion (CAS-11/12) only for IR ≥ 2.0.0. v1 rulesets carry no ``ir_version``."""
    versions = {str(getattr(c, "ir_version", None) or "1.0.0") for c in rs.active()}
    return "affirmative" if versions and all(int(v.split(".")[0]) >= 2 for v in versions) else "v1"


def _atoms(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if "args" in node:
        return [a for arg in node["args"] for a in _atoms(arg)]
    return [node]


def is_value_criterion(c: CriterionIR) -> bool:
    """A value comparison (threshold, age, derived value): a FALSE result is a failing value, i.e. affirmative."""
    logic = c.logic.model_dump(mode="json", by_alias=True, exclude_none=True)
    return any(a.get("value") is not None or a.get("age") is not None for a in _atoms(logic))


def is_index_criterion(c: CriterionIR) -> bool:
    return bool(getattr(c, "index", None))


def window_of(c: CriterionIR, index_date: date) -> tuple[date, date]:
    """Note window: the IR window when narrower than a year, else the year before the index date."""
    lo = index_date - timedelta(days=365)
    w = getattr(c.logic, "window", None)
    if w is not None and w.from_days is not None and w.from_days > -365:
        lo = index_date + timedelta(days=int(w.from_days))
    return lo, index_date


def lexicon_terms(c: CriterionIR, extra: Mapping[str, Sequence[str]]) -> list[str]:
    """Approved lexicon keys for the criterion: the site table when present, else the shipped bilingual terms."""
    if c.id in extra:
        return [str(t) for t in extra[c.id]]
    from orchestrator.scenarios.terms import keywords

    return keywords(f"{c.text} {c.note_question or ''}", limit=24)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.findall(text) if s.strip()]


# ------------------------------------------------------------------------------------------------ the run
POP_SQL = """
SELECT p.pid,
       (SELECT arg_max(e2.dept, e2.start) FROM encounter e2 WHERE e2.pid = p.pid) AS dept
FROM patient p
WHERE EXISTS (SELECT 1 FROM encounter e WHERE e.pid = p.pid
              AND CAST(e.start AS DATE) BETWEEN CAST($1 AS DATE) AND CAST($2 AS DATE))
ORDER BY p.pid
"""
CONSENT_SQL = "SELECT pid, status, contact_ok FROM consent ORDER BY pid, date"
NOTES_SQL = """
SELECT did, pid, CAST(date AS DATE) AS d, type, text FROM document
WHERE list_contains(CAST($1 AS VARCHAR[]), pid) AND CAST(date AS DATE) BETWEEN CAST($2 AS DATE) AND CAST($3 AS DATE)
ORDER BY pid, date DESC, did
"""


@dataclass
class _Note:
    did: str
    d: date
    type: str
    text: str
    sents: list[str]


@dataclass
class _Route:
    """A note pair on its way to S3."""

    pid: str
    cid: str
    excerpts: list[dict[str, Any]]
    sentence_set: str
    via: Stage  # S2 (lexicon hit) or S2b (above threshold)
    margin: float = 0.0


class _Run:
    def __init__(
        self,
        lake: LakeLike,
        rs: Ruleset,
        cfg: CascadeConfig,
        judge: JudgeClient | None,
        embedder: Embedder | None,
    ) -> None:
        self.lake = lake
        self.rs = rs
        self.cfg = cfg
        self.judge = judge
        self.embedder = BatchEmbedder(embedder) if embedder is not None else None
        self.hashes = criterion_hashes(rs)
        self.ir_hash = ruleset_ir_hash(self.hashes)
        self.semantics: Semantics = cfg.semantics or ir_semantics(rs)
        self.crit = {c.id: c for c in rs.active()}
        self.metrics = CascadeMetrics()
        self.stages: list[StageLog] = []
        self.traces: dict[str, PatientTrace] = {}
        self.cache: dict[str, JudgeReply] = {}
        self.items = 0
        self.tokens = 0

    def log(self, stage: Stage, p_in: int, p_out: int, q_in: int, q_out: int, **detail: Any) -> None:
        self.stages.append(StageLog(stage, p_in, p_out, q_in, q_out, PATIENT_CLASS, self.ir_hash, dict(detail)))

    def alive(self) -> list[PatientTrace]:
        return [t for t in self.traces.values() if t.in_scope and t.exit_stage is None]

    def exclude(self, t: PatientTrace, stage: Stage, cid: str) -> None:
        if t.exit_stage is None:
            t.exit_stage, t.exit_criterion = stage, cid

    # -------------------------------------------------------------------------------------------- S0
    def s0(self) -> list[date]:
        cfg = self.cfg
        if cfg.index_mode == "single":
            idx = [cfg.run_date]
            pop_from = add_months(cfg.run_date, -cfg.lookback_months)
        else:
            idx = month_ends(cfg.run_date, cfg.lookback_months)
            if not idx:
                raise CascadeError("lookback must be at least one month")
            pop_from = add_months(idx[0], -1)
        n_all = int(self.lake.query("SELECT count(*) AS n FROM patient", [], cfg.snapshot).to_pylist()[0]["n"])
        rows = self.lake.query(POP_SQL, [pop_from.isoformat(), idx[-1].isoformat()], cfg.snapshot).to_pylist()
        consent: dict[str, tuple[str, bool | None]] = {}
        try:
            for r in self.lake.query(CONSENT_SQL, [], cfg.snapshot).to_pylist():
                consent[str(r["pid"])] = (str(r["status"] or ""), r["contact_ok"])
        except Exception:  # a lake without the consent table has no opt-outs to apply
            consent = {}
        opted_out = 0
        for r in rows:
            pid = str(r["pid"])
            status, contact = consent.get(pid, ("", None))
            t = PatientTrace(pid=pid, index_date=idx[-1], department=r.get("dept"))
            if status == "rejected":
                t.in_scope, t.scope_reason = False, "research-use opt-out (FHIR Consent rejected)"
                opted_out += 1
            t.contact_ok = contact is not False
            self.traces[pid] = t
        n_scope = sum(1 for t in self.traces.values() if t.in_scope)
        self.metrics.n_scope = n_scope
        n_c = len(self.crit)
        self.log(
            "S0",
            n_all,
            n_scope,
            n_all * n_c,
            n_scope * n_c,
            population=f"≥1 encounter {pop_from.isoformat()}…{idx[-1].isoformat()}",
            opted_out=opted_out,
            contact_denied=sum(1 for t in self.traces.values() if t.in_scope and not t.contact_ok),
        )
        self.metrics.n_after["S0"] = n_scope
        return idx

    # -------------------------------------------------------------------------------------------- S1
    def applied(self) -> list[CriterionIR]:
        return [
            c
            for c in self.rs.active()
            if c.class_ == "structured" and c.kind in ("inclusion", "exclusion") and f'"C_{c.id}"' in self.rs.sql
        ]

    def _pass(self, c: CriterionIR, v: bool | None) -> bool:
        if c.kind == "inclusion":
            return v is True
        return v is not True

    def s1(self, idx: list[date]) -> list[CriterionIR]:
        applied = self.applied()
        scope = [t.pid for t in self.traces.values() if t.in_scope]
        if not applied:
            raise CascadeError(f"ruleset {self.rs.id} has no compiled structured criteria")
        table = self.lake.query(self.rs.sql, [[d.isoformat() for d in idx], scope], self.cfg.snapshot).to_pylist()
        by_pid: dict[str, list[dict[str, Any]]] = {}
        for row in table:
            by_pid.setdefault(str(row["pid"]), []).append(row)
        for pid in scope:
            t = self.traces[pid]
            rows = sorted(by_pid.get(pid, []), key=lambda r: r["index_date"])
            best: dict[str, Any] | None = None
            best_depth = -1
            for row in rows:
                depth = 0
                for c in applied:
                    if not self._pass(c, row.get(f"C_{c.id}")):
                        break
                    depth += 1
                if depth >= best_depth:  # latest date on ties
                    best, best_depth = row, depth
            if best is None:  # not alive at any index date (deceased before the lookback's first month-end)
                t.in_scope, t.scope_reason = False, "not alive at an index date"
                continue
            t.index_date = best["index_date"]
            applied_ids = {a.id for a in applied}
            for c in self.rs.active():
                if c.class_ != "structured" or c.kind not in ("inclusion", "exclusion"):
                    continue
                if c.id not in applied_ids:
                    t.outcomes[c.id] = Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="not compiled")
                    continue
                t.outcomes[c.id] = self._s1_outcome(c, best)
            first_fail = next((c.id for c in applied if t.outcomes[c.id].hard), None)
            if first_fail:
                self.exclude(t, "S1", first_fail)
        n_scope = self.metrics.n_scope = sum(1 for t in self.traces.values() if t.in_scope)
        self.metrics.n_after["S0"] = n_scope
        self.stages[0].patients_out = n_scope
        alive = self.alive()
        n_struct = len(applied)
        self.log(
            "S1",
            n_scope,
            len(alive),
            n_scope * n_struct,
            sum(1 for t in alive for c in applied if t.outcomes[c.id].status != "fail"),
            semantics=self.semantics,
            index_dates=len(idx),
            deferred_index=sum(1 for t in alive for o in t.outcomes.values() if o.reason == "index_absent"),
        )
        self.metrics.n_after["S1"] = len(alive)
        return applied

    def _s1_outcome(self, c: CriterionIR, row: Mapping[str, Any]) -> Outcome:
        v = row.get(f"C_{c.id}")
        ev = [
            {
                "source": "lake",
                "record": x.split("|")[0],
                "date": x.split("|")[1] if "|" in x else None,
                "lineage": f"snapshot:{self.cfg.snapshot or ''}",
                "index_date": row["index_date"].isoformat(),
            }
            for x in str(row.get(f"E_{c.id}") or "").split(";")
            if x
        ]
        if c.kind == "exclusion":
            if v is True:
                return Outcome(c.id, "fail", "S1", hard=True, stratum=STRATUM_S1, evidence=ev, reason="matching record")
            if v is None:
                return Outcome(c.id, "pass", "S1", unknown_kind="data_gap", reason=UNKNOWN_KEPT)
            return Outcome(c.id, "pass", "S1", evidence=ev)
        if v is True:
            return Outcome(c.id, "pass", "S1", evidence=ev)
        if v is None:
            return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="no value in the window")
        # inclusion FALSE
        if self.semantics == "v1" or is_value_criterion(c):
            return Outcome(c.id, "fail", "S1", hard=True, stratum=STRATUM_S1, evidence=ev, reason="failing value")
        if is_index_criterion(c):
            return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="index_absent")
        return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="no record (CAS-11: missing → unknown)")

    # -------------------------------------------------------------------------------------------- notes
    def notes(self, pids: list[str]) -> dict[str, list[_Note]]:
        if not pids:
            return {}
        lo = min(self.traces[p].index_date for p in pids) - timedelta(days=366)
        hi = max(self.traces[p].index_date for p in pids)
        try:
            rows = self.lake.query(NOTES_SQL, [pids, lo.isoformat(), hi.isoformat()], self.cfg.snapshot).to_pylist()
        except Exception:  # a lake without notes (MIMIC demo): every note pair is a data gap
            rows = []
        out: dict[str, list[_Note]] = {}
        for r in rows:
            text = str(r["text"] or "")
            out.setdefault(str(r["pid"]), []).append(
                _Note(str(r["did"]), r["d"], str(r["type"] or "note"), text, sentences(text))
            )
        return out

    @staticmethod
    def excerpts(notes: list[_Note], keep: set[str]) -> list[dict[str, Any]]:
        """Whole notes holding an evidence sentence, newest first, within the token budget (v1 RAG budget)."""
        out: list[dict[str, Any]] = []
        budget = EXCERPT_TOKENS
        for n in sorted(notes, key=lambda n: (n.d, n.did), reverse=True):
            if n.did not in keep:
                continue
            cost = expected_tokens([{"text": n.text}]) - 300
            if cost > budget:
                break
            budget -= cost
            out.append({"date": n.d.isoformat(), "note_type": n.type, "text": n.text, "did": n.did})
        return out

    # -------------------------------------------------------------------------------------------- S2 / S2b
    def s2(self, note_crit: list[CriterionIR]) -> tuple[list[_Route], list[tuple[str, str, list[_Note]]]]:
        alive = self.alive()
        rescue = [t for t in alive if any(o.reason == "index_absent" for o in t.outcomes.values())]
        notes = self.notes([t.pid for t in alive])
        routes: list[_Route] = []
        zero: list[tuple[str, str, list[_Note]]] = []
        excluded_here = 0
        for t in alive:
            pnotes = notes.get(t.pid, [])
            for c in note_crit:
                lo, hi = window_of(c, t.index_date)
                win = [n for n in pnotes if lo <= n.d <= hi]
                if not win:
                    self.metrics.pairs_s2_no_notes += 1
                    t.outcomes[c.id] = Outcome(
                        c.id, "unknown", "S2", unknown_kind="data_gap", reason="no note in window"
                    )
                    continue
                terms = [norm(x).lower() for x in lexicon_terms(c, self.cfg.lexicon)]
                hits = [(n, s) for n in win for s in n.sents if terms and any(k in norm(s).lower() for k in terms)]
                if hits:
                    self.metrics.pairs_s2_hit += 1
                    sset = sorted({sentence_hash(s) for _, s in hits})
                    routes.append(
                        _Route(t.pid, c.id, self.excerpts(win, {n.did for n, _ in hits}), _set_hash(sset), "S2")
                    )
                    continue
                self.metrics.pairs_s2_zero_hit += 1
                if c.id in self.cfg.zero_hit_allowed:  # CAS-13 certified: absence semantics directly after S2
                    if c.kind == "inclusion":
                        t.outcomes[c.id] = Outcome(
                            c.id, "fail", "S2", hard=True, stratum=STRATUM_ZERO_HIT, reason="zero hits (certified)"
                        )
                        self.exclude(t, "S2", c.id)
                        excluded_here += 1
                    else:
                        t.outcomes[c.id] = Outcome(c.id, "pass", "S2", reason="zero hits (certified absence)")
                    continue
                zero.append((t.pid, c.id, win))
        # CAS-11 exception: absence of the index condition → lexicon sweep over the lookback, then S2b
        for t in rescue:
            cid = next(o.criterion_id for o in t.outcomes.values() if o.reason == "index_absent")
            c = self.crit[cid]
            terms = [norm(x).lower() for x in lexicon_terms(c, self.cfg.lexicon)]
            pnotes = notes.get(t.pid, [])
            hit = next((s for n in pnotes for s in n.sents if terms and any(k in norm(s).lower() for k in terms)), None)
            if hit is not None:
                self._rescue(t, cid, "S2", hit)
            else:
                zero.append((t.pid, f"index:{cid}", pnotes))
        alive_after = self.alive()
        self.log(
            "S2",
            len(alive),
            len(alive_after),
            len(alive) * len(note_crit),
            len(routes) + len(zero),
            hits=self.metrics.pairs_s2_hit,
            zero_hit=self.metrics.pairs_s2_zero_hit,
            no_notes=self.metrics.pairs_s2_no_notes,
            excluded_zero_hit=excluded_here,
        )
        self.metrics.n_after["S2"] = len(alive_after)
        return routes, zero

    def _rescue(self, t: PatientTrace, cid: str, stage: Stage, sentence: str) -> None:
        o = t.outcomes[cid]
        o.reason = "index rescued"
        o.rescue = {"stage": stage, "sentence_hash": sentence_hash(sentence)}
        self.metrics.rescued += 1

    def s2b(self, zero: list[tuple[str, str, list[_Note]]], routes: list[_Route]) -> None:
        alive_before = len(self.alive())
        n_in = len(zero)
        for pid, key, win in zero:
            t = self.traces[pid]
            index_sweep = key.startswith("index:")
            cid = key.split(":", 1)[1] if index_sweep else key
            c = self.crit[cid]
            sents = [(n, s) for n in win for s in n.sents]
            query = " ".join([c.note_question or c.text, *lexicon_terms(c, self.cfg.lexicon)])
            thr = self.cfg.thresholds.get(c.kind, self.cfg.language)
            if self.embedder is None:
                res_above, best, top = True, 1.0, list(range(min(5, len(sents))))  # no S2b: never absence
            else:
                res = screen(self.embedder, query, [s for _, s in sents], thr)
                res_above, best, top = res.above, res.best, [i for i, _ in res.top]
            if index_sweep:
                if res_above and sents:
                    self._rescue(t, cid, "S2b", sents[top[0]][1])
                else:
                    o = t.outcomes[cid]
                    o.status, o.hard, o.stratum, o.stage = "fail", True, STRATUM_INDEX, "S2b"
                    o.unknown_kind, o.reason = None, "index condition absent: no code, no S2 or S2b mention"
                    self.exclude(t, "S2b", cid)
                continue
            if res_above:
                self.metrics.pairs_s2b_above += 1
                keep = {sents[i][0].did for i in top}
                sset = sorted({sentence_hash(sents[i][1]) for i in top})
                routes.append(_Route(pid, cid, self.excerpts(win, keep), _set_hash(sset), "S2b", best - thr.value))
                continue
            self.metrics.pairs_s2b_below += 1
            detail = {"best": round(best, 4), "threshold": thr.value, "threshold_source": thr.source}
            if c.kind == "inclusion":
                t.outcomes[cid] = Outcome(
                    cid, "fail", "S2b", hard=True, stratum=STRATUM_S2B, evidence=[detail], reason="S2b below"
                )
                self.exclude(t, "S2b", cid)
            else:
                t.outcomes[cid] = Outcome(cid, "pass", "S2b", evidence=[detail], reason="S2b below: absence")
        self.metrics.s2b_embed_batches = self.embedder.batches if self.embedder else 0
        alive = self.alive()
        self.log(
            "S2b",
            alive_before,
            len(alive),
            n_in,
            self.metrics.pairs_s2b_above,
            above=self.metrics.pairs_s2b_above,
            below=self.metrics.pairs_s2b_below,
            embed_batches=self.metrics.s2b_embed_batches,
            embed_model=self.embedder.model if self.embedder else None,
        )
        self.metrics.n_after["S2b"] = len(alive)

    # -------------------------------------------------------------------------------------------- CAS-8 sample
    def sample(self, routes: list[_Route]) -> None:
        cap = self.cfg.sample_per_stratum
        alive = self.alive()
        sig: dict[str, list[str]] = {}
        for r in routes:
            sig.setdefault(r.pid, []).append(f"{r.cid}:{r.via}")
        strata: dict[str, list[str]] = {}
        for t in alive:
            t.sample_stratum = f"{'+'.join(sorted(sig.get(t.pid, []))) or 'no_route'}|{t.department or '-'}"
            strata.setdefault(t.sample_stratum, []).append(t.pid)
        rng = random.Random(self.cfg.seed)
        for key in sorted(strata):
            pids = sorted(strata[key])
            chosen = set(pids) if cap is None or len(pids) <= cap else set(rng.sample(pids, cap))
            for p in pids:
                self.traces[p].sampled = p in chosen
        self.metrics.sampled_patients = sum(1 for t in alive if t.sampled)

    # -------------------------------------------------------------------------------------------- S3 / S4
    def _power(self, cid: str) -> float:
        return float(self.cfg.exclusion_power.get(self.hashes[cid], EXCLUSION_POWER_PRIOR))

    def _ask(self, role: str, r: _Route, t: PatientTrace) -> tuple[JudgeReply, bool]:
        assert self.judge is not None
        c = self.crit[r.cid]
        lo, hi = window_of(c, t.index_date)
        key = json.dumps([r.pid, self.hashes[r.cid], r.sentence_set, role, lo.isoformat(), hi.isoformat()])
        if key in self.cache:
            self.metrics.cache_hits += 1
            return self.cache[key], True
        reply = self.judge.judge(
            role=role,
            criterion_text=c.text,
            note_question=c.note_question or c.text,
            index_date=t.index_date,
            excerpts=r.excerpts,
            study_id=self.cfg.study_id,
            data_class=self.cfg.notes_class,
            step_id=self.cfg.step_id or f"cascade:{self.cfg.study_id}",
            purpose=self.cfg.purpose,
        )
        if reply.refused:
            self.metrics.gateway_refusals += 1
        self.metrics.tokens_in += reply.tokens_in
        self.metrics.tokens_out += reply.tokens_out
        self.cache[key] = reply
        return reply, False

    def _map(self, c: CriterionIR, reply: JudgeReply, span: dict[str, Any] | None, stage: Stage) -> Outcome:
        ev = [span] if span else []
        meta = {"call_id": reply.call_id, "build_sha": reply.build_sha, "prompt": reply.prompt}
        if reply.verdict not in ("pass", "fail"):
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[meta], reason="abstained")
        if span is None:
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[meta], reason="insufficient")
        condition_present = reply.verdict == "pass"
        eligible = condition_present if c.kind == "inclusion" else not condition_present
        if eligible:
            return Outcome(c.id, "pass", stage, evidence=[*ev, meta], reason=reply.reason[:200])
        if reply.confidence < self.cfg.confidence_floor:
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[*ev, meta], reason="abstained")
        return Outcome(c.id, "fail", stage, hard=True, stratum=STRATUM_S3, evidence=[*ev, meta], reason="not_met")

    def s3(self, routes: list[_Route]) -> list[_Route]:
        by_pid: dict[str, list[_Route]] = {}
        for r in routes:
            by_pid.setdefault(r.pid, []).append(r)
        alive = self.alive()
        p_in = len(alive)
        judged: list[_Route] = []
        if self.judge is None:
            for pid, rs_ in by_pid.items():
                for r in rs_:
                    o = Outcome(r.cid, "unknown", "S3", unknown_kind="uncertain", reason="no judge configured")
                    self.traces[pid].outcomes[r.cid] = o
        for t in alive:
            pending = by_pid.get(t.pid, [])
            if self.judge is None or not pending:
                continue
            if not t.sampled:
                for r in pending:
                    t.outcomes[r.cid] = Outcome(r.cid, "unknown", "S3", unknown_kind="uncertain", reason="not sampled")
                continue
            # CAS-3: descending exclusion power / expected tokens
            pending = sorted(pending, key=lambda r: (-self._power(r.cid) / expected_tokens(r.excerpts), r.cid))
            for i, r in enumerate(pending):
                cost = expected_tokens(r.excerpts)
                if self.items + 1 > self.cfg.max_llm_items or self.tokens + cost > self.cfg.max_tokens:
                    t.unprocessed = True  # CAS-4: never silently truncated; SAFE-13: never an exclusion
                    for rest in pending[i:]:
                        t.outcomes[rest.cid] = Outcome(
                            rest.cid, "unknown", "S3", unknown_kind="uncertain", reason="unprocessed (budget)"
                        )
                    break
                reply, hit = self._ask("judge", r, t)
                if not hit:
                    self.items += 1
                    self.tokens += cost
                    self.metrics.pairs_judged["S3"] += 1
                c = self.crit[r.cid]
                lo, hi = window_of(c, t.index_date)
                o = self._map(c, reply, verify_span(reply, r.excerpts, lo, hi), "S3")
                t.outcomes[r.cid] = o
                judged.append(r)
                if o.hard:
                    self.exclude(t, "S3", r.cid)
                    for rest in pending[i + 1 :]:
                        t.outcomes[rest.cid] = Outcome(
                            rest.cid, "unknown", "S3", unknown_kind="uncertain", reason="not judged (CAS-3 stop)"
                        )
                    break
        self.metrics.unprocessed = sum(1 for t in self.traces.values() if t.unprocessed)
        alive_after = self.alive()
        self.log(
            "S3",
            p_in,
            len(alive_after),
            len(routes),
            sum(1 for r in judged if self.traces[r.pid].outcomes[r.cid].status != "fail"),
            judged=self.metrics.pairs_judged["S3"],
            unprocessed=self.metrics.unprocessed,
            sampled=self.metrics.sampled_patients,
            cache_hits=self.metrics.cache_hits,
        )
        self.metrics.n_after["S3"] = len(alive_after)
        return judged

    def s4(self, judged: list[_Route]) -> None:
        alive = self.alive()
        candidates = [t for t in alive if self._would_be_strong(t)]
        p_in = len(alive)
        cand = {t.pid for t in candidates}
        pairs = [r for r in judged if r.pid in cand and self.traces[r.pid].outcomes[r.cid].stage == "S3"]
        disagreements = 0
        if self.judge is not None:
            for r in pairs:
                t = self.traces[r.pid]
                first = t.outcomes[r.cid]
                reply, hit = self._ask("second_opinion", r, t)
                if not hit:
                    self.metrics.pairs_judged["S4"] += 1
                c = self.crit[r.cid]
                lo, hi = window_of(c, t.index_date)
                second = self._map(c, reply, verify_span(reply, r.excerpts, lo, hi), "S4")
                if second.status != first.status:
                    disagreements += 1
                    t.outcomes[r.cid] = Outcome(
                        r.cid,
                        "unknown",
                        "S4",
                        unknown_kind="uncertain",
                        evidence=first.evidence + second.evidence,
                        reason="S3/S4 disagree",
                    )
        alive_after = self.alive()
        self.log("S4", p_in, len(alive_after), len(pairs), len(pairs) - disagreements, disagreements=disagreements)
        self.metrics.n_after["S4"] = len(alive_after)

    def _would_be_strong(self, t: PatientTrace) -> bool:
        return all(o.status == "pass" for o in t.outcomes.values()) and any(
            o.stage == "S3" for o in t.outcomes.values()
        )

    # -------------------------------------------------------------------------------------------- tiers + S5
    def tiers(self, human: list[CriterionIR]) -> None:
        for t in self.traces.values():
            if not t.in_scope:
                t.tier = "out_of_scope"
                continue
            for c in human:
                t.outcomes.setdefault(c.id, Outcome(c.id, "pending_human", "S5", reason="human criterion"))
            if t.exit_stage is not None:
                fails = [o for o in t.outcomes.values() if o.hard]
                timed = all(self.crit[o.criterion_id].time_sensitive for o in fails) if fails else False
                t.tier = "watchlist" if timed else "excluded"
                continue
            kinds = {o.unknown_kind for o in t.outcomes.values() if o.status == "unknown"}
            if "uncertain" in kinds:
                t.tier = "potential:uncertain"
            elif "data_gap" in kinds:
                t.tier = "potential:data_gap"
            else:
                t.tier = "strong"

    def s5(self, reviewer: Reviewer | None) -> tuple[list[ReviewItem], list[str]]:
        order = {"strong": 0, "potential:uncertain": 1, "potential:data_gap": 2}
        cands = [t for t in self.traces.values() if t.in_scope and t.tier in order]
        listable = sorted((t for t in cands if t.contact_ok), key=lambda t: (order[t.tier], t.pid))
        queue = [
            ReviewItem(
                pid=t.pid,
                tier=t.tier,
                pending_human=sorted(o.criterion_id for o in t.outcomes.values() if o.status == "pending_human"),
                uncertain=sorted(o.criterion_id for o in t.outcomes.values() if o.unknown_kind == "uncertain"),
                data_gap=sorted(
                    o.criterion_id
                    for o in t.outcomes.values()
                    if o.status == "unknown" and o.unknown_kind == "data_gap"
                ),
                department=t.department,
            )
            for t in listable
        ]
        final: list[str] = []
        for item in queue:
            t = self.traces[item.pid]
            decision = reviewer(item, t) if reviewer is not None else {"decision": "pending"}
            t.review = decision
            given = decision.get("criteria")
            for cid, status in (given if isinstance(given, dict) else {}).items():
                if cid in self.crit and status in ("pass", "fail"):
                    t.outcomes[cid] = Outcome(cid, status, "S5", hard=status == "fail", reason="S5 reviewer")
            if decision.get("decision") == "confirm":
                final.append(item.pid)
        self.log(
            "S5",
            len(queue),
            len(final),
            sum(len(q.pending_human) + len(q.uncertain) + len(q.data_gap) for q in queue),
            0,
            candidates=len(cands),
            contact_denied=len(cands) - len(listable),
            reviewed=sum(1 for q in queue if (self.traces[q.pid].review or {}).get("decision") != "pending"),
        )
        self.metrics.n_after["S5"] = len(final)
        return queue, final


def _set_hash(hashes: Sequence[str]) -> str:
    return "sha256:" + hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


def run_cascade(
    lake: Any,
    rs: Ruleset,
    cfg: CascadeConfig,
    *,
    judge: JudgeClient | None = None,
    embedder: Embedder | None = None,
    reviewer: Reviewer | None = None,
) -> CascadeResult:
    """Run S0 → S5 for one study. ``lake`` is a ``lake.client.LakeAPI`` on the pinned L5 snapshot."""
    run = _Run(lake, rs, cfg, judge, embedder)
    idx = run.s0()
    applied = run.s1(idx)
    note_crit = [c for c in rs.active() if c.class_ == "note" and c.kind in ("inclusion", "exclusion")]
    human = [c for c in rs.active() if c.class_ == "human"]
    run.metrics.note_criteria = len(note_crit)
    routes, zero = run.s2(note_crit)
    run.s2b(zero, routes)
    alive = {t.pid for t in run.alive()}
    routes = [r for r in routes if r.pid in alive]
    run.sample(routes)
    judged = run.s3(routes)
    run.s4(judged)
    run.tiers(human)
    queue, final = run.s5(reviewer)
    denom = run.metrics.n_after.get("S1", 0) * len(note_crit)
    run.metrics.llm_share = round(run.metrics.pairs_judged["S3"] / denom, 4) if denom else 0.0
    if [s.stage for s in run.stages] != list(STAGES):
        raise CascadeError(f"stages ran out of order: {[s.stage for s in run.stages]}")  # CAS-1
    return CascadeResult(
        study_id=cfg.study_id,
        ruleset=rs.id,
        ruleset_version=rs.version,
        semantics=run.semantics,
        ir_hash=run.ir_hash,
        criterion_hashes=run.hashes,
        index_dates=idx,
        traces=run.traces,
        stages=run.stages,
        metrics=run.metrics,
        queue=queue,
        final_list=final,
        applied=[c.id for c in applied],
        note_criteria=[c.id for c in note_crit],
        human_criteria=[c.id for c in human],
    )


def write_outputs(result: CascadeResult, out_dir: Path) -> dict[str, Path]:
    """Patient-level files (D3, perimeter only): traces, the review queue and the final list, plus the stage log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "traces": out_dir / "cascade_traces.jsonl",
        "queue": out_dir / "review_queue.jsonl",
        "final_list": out_dir / "final_list.json",
        "stage_log": out_dir / "cascade_log.jsonl",
        "manifest": out_dir / "cascade_manifest.json",
    }
    with paths["traces"].open("w", encoding="utf-8") as fh:
        for pid in sorted(result.traces):
            row = {"data_class": PATIENT_CLASS, **result.traces[pid].to_dict()}
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    with paths["queue"].open("w", encoding="utf-8") as fh:
        for q in result.queue:
            fh.write(json.dumps({"data_class": PATIENT_CLASS, **q.__dict__}, ensure_ascii=False, sort_keys=True) + "\n")
    paths["final_list"].write_text(
        json.dumps({"data_class": PATIENT_CLASS, "study_id": result.study_id, "pids": result.final_list}, indent=1)
        + "\n",
        encoding="utf-8",
    )
    with paths["stage_log"].open("w", encoding="utf-8") as fh:
        for s in result.manifest_block()["stages"]:
            fh.write(json.dumps(s, sort_keys=True, default=str) + "\n")
    paths["manifest"].write_text(json.dumps(result.manifest_block(), indent=1, sort_keys=True, default=str) + "\n")
    return paths


__all__ = [
    "PATIENT_CLASS",
    "UNKNOWN_KEPT",
    "CascadeConfig",
    "CascadeError",
    "CascadeResult",
    "Reviewer",
    "criterion_hashes",
    "ir_semantics",
    "ruleset_ir_hash",
    "run_cascade",
    "write_outputs",
]
