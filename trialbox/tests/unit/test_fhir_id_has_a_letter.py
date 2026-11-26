"""Every pseudonym used as a client-assigned FHIR id has a letter. The FHIR store refuses an id of digits only
(HAPI-0960): one such id failed the whole FHIR load, so the lake got no snapshot and every SCREEN failed. A 32-hex
pseudonym is all digits with p = 0.625^32; the two below were, under the synthetic test key. Synthetic data only."""

from __future__ import annotations

import re

from adapter.load_fhir import _bundle
from adapter.mapping.engine import resource_id
from adapter.pipeline import bulk_id, pseudonymise_bulk
from hypothesis import given
from hypothesis import strategies as st
from lake.flatten import Flattener
from tb_common.crypto import PID_HEX_LEN, pid_for_mrn, with_a_letter

KEY = b"trialbox-test-site-key-0123456789abcdef"
# HAPI's id: [A-Za-z0-9\-\.]{1,64}; the pseudonym stays lower-case hex of its own length
FHIR_ID = re.compile(r"[A-Za-z0-9\-.]{1,64}")
PSEUDONYM = re.compile(rf"[0-9a-f]{{{PID_HEX_LEN}}}")
ALL_DIGITS = {
    ("Encounter", "E10058808"): "06832626985074239411974345651068",
    ("MedicationRequest", "M10232949"): "19590097976353681727667011709040",
}


def _fits(rid: str) -> bool:
    return bool(FHIR_ID.fullmatch(rid) and PSEUDONYM.fullmatch(rid)) and not rid.isdigit()


def test_the_two_all_digit_ids_now_have_a_letter() -> None:
    for (rtype, value), was in ALL_DIGITS.items():
        rid = resource_id(KEY, rtype, value)
        assert _fits(rid), (rtype, rid)
        assert rid != was and rid[1:] == was[1:]  # only the first digit moved
        assert resource_id(KEY, rtype, value) == rid  # still stable


def test_the_two_ids_round_trip_through_the_bulk_mapping_the_store_load_and_the_lake() -> None:
    export = [
        {"resourceType": "Patient", "id": "10000001"},
        {"resourceType": "Encounter", "id": "E10058808", "subject": {"reference": "Patient/10000001"}},
        {
            "resourceType": "MedicationRequest",
            "id": "M10232949",
            "subject": {"reference": "Patient/10000001"},
            "encounter": {"reference": "Encounter/E10058808"},
        },
        {
            "resourceType": "Condition",
            "id": "C1",
            "subject": {"reference": "Patient/10000001"},
            "encounter": {"reference": "Encounter/E10058808"},
        },
    ]
    out = {r["resourceType"]: r for r in pseudonymise_bulk(iter(export), KEY)}
    eid, mid = resource_id(KEY, "Encounter", "E10058808"), resource_id(KEY, "MedicationRequest", "M10232949")
    assert out["Encounter"]["id"] == eid == bulk_id(KEY, "Encounter", "E10058808")
    assert out["MedicationRequest"]["id"] == mid == bulk_id(KEY, "MedicationRequest", "M10232949")
    assert out["MedicationRequest"]["encounter"]["reference"] == out["Condition"]["encounter"]["reference"]
    assert out["Condition"]["encounter"]["reference"] == f"Encounter/{eid}"
    # the store's PUT url is the id the store must take
    for entry in _bundle(list(out.values()))["entry"]:
        _, rid = entry["request"]["url"].split("/")
        assert FHIR_ID.fullmatch(rid) and not rid.isdigit(), entry["request"]["url"]
    # the lake reads the reference back to the encounter's own id
    flat = Flattener(tz="Asia/Tokyo")
    assert flat.encounter(out["Encounter"])["eid"] == eid == flat.condition(out["Condition"])["eid"]
    assert flat.condition(out["Condition"])["pid"] == pid_for_mrn(KEY, "10000001") == out["Patient"]["id"]


@given(st.binary(min_size=16, max_size=64), st.text(min_size=1, max_size=40), st.text(max_size=40))
def test_every_pseudonym_is_an_id_the_fhir_store_takes(key: bytes, rtype: str, value: str) -> None:
    assert _fits(resource_id(key, rtype, value))
    assert _fits(pid_for_mrn(key, value))


@given(st.from_regex(r"[0-9]{32}", fullmatch=True))
def test_an_all_digit_pseudonym_gets_a_letter_and_keeps_its_shape(digits: str) -> None:
    assert _fits(with_a_letter(digits))


@given(st.text(alphabet="0123456789abcdef", min_size=32, max_size=32).filter(lambda s: not s.isdigit()))
def test_a_pseudonym_with_a_letter_is_unchanged(hex_id: str) -> None:
    assert with_a_letter(hex_id) == hex_id
