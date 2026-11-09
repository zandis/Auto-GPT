"""D-177: the on-box model servers take calls only with ``TB_LLM_API_KEY``, and only the gateway holds it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
VLLM_FILES = ["docker-compose.yml", "docker-compose.gb10.yml", "docker-compose.rtx5090.yml",
              "docker-compose.rtxpro6000.yml"]  # fmt: skip


def _load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))
    return doc


def test_every_vllm_server_gets_the_key() -> None:
    seen = 0
    for name in VLLM_FILES:
        for svc, body in (_load(name).get("services") or {}).items():
            if svc in ("llm-service", "llm-verifier") and "command" in body:
                env = body.get("environment") or {}
                assert env.get("VLLM_API_KEY") == "${TB_LLM_API_KEY:-}", f"{name} {svc}"
                seen += 1
    assert seen == 7  # base llm-service; gb10, rtx5090, rtxpro6000: the pair each


def test_only_the_gateway_keeps_the_key() -> None:
    doc = _load("docker-compose.secrets.yml")
    for svc, body in doc["services"].items():
        env = body.get("environment") or {}
        if svc == "gateway":
            assert "TB_LLM_API_KEY" not in env
        else:
            assert env.get("TB_LLM_API_KEY") == "", svc


def test_routing_sends_the_key_to_the_on_box_endpoints() -> None:
    from gateway.policy import RoutingPolicy

    eps = RoutingPolicy.load(ROOT / "models" / "routing.yaml").endpoints
    assert eps["serving"].api_key_env == eps["verifier"].api_key_env == "TB_LLM_API_KEY"


def test_install_makes_the_key_and_checks_the_servers() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "TB_LLM_API_KEY=%s" in sh and "doctor --serving" in sh and "TB_COMPOSE_OVERRIDE" in sh
