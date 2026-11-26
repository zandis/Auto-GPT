"""The safety invariants of TB-PLAN-06 §7.4 as properties over enumerated inputs (T-650; TB-DR-04 §3.3, §3.4).

``hypothesis`` is not in the test dependencies, so each property is checked over a table that enumerates its input
space exhaustively on a small domain (every combination of TRUE / FALSE / NULL over a handful of criteria, every vote
pair of the two-model rule, every fact kind at every date that matters to a window). An exhaustive small domain covers
the boundary and "absent field" cases that the surviving mutants of TB-DR-04 §3.3 lived in.

Properties (numbered as TB-DR-04 §3.4):

* P1 unknown never excludes (v1 path: NAV, MICROBATCH, CASE);
* P2 unknown never excludes (the SCREEN cascade at S1);
* P3 and P4 proposed facts never count, and a proposed fact that would change an answer once confirmed already makes
  it unknown (oracle: the same lake with the facts confirmed);
* P5 unreadable codes are never a silent FALSE;
* P6 the pair: a decided answer only when both models agree, never surer than either.

The last block runs the cascade's exclusion paths after S1 (S2 certified zero hits, S2b index absent, the judge-reply
mapping, S3 with no judge, not sampled or out of budget, S4 disagreement), which no unit test ran before (ENG-020).
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest
from criteria_compiler.compile_sql.generator import MARK, SqlGenerator
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.flatten import BASIS, DEMOGRAPHIC
from lake.store import Lake
from matching import carried as carried_mod
from matching import coverage as coverage_mod
from matching import proposed as proposed_mod
from matching import recorded as recorded_mod
from matching.cascade import engine as cascade_engine
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.cascade.judge import JudgeReply
from matching.cascade.model import STRATUM_INDEX, STRATUM_S1, STRATUM_S3, STRATUM_ZERO_HIT
from matching.coverage import UNKNOWN_CODE_SYSTEM, Coverage, known_systems
from matching.note_answer import INCLUSION_REASON, NOT_AFFIRMED_REASON
from matching.proposed import PROPOSED_FACT, SUSPECTED_DIAGNOSIS
from orchestrator.scenarios.evaluate import (
    Verdict,
    eligibility,
    evaluate_patients,
    structured_candidate,
    tier,
)
from tb_common import derived as d
from tb_common.pair import Vote, combine
from tb_common.reasons import MIN_CONFIDENCE, Reason
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR, CriterionVerdict, Evidence, PatientEvaluation

ROOT = Path(__file__).resolve().parents[2]
BASE_MANIFEST = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest  # any approved manifest: scopes, routing, ...
INDEX = date(2026, 10, 5)
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
TRI = (True, False, None)


def _ir(cid: str, kind: str, class_: str, logic: dict[str, Any], **extra: Any) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": cid.split("-", maxsplit=1)[0], "kind": kind, "class": class_, "text": extra.pop("text", cid),
         "logic": logic, **extra}
    )  # fmt: skip


def _ruleset(crits: Sequence[CriterionIR], *, sql: str | None = None, vs: dict[str, Any] | None = None) -> Ruleset:
    rid = crits[0].ruleset
    manifest = BASE_MANIFEST.model_copy(update={"id": rid, "library": None, "criteria": [c.id for c in crits]})
    if sql is None:  # a stand-in for the compiled SQL: the cascade reads which criteria it carries from the text
        # it carries the D-275 mark, as freshly compiled SQL does, so the cascade runs it as it is (no overlay)
        sql = MARK + "\n-- " + " ".join(f'"C_{c.id}"' for c in crits if c.class_ in ("structured", "mixed"))
    return Ruleset(manifest=manifest, criteria=list(crits), valuesets=vs or {}, sql=sql)


COND = {"domain": "condition", "quantifier": "any", "valueset": "VS_A"}
COND_YEAR = {**COND, "window": {"anchor": "index", "from_days": -365, "to_days": 0}}
VALUE = {"domain": "observation", "quantifier": "latest", "valueset": "VS_LAB",
         "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"},
         "window": {"anchor": "index", "from_days": -365, "to_days": 0}}  # fmt: skip


# ================================================================================================ P6 the pair
VERDICTS = ("pass", "fail", "unknown")
CONFIDENCES = (0.0, 0.3, MIN_CONFIDENCE - 0.01, MIN_CONFIDENCE, 0.8, 1.0)
VOTE_REASONS = (None, Reason.NOTE.value, Reason.QUOTE_NOT_FOUND.value, Reason.MODEL_DOWN.value)
VOTES = [Vote(v, c, r) for v in VERDICTS for c in CONFIDENCES for r in VOTE_REASONS]
FAILED = (Reason.MODEL_DOWN.value, Reason.QUOTE_NOT_FOUND.value)


def test_p6_the_pair_decides_only_when_both_agree_and_is_never_surer_than_either() -> None:
    """Every vote pair (72 judge votes x 72 verifier votes and no verifier): kills U11, U12, U13."""
    n = 0
    for first in VOTES:
        for second in [None, *VOTES]:
            dec = combine(first, second)
            n += 1
            case = (first, second, dec)
            assert dec.verdict in VERDICTS, case
            if dec.disagreement or dec.failure:
                assert dec.verdict == "unknown", case
            if first.verdict == "unknown":
                assert dec.verdict == "unknown", case  # an undecided judge answer is never decided by the pair
            if dec.verdict == "unknown":
                continue
            # a decided answer: the judge's own, sure enough, no surer than either model
            assert dec.verdict == first.verdict, case
            assert dec.confidence >= MIN_CONFIDENCE and dec.confidence <= first.confidence, case
            if second is not None:
                assert second.verdict == first.verdict and second.reason not in FAILED, case
                assert dec.confidence <= second.confidence, case
    assert n == len(VOTES) * (len(VOTES) + 1)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (Vote("fail", 0.9), Vote("pass", 0.9), ("unknown", Reason.DISAGREE.value)),
        (Vote("fail", 0.9), Vote("unknown", 0.0, Reason.MODEL_DOWN.value), ("unknown", Reason.MODEL_DOWN.value)),
        (Vote("fail", 0.9), Vote("fail", 0.9, Reason.QUOTE_NOT_FOUND.value),
         ("unknown", Reason.VERIFIER_QUOTE_MISSING.value)),
        (Vote("fail", MIN_CONFIDENCE - 0.01), None, ("unknown", Reason.LOW_CONFIDENCE.value)),
        (Vote("fail", 0.9), Vote("fail", MIN_CONFIDENCE - 0.01), ("unknown", Reason.LOW_CONFIDENCE.value)),
        (Vote("fail", 0.9, "note"), Vote("fail", 0.7), ("fail", "note")),
    ],
)  # fmt: skip
def test_p6_named_cases(first: Vote, second: Vote | None, expected: tuple[str, str]) -> None:
    dec = combine(first, second)
    assert (dec.verdict, dec.reason) == expected


# ================================================================================================ P1 v1 path
V1_CRITERIA = [
    _ir("V-INC-01", "inclusion", "structured", COND),
    _ir("V-INC-02", "inclusion", "structured", VALUE),
    _ir("V-EXC-01", "exclusion", "structured", COND),
    _ir("V-INC-03", "inclusion", "mixed", COND, note_question="Is it in the notes?"),
    _ir("V-EXC-02", "exclusion", "mixed", COND, note_question="Is it in the notes?"),
]
V1 = _ruleset(V1_CRITERIA)
V1_IDS = [c.id for c in V1_CRITERIA]


def _v1_excludes(vals: Mapping[str, bool | None]) -> bool:
    """SPEC §8.2: a structured inclusion FALSE, or a structured or mixed exclusion TRUE. Nothing else."""
    return (
        vals["V-INC-01"] is False or vals["V-INC-02"] is False or vals["V-EXC-01"] is True or vals["V-EXC-02"] is True
    )


class _AnswerEngine:
    name = "sql"

    def __init__(self, answers: Mapping[str, Mapping[str, bool | None]]) -> None:
        self.answers = answers

    def evaluate(self, rs: Ruleset, pids: list[str], index_date: date, ids: list[str]) -> dict[str, PatientEvaluation]:
        return {
            p: PatientEvaluation(pid=p, index_date=index_date, engine="sql",
                                 results={i: self.answers[p].get(i) for i in ids})
            for p in pids
            if p in self.answers
        }  # fmt: skip


def _combos(ids: Sequence[str]) -> dict[str, dict[str, bool | None]]:
    return {
        "P" + "".join({True: "t", False: "f", None: "n"}[v] for v in vals): dict(zip(ids, vals, strict=True))
        for vals in itertools.product(TRI, repeat=len(ids))
    }


def _nulled(vals: Mapping[str, bool | None]) -> Iterable[tuple[str, dict[str, bool | None]]]:
    """Every way to set one decided value to unknown."""
    for k, v in vals.items():
        if v is not None:
            yield k, {**vals, k: None}


def _key(vals: Mapping[str, bool | None], ids: Sequence[str]) -> str:
    return "P" + "".join({True: "t", False: "f", None: "n"}[vals[i]] for i in ids)


def test_p1_unknown_never_excludes_on_the_v1_path() -> None:
    """All 243 TRUE/FALSE/NULL combinations of five criteria through ``evaluate_patients`` (no judge). A patient is
    excluded exactly when a structured inclusion is FALSE or an exclusion is TRUE; setting any decided value to
    unknown never turns a kept patient into an excluded one. Kills U01, U02, U03."""
    combos = _combos(V1_IDS)
    res = evaluate_patients(V1, sorted(combos), INDEX, _AnswerEngine(combos), None, 0.75, workers=1)
    for pid, vals in combos.items():
        ev = PatientEvaluation(pid=pid, index_date=INDEX, engine="sql", results=vals)
        out = res[pid]
        assert structured_candidate(V1, ev) is (not _v1_excludes(vals)), (pid, vals)
        assert (out.tier == "excluded") is _v1_excludes(vals), (pid, vals, out.tier)
        if out.tier != "excluded":
            for v in out.verdicts:
                if vals[v.id] is None:
                    assert v.verdict == "unknown", (pid, v)
            if any(vals[i] is None for i in ("V-INC-01", "V-INC-02", "V-EXC-01")):
                assert out.tier == "review" and out.n_unknown >= 1, (pid, out)
        for k, nulled in _nulled(vals):
            if out.tier != "excluded":
                assert res[_key(nulled, V1_IDS)].tier != "excluded", (pid, k)


def test_p1_a_single_null_structured_inclusion_keeps_the_patient_for_review() -> None:
    """ENG-018 (mutant U02): one structured inclusion NULL, everything else eligible: a candidate in review, the
    criterion ``unknown``; never ``excluded`` with no verdict that explains it."""
    vals = {"V-INC-01": True, "V-INC-02": None, "V-EXC-01": False, "V-INC-03": True, "V-EXC-02": False}
    ev = PatientEvaluation(pid="NULL-INC", index_date=INDEX, engine="sql", results=vals)
    assert structured_candidate(V1, ev) is True
    out = evaluate_patients(V1, ["NULL-INC"], INDEX, _AnswerEngine({"NULL-INC": vals}), None, 0.75, workers=1)
    pv = out["NULL-INC"]
    assert pv.tier == "review" and pv.n_unknown >= 1
    verdict = next(v for v in pv.verdicts if v.id == "V-INC-02")
    assert verdict.verdict == "unknown" and verdict.evidence is not None
    assert verdict.evidence.reason == Reason.DATA_GAP.value


def test_p1_eligibility_of_an_unknown_predicate_is_unknown() -> None:
    for kind in ("inclusion", "exclusion"):
        assert eligibility(kind, None) == "unknown"
        assert eligibility(kind, True) == ("pass" if kind == "inclusion" else "fail")
        assert eligibility(kind, False) == ("fail" if kind == "inclusion" else "pass")


def test_p1_a_patient_missing_from_the_snapshot_is_never_excluded() -> None:
    """U15: the engine returns no row for the patient: review, every criterion unknown."""
    out = evaluate_patients(V1, ["GONE"], INDEX, _AnswerEngine({}), None, 0.75, workers=1)["GONE"]
    assert out.tier == "review" and {v.verdict for v in out.verdicts} == {"unknown"}
    assert structured_candidate(V1, None) is False  # and so the v1 filter never lists it as a candidate either


TIER_CRITERIA = [
    _ir("T-INC-01", "inclusion", "structured", COND),
    _ir("T-EXC-01", "exclusion", "structured", COND),
    _ir("T-INC-02", "inclusion", "note", COND, note_question="Q?"),
    _ir("T-EXC-02", "exclusion", "note", COND, note_question="Q?"),
    _ir("T-INC-03", "inclusion", "human", COND, human_question="Q?"),
]
TIER_RS = _ruleset(TIER_CRITERIA)
STATED_02 = "T-EXC-02 present."  # a quote that states T-EXC-02's condition (the criterion's text is its id)


def test_p1_tier_excludes_only_on_a_coded_fail() -> None:
    """``tier`` over every verdict for two structured criteria, two note criteria at three confidences and a human
    criterion, with note answers allowed to block or not, and the note exclusion's quote stated or absent:
    ``excluded`` exactly when a structured verdict fails. Kills U03. The note inclusion's "not met" is review, never
    an exclusion (R22-17, D-1069; ruled on #639 7079180333), and so is the note exclusion's "present", with or
    without a quote, affirmed or not (ring 0, D-1072: a note answer never excludes).
    """
    threshold = 0.75
    sv: tuple[Verdict, ...] = ("pass", "fail", "unknown")
    notes = [(v, c) for v in sv for c in (0.5, 0.75, 0.95)]
    n = 0
    for s1, s2, (n1, c1), (n2, c2), block, (q2, a2) in itertools.product(
        sv, sv, notes, notes, (True, False), ((STATED_02, True), (STATED_02, None), (None, True))
    ):
        verdicts = [
            CriterionVerdict(id="T-INC-01", verdict=s1, evidence=Evidence(resource_refs=[])),
            CriterionVerdict(id="T-EXC-01", verdict=s2, evidence=Evidence(resource_refs=[])),
            CriterionVerdict(id="T-INC-02", verdict=n1, evidence=Evidence(resource_refs=[], confidence=c1)),
            CriterionVerdict(
                id="T-EXC-02", verdict=n2, evidence=Evidence(resource_refs=[], confidence=c2, quote=q2), affirmed=a2
            ),
            CriterionVerdict(id="T-INC-03", verdict="pending_human", evidence=Evidence(resource_refs=[])),
        ]
        t, _, n_unknown = tier(TIER_RS, verdicts, threshold, note_block=block)
        # D-1072 (ring 0): no note answer excludes, a sure, stated, affirmed pair's neither; only a coded fail does
        assert (t == "excluded") is ("fail" in (s1, s2)), (s1, s2, n1, c1, n2, c2, block, q2, t)
        assert n_unknown == [s1, s2, n1, n2].count("unknown")
        if t != "excluded" and "unknown" in (s1, s2, n1, n2):
            assert t == "review"
        n += 1
    assert n == 3 * 3 * 9 * 9 * 2 * 3


# ================================================================================================ fake lake
@dataclass
class _Rows:
    rows: list[dict[str, Any]]

    def to_pylist(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]


@dataclass
class _FakeLake:
    """The lake surface the cascade reads, answered from tables in memory (no database, no files)."""

    rs: Ruleset
    # pid -> {criterion id: value} (E_ evidence under "E_<id>"), or one such dict per index date
    s1: Mapping[str, Any]
    gaps: list[dict[str, Any]] = field(default_factory=list)  # Coverage rows
    facts: list[dict[str, Any]] = field(default_factory=list)  # Proposed rows
    notes: list[dict[str, Any]] = field(default_factory=list)  # document rows
    queries: list[str] = field(default_factory=list)

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> _Rows:
        params = params or []
        if sql == self.rs.sql:
            idx = [date.fromisoformat(x) for x in params[0]]
            scope = set(params[1]) if params[1] is not None else set(self.s1)
            out = []
            for pid in sorted(scope & set(self.s1)):
                given = self.s1[pid]
                for n, i in enumerate(idx):
                    row: dict[str, Any] = {"pid": pid, "index_date": i}
                    for k, v in (given[n] if isinstance(given, list) else given).items():
                        row[k if k.startswith("E_") else f"C_{k}"] = v
                    out.append(row)
            self.queries.append("s1")
            return _Rows(out)
        if sql == coverage_mod.SQL:
            self.queries.append("coverage")
            return _Rows([r for r in self.gaps if params[0] is None or r["pid"] in params[0]])
        if sql == carried_mod.SQL:  # D-795: a site whose rows carry every system the ruleset's lists use
            self.queries.append("carried")
            systems = {i["system"] for v in (self.rs.valuesets or {}).values()
                       for i in (v.get("compose") or {}).get("include") or [] if i.get("system")}  # fmt: skip
            return _Rows([{"domain": d, "system": sy} for d in carried_mod.DOMAINS for sy in sorted(systems)])
        if sql in recorded_mod.QUERIES.values():  # D-914: every patient has records of every kind
            self.queries.append("recorded")
            return _Rows([{"pid": p} for p in params[0]])
        if sql == proposed_mod.SQL:
            self.queries.append("proposed")
            return _Rows([r for r in self.facts if params[0] is None or r["pid"] in params[0]])
        if sql == cascade_engine.NOTES_SQL:
            self.queries.append("notes")
            return _Rows([r for r in self.notes if r["pid"] in params[0]])
        if sql == cascade_engine.CONSENT_SQL:
            return _Rows([])
        if "count(*)" in sql and "FROM patient" in sql:
            return _Rows([{"n": len(self.s1)}])
        raise AssertionError(f"unexpected query: {sql[:80]}")


def _cascade(lake: _FakeLake, **cfg: Any) -> Any:
    conf = {"study_id": lake.rs.id, "run_date": INDEX, "index_mode": "single", "population": sorted(lake.s1),
            "semantics": "v1", "snapshot": None, **cfg}  # fmt: skip
    judge = conf.pop("judge", None)
    embedder = conf.pop("embedder", None)
    return run_cascade(lake, lake.rs, CascadeConfig(**conf), judge=judge, embedder=embedder)


# ================================================================================================ P2 cascade S1
S1_CRITERIA = [
    _ir("C-INC-01", "inclusion", "structured", COND),  # presence
    _ir("C-INC-02", "inclusion", "structured", VALUE),  # a value: FALSE is a failing value in both semantics
    _ir("C-EXC-01", "exclusion", "structured", COND),
    _ir("C-EXC-02", "exclusion", "structured", VALUE),
]
S1_RS = _ruleset(S1_CRITERIA)
S1_IDS = [c.id for c in S1_CRITERIA]


def _s1_excludes(vals: Mapping[str, bool | None], semantics: str) -> bool:
    presence_fails = semantics == "v1" and vals["C-INC-01"] is False
    return presence_fails or vals["C-INC-02"] is False or vals["C-EXC-01"] is True or vals["C-EXC-02"] is True


@pytest.mark.parametrize("semantics", ["v1", "affirmative"])
def test_p2_unknown_never_excludes_at_the_cascade_s1(semantics: str) -> None:
    """All 81 combinations of four structured criteria at S1. Exits at S1 exactly when an exclusion is TRUE or an
    inclusion FALSE (under affirmative semantics only a value inclusion); a NULL inclusion is ``unknown`` and a NULL
    exclusion ``pass``, neither hard; setting any decided value to NULL never turns a kept patient into an excluded
    one. Kills U04, U05, U06."""
    combos = _combos(S1_IDS)
    res = _cascade(_FakeLake(S1_RS, combos), semantics=semantics)
    for pid, vals in combos.items():
        t = res.traces[pid]
        want = _s1_excludes(vals, semantics)
        assert (t.exit_stage == "S1") is want, (pid, vals, t.exit_stage)
        assert (t.tier == "excluded") is want, (pid, t.tier)
        for cid, v in vals.items():
            o = t.outcomes[cid]
            if v is None:
                assert not o.hard and o.status == ("pass" if cid.startswith("C-EXC") else "unknown"), (pid, o)
                assert o.unknown_kind == "data_gap", (pid, o)
            if o.hard:
                assert o.stratum == STRATUM_S1 and v is (cid.startswith("C-EXC")), (pid, o)
        for k, nulled in _nulled(vals):
            if t.exit_stage is None:
                assert res.traces[_key(nulled, S1_IDS)].exit_stage is None, (pid, k)


@pytest.mark.parametrize("semantics", ["v1", "affirmative"])
def test_p2_derived_values_without_a_value_and_unreadable_codes_never_exclude(semantics: str) -> None:
    """U07, U16: a score with no value (the engine says why in the evidence) and a FALSE inclusion beside a record in
    a code system nobody can read are ``unknown`` (an exclusion ``pass``), never a hard fail, at any combination of
    the other criteria's values."""
    ok = {"C-INC-01": True, "C-INC-02": True, "C-EXC-01": False, "C-EXC-02": False}
    s1: dict[str, dict[str, Any]] = {}
    for other in itertools.product(TRI, repeat=2):
        tag = "".join({True: "t", False: "f", None: "n"}[v] for v in other)
        s1[f"DER-INC-{tag}"] = {**ok, "C-INC-02": None, "E_C-INC-02": f"{d.MISSING}:age", "C-EXC-01": other[0],
                                "C-EXC-02": other[1]}  # fmt: skip
        s1[f"DER-EXC-{tag}"] = {**ok, "C-EXC-02": None, "E_C-EXC-02": f"{d.UNIT}:creatinine", "C-EXC-01": other[0],
                                "C-INC-02": other[1]}  # fmt: skip
        s1[f"GAP-{tag}"] = {**ok, "C-INC-01": False, "C-EXC-01": other[0], "C-INC-02": other[1]}
    gaps = [{"pid": p, "domain": "condition", "rid": f"who-{p}", "d": date(2026, 3, 1), "system": "urn:who"}
            for p in s1 if p.startswith("GAP-")]  # fmt: skip
    res = _cascade(_FakeLake(S1_RS, s1, gaps=gaps), semantics=semantics)
    for pid, vals in s1.items():
        t = res.traces[pid]
        if pid.startswith("DER-INC"):
            o = t.outcomes["C-INC-02"]
            assert o.status == "unknown" and not o.hard and o.reason == d.MISSING, (pid, o)
        elif pid.startswith("DER-EXC"):
            o = t.outcomes["C-EXC-02"]
            assert o.status == "pass" and not o.hard and o.reason == d.UNIT, (pid, o)
        else:
            o = t.outcomes["C-INC-01"]
            assert o.status == "unknown" and not o.hard and o.reason == UNKNOWN_CODE_SYSTEM, (pid, o)
            assert o.evidence[0]["record"] == f"who-{pid}"
        others = {k: v for k, v in vals.items() if not k.startswith("E_")}
        rest_excludes = _s1_excludes({**others, **{k: None for k in ("C-INC-01",) if pid.startswith("GAP")},
                                      **{k: None for k in ("C-INC-02",) if pid.startswith("DER-INC")},
                                      **{k: None for k in ("C-EXC-02",) if pid.startswith("DER-EXC")}}, semantics)  # fmt: skip
        assert (t.exit_stage == "S1") is rest_excludes, (pid, t.exit_stage, t.exit_criterion)


def test_p2_a_null_exclusion_does_not_stop_the_funnel_at_an_index_date() -> None:
    """U04: over several index dates the cascade takes the date where the sequential funnel reaches deepest. A NULL
    exclusion passes there (D-18), so a date where the exclusion is unknown beats a later date where it is TRUE."""
    rs = _ruleset([S1_CRITERIA[0], S1_CRITERIA[2]])
    rows = {"DEEP": [{"C-INC-01": True, "C-EXC-01": None}, {"C-INC-01": True, "C-EXC-01": True}],
            "LATE": [{"C-INC-01": True, "C-EXC-01": True}, {"C-INC-01": True, "C-EXC-01": None}]}  # fmt: skip
    res = _cascade(_FakeLake(rs, rows), index_mode="month_ends", lookback_months=2)
    first, last = res.index_dates
    for pid, when in (("DEEP", first), ("LATE", last)):
        t = res.traces[pid]
        assert t.exit_stage is None and t.index_date == when, (pid, t.exit_stage, t.index_date)
        assert t.outcomes["C-EXC-01"].status == "pass" and not t.outcomes["C-EXC-01"].hard


@pytest.mark.parametrize(
    ("policy", "judge", "verifier", "may_block"),
    [("both_agree", False, False, False), ("both_agree", True, False, False), ("never", True, True, False)],
)
def test_p6_a_single_model_never_excludes(
    monkeypatch: pytest.MonkeyPatch, policy: str, judge: bool, verifier: bool, may_block: bool
) -> None:
    """U14: without a second model (or with note answers set never to block) a note answer never excludes."""
    from types import SimpleNamespace

    from orchestrator.scenarios.evaluate import NoteJudge, effective_note_block

    monkeypatch.setenv("TB_NOTE_BLOCK", policy)
    j = None
    if judge:
        j = NoteJudge(None, SimpleNamespace(), verifier=SimpleNamespace() if verifier else None)  # type: ignore[arg-type]
    allowed, effective, _ = effective_note_block(j)
    assert (allowed, effective) == (may_block, "never")


# ================================================================================================ P3, P4 proposed facts
PROP_CRITERIA = [
    _ir("PROP-INC-01", "inclusion", "structured", {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}}),
    _ir("PROP-INC-02", "inclusion", "structured", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"}),
    _ir("PROP-INC-03", "inclusion", "structured",
        {"domain": "observation", "quantifier": "latest", "valueset": "VS_SERUM_URATE",
         "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"},
         "window": {"anchor": "index", "from_days": -365, "to_days": 0}}),
    _ir("PROP-INC-04", "inclusion", "structured",
        {"domain": "condition", "quantifier": "none", "valueset": "VS_MALIGNANCY"}),
    _ir("PROP-EXC-01", "exclusion", "structured",
        {"domain": "condition", "quantifier": "any", "valueset": "VS_MALIGNANCY",
         "window": {"anchor": "index", "from_days": -365, "to_days": 0}}),
    _ir("PROP-INC-05", "inclusion", "structured",
        {"domain": "observation", "derived": "egfr_ckd_epi", "quantifier": "latest",
         "valueset": "VS_EGFR_CKD_EPI_COMPONENTS", "value": {"op": ">=", "num": 60},
         "window": {"anchor": "index", "from_days": -365, "to_days": 0}}),
]  # fmt: skip
PROP_IDS = [c.id for c in PROP_CRITERIA]
# when a fact is dated, relative to the index date: inside, on the index date, on the window's lower bound, one day
# before it, one day after the index date, and no date at all
OFFSETS: dict[str, int | None] = {"in": -30, "index": 0, "lower": -365, "before": -366, "after": 1, "undated": None}
CREATININE = d.CODES["creatinine"]


