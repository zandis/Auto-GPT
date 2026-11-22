"""Bug hunt BH1, area 4 (parsing of hospital feeds): probes of the ``fhir_bulk`` path. Synthetic data only.

Entry point: a FHIR Bulk ``$export`` folder read by ``python -m adapter.cli run`` with source ``fhir_bulk``
(``adapter.pipeline._run_ingest``): every resource goes through :func:`adapter.pipeline.pseudonymise_bulk` and is
spooled to the lake's NDJSON snapshot and fhir-store; the lake build then flattens it (``lake.flatten.Flattener``).

Each probe asserts the safe behaviour and is an expected failure until its finding is fixed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

KEY = b"k" * 32
MRN = "00012345"
NAME = "試験 花子"


def _pseudonymised(export: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from adapter.pipeline import pseudonymise_bulk

    return list(pseudonymise_bulk(iter(export), KEY))


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-02: fhir_bulk keeps the patient's name and chart number in narrative and display",
)
def test_bulk_pseudonymisation_drops_names_and_chart_numbers_from_narrative_and_display() -> None:
    """A conformant export carries the patient's name in ``Patient.text.div`` (the generated narrative) and in a
    reference's ``display``, and the chart number in a logical reference's ``identifier``; none may reach the lake."""
    export: list[dict[str, Any]] = [
        {
            "resourceType": "Patient",
            "id": MRN,
            "text": {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{NAME} {MRN}</div>'},
            "name": [{"text": NAME}],
            "identifier": [{"value": MRN}],
            "gender": "female",
            "birthDate": "1960-01-01",
        },
        {
            "resourceType": "Condition",
            "id": "C1",
            "subject": {
                "reference": f"Patient/{MRN}",
                "display": NAME,
                "identifier": {"system": "urn:example:mrn", "value": MRN},
            },
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9"}]},
        },
    ]
    text = json.dumps(_pseudonymised(export), ensure_ascii=False)
    assert NAME not in text
    assert MRN not in text


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-03: an absolute or versioned Patient reference keeps the chart number, unlinked",
)
@pytest.mark.parametrize(
    "ref",
    [f"https://his.example.invalid/fhir/Patient/{MRN}", f"Patient/{MRN}/_history/2"],
    ids=["absolute", "versioned"],
)
def test_bulk_reference_forms_reach_the_patients_pseudonym(ref: str) -> None:
    """FHIR R4 allows an absolute URL and a version-specific reference (``Patient/x/_history/n``). Each must point at
    the Patient's pseudonym and must not carry the chart number."""
    from tb_common.crypto import pid_for_mrn

    export: list[dict[str, Any]] = [
        {"resourceType": "Patient", "id": MRN, "gender": "female", "birthDate": "1960-01-01"},
        {"resourceType": "Condition", "id": "C1", "subject": {"reference": ref}},
    ]
    out = _pseudonymised(export)
    cond = next(r for r in out if r["resourceType"] == "Condition")
    assert MRN not in json.dumps(out)
    assert cond["subject"]["reference"] == f"Patient/{pid_for_mrn(KEY, MRN)}"


@pytest.mark.xfail(
    strict=True,
    reason="open finding: BH1-04: a valid FHIR partial date (birthDate 1960-05) fails the whole lake build",
)
@pytest.mark.parametrize("birth", ["1960", "1960-05"])
def test_a_partial_birth_date_is_read_not_fatal(birth: str) -> None:
    """FHIR R4 ``date`` allows a year or a year and month. A Patient of a conformant export with such a birth date
    must be flattened (its birth date unknown or at its precision), not raise and fail the night's lake build."""
    from lake.flatten import Flattener

    patient = {"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": birth}
    rows = Flattener("Asia/Tokyo").flatten({"Patient": [patient]})
    assert [r["pid"] for r in rows["patient"]] == ["p1"]
