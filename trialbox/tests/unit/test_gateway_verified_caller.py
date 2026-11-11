"""T-212b (D-437; CR-040, LLM-039): the gateway routes on the verified caller, not on the self-declared header.

``X-TB-Caller`` is a claim; the service the request's ``X-TB-Service-Token`` identifies (``service_auth``, D-138) may
claim only its names of ``service_callers`` in ``models/routing.yaml``, so the role rights of a caller entry are bound
to the verified service. The one-GPU swap is for the ``serving_control`` services only. The model key is a secret
file, read by the gateway and model-guard, and ``trialbox secrets rotate --service model`` replaces it. All tokens and
keys here are synthetic.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.policy import RoutingPolicy, endpoint_key
from model_guard import build as guard_build
from tb_common import service_auth
from tb_common.policy.classes import Environment

from tests.unit.test_gateway import H, _gw, _judge_body, _records
from tools.trialbox import svc_secrets as sx

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("orchestrator", "criteria-compiler", "doc-parser", "console", "mail-gateway", "operator")


@pytest.fixture
def tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A per-service token registry (as ``trialbox secrets init`` writes it) on a PRODUCTION process."""
    toks = {name: secrets.token_hex(16) for name in SERVICES}
    reg = tmp_path / "tokens.json"
    doc = {"schema": "tb-service-tokens/1", "services": {n: service_auth.token_hash(t) for n, t in toks.items()}}
    reg.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("TB_SERVICE_TOKENS", str(reg))
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    return toks


def _post(http: TestClient, token: str, **over: str) -> httpx.Response:
    r: httpx.Response = http.post(
        "/v1/chat/completions", json=_judge_body(), headers={**H(**over), "X-TB-Service-Token": token}
    )
    return r