def _day(offset: int | None) -> str | None:
    return None if offset is None else (INDEX + timedelta(days=offset)).isoformat()


def _tag(r: dict[str, Any], basis: str | None) -> dict[str, Any]:
    if basis:
        r["meta"] = {"tag": [{"system": BASIS, "code": basis}]}
    return r


def _patient(pid: str, birth: str = "1960-01-01", sex: str = "male") -> list[dict[str, Any]]:
    return [
        {"resourceType": "Patient", "id": pid, "gender": sex, "birthDate": birth},
        {"resourceType": "Encounter", "id": f"e-{pid}", "subject": {"reference": f"Patient/{pid}"},
         "period": {"start": "2026-09-01"}, "class": {"code": "AMB"}},
    ]  # fmt: skip


def _cond(rid: str, pid: str, code: str, day: str | None, basis: str | None = None) -> dict[str, Any]:
    cc = {"coding": [{"system": ICD, "code": code}]} if code else {"text": "chart wording"}
    r: dict[str, Any] = {"resourceType": "Condition", "id": rid, "subject": {"reference": f"Patient/{pid}"}, "code": cc}
    if day:
        r["onsetDateTime"] = day
    return _tag(r, basis)


def _lab(
    rid: str, pid: str, code: tuple[str, str], value: float, day: str | None, basis: str | None = None
) -> dict[str, Any]:
    r: dict[str, Any] = {"resourceType": "Observation", "id": rid, "subject": {"reference": f"Patient/{pid}"},
                         "code": {"coding": [{"system": code[0], "code": code[1]}]},
                         "valueQuantity": {"value": value, "unit": "mg/dL", "code": "mg/dL"},
                         "category": [{"coding": [{"code": "laboratory"}]}]}  # fmt: skip
    if day:
        r["effectiveDateTime"] = day
    return _tag(r, basis)


