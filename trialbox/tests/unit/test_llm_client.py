from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from tb_common.audit import AuditLog, verify
from tb_common.llm import LlmClient, LlmSchemaError, load_prompt
from tb_common.phi_guard import scan


def _client(tmp_path: Path, **kw: Any) -> LlmClient:
    c = LlmClient("http://stub/v1", "stub", audit=AuditLog(tmp_path), **kw)
    c.http = TestClient(stub)
    return c


def test_prompts_have_front_matter() -> None:
    for pid in ("ir_extract", "concept_map", "ie_locate", "judge", "draft_doc"):
        p = load_prompt(pid)
        assert p.meta.output_schema and p.system and p.user
    assert load_prompt("judge").meta.phi is True and load_prompt("judge").meta.model_class == "local"


def test_judge_through_stub_and_audit(tmp_path: Path) -> None:
    c = _client(tmp_path)
    r = c.chat_json(
        "judge",
        {
            "criterion_text": "x",
            "note_question": "Is the patient currently (ongoing) having a gout flare?",
            "index_date": "2026-10-05",
            "excerpts": [
                {
                    "date": "2026-10-01",
                    "note_type": "progress",
                    "text": "目前右側第一蹠趾關節急性紅腫熱痛，診斷為急性痛風發作中。",
                }
            ],
        },
    )
    assert r.data["verdict"] == "pass" and r.target == "local"
    assert verify(tmp_path).ok
    line = json.loads(next(tmp_path.glob("*.jsonl")).read_text().splitlines()[0])
    assert line["event"] == "llm.call" and line["prompt_version"] == "judge_v3"


def test_cloud_routing_requires_service_flag_and_clearance(tmp_path: Path) -> None:
    c = _client(tmp_path, cloud_base_url="http://cloud/v1", cloud_enabled=True, service_name="criteria-compiler")
    meta = load_prompt("ir_extract").meta
    text = "criteria text"
    assert c._target(meta, text, None) == "local"
    clear = scan(text).clearance
    assert c._target(meta, text, clear) == "cloud"
    assert c._target(meta, text + "!", clear) == "local"  # clearance bound to the exact text
    c.service_name = "orchestrator"
    assert c._target(meta, text, clear) == "local"
    assert c._target(load_prompt("judge").meta, text, clear) == "local"  # PHI prompts never go to cloud


class _Flaky(httpx.MockTransport):
    pass


def test_schema_violation_retry_then_error(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        bad = len(calls) == 1
        content = json.dumps({"verdict": "maybe"} if bad else {"verdict": "unknown", "confidence": 0.5})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    c = LlmClient("http://x/v1", "m", audit=AuditLog(tmp_path))
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    r = c.chat_json("judge", {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []})
    assert r.attempts == 2 and r.data["verdict"] == "unknown"

    def always_bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    c.http = httpx.Client(transport=httpx.MockTransport(always_bad))
    with pytest.raises(LlmSchemaError):
        c.chat_json("judge", {"criterion_text": "x", "note_question": "q", "index_date": "2026-01-01", "excerpts": []})
