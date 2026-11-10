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
    assert (
        ph["ph.dementia"]["verified"] == "no"
        and "(WHO ICD-10 only, or a range category ICD-10-CM lacks): F00" in ph["ph.dementia"]["verified_note"]
    )
    assert ph["ph.gout_refractory"]["verified"] == "yes"  # ATC M04AA and LOINC are not read as ICD codes
    tr = built["phenotype_icd10cm.csv"]
    assert set(tr) == {"ph.ra", "ph.dementia"}
    ra = tr["ph.ra"]
    assert ra["icd10cm_include"] == "M05;M06" and ra["icd10cm_exclude"] == "M06.1"
    assert ra["icd10cm_billable_codes"] == "331" and ra["codes_verified"] == "yes" and ra["mapping_verified"] == "no"
    assert ra["name_check"].startswith("1 of 2 SNOMED entry concept names") and ra["name_check"].endswith(
        "1 of those inside the include set"
    )
    assert "[SNOMED, OMOP concept 80809]" in ra["entry_concepts"]  # not a SNOMED CT code
    assert "Rheumatoid arthritis" not in ra["entry_concepts"]  # SNOMED CT names are licensed text: ids only
    assert "Athena" in ra["derivation"] and ra["may_exclude"] == "no"
    assert ph["ph.breast_cancer"]["verified"] == "no" and "ICD-O-3 C50" in ph["ph.breast_cancer"]["verified_note"]
    assert ph["ph.local_only"]["verified"] == "no" and "no code in `codes`" in ph["ph.local_only"]["verified_note"]
    assert ph["ph.tb"]["verified"] == "no" and "A16" in ph["ph.tb"]["verified_note"]  # a range: every category checked
    # phenotype codes have no per-code fit review yet: no phenotype may exclude
    assert {v["may_exclude"] for v in ph.values()} == {"no"}


def test_phenotype_codes_outside_icd_must_be_found(cat: Path) -> None:
    _edit_evidence(cat, atc={})
    gout = _build(cat)["phenotypes.csv"]["ph.gout_refractory"]
    assert gout["verified"] == "no" and gout["may_exclude"] == "no"
    assert "not verified: ATC M04AA (not found in the source)" in gout["verified_note"]


def _codes(cat: Path) -> dict[tuple[str, str, str, str], dict[str, str]]:
    text = cv.build(cv.Paths(cat))[cat / "codes_checked.csv"]
    return {(r["file"], r["row"], r["field"], r["code"]): r for r in csv.DictReader(io.StringIO(text))}


def test_every_code_is_registered_with_its_source(cat: Path) -> None:
    codes = _codes(cat)
    assert codes[("phenotypes.csv", "ph.tb", "codes", "A16")]["verified"] == "no"
    assert codes[("phenotypes.csv", "ph.tb", "codes", "A17")]["verified"] == "yes"
    cr = codes[("items.csv", "lab.creatinine", "loinc", "2160-0")]
    assert cr["verified"] == "yes" and cr["source"] == cv.SRC_LOINC and cr["may_exclude"] == "yes"
    assert cr["name_in_source"] == "Creatinine [Mass/volume] in Serum or Plasma" and cr["verified_date"] == "2026-11-09"
    assert codes[("items.csv", "lab.creatinine", "jlac10", "3C015000002327101")]["may_exclude"] == "yes"
    side = codes[("items.csv", "lab.creatinine", "source", "14682-9")]
    assert side["verified"] == "yes" and side["use"] == "text" and side["may_exclude"] == "no"
    vitd = codes[("items.csv", "lab.vitd", "loinc", "1989-3")]
    assert vitd["verified"] == "yes" and vitd["may_exclude"] == "no"  # a partial fit never excludes
    haq = codes[("items.csv", "rheum.haq_di", "cdisc_qrs", "HAQ01TC")]
    assert haq["verified"] == "yes" and haq["name_in_source"].startswith("C106667 Health Assessment")
    assert haq["use"] == "reference" and haq["may_exclude"] == "no"  # a codelist is not a patient fact
    assert codes[("items.csv", "rheum.haq_di", "cdisc_qrs", "HAQ99TC")]["verified"] == "no"
    typo = codes[("items.csv", "rheum.haq_di", "source", "1234-5")]
    assert typo["verified"] == "no" and typo["note"] == "the LOINC check digit is wrong"
    gout = codes[("phenotypes.csv", "ph.gout_refractory", "codes", "M04AA")]
    assert gout["verified"] == "yes" and gout["may_exclude"] == "no"  # fit to the phenotype not reviewed
    assert codes[("phenotypes.csv", "ph.dementia", "codes", "F00")]["verified"] == "no"
    assert codes[("phenotypes.csv", "ph.breast_cancer", "codes", "C50")]["system"] == "ICD-O-3"
    mapped = codes[("phenotype_icd10cm.csv", "ph.ra", "icd10cm_include", "M05")]
    assert mapped["verified"] == "yes" and mapped["use"] == "mapping" and mapped["may_exclude"] == "no"
    assert codes[("scores/demo.yaml", "line 3", "text", "N04B")]["verified"] == "no"
    assert codes[("scores/demo.yaml", "line 3", "text", "HAQ01TC")]["verified"] == "yes"


