"""Contract version 1 with the internal EDC (D-1042): the door's events, held writes and OIDC codes, against the trial
database (E-EDCB-2, D-1044).

E-PURE: these three take ``db_url``, so they are not in ``test_edc_contract.py``, which is a pure module (no PostgreSQL,
``make test-pure``). They moved here unchanged.
"""

from __future__ import annotations

import json

import httpx
import pytest
from edc_backend import events, oidc, tools

from tests.rc_kit import TOKEN_A, TOKEN_B
from tests.unit.test_edc_contract import BODY, _sign


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
