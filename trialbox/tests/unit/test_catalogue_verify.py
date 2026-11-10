"""tools/catalogue_verify.py (D-180): catalogue codes come only from recorded public evidence. No network here."""

from __future__ import annotations

import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from tools import catalogue_verify as cv

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "catalogue_verify"


@pytest.fixture
def cat(tmp_path: Path) -> Path:
    dest = tmp_path / "catalogue"
    shutil.copytree(FIXTURE, dest)
    return dest


def _rows(text: str) -> dict[str, dict[str, str]]:
    return {r[next(iter(r))]: r for r in csv.DictReader(io.StringIO(text))}


def _build(cat: Path) -> dict[str, dict[str, dict[str, str]]]:
    out = cv.build(cv.Paths(cat))
    return {p.name: _rows(text) for p, text in out.items()}


def test_items_adopt_partial_local_and_jlac10(cat: Path) -> None:
    items = _build(cat)["items.csv"]
    kl6 = items["lab.kl6"]
    assert kl6["loinc"] == "93369-7" and kl6["omop_concept_id"] == ""
    assert kl6["licence_notes"] == cv.LOINC_NOTICE and kl6["source"].startswith("LOINC 93369-7; was local:")
    assert kl6["verified"] == "yes" and kl6["code_fit"] == "exact" and kl6["verified_date"] == "2026-11-09"
    assert "'KL-6' (1 hits)" in kl6["verified_note"] and "Krebs von den Lungen-6" in kl6["verified_source"]
    assert kl6["jlac10"] == "" and "not in the MHLW table" in kl6["jlac10_source"]
    cr = items["lab.creatinine"]
    assert cr["verified"] == "yes" and cr["code_fit"] == "exact"
    assert cr["jlac10"] == "3C015000002327101" and "血清クレアチニン" in cr["jlac10_source"]
    vitd = items["lab.vitd"]
    assert vitd["verified"] == "yes" and vitd["code_fit"] == "partial" and vitd["verified_note"] == "D3 only"
    das = items["rheum.das28_esr"]
    assert das["loinc"] == "local" and das["verified"] == "no" and das["code_fit"] == "none"
    assert "'DAS28-ESR' (0 hits), 'DAS28' (0 hits): no LOINC term adopted" in das["verified_note"]


def test_build_is_idempotent(cat: Path) -> None:
    outputs = cv.build(cv.Paths(cat))
    for p, text in outputs.items():
        p.write_text(text, encoding="utf-8")
    assert cv.stale(cv.build(cv.Paths(cat))) == []
    assert cv.main(["build", "--check", "--catalogue", str(cat)]) == 0


def test_check_reports_a_stale_catalogue(cat: Path) -> None:
    assert cv.main(["build", "--check", "--catalogue", str(cat)]) == 1


def _edit_evidence(cat: Path, **changes: object) -> None:
    path = cat / "verification" / "evidence.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_never_adopts_a_code_the_evidence_lacks(cat: Path) -> None:
    data = json.loads((cat / "verification" / "evidence.json").read_text(encoding="utf-8"))
    codes = {k: v for k, v in data["loinc_codes"].items() if k != "93369-7"}
    _edit_evidence(cat, loinc_codes=codes)
    with pytest.raises(cv.CatalogueError, match="adopted LOINC 93369-7 is not in the evidence"):
        cv.build(cv.Paths(cat))
    assert cv.main(["build", "--catalogue", str(cat)]) == 2


def test_a_coded_item_missing_from_the_source_is_not_verified(cat: Path) -> None:
    data = json.loads((cat / "verification" / "evidence.json").read_text(encoding="utf-8"))
    _edit_evidence(cat, loinc_codes={k: v for k, v in data["loinc_codes"].items() if k != "2160-0"})
    cr = _build(cat)["items.csv"]["lab.creatinine"]
    assert cr["verified"] == "no" and "not found" in cr["verified_note"]


