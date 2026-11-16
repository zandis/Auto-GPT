"""The filter-first cascade S0 → S1 → S2 → S2b → S3 → S4 → S5 over the lake snapshot (spec v4 §4.5).

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
import threading
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from criteria_compiler.compile_sql.overlay import safe_sql
from tb_common import lakeprobe
from tb_common.labunit import reason_of as derived_reason
from tb_common.optout import REGISTRY_SQL, RegistryState, registry_state
from tb_common.reasons import CODES as REASON_CODES
from tb_common.ruleset import Ruleset
from tb_common.timeutil import add_months, month_ends
from tb_contracts import CriterionIR

from matching import excerpts as excerpt_builder
from matching.carried import NOT_CARRIED, Carried
from matching.cascade.judge import (
    ASKING,
    Asking,
    JudgeClient,
    JudgeReply,
    expected_tokens,
    norm,
    question_digest,
    sentence_hash,
    verify_span,
)
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
from matching.cascade.s2b_semantic import (
    BatchEmbedder,
    Embedder,
    SentenceSource,
    SourceFallback,
    SourceRanking,
    ThresholdTable,
    boilerplate,
    screen,
)
from matching.coverage import UNKNOWN_CODE_SYSTEM, Coverage
from matching.excerpts import sentences
from matching.proposed import PROPOSED_FACT, SUSPECTED_DIAGNOSIS, Proposed
from matching.recorded import NO_RECORD, Recorded
from matching.stored_scores import apply_rows

PATIENT_CLASS = "D3"  # every cascade output is patient level (§7.1)
# no row of the compiled SQL's base for a scoped patient: not in this snapshot, or deceased / not yet born at every
# index date (a wrong date is common in hand-kept sheets). Never an exclusion: a person looks (D-142, review B-02)
NOT_AT_INDEX = "not alive at an index date"
UNKNOWN_KEPT = "unknown_kept"  # v1: an unknown exclusion does not exclude (FEAS D-18)
CODE_OUTSIDE_LIST = "code_outside_list"  # D-113: coded inside a grouper's family, not in its list: kept, unknown
EXCERPT_TOKENS = 2500  # fits beside the judge prompt and its answer on every profile (8k and up, T-603)
EXCLUSION_POWER_PRIOR = 0.5  # CAS-3 prior until the criterion library has site history

Reviewer = Callable[[ReviewItem, PatientTrace], dict[str, Any]]


FILTERED = ("structured", "mixed")  # classes whose logic the compiled SQL decides (D-32, D-98)
JUDGED = ("note", "mixed")  # classes whose note_question the judge may be asked (mixed: when the codes were silent)


class CascadeError(RuntimeError):
    pass


class LakeLike:
    """The lake surface the cascade needs (``lake.client.LakeAPI``)."""

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        raise NotImplementedError


def s1_rows(environ: Mapping[str, str] | None = None) -> int:
    """``TB_CASCADE_S1_ROWS``: the rows (patients times index dates) one S1 query may carry (D-748). A whole number
    above 0, else the setting is refused."""
    import os

    from tb_common.config import DECLARED

    env = os.environ if environ is None else environ
    raw = env.get("TB_CASCADE_S1_ROWS") or DECLARED["TB_CASCADE_S1_ROWS"].default
    if not raw.isascii() or not raw.isdigit() or int(raw) <= 0:
        raise CascadeError(f"TB_CASCADE_S1_ROWS={raw!r}: give a whole number of rows above 0")
    return int(raw)


@dataclass
class CascadeConfig:
    study_id: str
    run_date: date
    lookback_months: int = 36
    index_mode: str = "month_ends"  # month_ends (FEAS population, v1) | single (screening at run_date)
    notes_class: str = "D0"  # class label of note text sent to the gateway (eval/DATASETS.yaml for D0 datasets)
    purpose: str = "feasibility"
    step_id: str = ""
    # CAS-4: the budget of S3 pairs. None: no budget (T-689, D-456: SCREEN's default is the population's own pairs)
    max_llm_items: int | None = 2000
    # T-694 part 3: S2 and S2b run on this many patients at a time, reading only their notes; None: all at once. The
    # statuses, metrics and stage logs are the same for any size
    note_batch: int | None = None
    # model calls in flight at once (S3, S4): the serving profile's sequences (vLLM --max-num-seqs); 1 = one by one.
    # Each patient's criteria stay in order (CAS-3 stops at a hard fail); patients run side by side (D-142, A-07)
    llm_concurrency: int = 1
    # a token budget beside the pair budget, only when a caller sets one. It was a hidden 10,000,000 that stopped a
    # job before its pair budget and under that budget's name (T-689, D-456; scale review F-16)
    max_tokens: int | None = None
    zero_hit_allowed: frozenset[str] = frozenset()  # CAS-13 certified criteria, read from the registry
    semantics: Semantics | None = None  # None: from the IR version (CAS-19)
    exclusion_power: Mapping[str, float] = field(default_factory=dict)  # canonical hash -> pooled not_met share
    confidence_floor: float = 0.75  # below: abstained (not hard, CAS-7)
    thresholds: ThresholdTable = field(default_factory=ThresholdTable)
    lexicon: Mapping[str, Sequence[str]] = field(default_factory=dict)  # approved terms per criterion id
    # NEW-LLM-2 (LLM-002): SCREEN sets it. A note criterion with no lexicon term and only a non-semantic embedder (the
    # hash stub) is "not evaluated" instead of judged on the first sentences of each note; counted in no_retrieval
    require_retrieval: bool = False
    language: str = "zh-TW"  # language stratum of the site notes (S2b thresholds)
    sample_per_stratum: int | None = None  # CAS-8: ≤ 200 in feasibility runs; None screens everyone
    # NEW-B-47 (D-748): the rows (patients times index dates) one S1 query may carry; None: TB_CASCADE_S1_ROWS
    s1_rows: int | None = None
    seed: int = 20261025
    snapshot: str | None = None
    # D-442: the stored derived rows (``tb_common.derived_store.stored_read``, None while the flag is off)
    stored: Any = None
    # D-103 (SCREEN runs the cascade): the population is given by the caller instead of POP_SQL (the practitioner /
    # appointment scope of a screening run); a note ``fail`` is soft (review, never exclusion) when ``note_block`` is
    # False (D-95/D-97 single-model fallback); zero-hit pairs below the S2b threshold go to the judge instead of
    # taking absence semantics when ``absence_semantics`` is False (screening spends the tokens, feasibility saves
    # them).
    population: Sequence[str] | None = None
    note_block: bool = True
    absence_semantics: bool = True
    # D-904 (lane G's review): False skips S2b for a zero-hit pair the judge reads anyway (no absence semantics, not
    # the index sweep) when every note of its window fits the excerpt budget: the ranking would change no prompt
    s2b_when_fits: bool = True
    # T-708 (D-477): the consent state of S0, given by the caller's decision context (the orchestrator). None: a
    # caller with no job (a tool) and S0 reads the lake by the same rule (``tb_common.optout.registry_state``).
    registry: Callable[[], RegistryState | None] | None = None


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
            "context_unknown": dict(sorted(m.context_unknown.items())),
            "no_retrieval": dict(sorted(m.no_retrieval.items())),
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
    from orchestrator.scenarios.terms import keywords, source_words

    text = f"{c.text} {c.note_question or ''}"
    return [*source_words(text), *keywords(text, limit=24)]


# ------------------------------------------------------------------------------------------------ the run
POP_SQL = """
SELECT p.pid,
       (SELECT arg_max(e2.dept, e2.start) FROM encounter e2 WHERE e2.pid = p.pid) AS dept
