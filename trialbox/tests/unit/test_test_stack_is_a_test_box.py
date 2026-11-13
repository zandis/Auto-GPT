"""The nightly of 2026-11-13: every compose test that needs data failed at its set-up with
``503 Service Unavailable`` from ``POST http://127.0.0.1:8016/run``. The adapter of the synthetic test stack had no
``TB_ENV``, which is PRODUCTION, and ``.env.example`` gives the placeholder service token, which counts as none: a
PRODUCTION service with no token refuses every changing call (``tb_common.service_auth.authorize``), and that is
right. The stack is synthetic and says so (D-560, D-640): every service that the harness or a TEST service of the
stack calls is TEST too."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tb_common import service_auth
from tb_common.config import environment_name

from tools import network_sheet

ROOT = Path(__file__).resolve().parents[2]
FILES = ["deploy/docker-compose.yml", "deploy/docker-compose.test.yml"]  # Makefile COMPOSE_TEST
HARNESS_CALLS = {"adapter", "lake"}  # tests/stack.py: POST adapter /run; the lake protects its reads too

pytestmark = pytest.mark.nodb


def _stack() -> dict[str, dict[str, str]]:
    """Each TrialBox service of the test stack with the environment its container gets: ``deploy/.env`` (the
    example, as ``make deploy/.env`` copies it) under the compose files' own values."""
    dotenv = network_sheet.read_env(ROOT / ".env.example")
    out: dict[str, dict[str, str]] = {}
    services: dict[str, Any] = network_sheet.load(FILES)["services"]
    for svc in services.values():
        env = svc.get("environment") or {}
        if isinstance(env, dict) and env.get("TB_SERVICE_NAME"):
            own = {k: network_sheet.interpolate(str(v), dotenv) for k, v in env.items() if v is not None}
            out[str(env["TB_SERVICE_NAME"])] = {**dotenv, **own}
    return out


def _refusal(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in ("TB_SERVICE_TOKEN", "TB_SERVICE_TOKEN_FILE", service_auth.REGISTRY_ENV):
        monkeypatch.delenv(name, raising=False)
        if env.get(name):
            monkeypatch.setenv(name, env[name])
    return service_auth.authorize("POST", None, environment_name(env), protect_reads=True)[0]


def test_the_example_token_is_a_placeholder_and_a_production_service_refuses_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule the stack met, kept: nothing here loosens it."""
    env = {**network_sheet.read_env(ROOT / ".env.example"), "TB_ENV": "PRODUCTION"}
    refused = _refusal(env, monkeypatch)
    assert refused is not None and refused[0] == 503 and "TB_SERVICE_TOKEN" in refused[1]


def test_every_service_the_harness_or_a_test_service_calls_takes_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    stack = _stack()
    test_services = {name for name, env in stack.items() if environment_name(env) == "TEST"}
    assert {"orchestrator", "criteria-compiler", "mail-gateway"} <= test_services  # D-640, D-369
    called = set(HARNESS_CALLS)
    for callee, callers in service_auth.CALLERS.items():
        if callee in stack and callers & test_services:
            called.add(callee)
    refused = {name: _refusal(stack[name], monkeypatch) for name in sorted(called)}
    assert {n: r for n, r in refused.items() if r is not None} == {}
    assert {"adapter", "lake", "doc-parser"} <= called  # the three that were PRODUCTION on 2026-11-13
