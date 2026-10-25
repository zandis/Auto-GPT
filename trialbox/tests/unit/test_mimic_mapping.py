"""MIMIC-IV FHIR demo normalisation tables and step (services/adapter/mapping/mimic; docs/OPEN_DATA.md)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.mimic.normalise import (
    ATC,
    DEPARTMENT,
    ICD9CM,
    ICD10CM,
    ICD10PCS,
    LOINC,
    MIMIC_CS,
    SNOMED,
    UCUM,
    MimicNormaliser,
    MimicTables,
    icd9_dotted,
    icd10_dotted,
    read_release,
    shift_value,
    write_bulk,
)
from tb_common.ruleset import Ruleset

from tools import fetch_open_data, open_data_e2e

ROOT = Path(__file__).resolve().parents[2]
OPEN = ROOT / "tests" / "fixtures" / "open_data"
T = MimicTables.load()

ICD10CM_RE = re.compile(r"^[A-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$")
ATC_RE = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")


def luhn_ok(loinc: str) -> bool:
    """LOINC check digit (mod 10, the Luhn scheme)."""
    body, _, check = loinc.partition("-")
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10 == int(check)


_VD = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VP = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_ok(sctid: str) -> bool:
    """SNOMED CT identifiers end with a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(sctid)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


# ---------------------------------------------------------------------------------------------- tables
def test_tables_well_formed() -> None:
    assert T.icd9 and T.labs and T.drugs and T.icu_items
    for icd9, (icd10, display) in T.icd9.items():
        assert re.match(r"^(V\d{2,4}|E\d{3,4}|\d{3,5})$", icd9), icd9
        assert ICD10CM_RE.match(icd10), (icd9, icd10)
        assert display
    for itemid, lab in T.labs.items():
        assert itemid.isdigit() and luhn_ok(lab.loinc), (itemid, lab.loinc)
        assert lab.ucum and lab.display
    for _, atc, _ in T.drugs:
        assert ATC_RE.match(atc), atc
    for itemid, (sctid, _) in T.icu_items.items():
        assert itemid.isdigit() and verhoeff_ok(sctid), (itemid, sctid)


def test_check_digit_helpers() -> None:
    assert luhn_ok("2160-0") and luhn_ok("33762-6") and not luhn_ok("2160-1")
    assert verhoeff_ok("40617009") and not verhoeff_ok("40617008")


def test_duplicate_icd9_rejected(tmp_path: Path) -> None:
    for name in ("labitem_to_loinc.csv", "drug_to_atc.csv", "icu_item_to_snomed.csv"):
        (tmp_path / name).write_text((open_data_tables() / name).read_text("utf-8"), "utf-8")
    (tmp_path / "icd9_to_icd10cm.csv").write_text(
        "icd9,icd10cm,display,basis\n4280,I50.9,x,gem\n4280,I50.1,y,gem\n", "utf-8"
    )
    with pytest.raises(ValueError, match="duplicate"):
        MimicTables.load(tmp_path)


def open_data_tables() -> Path:
    from adapter.mapping.mimic.normalise import TABLES

    return TABLES


@pytest.mark.parametrize(
    ("raw", "dotted"), [("I5023", "I50.23"), ("N179", "N17.9"), ("Z66", "Z66"), ("i10", "I10"), ("E11.10", "E11.10")]
)
def test_icd10_dotted(raw: str, dotted: str) -> None:
    assert icd10_dotted(raw) == dotted


def test_icd9_dotted() -> None:
    assert icd9_dotted("4280") == "428.0"
    assert icd9_dotted("V4511") == "V45.11"
    assert icd9_dotted("E8889") == "E888.9"
    assert icd9_dotted("042") == "042"
    assert icd9_dotted("3995", procedure=True) == "39.95"


def test_drug_names_to_atc() -> None:
    assert T.atc_for("Furosemide") == ("C03CA01", "furosemide")
    assert T.atc_for("Furosemide-Heart Failure") == ("C03CA01", "furosemide")
    assert T.atc_for("MetFORMIN XR (Glucophage XR)") == ("A10BA02", "metformin")
    assert T.atc_for("Sacubitril-Valsartan (24mg-26mg)") == ("C09DX04", "valsartan and sacubitril")
    assert T.atc_for("Insulin") is None
    assert T.atc_for("Furosemidex") is None  # whole words only


def test_shift_value() -> None:
    assert shift_value("2180-05-06T22:23:00-04:00", -56000) == "2027-01-09T22:23:00-04:00"
    assert shift_value("2083-04-10", 10) == "2083-04-20"