def _demo(rid: str, pid: str, what: str, value: str, basis: str) -> dict[str, Any]:
    return _tag({"resourceType": "Observation", "id": rid, "subject": {"reference": f"Patient/{pid}"},
                 "code": {"coding": [{"system": DEMOGRAPHIC, "code": what}]}, "valueString": value}, basis)  # fmt: skip


URATE = (LOINC, "3084-1")


def _base(pid: str, gout: bool, birth: str = "1960-01-01", sex: str = "male") -> list[dict[str, Any]]:
    """Coded records of an eligible patient (age 66, gout, urate 8.4, creatinine 1.3: eGFR about 60.6)."""
    out = [*_patient(pid, birth, sex), _lab(f"u-{pid}", pid, URATE, 8.4, "2026-09-01"),
           _lab(f"cr-{pid}", pid, CREATININE, 1.3, "2026-09-01")]  # fmt: skip
    if gout:
        out.append(_cond(f"g-{pid}", pid, "M10.9", "2026-01-10"))
    return out


# the facts each patient adds to the coded base (a demographic fact has no date)
COND_FACTS = {"gout": "M10.9", "malig": "C50.911", "nocode": "", "other": "I10"}
LAB_FACTS = {"urate-lo": (URATE, 5.0), "urate-hi": (URATE, 9.0), "creat-hi": (CREATININE, 3.0)}
DEMO_FACTS = {"birth-old": ("birth_date", "1950-01-01"), "birth-child": ("birth_date", "2015-01-01"),
              "sex": ("sex", "female")}  # fmt: skip


