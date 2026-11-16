"""CGRD-B5a (D-843): the simulator refuses the values a real REDCap refuses, and the whole file with one.

The simulator took values a real REDCap refuses (EDC-001): a choice that is not one of the field's codes, a word in a
number field, a date in neither of the two forms REDCap's import reads (Y-M-D, M/D/Y), a ROC date. The send's own
checks were tested against a laxer stand-in than the real thing. It now refuses them as REDCap does, the whole
import with one bad value (nothing of the file is written); a row on the other arm's event is still taken, as REDCap
takes it, so the bridge's own arm check stays the thing under test. Synthetic data only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import RcError
from rc_sim.app import create_app

from tests import edc_kit as k

META = [
    {"field_name": "record_id", "form_name": "f", "field_type": "text"},
    {"field_name": "sex", "form_name": "f", "field_type": "radio", "select_choices_or_calculations": "1, Male | 2, Female"},
    {"field_name": "gout", "form_name": "f", "field_type": "yesno"},
    {"field_name": "ok", "form_name": "f", "field_type": "truefalse"},
    {"field_name": "site", "form_name": "f", "field_type": "dropdown", "select_choices_or_calculations": "A, One | B, Two"},
    {"field_name": "n", "form_name": "f", "field_type": "text", "text_validation_type_or_show_slider_number": "integer"},
    {"field_name": "w", "form_name": "f", "field_type": "text", "text_validation_type_or_show_slider_number": "number"},
    {"field_name": "d", "form_name": "f", "field_type": "text", "text_validation_type_or_show_slider_number": "date_dmy"},
    {"field_name": "t", "form_name": "f", "field_type": "text",
     "text_validation_type_or_show_slider_number": "datetime_ymd"},
    {"field_name": "note", "form_name": "f", "field_type": "text"},
]  # fmt: skip


def _client() -> object:
    sim = create_app()
    token = TestClient(sim).post("/sim/projects", json={"metadata": META}).json()["token"]
    return k.client_for(sim, token)


@pytest.mark.parametrize(("field", "value"), [
    ("sex", "9"), ("sex", "Male"), ("gout", "2"), ("gout", "yes"), ("ok", "true"), ("site", "C"),
    ("n", "1.5"), ("n", "two"), ("w", "heavy"), ("w", "72,5"),
    ("d", "115/11/01"), ("d", "05-11-2026"), ("d", "2026-02-30"), ("d", "13/01/2026"),
    ("t", "2026-11-05"), ("t", "2026-11-05 25:00"),
])  # fmt: skip
def test_a_value_redcap_refuses_is_refused_and_nothing_of_the_file_is_written(field: str, value: str) -> None:
    c = _client()
    with pytest.raises(RcError) as e:
        c.import_records([{"record_id": "1", "note": "good row"}, {"record_id": "2", field: value}])  # type: ignore[attr-defined]
    assert e.value.refused and "does not fit its field's validation" in e.value.message
    assert c.records() == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(("field", "value"), [
    ("sex", "2"), ("gout", "0"), ("ok", "1"), ("site", "B"), ("n", "-3"), ("w", "72.5"), ("w", "72"),
    ("d", "2026-11-05"), ("d", "11/05/2026"), ("d", "2026-1-5"), ("t", "2026-11-05 08:30"), ("t", "11/05/2026 08:30"),
    ("note", "anything at all"),
])  # fmt: skip
def test_a_value_redcap_takes_is_taken(field: str, value: str) -> None:
    c = _client()
    assert c.import_records([{"record_id": "1", field: value}]) == ["1"]  # type: ignore[attr-defined]
