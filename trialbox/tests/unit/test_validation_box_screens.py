"""VALIDATION-ROUTES (D-823), review FIX FIRST 1: the screen's D3 calls go through the gateway of a VALIDATION box.

The routing table alone was not enough: the gateway checks the study step before routing, and a D3 call without a
confirmed step passes only under ``phi_on_box`` (PRODUCTION only before this card). The installed box of
``test_gateway_box_phi`` (its compose settings, pins, tokens, the stub as llm-service and llm-verifier), run as a
VALIDATION box: the judge and the verifier answer D3 calls, on the box, on the patient route; front-desk text at D3
stays refused."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app, from_env
from llm_stub.app import app as stub
from orchestrator.app import verifier_client
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.llm import LlmClient

from tests.unit import test_gateway_box_phi as boxphi


@pytest.fixture
def validation_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import os

    dotenv = boxphi._dotenv()
    host = {
        "TB_AUDIT_DIR": str(tmp_path / "audit"),
        "TB_REGISTRY_OVERRIDE": str(boxphi._pin(tmp_path)),
        "TB_REGISTRY_PATH": str(tmp_path / "registry.release.yaml"),
        "TB_SETTINGS": str(boxphi.ROOT / "deploy" / "settings.example.yaml"),
        "TB_DB_URL": os.environ["TB_DB_URL"],
        "TB_AUDIT_WRITER": "file",
        "TB_SERVICE_TOKEN": "",
        "TB_SERVICE_TOKENS": str(boxphi._token_registry(tmp_path, ("gateway", "orchestrator"))),
        "TB_ENV": "VALIDATION",
    }

    def enter(service: str) -> dict[str, str]:
        env = {**boxphi._service_env(service, dotenv), **host}
        env["TB_SERVICE_TOKEN_FILE"] = str(tmp_path / "tokens" / f"{service}.token")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        get_config.cache_clear()
        return env

    assert enter("gateway")["TB_ENV"] == "VALIDATION"
    gw = from_env()
    gw.http = TestClient(stub)
    app = TestClient(create_app(gw))
    enter("orchestrator")
    audit = AuditLog(tmp_path / "orch-audit")
    llm = LlmClient.from_config(audit)
    verifier = verifier_client(audit)
    assert llm.gateway is not None and verifier is not None and verifier.gateway is not None
    llm.gateway.http = app
    verifier.gateway.http = app
    yield llm, verifier, tmp_path
    get_config.cache_clear()


def test_a_validation_box_judges_and_verifies_d3_on_the_box(validation_box: Any) -> None:
    llm, verifier, tmp_path = validation_box
    assert llm.chat_json("judge", boxphi.JUDGE_VARS).data["verdict"] in ("pass", "fail", "unknown")
    assert verifier.chat_json("judge", boxphi.JUDGE_VARS).data["verdict"] in ("pass", "fail", "unknown")
    recs = [r for r in boxphi._calls(tmp_path) if r["event"] == "llm.gateway.call"]
    assert [(r["detail"]["role"], r["model"]) for r in recs] == [("judge", "j-workhorse"), ("judge", "v-verifier")]
    for r in recs:
        d = r["detail"]
        assert (d["class"], d["step_basis"], d["zone"], d["route_id"]) == ("D3", "box_policy", "perimeter", "patient")