def _variants() -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """pid -> (resources with the fact proposed or suspected, resources with the same fact confirmed)."""
    out: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for gout in (True, False):
        pid = f"BASE-{'G' if gout else 'N'}"
        out[pid] = (_base(pid, gout), _base(pid, gout))
    for (name, code), (when, off), gout in itertools.product(COND_FACTS.items(), OFFSETS.items(), (True, False)):
        pid = f"C-{name}-{when}-{'G' if gout else 'N'}"
        day = _day(off)
        out[pid] = tuple(  # type: ignore[assignment]
            [*_base(pid, gout), _cond(f"f-{pid}", pid, code, day, basis)] for basis in ("proposed", "confirmed")
        )
    for (name, code), (when, off), gout in itertools.product(COND_FACTS.items(), OFFSETS.items(), (True, False)):
        pid = f"S-{name}-{when}-{'G' if gout else 'N'}"  # a suspected diagnosis (疑い, D-142); confirmed: coded
        suspected = _cond(f"f-{pid}", pid, code, _day(off))
        suspected["verificationStatus"] = {"coding": [{"code": "provisional"}]}
        out[pid] = ([*_base(pid, gout), suspected], [*_base(pid, gout), _cond(f"f-{pid}", pid, code, _day(off))])
    for (name, (loinc, num)), (when, off) in itertools.product(LAB_FACTS.items(), OFFSETS.items()):
        pid = f"L-{name}-{when}"
        day = _day(off)
        out[pid] = tuple(  # type: ignore[assignment]
            [*_base(pid, True), _lab(f"f-{pid}", pid, loinc, num, day, basis)] for basis in ("proposed", "confirmed")
        )
    for name, (what, text) in DEMO_FACTS.items():
        pid = f"D-{name}"
        confirmed = {"birth_date": {"birth": text}, "sex": {"sex": text}}[what]
        out[pid] = ([*_base(pid, True), _demo(f"f-{pid}", pid, what, text, "proposed")],
                    _base(pid, True, **confirmed))  # fmt: skip
    return out


VARIANTS = _variants()