FROM patient p
WHERE EXISTS (SELECT 1 FROM encounter e WHERE e.pid = p.pid
              AND CAST(e.start AS DATE) BETWEEN CAST($1 AS DATE) AND CAST($2 AS DATE))
ORDER BY p.pid
"""
#: the consent query of S0: the registry's one rule (T-708, D-477); the name the stand-in lakes of the tests know
CONSENT_SQL = REGISTRY_SQL


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
    # the sentences as the lexicon matches them (NFKC, folded): once per note, not once per criterion and patient
    low: list[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.low = [norm(s).lower() for s in self.sents]


@dataclass
class _Route:
    """A note pair on its way to S3."""

    pid: str
    cid: str
    excerpts: list[dict[str, Any]]
    sentence_set: str
    via: Stage  # S2 (lexicon hit) or S2b (above threshold)
    margin: float = 0.0
    left_out: int = 0  # evidence notes the excerpt budget did not show in full (D-276): a "not met" is then not final


class _Run:
    def __init__(
        self,
        lake: LakeLike,
        rs: Ruleset,
        cfg: CascadeConfig,
        judge: JudgeClient | None,
        embedder: Embedder | None,
        s2b_source: SentenceSource | None = None,
    ) -> None:
        self.lake = lake
        self.s2b_source = s2b_source  # T-203b (D-449): stored vectors behind the flag vec.s2b; None = on the fly
        self.rs = rs
        self.cfg = cfg
        self.judge = judge
        self._budgets: dict[str, int] = {}  # criterion id -> the excerpt budget of its judge prompt (budget_of)
        self.embedder = BatchEmbedder(embedder) if embedder is not None else None
        self.hashes = criterion_hashes(rs)
        self.ir_hash = ruleset_ir_hash(self.hashes)
        self.semantics: Semantics = cfg.semantics or ir_semantics(rs)
        self.crit = {c.id: c for c in rs.active()}
        self.metrics = CascadeMetrics()
        self.stages: list[StageLog] = []
        self.traces: dict[str, PatientTrace] = {}
        self.cache: dict[str, JudgeReply] = {}
        self._lock = threading.RLock()  # budget, cache and counters when S3 / S4 run patients side by side
        self.items = 0
        self.tokens = 0
        self.coverage = Coverage()  # rows in a code system nobody can read (F-10, D-130); loaded at S1
        self._s2_excluded = 0  # patients S2 excluded on a certified zero hit, summed over the batches (T-694 part 3)
        self.carried = Carried()  # the code systems the site's rows carry (F11, D-795); loaded at S1
        self.recorded = Recorded()  # the kinds of coded record each patient has at all (D-914); loaded at S1
        self._uncarried_index: set[str] = set()  # index conditions whose list no row can carry: absence never excludes
        self.coded = True  # whether S1 applied a coded criterion (D-788); set at S1
        self.proposed = Proposed()  # facts read from a chart, not yet confirmed (D-135); loaded at S1

    def log(self, stage: Stage, p_in: int, p_out: int, q_in: int, q_out: int, **detail: Any) -> None:
        self.stages.append(StageLog(stage, p_in, p_out, q_in, q_out, PATIENT_CLASS, self.ir_hash, dict(detail)))

    def _semantic(self) -> bool:
        """Can S2b find a sentence by meaning? Not with no embedder or the hash stub (NEW-LLM-2); yes with stored
        vectors (the flag vec.s2b, D-449: the embed service's model, known per query)."""
        if self.s2b_source is not None:
            return True
        return self.embedder is not None and not str(self.embedder.model).startswith("hash")

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
        if cfg.population is not None:
            rows = [{"pid": p, "dept": None} for p in sorted(set(cfg.population))]
            population = f"{len(rows)} patients given by the caller (screening scope)"
        else:
            rows = self.lake.query(POP_SQL, [pop_from.isoformat(), idx[-1].isoformat()], cfg.snapshot).to_pylist()
            population = f"≥1 encounter {pop_from.isoformat()}…{idx[-1].isoformat()}"
        # T-708 (D-477, review M2): one consent rule on every path. The patient's latest statement on or before the
        # index date decides, an undated one is the oldest, one entered in error is none, ties of a day fail closed
        # (``tb_common.optout.registry_rule``). Only a lake that has no consent table at all has no opt-outs to
        # apply; any other failure stops the run, because skipping opt-outs would list patients who said no (D-127,
        # review F-04)
        state = (
            cfg.registry() if cfg.registry is not None else registry_state(self.lake, cfg.snapshot, idx[-1].isoformat())
        )
        refused = state.refused if state is not None else frozenset()
        no_contact = state.no_contact if state is not None else frozenset()
        opted_out = 0
        for r in rows:
            pid = str(r["pid"])
            t = PatientTrace(pid=pid, index_date=idx[-1], department=r.get("dept"))
            if pid in refused:
                t.in_scope, t.scope_reason = False, "research-use opt-out (FHIR Consent rejected)"
                opted_out += 1
            t.contact_ok = pid not in no_contact
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
            population=population,
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
            if c.class_ in FILTERED and c.kind in ("inclusion", "exclusion") and f'"C_{c.id}"' in self.rs.sql
        ]

    def _pass(self, c: CriterionIR, v: bool | None) -> bool:
        if c.kind == "inclusion":
            return v is True
        return v is not True

    def _s1_rows(self, idx: list[date], scope: list[str]) -> list[dict[str, Any]]:
        """NEW-B-47 (D-748): the ruleset's SQL over the scope in batches of patients: its rows are per patient and
        index date, so the batches change no row; the lake holds one batch, not the whole scope, at a time. The
        lake's memory grows with the rows the query carries (patients times index dates), so a batch is as many
        patients as fit the rows a query may carry."""
        rows_ = s1_rows() if self.cfg.s1_rows is None else self.cfg.s1_rows
        if rows_ <= 0:
            raise CascadeError(f"s1_rows={rows_}: give a whole number of rows above 0")
        size = max(1, rows_ // max(1, len(idx)))
        dates_ = [d.isoformat() for d in idx]
        sql = safe_sql(self.rs)
        rows: list[dict[str, Any]] = []
        for start in range(0, max(len(scope), 1), size):
            rows += self.lake.query(sql, [dates_, scope[start : start + size]], self.cfg.snapshot).to_pylist()
        return rows

    def s1(self, idx: list[date]) -> list[CriterionIR]:
        applied = self.applied()
        scope = [t.pid for t in self.traces.values() if t.in_scope]
        # A-NOTES-ONLY (D-788): a ruleset with no coded criterion is screened (lane G's public sets): the SQL still
        # lists each in-scope patient alive at each index date, every patient passes S1 at its latest one, and the
        # notes decide. Such a run needs a pair budget, since every patient goes to the models. D-909 (red of lane G's
        # run, 2026-11-16): a ruleset where nothing decides (every criterion a person's) is an answer, not an error:
        # S0 and S1 still scope the patients, nobody is judged, and every patient in scope goes to review
        self.coded = bool(applied)
        if not applied:
            if not any(c.class_ in JUDGED and c.kind in ("inclusion", "exclusion") for c in self.rs.active()):
                self.metrics.nothing_decides = True
            elif self.cfg.max_llm_items is None:
                raise CascadeError(
                    f"ruleset {self.rs.id} has no coded criterion, so every patient goes to the models: set max_pairs"
                )
        # D-275: SQL approved before the unit / sex / order-date rules runs guarded by them (unknown on a difference)
        table = self._s1_rows(idx, scope)
        # D-442: the stored-row read, the same function as the v1 engine's (only while the flag is on: cfg.stored)
        apply_rows(table, applied, self.cfg.stored, self.cfg.snapshot, getattr(self.rs.manifest, "derived_pins", None))
        self.coverage = Coverage.for_criteria(self.lake, applied, scope, self.cfg.snapshot, self.rs.valuesets)
        self.carried = Carried.for_criteria(self.lake, applied, self.cfg.snapshot)
        self.recorded = Recorded.for_criteria(self.lake, applied, scope, self.cfg.snapshot)
        self.proposed = Proposed.for_criteria(self.lake, applied, scope, self.cfg.snapshot, self.rs.valuesets)
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
                    if not self._pass(c, row.get(f"C_{c.id}")) and not (c.class_ == "mixed" and c.kind == "inclusion"):
                        break
                    depth += 1
                if depth >= best_depth:  # latest date on ties
                    best, best_depth = row, depth
            if best is None:  # not alive at any index date (deceased before the lookback's first month-end)
                t.in_scope, t.scope_reason = False, NOT_AT_INDEX
                continue
            t.index_date = best["index_date"]
            applied_ids = {a.id for a in applied}
            for c in self.rs.active():
                if c.class_ not in FILTERED or c.kind not in ("inclusion", "exclusion"):
                    continue
                if c.id not in applied_ids:
                    if c.class_ == "mixed":  # D-98: logic did not compile, the notes decide
                        continue
                    t.outcomes[c.id] = Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="not compiled")
                    continue
                if c.class_ == "mixed" and best.get(f"C_{c.id}") is not True:
                    continue  # D-98: codes silent (false or null) → the notes decide at S2/S3
                t.outcomes[c.id] = self._s1_outcome(c, best)
            first_fail = next((c.id for c in applied if c.id in t.outcomes and t.outcomes[c.id].hard), None)
            if first_fail:
                self.exclude(t, "S1", first_fail)
        n_scope = self.metrics.n_scope = sum(1 for t in self.traces.values() if t.in_scope)
        self.metrics.n_after["S0"] = n_scope
        self.stages[0].patients_out = n_scope
        alive = self.alive()
        n_struct = len(applied)
        n_prop = sum(
            1 for t in alive if any(o.reason in (PROPOSED_FACT, SUSPECTED_DIAGNOSIS) for o in t.outcomes.values())
        )
        self.log(
            "S1",
            n_scope,
            len(alive),
            n_scope * n_struct,
            sum(1 for t in alive for c in applied if c.id in t.outcomes and t.outcomes[c.id].status != "fail"),
            semantics=self.semantics,
            index_dates=len(idx),
            deferred_index=sum(1 for t in alive for o in t.outcomes.values() if o.reason == "index_absent"),
            unknown_code_system=sum(
                1 for t in alive if any(o.reason == UNKNOWN_CODE_SYSTEM for o in t.outcomes.values())
            ),
            **({"proposed_fact": n_prop} if n_prop else {}),  # D-135, only when a site has proposed facts
        )
        self.metrics.n_after["S1"] = len(alive)
        return applied

    def _s1_outcome(self, c: CriterionIR, row: Mapping[str, Any]) -> Outcome:
        """The S1 outcome of one structured criterion, with D-135's rule on top: a proposed fact (read from a
        chart, not confirmed) that could change the coded answer makes it unknown. The patient needs information; the
        fact never excludes and never counts as met."""
        # F11 (D-795): a list in a system no row of the domain carries cannot answer: a person looks, never excluded.
        # The study's own condition keeps its note sweep (the notes may still find it); its absence never excludes
        doubt = bool(self.carried.doubt(c, self.rs.valuesets, row.get(f"C_{c.id}")))
        if doubt and is_index_criterion(c):
            self._uncarried_index.add(c.id)
            doubt = False
        out = self._s1_coded(c, row)
        if out.reason == UNKNOWN_CODE_SYSTEM:
            return out
        fids = self.proposed.refs(c, str(row["pid"]), row["index_date"], row.get(f"C_{c.id}"))
        if not fids and doubt:  # a proposed fact, when there is one, says more to the person who looks
            return Outcome(c.id, "pass" if c.kind == "exclusion" else "unknown", "S1", unknown_kind="data_gap",
                           reason=NOT_CARRIED)  # fmt: skip
        # D-914: a patient with no coded record of the atom's kind at all: their record says nothing either way
        if not fids and not is_index_criterion(c) and self.recorded.doubt(c, str(row["pid"]), row.get(f"C_{c.id}")):
            return Outcome(c.id, "pass" if c.kind == "exclusion" else "unknown", "S1", unknown_kind="data_gap",
                           reason=NO_RECORD)  # fmt: skip
        if not fids:
            return out
        ev = [{"source": "lake", "record": x.split("|")[0], "date": x.split("|")[1] if "|" in x else None,
               "lineage": f"snapshot:{self.cfg.snapshot or ''}", "index_date": row["index_date"].isoformat()}
              for x in fids[:20]]  # fmt: skip
        why = self.proposed.reason(str(row["pid"]), fids)  # proposed_fact, or suspected_diagnosis (D-142)
        if c.kind == "exclusion":  # an exclusion left unknown keeps the patient (D-18); the list says unknown
            return Outcome(c.id, "pass", "S1", unknown_kind="data_gap", evidence=ev, reason=why)
        return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", evidence=ev, reason=why)

    def _s1_coded(self, c: CriterionIR, row: Mapping[str, Any]) -> Outcome:
        v = row.get(f"C_{c.id}")
        # D-149: a score with no value carries its reason (missing input, unit) in the evidence, not a record
        why, refs = derived_reason(x for x in str(row.get(f"E_{c.id}") or "").split(";") if x)
        ev = [
            {
                "source": "lake",
                "record": x.split("|")[0],
                "date": x.split("|")[1] if "|" in x else None,
                "lineage": f"snapshot:{self.cfg.snapshot or ''}",
                "index_date": row["index_date"].isoformat(),
            }
            for x in refs
        ]
        if v is None and why is not None:
            return Outcome(c.id, "pass" if c.kind == "exclusion" else "unknown", "S1", unknown_kind="data_gap",
                           evidence=ev, reason=why)  # fmt: skip
        if c.kind == "exclusion":
            if v is True:
                return Outcome(c.id, "fail", "S1", hard=True, stratum=STRATUM_S1, evidence=ev, reason="matching record")
            if v is None:
                why = CODE_OUTSIDE_LIST if ev else UNKNOWN_KEPT
                return Outcome(c.id, "pass", "S1", unknown_kind="data_gap", evidence=ev, reason=why)
            return Outcome(c.id, "pass", "S1", evidence=ev)
        if v is True:
            return Outcome(c.id, "pass", "S1", evidence=ev)
        if v is None and ev:  # D-113: a record coded inside the grouper's family but outside its code list
            return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", evidence=ev, reason=CODE_OUTSIDE_LIST)
        if v is None:
            return Outcome(c.id, "unknown", "S1", unknown_kind="data_gap", reason="no value in the window")
        # inclusion FALSE. F-10 (D-130): with a record in the atom's window coded in a system no ValueSet can read,
        # FALSE only means "not among the codes we can read": unknown, a person checks, never a silent exclusion
        gap = self.coverage.refs(c, str(row["pid"]), row["index_date"])
        if gap:
            return Outcome(
                c.id,
                "unknown",
                "S1",
                unknown_kind="data_gap",
                evidence=[
                    {
                        "source": "lake",
                        "record": x.split("|")[0],
                        "date": x.split("|")[1] if "|" in x else None,
                        "lineage": f"snapshot:{self.cfg.snapshot or ''}",
                        "index_date": row["index_date"].isoformat(),
                    }
                    for x in gap[:20]
                ],
                reason=UNKNOWN_CODE_SYSTEM,
            )
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
        # a lake without a note table (MIMIC demo): every note pair is a data gap. Whether it has none is asked of
        # the lake, not read out of the failure's text (D-650); any other failure stops the run instead of turning
        # every note criterion into "unknown" without saying why (D-127, review F-04)
        params = [pids, lo.isoformat(), hi.isoformat()]
        rows = lakeprobe.rows_or_no_table(self.lake, NOTES_SQL, params, self.cfg.snapshot, "document") or []
        out: dict[str, list[_Note]] = {}
        for r in rows:
            text = str(r["text"] or "")
            out.setdefault(str(r["pid"]), []).append(
                _Note(str(r["did"]), r["d"], str(r["type"] or "note"), text, sentences(text))
            )
        return out

    @staticmethod
    def excerpts(notes: list[_Note], keep: Mapping[str, Collection[str]]) -> list[dict[str, Any]]:
        """The window's notes for one judge prompt, the evidence notes first, within the token budget.

        A note that does not fit whole is cut around its evidence sentences (at most half the budget), and a note
        that no longer fits is skipped, not the end of the search: one long note used to stop the loop and hide
        every older note, so the model got nothing at all (D-142, review A-06)."""
        return _Run.excerpt_set(notes, keep)[0]

    @staticmethod
    def excerpt_set(
        notes: list[_Note], keep: Mapping[str, Collection[str]], budget: int | None = None, ranked: bool = False
    ) -> tuple[list[dict[str, Any]], int]:
        """:meth:`excerpts`, and how many of the window's notes are not shown in full: the one excerpt builder
        (:func:`matching.excerpts.build`, T-710, D-479). ``notes``: every note of the criterion's window; ``keep``:
        the evidence sentences per note (lexicon hits at S2, the top sentences at S2b): read first, and what a cut
        note is cut around. Both models read this one set, so with any window note left out their agreement on
        "not met" is not final (D-276, review S-10; :meth:`_map`). ``budget``: the models' context
        (:meth:`budget_of`); :data:`EXCERPT_TOKENS` when not given. ``ranked``: ``keep`` is in the ranking's order
        (S2b's top sentences, best first)."""
        window = [excerpt_builder.Note(n.did, n.d, n.type, n.text, n.sents) for n in notes]
        size = EXCERPT_TOKENS if budget is None else budget
        # sized with the count the prompt is sized with (each note with its date and type as JSON), not the text
        # alone: hundreds of short notes passed as all shown and the gateway refused the call (review of D-645)
        got = excerpt_builder.build(window, keep, size, tokens=_tokens, ranked=ranked)
        return got.shown, got.left_out

    def budget_of(self, c: CriterionIR, index_date: date) -> int:
        """Tokens of notes one judge prompt for ``c`` may hold: what the judge's and the verifier's context leave
        (T-603, OD-10; the judge tells), kept for the run once told. SCR-18: when the judge cannot tell (a failed
        context lookup) this prompt gets :data:`EXCERPT_TOKENS` and the next one asks again, never the default for
        the rest of the run; the prompt is counted in ``metrics.context_unknown``. A judge without
        ``excerpt_budget`` (a test's) has the default, kept. A told 0 is kept (the prompt leaves no room); a judge
        that raises raises here, as before."""
        with self._lock:
            if c.id in self._budgets:
                return self._budgets[c.id]
        fn = getattr(self.judge, "excerpt_budget", None)
        if not callable(fn):
            with self._lock:
                self._budgets[c.id] = EXCERPT_TOKENS
            return EXCERPT_TOKENS
        room = fn(c, index_date)
        with self._lock:
            if isinstance(room, int) and not isinstance(room, bool):
                self._budgets[c.id] = room
                return room
            self.metrics.context_unknown[c.id] = self.metrics.context_unknown.get(c.id, 0) + 1
        return EXCERPT_TOKENS

    # -------------------------------------------------------------------------------------------- S2 / S2b
    def s2(
        self, note_crit: list[CriterionIR], pids: Collection[str] | None = None, record: bool = True
    ) -> tuple[list[_Route], list[tuple[str, str, list[_Note]]]]:
        """S2 over the alive patients, or those of ``pids`` (a batch, T-694 part 3); ``record``: write the stage log
        (a batched run writes it once, from the totals)."""
        alive = [t for t in self.alive() if pids is None or t.pid in pids]
        rescue = [t for t in alive if any(o.reason == "index_absent" for o in t.outcomes.values())]
        notes = self.notes([t.pid for t in alive])
        terms_of: dict[str, list[str]] = {}

        def terms(c: CriterionIR) -> list[str]:  # the lexicon keys of a criterion, worked out once per run
            if c.id not in terms_of:
                terms_of[c.id] = [norm(x).lower() for x in lexicon_terms(c, self.cfg.lexicon)]
            return terms_of[c.id]

        routes: list[_Route] = []
        zero: list[tuple[str, str, list[_Note]]] = []
        excluded_here = 0
        for t in alive:
            pnotes = notes.get(t.pid, [])
            for c in note_crit:
                if c.id in t.outcomes and t.outcomes[c.id].stage == "S1":
                    continue  # D-98 mixed: the codes settled it
                lo, hi = window_of(c, t.index_date)
                win = [n for n in pnotes if lo <= n.d <= hi]
                if not win:
                    self.metrics.pairs_s2_no_notes += 1
                    t.outcomes[c.id] = Outcome(
                        c.id, "unknown", "S2", unknown_kind="data_gap", reason="no note in window"
                    )
                    continue
                keys = terms(c)
                if not keys and self.cfg.require_retrieval and not self._semantic():
                    self.metrics.no_retrieval[c.id] = self.metrics.no_retrieval.get(c.id, 0) + 1
                    t.outcomes[c.id] = Outcome(
                        c.id,
                        "unknown",
                        "S2",
                        unknown_kind="uncertain",
                        reason="not evaluated: no lexicon term and no semantic embedder for this criterion",
                    )
                    continue
                hits = [
                    (n, s) for n in win for s, low in zip(n.sents, n.low, strict=True) if any(k in low for k in keys)
                ]
                if hits:
                    self.metrics.pairs_s2_hit += 1
                    sset = sorted({sentence_hash(s) for _, s in hits})
                    found: dict[str, set[str]] = {}
                    for n, s in hits:
                        found.setdefault(n.did, set()).add(s)
                    shown, left = self.excerpt_set(win, found, self.budget_of(c, t.index_date))
                    routes.append(_Route(t.pid, c.id, shown, _set_hash(sset), "S2", left_out=left))
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
            keys = terms(self.crit[cid])
            pnotes = notes.get(t.pid, [])
            hit = next(
                (s for n in pnotes for s, low in zip(n.sents, n.low, strict=True) if any(k in low for k in keys)), None
            )
            if hit is not None:
                self._rescue(t, cid, "S2", hit)
            else:
                zero.append((t.pid, f"index:{cid}", pnotes))
        self._s2_excluded += excluded_here
        if record:
            self._log_s2(len(alive), len(note_crit), len(routes) + len(zero))
        return routes, zero

    def _log_s2(self, p_in: int, n_crit: int, q_out: int) -> None:
        alive_after = self.alive()
        self.log(
            "S2",
            p_in,
            len(alive_after),
            p_in * n_crit,
            q_out,
            hits=self.metrics.pairs_s2_hit,
            zero_hit=self.metrics.pairs_s2_zero_hit,
            no_notes=self.metrics.pairs_s2_no_notes,
            excluded_zero_hit=self._s2_excluded,
        )
        self.metrics.n_after["S2"] = len(alive_after)

    def _rescue(self, t: PatientTrace, cid: str, stage: Stage, sentence: str) -> None:
        o = t.outcomes[cid]
        o.reason = "index rescued"
        o.rescue = {"stage": stage, "sentence_hash": sentence_hash(sentence)}
        self.metrics.rescued += 1

    def s2b(self, zero: list[tuple[str, str, list[_Note]]], routes: list[_Route], record: bool = True) -> None:
        alive_before = len(self.alive())
        n_in = len(zero)
        for pid, key, win in zero:
            t = self.traces[pid]
            index_sweep = key.startswith("index:")
            cid = key.split(":", 1)[1] if index_sweep else key
            c = self.crit[cid]
            sents = [(n, s) for n in win for s in n.sents]
            if sents and not index_sweep and not self.cfg.absence_semantics and not self.cfg.s2b_when_fits:
                shown, left = self.excerpt_set(win, {}, self.budget_of(c, t.index_date))
                if left == sum(1 for n in win if not n.text.strip()):  # every note with text shown in full
                    self.metrics.pairs_s2b_above += 1
                    self.metrics.s2b_skipped_fit += 1
                    sset = sorted({sentence_hash(x) for _, x in sents})
                    routes.append(_Route(pid, cid, shown, _set_hash(sset), "S2b", 0.0, left_out=left))
                    continue
            query = " ".join([c.note_question or c.text, *lexicon_terms(c, self.cfg.lexicon)])
            thr = self.cfg.thresholds.get(c.kind, self.cfg.language)
            stored = self._from_store(t, query, win, len(sents)) if sents else None
            if stored is not None:
                # the threshold is fitted to on-the-fly vectors (D-429): a stored score never decides a rescue
                # (index sweep) until the refit after G1; it only picks the excerpts (D-449)
                res_above, best, top = False, stored.best, [i for i, _ in stored.top]
            elif self.embedder is None:
                res_above, best, top = True, 1.0, list(range(min(5, len(sents))))  # no S2b: never absence
            else:
                skip = boilerplate([n.sents for n in win])  # D-905: recurring template lines are not embedded
                idx = [i for i, (_, x) in enumerate(sents) if x.strip() not in skip] or list(range(len(sents)))
                res = screen(self.embedder, query, [sents[i][1] for i in idx], thr)
                res_above, best, top = res.above, res.best, [idx[i] for i, _ in res.top]
            held = (
                index_sweep
                and res_above
                and stored is None
                and self.embedder is not None
                and thr.source == "public_prior"
                and not str(self.embedder.model).startswith("hash")
            )
            if held:
                # NEW-LLM-2: the placeholder threshold was set for the hash stub; a real model's similarities clear it
                # almost always, so its score above it never rescues an index condition until the refit (as D-449 for
                # stored vectors), and a rescue held back is never an absence either: a person looks. A score below it
                # keeps its earlier path
                res_above = False
            if index_sweep:
                if res_above and sents:
                    self._rescue(t, cid, "S2b", sents[top[0]][1])
                elif cid in self._uncarried_index:  # F11 (D-795): no code could be there, so absence says nothing
                    t.outcomes[
                        cid
                    ].reason = (
                        f"index condition not found in the notes, its list's codes not carried ({NOT_CARRIED}); review"
                    )
                elif held or not self.cfg.absence_semantics:
                    t.outcomes[cid].reason = "index condition not coded and not found in the notes; review"
                else:
                    o = t.outcomes[cid]
                    o.status, o.hard, o.stratum, o.stage = "fail", True, STRATUM_INDEX, "S2b"
                    o.unknown_kind, o.reason = None, "index condition absent: no code, no S2 or S2b mention"
                    self.exclude(t, "S2b", cid)
                continue
            if res_above or (not self.cfg.absence_semantics and sents):
                self.metrics.pairs_s2b_above += 1
                keep: dict[str, set[str]] = {}
                for i in top:
                    keep.setdefault(sents[i][0].did, set()).add(sents[i][1])
                sset = sorted({sentence_hash(sents[i][1]) for i in top})
                # T-710 (D-479): every window note is offered to the builder and each one not shown in full counts as
                # left out, on either ranking (the rule PR #275 added here for S2b alone, D-449)
                shown, left = self.excerpt_set(win, keep, self.budget_of(c, t.index_date), ranked=True)
                routes.append(_Route(pid, cid, shown, _set_hash(sset), "S2b", best - thr.value, left_out=left))
                continue
            self.metrics.pairs_s2b_below += 1
            detail = {"best": round(best, 4), "threshold": thr.value, "threshold_source": thr.source}
            if c.kind == "inclusion":
                # An inclusion criterion the semantic pre-filter finds no mention of is NOT an exclusion: the
                # threshold is a public-prior placeholder until the LTT fit exists (independent review 2026-10-27,
                # finding 6; D-90). The pair goes to the review queue as ``unknown`` and the patient stays in.
                t.outcomes[cid] = Outcome(
                    cid,
                    "unknown",
                    "S2b",
                    unknown_kind="uncertain",
                    stratum=STRATUM_S2B,
                    evidence=[detail],
                    reason="S2b below: no mention found; review (never an exclusion)",
                )
            else:
                t.outcomes[cid] = Outcome(cid, "pass", "S2b", evidence=[detail], reason="S2b below: absence")
        self.metrics.s2b_embed_batches = self.embedder.batches if self.embedder else 0
        if record:
            self._log_s2b(alive_before, n_in)

    def _log_s2b(self, alive_before: int, n_in: int) -> None:
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
            **self._source_detail(),
        )
        self.metrics.n_after["S2b"] = len(alive)

    def _from_store(self, t: PatientTrace, query: str, win: list[_Note], n_sents: int) -> SourceRanking | None:
        """T-203b (D-449): the pair's ranking from the stored vectors, or None for the on-the-fly path.

        Asked only with absence semantics off (screening): there S2b picks the excerpts and the index rescue and
        never decides an exclusion, and the threshold stays the one fitted to on-the-fly vectors (D-429: the refit
        follows G1). Anything the source cannot answer, any error, and any answer that does not index the window's
        sentences is a fallback: the pair goes the on-the-fly way and the patient's trace records it."""
        src = self.s2b_source
        if src is None:
            return None
        rec = t.s2b_source
        if rec is None:
            rec = t.s2b_source = {"vec_pairs": 0, "fallback_pairs": 0, "vec_model": None, "fallback": []}
        rec["on_the_fly_model"] = self.embedder.model if self.embedder else None
        got: SourceRanking | SourceFallback
        if self.cfg.absence_semantics:
            got = SourceFallback("absence semantics on: the S2b threshold is fitted to on-the-fly vectors (D-429)")
        else:
            try:
                got = src.rank(t.pid, query, win, 5)
            except Exception as exc:  # a store or lake that fails is a fallback, never a lost pair
                got = SourceFallback(f"vector store error: {type(exc).__name__}")
        if isinstance(got, SourceRanking):
            if not got.top or any(not 0 <= i < n_sents for i, _ in got.top):
                got = SourceFallback("the stored ranking does not index the window's sentences")
            elif rec["vec_model"] not in (None, got.model):
                got = SourceFallback(f"vectors of a second model ({got.model}) in one patient's run: refused")
        if isinstance(got, SourceFallback):
            rec["fallback_pairs"] += 1
            if got.reason not in rec["fallback"]:
                rec["fallback"] = sorted([*rec["fallback"], got.reason])
            return None
        rec["vec_pairs"] += 1
        rec["vec_model"] = got.model
        return got

    def _source_detail(self) -> dict[str, Any]:
        """The S2b stage log's account of the stored-vector source; nothing when none was given (flag off)."""
        if self.s2b_source is None:
            return {}
        recs = [t.s2b_source for t in self.traces.values() if t.s2b_source]
        models = sorted({str(r["vec_model"]) for r in recs if r["vec_model"]})
        return {
            "vec_pairs": sum(int(r["vec_pairs"]) for r in recs),
            "vec_fallback_pairs": sum(int(r["fallback_pairs"]) for r in recs),
            "vec_fallback_patients": sum(1 for r in recs if r["fallback_pairs"]),
            "vec_model": ",".join(models) or None,
        }

    def note_stage(self, note_crit: list[CriterionIR]) -> list[_Route]:
        """S2 then S2b (T-694 part 3). With ``cfg.note_batch`` both run on that many alive patients at a time, each
        batch reading only its patients' notes, which are let go after it; the stage logs are written once from the
        totals and the routes are put in the order of an unbatched run, so the statuses, the metrics and a pair budget
        are the same for any batch size."""
        size = self.cfg.note_batch
        if size is None:
            routes, zero = self.s2(note_crit)
            self.s2b(zero, routes)
            return routes
        if size < 1:
            raise CascadeError("note_batch must be at least 1 patient")
        order = [t.pid for t in self.alive()]
        rank = {p: i for i, p in enumerate(order)}
        crit_rank = {c.id: i for i, c in enumerate(note_crit)}
        s2_routes: list[_Route] = []
        s2b_routes: list[_Route] = []
        n_zero = n_s2_out = 0
        after_s2: set[str] = set(order)
        for start in range(0, len(order), size):
            batch = set(order[start : start + size])
            routes, zero = self.s2(note_crit, batch, record=False)
            n_s2_out += len(routes) + len(zero)
            n_zero += len(zero)
            after_s2 -= {p for p in batch if self.traces[p].exit_stage is not None}
            s2_routes += routes
            before = len(routes)
            self.s2b(zero, routes, record=False)
            s2b_routes += routes[before:]
        # the stage logs of an unbatched run: S2 counted before any S2b exclusion, S2b from S2's survivors
        exited_s2b = {p for p in order if self.traces[p].exit_stage == "S2b"}
        s2b_back = {p: self.traces[p].exit_stage for p in exited_s2b}
        for p in exited_s2b:  # S2's count is taken as if S2b had not run yet
            self.traces[p].exit_stage = None
        self._log_s2(len(order), len(note_crit), n_s2_out)
        for p, stage in s2b_back.items():
            self.traces[p].exit_stage = stage
        self._log_s2b(len(after_s2), n_zero)
        key = lambda r: (rank.get(r.pid, len(rank)), crit_rank.get(r.cid, len(crit_rank)))  # noqa: E731
        return sorted(s2_routes, key=key) + sorted(s2b_routes, key=key)

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
        # D-907: the canonical hash drops the criterion's text, so two criteria with one note question and structure
        # would share an answer whenever their sentence sets meet (always on D-904's whole-window path); the text's
        # hash keeps one criterion's answer from being read as another's
        text = hashlib.sha256(c.text.encode("utf-8")).hexdigest()
        key = json.dumps([r.pid, self.hashes[r.cid], text, r.sentence_set, role, lo.isoformat(), hi.isoformat()])
        with self._lock:
            if key in self.cache:
                self.metrics.cache_hits += 1
                return self.cache[key], True
        # D-908: the store below the judge keys and erases by these; an audit sample (CAS-8) is always asked live
        question = question_digest(c.text, c.note_question or c.text, t.index_date.isoformat(), list(r.excerpts))
        asking = ASKING.set(Asking(r.pid, self.hashes[r.cid], (lo.isoformat(), hi.isoformat()),
                                   audit=self.cfg.sample_per_stratum is not None, role=role,
                                   question=question))  # fmt: skip
        try:
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
        finally:
            ASKING.reset(asking)
        with self._lock:
            if reply.refused:
                self.metrics.gateway_refusals += 1
            self.metrics.tokens_in += reply.tokens_in
            self.metrics.tokens_out += reply.tokens_out
            self.cache[key] = reply
        return reply, False

    def _side_by_side(self, fn: Callable[[Any], Any], items: Sequence[Any]) -> list[Any]:
        """``fn`` over ``items``, ``cfg.llm_concurrency`` at a time; results in the order of ``items``."""
        workers = max(1, int(self.cfg.llm_concurrency or 1))
        if workers == 1 or len(items) < 2:
            return [fn(x) for x in items]
        with ThreadPoolExecutor(max_workers=min(workers, len(items)), thread_name_prefix="cascade") as ex:
            return list(ex.map(fn, items))

    def _map(
        self, c: CriterionIR, reply: JudgeReply, span: dict[str, Any] | None, stage: Stage, left_out: int = 0
    ) -> Outcome:
        ev = [span] if span else []
        meta = {
            "call_id": reply.call_id,
            "build_sha": reply.build_sha,
            "prompt": reply.prompt,
            "confidence": reply.confidence,
        }
        if reply.opinions:
            meta["opinions"] = list(reply.opinions)
        if reply.verdict not in ("pass", "fail"):  # keep the judge's coded reason (disagree, low_confidence, ...)
            why = reply.reason if reply.reason in REASON_CODES else "abstained"
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[meta], reason=why)
        if span is None:
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[meta], reason="insufficient")
        condition_present = reply.verdict == "pass"
        eligible = condition_present if c.kind == "inclusion" else not condition_present
        if eligible:
            if left_out:
                # T-603 (review LLM-016, CR-004 flag half): the answer that keeps the patient stands, flagged; the
                # caller marks the patient (PatientTrace.notes_over_budget) and the tier is never "strong"
                why = f"notes_over_budget: {left_out} note(s) of the window did not fit the excerpts"
                return Outcome(c.id, "pass", stage, evidence=[*ev, meta], reason=why)
            return Outcome(c.id, "pass", stage, evidence=[*ev, meta], reason=reply.reason[:200])
        if left_out:
            # D-276 (review S-10): the judge and the verifier read the same excerpts. With an evidence note left out
            # by the budget, "not met" is an answer about part of the record: a person looks, nobody is excluded
            why = f"not judged: {left_out} note(s) of the window did not fit the excerpts, so not met is not final"
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[*ev, meta], reason=why)
        if reply.confidence < self.cfg.confidence_floor:
            return Outcome(c.id, "unknown", stage, unknown_kind="uncertain", evidence=[*ev, meta], reason="abstained")
        if not self.cfg.note_block:  # D-97: a single model may send a patient to review, never out
            return Outcome(
                c.id,
                "fail",
                stage,
                hard=False,
                evidence=[*ev, meta],
                reason="not_met (single model: review, not exclusion)",
            )
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
        work: list[tuple[PatientTrace, list[_Route]]] = []
        for t in alive:
            pending = by_pid.get(t.pid, [])
            if self.judge is None or not pending:
                continue
            if not t.sampled:
                for r in pending:
                    t.outcomes[r.cid] = Outcome(r.cid, "unknown", "S3", unknown_kind="uncertain", reason="not sampled")
                continue
            # CAS-3: descending exclusion power / expected tokens
            work.append((t, sorted(pending, key=lambda r: (-self._power(r.cid) / expected_tokens(r.excerpts), r.cid))))

        def one(item: tuple[PatientTrace, list[_Route]]) -> list[_Route]:
            t, pending = item
            done: list[_Route] = []
            for i, r in enumerate(pending):
                cost = expected_tokens(r.excerpts)
                with self._lock:  # reserve the call's share of the budget before asking
                    stopped = budget_stop(self.cfg, self.items, self.tokens, cost)
                    over = bool(stopped)
                    if not over:
                        self.items += 1
                        self.tokens += cost
                    elif not self.metrics.budget_stopped:
                        self.metrics.budget_stopped = stopped  # the budget that ran out first, by name (F-16)
                if over:
                    t.unprocessed = True  # CAS-4: never silently truncated; SAFE-13: never an exclusion
                    for rest in pending[i:]:
                        t.outcomes[rest.cid] = Outcome(
                            rest.cid, "unknown", "S3", unknown_kind="uncertain", reason="unprocessed (budget)"
                        )
                    break
                reply, hit = self._ask("judge", r, t)
                with self._lock:
                    if hit:  # a cached answer costs nothing
                        self.items -= 1
                        self.tokens -= cost
                    else:
                        self.metrics.pairs_judged["S3"] += 1
                c = self.crit[r.cid]
                lo, hi = window_of(c, t.index_date)
                o = self._map(c, reply, verify_span(reply, r.excerpts, lo, hi), "S3", r.left_out)
                t.outcomes[r.cid] = o
                if r.left_out:
                    self._flag(t, r.cid)
                done.append(r)
                if o.hard:
                    self.exclude(t, "S3", r.cid)
                    for rest in pending[i + 1 :]:
                        t.outcomes[rest.cid] = Outcome(
                            rest.cid, "unknown", "S3", unknown_kind="uncertain", reason="not judged (CAS-3 stop)"
                        )
                    break
            return done

        for done in self._side_by_side(one, work):
            judged.extend(done)
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

            def one(r: _Route) -> bool:
                t = self.traces[r.pid]
                first = t.outcomes[r.cid]
                reply, hit = self._ask("second_opinion", r, t)
                if not hit:
                    with self._lock:
                        self.metrics.pairs_judged["S4"] += 1
                c = self.crit[r.cid]
                lo, hi = window_of(c, t.index_date)
                second = self._map(c, reply, verify_span(reply, r.excerpts, lo, hi), "S4", r.left_out)
                if second.status == first.status:
                    return False
                t.outcomes[r.cid] = Outcome(
                    r.cid,
                    "unknown",
                    "S4",
                    unknown_kind="uncertain",
                    evidence=first.evidence + second.evidence,
                    reason="S3/S4 disagree",
                )
                return True

            disagreements = sum(self._side_by_side(one, pairs))
        alive_after = self.alive()
        self.log("S4", p_in, len(alive_after), len(pairs), len(pairs) - disagreements, disagreements=disagreements)
        self.metrics.n_after["S4"] = len(alive_after)

    def _flag(self, t: PatientTrace, cid: str) -> None:
        """T-603 (CR-004 flag half): an evidence note of ``cid`` did not fit what the models read; the candidate
        carries the flag and its tier is never "strong" (:meth:`tiers`)."""
        with self._lock:
            if cid not in t.notes_over_budget:
                if not t.notes_over_budget:
                    self.metrics.notes_over_budget += 1
                t.notes_over_budget.append(cid)

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
            if any(o.status == "fail" and not o.hard for o in t.outcomes.values()):
                kinds.add("uncertain")  # soft note fail (D-97): a person decides
            if t.notes_over_budget:
                kinds.add("uncertain")  # T-603: a note the models did not read in full: a person looks
            if any(self._weak_met(o) for o in t.outcomes.values()):
                kinds.add("uncertain")  # T-709 (D-478, review M1a): a "met" below the floor is a person's check
            if not self.coded and not any(o.status == "pass" and o.stage in ("S3", "S4") for o in t.outcomes.values()):
                kinds.add("uncertain")  # D-788 review: with nothing coded, "strong" needs a judged "met", not absence
            if "uncertain" in kinds:
                t.tier = "potential:uncertain"
            elif "data_gap" in kinds:
                t.tier = "potential:data_gap"
            else:
                t.tier = "strong"

    def _weak_met(self, o: Outcome) -> bool:
        """A judged "met" whose confidence is below the floor: it keeps the patient and never counts as strong
        (the rule of ``matching.decision.answer_of``; before T-709 the floor was checked on the excluding side
        only)."""
        if o.status != "pass" or o.stage not in ("S3", "S4"):
            return False
        conf = next((e["confidence"] for e in o.evidence if e.get("confidence") is not None), None)
        return conf is not None and float(conf) < self.cfg.confidence_floor

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


