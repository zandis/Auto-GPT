"""NEW-DIN-9 (DIN-009, DIN-017; D-590): a site declares its unit spellings; lost values are counted; a value with no
unit must be plausible."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping
from tb_common import labvalue

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
LOOKUP = BASE.parent / "lab_local_to_loinc.csv"


def test_the_shared_rule_stands_the_same_unknown_text_on_both_sides_is_no_unit_anybody_can_check() -> None:
    """D-215, unchanged: a value comes back only when both units are one UCUM code."""
    for unit in ("COI", "萬/μL", "thou/uL"):
        assert labvalue.units_agree(unit, unit) is False


def _site(tmp_path: Path, extra: list[dict[str, str]], columns: tuple[str, ...] = (), top: str = "") -> Mapper:
    """The shared mapping with look-up rows added (a site's own analytes and spellings)."""
    with LOOKUP.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    fields = [*rows[0].keys(), *columns]
    with (tmp_path / LOOKUP.name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for r in [*rows, *({**rows[0], **e} for e in extra)]:
            w.writerow({k: r.get(k, "") for k in fields})
    (tmp_path / "m.yaml").write_text(BASE.read_text(encoding="utf-8") + top, encoding="utf-8")
    return Mapper(Mapping.load(tmp_path / "m.yaml"), b"k" * 32, "s")


def _lab(code: str, value: str, unit: str, no: str = "L1") -> dict[str, str]:
    return {"lab_no": no, "mrn": "P1", "local_code": code, "item_name": "x", "result_value": value, "unit": unit,
            "sample_datetime": "2026-05-30 10:30:00"}  # fmt: skip


def _one(mapper: Mapper, row: dict[str, str]) -> dict[str, Any]:
    (res,) = mapper.map_table("lab", iter([row]))
    return dict(res)


SPELLINGS = """
unit_spellings:
  "thou/uL": 10*3/uL
  "萬/μL": 10*4/uL
  "mg/ dl.": mg/dL
"""


def test_a_site_takes_a_new_spelling_into_use_by_a_line_in_its_mapping(tmp_path: Path) -> None:
    mapper = _site(tmp_path, [
        {"local_code": "WBC2", "code": "6690-2", "ucum": "10*3/uL", "factor": "1", "source_unit": "10*3/uL"},
        {"local_code": "PLT2", "code": "777-3", "ucum": "10*3/uL", "factor": "10", "source_unit": "10*4/uL"},
    ], top=SPELLINGS)  # fmt: skip
    res = _one(mapper, _lab("WBC2", "6.5", "thou/uL"))
    assert res["valueQuantity"] == {"value": 6.5, "unit": "10*3/uL", "system": "http://unitsofmeasure.org",
                                    "code": "10*3/uL"}  # fmt: skip
    assert (
        _one(mapper, _lab("WBC2", "6.5", " thou / uL "))["valueQuantity"]["value"] == 6.5
    )  # blanks are not part of it
    assert _one(mapper, _lab("PLT2", "25.1", "萬/μL"))["valueQuantity"]["value"] == 251
    assert _one(mapper, _lab("CRE", "1.1", "mg/ dl."))["valueQuantity"]["value"] == 1.1
    assert not mapper.unmapped
    other = _one(mapper, _lab("WBC2", "6.5", "萬/μL"))  # the spelling of another unit: still no value
    assert "valueQuantity" not in other and other["dataAbsentReason"]["text"] == labvalue.UNIT_MISMATCH
    assert "valueQuantity" not in _one(mapper, _lab("WBC2", "6.5", "百/μL"))  # nobody declared it


@pytest.mark.parametrize(("line", "why"), [
    ('"thou/uL": thousands', "not a UCUM code the box knows"),
    ('"thou/uL": ""', "not a UCUM code the box knows"),
    ('"mg/dL": g/dL', "already means"),
    ('"": mg/dL', "not a UCUM code"),
])  # fmt: skip
def test_a_spelling_declared_wrongly_stops_the_mapping_from_loading(tmp_path: Path, line: str, why: str) -> None:
    from adapter.mapping.engine import MappingError

    with pytest.raises(MappingError, match=why):
        _site(tmp_path, [], top=f"\nunit_spellings:\n  {line}\n")
    with pytest.raises(MappingError, match="unit_spellings is a map"):
        _site(tmp_path, [], top="\nunit_spellings: [mg/dL]\n")


def test_the_mapping_check_reads_a_site_spelling_as_the_night_does(tmp_path: Path) -> None:
    from tools import mapping_check

    mapper = _site(tmp_path, [{"local_code": "WBC2", "code": "6690-2", "ucum": "10*3/uL", "factor": "1",
                               "source_unit": "10*3/uL"}], top=SPELLINGS)  # fmt: skip
    args = {"lookup": "lab", "key": "local_code", "column": "result_value", "unit_column": "unit"}
    pairs = mapping_check.unit_pairs(mapper.m, args, [_lab("WBC2", "6.5", "thou/uL"), _lab("WBC2", "6.5", "百/μL")])
    assert {p["row_unit"]: p["read"] for p in pairs} == {"thou/uL": "same unit", "百/μL": "unit_mismatch: no value"}


def test_a_unit_mismatch_is_counted_per_lab_code_once_a_row(tmp_path: Path) -> None:
    mapper = _site(tmp_path, [])
    rows = [_lab("CRE", "97", "umol/L", "L1"), _lab("CRE", "88", "umol/L", "L2"), _lab("UA", "300", "umol/L", "L3"),
            _lab("CRE", "1.1", "mg/dL", "L4")]  # fmt: skip
    assert len(list(mapper.map_table("lab", iter(rows)))) == 4  # the results are kept, without a number
    assert dict(mapper.unmapped) == {("lab", "unit_mismatch", "CRE"): 2, ("lab", "unit_mismatch", "UA"): 1}
    assert mapper.unmapped_summary() == {"lab": {"unit_mismatch": {"rows": 3, "codes": 2}}}


@pytest.mark.parametrize(("code", "value", "ok"), [
    ("CRE", "1.1", True), ("CRE", "88", False), ("CRE", "0.05", False), ("CRE", "20", True), ("CRE", "0.1", True),
    ("UA", "6.2", True), ("UA", "360", False), ("HBA1C", "7.2", True), ("HBA1C", "0.072", False), ("HBA1C", "53", False),
    ("CRE", "<0.1", True), ("CRE", ">30", False), ("CRE", "88 H", False),
])  # fmt: skip
def test_a_value_with_no_unit_must_be_plausible_in_the_look_ups_unit(
    tmp_path: Path, code: str, value: str, ok: bool
) -> None:
    mapper = _site(tmp_path, [])
    if code not in mapper.m.lookups["lab"].rows:
        pytest.skip(f"the shared look-up has no {code}")
    res = _one(mapper, _lab(code, value, ""))
    assert ("valueQuantity" in res) is ok
    if not ok:
        # no value[x] at all, like a unit mismatch: a text value would be read back as a number by the lake
        assert "valueString" not in res and res["dataAbsentReason"]["text"] == labvalue.NO_UNIT_IMPLAUSIBLE
        assert res["note"] == [{"text": value}]
        assert dict(mapper.unmapped) == {("lab", "no_unit_implausible", code): 1}
        from lake.flatten import Flattener

        row = Flattener().observation(res)
        assert row["value_num"] is None and row.get("value_text") in (None, "")
    else:
        assert not mapper.unmapped


def test_a_value_that_states_its_unit_is_not_range_checked(tmp_path: Path) -> None:
    mapper = _site(tmp_path, [])
    assert _one(mapper, _lab("CRE", "88", "mg/dL"))["valueQuantity"]["value"] == 88 and not mapper.unmapped


def test_the_sites_look_up_can_state_a_range_and_it_wins(tmp_path: Path) -> None:
    mapper = _site(tmp_path, [
        {"local_code": "CRP9", "code": "1988-5", "ucum": "mg/L", "factor": "10", "source_unit": "mg/dL",
         "plausible_low": "0", "plausible_high": "500"},
        {"local_code": "CRE9", "code": "2160-0", "ucum": "mg/dL", "factor": "1", "source_unit": "",
         "plausible_low": "0.1", "plausible_high": "100"},
    ], ("plausible_low", "plausible_high"))  # fmt: skip
    assert _one(mapper, _lab("CRP9", "5", ""))["valueQuantity"]["value"] == 50  # the range is in the unit written
    assert "valueQuantity" not in _one(mapper, _lab("CRP9", "51", ""))  # 510 mg/L
    assert _one(mapper, _lab("CRE9", "88", ""))["valueQuantity"]["value"] == 88  # the site widened it
    assert dict(mapper.unmapped) == {("lab", "no_unit_implausible", "CRP9"): 1}


def test_a_range_the_look_up_states_badly_stops_the_mapping_from_loading(tmp_path: Path) -> None:
    from adapter.mapping.engine import MappingError

    for low, high in (("low", "20"), ("0.1", ""), ("", "20"), ("20", "0.1"), ("nan", "nan"), ("0.1", "inf")):
        with pytest.raises(MappingError, match="plausible"):  # when the mapping loads, not row by row at night
            _site(tmp_path, [{"local_code": "CRE8", "code": "2160-0", "ucum": "mg/dL", "factor": "1",
                              "plausible_low": low, "plausible_high": high}], ("plausible_low", "plausible_high"))  # fmt: skip


def test_the_built_in_ranges_are_only_used_in_their_own_unit(tmp_path: Path) -> None:
    """Creatinine written in µmol/L by the look-up: the mg/dL range says nothing about it."""
    mapper = _site(tmp_path, [{"local_code": "CRE7", "code": "2160-0", "ucum": "umol/L", "factor": "1",
                               "source_unit": "umol/L"}])  # fmt: skip
    assert _one(mapper, _lab("CRE7", "88", ""))["valueQuantity"]["value"] == 88 and not mapper.unmapped


def test_two_spellings_that_fold_to_one_cannot_mean_two_units(tmp_path: Path) -> None:
    from adapter.mapping.engine import MappingError

    with pytest.raises(MappingError, match="declared twice"):
        _site(tmp_path, [], top='\nunit_spellings:\n  "thou/uL": 10*3/uL\n  "thou / uL": 10*4/uL\n')
    _site(tmp_path, [], top='\nunit_spellings:\n  "thou/uL": 10*3/uL\n  "thou / uL": 10*3/uL\n')  # the same: fine


def test_a_site_mapping_adds_its_spellings_to_the_ones_it_extends(tmp_path: Path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text(BASE.read_text(encoding="utf-8") + '\nunit_spellings:\n  "thou/uL": 10*3/uL\n', encoding="utf-8")
    (tmp_path / LOOKUP.name).write_bytes(LOOKUP.read_bytes())
    site = tmp_path / "site.yaml"
    site.write_text(
        f'version: 1\nname: s\nextends: {base}\ntz: Asia/Taipei\nunit_spellings:\n  "萬/μL": 10*4/uL\n'
        "tables:\n  lab: {source: lab, key: lab_no}\n",
        encoding="utf-8",
    )
    assert Mapping.load(site).unit_spellings == {"thou/uL": "10*3/uL", "萬/μL": "10*4/uL"}


def test_a_lost_value_is_counted_under_the_look_ups_code_not_under_each_spelling_of_it(tmp_path: Path) -> None:
    mapper = _site(tmp_path, [])
    rows = [_lab("CRE", "97", "umol/L", "L1"), _lab("cre", "88", "umol/L", "L2"), _lab(" CRE ", "88", "", "L3")]
    list(mapper.map_table("lab", iter(rows)))
    assert dict(mapper.unmapped) == {("lab", "unit_mismatch", "CRE"): 2, ("lab", "no_unit_implausible", "CRE"): 1}


def test_the_mapping_checks_proposal_names_the_code_a_site_spelling_stands_for(tmp_path: Path) -> None:
    from tools import mapping_check

    mapper = _site(tmp_path, [{"local_code": "WBC2", "code": "6690-2", "ucum": "10*3/uL", "factor": "1",
                               "source_unit": "10*3/uL"}], top=SPELLINGS)  # fmt: skip
    args = {"lookup": "lab", "key": "local_code", "column": "result_value", "unit_column": "unit"}
    (pair,) = mapping_check.unit_pairs(mapper.m, args, [_lab("WBC2", "6.5", "萬/μL")])
    assert pair["read"] == "unit_mismatch: no value" and "source_unit 10*4/uL, factor" in pair["proposal"]
