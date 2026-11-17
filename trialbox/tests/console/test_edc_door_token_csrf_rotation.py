# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""E-EDCB-3 (D-1045): the EDC door's token exchange, the tool route's CSRF check, and the event secret's rotation.

The owner's brief (D-1060): ``redirect_uri`` and ``client_id`` are bound to a code when it is issued and must match at
``/token``; a wrong client secret is 401; with OIDC off all four OIDC routes answer 404; ``POST /api/edc/tools`` needs
the session's CSRF token; ``TB_EDC_EVENT_SECRET`` may hold ``current,previous`` so the secret can be changed without a
gap.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from edc_backend import linkmap
from fastapi.testclient import TestClient

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name

CB = "https://edc.example/callback"
OTHER_CB = "https://edc.example/other"
SECRET = "oidc-client-secret-for-tests"


@pytest.fixture
def oidc_on(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, db_url: str) -> dict[str, Any]:
    monkeypatch.setenv("TB_EDC_OIDC", "1")
    monkeypatch.setenv("TB_EDC_OIDC_ISSUER", "https://box.example")
    monkeypatch.setenv("TB_EDC_OIDC_CLIENT_ID", "edc")
    monkeypatch.setenv("TB_EDC_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("TB_EDC_OIDC_REDIRECT", f"{CB},{OTHER_CB}")
    return box


def _code(c: TestClient, redirect: str = CB) -> str:
    r = c.get("/api/edc/oidc/authorize", params={"client_id": "edc", "redirect_uri": redirect, "state": "s1"},
              follow_redirects=False)  # fmt: skip
    assert r.status_code == 302, r.text
    return str(parse_qs(urlparse(r.headers["location"]).query)["code"][0])


def _token(c: TestClient, code: str, **over: str) -> Any:
    form = {"grant_type": "authorization_code", "code": code, "client_id": "edc", "client_secret": SECRET,
            "redirect_uri": CB, **over}  # fmt: skip
    return TestClient(c.app).post("/api/edc/oidc/token", data=form)


def test_the_code_redeems_with_its_own_client_and_redirect(oidc_on: dict[str, Any]) -> None:
    c, _ = login(oidc_on["app"])
    r = _token(c, _code(c))
    assert r.status_code == 200 and r.json()["token_type"] == "Bearer"


def test_a_redirect_that_is_not_the_codes_is_refused_and_the_code_is_spent(oidc_on: dict[str, Any]) -> None:
    c, _ = login(oidc_on["app"])
    code = _code(c)
    r = _token(c, code, redirect_uri=OTHER_CB)  # an allowed redirect, but not the one this code was issued for
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert _token(c, code).status_code == 400  # a code is spent by any attempt at it


def test_the_redirect_is_required_at_token(oidc_on: dict[str, Any]) -> None:
    c, _ = login(oidc_on["app"])
    assert _token(c, _code(c), redirect_uri="").status_code == 400


def test_a_wrong_client_secret_or_client_is_401(oidc_on: dict[str, Any]) -> None:
    c, _ = login(oidc_on["app"])
    code = _code(c)
    assert _token(c, code, client_secret="not-it").status_code == 401
    assert _token(c, code, client_id="someone-else").status_code == 401
    assert _token(c, code).status_code == 200  # neither spent the code: the client was refused before it


def test_oidc_off_is_404_on_all_four_routes(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_EDC_OIDC", raising=False)
    c, _ = login(box["app"])
    assert c.get("/api/edc/oidc/.well-known/openid-configuration").status_code == 404
    assert c.get("/api/edc/oidc/authorize", params={"client_id": "edc", "redirect_uri": CB}).status_code == 404
    assert c.post("/api/edc/oidc/token", data={"code": "x"}).status_code == 404
    assert c.get("/api/edc/oidc/userinfo", headers={"authorization": "Bearer x"}).status_code == 404


def test_the_tool_route_needs_the_csrf_token(box: dict[str, Any], db_url: str) -> None:
    c, csrf = login(box["app"])
    body = {"tool": "open_query", "project_id": "proj-1", "record_id": "1001"}
    assert c.post("/api/edc/tools", json=body).status_code == 400
    assert c.post("/api/edc/tools", json=body, headers={"x-csrf": "not-the-token"}).status_code == 400
    r = c.post("/api/edc/tools", json=body, headers={"x-csrf": csrf})
    assert r.status_code == 200 and r.json()["needs_confirm"] is True


def test_the_confirmation_needs_the_csrf_token_and_its_holder(box: dict[str, Any], db_url: str) -> None:
    c, csrf = login(box["app"])
    pid = c.post("/api/edc/tools", json={"tool": "open_query", "project_id": "proj-1"},
                 headers={"x-csrf": csrf}).json()["proposal_id"]  # fmt: skip
    assert c.post(f"/api/edc/tools/{pid}/confirm").status_code == 400  # no CSRF token
    box["users"].create("admin2", "admin", "second-admin-password-1", "admin2@hospa.test")
    other, other_csrf = login(box["app"], "admin2", "second-admin-password-1")
    assert other.post(f"/api/edc/tools/{pid}/confirm", headers={"x-csrf": other_csrf}).status_code == 404


def _signed(secret: str, doc: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(doc).encode()
    return raw, "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def test_the_event_secret_rotates_with_current_and_previous(
    box: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_url: str,
) -> None:
    monkeypatch.setenv("TB_EDC_EVENT_DIR", str(tmp_path / "edc"))
    linkmap.save(str(tmp_path / "edc"), {"studies": {}})
    monkeypatch.setenv("TB_EDC_EVENT_SECRET", "new-secret-2026,old-secret-2025")
    c = TestClient(box["app"])
    for n, (secret, want) in enumerate([("new-secret-2026", 200), ("old-secret-2025", 200), ("another", 401)]):
        doc = {"spec": "trialbox.edc.event.v1", "id": f"evt-{n}", "type": "query.opened", "project_id": "p"}
        raw, sig = _signed(secret, doc)
        assert c.post("/api/edc/events/v1", content=raw, headers={"x-trialbox-signature": sig}).status_code == want
    monkeypatch.setenv("TB_EDC_EVENT_SECRET", "new-secret-2026")  # the rotation ends: the old one is refused
    raw, sig = _signed("old-secret-2025", {"spec": "trialbox.edc.event.v1", "id": "evt-9", "type": "query.opened"})
    assert c.post("/api/edc/events/v1", content=raw, headers={"x-trialbox-signature": sig}).status_code == 401
