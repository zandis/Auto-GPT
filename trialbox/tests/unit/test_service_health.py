from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

SERVICES = [
    "mail_gateway",
    "doc_parser",
    "criteria_compiler",
    "lake",
    "orchestrator",
    "adapter",
    "embed_service",
    "llm_stub",
]


@pytest.mark.parametrize("svc", SERVICES)
def test_healthz(svc: str) -> None:
    mod = importlib.import_module(f"{svc}.app")
    with TestClient(mod.app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == svc.replace("_", "-").replace("llm-stub", "llm-stub")


def test_non_idempotent_client_never_resends(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /send must not be repeated once it may have reached the gateway: a 500 (the password mail failed after
    the archive went out) or a read timeout would otherwise mail the PHI archive again with a new password."""
    import httpx
    from tb_common.http import ServiceClient, ServiceError

    monkeypatch.setattr("time.sleep", lambda s: None)
    for outcome, idempotent, calls_expected in (
        (httpx.Response(500, text="smtp failed"), False, 1),
        (httpx.ReadTimeout("slow"), False, 1),
        (httpx.ConnectError("refused"), False, 3),  # never connected: safe to try again
        (httpx.Response(500, text="smtp failed"), True, 3),
    ):
        calls: list[int] = []

        def handler(req: httpx.Request, outcome: object = outcome, calls: list[int] = calls) -> httpx.Response:
            calls.append(1)
            if isinstance(outcome, Exception):
                raise outcome
            assert isinstance(outcome, httpx.Response)
            return outcome

        c = ServiceClient("http://mail", "mail-gateway", retries=2, idempotent=idempotent)
        c.client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ServiceError):
            c.post_raw("/send", {"x": 1})
        assert len(calls) == calls_expected, (outcome, idempotent)