def _build(tmp: Path, name: str, resources: Iterable[dict[str, Any]]) -> LakeLocal:
    nd = tmp / f"{name}-nd"
    nd.mkdir()
    by: dict[str, list[dict[str, Any]]] = {}
    for r in resources:
        by.setdefault(r["resourceType"], []).append(r)
    for t, rows in by.items():
        (nd / f"{t}.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    Lake(tmp / name).rebuild(INDEX.isoformat(), HashEmbedder(), nd)
    return LakeLocal(tmp / name, HashEmbedder())


@pytest.fixture(scope="module")
def prop_world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    term = Terminology()
    vs: dict[str, Any] = {}
    for name, domain, concept in (("VS_GOUT", "condition", "gout"), ("VS_SERUM_URATE", "observation", "serum urate"),
                                  ("VS_MALIGNANCY", "condition", "malignancy")):  # fmt: skip
        mapped = term.map(domain, concept)
        vs[name] = valueset("PROP", name, concept, mapped.concepts, "1.0.0", families=mapped.families)
    vs["VS_EGFR_CKD_EPI_COMPONENTS"] = valueset(
        "PROP", "VS_EGFR_CKD_EPI_COMPONENTS", "egfr_ckd_epi",
        [Concept(*d.CODES[c], c) for c in d.COMPONENTS["egfr_ckd_epi"]], "1.0.0",
    )  # fmt: skip
    sql = SqlGenerator("PROP", "1.0.0", ValueSets("PROP", vs, term)).render(PROP_CRITERIA)
    rs = _ruleset(PROP_CRITERIA, sql=sql, vs=vs)
    tmp = tmp_path_factory.mktemp("prop-diff")
    proposed = _build(tmp, "proposed", (r for p, _ in VARIANTS.values() for r in p))
    confirmed = _build(tmp, "confirmed", (r for _, c in VARIANTS.values() for r in c))
    pids = sorted(VARIANTS)

    def raw(lake: LakeLocal) -> dict[str, dict[str, bool | None]]:
        rows = lake.query(sql, [[INDEX.isoformat()], pids]).to_pylist()
        return {r["pid"]: {c: r[f"C_{c}"] for c in PROP_IDS} for r in rows}

    from orchestrator.scenarios.evaluate import SqlEngine

    return {"rs": rs, "lake": proposed, "raw": raw(proposed), "confirmed": raw(confirmed),
            "evaluated": SqlEngine(proposed).evaluate(rs, pids, INDEX, PROP_IDS), "pids": pids}  # fmt: skip


def test_p3_p4_the_table_is_not_vacuous(prop_world: dict[str, Any]) -> None:
    """The base patients are what the table assumes, and confirming a fact does flip every criterion somewhere."""
    raw, conf = prop_world["raw"], prop_world["confirmed"]
    assert raw["BASE-G"] == {c: not c.startswith("PROP-EXC") for c in PROP_IDS}
    assert raw["BASE-N"]["PROP-INC-02"] is False
    flipped = {(pid, c) for pid in raw for c in PROP_IDS if raw[pid][c] != conf[pid][c]}
    for must in [("L-urate-lo-index", "PROP-INC-03"), ("C-gout-undated-N", "PROP-INC-02"),
                 ("C-malig-index-G", "PROP-EXC-01"), ("C-malig-lower-G", "PROP-EXC-01"),
                 ("C-malig-in-G", "PROP-INC-04"), ("C-gout-in-N", "PROP-INC-02"), ("L-creat-hi-in", "PROP-INC-05"),
                 ("D-birth-old", "PROP-INC-05"), ("D-sex", "PROP-INC-05"), ("D-birth-child", "PROP-INC-01"),
                 ("S-malig-in-G", "PROP-EXC-01"), ("S-gout-undated-N", "PROP-INC-02")]:  # fmt: skip
        assert must in flipped, must
    for unchanged in [("L-urate-lo-before", "PROP-INC-03"), ("L-urate-lo-after", "PROP-INC-03"),
                      ("C-malig-before-G", "PROP-EXC-01"), ("C-other-in-G", "PROP-EXC-01")]:  # fmt: skip
        assert unchanged not in flipped, unchanged


def test_p3_proposed_facts_never_decide_an_answer(prop_world: dict[str, Any]) -> None:
    """For every fact kind at every date: the runtime answer is the coded answer or ``unknown``, never another
    decided answer, and an unknown coded answer stays unknown. Kills P01 to P04, P08, P11."""
    raw, ev = prop_world["raw"], prop_world["evaluated"]
    # D-914: a patient with no coded record of the criterion's kind at all also reads unknown, with its own reason
    rec = recorded_mod.Recorded.load(prop_world["lake"], prop_world["pids"], None)
    by_id = prop_world["rs"].by_id()
    for pid in prop_world["pids"]:
        got = ev[pid].results
        for c in PROP_IDS:
            assert got[c] in (raw[pid][c], None), (pid, c, raw[pid][c], got[c])
            if got[c] is None and raw[pid][c] is not None:
                why = (ev[pid].reasons or {})[c]
                if why == recorded_mod.NO_RECORD:
                    assert rec.doubt(by_id[c], pid, raw[pid][c]), (pid, c)  # only for a record that is not there
                    continue
                want = SUSPECTED_DIAGNOSIS if pid.startswith("S-") else PROPOSED_FACT
                assert why == want, (pid, c)
    base = {c: ev["BASE-G"].results[c] for c in PROP_IDS}
    assert base == raw["BASE-G"] and not ev["BASE-G"].reasons


def test_p4_a_fact_that_would_change_an_answer_once_confirmed_already_makes_it_unknown(
    prop_world: dict[str, Any],
) -> None:
    """The completeness half (oracle: the same lake with every fact confirmed). Undated facts, facts on the index date
    and on the window's lower bound, and a proposed birth date or sex under a derived value (eGFR) are all in the
    table. Kills P05, P06, P07."""
    raw, conf, ev = prop_world["raw"], prop_world["confirmed"], prop_world["evaluated"]
    missed = [(pid, c, raw[pid][c], conf[pid][c]) for pid in prop_world["pids"] for c in PROP_IDS
              if conf[pid][c] != raw[pid][c] and ev[pid].results[c] is not None]  # fmt: skip
    assert not missed


def test_p3_the_cascade_never_excludes_on_a_proposed_fact(prop_world: dict[str, Any]) -> None:
    """S1 of the SCREEN cascade on the same lake: a patient leaves only when the coded answers alone exclude them."""
    cfg = CascadeConfig(study_id="PROP", run_date=INDEX, index_mode="single", population=prop_world["pids"],
                        semantics="v1", snapshot=None)  # fmt: skip
    res = run_cascade(prop_world["lake"], prop_world["rs"], cfg)
    raw = prop_world["raw"]
    for pid in prop_world["pids"]:
        coded_excludes = any(
            (raw[pid][c] is False and c.startswith("PROP-INC")) or (raw[pid][c] is True and c.startswith("PROP-EXC"))
            for c in PROP_IDS
        )
        if res.traces[pid].exit_stage is not None:
            assert coded_excludes, (pid, res.traces[pid].exit_criterion)
        for c, o in res.traces[pid].outcomes.items():
            if o.reason in (PROPOSED_FACT, SUSPECTED_DIAGNOSIS):
                assert not o.hard and o.status in ("unknown", "pass"), (pid, c, o)


# ================================================================================================ P5 coverage
@dataclass
class _DuckLake:
    """The two coded tables Coverage reads, in an in-memory DuckDB: the real SQL runs on them."""

    con: Any

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        return self.con.execute(sql, params or []).to_arrow_table()


GAP_ROWS: list[tuple[str, str | None, str | None, str | None, str | None, bool]] = [
    # pid, code, system, onset, recorded, unreadable?
    ("ICD-OK", "M10.9", ICD, "2026-03-01", None, False),
    ("ICD-EMPTY-CODE", "", ICD, "2026-03-01", None, True),
    ("ICD-NULL-CODE", None, ICD, "2026-03-01", None, True),
    ("NO-SYSTEM", "M10.9", "", "2026-03-01", None, True),
    ("NULL-SYSTEM", "M10.9", None, "2026-03-01", None, True),
    ("WHO", "M10", "urn:who-icd10", "2026-03-01", None, True),
    ("LOCAL-KNOWN", "L-1", "urn:local", "2026-03-01", None, False),  # a system a ValueSet of the ruleset lists
    ("WHO-UNDATED", "M10", "urn:who-icd10", None, None, True),
    ("WHO-RECORDED", "M10", "urn:who-icd10", None, "2026-03-01", True),
    ("TEXT-UNDATED", None, None, None, None, True),
    ("WHO-OLD", "M10", "urn:who-icd10", "2020-01-01", None, True),
    ("WHO-LOWER", "M10", "urn:who-icd10", (INDEX - timedelta(days=365)).isoformat(), None, True),
    ("WHO-BEFORE", "M10", "urn:who-icd10", (INDEX - timedelta(days=366)).isoformat(), None, True),
    ("WHO-INDEX", "M10", "urn:who-icd10", INDEX.isoformat(), None, True),
    ("WHO-AFTER", "M10", "urn:who-icd10", (INDEX + timedelta(days=1)).isoformat(), None, True),
]
MED_ROWS = [("ATC-OK", "M04AA01", "2026-03-01", False), ("ATC-EMPTY", "", "2026-03-01", True),
            ("ATC-NULL", None, None, True)]  # fmt: skip
COVERAGE_VS = {"VS_A": {"compose": {"include": [{"system": ICD}, {"system": "urn:local"}]}}}


@pytest.fixture(scope="module")
def gap_lake() -> _DuckLake:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE condition (pid VARCHAR, cid VARCHAR, code VARCHAR, system VARCHAR, onset DATE, recorded DATE)"
    )
    con.execute(
        'CREATE TABLE medication (pid VARCHAR, mid VARCHAR, atc VARCHAR, authored DATE, start DATE, "end" DATE)'
    )
    for pid, code, system, onset, recorded, _ in GAP_ROWS:
        con.execute("INSERT INTO condition VALUES (?, ?, ?, ?, ?, ?)", [pid, f"c-{pid}", code, system, onset, recorded])
    for pid, atc, authored, _ in MED_ROWS:
        con.execute("INSERT INTO medication VALUES (?, ?, ?, ?, NULL, NULL)", [pid, f"m-{pid}", atc, authored])
    return _DuckLake(con)


def test_p5_unreadable_rows_are_found_by_the_coverage_query(gap_lake: _DuckLake) -> None:
    """Every row the mapping cannot read, dated or not, is listed; a readable one never is. Kills U10."""
    cov = Coverage.load(gap_lake, None, None, known_systems(COVERAGE_VS))
    assert cov.patients("condition") == {pid for pid, *_, bad in GAP_ROWS if bad}
    assert cov.patients("medication") == {pid for pid, *_, bad in MED_ROWS if bad}
    undated = {pid: [r.d for r in rows] for pid, rows in cov.rows.items() if pid.endswith("UNDATED")}
    assert undated == {"WHO-UNDATED": [None], "TEXT-UNDATED": [None]}
    assert cov.rows["WHO-RECORDED"][0].d == date(2026, 3, 1)  # no onset: the recorded date


COVERAGE_CRITERIA = {
    "any": _ir("G-INC-01", "inclusion", "structured", COND),
    "year": _ir("G-INC-02", "inclusion", "structured", COND_YEAR),
    "med": _ir("G-INC-03", "inclusion", "structured",
               {"domain": "medication", "quantifier": "any", "valueset": "VS_MED"}),
    "none": _ir("G-INC-04", "inclusion", "structured", {**COND, "quantifier": "none"}),
    "not": _ir("G-INC-05", "inclusion", "structured", {"op": "not", "args": [COND]}),
    "exclusion": _ir("G-EXC-01", "exclusion", "structured", COND),
}  # fmt: skip
IN_YEAR = {"WHO", "ICD-EMPTY-CODE", "ICD-NULL-CODE", "NO-SYSTEM", "NULL-SYSTEM", "WHO-RECORDED", "WHO-LOWER",
           "WHO-INDEX"}  # fmt: skip
UNDATED = {"WHO-UNDATED", "TEXT-UNDATED"}


