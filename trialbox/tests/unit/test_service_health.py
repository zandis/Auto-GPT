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
