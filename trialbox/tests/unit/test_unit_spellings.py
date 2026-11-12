"""NEW-STD-4 (STD-004, DIN-009; D-585): the feed's unit reader takes the spellings labs print, and IU/L as U/L for
enzyme activity only.

Before: ``ALT, 45, IU/L`` against a look-up unit ``U/L`` gave ``dataAbsentReason: unit_mismatch``;
``labvalue.ucum('×10^3/μL')`` was None; ``秒`` and ``mL/分/1.73m2`` were not read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping
from tb_common import labunit, labvalue

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
ALT, CRE, INSULIN = "1742-6", "2160-0", "20448-7"


@pytest.mark.parametrize(
    ("written", "code"),
    [
        ("×10^3/μL", "10*3/uL"), ("×10^3/µL", "10*3/uL"), ("× 10^3 / uL", "10*3/uL"), ("✕10^3/μL", "10*3/uL"),
        ("x10^3/μL", "10*3/uL"), ("X10^3/uL", "10*3/uL"), ("千/μL", "10*3/uL"), ("千/uL", "10*3/uL"),
        ("×10^4/μL", "10*4/uL"), ("x10^4/µL", "10*4/uL"), ("万/μL", "10*4/uL"),
        ("×10^6/μL", "10*6/uL"), ("x10^6/µL", "10*6/uL"),
        ("×10^2/μL", "10*2/uL"), ("x10^2/uL", "10*2/uL"), ("10^2/µL", "10*2/uL"), ("10*2/uL", "10*2/uL"),
        ("個/μL", "/uL"), ("個/uL", "/uL"),
        ("mL/分/1.73m2", "mL/min/{1.73_m2}"), ("ｍＬ／分／１．７３ｍ２", "mL/min/{1.73_m2}"),
        ("mL/min/1.73m^2", "mL/min/{1.73_m2}"), ("ml/分/1.73m2", "mL/min/{1.73_m2}"),
        ("秒", "s"), ("sec", "s"), ("mm/時", "mm/h"), ("mm/hr", "mm/h"),
        ("IU/L", "[IU]/L"), ("U/L", "U/L"),
    ],
)  # fmt: skip
def test_a_spelling_a_lab_prints_is_the_unit_it_means(written: str, code: str) -> None:
    assert labvalue.ucum(written) == code
    assert labvalue.units_agree(written, code) is True


@pytest.mark.parametrize("written", ["G/L", "分", "時", "x", "×", "10^3", "×10^5/μL", "秒/分", "COI", "S/CO", "倍",
                                     "copies/mL", "/HPF", "mg/day", "S", "M"])  # fmt: skip
def test_what_cannot_be_told_stays_unknown(written: str) -> None:
    """Never a guess: ``G/L`` is giga per litre in a blood count and grams per litre in an upper-case export."""
    assert labvalue.ucum(written) not in ("s", "min", "h", "m", "10*3/uL")
    if written == "G/L":  # read as an upper-case export's grams per litre, as before: never as a count
        assert labvalue.ucum(written) == "g/L"
    assert labvalue.units_agree(written, "10*3/uL") is False


def test_a_new_count_unit_agrees_with_itself_and_converts_to_nothing() -> None:
    assert labvalue.units_agree("×10^2/μL", "10*2/uL") is True
    assert labvalue.units_agree("×10^2/μL", "10*3/uL") is False  # 52 x10^2 is not 52 x10^3
    assert labvalue.conversion("10*2/uL", "10*3/uL") is None  # not converted here (D-585, 2)


@pytest.mark.parametrize("loinc", sorted(labvalue.ENZYME_ACTIVITY))
@pytest.mark.parametrize(("row", "table"), [("IU/L", "U/L"), ("U/L", "IU/L"), ("ＩＵ／Ｌ", "U/L"), ("iu/l", "U/L"),
                                            ("mIU/mL", "mU/mL"), ("IU/mL", "U/mL"), ("U/L", "U/L")])  # fmt: skip
def test_iu_and_u_are_one_unit_for_enzyme_activity(loinc: str, row: str, table: str) -> None:
    assert labvalue.units_agree(row, table, loinc) is True
    got = labvalue.read("45", row, table, loinc)
    assert (got.value, got.reason) == (45.0, None)


@pytest.mark.parametrize("loinc", [None, "", INSULIN, CRE, "3084-1"])
def test_iu_and_u_stay_apart_for_every_other_analyte(loinc: str | None) -> None:
    assert labvalue.units_agree("IU/L", "U/L", loinc) is False
    assert labvalue.units_agree("mIU/mL", "mU/mL", loinc) is False
    assert labvalue.read("45", "IU/L", "U/L", loinc).reason == labvalue.UNIT_MISMATCH


def test_an_enzyme_in_another_unit_is_still_a_mismatch() -> None:
    for row in ("ukat/L", "mg/dL", "IU/mL", "mIU/L", "%"):
        assert labvalue.units_agree(row, "U/L", ALT) is False, row
    assert labvalue.units_agree("", "U/L", ALT) is None  # no unit on the row: the site's declared unit applies


def test_the_enzyme_list_is_catalytic_activity_only() -> None:
    assert {ALT, "1920-8", "6768-6", "2532-0", "2157-6", "2324-2"} <= labvalue.ENZYME_ACTIVITY
    assert not labvalue.ENZYME_ACTIVITY & set(labvalue.MOLAR)  # no analyte with a molar mass is an enzyme activity


# ------------------------------------------------------------------------------------------- through the mapping
def _lab(code: str, value: str, unit: str) -> dict[str, str]:
    return {"lab_no": "L1", "mrn": "P1", "local_code": code, "item_name": "x", "result_value": value, "unit": unit,
            "sample_datetime": "2026-05-30 10:30:00"}  # fmt: skip


@pytest.fixture(scope="module")
def mapper() -> Mapper:
    return Mapper(Mapping.load(MAPPING), b"k" * 32, "s")


@pytest.mark.parametrize("unit", ["IU/L", "U/L", "iu/l", "ＩＵ／Ｌ", ""])
def test_an_alt_result_in_iu_per_litre_is_a_value_in_the_look_ups_unit(mapper: Mapper, unit: str) -> None:
    (obs,) = mapper.map_table("lab", iter([_lab("ALT", "45", unit)]))
    assert obs["valueQuantity"]["value"] == 45 and obs["valueQuantity"]["code"] == "U/L"
    assert "dataAbsentReason" not in obs


def test_a_creatinine_result_in_another_unit_is_still_no_value(mapper: Mapper) -> None:
    for unit in ("umol/L", "IU/L", "µmol/L"):
        (obs,) = mapper.map_table("lab", iter([_lab("CRE", "88", unit)]))
        assert "valueQuantity" not in obs and obs["dataAbsentReason"]["text"] == labvalue.UNIT_MISMATCH


# ------------------------------------------------------------------------------------------- the engines' side
def test_nothing_changes_in_the_table_the_engines_read() -> None:
    """D-585, 5: the compiled SQL and CQL of every ruleset stay as they are. A spelling or a unit added to
    ``labunit.UCUM`` or ``SCALES`` changes the arms ``value_sql`` writes; this card adds none."""
    assert "10*2/uL" not in labunit.UCUM and "10*2/uL" not in labunit.SCALES["number concentration"]
    assert labunit.key("×10^3/μL") not in labunit.FAMILIES and labunit.key("千/μL") not in labunit.FAMILIES
    assert len(labunit.FAMILIES) == 43
    assert labunit.convert(100, "IU/L", "U/L", "http://loinc.org", ALT) is None  # the engines' own rule: lane A's


# ---------------------------------------------------------------- the adversarial review of PR #357 (2026-11-12)
@pytest.mark.parametrize(("typed", "code"), [("×10^3/μL", "10*3/uL"), ("千/μL", "10*3/uL"), ("秒", "s"),
                                             ("mm/時", "mm/h"), ("mL/分/1.73m2", "mL/min/{1.73_m2}"),
                                             ("×10^2/μL", "10*2/uL"), ("mg/dl", "mg/dL"), ("mg/dL", "mg/dL")])  # fmt: skip
def test_a_look_up_typed_in_a_labs_spelling_stores_the_unit_as_its_code(typed: str, code: str) -> None:
    """MED-1: the look-up's own text was stored as the unit, so a row that agreed with ``×10^3/μL`` was stored in a
    unit the engines cannot read, silently. The stored unit is the UCUM code."""
    m = Mapping.load(MAPPING)
    m.lookups["lab"].rows["CRE"] = {**m.lookups["lab"].rows["CRE"], "ucum": typed, "source_unit": ""}
    (obs,) = Mapper(m, b"k" * 32, "s").map_table("lab", iter([_lab("CRE", "52", typed)]))
    q = obs["valueQuantity"]
    assert (q["value"], q["unit"], q["code"]) == (52, code, code)
    if code in labunit.UCUM:
        assert labunit.convert(52, q["code"], code) == 52  # the engines read what was stored


def test_the_enzyme_codes_are_the_ones_the_catalogue_confirms() -> None:
    text = (ROOT / "catalogue/codes_checked.csv").read_text(encoding="utf-8")
    for code in labvalue.ENZYME_ACTIVITY:
        row = next(line for line in text.splitlines() if code in line.split(","))
        assert "Enzymatic activity/volume" in row, code
