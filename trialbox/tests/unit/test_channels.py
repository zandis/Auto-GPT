"""Conversation grammar and the native engine (spec v4 §3.4; S1-10; D-121).

Grammar lines run deterministically without a model (FR-CONV-1). Free text goes through ``classify_intent`` on the
real ``tb-gateway`` (TEST environment, D0, route ``dev-stub``) with a deterministic stub upstream. The Hermes agent,
the front-door MCP server and the channel relay were removed in D-121; their tests went with them.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from channels.config import ChannelsConfig, ChannelsConfigError
from channels.grammar import GrammarError, parse_line
from channels.native.engine import NativeEngine, detect_language
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.core import Gateway, GatewayConfig
from gateway.policy import RoutingPolicy
from guard.guard import Guard
from registry.registry import Registry
from tb_common.audit import AuditLog
from tb_common.policy.classes import Environment, Topology
from tb_llm import GatewayClient


def classify_stub(inp: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for the classify_intent model (keyword rules over the tokenised text)."""
    text: str = inp["text"]
    lang = inp["language"]
    study = next(iter(re.findall(r"\b[A-Z]{4}\b", text)), None)
    if re.search(r"做得起來|feasib|how many|何例", text, re.I):
        out: dict[str, Any] = {"type": "FEAS", "study": study, "language": lang}
        if "三年" in text or "3 years" in text:
            out["lookback_months"] = 36
        return out
    return {"type": "UNKNOWN", "language": lang}


class Upstream:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    def client(self) -> httpx.Client:
        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            assert req.headers.get("x-tb-prompt-id") == "classify_intent"
            user = next(m["content"] for m in body["messages"] if m["role"] == "user")
            inp = json.loads(user.split("```json", 1)[1].split("```", 1)[0])
            self.inputs.append(inp)
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"role": "assistant", "content": json.dumps(classify_stub(inp))}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.req("S1-10", "FR-CONV-8")
def test_native_engine_classifies_free_text_through_the_gateway(tmp_path: Path) -> None:
    upstream = Upstream()
    gw = Gateway(
        RoutingPolicy.load(),
        Registry.load(),
        AuditLog(tmp_path / "gw_audit"),
        GatewayConfig(topology=Topology.A, environment=Environment.TEST),
        http=upstream.client(),
        guard=Guard("^\\d{8}$"),
        env={},
    )
    gwc = GatewayClient("http://testserver/v1", "converse-native", http=TestClient(create_app(gw)))
    engine = NativeEngine(gwc, today=lambda: date(2026, 10, 19))
    text = "GZQO 這個試驗做得起來嗎？過去三年"
    intent = engine.classify(text, (), detect_language(text), "D0")
    assert intent.type == "FEAS" and intent.study == "GZQO" and intent.lookback_months == 36
    assert upstream.inputs and upstream.inputs[0]["language"] == "zh-TW"


# ------------------------------------------------------------------------------------------------ grammar
@pytest.mark.req("FR-UX-10", "S1-10")
@pytest.mark.parametrize(
    ("text", "cmd", "study"),
    [
        ("FEAS NEW scope=hospital lookback=24m deadline=2026-10-23", "FEAS", "NEW"),
        ("Re: FEAS GZQO lookback=36", "FEAS", "GZQO"),
        ("FEAS GZQO pid=P0001", "FEAS", "GZQO"),  # v1 subject grammar fallback
        ('ASK GZQO "prednisone 10 mg"', "ASK", "GZQO"),
        ("SCREEN GZQO scope=practitioners:P12345,P23456 cadence=weekly", "SCREEN", "GZQO"),
        ("STUDY GZQO recruiting", "STUDY", "GZQO"),
        ("CONFIRM P0156 P0203", "CONFIRM", None),
        ("REJECT P0177 R03", "REJECT", None),
        ("DEFER P0190 2026-11-17", "DEFER", None),
        ("STATE P0156 consented 2026-10-17", "STATE", None),
        ("ANSWERS 1Y 2N 3?", "ANSWERS", None),
        ("DIGEST weekly", "DIGEST", None),
        ("ok", "OK", None),
        ("STATUS", "STATUS", None),
        ("HELP", "HELP", None),
    ],
)
def test_grammar_lines_parse(text: str, cmd: str, study: str | None) -> None:
    line = parse_line(text)
    assert line is not None and line.command == cmd and line.study == study


@pytest.mark.req("FR-UX-10")
def test_grammar_rejects_malformed_lines_and_leaves_free_text_alone() -> None:
    for bad in (
        "FEAS",
        "REJECT P0177 R09",
        "STATE P0156 married",
        "DIGEST hourly",
        "ASK GZQO no quotes",
        "FEAS NEW deadline=Friday",
    ):
        with pytest.raises(GrammarError):
            parse_line(bad)
    for free in (
        "這個試驗做得起來嗎",
        "status of GZQO?",
        "ok thanks",
        "",
        "Feas for GZQO please",
        "FEAS for GZQO or RA-BIO?",  # stress test #20: a sentence that starts with a command word
        "STATUS of my requests?",
    ):
        assert parse_line(free) is None
    assert parse_line("APPROVE GZQO version=1.0.0") is not None and parse_line("APPROVE G-1 sha=ab").approval  # type: ignore[union-attr]


def test_language_detection() -> None:
    assert detect_language("這個試驗做得起來嗎") == "zh-TW"
    assert detect_language("この試験、当院で何例くらい見込めますか？") == "ja"
    assert detect_language("How many patients?") == "en"
    assert detect_language("病人 s/p PCI，denied chest pain，Lab: normal") == "mixed"


@pytest.mark.req("S1-10")
def test_channels_config_fails_closed() -> None:
    assert ChannelsConfig.from_settings({}).engine == "native"  # the only engine (D-121)
    for bad in (
        {"engine": "slack"},
        {"engine": "hermes"},
        {"fallback": "hermes"},
        {"teams": {"mode": "fake"}},
        {"colour": 1},
    ):
        with pytest.raises(ChannelsConfigError):
            ChannelsConfig.from_settings({"channels": bad})