def test_unknown_never_excludes(cat: Path) -> None:
    """The product rule, over every generated file: a code or row that is not verified never has may_exclude = yes;
    text mentions and hand-made mappings never exclude."""
    built = cv.build(cv.Paths(cat))
    for path, text in built.items():
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("may_exclude") != "yes":
                continue
            assert r.get("verified", r.get("codes_verified")) == "yes", (path.name, r)
            assert r.get("use", "code") == "code" and r.get("code_fit", "exact") == "exact", (path.name, r)
            assert r.get("mapping_verified", "yes") == "yes", (path.name, r)


def test_a_partial_jlac10_never_excludes(cat: Path) -> None:
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace("3C015000002327101,exact,", "3C015000002327101,partial,"))
    row = _codes(cat)[("items.csv", "lab.creatinine", "jlac10", "3C015000002327101")]
    assert row["verified"] == "yes" and row["may_exclude"] == "no"


def _shipped(name: str) -> list[dict[str, str]]:
    with (cv.CATALOGUE / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_the_shipped_catalogue_obeys_unknown_never_excludes() -> None:
    items = _shipped("items.csv")
    assert any(r["may_exclude"] == "yes" for r in items)  # the rule is not vacuous
    for r in items:
        if r["may_exclude"] == "yes":
            assert r["verified"] == "yes" and r["code_fit"] == "exact", r["id"]
        if r["code_fit"] in ("unreviewed", "partial", "none"):
            assert r["may_exclude"] == "no", r["id"]
    assert {r["may_exclude"] for r in _shipped("phenotypes.csv")} == {"no"}
    assert {r["may_exclude"] for r in _shipped("phenotype_icd10cm.csv")} == {"no"}
    codes = _shipped("codes_checked.csv")
    for r in codes:
        if r["may_exclude"] == "yes":
            assert r["verified"] == "yes" and r["use"] == "code", r
            assert r["file"] == "items.csv" and r["field"] in ("loinc", "jlac10"), r
    ra = {(r["code"], r["use"]) for r in codes if r["row"] == "ph.ra" and r["file"] == "phenotypes.csv"}
    assert ("M06.1", "exclude") in ra and ("M06.4", "exclude") in ra and ("M06.1", "code") not in ra
    sle = [r for r in codes if r["file"] == "phenotypes.csv" and r["row"] == "ph.sle" and r["code"] == "M32.0"]
    assert sle and all(r["use"] == "exclude" and r["may_exclude"] == "no" for r in sle)
    for item_id in ("rheum.tjc28", "rheum.sjc28"):
        assert next(r for r in items if r["id"] == item_id)["may_exclude"] == "no"


def test_a_code_has_one_fit_everywhere() -> None:
    """A code that is a partial or unreviewed fit anywhere is never may_exclude = yes anywhere else."""
    items = {r["id"]: r for r in _shipped("items.csv")}
    weak = {r["loinc"] for r in items.values() if r["code_fit"] in ("partial", "unreviewed")}
    for r in _shipped("codes_checked.csv"):
        if r["system"] == "LOINC" and r["code"] in weak:
            assert r["may_exclude"] == "no", r


def test_every_code_shape_in_the_shipped_catalogue_is_registered() -> None:
    """Grep each catalogue file for LOINC (valid check digit) and ATC (level 3+) shapes, independently of the scanner;
    each one must be in codes_checked.csv for that file and row."""
    import re

    registered = {(r["file"], r["row"], r["code"]) for r in _shipped("codes_checked.csv")}
    loinc = re.compile(r"(?<![\w.-])(\d{3,7}-\d)(?![\w.-])")
    atc = re.compile(r"(?<![\w.])([A-V]\d{2}[A-Z](?:[A-Z](?:\d{2})?)?)(?![\w.])")
    missing = []
    skip = {"verified_source", "verified_date", "licence_notes", "jlac10_source"}
    for name, key in (("items.csv", "id"), ("phenotypes.csv", "id"), ("specialties.csv", "specialty_id")):
        for r in _shipped(name):
            for fld, cell in r.items():
                if fld in skip:
                    continue
                shapes = [t for t in loinc.findall(cell) if cv.loinc_check_digit_ok(t)]
                if "exposure" in cell or "ATC" in cell:
                    shapes += atc.findall(cell)
                missing += [(name, r[key], t) for t in shapes if (name, r[key], t) not in registered]
    assert missing == []


def _set_item_unit(cat: Path, unit: str) -> None:
    items = cat / "items.csv"
    items.write_text(items.read_text(encoding="utf-8").replace(",yes,mg/dL\n", f",yes,{unit}\n"), encoding="utf-8")


def test_a_jlac10_unit_that_differs_needs_a_factor(cat: Path) -> None:
    _set_item_unit(cat, "umol/L")  # the MHLW code is in mg/dl
    with pytest.raises(cv.CatalogueError, match="differs from the item's unit 'umol/L' and jlac10_map gives no unit"):
        cv.build(cv.Paths(cat))
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace(",exact,mg/dL,,", ",exact,mg/dL,88.4,"), encoding="utf-8")
    cr = _build(cat)["items.csv"]["lab.creatinine"]
    assert cr["jlac10_source"].endswith("MHLW unit mg/dl (mg/dL); x88.4 to umol/L")


