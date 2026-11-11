"""T-619a (D-417; STD-011, STD-017, STD-070): standards conformance.

TW Core slices from the TW mapping, the instants written in the site's offset at ingest, the CQL comparator on
censored results, the rule files of both IGs and the parts of the CI checks that need no JVM. The HL7 validator run
(``tools/twcore_check.py``) and the CQL engine run (``tools/cql_path_check.py``) are the CI job ``standards``; the
edge-case run is here too when the local CQL engine is fetched.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from adapter.instants import site_instant, to_site_offset
from adapter.mapping.engine import Mapper, Mapping
from adapter.validate.validator import Hl7Validator
from criteria_compiler.compile_cql.generator import cmp_expr
from criteria_compiler.equivalence import edge
from tb_contracts import Atom

from tools import cql_eval, jpcore_rules, twcore_check

ROOT = Path(__file__).resolve().parents[2]
TW = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
JP = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
CS = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/"
UTC8 = ZoneInfo("Etc/GMT-8")


def _one(m: Mapping, rtype: str, table: str, row: dict[str, Any]) -> dict[str, Any]:
    mapper = Mapper(m, b"k" * 32, "S1")
    return next(r for r in mapper.map_table(table, iter([row])) if r["resourceType"] == rtype)


def _systems(codings: list[dict[str, Any]]) -> list[str]:
    return [str(c.get("system")) for c in codings]


# ------------------------------------------------------------------ STD-011: TW Core slices from the mapping
def test_a_diagnosis_takes_the_icd10_cm_tw_edition_of_its_date() -> None:
    m = Mapping.load(TW)
    row = {"diag_no": "D1", "enc_no": "E1", "mrn": "1", "icd10": "E11.9", "status": "A"}
    old = _one(m, "Condition", "diagnosis", {**row, "diag_date": "2024-12-31"})
    new = _one(m, "Condition", "diagnosis", {**row, "diag_date": "2025/01/01"})
    assert _systems(old["code"]["coding"]) == ["http://hl7.org/fhir/sid/icd-10-cm", CS + "icd-10-cm-2014-tw"]
    assert _systems(new["code"]["coding"]) == ["http://hl7.org/fhir/sid/icd-10-cm", CS + "icd-10-cm-2023-tw"]
    assert {c["code"] for c in new["code"]["coding"]} == {"E11.9"}  # the lake reads coding[0], unchanged
    undated = _one(m, "Condition", "diagnosis", {**row, "diag_date": ""})
    assert _systems(undated["code"]["coding"]) == ["http://hl7.org/fhir/sid/icd-10-cm"]


def test_drug_service_department_and_identifier_fill_their_slices() -> None:
    m = Mapping.load(TW)
    rx = _one(
        m,
        "MedicationRequest",
        "medication",
        {"rx_no": "M1", "mrn": "1", "nhi_drug_code": "AC00011100", "atc": "C10AA05", "drug_name": "x",
         "order_date": "2026-08-01", "start_date": "2026-08-01", "end_date": "2026-08-28", "status": "active",
         "daily_dose": "20", "dose_unit": "mg"},
    )  # fmt: skip
    codings = rx["medicationCodeableConcept"]["coding"]
    assert codings[0]["system"].endswith("/nhi-drug") and codings[-1] == {"system": CS + "medication-nhi-tw",
                                                                           "code": "AC00011100"}  # fmt: skip
    # T-616 reads the therapy period from boundsPeriod first; the mapping writes it, the same as the validity period
    bounds = rx["dosageInstruction"][0]["timing"]["repeat"]["boundsPeriod"]
    assert bounds == rx["dispenseRequest"]["validityPeriod"] == {"start": "2026-08-01", "end": "2026-08-28"}
    proc = _one(
        m, "Procedure", "procedure", {"proc_no": "P1", "mrn": "1", "order_code": "75613B", "proc_date": "2025-02-23"}
    )
    assert _systems(proc["code"]["coding"])[1] == CS + "medical-service-payment-tw"
    enc = {"enc_no": "E1", "mrn": "1", "visit_datetime": "2026-01-07 12:40:00", "staff_id": "P1", "enc_type": "OPD"}
    onc = _one(m, "Encounter", "encounter", {**enc, "dept_code": "ONC"})
    assert onc["serviceType"]["coding"][1] == {"system": CS + "medical-consultation-department-nhi-tw", "code": "AF"}
    # the other departments are SNOMED CT coded in TW Core, which TrialBox does not ship: local coding only
    assert len(_one(m, "Encounter", "encounter", {**enc, "dept_code": "RHEU"})["serviceType"]["coding"]) == 1
    pat = _one(m, "Patient", "patient", {"mrn": "1", "sex": "F", "birth_date": "1960-01-01"})
    assert pat["identifier"][0]["type"]["coding"][0]["code"] == "ANON"  # a pseudonym, never the record number


def test_the_japan_mapping_carries_no_tw_core_coding() -> None:
    m = Mapping.load(JP)
    assert m.fhir_profiles == "jp-core"
    cond = _one(m, "Condition", "diagnosis",
                {"diag_no": "D1", "mrn": "1", "icd10": "E11.9", "icd10cm": "E11.9", "diag_date": "2024-01-01"})  # fmt: skip
    rx = _one(m, "MedicationRequest", "medication",
              {"rx_no": "M1", "mrn": "1", "nhi_drug_code": "620004422", "order_date": "2026-08-01",
               "daily_dose": "1", "dose_unit": "tab"})  # fmt: skip
    text = json.dumps([cond, rx])
    assert "twcore.mohw.gov.tw/ig/twcore/CodeSystem" not in text and "ANON" not in text


# ------------------------------------------------------------------ STD-070: one offset at ingest
def test_an_instant_is_written_in_the_site_offset_and_keeps_its_moment() -> None:
    assert site_instant("2026-04-07T23:30:00Z", UTC8) == "2026-04-08T07:30:00+08:00"
    assert site_instant("2026-04-25T10:30:00+09:00", UTC8) == "2026-04-25T09:30:00+08:00"
    assert site_instant("2026-04-25T10:30+09:00", UTC8) == "2026-04-25T09:30+08:00"
    assert site_instant("2026-04-07T23:30:00.123Z", UTC8) == "2026-04-08T07:30:00.123+08:00"
    for same in ("2026-04-25T10:30:00+08:00", "2026-04-25", "2026-04", "2026-04-25T10:30:00", "not a date", "75 H"):
        assert site_instant(same, UTC8) == same


def test_to_site_offset_walks_every_resource_and_counts() -> None:
    rs = edge.resources()
    n = to_site_offset(rs, UTC8)
    assert n == 1  # the one UTC time stamp; the others were stated in the site offset already
    obs = next(r for r in rs if r["id"] == "edge-utc-alt")
    assert obs["effectiveDateTime"] == "2026-04-08T07:30:00+08:00"


# ------------------------------------------------------------------ CR-001 / CR-098: the CQL comparator
def test_cql_compares_a_censored_result_as_the_sql_does() -> None:
    atom = Atom.model_validate(
        {"domain": "observation", "valueset": "VS_ALT", "value": {"op": ">", "num": 120, "unit": "U/L"}}
    )
    plain = cmp_expr(atom, "V")
    assert plain == "(V > 120)"
    c = cmp_expr(atom, "V", censor="C")
    assert "when C in { '<', '<=' } then (if V <= 120 then false else null)" in c
    assert "when C in { '>', '>=' } then (if V > 120 then true else null)" in c
    assert c.endswith(f"else {plain} end)")  # no comparator, or "ad": the plain comparison
    shipped = (ROOT / "rulesets/GZQO/cql/TB_GZQO_v1_0.cql").read_text(encoding="utf-8")
    assert ".comparator.value in { '<', '<=' }" in shipped


def test_the_edge_fixture_is_synthetic_and_covers_both_edges() -> None:
    want = edge.expected()
    assert set(want.values()) == {True, False, None}
    assert any(when.endswith("Z") for when, *_ in edge.CASES.values())
    assert {c for _, _, c, _ in edge.CASES.values()} >= {"<", ">"}
    assert date(2026, 10, 5) == edge.INDEX_DATE


@pytest.mark.skipif(not cql_eval.available(), reason="local CQL engine not fetched (python -m tools.cql_eval --fetch)")
def test_sql_and_cql_agree_on_the_edge_fixture() -> None:
    from tools import cql_path_check

    out = cql_path_check.edge()
    assert not out["problems"], out["problems"]
    assert out["site_offset"]["sql"] == out["site_offset"]["cql"] == edge.expected()
    assert out["as_sent"]["disagreements"] == [("edge-utc", None, True)]


# ------------------------------------------------------------------ STD-011 / STD-017: the rule files
def test_the_tw_core_rule_file_is_the_pinned_package_and_ships_no_snomed_codes() -> None:
    rules = json.loads((ROOT / "services/adapter/validate/twcore_rules.json").read_text(encoding="utf-8"))
    assert rules["package"]["id"] == "tw.gov.mohw.twcore" and rules["package"]["version"] == "1.0.0"
    pins = (ROOT / "tools/fhir-packages.sha256").read_text(encoding="utf-8")
    assert f"{rules['package']['sha256']}  tw.gov.mohw.twcore#1.0.0" in pins
    cond = rules["profiles"]["https://twcore.mohw.gov.tw/ig/twcore/StructureDefinition/Condition-twcore"]
    assert {e.get("sliceName") for e in cond["elements"]} >= {"icd10-cm-2014", "icd10-cm-2023"}
    for vs in rules["valuesets"].values():
        assert "http://snomed.info/sct" not in (vs["codes"] or {})


def test_the_rule_diff_lists_profiles_elements_and_valuesets() -> None:
    old = {"profiles": {"u1": {"name": "A", "base": "b", "elements": [{"id": "A.x", "path": "A.x", "min": 0}]},
                        "u2": {"name": "B", "base": "b", "elements": []}},
           "valuesets": {"v1": {"systems": ["s"], "codes": None}}}  # fmt: skip
    new = {"profiles": {"u1": {"name": "A", "base": "c", "elements": [{"id": "A.x", "path": "A.x", "min": 1},
                                                                      {"id": "A.y", "path": "A.y", "min": 1}]}},
           "valuesets": {"v2": {"systems": ["s"], "codes": None}}}  # fmt: skip
    got = jpcore_rules.diff(old, new)
    assert "- profile u2" in got and "~ A: parent b -> c" in got and "+ A A.y" in got and "~ A A.x: min" in got
    assert "+ valueset v2" in got and "- valueset v1" in got
    assert jpcore_rules.IGS["jp"][1] == "1.1.0" and "1.2.0" in jpcore_rules.IGS["jp"][0]


# ------------------------------------------------------------------ the HL7 validator job's own logic
def test_the_validator_result_names_the_elements_no_slice_matched() -> None:
    doc = {"resourceType": "Bundle", "entry": [{"resource": {
        "resourceType": "OperationOutcome",
        "extension": [{"url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-file",
                       "valueString": "r00003-Condition.json"}],
        "issue": [{"severity": "information", "expression": ["Condition.code.coding[0]"],
                   "details": {"text": "This element does not match any known slice defined in the profile X"}},
                  {"severity": "warning", "expression": ["Condition.code.coding[1].code"],
                   "details": {"text": "Unknown Code 'N18.30'"}}]}}]}  # fmt: skip
    res = Hl7Validator._parse(doc, 4)
    assert res.errors == 0 and res.unsliced == {3: ["Condition.code.coding[0]"]}


def test_the_validator_sample_takes_slice_carriers_first() -> None:
    def cond(i: int, tw: bool) -> dict[str, Any]:
        codings = [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9"}]
        if tw:
            codings.append({"system": CS + "icd-10-cm-2014-tw", "code": "E11.9"})
        return {"resourceType": "Condition", "id": f"c{i}", "code": {"coding": codings}}

    pool = [cond(i, i == 37) for i in range(60)] + [{"resourceType": "Patient", "id": f"p{i}"} for i in range(60)]
    picked = twcore_check.choose(pool, 10)
    assert len(picked) == 10 and picked[0]["id"] == "c37"
    assert {r["resourceType"] for r in picked} == {"Condition", "Patient"}
