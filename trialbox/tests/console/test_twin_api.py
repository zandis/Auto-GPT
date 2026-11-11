"""T-204 (D-440): the patient twin's read route ``GET /api/v1/studies/{rs}/patients/{pid}/twin``.

A viewer gets 403; a reader of the study's patients gets 200 and exactly one audit event naming role, layers and
basis; outside one's own rights only a break-glass grant opens one patient (D-430); an opted-out patient and a patient
the study does not have are 404; the setpoint and gap layers only for the study's PI. Synthetic pseudonyms only."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from patient_profile import twin as tw
from tb_common.optout import OptOutRegister
from tb_contracts.schema import schema_errors

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - fixture by name
from tests.console.test_d280_breakglass import A, B, _events, _open
from tests.console.test_role_pages import PW, _user

SNAP = "2026-10-04"


def _put_twin(pid: str) -> None:
    row = {"pid": pid, "birth_date": date(1970, 1, 1), "sex": "female", "deceased_date": None, "deceased": None,
           "src_table": "patient", "src_row_hash": "ph1", "mapping_version": "map@3"}  # fmt: skip
    cond = {"pid": pid, "cid": f"{pid[:4]}-c1", "onset": date(2025, 3, 1), "recorded": None, "code": "M05.79",
            "system": "http://hl7.org/fhir/sid/icd-10", "status": "active", "src_table": "diagnosis",
            "src_row_hash": "dh1", "mapping_version": "map@3"}  # fmt: skip
    st = tw.ProfileStore()
    st.put(tw.assemble(pid, SNAP, {"patient": [row], "condition": [cond]}), "2026-10-05T00:00:00+00:00")
    st.close()


def _api(b: dict[str, Any], name: str, role: str) -> TestClient:
    _user(b, name, role)
    token, _ = b["users"].new_session(b["users"].get(name), via="api")
    return TestClient(b["app"], headers={"Authorization": f"Bearer {token}"})


def _url(pid: str = A, rs: str = "GZQO") -> str:
    return f"/api/v1/studies/{rs}/patients/{pid}/twin"


def test_a_viewer_is_refused_and_a_reader_gets_the_twin_with_one_audit_event(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(990))
    _put_twin(A)
    viewer = _api(box, "vw1", "viewer")
    assert viewer.get(_url()).status_code == 403
    crc = _api(box, "crc1", "coordinator")
    before = len(_events(box, "console.twin_view"))
    r = crc.get(_url())
    assert r.status_code == 200, r.text[-300:]
    body = r.json()
    assert body["as_of"]["version"] == 1 and body["as_of"]["snapshot"] == SNAP
    doc = {k: v for k, v in body.items() if k != "as_of"}
    assert schema_errors(tw.SCHEMA_NAME, doc) == []
    assert "setpoint" not in doc["layers"] and "gap" not in doc["layers"]  # not the study's PI: absent
    assert doc["layers"]["similarity"] is None and doc["layers"]["phenotype"]["items"][0]["code"] == "M05.79"
    ev = _events(box, "console.twin_view")[before:]
    assert len(ev) == 1
    assert ev[0]["ruleset"] == "GZQO" and ev[0]["detail"]["role"] == "coordinator"
    assert ev[0]["detail"]["basis"] == SNAP and ev[0]["detail"]["version"] == 1
    assert ev[0]["detail"]["layers"] == ["phenotype", "record", "timeline"]
    # no token: sign in first
    assert TestClient(box["app"]).get(_url()).status_code == 401


def test_the_study_pi_sees_the_research_layers_and_an_unlogged_investigator_needs_a_grant(
    box: dict[str, Any],  # noqa: F811
) -> None:
    _done_screen(box["backend"], _ulid(991))
    _put_twin(A)
    _put_twin(B)
    lpi = _api(box, "drsato", "investigator")
    name_pi(box, "drsato")
    r = lpi.get(_url())
    assert r.status_code == 200 and {"setpoint", "gap"} <= set(r.json()["layers"])
    assert r.json()["layers"]["setpoint"] is None  # empty until T-313
    # an investigator the log does not reach: refused, then one patient under its own grant
    drlee = _api(box, "drlee", "investigator")
    assert drlee.get(_url()).status_code == 403
    c, _ = login(box["app"], "drlee", PW)  # the grant is opened on the page by the same account
    assert _open(c, kind="patient", ruleset="GZQO", pid=A).status_code == 303
    r = drlee.get(_url())
    assert r.status_code == 200 and "setpoint" not in r.json()["layers"]
    ev = _events(box, "console.twin_view")[-1]
    assert ev["detail"]["role"] == "breakglass" and "grant" in ev["detail"]
    assert any(u["detail"].get("what") == "twin" for u in _events(box, "console.breakglass_use"))
    assert drlee.get(_url(B)).status_code == 403  # that patient only


def test_the_administrator_reads_no_twin_without_a_grant(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(992))
    _put_twin(A)
    token, _ = box["users"].new_session(box["users"].get("admin"), via="api")
    admin = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    assert admin.get(_url()).status_code == 403


def test_opted_out_unknown_and_outside_the_study_are_not_found(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(993))
    _put_twin(A)
    _put_twin("d" * 32)
    crc = _api(box, "crc2", "coordinator")
    assert crc.get(_url("d" * 32)).status_code == 404  # a twin exists, but not a patient of this study
    assert crc.get(_url(B)).status_code == 404  # listed, no twin built yet
    assert crc.get(_url(rs="NOPE")).status_code == 404
    reg = OptOutRegister()
    reg.add(A, "paper", "", "console:office1", "2026-10-05T00:00:00+00:00")
    reg.close()
    assert crc.get(_url()).status_code == 404  # opted out: refused before the next build erases the row