def _refusals(tmp_path: Path) -> list[dict[str, Any]]:
    return [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.refuse"]


# ------------------------------------------------------------------------------------------------ acceptance
def test_a_doc_parser_token_cannot_use_role_judge(tmp_path: Path, tokens: dict[str, str]) -> None:
    http = TestClient(create_app(_gw(tmp_path)))
    dp = tokens["doc-parser"]
    # by its own name: the role is not its right
    r = _post(http, dp, Caller="doc-parser", Purpose="documents")
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_not_allowed"
    # by claiming a caller whose rights include the judge (orchestrator, eval) or every role (testbench)
    for claimed, purpose in (("orchestrator", "screening"), ("testbench", "evaluation"), ("eval", "evaluation")):
        r = _post(http, dp, Caller=claimed, Purpose=purpose)
        assert r.status_code == 403 and r.json()["error"]["code"] == "caller_unverified", claimed
    refused = _refusals(tmp_path)
    assert [d["reason"] for d in refused] == ["role_not_allowed"] + ["caller_unverified"] * 3
    assert all(d["service"] == "doc-parser" for d in refused)  # audited with the verified service
    assert not [r for r in _records(tmp_path) if r["event"] == "llm.gateway.call"]


def test_each_service_may_claim_only_its_own_names(tmp_path: Path, tokens: dict[str, str]) -> None:
    http = TestClient(create_app(_gw(tmp_path)))
    ok = _post(http, tokens["orchestrator"])
    assert ok.status_code == 200, ok.json()
    (call,) = [r for r in _records(tmp_path) if r["event"] == "llm.gateway.call"]
    assert call["actor"] == "orchestrator" and call["detail"]["service"] == "orchestrator"
    # the console is the front desk (converse-native) and nothing else
    r = _post(http, tokens["console"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "caller_unverified"
    # the operator (the administrator's host token) may run the test bench
    r = _post(http, tokens["operator"], Caller="testbench", Purpose="development")
    assert r.status_code == 200, r.json()
    # mail-gateway has no row: whatever it claims is refused (service_auth already refuses it at the door)
    r = _post(http, tokens["mail-gateway"])
    assert r.status_code == 403


def test_the_shared_token_names_no_service_and_is_believed_only_in_dev_and_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = secrets.token_hex(16)
    monkeypatch.delenv("TB_SERVICE_TOKENS", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_SERVICE_TOKEN", shared)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    for env, status in ((Environment.PRODUCTION, 403), (Environment.VALIDATION, 403), (Environment.TEST, 200)):
        gw = _gw(tmp_path / env.value, env=env, confirm=lambda caller, study, step: True)
        r = _post(TestClient(create_app(gw)), shared)
        assert r.status_code == status, (env, r.json())
        if status == 403:
            assert r.json()["error"]["code"] == "caller_unverified"
            assert _refusals(tmp_path / env.value)[0]["service"] == "legacy"


def test_a_call_without_any_identity_outside_dev_and_test_is_refused(tmp_path: Path) -> None:
    """``service`` None comes only from an open token layer (DEV/TEST); a PRODUCTION process never believes it."""
    import os

    gw = _gw(tmp_path, env=Environment.PRODUCTION)
    old = os.environ.get("TB_ENV")
    os.environ["TB_ENV"] = "PRODUCTION"
    try:
        res = gw.chat(H(), _judge_body(), service=None)
    finally:
        if old is None:
            os.environ.pop("TB_ENV")
        else:
            os.environ["TB_ENV"] = old
    assert res.status == 403 and res.body["error"]["code"] == "caller_unverified"


# ------------------------------------------------------------------------------------------------ the GPU swap
class _Swap:
    def __init__(self) -> None:
        self.urls: dict[str, str] = {}
        self.calls: list[str] = []

    def activate(self, endpoint: str, hold: bool = False) -> dict[str, Any]:
        self.calls.append(f"activate:{endpoint}")
        return {"swap": "sleep", "active": endpoint}

    def release(self) -> dict[str, Any]:
        self.calls.append("release")
        return {"swap": "sleep", "active": None}

    def status(self) -> dict[str, Any]:
        return {"swap": "sleep"}


def test_only_the_owners_swap_the_gpu(tmp_path: Path, tokens: dict[str, str]) -> None:
    gw = _gw(tmp_path)
    swap = _Swap()
    gw.swap = swap  # type: ignore[assignment]
    http = TestClient(create_app(gw))

    def act(service: str, caller: str, path: str = "activate") -> httpx.Response:
        hdr = {"X-TB-Caller": caller, "X-TB-Service-Token": tokens[service]}
        r: httpx.Response = http.post(f"/v1/serving/{path}", json={"endpoint": "verifier"}, headers=hdr)
        return r

    for service, caller, code in (
        ("doc-parser", "orchestrator", "caller_unverified"),  # a claim it may not make
        ("doc-parser", "doc-parser", "caller_unknown"),  # its own name has no judge right
        ("console", "converse-native", "caller_unknown"),
        ("operator", "eval", ""),  # the operator owns the swap
        ("orchestrator", "orchestrator", ""),
    ):
        r = act(service, caller)
        assert r.status_code == (200 if not code else 403), (service, caller, r.json())
        if code:
            assert r.json()["error"]["code"] == code
    assert act("doc-parser", "orchestrator", "release").status_code == 403
    assert act("orchestrator", "orchestrator", "release").status_code == 200
    assert swap.calls == ["activate:verifier", "activate:verifier", "release"]
    refused = [r["detail"] for r in _records(tmp_path) if r["event"] == "llm.gateway.swap_refused"]
    assert len(refused) == 4 and refused[0] == {"caller": "orchestrator", "service": "doc-parser",
                                                "reason": "caller_unverified"}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the map itself
def test_the_shipped_map_covers_every_service_that_may_call_the_gateway() -> None:
    p = RoutingPolicy.load()
    may_call = set(service_auth.CALLERS["gateway"]) | {service_auth.OPERATOR}
    assert set(p.service_callers) == may_call
    assert p.service_callers["doc-parser"] == ("doc-parser",)
    assert p.serving_control == {"orchestrator", "operator"}
    for svc, names in p.service_callers.items():  # nobody but the operator may claim the test bench or eval
        if svc != service_auth.OPERATOR:
            assert not {"testbench", "eval", "*"} & set(names), svc


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"service_callers": {"doc-parser": ["*"]}}, "only operator"),
        ({"service_callers": {"doc-parser": ["nobody"]}}, "unknown callers"),
        ({"serving_control": ["doc-parser"], "service_callers": {"orchestrator": ["orchestrator"]}}, "serving_control"),
    ],
)
def test_the_map_cannot_be_widened_by_mistake(change: dict[str, Any], match: str) -> None:
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match=match):
        RoutingPolicy({**doc, **change})


