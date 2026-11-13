"""NEW-B-16 (D-536): a drug code is ATC only when its coding's system IS the ATC system.

The lake's flattener and the OMOP loader took a coding for ATC when its system merely contained the letters
"atc". A house code system whose address holds them (``.../CodeSystem/batch-catalog``: "b-atc-h") landed in the
lake's ``atc`` column and was then matched by prefix as ATC by whatever reads that column: a house code "C10..."
would count as a statin."""

from __future__ import annotations

from typing import Any

import pytest
from lake.flatten import ATC_SYSTEM, Flattener, is_atc_system

pytestmark = pytest.mark.nodb
HOUSE = "https://hospa.test/fhir/CodeSystem/batch-catalog"  # holds the letters "atc"; it is not ATC
NHI = "https://twcore.mohw.gov.tw/ig/twcore/CodeSystem/medication-nhi-tw"


def _order(codings: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "id": "m1",
        "status": "active",
        "intent": "order",
        "subject": {"reference": "Patient/p1"},
        "authoredOn": "2026-09-01",
        "medicationCodeableConcept": {"coding": codings},
    }


def _row(codings: list[dict[str, str]]) -> dict[str, Any]:
    (row,) = Flattener("Asia/Taipei").flatten({"MedicationRequest": [_order(codings)]})["medication"]
    return dict(row)


def test_a_house_code_whose_system_holds_the_letters_is_not_atc() -> None:
    row = _row([{"system": HOUSE, "code": "C10AA05"}])
    assert row["atc"] is None and row["nhi_code"] == "C10AA05"  # the order's own code, never read as a statin


def test_the_atc_system_is_atc_beside_a_house_code_in_either_order() -> None:
    for codings in (
        [{"system": HOUSE, "code": "H-77"}, {"system": ATC_SYSTEM, "code": "C10AA05"}],
        [{"system": ATC_SYSTEM, "code": "C10AA05"}, {"system": HOUSE, "code": "H-77"}],
        [{"system": NHI, "code": "AC00011100"}, {"system": ATC_SYSTEM, "code": "C10AA05"}],
    ):
        row = _row(codings)
        assert row["atc"] == "C10AA05" and row["nhi_code"] in ("H-77", "AC00011100"), codings


@pytest.mark.parametrize(
    ("system", "atc"),
    [
        ("http://www.whocc.no/atc", True),
        ("http://www.whocc.no/atc/", True),  # a trailing slash is the same address
        ("HTTP://WWW.WHOCC.NO/ATC", True),
        ("https://www.whocc.no/atc", True),  # the scheme is not what names the system
        ("urn:oid:2.16.840.1.113883.6.73", True),  # the same system by its OID
        (HOUSE, False),
        ("https://hospa.test/atc", False),
        ("http://www.whocc.no/atc-ddd-local", False),
        ("", False),
        (None, False),
    ],
)
def test_what_is_the_atc_system(system: str | None, atc: bool) -> None:
    assert is_atc_system(system) is atc