def test_the_jlac10_source_unit_must_be_the_mhlw_unit(cat: Path) -> None:
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace(",exact,mg/dL,,", ",exact,mg/L,,"), encoding="utf-8")
    with pytest.raises(cv.CatalogueError, match="source_unit_ucum 'mg/L' is not the MHLW unit 'mg/dl'"):
        cv.build(cv.Paths(cat))


def test_a_jlac10_code_without_a_unit_cannot_fit_exactly(cat: Path) -> None:
    data = json.loads((cat / "verification" / "evidence.json").read_text(encoding="utf-8"))
    data["jlac10"]["3C015000002327101"]["unit"] = ""
    _edit_evidence(cat, jlac10=data["jlac10"])
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace(",exact,mg/dL,,", ",exact,,,"), encoding="utf-8")
    with pytest.raises(cv.CatalogueError, match="gives no unit, so the code cannot fit 'mg/dL' exactly"):
        cv.build(cv.Paths(cat))
    jl.write_text(jl.read_text(encoding="utf-8").replace(",exact,,,", ",partial,,,"), encoding="utf-8")
    assert "gives no unit; not checked" in _build(cat)["items.csv"]["lab.creatinine"]["jlac10_source"]


def test_adopting_loinc_keeps_the_other_licence_notes(cat: Path) -> None:
    items = cat / "items.csv"
    note = "Instrument copyright A. Author; licence not verified"
    items.write_text(
        items.read_text(encoding="utf-8").replace("ILD marker,local concept,", f"ILD marker,{note},"), encoding="utf-8"
    )
    kl6 = _build(cat)["items.csv"]["lab.kl6"]
    assert kl6["licence_notes"] == f"{note}; {cv.LOINC_NOTICE}"
    for p, text in cv.build(cv.Paths(cat)).items():
        p.write_text(text, encoding="utf-8")
    assert _build(cat)["items.csv"]["lab.kl6"]["licence_notes"] == f"{note}; {cv.LOINC_NOTICE}"  # appended once
    shipped = {r["id"]: r["licence_notes"] for r in _shipped("items.csv")}
    assert shipped["card.kccq"].startswith("KCCQ copyright J. Spertus") and cv.LOINC_NOTICE in shipped["card.kccq"]
    assert all(
        shipped[f"onc.tnm_{t}"].startswith("AJCC staging content is licensed") for t in ("ct", "cn", "cm", "pt", "pn")
    )
    assert all(
        shipped[f"onc.{f}_icdo3"].startswith("ICD-O-3 is WHO-copyrighted") for f in ("primary_site", "morphology")
    )


