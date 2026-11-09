"""Derived scores (dataflow review §4 and P0-5, D-149): units, the same visit, JSN eGFR, and published worked examples,
in the Python reference and in the compiled SQL on a small lake. A missing input or a unit that does not fit is no
value with a reason, never FALSE (D-130).

Worked examples: CKD-EPI 2021 59.3 and 69.2 (review §4.2, verified against public calculators; catalogue
``egfr_ckd_epi_2021.yaml``), JSN 2009 63.1 (catalogue ``egfr_jsn_2009.yaml``, the JSN 早見表) and 59.9 / 40.9 (review),
DAS28-ESR 4.26 and DAS28-CRP 3.99 (review), CDAI 14.5 (review), 27 and 1.5 and SDAI 31 and 1.2 (catalogue
``cdai.yaml`` / ``sdai.yaml``), BMI 22.9 and age at index 65 (review)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract.postprocess import _convert_logic
from criteria_compiler.service import CompilerDeps
from criteria_compiler.terminology.mapper import Concept, Terminology, ValueSets, valueset
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from lake.store import Lake
from matching.cascade.engine import CascadeConfig, run_cascade
from orchestrator.scenarios.evaluate import SqlEngine
from orchestrator.scenarios.screen_cascade import verdicts_of
from tb_common import derived as d
from tb_common.reasons import LABELS, code_of
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionIR

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 11, 9)
LOINC, SCORE = d.LOINC, d.SCORE


# ------------------------------------------------------------------------------------------------ Python reference
@pytest.mark.parametrize(
    ("fn", "args", "expected", "places"),
    [
        (d.egfr_ckd_epi, (1.1, 55, True), 59.3, 1),
        (d.egfr_ckd_epi, (1.2, 60, False), 69.2, 1),
        (d.egfr_jsn, (1.0, 50, False), 63.1, 1),  # catalogue example (JSN 早見表)
        (d.egfr_jsn, (1.0, 60, False), 59.9, 1),
        (d.egfr_jsn, (1.1, 55, True), 40.9, 1),  # the same woman is 59.3 by CKD-EPI: "eGFR >= 45" flips
        (d.das28_esr, (4, 3, 40, 20), 4.26, 2),
        (d.das28_crp, (4, 3, 40, 10), 3.99, 2),
        (d.cdai, (4, 3, 4.0, 3.5), 14.5, 1),
        (d.cdai, (8, 6, 7, 6), 27, 1),
        (d.cdai, (0, 0, 1, 0.5), 1.5, 1),
        (d.sdai, (10, 8, 6, 5, 2.0), 31, 1),
        (d.sdai, (0, 0, 0.5, 0.5, 0.2), 1.2, 1),
        (d.bmi, (70, 175), 22.9, 1),
    ],
)
def test_published_worked_examples(fn: Any, args: tuple[Any, ...], expected: float, places: int) -> None:
    assert round(fn(*args), places) == expected


def test_age_at_index_is_complete_years() -> None:
    assert d.age_at(date(1960, 11, 10), date(2026, 11, 9)) == 65  # the day before the birthday
    assert d.age_at(date(1960, 11, 9), date(2026, 11, 9)) == 66


def _o(value: float | None, unit: str | None, days: int = 0, oid: str = "") -> d.Obs:
    return d.Obs(value, unit, IDX - timedelta(days=days), oid or f"o{days}{unit}{value}")


def test_crp_in_mg_dl_gives_the_same_das28_as_in_mg_l() -> None:
    joints = {"tjc28": [_o(4, None)], "sjc28": [_o(3, "{count}")], "ptga": [_o(40, "mm")]}
    mg_l = d.compute("das28", {**joints, "crp": [_o(10, "mg/L")]})
    mg_dl = d.compute("das28", {**joints, "crp": [_o(1.0, "mg/dL")]})
    assert mg_l.value is not None and mg_dl.value is not None
    assert round(mg_l.value, 2) == round(mg_dl.value, 2) == 3.99
    # before D-149 the 1.0 mg/dL entered as 1.0 mg/L: 3.37 (the review's 3.38 adds terms rounded first), 0.6 low
    assert round(d.das28_crp(4, 3, 40, 1.0), 2) == 3.37


def test_unknown_never_false_missing_unit_spread_and_zero() -> None:
    joints = {"tjc28": [_o(4, None)], "sjc28": [_o(3, None)], "ptga": [_o(40, "mm")]}
    assert d.compute("das28", {**joints, "crp": [_o(1.0, "mmol/L")]}).reason == "derived_unit:crp"
    assert d.compute("das28", {**joints, "crp": [_o(1.0, None)]}).reason == "derived_unit:crp"  # a chart value
    # a CRP drawn 30 days from the joint count is not the same visit: no value, not a DAS28 of two visits
    assert d.compute("das28", {**joints, "crp": [_o(1.0, "mg/dL", days=30)]}).reason == "derived_missing_input:crp"
    assert d.compute("das28", {**joints, "crp": [_o(1.0, "mg/dL", days=7)]}).value is not None
    assert d.compute("das28", {**joints, "esr": [_o(0, "mm/h")]}).reason == "derived_missing_input:esr"  # ln(0)
    no_ptga = {"tjc28": joints["tjc28"], "sjc28": joints["sjc28"], "crp": [_o(10, "mg/L")]}
    assert d.compute("das28", no_ptga).reason == "derived_missing_input:ptga"
    assert d.compute("egfr_jsn", {"creatinine": [_o(1.0, "mg/dL")]}, age=60).reason == "derived_missing_input:sex"
    umol = d.compute("egfr_ckd_epi", {"creatinine": [_o(97.24, "µmol/L")]}, age=55, female=True)
    assert umol.value is not None and round(umol.value, 1) == 59.3


def test_the_site_chooses_the_equation_and_a_protocol_may_name_it() -> None:
    assert d.egfr_for_site(d.country_of("Asia/Tokyo")) == "egfr_jsn"
    assert d.egfr_for_site(d.country_of("Asia/Taipei")) == "egfr_ckd_epi"
    assert d.egfr_for_site(d.country_of(None, "ja")) == "egfr_jsn"
    deps = CompilerDeps(None, None, None, None, {}, tz="Asia/Tokyo")  # type: ignore[arg-type]
    assert deps.egfr() == "egfr_jsn"
    assert CompilerDeps(None, None, None, None, {}, tz="Asia/Taipei").egfr() == "egfr"  # type: ignore[arg-type]
    plain = {"domain": "observation", "derived": "egfr", "quantifier": "latest"}
    assert _convert_logic(plain, {}, "egfr_jsn")["derived"] == "egfr_jsn"
    assert _convert_logic(plain, {}, "egfr_jsn")["valueset"] == "VS_EGFR_JSN_COMPONENTS"
    named = {**plain, "derived": "egfr_ckd_epi"}  # the protocol named CKD-EPI: a Japanese site keeps it
    assert _convert_logic(named, {}, "egfr_jsn")["derived"] == "egfr_ckd_epi"


# ------------------------------------------------------------------------------------------------ the compiled SQL
def _pat(pid: str, birth: str, sex: str) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": pid, "birthDate": birth, "gender": sex}


def _obs(pid: str, n: int, system: str, code: str, value: float, unit: str | None, days: int = 0) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value}
    if unit is not None:
        q.update({"unit": unit, "code": unit})
    on = (IDX - timedelta(days=10 + days)).isoformat()
    return {"resourceType": "Observation", "id": f"{pid}-{n}", "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": system, "code": code}]}, "effectiveDateTime": f"{on}T09:00:00+09:00",
            "valueQuantity": q}  # fmt: skip


def _das(pid: str, marker: tuple[str, float, str | None, int] | None, ptga: bool = True) -> list[dict[str, Any]]:
    out = [_obs(pid, 1, SCORE, "TJC28", 4, ""), _obs(pid, 2, SCORE, "SJC28", 3, None)]
    if ptga:
        out.append(_obs(pid, 3, SCORE, "PTGA", 40, "mm"))
    if marker is not None:
        kind, value, unit, days = marker
        out.append(_obs(pid, 4, LOINC, "4537-7" if kind == "esr" else "1988-5", value, unit, days))
    return out


PATIENTS = {
    # eGFR: female 55 Cr 1.1 / male 60 Cr 1.2 / male 60 Cr 1.0 / the woman in µmol/L / a sheet value with no unit
    "P-F55": (_pat("P-F55", "1971-01-01", "female"), [_obs("P-F55", 1, LOINC, "2160-0", 1.1, "mg/dL")]),
    "P-M60": (_pat("P-M60", "1966-01-01", "male"), [_obs("P-M60", 1, LOINC, "2160-0", 1.2, "mg/dL")]),
    "P-M60J": (_pat("P-M60J", "1966-01-01", "male"), [_obs("P-M60J", 1, LOINC, "2160-0", 1.0, "mg/dL")]),
    "P-UMOL": (_pat("P-UMOL", "1971-01-01", "female"), [_obs("P-UMOL", 1, LOINC, "2160-0", 97.24, "umol/L")]),
    "P-NOUNIT": (_pat("P-NOUNIT", "1971-01-01", "female"), [_obs("P-NOUNIT", 1, LOINC, "2160-0", 1.1, None)]),
    # DAS28
    "D-ESR": (_pat("D-ESR", "1970-01-01", "female"), _das("D-ESR", ("esr", 20, "mm/h", 0))),
    "D-MGL": (_pat("D-MGL", "1970-01-01", "female"), _das("D-MGL", ("crp", 10, "mg/L", 2))),
    "D-MGDL": (_pat("D-MGDL", "1970-01-01", "female"), _das("D-MGDL", ("crp", 1.0, "mg/dL", 2))),
    "D-FAR": (_pat("D-FAR", "1970-01-01", "female"), _das("D-FAR", ("crp", 1.0, "mg/dL", 30))),
    "D-BADUNIT": (_pat("D-BADUNIT", "1970-01-01", "female"), _das("D-BADUNIT", ("crp", 1.0, "mmol/L", 0))),
    "D-NOPTGA": (_pat("D-NOPTGA", "1970-01-01", "female"), _das("D-NOPTGA", ("crp", 10, "mg/L", 0), ptga=False)),
    # BMI and age at index
    "B-1": (
        _pat("B-1", "1960-11-10", "male"),
        [_obs("B-1", 1, LOINC, "29463-7", 70, "kg"), _obs("B-1", 2, LOINC, "8302-2", 1.75, "m")],
    ),
}


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    tmp = tmp_path_factory.mktemp("derived")
    nd = tmp / "nd"
    nd.mkdir()
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps(p) for p, _ in PATIENTS.values()) + "\n")
    obs = [o for _, os in PATIENTS.values() for o in os]
    (nd / "Observation.ndjson").write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in obs) + "\n")
    Lake(tmp / "lake", "Asia/Tokyo").rebuild("2026-11-09", HashEmbedder(), nd)
    return LakeLocal(tmp / "lake", HashEmbedder(), "Asia/Tokyo")


def _crit(cid: str, derived: str | None, op: str | None = None, num: float | None = None, kind: str = "inclusion",
          days: int = 365, age_min: int | None = None) -> CriterionIR:  # fmt: skip
    if derived is None:
        logic: dict[str, Any] = {"domain": "demographic", "valueset": "NONE", "age": {"min": age_min}}
    else:
        logic = {"domain": "observation", "derived": derived, "quantifier": "latest",
                 "valueset": f"VS_{derived.upper()}_COMPONENTS",
                 "window": {"anchor": "index", "from_days": -days, "to_days": 0}}  # fmt: skip
        if op is not None:
            logic["value"] = {"op": op, "num": num}
    return CriterionIR.model_validate({"id": cid, "ruleset": "DER", "kind": kind, "class": "structured",
                                       "text": cid, "logic": logic})  # fmt: skip


def _vs(derived: str) -> dict[str, Any]:
    concepts = [Concept(*d.CODES[c], c) for c in d.COMPONENTS[derived]]
    return valueset("DER", f"VS_{derived.upper()}_COMPONENTS", derived, concepts, "1.0.0")


def _run(lake: LakeLocal, crits: list[CriterionIR]) -> dict[str, dict[str, Any]]:
    vs = {f"VS_{s.upper()}_COMPONENTS": _vs(s) for s in d.COMPONENTS}
    sql = SqlGenerator("DER", "1.0.0", ValueSets("DER", vs, Terminology())).render(crits)
    rows = lake.query(sql, [[IDX.isoformat()], list(PATIENTS)]).to_pylist()
    return {r["pid"]: r for r in rows}


def _value_between(lake: LakeLocal, derived: str, lo: float, hi: float, days: int = 365) -> dict[str, Any]:
    rows = _run(lake, [_crit("DER-INC-01", derived, ">=", lo, days=days), _crit("DER-INC-02", derived, "<", hi,
                                                                                 days=days)])  # fmt: skip
    return {p: (r["C_DER-INC-01"] and r["C_DER-INC-02"]) if r["C_DER-INC-01"] is not None else None
            for p, r in rows.items()}  # fmt: skip


def test_sql_egfr_equations_match_the_worked_examples(lake: LakeLocal) -> None:
    ckd = _value_between(lake, "egfr_ckd_epi", 59.25, 59.35)
    assert ckd["P-F55"] is True and ckd["P-UMOL"] is True and ckd["P-NOUNIT"] is None
    assert _value_between(lake, "egfr_ckd_epi", 69.15, 69.25)["P-M60"] is True
    assert _value_between(lake, "egfr", 69.15, 69.25)["P-M60"] is True  # a stored plain egfr stays CKD-EPI 2021
    jsn = _value_between(lake, "egfr_jsn", 40.85, 40.95)
    assert jsn["P-F55"] is True and jsn["P-UMOL"] is True
    assert _value_between(lake, "egfr_jsn", 59.85, 59.95)["P-M60J"] is True
    # "eGFR >= 45": the same woman passes by CKD-EPI and fails by JSN
    rows = _run(lake, [_crit("DER-INC-01", "egfr_ckd_epi", ">=", 45), _crit("DER-INC-02", "egfr_jsn", ">=", 45)])
    assert (rows["P-F55"]["C_DER-INC-01"], rows["P-F55"]["C_DER-INC-02"]) == (True, False)


def test_sql_das28_units_and_visits(lake: LakeLocal) -> None:
    esr = _value_between(lake, "das28", 4.255, 4.265, days=90)
    assert esr["D-ESR"] is True
    crp = _value_between(lake, "das28", 3.985, 3.995, days=90)
    assert crp["D-MGL"] is True and crp["D-MGDL"] is True  # mg/dL converted: the same DAS28
    rows = _run(lake, [_crit("DER-INC-01", "das28", ">", 3.2, days=90),
                       _crit("DER-EXC-01", "das28", ">", 3.2, kind="exclusion", days=90)])  # fmt: skip
    for pid, why in (("D-FAR", "derived_missing_input:crp"), ("D-BADUNIT", "derived_unit:crp"),
                     ("D-NOPTGA", "derived_missing_input:ptga")):  # fmt: skip
        assert rows[pid]["C_DER-INC-01"] is None and rows[pid]["C_DER-EXC-01"] is None, pid  # never FALSE
        assert rows[pid]["E_DER-INC-01"] == why, pid


def test_sql_bmi_converts_metres_and_age_is_complete_years(lake: LakeLocal) -> None:
    assert _value_between(lake, "bmi", 22.85, 22.87)["B-1"] is True
    rows = _run(lake, [_crit("DER-INC-01", None, age_min=65), _crit("DER-INC-02", None, age_min=66)])
    assert (rows["B-1"]["C_DER-INC-01"], rows["B-1"]["C_DER-INC-02"]) == (True, False)


def _ruleset(crits: list[CriterionIR]) -> Ruleset:
    vs = {"VS_DAS28_COMPONENTS": _vs("das28")}
    sql = SqlGenerator("DER", "1.0.0", ValueSets("DER", vs, Terminology())).render(crits)
    base = Ruleset.load(ROOT / "rulesets" / "GOUT-COH").manifest
    manifest = base.model_copy(update={"id": "DER", "library": None, "criteria": [c.id for c in crits]})
    return Ruleset(manifest=manifest, criteria=crits, valuesets=vs, sql=sql)


def test_engines_say_why_and_never_exclude(lake: LakeLocal) -> None:
    inc = _crit("DER-INC-01", "das28", ">", 3.2, days=90)
    exc = _crit("DER-EXC-01", "das28", ">", 5.1, kind="exclusion", days=90)
    rs = _ruleset([inc, exc])
    ev = SqlEngine(lake).evaluate(rs, ["D-BADUNIT", "D-FAR", "D-MGDL"], IDX, [inc.id, exc.id])
    assert ev["D-BADUNIT"].reasons == {inc.id: "derived_unit", exc.id: "derived_unit"}
    assert ev["D-FAR"].reasons == {inc.id: "derived_missing_input", exc.id: "derived_missing_input"}
    assert (ev["D-BADUNIT"].evidence or {})[inc.id] == []  # the reason is not shown as a record
    assert ev["D-MGDL"].results == {inc.id: True, exc.id: False} and not ev["D-MGDL"].reasons
    pids = ["D-BADUNIT", "D-FAR", "D-MGDL"]
    cfg = CascadeConfig(study_id="DER", run_date=IDX, lookback_months=36, index_mode="single", purpose="screening",
                        step_id="der", snapshot=None, population=pids, note_block=False,
                        absence_semantics=False)  # fmt: skip
    res = run_cascade(lake, rs, cfg, judge=None, embedder=HashEmbedder(), reviewer=None)
    bad = res.traces["D-BADUNIT"].outcomes
    assert bad[inc.id].status == "unknown" and bad[inc.id].reason == "derived_unit" and not bad[inc.id].hard
    assert bad[exc.id].status == "pass" and bad[exc.id].reason == "derived_unit"  # an unknown exclusion keeps them
    assert res.traces["D-FAR"].outcomes[inc.id].reason == "derived_missing_input"
    assert verdicts_of(rs, res.traces["D-BADUNIT"]).tier != "excluded"
    assert code_of("derived_unit") == "derived_unit" and set(LABELS["derived_unit"]) == {"en", "ja", "zh-TW"}


def test_cql_names_the_equation_and_translates() -> None:
    vs = {f"VS_{s.upper()}_COMPONENTS": _vs(s) for s in ("egfr_jsn", "das28")}
    crits = [_crit("DER-INC-01", "egfr_jsn", ">=", 45), _crit("DER-INC-02", "das28", ">", 3.2, days=90)]
    gen = CqlGenerator("DER", "1.0.0", ValueSets("DER", vs, Terminology()))
    cql = gen.render(crits)
    common = render_common()
    assert "TB.EGFRJSN(" in cql and 'TB."Conv_creatinine"' in cql and "TB.SameVisit(X" in cql
    assert "when 'mg/dl' then \"ObsValue\"(O) * 10.0" in common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source

    if not available():
        pytest.skip("cql-translator jars not available on the host (.cache/jvm)")
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": common, gen.library: cql})
    assert gen.library in tr.elm and "TB_Common" in tr.elm


def test_a_feed_result_without_a_unit_takes_the_declared_default(tmp_path: Path) -> None:
    """Owner decision (D-144, D-149): a feed's analyte has the site's declared unit; a sheet or chart has none."""
    from adapter.pipeline import UNIT_SOURCE, _bulk_unit_defaults, apply_unit_defaults

    mapping = tmp_path / "site.yaml"
    mapping.write_text('version: 1\nunit_defaults: {"1988-5": mg/dL}\n', encoding="utf-8")
    defaults = _bulk_unit_defaults(mapping)
    feed = [
        _obs("P", 1, LOINC, "1988-5", 1.0, None),
        _obs("P", 2, LOINC, "1988-5", 10, "mg/L"),
        _obs("P", 3, LOINC, "2160-0", 1.0, None),
    ]
    assert apply_unit_defaults(feed, defaults) == 1
    assert feed[0]["valueQuantity"]["code"] == "mg/dL" and feed[0]["meta"]["tag"][0]["system"] == UNIT_SOURCE
    assert feed[1]["valueQuantity"]["code"] == "mg/L"  # a unit the row has is never replaced
    assert "unit" not in feed[2]["valueQuantity"]  # no declared default for this analyte: stays unknown
    assert d.convert("crp", 1.0, feed[0]["valueQuantity"]["code"]) == (10.0, None)
