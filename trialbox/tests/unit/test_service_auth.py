"""D-114: the orchestrator's changing calls need the box's service token; the audit actor comes from X-TB-Actor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.http import ServiceClient

TOKEN = "test-service-token-0123456789"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from orchestrator import app as oapp

    return TestClient(oapp.app)


def test_changing_calls_need_the_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    body = {"pid": "PID-00000001"}
    r = client.post("/jobs/J1/reveal", json=body)
    assert r.status_code == 401 and "X-TB-Service-Token" in r.json()["detail"]
    r = client.post("/jobs/J1/reveal", json=body, headers={sa.TOKEN_HEADER: "wrong"})
    assert r.status_code == 403
    for path in ("/jobs", "/notices", "/jobs/J1/cancel", "/registry/X", "/studies"):
        assert client.post(path, json={}).status_code == 401, path
    # with the token the call reaches the route (an unknown route answers 404, not 401/403)
    assert client.post("/no-such-route", json={}, headers={sa.TOKEN_HEADER: TOKEN}).status_code == 404


def test_no_token_fails_closed_outside_dev_and_test(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert client.post("/no-such-route", json={}).status_code == 503
    monkeypatch.setenv("TB_SERVICE_TOKEN", "change-me-service-token")  # the .env.example placeholder is no token
    assert client.post("/no-such-route", json={}).status_code == 503
    monkeypatch.setenv("TB_ENV", "TEST")
    assert client.post("/no-such-route", json={}).status_code == 404
    monkeypatch.delenv("TB_ENV")
    assert client.post("/no-such-route", json={}).status_code == 503  # unset TB_ENV is PRODUCTION


def test_reads_stay_open(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert client.get("/healthz").status_code != 401


def test_token_from_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    f = tmp_path / "service_token"
    f.write_text(TOKEN + "\n")
    monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(f))
    assert sa.service_token() == TOKEN
    assert sa.check("POST", TOKEN, "PRODUCTION") is None


def test_reveal_audits_the_header_actor_not_the_body(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    events: list[dict[str, Any]] = []
    job = SimpleNamespace(type="SCREEN", state="done", ruleset="RS")
    fake = SimpleNamespace(
        db=SimpleNamespace(get=lambda _id: job),
        cfg=SimpleNamespace(env=SimpleNamespace(secrets_dir="/nonexistent")),
        audit=SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw})),
    )
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids: {p: "MRN-1" for p in pids})
    ok = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("山田 花子")}
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001", "by": "someone-else"}, headers=ok)
    assert r.status_code == 200 and r.json()["mrn"] == "MRN-1"
    assert events[-1]["actor"] == "山田 花子"  # from the authenticated header, the body's "by" is ignored
    # a token holder that names no user is refused, and nothing is revealed
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001", "by": "x"}, headers={sa.TOKEN_HEADER: TOKEN})
    assert r.status_code == 400 and len(events) == 1


def test_service_client_sends_the_token_to_every_trialbox_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    seen: dict[str, httpx.Headers] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.host] = req.headers
        return httpx.Response(200, json={})

    for host, service in (("orchestrator", "orchestrator"), ("mail", "mail-gateway")):
        c = ServiceClient(f"http://{host}", service, retries=0)
        c.client = httpx.Client(transport=httpx.MockTransport(handler))
        c.post_raw("/x", {}, sa.actor_header("佐藤"))
    assert seen["orchestrator"][sa.TOKEN_HEADER] == TOKEN
    assert sa.actor_of(seen["orchestrator"][sa.ACTOR_HEADER], None) == "佐藤"
    assert seen["mail"][sa.TOKEN_HEADER] == TOKEN  # D-127 (F-11): every service checks it now