def budget_stop(cfg: CascadeConfig, items: int, tokens: int, cost: int) -> str:
    """Which budget one more pair of ``cost`` tokens would pass: ``pairs``, ``tokens`` or "" (it fits)."""
    if cfg.max_llm_items is not None and items + 1 > cfg.max_llm_items:
        return "pairs"
    if cfg.max_tokens is not None and tokens + cost > cfg.max_tokens:
        return "tokens"
    return ""


def _tokens(text: str) -> int:
    """What a note of ``text`` costs in the cascade's excerpt set: the builder's own count (D-645)."""
    return excerpt_builder.note_tokens(text)


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
    s2b_source: SentenceSource | None = None,
) -> CascadeResult:
    """Run S0 → S5 for one study. ``lake`` is a ``lake.client.LakeAPI`` on the pinned L5 snapshot. ``s2b_source``
    (T-203b, flag ``vec.s2b``): S2b ranks from stored vectors where they answer, else on the fly (D-449)."""
    run = _Run(lake, rs, cfg, judge, embedder, s2b_source)
    idx = run.s0()
    applied = run.s1(idx)
    note_crit = [c for c in rs.active() if c.class_ in JUDGED and c.kind in ("inclusion", "exclusion")]
    human = [c for c in rs.active() if c.class_ == "human"]
    run.metrics.note_criteria = len(note_crit)
    routes = run.note_stage(note_crit)
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