def test_jlac10_fit_is_required(cat: Path) -> None:
    jl = cat / "verification" / "jlac10_map.csv"
    jl.write_text(jl.read_text(encoding="utf-8").replace("3C015000002327101,exact,", "3C015000002327101,,"))
    with pytest.raises(cv.CatalogueError, match="fit must be exact or partial"):
        cv.build(cv.Paths(cat))


def test_an_unreviewed_code_never_excludes(cat: Path) -> None:
    dec = cat / "verification" / "loinc_decisions.csv"
    dec.write_text(dec.read_text(encoding="utf-8").replace("lab.creatinine,fit_exact,,,,read against the item\n", ""))
    cr = _build(cat)["items.csv"]["lab.creatinine"]
    assert cr["verified"] == "yes" and cr["code_fit"] == "unreviewed" and cr["may_exclude"] == "no"


def test_loinc_check_digit_and_tokens() -> None:
    assert cv.loinc_check_digit_ok("8480-6") and cv.loinc_check_digit_ok("98979-8")
    assert not cv.loinc_check_digit_ok("23538-3") and not cv.loinc_check_digit_ok("x-1")
    assert cv.loinc_tokens("LOINC 98979-8/62238-1/local JSN") == ["98979-8", "62238-1"]
    assert cv.loinc_tokens("range 120-180 mg, no code word") == []
    assert cv.loinc_tokens("LOINC 4548-4; target 7.0-10.5%") == ["4548-4"]
    assert cv.atc_tokens("M10.*; ATC C02/C03/C07; LOINC 3084-1") == ["C02", "C03", "C07"]
    assert cv.atc_tokens("rows with ATC N04B (dopaminergic agents)") == ["N04B"]
    assert cv.cdisc_tokens("RS domain (RSCAT RECIST 1.1; response codelist not verified)") == []
    assert cv.cdisc_tokens("PASI02TC..PASI05TC (RS)") == ["PASI02TC", "PASI05TC"]


