"""NEW-DIN-7 (DIN-007, D-587): a status code the map does not know is unknown, for diagnoses, visits and bookings.

Before: D-275's rule covered lab and order status only. A diagnosis ``status=X`` became ``active``, an unknown
visit type ``AMB``, an unknown booking status ``booked``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping
from lake import flatten

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
ACT, NULLFLAVOR = (
    "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "http://terminology.hl7.org/CodeSystem/v3-NullFlavor",
)


@pytest.fixture
def mapper() -> Mapper:
    return Mapper(Mapping.load(MAPPING), b"k" * 32, "s")


def _diag(status: str, **more: str) -> dict[str, str]:
    return {"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": "M05.79", "diag_date": "2024-03-02",
            "recorded_date": "2024-03-02", "status": status, **more}  # fmt: skip


def _one(mapper: Mapper, table: str, row: dict[str, str]) -> dict[str, Any]:
    (res,) = mapper.map_table(table, iter([row]))
    return dict(res)


@pytest.mark.parametrize(("status", "want"), [("A", "active"), ("R", "resolved"), ("", "active"), (" A ", "active"),
                                              ("R ", "resolved")])  # fmt: skip
def test_a_diagnosis_status_the_map_knows_reads_as_before(mapper: Mapper, status: str, want: str) -> None:
    res = _one(mapper, "diagnosis", _diag(status))
    assert res["clinicalStatus"]["coding"][0]["code"] == want and "verificationStatus" not in res
    assert not mapper.unmapped


@pytest.mark.parametrize("status", ["X", "D", "deleted", "9", "a", "ruled out"])
def test_a_diagnosis_status_the_map_does_not_know_is_never_active(mapper: Mapper, status: str) -> None:
    res = _one(mapper, "diagnosis", _diag(status))
    assert "clinicalStatus" not in res
    assert flatten.verification_of(res) == "unconfirmed" and "unconfirmed" in flatten.SUSPECTED
    assert res["code"]["coding"][0]["code"] == "M05.79"  # the record is kept; it decides nothing
    assert dict(mapper.unmapped) == {("diagnosis", "column:status", status): 1}


def test_a_suspected_diagnosis_with_an_unknown_status_is_still_provisional(mapper: Mapper) -> None:
    res = _one(mapper, "diagnosis", _diag("X", suspected="Y"))
    assert flatten.verification_of(res) == "provisional" and "clinicalStatus" not in res


def _enc(enc_type: str) -> dict[str, str]:
    return {"enc_no": "E1", "mrn": "P1", "visit_datetime": "2026-05-12 08:30:00", "dept_code": "RHEU",
            "staff_id": "S1", "enc_type": enc_type}  # fmt: skip


@pytest.mark.parametrize(("enc_type", "want"), [("OPD", "AMB"), ("IPD", "IMP"), ("ER", "EMER"), ("", "AMB"),
                                                (" IPD ", "IMP")])  # fmt: skip
def test_a_visit_type_the_map_knows_reads_as_before(mapper: Mapper, enc_type: str, want: str) -> None:
    res = _one(mapper, "encounter", _enc(enc_type))
    assert res["class"] == {"system": ACT, "code": want} and not mapper.unmapped


@pytest.mark.parametrize("enc_type", ["DAY", "HOME", "opd", "9"])
def test_a_visit_type_the_map_does_not_know_is_unknown_not_out_patient(mapper: Mapper, enc_type: str) -> None:
    res = _one(mapper, "encounter", _enc(enc_type))
    assert res["class"] == {"system": NULLFLAVOR, "code": "UNK"}
    assert dict(mapper.unmapped) == {("encounter", "column:enc_type", enc_type): 1}  # once a row, not once an element


def _appt(status: str) -> dict[str, str]:
    return {"appt_no": "A1", "mrn": "P1", "appt_datetime": "2026-05-12 08:30:00", "duration_min": "15",
            "staff_id": "S1", "dept_code": "RHEU", "status": status}  # fmt: skip


@pytest.mark.parametrize(("status", "want"), [("B", "booked"), ("A", "arrived"), ("C", "cancelled"), ("N", "noshow"),
                                              ("", "booked"), (" C ", "cancelled")])  # fmt: skip
def test_a_booking_status_the_map_knows_reads_as_before(mapper: Mapper, status: str, want: str) -> None:
    assert _one(mapper, "appointment", _appt(status))["status"] == want and not mapper.unmapped


@pytest.mark.parametrize("status", ["Z", "X", "b", "moved"])
def test_a_booking_whose_status_the_map_does_not_know_is_left_out_and_counted(mapper: Mapper, status: str) -> None:
    assert list(mapper.map_table("appointment", iter([_appt(status), _appt(status)]))) == []
    assert dict(mapper.unmapped) == {("appointment", "column:status", status): 2}
    assert mapper.unmapped_summary() == {"appointment": {"column:status": {"rows": 2, "codes": 1}}}


def test_the_status_of_a_lab_result_is_counted_too(mapper: Mapper) -> None:
    """D-275's own case: an unknown result status was already ``unknown``; it is now counted with the others."""
    row = {"lab_no": "L1", "mrn": "P1", "local_code": "CRE", "item_name": "x", "result_value": "1.1", "unit": "mg/dL",
           "sample_datetime": "2026-05-30 10:30:00", "result_status": "ZZ"}  # fmt: skip
    res = _one(mapper, "lab", row)
    assert res["status"] == "unknown" and dict(mapper.unmapped) == {("lab", "column:result_status", "ZZ"): 1}


def test_known_and_unknown_to_are_opposites_for_a_code_and_both_let_a_blank_through_or_not(mapper: Mapper) -> None:
    known, unknown = {"column": "s", "known": ["A", "R"]}, {"column": "s", "unknown_to": ["A", "R"]}
    for value, is_known, is_unknown in (("A", True, False), (" R ", True, False), ("X", False, True),
                                        ("", True, False), (None, True, False), ("  ", True, False)):  # fmt: skip
        assert mapper.cond(known, {"s": value}) is is_known and mapper.cond(unknown, {"s": value}) is is_unknown
