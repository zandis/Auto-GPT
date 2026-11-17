"""Contract version 1 with the internal EDC (D-1042): schedule, events, map, tools, OIDC, and the study read.

The demo path is the unset backend. These tests set the variables themselves.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from edc_backend import events, linkmap, oidc, tools
from edc_backend.connection import connect
from edc_backend.study import accept_version
from fastapi.testclient import TestClient
from orchestrator.study_api import StudyService
from rc_bridge.client import RcError, RedcapClient
from rc_sim.app import create_app

from tests.rc_kit import TOKEN_A, TOKEN_B

pytestmark = pytest.mark.nodb

BODY = {
    "spec": "trialbox.edc.event.v1",
    "id": "11111111-1111-1111-1111-111111111111",
    "type": "record.saved",
    "project_id": "proj-1",
    "record_id": "1001",
    "occurred_at": "2026-11-16T00:00:00Z",
    "data": {"instrument": "adverse_event"},
}


def _sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class _Store:
    def token(self, ref: str) -> str | None:
        return TOKEN_A if ref == "main" else None


def test_unset_backend_still_rejects_an_unsupported_redcap(monkeypatch: pytest.MonkeyPatch) -> None:
    # E-EDCB-1: master's study link accepts 13 since RC13-F (D-852, the owner's D-1024); 12 is still refused
    monkeypatch.delenv("TB_EDC_BACKEND", raising=False)
    app = create_app(version="12.5.0")
    http = TestClient(app, base_url="http://rc")
    rc = RedcapClient("https://rc.example/", TOKEN_A, http=http)
    rc.url = "/api/"
    with pytest.raises(RcError) as err:
        accept_version(rc)
    assert err.value.code == "RC-VERSION"


def test_the_study_link_uses_the_backend_and_accepts_13(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_EDC_BACKEND", "internal")
    monkeypatch.setenv("TB_EDC_INTERNAL_URL", "inproc://rc-sim")
    monkeypatch.setenv("TB_EDC_INTERNAL_TOKEN", TOKEN_A)
    from rc_sim.app import app as default_app
    from rc_sim.app import register_inproc

    register_inproc(create_app(version="13.7.23"))
    svc = StudyService(store=_Store(), registry=None, audit=None, now=datetime.now)  # type: ignore[arg-type]
    rc = svc.client("main")
    try:
        assert rc.url == "/api/"
        assert svc._version(rc) == "13.7.23"
    finally:
        rc.close()
        register_inproc(default_app)


def test_an_empty_project_gains_arms_and_events() -> None:
    app = create_app()
    http = TestClient(app, base_url="http://rc")
    made = http.post(
        "/sim/projects",
        json={"title": "empty", "metadata": [{"field_name": "record_id", "form_name": "visit", "field_type": "text"}]},
    ).json()
    conn = connect(
        {"TB_EDC_BACKEND": "redcap", "TB_REDCAP_API_URL": "https://rc.example/", "TB_REDCAP_API_TOKEN": made["token"]},
        http=http,
    )
    assert conn is not None
    conn.client.url = "/api/"
    out = conn.ensure_schedule(
        arms=[{"arm_num": 1, "name": "Main"}],
        events=[{"arm_num": 1, "unique_event_name": "week1_arm_1", "event_name": "Week 1", "day_offset": 7}],
        mapping=[{"arm_num": 1, "unique_event_name": "week1_arm_1", "form": "visit"}],
    )
    assert out["arms"]["count"] == 1 and out["events"]["count"] == 1
    assert conn.events()[0]["unique_event_name"] == "week1_arm_1"
    assert conn.arms()[0]["name"] == "Main"


def test_events_are_signed_retried_and_idempotent(db_url: str) -> None:
    # E-EDCB-2 (D-1044): whether an id is new is the database's to say, not a file's
    from edc_backend import store as door

    raw = json.dumps(BODY).encode()
    secret = "event-secret"
    book = door.DoorStore(db_url)
    doc = events.check(secret, raw, _sign(secret, raw))
    assert doc["type"] == "record.saved"
    assert book.take_event(events.row_of(doc), None) is True
    assert book.take_event(events.row_of(events.check(secret, raw, _sign(secret, raw))), None) is False
    with pytest.raises(events.EventRejected) as err:
        events.check(secret, raw, "sha256=00")
    assert err.value.status == 401
    assert events.event_secret({}) == ""


def test_the_map_joins_a_project_to_a_study(tmp_path: Path) -> None:
    linkmap.save(
        str(tmp_path),
        {"studies": {"gzqo": "proj-1"}, "sites": {"linkou": "dag_linkou"}, "subjects": {"GZQO": {"S-1": "1001"}}},
    )
    assert linkmap.study_for_project(str(tmp_path), "proj-1") == "GZQO"
    saved = linkmap.load(str(tmp_path))
    assert saved["sites"]["linkou"] == "dag_linkou" and saved["subjects"]["GZQO"]["S-1"] == "1001"


def test_tools_stay_off_without_the_module_and_writes_wait(monkeypatch: pytest.MonkeyPatch, db_url: str) -> None:
    # E-EDCB-2 (D-1044): held writes are kept in the trial database
    monkeypatch.setenv("TB_EDC_TOOL_TOKEN", TOKEN_B)
    monkeypatch.setenv("TB_EDC_TOOL_URL", "https://edc.example")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/capabilities"):
            modules = [{"id": "core"}]
            if request.headers.get("x-test-on") == "1":
                modules.append({"id": "trialbox"})
            return httpx.Response(200, json={"modules": modules})
        body = json.loads(request.content)
        assert request.headers["authorization"] == f"Bearer {TOKEN_B}"
        assert TOKEN_A not in request.headers["authorization"]
        return httpx.Response(
            200, json={"allow": True, "deidentified": True, "result": body["tool"], "confirm": body["confirm"]}
        )

    transport = httpx.MockTransport(handler)
    off = tools.ToolClient("https://edc.example", TOKEN_B, httpx.Client(transport=transport))
    with pytest.raises(tools.ToolError) as err:
        off.call("explain_field", "proj-1")
    assert "off" in err.value.message and all(not r.url.path.endswith("/tools") for r in seen)
    held = tools.Proposals()
    proposal = held.hold("admin", "open_query", "proj-1", "1001")
    assert held.take("admin", proposal)["tool"] == "open_query"

    def on(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/capabilities"):
            return httpx.Response(200, json={"modules": [{"id": "trialbox"}]})
        body = json.loads(request.content)
        assert body["confirm"] is True
        assert "mrn" not in body
        return httpx.Response(200, json={"allow": True, "deidentified": True, "result": "ok"})

    client = tools.ToolClient("https://edc.example", TOKEN_B, httpx.Client(transport=httpx.MockTransport(on)))
    assert client.call("open_query", "proj-1", record_id="1001", confirm=True)["deidentified"] is True
    with pytest.raises(tools.ToolError):
        client.call("apply_draft", "proj-1", confirm=False)


def test_oidc_issues_a_code_and_stays_off_by_default(monkeypatch: pytest.MonkeyPatch, db_url: str) -> None:
    # E-EDCB-2 (D-1044): codes are kept in the trial database
    assert oidc.enabled() is False
    monkeypatch.setenv("TB_EDC_OIDC", "1")
    monkeypatch.setenv("TB_EDC_OIDC_ISSUER", "https://box.example")
    monkeypatch.setenv("TB_EDC_OIDC_CLIENT_ID", "edc")
    monkeypatch.setenv("TB_EDC_OIDC_CLIENT_SECRET", "oidc-secret")
    monkeypatch.setenv("TB_EDC_OIDC_REDIRECT", "https://edc.example/callback")
    assert oidc.discovery()["issuer"] == "https://box.example"
    target = oidc.authorize_redirect("crc", "https://edc.example/callback", "xyz")
    assert "state=xyz" in target and "code=" in target
    code = oidc.issue_code("pi")
    assert oidc.take_code(code) == "pi"
    assert oidc.take_code(code) is None
    token = oidc.sign_id_token("crc")
    assert oidc.subject_of(token) == "crc"
    assert oidc.secret_ok("oidc-secret")
    assert oidc.secret_ok("other") is False
