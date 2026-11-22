"""T-613b (D-334; STD-001, STD-002, STD-022, CR-001 adapter half): units read per row on every shipped path, the
unit and conversion table, presence results in Japanese, Chinese and English, and what ``mapping_check`` lists."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest
import yaml
from adapter.mapping.engine import DATA_ABSENT, Mapper, Mapping
from adapter.pipeline import make_source
from adapter.sources.ssmix2 import hl7
from adapter.sources.ssmix2.source import storage_dir
from tb_common import labunit, labvalue

from tools import mapping_check

ROOT = Path(__file__).resolve().parents[2]
MAPPING_DIR = ROOT / "services/adapter/mapping"
TW = MAPPING_DIR / "tw_core/demo_his.yaml"
JP = MAPPING_DIR / "jp_core/ssmix2_site.yaml"
KEY = b"t613b-test-key-0123456789abcdef!"
LOINC_CREATININE = "2160-0"

# ------------------------------------------------------------------------------------------ conversion table
# (LOINC, from, to, factor): textbook factors (Tietz; the SI unit tables of the AMA Manual of Style), within 0.2 %
PAIRS = [
    ("2160-0", "umol/L", "mg/dL", 1 / 88.4),  # creatinine, the engines' own factor (labunit)
    ("2160-0", "mg/dL", "µmol/L", 88.4),
    ("2160-0", "mmol/L", "mg/dL", 11.312),
    ("3084-1", "umol/L", "mg/dL", 1 / 59.48),  # urate
    ("3084-1", "mg/dL", "mmol/L", 0.05948),
    ("2345-7", "mmol/L", "mg/dL", 18.016),  # glucose
    ("1558-6", "mg/dl", "mmol/l", 1 / 18.016),
    ("1975-2", "umol/L", "mg/dL", 1 / 17.104),  # bilirubin
    ("1968-7", "mg/dL", "umol/L", 17.104),
    ("2093-3", "mmol/L", "mg/dL", 38.67),  # cholesterol
    ("2089-1", "mg/dL", "mmol/L", 1 / 38.67),  # LDL
    ("2085-9", "mmol/L", "mg/dL", 38.67),  # HDL
    ("2571-8", "mmol/L", "mg/dL", 88.57),  # triglyceride
    ("17861-6", "mmol/L", "mg/dL", 4.008),  # calcium
    ("17861-6", "mEq/L", "mmol/L", 0.5),
    ("2777-1", "mmol/L", "mg/dL", 3.097),  # phosphate
    ("2601-3", "mmol/L", "mg/dL", 2.431),  # magnesium
    ("2601-3", "meq/L", "mmol/L", 0.5),
    ("3094-0", "mmol/L", "mg/dL", 2.801),  # urea nitrogen
    ("718-7", "g/dL", "mmol/L", 0.6206),  # hemoglobin
    ("718-7", "g/dL", "g/L", 10.0),
    ("1751-7", "g/dL", "g/L", 10.0),  # albumin: one scale family, no analyte row needed
    ("1988-5", "mg/dL", "mg/L", 10.0),  # CRP, the engines' own factor (labunit)
    ("1988-5", "ug/mL", "mg/L", 1.0),
    ("2951-2", "mEq/L", "mmol/L", 1.0),  # sodium
    ("2823-3", "meq/l", "mmol/L", 1.0),  # potassium
    ("3024-7", "ng/dL", "pmol/L", 12.87),  # free T4
    ("2143-6", "ug/dL", "nmol/L", 27.59),  # cortisol
    ("1989-3", "ng/mL", "nmol/L", 2.496),  # 25-OH vitamin D
    ("16362-6", "ug/dL", "umol/L", 0.5872),  # ammonia
    ("777-3", "10*4/uL", "10*3/uL", 10.0),  # platelets, JLAC10 (万/µL)
    ("777-3", "万/µL", "10^9/L", 10.0),
    ("6690-2", "/uL", "10*3/uL", 0.001),  # WBC, JLAC10
    ("1742-6", "U/L", "mU/mL", 1.0),  # ALT
    ("3016-3", "uIU/mL", "mIU/L", 1.0),  # TSH
    ("10839-9", "ng/L", "pg/mL", 1.0),  # troponin I: one UCUM code, two spellings
]


@pytest.mark.parametrize(("loinc", "have", "need", "factor"), PAIRS)
def test_conversion_pairs(loinc: str, have: str, need: str, factor: float) -> None:
    got = labvalue.conversion(have, need, loinc)
    assert got is not None and math.isclose(got, factor, rel_tol=2e-3), (have, need, got)
    back = labvalue.conversion(need, have, loinc)
    assert back is not None and math.isclose(got * back, 1.0, rel_tol=1e-9)


def test_thirty_pairs_at_least() -> None:
    assert len(PAIRS) >= 30


@pytest.mark.parametrize(
    ("loinc", "have", "need"),
    [
        ("4548-4", "%", "mmol/mol"),  # HbA1c NGSP and IFCC: an offset, not a factor
        (None, "mmol/L", "mg/dL"),  # mass to substance needs the analyte
        ("1742-6", "U/L", "[IU]/L"),  # enzyme units and international units are kept apart
        ("2160-0", "mg/dL", "U/L"),
        ("2160-0", "mg/dL", "furlongs"),  # a unit the spelling table does not know
        ("2160-0", None, "mg/dL"),
        ("1988-5", "mg/dL", "mmol/L"),  # CRP has no molar mass row
    ],
)
def test_no_tested_factor(loinc: str | None, have: str | None, need: str) -> None:
    assert labvalue.conversion(have, need, loinc) is None


def test_the_engines_factors_are_the_tables() -> None:
    """The analytes the SQL and CQL engines convert (labunit, D-275) have the same factors here: one source."""
    for (system, code), table in labunit.ANALYTES.items():
        if system != "http://loinc.org":
            continue
        for have in table:
            for need in table:
                ours = labvalue.ANALYTES[code][have] / labvalue.ANALYTES[code][need]
                assert math.isclose(ours, table[have] / table[need], rel_tol=1e-12), (code, have, need)


def test_the_catalogue_jlac10_factors_agree() -> None:
    """Every JLAC10 row whose MHLW unit differs from the item's unit names a factor; the table gives the same one."""
    with (ROOT / "catalogue/items.csv").open(encoding="utf-8") as fh:
        items = {r["id"]: r for r in csv.DictReader(fh)}
    checked = 0
    with (ROOT / "catalogue/verification/jlac10_map.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["unit_factor"]:
                continue
            item = items[r["item_id"]]
            got = labvalue.conversion(r["source_unit_ucum"], item["unit_ucum"], item["loinc"])
            assert got is not None and math.isclose(got, float(r["unit_factor"]), rel_tol=1e-9), r["item_id"]
            checked += 1
    assert checked >= 3


def test_one_reason_spelling() -> None:
    assert labvalue.UNIT_MISMATCH is labunit.UNIT_MISMATCH


# ------------------------------------------------------------------------------------------ presence results
SPELLINGS = [
    # Japanese
    ("陰性", "NEG"),
    ("陽性", "POS"),
    ("（－）", "NEG"),
    ("（＋）", "POS"),
    ("陰性(-)", "NEG"),
    ("(+)陽性", "POS"),
    ("検出せず", "NEG"),
    ("判定保留", "UNK"),
    ("±", "UNK"),
    ("弱陽性", "UNK"),
    # Chinese (Taiwan; and the simplified forms a Chinese export uses)
    ("未檢出", "NEG"),
    ("檢出", "POS"),
    ("無反應", "NEG"),
    ("陰性 (－)", "NEG"),
    ("阳性", "POS"),
    ("灰區", "UNK"),
    # English
    ("Negative", "NEG"),
    ("POSITIVE", "POS"),
    ("Non-reactive", "NEG"),
    ("Reactive", "POS"),
    ("not detected", "NEG"),
    ("neg", "NEG"),
    ("2+", "POS"),
    ("Equivocal", "UNK"),
    ("-", "NEG"),
    ("+", "POS"),
    # contradictions and text the table does not know
    ("陰性(+)", "UNK"),
    ("see note", None),
    ("", None),
    ("75", None),
]


@pytest.mark.parametrize(("text", "want"), SPELLINGS)
def test_presence(text: str, want: str | None) -> None:
    assert labvalue.presence(text) == want


def test_twenty_spellings_in_three_languages() -> None:
    assert sum(1 for _, w in SPELLINGS if w is not None) >= 20


def test_answer_key_site_word_first() -> None:
    answers = {"POS": "LA6576-8|Positive", "NEG": "LA6577-6|Negative", "(-)": "LA6576-8|Positive"}
    assert labvalue.answer_key("(-)", answers) == "(-)"  # a site's own (odd) word wins over the shared table
    assert labvalue.answer_key("陰性", answers) == "NEG"
    assert labvalue.answer_key("判定保留", answers) is None
    assert labvalue.answer_key("陽性", {"NEG": "x"}) is None  # the lookup has no answer for it


# ------------------------------------------------------------------------------------------ the shipped paths
def _lab_row(**kw: str) -> dict[str, str]:
    row = {
        "lab_no": "L1",
        "mrn": "M0001",
        "local_code": "CRE",
        "item_name": "Creatinine",
        "result_value": "88",
        "unit": "µmol/L",
        "sample_datetime": "2026-10-01 09:00:00",
        "updated_at": "2026-10-01 09:00:00",
    }
    row.update(kw)
    return row


def _is_mismatch(res: dict[str, object]) -> bool:
    absent = res.get("dataAbsentReason") or {}
    return (
        not any(k.startswith("value") for k in res)
        and isinstance(absent, dict)
        and absent.get("text") == labvalue.UNIT_MISMATCH
        and absent.get("coding") == [{"system": DATA_ABSENT, "code": "error"}]
    )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _map_lab(mapping: Path, kind: str, where: Path) -> list[dict[str, object]]:
    m = Mapping.load(mapping)
    src = make_source(kind, str(where))
    rows = [m.normalize("lab", r) for r in src.rows("lab", m.tables["lab"]["source"], None, None)]
    return list(Mapper(m, KEY, "S").map_table("lab", iter(rows)))


def test_umol_creatinine_through_csv_has_no_value(tmp_path: Path) -> None:
    """Acceptance: 88 µmol/L creatinine through the CSV path leaves no value and the reason ``unit_mismatch`` (before
    PR #70 it left as 88 mg/dL); the same lookup's mg/dL row and a row without a unit read as before."""
    _write_csv(
        tmp_path / "lab.csv",
        [
            _lab_row(),
            _lab_row(lab_no="L2", result_value="1.0", unit="mg/dL"),
            _lab_row(lab_no="L3", result_value="1.1", unit=""),
            _lab_row(lab_no="L4", local_code="HBSAG", item_name="HBsAg", result_value="陰性", unit=""),
        ],
    )
    out = {r["id"]: r for r in _map_lab(TW, "csv", tmp_path)}
    mismatched = [r for r in out.values() if _is_mismatch(r)]
    assert len(mismatched) == 1 and mismatched[0]["note"] == [{"text": "88 µmol/L"}]
    quantities = sorted(r["valueQuantity"]["value"] for r in out.values() if "valueQuantity" in r)  # type: ignore[index]
    assert quantities == [1.0, 1.1]
    coded = [r["valueCodeableConcept"] for r in out.values() if "valueCodeableConcept" in r]
    assert coded and coded[0]["coding"][0]["code"] == "LA6577-6" and coded[0]["text"] == "陰性"  # type: ignore[index]


def _oml(root: Path, order: str, jlac: str, name: str, value: str, unit: str) -> None:
    d = storage_dir(root, "12345678", "20261001", "OML-11")
    d.mkdir(parents=True, exist_ok=True)
    msg = (
        "\r".join(
            [
                "MSH|^~\\&|HIS||TB||20261001||OUL^R22|1|P|2.5||||||~ISO IR87",
                "PID|||12345678^^^^PI",  # every SS-MIX2 message carries its patient (PR #1095 fourth review b)
                f"OBR|1|{order}",
                f"OBX|1|NM|{jlac}^{name}^JC10||{hl7.escape(value)}|{hl7.escape(unit)}||||||||20261001090000"
                + "|" * 7
                + order,
            ]
        )
        + "\r"
    )  # every segment ended by CR, the last one too (R22-44)
    (d / f"12345678_20261001_OML-11_{order}_20261001000000000_-_1").write_bytes(msg.encode("iso2022_jp"))


def test_umol_creatinine_through_ssmix2_has_no_value(tmp_path: Path) -> None:
    """Acceptance, the JP template: OBX-6 is the row's unit; µmol/L creatinine against the JLAC10 lookup's mg/dL has
    no value and the reason ``unit_mismatch``; mg/dl reads; 陽性 and 陰性 read to the LOINC answers."""
    root = tmp_path / "ss"
    _oml(root, "L1", "3C015000002327101", "クレアチニン", "88", "μmol/L")  # Greek mu: JIS X 0208 has no micro sign
    _oml(root, "L2", "3C015000002327101", "クレアチニン", "0.9", "mg/dl")
    _oml(root, "L3", "5F016141002305911", "HBs抗原", "陽性", "")
    _oml(root, "L4", "5E071160001905911", "IGRA", "陰性（−）", "")  # JIS X 0208 minus, U+2212
    _oml(root, "L5", "5E071160001905911", "IGRA", "判定保留", "")
    out = _map_lab(JP, "ssmix2", root)
    assert len(out) == 5
    mismatched = [r for r in out if _is_mismatch(r)]
    assert len(mismatched) == 1 and mismatched[0]["note"] == [{"text": "88 μmol/L"}]
    assert [r["valueQuantity"]["value"] for r in out if "valueQuantity" in r] == [0.9]  # type: ignore[index]
    answers = sorted(r["valueCodeableConcept"]["coding"][0]["code"] for r in out if "valueCodeableConcept" in r)  # type: ignore[index]
    assert answers == ["LA6576-8", "LA6577-6"]
    assert [r["valueString"] for r in out if "valueString" in r] == ["判定保留"]  # unknown to the engines


@pytest.mark.parametrize("name", ["csv_site.yaml", "cgrd_sql_site.yaml"])
def test_the_site_templates_read_the_row_unit(name: str) -> None:
    """The templates extend the shared resources, whose lab Observation checks ``unit``: each must map the HIS unit
    column to it, or the mapping stops at the first lab row (``unit_column`` is never skipped)."""
    doc = yaml.safe_load((MAPPING_DIR / "templates" / name).read_text(encoding="utf-8"))
    assert doc["extends"] == "../tw_core/demo_his.yaml"
    assert "unit" in doc["tables"]["lab"]["rename"].values()


@pytest.mark.parametrize("path", [TW, JP])
def test_shipped_mappings_check_the_row_unit_and_declare_unit_defaults(path: Path) -> None:
    m = Mapping.load(path)
    args = mapping_check.lab_value_args(m, "lab")
    assert args is not None and args["unit_column"] == "unit"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw.get("unit_defaults"), "declared in the file itself: a fhir_bulk feed reads it without extends"
    assert m.unit_defaults[LOINC_CREATININE] == "mg/dL" and m.unit_defaults["1988-5"] == "mg/L"
    assert mapping_check.unit_default_conflicts(m) == []
    quantity = {r["code"] for r in m.lookups["lab"].rows.values() if r["system"] == "loinc" and r["ucum"]}
    assert quantity <= set(m.unit_defaults)  # every LOINC quantity analyte of the lookup has its default


def test_a_unit_default_against_the_lookup_fails_the_check(tmp_path: Path) -> None:
    site = tmp_path / "site.yaml"
    site.write_text(
        f"version: 1\nextends: {TW}\ntz: Asia/Taipei\ntables: {{lab: {{source: lab, key: lab_no}}}}\n"
        'unit_defaults: {"1988-5": mg/dL}\n',
        encoding="utf-8",
    )
    (tmp_path / "lab_local_to_loinc.csv").write_bytes((TW.parent / "lab_local_to_loinc.csv").read_bytes())
    m = Mapping.load(site)
    assert mapping_check.unit_default_conflicts(m) == [
        "unit_defaults 1988-5: mg/dL but the lab lookup writes mg/L (CRP)"
    ]
    _write_csv(tmp_path / "lab.csv", [_lab_row(result_value="1.0", unit="mg/dL")])
    rep = mapping_check.check(site, "csv", str(tmp_path))
    assert rep["passed"] is False and rep["unit_default_conflicts"]


def test_mapping_check_lists_unit_pairs_and_raw_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Acceptance: ``mapping_check`` lists every (analyte, row unit) pair with how it is read and, for a mismatch,
    the tested factor; and every raw text of a coded result with what it reads as."""
    _write_csv(
        tmp_path / "lab.csv",
        [
            _lab_row(),
            _lab_row(lab_no="L2", result_value="1.0", unit="mg/dL"),
            _lab_row(lab_no="L3", result_value="1.1", unit=""),
            _lab_row(lab_no="L4", local_code="ALT", result_value="30", unit="IU/L"),
            _lab_row(lab_no="L5", local_code="HBSAG", result_value="陰性", unit=""),
            _lab_row(lab_no="L6", local_code="HBSAG", result_value="POS", unit=""),
            _lab_row(lab_no="L7", local_code="HBSAG", result_value="判定保留", unit=""),
            _lab_row(lab_no="L8", local_code="HBSAG", result_value="see note", unit=""),
            _lab_row(lab_no="L9", local_code="UA", result_value="30", unit="IU/L"),
        ],
    )
    rep = mapping_check.check(TW, "csv", str(tmp_path))
    lab = rep["tables"]["lab"]
    pairs = {(p["code"], p["row_unit"]): p for p in lab["unit_pairs"]}
    assert pairs[("CRE", "µmol/L")]["read"] == "unit_mismatch: no value"
    assert math.isclose(pairs[("CRE", "µmol/L")]["factor"], 1 / 88.4, rel_tol=1e-6)
    assert "source_unit µmol/L" in pairs[("CRE", "µmol/L")]["proposal"]
    assert pairs[("CRE", "mg/dL")]["read"] == "same unit"
    assert pairs[("CRE", "")]["read"] == "no unit: read in the lookup's unit"
    # NEW-STD-4 (D-585): for an enzyme activity IU/L is U/L; for any other analyte it is still another unit
    assert pairs[("ALT", "IU/L")]["read"] == "same unit"
    assert pairs[("UA", "IU/L")]["factor"] is None and "no tested factor" in pairs[("UA", "IU/L")]["proposal"]
    values = {q["raw"]: q["read"] for q in lab["qualitative_values"]}
    assert values == {
        "陰性": "NEG (shared table)",
        "POS": "POS (site answer)",
        "判定保留": "unknown (unsettled on purpose)",
        "see note": "unknown (not recognised: stays text)",
    }
    assert rep["passed"] is True  # mismatches and unread values are warnings, not a failed mapping
    assert mapping_check.main(["--mapping", str(TW), "--source", "csv", "--path", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "CRE [µmol/L] vs mg/dL: unit_mismatch: no value" in printed and "'陰性': NEG (shared table)" in printed
