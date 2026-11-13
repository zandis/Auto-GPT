"""REDCap's own error text is not passed on. An import error quotes the record, the field and the VALUE it refused
(`"1","tb_weight","...","The value you provided could not be validated ..."`); the client put that text into its
message, which reaches the set-up page and the stored read log. The message now carries the status and the kind of
error, in the box's own words. Found by lane C2's error-answer card (D-555)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from rc_bridge.client import RcError, RedcapClient
from rc_sim.app import create_app

from tests.rc_kit import TOKEN_A, TOKEN_B

TYPED = "seventy-two point five"  # what a person typed into a number field: a record's value


def _client(sim: Any, token: str) -> RedcapClient:
    rc = RedcapClient("https://rc.example/", token, http=TestClient(sim, base_url="http://rc"))
    rc.url = "/api/"
    return rc


def _validated(sim: Any, token: str, field: str) -> None:
    for m in sim.state.sim.projects[token]["metadata"]:
        if m["field_name"] == field:
            m["text_validation_type_or_show_slider_number"] = "number_1dp"


def test_the_simulator_quotes_the_value_as_redcap_does() -> None:
    sim = create_app()
    _validated(sim, TOKEN_A, "tb_status_date")
    r = TestClient(sim, base_url="http://rc").post("/api/", data={
        "token": TOKEN_A, "content": "record", "format": "json", "type": "flat",
        "data": f'[{{"record_id": "1", "tb_status_date": "{TYPED}"}}]'})  # fmt: skip
    assert r.status_code == 400 and TYPED in r.json()["error"] and '"tb_status_date"' in r.json()["error"]


def test_a_refused_value_is_not_in_the_clients_message() -> None:
    sim = create_app()
    _validated(sim, TOKEN_A, "tb_status_date")
    with pytest.raises(RcError) as e:
        _client(sim, TOKEN_A).import_records([{"record_id": "1", "tb_status_date": TYPED}])
    assert e.value.code == "RC-UPSTREAM"
    assert TYPED not in e.value.message and TYPED not in str(e.value)
    assert "400" in e.value.message and "validation" in e.value.message  # the status and the kind of error


@pytest.mark.parametrize(("token", "row", "says"), [
    (TOKEN_A, {"record_id": "1", "nope": "x"}, "nope"),                                    # a field name is not a value
    (TOKEN_B, {"rec_id": "1", "tb_status": "1"}, "event"),                                 # longitudinal, no event
    (TOKEN_B, {"rec_id": "1", "redcap_event_name": "m12_arm_1", "tb_status": "1"}, "event"),
])  # fmt: skip
def test_the_kind_of_error_is_said_in_the_boxs_own_words(token: str, row: dict[str, str], says: str) -> None:
    with pytest.raises(RcError) as e:
        _client(create_app(), token).import_records([row])
    assert says in e.value.message and "REDCap returned 400" in e.value.message


def test_text_the_box_does_not_know_is_not_passed_on() -> None:
    from rc_bridge.client import error_kind

    odd = 'Something new: "1","dob","1960-05-01","unexpected"'
    assert error_kind(odd) == "REDCap's own text is not shown: it can quote a record's value"
    assert "1960" not in error_kind(odd)
    # a field list is given back as field names only, whatever else the text holds
    listed = "The following fields were not found in the project as real data fields: nope, also_nope, 1960-05-01 x"
    assert error_kind(listed) == "fields that are not in the project: nope, also_nope"


def test_a_classic_project_is_still_told_apart() -> None:
    """The lifecycle's schedule from REDCap answers 409, not 502, for a classic project: it reads this word."""
    from rc_bridge.client import error_kind

    assert "classic" in error_kind("You cannot export arms or events for classic projects")