@pytest.mark.parametrize(
    ("which", "expected"),
    [
        ("any", IN_YEAR | UNDATED | {"WHO-OLD", "WHO-BEFORE"}),  # no window: anything up to the index date
        ("year", IN_YEAR | UNDATED),  # the window's bounds count; an undated row always counts
        ("med", {"ATC-EMPTY", "ATC-NULL"}),
        ("none", set()),  # "no gout": a record makes it falser, never truer
        ("not", set()),
        ("exclusion", set()),  # exclusions are not widened: FALSE keeps the patient anyway
    ],
)
def test_p5_an_unreadable_row_turns_a_false_inclusion_into_unknown(
    gap_lake: _DuckLake, which: str, expected: set[str]
) -> None:
    """Per criterion shape, the patients whose FALSE becomes ``unknown`` (non-empty refs). Kills U08, U09, U10."""
    cov = Coverage.load(gap_lake, None, None, known_systems(COVERAGE_VS))
    c = COVERAGE_CRITERIA[which]
    got = {pid for pid in cov.rows if cov.refs(c, pid, INDEX)}
    assert got == expected


# ================================================================================================ ENG-020 S2 to S4
NOTE_TEXT = "Gout flare in the left toe."
INFECTED = "Active infection of the left toe."  # states N-EXC-01's condition (D-985)
CASCADE_CRITERIA = [
    _ir("N-INC-00", "inclusion", "structured", COND),
    _ir("N-INC-01", "inclusion", "note", COND, text="Gout flare documented", note_question="Is a gout flare noted?"),
    _ir("N-EXC-01", "exclusion", "note", COND, text="Active infection", note_question="Is an infection noted?"),
]
CASCADE_RS = _ruleset(CASCADE_CRITERIA)
LEXICON = {"N-INC-01": ["flare"], "N-EXC-01": ["infection"], "N-INC-00": ["gout"]}


def _note(pid: str, text: str = NOTE_TEXT, offset: int = -10, did: str | None = None) -> dict[str, Any]:
    return {"did": did or f"doc-{pid}", "pid": pid, "d": INDEX + timedelta(days=offset), "type": "progress",
            "text": text}  # fmt: skip


@dataclass
class _Judge:
    """Answers by role and criterion text; quotes the first excerpt verbatim so the span verifies."""

    answers: Mapping[tuple[str, str], tuple[str, float]]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def judge(self, *, role: str, criterion_text: str, excerpts: list[dict[str, Any]], **_: Any) -> JudgeReply:
        self.calls.append((role, criterion_text))
        verdict, conf = self.answers.get((role, criterion_text), ("unknown", 0.0))
        ex = excerpts[0]
        quote = str(ex["text"]) if verdict != "unknown" else None
        # a pair of judge v6: a decided answer both models affirmed (round 5 of R22-16, #639 7115208555)
        return JudgeReply(verdict, conf, quote, str(ex["date"]) if quote else None, "from the notes", call_id="c1",
                          affirmed=quote is not None)  # fmt: skip


def _lake(rs: Ruleset, pids: Sequence[str], notes: Sequence[dict[str, Any]], s1: bool | None = True) -> _FakeLake:
    return _FakeLake(rs, {p: {"N-INC-00": s1} for p in pids}, notes=list(notes))


def test_s2_certified_zero_hit_excludes_only_on_an_inclusion() -> None:
    """CAS-13: a certified criterion whose lexicon finds nothing in the notes takes absence semantics at S2: a hard
    fail for an inclusion (stratum zero-hit), a pass for an exclusion."""
    lake = _lake(CASCADE_RS, ["Z-1"], [_note("Z-1", "Routine visit. Nothing to report.")])
    res = _cascade(lake, lexicon=LEXICON, zero_hit_allowed=frozenset({"N-INC-01", "N-EXC-01"}))
    t = res.traces["Z-1"]
    inc, exc = t.outcomes["N-INC-01"], t.outcomes["N-EXC-01"]
    assert inc.status == "fail" and inc.hard and inc.stage == "S2" and inc.stratum == STRATUM_ZERO_HIT
    assert exc.status == "pass" and not exc.hard and exc.stage == "S2"
    assert (t.exit_stage, t.exit_criterion, t.tier) == ("S2", "N-INC-01", "excluded")
    assert res.stage("S2").detail["excluded_zero_hit"] == 1


def test_s2_uncertified_zero_hits_and_no_judge_never_exclude() -> None:
    """The same notes without certification go on to S2b and S3; with no judge configured S3 leaves the pairs
    ``unknown`` and the patient in review."""
    lake = _lake(CASCADE_RS, ["Z-2"], [_note("Z-2", "Routine visit. Nothing to report.")])
    res = _cascade(lake, lexicon=LEXICON, zero_hit_allowed=frozenset({"N-EXC-01"}))
    t = res.traces["Z-2"]
    assert t.exit_stage is None and t.tier == "potential:uncertain"
    o = t.outcomes["N-INC-01"]
    assert (o.status, o.stage, o.reason, o.hard) == ("unknown", "S3", "no judge configured", False)
    assert t.outcomes["N-EXC-01"].status == "pass"  # certified absence of the exclusion


def test_s2_no_note_in_the_window_is_a_data_gap() -> None:
    lake = _lake(CASCADE_RS, ["Z-3"], [_note("Z-3", offset=-400)])
    res = _cascade(lake, lexicon=LEXICON, zero_hit_allowed=frozenset({"N-INC-01", "N-EXC-01"}))
    t = res.traces["Z-3"]
    assert t.exit_stage is None and t.tier == "potential:data_gap"
    assert {t.outcomes[c].reason for c in ("N-INC-01", "N-EXC-01")} == {"no note in window"}


@dataclass
class _Embedder:
    """Every sentence orthogonal to the query (``below``) or the same as it (``above``)."""

    above: bool
    model: str = "stub-embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0], *([[1.0, 0.0] if self.above else [0.0, 1.0]] * (len(texts) - 1))]


@pytest.mark.parametrize("absence", [True, False])
def test_s2b_below_the_threshold_never_excludes_on_an_inclusion(absence: bool) -> None:
    """D-90: a zero-hit pair the semantic screen finds no mention of is ``unknown`` for an inclusion (review, never an
    exclusion) and absent for an exclusion; with absence semantics off (screening) both go on to the judge."""
    lake = _lake(CASCADE_RS, ["B-1"], [_note("B-1", "Routine visit. Nothing to report.")])
    res = _cascade(lake, lexicon=LEXICON, embedder=_Embedder(above=False), absence_semantics=absence)
    t = res.traces["B-1"]
    inc, exc = t.outcomes["N-INC-01"], t.outcomes["N-EXC-01"]
    assert t.exit_stage is None and not inc.hard and not exc.hard
    if absence:
        assert (inc.status, inc.stage, inc.unknown_kind) == ("unknown", "S2b", "uncertain")
        assert (exc.status, exc.stage, exc.reason) == ("pass", "S2b", "S2b below: absence")
        assert res.stage("S2b").detail["below"] == 2
    else:
        assert {o.reason for o in (inc, exc)} == {"no judge configured"}
    above = _cascade(_lake(CASCADE_RS, ["B-2"], [_note("B-2", "Routine visit.")]), lexicon=LEXICON,
                     embedder=_Embedder(above=True))  # fmt: skip
    assert above.stage("S2b").detail["above"] == 2 and above.traces["B-2"].exit_stage is None


INDEX_CRIT = _ir("X-INC-01", "inclusion", "structured", COND, text="Gout")
object.__setattr__(INDEX_CRIT, "index", True)  # an IR v3 index criterion (CAS-18); the v1 model has no such field
INDEX_RS = _ruleset([INDEX_CRIT])


@pytest.mark.parametrize(
    ("notes", "absence", "excluded", "reason"),
    [
        ([], True, True, "index condition absent: no code, no S2 or S2b mention"),
        ([], False, False, "index condition not coded and not found in the notes; review"),
        ([_note("I-1", "Gout seen in clinic.", offset=-200)], True, False, "index rescued"),  # S2 lexicon sweep
        ([_note("I-1", "Seen in clinic.", offset=-200)], True, False, "index rescued"),  # S2b, no embedder: above
        (
            [_note("I-1", "Seen in clinic.", offset=-200)],
            "below",
            True,
            "index condition absent: no code, no S2 or S2b mention",
        ),  # S2b below the threshold
    ],
)
def test_s2b_index_absent(notes: list[dict[str, Any]], absence: bool | str, excluded: bool, reason: str) -> None:
    """CAS-11 and CAS-18: under affirmative semantics a FALSE index criterion is ``index_absent`` at S1; it is
    excluded at S2b only when no note mentions it and absence semantics apply, else rescued or sent to review."""
    lake = _FakeLake(INDEX_RS, {"I-1": {"X-INC-01": False}}, notes=notes)
    embedder = _Embedder(above=False) if absence == "below" else None
    res = _cascade(lake, semantics="affirmative", lexicon={"X-INC-01": ["gout"]}, absence_semantics=bool(absence),
                   embedder=embedder)  # fmt: skip
    t = res.traces["I-1"]
    o = t.outcomes["X-INC-01"]
    assert o.reason == reason
    assert (t.exit_stage == "S2b") is excluded
    if excluded:
        assert o.hard and o.status == "fail" and o.stratum == STRATUM_INDEX and t.tier == "excluded"
    else:
        assert not o.hard and o.status == "unknown" and t.tier.startswith("potential")


