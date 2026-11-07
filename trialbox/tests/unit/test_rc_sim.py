"""REDCap API simulator (ICD-04S, FR-RC-09/17): methods R1-R3, R7, R8, 501 for the rest, token check, rate limit."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from rc_sim.app import NO_PERMISSION, create_app

from tests.rc_kit import TOKEN_A, TOKEN_B


def post(c: TestClient, token: str, content: str, **extra: str) -> Any:
    return c.post("/api/", data={"token": token, "content": content, "format": "json", **extra})


def test_read_methods_answer_like_redcap() -> None:
    c = TestClient(create_app())
    assert post(c, TOKEN_A, "version").json() == "16.0.10"
    assert post(c, TOKEN_A, "project").json()["project_id"] == 101
    meta = post(c, TOKEN_B, "metadata").json()
    assert {m["field_name"] for m in meta} >= {"rec_id", "tb_screening_no", "icf_dt", "rand_yn", "withdrawn"}
    assert {"field_name", "form_name", "field_type", "select_choices_or_calculations", "branching_logic"} <= set(
        meta[0]
    )
    assert [d["unique_group_name"] for d in post(c, TOKEN_B, "dag").json()] == ["cgmh_linkou", "jp_head"]
    assert post(c, TOKEN_A, "dag").json() == []


def test_record_export_options() -> None:
    c = TestClient(create_app())
    rows = post(c, TOKEN_A, "record", type="flat", **{"fields[0]": "consent_date"}).json()
    assert rows == [
        {"record_id": "1", "consent_date": "2026-10-20"},
        {"record_id": "2", "consent_date": ""},
    ]
    rows = post(c, TOKEN_B, "record", type="flat", exportDataAccessGroups="true", **{"events[0]": "m12_arm_1"}).json()
    assert [(r["rec_id"], r["redcap_event_name"], r["redcap_data_access_group"]) for r in rows] == [
        ("7", "m12_arm_1", "cgmh_linkou")
    ]
    rows = post(c, TOKEN_A, "record", type="flat", **{"records[0]": "2"}).json()
    assert [r["record_id"] for r in rows] == ["2"]
    rows = post(c, TOKEN_A, "record", type="flat", dateRangeBegin="2026-10-22 00:00:00").json()
    assert [r["record_id"] for r in rows] == ["2"]


def test_wrong_token_unsupported_method_and_rate_limit() -> None:
    c = TestClient(create_app())
    r = post(c, "0" * 32, "record")
    assert r.status_code == 403 and r.json() == {"error": NO_PERMISSION}
    for content in ("file", "import", "arm", "event", "participantList"):
        r = post(c, TOKEN_A, content)
        assert r.status_code == 501 and "error" in r.json()
    limited = TestClient(create_app(rate_limit=2))
    assert [post(limited, TOKEN_A, "version").status_code for _ in range(3)] == [200, 200, 429]
    assert (
        TestClient(create_app(version="12.4.1")).post("/api/", data={"token": TOKEN_A, "content": "version"}).json()
        == "12.4.1"
    )


def test_sim_records_add_edit_and_stamp() -> None:
    sim = create_app()
    c = TestClient(sim)
    r = c.post("/sim/records", json={"project_id": 101, "records": [{"record_id": "3", "tb_screening_no": "X-1"}],
                                     "at": "2026-11-07T09:00:00"})  # fmt: skip
    assert r.json() == {"count": 1}
    r = c.post("/sim/records", json={"project_id": 101, "records": [{"record_id": "1", "enrolled": "0"}]})
    rows = {x["record_id"]: x for x in post(c, TOKEN_A, "record").json()}
    assert rows["3"]["tb_screening_no"] == "X-1" and rows["1"]["enrolled"] == "0"
    assert (
        c.post("/sim/records", json={"project_id": 101, "records": [{"record_id": "1", "nope": "1"}]}).status_code
        == 400
    )
    assert c.post("/sim/records", json={"project_id": 999, "records": []}).status_code == 404
    other = TestClient(create_app())  # each app has its own copy of the fixtures
    assert len(post(other, TOKEN_A, "record").json()) == 2
