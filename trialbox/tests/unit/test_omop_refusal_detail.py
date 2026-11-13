"""The OMOP store's refusals name the kind of refusal and the schema (resource type, table, column), never a
source record's id nor a row's value (D-681): the text reaches a ``refused`` detail, a log and a page whole."""

from __future__ import annotations

from typing import Any

import pytest

SRCID = "tbrd-rec-7781"  # a source record id: in a site feed it is the hospital's own key of a patient's record
TZ = "Asia/Taipei"


@pytest.fixture
def store(db_url: str) -> Any:
    from omop import schema

    db = schema.connect(db_url, "omop_refdetail")
    yield db
    db.close()


def test_a_record_with_no_observation_column_is_refused_without_its_id() -> None:
    from omop.load import Rec, _to_observation
    from omop.schema import OmopError

    rec = Rec("Procedure", SRCID, 0, "procedure_occurrence", "p-1", None, "confirmed", 1)
    rec.row = {"quantity": 2, "modifier_source_value": "LT"}
    with pytest.raises(OmopError) as e:
        _to_observation(rec)
    text = str(e.value)
    assert SRCID not in text and "LT" not in text
    # what a maintainer needs: the resource type, the table it came from, the columns with no place
    assert "Procedure" in text and "procedure_occurrence" in text
    assert "modifier_source_value" in text and "quantity" in text


def test_a_medication_read_two_ways_is_refused_without_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from omop.load import Rec, _Builder
    from omop.schema import OmopError

    b = _Builder(TZ, "feed", {})
    r = {
        "resourceType": "MedicationRequest",
        "id": SRCID,
        "subject": {"reference": "Patient/p-1"},
        "authoredOn": "2026-09-01",
        "medicationCodeableConcept": {"coding": [{"system": "urn:tbrd:house", "code": "HOUSE-0042"}]},
    }
    real = b.fl.medication

    def other(res: Any) -> Any:
        m = dict(real(res))
        m["nhi_code"] = "ANOTHER-CODE"
        return m

    monkeypatch.setattr(b.fl, "medication", other)
    with pytest.raises(OmopError) as e:
        b.medication(r, Rec("MedicationRequest", SRCID, 0, None, None, None, "confirmed", 1))
    text = str(e.value)
    assert SRCID not in text and "HOUSE-0042" not in text and "ANOTHER-CODE" not in text
    assert "MedicationRequest" in text and "flattener" in text


def test_a_status_change_of_an_absent_record_is_refused_without_its_id(store: Any) -> None:
    from omop.load import set_status
    from omop.schema import OmopError

    with pytest.raises(OmopError) as e:
        set_status(store, ("site", "Condition", SRCID, 0), "confirmed", "steward:t", "read in the chart")
    text = str(e.value)
    assert SRCID not in text
    assert "Condition" in text and "site" in text  # the kind and the resource type: identifiers of the schema