def _run_for_map(note_block: bool = True) -> Any:
    cfg = CascadeConfig(study_id="N", run_date=INDEX, semantics="v1", note_block=note_block)
    lake: Any = _FakeLake(CASCADE_RS, {})
    return cascade_engine._Run(lake, CASCADE_RS, cfg, None, None)


SPAN = {"did": "d1", "start": 0, "end": 5, "date": INDEX.isoformat(), "sentence_hash": "h", "quote": "q"}


def test_judge_reply_mapping_is_never_hard() -> None:
    """``_map`` over every verdict, reason, confidence, span and note-block setting, for both kinds: never a hard
    fail (ring 0, D-1072; before it, a hard fail for a pair's verified, sure, affirmed exclusion "present" while note
    answers were allowed to block). An inclusion's "not met" from the notes is soft (R22-17)."""
    by = {c.id: c for c in CASCADE_CRITERIA}
    n = 0
    # D-985 (F6): the quote states the condition (both criteria's), or only names a drug: an exclusion "present" on
    # the latter is an inference and never a hard fail
    stated, drug = "Active infection and a gout flare noted.", "Taking amoxicillin 500 mg."
    for cid, verdict, reason, conf, span, block, quote, affirmed in itertools.product(
        ("N-INC-01", "N-EXC-01"),
        ("pass", "fail", "unknown"),
        ("from the notes", Reason.DISAGREE.value, Reason.REFUSED.value),
        (0.5, 0.74, 0.75, 0.95),
        (SPAN, None),
        (True, False),
        (stated, drug),
        (True, False),
    ):
        run = _run_for_map(block)
        c = by[cid]
        sp = {**span, "quote": quote} if span else None
        o = run._map(c, JudgeReply(verdict, conf, quote, None, reason, affirmed=affirmed), sp, "S3")
        decided = verdict in ("pass", "fail")
        ineligible = decided and ((verdict == "fail") if c.kind == "inclusion" else (verdict == "pass"))
        guess = c.kind == "exclusion" and verdict == "pass" and quote == drug
        # R22-17 (D-1069; ruled on #639 7079180333): an inclusion's "not met" from the notes is never a hard fail
        excl = c.kind == "exclusion"
        unsaid = excl and verdict == "pass" and not affirmed  # round 5: not affirmed by both
        # D-1072 (ring 0): a note answer is never a hard fail, a pair's stated, affirmed, sure "present" neither
        assert o.hard is False, (cid, verdict, reason, conf, span is not None, block, o)
        if o.hard:
            assert o.status == "fail" and o.stratum == STRATUM_S3 and o.reason == "not_met"
        if not decided:
            assert o.status == "unknown" and o.reason == (reason if reason in (Reason.DISAGREE.value,
                                                                               Reason.REFUSED.value) else "abstained")  # fmt: skip
        elif span is None:
            assert o.status == "unknown" and o.reason == "insufficient"
        elif ineligible and conf < 0.75:
            assert o.status == "unknown" and o.reason == "abstained"
        elif guess:
            assert o.status == "unknown" and o.reason.startswith("inferred")
        elif ineligible and not excl:
            assert o.status == "fail" and not o.hard and o.reason == INCLUSION_REASON
        elif unsaid:
            assert o.status == "unknown" and o.reason == NOT_AFFIRMED_REASON
        elif ineligible and not block:
            assert o.status == "fail" and not o.hard  # D-97: a single model sends to review, never out
        elif not ineligible:
            assert o.status == "pass"
        n += 1
    assert n == 2 * 3 * 3 * 4 * 2 * 2 * 2 * 2


def test_s3_a_note_fail_never_stops_the_patient_and_every_criterion_is_judged() -> None:
    """Ring 0 (D-1072): a pair's verified, sure, stated "not met" from the notes is no hard fail, so CAS-3 never stops
    a patient at S3 on a note answer: the patient stays, for review, and every note criterion is judged (before
    D-1072 the first such answer excluded the patient and the criteria after it were ``unknown``)."""
    judge = _Judge({("judge", "Active infection"): ("pass", 0.95), ("judge", "Gout flare documented"): ("fail", 0.95)})
    lake = _lake(CASCADE_RS, ["J-1"], [_note("J-1", "Gout flare with infection.")])
    res = _cascade(lake, lexicon=LEXICON, judge=judge, sample_per_stratum=None)
    t = res.traces["J-1"]
    assert t.exit_stage is None and t.tier == "potential:uncertain"
    assert not [o for o in t.outcomes.values() if o.hard]
    rest = [o for c, o in t.outcomes.items() if c in ("N-INC-01", "N-EXC-01")]
    assert [o.status for o in rest] == ["fail", "fail"] and "not judged (CAS-3 stop)" not in [o.reason for o in rest]
    assert len(judge.calls) == 2


def test_s3_not_sampled_and_out_of_budget_never_exclude() -> None:
    """CAS-8: a patient outside the feasibility sample is ``unknown`` (not sampled). CAS-4: when the budget runs out
    the remaining pairs are ``unknown`` and the patient is marked unprocessed. Neither is ever an exclusion, even
    when the judge would have excluded. R22-17 (D-1069; ruled on #639 7079180333): the answer that would have excluded
    is the note exclusion's "present" on a quote that states it; the inclusion case beside it is review."""
    judge = _Judge({("judge", "Active infection"): ("pass", 0.95)})
    rs = _ruleset([CASCADE_CRITERIA[0], CASCADE_CRITERIA[2]])
    pids = ["S-1", "S-2", "S-3"]
    lake = _lake(rs, pids, [_note(p, INFECTED, did="same") for p in pids])
    res = _cascade(lake, lexicon=LEXICON, judge=judge, sample_per_stratum=1)
    sampled = [p for p in pids if res.traces[p].sampled]
    # D-1072 (ring 0): the judged patient's "present" is a "not met" for review, no longer an exclusion at S3
    assert len(sampled) == 1 and res.traces[sampled[0]].exit_stage is None
    assert res.traces[sampled[0]].outcomes["N-EXC-01"].status == "fail"
    for p in set(pids) - set(sampled):
        t = res.traces[p]
        o = t.outcomes["N-EXC-01"]
        assert (o.status, o.reason, o.hard, t.exit_stage) == ("unknown", "not sampled", False, None)
        assert t.tier == "potential:uncertain"
    inc = _ruleset(CASCADE_CRITERIA[:2])
    res = _cascade(_lake(inc, pids, [_note(p, did="same") for p in pids]), lexicon=LEXICON,
                   judge=_Judge({("judge", "Gout flare documented"): ("fail", 0.95)}), sample_per_stratum=1)  # fmt: skip
    assert not any(t.exit_stage for t in res.traces.values())  # the inclusion case beside it: review, never out
    lake = _lake(rs, pids, [_note(p, INFECTED) for p in pids])
    res = _cascade(lake, lexicon=LEXICON, judge=_Judge({("judge", "Active infection"): ("pass", 0.95)}),
                   sample_per_stratum=None, max_llm_items=0)  # fmt: skip
    for p in pids:
        t = res.traces[p]
        o = t.outcomes["N-EXC-01"]
        assert t.unprocessed and t.exit_stage is None and (o.status, o.reason) == ("unknown", "unprocessed (budget)")
    assert res.metrics.unprocessed == 3


@pytest.mark.parametrize(("second", "agree"), [(("fail", 0.95), False), (("pass", 0.95), True)])
def test_s4_a_second_opinion_that_disagrees_sends_a_strong_candidate_to_review(
    second: tuple[str, float], agree: bool
) -> None:
    judge = _Judge({("judge", "Gout flare documented"): ("pass", 0.95),
                    ("second_opinion", "Gout flare documented"): second})  # fmt: skip
    rs = _ruleset(CASCADE_CRITERIA[:2])
    res = _cascade(_lake(rs, ["V-1"], [_note("V-1")]), lexicon=LEXICON, judge=judge, sample_per_stratum=None)
    t = res.traces["V-1"]
    o = t.outcomes["N-INC-01"]
    assert t.exit_stage is None
    assert ("second_opinion", "Gout flare documented") in judge.calls
    if agree:
        assert (o.status, o.stage, t.tier) == ("pass", "S3", "strong")
        assert res.stage("S4").detail["disagreements"] == 0
    else:
        assert (o.status, o.stage, o.reason, t.tier) == ("unknown", "S4", "S3/S4 disagree", "potential:uncertain")
        assert res.stage("S4").detail["disagreements"] == 1


