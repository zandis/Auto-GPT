"""NEW-B-30 (D-671): the night's validation line names a choice element as the HL7 validator writes it.

Lane E ran the real validator once on synthetic resources (D-682): the night's lines held no value, but three of
six said ``?`` for the element, because the validator writes a choice element as ``Observation.value[x].value``
and as ``Observation.value.ofType(Quantity)``, two forms the line's shape for an element (D-669) did not take.
The line said less than it could. The two forms are names and a type's name: no value of a row."""

from __future__ import annotations

from typing import Any

import pytest
from adapter.validate.validator import Hl7Validator

VALUE = "WANG XIAOMING"  # a made-up name, standing for a value of a row
FILE_URL = "http://hl7.org/fhir/StructureDefinition/operationoutcome-file"
MSG_ID = "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id"


def _line(place: str, code: str = "invalid", mid: str = "", fname: str = "r00000-Observation.json") -> str:
    issue: dict[str, Any] = {"severity": "error", "code": code, "expression": [place],
                             "details": {"text": f"the validator's sentence about '{VALUE}'"}}  # fmt: skip
    if mid:
        issue["extension"] = [{"url": MSG_ID, "valueCode": mid}]
    doc = {"resourceType": "Bundle", "entry": [{"resource": {
        "resourceType": "OperationOutcome", "extension": [{"url": FILE_URL, "valueString": fname}],
        "issue": [issue]}}]}  # fmt: skip
    (line,) = Hl7Validator._parse(doc, 1).messages
    assert VALUE not in line
    return line


# the forms of the run lane E recorded in D-682: two lines in full, and the two element forms that read "?"
def test_the_two_lines_of_the_real_run_read_as_recorded() -> None:
    assert _line("Patient.gender", "code-invalid", "Terminology_TX_NoValid_16", "r00000-Patient.json") == (
        "r00000-Patient.json Patient.gender: code-invalid (Terminology_TX_NoValid_16)"
    )
    assert _line("Patient.birthDate", "invalid", "Type_Specific_Checks_DT_Date_Valid", "r00000-Patient.json") == (
        "r00000-Patient.json Patient.birthDate: invalid (Type_Specific_Checks_DT_Date_Valid)"
    )


@pytest.mark.parametrize(
    "place",
    [
        "Observation.value[x].value",  # as the real run wrote it
        "Observation.value.ofType(Quantity)",  # as the real run wrote it
        "Observation.value.ofType(Quantity).value",
        "Observation.component[0].value[x]",
        "Observation.component[2].value.ofType(CodeableConcept).coding[0].code",
        "Bundle.entry[0].resource.ofType(Observation).value[x]",
    ],
)
def test_a_choice_element_is_named_as_the_validator_writes_it(place: str) -> None:
    assert _line(place) == f"r00000-Observation.json {place}: invalid"


@pytest.mark.parametrize(
    "place",
    [
        f"Observation.value.ofType({VALUE})",  # a type's name is one word of letters and digits
        "Observation.value.ofType(Quantity, Range)",
        "Observation.value.ofType()",
        "Observation.value.ofType(Quantity",
        "Observation.value.where(code = 'x')",
        "Observation.value.exists()",
        "Observation.value[y]",
        "Observation.value[x][x]",
        "Observation.value[0][x]",
        "Observation.value[WANG-XIAOMING]",
        "Observation.identifier:WANG",
        "ofType(Quantity).value",  # a path starts with a resource's name
        "Observation..value",
        "Observation.value.",
        "Observation.value.ofType(王小明)",  # letters are the plain ones
        "Observation.value.ofType(WANG_XIAOMING)",
        "Observation.王小明",
        "Observation.value[x][0]",
        "Observation.value.ofType(Quantity)[0]",
        "Observation.value.ofType(Quantity)[x]",
        "Observation.valueofType(Quantity)",
        "Observation.value[٣]",  # a numbered place is written in plain digits
        "Observation.value[１]",
        "Observation.value.ofType(Quantity).ofType(Range)",  # a type is named once
    ],
)
def test_any_other_form_of_an_element_is_still_a_question_mark(place: str) -> None:
    assert _line(place) == "r00000-Observation.json ?: invalid"


def test_the_publishs_words_for_a_refusal_never_repeat_a_body_that_is_not_the_lakes() -> None:
    """Found by this card's review: with no ``detail`` in the answer the whole body was put before the error."""
    import httpx
    from adapter.publish import _said

    request = httpx.Request("POST", "http://lake/promote")
    page = httpx.Response(502, text=f"<html>Bad Gateway {VALUE}</html>", request=request)
    said = _said(httpx.HTTPStatusError("502 Bad Gateway for url http://lake/promote", request=request, response=page))
    assert VALUE not in said and "502" in said
    lake = httpx.Response(409, json={"detail": "lake snapshot 2026-10-04 was built again since"}, request=request)
    said = _said(httpx.HTTPStatusError("409 Conflict for url http://lake/promote", request=request, response=lake))
    assert said.startswith("lake snapshot 2026-10-04 was built again since (409 Conflict")
    odd = httpx.Response(409, json={"detail": {"x": VALUE}}, request=request)
    assert VALUE not in _said(httpx.HTTPStatusError("409 Conflict", request=request, response=odd))