def test_parse_cdisc_and_atc() -> None:
    text = (
        "Code\tCodelist Code\tExt\tCodelist Name\tCDISC Submission Value\n"
        "C106667\t\tNo\tHAQ-DI Test Code\tHAQ01TC\n"
        "C1\tC106667\t\tHAQ-DI Test Code\tHAQ0101\n"
    )
    assert cv.parse_cdisc(text, {"HAQ01TC", "HAQ0101"}) == {
        "HAQ01TC": {"nci_code": "C106667", "name": "HAQ-DI Test Code"}
    }
    page = b'M04 <b><a href="./?code=M04&showdescription=no">ANTIGOUT</a></b><br/>M04AA <b><a href="./?code=M04AA&showdescription=no">Preparations &amp; more</a></b>'
    assert cv.fetch_atc(lambda _u: page, "M04AA") == "Preparations & more"
    assert cv.fetch_atc(lambda _u: page, "M04AB") is None


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
    assert cv.icd_tokens("I60-I64") == ["I60", "I61", "I62", "I63", "I64"]
    assert cv.icd_tokens("C92.0*, C92.4-C92.6") == ["C92.0", "C92.4", "C92.5", "C92.6"]
    assert cv.icd_split("M32.* (excl. M32.0 drug-induced)") == (["M32"], ["M32.0"])
    assert cv.icd_split("ICD-10-CM M05.*, M06.* (excl. M06.1, M06.4)") == (["M05", "M06"], ["M06.1", "M06.4"])
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
        "atc_ddd_index/?code=M04AA": b'M04AA <b><a href="./?code=M04AA&showdescription=no">Uric acid</a></b>',
        "atc_ddd_index/": b"<html>no such code</html>",
        "SDTM%20Terminology.txt": b"Code\tCodelist Code\tE\tName\tValue\nC106667\t\tNo\tHAQ\tHAQ01TC\n",
    }
    monkeypatch.setattr(cv, "fetch_mhlw", lambda get: {"3C015000002327101": {"name": "血清クレアチニン"}})
    ev = cv.fetch(cv.Paths(cat), "2026-11-09", get=_fake_get(routes), log=lambda _m: None)
    assert ev.loinc_codes == {"93369-7": "KL-6 name"}  # the other codes were not found: never invented
    assert ev.loinc_searches["DAS28"] == {"total": 0, "hits": []}
    assert set(ev.cohorts) == {"33", "858"} and ev.cohorts["858"]["entry_concepts"] == []
    assert [c["concept_id"] for c in ev.cohorts["33"]["entry_concepts"]] == [4182210]
    assert ev.icd10cm_prefixes["M05"]["n"] == 2 and ev.icd10cm_prefixes["F00"]["n"] == 0
    assert ev.icd10cm_names == {"4182210": ["F03.90"]}  # searched by name, kept by OMOP concept id
    assert "name" not in ev.cohorts["33"]["entry_concepts"][0]
    assert ev.atc == {"M04AA": "Uric acid"}  # N04B (the score file) was not listed: not invented
    assert ev.cdisc == {"HAQ01TC": {"nci_code": "C106667", "name": "HAQ"}}
    assert all("CONCEPT_CODE" not in c and "code" not in c for c in ev.cohorts["33"]["entry_concepts"])
    assert json.loads(ev.dump())["date"] == "2026-11-09"


def test_evidence_keeps_no_cpt4_hcpcs_or_snomed_names(cat: Path) -> None:
    ev = cv.Evidence.load(cat / "verification" / "evidence.json")
    ev.cohorts["33"]["entry_concepts"] = [
        {"set": "s", "concept_id": n, "vocabulary": vocab, "name": f"licensed {vocab} text", "excluded": False}
        for n, vocab in enumerate(["CPT4", "HCPCS", "SNOMED", "RxNorm"], 1)
    ]
    dumped = ev.dump()
    assert "licensed CPT4 text" not in dumped and "licensed HCPCS text" not in dumped
    assert "licensed SNOMED text" not in dumped and "licensed RxNorm text" in dumped
    kept = json.loads(dumped)["cohorts"]["33"]["entry_concepts"]
    assert [c["concept_id"] for c in kept] == [1, 2, 3, 4]  # the ids stay
    shipped = (cv.CATALOGUE / "verification" / "evidence.json").read_text(encoding="utf-8")
    assert shipped == cv.Evidence.load(cv.CATALOGUE / "verification" / "evidence.json").dump()


def test_parse_mhlw_rows() -> None:
    head = ("実施項目", None, None, "区分名称", None, "項目コード（17桁）", "項目名", *[None] * 13)
    row = ("〇", "〇", 10, "生化学検査", 10, "3C015000002327101", "血清クレアチニン", *[None] * 4, "mg/dl", *[None] * 7,
           "1：可視吸光光度法")  # fmt: skip
    got = cv.parse_mhlw_rows([head, row, ("short",)])
    assert got == {"3C015000002327101": {"group": "生化学検査", "name": "血清クレアチニン", "unit": "mg/dl",
                                         "method": "1：可視吸光光度法"}}  # fmt: skip


def test_the_shipped_catalogue_is_up_to_date() -> None:
    assert cv.main(["build", "--check"]) == 0