# ================================================================================================ T-203b S2b cut sets
# D-449 (review of PR #275, HIGH 1): S2b shows the judge only the notes that hold one of its top sentences. A window
# note with none of them is part of the record the models did not read, so a "not met" on that cut set must never
# exclude: it counts as left out (the D-276 guard), on the on-the-fly ranking and on a stored one.
DECISIVE = "Painful swollen red first toe since Monday."
FILLER = "\n".join(f"Routine line {i} of the visit." for i in range(1, 6))


@dataclass
class _Reader:
    """A judge that READS the excerpts: the gout inclusion is met only when the decisive sentence is shown, else a
    confident "not met"; the infection exclusion is absent. Both roles answer alike (the pair agrees)."""

    shown: dict[str, set[str]] = field(default_factory=dict)  # pid -> note ids it was shown
    pid_of: dict[str, str] = field(default_factory=dict)

    def judge(self, *, role: str, criterion_text: str, excerpts: list[dict[str, Any]], **_: Any) -> JudgeReply:
        for e in excerpts:
            self.shown.setdefault(self.pid_of[str(e["did"])], set()).add(str(e["did"]))
        hit = next((e for e in excerpts if "swollen" in str(e["text"])), None)
        ex = hit or excerpts[0]
        if criterion_text == "Gout flare documented":
            verdict = "pass" if hit is not None else "fail"
        else:
            verdict = "fail"  # no infection: the exclusion does not apply
        return JudgeReply(verdict, 0.95, str(ex["text"]), str(ex["date"]), "from the notes", call_id="r1")


@dataclass
class _Toe:
    """On-the-fly embedder: the decisive sentence first (``first``) or last (every other sentence above it)."""

    first: bool
    model: str = "stub-embedder"

    def embed(self, texts: list[str]) -> list[list[float]]:
        def v(s: str) -> list[float]:
            near = ("swollen" in s) == self.first
            return [1.0, 0.0] if near else [0.6, 0.8]

        return [[1.0, 0.0], *[v(s) for s in texts[1:]]]


@dataclass
class _Ranked:
    """A stored-vector source (D-449): ``decisive`` first, ``fillers`` (the decisive sentence never in the top five),
    ``fallback``, ``error``, or ``mixed`` (a fallback for the exclusion's pairs, a fillers ranking for the rest)."""

    kind: str

    def rank(self, pid: str, query: str, notes: Sequence[Any], k: int) -> Any:
        from matching.cascade.s2b_semantic import SourceFallback, SourceRanking

        sents = [s for n in notes for s in n.sents]
        if self.kind == "error":
            raise ConnectionError("vector store down")
        if self.kind == "fallback" or (self.kind == "mixed" and "infection" in query.lower()):
            return SourceFallback("vector store unavailable")
        order = sorted(range(len(sents)), key=lambda i: (("swollen" in sents[i]) != (self.kind == "decisive"), i))
        return SourceRanking(0.9, [(i, 0.9) for i in order[:k]], "m")


def _toe_run(notes: list[dict[str, Any]], pids: list[str], embedder: Any, source: Any) -> tuple[Any, _Reader]:
    lake = _lake(CASCADE_RS, pids, notes)
    judge = _Reader(pid_of={str(n["did"]): str(n["pid"]) for n in notes})
    conf: dict[str, Any] = {"study_id": lake.rs.id, "run_date": INDEX, "index_mode": "single",
                            "population": sorted(lake.s1), "semantics": "v1", "snapshot": None, "lexicon": LEXICON,
                            "absence_semantics": False, "sample_per_stratum": None}  # fmt: skip
    res = run_cascade(lake, lake.rs, CascadeConfig(**conf), judge=judge, embedder=embedder, s2b_source=source)
    return res, judge


@pytest.mark.parametrize("flag", ["off", "on"])
def test_regression_a_ranking_that_cuts_the_decisive_note_never_excludes(
    flag: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's reproduction: two window notes, five filler sentences and one decisive sentence. The on-the-fly
    ranking puts the decisive sentence first and shows both notes (strong); a stored ranking that puts the fillers
    first used to show only the filler note, and the confident "not met" became a hard exclusion at S3. Now the
    unshown note counts as left out: "needs information", never "not matched".

    Since T-710 (D-479) the ranking only orders the reading: with room for the window both notes are shown
    whatever the ranking (first block). The cut of the reproduction needs a budget that holds the first-ranked
    note alone, which is what this test sets for the rest."""
    notes = [_note("T-1", FILLER, offset=-10, did="a"), _note("T-1", DECISIVE, offset=-11, did="b")]
    source = _Ranked("fillers") if flag == "on" else None
    roomy, read = _toe_run(notes, ["T-1"], _Toe(first=True), source)
    assert read.shown["T-1"] == {"a", "b"} and roomy.traces["T-1"].tier == "strong"  # room: nothing is cut
    assert roomy.traces["T-1"].outcomes["N-INC-01"].status == "pass"  # and the answer is the decisive note's
    monkeypatch.setattr(cascade_engine, "EXCERPT_TOKENS", cascade_engine._tokens(FILLER))  # the filler note alone
    res, judge = _toe_run(notes, ["T-1"], _Toe(first=True), source)
    t = res.traces["T-1"]
    o = t.outcomes["N-INC-01"]
    if flag == "off":  # the decisive note is ranked first and read whole; the filler note no longer fits: flagged
        assert o.status == "pass" and "b" in judge.shown["T-1"] and t.tier == "potential:uncertain"
    else:
        assert judge.shown["T-1"] == {"a"} and t.s2b_source is not None and t.s2b_source["vec_pairs"] == 2
        assert t.exit_stage is None and t.tier != "excluded" and not o.hard
        assert (o.status, o.unknown_kind) == ("unknown", "uncertain") and o.reason.startswith("not judged: 1 ")
    # the same cut on the on-the-fly path (master's defect): the decisive sentence ranked last, never shown
    monkeypatch.setattr(cascade_engine, "EXCERPT_TOKENS", cascade_engine._tokens(FILLER + "\nAnother routine line."))
    cut, judge2 = _toe_run([_note("T-2", FILLER + "\nAnother routine line.", offset=-10, did="a2"),
                            _note("T-2", DECISIVE, offset=-11, did="b2")], ["T-2"], _Toe(first=False), None)  # fmt: skip
    t2 = cut.traces["T-2"]
    assert judge2.shown["T-2"] == {"a2"} and t2.exit_stage is None and t2.tier != "excluded"
    assert t2.outcomes["N-INC-01"].status == "unknown"


TOE_PATIENTS: dict[str, list[tuple[str, int]]] = {  # pid -> (text, offset) of its window notes
    "U-1": [(FILLER, -10), (DECISIVE, -11)],  # decisive in the second note
    "U-2": [(DECISIVE, -10), (FILLER, -11)],  # decisive in the first note
    "U-3": [(FILLER, -10), ("One more routine line.\nNothing else.", -12), (DECISIVE, -13)],  # three notes
    "U-4": [(FILLER, -10), ("One more routine line.", -11)],  # no decisive sentence anywhere: may be excluded
    "U-5": [(FILLER + "\n" + DECISIVE, -10)],  # one note
}


@pytest.mark.parametrize(
    ("embedder", "source"),
    [
        pytest.param(_Toe(first=True), None, id="on-the-fly decisive first"),
        pytest.param(_Toe(first=False), None, id="on-the-fly decisive last"),
        *[
            pytest.param(_Toe(first=True), _Ranked(k), id=f"stored {k}")
            for k in ("decisive", "fillers", "fallback", "error", "mixed")
        ],
        pytest.param(_Toe(first=False), _Ranked("mixed"), id="stored mixed over on-the-fly last"),
    ],
)
def test_no_ranking_excludes_a_patient_for_what_it_left_out(embedder: Any, source: Any) -> None:
    """For any S2b ranking, on the fly or stored (including fallbacks, errors and a mix inside one patient's run): a
    patient the full-record judge would not exclude is never excluded, and a patient is excluded only when the judge
    was shown every window note."""
    notes = [_note(pid, text, offset=off, did=f"{pid}-{i}") for pid, ns in TOE_PATIENTS.items()
             for i, (text, off) in enumerate(ns)]  # fmt: skip
    res, judge = _toe_run(notes, sorted(TOE_PATIENTS), embedder, source)
    for pid, ns in TOE_PATIENTS.items():
        t = res.traces[pid]
        full_record_met = any("swollen" in text for text, _ in ns)
        if full_record_met:
            assert t.exit_stage is None and t.tier != "excluded", (pid, t.outcomes)
        if t.tier == "excluded":
            assert judge.shown[pid] == {f"{pid}-{i}" for i in range(len(ns))}, pid
        assert not any(o.hard for o in t.outcomes.values()) or not full_record_met, pid
    if isinstance(source, _Ranked) and source.kind == "mixed":
        recs = [t.s2b_source for t in res.traces.values() if t.s2b_source]
        assert any(r["vec_pairs"] and r["fallback_pairs"] for r in recs)  # a mixed patient-run is recorded as such
