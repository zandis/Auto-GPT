"""The stub serves a list of model names and refuses the rest, as vLLM does (D-276; review S-3, P-34).

It used to answer under whatever ``model`` it was asked for and list only ``trialbox-stub``: a mistyped or unserved
name passed every test (the first complete run failed on exactly that, 404 from vLLM), and "two models" could be one
name asked twice. Its judge also gave one fixed, confident, well-quoted answer, so no rule about a contested answer
could be reached; the personas give those answers by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from llm_stub.app import DEFAULT_MODELS, served_models
from llm_stub.app import app as stub
from llm_stub.handlers import PERSONAS
from tb_common.llm import LlmClient, LlmError

from tools import pin_model

ROOT = Path(__file__).resolve().parents[2]
VARS: dict[str, Any] = {
    "criterion_text": "Good response to treatment",
    "note_question": "Is a good treatment response documented?",
    "index_date": "2026-10-05",
    "excerpts": [{"date": "2026-09-20", "note_type": "progress", "text": "治療反應不佳。"}],
}


@pytest.fixture(autouse=True)
def _default_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_STUB_MODELS", raising=False)


def _client(model: str) -> LlmClient:
    c = LlmClient("http://stub/v1", model)
    c.http = TestClient(stub)
    return c


def _judge(model: str) -> dict[str, Any]:
    res = _client(model).chat_json("judge", VARS)
    assert res.model == model  # answered under the served name it was asked for
    return res.data


def test_an_unserved_model_name_is_refused_with_404_like_vllm() -> None:
    http = TestClient(stub)
    body = {"model": "trialbox-stbu", "messages": [{"role": "user", "content": "hi"}]}
    r = http.post("/v1/chat/completions", json=body, headers={"X-TB-Prompt-Id": "judge"})
    assert r.status_code == 404
    assert r.json() == {
        "object": "error",
        "message": "The model `trialbox-stbu` does not exist.",
        "type": "NotFoundError",
        "param": None,
        "code": 404,
    }
    with pytest.raises(LlmError, match="404"):
        _client("stub-typo").chat_json("judge", VARS)


def test_models_lists_what_is_served_and_the_served_names_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    http = TestClient(stub)
    listed = [m["id"] for m in http.get("/v1/models").json()["data"]]
    assert listed == served_models() == [*DEFAULT_MODELS, *PERSONAS]
    for name in DEFAULT_MODELS:
        assert _judge(name)["verdict"] == "fail"
    monkeypatch.setenv("TB_STUB_MODELS", "site-judge, site-verifier")
    assert [m["id"] for m in http.get("/v1/models").json()["data"]][:2] == ["site-judge", "site-verifier"]
    assert _judge("site-judge")["verdict"] == "fail"
    with pytest.raises(LlmError, match="404"):
        _client("stub").chat_json("judge", VARS)  # no longer served


def test_the_default_names_cover_every_name_the_repository_asks_the_stub_for() -> None:
    """The registry's stub builds, the in-process judge and verifier, and the pair's served names (the cloud
    rehearsal's stand-in forwards them to the stub unchanged)."""
    reg = yaml.safe_load((ROOT / "models" / "registry.yaml").read_text(encoding="utf-8"))
    stub_served = {b["served"]["stub"] for b in reg["builds"] if b.get("serving") == "stub"}
    assert stub_served == {"trialbox-stub", "stub-verifier"} and stub_served <= set(DEFAULT_MODELS)
    assert {pin_model.JUDGE_SERVED, pin_model.VERIFIER_SERVED, "stub"} <= set(DEFAULT_MODELS)
    assert not set(PERSONAS) & set(DEFAULT_MODELS)
    # the stub box names the second stub build as its verifier, not the judge's build again (S-2)
    for script in ("poc.sh", "poc.ps1"):
        text = (ROOT / "deploy" / script).read_text(encoding="utf-8")
        assert "stub-verifier" in text and "TB_GATEWAY_VERIFIER_MODEL=trialbox-stub" not in text, script


def test_the_personas_give_the_contested_answers() -> None:
    plain = _judge("stub")
    assert plain["verdict"] == "fail" and plain["confidence"] == 0.9 and plain["quote"] == "治療反應不佳。"
    assert _judge("stub-verifier") == plain  # a second served name, the same honest answer
    assert _judge("stub-dissent")["verdict"] == "pass" and _judge("stub-dissent")["quote"] == plain["quote"]
    assert _judge("stub-lowconf") == {**plain, "confidence": 0.4}
    assert _judge("stub-badquote")["quote"] not in json.dumps(VARS, ensure_ascii=False)
    assert _judge("stub-olddate") == {**plain, "quote_date": "2026-09-19"}
    with pytest.raises(LlmError, match="503"):
        _client("stub-down").chat_json("judge", VARS)
    # a persona changes the judge's answer only; an undecided answer stays undecided
    silent = {**VARS, "excerpts": [{"date": "2026-09-20", "note_type": "progress", "text": "血壓穩定。"}]}
    for name in ("stub-dissent", "stub-badquote", "stub-olddate"):
        d = _client(name).chat_json("judge", silent).data
        assert d["verdict"] == "unknown" and d.get("quote") is None