# ---------------------------------------------------------------------------------------------- normaliser
def _bundle() -> dict[str, list[dict[str, Any]]]:
    def coding(system: str, code: str, display: str = "") -> dict[str, Any]:
        return {
            "coding": [{"system": f"{MIMIC_CS}{system}", "code": code, **({"display": display} if display else {})}]
        }

    pat = {"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "2100-01-01"}
    subj = {"reference": "Patient/p1"}
    hosp = {
        "resourceType": "Encounter",
        "id": "e1",
        "subject": subj,
        "class": {"code": "EMER"},
        "period": {"start": "2160-03-01T10:00:00-05:00", "end": "2160-03-05T10:00:00-05:00"},
        "serviceType": coding("mimic-services", "CMED"),
    }
    icu = {
        "resourceType": "Encounter",
        "id": "e2",
        "subject": subj,
        "class": {"code": "ACUTE"},
        "identifier": [{"system": "http://mimic.mit.edu/fhir/mimic/identifier/encounter-icu", "value": "1"}],
        "period": {"start": "2160-03-02T10:00:00-05:00", "end": "2160-03-03T10:00:00-05:00"},
    }
    return {
        "Patient": [pat],
        "Encounter": [hosp, icu],
        "Condition": [
            {
                "resourceType": "Condition",
                "id": "c1",
                "subject": subj,
                "encounter": {"reference": "Encounter/e1"},
                "code": coding("mimic-diagnosis-icd10", "I5023", "Acute on chronic systolic HF"),
            },
            {
                "resourceType": "Condition",
                "id": "c2",
                "subject": subj,
                "encounter": {"reference": "Encounter/e1"},
                "code": coding("mimic-diagnosis-icd9", "5849", "AKI"),
            },
            {
                "resourceType": "Condition",
                "id": "c3",
                "subject": subj,
                "encounter": {"reference": "Encounter/e1"},
                "code": coding("mimic-diagnosis-icd9", "2724", "Hyperlipidemia"),
            },
        ],
        "Observation": [
            {
                "resourceType": "Observation",
                "id": "o1",
                "subject": subj,
                "code": coding("mimic-d-labitems", "50912"),
                "effectiveDateTime": "2160-03-02T06:00:00-05:00",
                "valueQuantity": {"value": 4.2, "unit": "mg/dL", "code": "mg/dL"},
            },
            {
                "resourceType": "Observation",
                "id": "o2",
                "subject": subj,
                "code": coding("mimic-d-labitems", "50971"),
                "effectiveDateTime": "2160-03-02T06:00:00-05:00",
                "valueQuantity": {"value": 5.1, "unit": "mEq/L", "code": "mEq/L"},
            },
            {
                "resourceType": "Observation",
                "id": "o3",
                "subject": subj,
                "code": coding("mimic-d-labitems", "99999"),
                "effectiveDateTime": "2160-03-02T06:00:00-05:00",
            },
        ],
        "Medication": [
            {
                "resourceType": "Medication",
                "id": "m1",
                "code": coding("mimic-medication-ndc", "51079030020"),
                "identifier": [
                    {"system": f"{MIMIC_CS}mimic-medication-ndc", "value": "51079030020"},
                    {"system": f"{MIMIC_CS}mimic-medication-name", "value": "Furosemide"},
                ],
            },
            {
                "resourceType": "Medication",
                "id": "mix1",
                "identifier": [
                    {
                        "system": "http://mimic.mit.edu/fhir/mimic/identifier/medication-mix",
                        "value": "Torsemide--TORS20--0001_Sodium Chloride 0.9%--NS100--0002",
                    }
                ],
            },
        ],
        "MedicationRequest": [
            {
                "resourceType": "MedicationRequest",
                "id": "r1",
                "subject": subj,
                "status": "completed",
                "authoredOn": "2160-03-01T12:00:00-05:00",
                "medicationReference": {"reference": "Medication/m1"},
            },
            {
                "resourceType": "MedicationRequest",
                "id": "r2",
                "subject": subj,
                "status": "completed",
                "authoredOn": "2160-03-01T12:00:00-05:00",
                "medicationCodeableConcept": coding("mimic-medication-name", "Bumetanide"),
            },
            {
                "resourceType": "MedicationRequest",
                "id": "r3",
                "subject": subj,
                "status": "completed",
                "authoredOn": "2160-03-01T12:00:00-05:00",
                "medicationReference": {"reference": "Medication/mix1"},
            },
        ],
        "Procedure": [
            {
                "resourceType": "Procedure",
                "id": "x1",
                "subject": subj,
                "code": coding("mimic-d-items", "225802"),
                "performedPeriod": {"start": "2160-03-02T12:00:00-05:00", "end": "2160-03-03T12:00:00-05:00"},
            },
            {
                "resourceType": "Procedure",
                "id": "x2",
                "subject": subj,
                "code": coding("mimic-procedure-icd9", "3995"),
                "performedDateTime": "2160-03-02T00:00:00-05:00",
            },
            {
                "resourceType": "Procedure",
                "id": "x3",
                "subject": subj,
                "code": coding("mimic-procedure-icd10", "5A1D90Z"),
                "performedDateTime": "2160-03-02T00:00:00-05:00",
            },
        ],
        "Organization": [{"resourceType": "Organization", "id": "org"}],
    }


def _first(r: dict[str, Any], key: str = "code") -> dict[str, Any]:
    first: dict[str, Any] = r[key]["coding"][0]
    return first


def test_normalise_bundle(tmp_path: Path) -> None:
    lo, hi = date(2024, 1, 1), date(2026, 9, 1)
    norm = MimicNormaliser(T, lo, hi)
    src = _bundle()
    out = norm.normalise({k: [r for r in v if norm.keep_raw(r)] for k, v in src.items()})
    assert set(out) == {"Patient", "Encounter", "Condition", "Observation", "MedicationRequest", "Procedure"}
    days = norm.report.shifts["p1"]
    anchor = date(2160, 3, 2) + timedelta(days=days)  # last encounter start (the ICU stay)
    assert lo <= anchor <= hi
    # dates move together: age and intervals are preserved
    pat = out["Patient"][0]
    assert pat["birthDate"] == (date(2100, 1, 1) + timedelta(days=days)).isoformat()
    enc = {e["id"]: e for e in out["Encounter"]}
    assert _first(enc["e1"], "serviceType") == {"system": DEPARTMENT, "code": "CMED"}
    assert _first(enc["e2"], "serviceType")["code"] == "ICU"
    cond = {c["id"]: c for c in out["Condition"]}
    assert _first(cond["c1"]) == {"system": ICD10CM, "code": "I50.23", "display": "Acute on chronic systolic HF"}
    assert cond["c1"]["recordedDate"] == enc["e1"]["period"]["start"]
    assert _first(cond["c2"])["system"] == ICD10CM and _first(cond["c2"])["code"] == "N17.9"
    assert cond["c2"]["code"]["coding"][1] == {"system": ICD9CM, "code": "584.9", "display": "AKI"}
    assert _first(cond["c3"]) == {"system": ICD9CM, "code": "272.4", "display": "Hyperlipidemia"}  # unmapped
    obs = {o["id"]: o for o in out["Observation"]}
    assert set(obs) == {"o1", "o2"}  # unmapped lab item skipped at read time
    assert _first(obs["o1"])["code"] == "2160-0" and obs["o1"]["code"]["coding"][1]["code"] == "50912"
    assert obs["o2"]["valueQuantity"] == {"value": 5.1, "unit": "mmol/L", "system": UCUM, "code": "mmol/L"}
    meds = {m["id"]: m for m in out["MedicationRequest"]}
    assert "medicationReference" not in meds["r1"]
    assert meds["r1"]["medicationCodeableConcept"]["text"] == "Furosemide"
    assert _first(meds["r1"], "medicationCodeableConcept") == {
        "system": ATC,
        "code": "C03CA01",
        "display": "furosemide",
    }
    assert _first(meds["r2"], "medicationCodeableConcept")["code"] == "C03CA02"
    assert meds["r3"]["medicationCodeableConcept"]["text"] == "Torsemide + Sodium Chloride 0.9%"
    assert _first(meds["r3"], "medicationCodeableConcept")["code"] == "C03CA04"
    proc = {p["id"]: p for p in out["Procedure"]}
    assert _first(proc["x1"])["system"] == SNOMED and proc["x1"]["performedDateTime"].startswith(anchor.isoformat())
    assert _first(proc["x2"]) == {"system": ICD9CM, "code": "39.95"}
    assert _first(proc["x3"]) == {"system": ICD10PCS, "code": "5A1D90Z"}
    counts = norm.report.as_dict()["counts"]
    assert counts["condition.icd9_mapped"] == 1 and counts["condition.icd9_unmapped"] == 1
    assert counts["observation.skipped_unmapped_lab"] == 1 and counts["medication_request.atc"] == 3
    # round trip through the bulk writer and the release reader
    written = write_bulk(tmp_path / "bulk", out)
    assert written["Observation"] == 2
    (tmp_path / "rel").mkdir()
    for rtype, items in src.items():
        (tmp_path / "rel" / f"Mimic{rtype}.ndjson").write_text("\n".join(json.dumps(r) for r in items) + "\n", "utf-8")
    again = read_release(tmp_path / "rel")
    assert sum(len(v) for v in again.values()) == sum(len(v) for v in src.values())


def test_flattened_rows_hit_the_lake_columns() -> None:
    """Normalised resources flatten to the codes the compiler's SQL matches on (lake.flatten)."""
    from lake.flatten import Flattener

    norm = MimicNormaliser(T, date(2024, 1, 1), date(2026, 9, 1))
    out = norm.normalise(_bundle())
    rows = Flattener("America/New_York").flatten(out)
    assert {(r["system"], r["code"]) for r in rows["condition"]} >= {(ICD10CM, "I50.23"), (ICD10CM, "N17.9")}
    assert all(r["recorded"] is not None for r in rows["condition"])
    lab = next(r for r in rows["observation"] if r["code"] == "2160-0")
    assert lab["system"] == LOINC and lab["value_num"] == 4.2 and lab["local_code"] == "50912"
    assert {r["atc"] for r in rows["medication"]} == {"C03CA01", "C03CA02", "C03CA04"}
    assert {r["dept"] for r in rows["encounter"]} == {"CMED", "ICU"}
    assert all(r["performed"] is not None for r in rows["procedure"])


# ---------------------------------------------------------------------------------------------- rulesets
@pytest.mark.parametrize("rid", open_data_e2e.RULESETS)
def test_open_data_rulesets_compile(rid: str) -> None:
    rs = open_data_e2e.load_ruleset(OPEN / "rulesets" / rid)
    assert [c.id for c in rs.ordered()] == rs.manifest.criteria
    structured = [c for c in rs.active() if c.class_ == "structured"]
    assert structured and all(f'"C_{c.id}"' in rs.sql for c in structured)
    assert any(c.class_ in ("note", "human") for c in rs.active())  # the non-computable part is marked
    for c in rs.active():
        if c.class_ == "note":
            assert c.note_question
        if c.class_ == "human":
            assert c.human_question
    fixture = json.loads((OPEN / f"ctgov_{rs.manifest.nct_id}.json").read_text("utf-8"))
    assert fixture["nct_id"] == rs.manifest.nct_id and re.match(r"^\d{4}-\d{2}-\d{2}$", fixture["retrieved"])
    elig = fixture["study"]["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]
    assert "Inclusion Criteria" in elig and "Exclusion Criteria" in elig
    assert rs.manifest.source_documents == [f"tests/fixtures/open_data/ctgov_{rs.manifest.nct_id}.json"]
    assert rs.manifest.nct_id in fetch_open_data.TRIALS


@pytest.mark.parametrize("rid", open_data_e2e.RULESETS)
def test_ruleset_codes_are_reachable(rid: str) -> None:
    """Every LOINC / ATC / SNOMED code a ruleset matches on can be produced by the normalisation tables."""
    rs = Ruleset.load(OPEN / "rulesets" / rid)
    loinc = {lab.loinc for lab in T.labs.values()}
    atc = {a for _, a, _ in T.drugs}
    sct = {s for s, _ in T.icu_items.values()}
    for name, vs in rs.valuesets.items():
        for inc in vs["compose"]["include"]:
            codes = {c["code"] for c in inc["concept"]}
            if inc["system"] == LOINC:
                assert codes <= loinc, (name, codes - loinc)
            elif inc["system"] == ATC:
                assert codes <= atc, (name, codes - atc)
            elif inc["system"] == SNOMED:
                assert codes <= sct, (name, codes - sct)
            elif inc["system"] == ICD10CM:
                assert all(ICD10CM_RE.match(c) for c in codes), name


def test_fetch_sums_parser() -> None:
    sums = fetch_open_data.parse_sums(
        "bcdf0000000000000000000000000000000000000000000000000000000000aa LICENSE.txt\n"
        "6be4000000000000000000000000000000000000000000000000000000000bbb fhir/MimicCondition.ndjson.gz\n"
        "garbage line\n"
    )
    assert sums["fhir/MimicCondition.ndjson.gz"].endswith("bbb") and len(sums) == 2
    assert set(fetch_open_data.FILES) >= {f"fhir/{f}" for f in open_data_e2e.REQUIRED_FILES}


def test_streaming_run_matches_in_memory(tmp_path: Path) -> None:
    import gzip

    rel = tmp_path / "fhir"
    rel.mkdir()
    for rtype, items in _bundle().items():
        with gzip.open(rel / f"Mimic{rtype}.ndjson.gz", "wt", encoding="utf-8") as fh:
            for r in items:
                fh.write(json.dumps(r) + "\n")  # the release layout: '"code": "50912", "system": ...'
    streamed = MimicNormaliser(T, date(2024, 1, 1), date(2026, 9, 1))
    counts = streamed.run(rel, tmp_path / "bulk")
    in_memory = MimicNormaliser(T, date(2024, 1, 1), date(2026, 9, 1)).normalise(_bundle())
    assert counts == {k: len(v) for k, v in in_memory.items()}
    for rtype, items in in_memory.items():
        lines = (tmp_path / "bulk" / f"{rtype}.ndjson").read_text("utf-8").splitlines()
        assert sorted(json.loads(x)["id"] for x in lines) == sorted(r["id"] for r in items)
        assert [json.loads(x) for x in lines] == items
    # the unmapped lab line is dropped before parsing
    assert streamed.report.counts["observation.skipped_unmapped_lab"] == 1