def test_search_hits_need_a_reviewed_decision(cat: Path) -> None:
    data = json.loads((cat / "verification" / "evidence.json").read_text(encoding="utf-8"))
    data["loinc_searches"]["DAS28-ESR"] = {"total": 1, "hits": [["0000-0", "something"]]}
    _edit_evidence(cat, loinc_searches=data["loinc_searches"])
    dec = cat / "verification" / "loinc_decisions.csv"
    dec.write_text("\n".join(dec.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(cv.CatalogueError, match="review them in loinc_decisions"):
        cv.build(cv.Paths(cat))


def test_a_retired_local_id_is_never_reused(cat: Path) -> None:
    items = cat / "items.csv"
    items.write_text(
        items.read_text(encoding="utf-8").replace("local,2000001009", "local,2000001002"), encoding="utf-8"
    )
    with pytest.raises(cv.CatalogueError, match="reuses retired local id 2000001002"):
        cv.build(cv.Paths(cat))


def test_jlac10_codes_must_be_in_the_mhlw_evidence(cat: Path) -> None:
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace("3C015000002327101", "3C015000002399901"), encoding="utf-8")
    with pytest.raises(cv.CatalogueError, match="not in the MHLW evidence"):
        cv.build(cv.Paths(cat))


def test_phenotypes_verified_and_translated(cat: Path) -> None:
    built = _build(cat)
    ph = built["phenotypes.csv"]
    assert ph["ph.ra"]["verified"] == "yes" and "858 Pending peer review" in ph["ph.ra"]["verified_note"]
    assert ph["ph.dementia"]["verified"] == "no" and "not ICD-10-CM codes: F00" in ph["ph.dementia"]["verified_note"]
    assert ph["ph.gout_refractory"]["verified"] == "yes"  # ATC M04AA and LOINC are not read as ICD codes
    tr = built["phenotype_icd10cm.csv"]
    assert set(tr) == {"ph.ra", "ph.dementia"}
    ra = tr["ph.ra"]
    assert ra["icd10cm_include"] == "M05;M06" and ra["icd10cm_exclude"] == "M06.1"
    assert ra["icd10cm_billable_codes"] == "331" and ra["codes_verified"] == "yes" and ra["mapping_verified"] == "no"
    assert ra["name_check"].startswith("1 of 2 SNOMED entry concept names") and ra["name_check"].endswith(
        "1 of those inside the include set"
    )
    assert "Rheumatoid arthritis [SNOMED 80809]" in ra["entry_concepts"]
    assert "Athena" in ra["derivation"]


def test_every_linked_phenotype_needs_a_translation(cat: Path) -> None:
    mp = cat / "verification" / "phenotype_icd10cm_map.csv"
    mp.write_text("\n".join(mp.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(cv.CatalogueError, match="no ICD-10-CM translation for: ph.dementia"):
        cv.build(cv.Paths(cat))


def test_translation_codes_must_exist(cat: Path) -> None:
    mp = cat / "verification" / "phenotype_icd10cm_map.csv"
    mp.write_text(mp.read_text(encoding="utf-8").replace("F01;F02", "F00;F02"), encoding="utf-8")
    dem = _build(cat)["phenotype_icd10cm.csv"]["ph.dementia"]
    assert dem["codes_verified"] == "no" and "unknown codes: F00" in dem["note"]


def test_icd_tokens() -> None:
    assert cv.icd_tokens("ICD-10-CM M05.*, M06.* (excl. M06.1, M06.4); MEDIS 'x'") == ["M05", "M06", "M06.1", "M06.4"]
    assert cv.icd_tokens("E11.*; ATC A10; LOINC 4548-4") == ["E11"]
    assert cv.icd_tokens("M10.*, M1A.*") == ["M10", "M1A"]
    assert cv.icd_tokens("C34.* + morphology 8140/8070") == ["C34"]
    assert cv.icd_tokens("I60-I64") == ["I60", "I64"]
    assert cv.icd_tokens("LOINC 98979-8/62238-1/local JSN") == []
    assert cv.search_term("Creatinine, serum (enzymatic)") == "Creatinine serum"


def _fake_get(routes: dict[str, bytes]) -> cv.Getter:
    def get(url: str) -> bytes:
        for key, body in routes.items():
            if key in url:
                return body
        raise AssertionError(f"unexpected url {url}")

    return get


def test_fetch_with_a_fake_network(cat: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cohort = {
        "PrimaryCriteria": {"CriteriaList": [{"ConditionOccurrence": {"CodesetId": 0}}]},
        "ConceptSets": [
            {"id": 0, "name": "Dementia", "expression": {"items": [{"concept": {
                "CONCEPT_ID": 4182210, "VOCABULARY_ID": "SNOMED", "CONCEPT_CODE": "52448006",
                "CONCEPT_NAME": "Dementia", "DOMAIN_ID": "Condition"}, "includeDescendants": True}]}},
            {"id": 1, "name": "Not used at entry", "expression": {"items": [{"concept": {
                "CONCEPT_ID": 1, "VOCABULARY_ID": "RxNorm", "CONCEPT_NAME": "x"}}]}},
        ],
    }  # fmt: skip
    routes = {
        "loinc_items/v3/search?terms=93369-7": json.dumps([1, ["93369-7"], None, [["93369-7", "KL-6 name"]]]).encode(),
        "loinc_items/v3/search": json.dumps([0, [], None, []]).encode(),
        "Cohorts.csv": '﻿"cohortId","cohortName","status"\n33,Dementia,Pending\n858,RA,Pending\n'.encode(),
        "cohorts/33.json": json.dumps(cohort).encode(),
        "cohorts/858.json": json.dumps({"PrimaryCriteria": {}, "ConceptSets": []}).encode(),
        "icd10cm/v3/search?terms=Dementia": json.dumps([1, ["F03.90"], None, [["F03.90", "Dementia"]]]).encode(),
        "icd10cm/v3/search?terms=M05&": json.dumps([2, [], None, [["M05.00", "a"], ["M05.10", "b"]]]).encode(),
        "icd10cm/v3/search": json.dumps([0, [], None, []]).encode(),
    }
    monkeypatch.setattr(cv, "fetch_mhlw", lambda get: {"3C015000002327101": {"name": "血清クレアチニン"}})
    ev = cv.fetch(cv.Paths(cat), "2026-11-09", get=_fake_get(routes), log=lambda _m: None)
    assert ev.loinc_codes == {"93369-7": "KL-6 name"}  # the other codes were not found: never invented
    assert ev.loinc_searches["DAS28"] == {"total": 0, "hits": []}
    assert set(ev.cohorts) == {"33", "858"} and ev.cohorts["858"]["entry_concepts"] == []
    assert [c["concept_id"] for c in ev.cohorts["33"]["entry_concepts"]] == [4182210]
    assert ev.icd10cm_prefixes["M05"]["n"] == 2 and ev.icd10cm_prefixes["F00"]["n"] == 0
    assert ev.icd10cm_names == {"Dementia": ["F03.90"]}
    assert json.loads(ev.dump())["date"] == "2026-11-09"


def test_parse_mhlw_rows() -> None:
    head = ("実施項目", None, None, "区分名称", None, "項目コード（17桁）", "項目名", *[None] * 13)
    row = ("〇", "〇", 10, "生化学検査", 10, "3C015000002327101", "血清クレアチニン", *[None] * 4, "mg/dl", *[None] * 7,
           "1：可視吸光光度法")  # fmt: skip
    got = cv.parse_mhlw_rows([head, row, ("short",)])
    assert got == {"3C015000002327101": {"group": "生化学検査", "name": "血清クレアチニン", "unit": "mg/dl",
                                         "method": "1：可視吸光光度法"}}  # fmt: skip


def test_the_shipped_catalogue_is_up_to_date() -> None:
    assert cv.main(["build", "--check"]) == 0
