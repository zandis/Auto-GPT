"""D-596: a lab number the mapping cannot compute is one rejected row with or without a unit; a look-up factor is
above zero."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping, MappingError
from adapter.pipeline import reject_key
from tb_common import labvalue

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
LOOKUP = BASE.parent / "lab_local_to_loinc.csv"
CASES = [("CRE", "mg/dL"), ("CRE", ""), ("ALT", "U/L"), ("ALT", ""), ("CRP", "mg/dL"), ("CRP", "")]


def _lab(code: str, value: str, unit: str) -> dict[str, str]:
    return {"lab_no": "L1", "mrn": "P1", "local_code": code, "item_name": "x", "result_value": value, "unit": unit,
            "sample_datetime": "2026-05-30 10:30:00"}  # fmt: skip


@pytest.fixture
def mapper() -> Mapper:
    return Mapper(Mapping.load(BASE), b"k" * 32, "s")


@pytest.mark.parametrize(("code", "unit"), CASES)
@pytest.mark.parametrize("value", ["9" * 30, "1" + "0" * 40 + ".5", "9" * 60])
def test_a_number_the_mapping_cannot_compute_is_the_same_rejected_row_whatever_its_unit(
    mapper: Mapper, code: str, unit: str, value: str
) -> None:
    """D-527's outcome (an ``ArithmeticError``, which the night counts as one rejected row). Without a unit the
    plausibility check used to come first and keep the row with no value."""
    with pytest.raises(ArithmeticError) as got:
        list(mapper.map_table("lab", iter([_lab(code, value, unit)])))
    assert reject_key(got.value) == "InvalidOperation: a number the mapping cannot compute"
    assert not mapper.unmapped  # not counted as implausible or as a unit mismatch


def test_a_plausible_or_implausible_number_without_a_unit_reads_as_before(mapper: Mapper) -> None:
    (ok,) = mapper.map_table("lab", iter([_lab("CRE", "1.1", "")]))
    assert ok["valueQuantity"]["value"] == 1.1
    (far,) = mapper.map_table("lab", iter([_lab("CRE", "88", "")]))
    assert far["dataAbsentReason"]["text"] == labvalue.NO_UNIT_IMPLAUSIBLE


@pytest.mark.parametrize("value", ["45", "45.5", "0", "12345678901234567890", "0.000001", "<0.3"])
def test_a_number_the_box_can_hold_reads_as_before(mapper: Mapper, value: str) -> None:
    (res,) = mapper.map_table("lab", iter([_lab("ALT", value, "U/L")]))
    assert "valueQuantity" in res and not mapper.unmapped


def _site(tmp_path: Path, factor: str) -> Path:
    with LOOKUP.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    alt = next(r for r in rows if r["local_code"] == "ALT")  # an analyte with no plausible range of its own
    rows.append({**alt, "local_code": "ZERO", "factor": factor})
    with (tmp_path / LOOKUP.name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    (tmp_path / "m.yaml").write_text(BASE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path / "m.yaml"


@pytest.mark.parametrize("factor", ["0", "0.0", "-1", "-0.1", "nan", "inf", "ten", "-inf", "1e-400", "1e400", " "])
def test_a_factor_that_is_not_a_number_above_zero_stops_the_mapping_from_loading(tmp_path: Path, factor: str) -> None:
    with pytest.raises(MappingError, match=r"look-up lab.*ZERO.*factor"):
        Mapping.load(_site(tmp_path, factor))


@pytest.mark.parametrize(("factor", "want"), [("", 5), ("1", 5), ("10", 50), ("0.1", 0.5), (" 2 ", 10)])
def test_a_factor_above_zero_and_an_empty_one_read_as_before(tmp_path: Path, factor: str, want: Any) -> None:
    m = Mapper(Mapping.load(_site(tmp_path, factor)), b"k" * 32, "s")
    (res,) = m.map_table("lab", iter([_lab("ZERO", "5", "")]))
    assert res["valueQuantity"]["value"] == want


def test_a_range_stated_in_the_look_up_does_not_change_the_outcome_either(tmp_path: Path) -> None:
    with LOOKUP.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    alt = next(r for r in rows if r["local_code"] == "ALT")
    fields = [*rows[0].keys(), "plausible_low", "plausible_high"]
    rows.append({**alt, "local_code": "ALTB", "plausible_low": "0", "plausible_high": "1000"})
    with (tmp_path / LOOKUP.name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    (tmp_path / "m.yaml").write_text(BASE.read_text(encoding="utf-8"), encoding="utf-8")
    m = Mapper(Mapping.load(tmp_path / "m.yaml"), b"k" * 32, "s")
    for unit in ("U/L", ""):
        with pytest.raises(ArithmeticError):
            list(m.map_table("lab", iter([_lab("ALTB", "9" * 30, unit)])))
    (far,) = m.map_table("lab", iter([_lab("ALTB", "5000", "")]))
    assert far["dataAbsentReason"]["text"] == labvalue.NO_UNIT_IMPLAUSIBLE