def test_a_policy_without_the_map_refuses_every_verified_service(tmp_path: Path, tokens: dict[str, str]) -> None:
    doc = yaml.safe_load((ROOT / "models" / "routing.yaml").read_text(encoding="utf-8"))
    doc.pop("service_callers")
    doc.pop("serving_control")
    gw = _gw(tmp_path)
    gw.policy = RoutingPolicy(doc)
    r = _post(TestClient(create_app(gw)), tokens["orchestrator"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "caller_unverified"


# ------------------------------------------------------------------------------------------------ the model key
def _box(tmp_path: Path, env_lines: str) -> Path:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / "docker-compose.yml").write_text("services:\n  llm-service:\n    image: x\n", encoding="utf-8")
    (deploy / "docker-compose.gb10.yml").write_text("services:\n  llm-verifier:\n    image: x\n", encoding="utf-8")
    (deploy / ".env").write_text(env_lines, encoding="utf-8")
    return deploy


def test_init_moves_the_model_key_into_its_file(tmp_path: Path) -> None:
    old = "k" * 48
    deploy = _box(tmp_path, f"COMPOSE_PROFILES=gpu\nTB_LLM_API_KEY={old}\n")
    res = sx.init(deploy, uid=None)
    key_file = sx.model_key_path(deploy)
    assert sx.MODEL in res.created and key_file.read_text(encoding="utf-8").strip() == old  # the servers keep working
    assert key_file.stat().st_mode & 0o777 == 0o600 and key_file.parent.stat().st_mode & 0o777 == 0o700
    assert sx.MODEL not in sx.init(deploy, uid=None).created  # re-run: kept
    row = next(r for r in sx.status(deploy) if r["name"] == "model key")
    assert row["present"] and row["mode"] == "0o600" and old not in json.dumps(sx.status(deploy))


def test_rotate_old_key_refused_new_key_works(tmp_path: Path) -> None:
    deploy = _box(
        tmp_path,
        "COMPOSE_PROFILES=gpu\nCOMPOSE_FILE=docker-compose.yml:docker-compose.gb10.yml\nTB_LLM_API_KEY=\n",
    )
    sx.init(deploy, uid=None)
    key_file = sx.model_key_path(deploy)
    old = key_file.read_text(encoding="utf-8").strip()
    env = {"TB_LLM_API_KEY_FILE": str(key_file), "TB_GUARD_ROUTES": "llm-service=llm-service-vllm:8000"}
    assert guard_build(env).authorised(f"Bearer {old}")
    ran: list[list[str]] = []

    def runner(argv: Sequence[str], stdin: str | None) -> None:
        ran.append(list(argv))

    res = sx.rotate(deploy, ["model"], runner=runner, uid=None)
    new = key_file.read_text(encoding="utf-8").strip()
    assert new and new != old
    # one command recreates every holder of the key: the two vLLM servers, model-guard, the gateway
    assert res.restarted == ["llm-service", "llm-verifier", "model-guard", "gateway"]
    assert len(ran) == 1 and ran[0][-4:] == ["llm-service", "llm-verifier", "model-guard", "gateway"]
    assert "--force-recreate" in ran[0]
    assert sx._read_env(deploy / ".env")["TB_LLM_API_KEY"] == new  # the vLLM servers' copy follows
    guard = guard_build(env)  # the recreated guard
    assert not guard.authorised(f"Bearer {old}") and guard.authorised(f"Bearer {new}")
    # the recreated gateway sends the new key (the file before the variable)
    assert endpoint_key("TB_LLM_API_KEY", {**env, "TB_LLM_API_KEY": old}) == new
    # no token was rotated, and nothing printed a key
    assert res.rotated == ["model"]


def test_a_stub_box_rotates_the_key_and_restarts_the_gateway_only(tmp_path: Path) -> None:
    deploy = _box(tmp_path, "COMPOSE_PROFILES=stub\n")
    ran: list[list[str]] = []
    res = sx.rotate(deploy, ["model"], runner=lambda argv, stdin: ran.append(list(argv)), uid=None)
    assert res.restarted == ["gateway"] and ran[0][-1] == "gateway"
    with pytest.raises(sx.SecretsError, match="unknown service"):
        sx.rotate(deploy, ["models"], runner=lambda argv, stdin: None, uid=None)


def test_the_gateway_reads_the_key_file_before_the_variable(tmp_path: Path) -> None:
    key = tmp_path / "llm.key"
    key.write_text("file-key-0123456789\n", encoding="utf-8")
    env = {"TB_LLM_API_KEY_FILE": str(key), "TB_LLM_API_KEY": "env-key"}
    ep = next(e for e in RoutingPolicy.load().endpoints.values() if e.api_key_env == "TB_LLM_API_KEY")
    assert endpoint_key(ep.api_key_env, env) == "file-key-0123456789"
    assert endpoint_key(ep.api_key_env, {"TB_LLM_API_KEY_FILE": str(tmp_path / "gone"), "TB_LLM_API_KEY": "e"}) == "e"
    assert endpoint_key("", env) == ""
