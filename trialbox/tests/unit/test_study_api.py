"""Orchestrator API for the S-28 study store and the REDCap read-back (D-109): the HTTP surface the console uses."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.study_api import plan, router

from tests.rc_kit import LINK_A, PIDS, TOKEN_A, study_service


def test_plan_goes_through_consent() -> None:
    assert plan(None, "enrolled") == ["consented", "enrolled"]
    assert plan("contacted", "consented") == ["consented"]
    assert plan("candidate", "withdrawn") == ["withdrawn"]
    assert plan("declined", "consented") is None  # listed as a conflict for the coordinator


def test_settings_connection_link_and_read_over_http(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, sim, _clock):
        app = FastAPI()
        app.include_router(router(lambda: svc))
        c = TestClient(app)
        assert c.get("/studies/GZQO/settings").status_code == 404
        body = {"study_type": "trial", "cohort_kind": "enrolled", "not_suitable_reasons": ["stage", "other"],
                "screening_no_format": "GZ-", "screening_no_next": 101, "by": "crc"}  # fmt: skip
        r = c.put("/studies/gzqo/settings", json=body)
        assert r.status_code == 200 and r.json()["screening_no_next"] == 101
        assert c.get("/studies/GZQO/settings").json()["not_suitable_reasons"] == ["stage", "other"]
        assert c.put("/studies/GZQO/settings", json={**body, "not_suitable_reasons": ["x"]}).status_code == 400

        r = c.put("/redcap/connections/main", json={"url": "inproc://rc-sim-test", "by": "admin"})
        assert r.status_code == 400  # the token is entered once
        r = c.put("/redcap/connections/main", json={"url": "inproc://rc-sim-test", "token": TOKEN_A.lower(),
                                                    "by": "admin"})  # fmt: skip
        assert r.status_code == 200 and "token" not in r.json() and r.json()["token_set"] is True
        r = c.put("/redcap/connections/main", json={"url": "inproc://rc-sim-test", "token": "short", "by": "admin"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RC-TOKEN"
        r = c.post("/redcap/connections/main/test")
        assert r.json()["version"] == "16.0.10" and r.json()["project_id"] == 101
        conns = {x["token_ref"]: x for x in c.get("/redcap/connections").json()["connections"]}
        assert conns["main"]["check_result"] == "ok"

        r = c.put("/studies/GZQO/redcap-link", json={"link": {**LINK_A, "token_ref": "main",
                                                              "consent_field": "icf_dt"}, "by": "crc"})  # fmt: skip
        assert r.status_code == 409
        assert r.json()["detail"] == {"code": "RC-LINK-FIELD", "message": r.json()["detail"]["message"],
                                      "fields": ["icf_dt"]}  # fmt: skip
        r = c.put("/studies/GZQO/redcap-link", json={"link": {**LINK_A, "token_ref": "main"}, "by": "crc"})
        assert r.status_code == 200 and r.json()["enabled"] is True
        r = c.post("/studies/GZQO/redcap-link/test", json={"screening": {"GZQO-0901": PIDS["GZQO-0901"]}})
        assert r.json()["records"] == 2 and r.json()["sample"][0]["status"] == "enrolled"
        r = c.post("/studies/GZQO/redcap-read", json={"screening": {"GZQO-0901": PIDS["GZQO-0901"]}, "by": "crc"})
        assert r.status_code == 200 and r.json()["changes"][0]["to"] == "enrolled"
        assert c.get("/studies/GZQO/redcap-records").json()[0]["subject_no"] == "S-0001"
        assert c.get("/studies/GZQO/redcap-link").json()["reads"][0]["ok"] is True
        assert c.post("/studies/NOPE/redcap-read", json={}).status_code == 404
        assert c.get("/studies/bad id/settings").status_code == 400
        del sim
