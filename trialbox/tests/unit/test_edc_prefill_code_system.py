"""D-598: a draft eCRF value is read only from a record whose code is of the item's code system. A hospital's own
code that happens to read like a LOINC or an ICD-10 code is another code. Synthetic data only (``tests.edc_kit``)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from datacore import forms
from edc import mapping
from edc.prefill import LakeFacts

from tests import edc_kit as k

LOINC = "http://loinc.org"
ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
ICD10 = "http://hl7.org/fhir/sid/icd-10"
HOUSE = "http://hospital.example/codes"


def _draft(tmp_path: Path, facts: k.FakeFacts) -> dict[str, dict[str, Any]]:
    svc, _, _ = k.service(tmp_path, facts)
    k.ready(svc)
    return {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}


def _weight(system: Any) -> dict[str, Any]:
    return {"row": "a", "code": "29463-7", "system": system, "d": date(2026, 11, 1), "value_num": 72.5, "unit": "kg",
            "cmp": ""}  # fmt: skip


@pytest.mark.parametrize("system", [HOUSE, "", None, "urn:oid:1.2.392.200119.4.504", ICD10CM, "HTTP://LOINC.ORG/x"])
def test_a_result_under_another_code_system_is_never_the_value(tmp_path: Path, system: Any) -> None:
    facts = k.FakeFacts()
    facts.data["observation"] = [_weight(system)]
    w = _draft(tmp_path, facts)["weight"]
    assert (w["state"], w["value"], w["why"], w["citation"]) == ("unknown", "", "no_record", None)


def test_a_loinc_result_is_the_value_as_before(tmp_path: Path) -> None:
    facts = k.FakeFacts()
    facts.data["observation"] = [_weight(LOINC)]
    w = _draft(tmp_path, facts)["weight"]
    assert (w["state"], w["value"]) == ("drafted", "72.5") and w["citation"]["row"] == "a"


def test_a_house_result_does_not_make_a_conflict_with_the_loinc_one(tmp_path: Path) -> None:
    facts = k.FakeFacts()
    facts.data["observation"] = [_weight(LOINC), {**_weight(HOUSE), "row": "b", "value_num": 75.0}]
    w = _draft(tmp_path, facts)["weight"]
    assert (w["state"], w["value"]) == ("drafted", "72.5")


def _gout(system: Any) -> dict[str, Any]:
    return {"row": "c1", "code": "M10.9", "system": system, "d": date(2024, 1, 10), "status": "active"}


@pytest.mark.parametrize("system", [HOUSE, "", None, "http://hl7.org/fhir/sid/icd-9-cm", LOINC])
def test_a_diagnosis_under_another_code_system_never_drafts_yes(tmp_path: Path, system: Any) -> None:
    facts = k.FakeFacts()
    facts.data["condition"] = [_gout(system)]
    g = _draft(tmp_path, facts)["mh_gout"]
    assert (g["state"], g["value"], g["why"]) == ("unknown", "", "no_record")


@pytest.mark.parametrize("system", [ICD10CM, ICD10])
def test_an_icd10_diagnosis_drafts_yes_as_before(tmp_path: Path, system: str) -> None:
    facts = k.FakeFacts()
    facts.data["condition"] = [_gout(system)]
    g = _draft(tmp_path, facts)["mh_gout"]
    assert g["state"] == "drafted" and g["citation"]["row"] == "c1"


def test_an_item_that_names_its_system_reads_that_system_only(tmp_path: Path) -> None:
    """An item map row with ``system`` = WHO ICD-10 does not read an ICD-10-CM row of the same code."""
    items = [{**m, "system": ICD10} if m["item"] == "mh_gout" else m for m in k.MAP]
    for system, state in ((ICD10, "drafted"), (ICD10CM, "unknown")):
        facts = k.FakeFacts()
        facts.data["condition"] = [_gout(system)]
        svc, _, _ = k.service(tmp_path / state, facts)
        k.ready(svc)
        svc.put_map(k.STUDY, items, k.TARGET, "crc")
        got = {r["item"]: r for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc")}
        assert got["mh_gout"]["state"] == state


@pytest.mark.parametrize(("item", "system", "refused"), [
    ("weight", "LOINC", True), ("weight", ICD10CM, True), ("weight", LOINC, False), ("weight", "", False),
    ("mh_gout", "ICD-10", True), ("mh_gout", LOINC, True), ("mh_gout", ICD10, False), ("mh_gout", ICD10CM, False),
])  # fmt: skip
def test_the_map_check_refuses_a_code_system_the_box_does_not_read(item: str, system: str, refused: bool) -> None:
    fields = {f.name: f for f in (forms.field_of(r) for r in k.CRF)}
    items = [mapping.ItemMap.from_dict({**m, "system": system} if m["item"] == item else m) for m in k.MAP]
    bad = mapping.check(items, fields, {"record_id", "tb_screening_no"})
    assert ({"item": item, "code": "system"} in bad) is refused


def test_the_lake_reading_carries_each_row_s_code_system() -> None:
    asked: list[str] = []

    class Lake:
        def snapshot(self) -> str:
            return "s"

        def query(self, sql: str, params: list[Any], snap: Any) -> Any:
            asked.append(sql)
            return type("T", (), {"to_pylist": lambda self: []})()

    facts = LakeFacts(Lake())
    for source in ("observation", "condition"):
        facts.rows("p", source)
    assert all(" system" in sql.split(" FROM ")[0] for sql in asked) and len(asked) == 2
