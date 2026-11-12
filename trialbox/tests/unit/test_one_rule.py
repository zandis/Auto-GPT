"""The one rule of site set-up (D-131, D-135), safety-critical: a proposed fact (read from a chart by the model, not
yet confirmed by a person) can only send a patient to "needs information". It never excludes and never counts as
met. Once a coordinator confirms it, it is a coded record and counts like one, and may exclude.

Checked on the three runtime paths over one small lake: the SQL engine (NAV, MICROBATCH, CASE, the site set-up's
patient check), the SCREEN cascade at S1, and the feasibility counts.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.flatten import BASIS, DEMOGRAPHIC
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from matching.proposed import PROPOSED_FACT, SUSPECTED_DIAGNOSIS, FactRow, Proposed, signed_atoms, site_basis
from orchestrator.scenarios.evaluate import SqlEngine, structured_verdict
from orchestrator.scenarios.feas_compute import FeasParams, compute
from tb_common.reasons import LABELS, Reason, code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
ICD = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
SNAP = "2026-10-05"
INDEX = date(2026, 10, 5)


def _crit(cid: str, kind: str, text: str, logic: dict[str, Any]) -> CriterionIR:
    return CriterionIR.model_validate({"id": cid, "ruleset": "RULE", "kind": kind, "class": "structured",
                                       "text": text, "logic": logic})  # fmt: skip


CRITERIA = [
    _crit(
        "RULE-INC-01",
        "inclusion",
        "Aged 18 or older",
        {"domain": "demographic", "valueset": "NONE", "age": {"min": 18}},
    ),
    _crit("RULE-INC-02", "inclusion", "Gout", {"domain": "condition", "quantifier": "any", "valueset": "VS_GOUT"}),
    _crit(
        "RULE-INC-03",
        "inclusion",
        "Serum urate >= 7.0 mg/dL in the last year",
        {
            "domain": "observation",
            "quantifier": "latest",
            "valueset": "VS_SERUM_URATE",
            "value": {"op": ">=", "num": 7.0, "unit": "mg/dL"},
            "window": {"anchor": "index", "from_days": -365, "to_days": 0},
        },
    ),
    _crit(
        "RULE-INC-04",
        "inclusion",
        "No malignancy",
        {"domain": "condition", "quantifier": "none", "valueset": "VS_MALIGNANCY"},
    ),
    _crit(
        "RULE-EXC-01",
        "exclusion",
        "Any malignancy",
        {"domain": "condition", "quantifier": "any", "valueset": "VS_MALIGNANCY"},
    ),
]


def _tag(r: dict[str, Any], basis: str | None) -> dict[str, Any]:
    if basis:
        r["meta"] = {"tag": [{"system": BASIS, "code": basis}]}
    return r


def _pat(pid: str, birth: str | None) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "gender": "male", **({"birthDate": birth} if birth else {})}


def _enc(pid: str) -> dict[str, Any]:
    return {"resourceType": "Encounter", "id": f"e-{pid}", "subject": {"reference": f"Patient/{pid}"},
            "period": {"start": "2026-09-01"}, "class": {"code": "AMB"}}  # fmt: skip


def _cond(rid: str, pid: str, code: str, day: str, basis: str | None = None) -> dict[str, Any]:
    cc = {"coding": [{"system": ICD, "code": code}]} if code else {"text": "chart wording"}
    return _tag({"resourceType": "Condition", "id": rid, "subject": {"reference": f"Patient/{pid}"}, "code": cc,
                 "onsetDateTime": day}, basis)  # fmt: skip


def _urate(rid: str, pid: str, value: float, day: str, basis: str | None = None) -> dict[str, Any]:
    return _tag({"resourceType": "Observation", "id": rid, "subject": {"reference": f"Patient/{pid}"},
                 "code": {"coding": [{"system": LOINC, "code": "3084-1"}]}, "effectiveDateTime": day,
                 "valueQuantity": {"value": value, "unit": "mg/dL", "code": "mg/dL"},
                 "category": [{"coding": [{"code": "laboratory"}]}]}, basis)  # fmt: skip


def _demo(rid: str, pid: str, what: str, value: str, basis: str) -> dict[str, Any]:
    return _tag({"resourceType": "Observation", "id": rid, "subject": {"reference": f"Patient/{pid}"},
                 "code": {"coding": [{"system": DEMOGRAPHIC, "code": what}]}, "valueString": value}, basis)  # fmt: skip


def _coded_ok(pid: str) -> list[dict[str, Any]]:
    return [_pat(pid, "1960-01-01"), _enc(pid), _cond(f"g-{pid}", pid, "M10.9", "2026-01-10"),
            _urate(f"u-{pid}", pid, 8.4, "2026-09-01")]  # fmt: skip


PATIENTS: dict[str, list[dict[str, Any]]] = {
    # coded records only: eligible
    "CODED-OK": _coded_ok("CODED-OK"),
    # a chart-only patient: every fact proposed. Nothing counts, nothing excludes: needs information
    "PROP-ONLY": [
        _pat("PROP-ONLY", None),
        _enc("PROP-ONLY"),
        _demo("pd-1", "PROP-ONLY", "birth_date", "1958-04-03", "proposed"),
        _cond("pc-1", "PROP-ONLY", "M10.9", "2026-02-01", "proposed"),
        _urate("pu-1", "PROP-ONLY", 8.4, "2026-09-02", "proposed"),
    ],
    # coded-eligible with a proposed malignancy: not excluded, needs information
    "PROP-EXC": [*_coded_ok("PROP-EXC"), _cond("pc-2", "PROP-EXC", "C50.911", "2026-05-01", "proposed")],
    # the same malignancy, confirmed by a coordinator: it counts like a coded record and excludes
    "CONF-EXC": [*_coded_ok("CONF-EXC"), _cond("cf-1", "CONF-EXC", "C50.911", "2026-05-01", "confirmed")],
    # a chart-only patient whose facts were all confirmed: counted
    "CONF-INC": [
        _pat("CONF-INC", "1958-04-03"),
        _enc("CONF-INC"),
        _demo("cd-1", "CONF-INC", "birth_date", "1958-04-03", "confirmed"),
        _cond("cf-2", "CONF-INC", "M10.9", "2026-02-01", "confirmed"),
        _urate("cf-3", "CONF-INC", 8.4, "2026-09-02", "confirmed"),
    ],
    # a newer proposed urate value could move a decided value criterion either way: needs information
    "PROP-VAL": [*_coded_ok("PROP-VAL"), _urate("pu-2", "PROP-VAL", 5.0, "2026-09-20", "proposed")],
    # a proposed value outside the criterion's window changes nothing
    "PROP-OLD": [*_coded_ok("PROP-OLD"), _urate("pu-3", "PROP-OLD", 5.0, "2024-01-01", "proposed")],
    # a proposed diagnosis of another kind (hypertension) changes nothing
    "PROP-OTHER": [*_coded_ok("PROP-OTHER"), _cond("pc-3", "PROP-OTHER", "I10", "2026-05-01", "proposed")],
    # a proposed diagnosis with no code: it could be anything, so a decided condition answer it could flip is unknown
    "PROP-NOCODE": [*_coded_ok("PROP-NOCODE"), _cond("pc-4", "PROP-NOCODE", "", "2026-05-01", "proposed")],
    # a coded patient with no gout and a proposed gout from a chart: not excluded for lack of gout, needs information
    "PROP-RESCUE": [
        _pat("PROP-RESCUE", "1960-01-01"),
        _enc("PROP-RESCUE"),
        _urate("u-r", "PROP-RESCUE", 8.4, "2026-09-01"),
        _cond("pc-5", "PROP-RESCUE", "M10.9", "2026-03-01", "proposed"),
    ],
}


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    term = Terminology()
    vs = {}
    for name, domain, concept in (("VS_GOUT", "condition", "gout"), ("VS_SERUM_URATE", "observation", "serum urate"),
                                  ("VS_MALIGNANCY", "condition", "malignancy")):  # fmt: skip
        res = term.map(domain, concept)
        vs[name] = valueset("RULE", name, concept, res.concepts, "1.0.0", families=res.families)
    sql = SqlGenerator("RULE", "1.0.0", ValueSets("RULE", vs, term)).render(CRITERIA)
    nd = tmp_path_factory.mktemp("rule-nd")
    by: dict[str, list[dict[str, Any]]] = {}
    for rows_ in PATIENTS.values():
        for r in rows_:
            by.setdefault(r["resourceType"], []).append(r)
    for t, rows in by.items():
        (nd / f"{t}.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    lake_dir = tmp_path_factory.mktemp("rule-lake")
    Lake(lake_dir).rebuild(SNAP, HashEmbedder(), nd)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "RULE", "library": None, "criteria": [c.id for c in CRITERIA]})
    rs = Ruleset(manifest=manifest, criteria=CRITERIA, valuesets=vs, sql=sql)
    return {"lake": LakeLocal(lake_dir, HashEmbedder()), "rs": rs}


def test_a_proposed_fact_never_reaches_a_coded_table(world: dict[str, Any]) -> None:
    lake = world["lake"]
    cond = {r["cid"] for r in lake.query("SELECT cid FROM condition").to_pylist()}
    obs = {r["oid"] for r in lake.query("SELECT oid FROM observation").to_pylist()}
    assert not {"pc-1", "pc-2", "pc-3", "pc-4", "pc-5"} & cond and not {"pu-1", "pu-2", "pu-3", "pd-1"} & obs
    assert {"cf-1", "cf-2"} <= cond and "cf-3" in obs  # confirmed facts are coded records
    assert "cd-1" not in obs  # a demographic fact is only listed (the patient row carries the value)
    facts = {r["fid"]: r["basis"] for r in lake.query("SELECT fid, basis FROM site_fact").to_pylist()}
    assert facts["pc-2"] == "proposed" and facts["cf-1"] == "confirmed" and facts["pd-1"] == "proposed"
    confirmed, proposed = site_basis(lake, None)
    assert confirmed == {"CONF-EXC", "CONF-INC"}
    assert proposed == {"PROP-ONLY", "PROP-EXC", "PROP-VAL", "PROP-OLD", "PROP-OTHER", "PROP-NOCODE", "PROP-RESCUE"}


def test_sql_engine_proposed_facts_only_send_to_needs_information(world: dict[str, Any]) -> None:
    rs = world["rs"]
    ids = [c.id for c in CRITERIA]
    ev = SqlEngine(world["lake"]).evaluate(rs, sorted(PATIENTS), INDEX, ids)
    res = {pid: e.results for pid, e in ev.items()}
    why = {pid: e.reasons or {} for pid, e in ev.items()}
    assert res["CODED-OK"] == {i: (i != "RULE-EXC-01") for i in ids}  # eligible: inclusions TRUE, exclusion FALSE
    # chart only: nothing is met by a proposed fact, nothing excludes; the proposed gout makes "no gout" unknown
    assert res["PROP-ONLY"]["RULE-INC-01"] is None and res["PROP-ONLY"]["RULE-INC-02"] is None
    assert (
        why["PROP-ONLY"]["RULE-INC-02"] == PROPOSED_FACT
        and "pc-1" in (ev["PROP-ONLY"].evidence or {})["RULE-INC-02"][0]
    )
    assert res["PROP-ONLY"]["RULE-INC-03"] is None  # no coded urate: unknown, never met by the proposed one
    # a proposed malignancy: the exclusion is unknown (not TRUE), "no malignancy" is unknown (not FALSE)
    assert res["PROP-EXC"]["RULE-EXC-01"] is None and why["PROP-EXC"]["RULE-EXC-01"] == PROPOSED_FACT
    assert res["PROP-EXC"]["RULE-INC-04"] is None and why["PROP-EXC"]["RULE-INC-04"] == PROPOSED_FACT
    # confirmed: it counts and excludes
    assert res["CONF-EXC"]["RULE-EXC-01"] is True and res["CONF-EXC"]["RULE-INC-04"] is False
    assert not why["CONF-EXC"]
    assert all(v is True for k, v in res["CONF-INC"].items() if k != "RULE-EXC-01") and not why["CONF-INC"]
    assert res["PROP-VAL"]["RULE-INC-03"] is None and why["PROP-VAL"]["RULE-INC-03"] == PROPOSED_FACT
    assert res["PROP-OLD"] == res["CODED-OK"] and not why["PROP-OLD"]  # outside the window
    assert res["PROP-OTHER"] == res["CODED-OK"] and not why["PROP-OTHER"]  # another kind of diagnosis
    assert res["PROP-NOCODE"]["RULE-EXC-01"] is None and res["PROP-NOCODE"]["RULE-INC-02"] is True  # TRUE stays
    assert res["PROP-RESCUE"]["RULE-INC-02"] is None and why["PROP-RESCUE"]["RULE-INC-02"] == PROPOSED_FACT
    # no proposed fact ever turned an answer into a decided one: every changed answer is unknown
    for pid, e in ev.items():
        for cid, reason in (e.reasons or {}).items():
            if reason == PROPOSED_FACT:
                assert e.results[cid] is None, (pid, cid)
    c = next(c for c in CRITERIA if c.id == "RULE-EXC-01")
    v = structured_verdict(c, ev["PROP-EXC"])
    assert v.verdict == "unknown" and v.evidence is not None and v.evidence.reason == Reason.PROPOSED_FACT.value


def test_cascade_s1_never_excludes_on_a_proposed_fact(world: dict[str, Any]) -> None:
    cfg = CascadeConfig(study_id="RULE", run_date=INDEX, index_mode="single", population=sorted(PATIENTS),
                        semantics="v1", snapshot=None)  # fmt: skip
    out = run_cascade(world["lake"], world["rs"], cfg)
    exits = {pid: t.exit_criterion for pid, t in out.traces.items()}
    assert exits["CONF-EXC"] == "RULE-INC-04"  # the confirmed malignancy excludes ("no malignancy" fails first)
    for pid in ("PROP-EXC", "PROP-VAL", "PROP-NOCODE", "PROP-RESCUE", "CODED-OK", "CONF-INC", "PROP-OLD"):
        assert exits[pid] is None, (pid, exits[pid])
    for pid in ("PROP-EXC", "PROP-VAL", "PROP-RESCUE"):
        t = out.traces[pid]
        changed = [o for o in t.outcomes.values() if o.reason == PROPOSED_FACT]
        assert changed and all(not o.hard and o.unknown_kind == "data_gap" for o in changed), pid
    t = out.traces["PROP-EXC"]
    assert t.outcomes["RULE-EXC-01"].status == "pass" and t.outcomes["RULE-INC-04"].status == "unknown"
    assert out.stage("S1").detail["proposed_fact"] >= 3
    assert code_of(PROPOSED_FACT, "unknown", False) == Reason.PROPOSED_FACT


def test_feasibility_never_counts_a_proposed_fact(world: dict[str, Any]) -> None:
    res, raw = compute(world["lake"], world["rs"], FeasParams(run_date=INDEX, snapshot=SNAP, lookback_months=3))
    last = "RULE-EXC-01"
    # counted: the coded patients and the confirmed chart patient; never the proposed-only patient, never the one
    # whose only gout is proposed; the proposed malignancy does not exclude (it is not a coded record either)
    counted = {"CODED-OK", "CONF-INC", "PROP-EXC", "PROP-VAL", "PROP-OLD", "PROP-OTHER", "PROP-NOCODE"}
    assert raw.remaining[last] == len(counted)
    assert raw.remaining["RULE-INC-01"] == len(PATIENTS) - 1  # the chart-only patient has no confirmed birth date
    assert raw.basis[last] == {"coded": len(counted) - 1, "confirmed": 1, "proposed": 2}
    keys = [k.key for k in res.note_keys or []]
    assert "feas.note.basis.confirmed" in keys and "feas.note.basis.proposed" in keys


def test_signed_atoms_and_words() -> None:
    by = {c.id: c for c in CRITERIA}
    assert [s for _, s in signed_atoms(by["RULE-INC-02"].logic)] == ["+"]
    assert [s for _, s in signed_atoms(by["RULE-INC-04"].logic)] == ["-"]
    assert [s for _, s in signed_atoms(by["RULE-INC-03"].logic)] == ["±"]
    neg = CriterionIR.model_validate({"id": "X-INC-01", "ruleset": "X", "kind": "inclusion", "class": "structured",
                                      "text": "no gout", "logic": {"op": "not", "args": [
                                          {"domain": "condition", "valueset": "VS_GOUT"}]}})  # fmt: skip
    assert [s for _, s in signed_atoms(neg.logic)] == ["-"]
    assert set(LABELS[PROPOSED_FACT]) == {"en", "ja", "zh-TW"}


def test_a_lake_built_before_step_5b_has_no_proposed_facts() -> None:
    class OldLake:
        def query(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("lake query failed (422): CatalogException: Table with name site_fact does not exist!")

    assert Proposed.load(OldLake(), None, None).rows == {} and site_basis(OldLake(), None) == (set(), set())

    class Broken:
        def query(self, *_a: Any, **_k: Any) -> Any:
            raise RuntimeError("lake query failed (503)")

    with pytest.raises(RuntimeError):  # any other failure stops the run (D-127): the rule is never dropped silently
        Proposed.load(Broken(), None, None)


# ---------------------------------------------------------------------------------------- T-650 (TB-DR-04 §3.3)
# One test per mutant that survived every safety-core test (ENG-019): the facts are given directly, no lake.
BY = {c.id: c for c in CRITERIA}
EGFR = _crit(
    "RULE-INC-05",
    "inclusion",
    "eGFR >= 60 in the last year",
    {"domain": "observation", "derived": "egfr_ckd_epi", "quantifier": "latest", "valueset": "VS_EGFR",
     "value": {"op": ">=", "num": 60}, "window": {"anchor": "index", "from_days": -365, "to_days": 0}},
)  # fmt: skip


def _facts(*rows: FactRow) -> Proposed:
    return Proposed({"P": list(rows)})


def test_an_undated_proposed_fact_always_counts() -> None:
    """P05: a proposed fact with no date could be in any window: it makes a decided answer it could flip unknown."""
    gout = _facts(FactRow("f-gout", "condition", "M10.9", ICD, None))
    assert gout.refs(BY["RULE-INC-02"], "P", INDEX, False) == ["f-gout"]
    urate = _facts(FactRow("f-urate", "observation", "3084-1", LOINC, None))
    assert urate.refs(BY["RULE-INC-03"], "P", INDEX, True) == ["f-urate"]
    malignancy = _facts(FactRow("f-mal", "condition", "C50.911", ICD, None))
    assert malignancy.refs(BY["RULE-EXC-01"], "P", INDEX, False) == ["f-mal"]
    assert malignancy.refs(BY["RULE-INC-04"], "P", INDEX, True) == ["f-mal"]


@pytest.mark.parametrize(
    ("offset", "counts"),
    [(0, True), (-1, True), (-365, True), (-366, False), (1, False)],
)
def test_a_proposed_fact_on_a_window_bound_counts(offset: int, counts: bool) -> None:
    """P06: the window is closed at both ends: a fact on the index date or on the first day of the window counts;
    one day outside either end does not."""
    day = INDEX + timedelta(days=offset)
    p = _facts(FactRow("f-urate", "observation", "3084-1", LOINC, day))
    want = [f"f-urate|{day.isoformat()}"] if counts else []
    assert p.refs(BY["RULE-INC-03"], "P", INDEX, True) == want
    assert p.refs(BY["RULE-INC-03"], "P", INDEX, False) == want


@pytest.mark.parametrize("what", ["birth_date", "sex"])
def test_a_proposed_birth_date_or_sex_matters_to_a_derived_value(what: str) -> None:
    """P07: eGFR is computed from the age and the sex, so a proposed birth date or sex makes a decided eGFR answer
    unknown, either way; it does not touch a lab value that does not use them."""
    p = _facts(FactRow("f-demo", "demographic", what, "", None))
    assert p.refs(EGFR, "P", INDEX, True) == ["f-demo"] and p.refs(EGFR, "P", INDEX, False) == ["f-demo"]
    assert p.refs(BY["RULE-INC-03"], "P", INDEX, True) == []
    assert p.refs(EGFR, "P", INDEX, None) == []  # an unknown answer stays unknown, with no fact attached


def test_mixed_bases_are_reported_as_proposed_facts() -> None:
    """P12: ``suspected_diagnosis`` only when every fact behind the answer is a suspected diagnosis; a mix with a
    proposed fact is ``proposed_fact``."""
    day = date(2026, 5, 1)
    p = _facts(
        FactRow("f-sus", "condition", "C50.911", ICD, day, "suspected"),
        FactRow("f-pro", "condition", "C50.911", ICD, day, "proposed"),
    )
    refs = p.refs(BY["RULE-EXC-01"], "P", INDEX, False)
    assert refs == ["f-sus|2026-05-01", "f-pro|2026-05-01"]
    assert p.reason("P", refs) == PROPOSED_FACT
    assert p.reason("P", refs[:1]) == SUSPECTED_DIAGNOSIS
    assert p.reason("P", refs[1:]) == PROPOSED_FACT
